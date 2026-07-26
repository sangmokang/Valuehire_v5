"""Host-local, read-only Chrome/Chromium inventory.

The collector consumes already captured process/listener/CDP snapshots.  It has
no subprocess, HTTP, browser-launch, attach, or target-manipulation capability.
Callers may gather those local snapshots separately after machine readiness has
been established.
"""

from __future__ import annotations

import ntpath
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .fleet_heartbeat import normalize_machine_hostname
from .session_guard import _is_managed_chrome_executable

_OPTION = re.compile(
    r"(?:^|\s)--(?P<name>[A-Za-z0-9][A-Za-z0-9-]*)"
    r"(?:=(?P<value>.*?))?"
    r"(?=\s+--[A-Za-z0-9][A-Za-z0-9-]*(?:=|\s|$)|$)"
)
_SITES = (
    ("linkedin.com", "linkedin_rps"),
    ("saramin.co.kr", "saramin"),
    ("jobkorea.co.kr", "jobkorea"),
)
_CANONICAL_MACHINES = frozenset({"macmini", "macbook_pro", "winpc"})
_SAFE_MARKER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,79}")


def _options(command: str) -> dict[str, list[str | None]]:
    found: dict[str, list[str | None]] = {}
    for match in _OPTION.finditer(command):
        found.setdefault(match.group("name"), []).append(match.group("value"))
    return found


def _literal(value: str | None) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _is_chrome_executable(value: str) -> bool:
    if _is_managed_chrome_executable(value):
        return True
    literal = _literal(value).casefold()
    basename = ntpath.basename(literal.replace("/", "\\"))
    return basename in {
        "chrome.exe",
        "chromium.exe",
        "chrome",
        "chromium",
        "google-chrome",
        "google-chrome-stable",
    }


def _safe_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return ""
    if not parsed.scheme or not host:
        return ""
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc += f":{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _site(value: str) -> str | None:
    try:
        host = (urlsplit(value).hostname or "").casefold()
    except ValueError:
        return None
    for suffix, site in _SITES:
        if host == suffix or host.endswith(f".{suffix}"):
            return site
    return None


def _targets(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        return []
    result: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, Mapping):
            continue
        sanitized_url = _safe_url(raw.get("url"))
        markers = raw.get("marker_names")
        result.append(
            {
                "target_id": raw.get("id") if isinstance(raw.get("id"), str) else "",
                "type": raw.get("type") if isinstance(raw.get("type"), str) else "",
                "sanitized_url": sanitized_url,
                "site": _site(sanitized_url),
                "marker_names": [
                    marker
                    for marker in markers
                    if isinstance(marker, str) and _SAFE_MARKER.fullmatch(marker)
                ]
                if isinstance(markers, list)
                else [],
            }
        )
    return result


def _roots(snapshot: str) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    for raw_line in snapshot.splitlines():
        line = raw_line.strip()
        pid_text, separator, command = line.partition(" ")
        if not separator or not pid_text.isascii() or not pid_text.isdigit():
            continue
        option_start = re.search(r"(?:^|\s)--[A-Za-z0-9]", command)
        executable = (
            command[: option_start.start()].strip() if option_start else command.strip()
        )
        if not _is_chrome_executable(executable):
            continue
        options = _options(command)
        if "type" in options:
            continue
        profile_values = options.get("user-data-dir", [])
        profile = _literal(profile_values[0]) if len(profile_values) == 1 else ""
        if not profile or not (os.path.isabs(profile) or ntpath.isabs(profile)):
            profile = ""
        port_values = options.get("remote-debugging-port", [])
        port_text = _literal(port_values[0]) if len(port_values) == 1 else ""
        port = int(port_text) if port_text.isascii() and port_text.isdigit() else None
        if port is not None and not 1 <= port <= 65535:
            port = None
        roots.append(
            {
                "browser_pid": int(pid_text),
                "executable": executable,
                "profile_path": profile,
                "declared_port": port,
                "_port_count": len(port_values),
                "_profile_count": len(profile_values),
                "_debug_addresses": [
                    _literal(value)
                    for value in options.get("remote-debugging-address", [])
                ],
            }
        )
    return roots


def collect_browser_inventory(
    *,
    local_machine_id: str,
    machine_readiness: Mapping[str, Any],
    process_snapshot: str,
    listener_snapshot: Sequence[Mapping[str, Any]],
    endpoint_responses: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Build a secret-free inventory for one ready local machine."""
    canonical = normalize_machine_hostname(local_machine_id)
    if (
        local_machine_id not in _CANONICAL_MACHINES
        or canonical != local_machine_id
        or machine_readiness.get("registered") is not True
        or machine_readiness.get("online") is not True
        or machine_readiness.get("reason") is not None
    ):
        raise ValueError("valid local machine readiness is required")
    if not isinstance(process_snapshot, str):
        raise TypeError("process_snapshot must be text")

    roots = _roots(process_snapshot)
    profile_counts: dict[str, int] = {}
    for root in roots:
        profile = root["profile_path"]
        if profile:
            profile_counts[profile] = profile_counts.get(profile, 0) + 1

    report: list[dict[str, Any]] = []
    for root in roots:
        issues: list[str] = []
        port = root["declared_port"]
        addresses = root.pop("_debug_addresses")
        port_count = root.pop("_port_count")
        profile_count = root.pop("_profile_count")
        if profile_count != 1 or not root["profile_path"]:
            issues.append(
                "AMBIGUOUS_PROFILE" if profile_count > 1 else "MISSING_PROFILE"
            )
        if port_count != 1 or port is None:
            issues.append(
                "AMBIGUOUS_DECLARED_PORT" if port_count > 1 else "MISSING_DECLARED_PORT"
            )
        if len(addresses) > 1 or (
            addresses and addresses[0] not in {"127.0.0.1", "localhost"}
        ):
            issues.append("NON_LOOPBACK_DEBUG_ADDRESS")

        listeners = [
            row
            for row in listener_snapshot
            if isinstance(row, Mapping) and row.get("port") == port
        ]
        local = [row for row in listeners if row.get("address") == "127.0.0.1"]
        remote = [row for row in listeners if row.get("address") != "127.0.0.1"]
        listen_pid: int | None = None
        if remote:
            issues.append("NON_LOOPBACK_LISTENER")
        elif len(local) > 1:
            issues.append("AMBIGUOUS_LISTENER")
        elif len(local) == 1 and isinstance(local[0].get("pid"), int):
            listen_pid = local[0]["pid"]
            if listen_pid != root["browser_pid"]:
                issues.append("LISTENER_PID_MISMATCH")
        elif port is not None:
            issues.append("LISTENER_MISSING")

        endpoint = (
            f"http://127.0.0.1:{port}"
            if port is not None
            and "NON_LOOPBACK_DEBUG_ADDRESS" not in issues
            and "NON_LOOPBACK_LISTENER" not in issues
            and "AMBIGUOUS_LISTENER" not in issues
            else None
        )
        response = endpoint_responses.get(endpoint) if endpoint else None
        live = (
            isinstance(response, Mapping)
            and isinstance(response.get("version"), Mapping)
            and isinstance(response.get("targets"), list)
        )
        if endpoint and not live:
            issues.append("ENDPOINT_DEAD")
        profile = root["profile_path"]
        if profile and profile_counts.get(profile, 0) > 1:
            issues.append("DUPLICATE_PROFILE")
        report.append(
            {
                **root,
                "listen_pid": listen_pid,
                "endpoint": endpoint,
                "endpoint_live": live,
                "targets": _targets(response.get("targets")) if live else [],
                "issues": issues,
            }
        )
    return report
