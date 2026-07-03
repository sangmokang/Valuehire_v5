"""PC-D5 — 라이브 ExecuteHarvestItem 어댑터 (GuardedPortalSearchRunner→harvest 계약).

인수기준: GuardedPortalSearchRunner 를 harvest 계약(HarvestItem→Iterable[profile], 챌린지
감지 시 STOP)으로 감싸는 어댑터가, 결정론 소비 테스트에서
  (1) 정상 검색 → 프로필 Iterable 반환,
  (2) 챌린지(세션락/authwall/재인증/사이트중단) 감지 → STOP(빈 반환 + 사유 기록),
  (3) 챌린지 후 봇처럼 다음 키워드를 계속 두드리지 않음(SOT2),
  (4) run_harvest_cycle 에 execute_item 으로 실제로 꽂혀 저장까지 흐름(고아 아님, R4)
을 단언한다. 브라우저/네트워크 없이 fake runner 로 결정론 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest

from tools.multi_position_sourcing.harvest_executor import HarvestSearchExecutor
from tools.multi_position_sourcing.harvest_runner import HarvestItem, run_harvest_cycle
from tools.multi_position_sourcing.portal_runtime import GuardedSearchResult


def _result(
    status: str,
    *,
    cards: tuple[object, ...] = (),
    reauth_cause: str = "",
    pause_site: bool = False,
    reason: str = "",
) -> GuardedSearchResult:
    return GuardedSearchResult(
        site="saramin",
        worker_id="w1",
        keyword="k",
        status=status,  # type: ignore[arg-type]
        reason=reason,
        reauth_cause=reauth_cause,
        pause_site=pause_site,
        candidate_cards=cards,  # type: ignore[arg-type]
    )


class _FakeRunner:
    """run_keyword_search 만 흉내내는 결정론 러너 (호출 순서대로 미리 세팅된 결과 반환)."""

    def __init__(self, results: list[GuardedSearchResult]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, int]] = []

    async def run_keyword_search(
        self, keyword: str, *, searches_today: int, reauth_cause_override: str = ""
    ) -> GuardedSearchResult:
        self.calls.append((keyword, searches_today))
        return self._results.pop(0)


def _executor(runner: _FakeRunner, keywords: tuple[str, ...]) -> HarvestSearchExecutor:
    return HarvestSearchExecutor(
        runner_for_channel=lambda ch: runner,
        keywords_for_segment=lambda seg: keywords,
    )


def test_returns_candidate_cards_on_search() -> None:
    runner = _FakeRunner([_result("searched", cards=("p1", "p2"))])
    ex = _executor(runner, ("engineer",))
    item = HarvestItem(segment_id="it_ai_data", channel="saramin", machine="m1")

    out = tuple(asyncio.run(ex(item)))

    assert out == ("p1", "p2")
    assert ex.stops == []
    assert runner.calls == [("engineer", 0)]


def test_multiple_keywords_accumulate_and_advance_pacing() -> None:
    runner = _FakeRunner(
        [_result("searched", cards=("a",)), _result("searched", cards=("b", "c"))]
    )
    ex = _executor(runner, ("kw1", "kw2"))
    item = HarvestItem(segment_id="it_ai_data", channel="saramin", machine="m1")

    out = tuple(asyncio.run(ex(item)))

    assert out == ("a", "b", "c")
    # searches_today 가 성공마다 1씩 증가(페이싱 카운터 전파)
    assert runner.calls == [("kw1", 0), ("kw2", 1)]


def test_challenge_not_ready_reauth_stops_empty_with_reason() -> None:
    runner = _FakeRunner(
        [
            _result("not_ready", reauth_cause="login_redirect"),
            _result("searched", cards=("must_not_reach",)),
        ]
    )
    ex = _executor(runner, ("kw1", "kw2"))
    item = HarvestItem(segment_id="it_ai_data", channel="linkedin_rps", machine="m1")

    out = tuple(asyncio.run(ex(item)))

    assert out == ()  # 빈 반환
    assert len(ex.stops) == 1
    assert "login_redirect" in ex.stops[0].reason  # 사유
    # 챌린지 뜬 뒤 두 번째 키워드를 두드리지 않는다(봇 금지, SOT2)
    assert len(runner.calls) == 1


def test_pause_site_error_stops_empty_with_reason() -> None:
    runner = _FakeRunner([_result("error", pause_site=True, reason="reauth recovery failed")])
    ex = _executor(runner, ("kw1",))
    item = HarvestItem(segment_id="it_ai_data", channel="linkedin_rps", machine="m1")

    out = tuple(asyncio.run(ex(item)))

    assert out == ()
    assert len(ex.stops) == 1
    assert ex.stops[0].channel == "linkedin_rps"


def test_no_keywords_returns_empty_and_does_not_search() -> None:
    runner = _FakeRunner([])
    ex = _executor(runner, ())
    item = HarvestItem(segment_id="unknown", channel="saramin", machine="m1")

    out = tuple(asyncio.run(ex(item)))

    assert out == ()
    assert runner.calls == []  # 검색어 없으면 아예 두드리지 않는다


def test_adapter_plugs_into_run_harvest_cycle() -> None:
    """R4 고아 금지: 어댑터가 run_harvest_cycle 의 execute_item 으로 실제로 동작한다."""
    runner = _FakeRunner([_result("searched", cards=("p1", "p2"))])
    ex = _executor(runner, ("engineer",))
    saved: list[object] = []

    summary = run_harvest_cycle(
        [HarvestItem(segment_id="it_ai_data", channel="saramin", machine="m1")],
        execute_item=ex,
        save_rail=saved.append,
        run_id="run-1",
        today="2026-07-03",
    )

    assert summary.saved_profiles == 2
    assert saved == ["p1", "p2"]
    assert summary.log_records[0]["status"] == "ok"
