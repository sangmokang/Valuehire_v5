"""Cross-agent lease + owner-activity guard for exactly one browser mutation."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from .owner_activity import DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS

CENTRAL_HEARTBEAT_MAX_AGE_SECONDS = 30


def _decision(
    *, allowed: bool, state: str, token_matches: bool,
    idle_checks: list[dict[str, Any]], reason: str,
) -> dict[str, Any]:
    return {
        "allowed": allowed,
        "state": state,
        "token_matches": token_matches,
        "idle_checks": idle_checks,
        "reason": reason,
    }


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed


def _lease_valid(
    row: Any,
    *,
    lease_key: str,
    token: str,
    owner_pid: int,
    owner_job: str,
    now: datetime,
) -> tuple[bool, bool]:
    if not isinstance(row, Mapping):
        return False, False
    if now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
        return False, row.get("token") == token
    token_matches = row.get("token") == token
    heartbeat = _utc(row.get("heartbeat_at"))
    expires = _utc(row.get("expires_at"))
    valid = (
        row.get("lease_key") == lease_key
        and token_matches
        and row.get("owner_pid") == owner_pid
        and row.get("owner_job") == owner_job
        and row.get("released") is False
        and heartbeat is not None
        and expires is not None
        and 0 <= (now - heartbeat).total_seconds()
        <= CENTRAL_HEARTBEAT_MAX_AGE_SECONDS
        and expires > now
    )
    return valid, token_matches


def _idle_check(snapshot: Any) -> tuple[str, dict[str, Any]]:
    status = getattr(snapshot, "detection_status", "")
    portal = getattr(snapshot, "portal_site_active", None)
    idle = getattr(snapshot, "idle_seconds", None)
    foreground = str(getattr(snapshot, "foreground_app", "") or "").casefold()
    valid_idle = (
        not isinstance(idle, bool)
        and isinstance(idle, (int, float))
        and math.isfinite(float(idle))
        and float(idle) >= 0
    )
    if (
        status != "ok"
        or portal not in {True, False}
        or not valid_idle
        or (
            portal is True
            and "chrome" not in foreground
            and "chromium" not in foreground
        )
    ):
        return "OWNER_ACTIVITY_UNKNOWN", {
            "status": "UNKNOWN", "portal_active": None, "idle_bucket": "unknown",
        }
    if portal is True and float(idle) < DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS:
        return "HUMAN_ACTIVE", {
            "status": "HUMAN_ACTIVE", "portal_active": True, "idle_bucket": "<60",
        }
    return "", {
        "status": "CLEAR", "portal_active": portal,
        "idle_bucket": ">=60" if portal else "not_applicable",
    }


def guarded_mutation(
    *,
    lease_key: str,
    expected_token: str,
    local_lock: Any,
    central_lease_reader: Callable[[str], Any],
    owner_snapshot: Callable[[], Any],
    command: Callable[[], Any],
    now: Callable[[], datetime],
    sleep: Callable[[float], None] = time.sleep,
    machine: str,
    owner_pid: int,
    owner_job: str,
    request_id: str,
    delegated_for_request_id: str | None,
) -> dict[str, Any]:
    """Run command once only after local+central token and two idle proofs."""
    checks: list[dict[str, Any]] = []

    def blocked(reason: str, token_matches: bool = False) -> dict[str, Any]:
        return {
            "decision": _decision(
                allowed=False, state="BLOCKED", token_matches=token_matches,
                idle_checks=checks, reason=reason,
            ),
            "result": None,
            "mutation_count": 0,
        }

    if (
        not isinstance(lease_key, str)
        or not lease_key.startswith("login:")
        or not expected_token
        or machine == "winpc" and delegated_for_request_id != request_id
    ):
        return blocked("LEASE_CONFLICT")
    try:
        local_lock.assert_owned()
        first_lease = central_lease_reader(lease_key)
        current = now()
    except Exception:
        return blocked("LEASE_CONFLICT")
    first_valid, first_token = _lease_valid(
        first_lease, lease_key=lease_key, token=expected_token,
        owner_pid=owner_pid, owner_job=owner_job, now=current,
    )
    if not first_valid:
        return blocked("LEASE_CONFLICT", first_token)
    try:
        first_snapshot = owner_snapshot()
    except Exception:
        return blocked("OWNER_ACTIVITY_UNKNOWN", True)
    first_reason, first_check = _idle_check(first_snapshot)
    checks.append(first_check)
    if first_reason:
        return blocked(first_reason, True)

    sleep(1.0)
    try:
        local_lock.assert_owned()
        second_lease = central_lease_reader(lease_key)
        current = now()
    except Exception:
        return blocked("LEASE_TOKEN_LOST")
    second_valid, second_token = _lease_valid(
        second_lease, lease_key=lease_key, token=expected_token,
        owner_pid=owner_pid, owner_job=owner_job, now=current,
    )
    if not second_valid:
        return blocked("LEASE_TOKEN_LOST", second_token)
    try:
        second_snapshot = owner_snapshot()
    except Exception:
        return blocked("OWNER_ACTIVITY_UNKNOWN", True)
    second_reason, second_check = _idle_check(second_snapshot)
    checks.append(second_check)
    if second_reason:
        return blocked(second_reason, True)

    result = command()
    return {
        "decision": _decision(
            allowed=True, state="MUTATED", token_matches=True,
            idle_checks=checks, reason="ALLOWED",
        ),
        "result": result,
        "mutation_count": 1,
    }
