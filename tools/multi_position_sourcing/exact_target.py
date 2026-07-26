"""Resolve one existing page target without attaching to or mutating a browser."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .fleet_heartbeat import normalize_machine_hostname

_SITE_HOSTS = {
    "saramin": ("saramin.co.kr",),
    "jobkorea": ("jobkorea.co.kr",),
    "linkedin_rps": ("linkedin.com",),
}
_AUTH_MARKERS = frozenset({
    "authenticated_shell", "account_or_logout", "logout_and_account",
    "recruiter_account", "gnb_account_marker",
})


class ExactTargetError(ValueError):
    pass


def inventory_hash(inventory: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps(
        inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _safe_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    netloc = parsed.hostname + (f":{port}" if port is not None else "")
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _official(site: str, value: Any) -> bool:
    url = _safe_url(value)
    try:
        host = (urlsplit(url).hostname or "").casefold()
    except ValueError:
        return False
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in _SITE_HOSTS.get(site, ())
    )


def _local_endpoint(value: Any) -> bool:
    try:
        parsed = urlsplit(value) if isinstance(value, str) else None
        return bool(
            parsed and parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1" and parsed.port
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
        )
    except ValueError:
        return False


def _live_target(
    endpoint: str,
    target: Mapping[str, Any],
    observations: Mapping[str, Any],
) -> Mapping[str, Any]:
    observation = observations.get(endpoint)
    if not isinstance(observation, Mapping):
        raise ExactTargetError("ENDPOINT_CONFLICT")
    targets = observation.get("targets")
    if not isinstance(targets, list):
        raise ExactTargetError("ENDPOINT_CONFLICT")
    target_id = target.get("target_id")
    matches = [
        item for item in targets
        if isinstance(item, Mapping)
        and (item.get("target_id") or item.get("id")) == target_id
    ]
    if len(matches) > 1:
        raise ExactTargetError("TARGET_AMBIGUOUS")
    if not matches:
        raise ExactTargetError("TARGET_IDENTITY_CHANGED")
    live = matches[0]
    if live.get("type") != "page":
        raise ExactTargetError("TARGET_IDENTITY_CHANGED")
    live_url = _safe_url(live.get("sanitized_url") or live.get("url"))
    if live_url != _safe_url(target.get("sanitized_url")):
        raise ExactTargetError("TARGET_IDENTITY_CHANGED")
    return live


def _candidate(
    machine: str,
    browser: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    site: str,
    expected_profile: str | None,
    expected_role: str | None,
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    endpoint = browser.get("endpoint")
    issues = browser.get("issues")
    if (
        browser.get("endpoint_live") is not True
        or not _local_endpoint(endpoint)
        or browser.get("listen_pid") != browser.get("browser_pid")
        or (isinstance(issues, list) and bool(issues))
    ):
        raise ExactTargetError("ENDPOINT_CONFLICT")
    if expected_profile is not None and browser.get("profile_path") != expected_profile:
        raise ExactTargetError("TARGET_IDENTITY_CHANGED")
    if expected_role is not None and browser.get("role") != expected_role:
        raise ExactTargetError("TARGET_IDENTITY_CHANGED")
    _live_target(str(endpoint), target, observations)
    return {
        "machine": machine,
        "browser_pid": browser.get("browser_pid"),
        "profile_path": browser.get("profile_path"),
        "cdp_endpoint": endpoint,
        "target_id": target.get("target_id"),
        "site": site,
        "sanitized_url": _safe_url(target.get("sanitized_url")),
    }


def resolve_exact_target(
    *,
    machine: str,
    site: str,
    target_id: str | None,
    expected_profile: str | None,
    expected_role: str | None,
    browser_inventory: Sequence[Mapping[str, Any]],
    expected_inventory_hash: str,
    endpoint_observations: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one immutable attach-preparation record or one explicit blocker."""
    current_hash = inventory_hash(browser_inventory)
    if current_hash != expected_inventory_hash:
        raise ExactTargetError("TARGET_IDENTITY_CHANGED")
    if normalize_machine_hostname(machine) != machine or site not in _SITE_HOSTS:
        raise ExactTargetError("TARGET_SITE_MISMATCH")
    endpoints = [
        browser.get("endpoint") for browser in browser_inventory
        if isinstance(browser, Mapping) and browser.get("endpoint") is not None
    ]
    if len(endpoints) != len(set(endpoints)):
        raise ExactTargetError("ENDPOINT_CONFLICT")

    all_targets: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for browser in browser_inventory:
        if not isinstance(browser, Mapping):
            continue
        targets = browser.get("targets")
        if not isinstance(targets, list):
            continue
        for target in targets:
            if isinstance(target, Mapping) and target.get("type") == "page":
                all_targets.append((browser, target))
    if target_id is not None:
        matches = [
            pair for pair in all_targets if pair[1].get("target_id") == target_id
        ]
        if not matches:
            raise ExactTargetError("TARGET_IDENTITY_CHANGED")
        if len(matches) > 1:
            raise ExactTargetError("TARGET_AMBIGUOUS")
        browser, target = matches[0]
        if target.get("site") != site or not _official(site, target.get("sanitized_url")):
            raise ExactTargetError("TARGET_SITE_MISMATCH")
        selected = _candidate(
            machine, browser, target, site=site,
            expected_profile=expected_profile, expected_role=expected_role,
            observations=endpoint_observations,
        )
        return {
            **selected, "selection_reason": "EXPLICIT_TARGET_ID",
            "inventory_hash": current_hash,
        }

    site_targets = [
        pair for pair in all_targets
        if pair[1].get("site") == site
        and _official(site, pair[1].get("sanitized_url"))
    ]
    if not site_targets:
        if all_targets:
            raise ExactTargetError("TARGET_SITE_MISMATCH")
        raise ExactTargetError("TARGET_MISSING")

    def markers(pair: tuple[Mapping[str, Any], Mapping[str, Any]]) -> set[str]:
        raw = pair[1].get("marker_names")
        return {item for item in raw if isinstance(item, str)} if isinstance(raw, list) else set()

    priorities = [
        ("FRESH_AUTH_MARKER", [
            pair for pair in site_targets if markers(pair) & _AUTH_MARKERS
        ]),
        ("VERIFIED_LOGIN_FORM", [
            pair for pair in site_targets if "verified_login_form" in markers(pair)
        ]),
        ("EXACT_PROFILE", [
            pair for pair in site_targets
            if expected_profile is not None
            and pair[0].get("profile_path") == expected_profile
            and (expected_role is None or pair[0].get("role") == expected_role)
        ]),
    ]
    for reason, candidates in priorities:
        if len(candidates) > 1:
            raise ExactTargetError("TARGET_AMBIGUOUS")
        if len(candidates) == 1:
            browser, target = candidates[0]
            selected = _candidate(
                machine, browser, target, site=site,
                expected_profile=expected_profile if reason == "EXACT_PROFILE" else None,
                expected_role=expected_role if reason == "EXACT_PROFILE" else None,
                observations=endpoint_observations,
            )
            return {
                **selected, "selection_reason": reason,
                "inventory_hash": current_hash,
            }
    if len(site_targets) > 1:
        raise ExactTargetError("TARGET_AMBIGUOUS")
    raise ExactTargetError("TARGET_MISSING")


def exact_target_session_guard_args(
    exact_target: Mapping[str, Any], *, agent: str,
) -> list[str]:
    """Pass only the already selected target id to the existing session guard."""
    site = exact_target.get("site")
    target_id = exact_target.get("target_id")
    if site not in _SITE_HOSTS or not isinstance(target_id, str) or not target_id:
        raise ExactTargetError("TARGET_IDENTITY_CHANGED")
    return [
        "human-auth", "--site", str(site), "--agent", str(agent),
        "--target-id", target_id,
    ]
