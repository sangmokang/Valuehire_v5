from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import os
import re
import shlex
from typing import Any

from .access import DiscordAuthorizedUser, is_authorized_discord_dm
from .models import Channel

DIRECT_SEARCH_SKILL_COMMANDS: dict[str, str] = {
    "url": "url",
    "aisearch": "aisearch",
    "humansearch": "humansearch",
}

# 단일 봇 콘솔 명령(AC-1, 2026-07-22) — 게이트웨이가 기존 fleet-* 계약으로 정규화한다.
# jobs → fleet-status(+웹 링크), skill/login → fleet-run(skill:<이름>, 화이트리스트 게이트).
BOT_CONSOLE_COMMANDS: tuple[str, ...] = ("jobs", "login", "skill")

SUPPORTED_DISCORD_COMMANDS: tuple[str, ...] = (
    "search-status",
    "run-search",
    "register-position",
    "session-status",
    "relogin-needed",
    *DIRECT_SEARCH_SKILL_COMMANDS,
    *BOT_CONSOLE_COMMANDS,
    # 함대 작업 큐 명령(단계 C, 2026-07-11) — 기존 run-search(source/keyword) 와 별개.
    "fleet-run",
    "fleet-resume",
    "fleet-status",
    "fleet-cancel",
    # 엔진·모델 선택(2026-07-24 사장님 /st) — 조회는 누구나, 설정은 owner 전용(dispatch).
    "model",
)

SEARCH_SOURCES: tuple[Channel, ...] = ("saramin", "jobkorea", "linkedin_rps", "public_web")
MENTION_RE = re.compile(r"^<@!?(?P<bot_id>\d{15,22})>\s*")


@dataclass(frozen=True)
class DiscordAccessConfig:
    allowed_channel_ids: tuple[str, ...] = ()
    allowed_role_ids: tuple[str, ...] = ()
    allow_dm: bool = True


@dataclass(frozen=True)
class DiscordCommandParseResult:
    should_route: bool
    invocation_kind: str
    command_name: str = ""
    options: Mapping[str, str] = field(default_factory=dict)
    reason: str = ""


@dataclass(frozen=True)
class DiscordInvocation:
    user_id: str
    channel_id: str
    command_name: str
    is_dm: bool
    invocation_kind: str
    guild_id: str = ""
    member_role_ids: tuple[str, ...] = ()
    options: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DiscordRoutingDecision:
    allowed: bool
    reason: str
    response_visibility: str
    command_name: str
    options: Mapping[str, str] = field(default_factory=dict)


def parse_discord_id_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    ids: list[str] = []
    for raw in re.split(r"[\s,]+", value):
        item = raw.strip()
        if re.fullmatch(r"\d{15,22}", item):
            ids.append(item)
    return tuple(dict.fromkeys(ids))


def load_discord_access_config(env: Mapping[str, str] | None = None) -> DiscordAccessConfig:
    source = os.environ if env is None else env
    allow_dm = source.get("DISCORD_ALLOW_DM_COMMANDS", "1").strip().lower() not in {"0", "false", "no"}
    return DiscordAccessConfig(
        allowed_channel_ids=parse_discord_id_list(source.get("DISCORD_ALLOWED_CHANNEL_IDS")),
        allowed_role_ids=parse_discord_id_list(source.get("DISCORD_ALLOWED_ROLE_IDS")),
        allow_dm=allow_dm,
    )


def _parse_options(raw: str) -> dict[str, str]:
    options: dict[str, str] = {}
    for token in shlex.split(raw):
        if ":" not in token:
            continue
        key, value = token.split(":", 1)
        normalized = key.strip().lower().replace("-", "_")
        if normalized and value.strip():
            options[normalized] = value.strip()
    return options


def parse_discord_command_text(message: str, *, bot_user_id: str = "") -> DiscordCommandParseResult:
    text = message.strip()
    if not text:
        return DiscordCommandParseResult(False, "unknown", reason="empty message")

    invocation_kind = "message"
    if text.startswith("/"):
        invocation_kind = "slash"
        text = text[1:].strip()
    else:
        mention = MENTION_RE.match(text)
        if mention:
            if bot_user_id and mention.group("bot_id") != bot_user_id:
                return DiscordCommandParseResult(False, "mention", reason="message mentions another bot")
            invocation_kind = "mention"
            text = text[mention.end() :].strip()

    if invocation_kind == "message":
        return DiscordCommandParseResult(False, invocation_kind, reason="not a slash command or direct bot mention")

    parts = text.split(maxsplit=1)
    command_name = parts[0].lstrip("/").strip().lower() if parts else ""
    raw_options = parts[1] if len(parts) > 1 else ""
    if command_name not in SUPPORTED_DISCORD_COMMANDS:
        return DiscordCommandParseResult(False, invocation_kind, command_name=command_name, reason="unsupported command")

    options = _parse_options(raw_options)
    if command_name == "run-search":
        source = options.get("source", "")
        keyword = options.get("keyword", "")
        if source not in SEARCH_SOURCES:
            return DiscordCommandParseResult(False, invocation_kind, command_name=command_name, options=options, reason="unsupported search source")
        if not keyword:
            return DiscordCommandParseResult(False, invocation_kind, command_name=command_name, options=options, reason="missing keyword")
    if command_name == "register-position":
        url = options.get("url", "")
        position_text = options.get("text", "") or options.get("jd", "")
        if not url and not position_text:
            return DiscordCommandParseResult(False, invocation_kind, command_name=command_name, options=options, reason="missing position url or text")

    return DiscordCommandParseResult(True, invocation_kind, command_name=command_name, options=options, reason="supported command")


def _response_visibility(invocation: DiscordInvocation) -> str:
    if invocation.is_dm:
        return "dm"
    if invocation.invocation_kind == "slash":
        return "ephemeral"
    return "public_ack_then_dm"


def route_discord_invocation(
    invocation: DiscordInvocation,
    *,
    authorized_users: Sequence[DiscordAuthorizedUser],
    config: DiscordAccessConfig,
) -> DiscordRoutingDecision:
    visibility = _response_visibility(invocation)
    if invocation.command_name not in SUPPORTED_DISCORD_COMMANDS:
        return DiscordRoutingDecision(False, "unsupported command", visibility, invocation.command_name, invocation.options)

    user_allowed = is_authorized_discord_dm(invocation.user_id, tuple(authorized_users))
    if invocation.is_dm:
        allowed = bool(config.allow_dm and user_allowed)
        reason = "authorized personal DM" if allowed else "not an authorized Discord personal DM user"
        return DiscordRoutingDecision(allowed, reason, visibility, invocation.command_name, invocation.options)

    if not invocation.guild_id:
        return DiscordRoutingDecision(False, "guild channel invocation missing guild_id", visibility, invocation.command_name, invocation.options)
    if not config.allowed_channel_ids:
        return DiscordRoutingDecision(False, "server channel allowlist is not configured", visibility, invocation.command_name, invocation.options)
    if invocation.channel_id not in config.allowed_channel_ids:
        return DiscordRoutingDecision(False, "server channel is not allowlisted", visibility, invocation.command_name, invocation.options)

    role_allowed = bool(set(invocation.member_role_ids) & set(config.allowed_role_ids))
    identity_allowed = user_allowed or role_allowed
    if not identity_allowed:
        return DiscordRoutingDecision(False, "user is neither an authorized contact nor in an allowed role", visibility, invocation.command_name, invocation.options)

    return DiscordRoutingDecision(True, "authorized server channel invocation", visibility, invocation.command_name, invocation.options)


def discord_message_content_intent_required(*, free_text_channel_commands: bool) -> bool:
    """Return whether the design needs Discord's privileged Message Content intent.

    Slash commands do not require Message Content. Direct bot mentions can be used
    as an explicit-intent fallback. A generic prefix/free-text parser in server
    channels would require Message Content and is intentionally outside the safe
    default design.
    """
    return bool(free_text_channel_commands)


def discord_slash_command_payloads() -> list[dict[str, Any]]:
    source_choices = [{"name": source, "value": source} for source in SEARCH_SOURCES]
    return [
        {
            "name": "search-status",
            "description": "Show the Valuehire search queue status.",
            "type": 1,
            "contexts": [0, 1],
        },
        {
            "name": "run-search",
            "description": "Queue an approved Valuehire search run.",
            "type": 1,
            "contexts": [0, 1],
            "options": [
                {
                    "name": "source",
                    "description": "Search source.",
                    "type": 3,
                    "required": True,
                    "choices": source_choices,
                },
                {
                    "name": "keyword",
                    "description": "Approved search keyword.",
                    "type": 3,
                    "required": True,
                },
            ],
        },
        {
            "name": "register-position",
            "description": "Register or link a Valuehire position from a Wanted URL or JD text.",
            "type": 1,
            "contexts": [0, 1],
            "options": [
                {
                    "name": "url",
                    "description": "Wanted or ClickUp URL for the position.",
                    "type": 3,
                    "required": False,
                },
                {
                    "name": "text",
                    "description": "Company, role, or pasted JD text.",
                    "type": 3,
                    "required": False,
                },
            ],
        },
        {
            "name": "session-status",
            "description": "Show portal login/session readiness without secrets.",
            "type": 1,
            "contexts": [0, 1],
        },
        {
            "name": "relogin-needed",
            "description": "Report which protected portals need manual relogin.",
            "type": 1,
            "contexts": [0, 1],
        },
        *[
            {
                "name": command,
                "description": f"Queue the Valuehire {skill} search skill.",
                "type": 1,
                "contexts": [0, 1],
                "options": [
                    {
                        "name": "url",
                        "description": "Position URL (ClickUp or supported job posting).",
                        "type": 3,
                        "required": True,
                    },
                    {
                        "name": "machine",
                        "description": "Target machine (optional).",
                        "type": 3,
                        "required": False,
                        "choices": [
                            {"name": machine, "value": machine}
                            for machine in ("macmini", "macbook", "winpc")
                        ],
                    },
                    {
                        "name": "engine",
                        "description": "Execution engine (default: claude).",
                        "type": 3,
                        "required": False,
                        "choices": [
                            {"name": engine, "value": engine}
                            for engine in ("claude", "codex")
                        ],
                    },
                ],
            }
            for command, skill in DIRECT_SEARCH_SKILL_COMMANDS.items()
        ],
        {
            "name": "jobs",
            "description": "Show recent Valuehire fleet jobs with the web dashboard link.",
            "type": 1,
            "contexts": [0, 1],
        },
        {
            "name": "login",
            "description": "Check/recover portal login sessions (not yet queue-supported).",
            "type": 1,
            "contexts": [0, 1],
            "options": [
                {
                    "name": "portal",
                    "description": "Portal to check.",
                    "type": 3,
                    "required": False,
                    "choices": [
                        {"name": portal, "value": portal}
                        for portal in ("saramin", "jobkorea", "linkedin", "all")
                    ],
                },
                {
                    "name": "machine",
                    "description": "Target machine (optional).",
                    "type": 3,
                    "required": False,
                    "choices": [
                        {"name": machine, "value": machine}
                        for machine in ("macmini", "macbook", "winpc")
                    ],
                },
            ],
        },
        {
            "name": "skill",
            "description": "Run a whitelisted Valuehire skill (humansearch/aisearch/url).",
            "type": 1,
            "contexts": [0, 1],
            "options": [
                {
                    "name": "name",
                    "description": "Skill name (whitelisted only).",
                    "type": 3,
                    "required": True,
                },
                {
                    "name": "url",
                    "description": "Position or search URL.",
                    "type": 3,
                    "required": False,
                },
                {
                    "name": "machine",
                    "description": "Target machine (optional).",
                    "type": 3,
                    "required": False,
                    "choices": [
                        {"name": machine, "value": machine}
                        for machine in ("macmini", "macbook", "winpc")
                    ],
                },
                {
                    "name": "engine",
                    "description": "Execution engine (default: claude).",
                    "type": 3,
                    "required": False,
                    "choices": [
                        {"name": engine, "value": engine}
                        for engine in ("claude", "codex")
                    ],
                },
            ],
        },
        {
            "name": "fleet-run",
            "description": "Queue a Valuehire fleet search job (humansearch/aisearch/url).",
            "type": 1,
            "contexts": [0, 1],
            "options": [
                {"name": "url", "description": "Position or search URL.", "type": 3, "required": True},
                {"name": "skill", "description": "Search skill (default: humansearch).", "type": 3, "required": False,
                 "choices": [{"name": s, "value": s} for s in ("humansearch", "aisearch", "url")]},
                {"name": "machine", "description": "Target machine.", "type": 3, "required": False,
                 "choices": [{"name": m, "value": m} for m in ("macmini", "macbook", "winpc")]},
            ],
        },
        {
            "name": "fleet-status",
            "description": "Show recent Valuehire fleet jobs.",
            "type": 1,
            "contexts": [0, 1],
        },
        {
            "name": "fleet-resume",
            "description": "(owner) Resume a paused fleet job.",
            "type": 1,
            "contexts": [0, 1],
            "options": [{"name": "job", "description": "Job id.", "type": 3, "required": True}],
        },
        {
            "name": "fleet-cancel",
            "description": "(owner) Cancel a queued/paused fleet job.",
            "type": 1,
            "contexts": [0, 1],
            "options": [{"name": "job", "description": "Job id.", "type": 3, "required": True}],
        },
        {
            "name": "model",
            "description": "Show or (owner) set default engine/model for fleet jobs.",
            "type": 1,
            "contexts": [0, 1],
            "options": [
                {"name": "engine", "description": "Engine (codex|claude).", "type": 3, "required": False,
                 "choices": [{"name": e, "value": e} for e in ("codex", "claude")]},
                {"name": "model", "description": "Model name (e.g. claude-opus-4-8, gpt-5.5).",
                 "type": 3, "required": False},
            ],
        },
    ]
