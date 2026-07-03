"""PC-D5 — 라이브 ExecuteHarvestItem 어댑터 (GuardedPortalSearchRunner→harvest 계약).

인수기준: GuardedPortalSearchRunner 를 harvest 계약(HarvestItem→Iterable[profile], 챌린지
감지 시 STOP)으로 감싸는 어댑터가, 결정론 소비 테스트에서
  (1) 정상 검색 → 프로필 Iterable 반환,
  (2) 챌린지(세션락/authwall/재인증/사이트중단)·상한·DOM오류 등 비-정상 상태 감지 → 즉시 STOP,
      그 이전에 찾은 카드는 보존(harvest=발견 즉시 저장), STOP 사유를 기록,
  (3) STOP 후 봇처럼 다음 키워드를 계속 두드리지 않음(SOT2),
  (4) run_harvest_cycle 에 execute_item 으로 실제로 꽂혀 저장까지 흐름(고아 아님, R4)
을 단언한다. 브라우저/네트워크 없이 fake runner 로 결정론 검증한다.

STOP 규율은 기존 라이브 어댑터 portal_queue_executor.execute_queue_item 선례와 일치한다 —
``searched`` 만 다음 키워드로 진행하고, 그 외 모든 status(not_ready·pacing_blocked·error·
selector_missing) 또는 pause_site 는 즉시 halt(같은 러너를 감싸는 두 어댑터의 봇금지 불변식 일치).
"""

from __future__ import annotations

import asyncio

from tools.multi_position_sourcing.harvest_executor import HarvestSearchExecutor
from tools.multi_position_sourcing.harvest_runner import HarvestItem, run_harvest_cycle
from tools.multi_position_sourcing.portal_runtime import GuardedSearchResult


def _result(
    status: str,
    *,
    cards: tuple[object, ...] = (),
    reauth_cause: str = "",
    pause_site: bool = False,
    skipped_due_to_cap: bool = False,
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
        skipped_due_to_cap=skipped_due_to_cap,
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

    assert out == ()  # 첫 키워드에서 챌린지 → 모은 카드 없음
    assert len(ex.stops) == 1
    assert "login_redirect" in ex.stops[0].reason  # 사유
    # 챌린지 뜬 뒤 두 번째 키워드를 두드리지 않는다(봇 금지, SOT2)
    assert len(runner.calls) == 1


def test_challenge_keeps_already_collected_cards_and_stops() -> None:
    """kw1 이 카드를 찾은 뒤 kw2 에서 챌린지가 뜨면: 찾은 카드는 보존, kw3 는 두드리지 않는다.

    harvest 는 발견 즉시 저장(차감0)이라 챌린지 전에 실제로 찾은 카드를 버리지 않는다. 동시에
    챌린지 후 남은 키워드(kw3)는 두드리지 않아 봇처럼 굴지 않는다(SOT2). runner 에 결과를 2개만
    넣어 kw3 를 호출하면 IndexError 가 나도록 해 '멈춤'을 강제 검증한다.
    """
    runner = _FakeRunner(
        [
            _result("searched", cards=("early1", "early2")),
            _result("not_ready", reauth_cause="http_403"),
        ]
    )
    ex = _executor(runner, ("kw1", "kw2", "kw3"))
    item = HarvestItem(segment_id="it_ai_data", channel="saramin", machine="m1")

    out = tuple(asyncio.run(ex(item)))

    assert out == ("early1", "early2")  # 챌린지 전 카드 보존
    assert len(ex.stops) == 1
    assert "http_403" in ex.stops[0].reason
    assert len(runner.calls) == 2  # kw3 는 두드리지 않음


def test_pacing_blocked_stops_and_does_not_hammer() -> None:
    """일일 검색 상한(pacing_blocked) 도달 시 STOP — 다음 키워드를 계속 두드리지 않는다.

    같은 러너를 감싸는 기존 어댑터 portal_queue_executor 도 pacing_blocked 를 stop 으로 취급한다.
    상한 도달을 'ok/0건' 으로 삼키면 드라이버가 하루치 상한을 모른 채 계속 돌린다(봇 근접).
    """
    runner = _FakeRunner(
        [
            _result(
                "pacing_blocked",
                skipped_due_to_cap=True,
                reason="daily protected-portal search cap reached",
            ),
            _result("searched", cards=("must_not_reach",)),
        ]
    )
    ex = _executor(runner, ("kw1", "kw2"))
    item = HarvestItem(segment_id="it_ai_data", channel="saramin", machine="m1")

    out = tuple(asyncio.run(ex(item)))

    assert out == ()
    assert len(ex.stops) == 1
    assert "cap" in ex.stops[0].reason.lower()
    assert len(runner.calls) == 1  # 상한 후 두 번째 키워드 안 두드림


def test_selector_missing_stops_fail_closed() -> None:
    """selector_missing(DOM 구조 어긋남) 도 즉시 STOP — 같은 페이지를 키워드마다 재시도하지 않는다."""
    runner = _FakeRunner(
        [_result("selector_missing", reason="search box not found"), _result("searched", cards=("x",))]
    )
    ex = _executor(runner, ("kw1", "kw2"))
    item = HarvestItem(segment_id="it_ai_data", channel="saramin", machine="m1")

    out = tuple(asyncio.run(ex(item)))

    assert out == ()
    assert len(ex.stops) == 1
    assert len(runner.calls) == 1


def test_stopping_result_cards_are_preserved() -> None:
    """정지 결과 자체가 카드를 실어 보내면(예: not_ready 직전 페이지에 렌더된 카드) 보존한다.

    portal_runtime._result_from_attempt 는 비-searched 결과에도 attempt.candidate_cards 를
    실어 줄 수 있다 — 그 카드를 버리지 않고 저장 대상으로 넘긴다(harvest=발견 즉시 저장).
    """
    runner = _FakeRunner(
        [_result("not_ready", cards=("onpage1",), reauth_cause="login_marker_lost")]
    )
    ex = _executor(runner, ("kw1", "kw2"))
    item = HarvestItem(segment_id="it_ai_data", channel="saramin", machine="m1")

    out = tuple(asyncio.run(ex(item)))

    assert out == ("onpage1",)  # 정지 결과에 실린 카드도 보존
    assert len(ex.stops) == 1
    assert len(runner.calls) == 1  # 그래도 다음 키워드는 안 두드림


def test_pause_site_alone_stops_even_without_reauth_or_error() -> None:
    """pause_site 는 STOP 사유로 명시 기록된다(사람 개입 필요 신호)."""
    runner = _FakeRunner([_result("not_ready", reauth_cause="", pause_site=True)])
    ex = _executor(runner, ("kw1", "kw2"))
    item = HarvestItem(segment_id="it_ai_data", channel="linkedin_rps", machine="m1")

    out = tuple(asyncio.run(ex(item)))

    assert out == ()
    assert len(ex.stops) == 1
    assert "pause_site" in ex.stops[0].reason
    assert len(runner.calls) == 1  # 두 번째 키워드 안 두드림


def test_searched_with_pause_site_still_stops() -> None:
    """pause_site 는 status 와 무관한 무조건 STOP — status='searched' 여도 멈춘다(봇금지 방어).

    실제 러너는 searched 에 pause_site 를 세우지 않지만, 어댑터는 그 불변식에 기대지 않고
    pause_site 를 최우선 STOP 신호로 방어한다(V1 Codex 지적). 카드는 보존하되 다음 키워드는
    두드리지 않는다.
    """
    runner = _FakeRunner(
        [
            _result("searched", cards=("p1",), pause_site=True),
            _result("searched", cards=("must_not_reach",)),
        ]
    )
    ex = _executor(runner, ("kw1", "kw2"))
    item = HarvestItem(segment_id="it_ai_data", channel="linkedin_rps", machine="m1")

    out = tuple(asyncio.run(ex(item)))

    assert out == ("p1",)  # searched 카드는 보존
    assert len(ex.stops) == 1
    assert "pause_site" in ex.stops[0].reason
    assert len(runner.calls) == 1  # pause_site 후 다음 키워드 안 두드림


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
