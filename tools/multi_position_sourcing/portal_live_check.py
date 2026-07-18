from __future__ import annotations

import argparse
import asyncio
import base64
import errno
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .access import portal_credential_status, resolve_portal_credentials
from .models import Channel
from .portal_autologin import auto_relogin_portal
from .portal_keychain import add_generic_password
from .portal_login import DEFAULT_ENV_FILE, load_env_file, ready_check_for_channel
from .portal_ops import (
    DEFAULT_PACING_POLICIES,
    DiscordWebhookNotifier,
    ReauthEvent,
    ReauthEventStore,
    ReauthWeeklyKey,
    SitePacingPolicy,
    SupabaseReauthEventStore,
)
from .portal_recovery import MacKeychainPortalCredentialProvider, PortalCredentials, RecoveryDecision
from .portal_runtime import GuardedPortalSearchRunner, GuardedSearchResult
from .portal_safety import safe_artifact_url, safe_exception_label
from .portal_snapshot import (
    EncryptedSessionSnapshot,
    MacKeychainSessionKeyProvider,
    OpenSslSessionEncryptor,
    PAYLOAD_VERSION,
    SupabaseRestConfig,
    SupabaseSessionSnapshotStore,
    capture_validated_snapshot,
    validate_snapshot_by_reinjection,
)
from .portal_worker import (
    DEFAULT_PROFILE_ROOT,
    PortalSearchAttempt,
    PortalWorker,
    PortalWorkerConfig,
    ProfileLockError,
    SearchLivenessMonitor,
    _close_page_if_possible,
    _lock_handle,
    _unlock_handle,
    resolve_chrome_cdp_endpoint,
    validate_portal_profile_root,
)

DEFAULT_LIVE_OUTPUT = "artifacts/portal_live_check_latest.json"
DEFAULT_ARTIFACT_ROOT = Path("artifacts")
DEFAULT_SUPABASE_SCHEMA_PATH = Path("docs/ai-search/session-state-supabase-schema-2026-06-09.sql")
PROFILE_RECOVERY_POLICY = "snapshot_only_no_auto_relogin"
PROOF_ARTIFACT_MAX_AGE = timedelta(hours=24)
DISCORD_WEBHOOK_KEYCHAIN_SERVICE = "valuehire.discord"
DISCORD_WEBHOOK_KEYCHAIN_ACCOUNT = "reauth_webhook_url"
PROTECTED_PORTAL_CHANNELS: tuple[Channel, ...] = ("saramin", "jobkorea", "linkedin_rps")
SNAPSHOT_RECOVERY_CHANNELS: tuple[Channel, ...] = ("saramin", "jobkorea")
REQUIRED_SUPABASE_SCHEMA_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "session_snapshot_table",
        (
            "create table if not exists public.session_state",
            "storage_state_enc bytea not null",
            "unique (site, worker_id, kind)",
        ),
    ),
    (
        "validated_snapshot_only_constraint",
        (
            "constraint session_state_validated_only_check",
            "check (is_validated = true)",
        ),
    ),
    (
        "encrypted_snapshot_envelope_constraint",
        (
            "constraint session_state_encrypted_envelope_check",
            "substring(storage_state_enc from 1 for 5) = decode('5648535331', 'hex')",
        ),
    ),
    (
        "reauth_events_table",
        (
            "create table if not exists public.reauth_events",
            "cause text not null",
            "recovered_by text not null",
            "occurred_at timestamptz not null",
        ),
    ),
    (
        "reauth_event_policy_constraints",
        (
            "recovered_by in ('snapshot_reinject', 'auto_relogin', 'human', 'unrecovered')",
            "constraint reauth_events_cause_allowed_check",
            "'profile_corrupt'",
            "'cookie_rotated'",
            "'forced_logout'",
            "'login_redirect'",
            "'login_marker_missing'",
            "'login_marker_lost'",
            "'unknown'",
            "cause ~ '^http_(401|403)$'",
        ),
    ),
    (
        "row_level_security_enabled",
        (
            "alter table public.session_state enable row level security",
            "alter table public.reauth_events enable row level security",
        ),
    ),
    (
        "public_anon_authenticated_revoked",
        (
            "revoke all on public.session_state from public, anon, authenticated",
            "revoke all on public.reauth_events from public, anon, authenticated",
        ),
    ),
    (
        "service_role_reauth_events_access",
        (
            "grant select, insert on public.reauth_events to service_role",
            "create policy service_role_reauth_events_all",
        ),
    ),
    (
        "service_role_snapshot_rpcs",
        (
            "grant execute on function public.save_validated_session_snapshot",
            "grant execute on function public.latest_validated_session_snapshot",
            "grant execute on function public.validated_session_snapshots",
            "to service_role",
        ),
    ),
    (
        "weekly_reauth_counts_rpc",
        (
            """
            create or replace function public.reauth_weekly_counts(
              week_start_arg timestamptz
            )
            returns table (
              site text,
              worker_id text,
              cause text,
              recovered_by text,
              count bigint
            )
            language sql
            security definer
            set search_path = public
            """,
            "count(*)::bigint as count",
            "group by re.site, re.worker_id, re.cause, re.recovered_by",
            "grant execute on function public.reauth_weekly_counts",
            "to service_role",
        ),
    ),
)


def utc_now_live_check() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class LiveSearchConfig:
    channel: Channel
    keyword: str
    worker_id: str
    profile_root: Path
    chrome_cdp_endpoint: str
    headless: bool
    searches_today: int
    no_sleep: bool
    disable_auto_relogin: bool
    delete_profile_before_start: bool
    confirm_delete_profile: str
    profile_only: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_root", validate_portal_profile_root(self.profile_root))


@dataclass(frozen=True)
class LiveSessionConfig:
    channel: Channel
    worker_id: str
    profile_root: Path
    chrome_cdp_endpoint: str
    headless: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_root", validate_portal_profile_root(self.profile_root))


@dataclass(frozen=True)
class LiveRestartSearchConfig:
    channel: Channel
    keyword: str
    worker_id: str
    profile_root: Path
    chrome_cdp_endpoint: str
    headless: bool
    searches_today: int
    no_sleep: bool
    disable_auto_relogin: bool
    timeout_seconds: int
    profile_only: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_root", validate_portal_profile_root(self.profile_root))


def safe_result_payload(
    result: GuardedSearchResult,
    *,
    profile_deleted_before_start: bool = False,
    snapshot_capture_required: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "site": result.site,
        "worker_id": result.worker_id,
        "keyword": result.keyword,
        "generated_at": utc_now_live_check(),
        "mode": "guarded",
        "status": result.status,
        "reason": result.reason,
        "attempt_status": "" if result.attempt is None else result.attempt.status,
        "attempt_reason": "" if result.attempt is None else result.attempt.reason,
        "url": "" if result.attempt is None else safe_artifact_url(result.attempt.url),
        "reauth_cause": result.reauth_cause or ("" if result.attempt is None else result.attempt.reauth_cause),
        "snapshot_capture_required": snapshot_capture_required,
        "snapshot_capture_policy": "required" if snapshot_capture_required else "skipped_profile_only",
        "snapshot_captured": result.snapshot_captured,
        "snapshot_kind": result.snapshot_kind or "",
        "retried_after_recovery": result.retried_after_recovery,
        "pause_site": result.pause_site,
        "skipped_due_to_cap": result.skipped_due_to_cap,
        "pacing_delay_seconds": round(result.pacing_delay_seconds, 3),
        "profile_deleted_before_start": profile_deleted_before_start,
        "result_count": len(result.candidate_cards),
        "results": [
            {
                "profile_url": safe_artifact_url(card.profile_url),
                "snippet": card.snippet,
                "source_channel": card.source_channel,
            }
            for card in result.candidate_cards
        ],
    }
    if result.recovery_decision is not None:
        payload["recovery"] = safe_recovery_payload(result.recovery_decision)
    return payload


def safe_profile_only_result_payload(
    attempt: PortalSearchAttempt,
    *,
    profile_deleted_before_start: bool = False,
    pacing_delay_seconds: float = 0.0,
) -> dict[str, object]:
    result = GuardedSearchResult(
        site=attempt.channel,
        worker_id=attempt.worker_id,
        keyword=attempt.keyword,
        status=attempt.status,
        reason=attempt.reason,
        attempt=attempt,
        reauth_cause=attempt.reauth_cause,
        pacing_delay_seconds=pacing_delay_seconds,
        candidate_cards=attempt.candidate_cards,
    )
    payload = safe_result_payload(
        result,
        profile_deleted_before_start=profile_deleted_before_start,
        snapshot_capture_required=False,
    )
    payload["mode"] = "profile_only"
    return payload


def safe_profile_only_pacing_blocked_payload(
    *,
    site: Channel,
    worker_id: str,
    keyword: str,
) -> dict[str, object]:
    result = GuardedSearchResult(
        site=site,
        worker_id=worker_id,
        keyword=keyword,
        status="pacing_blocked",
        reason="daily protected-portal search cap reached",
        skipped_due_to_cap=True,
    )
    payload = safe_result_payload(result, snapshot_capture_required=False)
    payload["mode"] = "profile_only"
    return payload


def safe_profile_lock_blocked_payload(
    *,
    site: Channel,
    worker_id: str,
    keyword: str,
    mode: str = "guarded",
    profile_deleted_before_start: bool = False,
    snapshot_capture_required: bool = True,
    pacing_delay_seconds: float = 0.0,
) -> dict[str, object]:
    attempt = PortalSearchAttempt(
        channel=site,
        worker_id=worker_id,
        keyword=keyword,
        status="not_ready",
        reason="profile_locked",
        url="",
        reauth_cause="",
    )
    result = GuardedSearchResult(
        site=site,
        worker_id=worker_id,
        keyword=keyword,
        status="not_ready",
        reason="profile_locked",
        attempt=attempt,
        pacing_delay_seconds=pacing_delay_seconds,
    )
    payload = safe_result_payload(
        result,
        profile_deleted_before_start=profile_deleted_before_start,
        snapshot_capture_required=snapshot_capture_required,
    )
    payload["mode"] = mode
    payload["profile_lock_blocked"] = True
    return payload


def safe_restart_smoke_payload(
    *,
    site: Channel,
    worker_id: str,
    keyword: str,
    first: dict[str, object],
    second: dict[str, object],
) -> dict[str, object]:
    mode = _restart_smoke_mode(first, second)
    return {
        "kind": "portal_restart_search_smoke",
        "site": site,
        "worker_id": worker_id,
        "keyword": keyword,
        "generated_at": utc_now_live_check(),
        "mode": mode,
        "snapshot_capture_policy": _restart_smoke_snapshot_policy(mode),
        "worker_restarts": 2,
        "passed": _is_clean_result_payload(first) and _is_clean_result_payload(second),
        "first": first,
        "second": second,
    }


def safe_restart_smoke_timeout_payload(
    *,
    site: Channel,
    worker_id: str,
    keyword: str,
    timeout_seconds: int,
    first: dict[str, object] | None = None,
    second: dict[str, object] | None = None,
) -> dict[str, object]:
    mode = _restart_smoke_mode(first, second)
    payload: dict[str, object] = {
        "kind": "portal_restart_search_smoke",
        "site": site,
        "worker_id": worker_id,
        "keyword": keyword,
        "generated_at": utc_now_live_check(),
        "mode": mode,
        "snapshot_capture_policy": _restart_smoke_snapshot_policy(mode),
        "worker_restarts": 2,
        "passed": False,
        "status": "timeout",
        "reason": "restart_smoke_timeout",
        "timeout_seconds": timeout_seconds,
    }
    if first is not None:
        payload["first"] = first
    if second is not None:
        payload["second"] = second
    return payload


def _restart_smoke_mode(first: dict[str, object] | None, second: dict[str, object] | None) -> str:
    modes = {
        str(payload.get("mode"))
        for payload in (first, second)
        if isinstance(payload, dict) and payload.get("mode")
    }
    if modes == {"profile_only"}:
        return "profile_only"
    if modes == {"guarded"}:
        return "guarded"
    if modes:
        return "mixed"
    return "guarded"


def _restart_smoke_snapshot_policy(mode: str) -> str:
    return "skipped_profile_only" if mode == "profile_only" else "required"


def safe_live_search_timeout_payload(
    *,
    site: Channel,
    worker_id: str,
    keyword: str,
    lifecycle: str,
    timeout_seconds: int,
) -> dict[str, object]:
    return {
        "site": site,
        "worker_id": worker_id,
        "keyword": keyword,
        "generated_at": utc_now_live_check(),
        "status": "timeout",
        "reason": "restart_smoke_lifecycle_timeout",
        "url": "",
        "reauth_cause": "",
        "snapshot_captured": False,
        "snapshot_kind": "",
        "retried_after_recovery": False,
        "pause_site": False,
        "skipped_due_to_cap": False,
        "pacing_delay_seconds": 0.0,
        "profile_deleted_before_start": False,
        "result_count": 0,
        "results": [],
        "lifecycle": lifecycle,
        "timeout_seconds": timeout_seconds,
    }


def safe_live_search_not_run_payload(
    *,
    site: Channel,
    worker_id: str,
    keyword: str,
    lifecycle: str,
    reason: str,
) -> dict[str, object]:
    return {
        "site": site,
        "worker_id": worker_id,
        "keyword": keyword,
        "generated_at": utc_now_live_check(),
        "status": "not_run",
        "reason": reason,
        "url": "",
        "reauth_cause": "",
        "snapshot_captured": False,
        "snapshot_kind": "",
        "retried_after_recovery": False,
        "pause_site": False,
        "skipped_due_to_cap": False,
        "pacing_delay_seconds": 0.0,
        "profile_deleted_before_start": False,
        "result_count": 0,
        "results": [],
        "lifecycle": lifecycle,
    }


def _is_clean_result_payload(payload: dict[str, object]) -> bool:
    return (
        payload.get("status") == "searched"
        and not payload.get("reauth_cause")
        and payload.get("retried_after_recovery") is not True
        and payload.get("profile_deleted_before_start") is not True
    )


def safe_recovery_payload(decision: RecoveryDecision) -> dict[str, object]:
    return {
        "recovered": decision.recovered,
        "recovered_by": decision.recovered_by,
        "reauth_event_recorded": decision.reauth_event_recorded,
        "pause_site": decision.pause_site,
        "discord_alert_sent": decision.discord_alert_sent,
    }


def safe_attempt_payload(attempt: PortalSearchAttempt) -> dict[str, object]:
    return {
        "site": attempt.channel,
        "worker_id": attempt.worker_id,
        "keyword": attempt.keyword,
        "status": attempt.status,
        "reason": attempt.reason,
        "url": safe_artifact_url(attempt.url),
        "reauth_cause": attempt.reauth_cause,
    }


def safe_snapshot_payload(
    record: EncryptedSessionSnapshot | None,
    *,
    site: Channel,
    worker_id: str,
    ready: bool,
    url: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "validated_session_snapshot",
        "site": site,
        "worker_id": worker_id,
        "generated_at": utc_now_live_check(),
        "ready": ready,
        "url": safe_artifact_url(url),
        "snapshot_captured": record is not None,
    }
    if record is None:
        payload["status"] = "not_captured"
        return payload
    payload.update(
        {
            "status": "captured",
            "snapshot_kind": record.kind,
            "is_validated": record.is_validated,
            "captured_at": record.captured_at,
            "updated_at": record.updated_at,
        }
    )
    return payload


def safe_snapshot_metadata_payload(
    record: EncryptedSessionSnapshot | None,
    *,
    site: Channel,
    worker_id: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "session_snapshot_metadata",
        "site": site,
        "worker_id": worker_id,
        "generated_at": utc_now_live_check(),
        "snapshot_present": record is not None,
    }
    if record is None:
        payload["status"] = "missing"
        return payload
    payload.update(
        {
            "status": "present",
            "snapshot_kind": record.kind,
            "is_validated": record.is_validated,
            "encrypted_envelope": PAYLOAD_VERSION.decode("ascii")
            if record.storage_state_enc.startswith(PAYLOAD_VERSION)
            else "unknown",
            "encrypted_bytes": len(record.storage_state_enc),
            "captured_at": record.captured_at,
            "updated_at": record.updated_at,
        }
    )
    return payload


def safe_weekly_counts_payload(
    counts: dict[ReauthWeeklyKey, int],
    *,
    week_start: str,
) -> dict[str, object]:
    rows = [
        {
            "site": site,
            "worker_id": worker_id,
            "cause": cause,
            "recovered_by": recovered_by,
            "count": count,
        }
        for (site, worker_id, cause, recovered_by), count in sorted(counts.items())
    ]
    return {
        "kind": "reauth_weekly_counts",
        "generated_at": utc_now_live_check(),
        "status": "present",
        "week_start": week_start,
        "total_events": sum(counts.values()),
        "rows": rows,
    }


def _safe_weekly_count_rows(rows: object) -> list[dict[str, object]]:
    if not isinstance(rows, list):
        return []
    safe_rows: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        count = _safe_nonnegative_int(row.get("count"))
        safe_rows.append(
            {
                "site": str(row.get("site") or ""),
                "worker_id": str(row.get("worker_id") or ""),
                "cause": str(row.get("cause") or ""),
                "recovered_by": str(row.get("recovered_by") or ""),
                "count": 0 if count is None else count,
            }
        )
    return safe_rows


def _safe_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) and value >= 0 else None


def safe_weekly_trend_payload(weekly_payloads: list[dict[str, object]]) -> dict[str, object]:
    weeks: list[dict[str, object]] = []
    totals: list[int | None] = []
    error_types: set[str] = set()
    for payload in weekly_payloads:
        status = str(payload.get("status") or "unavailable")
        total = _safe_nonnegative_int(payload.get("total_events"))
        week: dict[str, object] = {
            "week_start": str(payload.get("week_start") or ""),
            "status": status,
            "total_events": total if total is not None else 0,
            "rows": _safe_weekly_count_rows(payload.get("rows")),
        }
        error_type = payload.get("error_type")
        if isinstance(error_type, str) and error_type:
            week["error_type"] = error_type
            error_types.add(error_type)
        weeks.append(week)
        totals.append(total if status == "present" else None)

    present_totals = [total for total in totals if total is not None]
    latest_total = totals[-1] if totals else None
    previous_total = totals[-2] if len(totals) >= 2 else None
    delta = latest_total - previous_total if latest_total is not None and previous_total is not None else None
    return {
        "kind": "reauth_weekly_trend",
        "generated_at": utc_now_live_check(),
        "status": "present" if weekly_payloads and len(present_totals) == len(weekly_payloads) else "unavailable",
        "latest_week_start": weeks[-1]["week_start"] if weeks else "",
        "weeks_observed": len(weeks),
        "latest_total_events": latest_total if latest_total is not None else 0,
        "previous_total_events": previous_total if previous_total is not None else 0,
        "delta_from_previous_week": delta,
        "latest_week_zero": latest_total == 0 if latest_total is not None else False,
        "zero_event_weeks": sum(1 for total in present_totals if total == 0),
        "error_types": sorted(error_types),
        "weeks": weeks,
    }


def live_readiness_payload(
    env: dict[str, str] | None = None,
    *,
    session_key_available: Callable[[], bool] | None = None,
    portal_credentials_available: Callable[[Channel], bool] | None = None,
    playwright_available: Callable[[], bool] | None = None,
    supabase_access_payload: Callable[[dict[str, str]], dict[str, object]] | None = None,
    supabase_schema_payload: Callable[[], dict[str, object]] | None = None,
    pacing_policy_payload: Callable[[], dict[str, object]] | None = None,
) -> dict[str, object]:
    source = os.environ if env is None else env
    checks: list[dict[str, object]] = []

    def add_check(name: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "name": name,
                "status": "passed" if passed else "missing",
                "detail": detail,
            }
        )

    def add_supabase_access_check(payload: dict[str, object]) -> None:
        check: dict[str, object] = {
            "name": "supabase_access",
            "status": "passed" if payload.get("ready") is True else "failed",
            "detail": "Supabase service-role REST/RPC access is ready",
        }
        action_hint = payload.get("action_hint")
        if isinstance(action_hint, str) and action_hint:
            check["action_hint"] = action_hint
        checks.append(check)

    def add_supabase_schema_check(payload: dict[str, object]) -> None:
        check: dict[str, object] = {
            "name": "supabase_schema_proof",
            "status": "passed" if payload.get("ready") is True else "failed",
            "detail": "Supabase session schema migration contract includes encrypted snapshots, RLS, and reauth aggregates",
        }
        action_hint = payload.get("action_hint")
        if isinstance(action_hint, str) and action_hint:
            check["action_hint"] = action_hint
        failed_checks = payload.get("failed_checks")
        if isinstance(failed_checks, list) and failed_checks:
            check["failed_checks"] = [str(item) for item in failed_checks if isinstance(item, str)]
        checks.append(check)

    def add_pacing_policy_check(payload: dict[str, object]) -> None:
        check: dict[str, object] = {
            "name": "portal_pacing_policy",
            "status": "passed" if payload.get("ready") is True else "failed",
            "detail": "Protected portal pacing includes jittered search delays, page delays, and daily caps",
        }
        action_hint = payload.get("action_hint")
        if isinstance(action_hint, str) and action_hint:
            check["action_hint"] = action_hint
        failed_checks = payload.get("failed_checks")
        if isinstance(failed_checks, list) and failed_checks:
            check["failed_checks"] = [str(item) for item in failed_checks if isinstance(item, str)]
        checks.append(check)

    add_check(
        "supabase_url_env",
        bool(_first_env(source, ("SUPABASE_URL", "VALUEHIRE_SUPABASE_URL"))),
        "SUPABASE_URL or VALUEHIRE_SUPABASE_URL is configured",
    )
    add_check(
        "supabase_service_role_env",
        bool(_first_env(source, ("SUPABASE_SERVICE_ROLE_KEY", "VALUEHIRE_SUPABASE_SERVICE_ROLE_KEY"))),
        "SUPABASE_SERVICE_ROLE_KEY or VALUEHIRE_SUPABASE_SERVICE_ROLE_KEY is configured",
    )
    if supabase_access_payload is None:
        supabase_access_payload = supabase_access_check_payload
    add_supabase_access_check(supabase_access_payload(dict(source)))
    if supabase_schema_payload is None:
        supabase_schema_payload = supabase_schema_proof_payload
    add_supabase_schema_check(supabase_schema_payload())
    if pacing_policy_payload is None:
        pacing_policy_payload = pacing_policy_proof_payload
    add_pacing_policy_check(pacing_policy_payload())
    add_check(
        "discord_reauth_webhook_env",
        bool(discord_webhook_from_env(source)),
        "DISCORD_REAUTH_WEBHOOK_URL/VALUEHIRE_DISCORD_REAUTH_WEBHOOK_URL or macOS Keychain valuehire.discord/reauth_webhook_url is configured",
    )

    if playwright_available is None:
        playwright_available = lambda: importlib.util.find_spec("playwright.async_api") is not None
    add_check("playwright_available", playwright_available(), "playwright.async_api import target is available")

    if session_key_available is None:
        session_key_available = _session_key_available
    add_check(
        "mac_keychain_session_key",
        session_key_available(),
        "macOS Keychain valuehire.session_state/session_state_v2 exists and is decodable",
    )

    if portal_credentials_available is None:
        portal_credentials_available = _portal_credentials_available
    for site in PROTECTED_PORTAL_CHANNELS:
        add_check(
            f"{site}_keychain_credentials",
            portal_credentials_available(site),
            f"macOS Keychain valuehire.portal_credentials entries exist for {site}",
        )

    return {
        "kind": "portal_live_readiness",
        "generated_at": utc_now_live_check(),
        "ready": all(check["status"] == "passed" for check in checks),
        "checks": checks,
    }


def init_session_key_payload(
    *,
    session_key_available: Callable[[], bool] | None = None,
    key_provider: Any | None = None,
) -> dict[str, object]:
    existed_before = _session_key_available() if session_key_available is None else session_key_available()
    provider = key_provider if key_provider is not None else MacKeychainSessionKeyProvider(create_if_missing=True)
    try:
        provider.get_key()
    except Exception as exc:
        return {
            "kind": "portal_session_key_init",
            "generated_at": utc_now_live_check(),
            "status": "failed",
            "session_key_available": False,
            "created": False,
            "error_type": exc.__class__.__name__,
        }
    return {
        "kind": "portal_session_key_init",
        "generated_at": utc_now_live_check(),
        "status": "ready",
        "session_key_available": True,
        "created": not existed_before,
        "service": "valuehire.session_state",
        "account": "session_state_v2",
    }


def init_portal_credentials_payload(
    env: dict[str, str] | None = None,
    *,
    channels: tuple[Channel, ...] = PROTECTED_PORTAL_CHANNELS,
    credential_provider: Any | None = None,
) -> dict[str, object]:
    source = os.environ if env is None else env
    provider = credential_provider if credential_provider is not None else MacKeychainPortalCredentialProvider()
    env_status = portal_credential_status(source)
    rows: list[dict[str, object]] = []

    for site in channels:
        resolved = resolve_portal_credentials(site, source)
        status = env_status.get(site, {})
        if resolved is None:
            rows.append(
                {
                    "site": site,
                    "status": "missing_env",
                    "username_key": status.get("username_key", ""),
                    "password_key": status.get("password_key", ""),
                }
            )
            continue
        username, password = resolved
        try:
            provider.store(site, PortalCredentials(username=username, password=password))
        except Exception as exc:
            rows.append(
                {
                    "site": site,
                    "status": "failed",
                    "username_key": status.get("username_key", ""),
                    "password_key": status.get("password_key", ""),
                    "error_type": exc.__class__.__name__,
                }
            )
            continue
        rows.append(
            {
                "site": site,
                "status": "ready",
                "username_key": status.get("username_key", ""),
                "password_key": status.get("password_key", ""),
                "keychain_service": getattr(provider, "service", "valuehire.portal_credentials"),
                "keychain_accounts": [f"{site}:username", f"{site}:password"],
            }
        )

    return {
        "kind": "portal_credentials_init",
        "generated_at": utc_now_live_check(),
        "ready": all(row["status"] in {"ready", "skipped"} for row in rows),
        "rows": rows,
    }


def init_discord_webhook_payload(
    env: dict[str, str] | None = None,
    *,
    webhook_writer: Callable[[str], None] | None = None,
    keychain_reader: Callable[[], str] | None = None,
) -> dict[str, object]:
    source = os.environ if env is None else env
    webhook_url, env_key = _discord_webhook_from_env_value(source)
    if not webhook_url:
        reader = keychain_reader if keychain_reader is not None else _read_discord_webhook_keychain
        try:
            existing_webhook = reader()
        except Exception:
            existing_webhook = ""
        if existing_webhook:
            return {
                "kind": "discord_webhook_init",
                "generated_at": utc_now_live_check(),
                "ready": True,
                "status": "ready",
                "source": "keychain",
                "env_key": "",
                "keychain_service": DISCORD_WEBHOOK_KEYCHAIN_SERVICE,
                "keychain_account": DISCORD_WEBHOOK_KEYCHAIN_ACCOUNT,
            }
        return {
            "kind": "discord_webhook_init",
            "generated_at": utc_now_live_check(),
            "ready": False,
            "status": "missing_env",
            "source": "missing",
            "env_key": "",
            "keychain_service": DISCORD_WEBHOOK_KEYCHAIN_SERVICE,
            "keychain_account": DISCORD_WEBHOOK_KEYCHAIN_ACCOUNT,
        }
    writer = webhook_writer if webhook_writer is not None else _write_discord_webhook_keychain
    try:
        writer(webhook_url)
    except Exception as exc:
        return {
            "kind": "discord_webhook_init",
            "generated_at": utc_now_live_check(),
            "ready": False,
            "status": "failed",
            "source": "env",
            "env_key": env_key,
            "error_type": exc.__class__.__name__,
            "keychain_service": DISCORD_WEBHOOK_KEYCHAIN_SERVICE,
            "keychain_account": DISCORD_WEBHOOK_KEYCHAIN_ACCOUNT,
        }
    return {
        "kind": "discord_webhook_init",
        "generated_at": utc_now_live_check(),
        "ready": True,
        "status": "ready",
        "source": "env",
        "env_key": env_key,
        "keychain_service": DISCORD_WEBHOOK_KEYCHAIN_SERVICE,
        "keychain_account": DISCORD_WEBHOOK_KEYCHAIN_ACCOUNT,
    }


def supabase_config_from_env(env: dict[str, str] | None = None) -> SupabaseRestConfig:
    source = os.environ if env is None else env
    url = _first_env(source, ("SUPABASE_URL", "VALUEHIRE_SUPABASE_URL"))
    service_role_key = _first_env(
        source,
        ("SUPABASE_SERVICE_ROLE_KEY", "VALUEHIRE_SUPABASE_SERVICE_ROLE_KEY"),
    )
    if not url:
        raise RuntimeError("SUPABASE_URL or VALUEHIRE_SUPABASE_URL is required")
    if not service_role_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY or VALUEHIRE_SUPABASE_SERVICE_ROLE_KEY is required")
    return SupabaseRestConfig(url=url, service_role_key=service_role_key)


def supabase_access_check_payload(
    env: dict[str, str] | None = None,
    *,
    urlopen: Any = urllib.request.urlopen,
) -> dict[str, object]:
    try:
        config = supabase_config_from_env(env)
    except Exception as exc:
        return {
            "kind": "supabase_access_check",
            "generated_at": utc_now_live_check(),
            "ready": False,
            "checks": [
                {
                    "name": "supabase_config",
                    "status": "failed",
                    "error_type": exc.__class__.__name__,
                }
            ],
        }

    checks = [
        _supabase_probe_request(
            config=config,
            name="reauth_events_read",
            method="GET",
            path="/reauth_events?select=id&limit=1",
            payload=None,
            urlopen=urlopen,
        ),
        _supabase_probe_request(
            config=config,
            name="latest_snapshot_rpc",
            method="POST",
            path="/rpc/latest_validated_session_snapshot",
            payload={"site_arg": "saramin", "worker_id_arg": "__valuehire_access_probe__"},
            urlopen=urlopen,
        ),
        _supabase_probe_request(
            config=config,
            name="validated_snapshots_rpc",
            method="POST",
            path="/rpc/validated_session_snapshots",
            payload={"site_arg": "saramin", "worker_id_arg": "__valuehire_access_probe__"},
            urlopen=urlopen,
        ),
        _supabase_probe_request(
            config=config,
            name="reauth_weekly_counts_rpc",
            method="POST",
            path="/rpc/reauth_weekly_counts",
            payload={"week_start_arg": "1970-01-05T00:00:00+00:00"},
            urlopen=urlopen,
        ),
    ]
    key_diagnostics = _safe_supabase_key_diagnostics(config)
    return {
        "kind": "supabase_access_check",
        "generated_at": utc_now_live_check(),
        "ready": all(check["status"] == "passed" for check in checks),
        "key_diagnostics": key_diagnostics,
        "action_hint": _supabase_access_action_hint(checks, key_diagnostics),
        "checks": checks,
    }


def supabase_schema_proof_payload(schema_path: Path = DEFAULT_SUPABASE_SCHEMA_PATH) -> dict[str, object]:
    if not schema_path.exists():
        return {
            "kind": "supabase_session_schema_proof",
            "generated_at": utc_now_live_check(),
            "ready": False,
            "status": "missing",
            "schema_path": str(schema_path),
            "action_hint": "supabase_session_schema_file_missing",
            "checks": [],
            "failed_checks": ["schema_file"],
        }
    try:
        normalized_schema = _normalize_sql_for_schema_proof(schema_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return {
            "kind": "supabase_session_schema_proof",
            "generated_at": utc_now_live_check(),
            "ready": False,
            "status": "failed",
            "schema_path": str(schema_path),
            "action_hint": "supabase_session_schema_unreadable",
            "error_type": exc.__class__.__name__,
            "checks": [],
            "failed_checks": ["schema_file"],
        }

    checks = [
        {
            "name": name,
            "status": "passed" if _schema_markers_present(normalized_schema, markers) else "failed",
        }
        for name, markers in REQUIRED_SUPABASE_SCHEMA_MARKERS
    ]
    failed_checks = [str(check["name"]) for check in checks if check["status"] != "passed"]
    ready = not failed_checks
    return {
        "kind": "supabase_session_schema_proof",
        "generated_at": utc_now_live_check(),
        "ready": ready,
        "status": "ready" if ready else "failed",
        "schema_path": str(schema_path),
        "action_hint": "ready" if ready else "apply_supabase_session_schema",
        "checks": checks,
        "failed_checks": failed_checks,
    }


def pacing_policy_proof_payload(
    policies: dict[Channel, SitePacingPolicy] | None = None,
) -> dict[str, object]:
    policy_map = policies or DEFAULT_PACING_POLICIES
    checks: list[dict[str, object]] = []

    def add_check(name: str, passed: bool, *, site: str = "", detail: str = "") -> None:
        check: dict[str, object] = {
            "name": name,
            "status": "passed" if passed else "failed",
        }
        if site:
            check["site"] = site
        if detail:
            check["detail"] = detail
        checks.append(check)

    protected_present = all(channel in policy_map for channel in PROTECTED_PORTAL_CHANNELS)
    add_check(
        "protected_portal_policies_present",
        protected_present,
        detail="saramin, jobkorea, and linkedin_rps all have explicit pacing policies",
    )
    site_rows: list[dict[str, object]] = []
    for channel in PROTECTED_PORTAL_CHANNELS:
        policy = policy_map.get(channel)
        if policy is None:
            continue
        site_rows.append(
            {
                "site": channel,
                "min_search_delay_seconds": policy.min_search_delay_seconds,
                "max_search_delay_seconds": policy.max_search_delay_seconds,
                "min_page_delay_seconds": policy.min_page_delay_seconds,
                "max_page_delay_seconds": policy.max_page_delay_seconds,
                "daily_search_cap": policy.daily_search_cap,
            }
        )
        add_check(
            "search_delay_positive_range",
            policy.min_search_delay_seconds > 0
            and policy.max_search_delay_seconds >= policy.min_search_delay_seconds,
            site=channel,
        )
        add_check(
            "search_delay_jittered_not_fixed",
            policy.max_search_delay_seconds > policy.min_search_delay_seconds,
            site=channel,
        )
        add_check(
            "page_delay_positive_range",
            policy.min_page_delay_seconds > 0
            and policy.max_page_delay_seconds >= policy.min_page_delay_seconds,
            site=channel,
        )
        add_check(
            "page_delay_jittered_not_fixed",
            policy.max_page_delay_seconds > policy.min_page_delay_seconds,
            site=channel,
        )
        add_check("daily_search_cap_positive", policy.daily_search_cap > 0, site=channel)

    linkedin = policy_map.get("linkedin_rps")
    saramin = policy_map.get("saramin")
    jobkorea = policy_map.get("jobkorea")
    if linkedin is not None and saramin is not None and jobkorea is not None:
        add_check(
            "linkedin_daily_cap_conservative",
            linkedin.daily_search_cap <= min(saramin.daily_search_cap, jobkorea.daily_search_cap),
            site="linkedin_rps",
            detail="LinkedIn RPS cap must be no higher than Saramin/Jobkorea caps",
        )
        add_check(
            "linkedin_search_delay_conservative",
            linkedin.min_search_delay_seconds
            >= max(saramin.min_search_delay_seconds, jobkorea.min_search_delay_seconds),
            site="linkedin_rps",
            detail="LinkedIn RPS minimum search delay must be at least the other protected portals",
        )
        add_check(
            "linkedin_page_delay_conservative",
            linkedin.min_page_delay_seconds
            >= max(saramin.min_page_delay_seconds, jobkorea.min_page_delay_seconds),
            site="linkedin_rps",
            detail="LinkedIn RPS minimum page delay must be at least the other protected portals",
        )

    failed_checks = [
        f"{check.get('site') + ':' if check.get('site') else ''}{check['name']}"
        for check in checks
        if check["status"] != "passed"
    ]
    ready = not failed_checks
    return {
        "kind": "portal_pacing_policy_proof",
        "generated_at": utc_now_live_check(),
        "ready": ready,
        "status": "ready" if ready else "failed",
        "action_hint": "ready" if ready else "fix_portal_pacing_policy",
        "sites": site_rows,
        "checks": checks,
        "failed_checks": failed_checks,
    }


def _normalize_sql_for_schema_proof(sql: str) -> str:
    return " ".join(sql.lower().split())


def _schema_markers_present(normalized_schema: str, markers: tuple[str, ...]) -> bool:
    return all(_normalize_sql_for_schema_proof(marker) in normalized_schema for marker in markers)


def _safe_supabase_key_diagnostics(config: SupabaseRestConfig) -> dict[str, object]:
    parsed_url = urllib.parse.urlparse(config.url)
    host = parsed_url.hostname or ""
    url_project_ref = host.split(".", 1)[0] if host.endswith(".supabase.co") else ""
    diagnostics: dict[str, object] = {
        "configured": bool(config.service_role_key),
        "format": "missing",
        "role_claim": "unknown",
        "expired": "unknown",
        "url_host_is_supabase": bool(url_project_ref),
        "url_key_ref_match": "unknown",
        "project_ref_claim_source": "unknown",
    }
    if not config.service_role_key:
        return diagnostics
    if config.service_role_key.count(".") < 2:
        diagnostics["format"] = "non_jwt_or_new_secret"
        diagnostics["project_ref_claim_source"] = "not_applicable"
        return diagnostics

    diagnostics["format"] = "jwt"
    try:
        payload_segment = config.service_role_key.split(".", 2)[1]
        payload_segment += "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_segment.encode("ascii")))
    except Exception:
        diagnostics["role_claim"] = "decode_error"
        return diagnostics
    if not isinstance(payload, dict):
        return diagnostics

    role = payload.get("role")
    diagnostics["role_claim"] = role if role in {"service_role", "anon", "authenticated"} else "other_or_missing"
    exp = payload.get("exp")
    if isinstance(exp, int):
        diagnostics["expired"] = exp < int(time.time())
    ref, ref_source = _safe_supabase_jwt_project_ref(payload)
    diagnostics["project_ref_claim_source"] = ref_source
    if isinstance(ref, str) and url_project_ref:
        diagnostics["url_key_ref_match"] = "passed" if ref == url_project_ref else "failed"
    elif url_project_ref:
        diagnostics["url_key_ref_match"] = "not_embedded"
    return diagnostics


def _safe_supabase_jwt_project_ref(payload: dict[str, object]) -> tuple[str | None, str]:
    ref = payload.get("ref")
    if isinstance(ref, str) and ref:
        return ref, "ref"
    iss = payload.get("iss")
    if isinstance(iss, str):
        parsed = urllib.parse.urlparse(iss)
        host = parsed.hostname or ""
        if host.endswith(".supabase.co"):
            return host.split(".", 1)[0], "iss"
    return None, "none"


def _supabase_access_action_hint(
    checks: list[dict[str, object]],
    key_diagnostics: dict[str, object],
) -> str:
    hints = {
        str(check.get("http_error_hint"))
        for check in checks
        if check.get("status") == "failed" and check.get("http_error_hint")
    }
    if not hints:
        return "ready"
    if "jwt_expired" in hints or key_diagnostics.get("expired") is True:
        return "replace_expired_service_role_key"
    if key_diagnostics.get("role_claim") not in {"service_role", "unknown"}:
        return "replace_with_service_role_key"
    if key_diagnostics.get("url_key_ref_match") == "failed":
        return "supabase_url_and_service_role_key_project_mismatch"
    if "invalid_jwt_signature_or_project_mismatch" in hints:
        return "replace_service_role_key_for_configured_project"
    if "invalid_api_key" in hints:
        return "configured_service_role_key_rejected_by_supabase"
    if "schema_or_rpc_missing" in hints:
        return "apply_session_state_supabase_schema"
    if "permission_denied" in hints:
        return "apply_session_state_schema_or_service_role_policies"
    if "unauthorized_unclassified" in hints:
        return "supabase_authorization_failed"
    return "check_supabase_access_artifact"


def _supabase_probe_request(
    *,
    config: SupabaseRestConfig,
    name: str,
    method: str,
    path: str,
    payload: dict[str, object] | None,
    urlopen: Any,
) -> dict[str, object]:
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        config.rest_url + path,
        data=body,
        headers=config.headers(),
        method=method,
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            status = int(getattr(response, "status", 0) or 0)
            response.read()
    except urllib.error.HTTPError as exc:
        http_error_hint = _classify_supabase_http_error(exc)
        exc.close()
        return {
            "name": name,
            "status": "failed",
            "http_status": exc.code,
            "error_type": "HTTPError",
            "http_error_hint": http_error_hint,
        }
    except Exception as exc:
        return {
            "name": name,
            "status": "failed",
            "http_status": 0,
            "error_type": exc.__class__.__name__,
        }
    return {
        "name": name,
        "status": "passed" if 200 <= status < 300 else "failed",
        "http_status": status,
    }


def _classify_supabase_http_error(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(4096)
    except Exception:
        raw = b""
    try:
        body = raw.decode("utf-8", errors="ignore").lower()
    except Exception:
        body = ""
    reason = str(getattr(exc, "reason", "")).lower()
    haystack = f"{reason} {body}"
    if "jwserror" in haystack or "jwsinvalidsignature" in haystack or "invalid signature" in haystack:
        return "invalid_jwt_signature_or_project_mismatch"
    if "jwt expired" in haystack or ("expired" in haystack and "jwt" in haystack):
        return "jwt_expired"
    if "invalid api key" in haystack or "invalidapikey" in haystack:
        return "invalid_api_key"
    if exc.code == 404:
        return "schema_or_rpc_missing"
    if "permission denied" in haystack or "insufficient" in haystack:
        return "permission_denied"
    if exc.code == 401:
        return "unauthorized_unclassified"
    return "http_error_unclassified"


def discord_webhook_from_env(
    env: dict[str, str] | None = None,
    *,
    keychain_reader: Callable[[], str] | None = None,
) -> str:
    source = os.environ if env is None else env
    webhook_url, _env_key = _discord_webhook_from_env_value(source)
    if webhook_url:
        return webhook_url
    reader = keychain_reader if keychain_reader is not None else _read_discord_webhook_keychain
    try:
        return reader()
    except Exception:
        return ""


async def run_live_search(config: LiveSearchConfig) -> dict[str, object]:
    if config.profile_only:
        return await run_profile_only_live_search(config)

    supabase_config = supabase_config_from_env()
    encryptor = OpenSslSessionEncryptor(MacKeychainSessionKeyProvider())
    snapshot_store = SupabaseSessionSnapshotStore(supabase_config)
    event_store = SupabaseReauthEventStore(supabase_config)
    discord_webhook_url = discord_webhook_from_env()
    discord_notifier = (
        DiscordWebhookNotifier(discord_webhook_url)
        if discord_webhook_url
        else None
    )
    credential_provider = None
    auto_relogin = None
    if config.channel in PROTECTED_PORTAL_CHANNELS and not config.disable_auto_relogin:
        credential_provider = MacKeychainPortalCredentialProvider()
        auto_relogin = auto_relogin_portal

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("playwright is required for portal live check") from exc

    worker_config = PortalWorkerConfig(
        channel=config.channel,
        worker_id=config.worker_id,
        profile_root=config.profile_root,
        mode="headed" if config.channel == "linkedin_rps" else ("headless" if config.headless else "headed"),
        chrome_cdp_endpoint=config.chrome_cdp_endpoint,
    )
    profile_deleted = delete_profile_dir_if_confirmed(
        worker_config.profile_dir,
        enabled=config.delete_profile_before_start,
        confirm=config.confirm_delete_profile,
    )
    ready_check = ready_check_for_channel(config.channel)

    async with async_playwright() as playwright:
        try:
            async with PortalWorker(worker_config, playwright=playwright) as worker:
                runner = GuardedPortalSearchRunner(
                    worker=worker,
                    encryptor=encryptor,
                    snapshot_store=snapshot_store,
                    event_store=event_store,
                    snapshot_validator=lambda state: validate_snapshot_by_reinjection(
                        playwright=playwright,
                        site=config.channel,
                        state=state,
                        ready_check=ready_check,
                        browser=worker.browser if config.channel == "linkedin_rps" else None,
                    ),
                    ready_check=ready_check,
                    credential_provider=credential_provider,
                    auto_relogin=auto_relogin,
                    discord_notifier=discord_notifier,
                    sleep=None if config.no_sleep else asyncio.sleep,
                )
                result = await runner.run_keyword_search(
                    config.keyword,
                    searches_today=config.searches_today,
                    reauth_cause_override="profile_corrupt" if profile_deleted else "",
                )
        except ProfileLockError:
            return safe_profile_lock_blocked_payload(
                site=config.channel,
                worker_id=config.worker_id,
                keyword=config.keyword,
                mode="guarded",
                profile_deleted_before_start=profile_deleted,
                snapshot_capture_required=True,
            )
    return safe_result_payload(result, profile_deleted_before_start=profile_deleted)


async def run_profile_only_live_search(config: LiveSearchConfig) -> dict[str, object]:
    pacing_delay_seconds = await _apply_profile_only_pacing(config)
    if pacing_delay_seconds < 0:
        return safe_profile_only_pacing_blocked_payload(
            site=config.channel,
            worker_id=config.worker_id,
            keyword=config.keyword,
        )

    worker_config = PortalWorkerConfig(
        channel=config.channel,
        worker_id=config.worker_id,
        profile_root=config.profile_root,
        mode="headed" if config.channel == "linkedin_rps" else ("headless" if config.headless else "headed"),
        chrome_cdp_endpoint=config.chrome_cdp_endpoint,
        connection_mode="raw_single_tab",
    )
    profile_deleted = delete_profile_dir_if_confirmed(
        worker_config.profile_dir,
        enabled=config.delete_profile_before_start,
        confirm=config.confirm_delete_profile,
    )
    ready_check = ready_check_for_channel(config.channel)
    try:
        async with PortalWorker(worker_config) as worker:
            attempt = await worker.run_one_search(
                config.keyword,
                ready_check=ready_check,
                monitor=SearchLivenessMonitor(config.channel),
            )
    except ProfileLockError:
        return safe_profile_lock_blocked_payload(
            site=config.channel,
            worker_id=config.worker_id,
            keyword=config.keyword,
            mode="profile_only",
            profile_deleted_before_start=profile_deleted,
            snapshot_capture_required=False,
            pacing_delay_seconds=pacing_delay_seconds,
        )
    return safe_profile_only_result_payload(
        attempt,
        profile_deleted_before_start=profile_deleted,
        pacing_delay_seconds=pacing_delay_seconds,
    )


async def _apply_profile_only_pacing(config: LiveSearchConfig) -> float:
    policy = DEFAULT_PACING_POLICIES.get(config.channel)
    if policy is None:
        return 0.0
    if not policy.can_start_search(searches_today=config.searches_today):
        return -1.0
    delay_seconds = policy.next_search_delay_seconds()
    if not config.no_sleep:
        await asyncio.sleep(delay_seconds)
    return delay_seconds


async def run_restart_search_smoke(config: LiveRestartSearchConfig) -> dict[str, object]:
    base = LiveSearchConfig(
        channel=config.channel,
        keyword=config.keyword,
        worker_id=config.worker_id,
        profile_root=config.profile_root,
        chrome_cdp_endpoint=config.chrome_cdp_endpoint,
        headless=config.headless,
        searches_today=config.searches_today,
        no_sleep=config.no_sleep,
        disable_auto_relogin=config.disable_auto_relogin,
        delete_profile_before_start=False,
        confirm_delete_profile="",
        profile_only=config.profile_only,
    )
    first = await _run_restart_lifecycle(config, base, lifecycle="first")
    if not _is_clean_result_payload(first):
        second = safe_live_search_not_run_payload(
            site=config.channel,
            worker_id=config.worker_id,
            keyword=config.keyword,
            lifecycle="second",
            reason="first_lifecycle_not_clean",
        )
        if first.get("status") == "timeout":
            return safe_restart_smoke_timeout_payload(
                site=config.channel,
                worker_id=config.worker_id,
                keyword=config.keyword,
                timeout_seconds=config.timeout_seconds,
                first=first,
                second=second,
            )
        return safe_restart_smoke_payload(
            site=config.channel,
            worker_id=config.worker_id,
            keyword=config.keyword,
            first=first,
            second=second,
        )
    second_base = replace(base, searches_today=config.searches_today + 1)
    second = await _run_restart_lifecycle(config, second_base, lifecycle="second")
    if second.get("status") == "timeout":
        return safe_restart_smoke_timeout_payload(
            site=config.channel,
            worker_id=config.worker_id,
            keyword=config.keyword,
            timeout_seconds=config.timeout_seconds,
            first=first,
            second=second,
        )
    return safe_restart_smoke_payload(
        site=config.channel,
        worker_id=config.worker_id,
        keyword=config.keyword,
        first=first,
        second=second,
    )


def profile_recovery_search_config(config: LiveSearchConfig) -> LiveSearchConfig:
    if config.channel not in {"saramin", "jobkorea"}:
        raise ValueError("profile recovery smoke is supported only for saramin and jobkorea")
    return replace(
        config,
        disable_auto_relogin=True,
        delete_profile_before_start=True,
        profile_only=False,
    )


async def run_profile_recovery_smoke(config: LiveSearchConfig) -> dict[str, object]:
    recovery_config = profile_recovery_search_config(config)
    metadata = snapshot_metadata_payload(channel=recovery_config.channel, worker_id=recovery_config.worker_id)
    if not profile_recovery_snapshot_ready(metadata):
        return safe_profile_recovery_not_run_payload(recovery_config, metadata=metadata)
    payload = await run_live_search(recovery_config)
    return _profile_recovery_smoke_payload(payload)


def _profile_recovery_smoke_payload(payload: dict[str, object]) -> dict[str, object]:
    enriched = dict(payload)
    enriched["kind"] = "portal_profile_recovery_smoke"
    enriched["recovery_policy"] = PROFILE_RECOVERY_POLICY
    enriched["auto_relogin_disabled"] = True
    return enriched


async def _run_restart_lifecycle(
    config: LiveRestartSearchConfig,
    search_config: LiveSearchConfig,
    *,
    lifecycle: str,
) -> dict[str, object]:
    try:
        return await asyncio.wait_for(
            run_live_search(search_config),
            timeout=config.timeout_seconds,
        )
    except TimeoutError:
        return safe_live_search_timeout_payload(
            site=config.channel,
            worker_id=config.worker_id,
            keyword=config.keyword,
            lifecycle=lifecycle,
            timeout_seconds=config.timeout_seconds,
        )


async def capture_live_snapshot(config: LiveSessionConfig) -> dict[str, object]:
    supabase_config = supabase_config_from_env()
    encryptor = OpenSslSessionEncryptor(MacKeychainSessionKeyProvider())
    snapshot_store = SupabaseSessionSnapshotStore(supabase_config)
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("playwright is required for portal live snapshot capture") from exc

    worker_config = PortalWorkerConfig(
        channel=config.channel,
        worker_id=config.worker_id,
        profile_root=config.profile_root,
        mode="headed" if config.channel == "linkedin_rps" else ("headless" if config.headless else "headed"),
        chrome_cdp_endpoint=config.chrome_cdp_endpoint,
    )
    ready_check = ready_check_for_channel(config.channel)

    async with async_playwright() as playwright:
        async with PortalWorker(worker_config, playwright=playwright) as worker:
            page = await worker.context.new_page()
            try:
                ready = await ready_check(page)
                if not ready:
                    return safe_snapshot_payload(
                        None,
                        site=config.channel,
                        worker_id=config.worker_id,
                        ready=False,
                        url=getattr(page, "url", ""),
                    )
                record = await capture_validated_snapshot(
                    context=worker.context,
                    site=config.channel,
                    worker_id=config.worker_id,
                    encryptor=encryptor,
                    store=snapshot_store,
                    validator=lambda state: validate_snapshot_by_reinjection(
                        playwright=playwright,
                        site=config.channel,
                        state=state,
                        ready_check=ready_check,
                        browser=worker.browser if config.channel == "linkedin_rps" else None,
                    ),
                )
                return safe_snapshot_payload(
                    record,
                    site=config.channel,
                    worker_id=config.worker_id,
                    ready=True,
                    url=getattr(page, "url", ""),
                )
            finally:
                await _close_page_if_possible(page)


def weekly_reauth_counts_payload(
    *,
    week_start: str,
    store: Any | None = None,
) -> dict[str, object]:
    try:
        event_store = store if store is not None else SupabaseReauthEventStore(supabase_config_from_env())
        payload = safe_weekly_counts_payload(event_store.weekly_counts(week_start=week_start), week_start=week_start)
    except Exception as exc:
        return {
            "kind": "reauth_weekly_counts",
            "generated_at": utc_now_live_check(),
            "status": "unavailable",
            "week_start": week_start,
            "total_events": 0,
            "rows": [],
            "error_type": exc.__class__.__name__,
        }
    payload["status"] = "present"
    return payload


def reauth_weekly_trend_payload(
    *,
    latest_week_start: str,
    weeks: int,
    store: Any | None = None,
) -> dict[str, object]:
    if weeks < 1 or weeks > 26:
        raise ValueError("weeks must be between 1 and 26")
    try:
        latest = _parse_week_start_date(latest_week_start)
        event_store = store if store is not None else SupabaseReauthEventStore(supabase_config_from_env())
        payloads = [
            weekly_reauth_counts_payload(
                week_start=(latest - timedelta(days=7 * offset)).isoformat(),
                store=event_store,
            )
            for offset in reversed(range(weeks))
        ]
        return safe_weekly_trend_payload(payloads)
    except Exception as exc:
        return {
            "kind": "reauth_weekly_trend",
            "generated_at": utc_now_live_check(),
            "status": "unavailable",
            "latest_week_start": latest_week_start,
            "weeks_observed": 0,
            "latest_total_events": 0,
            "previous_total_events": 0,
            "delta_from_previous_week": None,
            "latest_week_zero": False,
            "zero_event_weeks": 0,
            "weeks": [],
            "error_type": exc.__class__.__name__,
        }


def _parse_week_start_date(week_start: str) -> date:
    if "T" in week_start:
        return datetime.fromisoformat(week_start.replace("Z", "+00:00")).date()
    return date.fromisoformat(week_start)


def current_utc_week_start(today: date | None = None) -> str:
    current = today or datetime.now(timezone.utc).date()
    monday = current - timedelta(days=current.weekday())
    return monday.isoformat()


def refresh_dod_status_artifacts(
    *,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    worker_id: str = "default",
    week_start: str = "",
    keyword: str = "snapshot-precheck",
    profile_root: Path = DEFAULT_PROFILE_ROOT,
) -> dict[str, object]:
    week = week_start or current_utc_week_start()
    artifacts: list[dict[str, object]] = []
    artifact_payloads: dict[str, dict[str, object]] = {}

    def write(name: str, path: Path, payload: dict[str, object]) -> None:
        _write_json_artifact(path, payload)
        record(name, path, payload)

    def record(name: str, path: Path, payload: dict[str, object]) -> None:
        artifact_payloads[name] = payload
        artifacts.append(
            {
                "name": name,
                "path": str(path),
                "status": _dod_refresh_status(name, payload),
            }
        )

    write("readiness", artifact_root / "portal_live_readiness_latest.json", live_readiness_payload())
    write("supabase_access", artifact_root / "portal_supabase_access_latest.json", supabase_access_check_payload())
    write(
        "supabase_schema_proof",
        artifact_root / "portal_supabase_schema_proof_latest.json",
        supabase_schema_proof_payload(),
    )
    write(
        "pacing_policy_proof",
        artifact_root / "portal_pacing_policy_proof_latest.json",
        pacing_policy_proof_payload(),
    )
    write(
        "artifact_profile_precheck",
        artifact_root / "portal_artifact_profile_precheck_latest.json",
        artifact_profile_precheck_payload(artifact_root),
    )
    write(
        "portal_session_preflight_status",
        artifact_root / "portal_session_preflight_status_latest.json",
        portal_session_preflight_status_payload(artifact_root / "portal_session_status_latest.json"),
    )
    write(
        "restart_smoke_proof",
        artifact_root / "portal_restart_smoke_proof_status_latest.json",
        restart_smoke_proof_status_payload(artifact_root),
    )
    discord_alert_path = artifact_root / "portal_discord_alert_test_latest.json"
    existing_discord_alert = _read_json_artifact_if_present(discord_alert_path)
    if _is_complete_discord_alert_artifact(existing_discord_alert):
        record("discord_alert_precheck", discord_alert_path, existing_discord_alert)
    elif not discord_webhook_from_env():
        write("discord_alert_precheck", discord_alert_path, missing_discord_alert_webhook_payload())
    elif isinstance(existing_discord_alert, dict) and existing_discord_alert.get("kind") == "discord_alert_test":
        record("discord_alert_precheck", discord_alert_path, existing_discord_alert)
    else:
        write("discord_alert_precheck", discord_alert_path, discord_alert_test_not_run_payload())
    for channel in ("saramin", "jobkorea", "linkedin_rps"):
        metadata = snapshot_metadata_payload(channel=channel, worker_id=worker_id)
        write(
            f"snapshot_metadata_{channel}",
            artifact_root / f"portal_snapshot_metadata_{channel}.json",
            metadata,
        )
        if channel in SNAPSHOT_RECOVERY_CHANNELS and not profile_recovery_snapshot_ready(metadata):
            write(
                f"profile_recovery_precheck_{channel}",
                artifact_root / f"portal_profile_recovery_{channel}.json",
                safe_profile_recovery_not_run_payload(
                    LiveSearchConfig(
                        channel=channel,
                        keyword=keyword,
                        worker_id=worker_id,
                        profile_root=profile_root,
                        chrome_cdp_endpoint="",
                        headless=False,
                        searches_today=0,
                        no_sleep=True,
                        disable_auto_relogin=True,
                        delete_profile_before_start=True,
                        confirm_delete_profile="",
                    ),
                    metadata=metadata,
                ),
            )
    write(
        "profile_recovery_proof",
        artifact_root / "portal_profile_recovery_proof_status_latest.json",
        profile_recovery_proof_status_payload(artifact_root),
    )
    write(
        "reauth_weekly_counts",
        artifact_root / "portal_reauth_weekly_counts_latest.json",
        weekly_reauth_counts_payload(week_start=week),
    )
    write(
        "reauth_weekly_trend",
        artifact_root / "portal_reauth_weekly_trend_latest.json",
        reauth_weekly_trend_payload(latest_week_start=week, weeks=4),
    )
    blocker_summary = dod_refresh_blocker_summary(
        artifacts,
        artifact_payloads,
        artifact_root=artifact_root,
        worker_id=worker_id,
        week_start=week,
        keyword=keyword,
        profile_root=profile_root,
    )

    return {
        "kind": "portal_dod_status_artifact_refresh",
        "generated_at": utc_now_live_check(),
        "ready": all(item["status"] == "ready" for item in artifacts),
        "artifact_root": str(artifact_root),
        "worker_id": worker_id,
        "week_start": week,
        "artifacts": artifacts,
        "blocking_reasons": blocker_summary["blocking_reasons"],
        "action_items": blocker_summary["action_items"],
        "dod_blockers": blocker_summary["dod_blockers"],
        "skipped_live_artifacts": [
            "restart-smoke",
            "profile-recovery-smoke",
            "discord-alert-test",
        ],
    }


def dod_refresh_blocker_summary(
    artifacts: list[dict[str, object]],
    artifact_payloads: dict[str, dict[str, object]],
    *,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    worker_id: str = "default",
    week_start: str = "",
    keyword: str = "snapshot-precheck",
    profile_root: Path = DEFAULT_PROFILE_ROOT,
) -> dict[str, list[dict[str, object]]]:
    reasons: list[dict[str, object]] = []
    action_items: list[dict[str, object]] = []
    action_by_name: dict[str, dict[str, object]] = {}

    def add_action(area: str, action: str, *, status: str, action_hint: str = "") -> None:
        existing = action_by_name.get(action)
        if existing is not None:
            sources = existing.setdefault("sources", [])
            if isinstance(sources, list) and area not in sources:
                sources.append(area)
            if existing.get("status") == "not_ready" and status != "not_ready":
                existing["status"] = status
            if action_hint and not existing.get("action_hint"):
                existing["action_hint"] = action_hint
            return
        item: dict[str, object] = {
            "area": area,
            "action": action,
            "status": status,
            "sources": [area],
        }
        if action_hint:
            item["action_hint"] = action_hint
        command_hints = _command_hints_for_action(
            action,
            artifact_root=artifact_root,
            worker_id=worker_id,
            week_start=week_start,
            keyword=keyword,
            profile_root=profile_root,
        )
        if command_hints:
            item["commands"] = list(command_hints)
        blocks_dod = _dod_ids_blocked_by_action(action)
        if blocks_dod:
            item["blocks_dod"] = list(blocks_dod)
        action_by_name[action] = item
        action_items.append(item)

    for artifact in artifacts:
        name = str(artifact.get("name") or "")
        status = str(artifact.get("status") or "unknown")
        if status == "ready":
            continue
        reason: dict[str, object] = {"name": name, "status": status}
        payload = artifact_payloads.get(name, {})
        if name == "readiness":
            failed_checks = _failed_readiness_check_names(payload)
            reason["failed_checks"] = failed_checks
            for check_name in failed_checks:
                add_action(
                    _readiness_action_area(check_name),
                    _readiness_action_for_check(check_name),
                    status=status,
                    action_hint=_readiness_action_hint(payload, check_name),
                )
        elif name == "supabase_access":
            action_hint = str(payload.get("action_hint") or "")
            if action_hint:
                reason["action_hint"] = action_hint
            add_action(
                "supabase_access",
                "fix_supabase_service_role_schema_or_key",
                status=status,
                action_hint=action_hint,
            )
        elif name == "supabase_schema_proof":
            action_hint = str(payload.get("action_hint") or "")
            if action_hint:
                reason["action_hint"] = action_hint
            failed_checks = payload.get("failed_checks")
            if isinstance(failed_checks, list) and failed_checks:
                reason["failed_checks"] = [str(check) for check in failed_checks]
            add_action(
                "supabase_schema",
                "apply_supabase_session_schema",
                status=status,
                action_hint=action_hint,
            )
        elif name == "pacing_policy_proof":
            action_hint = str(payload.get("action_hint") or "")
            if action_hint:
                reason["action_hint"] = action_hint
            failed_checks = payload.get("failed_checks")
            if isinstance(failed_checks, list) and failed_checks:
                reason["failed_checks"] = [str(check) for check in failed_checks]
            add_action(
                "pacing_policy",
                "fix_portal_pacing_policy",
                status=status,
                action_hint=action_hint,
            )
        elif name == "artifact_profile_precheck":
            action_hint = str(payload.get("action_hint") or "")
            if action_hint:
                reason["action_hint"] = action_hint
            profile_artifacts = payload.get("profile_artifacts")
            if isinstance(profile_artifacts, list) and profile_artifacts:
                reason["profile_artifacts"] = [str(path) for path in profile_artifacts]
            add_action(
                "artifact_profile_precheck",
                "remove_persistent_profiles_from_artifacts",
                status=status,
                action_hint=action_hint,
            )
            cleanup_command = _artifact_profile_cleanup_command_hint(payload)
            if cleanup_command:
                find_command = _artifact_profile_find_command_hint(payload)
                action_by_name["remove_persistent_profiles_from_artifacts"]["commands"] = [
                    find_command,
                    cleanup_command,
                    _dod_audit_latest_defaults_command_hint(artifact_root),
                ]
        elif name == "portal_session_preflight_status":
            reason.update(_portal_preflight_blocking_reason(payload))
            add_action(
                "portal_session_preflight",
                "refresh_portal_session_preflight",
                status=status,
                action_hint=str(payload.get("action_hint") or ""),
            )
        elif name == "restart_smoke_proof":
            reason.update(_restart_smoke_proof_blocking_reason(payload))
            add_action(
                "restart_smoke",
                "run_guarded_restart_smoke_all_sites",
                status=status,
                action_hint=str(payload.get("action_hint") or ""),
            )
        elif name == "discord_alert_precheck":
            action_hint = str(payload.get("action_hint") or "")
            if action_hint:
                reason["action_hint"] = action_hint
            action = (
                "configure_discord_reauth_webhook"
                if status == "missing_webhook"
                else "run_linkedin_discord_alert_test"
            )
            add_action("discord_alert_precheck", action, status=status, action_hint=action_hint)
        elif name.startswith("snapshot_metadata_"):
            add_action("snapshot_metadata", "restore_supabase_snapshot_read_access", status=status)
        elif name.startswith("profile_recovery_precheck_"):
            add_action("profile_recovery", "capture_validated_snapshots_before_profile_recovery_smoke", status=status)
        elif name == "profile_recovery_proof":
            reason.update(_profile_recovery_proof_blocking_reason(payload))
            add_action(
                "profile_recovery",
                "run_profile_recovery_smoke_saramin_jobkorea",
                status=status,
                action_hint=str(payload.get("action_hint") or ""),
            )
        elif name in {"reauth_weekly_counts", "reauth_weekly_trend"}:
            add_action("reauth_events", "restore_supabase_reauth_event_read_access", status=status)
        reasons.append(reason)
    return {
        "blocking_reasons": reasons,
        "action_items": action_items,
        "dod_blockers": _dod_blockers_from_action_items(action_items),
    }


def _dod_blockers_from_action_items(action_items: list[dict[str, object]]) -> list[dict[str, object]]:
    actions_by_dod: dict[str, list[str]] = {}
    for item in action_items:
        action = item.get("action")
        blocks = item.get("blocks_dod")
        if not isinstance(action, str) or not isinstance(blocks, list):
            continue
        for dod_id in blocks:
            if isinstance(dod_id, str):
                actions_by_dod.setdefault(dod_id, []).append(action)
    return [
        {"id": dod_id, "actions": sorted(set(actions))}
        for dod_id, actions in sorted(actions_by_dod.items())
    ]


def _dod_ids_blocked_by_action(action: str) -> tuple[str, ...]:
    mapping = {
        "fix_supabase_service_role_schema_or_key": (
            "dod_1_restart_search_all_sites",
            "dod_2_profile_corruption_snapshot_recovery",
            "dod_6_no_plaintext_session_output",
            "dod_7_reauth_events_weekly_observable",
        ),
        "apply_supabase_session_schema": (
            "dod_6_no_plaintext_session_output",
            "dod_7_reauth_events_weekly_observable",
        ),
        "fix_portal_pacing_policy": (),
        "remove_persistent_profiles_from_artifacts": ("dod_6_no_plaintext_session_output",),
        "configure_discord_reauth_webhook": ("dod_5_linkedin_discord_alert",),
        "run_linkedin_discord_alert_test": ("dod_5_linkedin_discord_alert",),
        "refresh_portal_session_preflight": ("dod_1_restart_search_all_sites",),
        "run_guarded_restart_smoke_all_sites": ("dod_1_restart_search_all_sites",),
        "restore_supabase_snapshot_read_access": (
            "dod_2_profile_corruption_snapshot_recovery",
            "dod_6_no_plaintext_session_output",
        ),
        "capture_validated_snapshots_before_profile_recovery_smoke": (
            "dod_2_profile_corruption_snapshot_recovery",
        ),
        "run_profile_recovery_smoke_saramin_jobkorea": ("dod_2_profile_corruption_snapshot_recovery",),
        "restore_supabase_reauth_event_read_access": (
            "dod_5_linkedin_discord_alert",
            "dod_7_reauth_events_weekly_observable",
        ),
    }
    return mapping.get(action, ())


def _artifact_profile_cleanup_command_hint(payload: dict[str, object]) -> str:
    argv = payload.get("cleanup_command_argv")
    if not isinstance(argv, list) or not argv:
        return ""
    command: list[str] = []
    for arg in argv:
        if not isinstance(arg, str) or not arg:
            return ""
        command.append(arg)
    return shlex.join(command)


def _artifact_profile_find_command_hint(payload: dict[str, object]) -> str:
    artifact_root = payload.get("artifact_root")
    root = artifact_root if isinstance(artifact_root, str) and artifact_root else str(DEFAULT_ARTIFACT_ROOT)
    return shlex.join(
        [
            "find",
            root,
            "-maxdepth",
            "4",
            "(",
            "-type",
            "d",
            "-name",
            "portal_profiles",
            "-o",
            "-type",
            "f",
            "-name",
            ".profile.lock",
            ")",
            "-print",
        ]
    )


def _dod_audit_latest_defaults_command_hint(artifact_root: Path) -> str:
    return shlex.join(
        [
            "python3",
            "-m",
            "tools.multi_position_sourcing.portal_dod_audit",
            "--latest-defaults",
            "--artifact-root",
            str(artifact_root),
        ]
    )


def _command_hints_for_action(
    action: str,
    *,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    worker_id: str = "default",
    week_start: str = "",
    keyword: str = "snapshot-precheck",
    profile_root: Path = DEFAULT_PROFILE_ROOT,
) -> tuple[str, ...]:
    def artifact_path(name: str) -> str:
        return str(artifact_root / name)

    def live_check_command(*args: str) -> str:
        return shlex.join(["python3", "-m", "tools.multi_position_sourcing.portal_live_check", *args])

    def portal_login_command(*args: str) -> str:
        return shlex.join(["python3", "-m", "tools.multi_position_sourcing.portal_login", *args])

    def profile_dir(channel: str) -> str:
        return str(profile_root / channel / worker_id)

    mapping = {
        "configure_supabase_url": (
            live_check_command("readiness", "--output", artifact_path("portal_live_readiness_latest.json")),
            live_check_command("supabase-access-check", "--output", artifact_path("portal_supabase_access_latest.json")),
        ),
        "configure_supabase_service_role_key": (
            live_check_command("readiness", "--output", artifact_path("portal_live_readiness_latest.json")),
            live_check_command("supabase-access-check", "--output", artifact_path("portal_supabase_access_latest.json")),
        ),
        "fix_supabase_service_role_schema_or_key": (
            live_check_command("supabase-access-check", "--output", artifact_path("portal_supabase_access_latest.json")),
            live_check_command("supabase-schema-proof", "--output", artifact_path("portal_supabase_schema_proof_latest.json")),
            live_check_command("readiness", "--output", artifact_path("portal_live_readiness_latest.json")),
        ),
        "apply_supabase_session_schema": (
            live_check_command("supabase-schema-proof", "--output", artifact_path("portal_supabase_schema_proof_latest.json")),
            "psql \"$SUPABASE_DB_URL\" -f docs/ai-search/session-state-supabase-schema-2026-06-09.sql",
            live_check_command("supabase-access-check", "--output", artifact_path("portal_supabase_access_latest.json")),
        ),
        "fix_portal_pacing_policy": (
            live_check_command("pacing-policy-proof", "--output", artifact_path("portal_pacing_policy_proof_latest.json")),
        ),
        "remove_persistent_profiles_from_artifacts": (
            _artifact_profile_find_command_hint({"artifact_root": str(artifact_root)}),
            live_check_command(
                "cleanup-artifact-profiles",
                "--artifact-root",
                str(artifact_root),
                "--confirm-delete-artifact-profiles",
                str(artifact_root / "portal_profiles"),
                "--output",
                artifact_path("portal_artifact_profile_cleanup_latest.json"),
            ),
            _dod_audit_latest_defaults_command_hint(artifact_root),
        ),
        "configure_discord_reauth_webhook": (
            live_check_command("init-discord-webhook", "--output", artifact_path("discord_webhook_init_latest.json")),
            live_check_command(
                "discord-alert-test",
                "--record-reauth-event",
                "--output",
                artifact_path("portal_discord_alert_test_latest.json"),
            ),
            live_check_command(
                "dod-refresh-status",
                "--artifact-root",
                str(artifact_root),
                "--worker-id",
                worker_id,
                "--week-start",
                week_start,
                "--keyword",
                keyword,
                "--profile-root",
                str(profile_root),
                "--output",
                artifact_path("portal_dod_status_refresh_latest.json"),
            ),
        ),
        "run_linkedin_discord_alert_test": (
            live_check_command(
                "discord-alert-test",
                "--record-reauth-event",
                "--output",
                artifact_path("portal_discord_alert_test_latest.json"),
            ),
            _dod_audit_latest_defaults_command_hint(artifact_root),
        ),
        "refresh_portal_session_preflight": (
            portal_login_command(
                "--channels",
                "saramin,jobkorea,linkedin_rps",
                "--profile-root",
                str(profile_root),
                "--worker-id",
                worker_id,
                "--no-human-intervention",
                "--channel-timeout-seconds",
                "180",
                "--output",
                artifact_path("portal_session_status_latest.json"),
            ),
            _dod_audit_latest_defaults_command_hint(artifact_root),
        ),
        "run_guarded_restart_smoke_all_sites": (
            live_check_command(
                "restart-smoke",
                "--channel",
                "saramin",
                "--keyword",
                keyword,
                "--worker-id",
                worker_id,
                "--profile-root",
                str(profile_root),
                "--timeout-seconds",
                "180",
                "--output",
                artifact_path("portal_restart_smoke_saramin.json"),
            ),
            live_check_command(
                "restart-smoke",
                "--channel",
                "jobkorea",
                "--keyword",
                keyword,
                "--worker-id",
                worker_id,
                "--profile-root",
                str(profile_root),
                "--timeout-seconds",
                "180",
                "--output",
                artifact_path("portal_restart_smoke_jobkorea.json"),
            ),
            live_check_command(
                "restart-smoke",
                "--channel",
                "linkedin_rps",
                "--keyword",
                keyword,
                "--worker-id",
                worker_id,
                "--profile-root",
                str(profile_root),
                "--timeout-seconds",
                "180",
                "--output",
                artifact_path("portal_restart_smoke_linkedin_rps.json"),
            ),
            live_check_command(
                "restart-smoke-proof",
                "--artifact-root",
                str(artifact_root),
                "--output",
                artifact_path("portal_restart_smoke_proof_status_latest.json"),
            ),
            _dod_audit_latest_defaults_command_hint(artifact_root),
        ),
        "install_playwright": (
            "python3 -m playwright install chromium",
            live_check_command("readiness", "--output", artifact_path("portal_live_readiness_latest.json")),
        ),
        "initialize_session_encryption_key": (
            live_check_command("init-session-key", "--output", artifact_path("portal_session_key_init_latest.json")),
            live_check_command("readiness", "--output", artifact_path("portal_live_readiness_latest.json")),
        ),
        "store_saramin_keychain_credentials": (
            live_check_command(
                "init-portal-credentials",
                "--channels",
                "saramin",
                "--output",
                artifact_path("portal_credentials_init_latest.json"),
            ),
            live_check_command("readiness", "--output", artifact_path("portal_live_readiness_latest.json")),
        ),
        "store_jobkorea_keychain_credentials": (
            live_check_command(
                "init-portal-credentials",
                "--channels",
                "jobkorea",
                "--output",
                artifact_path("portal_credentials_init_latest.json"),
            ),
            live_check_command("readiness", "--output", artifact_path("portal_live_readiness_latest.json")),
        ),
        "restore_supabase_snapshot_read_access": (
            live_check_command(
                "snapshot-metadata",
                "--channel",
                "saramin",
                "--worker-id",
                worker_id,
                "--output",
                artifact_path("portal_snapshot_metadata_saramin.json"),
            ),
            live_check_command(
                "snapshot-metadata",
                "--channel",
                "jobkorea",
                "--worker-id",
                worker_id,
                "--output",
                artifact_path("portal_snapshot_metadata_jobkorea.json"),
            ),
            live_check_command(
                "snapshot-metadata",
                "--channel",
                "linkedin_rps",
                "--worker-id",
                worker_id,
                "--output",
                artifact_path("portal_snapshot_metadata_linkedin_rps.json"),
            ),
        ),
        "capture_validated_snapshots_before_profile_recovery_smoke": (
            live_check_command(
                "capture-snapshot",
                "--channel",
                "saramin",
                "--worker-id",
                worker_id,
                "--profile-root",
                str(profile_root),
                "--output",
                artifact_path("portal_snapshot_capture_saramin.json"),
            ),
            live_check_command(
                "capture-snapshot",
                "--channel",
                "jobkorea",
                "--worker-id",
                worker_id,
                "--profile-root",
                str(profile_root),
                "--output",
                artifact_path("portal_snapshot_capture_jobkorea.json"),
            ),
        ),
        "run_profile_recovery_smoke_saramin_jobkorea": (
            live_check_command(
                "profile-recovery-smoke",
                "--channel",
                "saramin",
                "--keyword",
                keyword,
                "--worker-id",
                worker_id,
                "--profile-root",
                str(profile_root),
                "--confirm-delete-profile",
                profile_dir("saramin"),
                "--output",
                artifact_path("portal_profile_recovery_saramin.json"),
            ),
            live_check_command(
                "profile-recovery-smoke",
                "--channel",
                "jobkorea",
                "--keyword",
                keyword,
                "--worker-id",
                worker_id,
                "--profile-root",
                str(profile_root),
                "--confirm-delete-profile",
                profile_dir("jobkorea"),
                "--output",
                artifact_path("portal_profile_recovery_jobkorea.json"),
            ),
            live_check_command(
                "profile-recovery-proof",
                "--artifact-root",
                str(artifact_root),
                "--output",
                artifact_path("portal_profile_recovery_proof_status_latest.json"),
            ),
            _dod_audit_latest_defaults_command_hint(artifact_root),
        ),
        "restore_supabase_reauth_event_read_access": (
            live_check_command(
                "reauth-weekly-counts",
                "--week-start",
                week_start,
                "--output",
                artifact_path("portal_reauth_weekly_counts_latest.json"),
            ),
            live_check_command(
                "reauth-weekly-trend",
                "--latest-week-start",
                week_start,
                "--weeks",
                "4",
                "--output",
                artifact_path("portal_reauth_weekly_trend_latest.json"),
            ),
        ),
    }
    return mapping.get(action, ())


def _failed_readiness_check_names(payload: dict[str, object]) -> list[str]:
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return []
    names: list[str] = []
    for check in checks:
        if not isinstance(check, dict) or check.get("status") == "passed":
            continue
        name = check.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _readiness_action_for_check(check_name: str) -> str:
    actions = {
        "supabase_url_env": "configure_supabase_url",
        "supabase_service_role_env": "configure_supabase_service_role_key",
        "supabase_access": "fix_supabase_service_role_schema_or_key",
        "supabase_schema_proof": "apply_supabase_session_schema",
        "portal_pacing_policy": "fix_portal_pacing_policy",
        "discord_reauth_webhook_env": "configure_discord_reauth_webhook",
        "playwright_available": "install_playwright",
        "mac_keychain_session_key": "initialize_session_encryption_key",
        "saramin_keychain_credentials": "store_saramin_keychain_credentials",
        "jobkorea_keychain_credentials": "store_jobkorea_keychain_credentials",
    }
    return actions.get(check_name, "resolve_readiness_check")


def _readiness_action_area(check_name: str) -> str:
    areas = {
        "supabase_url_env": "supabase_access",
        "supabase_service_role_env": "supabase_access",
        "supabase_access": "supabase_access",
        "supabase_schema_proof": "supabase_schema",
        "portal_pacing_policy": "pacing_policy",
        "discord_reauth_webhook_env": "discord_alert_precheck",
        "playwright_available": "runtime",
        "mac_keychain_session_key": "session_encryption",
        "saramin_keychain_credentials": "portal_credentials",
        "jobkorea_keychain_credentials": "portal_credentials",
    }
    return areas.get(check_name, check_name)


def _readiness_action_hint(payload: dict[str, object], check_name: str) -> str:
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return ""
    for check in checks:
        if not isinstance(check, dict) or check.get("name") != check_name:
            continue
        hint = check.get("action_hint")
        return hint if isinstance(hint, str) else ""
    return ""


def portal_session_preflight_status_payload(path: Path) -> dict[str, object]:
    payload = _read_json_artifact_if_present(path)
    status_payload: dict[str, object] = {
        "kind": "portal_session_preflight_status",
        "generated_at": utc_now_live_check(),
        "status": "missing",
        "ready": False,
        "path": str(path),
        "preflight_generated_at": "unknown",
        "schema_issues": ["missing_artifact"],
        "not_ready_channels": list(PROTECTED_PORTAL_CHANNELS),
        "snapshot_issues": [],
        "action_hint": "portal_session_preflight_missing",
    }
    if payload is None:
        return status_payload

    schema_issues = _portal_preflight_schema_issues(payload)
    sessions = payload.get("portal_sessions")
    session_items = sessions if isinstance(sessions, list) else []
    not_ready = _portal_preflight_not_ready_channels(session_items)
    snapshot_issues = _portal_preflight_snapshot_issues(session_items)
    if schema_issues:
        status = "stale_schema"
        action_hint = "portal_session_preflight_schema_stale"
    elif not_ready:
        status = "not_ready"
        action_hint = "portal_session_preflight_not_ready"
    elif payload.get("ready") is not True:
        status = "not_ready"
        action_hint = "portal_session_preflight_not_ready"
    elif snapshot_issues:
        status = "snapshot_not_captured"
        action_hint = "portal_session_preflight_snapshot_missing"
    else:
        status = "ready"
        action_hint = "ready"

    return {
        **status_payload,
        "status": status,
        "ready": status == "ready" and payload.get("ready") is True,
        "preflight_generated_at": str(payload.get("generated_at") or "unknown"),
        "schema_issues": schema_issues,
        "not_ready_channels": not_ready,
        "snapshot_issues": snapshot_issues,
        "action_hint": action_hint,
    }


def restart_smoke_proof_status_payload(artifact_root: Path) -> dict[str, object]:
    missing_sites: list[str] = []
    incomplete_sites: list[str] = []
    non_guarded_sites: list[str] = []
    schema_issues: dict[str, list[str]] = {}
    proof_issues: dict[str, list[str]] = {}
    stale_artifacts: dict[str, str] = {}
    paths: dict[str, str] = {}
    generated_at = utc_now_live_check()
    proof_generated_at = _parse_utc_timestamp(generated_at) or datetime.now(timezone.utc)

    for channel in PROTECTED_PORTAL_CHANNELS:
        path = artifact_root / f"portal_restart_smoke_{channel}.json"
        profile_only_paths = (
            artifact_root / f"portal_restart_smoke_{channel}_profile_only.json",
            *((
                artifact_root / "portal_restart_smoke_linkedin_profile_only.json",
            ) if channel == "linkedin_rps" else ()),
        )
        selected_path, payload = _best_restart_smoke_payload_for_site(path, profile_only_paths)
        paths[channel] = str(selected_path)
        if payload is None:
            missing_sites.append(channel)
            continue
        schema = _restart_smoke_payload_schema_issues(channel, payload)
        proof = _restart_smoke_proof_issues(channel, payload)
        stale = _proof_artifact_stale_reason(payload, now=proof_generated_at)
        if schema or proof or stale:
            incomplete_sites.append(channel)
        if schema:
            schema_issues[channel] = schema
        if proof:
            proof_issues[channel] = proof
        if stale:
            stale_artifacts[channel] = stale
        if payload.get("mode") != "guarded":
            non_guarded_sites.append(channel)

    ready = not missing_sites and not incomplete_sites
    if ready:
        status = "ready"
        action_hint = "ready"
    elif missing_sites:
        status = "missing"
        action_hint = "restart_smoke_missing"
    elif stale_artifacts and not schema_issues and not proof_issues:
        status = "failed"
        action_hint = "restart_smoke_stale"
    else:
        status = "failed"
        action_hint = "restart_smoke_incomplete"

    return {
        "kind": "portal_restart_smoke_proof_status",
        "generated_at": generated_at,
        "status": status,
        "ready": ready,
        "missing_sites": missing_sites,
        "incomplete_sites": incomplete_sites,
        "non_guarded_sites": non_guarded_sites,
        "schema_issues": schema_issues,
        "proof_issues": proof_issues,
        "stale_artifacts": stale_artifacts,
        "paths": paths,
        "action_hint": action_hint,
    }


def _best_restart_smoke_payload_for_site(
    full_path: Path,
    profile_only_paths: tuple[Path, ...],
) -> tuple[Path, dict[str, object] | None]:
    candidates: list[tuple[Path, dict[str, object]]] = []
    for candidate_path, payload in (
        (full_path, _read_json_artifact_if_present(full_path)),
        *(
            (profile_only_path, _read_json_artifact_if_present(profile_only_path))
            for profile_only_path in profile_only_paths
        ),
    ):
        if isinstance(payload, dict):
            candidates.append((candidate_path, payload))
    if not candidates:
        return full_path, None
    best: dict[str, object] | None = None
    best_path = full_path
    best_score = -1
    for index, (candidate_path, payload) in enumerate(candidates):
        rank = _restart_smoke_artifact_rank(payload)
        if rank is None:
            continue
        score = rank * 10 - index
        if best is None or score > best_score:
            best = payload
            best_path = candidate_path
            best_score = score
    if best is None:
        return candidates[0][0], candidates[0][1]
    return best_path, best


def _restart_smoke_artifact_rank(payload: dict[str, object]) -> int | None:
    if payload.get("kind") != "portal_restart_search_smoke":
        return None
    if _is_restart_smoke_guarded_artifact(payload):
        return 2
    generated_at = payload.get("generated_at")
    if isinstance(generated_at, str) and generated_at:
        if payload.get("mode") == "profile_only":
            return 1
    return 0


def _is_restart_smoke_guarded_artifact(payload: dict[str, object]) -> bool:
    first = payload.get("first")
    second = payload.get("second")
    return (
        payload.get("kind") == "portal_restart_search_smoke"
        and isinstance(payload.get("generated_at"), str)
        and bool(payload.get("generated_at"))
        and payload.get("mode") == "guarded"
        and payload.get("snapshot_capture_policy") == "required"
        and payload.get("passed") is True
        and int(payload.get("worker_restarts") or 0) >= 2
        and isinstance(first, dict)
        and isinstance(second, dict)
        and _is_full_guarded_search_result(first)
        and _is_full_guarded_search_result(second)
    )


def _restart_smoke_payload_schema_issues(channel: Channel, payload: dict[str, object]) -> list[str]:
    issues: list[str] = []
    required_top_level = (
        "kind",
        "site",
        "worker_id",
        "keyword",
        "generated_at",
        "mode",
        "snapshot_capture_policy",
        "worker_restarts",
        "passed",
        "first",
        "second",
    )
    missing_top_level = [field for field in required_top_level if field not in payload]
    if missing_top_level:
        issues.append(f"missing_top_level={missing_top_level}")
    if payload.get("kind") != "portal_restart_search_smoke":
        issues.append("kind")
    if payload.get("site") != channel:
        issues.append("site")
    if not isinstance(payload.get("generated_at"), str) or not payload.get("generated_at"):
        issues.append("generated_at")
    for label in ("first", "second"):
        lifecycle = payload.get(label)
        if not isinstance(lifecycle, dict):
            issues.append(f"{label}=missing_or_invalid")
            continue
        if lifecycle.get("status") != "searched":
            continue
        missing_result_fields = [
            field
            for field in (
                "mode",
                "snapshot_capture_required",
                "snapshot_capture_policy",
                "snapshot_captured",
            )
            if field not in lifecycle
        ]
        if missing_result_fields:
            issues.append(f"{label}_missing={missing_result_fields}")
    return issues


def _restart_smoke_proof_issues(channel: Channel, payload: dict[str, object]) -> list[str]:
    issues: list[str] = []
    if payload.get("kind") != "portal_restart_search_smoke":
        issues.append("kind")
    if payload.get("site") != channel:
        issues.append("site")
    if not isinstance(payload.get("generated_at"), str) or not payload.get("generated_at"):
        issues.append("generated_at")
    if payload.get("mode") != "guarded":
        issues.append("mode_guarded")
    if payload.get("snapshot_capture_policy") != "required":
        issues.append("snapshot_capture_policy")
    if payload.get("passed") is not True:
        issues.append("passed")
    if int(payload.get("worker_restarts") or 0) < 2:
        issues.append("worker_restarts")
    first = payload.get("first")
    second = payload.get("second")
    if not isinstance(first, dict) or not _is_full_guarded_search_result(first):
        issues.append("first_full_guarded")
    if not isinstance(second, dict) or not _is_full_guarded_search_result(second):
        issues.append("second_full_guarded")
    return issues


def _is_full_guarded_search_result(payload: dict[str, object]) -> bool:
    return (
        _is_clean_result_payload(payload)
        and payload.get("mode") == "guarded"
        and payload.get("snapshot_capture_required") is True
        and payload.get("snapshot_capture_policy") == "required"
        and payload.get("snapshot_captured") is True
        and payload.get("profile_deleted_before_start") is not True
        and not payload.get("reauth_cause")
        and payload.get("retried_after_recovery") is not True
    )


def _restart_smoke_proof_blocking_reason(payload: dict[str, object]) -> dict[str, object]:
    reason: dict[str, object] = {}
    for key in (
        "missing_sites",
        "incomplete_sites",
        "non_guarded_sites",
        "schema_issues",
        "proof_issues",
        "stale_artifacts",
        "action_hint",
    ):
        value = payload.get(key)
        if value:
            reason[key] = value
    return reason


def profile_recovery_proof_status_payload(artifact_root: Path) -> dict[str, object]:
    missing_sites: list[str] = []
    incomplete_sites: list[str] = []
    schema_issues: dict[str, list[str]] = {}
    proof_issues: dict[str, list[str]] = {}
    stale_artifacts: dict[str, str] = {}
    paths: dict[str, str] = {}
    generated_at = utc_now_live_check()
    proof_generated_at = _parse_utc_timestamp(generated_at) or datetime.now(timezone.utc)

    for channel in SNAPSHOT_RECOVERY_CHANNELS:
        path = artifact_root / f"portal_profile_recovery_{channel}.json"
        paths[channel] = str(path)
        payload = _read_json_artifact_if_present(path)
        if payload is None:
            missing_sites.append(channel)
            continue
        schema = _profile_recovery_payload_schema_issues(channel, payload)
        proof = _profile_recovery_proof_issues(channel, payload)
        stale = _proof_artifact_stale_reason(payload, now=proof_generated_at)
        if schema or proof or stale:
            incomplete_sites.append(channel)
        if schema:
            schema_issues[channel] = schema
        if proof:
            proof_issues[channel] = proof
        if stale:
            stale_artifacts[channel] = stale

    ready = not missing_sites and not incomplete_sites
    if ready:
        status = "ready"
        action_hint = "ready"
    elif missing_sites:
        status = "missing"
        action_hint = "profile_recovery_smoke_missing"
    elif stale_artifacts and not schema_issues and not proof_issues:
        status = "failed"
        action_hint = "profile_recovery_smoke_stale"
    else:
        status = "failed"
        action_hint = "profile_recovery_smoke_incomplete"

    return {
        "kind": "portal_profile_recovery_proof_status",
        "generated_at": generated_at,
        "status": status,
        "ready": ready,
        "missing_sites": missing_sites,
        "incomplete_sites": incomplete_sites,
        "schema_issues": schema_issues,
        "proof_issues": proof_issues,
        "stale_artifacts": stale_artifacts,
        "paths": paths,
        "action_hint": action_hint,
    }


def _profile_recovery_payload_schema_issues(channel: Channel, payload: dict[str, object]) -> list[str]:
    issues: list[str] = []
    required_top_level = (
        "kind",
        "site",
        "worker_id",
        "keyword",
        "generated_at",
        "recovery_policy",
        "auto_relogin_disabled",
        "mode",
        "status",
        "reauth_cause",
        "snapshot_capture_required",
        "snapshot_capture_policy",
        "snapshot_captured",
        "retried_after_recovery",
        "profile_deleted_before_start",
        "recovery",
    )
    missing_top_level = [field for field in required_top_level if field not in payload]
    if missing_top_level:
        issues.append(f"missing_top_level={missing_top_level}")
    if payload.get("kind") != "portal_profile_recovery_smoke":
        issues.append("kind")
    if payload.get("recovery_policy") != PROFILE_RECOVERY_POLICY:
        issues.append("recovery_policy")
    if payload.get("auto_relogin_disabled") is not True:
        issues.append("auto_relogin_disabled")
    if payload.get("site") != channel:
        issues.append("site")
    if not isinstance(payload.get("generated_at"), str) or not payload.get("generated_at"):
        issues.append("generated_at")
    if "recovery" in payload and not isinstance(payload.get("recovery"), dict):
        issues.append("recovery")
    return issues


def _profile_recovery_proof_issues(channel: Channel, payload: dict[str, object]) -> list[str]:
    issues: list[str] = []
    recovery = payload.get("recovery")
    if payload.get("kind") != "portal_profile_recovery_smoke":
        issues.append("kind")
    if payload.get("site") != channel:
        issues.append("site")
    if not isinstance(payload.get("generated_at"), str) or not payload.get("generated_at"):
        issues.append("generated_at")
    if payload.get("mode") != "guarded":
        issues.append("mode_guarded")
    if payload.get("recovery_policy") != PROFILE_RECOVERY_POLICY:
        issues.append("recovery_policy")
    if payload.get("auto_relogin_disabled") is not True:
        issues.append("auto_relogin_disabled")
    if payload.get("status") != "searched":
        issues.append("status_searched")
    if payload.get("profile_deleted_before_start") is not True:
        issues.append("profile_deleted_before_start")
    if payload.get("reauth_cause") != "profile_corrupt":
        issues.append("reauth_cause")
    if payload.get("snapshot_capture_required") is not True:
        issues.append("snapshot_capture_required")
    if payload.get("snapshot_capture_policy") != "required":
        issues.append("snapshot_capture_policy")
    if payload.get("snapshot_captured") is not True:
        issues.append("snapshot_captured")
    if payload.get("retried_after_recovery") is not True:
        issues.append("retried_after_recovery")
    if not isinstance(recovery, dict):
        issues.append("recovery")
    else:
        if recovery.get("recovered") is not True:
            issues.append("recovery.recovered")
        if recovery.get("recovered_by") != "snapshot_reinject":
            issues.append("recovery.recovered_by")
        if recovery.get("reauth_event_recorded") is not True:
            issues.append("recovery.reauth_event_recorded")
    return issues


def _profile_recovery_proof_blocking_reason(payload: dict[str, object]) -> dict[str, object]:
    reason: dict[str, object] = {}
    for key in (
        "missing_sites",
        "incomplete_sites",
        "schema_issues",
        "proof_issues",
        "stale_artifacts",
        "action_hint",
    ):
        value = payload.get(key)
        if value:
            reason[key] = value
    return reason


def _proof_artifact_stale_reason(
    payload: dict[str, object],
    *,
    now: datetime,
    max_age: timedelta = PROOF_ARTIFACT_MAX_AGE,
) -> str:
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        return "missing_generated_at"
    parsed = _parse_utc_timestamp(generated_at)
    if parsed is None:
        return "invalid_generated_at"
    if parsed > now + timedelta(minutes=5):
        return "future_generated_at"
    if now - parsed > max_age:
        return f"older_than_{int(max_age.total_seconds() // 3600)}h"
    return ""


def _parse_utc_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _portal_preflight_schema_issues(payload: dict[str, object]) -> list[str]:
    issues: list[str] = []
    if payload.get("kind") != "portal_session_preflight":
        issues.append("kind")
    if not isinstance(payload.get("generated_at"), str) or not payload.get("generated_at"):
        issues.append("generated_at")
    if not isinstance(payload.get("portal_sessions"), list):
        issues.append("portal_sessions")
    if not isinstance(payload.get("ready"), bool):
        issues.append("ready")
    return issues


def _portal_preflight_not_ready_channels(sessions: list[object]) -> list[str]:
    ready_channels = {
        str(item.get("channel"))
        for item in sessions
        if isinstance(item, dict) and item.get("ready") is True
    }
    return [channel for channel in PROTECTED_PORTAL_CHANNELS if channel not in ready_channels]


def _portal_preflight_snapshot_issues(sessions: list[object]) -> list[str]:
    issues: list[str] = []
    for item in sessions:
        if not isinstance(item, dict) or item.get("ready") is not True:
            continue
        channel = str(item.get("channel") or "")
        if channel not in PROTECTED_PORTAL_CHANNELS:
            continue
        if item.get("snapshot_capture_required") is not True:
            issues.append(f"{channel}:snapshot_capture_required_not_true")
            continue
        if item.get("snapshot_captured") is not True:
            issues.append(f"{channel}:snapshot_not_captured")
    return issues


def _portal_preflight_blocking_reason(payload: dict[str, object]) -> dict[str, object]:
    reason: dict[str, object] = {}
    for key in ("preflight_generated_at", "schema_issues", "not_ready_channels", "snapshot_issues", "action_hint"):
        value = payload.get(key)
        if value:
            reason[key] = value
    return reason


def _dod_refresh_status(name: str, payload: dict[str, object]) -> str:
    if name in {"readiness", "supabase_access"}:
        return "ready" if payload.get("ready") is True else "not_ready"
    if name == "supabase_schema_proof":
        return "ready" if payload.get("ready") is True else str(payload.get("status") or "not_ready")
    if name == "pacing_policy_proof":
        return "ready" if payload.get("ready") is True else str(payload.get("status") or "not_ready")
    if name == "artifact_profile_precheck":
        return "ready" if payload.get("status") == "ready" else str(payload.get("status") or "not_ready")
    if name == "portal_session_preflight_status":
        return "ready" if payload.get("ready") is True else str(payload.get("status") or "not_ready")
    if name == "restart_smoke_proof":
        return "ready" if payload.get("ready") is True else str(payload.get("status") or "not_ready")
    if name == "profile_recovery_proof":
        return "ready" if payload.get("ready") is True else str(payload.get("status") or "not_ready")
    if name.startswith("snapshot_metadata_"):
        return "ready" if profile_recovery_snapshot_ready(payload) else str(payload.get("status") or "not_ready")
    if name.startswith("profile_recovery_precheck_"):
        return str(payload.get("status") or "not_ready")
    if name == "discord_alert_precheck":
        if _is_complete_discord_alert_artifact(payload):
            return "ready"
        return _incomplete_discord_alert_status(payload)
    if name == "reauth_weekly_counts":
        return "ready" if payload.get("status") == "present" else str(payload.get("status") or "not_ready")
    if name == "reauth_weekly_trend":
        return "ready" if payload.get("status") == "present" else str(payload.get("status") or "not_ready")
    return str(payload.get("status") or "unknown")


def artifact_profile_precheck_payload(artifact_root: Path = DEFAULT_ARTIFACT_ROOT) -> dict[str, object]:
    profile_artifacts = _persistent_profile_artifact_paths(artifact_root)
    status = "unsafe" if profile_artifacts else "ready"
    profile_root = artifact_root / "portal_profiles"
    payload: dict[str, object] = {
        "kind": "portal_artifact_profile_precheck",
        "generated_at": utc_now_live_check(),
        "status": status,
        "artifact_root": str(artifact_root),
        "profile_artifacts": profile_artifacts,
    }
    if profile_artifacts:
        payload["action_hint"] = "remove_persistent_profiles_from_artifacts"
        payload["cleanup_confirmation"] = str(profile_root)
        payload["cleanup_command_argv"] = [
            "python3",
            "-m",
            "tools.multi_position_sourcing.portal_live_check",
            "cleanup-artifact-profiles",
            "--artifact-root",
            str(artifact_root),
            "--confirm-delete-artifact-profiles",
            str(profile_root),
            "--output",
            str(artifact_root / "portal_artifact_profile_cleanup_latest.json"),
        ]
    return payload


def cleanup_artifact_profiles_payload(
    *,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    confirm_delete_artifact_profiles: str,
) -> dict[str, object]:
    profile_root = artifact_root / "portal_profiles"
    expected_confirm = str(profile_root)
    if artifact_root.is_symlink():
        return {
            "kind": "portal_artifact_profile_cleanup",
            "generated_at": utc_now_live_check(),
            "artifact_root": str(artifact_root),
            "profile_root": expected_confirm,
            "profile_artifacts_before": [],
            "deleted": False,
            "status": "failed",
            "reason": "artifact profile cleanup refuses a symlink artifact root",
            "profile_artifacts_after": [],
        }
    before = _persistent_profile_artifact_paths(artifact_root)
    base_payload: dict[str, object] = {
        "kind": "portal_artifact_profile_cleanup",
        "generated_at": utc_now_live_check(),
        "artifact_root": str(artifact_root),
        "profile_root": expected_confirm,
        "profile_artifacts_before": before,
        "deleted": False,
    }
    if confirm_delete_artifact_profiles != expected_confirm:
        return {
            **base_payload,
            "status": "not_confirmed",
            "reason": f"cleanup requires --confirm-delete-artifact-profiles {expected_confirm}",
            "profile_artifacts_after": before,
        }
    if not profile_root.exists():
        return {
            **base_payload,
            "status": "ready",
            "reason": "artifact profile root absent",
            "profile_artifacts_after": [],
        }
    if profile_root.is_symlink() or not profile_root.is_dir():
        return {
            **base_payload,
            "status": "failed",
            "reason": "artifact profile cleanup requires a real portal_profiles directory",
            "profile_artifacts_after": before,
        }
    try:
        with _exclusive_artifact_profile_locks(profile_root):
            shutil.rmtree(profile_root)
    except RuntimeError as exc:
        error_message = str(exc)
        if error_message in {
            "artifact profile cleanup refused because a profile is locked",
            "artifact profile cleanup refused because a profile lock is a symlink",
        }:
            safe_reason = error_message
        else:
            safe_reason = safe_exception_label(exc, action="artifact profile cleanup failed")
        return {
            **base_payload,
            "status": "failed",
            "reason": safe_reason,
            "profile_artifacts_after": _persistent_profile_artifact_paths(artifact_root),
        }
    except Exception as exc:
        return {
            **base_payload,
            "status": "failed",
            "reason": safe_exception_label(exc, action="artifact profile cleanup failed"),
            "profile_artifacts_after": _persistent_profile_artifact_paths(artifact_root),
        }
    return {
        **base_payload,
        "status": "ready",
        "reason": "artifact profiles removed",
        "deleted": True,
        "profile_artifacts_after": _persistent_profile_artifact_paths(artifact_root),
    }


class _exclusive_artifact_profile_locks:
    def __init__(self, profile_root: Path) -> None:
        self.profile_root = profile_root
        self._handles: list[Any] = []

    def __enter__(self) -> "_exclusive_artifact_profile_locks":
        for lock_path in sorted(self.profile_root.rglob(".profile.lock")):
            if lock_path.is_symlink():
                self._close_all()
                raise RuntimeError("artifact profile cleanup refused because a profile lock is a symlink")
            handle = _open_artifact_profile_lock(lock_path)
            try:
                _lock_handle(handle)
            except (BlockingIOError, OSError) as exc:
                handle.close()
                self._close_all()
                raise RuntimeError("artifact profile cleanup refused because a profile is locked") from exc
            self._handles.append(handle)
        return self

    def __exit__(self, *_exc: object) -> None:
        self._close_all()

    def _close_all(self) -> None:
        while self._handles:
            handle = self._handles.pop()
            try:
                _unlock_handle(handle)
            finally:
                handle.close()


def _open_artifact_profile_lock(lock_path: Path) -> Any:
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK}:
            raise RuntimeError("artifact profile cleanup refused because a profile lock is a symlink") from exc
        raise
    return os.fdopen(fd, "a+", encoding="utf-8")


def _persistent_profile_artifact_paths(root: Path) -> list[str]:
    if not root.exists():
        return []
    if root.is_file():
        return [str(root.parent)] if root.name == ".profile.lock" else []
    offenders: list[str] = []
    for path in (root, *root.rglob("*")):
        if path.is_dir() and path.name == "portal_profiles":
            offenders.append(str(path))
            continue
        if path.is_file() and path.name == ".profile.lock":
            offenders.append(str(path.parent))
    return _dedupe_strings(offenders)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _is_complete_discord_alert_artifact(payload: object) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("kind") == "discord_alert_test"
        and isinstance(payload.get("generated_at"), str)
        and bool(payload.get("generated_at"))
        and payload.get("delivered") is True
        and payload.get("reauth_event_recorded") is True
        and _is_linkedin_human_discord_alert_event(payload.get("event"))
    )


def _incomplete_discord_alert_status(payload: dict[str, object]) -> str:
    status = str(payload.get("status") or "not_ready")
    if (
        payload.get("kind") == "discord_alert_test"
        and payload.get("delivered") is True
        and payload.get("reauth_event_recorded") is True
        and not _is_linkedin_human_discord_alert_event(payload.get("event"))
    ):
        return "event_mismatch"
    if status == "delivered":
        return "not_ready"
    return status


def _is_linkedin_human_discord_alert_event(event: object) -> bool:
    return (
        isinstance(event, dict)
        and event.get("site") == "linkedin_rps"
        and isinstance(event.get("worker_id"), str)
        and bool(event.get("worker_id"))
        and event.get("cause") == "forced_logout"
        and event.get("recovered_by") == "human"
        and isinstance(event.get("occurred_at"), str)
        and bool(event.get("occurred_at"))
    )


def snapshot_metadata_payload(
    *,
    channel: Channel,
    worker_id: str,
    store: Any | None = None,
) -> dict[str, object]:
    try:
        snapshot_store = store if store is not None else SupabaseSessionSnapshotStore(supabase_config_from_env())
        record = snapshot_store.latest_validated(site=channel, worker_id=worker_id)
    except Exception as exc:
        return {
            "kind": "session_snapshot_metadata",
            "site": channel,
            "worker_id": worker_id,
            "generated_at": utc_now_live_check(),
            "snapshot_present": False,
            "status": "unavailable",
            "error_type": exc.__class__.__name__,
        }
    return safe_snapshot_metadata_payload(
        record,
        site=channel,
        worker_id=worker_id,
    )


def profile_recovery_snapshot_ready(metadata: dict[str, object]) -> bool:
    return (
        metadata.get("kind") == "session_snapshot_metadata"
        and metadata.get("status") == "present"
        and metadata.get("snapshot_present") is True
        and metadata.get("is_validated") is True
        and metadata.get("encrypted_envelope") == PAYLOAD_VERSION.decode("ascii")
    )


def safe_profile_recovery_not_run_payload(
    config: LiveSearchConfig,
    *,
    metadata: dict[str, object],
) -> dict[str, object]:
    return {
        "kind": "portal_profile_recovery_smoke",
        "site": config.channel,
        "worker_id": config.worker_id,
        "keyword": config.keyword,
        "generated_at": utc_now_live_check(),
        "recovery_policy": PROFILE_RECOVERY_POLICY,
        "auto_relogin_disabled": True,
        "mode": "guarded",
        "status": "not_run",
        "reason": "validated_snapshot_required_before_profile_deletion",
        "reauth_cause": "profile_corrupt",
        "snapshot_capture_required": True,
        "snapshot_capture_policy": "required",
        "snapshot_captured": False,
        "retried_after_recovery": False,
        "profile_deleted_before_start": False,
        "recovery": {
            "recovered": False,
            "recovered_by": "",
            "reauth_event_recorded": False,
            "pause_site": False,
            "discord_alert_sent": False,
        },
        "snapshot_metadata_status": str(metadata.get("status") or "missing"),
        "snapshot_present": metadata.get("snapshot_present") is True,
    }


def delete_profile_dir_if_confirmed(path: Path, *, enabled: bool, confirm: str) -> bool:
    if not enabled:
        return False
    expected = str(path)
    if confirm != expected:
        raise RuntimeError(f"profile deletion requires --confirm-delete-profile {expected}")
    if path.is_symlink():
        raise RuntimeError("profile deletion requires a real profile directory")
    if not path.exists():
        return False
    if not path.is_dir():
        raise RuntimeError("profile deletion requires a real profile directory")
    with _exclusive_profile_deletion_lock(path):
        shutil.rmtree(path)
    return True


class _exclusive_profile_deletion_lock:
    def __init__(self, profile_dir: Path) -> None:
        self.profile_dir = profile_dir
        self._handle: Any | None = None

    def __enter__(self) -> "_exclusive_profile_deletion_lock":
        lock_path = self.profile_dir / ".profile.lock"
        handle = lock_path.open("a+", encoding="utf-8")
        try:
            _lock_handle(handle)
        except (BlockingIOError, OSError) as exc:
            handle.close()
            raise RuntimeError("profile deletion refused because the profile is locked") from exc
        self._handle = handle
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._handle is None:
            return
        try:
            _unlock_handle(self._handle)
        finally:
            self._handle.close()
            self._handle = None


def send_discord_alert_test(
    webhook_url: str,
    *,
    event_store: ReauthEventStore | None = None,
    urlopen: Any | None = None,
    occurred_at: str | None = None,
    record_reauth_event_requested: bool = False,
    reauth_event_error_type: str = "",
) -> dict[str, object]:
    notifier = (
        DiscordWebhookNotifier(webhook_url, urlopen=urlopen)
        if urlopen is not None
        else DiscordWebhookNotifier(webhook_url)
    )
    event = ReauthEvent(
        id="manual-live-check",
        site="linkedin_rps",
        worker_id="default",
        cause="forced_logout",
        recovered_by="human",
        occurred_at=occurred_at or utc_now_live_check(),
    )
    delivery_error_type = ""
    try:
        delivered = notifier.send_reauth_alert(event)
    except Exception as exc:
        delivered = False
        delivery_error_type = exc.__class__.__name__
    reauth_event_recorded = False
    record_requested = record_reauth_event_requested or event_store is not None
    if delivered and event_store is not None:
        try:
            event_store.record(
                site=event.site,
                worker_id=event.worker_id,
                cause=event.cause,
                recovered_by=event.recovered_by,
                occurred_at=event.occurred_at,
            )
            reauth_event_recorded = True
        except Exception as exc:
            reauth_event_error_type = exc.__class__.__name__
    payload = {
        "kind": "discord_alert_test",
        "generated_at": utc_now_live_check(),
        "status": _discord_alert_test_status(
            delivered=delivered,
            record_requested=record_requested,
            reauth_event_recorded=reauth_event_recorded,
        ),
        "delivered": delivered,
        "reauth_event_recording_requested": record_requested,
        "reauth_event_recorded": reauth_event_recorded,
        "event": asdict(event),
    }
    if delivery_error_type:
        payload["delivery_error_type"] = delivery_error_type
    if reauth_event_error_type:
        payload["reauth_event_error_type"] = reauth_event_error_type
    return payload


def _discord_alert_test_status(
    *,
    delivered: bool,
    record_requested: bool,
    reauth_event_recorded: bool,
) -> str:
    if not delivered:
        return "delivery_failed"
    if record_requested and not reauth_event_recorded:
        return "recording_failed"
    return "delivered"


def missing_discord_alert_webhook_payload() -> dict[str, object]:
    return {
        "kind": "discord_alert_test",
        "generated_at": utc_now_live_check(),
        "status": "missing_webhook",
        "delivered": False,
        "reauth_event_recording_requested": True,
        "reauth_event_recorded": False,
        "action_hint": "discord_reauth_webhook_missing",
        "reason": (
            "DISCORD_REAUTH_WEBHOOK_URL/VALUEHIRE_DISCORD_REAUTH_WEBHOOK_URL "
            "or macOS Keychain valuehire.discord/reauth_webhook_url is required"
        ),
    }


def discord_alert_test_not_run_payload() -> dict[str, object]:
    return {
        "kind": "discord_alert_test",
        "generated_at": utc_now_live_check(),
        "status": "not_run",
        "delivered": False,
        "reauth_event_recording_requested": True,
        "reauth_event_recorded": False,
        "action_hint": "discord_alert_test_required",
        "reason": "discord_alert_test_required",
    }


def _session_key_available() -> bool:
    try:
        MacKeychainSessionKeyProvider(create_if_missing=False).get_key()
    except Exception:
        return False
    return True


def _portal_credentials_available(site: Channel) -> bool:
    try:
        MacKeychainPortalCredentialProvider().load(site)
    except Exception:
        return False
    return True


def _discord_webhook_from_env_value(source: dict[str, str]) -> tuple[str, str]:
    for name in ("DISCORD_REAUTH_WEBHOOK_URL", "VALUEHIRE_DISCORD_REAUTH_WEBHOOK_URL"):
        value = source.get(name, "").strip()
        if value:
            return value, name
    return "", ""


def _read_discord_webhook_keychain() -> str:
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            DISCORD_WEBHOOK_KEYCHAIN_SERVICE,
            "-a",
            DISCORD_WEBHOOK_KEYCHAIN_ACCOUNT,
            "-w",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        return ""
    try:
        return base64.b64decode(result.stdout.strip(), validate=True).decode("utf-8")
    except Exception:
        return ""


def _write_discord_webhook_keychain(webhook_url: str) -> None:
    encoded = base64.b64encode(webhook_url.encode("utf-8")).decode("ascii")
    result = add_generic_password(
        service=DISCORD_WEBHOOK_KEYCHAIN_SERVICE,
        account=DISCORD_WEBHOOK_KEYCHAIN_ACCOUNT,
        password=encoded,
    )
    if result.returncode != 0:
        raise RuntimeError("failed to write Discord webhook to macOS keychain")


def _first_env(source: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = source.get(name, "").strip()
        if value:
            return value
    return ""


def _parse_channel(value: str) -> Channel:
    if value not in {"saramin", "jobkorea", "linkedin_rps"}:
        raise argparse.ArgumentTypeError("channel must be saramin, jobkorea, or linkedin_rps")
    return value  # type: ignore[return-value]


def _parse_snapshot_recovery_channel(value: str) -> Channel:
    channel = _parse_channel(value)
    if channel not in {"saramin", "jobkorea"}:
        raise argparse.ArgumentTypeError("profile recovery smoke supports only saramin or jobkorea")
    return channel


def _parse_channels(value: str) -> tuple[Channel, ...]:
    channels: list[Channel] = []
    for raw in value.split(","):
        channel = raw.strip()
        if channel:
            channels.append(_parse_channel(channel))
    if not channels:
        raise argparse.ArgumentTypeError("at least one channel is required")
    return tuple(channels)


def _write_json_artifact(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json_artifact_if_present(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_output(path: str, payload: dict[str, object]) -> None:
    output = Path(path)
    _write_json_artifact(output, payload)
    print(str(output))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live protected portal session checks without printing secrets.")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    readiness = subparsers.add_parser(
        "readiness",
        help="Check live DoD prerequisites without contacting portals or printing secrets.",
    )
    readiness.add_argument("--output", default="artifacts/portal_live_readiness_latest.json")

    supabase_access = subparsers.add_parser(
        "supabase-access-check",
        help="Check Supabase REST/RPC access without printing service-role keys or response bodies.",
    )
    supabase_access.add_argument("--output", default="artifacts/portal_supabase_access_latest.json")

    supabase_schema = subparsers.add_parser(
        "supabase-schema-proof",
        help="Validate the local Supabase session schema migration without printing SQL or secrets.",
    )
    supabase_schema.add_argument("--schema-path", type=Path, default=DEFAULT_SUPABASE_SCHEMA_PATH)
    supabase_schema.add_argument("--output", default="artifacts/portal_supabase_schema_proof_latest.json")

    pacing_policy = subparsers.add_parser(
        "pacing-policy-proof",
        help="Validate protected-portal pacing policy guardrails without contacting portals.",
    )
    pacing_policy.add_argument("--output", default="artifacts/portal_pacing_policy_proof_latest.json")

    artifact_profile = subparsers.add_parser(
        "artifact-profile-precheck",
        help="Detect persistent browser profiles under artifact outputs without deleting them.",
    )
    artifact_profile.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    artifact_profile.add_argument("--output", default="artifacts/portal_artifact_profile_precheck_latest.json")

    cleanup_profiles = subparsers.add_parser(
        "cleanup-artifact-profiles",
        help="Remove persistent browser profiles from artifact outputs after an exact confirmation string.",
    )
    cleanup_profiles.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    cleanup_profiles.add_argument("--confirm-delete-artifact-profiles", required=True)
    cleanup_profiles.add_argument("--output", default="artifacts/portal_artifact_profile_cleanup_latest.json")

    dod_refresh = subparsers.add_parser(
        "dod-refresh-status",
        help="Refresh non-destructive latest DoD status artifacts without portal searches or Discord sends.",
    )
    dod_refresh.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    dod_refresh.add_argument("--worker-id", default="default")
    dod_refresh.add_argument("--week-start", default="")
    dod_refresh.add_argument("--keyword", default="snapshot-precheck")
    dod_refresh.add_argument("--profile-root", default=str(DEFAULT_PROFILE_ROOT))
    dod_refresh.add_argument("--output", default="artifacts/portal_dod_status_refresh_latest.json")

    init_key = subparsers.add_parser(
        "init-session-key",
        help="Create or verify the local Mac Keychain session encryption key without printing it.",
    )
    init_key.add_argument("--output", default="artifacts/portal_session_key_init_latest.json")

    init_credentials = subparsers.add_parser(
        "init-portal-credentials",
        help="Import Saramin/Jobkorea/LinkedIn RPS env credentials into Mac Keychain without printing secrets.",
    )
    init_credentials.add_argument("--channels", default="saramin,jobkorea,linkedin_rps", type=_parse_channels)
    init_credentials.add_argument("--output", default="artifacts/portal_credentials_init_latest.json")

    init_discord = subparsers.add_parser(
        "init-discord-webhook",
        help="Import the Discord reauth webhook env value into Mac Keychain without printing it.",
    )
    init_discord.add_argument("--output", default="artifacts/discord_webhook_init_latest.json")

    search = subparsers.add_parser("search", help="Run one guarded protected-portal keyword search.")
    search.add_argument("--channel", required=True, type=_parse_channel)
    search.add_argument("--keyword", required=True)
    search.add_argument("--worker-id", default="default")
    search.add_argument("--profile-root", default=str(DEFAULT_PROFILE_ROOT))
    search.add_argument("--chrome-cdp-endpoint", default=None, help="CDP endpoint of a running Chrome (SOT: browser_policy.json / $VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT; 어긋난 값은 검문소가 거부 — 포트 변경은 SOT를 고친다)")
    search.add_argument("--headless", action="store_true")
    search.add_argument("--searches-today", type=int, default=0)
    search.add_argument("--no-sleep", action="store_true")
    search.add_argument("--disable-auto-relogin", action="store_true")
    search.add_argument(
        "--profile-only",
        action="store_true",
        help="M1 smoke mode: prove persistent profile search without snapshot capture, recovery, or Supabase writes.",
    )
    search.add_argument("--delete-profile-before-start", action="store_true")
    search.add_argument("--confirm-delete-profile", default="")
    search.add_argument("--output", default=DEFAULT_LIVE_OUTPUT)

    restart = subparsers.add_parser(
        "restart-smoke",
        help="Run two guarded searches with separate worker lifecycles to prove restart persistence.",
    )
    restart.add_argument("--channel", required=True, type=_parse_channel)
    restart.add_argument("--keyword", required=True)
    restart.add_argument("--worker-id", default="default")
    restart.add_argument("--profile-root", default=str(DEFAULT_PROFILE_ROOT))
    restart.add_argument("--chrome-cdp-endpoint", default=None, help="CDP endpoint of a running Chrome (SOT: browser_policy.json / $VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT; 어긋난 값은 검문소가 거부 — 포트 변경은 SOT를 고친다)")
    restart.add_argument("--headless", action="store_true")
    restart.add_argument("--searches-today", type=int, default=0)
    restart.add_argument("--no-sleep", action="store_true")
    restart.add_argument("--disable-auto-relogin", action="store_true")
    restart.add_argument(
        "--profile-only",
        action="store_true",
        help="M1 smoke mode: prove restart persistence without snapshot capture, recovery, or Supabase writes.",
    )
    restart.add_argument("--timeout-seconds", type=int, default=180, help="Per worker lifecycle timeout.")
    restart.add_argument("--output", default="artifacts/portal_restart_smoke_latest.json")

    restart_proof = subparsers.add_parser(
        "restart-smoke-proof",
        help="Aggregate restart-smoke artifacts into the DoD1 proof-status artifact.",
    )
    restart_proof.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    restart_proof.add_argument("--output", default="artifacts/portal_restart_smoke_proof_status_latest.json")

    recovery = subparsers.add_parser(
        "profile-recovery-smoke",
        help="Delete a Saramin/Jobkorea profile and prove snapshot-only recovery; auto-relogin is disabled.",
    )
    recovery.add_argument("--channel", required=True, type=_parse_snapshot_recovery_channel)
    recovery.add_argument("--keyword", required=True)
    recovery.add_argument("--worker-id", default="default")
    recovery.add_argument("--profile-root", default=str(DEFAULT_PROFILE_ROOT))
    recovery.add_argument("--chrome-cdp-endpoint", default=None, help="CDP endpoint of a running Chrome (SOT: browser_policy.json / $VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT; 어긋난 값은 검문소가 거부 — 포트 변경은 SOT를 고친다)")
    recovery.add_argument("--headless", action="store_true")
    recovery.add_argument("--searches-today", type=int, default=0)
    recovery.add_argument("--no-sleep", action="store_true")
    recovery.add_argument("--confirm-delete-profile", required=True)
    recovery.add_argument("--output", default="artifacts/portal_profile_recovery_latest.json")

    recovery_proof = subparsers.add_parser(
        "profile-recovery-proof",
        help="Aggregate profile-recovery-smoke artifacts into the DoD2 proof-status artifact.",
    )
    recovery_proof.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    recovery_proof.add_argument("--output", default="artifacts/portal_profile_recovery_proof_status_latest.json")

    snapshot = subparsers.add_parser("capture-snapshot", help="Capture a validated snapshot from a ready portal session.")
    snapshot.add_argument("--channel", required=True, type=_parse_channel)
    snapshot.add_argument("--worker-id", default="default")
    snapshot.add_argument("--profile-root", default=str(DEFAULT_PROFILE_ROOT))
    snapshot.add_argument("--chrome-cdp-endpoint", default=None, help="CDP endpoint of a running Chrome (SOT: browser_policy.json / $VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT; 어긋난 값은 검문소가 거부 — 포트 변경은 SOT를 고친다)")
    snapshot.add_argument("--headless", action="store_true")
    snapshot.add_argument("--output", default="artifacts/portal_snapshot_capture_latest.json")

    weekly = subparsers.add_parser("reauth-weekly-counts", help="Read weekly reauth counts from Supabase.")
    weekly.add_argument("--week-start", default="")
    weekly.add_argument("--output", default="artifacts/portal_reauth_weekly_counts_latest.json")

    trend = subparsers.add_parser("reauth-weekly-trend", help="Read several weekly reauth aggregates from Supabase.")
    trend.add_argument("--latest-week-start", default="")
    trend.add_argument("--weeks", type=int, default=4)
    trend.add_argument("--output", default="artifacts/portal_reauth_weekly_trend_latest.json")

    metadata = subparsers.add_parser("snapshot-metadata", help="Read safe encrypted snapshot metadata from Supabase.")
    metadata.add_argument("--channel", required=True, type=_parse_channel)
    metadata.add_argument("--worker-id", default="default")
    metadata.add_argument("--output", default="artifacts/portal_snapshot_metadata_latest.json")

    alert = subparsers.add_parser("discord-alert-test", help="Send a synthetic LinkedIn reauth alert.")
    alert.add_argument("--webhook-url", default="")
    alert.add_argument("--record-reauth-event", action="store_true")
    alert.add_argument("--output", default="artifacts/portal_discord_alert_test_latest.json")

    args = parser.parse_args()
    load_env_file(args.env_file)
    if hasattr(args, "chrome_cdp_endpoint"):
        args.chrome_cdp_endpoint = resolve_chrome_cdp_endpoint(args.chrome_cdp_endpoint)

    if args.command == "readiness":
        payload = live_readiness_payload()
        _write_output(args.output, payload)
        if payload.get("ready") is not True:
            raise SystemExit(2)
        return

    if args.command == "supabase-access-check":
        payload = supabase_access_check_payload()
        _write_output(args.output, payload)
        if payload.get("ready") is not True:
            raise SystemExit(2)
        return

    if args.command == "supabase-schema-proof":
        payload = supabase_schema_proof_payload(args.schema_path)
        _write_output(args.output, payload)
        if payload.get("ready") is not True:
            raise SystemExit(2)
        return

    if args.command == "pacing-policy-proof":
        payload = pacing_policy_proof_payload()
        _write_output(args.output, payload)
        if payload.get("ready") is not True:
            raise SystemExit(2)
        return

    if args.command == "artifact-profile-precheck":
        payload = artifact_profile_precheck_payload(args.artifact_root)
        _write_output(args.output, payload)
        if payload.get("status") != "ready":
            raise SystemExit(2)
        return

    if args.command == "cleanup-artifact-profiles":
        payload = cleanup_artifact_profiles_payload(
            artifact_root=args.artifact_root,
            confirm_delete_artifact_profiles=args.confirm_delete_artifact_profiles,
        )
        _write_output(args.output, payload)
        if payload.get("status") != "ready":
            raise SystemExit(2)
        return

    if args.command == "dod-refresh-status":
        payload = refresh_dod_status_artifacts(
            artifact_root=args.artifact_root,
            worker_id=args.worker_id,
            week_start=args.week_start,
            keyword=args.keyword,
            profile_root=Path(args.profile_root),
        )
        _write_output(args.output, payload)
        if payload.get("ready") is not True:
            raise SystemExit(2)
        return

    if args.command == "init-session-key":
        _write_output(args.output, init_session_key_payload())
        return

    if args.command == "init-portal-credentials":
        _write_output(args.output, init_portal_credentials_payload(channels=args.channels))
        return

    if args.command == "init-discord-webhook":
        _write_output(args.output, init_discord_webhook_payload())
        return

    if args.command == "search":
        payload = asyncio.run(
            run_live_search(
                LiveSearchConfig(
                    channel=args.channel,
                    keyword=args.keyword,
                    worker_id=args.worker_id,
                    profile_root=Path(args.profile_root),
                    chrome_cdp_endpoint=args.chrome_cdp_endpoint,
                    headless=args.headless,
                    searches_today=args.searches_today,
                    no_sleep=args.no_sleep,
                    disable_auto_relogin=args.disable_auto_relogin,
                    delete_profile_before_start=args.delete_profile_before_start,
                    confirm_delete_profile=args.confirm_delete_profile,
                    profile_only=args.profile_only,
                )
            )
        )
        _write_output(args.output, payload)
        return

    if args.command == "restart-smoke":
        restart_config = LiveRestartSearchConfig(
            channel=args.channel,
            keyword=args.keyword,
            worker_id=args.worker_id,
            profile_root=Path(args.profile_root),
            chrome_cdp_endpoint=args.chrome_cdp_endpoint,
            headless=args.headless,
            searches_today=args.searches_today,
            no_sleep=args.no_sleep,
            disable_auto_relogin=args.disable_auto_relogin,
            timeout_seconds=args.timeout_seconds,
            profile_only=args.profile_only,
        )
        payload = asyncio.run(run_restart_search_smoke(restart_config))
        _write_output(args.output, payload)
        if payload.get("status") == "timeout":
            raise SystemExit(2)
        return

    if args.command == "restart-smoke-proof":
        payload = restart_smoke_proof_status_payload(args.artifact_root)
        _write_output(args.output, payload)
        if payload.get("ready") is not True:
            raise SystemExit(2)
        return

    if args.command == "profile-recovery-smoke":
        payload = asyncio.run(
            run_profile_recovery_smoke(
                LiveSearchConfig(
                    channel=args.channel,
                    keyword=args.keyword,
                    worker_id=args.worker_id,
                    profile_root=Path(args.profile_root),
                    chrome_cdp_endpoint=args.chrome_cdp_endpoint,
                    headless=args.headless,
                    searches_today=args.searches_today,
                    no_sleep=args.no_sleep,
                    disable_auto_relogin=True,
                    delete_profile_before_start=True,
                    confirm_delete_profile=args.confirm_delete_profile,
                )
            )
        )
        _write_output(args.output, payload)
        if payload.get("status") != "searched":
            raise SystemExit(2)
        return

    if args.command == "profile-recovery-proof":
        payload = profile_recovery_proof_status_payload(args.artifact_root)
        _write_output(args.output, payload)
        if payload.get("ready") is not True:
            raise SystemExit(2)
        return

    if args.command == "capture-snapshot":
        payload = asyncio.run(
            capture_live_snapshot(
                LiveSessionConfig(
                    channel=args.channel,
                    worker_id=args.worker_id,
                    profile_root=Path(args.profile_root),
                    chrome_cdp_endpoint=args.chrome_cdp_endpoint,
                    headless=args.headless,
                )
            )
        )
        _write_output(args.output, payload)
        return

    if args.command == "reauth-weekly-counts":
        _write_output(args.output, weekly_reauth_counts_payload(week_start=args.week_start or current_utc_week_start()))
        return

    if args.command == "reauth-weekly-trend":
        _write_output(
            args.output,
            reauth_weekly_trend_payload(
                latest_week_start=args.latest_week_start or current_utc_week_start(),
                weeks=args.weeks,
            ),
        )
        return

    if args.command == "snapshot-metadata":
        _write_output(args.output, snapshot_metadata_payload(channel=args.channel, worker_id=args.worker_id))
        return

    webhook_url = args.webhook_url or discord_webhook_from_env()
    if not webhook_url:
        _write_output(args.output, missing_discord_alert_webhook_payload())
        raise SystemExit(2)
    event_store = None
    reauth_event_error_type = ""
    if args.record_reauth_event:
        try:
            event_store = SupabaseReauthEventStore(supabase_config_from_env())
        except Exception as exc:
            reauth_event_error_type = exc.__class__.__name__
    payload = send_discord_alert_test(
        webhook_url,
        event_store=event_store,
        record_reauth_event_requested=args.record_reauth_event,
        reauth_event_error_type=reauth_event_error_type,
    )
    _write_output(args.output, payload)
    if payload.get("delivered") is not True or (
        args.record_reauth_event and payload.get("reauth_event_recorded") is not True
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
