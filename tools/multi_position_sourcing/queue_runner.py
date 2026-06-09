from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone

from .models import Channel, QueueCycleSummary, QueueItem
from .portal_session import portal_session_pending_reason, portal_session_ready

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
    now = _parse_due(now_iso, datetime.now(timezone.utc))
    stopped: list[str] = []
    updated: list[QueueItem] = []
    searched_groups: list[str] = []

    if owner_activity_detected:
        stopped.append(STOP_REASONS["owner_activity"])
    if stop_signal:
        stopped.append(STOP_REASONS.get(stop_signal, stop_signal))
    if not chrome_connected:
        stopped.append("Chrome CDP not connected; pending queue preserved for resume")
    global_stop = bool(stopped)

    processed = 0
    for item in queue:
        if item.status not in {"pending", "failed"}:
            updated.append(item)
            continue
        if processed >= max_items_per_cycle or global_stop:
            updated.append(item)
            continue
        if _parse_due(item.next_run_at, now) > now:
            updated.append(item)
            continue
        if not portal_session_ready(item.channel, portal_sessions):
            reason = portal_session_pending_reason(item.channel)
            if reason not in stopped:
                stopped.append(reason)
            updated.append(item)
            continue

        processed += 1
        searched_groups.append(item.group_id)
        updated.append(
            replace(
                item,
                status="done",
                attempts=item.attempts + 1,
                last_error="",
            )
        )

    return QueueCycleSummary(
        searched_groups=tuple(searched_groups),
        opened_profiles=0,
        saved_profiles=0,
        matched_profiles=0,
        stopped_reasons=tuple(stopped),
        updated_items=tuple(updated),
    )
