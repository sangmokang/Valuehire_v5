"""오케스트레이터 배선 계약 — apps/aisearch 8개 모듈이 하나의 실행 경로로 묶임을 증명.

V1 적대검증 BLOCKER("고아 모듈/배선 부재") 해소 계약:
  run_search_pipeline(jd, deps) 단일 진입점이
  AC1 boolean_builder → AC2 portal_search → AC8 banner → AC3 pagination_store
  → AC7 intervention → AC4 score_gate(register_if_eligible 경유만)
  → AC5 recorders(DualRecorder, 기본 dry-run) → AC9 draft_builder
  를 실제로 호출한다. 전부 페이크 드라이버/저장소/클라이언트 — 네트워크/브라우저 0.
"""
from __future__ import annotations

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
from apps.aisearch.core.intervention import InterventionMonitor
from apps.aisearch.core.orchestrator import (
    LINKEDIN_CHANNEL,
    STATUS_ABORTED,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
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
    def __init__(self, events: list, fail: bool = False):
        self.events = events
        self.fail = fail
        self.snippets: list[str] = []

    def run_js(self, snippet: str) -> None:
        if self.fail:
            raise RuntimeError("driver down")
        self.snippets.append(snippet)
        self.events.append(("js", snippet))


class FakeStore:
    def __init__(self, events: list, fail: bool = False):
        self.events = events
        self.fail = fail
        self.rows: list[tuple[str, dict]] = []

    def upsert(self, table: str, row: dict) -> None:
        if self.fail:
            raise RuntimeError("store down")
        self.rows.append((table, row))
        self.events.append(("upsert", table, row["page_type"]))


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

    def __init__(self, pages: int = 2, driver_fail: bool = False, store_fail: bool = False):
        self.events: list = []
        self.pages = pages
        self.driver = FakeDriver(self.events, fail=driver_fail)
        self.store = FakeStore(self.events, fail=store_fail)
        self.clickup = FakeClickUp()
        self.discord = FakeDiscord()
        self.notifier = FakeNotifier()
        self.now = [1000.0]
        self.monitor = SpyMonitor(lambda: self.now[0], self.notifier)
        self.recorder = DualRecorder(self.clickup, self.discord)  # 기본 dry-run
        self.list_calls: list[tuple[str, int]] = []
        self.candidates: dict[str, list[dict]] = {}
        self.list_side_effect = None  # (channel, page) 마다 호출되는 훅

    def fetch_list_page(self, channel: str, page: int) -> dict:
        self.list_calls.append((channel, page))
        self.events.append(("list", channel, page))
        if self.list_side_effect is not None:
            self.list_side_effect(channel, page)
        return {
            "url": f"https://example.test/{channel}?p={page}",
            "content": f"<html>{channel}-{page}</html>",
            "detail_refs": [f"{channel}-detail-{page}"],
            "has_next": page < self.pages,
        }

    def fetch_detail_page(self, channel: str, ref: str) -> dict:
        self.events.append(("detail", channel, ref))
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

    def test_completed_with_four_variants_in_order(self):
        h, report = self._run()
        assert report.status == STATUS_COMPLETED
        assert [(v.channel, v.task) for v in report.variants] == [
            (LINKEDIN_CHANNEL, f"{LINKEDIN_CHANNEL}:{STAGE_SEOUL_UNIVERSITY_PRIORITY}"),
            (LINKEDIN_CHANNEL, f"{LINKEDIN_CHANNEL}:{STAGE_EXPANDED}"),
            ("saramin", report.variants[2].task),
            ("jobkorea", report.variants[3].task),
        ]
        # AC2 디스크립터의 dedup_key 가 task 에 실려 있어야 배선 증명이 된다
        assert "saramin|or=" in report.variants[2].task
        assert "jobkorea|or=" in report.variants[3].task

    def test_banner_wraps_each_variant_and_pagination_runs_inside(self):
        h, _ = self._run()
        on = [s for s in h.driver.snippets if '"active": true' in s]
        off = [s for s in h.driver.snippets if '"active": false' in s]
        assert len(on) == 4 and len(off) == 4  # 변형마다 표시+해제 1쌍
        # 이벤트 순서: 각 변형은 배너 ON → list/detail/upsert → 배너 OFF
        js_idx = [i for i, e in enumerate(h.events) if e[0] == "js"]
        for k in range(0, len(js_idx), 2):
            start, end = js_idx[k], js_idx[k + 1]
            assert '"active": true' in h.events[start][1]
            assert '"active": false' in h.events[end][1]
            between = h.events[start + 1 : end]
            assert between, "배너 ON/OFF 사이에 순회가 있어야 한다"
            assert all(e[0] in ("list", "detail", "upsert") for e in between)

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
    def test_cap_reached_no_21st_request(self):
        h = Harness(pages=999)  # has_next 항상 True
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_COMPLETED
        assert max(p for _, p in h.list_calls) == 20
        # cap 도달 → RPS 는 확장 단계로 넘어가지 않고 종료(준비된 불린 변형 소진)
        lk = [v for v in report.variants if v.channel == LINKEDIN_CHANNEL]
        assert len(lk) == 1
        assert lk[0].pagination.next_action == NEXT_SWITCH_BOOLEAN_VARIANT


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
        # 2페이지 요청은 절대 나가지 않는다 (진행 금지)
        assert h.list_calls == [(LINKEDIN_CHANNEL, 1)]
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
        assert h.list_calls == [(LINKEDIN_CHANNEL, 1)]
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
