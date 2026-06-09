from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .models import Channel

PORTAL_SESSION_REQUIRED_CHANNELS: tuple[Channel, ...] = ("saramin", "jobkorea", "linkedin_rps")


@dataclass(frozen=True)
class PortalSessionStatus:
    channel: Channel
    ready: bool
    reason: str
    source: str = ""


def portal_session_required(channel: Channel) -> bool:
    return channel in PORTAL_SESSION_REQUIRED_CHANNELS


def portal_session_ready(
    channel: Channel,
    portal_sessions: Mapping[Channel, bool] | None,
) -> bool:
    if not portal_session_required(channel):
        return True
    return bool(portal_sessions and portal_sessions.get(channel))


def portal_session_pending_reason(channel: Channel) -> str:
    return f"{channel} login session not confirmed; pending queue preserved for resume"


def portal_session_flags(statuses: Iterable[PortalSessionStatus]) -> dict[Channel, bool]:
    return {status.channel: status.ready for status in statuses}
