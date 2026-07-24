"""Protected-portal browser session guard.

The guard is intentionally small: it prevents destructive or ad-hoc shell
paths and points the agent back to the exact-target production runner.  It
does not inspect secrets, browser content, or external state.
"""
from __future__ import annotations

import os
import re
import shlex
from typing import Any


NAME = "login"
_RUNNER = "tools.multi_position_sourcing.session_guard"
_GUIDANCE = (
    "⛔ 차단(login): 로그인·검색 전에 기존 exact target을 정식 session_guard로 "
    "확인해야 합니다. `python3 -m tools.multi_position_sourcing.session_guard "
    "human-auth ...`를 사용하세요. 새 창·새 탭·브라우저 종료는 금지이며 "
    "작업 종료 시 CDP WebSocket만 해제합니다."
)

_BROWSER = re.compile(
    r"\b(google[ _-]?ch" r"rome|ch" r"rome|ch" r"romium)\b",
    re.IGNORECASE,
)
_PROCESS_TERMINATION = re.compile(
    r"(?:^|[\n;&`]|\$\()\s*(?:sudo\s+|env\s+\S+=\S+\s+)*"
    r"(?:p" r"kill|kill" r"all)\b"
    r"|(?:^|[\n;&`]|\$\()\s*(?:sudo\s+|env\s+\S+=\S+\s+)*"
    r"kill\b(?:\s+-\S+)*\s+(?:%|\d|\$\(|`)"
    r"|\bxargs\s+(?:-\S+\s+)*kill\b"
    r"|\bosascript\b[\s\S]*\bquit\b",
    re.IGNORECASE,
)
_PORTAL_LIFECYCLE = re.compile(
    r"(?:^|[\n;&|`]|\$\()\s*(?:sudo\s+|env\s+\S+=\S+\s+)*"
    r"(?:bash\s+|sh\s+|\./|/)?\S*portal_browsers\.sh\s+"
    r"(?:st" r"art|st" r"op|re" r"start)\b",
    re.IGNORECASE,
)
_PROTECTED_CONTEXT = re.compile(
    r"sara" r"min\.co\.kr|job" r"korea\.co\.kr|"
    r"link" r"edin\.com/talent|"
    r"\b(?:sara" r"min|job" r"korea|link" r"edin_rps)\b",
    re.IGNORECASE,
)
_UNSAFE_BROWSER_PRIMITIVE = re.compile(
    r"connectOver" r"CDP"
    r"|\b(?:browser|context|page)\.(?:new_page|new_tab|close)\s*\("
    r"|/json/" r"new\b"
    r"|\bTarget\.(?:create" r"Target|close" r"Target)\b"
    r"|\b(?:Browser|Page)\.close\b"
    r"|\bPage\.navi" r"gate\b"
    r"|\bInput\.dispatch" r"MouseEvent\b"
    r"|\bRuntime\.eval" r"uate\b",
    re.IGNORECASE,
)
_LEGACY_LOGIN_MODULE = re.compile(
    r"\bpython3?\s+-m\s+tools\.multi_position_sourcing\."
    r"(?:portal_login|portal_autologin)\b",
    re.IGNORECASE,
)
_READ_ONLY_PROGRAMS = frozenset({"rg", "grep", "sed", "git"})
_SHELL_CONTROL_CHARS = frozenset(";&|`")


def _command(tool_input: Any) -> str:
    if not isinstance(tool_input, dict):
        return ""
    value = tool_input.get("command")
    if value in (None, ""):
        value = tool_input.get("cmd", "")
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _has_shell_control(command: str) -> bool:
    if "\n" in command or "\r" in command or "$(" in command:
        return True
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|`")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return True
    return any(
        token and set(token).issubset(_SHELL_CONTROL_CHARS)
        for token in tokens
    )


def _is_read_only_inspection(command: str) -> bool:
    tokens = _tokens(command)
    if not tokens:
        return False
    program = os.path.basename(tokens[0])
    return program in _READ_ONLY_PROGRAMS and not _has_shell_control(command)


def _is_exact_session_guard(command: str) -> bool:
    if _has_shell_control(command):
        return False
    tokens = _tokens(command)
    if tokens and tokens[0].startswith("PYTHONPATH="):
        tokens = tokens[1:]
    if len(tokens) < 5:
        return False
    return (
        os.path.basename(tokens[0]) in {"python", "python3"}
        and tokens[1] == "-m"
        and tokens[2] == _RUNNER
        and tokens[3] in {"human-auth", "keepalive"}
    )


def check(tool: str, tool_input: dict[str, Any]) -> str | None:
    command = _command(tool_input)
    if not command or _is_read_only_inspection(command):
        return None
    if _is_exact_session_guard(command):
        return None
    if _PROCESS_TERMINATION.search(command) and _BROWSER.search(command):
        return _GUIDANCE
    if _PORTAL_LIFECYCLE.search(command):
        return _GUIDANCE
    if _LEGACY_LOGIN_MODULE.search(command):
        return _GUIDANCE
    if (
        _PROTECTED_CONTEXT.search(command)
        and _UNSAFE_BROWSER_PRIMITIVE.search(command)
    ):
        return _GUIDANCE
    return None
