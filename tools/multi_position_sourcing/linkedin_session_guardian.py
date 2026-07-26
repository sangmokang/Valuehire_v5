"""Pure LinkedIn Recruiter single-seat decision over one complete fleet view."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_KNOWN_STATES = {
    "AUTHENTICATED", "AUTH_LOST", "AUTH_UNKNOWN", "SELECTOR_DRIFT",
    "HUMAN_AUTH_REQUIRED", "AUTH_CONFLICT",
}


def _decision(
    state: str,
    reason: str,
    *,
    host: str | None = None,
    evidence: list[str] | None = None,
    mutation: bool = False,
) -> dict[str, Any]:
    return {
        "state": state,
        "session_host": host,
        "reason": reason,
        "evidence_refs": evidence or [],
        "login_mutation_allowed": mutation,
    }


def decide_linkedin_session(
    *,
    request_id: str,
    fleet_observations: Mapping[str, Any],
    selected_machine: str | None,
) -> dict[str, Any]:
    """Choose reuse/one login host without browser, cookie, or retry effects."""
    eligible = fleet_observations.get("eligible_machines")
    rows = fleet_observations.get("observations_by_machine")
    missing = fleet_observations.get("missing_machines")
    if (
        not request_id
        or fleet_observations.get("request_id") != request_id
        or fleet_observations.get("complete") is not True
        or not isinstance(eligible, list)
        or not eligible
        or len(eligible) != len(set(eligible))
        or not all(isinstance(machine, str) and machine for machine in eligible)
        or not isinstance(rows, Mapping)
        or set(rows) != set(eligible)
        or not isinstance(missing, list)
        or missing
    ):
        return _decision("DISCOVERY_INCOMPLETE", "DISCOVERY_INCOMPLETE")

    authenticated: list[str] = []
    human_auth_hosts: list[str] = []
    evidence_by_host: dict[str, str] = {}
    for machine in eligible:
        row = rows.get(machine)
        if not isinstance(row, Mapping):
            return _decision("DISCOVERY_INCOMPLETE", "DISCOVERY_INCOMPLETE")
        state = row.get("state")
        if state not in _KNOWN_STATES:
            return _decision("DISCOVERY_INCOMPLETE", "DISCOVERY_INCOMPLETE")
        ref = row.get("evidence_ref")
        if isinstance(ref, str) and ref:
            evidence_by_host[machine] = ref
        blocks = row.get("block_names")
        if state == "AUTH_CONFLICT" or (
            isinstance(blocks, list) and "multiple_sign_in" in blocks
        ):
            return _decision(
                "AUTH_CONFLICT", "MULTIPLE_SIGN_IN",
                evidence=[evidence_by_host[machine]]
                if machine in evidence_by_host else [],
            )
        if state == "AUTHENTICATED":
            authenticated.append(machine)
        elif state == "HUMAN_AUTH_REQUIRED":
            human_auth_hosts.append(machine)
        elif state in {"AUTH_UNKNOWN", "SELECTOR_DRIFT"}:
            return _decision("DISCOVERY_INCOMPLETE", "DISCOVERY_INCOMPLETE")

    if len(authenticated) > 1:
        return _decision(
            "AUTH_CONFLICT", "MULTIPLE_AUTHENTICATED_HOSTS",
            evidence=[
                evidence_by_host[machine] for machine in authenticated
                if machine in evidence_by_host
            ],
        )
    if authenticated:
        host = authenticated[0]
        if rows[host].get("ready") is not True:
            return _decision(
                "SESSION_HOST_UNREADY", "SESSION_HOST_UNREADY", host=host,
                evidence=[evidence_by_host[host]]
                if host in evidence_by_host else [],
            )
        return _decision(
            "SESSION_REUSE", "EXISTING_AUTHENTICATED_HOST", host=host,
            evidence=[evidence_by_host[host]] if host in evidence_by_host else [],
        )
    if human_auth_hosts:
        return _decision(
            "SESSION_HOST_UNREADY", "HUMAN_AUTH_PENDING",
            host=human_auth_hosts[0],
            evidence=[
                evidence_by_host[machine] for machine in human_auth_hosts
                if machine in evidence_by_host
            ],
        )
    selected = rows.get(selected_machine) if selected_machine in rows else None
    if (
        not isinstance(selected, Mapping)
        or selected.get("ready") is not True
    ):
        return _decision("SESSION_HOST_UNREADY", "SELECTED_MACHINE_UNREADY")
    return _decision(
        "LOGIN_ALLOWED", "NO_AUTHENTICATED_HOST",
        evidence=[evidence_by_host[selected_machine]]
        if selected_machine in evidence_by_host else [],
        mutation=True,
    )
