"""Valuehire fleet plugin for the Hermes gateway (~/.hermes/hermes-agent).

Wires fleet-run/fleet-status/fleet-resume/fleet-cancel slash commands to the
canonical dispatcher in tools/multi_position_sourcing/hermes_fleet_bridge.py
(Valuehire_v5 repo) — this plugin never re-implements auth/queue logic.

Deploy: symlink this directory to ``~/.hermes/plugins/valuehire_fleet`` so the
installed plugin is always exactly the git-tracked source (no stale-copy
drift), then add ``valuehire_fleet`` to ``plugins.enabled`` in
``~/.hermes/config.yaml`` and restart the gateway. See
docs/prompts/fleet-control-hermes-bridge-prompts-2026-07-13.md for the full
install/rollback procedure — do not do this without owner approval (touches
the live production Discord bot).

Identity problem (structural Hermes limitation): register_command() handlers
only receive ``raw_args: str``, never the sender's platform user id
(hermes_cli/plugins.py:414). We solve this with the ``pre_gateway_dispatch``
hook, which fires once per incoming message BEFORE command dispatch and DOES
receive the full ``MessageEvent`` (event.source.user_id, event.source.platform
— gateway/session.py:SessionSource). We stash the sender id in a contextvar
there; the command handlers read it back. If the hook never fires for some
reason, the contextvar stays at its default "" and
``hermes_fleet_bridge.dispatch_hermes_fleet_command()`` fail-closes (raises)
rather than assuming owner or member identity.
"""

from __future__ import annotations

import contextvars
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

# Resolve the Valuehire_v5 repo root through this file's own path. Works
# whether this file is reached via the ~/.hermes/plugins/valuehire_fleet
# symlink or the repo path directly — Path.resolve() follows symlinks.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# 2026-07-13 라이브 적대검증에서 발견: Hermes 자신도 최상위 패키지 이름 "tools" 를 쓴다
# (~/.hermes/hermes-agent/tools/). sys.path 순서는 상관없다 — 파이썬은 "tools" 를
# 먼저 찾으면 sys.modules 캐시를 그대로 재사용하므로, Hermes 부팅 과정에서 이미
# import 된 Hermes 자신의 tools 패키지가 우리 것을 가려버려
# "No module named 'tools.multi_position_sourcing'" 로 죽는다(gateway/run.py 쪽
# "Plugin command dispatch failed" 경고로 조용히 삼켜짐, 실사용자에겐 그냥 무응답).
# "tools" 라는 이름을 아예 안 거치도록, 별명(alias)으로 직접 로드한다.
_ALIAS = "_valuehire_multi_position_sourcing"


def _load_bridge_module():
    """``tools.multi_position_sourcing.hermes_fleet_bridge`` 를 별명 패키지로 로드.

    ``sys.modules['tools']`` 충돌을 피하려고 "tools" 라는 이름을 아예 거치지 않는다.
    이미 로드했으면(멱등) 캐시된 모듈을 그대로 반환한다.
    """
    bridge_name = f"{_ALIAS}.hermes_fleet_bridge"
    if bridge_name in sys.modules:
        return sys.modules[bridge_name]

    pkg_dir = _REPO_ROOT / "tools" / "multi_position_sourcing"
    if _ALIAS not in sys.modules:
        pkg_spec = importlib.util.spec_from_file_location(
            _ALIAS, pkg_dir / "__init__.py", submodule_search_locations=[str(pkg_dir)]
        )
        pkg_module = importlib.util.module_from_spec(pkg_spec)
        sys.modules[_ALIAS] = pkg_module
        pkg_spec.loader.exec_module(pkg_module)

    mod_spec = importlib.util.spec_from_file_location(
        bridge_name, pkg_dir / "hermes_fleet_bridge.py"
    )
    module = importlib.util.module_from_spec(mod_spec)
    module.__package__ = _ALIAS
    sys.modules[bridge_name] = module
    mod_spec.loader.exec_module(module)
    return module

_GATEWAY_USER_ID: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "valuehire_fleet_gateway_user_id", default=""
)
_GATEWAY_INVOCATION_CONTEXT: "contextvars.ContextVar[dict[str, object]]" = contextvars.ContextVar(
    "valuehire_fleet_gateway_invocation_context", default={}
)
_SNOWFLAKE_RE = re.compile(r"^[0-9]{15,22}$")

# Only Discord identities are meaningful here — docs/search-access.md only
# lists Discord snowflake IDs. A Telegram/WhatsApp numeric id must never be
# silently treated as a Discord id (cross-platform identity conflation).
_TRUSTED_PLATFORM = "discord"
_POSITION_CONTEXT_STORE = None
_SEARCH_INTAKE_TTL_SECONDS = 300.0
_PENDING_SEARCH_INTAKES: dict[tuple[str, str], tuple[float, str]] = {}


def _platform_name(source: object) -> str:
    platform = getattr(source, "platform", None)
    if platform is None:
        return ""
    value = getattr(platform, "value", platform)
    return str(value).strip().lower()


def _event_value(event: object, source: object, *names: str) -> str:
    raw_message = getattr(event, "raw_message", None)
    for owner in (event, source, raw_message):
        if owner is None:
            continue
        for name in names:
            value = getattr(owner, name, None)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def _discord_role_ids(event: object) -> tuple[str, ...]:
    raw_message = getattr(event, "raw_message", None)
    member = getattr(raw_message, "user", None) or getattr(raw_message, "author", None)
    role_ids: list[str] = []
    for role in getattr(member, "roles", ()) or ():
        role_id = str(getattr(role, "id", "") or "").strip()
        if _SNOWFLAKE_RE.fullmatch(role_id):
            role_ids.append(role_id)
    return tuple(dict.fromkeys(role_ids))


def _discord_guild_id(event: object, source: object) -> str:
    guild_id = _event_value(event, source, "guild_id")
    if guild_id:
        return guild_id
    raw_message = getattr(event, "raw_message", None)
    guild = getattr(raw_message, "guild", None)
    return str(getattr(guild, "id", "") or "").strip()


def _position_context_store(bridge):
    global _POSITION_CONTEXT_STORE
    if _POSITION_CONTEXT_STORE is None:
        module = __import__(f"{_ALIAS}.hermes_position_context", fromlist=["PositionContextStore"])
        _POSITION_CONTEXT_STORE = module.PositionContextStore()
    return _POSITION_CONTEXT_STORE


def _capture_gateway_identity(event=None, gateway=None, session_store=None, **_kwargs):
    """Capture identity and rewrite narrow natural search requests to fleet-run."""
    user_id = ""
    source = getattr(event, "source", None)
    if source is not None and _platform_name(source) == _TRUSTED_PLATFORM:
        raw = getattr(source, "user_id", None)
        if raw:
            user_id = str(raw).strip()
    _GATEWAY_USER_ID.set(user_id)
    _GATEWAY_INVOCATION_CONTEXT.set({})
    if not user_id:
        return None

    guild_id = _discord_guild_id(event, source)
    channel_id = _event_value(
        event, source, "chat_id", "channel_id", "conversation_id", "thread_id"
    ) or ("hermes-dm" if not guild_id else "hermes-unknown-channel")
    chat_type = str(getattr(source, "chat_type", "") or "").strip().lower()
    is_dm = chat_type in {"dm", "private"} if chat_type else not bool(guild_id)
    event_id = _event_value(event, source, "message_id", "event_id", "id")
    if not _SNOWFLAKE_RE.fullmatch(event_id):
        event_id = ""
    _GATEWAY_INVOCATION_CONTEXT.set({
        "channel_id": channel_id,
        "guild_id": guild_id,
        "is_dm": is_dm,
        "role_ids": _discord_role_ids(event),
        "event_id": event_id,
    })

    bridge = _load_bridge_module()
    message_id = event_id
    store = _position_context_store(bridge)
    context = store.get(user_id, channel_id)
    text = getattr(event, "text", "") or ""
    pending_key = (user_id, channel_id)
    pending = _PENDING_SEARCH_INTAKES.get(pending_key)
    if pending:
        created_at, fixed_skill = pending
        if time.time() - created_at > _SEARCH_INTAKE_TTL_SECONDS:
            _PENDING_SEARCH_INTAKES.pop(pending_key, None)
        elif text.strip() and not text.lstrip().startswith("/") and message_id:
            _PENDING_SEARCH_INTAKES.pop(pending_key, None)
            context_url = context.position_url if context else ""
            context_channels = context.channels if context else ()
            rewritten = bridge.natural_fleet_command_text(
                f"{fixed_skill} {text}",
                context_url=context_url,
                context_channels=context_channels,
                message_id=message_id,
                force_linkedin_first=fixed_skill == "aisearch",
            )
            if rewritten:
                clickup = re.search(r"https?://app\.clickup\.com/[^\s<>]+", text, re.IGNORECASE)
                if clickup:
                    store.put(
                        user_id,
                        channel_id,
                        clickup.group(0).rstrip(".,);]}"),
                        ("saramin", "jobkorea"),
                    )
                return {"action": "rewrite", "text": rewritten}
            # 자연어 정규화가 못 알아본 입력도 기존 fleet-run 파서로 넘긴다.
            # fixed_skill을 앞에 고정하고 event-derived idempotency를 뒤에 붙여
            # skill/idempotency 덮어쓰기는 중복 필드 오류로 fail-closed 된다.
            return {
                "action": "rewrite",
                "text": (
                    f"/fleet-run {fixed_skill} {text.strip()} "
                    f"idempotency:discord:{message_id}"
                ),
            }
    rewritten = bridge.natural_fleet_command_text(
        text,
        context_url=context.position_url if context else "",
        context_channels=context.channels if context else (),
        message_id=message_id,
    )
    if rewritten:
        clickup = re.search(r"https?://app\.clickup\.com/[^\s<>]+", text, re.IGNORECASE)
        if clickup:
            channels_match = re.search(r"\bchannels:([^\s]+)", rewritten)
            channels = channels_match.group(1).split(",") if channels_match else ("saramin", "jobkorea")
            store.put(user_id, channel_id, clickup.group(0).rstrip(".,);]}"), channels)
        return {"action": "rewrite", "text": rewritten}
    return None


def _make_handler(command_name: str, *, fixed_skill: str = ""):
    def _handler(raw_args: str) -> str:
        bridge = _load_bridge_module()

        gateway_user_id = _GATEWAY_USER_ID.get()
        invocation_context = dict(_GATEWAY_INVOCATION_CONTEXT.get())
        dispatch_command = "fleet-run" if fixed_skill else command_name
        if fixed_skill and re.search(r"(?:^|\s)(?:skill|idempotency):", raw_args):
            return "거부됨: 직접 검색 명령의 skill/idempotency 값은 Discord 이벤트로 고정됩니다"
        dispatch_args = f"{fixed_skill} {raw_args}".strip() if fixed_skill else raw_args
        event_id = str(invocation_context.get("event_id", "") or "")
        if fixed_skill and not _SNOWFLAKE_RE.fullmatch(event_id):
            return "거부됨: Discord event identity missing — 중복 방지 키 없이 직접 검색을 실행할 수 없음"
        if (
            dispatch_command == "fleet-run"
            and _SNOWFLAKE_RE.fullmatch(event_id)
            and not re.search(r"(?:^|\s)idempotency:", dispatch_args)
        ):
            dispatch_args = f"{dispatch_args} idempotency:discord:{event_id}".strip()
        try:
            result = bridge.dispatch_hermes_fleet_command(
                dispatch_command,
                dispatch_args,
                gateway_user_id=gateway_user_id,
                invocation_context=invocation_context,
            )
        except bridge.HermesFleetBridgeError as exc:
            return f"거부됨: {exc}"
        except Exception as exc:  # noqa: BLE001 — 마지막 방어선. 여기서 새면 Hermes 의
            # gateway/run.py 쪽 광역 except 가 조용히 로그만 남기고 무응답으로 삼켜, 원문
            # '/fleet-run ...' 이 그대로 LLM 채팅으로 흘러간다(적대검증에서 실제 발견된 경로).
            return f"오류: {exc}"
        return json.dumps(result, ensure_ascii=False)

    return _handler


def _make_search_intake_handler(command_name: str):
    fixed_skill = "humansearch" if command_name in {"url", "humansearch"} else "aisearch"

    def _handler(_raw_args: str) -> str:
        gateway_user_id = _GATEWAY_USER_ID.get()
        invocation_context = dict(_GATEWAY_INVOCATION_CONTEXT.get())
        channel_id = str(invocation_context.get("channel_id", "") or "")
        event_id = str(invocation_context.get("event_id", "") or "")
        if not gateway_user_id or not channel_id or not _SNOWFLAKE_RE.fullmatch(event_id):
            return "거부됨: Discord event identity missing — 검색 입력을 안전하게 연결할 수 없음"
        _PENDING_SEARCH_INTAKES[(gateway_user_id, channel_id)] = (time.time(), fixed_skill)
        if fixed_skill == "aisearch":
            return (
                "검색할 포지션 링크를 다음 메시지로 보내주세요. 받는 즉시 login 스킬로 "
                "기존 로그인을 확인하고 사람인·잡코리아·LinkedIn AI Search를 시작합니다."
            )
        return (
            "인재검색 URL과 필터값을 다음 메시지로 보내주세요. 직전 포지션을 이어받아 "
            "login 스킬로 기존 로그인을 확인한 뒤 humansearch를 시작합니다."
        )

    return _handler


_COMMANDS: tuple[tuple[str, str, str], ...] = (
    ("fleet-run",
     "<position/search URL...> [win|winpc|macmini|macbook]",
     "Queue an AI search job. 기본 skill=aisearch; machine은 명시하거나 기존 fleet 기본값 사용."),
    ("fleet-status", "", "Show recent Valuehire fleet jobs."),
    ("fleet-resume", "job:<id>", "(owner) Resume a paused fleet job."),
    ("fleet-cancel", "job:<id>", "(owner) Cancel a queued/paused fleet job."),
)


_DIRECT_SEARCH_COMMANDS: tuple[tuple[str, str], ...] = (
    ("url", "다음 메시지의 인재검색 URL·필터로 Human Search 시작"),
    ("aisearch", "다음 메시지의 포지션으로 3채널 AI Search 시작"),
    ("humansearch", "다음 메시지의 인재검색 URL·필터로 Human Search 시작"),
)


def register(ctx) -> None:
    ctx.register_hook("pre_gateway_dispatch", _capture_gateway_identity)
    for name, args_hint, description in _COMMANDS:
        ctx.register_command(
            name, handler=_make_handler(name), description=description, args_hint=args_hint
        )
    for name, description in _DIRECT_SEARCH_COMMANDS:
        ctx.register_command(
            name,
            handler=_make_search_intake_handler(name),
            description=description,
            args_hint="",
        )
