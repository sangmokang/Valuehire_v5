"""Deterministic aggregation of integrity-checked, sanitized browser reports."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from .fleet_heartbeat import normalize_machine_hostname

REPORT_SCHEMA_VERSION = 1
REPORT_MAX_AGE_SECONDS = 120
_REPORT_KEYS = frozenset({"machine_id", "captured_at", "schema_version",
                          "request_id", "inventory"})
_INVENTORY_KEYS = (
    "browser_pid", "executable", "profile_path", "declared_port", "listen_pid",
    "endpoint", "endpoint_live", "targets", "issues",
)
_TARGET_KEYS = ("target_id", "type", "sanitized_url", "site", "marker_names")


class FleetSnapshotError(ValueError):
    pass


def _safe_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.hostname:
        return ""
    netloc = parsed.hostname
    if port is not None:
        netloc += f":{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _is_local_endpoint(value: Any) -> bool:
    try:
        parsed = urlsplit(value) if isinstance(value, str) else None
        return bool(
            parsed and parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
            and parsed.port and parsed.path in {"", "/"}
            and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def _sanitize_report(report: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = {key: report.get(key) for key in _REPORT_KEYS}
    inventory: list[dict[str, Any]] = []
    raw_inventory = report.get("inventory")
    if isinstance(raw_inventory, list):
        for raw_browser in raw_inventory:
            if not isinstance(raw_browser, Mapping):
                continue
            browser = {key: raw_browser.get(key) for key in _INVENTORY_KEYS}
            if not _is_local_endpoint(browser.get("endpoint")):
                browser["endpoint"] = None
            targets: list[dict[str, Any]] = []
            raw_targets = raw_browser.get("targets")
            if isinstance(raw_targets, list):
                for raw_target in raw_targets:
                    if isinstance(raw_target, Mapping) and raw_target.get("type") == "page":
                        target = {key: raw_target.get(key) for key in _TARGET_KEYS}
                        target["sanitized_url"] = _safe_url(target.get("sanitized_url"))
                        targets.append(target)
            browser["targets"] = targets
            inventory.append(browser)
    sanitized["inventory"] = inventory
    return sanitized


def seal_browser_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlist the App 03 output and add a deterministic integrity hash."""
    raw = {key: value for key, value in report.items() if key != "integrity_hash"}
    sanitized = _sanitize_report(raw)
    return {**sanitized, "integrity_hash": _hash(sanitized)}


def _strict_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed


def _verified_payload(wrapper: Mapping[str, Any]) -> dict[str, Any]:
    source = wrapper.get("source_machine_id")
    payload = wrapper.get("payload")
    if not isinstance(source, str) or not isinstance(payload, Mapping):
        raise FleetSnapshotError("REPORT_HOST_MISMATCH")
    raw = {key: value for key, value in payload.items() if key != "integrity_hash"}
    sealed = seal_browser_report(raw)
    if (
        payload.get("integrity_hash") != sealed["integrity_hash"]
        or set(raw) != _REPORT_KEYS
        or raw != {key: sealed[key] for key in _REPORT_KEYS}
    ):
        raise FleetSnapshotError("SNAPSHOT_CONFLICT")
    if payload.get("machine_id") != source:
        raise FleetSnapshotError("REPORT_HOST_MISMATCH")
    if payload.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise FleetSnapshotError("REPORT_SCHEMA_MISMATCH")
    return dict(payload)


def aggregate_fleet_snapshot(
    *,
    expected_machine_ids: Sequence[str],
    machine_readiness: Sequence[Mapping[str, Any]],
    reports: Sequence[Mapping[str, Any]],
    request_id: str,
    requested_at: datetime,
    required_capability: str,
) -> dict[str, Any]:
    """Create one deterministic point-in-time snapshot; never choose a machine."""
    expected = list(expected_machine_ids)
    if (
        not request_id or not expected
        or requested_at.tzinfo is None
        or requested_at.utcoffset() != timezone.utc.utcoffset(requested_at)
        or len(expected) != len(set(expected))
        or any(normalize_machine_hostname(item) != item for item in expected)
    ):
        raise FleetSnapshotError("DISCOVERY_INCOMPLETE")
    readiness = {
        row.get("machine_id"): row
        for row in machine_readiness
        if isinstance(row, Mapping) and isinstance(row.get("machine_id"), str)
    }

    accepted: dict[str, dict[str, Any]] = {}
    stale: set[str] = set()
    seen_hashes: dict[str, str] = {}
    reported_for_request: set[str] = set()
    for wrapper in reports:
        payload = _verified_payload(wrapper)
        machine_id = payload["machine_id"]
        if machine_id not in expected:
            raise FleetSnapshotError("REPORT_HOST_MISMATCH")
        if payload.get("request_id") != request_id:
            continue
        reported_for_request.add(machine_id)
        integrity_hash = payload["integrity_hash"]
        previous = seen_hashes.get(machine_id)
        if previous is not None and previous != integrity_hash:
            raise FleetSnapshotError("SNAPSHOT_CONFLICT")
        seen_hashes[machine_id] = integrity_hash
        captured = _strict_utc(payload.get("captured_at"))
        age = (
            (requested_at - captured).total_seconds()
            if captured is not None else REPORT_MAX_AGE_SECONDS + 1
        )
        if age < 0 or age > REPORT_MAX_AGE_SECONDS:
            stale.add(machine_id)
            continue
        ready = readiness.get(machine_id)
        if (
            not isinstance(ready, Mapping)
            or ready.get("registered") is not True
            or ready.get("online") is not True
            or required_capability not in (ready.get("capabilities") or [])
        ):
            continue
        accepted[machine_id] = {
            key: value for key, value in payload.items() if key != "integrity_hash"}

    missing = [item for item in expected if item not in reported_for_request]
    stale_ordered = [item for item in expected if item in stale]
    reports_by_machine = {
        item: accepted[item] for item in expected if item in accepted
    }
    complete = len(reports_by_machine) == len(expected) and not missing and not stale_ordered
    sanitized_hash = _hash(reports_by_machine)
    requested_iso = requested_at.isoformat()
    blocking = (["DISCOVERY_INCOMPLETE"] if missing or len(accepted) < len(expected)
                else []) + (["REPORT_STALE"] if stale_ordered else [])
    snapshot_hash = _hash(
        {"request_id": request_id, "requested_at": requested_iso,
         "expected": expected, "reports_hash": sanitized_hash})
    return {
        "snapshot_id": f"fleet_{snapshot_hash[:24]}",
        "requested_at": requested_iso,
        "complete": complete,
        "missing_machines": missing,
        "stale_machines": stale_ordered,
        "reports_by_machine": reports_by_machine,
        "sanitized_hash": sanitized_hash,
        "blocking_reasons": blocking,
    }
