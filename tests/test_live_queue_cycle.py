"""Tests for the live queue <-> portal worker wiring (P0).

These cover three new seams:
  1. ``plan_queue_cycle`` — pure gating planner shared by the sync and live paths.
  2. ``run_live_queue_cycle`` — async cycle that executes eligible items through an
     injected ``execute_item`` adapter and aggregates real result counts.
  3. ``execute_queue_item`` / ``keywords_for_item`` — the adapter that drives a
     channel-bound ``GuardedPortalSearchRunner`` and maps its results.

The sync ``run_queue_cycle`` behavior must stay identical; a parity test guards that.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.models import (
    CandidateResultCard,
    ItemSearchResult,
    KeywordSession,
    QueueItem,
)
from tools.multi_position_sourcing.portal_queue_executor import (
    execute_queue_item,
    keywords_for_item,
    make_execute_item,
)
from tools.multi_position_sourcing.portal_runtime import GuardedSearchResult
from tools.multi_position_sourcing.queue_runner import (
    plan_queue_cycle,
    run_live_queue_cycle,
    run_queue_cycle,
)

NOW = "2026-06-10T00:00:00+00:00"


def _saramin_session(keyword: str) -> KeywordSession:
    return KeywordSession(channel="saramin", standard_keyword=keyword)


def _item(group_id: str, *, channel="saramin", keywords=(), status="pending") -> QueueItem:
    plan = tuple(KeywordSession(channel=channel, standard_keyword=k) for k in keywords)
    return QueueItem(group_id=group_id, channel=channel, keyword_plan=plan, status=status)


class _RecordingExecutor:
    """An injected ``execute_item`` that records calls and returns canned results."""

    def __init__(self, result_by_group: dict[str, ItemSearchResult]) -> None:
        self.result_by_group = result_by_group
        self.calls: list[str] = []

    async def __call__(self, item: QueueItem) -> ItemSearchResult:
        self.calls.append(item.group_id)
        return self.result_by_group[item.group_id]


class _FakeRunner:
    """Stands in for a channel-bound GuardedPortalSearchRunner."""

    def __init__(self, results_by_keyword: dict[str, GuardedSearchResult]) -> None:
        self.results_by_keyword = results_by_keyword
        self.calls: list[tuple[str, int]] = []

    async def run_keyword_search(
        self, keyword: str, *, searches_today: int, reauth_cause_override: str = ""
    ) -> GuardedSearchResult:
        self.calls.append((keyword, searches_today))
        return self.results_by_keyword[keyword]


def _guarded(keyword: str, *, status: str, cards: int = 0, reason: str = "", reauth_cause: str = "") -> GuardedSearchResult:
    candidate_cards = tuple(
        CandidateResultCard(profile_url=f"https://saramin.example/{keyword}/{i}", source_channel="saramin")
        for i in range(cards)
    )
    return GuardedSearchResult(
        site="saramin",
        worker_id="default",
        keyword=keyword,
        status=status,  # type: ignore[arg-type]
        reason=reason or status,
        reauth_cause=reauth_cause,
        candidate_cards=candidate_cards,
    )


# --------------------------------------------------------------------------------------
# plan_queue_cycle (pure planner) + sync parity
# --------------------------------------------------------------------------------------
class PlanQueueCycleTests(unittest.TestCase):
    def test_no_chrome_keeps_every_item(self) -> None:
        queue = (_item("g1"),)
        plan = plan_queue_cycle(queue, now_iso=NOW, chrome_connected=False)
        self.assertEqual(plan.decisions, ("keep",))
        self.assertIn("Chrome CDP not connected", plan.stopped_reasons[0])

    def test_session_required_blocks_protected_channel(self) -> None:
        queue = (_item("g1", channel="saramin"),)
        plan = plan_queue_cycle(queue, now_iso=NOW, chrome_connected=True)
        self.assertEqual(plan.decisions, ("keep",))
        self.assertIn("saramin login session not confirmed", plan.stopped_reasons[0])

    def test_ready_protected_channel_is_processed(self) -> None:
        queue = (_item("g1", channel="saramin"),)
        plan = plan_queue_cycle(
            queue, now_iso=NOW, chrome_connected=True, portal_sessions={"saramin": True}
        )
        self.assertEqual(plan.decisions, ("process",))
        self.assertEqual(plan.stopped_reasons, ())

    def test_max_items_caps_processing(self) -> None:
        queue = (_item("g1", channel="public_web"), _item("g2", channel="public_web"))
        plan = plan_queue_cycle(
            queue, now_iso=NOW, chrome_connected=True, max_items_per_cycle=1
        )
        self.assertEqual(plan.decisions, ("process", "keep"))

    def test_sync_cycle_still_matches_legacy_behavior(self) -> None:
        # Same scenario the pre-existing suite asserts: ready protected channel -> done.
        queue = (_item("backend-portal", channel="saramin", keywords=()),)
        summary = run_queue_cycle(
            queue, now_iso=NOW, chrome_connected=True, portal_sessions={"saramin": True}
        )
        self.assertEqual(summary.searched_groups, ("backend-portal",))
        self.assertEqual(summary.stopped_reasons, ())
        self.assertEqual(summary.updated_items[0].status, "done")
        self.assertEqual(summary.collected_cards, 0)


# --------------------------------------------------------------------------------------
# run_live_queue_cycle (async orchestration over injected executor)
# --------------------------------------------------------------------------------------
class RunLiveQueueCycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_chrome_never_calls_executor(self) -> None:
        executor = _RecordingExecutor({})
        queue = (_item("g1"),)
        summary = await run_live_queue_cycle(
            queue, now_iso=NOW, execute_item=executor, chrome_connected=False
        )
        self.assertEqual(executor.calls, [])
        self.assertEqual(summary.searched_groups, ())
        self.assertEqual(summary.updated_items[0].status, "pending")
        self.assertIn("Chrome CDP not connected", summary.stopped_reasons[0])

    async def test_session_not_ready_never_calls_executor(self) -> None:
        executor = _RecordingExecutor({})
        queue = (_item("g1", channel="saramin"),)
        summary = await run_live_queue_cycle(
            queue, now_iso=NOW, execute_item=executor, chrome_connected=True
        )
        self.assertEqual(executor.calls, [])
        self.assertIn("saramin login session not confirmed", summary.stopped_reasons[0])
        self.assertEqual(summary.updated_items[0].status, "pending")

    async def test_eligible_item_executes_and_aggregates_cards(self) -> None:
        executor = _RecordingExecutor(
            {"g1": ItemSearchResult(status="done", collected_cards=3)}
        )
        queue = (_item("g1", channel="saramin", keywords=("AI 엔지니어",)),)
        summary = await run_live_queue_cycle(
            queue,
            now_iso=NOW,
            execute_item=executor,
            chrome_connected=True,
            portal_sessions={"saramin": True},
        )
        self.assertEqual(executor.calls, ["g1"])
        self.assertEqual(summary.searched_groups, ("g1",))
        self.assertEqual(summary.collected_cards, 3)
        self.assertEqual(summary.updated_items[0].status, "done")
        self.assertEqual(summary.updated_items[0].attempts, 1)

    async def test_failed_execution_marks_item_failed(self) -> None:
        executor = _RecordingExecutor(
            {"g1": ItemSearchResult(status="failed", collected_cards=0, last_error="boom")}
        )
        queue = (_item("g1", channel="saramin"),)
        summary = await run_live_queue_cycle(
            queue,
            now_iso=NOW,
            execute_item=executor,
            chrome_connected=True,
            portal_sessions={"saramin": True},
        )
        self.assertEqual(summary.searched_groups, ())
        self.assertEqual(summary.updated_items[0].status, "failed")
        self.assertEqual(summary.updated_items[0].last_error, "boom")
        self.assertEqual(summary.updated_items[0].attempts, 1)

    async def test_stopped_execution_preserves_pending_for_resume(self) -> None:
        executor = _RecordingExecutor(
            {
                "g1": ItemSearchResult(
                    status="stopped", collected_cards=0, stop_reason="reauth required before search"
                )
            }
        )
        queue = (_item("g1", channel="saramin"),)
        summary = await run_live_queue_cycle(
            queue,
            now_iso=NOW,
            execute_item=executor,
            chrome_connected=True,
            portal_sessions={"saramin": True},
        )
        self.assertEqual(summary.searched_groups, ())
        self.assertIn("reauth required before search", summary.stopped_reasons)
        # Preserved for resume: not burned to failed, attempts not incremented.
        self.assertEqual(summary.updated_items[0].status, "pending")
        self.assertEqual(summary.updated_items[0].attempts, 0)

    async def test_max_items_limits_live_execution(self) -> None:
        executor = _RecordingExecutor(
            {
                "g1": ItemSearchResult(status="done", collected_cards=2),
                "g2": ItemSearchResult(status="done", collected_cards=9),
            }
        )
        queue = (_item("g1", channel="public_web"), _item("g2", channel="public_web"))
        summary = await run_live_queue_cycle(
            queue,
            now_iso=NOW,
            execute_item=executor,
            chrome_connected=True,
            max_items_per_cycle=1,
        )
        self.assertEqual(executor.calls, ["g1"])
        self.assertEqual(summary.searched_groups, ("g1",))
        self.assertEqual(summary.collected_cards, 2)
        self.assertEqual(summary.updated_items[1].status, "pending")


# --------------------------------------------------------------------------------------
# execute_queue_item / keywords_for_item (the real worker adapter)
# --------------------------------------------------------------------------------------
class KeywordsForItemTests(unittest.TestCase):
    def test_collects_dedupes_and_preserves_order(self) -> None:
        item = QueueItem(
            group_id="g1",
            channel="saramin",
            keyword_plan=(
                _saramin_session("AI 엔지니어"),
                _saramin_session("머신러닝"),
                _saramin_session("AI 엔지니어"),  # duplicate
                _saramin_session("   "),  # blank skipped
            ),
        )
        self.assertEqual(keywords_for_item(item), ("AI 엔지니어", "머신러닝"))

    def test_empty_plan_yields_no_keywords(self) -> None:
        self.assertEqual(keywords_for_item(_item("g1")), ())


class ExecuteQueueItemTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_keywords_searched_sums_cards_and_paces(self) -> None:
        runner = _FakeRunner(
            {
                "AI 엔지니어": _guarded("AI 엔지니어", status="searched", cards=2),
                "머신러닝": _guarded("머신러닝", status="searched", cards=3),
            }
        )
        item = _item("g1", channel="saramin", keywords=("AI 엔지니어", "머신러닝"))
        result = await execute_queue_item(item, runner=runner)
        self.assertEqual(result.status, "done")
        self.assertEqual(result.collected_cards, 5)
        # searches_today advances as each keyword search succeeds (pacing input).
        self.assertEqual(runner.calls, [("AI 엔지니어", 0), ("머신러닝", 1)])

    async def test_searches_today_seed_is_respected(self) -> None:
        runner = _FakeRunner({"AI 엔지니어": _guarded("AI 엔지니어", status="searched", cards=1)})
        item = _item("g1", channel="saramin", keywords=("AI 엔지니어",))
        await execute_queue_item(item, runner=runner, searches_today=4)
        self.assertEqual(runner.calls, [("AI 엔지니어", 4)])

    async def test_not_ready_stops_early_and_reports_reason(self) -> None:
        runner = _FakeRunner(
            {
                "kw1": _guarded(
                    "kw1", status="not_ready", reason="reauth required before search", reauth_cause="login_redirect"
                ),
                "kw2": _guarded("kw2", status="searched", cards=5),
            }
        )
        item = _item("g1", channel="saramin", keywords=("kw1", "kw2"))
        result = await execute_queue_item(item, runner=runner)
        self.assertEqual(result.status, "stopped")
        self.assertIn("reauth required before search", result.stop_reason)
        # Stops at the first not-ready keyword; kw2 is never attempted.
        self.assertEqual(runner.calls, [("kw1", 0)])

    async def test_pacing_blocked_stops(self) -> None:
        runner = _FakeRunner(
            {"kw1": _guarded("kw1", status="pacing_blocked", reason="daily protected-portal search cap reached")}
        )
        item = _item("g1", channel="saramin", keywords=("kw1",))
        result = await execute_queue_item(item, runner=runner)
        self.assertEqual(result.status, "stopped")
        self.assertIn("cap reached", result.stop_reason)

    async def test_error_marks_failed(self) -> None:
        runner = _FakeRunner({"kw1": _guarded("kw1", status="error", reason="portal search failed")})
        item = _item("g1", channel="saramin", keywords=("kw1",))
        result = await execute_queue_item(item, runner=runner)
        self.assertEqual(result.status, "failed")
        self.assertIn("portal search failed", result.last_error)

    async def test_selector_missing_marks_failed(self) -> None:
        runner = _FakeRunner({"kw1": _guarded("kw1", status="selector_missing", reason="portal selector missing")})
        item = _item("g1", channel="saramin", keywords=("kw1",))
        result = await execute_queue_item(item, runner=runner)
        self.assertEqual(result.status, "failed")

    async def test_empty_plan_is_done_without_calling_runner(self) -> None:
        runner = _FakeRunner({})
        item = _item("g1", channel="saramin", keywords=())
        result = await execute_queue_item(item, runner=runner)
        self.assertEqual(result.status, "done")
        self.assertEqual(result.collected_cards, 0)
        self.assertEqual(runner.calls, [])


class MakeExecuteItemTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_runner_lazily_per_processed_channel(self) -> None:
        built: list[str] = []

        def runner_for_channel(channel: str):
            built.append(channel)
            return _FakeRunner({"AI 엔지니어": _guarded("AI 엔지니어", status="searched", cards=4)})

        execute_item = make_execute_item(runner_for_channel)
        # Only the saramin item clears the gates (public_web also eligible but distinct);
        # the factory must be invoked exactly once per processed item, with its channel.
        queue = (_item("g1", channel="saramin", keywords=("AI 엔지니어",)),)
        summary = await run_live_queue_cycle(
            queue,
            now_iso=NOW,
            execute_item=execute_item,
            chrome_connected=True,
            portal_sessions={"saramin": True},
        )
        self.assertEqual(built, ["saramin"])
        self.assertEqual(summary.searched_groups, ("g1",))
        self.assertEqual(summary.collected_cards, 4)

    async def test_factory_not_called_when_no_item_is_eligible(self) -> None:
        built: list[str] = []

        def runner_for_channel(channel: str):
            built.append(channel)
            return _FakeRunner({})

        execute_item = make_execute_item(runner_for_channel)
        queue = (_item("g1", channel="saramin", keywords=("AI 엔지니어",)),)
        # No portal session confirmed -> gated out -> factory must never run.
        await run_live_queue_cycle(
            queue, now_iso=NOW, execute_item=execute_item, chrome_connected=True
        )
        self.assertEqual(built, [])


if __name__ == "__main__":
    unittest.main()
