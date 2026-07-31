"""V1 3차 적대검증 STILL-BROKEN 재현 — 결함 ⑥(저장 직전 BLOCKED 재확인),
⑦(제외어 최종 강제), ⑩(진짜 동시 실행).

근거: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-3/AC-7(전량 저장은
차단 신호 앞에서는 멈춘다), §2 "3사 동시 검색", §3 D6(동시 착수).

전부 페이크 — 실 브라우저/네트워크/실 sleep 0. 오케스트레이터 페이크 일습은
tests/test_aisearch_orchestrator.py 의 Harness 를 재사용한다(복제 금지).
"""
from __future__ import annotations

import pytest

import threading

from test_aisearch_orchestrator import (
    PAYLOAD_60,
    Harness,
    _candidate,
    _jd,
)

from apps.aisearch.core.orchestrator import (
    LINKEDIN_CHANNEL,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    run_search_pipeline,
)
from apps.aisearch.core.pagination_store import paginate_and_store


# ── 결함 ⑥ — 목록/상세 "저장 직전" BLOCKED 재확인 ──────────────────────────


@pytest.fixture(autouse=True)
def _structural_evidence_verifier(monkeypatch):
    """영수증 **실물** 무결성은 전용 테스트가 지킨다 — 여기서는 모양 검사로 대체.

    프로덕션 기본값이 정본 검증기(browser_evidence.complete_evidence_payload)라는
    사실은 tests/test_aisearch_v1_round3.py 가 따로 잠근다.
    """
    from tests.aisearch_evidence import use_structural_verifier

    use_structural_verifier(monkeypatch)


class TestBlockedRecheckBeforeStore:
    def test_captcha_during_list_response_saves_zero_rows(self):
        """목록 페이지 응답 수신 "도중" 캡차 인입 → 그 페이지 저장 0건.

        fetch 진입 전 점검은 통과했지만 응답이 돌아오는 사이 캡차가 떴다면,
        저장 직전 재확인이 없으면 오염 가능 페이지가 그대로 저장된다(결함 ⑥).
        """
        h = Harness(pages=3)

        def side_effect(channel: str, page: int) -> None:
            if page == 1:  # 어느 채널이든 1페이지 응답 도중 캡차
                h.monitor.on_signal("captcha")

        h.list_side_effect = side_effect
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_BLOCKED
        assert h.store.rows == []  # 응답은 받았지만 저장 직전 재확인으로 0건

    def test_captcha_during_detail_response_saves_zero_detail_rows(self):
        """상세 페이지 응답 수신 "도중" 캡차 인입 → 상세 저장 0건."""
        h = Harness(pages=1)

        def detail_side_effect(channel: str, ref: str) -> None:
            h.monitor.on_signal("captcha")  # 상세 응답 도중 캡차

        h.detail_side_effect = detail_side_effect
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_BLOCKED
        detail_rows = [r for _t, r in h.store.rows if r["page_type"] == "detail"]
        assert detail_rows == []  # 상세는 한 건도 저장되지 않는다

    def test_pagination_before_store_hook_blocks_upsert(self):
        """AC3 단위 계약: before_store 훅이 예외를 던지면 upsert 는 나가지 않는다."""

        class Boom(Exception):
            pass

        stored: list[dict] = []

        class Store:
            def upsert(self, table: str, row: dict) -> None:
                stored.append(row)

        def fetch_list(page: int) -> dict:
            return {
                "url": f"https://x.test/?p={page}",
                "content": "<html/>",
                "detail_refs": [],
                "has_next": False,
            }

        def before_store() -> None:
            raise Boom("blocked right before store")

        try:
            paginate_and_store(
                fetch_list,
                lambda ref: {"url": ref, "content": "<html/>"},
                Store(),
                channel="saramin",
                position_ref="Tech PM",
                machine="macmini",
                before_store=before_store,
            )
        except Boom:
            pass
        else:  # pragma: no cover - 결함 재현 시
            raise AssertionError("before_store 예외가 전파되지 않았다")
        assert stored == []


# ── 결함 ⑦ — 제외어 최종 강제(등록·초안 전 exclusion 게이트) ────────────────


class TestExclusionGate:
    def _jd_with_exclusion(self) -> dict:
        jd = _jd()
        jd["not_keywords"] = ["인턴"]
        return jd

    def test_excluded_candidate_never_registered_nor_drafted(self):
        """"인턴" 제외 + 인턴 후보 반환 → 등록 계획 0, 초안 0, excluded 1."""
        h = Harness(pages=1)
        cand = _candidate(PAYLOAD_60, "https://saramin.example/p/intern")
        cand["record"]["career_brief"] = "현대로템 인턴"  # 제외어 매칭 후보
        h.candidates["saramin"] = [cand]

        report = run_search_pipeline(self._jd_with_exclusion(), h.deps())
        assert report.status == STATUS_COMPLETED  # 제외는 실패가 아니다
        assert report.registered == []  # 등록 계획 0
        assert report.drafts == []  # 초안 0
        assert h.clickup.dedup_calls == []  # 등록 경로(중복확인 포함) 진입 0
        assert h.clickup.writes == [] and h.discord.posts == []
        excluded = report.excluded
        assert len(excluded) == 1  # excluded 1 + 제외 사유 기록
        entry = excluded[0]
        assert entry["channel"] == "saramin"
        assert entry["profile_url"] == "https://saramin.example/p/intern"
        assert entry["matched_keyword"] == "인턴"
        assert entry["matched_field"]
        assert "인턴" in entry["reason"]

    def test_exclusion_match_is_case_insensitive(self):
        h = Harness(pages=1)
        jd = _jd()
        jd["not_keywords"] = ["intern"]
        cand = _candidate(PAYLOAD_60, "https://jk.example/p/i1")
        cand["record"]["career_brief"] = "Samsung INTERN program"
        h.candidates["jobkorea"] = [cand]
        report = run_search_pipeline(jd, h.deps())
        assert report.registered == [] and report.drafts == []
        assert [e["matched_keyword"] for e in report.excluded] == ["intern"]

    def test_non_matching_candidate_still_registers(self):
        """제외어가 있어도 매칭 안 되는 후보는 정상 등록된다(과차단 금지)."""
        h = Harness(pages=1)
        h.candidates["saramin"] = [
            _candidate(PAYLOAD_60, "https://saramin.example/p/ok")
        ]
        report = run_search_pipeline(self._jd_with_exclusion(), h.deps())
        assert report.status == STATUS_COMPLETED
        assert len(report.registered) == 1
        assert report.excluded == []


# ── 결함 ⑩ — 채널별 파이프라인 진짜 동시 실행(스레드) ──────────────────────


class TestTrueConcurrency:
    def test_blocked_linkedin_does_not_prevent_saramin_start(self):
        """링크드인 드라이버 호출이 블록돼도 사람인은 시작·진행된다(D6).

        결정론적 증명: 링크드인 1페이지 fetch 를 threading.Event 대기로 막아두고,
        사람인 첫 fetch 가 그 이벤트를 세운다. 라운드로빈(한 스레드)이면 링크드인이
        끝나기 전 사람인이 시작될 수 없어 대기가 타임아웃(False)된다.
        """
        h = Harness(pages=1)
        saramin_started = threading.Event()
        linkedin_saw_saramin: list[bool] = []
        linkedin_first = threading.Event()

        def side_effect(channel: str, page: int) -> None:
            if channel == LINKEDIN_CHANNEL and not linkedin_first.is_set():
                linkedin_first.set()
                # 링크드인 호출이 "블록"된 동안 사람인이 시작되는지 관찰
                linkedin_saw_saramin.append(saramin_started.wait(timeout=3.0))
            elif channel == "saramin":
                saramin_started.set()

        h.list_side_effect = side_effect
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_COMPLETED
        assert linkedin_saw_saramin == [True], (
            "링크드인 fetch 가 블록된 3초 동안 사람인이 시작되지 않았다 — "
            "진짜 동시 실행이 아니다(결함 ⑩)"
        )

    def test_monitor_access_is_serialized_under_lock(self):
        """공유 상태(개입 모니터)는 락으로 보호 — 동시 진입 0 을 증명한다."""
        h = Harness(pages=2)
        overlap: list[str] = []
        in_flight = threading.Lock()
        original_poll = h.monitor.poll

        def guarded_poll():
            if not in_flight.acquire(blocking=False):
                overlap.append("concurrent poll")  # pragma: no cover - 결함 시
                return original_poll()
            try:
                return original_poll()
            finally:
                in_flight.release()

        h.monitor.poll = guarded_poll  # type: ignore[method-assign]
        report = run_search_pipeline(_jd(), h.deps())
        assert report.status == STATUS_COMPLETED
        assert overlap == []
