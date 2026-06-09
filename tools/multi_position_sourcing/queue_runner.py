from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from .models import Channel, ItemSearchResult, QueueCycleSummary, QueueItem
from .portal_session import portal_session_pending_reason, portal_session_ready

# An injected async adapter that executes one eligible queue item against a live portal
# and returns the real outcome. Production wires ``portal_queue_executor.execute_queue_item``
# (bound to a channel-specific GuardedPortalSearchRunner); tests inject a fake.
ExecuteItem = Callable[[QueueItem], Awaitable[ItemSearchResult]]

STOP_REASONS = {
    "captcha": "captcha/security challenge detected",
    "2fa": "2FA/security verification detected",
    "ip_security": "IP security or abnormal access warning detected",
    "owner_activity": "Chrome owner activity detected",
    "selector_failed": "all selector fallbacks failed",
    "write_gate_missing": "live write gate missing",
}


def _parse_due(value: str, now: datetime) -> datetime:
    if not value:
        return now
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class QueueCyclePlan:
    """Pure gating decision for one cycle, shared by the sync and live paths.

    ``decisions`` is aligned 1:1 with the input queue order; each entry is either
    ``"process"`` (the item cleared every gate and should be executed) or ``"keep"``
    (left unchanged this cycle). ``stopped_reasons`` records why work was withheld.
    """

    stopped_reasons: tuple[str, ...]
    decisions: tuple[str, ...]


def plan_queue_cycle(
    queue: tuple[QueueItem, ...] | list[QueueItem],
    *,
    now_iso: str,
    chrome_connected: bool,
    portal_sessions: Mapping[Channel, bool] | None = None,
    owner_activity_detected: bool = False,
    stop_signal: str = "",
    max_items_per_cycle: int = 2,
) -> QueueCyclePlan:
    """Decide which queue items are eligible this cycle without any side effects.

    This isolates the gating logic so the synchronous ``run_queue_cycle`` (dry-run) and
    the asynchronous ``run_live_queue_cycle`` (live search) make identical decisions.
    """
    now = _parse_due(now_iso, datetime.now(timezone.utc))
    stopped: list[str] = []

    if owner_activity_detected:
        stopped.append(STOP_REASONS["owner_activity"])
    if stop_signal:
        stopped.append(STOP_REASONS.get(stop_signal, stop_signal))
    if not chrome_connected:
        stopped.append("Chrome CDP not connected; pending queue preserved for resume")
    global_stop = bool(stopped)

    decisions: list[str] = []
    processed = 0
    for item in queue:
        if item.status not in {"pending", "failed"}:
            decisions.append("keep")
            continue
        if processed >= max_items_per_cycle or global_stop:
            decisions.append("keep")
            continue
        if _parse_due(item.next_run_at, now) > now:
            decisions.append("keep")
            continue
        if not portal_session_ready(item.channel, portal_sessions):
            reason = portal_session_pending_reason(item.channel)
            if reason not in stopped:
                stopped.append(reason)
            decisions.append("keep")
            continue

        processed += 1
        decisions.append("process")

    return QueueCyclePlan(stopped_reasons=tuple(stopped), decisions=tuple(decisions))


def run_queue_cycle(
    queue: tuple[QueueItem, ...] | list[QueueItem],
    *,
    now_iso: str,
    chrome_connected: bool,
    portal_sessions: Mapping[Channel, bool] | None = None,
    owner_activity_detected: bool = False,
    stop_signal: str = "",
    max_items_per_cycle: int = 2,
) -> QueueCycleSummary:
    """Dry-run cycle: apply gates and mark eligible items done without searching.

    Behavior is unchanged from before the live-wiring refactor; the gating now lives in
    ``plan_queue_cycle`` and is shared with ``run_live_queue_cycle``.
    """
    plan = plan_queue_cycle(
        queue,
        now_iso=now_iso,
        chrome_connected=chrome_connected,
        portal_sessions=portal_sessions,
        owner_activity_detected=owner_activity_detected,
        stop_signal=stop_signal,
        max_items_per_cycle=max_items_per_cycle,
    )

    updated: list[QueueItem] = []
    searched_groups: list[str] = []
    for item, decision in zip(queue, plan.decisions):
        if decision == "process":
            searched_groups.append(item.group_id)
            updated.append(replace(item, status="done", attempts=item.attempts + 1, last_error=""))
        else:
            updated.append(item)

    return QueueCycleSummary(
        searched_groups=tuple(searched_groups),
        opened_profiles=0,
        saved_profiles=0,
        matched_profiles=0,
        stopped_reasons=plan.stopped_reasons,
        updated_items=tuple(updated),
        collected_cards=0,
    )


async def run_live_queue_cycle(
    queue: tuple[QueueItem, ...] | list[QueueItem],
    *,
    now_iso: str,
    execute_item: ExecuteItem,
    chrome_connected: bool,
    portal_sessions: Mapping[Channel, bool] | None = None,
    owner_activity_detected: bool = False,
    stop_signal: str = "",
    max_items_per_cycle: int = 2,
) -> QueueCycleSummary:
    """Live cycle: run each eligible item through ``execute_item`` and aggregate results.

    Gating is identical to ``run_queue_cycle``; the only difference is that eligible items
    are actually searched (via the injected adapter) instead of being assumed done.

    Item status mapping from ``ItemSearchResult.status``:
      - ``done``    -> item ``done`` (recorded in ``searched_groups``, attempts +1)
      - ``failed``  -> item ``failed`` (attempts +1, ``last_error`` carried)
      - ``stopped`` -> item left ``pending`` for resume (attempts unchanged); the
                       ``stop_reason`` is surfaced (reauth / pacing / owner activity)
    """
    plan = plan_queue_cycle(
        queue,
        now_iso=now_iso,
        chrome_connected=chrome_connected,
        portal_sessions=portal_sessions,
        owner_activity_detected=owner_activity_detected,
        stop_signal=stop_signal,
        max_items_per_cycle=max_items_per_cycle,
    )

    stopped: list[str] = list(plan.stopped_reasons)
    updated: list[QueueItem] = []
    searched_groups: list[str] = []
    opened_profiles = 0
    saved_profiles = 0
    matched_profiles = 0
    collected_cards = 0

    for item, decision in zip(queue, plan.decisions):
        if decision != "process":
            updated.append(item)
            continue

        result = await execute_item(item)
        collected_cards += result.collected_cards
        opened_profiles += result.opened_profiles
        saved_profiles += result.saved_profiles
        matched_profiles += result.matched_profiles

        if result.status == "done":
            searched_groups.append(item.group_id)
            updated.append(replace(item, status="done", attempts=item.attempts + 1, last_error=""))
        elif result.status == "failed":
            updated.append(
                replace(item, status="failed", attempts=item.attempts + 1, last_error=result.last_error)
            )
        else:  # "stopped": preserve for resume, do not burn the attempt.
            if result.stop_reason and result.stop_reason not in stopped:
                stopped.append(result.stop_reason)
            updated.append(item)

    return QueueCycleSummary(
        searched_groups=tuple(searched_groups),
        opened_profiles=opened_profiles,
        saved_profiles=saved_profiles,
        matched_profiles=matched_profiles,
        stopped_reasons=tuple(stopped),
        updated_items=tuple(updated),
        collected_cards=collected_cards,
    )
