"""Browser-preserving login session lifecycle coordinator (App 15)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from .session_guard import (
    KEEPALIVE_INTERVAL_SECONDS,
    load_safe_keepalive_target,
    run_safe_keepalive_episode,
)


def _result(
    state: str,
    *,
    last_verified_at: float | None,
    last_keepalive_at: float | None,
    restore_pending: bool = False,
    cleanup_pending: bool = False,
    resume_from: str = "",
    mutation_count: int = 0,
) -> dict[str, Any]:
    return {
        "state": state,
        "last_verified_at": last_verified_at,
        "last_keepalive_at": last_keepalive_at,
        "restore_pending": restore_pending,
        "cleanup_pending": cleanup_pending,
        "resume_from": resume_from,
        "mutation_count": mutation_count,
        "browser_close_count": 0,
    }


def coordinate_lifecycle(
    *,
    operation: str,
    site: str,
    now: float,
    last_verified_at: float | None = None,
    last_keepalive_at: float | None = None,
    safe_target_path: str | Path | None = None,
    safe_target: Any = None,
    job_id: str = "",
    target_id: str = "",
    expected_job_id: str = "",
    expected_target_id: str = "",
    lease_token: str = "",
    current_lease_token: str = "",
    owner_active: bool = False,
    agent: str = "fleet",
    keepalive_runner: Callable[..., Mapping[str, Any]] = run_safe_keepalive_episode,
    disconnect: Callable[[], Any] | None = None,
    release_lease: Callable[[], Any] | None = None,
    close_browser: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Coordinate one keepalive/resume/handoff without ever closing a browser.

    ``close_browser`` is deliberately accepted only as a forbidden-action spy; it
    is never invoked. The production runner already detaches its CDP WebSocket and
    releases its own lease, while injected callbacks make shutdown behavior
    mechanically testable at this boundary.
    """
    del close_browser
    if site not in KEEPALIVE_INTERVAL_SECONDS:
        raise ValueError("unsupported site")

    if operation == "resume":
        same = bool(
            job_id and target_id
            and job_id == expected_job_id
            and target_id == expected_target_id
        )
        return _result(
            "AUTHENTICATED" if same else "TARGET_CHANGED",
            last_verified_at=last_verified_at,
            last_keepalive_at=last_keepalive_at,
            resume_from="KEEPALIVE" if same else "DISCOVER",
        )

    should_release = bool(
        lease_token and current_lease_token and lease_token == current_lease_token)
    if operation == "handoff":
        try:
            return _result(
                "HANDOFF" if should_release else "LEASE_TOKEN_LOST",
                last_verified_at=last_verified_at,
                last_keepalive_at=last_keepalive_at,
                cleanup_pending=not should_release,
                resume_from="HANDOFF",
            )
        finally:
            if disconnect is not None:
                disconnect()
            if should_release and release_lease is not None:
                release_lease()

    if operation != "keepalive":
        raise ValueError("unsupported lifecycle operation")

    try:
        baseline = last_keepalive_at
        if baseline is None:
            baseline = last_verified_at
        if (
            baseline is None
            or now - baseline < KEEPALIVE_INTERVAL_SECONDS[site]
            or owner_active
        ):
            return _result(
                "KEEPALIVE_SKIPPED",
                last_verified_at=last_verified_at,
                last_keepalive_at=last_keepalive_at,
            )
        target = safe_target
        if target is None:
            if safe_target_path is None:
                return _result(
                    "KEEPALIVE_SKIPPED",
                    last_verified_at=last_verified_at,
                    last_keepalive_at=last_keepalive_at,
                )
            try:
                target = load_safe_keepalive_target(safe_target_path)
            except (OSError, ValueError):
                return _result(
                    "KEEPALIVE_SKIPPED",
                    last_verified_at=last_verified_at,
                    last_keepalive_at=last_keepalive_at,
                )
        outcome = dict(keepalive_runner(site, target, agent=agent))
        status = str(outcome.get("status") or "")
        if status in {"ok", "restored", "authenticated"}:
            state = "AUTHENTICATED"
        elif status in {"auth_required", "auth_lost"}:
            state = "AUTH_LOST"
        elif status == "target_changed":
            state = "TARGET_CHANGED"
        elif outcome.get("restore_pending"):
            state = "RESTORE_PENDING"
        elif outcome.get("cleanup_pending"):
            state = "CLEANUP_PENDING"
        else:
            state = "KEEPALIVE_SKIPPED"
        success = state == "AUTHENTICATED"
        return _result(
            state,
            last_verified_at=now if success else last_verified_at,
            last_keepalive_at=now if success else last_keepalive_at,
            restore_pending=bool(outcome.get("restore_pending")),
            cleanup_pending=bool(outcome.get("cleanup_pending")),
            resume_from="KEEPALIVE" if success else (
                "DISCOVER" if state == "TARGET_CHANGED" else ""),
            mutation_count=int(outcome.get("mutations") or 0),
        )
    finally:
        if disconnect is not None:
            disconnect()
        if should_release and release_lease is not None:
            release_lease()
