"""Fail-closed shell guard for the Discord direct-gateway cutover boundary.

The production code remains authoritative.  This shared PreToolUse layer catches
the common operator bypasses before they become a second gateway or an unsigned
owner-agent enqueue.
"""

from __future__ import annotations

import os
import re


NAME = "discord-e2e-cutover"

_CANONICAL_START = re.compile(
    r"(?:^|[;&|]\s*)(?:python3?|[^\s]+/python3?)\s+"
    r"(?:\./)?scripts/discord_direct_gateway\.py(?:\s|$)",
    re.IGNORECASE,
)
_GATEWAY_BYPASS = re.compile(
    r"(?:_build_client|DirectGatewayClient)\s*\([^\n]*\)\s*\.run\s*\(",
    re.IGNORECASE,
)
_ENQUEUE = re.compile(r"\bdiscord_gateway_enqueue\b", re.IGNORECASE)
_EVENT_ID = re.compile(r"\bevent[_-]?id\s*[:=]\s*[0-9]{15,22}\b", re.IGNORECASE)
_AGENT_SKILL = re.compile(r"\b(?:skill\s*[:=]|p_skill\s*=\s*)agent\b", re.IGNORECASE)
_OWNER_PROOF = re.compile(r"\bverified_role\s*[:=]\s*owner\b", re.IGNORECASE)
_APPROVAL_ID = re.compile(r"\bapproval_id\s*[:=]\s*discord:[0-9]{15,22}\b", re.IGNORECASE)
_APPROVAL_SHA = re.compile(r"\bapproval_sha256\s*[:=]\s*[0-9a-f]{64}\b", re.IGNORECASE)
_DIRECT_ENGINE = re.compile(
    r"(?:^|[;&|]\s*)(?:codex(?:\.exe|\.cmd|\.bat)?\s+exec\b|"
    r"claude(?:\.exe|\.cmd|\.bat)?\s+(?:-p\b|--print\b))",
    re.IGNORECASE,
)


def _command(tool_input):
    value = (tool_input or {}).get("command", (tool_input or {}).get("cmd", ""))
    if isinstance(value, (list, tuple)):
        return " ".join(str(part) for part in value)
    return str(value or "")


def check(tool, tool_input):
    if tool not in {"Bash", "exec_command", "functions.exec_command"}:
        return None
    command = _command(tool_input)
    if not command:
        return None

    if _GATEWAY_BYPASS.search(command) and not _CANONICAL_START.search(command):
        return (
            "⛔ 차단(discord-e2e-cutover): direct gateway는 readiness·identity·"
            "killswitch·shared lease를 검사하는 정식 진입점 "
            "`python3 scripts/discord_direct_gateway.py`로만 시작하세요."
        )

    if _ENQUEUE.search(command) and not _EVENT_ID.search(command):
        return (
            "⛔ 차단(discord-e2e-cutover): Discord enqueue에는 snowflake event_id가 "
            "필수입니다. idempotency_key=discord:<event_id> 정식 경로를 사용하세요."
        )

    if _AGENT_SKILL.search(command) and not (
        _EVENT_ID.search(command)
        and _OWNER_PROOF.search(command)
        and _APPROVAL_ID.search(command)
        and _APPROVAL_SHA.search(command)
    ):
        return (
            "⛔ 차단(discord-e2e-cutover): skill=agent enqueue는 검증된 owner 신원과 "
            "event_id·approval_id·approval_sha256이 모두 필요합니다."
        )

    if os.environ.get("VALUEHIRE_DIRECT_GATEWAY_PROCESS") == "1" \
            and _DIRECT_ENGINE.search(command):
        return (
            "⛔ 차단(discord-e2e-cutover): direct gateway 프로세스 안에서 Claude/Codex를 "
            "직접 실행할 수 없습니다. 게이트웨이는 큐 enqueue만 수행합니다."
        )
    return None
