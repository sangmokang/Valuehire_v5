"""Pure, deterministic fleet routing from one complete browser snapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .fleet_heartbeat import normalize_machine_hostname
from .login_barrier import RECEIPT_MAX_AGE_SECONDS

_AUTH_TARGET_MARKERS = {
    "saramin": {"authenticated_shell", "gnb_profile_badge", "account_or_logout"},
    "jobkorea": {"authenticated_shell", "gnb_profile_badge", "logout_and_account"},
    "linkedin_rps": {"authenticated_shell", "recruiter_marker"},
}


def _decision(
    machine: str | None, reason: str, snapshot_id: str, evidence: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "selected_machine": machine,
        "reason": reason,
        "evidence_refs": list(evidence),
        "snapshot_id": snapshot_id,
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


def _target_hosts(
    reports: Mapping[str, Any], site: str,
) -> tuple[dict[str, list[str]], bool]:
    hosts: dict[str, list[str]] = {}
    conflict = False
    for machine, report in reports.items():
        if not isinstance(report, Mapping):
            continue
        inventory = report.get("inventory")
        if not isinstance(inventory, list):
            continue
        for browser in inventory:
            if not isinstance(browser, Mapping):
                continue
            targets = browser.get("targets")
            if not isinstance(targets, list):
                continue
            for target in targets:
                if not isinstance(target, Mapping) or target.get("site") != site:
                    continue
                markers = target.get("marker_names")
                if not isinstance(markers, list) or not markers:
                    continue
                if {"auth_conflict", "multiple_sign_in"}.intersection(markers):
                    conflict = True
                    continue
                if not set(markers).intersection(_AUTH_TARGET_MARKERS.get(site, set())):
                    continue
                target_id = target.get("target_id")
                hosts.setdefault(str(machine), []).append(
                    f"target:{machine}:{target_id}"
                )
    return hosts, conflict


def _receipt_hosts(
    receipts: Sequence[Mapping[str, Any]],
    *,
    site: str,
    requested_at: datetime,
    ready_machines: set[str],
) -> tuple[dict[str, list[str]], bool, bool, bool]:
    hosts: dict[str, list[str]] = {}
    stale = False
    conflict = False
    invalid_host = False
    for receipt in receipts:
        if not isinstance(receipt, Mapping) or receipt.get("channel") != site:
            continue
        if receipt.get("schema_version") != 1:
            invalid_host = True
            continue
        if receipt.get("state") == "AUTH_CONFLICT":
            conflict = True
            continue
        if receipt.get("state") != "AUTHENTICATED" or receipt.get("ready") is not True:
            continue
        host = receipt.get("host")
        if not isinstance(host, str) or host not in ready_machines:
            invalid_host = True
            continue
        verified = _utc(receipt.get("last_verified_at"))
        age = (
            (requested_at - verified).total_seconds()
            if verified is not None else RECEIPT_MAX_AGE_SECONDS + 1
        )
        if age < 0 or age > RECEIPT_MAX_AGE_SECONDS:
            stale = True
            continue
        hosts.setdefault(host, []).append(
            f"receipt:{host}:{receipt.get('target_id')}"
        )
    return hosts, stale, conflict, invalid_host


def decide_fleet_route(
    *,
    normalized_request: Mapping[str, Any],
    fleet_snapshot: Mapping[str, Any],
    login_receipts: Sequence[Mapping[str, Any]],
    site_role_defaults: Mapping[str, str],
) -> dict[str, Any]:
    """Return one RouteDecision without queue, browser, retry, or other effects."""
    snapshot_id = str(fleet_snapshot.get("snapshot_id") or "")
    if normalized_request.get("lookup_error") is True or fleet_snapshot.get("complete") is not True:
        return _decision(None, "DISCOVERY_INCOMPLETE", snapshot_id)
    requested_at = _utc(fleet_snapshot.get("requested_at"))
    reports = fleet_snapshot.get("reports_by_machine")
    if requested_at is None or not snapshot_id or not isinstance(reports, Mapping):
        return _decision(None, "DISCOVERY_INCOMPLETE", snapshot_id)
    ready_machines = {
        machine for machine in reports
        if isinstance(machine, str) and normalize_machine_hostname(machine) == machine
    }
    if len(ready_machines) != len(reports):
        return _decision(None, "DISCOVERY_INCOMPLETE", snapshot_id)
    if not ready_machines:
        return _decision(None, "DISCOVERY_INCOMPLETE", snapshot_id)

    site = str(normalized_request.get("site") or "")
    request_id = str(normalized_request.get("request_id") or "")
    target_hosts, target_conflict = _target_hosts(reports, site)
    receipt_hosts, stale, receipt_conflict, invalid_host = _receipt_hosts(
        login_receipts, site=site, requested_at=requested_at,
        ready_machines=ready_machines,
    )
    if invalid_host:
        return _decision(None, "ROUTE_AMBIGUOUS", snapshot_id)
    auth_hosts = set(target_hosts) | set(receipt_hosts)
    if site != "linkedin_rps" and (target_conflict or receipt_conflict):
        return _decision(None, "AUTH_CONFLICT", snapshot_id)
    if site == "linkedin_rps":
        from .linkedin_session_guardian import decide_linkedin_session

        default = site_role_defaults.get(site)
        selected = normalized_request.get("requested_machine")
        if selected not in ready_machines:
            selected = default if default in ready_machines else sorted(ready_machines)[0]
        observations = {
            machine: {
                "state": (
                    "AUTH_CONFLICT" if (target_conflict or receipt_conflict)
                    and machine == sorted(ready_machines)[0]
                    else "AUTHENTICATED" if machine in auth_hosts
                    else "AUTH_LOST"
                ),
                "ready": True,
                "evidence_ref": (
                    target_hosts.get(machine) or receipt_hosts.get(machine)
                    or [f"snapshot:{snapshot_id}:{machine}"]
                )[0],
            }
            for machine in ready_machines
        }
        session_decision = decide_linkedin_session(
            request_id=request_id,
            fleet_observations={
                "request_id": request_id,
                "complete": True,
                "eligible_machines": sorted(ready_machines),
                "missing_machines": [],
                "observations_by_machine": observations,
            },
            selected_machine=selected,
        )
        if session_decision["state"] == "AUTH_CONFLICT":
            return _decision(None, "AUTH_CONFLICT", snapshot_id,
                             session_decision["evidence_refs"])

    explicit = normalized_request.get("requested_machine")
    if explicit:
        canonical = normalize_machine_hostname(explicit)
        delegated = normalized_request.get("delegated_for_request_id")
        valid = (
            isinstance(explicit, str)
            and canonical == explicit
            and explicit in ready_machines
            and (explicit != "winpc" or delegated == request_id)
        )
        if not valid:
            return _decision(None, "INVALID_MACHINE", snapshot_id)
        return _decision(
            explicit, "EXPLICIT_MACHINE", snapshot_id,
            ["request:explicit_machine"],
        )

    if len(receipt_hosts) > 1:
        reason = "AUTH_CONFLICT" if site == "linkedin_rps" else "ROUTE_AMBIGUOUS"
        return _decision(None, reason, snapshot_id)
    if receipt_hosts:
        host = next(iter(receipt_hosts))
        return _decision(host, "FRESH_RECEIPT", snapshot_id, receipt_hosts[host])
    if len(target_hosts) > 1:
        reason = "AUTH_CONFLICT" if site == "linkedin_rps" else "ROUTE_AMBIGUOUS"
        return _decision(None, reason, snapshot_id)
    if target_hosts:
        host = next(iter(target_hosts))
        return _decision(
            host, "AUTHENTICATED_EXACT_TARGET", snapshot_id, target_hosts[host],
        )

    default = site_role_defaults.get(site)
    if isinstance(default, str) and default in ready_machines:
        return _decision(
            default, "SITE_ROLE_DEFAULT", snapshot_id, [f"default:{site}"],
        )
    if stale:
        return _decision(None, "STALE_RECEIPT", snapshot_id)
    return _decision(None, "NO_READY_MACHINE", snapshot_id)
