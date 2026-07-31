"""오케스트레이터 배선 계약 — apps/aisearch 8개 모듈이 하나의 실행 경로로 묶임을 증명.

V1 적대검증 BLOCKER("고아 모듈/배선 부재") 해소 계약:
  run_search_pipeline(jd, deps) 단일 진입점이
  AC1 boolean_builder → AC2 portal_search → AC8 banner → AC3 pagination_store
  → AC7 intervention → AC4 score_gate(register_if_eligible 경유만)
  → AC5 recorders(DualRecorder, 기본 dry-run) → AC9 draft_builder
  를 실제로 호출한다. 전부 페이크 드라이버/저장소/클라이언트 — 네트워크/브라우저 0.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from tools.multi_position_sourcing.matching_score_contract import CONTRACT_VERSION

from apps.aisearch.core import (
    banner,
    boolean_builder,
    draft_builder,
    orchestrator,
    pagination_store,
    portal_search,
    score_gate,
)
from apps.aisearch.core.boolean_builder import (
    STAGE_EXPANDED,
    STAGE_SEOUL_UNIVERSITY_PRIORITY,
)
from apps.aisearch.core.intervention import InterventionMonitor, feed_driver_events
from apps.aisearch.core.orchestrator import (
    LINKEDIN_CHANNEL,
    STATUS_ABORTED,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_PARTIAL,
    STATUS_WAITING_RESUME,
    PipelineDeps,
    run_search_pipeline,
)
from apps.aisearch.core.pagination_store import (
    NEXT_SWITCH_BOOLEAN_VARIANT,
    TABLE_NAME,
)
from apps.aisearch.core.recorders import DualRecorder


# ── 픽스처: AC4 계약 통과 payload (test_aisearch_ac4_score_gate.py 와 동일 구조) ──


def _score_payload(scores: dict[str, object] | None = None) -> dict[str, object]:
    dimensions: dict[str, dict[str, object]] = {}
    for index in range(1, 9):
        dimension_id = f"D{index}"
        entry: dict[str, object] = {
            "score": (scores or {}).get(dimension_id, 3),
            "evidence": f"{dimension_id} evidence",
        }
        if dimension_id == "D7":
            entry["needs_verification"] = []
        if dimension_id == "D8":
            entry["school_sensitive_client"] = False
        dimensions[dimension_id] = entry
    return {
        "contract_version": CONTRACT_VERSION,
        "gates": [{"requirement": "req-1", "verdict": "pass", "evidence": "met"}],
        "dimensions": dimensions,
        "total_years": 5,
    }


PAYLOAD_60 = _score_payload()  # 전 항목 3점 → 정확히 60점 (게이트 통과)
PAYLOAD_59 = _score_payload({"D5": 2})  # 59점 (게이트 차단)


# ── 픽스처: AC9 유효 초안 입력 (test_aisearch_ac9_draft.py 픽스처 재사용) ──

FULL_BRIEFING = {
    "one_line": "글로벌 1,000곳+에 시제품·목업·QDM 공급하는 제품개발 파트너",
    "history": "1993년 설립",
    "funding_stage": "2022년 코스닥 상장(종목 417970)",
    "revenue": "2024년 매출 약 680억, 영업이익 전년비 +92%",
    "headcount": "약 330명",
    "parent_group": "한국타이어 그룹 계열(지분 62.92%)",
    "ceo_quote": '대표 공개 발언: "로봇 액추에이터로 확장" (2026 기사)',
    "recent_news": "K-휴머노이드 연합 참여, 로봇 액추에이터 신사업",
}


def _valid_draft_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(
        candidate_name="김민수",
        candidate_company="현대로템",
        candidate_headline="기구설계 파트리더",
        company_name="한국프리시전웍스",
        position_title="Tech PM",
        briefing_elements=FULL_BRIEFING,
        jd_summary=(
            "시제품 개발 프로젝트 총괄, 글로벌 고객 커뮤니케이션, "
            "설계-생산-품질 부서 간 일정 조율과 리스크 관리를 담당합니다."
        ),
        channel="linkedin_rps",
    )
    try:
        draft_builder.build_candidate_draft(**kwargs)
    except draft_builder.DraftDensityError as e:
        kwargs["jd_summary"] = kwargs["jd_summary"] + "다" * (e.minimum - e.char_count)
        draft_builder.build_candidate_draft(**kwargs)  # 보정 후 유효성 확인
    return kwargs


DRAFT_KWARGS = _valid_draft_kwargs()


def _candidate(payload: dict[str, object], url: str) -> dict[str, Any]:
    return {
        "score_payload": payload,
        "record": {
            "profile_url": url,
            "why_fit": "필수요건 전부 충족",
            "profile_summary": "기구설계 10년, PM 전환 3년",
            "match_basis": "D1~D8 근거",
            "education": "서울 소재 4년제",
            "career_brief": "현대로템 파트리더",
        },
        "draft_inputs": dict(DRAFT_KWARGS),
    }


# ── 페이크 (네트워크/브라우저/실 sleep 0) ──


class FakeDriver:
    def __init__(self, events: list, fail: bool = False, release_fail: bool = False):
        self.events = events
        self.fail = fail
        self.release_fail = release_fail  # 배너 해제(OFF) 스니펫만 실패시킨다
        self.snippets: list[str] = []

    def run_js(self, snippet: str) -> None:
        if self.fail:
            raise RuntimeError("driver down")
        if self.release_fail and '"active": false' in snippet:
            raise RuntimeError("banner release failed")
        self.snippets.append(snippet)
        # 3차 결함 ⑩ — 채널별 스레드 동시 실행이므로 이벤트에 스레드 id 를
        # 마지막 원소로 남겨, 채널(스레드) 단위 순서 검증을 가능하게 한다.
        self.events.append(("js", snippet, threading.get_ident()))


class FakeStore:
    def __init__(self, events: list, fail: bool = False):
        self.events = events
        self.fail = fail
        self.rows: list[tuple[str, dict]] = []

    def upsert(self, table: str, row: dict) -> None:
        if self.fail:
            raise RuntimeError("store down")
        self.rows.append((table, row))
        self.events.append(("upsert", table, row["page_type"], threading.get_ident()))


class FakeClickUp:
    def __init__(self):
        self.dedup_calls: list[str] = []
        self.writes: list[str] = []

    def find_parent_task(self, list_id: str, position_name: str):
        return "parent-1"

    def subtask_exists_with_profile_url(self, list_id: str, profile_url: str) -> bool:
        self.dedup_calls.append(profile_url)
        return False

    def create_parent_task(self, list_id: str, position_name: str) -> str:
        self.writes.append("parent")
        return "parent-live"

    def create_candidate_subtask(self, list_id, parent_task_id, fields) -> str:
        self.writes.append("subtask")
        return "subtask-live"


class FakeDiscord:
    def __init__(self):
        self.posts: list[tuple[str, str]] = []

    def post_message(self, channel_id: str, content: str) -> str:
        self.posts.append((channel_id, content))
        return "msg-1"


class FakeAdmin:
    """AC-6 — admin.valuehire.cc 등록 페이크(실제 HTTP 없음)."""

    def __init__(self):
        self.registered: list[dict] = []

    def register_candidate(self, payload: dict) -> dict:
        self.registered.append(dict(payload))
        return {"ok": True, "candidate": {"id": f"admin-{len(self.registered)}"}, "deduped": False}


class FakeNotifier:
    def __init__(self):
        self.messages: list[str] = []

    def notify(self, message: str) -> None:
        self.messages.append(message)


class SpyMonitor(InterventionMonitor):
    def __init__(self, clock, notifier):
        super().__init__(clock, notifier)
        self.polls = 0

    def poll(self):
        self.polls += 1
        return super().poll()


class Harness:
    """페이크 일습 + 이벤트 로그. list_pages_per_channel 로 소진 시점 제어."""

    def __init__(
        self,
        pages: int = 2,
        driver_fail: bool = False,
        store_fail: bool = False,
        release_fail: bool = False,
        live_recorder: bool = False,
        discord=None,
        linkedin_session_lock=None,
    ):
        self.linkedin_session_lock = linkedin_session_lock
        self.events: list = []
        self.pages = pages
        self.driver = FakeDriver(self.events, fail=driver_fail, release_fail=release_fail)
        self.store = FakeStore(self.events, fail=store_fail)
        self.clickup = FakeClickUp()
        self.discord = discord if discord is not None else FakeDiscord()
        self.admin = FakeAdmin()
        self.notifier = FakeNotifier()
        self.now = [1000.0]
        self.monitor = SpyMonitor(lambda: self.now[0], self.notifier)
        if live_recorder:
            self.recorder = DualRecorder(
                self.clickup, self.discord, self.admin, live=True, owner_signoff=True
            )
        else:
            self.recorder = DualRecorder(self.clickup, self.discord, self.admin)  # 기본 dry-run
        self.list_calls: list[tuple[str, int]] = []
        self.search_payloads: list[tuple[str, int, dict]] = []
        self.candidates: dict[str, list[dict]] = {}
        self.list_side_effect = None  # (channel, page) 마다 호출되는 훅
        self.driver_events: list[dict] = []  # poll_driver_events 로 드레인되는 큐

    def poll_driver_events(self) -> list[dict]:
        drained, self.driver_events = self.driver_events, []
        return drained

    def fetch_list_page(self, channel: str, page: int, search: dict) -> dict:
        self.list_calls.append((channel, page))
        self.events.append(("list", channel, page, threading.get_ident()))
        self.search_payloads.append((channel, page, search))
        if self.list_side_effect is not None:
            self.list_side_effect(channel, page)
        return {
            "url": f"https://example.test/{channel}?p={page}",
            "content": f"<html>{channel}-{page}</html>",
            "detail_refs": [f"{channel}-detail-{page}"],
            "has_next": page < self.pages,
        }

    def fetch_detail_page(self, channel: str, ref: str) -> dict:
        self.events.append(("detail", channel, ref, threading.get_ident()))
        if getattr(self, "detail_side_effect", None) is not None:
            self.detail_side_effect(channel, ref)
        return {"url": f"https://example.test/{channel}/{ref}", "content": "<html>detail</html>"}

    def extract_candidates(self, channel: str) -> list[dict]:
        return list(self.candidates.get(channel, []))

    def deps(self) -> PipelineDeps:
        return PipelineDeps(
            driver=self.driver,
            store=self.store,
            monitor=self.monitor,
            recorder=self.recorder,
            fetch_list_page=self.fetch_list_page,
            fetch_detail_page=self.fetch_detail_page,
            extract_candidates=self.extract_candidates,
            machine="macmini",
            poll_driver_events=self.poll_driver_events,
            linkedin_session_lock=self.linkedin_session_lock,
        )


def _jd() -> dict[str, Any]:
    return {
        "position_name": "Tech PM",
        "keyword_groups": [["백엔드", "Backend"], ["PM"]],
        "requirements": {"min_years": 3},
        "or_keywords": ["백엔드", "Backend"],
        "and_keywords": ["Python"],
        "career_min": 3,
        "career_max": 10,
    }


# ── 배선 경로 증명: 모듈 함수 동일성 (복제 금지) ──


class TestWiringIdentity:
    def test_orchestrator_reuses_module_functions_not_copies(self):
        assert orchestrator.build_search_plan is boolean_builder.build_search_plan
        assert (
            orchestrator.build_portal_search_descriptors
            is portal_search.build_portal_search_descriptors
        )
        assert orchestrator.paginate_and_store is pagination_store.paginate_and_store
        assert orchestrator.register_if_eligible is score_gate.register_if_eligible
        assert orchestrator.build_dispatch_snippet is banner.build_dispatch_snippet
        assert orchestrator.build_candidate_draft is draft_builder.build_candidate_draft


# ── 해피패스: 전 모듈 호출 순서·횟수 ──


class TestHappyPath:
    def _run(self) -> tuple[Harness, Any]:
        h = Harness(pages=2)
        h.candidates["saramin"] = [
            _candidate(PAYLOAD_60, "https://saramin.example/p/60"),
            _candidate(PAYLOAD_59, "https://saramin.example/p/59"),
        ]
        report = run_search_pipeline(_jd(), h.deps())
        return h, report

    def test_completed_with_four_variants_all_channels(self):
        # V1 2차 결함 5 → 3차 결함 ⑩: 채널별 파이프라인은 스레드로 "실제 동시"
        # 실행되므로 채널 간 변형 순서는 비결정적이다 — 채널별 순서와 변형
        # 집합으로 검증한다(동시성 자체는 test_aisearch_v3_still_broken.py 의
        # threading.Event 기반 테스트가 결정론적으로 증명).
        h, report = self._run()
        assert report.status == STATUS_COMPLETED
        lk_tasks = [v.task for v in report.variants if v.channel == LINKEDIN_CHANNEL]
        # LinkedIn 채널 내부 순서(서울 우선 → 확장)는 유지된다
        assert lk_tasks == [
            f"{LINKEDIN_CHANNEL}:{STAGE_SEOUL_UNIVERSITY_PRIORITY}",
            f"{LINKEDIN_CHANNEL}:{STAGE_EXPANDED}",
        ]
        assert len(report.variants) == 4
        # AC2 디스크립터의 dedup_key 가 task 에 실려 있어야 배선 증명이 된다
        saramin_task = next(v.task for v in report.variants if v.channel == "saramin")
        jobkorea_task = next(v.task for v in report.variants if v.channel == "jobkorea")
        assert "saramin|or=" in saramin_task
        assert "jobkorea|or=" in jobkorea_task

    def test_each_channel_runs_on_its_own_thread(self):
        # 3차 결함 ⑩ — 채널당 스레드 1개: 채널별 fetch 는 서로 다른 스레드에서,
        # 같은 채널의 fetch 는 전부 같은 스레드에서 실행된다.
        h, _ = self._run()
        threads_by_channel: dict[str, set[int]] = {}
        for e in h.events:
            if e[0] == "list":
                threads_by_channel.setdefault(e[1], set()).add(e[-1])
        assert set(threads_by_channel) == {LINKEDIN_CHANNEL, "saramin", "jobkorea"}
        for channel, tids in threads_by_channel.items():
            assert len(tids) == 1, f"{channel} 이 여러 스레드에서 실행됐다"
        # 스레드 id 의 "전부 서로 다름"은 요구하지 않는다 — 페이크는 즉시
        # 반환하므로 풀이 유휴 워커를 재사용할 수 있다(정상). 블록 시에도
        # 다른 채널이 진행된다는 실제 동시성은 threading.Event 기반 테스트
        # (test_aisearch_v3_still_broken.TestTrueConcurrency)가 결정론적으로
        # 증명한다.

    def test_banner_wraps_each_variant_and_pagination_runs_inside(self):
        h, _ = self._run()
        on = [s for s in h.driver.snippets if '"active": true' in s]
        off = [s for s in h.driver.snippets if '"active": false' in s]
        assert len(on) == 4 and len(off) == 4  # 변형마다 표시+해제 1쌍
        # 이벤트 순서: 각 변형은 배너 ON → list/detail/upsert → 배너 OFF.
        # 채널 스레드가 동시 실행되므로(결함 ⑩) 스레드(=채널)별 스트림 안에서
        # 검증한다 — 전역 인터리브는 비결정적이지만 스레드 내 순서는 결정적이다.
        by_thread: dict[int, list[tuple]] = {}
        for e in h.events:
            by_thread.setdefault(e[-1], []).append(e)
        wrapped_variants = 0
        for events in by_thread.values():
            js_idx = [i for i, e in enumerate(events) if e[0] == "js"]
            assert len(js_idx) % 2 == 0, "배너 ON/OFF 짝이 맞지 않는다"
            for k in range(0, len(js_idx), 2):
                start, end = js_idx[k], js_idx[k + 1]
                assert '"active": true' in events[start][1]
                assert '"active": false' in events[end][1]
                between = events[start + 1 : end]
                assert between, "배너 ON/OFF 사이에 순회가 있어야 한다"
                assert all(e[0] in ("list", "detail", "upsert") for e in between)
                wrapped_variants += 1
        assert wrapped_variants == 4

    def test_pagination_saves_every_page_to_contract_table(self):
        h, report = self._run()
        # 채널 4회 실행 × (list 2 + detail 2) = 16 row 전량 저장(D4)
        assert len(h.store.rows) == 16
        assert {t for t, _ in h.store.rows} == {TABLE_NAME}
        for v in report.variants:
            assert v.pagination.pages_crawled == 2
            assert v.pagination.rows_saved == 4

    def test_monitor_polled_between_every_page(self):
        h, _ = self._run()
        total_list_fetches = len(h.list_calls)
        assert total_list_fetches == 8
        assert h.monitor.polls >= total_list_fetches  # 매 페이지 전 점검(AC7)

    def test_sub60_never_reaches_registration_and_60_registers_dry_run(self):
        h, report = self._run()
        # 60점 후보만 등록 경로 진입 — 59점은 중복확인(read)조차 호출되지 않음
        assert h.clickup.dedup_calls == ["https://saramin.example/p/60"]
        assert h.clickup.writes == []  # dry-run: 외부 쓰기 0
        assert h.discord.posts == []  # dry-run: Discord 발신 0
        assert len(report.registered) == 1
        rec = report.registered[0]
        assert rec.status == "dry_run"
        kinds = [a["kind"] for a in rec.planned_actions]
        assert "clickup_create_candidate_subtask" in kinds
        assert "discord_result_post" in kinds
        assert [b["score"] for b in report.below_threshold] == [59]

    def test_draft_built_only_for_registered_candidate_and_is_draft_only(self):
        _, report = self._run()
        assert len(report.drafts) == 1
        draft = report.drafts[0]
        assert draft["is_draft_only"] is True
        assert 1800 <= draft["char_count"] <= 1899


# ── D3: 20페이지 cap — 21페이지 요청 금지 + 다음 불린 변형 시그널 ──


class TestPaginationCap:
    def test_cap_reached_no_21st_request_and_next_variant_runs(self):
        # V1 2차 결함 4 — D3: 20페이지 cap 도달은 "다음 불린 변형 전환" 시그널이다.
        # cap 이후 플랜의 다음 변형(expanded)이 실제로 실행돼야 한다.
        h = Harness(pages=999)  # has_next 항상 True
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_COMPLETED
        assert max(p for _, p in h.list_calls) == 20  # 21페이지 요청 금지 유지
        lk = [v for v in report.variants if v.channel == LINKEDIN_CHANNEL]
        assert [v.task for v in lk] == [
            f"{LINKEDIN_CHANNEL}:{STAGE_SEOUL_UNIVERSITY_PRIORITY}",
            f"{LINKEDIN_CHANNEL}:{STAGE_EXPANDED}",
        ]
        for v in lk:
            assert v.pagination.next_action == NEXT_SWITCH_BOOLEAN_VARIANT
            assert v.pagination.pages_crawled == 20


# ── AC7: BLOCKED 즉시 중단 / 사람 개입 대기 시그널 ──


class TestIntervention:
    def test_captcha_blocks_pipeline_immediately(self):
        h = Harness(pages=5)

        def side_effect(channel: str, page: int) -> None:
            if page == 1:
                h.monitor.on_signal("captcha")  # 1페이지 처리 중 캡차 감지

        h.list_side_effect = side_effect
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_BLOCKED
        # 2페이지 요청은 절대 나가지 않는다 (진행 금지). 채널 스레드 동시
        # 실행(결함 ⑩)이므로 "어느 채널이 먼저였나"는 비결정적이지만,
        # 모든 채널이 1페이지(캡차 발생 지점)를 넘지 못한 것은 결정적이다.
        assert h.list_calls, "최소 한 채널은 1페이지를 시도했다"
        assert all(page == 1 for _c, page in h.list_calls)
        assert h.notifier.messages  # Discord 알림 경로(주입 notifier) 호출됨
        assert report.registered == [] and report.drafts == []
        # 중단 시에도 배너 해제 신호는 발신됐다
        assert '"active": false' in h.driver.snippets[-1]

    def test_human_input_returns_waiting_resume_signal(self):
        h = Harness(pages=5)

        def side_effect(channel: str, page: int) -> None:
            if page == 1:
                h.monitor.on_human_input()  # 사람 마우스/키보드 개입

        h.list_side_effect = side_effect
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_WAITING_RESUME
        # 결함 ⑩ 동시 실행 — 모든 채널이 개입 발생 지점(1페이지)을 넘지 못한다
        assert h.list_calls and all(page == 1 for _c, page in h.list_calls)
        # 30초 경과 후에는 모니터가 재개 가능 상태로 돌아온다(재실행 전제)
        h.now[0] += 30.0
        assert h.monitor.poll().value == "running"


# ── E8: 표에 없는 예외 — 명시적 중단 + 상태 보고 ──


class TestExplicitAbort:
    def test_driver_exception_aborts_with_error_report(self):
        h = Harness(driver_fail=True)
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_ABORTED
        assert report.error and "driver down" in report.error
        assert h.store.rows == [] and report.registered == []

    def test_store_failure_aborts_and_still_releases_banner(self):
        h = Harness(store_fail=True)
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_ABORTED
        assert report.error and "store down" in report.error
        assert '"active": false' in h.driver.snippets[-1]

    def test_missing_position_name_fails_closed(self):
        h = Harness()
        jd = _jd()
        del jd["position_name"]
        report = run_search_pipeline(jd, h.deps())
        assert report.status == STATUS_ABORTED
        assert h.driver.snippets == []  # 아무 브라우저 조작도 시작되지 않았다


# ── 59점 단독: 등록 함수 미호출 증명 (spec 4) ──


class TestScoreGateWiring:
    def test_only_sub60_candidates_registration_never_called(self):
        h = Harness(pages=1)
        h.candidates["jobkorea"] = [_candidate(PAYLOAD_59, "https://jk.example/p/59")]
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_COMPLETED
        assert h.clickup.dedup_calls == []  # 등록 경로(중복확인 포함) 진입 0
        assert h.clickup.writes == [] and h.discord.posts == []
        assert report.registered == [] and report.drafts == []
        assert [b["score"] for b in report.below_threshold] == [59]


# ── V1 2차 결함 1: 차단 신호는 매 단계에서 확인 — 후속 호출 0 ──


class TestBlockedEveryStage:
    def test_captcha_during_page_response_stops_before_detail(self):
        """검색 도중(1페이지 응답 중) 캡차 인입 → 상세조회 0, ClickUp 0, Discord 0."""
        h = Harness(pages=3)
        h.candidates[LINKEDIN_CHANNEL] = [
            _candidate(PAYLOAD_60, "https://lk.example/p/60")
        ]

        def side_effect(channel: str, page: int) -> None:
            if page == 1:
                h.monitor.on_signal("captcha")

        h.list_side_effect = side_effect
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_BLOCKED
        assert [e for e in h.events if e[0] == "detail"] == []  # 상세조회 0
        assert h.clickup.dedup_calls == [] and h.clickup.writes == []  # ClickUp 0
        assert h.discord.posts == []  # Discord 0
        assert report.registered == [] and report.drafts == []

    def test_captcha_during_detail_stops_before_registration(self):
        """상세조회 중 캡차 인입 → 등록·기록·초안 경로 진입 0."""
        h = Harness(pages=1)
        h.candidates[LINKEDIN_CHANNEL] = [
            _candidate(PAYLOAD_60, "https://lk.example/p/60")
        ]

        def detail_side_effect(channel: str, ref: str) -> None:
            h.monitor.on_signal("captcha")

        h.detail_side_effect = detail_side_effect
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_BLOCKED
        assert h.clickup.dedup_calls == []  # 등록(중복확인 포함) 진입 0
        assert h.discord.posts == []
        assert report.registered == [] and report.drafts == []


# ── V1 2차 결함 3: 배너 해제 실패는 삼키지 않고 결과에 보고한다 ──


class TestBannerReleaseFailure:
    def test_release_failure_reported_and_not_completed(self):
        h = Harness(pages=1, release_fail=True)
        report = run_search_pipeline(_jd(), h.deps())
        # 해제 실패가 본 흐름을 죽이지는 않지만, completed 로 조용히 끝나면 안 된다
        assert report.status == STATUS_PARTIAL
        assert len(report.banner_errors) == 4  # 변형 4개 전부 해제 실패
        for err in report.banner_errors:
            assert "banner release failed" in err["error"]
            assert err["task"]

    def test_no_release_failure_no_banner_errors(self):
        h = Harness(pages=1)
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_COMPLETED
        assert report.banner_errors == []


# ── V1 2차 결함 7: partial 기록 재개 — 미완 단계만 이어서 완결 ──


class FlakyDiscord(FakeDiscord):
    """첫 post_message 만 실패 — 이후에는 정상 발신."""

    def __init__(self):
        super().__init__()
        self.fail_next = True

    def post_message(self, channel_id: str, content: str) -> str:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("discord down")
        return super().post_message(channel_id, content)


class TestPartialResume:
    def test_partial_then_rerun_completes_discord_post(self):
        url = "https://saramin.example/p/60"
        h = Harness(pages=1, live_recorder=True, discord=FlakyDiscord())
        h.candidates["saramin"] = [_candidate(PAYLOAD_60, url)]

        report1 = run_search_pipeline(_jd(), h.deps())
        assert report1.status == STATUS_PARTIAL
        state1 = report1.record_states[url]
        assert state1.status == "partial"
        assert state1.pending_steps  # 미완 단계가 결과 객체에 보존된다
        assert h.discord.posts == []  # 1차: Discord 게시 실패
        assert h.clickup.writes == ["subtask"]  # subtask 는 이미 생성됨
        assert report1.drafts == []  # 미완결 후보 초안 금지(결함 8과 동일 원칙)

        report2 = run_search_pipeline(_jd(), h.deps(), previous=report1)
        assert report2.status == STATUS_COMPLETED
        assert report2.record_states[url].status == "recorded"
        assert report2.record_states[url].pending_steps == []
        # Discord 결과 채널 게시 1건 완료 + 미완 단계만 수행(subtask 재생성 0)
        result_posts = [p for p in h.discord.posts if p[0] == "1470955309089554554"]
        assert len(result_posts) == 1
        assert h.clickup.writes == ["subtask"]
        assert len(report2.drafts) == 1  # 완결됐으므로 초안 생성


# ── V1 2차 결함 8: 기록 실패 후보 초안 금지 + 전체 completed 금지 ──


class TestRecordFailureNoDraft:
    def test_failed_record_no_draft_and_status_partial(self):
        h = Harness(pages=1)
        bad = _candidate(PAYLOAD_60, "https://saramin.example/p/60")
        bad["record"]["why_fit"] = ""  # 필수 필드 누락 → recorder 가 failed 반환
        h.candidates["saramin"] = [bad]
        report = run_search_pipeline(_jd(), h.deps())
        assert report.drafts == []  # recorded/dry_run 아니면 초안 금지
        assert report.registered == []
        assert report.status == STATUS_PARTIAL
        assert len(report.record_failures) == 1
        failure = report.record_failures[0]
        assert failure["channel"] == "saramin"
        assert failure["status"] == "failed"
        assert "why_fit" in failure["error"]


# ── V1 2차 결함 2·9: 검색 호출 payload — Boolean·대학필터·필수요건·URL·입력단계 ──


class TestSearchPayloadRichness:
    def _run(self) -> Harness:
        h = Harness(pages=1)
        jd = _jd()
        jd["not_keywords"] = ["인턴"]
        report = run_search_pipeline(jd, h.deps())
        assert report.status == STATUS_COMPLETED
        return h

    def test_linkedin_payload_has_boolean_universities_requirements(self):
        h = self._run()
        lk = [p for c, _pg, p in h.search_payloads if c == LINKEDIN_CHANNEL]
        by_stage = {p["stage"]: p for p in lk}
        first = by_stage[STAGE_SEOUL_UNIVERSITY_PRIORITY]
        assert '("백엔드" OR "Backend")' in first["keywords"]
        assert '("PM")' in first["keywords"]
        assert 'NOT ("인턴")' in first["keywords"]  # 결함 2 — 제외어 반영
        assert first["required_filters"] == {"min_years": 3}  # RPS 필수요건
        assert isinstance(first["universities"], tuple) and first["universities"]
        assert first["location"] == "South Korea"
        expanded = by_stage[STAGE_EXPANDED]
        assert expanded["universities"] is None
        assert expanded["required_filters"] == {"min_years": 3}

    def test_saramin_payload_has_url_login_and_input_steps(self):
        h = self._run()
        sp = next(p for c, _pg, p in h.search_payloads if c == "saramin")
        assert sp["url"].startswith("https://www.saramin.co.kr/")
        assert "auth" in sp["login_url"]
        fields = {s["field"]: s for s in sp["steps"]}
        assert fields["or_keywords"]["values"] == ["백엔드", "Backend"]
        assert fields["and_keywords"]["values"] == ["Python"]
        assert fields["career_min"]["values"] == ["3"]
        assert all(s["selector"] for s in sp["steps"])
        assert sp["post_filter_exclude"] == ["인턴"]  # 결함 2 — 제외어 전달

    def test_jobkorea_payload_has_url_and_combined_keyword_step(self):
        h = self._run()
        jp = next(p for c, _pg, p in h.search_payloads if c == "jobkorea")
        assert jp["url"] == "https://www.jobkorea.co.kr/Corp/Person/Find"
        fields = {s["field"]: s for s in jp["steps"]}
        assert fields["keyword"]["values"] == ["백엔드 Backend Python"]
        assert fields["keyword"]["selector"] == "#txtKeyword"
        assert jp["post_filter_exclude"] == ["인턴"]

    def test_exclusions_missing_from_payload_fails(self):
        """제외어를 전달하지 않으면(반영 누락) 실패해야 한다는 계약의 대우 증명."""
        h = Harness(pages=1)
        jd = _jd()
        jd["not_keywords"] = ["인턴", "신입"]
        run_search_pipeline(jd, h.deps())
        for c, _pg, p in h.search_payloads:
            if c == LINKEDIN_CHANNEL:
                assert 'NOT ("인턴" OR "신입")' in p["keywords"]
            else:
                assert p["post_filter_exclude"] == ["인턴", "신입"]


# ── V1 2차 결함 10: 드라이버 이벤트 → InterventionMonitor 어댑터 배선 ──


class TestDriverEventFeed:
    def test_human_input_event_pauses_before_any_fetch(self):
        h = Harness(pages=2)
        h.driver_events.append({"type": "human_input"})
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_WAITING_RESUME
        assert h.list_calls == []  # 정지 — 어떤 페이지 요청도 나가지 않는다

    def test_captcha_event_blocks_before_any_fetch(self):
        h = Harness(pages=2)
        h.driver_events.append({"type": "signal", "kind": "captcha"})
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_BLOCKED
        assert h.list_calls == []
        assert h.notifier.messages  # 차단 알림 발신됨

    def test_midstream_captcha_event_stops_next_step(self):
        h = Harness(pages=5)

        def side_effect(channel: str, page: int) -> None:
            if page == 2:
                h.driver_events.append({"type": "signal", "kind": "captcha"})

        h.list_side_effect = side_effect
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_BLOCKED
        assert h.list_calls == [(LINKEDIN_CHANNEL, 1), (LINKEDIN_CHANNEL, 2)]
        # 이벤트 인입 후에는 상세조회도 나가지 않는다 (2페이지 상세 0)
        details = [e for e in h.events if e[0] == "detail"]
        assert all("detail-2" not in e[2] for e in details)

    def test_unknown_event_type_blocks_fail_closed(self):
        notifier = FakeNotifier()
        monitor = InterventionMonitor(lambda: 0.0, notifier)
        feed_driver_events(monitor, [{"type": "weird_event"}])
        assert monitor.state.value == "blocked"  # E8 — 표에 없는 이벤트는 차단


class _SpyLock:
    """V1 독립검증 결함4 — 진입/이탈만 기록하는 페이크 세션 락."""

    def __init__(self) -> None:
        self.enters = 0
        self.exits = 0
        self.active = False

    def __enter__(self):
        self.enters += 1
        self.active = True
        return self

    def __exit__(self, *exc_info):
        self.exits += 1
        self.active = False


class TestLinkedInSessionLockWiring:
    """V1 독립검증 결함4 — 링크드인 채널만 세션 락으로 감싸야 한다."""

    def test_linkedin_channel_is_wrapped_by_injected_lock(self):
        lock = _SpyLock()
        h = Harness(pages=1, linkedin_session_lock=lock)
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_COMPLETED
        assert lock.enters == 1
        assert lock.exits == 1
        assert lock.active is False  # 종료 후 반드시 해제

    def test_none_lock_does_not_crash_no_cross_device_protection(self):
        # linkedin_session_lock 미주입 — 기기 간 배제는 없지만 파이프라인은 진행돼야 한다.
        h = Harness(pages=1, linkedin_session_lock=None)
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_COMPLETED

    def test_lock_held_by_another_owner_aborts_pipeline_not_silent(self):
        from apps.aisearch.core.session_lock import (
            LinkedInSessionLock,
            LinkedInSessionLockError,
        )

        class _AlreadyHeldLock:
            def __enter__(self):
                raise LinkedInSessionLockError("다른 기기가 이미 보유 중")

            def __exit__(self, *exc_info):
                return False

        h = Harness(pages=1, linkedin_session_lock=_AlreadyHeldLock())
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_ABORTED
        assert "다른 기기" in (report.error or "")
