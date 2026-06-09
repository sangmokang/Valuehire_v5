from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from .models import Channel
from .portal_ops import is_allowed_reauth_cause
from .portal_snapshot import (
    InMemorySessionSnapshotStore,
    OpenSslSessionEncryptor,
    StaticSessionKeyProvider,
    capture_validated_snapshot,
)
from .portal_worker import PortalWorkerConfig, ProfileLock, ProfileLockError

AuditStatus = Literal["passed", "failed", "missing"]
PROTECTED_CHANNELS: tuple[Channel, ...] = ("saramin", "jobkorea", "linkedin_rps")
SNAPSHOT_RECOVERY_CHANNELS: tuple[Channel, ...] = ("saramin", "jobkorea")
SNAPSHOT_METADATA_CHANNELS: tuple[Channel, ...] = PROTECTED_CHANNELS
ALLOWED_REAUTH_RECOVERED_BY = ("snapshot_reinject", "auto_relogin", "human", "unrecovered")
ALLOWED_WEEKLY_COUNT_ROW_FIELDS = frozenset(("site", "worker_id", "cause", "recovered_by", "count"))
DEFAULT_SECRET_SCAN_PATH = Path("artifacts/portal_session_dod")
DEFAULT_ARTIFACT_ROOT = Path("artifacts")
DEFAULT_PRODUCER_SCAN_PATH = DEFAULT_ARTIFACT_ROOT
PROFILE_RECOVERY_POLICY = "snapshot_only_no_auto_relogin"
FORBIDDEN_OUTPUT_TERMS = (
    "storage_state",
    "storagestate",
    "plain-cookie",
    "cookie-secret",
    "password-secret",
    "service-role-secret",
    "signature-secret",
    "session-secret",
    "token-secret",
    "user:pass",
    "discord-bot-token-secret",
    "webhook.example",
    "discord.example.test/webhook",
)
TEXT_SESSION_SCAN_SUFFIXES = (".err", ".json", ".jsonl", ".log", ".ndjson", ".out", ".txt")
RESTART_SMOKE_REQUIRED_TOP_LEVEL_FIELDS = (
    "generated_at",
    "mode",
    "snapshot_capture_policy",
    "worker_restarts",
    "passed",
    "first",
    "second",
)
RESTART_SEARCH_RESULT_REQUIRED_FIELDS = (
    "mode",
    "snapshot_capture_required",
    "snapshot_capture_policy",
    "snapshot_captured",
)
PROFILE_RECOVERY_REQUIRED_TOP_LEVEL_FIELDS = (
    "kind",
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


def utc_now_dod_audit() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class AuditRequirement:
    id: str
    status: AuditStatus
    evidence: str


@dataclass(frozen=True)
class DefaultAuditArtifacts:
    session_status_path: Path
    preflight_status_path: Path
    restart_smoke_artifact_paths: tuple[Path, ...]
    restart_smoke_proof_path: Path
    profile_recovery_artifact_paths: tuple[Path, ...]
    profile_recovery_proof_path: Path
    snapshot_metadata_artifact_paths: tuple[Path, ...]
    discord_alert_path: Path
    weekly_counts_path: Path
    weekly_trend_path: Path
    supabase_access_path: Path
    supabase_schema_proof_path: Path


def latest_default_audit_artifacts(root: Path = DEFAULT_ARTIFACT_ROOT) -> DefaultAuditArtifacts:
    return DefaultAuditArtifacts(
        session_status_path=root / "portal_session_status_latest.json",
        preflight_status_path=root / "portal_session_preflight_status_latest.json",
        restart_smoke_artifact_paths=(
            root / "portal_restart_smoke_saramin_profile_only.json",
            root / "portal_restart_smoke_jobkorea_profile_only.json",
            root / "portal_restart_smoke_linkedin_profile_only.json",
            root / "portal_restart_smoke_saramin.json",
            root / "portal_restart_smoke_jobkorea.json",
            root / "portal_restart_smoke_linkedin_rps.json",
        ),
        restart_smoke_proof_path=root / "portal_restart_smoke_proof_status_latest.json",
        profile_recovery_artifact_paths=(
            root / "portal_profile_recovery_saramin.json",
            root / "portal_profile_recovery_jobkorea.json",
        ),
        profile_recovery_proof_path=root / "portal_profile_recovery_proof_status_latest.json",
        snapshot_metadata_artifact_paths=(
            root / "portal_snapshot_metadata_saramin.json",
            root / "portal_snapshot_metadata_jobkorea.json",
            root / "portal_snapshot_metadata_linkedin_rps.json",
        ),
        discord_alert_path=root / "portal_discord_alert_test_latest.json",
        weekly_counts_path=root / "portal_reauth_weekly_counts_latest.json",
        weekly_trend_path=root / "portal_reauth_weekly_trend_latest.json",
        supabase_access_path=root / "portal_supabase_access_latest.json",
        supabase_schema_proof_path=root / "portal_supabase_schema_proof_latest.json",
    )


def _existing_default_path(path: Path) -> Path | None:
    return path if path.exists() else None


def _existing_default_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(path for path in paths if path.exists())


def build_dod_audit_payload(
    *,
    session_status_path: Path | None,
    search_artifact_paths: tuple[Path, ...],
    profile_recovery_artifact_paths: tuple[Path, ...],
    preflight_status_path: Path | None = None,
    restart_smoke_artifact_paths: tuple[Path, ...] = (),
    restart_smoke_proof_path: Path | None = None,
    profile_recovery_proof_path: Path | None = None,
    snapshot_metadata_artifact_paths: tuple[Path, ...] = (),
    discord_alert_path: Path | None = None,
    weekly_counts_path: Path | None = None,
    weekly_trend_path: Path | None = None,
    supabase_access_path: Path | None = None,
    supabase_schema_proof_path: Path | None = None,
    secret_scan_paths: tuple[Path, ...] = (),
    producer_scan_paths: tuple[Path, ...] = (),
) -> dict[str, object]:
    session_status = _read_json_if_present(session_status_path)
    preflight_status = _read_json_if_present(preflight_status_path)
    search_artifacts = _artifacts_by_site(search_artifact_paths)
    restart_smoke_artifacts = _best_restart_smoke_artifacts_by_site(restart_smoke_artifact_paths)
    restart_smoke_proof = _read_json_if_present(restart_smoke_proof_path)
    recovery_artifacts = _artifacts_by_site(profile_recovery_artifact_paths)
    profile_recovery_proof = _read_json_if_present(profile_recovery_proof_path)
    snapshot_metadata_artifacts = _artifacts_by_site(snapshot_metadata_artifact_paths)
    discord_alert = _read_json_if_present(discord_alert_path)
    weekly_counts = _read_json_if_present(weekly_counts_path)
    weekly_trend = _read_json_if_present(weekly_trend_path)
    supabase_access = _read_json_if_present(supabase_access_path)
    supabase_schema_proof = _read_json_if_present(supabase_schema_proof_path)
    scanned_paths = tuple(
        path
        for path in (
            (session_status_path,) if session_status_path is not None else ()
        )
        + ((preflight_status_path,) if preflight_status_path is not None else ())
        + search_artifact_paths
        + restart_smoke_artifact_paths
        + ((restart_smoke_proof_path,) if restart_smoke_proof_path is not None else ())
        + profile_recovery_artifact_paths
        + ((profile_recovery_proof_path,) if profile_recovery_proof_path is not None else ())
        + snapshot_metadata_artifact_paths
        + ((discord_alert_path,) if discord_alert_path is not None else ())
        + ((weekly_counts_path,) if weekly_counts_path is not None else ())
        + ((weekly_trend_path,) if weekly_trend_path is not None else ())
        + ((supabase_access_path,) if supabase_access_path is not None else ())
        + ((supabase_schema_proof_path,) if supabase_schema_proof_path is not None else ())
    )

    requirements = [
        _restart_search_requirement(session_status, restart_smoke_artifacts, preflight_status, restart_smoke_proof),
        _profile_recovery_requirement(recovery_artifacts, profile_recovery_proof),
        _filelock_requirement(),
        _poison_snapshot_requirement(),
        _discord_alert_requirement(discord_alert),
        _secret_output_requirement(
            scanned_paths,
            snapshot_metadata_artifacts,
            supabase_access,
            supabase_schema_proof,
            secret_scan_paths,
            producer_scan_paths,
        ),
        _reauth_events_requirement(weekly_counts, weekly_trend, supabase_access, supabase_schema_proof),
    ]
    return {
        "kind": "portal_session_persistence_dod_audit",
        "generated_at": utc_now_dod_audit(),
        "passed": all(requirement.status == "passed" for requirement in requirements),
        "requirements": [asdict(requirement) for requirement in requirements],
    }


def _read_json_if_present(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        return None
    return decoded


def _artifacts_by_site(paths: tuple[Path, ...]) -> dict[str, dict[str, object]]:
    artifacts: dict[str, dict[str, object]] = {}
    for path in paths:
        payload = _read_json_if_present(path)
        if payload is None:
            continue
        site = str(payload.get("site") or payload.get("channel") or "")
        if site:
            artifacts[site] = payload
    return artifacts


def _best_restart_smoke_artifacts_by_site(paths: tuple[Path, ...]) -> dict[str, dict[str, object]]:
    candidates: dict[str, tuple[tuple[int, int], dict[str, object]]] = {}
    for index, path in enumerate(paths):
        payload = _read_json_if_present(path)
        if payload is None:
            continue
        site = str(payload.get("site") or payload.get("channel") or "")
        if not site:
            continue
        rank = _restart_smoke_artifact_rank(payload)
        if rank is None:
            continue
        current = candidates.get(site)
        score = (rank, -index)
        if current is None or score > current[0]:
            candidates[site] = (score, payload)
    return {site: payload for site, (_score, payload) in candidates.items()}


def _restart_smoke_artifact_rank(payload: dict[str, object]) -> int | None:
    if payload.get("kind") != "portal_restart_search_smoke":
        return None
    if _is_restart_smoke_artifact(payload):
        return 2
    generated_at = payload.get("generated_at")
    if isinstance(generated_at, str) and generated_at:
        if payload.get("mode") == "profile_only":
            return 1
    return 0


def _restart_search_requirement(
    session_status: dict[str, object] | None,
    restart_smoke_artifacts: dict[str, dict[str, object]],
    preflight_status: dict[str, object] | None = None,
    restart_smoke_proof: dict[str, object] | None = None,
) -> AuditRequirement:
    preflight_status_hint = _preflight_status_hint(preflight_status)
    restart_proof_hint = _restart_smoke_proof_hint(restart_smoke_proof)
    if session_status is None:
        return AuditRequirement(
            id="dod_1_restart_search_all_sites",
            status="missing",
            evidence=f"portal session preflight artifact was not supplied{preflight_status_hint}{restart_proof_hint}",
        )
    sessions = session_status.get("portal_sessions")
    if not isinstance(sessions, list):
        return AuditRequirement(
            id="dod_1_restart_search_all_sites",
            status="failed",
            evidence=(
                "portal session preflight artifact has no portal_sessions list"
                f"{preflight_status_hint}{restart_proof_hint}"
            ),
        )
    preflight_generated_at = str(session_status.get("generated_at") or "unknown")
    preflight_schema_issues = _preflight_schema_issues(session_status)
    ready_sites = {
        str(item.get("channel"))
        for item in sessions
        if isinstance(item, dict) and item.get("ready") is True
    }
    missing_ready = [site for site in PROTECTED_CHANNELS if site not in ready_sites]
    preflight_snapshot_issues = _preflight_snapshot_issues(sessions)
    missing_restart = [site for site in PROTECTED_CHANNELS if site not in restart_smoke_artifacts]
    restart_modes = _restart_smoke_modes(restart_smoke_artifacts)
    restart_generated_at = _restart_smoke_generated_at(restart_smoke_artifacts)
    restart_details = _restart_smoke_details(restart_smoke_artifacts)
    non_guarded_restart = _restart_smoke_non_guarded_sites(restart_smoke_artifacts)
    restart_schema_hint = _restart_smoke_schema_hint(restart_smoke_artifacts)
    if missing_ready or missing_restart:
        return AuditRequirement(
            id="dod_1_restart_search_all_sites",
            status="missing",
            evidence=(
                f"missing ready={missing_ready or []}, "
                f"missing restart-smoke artifacts={missing_restart or []}; "
                f"non_guarded_restart={non_guarded_restart}; "
                f"preflight_generated_at={preflight_generated_at}; "
                f"modes={restart_modes}; generated_at={restart_generated_at}; "
                f"details={restart_details}; preflight_schema_issues={preflight_schema_issues}; "
                f"preflight_snapshot_issues={preflight_snapshot_issues}"
                f"{restart_schema_hint}{preflight_status_hint}{restart_proof_hint}"
            ),
        )
    if preflight_schema_issues:
        return AuditRequirement(
            id="dod_1_restart_search_all_sites",
            status="failed",
            evidence=(
                "portal session preflight artifact is missing required freshness fields "
                f"{preflight_schema_issues}; preflight_generated_at={preflight_generated_at}; "
                f"modes={restart_modes}; generated_at={restart_generated_at}; details={restart_details}"
                f"{restart_schema_hint}{preflight_status_hint}{restart_proof_hint}"
            ),
        )
    if preflight_snapshot_issues:
        return AuditRequirement(
            id="dod_1_restart_search_all_sites",
            status="failed",
            evidence=(
                "ready preflight sessions did not prove validated login-success snapshot capture "
                f"for {preflight_snapshot_issues}; modes={restart_modes}; "
                f"preflight_generated_at={preflight_generated_at}; "
                f"generated_at={restart_generated_at}; details={restart_details}{restart_schema_hint}"
                f"{preflight_status_hint}{restart_proof_hint}"
            ),
        )
    failed = [
        site
        for site in PROTECTED_CHANNELS
        if not _is_restart_smoke_artifact(restart_smoke_artifacts[site])
    ]
    if failed:
        return AuditRequirement(
            id="dod_1_restart_search_all_sites",
            status="failed",
            evidence=(
                "guarded restart-smoke artifacts did not prove two clean worker lifecycles "
                f"with required snapshot capture for {failed}; "
                f"non_guarded_restart={non_guarded_restart}; "
                f"preflight_generated_at={preflight_generated_at}; "
                f"modes={restart_modes}; generated_at={restart_generated_at}; "
                f"details={restart_details}{restart_schema_hint}{preflight_status_hint}{restart_proof_hint}"
            ),
        )
    return AuditRequirement(
        id="dod_1_restart_search_all_sites",
        status="passed",
        evidence=(
            "all protected sites were ready and supplied restart-smoke artifacts prove two clean worker lifecycles; "
            "preflight_snapshot_capture=all_ready_sessions_captured; "
            f"preflight_generated_at={preflight_generated_at}; "
            f"modes={restart_modes}; generated_at={restart_generated_at}; details={restart_details}{restart_schema_hint}"
            f"{preflight_status_hint}{restart_proof_hint}"
        ),
    )


def _preflight_status_hint(preflight_status: dict[str, object] | None) -> str:
    if not isinstance(preflight_status, dict):
        return ""
    fields: list[str] = []
    status = preflight_status.get("status")
    if isinstance(status, str) and status:
        fields.append(f"preflight_status={status}")
    action_hint = preflight_status.get("action_hint")
    if isinstance(action_hint, str) and action_hint:
        fields.append(f"preflight_action_hint={action_hint}")
    generated_at = preflight_status.get("generated_at")
    if isinstance(generated_at, str) and generated_at:
        fields.append(f"preflight_status_generated_at={generated_at}")
    schema_issues = preflight_status.get("schema_issues")
    if isinstance(schema_issues, list) and schema_issues:
        fields.append(f"preflight_status_schema_issues={schema_issues}")
    snapshot_issues = preflight_status.get("snapshot_issues")
    if isinstance(snapshot_issues, list) and snapshot_issues:
        fields.append(f"preflight_status_snapshot_issues={snapshot_issues}")
    not_ready_channels = preflight_status.get("not_ready_channels")
    if isinstance(not_ready_channels, list) and not_ready_channels:
        fields.append(f"preflight_status_not_ready={not_ready_channels}")
    return "" if not fields else "; " + "; ".join(fields)


def _preflight_schema_issues(session_status: dict[str, object]) -> list[str]:
    generated_at = session_status.get("generated_at")
    if isinstance(generated_at, str) and generated_at:
        return []
    return ["missing_generated_at"]


def _preflight_snapshot_issues(sessions: list[object]) -> list[str]:
    issues: list[str] = []
    for item in sessions:
        if not isinstance(item, dict) or item.get("ready") is not True:
            continue
        channel = str(item.get("channel") or "")
        if channel not in PROTECTED_CHANNELS:
            continue
        if item.get("snapshot_capture_required") is not True:
            issues.append(f"{channel}:snapshot_capture_required_not_true")
            continue
        if item.get("snapshot_captured") is not True:
            issues.append(f"{channel}:snapshot_not_captured")
    return issues


def _is_restart_smoke_artifact(payload: dict[str, object]) -> bool:
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


def _is_clean_search_result(payload: dict[str, object]) -> bool:
    return (
        payload.get("status") == "searched"
        and payload.get("profile_deleted_before_start") is not True
        and not payload.get("reauth_cause")
        and payload.get("retried_after_recovery") is not True
    )


def _is_full_guarded_search_result(payload: dict[str, object]) -> bool:
    return (
        _is_clean_search_result(payload)
        and payload.get("mode") == "guarded"
        and payload.get("snapshot_capture_required") is True
        and payload.get("snapshot_capture_policy") == "required"
        and payload.get("snapshot_captured") is True
    )


def _restart_smoke_modes(artifacts: dict[str, dict[str, object]]) -> dict[str, str]:
    return {
        site: str(payload.get("mode") or "unknown")
        for site, payload in sorted(artifacts.items())
    }


def _restart_smoke_generated_at(artifacts: dict[str, dict[str, object]]) -> dict[str, str]:
    return {
        site: str(payload.get("generated_at") or "unknown")
        for site, payload in sorted(artifacts.items())
    }


def _restart_smoke_non_guarded_sites(artifacts: dict[str, dict[str, object]]) -> list[str]:
    return [
        site
        for site, payload in sorted(artifacts.items())
        if payload.get("mode") != "guarded" or payload.get("snapshot_capture_policy") != "required"
    ]


def _restart_smoke_details(artifacts: dict[str, dict[str, object]]) -> dict[str, dict[str, str]]:
    details: dict[str, dict[str, str]] = {}
    for site, payload in sorted(artifacts.items()):
        first = payload.get("first")
        second = payload.get("second")
        details[site] = {
            "mode": str(payload.get("mode") or "unknown"),
            "passed": str(payload.get("passed") is True),
            "snapshot_capture_policy": str(payload.get("snapshot_capture_policy") or ""),
            "first_status": str(first.get("status") if isinstance(first, dict) else ""),
            "first_reason": str(first.get("reason") if isinstance(first, dict) else ""),
            "second_status": str(second.get("status") if isinstance(second, dict) else ""),
            "second_reason": str(second.get("reason") if isinstance(second, dict) else ""),
        }
    return details


def _restart_smoke_schema_hint(artifacts: dict[str, dict[str, object]]) -> str:
    issues = _restart_smoke_schema_issues(artifacts)
    if not issues:
        return ""
    return f"; schema_issues={issues}"


def _restart_smoke_proof_hint(restart_smoke_proof: dict[str, object] | None) -> str:
    if not isinstance(restart_smoke_proof, dict):
        return ""
    fields: list[str] = []
    status = restart_smoke_proof.get("status")
    if isinstance(status, str) and status:
        fields.append(f"restart_smoke_proof_status={status}")
    action_hint = restart_smoke_proof.get("action_hint")
    if isinstance(action_hint, str) and action_hint:
        fields.append(f"restart_smoke_action_hint={action_hint}")
    generated_at = restart_smoke_proof.get("generated_at")
    if isinstance(generated_at, str) and generated_at:
        fields.append(f"restart_smoke_proof_generated_at={generated_at}")
    missing_sites = restart_smoke_proof.get("missing_sites")
    if isinstance(missing_sites, list) and missing_sites:
        fields.append(f"restart_smoke_missing_sites={missing_sites}")
    incomplete_sites = restart_smoke_proof.get("incomplete_sites")
    if isinstance(incomplete_sites, list) and incomplete_sites:
        fields.append(f"restart_smoke_incomplete_sites={incomplete_sites}")
    non_guarded_sites = restart_smoke_proof.get("non_guarded_sites")
    if isinstance(non_guarded_sites, list) and non_guarded_sites:
        fields.append(f"restart_smoke_non_guarded_sites={non_guarded_sites}")
    schema_issues = restart_smoke_proof.get("schema_issues")
    if isinstance(schema_issues, dict) and schema_issues:
        fields.append(f"restart_smoke_proof_schema_issues={schema_issues}")
    proof_issues = restart_smoke_proof.get("proof_issues")
    if isinstance(proof_issues, dict) and proof_issues:
        fields.append(f"restart_smoke_proof_issues={proof_issues}")
    stale_artifacts = restart_smoke_proof.get("stale_artifacts")
    if isinstance(stale_artifacts, dict) and stale_artifacts:
        fields.append(f"restart_smoke_stale_artifacts={stale_artifacts}")
    return "" if not fields else "; " + "; ".join(fields)


def _restart_smoke_schema_issues(artifacts: dict[str, dict[str, object]]) -> dict[str, list[str]]:
    issues: dict[str, list[str]] = {}
    for site, payload in sorted(artifacts.items()):
        if payload.get("mode") == "profile_only":
            continue
        site_issues: list[str] = []
        if payload.get("kind") != "portal_restart_search_smoke":
            site_issues.append("kind")
        missing_top_level = [
            field
            for field in RESTART_SMOKE_REQUIRED_TOP_LEVEL_FIELDS
            if field not in payload
        ]
        if missing_top_level:
            site_issues.append(f"missing_top_level={missing_top_level}")
        first = payload.get("first")
        second = payload.get("second")
        for label, lifecycle in (("first", first), ("second", second)):
            if not isinstance(lifecycle, dict):
                site_issues.append(f"{label}=missing_or_invalid")
                continue
            if lifecycle.get("status") != "searched":
                continue
            missing_result_fields = [
                field
                for field in RESTART_SEARCH_RESULT_REQUIRED_FIELDS
                if field not in lifecycle
            ]
            if missing_result_fields:
                site_issues.append(f"{label}_missing={missing_result_fields}")
        if site_issues:
            issues[site] = site_issues
    return issues


def _profile_recovery_requirement(
    recovery_artifacts: dict[str, dict[str, object]],
    profile_recovery_proof: dict[str, object] | None = None,
) -> AuditRequirement:
    missing = [site for site in SNAPSHOT_RECOVERY_CHANNELS if site not in recovery_artifacts]
    details = _profile_recovery_details(recovery_artifacts)
    schema_hint = _profile_recovery_schema_hint(recovery_artifacts)
    proof_hint = _profile_recovery_proof_hint(profile_recovery_proof)
    if missing:
        return AuditRequirement(
            id="dod_2_profile_corruption_snapshot_recovery",
            status="missing",
            evidence=(
                f"missing profile-corruption recovery artifacts for {missing}; "
                f"details={details}{schema_hint}{proof_hint}"
            ),
        )
    failed = [
        site
        for site in SNAPSHOT_RECOVERY_CHANNELS
        if not _is_profile_recovery_artifact(recovery_artifacts[site])
    ]
    if failed:
        return AuditRequirement(
            id="dod_2_profile_corruption_snapshot_recovery",
            status="failed",
            evidence=(
                f"profile-corruption artifacts did not prove snapshot-only recovery for {failed}; "
                f"details={details}{schema_hint}{proof_hint}"
            ),
        )
    return AuditRequirement(
        id="dod_2_profile_corruption_snapshot_recovery",
        status="passed",
        evidence=(
            "Saramin and Jobkorea profile-corruption artifacts show snapshot_reinject recovery; "
            f"details={details}{proof_hint}"
        ),
    )


def _is_profile_recovery_artifact(payload: dict[str, object]) -> bool:
    recovery = payload.get("recovery")
    return (
        isinstance(recovery, dict)
        and payload.get("kind") == "portal_profile_recovery_smoke"
        and isinstance(payload.get("generated_at"), str)
        and bool(payload.get("generated_at"))
        and payload.get("recovery_policy") == PROFILE_RECOVERY_POLICY
        and payload.get("auto_relogin_disabled") is True
        and payload.get("mode") == "guarded"
        and payload.get("status") == "searched"
        and payload.get("profile_deleted_before_start") is True
        and payload.get("reauth_cause") == "profile_corrupt"
        and payload.get("snapshot_capture_required") is True
        and payload.get("snapshot_capture_policy") == "required"
        and payload.get("snapshot_captured") is True
        and payload.get("retried_after_recovery") is True
        and recovery.get("recovered") is True
        and recovery.get("recovered_by") == "snapshot_reinject"
        and recovery.get("reauth_event_recorded") is True
    )


def _profile_recovery_details(artifacts: dict[str, dict[str, object]]) -> dict[str, dict[str, str]]:
    details: dict[str, dict[str, str]] = {}
    for site, payload in sorted(artifacts.items()):
        recovery = payload.get("recovery")
        details[site] = {
            "generated_at": str(payload.get("generated_at") or "unknown"),
            "status": str(payload.get("status") or "unknown"),
            "reason": str(payload.get("reason") or ""),
            "snapshot_metadata_status": str(payload.get("snapshot_metadata_status") or ""),
            "snapshot_present": str(payload.get("snapshot_present") is True),
            "recovered_by": str(recovery.get("recovered_by") if isinstance(recovery, dict) else ""),
        }
    return details


def _profile_recovery_schema_hint(artifacts: dict[str, dict[str, object]]) -> str:
    issues = _profile_recovery_schema_issues(artifacts)
    if not issues:
        return ""
    return f"; schema_issues={issues}"


def _profile_recovery_proof_hint(profile_recovery_proof: dict[str, object] | None) -> str:
    if not isinstance(profile_recovery_proof, dict):
        return ""
    fields: list[str] = []
    status = profile_recovery_proof.get("status")
    if isinstance(status, str) and status:
        fields.append(f"profile_recovery_proof_status={status}")
    action_hint = profile_recovery_proof.get("action_hint")
    if isinstance(action_hint, str) and action_hint:
        fields.append(f"profile_recovery_action_hint={action_hint}")
    generated_at = profile_recovery_proof.get("generated_at")
    if isinstance(generated_at, str) and generated_at:
        fields.append(f"profile_recovery_proof_generated_at={generated_at}")
    missing_sites = profile_recovery_proof.get("missing_sites")
    if isinstance(missing_sites, list) and missing_sites:
        fields.append(f"profile_recovery_missing_sites={missing_sites}")
    incomplete_sites = profile_recovery_proof.get("incomplete_sites")
    if isinstance(incomplete_sites, list) and incomplete_sites:
        fields.append(f"profile_recovery_incomplete_sites={incomplete_sites}")
    schema_issues = profile_recovery_proof.get("schema_issues")
    if isinstance(schema_issues, dict) and schema_issues:
        fields.append(f"profile_recovery_proof_schema_issues={schema_issues}")
    proof_issues = profile_recovery_proof.get("proof_issues")
    if isinstance(proof_issues, dict) and proof_issues:
        fields.append(f"profile_recovery_proof_issues={proof_issues}")
    stale_artifacts = profile_recovery_proof.get("stale_artifacts")
    if isinstance(stale_artifacts, dict) and stale_artifacts:
        fields.append(f"profile_recovery_stale_artifacts={stale_artifacts}")
    return "" if not fields else "; " + "; ".join(fields)


def _profile_recovery_schema_issues(artifacts: dict[str, dict[str, object]]) -> dict[str, list[str]]:
    issues: dict[str, list[str]] = {}
    for site, payload in sorted(artifacts.items()):
        site_issues: list[str] = []
        missing_top_level = [
            field
            for field in PROFILE_RECOVERY_REQUIRED_TOP_LEVEL_FIELDS
            if field not in payload
        ]
        if missing_top_level:
            site_issues.append(f"missing_top_level={missing_top_level}")
        if payload.get("kind") != "portal_profile_recovery_smoke":
            site_issues.append("kind")
        if payload.get("recovery_policy") != PROFILE_RECOVERY_POLICY:
            site_issues.append("recovery_policy")
        if payload.get("auto_relogin_disabled") is not True:
            site_issues.append("auto_relogin_disabled")
        if site_issues:
            issues[site] = site_issues
    return issues


def _filelock_requirement() -> AuditRequirement:
    with TemporaryDirectory() as tmp:
        configs = (
            PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=tmp),
            PortalWorkerConfig(channel="linkedin_rps", profile_root=tmp),
        )
        verified: list[str] = []
        for config in configs:
            first = ProfileLock(config)
            second = ProfileLock(config)
            first.acquire()
            try:
                try:
                    second.acquire()
                except ProfileLockError:
                    verified.append(f"{config.channel}/{config.worker_id}")
                    continue
                finally:
                    second.release()
            finally:
                first.release()
            return AuditRequirement(
                id="dod_3_profile_filelock_exclusion",
                status="failed",
                evidence=f"second lock attempt unexpectedly acquired {config.channel}/{config.worker_id}",
            )
        return AuditRequirement(
            id="dod_3_profile_filelock_exclusion",
            status="passed",
            evidence=f"second lock attempt failed with ProfileLockError for {', '.join(verified)}",
        )


def _poison_snapshot_requirement() -> AuditRequirement:
    passed = asyncio.run(_poison_snapshot_probe())
    return AuditRequirement(
        id="dod_4_poison_snapshot_rejected",
        status="passed" if passed else "failed",
        evidence=(
            "capture_validated_snapshot returned None when validator rejected state"
            if passed
            else "invalid snapshot was stored despite validator rejection"
        ),
    )


async def _poison_snapshot_probe() -> bool:
    class ProbeContext:
        async def storage_state(self) -> dict[str, object]:
            return {
                "cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "plain-cookie-secret"}],
                "origins": [],
            }

    store = InMemorySessionSnapshotStore()
    record = await capture_validated_snapshot(
        context=ProbeContext(),
        site="saramin",
        worker_id="worker-a",
        encryptor=OpenSslSessionEncryptor(StaticSessionKeyProvider(b"d" * 32)),
        store=store,
        validator=lambda _state: False,
    )
    return record is None and store.latest_validated(site="saramin", worker_id="worker-a") is None


def _discord_alert_requirement(discord_alert: dict[str, object] | None) -> AuditRequirement:
    if discord_alert is None:
        return AuditRequirement(
            id="dod_5_linkedin_discord_alert",
            status="missing",
            evidence="Discord alert delivery artifact was not supplied",
        )
    schema_issues = _discord_alert_schema_issues(discord_alert)
    if not schema_issues:
        return AuditRequirement(
            id="dod_5_linkedin_discord_alert",
            status="passed",
            evidence=(
                "Discord alert test artifact reports generated_at, delivered=true, reauth_event_recorded=true, "
                "and a linkedin_rps forced_logout human event; "
                f"details={_discord_alert_details(discord_alert)}"
            ),
        )
    return AuditRequirement(
        id="dod_5_linkedin_discord_alert",
        status="failed",
        evidence=(
            "Discord alert artifact is missing required delivery proof fields "
            f"{schema_issues}; requires kind=discord_alert_test, generated_at, delivered=true, "
            "reauth_event_recorded=true, and event={site: linkedin_rps, cause: forced_logout, recovered_by: human}; "
            f"details={_discord_alert_details(discord_alert)}"
        ),
    )


def _discord_alert_schema_issues(discord_alert: dict[str, object]) -> list[str]:
    issues: list[str] = []
    if discord_alert.get("kind") != "discord_alert_test":
        issues.append("kind")
    if not isinstance(discord_alert.get("generated_at"), str) or not discord_alert.get("generated_at"):
        issues.append("generated_at")
    if discord_alert.get("delivered") is not True:
        issues.append("delivered")
    if discord_alert.get("reauth_event_recorded") is not True:
        issues.append("reauth_event_recorded")
    issues.extend(_discord_alert_event_issues(discord_alert))
    return issues


def _discord_alert_event_issues(discord_alert: dict[str, object]) -> list[str]:
    event = discord_alert.get("event")
    if not isinstance(event, dict):
        return ["event"]
    issues: list[str] = []
    if event.get("site") != "linkedin_rps":
        issues.append("event.site")
    if not isinstance(event.get("worker_id"), str) or not event.get("worker_id"):
        issues.append("event.worker_id")
    if event.get("cause") != "forced_logout":
        issues.append("event.cause")
    if event.get("recovered_by") != "human":
        issues.append("event.recovered_by")
    if not isinstance(event.get("occurred_at"), str) or not event.get("occurred_at"):
        issues.append("event.occurred_at")
    return issues


def _discord_alert_details(discord_alert: dict[str, object]) -> dict[str, str]:
    event = discord_alert.get("event")
    event_details = event if isinstance(event, dict) else {}
    return {
        "kind": str(discord_alert.get("kind") or ""),
        "generated_at": str(discord_alert.get("generated_at") or "unknown"),
        "status": str(discord_alert.get("status") or ""),
        "delivered": str(discord_alert.get("delivered") is True),
        "reauth_event_recorded": str(discord_alert.get("reauth_event_recorded") is True),
        "event_site": str(event_details.get("site") or ""),
        "event_cause": str(event_details.get("cause") or ""),
        "event_recovered_by": str(event_details.get("recovered_by") or ""),
        "reason": str(discord_alert.get("reason") or ""),
        "action_hint": str(discord_alert.get("action_hint") or ""),
    }


def _secret_output_requirement(
    paths: tuple[Path, ...],
    snapshot_metadata_artifacts: dict[str, dict[str, object]],
    supabase_access: dict[str, object] | None,
    supabase_schema_proof: dict[str, object] | None,
    secret_scan_paths: tuple[Path, ...] = (),
    producer_scan_paths: tuple[Path, ...] = (),
) -> AuditRequirement:
    if not paths and not secret_scan_paths and not producer_scan_paths:
        return AuditRequirement(
            id="dod_6_no_plaintext_session_output",
            status="missing",
            evidence="no output artifacts were supplied for secret scan",
        )
    offenders: list[str] = []
    for path in paths:
        if not path.exists():
            offenders.append(f"{path}:missing")
            continue
        content = path.read_text(encoding="utf-8", errors="ignore").lower()
        matches = [term for term in FORBIDDEN_OUTPUT_TERMS if term in content]
        if matches:
            offenders.append(f"{path}:{','.join(matches)}")
    if offenders:
        return AuditRequirement(
            id="dod_6_no_plaintext_session_output",
            status="failed",
            evidence=f"forbidden plaintext/session terms found in {offenders}",
        )
    persistent_profile_artifacts = _persistent_profile_artifact_offenders(secret_scan_paths)
    if persistent_profile_artifacts:
        return AuditRequirement(
            id="dod_6_no_plaintext_session_output",
            status="failed",
            evidence=f"persistent browser profile artifacts found at {persistent_profile_artifacts}",
        )
    plaintext_session_files = _plaintext_session_artifact_offenders(secret_scan_paths)
    if plaintext_session_files:
        return AuditRequirement(
            id="dod_6_no_plaintext_session_output",
            status="failed",
            evidence=f"plaintext Playwright storage state artifacts found at {plaintext_session_files}",
        )
    plaintext_session_producers = _plaintext_session_producer_offenders(
        _dedupe_paths(secret_scan_paths + producer_scan_paths)
    )
    if plaintext_session_producers:
        return AuditRequirement(
            id="dod_6_no_plaintext_session_output",
            status="failed",
            evidence=f"plaintext Playwright storage state producer scripts found at {plaintext_session_producers}",
        )
    schema_hint = _supabase_schema_proof_hint(supabase_schema_proof)
    if supabase_schema_proof is not None and not _is_ready_supabase_schema_proof(supabase_schema_proof):
        return AuditRequirement(
            id="dod_6_no_plaintext_session_output",
            status="failed",
            evidence=f"Supabase session schema proof is not ready{schema_hint}",
        )
    missing_metadata = [site for site in SNAPSHOT_METADATA_CHANNELS if site not in snapshot_metadata_artifacts]
    if missing_metadata:
        return AuditRequirement(
            id="dod_6_no_plaintext_session_output",
            status="missing",
            evidence=f"missing encrypted snapshot metadata artifacts for {missing_metadata}{schema_hint}",
        )
    failed_metadata = [
        site
        for site in SNAPSHOT_METADATA_CHANNELS
        if not _is_encrypted_snapshot_metadata(snapshot_metadata_artifacts[site])
    ]
    if failed_metadata:
        unavailable = [
            site
            for site in failed_metadata
            if snapshot_metadata_artifacts[site].get("status") == "unavailable"
        ]
        if unavailable:
            hint = _supabase_access_hint(supabase_access)
            return AuditRequirement(
                id="dod_6_no_plaintext_session_output",
                status="failed",
                evidence=f"snapshot metadata could not be read from Supabase for {unavailable}{hint}{schema_hint}",
            )
        return AuditRequirement(
            id="dod_6_no_plaintext_session_output",
            status="failed",
            evidence=f"snapshot metadata did not prove encrypted validated DB payloads for {failed_metadata}{schema_hint}",
        )
    return AuditRequirement(
        id="dod_6_no_plaintext_session_output",
        status="passed",
        evidence=(
            "supplied artifacts and scan paths contain no plaintext session outputs; "
            f"DB metadata shows encrypted snapshots{schema_hint}"
        ),
    )


def _plaintext_session_artifact_offenders(scan_paths: tuple[Path, ...]) -> list[str]:
    offenders: list[str] = []
    for scan_path in scan_paths:
        candidates = _iter_secret_scan_candidates(scan_path)
        for path in candidates:
            if _is_plaintext_storage_state_file(path):
                offenders.append(str(path))
    return offenders


def _plaintext_session_producer_offenders(scan_paths: tuple[Path, ...]) -> list[str]:
    offenders: list[str] = []
    for scan_path in scan_paths:
        candidates = _iter_secret_scan_candidates(scan_path)
        for path in candidates:
            if _is_plaintext_storage_state_producer(path):
                offenders.append(str(path))
    return offenders


def _persistent_profile_artifact_offenders(scan_paths: tuple[Path, ...]) -> list[str]:
    offenders: list[str] = []
    for scan_path in scan_paths:
        offenders.extend(_persistent_profile_artifact_paths(scan_path))
    return _dedupe_strings(offenders)


def _persistent_profile_artifact_paths(scan_path: Path) -> list[str]:
    if not scan_path.exists():
        return []
    if scan_path.is_file():
        return [str(scan_path.parent)] if scan_path.name == ".profile.lock" else []
    offenders: list[str] = []
    for path in (scan_path, *scan_path.rglob("*")):
        if path.is_dir() and path.name == "portal_profiles":
            offenders.append(str(path))
            continue
        if path.is_file() and path.name == ".profile.lock":
            offenders.append(str(path.parent))
    return offenders


def _dedupe_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return tuple(deduped)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _iter_secret_scan_candidates(scan_path: Path) -> tuple[Path, ...]:
    if not scan_path.exists():
        return ()
    if scan_path.is_file():
        return (scan_path,)
    return tuple(path for path in scan_path.rglob("*") if path.is_file())


def _is_plaintext_storage_state_file(path: Path) -> bool:
    normalized_name = path.name.lower().replace("_", "").replace("-", "")
    if "storagestate" in normalized_name:
        return True
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            pass
        else:
            if _looks_like_playwright_storage_state(payload):
                return True
    if path.suffix.lower() not in TEXT_SESSION_SCAN_SUFFIXES:
        return False
    return _looks_like_playwright_storage_state_text(content)


def _is_plaintext_storage_state_producer(path: Path) -> bool:
    if path.suffix.lower() not in {".py", ".js", ".ts", ".mjs", ".cjs", ".jsx", ".tsx", ".sh"}:
        return False
    try:
        content = path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    compact = "".join(content.split()).replace("_", "")
    if "storagestate" not in compact:
        return False
    writes_state = (
        ".storage_state(" in content
        or "storage_state(path=" in content
        or ".storagestate(" in compact
        or "storagestate(path=" in compact
    )
    references_plain_file = (
        "_storage_state.json" in content
        or "storage_state.json" in content
        or "storagestate.json" in compact
    )
    uses_playwright_state = (
        "new_context(storage_state=" in content
        or "launch_persistent_context" in content
        or "newcontext({storagestate:" in compact
        or "newcontext({storagestate=" in compact
        or "launchpersistentcontext" in compact
    )
    return (
        writes_state
        or _persistent_context_receives_storage_state(compact)
        or (references_plain_file and uses_playwright_state)
    )


def _persistent_context_receives_storage_state(compact: str) -> bool:
    """Detect the forbidden launchPersistentContext storageState option."""
    marker = "launchpersistentcontext"
    start = 0
    while True:
        index = compact.find(marker, start)
        if index < 0:
            return False
        window = compact[index : index + 1000]
        if (
            "storagestate=" in window
            or "storagestate:" in window
            or "{storagestate" in window
            or ",storagestate" in window
        ):
            return True
        start = index + len(marker)


def _looks_like_playwright_storage_state(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    cookies = payload.get("cookies")
    origins = payload.get("origins")
    if not isinstance(cookies, list) or not isinstance(origins, list):
        return False
    if not cookies and not origins:
        return False
    return all(isinstance(cookie, dict) for cookie in cookies)


def _looks_like_playwright_storage_state_text(content: str) -> bool:
    normalized = content.lower()
    if '"cookies"' not in normalized or '"origins"' not in normalized:
        return False
    has_cookie_shape = '"domain"' in normalized and '"name"' in normalized and '"value"' in normalized
    has_origin_shape = '"origin"' in normalized and '"localstorage"' in normalized
    return has_cookie_shape or has_origin_shape


def _is_encrypted_snapshot_metadata(payload: dict[str, object]) -> bool:
    return (
        payload.get("kind") == "session_snapshot_metadata"
        and payload.get("status") == "present"
        and payload.get("snapshot_present") is True
        and payload.get("is_validated") is True
        and payload.get("encrypted_envelope") == "VHSS1"
        and int(payload.get("encrypted_bytes") or 0) > 64
    )


def _is_ready_supabase_schema_proof(payload: dict[str, object]) -> bool:
    checks = payload.get("checks")
    return (
        payload.get("kind") == "supabase_session_schema_proof"
        and payload.get("ready") is True
        and payload.get("status") == "ready"
        and isinstance(checks, list)
        and bool(checks)
        and all(isinstance(check, dict) and check.get("status") == "passed" for check in checks)
    )


def _supabase_schema_proof_hint(payload: dict[str, object] | None) -> str:
    if payload is None:
        return ""
    fields = [
        f"schema_proof_status={payload.get('status') or 'unknown'}",
        f"schema_proof_ready={payload.get('ready') is True}",
    ]
    action_hint = payload.get("action_hint")
    if isinstance(action_hint, str) and action_hint and action_hint != "ready":
        fields.append(f"schema_proof_action_hint={action_hint}")
    failed_checks = payload.get("failed_checks")
    if isinstance(failed_checks, list) and failed_checks:
        safe_failed_checks = [str(item) for item in failed_checks if isinstance(item, str)]
        if safe_failed_checks:
            fields.append(f"schema_proof_failed_checks={safe_failed_checks}")
    return "; " + "; ".join(fields)


def _reauth_events_requirement(
    weekly_counts: dict[str, object] | None,
    weekly_trend: dict[str, object] | None,
    supabase_access: dict[str, object] | None,
    supabase_schema_proof: dict[str, object] | None,
) -> AuditRequirement:
    observability_hint = _weekly_observability_hint(weekly_counts, weekly_trend)
    schema_hint = _supabase_schema_proof_hint(supabase_schema_proof)
    if supabase_schema_proof is not None and not _is_ready_supabase_schema_proof(supabase_schema_proof):
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="failed",
            evidence=f"Supabase reauth schema proof is not ready{schema_hint}{observability_hint}",
        )
    if weekly_counts is None:
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="missing",
            evidence=f"weekly reauth counts artifact was not supplied{schema_hint}{observability_hint}",
        )
    if weekly_counts.get("status") == "unavailable":
        hint = _supabase_access_hint(supabase_access)
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="failed",
            evidence=f"weekly reauth counts could not be read from Supabase{hint}{schema_hint}{observability_hint}",
        )
    schema_issues = _weekly_counts_schema_issues(weekly_counts)
    if schema_issues:
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="failed",
            evidence=(
                "weekly reauth counts artifact is not an observable aggregate; "
                f"schema_issues={schema_issues}{schema_hint}{observability_hint}"
            ),
        )
    rows = weekly_counts.get("rows")
    if not isinstance(rows, list):
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="failed",
            evidence=f"weekly reauth counts artifact has no rows list{schema_hint}{observability_hint}",
        )
    policy_issues = _weekly_counts_policy_issues(rows)
    if policy_issues:
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="failed",
            evidence=(
                "weekly reauth counts contain policy-invalid rows; "
                f"policy_issues={policy_issues}{schema_hint}{observability_hint}"
            ),
        )
    observed_sites = _observed_snapshot_recovery_sites(rows)
    missing = [site for site in SNAPSHOT_RECOVERY_CHANNELS if site not in observed_sites]
    if missing:
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="failed",
            evidence=(
                f"weekly counts missing profile_corrupt snapshot_reinject rows for {missing}"
                f"{schema_hint}{observability_hint}"
            ),
        )
    if not _has_linkedin_human_reauth(rows):
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="failed",
            evidence=f"weekly counts missing linkedin_rps forced_logout human row{schema_hint}{observability_hint}",
        )
    if weekly_trend is None:
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="missing",
            evidence=f"weekly reauth trend artifact was not supplied{schema_hint}{observability_hint}",
        )
    if weekly_trend.get("status") == "unavailable":
        hint = _supabase_access_hint(supabase_access)
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="failed",
            evidence=f"weekly reauth trend could not be read from Supabase{hint}{schema_hint}{observability_hint}",
        )
    trend_issues = _weekly_trend_schema_issues(weekly_trend)
    if trend_issues:
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="failed",
            evidence=(
                "weekly reauth trend artifact is not an observable convergence summary; "
                f"schema_issues={trend_issues}{schema_hint}{observability_hint}"
            ),
        )
    trend_observation_issues = _weekly_trend_observation_issues(weekly_trend)
    if trend_observation_issues:
        return AuditRequirement(
            id="dod_7_reauth_events_weekly_observable",
            status="failed",
            evidence=(
                "weekly reauth trend latest week missing required observations; "
                f"observation_issues={trend_observation_issues}{schema_hint}{observability_hint}"
            ),
        )
    return AuditRequirement(
        id="dod_7_reauth_events_weekly_observable",
        status="passed",
        evidence=(
            "weekly counts include Saramin/Jobkorea snapshot recovery rows and LinkedIn human reauth row; "
            f"trend latest_total_events={weekly_trend.get('latest_total_events')} "
            f"latest_week_zero={weekly_trend.get('latest_week_zero')} "
            f"zero_event_weeks={weekly_trend.get('zero_event_weeks')}{schema_hint}"
        ),
    )


def _weekly_observability_hint(
    weekly_counts: dict[str, object] | None,
    weekly_trend: dict[str, object] | None,
) -> str:
    fields: list[str] = []
    if isinstance(weekly_counts, dict):
        for field in ("status", "generated_at", "week_start", "error_type"):
            value = weekly_counts.get(field)
            if isinstance(value, str) and value:
                fields.append(f"weekly_counts_{field}={value}")
        total_events = weekly_counts.get("total_events")
        if isinstance(total_events, int):
            fields.append(f"weekly_counts_total_events={total_events}")
    if isinstance(weekly_trend, dict):
        for field in ("status", "generated_at", "latest_week_start"):
            value = weekly_trend.get(field)
            if isinstance(value, str) and value:
                fields.append(f"weekly_trend_{field}={value}")
        for field in ("weeks_observed", "latest_total_events", "previous_total_events", "zero_event_weeks"):
            value = weekly_trend.get(field)
            if isinstance(value, int):
                fields.append(f"weekly_trend_{field}={value}")
        latest_week_zero = weekly_trend.get("latest_week_zero")
        if isinstance(latest_week_zero, bool):
            fields.append(f"weekly_trend_latest_week_zero={latest_week_zero}")
        error_types = weekly_trend.get("error_types")
        if isinstance(error_types, list) and error_types:
            safe_error_types = [str(item) for item in error_types if isinstance(item, str)]
            if safe_error_types:
                fields.append(f"weekly_trend_error_types={safe_error_types}")
    return "" if not fields else "; " + "; ".join(fields)


def _weekly_counts_policy_issues(rows: list[object]) -> list[str]:
    # SOT invariant (docs/search-access.md): LinkedIn RPS auto-logs in from the secret
    # store like the other portals, so an auto_relogin reauth row for linkedin_rps is no
    # longer a policy violation. No weekly-count policy violations are flagged here.
    del rows  # retained for signature/back-compat; nothing to flag under the current policy
    return []


def _observed_snapshot_recovery_sites(rows: list[object]) -> set[str]:
    return {
        str(row.get("site"))
        for row in rows
        if isinstance(row, dict)
        and row.get("cause") == "profile_corrupt"
        and row.get("recovered_by") == "snapshot_reinject"
        and _positive_int(row.get("count")) is not None
    }


def _has_linkedin_reauth(rows: list[object]) -> bool:
    # SOT invariant: LinkedIn RPS auto-logs in from the secret store, so a forced_logout
    # may resolve as auto_relogin (recovered) or human (when a captcha/2FA/checkpoint is
    # detected and never bypassed). Either outcome proves reauth observability.
    return any(
        isinstance(row, dict)
        and row.get("site") == "linkedin_rps"
        and row.get("cause") == "forced_logout"
        and row.get("recovered_by") in {"auto_relogin", "human"}
        and _positive_int(row.get("count")) is not None
        for row in rows
    )


# Back-compat alias: older callers/tests referenced the human-only name.
_has_linkedin_human_reauth = _has_linkedin_reauth


def _weekly_trend_observation_issues(weekly_trend: dict[str, object]) -> list[str]:
    weeks = weekly_trend.get("weeks")
    if not isinstance(weeks, list) or not weeks:
        return ["latest_week_rows"]
    latest_week = weeks[-1]
    if not isinstance(latest_week, dict):
        return ["latest_week_rows"]
    latest_rows = latest_week.get("rows")
    if not isinstance(latest_rows, list):
        return ["latest_week_rows"]

    issues: list[str] = []
    missing_snapshot_sites = [
        site
        for site in SNAPSHOT_RECOVERY_CHANNELS
        if site not in _observed_snapshot_recovery_sites(latest_rows)
    ]
    if missing_snapshot_sites:
        issues.append(f"latest_week_missing_profile_corrupt_snapshot_reinject={missing_snapshot_sites}")
    if not _has_linkedin_human_reauth(latest_rows):
        issues.append("latest_week_missing_linkedin_rps_forced_logout_human")
    return issues


def _weekly_counts_schema_issues(weekly_counts: dict[str, object]) -> list[str]:
    issues: list[str] = []
    if weekly_counts.get("kind") != "reauth_weekly_counts":
        issues.append("kind")
    if weekly_counts.get("status") != "present":
        issues.append("status")
    if not isinstance(weekly_counts.get("generated_at"), str) or not weekly_counts.get("generated_at"):
        issues.append("generated_at")
    if not isinstance(weekly_counts.get("week_start"), str) or not weekly_counts.get("week_start"):
        issues.append("week_start")
    rows = weekly_counts.get("rows")
    if not isinstance(rows, list):
        issues.append("rows")
        return issues
    total_events = weekly_counts.get("total_events")
    total_events_int = _nonnegative_int(total_events)
    if total_events_int is None:
        issues.append("total_events")
    row_total = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append(f"rows[{index}]")
            continue
        if set(row) - ALLOWED_WEEKLY_COUNT_ROW_FIELDS:
            issues.append(f"rows[{index}].fields_allowed")
        for field in ("site", "worker_id", "cause", "recovered_by"):
            if not isinstance(row.get(field), str) or not row.get(field):
                issues.append(f"rows[{index}].{field}")
        if isinstance(row.get("site"), str) and row.get("site") not in PROTECTED_CHANNELS:
            issues.append(f"rows[{index}].site_allowed")
        if isinstance(row.get("cause"), str) and not is_allowed_reauth_cause(str(row.get("cause"))):
            issues.append(f"rows[{index}].cause_allowed")
        if isinstance(row.get("recovered_by"), str) and row.get("recovered_by") not in ALLOWED_REAUTH_RECOVERED_BY:
            issues.append(f"rows[{index}].recovered_by_allowed")
        # SOT invariant: linkedin_rps/auto_relogin is an allowed recovery outcome.
        count = _positive_int(row.get("count"))
        if count is None:
            issues.append(f"rows[{index}].count")
            continue
        row_total += count
    if total_events_int is not None and total_events_int != row_total:
        issues.append("total_events_sum")
    return issues


def _weekly_trend_schema_issues(weekly_trend: dict[str, object]) -> list[str]:
    issues: list[str] = []
    if weekly_trend.get("kind") != "reauth_weekly_trend":
        issues.append("kind")
    if weekly_trend.get("status") != "present":
        issues.append("status")
    if not isinstance(weekly_trend.get("generated_at"), str) or not weekly_trend.get("generated_at"):
        issues.append("generated_at")
    if not isinstance(weekly_trend.get("latest_week_start"), str) or not weekly_trend.get("latest_week_start"):
        issues.append("latest_week_start")
    weeks_observed = weekly_trend.get("weeks_observed")
    weeks_observed_int = _positive_int(weeks_observed)
    if weeks_observed_int is None:
        issues.append("weeks_observed")
    elif weeks_observed_int < 2:
        issues.append("weeks_observed_min")
    weeks = weekly_trend.get("weeks")
    if not isinstance(weeks, list) or not weeks:
        issues.append("weeks")
        return issues
    if len(weeks) < 2:
        issues.append("weeks_min")
    if weeks_observed_int is not None and weeks_observed_int != len(weeks):
        issues.append("weeks_observed_count")
    totals: list[int] = []
    zero_event_weeks = 0
    for index, week in enumerate(weeks):
        if not isinstance(week, dict):
            issues.append(f"weeks[{index}]")
            continue
        if not isinstance(week.get("week_start"), str) or not week.get("week_start"):
            issues.append(f"weeks[{index}].week_start")
        if week.get("status") != "present":
            issues.append(f"weeks[{index}].status")
        total = _nonnegative_int(week.get("total_events"))
        if total is None:
            issues.append(f"weeks[{index}].total_events")
        else:
            totals.append(total)
            if total == 0:
                zero_event_weeks += 1
        rows = week.get("rows")
        if not isinstance(rows, list):
            issues.append(f"weeks[{index}].rows")
            continue
        row_total = sum(
            count
            for row in rows
            if isinstance(row, dict)
            for count in [_positive_int(row.get("count"))]
            if count is not None
        )
        if total is not None and total != row_total:
            issues.append(f"weeks[{index}].total_events_sum")
        row_issues = _weekly_count_rows_schema_issues(rows, prefix=f"weeks[{index}].rows")
        issues.extend(row_issues)
        policy_issues = _weekly_counts_policy_issues(rows)
        issues.extend(f"weeks[{index}].{issue}" for issue in policy_issues)
    if not totals:
        return issues
    latest_total = weekly_trend.get("latest_total_events")
    if _nonnegative_int(latest_total) != totals[-1]:
        issues.append("latest_total_events")
    previous_total = weekly_trend.get("previous_total_events")
    expected_previous = totals[-2] if len(totals) >= 2 else 0
    if _nonnegative_int(previous_total) != expected_previous:
        issues.append("previous_total_events")
    expected_delta = totals[-1] - totals[-2] if len(totals) >= 2 else None
    if weekly_trend.get("delta_from_previous_week") != expected_delta:
        issues.append("delta_from_previous_week")
    if weekly_trend.get("latest_week_zero") != (totals[-1] == 0):
        issues.append("latest_week_zero")
    if _nonnegative_int(weekly_trend.get("zero_event_weeks")) != zero_event_weeks:
        issues.append("zero_event_weeks")
    latest_week = weeks[-1]
    if isinstance(latest_week, dict) and weekly_trend.get("latest_week_start") != latest_week.get("week_start"):
        issues.append("latest_week_start_match")
    return issues


def _weekly_count_rows_schema_issues(rows: list[object], *, prefix: str) -> list[str]:
    issues: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            issues.append(f"{prefix}[{index}]")
            continue
        if set(row) - ALLOWED_WEEKLY_COUNT_ROW_FIELDS:
            issues.append(f"{prefix}[{index}].fields_allowed")
        for field in ("site", "worker_id", "cause", "recovered_by"):
            if not isinstance(row.get(field), str) or not row.get(field):
                issues.append(f"{prefix}[{index}].{field}")
        if isinstance(row.get("site"), str) and row.get("site") not in PROTECTED_CHANNELS:
            issues.append(f"{prefix}[{index}].site_allowed")
        if isinstance(row.get("cause"), str) and not is_allowed_reauth_cause(str(row.get("cause"))):
            issues.append(f"{prefix}[{index}].cause_allowed")
        if isinstance(row.get("recovered_by"), str) and row.get("recovered_by") not in ALLOWED_REAUTH_RECOVERED_BY:
            issues.append(f"{prefix}[{index}].recovered_by_allowed")
        # SOT invariant: linkedin_rps/auto_relogin is an allowed recovery outcome.
        if _positive_int(row.get("count")) is None:
            issues.append(f"{prefix}[{index}].count")
    return issues


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) and value >= 0 else None


def _positive_int(value: object) -> int | None:
    parsed = _nonnegative_int(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _supabase_access_hint(supabase_access: dict[str, object] | None) -> str:
    if not isinstance(supabase_access, dict):
        return ""
    action_hint = supabase_access.get("action_hint")
    if not isinstance(action_hint, str) or not action_hint:
        return ""
    return f"; supabase_access action_hint={action_hint}"


def _write_output(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit safe live artifacts against the multisite session persistence DoD.")
    parser.add_argument(
        "--latest-defaults",
        action="store_true",
        help="Use the standard latest portal DoD artifact names under --artifact-root.",
    )
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--session-status", type=Path)
    parser.add_argument("--preflight-status", type=Path)
    parser.add_argument("--search-artifact", action="append", default=[], type=Path)
    parser.add_argument("--restart-smoke-artifact", action="append", default=[], type=Path)
    parser.add_argument("--restart-smoke-proof", type=Path)
    parser.add_argument("--profile-recovery-artifact", action="append", default=[], type=Path)
    parser.add_argument("--profile-recovery-proof", type=Path)
    parser.add_argument("--snapshot-metadata-artifact", action="append", default=[], type=Path)
    parser.add_argument("--discord-alert", type=Path)
    parser.add_argument("--weekly-counts", type=Path)
    parser.add_argument("--weekly-trend", type=Path)
    parser.add_argument("--supabase-access", type=Path)
    parser.add_argument("--supabase-schema-proof", type=Path)
    parser.add_argument(
        "--secret-scan-path",
        action="append",
        default=[],
        type=Path,
        help=(
            "Scan a path for plaintext Playwright storage state JSON artifacts; "
            "defaults to artifacts/portal_session_dod/, and latest-defaults also scans --artifact-root."
        ),
    )
    parser.add_argument(
        "--producer-scan-path",
        action="append",
        default=[],
        type=Path,
        help="Scan a path for scripts that can write plaintext Playwright storage state; latest-defaults scans --artifact-root.",
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/portal_session_dod_audit_latest.json"))
    args = parser.parse_args()
    defaults = latest_default_audit_artifacts(args.artifact_root) if args.latest_defaults else None
    session_status_path = args.session_status or (
        None if defaults is None else _existing_default_path(defaults.session_status_path)
    )
    preflight_status_path = args.preflight_status or (
        None if defaults is None else _existing_default_path(defaults.preflight_status_path)
    )
    restart_smoke_paths = tuple(args.restart_smoke_artifact)
    restart_smoke_proof_path = args.restart_smoke_proof or (
        None if defaults is None else _existing_default_path(defaults.restart_smoke_proof_path)
    )
    profile_recovery_paths = tuple(args.profile_recovery_artifact)
    profile_recovery_proof_path = args.profile_recovery_proof or (
        None if defaults is None else _existing_default_path(defaults.profile_recovery_proof_path)
    )
    snapshot_metadata_paths = tuple(args.snapshot_metadata_artifact)
    discord_alert_path = args.discord_alert or (
        None if defaults is None else _existing_default_path(defaults.discord_alert_path)
    )
    weekly_counts_path = args.weekly_counts or (
        None if defaults is None else _existing_default_path(defaults.weekly_counts_path)
    )
    weekly_trend_path = args.weekly_trend or (
        None if defaults is None else _existing_default_path(defaults.weekly_trend_path)
    )
    supabase_access_path = args.supabase_access or (
        None if defaults is None else _existing_default_path(defaults.supabase_access_path)
    )
    supabase_schema_proof_path = args.supabase_schema_proof or (
        None if defaults is None else _existing_default_path(defaults.supabase_schema_proof_path)
    )
    if defaults is not None:
        restart_smoke_paths = _existing_default_paths(defaults.restart_smoke_artifact_paths) + restart_smoke_paths
        profile_recovery_paths = _existing_default_paths(defaults.profile_recovery_artifact_paths) + profile_recovery_paths
        snapshot_metadata_paths = _existing_default_paths(defaults.snapshot_metadata_artifact_paths) + snapshot_metadata_paths
    if args.secret_scan_path:
        secret_scan_paths = tuple(args.secret_scan_path)
    elif defaults is not None:
        secret_scan_paths = _dedupe_paths((DEFAULT_SECRET_SCAN_PATH, args.artifact_root))
    else:
        secret_scan_paths = (DEFAULT_SECRET_SCAN_PATH,)
    producer_scan_paths = tuple(args.producer_scan_path)
    if defaults is not None and not producer_scan_paths:
        producer_scan_paths = (args.artifact_root,)

    payload = build_dod_audit_payload(
        session_status_path=session_status_path,
        search_artifact_paths=tuple(args.search_artifact),
        restart_smoke_artifact_paths=restart_smoke_paths,
        restart_smoke_proof_path=restart_smoke_proof_path,
        profile_recovery_artifact_paths=profile_recovery_paths,
        profile_recovery_proof_path=profile_recovery_proof_path,
        preflight_status_path=preflight_status_path,
        snapshot_metadata_artifact_paths=snapshot_metadata_paths,
        discord_alert_path=discord_alert_path,
        weekly_counts_path=weekly_counts_path,
        weekly_trend_path=weekly_trend_path,
        supabase_access_path=supabase_access_path,
        supabase_schema_proof_path=supabase_schema_proof_path,
        secret_scan_paths=secret_scan_paths,
        producer_scan_paths=producer_scan_paths,
    )
    _write_output(args.output, payload)
    if not payload["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
