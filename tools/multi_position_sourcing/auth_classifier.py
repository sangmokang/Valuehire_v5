"""Pure, data-driven authentication classifier over boolean DOM evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

AUTH_RULES: dict[str, dict[str, Any]] = {
    "saramin": {
        "hosts": ("saramin.co.kr",),
        "required": (
            "account_or_logout", "search_input", "career_min", "career_max",
        ),
        "proofs": (
            "account_or_logout", "search_input", "career_min", "career_max",
        ),
    },
    "jobkorea": {
        "hosts": ("jobkorea.co.kr",),
        "required": ("logout", "company_account", "talent_search"),
        "proofs": ("logout", "company_account", "talent_search"),
    },
    "linkedin_rps": {
        "hosts": ("linkedin.com",),
        "required": ("recruiter_marker",),
        "proofs": ("talent_surface", "recruiter_marker"),
    },
}
_COMMON_MARKERS = ("challenge_control", "multiple_sign_in")
_CHALLENGE_PATH = re.compile(
    r"/(?:checkpoint|uas/login-cap|authwall)(?:/|$)|"
    r"/enterprise-authentication/(?!sessions(?:/|$))",
)
_CONFLICT_PATH = re.compile(r"/enterprise-authentication/sessions(?:/|$)")


def _safe_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme != "https" or not parsed.hostname:
        return ""
    netloc = parsed.hostname.casefold() + (
        f":{port}" if port not in {None, 443} else ""
    )
    return urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))


def _official(site: str, url: str) -> bool:
    rule = AUTH_RULES.get(site)
    if rule is None:
        return False
    try:
        host = (urlsplit(url).hostname or "").casefold()
    except ValueError:
        return False
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in rule["hosts"]
    )


def _strict_utc(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return (
        parsed.tzinfo is not None
        and parsed.utcoffset() == timezone.utc.utcoffset(parsed)
    )


def classify_auth_observation(
    *,
    site: str,
    target_id_before: str,
    target_id_after: str,
    url_before: str,
    url_after: str,
    markers: Mapping[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    """Return only state, boolean evidence names, identity and sanitized URLs."""
    before = _safe_url(url_before)
    after = _safe_url(url_after)

    def result(
        state: str,
        *,
        proofs: list[str] | None = None,
        blocks: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "state": state,
            "proof_names": proofs or [],
            "block_names": blocks or [],
            "observed_at": observed_at,
            "target_id": target_id_after,
            "url_before": before,
            "url_after": after,
        }

    if (
        not isinstance(target_id_before, str)
        or not target_id_before
        or not isinstance(target_id_after, str)
        or not target_id_after
        or url_before != url_after
        or before != after
        or target_id_before != target_id_after
    ):
        return result(
            "TARGET_CHANGED_DURING_PROBE",
            blocks=["target_or_url_changed"],
        )
    rule = AUTH_RULES.get(site)
    if (
        rule is None
        or not _official(site, after)
        or not _strict_utc(observed_at)
        or not isinstance(markers, Mapping)
    ):
        return result("AUTH_UNKNOWN", blocks=["invalid_observation"])

    required_keys = (*rule["required"], *_COMMON_MARKERS)
    drift = [
        key for key in required_keys
        if key not in markers or not isinstance(markers.get(key), bool)
    ]
    if drift:
        return result("SELECTOR_DRIFT", blocks=drift)

    path = urlsplit(after).path.casefold()
    conflict = (
        site == "linkedin_rps"
        and (
            markers["multiple_sign_in"] is True
            or _CONFLICT_PATH.search(path) is not None
        )
    )
    if conflict:
        return result("AUTH_CONFLICT", blocks=["multiple_sign_in"])
    if markers["challenge_control"] is True:
        return result(
            "HUMAN_AUTH_REQUIRED", blocks=["challenge_control"],
        )
    if _CHALLENGE_PATH.search(path):
        return result("AUTH_LOST", blocks=["challenge_path"])

    proofs: list[str] = []
    if site == "linkedin_rps" and path.startswith("/talent/"):
        proofs.append("talent_surface")
    proofs.extend(
        key for key in rule["required"] if markers.get(key) is True
    )
    authenticated = (
        all(markers[key] is True for key in rule["required"])
        and (site != "linkedin_rps" or "talent_surface" in proofs)
    )
    if authenticated:
        ordered = [
            name for name in rule["proofs"] if name in proofs
        ]
        return result("AUTHENTICATED", proofs=ordered)
    return result(
        "AUTH_LOST",
        proofs=proofs,
        blocks=[
            key for key in rule["required"] if markers.get(key) is not True
        ],
    )
