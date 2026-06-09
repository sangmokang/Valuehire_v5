from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
from collections.abc import Mapping


@dataclass(frozen=True)
class DiscordAuthorizedUser:
    name: str
    alias: str
    email: str
    discord_id: str


def authorized_discord_users_from_markdown(markdown: str) -> tuple[DiscordAuthorizedUser, ...]:
    """Parse the Discord Contacts table from docs/search-access.md.

    The parser is deliberately small and fail-closed: only rows with an all-digit
    Discord ID are returned. Header/separator rows and malformed rows are ignored.
    """
    users: list[DiscordAuthorizedUser] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or "Discord ID" in line or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        name, alias, email, discord_id = cells[:4]
        if not re.fullmatch(r"\d{15,22}", discord_id):
            continue
        users.append(
            DiscordAuthorizedUser(
                name=name,
                alias=alias,
                email=email,
                discord_id=discord_id,
            )
        )
    return tuple(users)


def load_authorized_discord_users(path: str | Path = "docs/search-access.md") -> tuple[DiscordAuthorizedUser, ...]:
    content = Path(path).read_text(encoding="utf-8")
    return authorized_discord_users_from_markdown(content)


def is_authorized_discord_dm(discord_user_id: str, users: tuple[DiscordAuthorizedUser, ...] | list[DiscordAuthorizedUser]) -> bool:
    return any(user.discord_id == str(discord_user_id) for user in users)


# SOT invariant (docs/search-access.md): all three protected portals — Saramin,
# Jobkorea, AND LinkedIn RPS — auto-login from the Keychain-backed secret store.
# These env key names are import/preflight inputs only; runtime automatic login must
# load credentials from MacKeychainPortalCredentialProvider. Never re-disable LinkedIn
# auto-login. The only guardrails are the safety boundaries: a captcha / 2FA / checkpoint
# is never auto-bypassed, credentials are never hardcoded, and outreach stays human-gated.
PORTAL_CREDENTIAL_KEYS: dict[str, tuple[tuple[str, str], ...]] = {
    "saramin": (("SARAMIN_USERNAME", "SARAMIN_PASSWORD"), ("JOB_PORTAL_USERNAME", "JOB_PORTAL_PASSWORD")),
    "jobkorea": (("JOBKOREA_USERNAME", "JOBKOREA_PASSWORD"), ("JOB_PORTAL_USERNAME", "JOB_PORTAL_PASSWORD")),
    "linkedin_rps": (("LINKEDIN_USERNAME", "LINKEDIN_PASSWORD"), ("LINKEDIN_RPS_USERNAME", "LINKEDIN_RPS_PASSWORD")),
}


def _clean_secret(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().strip('"').strip("'")
    return "" if text == "<redacted>" else text


def _has_secret(value: object) -> bool:
    return bool(_clean_secret(value))


def portal_credential_status(env: Mapping[str, str] | None = None) -> dict[str, dict[str, object]]:
    """Report whether portal credentials exist without returning secret values.

    Per-portal keys are preferred:
    - SARAMIN_USERNAME / SARAMIN_PASSWORD
    - JOBKOREA_USERNAME / JOBKOREA_PASSWORD
    - LINKEDIN_USERNAME / LINKEDIN_PASSWORD

    The shared JOB_PORTAL_USERNAME / JOB_PORTAL_PASSWORD pair remains supported as a
    fallback for older Saramin/Jobkorea docs and deployments.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    status: dict[str, dict[str, object]] = {}
    for portal, pairs in PORTAL_CREDENTIAL_KEYS.items():
        selected_username_key = ""
        selected_password_key = ""
        ready = False
        for username_key, password_key in pairs:
            has_username = _has_secret(source.get(username_key))
            has_password = _has_secret(source.get(password_key))
            if has_username or has_password:
                selected_username_key = username_key
                selected_password_key = password_key
            if has_username and has_password:
                ready = True
                selected_username_key = username_key
                selected_password_key = password_key
                break
        status[portal] = {
            "ready": ready,
            "username_key": selected_username_key,
            "password_key": selected_password_key,
        }
    return status


def resolve_portal_credentials(channel: str, env: Mapping[str, str] | None = None) -> tuple[str, str] | None:
    """Return (username, password) for automatic login, or None when not configured.

    Drives automatic portal login for all three protected portals — Saramin, Jobkorea,
    AND LinkedIn RPS — and lets init-portal-credentials copy those secrets into macOS
    Keychain. It returns actual secret values, so callers must never log or echo the
    result, and credentials are only ever read from the secret store (never hardcoded).
    """
    source: Mapping[str, str] = os.environ if env is None else env
    pairs = PORTAL_CREDENTIAL_KEYS.get(channel)
    if not pairs:
        return None
    for username_key, password_key in pairs:
        username = _clean_secret(source.get(username_key))
        password = _clean_secret(source.get(password_key))
        if username and password:
            return username, password
    return None


def discord_dm_routing_guard(discord_user_id: str, *, is_dm: bool, access_doc_path: str | Path = "docs/search-access.md") -> dict[str, object]:
    """Return a fail-closed routing decision for Discord personal DM AI Search calls."""
    users = load_authorized_discord_users(access_doc_path)
    allowed = bool(is_dm and is_authorized_discord_dm(discord_user_id, users))
    return {
        "allowed": allowed,
        "reason": "authorized personal DM" if allowed else "not an authorized Discord personal DM user",
        "authorized_user_ids": tuple(user.discord_id for user in users),
    }
