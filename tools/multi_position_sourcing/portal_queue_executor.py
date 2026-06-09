"""Adapter wiring a queue item to a live ``GuardedPortalSearchRunner`` (P0).

This is the seam the diagnosis flagged as missing: ``run_queue_cycle`` gated items but
never actually searched. ``execute_queue_item`` runs an item's keyword plan through a
channel-bound guarded runner and reports a fail-closed :class:`ItemSearchResult` that
``run_live_queue_cycle`` aggregates.

Boundaries kept deliberately narrow:
  - It owns NO Playwright/browser lifecycle. The caller builds and supplies a runner that
    is already bound to the item's channel (see ``portal_live_check`` search wiring).
  - It performs NO writes, outreach, or profile saving — it only collects public result
    cards. ``opened/saved/matched_profiles`` stay 0 until those stages are wired.
  - The runner is duck-typed (only ``run_keyword_search`` is required) so this module does
    not import the heavy portal runtime and stays cheap to import in the dry-run path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .models import Channel, ItemSearchResult, QueueItem

# Builds (or returns) a GuardedPortalSearchRunner already bound to the given channel.
RunnerForChannel = Callable[[Channel], Any]


def keywords_for_item(item: QueueItem) -> tuple[str, ...]:
    """Return the ordered, de-duplicated standard keywords for an item's plan.

    Only ``standard_keyword`` is used here; ``variants``/``llm_screening_keywords`` are
    LLM-screening hints for a later stage, not portal query terms. Blank entries are
    dropped and order is preserved (first occurrence wins).
    """
    seen: set[str] = set()
    keywords: list[str] = []
    for session in item.keyword_plan:
        keyword = (session.standard_keyword or "").strip()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword)
    return tuple(keywords)


async def execute_queue_item(
    item: QueueItem,
    *,
    runner: Any,
    searches_today: int = 0,
) -> ItemSearchResult:
    """Run an item's keyword plan through ``runner`` and map the outcome (fail-closed).

    ``runner`` must expose ``async run_keyword_search(keyword, *, searches_today)`` and is
    expected to be bound to ``item.channel``. ``searches_today`` seeds the runner's pacing
    counter and advances once per successful keyword search within this item.

    Stops at the first non-searched keyword:
      - ``not_ready`` / ``pacing_blocked`` -> ``ItemSearchResult(status="stopped", ...)``
        (resumable: reauth needed, owner activity, or daily cap reached)
      - ``error`` / ``selector_missing``   -> ``ItemSearchResult(status="failed", ...)``
    An empty plan is a no-op ``done`` (the runner is never called).
    """
    keywords = keywords_for_item(item)
    collected_cards = 0
    count = searches_today

    for keyword in keywords:
        result = await runner.run_keyword_search(keyword, searches_today=count)
        collected_cards += len(getattr(result, "candidate_cards", ()) or ())

        if result.status == "searched":
            count += 1
            continue
        if result.status in {"not_ready", "pacing_blocked"}:
            return ItemSearchResult(
                status="stopped",
                collected_cards=collected_cards,
                stop_reason=result.reason or result.status,
                last_error=getattr(result, "reauth_cause", "") or "",
            )
        # "error" or "selector_missing" (or any unexpected status): fail-closed.
        return ItemSearchResult(
            status="failed",
            collected_cards=collected_cards,
            last_error=result.reason or result.status,
        )

    return ItemSearchResult(status="done", collected_cards=collected_cards)


def make_execute_item(
    runner_for_channel: RunnerForChannel,
    *,
    searches_today: int = 0,
) -> Callable[[QueueItem], Awaitable[ItemSearchResult]]:
    """Adapt a per-channel runner factory into an ``execute_item`` for the live cycle.

    This is the single injection point production uses:

        runner_for_channel = lambda channel: build_guarded_runner(channel, ...)
        summary = await run_live_queue_cycle(
            queue, now_iso=..., execute_item=make_execute_item(runner_for_channel),
            chrome_connected=True, portal_sessions=...,
        )

    The factory is invoked lazily, once per processed item, so a worker/browser for a
    channel is only built when an item for that channel actually clears the gates.
    """

    async def _execute(item: QueueItem) -> ItemSearchResult:
        runner = runner_for_channel(item.channel)
        return await execute_queue_item(item, runner=runner, searches_today=searches_today)

    return _execute
