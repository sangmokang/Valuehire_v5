"""디스코드 직결 게이트웨이 — 조각 C (얇은 수신기, goal §5C).

Discord 실 게이트웨이(websocket)에 discord.py(버전 고정, requirements-dev.txt)로 접속해
슬래시/텍스트 인터랙션을 받아 ``DiscordEnvelope`` 로 변환 → 기존
``tools.multi_position_sourcing.direct_receiver.handle_envelope()`` 를 호출 → 응답
전송까지만 한다. 이 스크립트는 스스로 서치·스킬·셸을 실행하지 않는다(INV-D1,
enqueue-only — 실행 능력은 handle_envelope 안 주입된 큐에만 있다).

지킬 것(goal §2·§3·§6·§9 그대로):
1. **슬래시 3초 규칙**: ``handle_envelope()``(내부에서 큐 등록 net I/O) 호출 전에 반드시
   3초 내 ``interaction.response.defer(ephemeral=True)`` 를 먼저 보낸다.
2. **명령 소유권 일치**: 등록하는 슬래시 명령 = ``fleet_dispatch.FLEET_COMMANDS`` 처리
   로직이 실제로 있는 것만. ``discord_routing.discord_slash_command_payloads()`` 는
   search-status/run-search/register-position/session-status/relogin-needed 도
   정의하지만, ``fleet_dispatch.dispatch_fleet_command`` 는
   ``if invocation.command_name not in FLEET_COMMANDS: return None`` 으로 이 5개를
   처리하지 않는다(fleet_dispatch.py 확인) — 등록하면 눌러도 항상 미지원으로 끝나는
   죽은 UI가 되므로 ``slash_commands_to_register()`` 로 교집합만 등록한다.
3. **envelope 필드 보존**: 길드 인터랙션이면 guild_id/channel_id/role_ids 를 실제로
   채운다(기존 hermes_fleet_bridge 어댑터처럼 DM 고정 금지).
4. **텍스트 명령**: 기본은 owner DM + 봇 멘션만(추가 인텐트 불필요) —
   ``discord_routing.parse_discord_command_text`` 재사용, 자유텍스트 길드 전체 파싱은
   하지 않는다(Message Content 인텐트가 필요하며 기본 off).
5. **비밀 미노출(INV-D5)**: 봇 토큰·예외 원문을 디스코드로 보내지 않는다. 이 스크립트
   자체는 DISCORD_BOT_TOKEN 만 필요하며 Supabase service-role 키를 직접 다루지 않는다
   (큐 클라이언트가 주입되어 그쪽 책임).
6. **fail-closed 침묵의 discord.py 요구사항 절충**: 슬래시 인터랙션은 defer 로 1차
   응답을 이미 보냈으므로, discord API 는 그 인터랙션에 최종 응답(followup)을 요구한다
   (안 보내면 그 사용자에게만 "상호작용 실패"가 표시됨 — 다른 사람에겐 안 보임).
   ``handle_envelope`` 의 response=None(=침묵 대상, 비인가/신원미상/미지원 전부 포함)
   케이스에서, 침묵 "사유"별로 회신 내용을 다르게 만들면 그 차이 자체가 "이 명령이
   나에게 적용된다/안 된다"는 신호가 되어 INV-D6(명령 존재를 비인가자에게 알리지
   않음)를 깬다. 그래서 response=None 인 모든 경로는 **항상 완전히 동일한 무정보
   ack**(``_GENERIC_SILENT_ACK``)만 보낸다 — 침묵 사유는 감사 로그에만 남는다.
   (이 판단이 애매하면 codex-rescue 2차 검증에서 재검토 요망 — goal §2 INV-D6 요구사항)
7. **네트워크 0 in 단위테스트**: tests/test_discord_direct_gateway.py 는 discord.Interaction/
   discord.Client 를 fake 로 만들어 검증한다. discord.py 라이브러리 import 자체는 하되
   (타입 힌트), 실제 client.run()/websocket 연결은 ``__main__`` 가드 밖에서 절대 호출하지
   않는다.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
from typing import Any, Callable, Mapping, Optional, Sequence

import discord

from tools.multi_position_sourcing.access import (
    DiscordAuthorizedUser,
    load_authorized_discord_users,
)
from tools.multi_position_sourcing.direct_receiver import DiscordEnvelope, handle_envelope
from tools.multi_position_sourcing.discord_routing import (
    DiscordAccessConfig,
    discord_slash_command_payloads,
    load_discord_access_config,
    parse_discord_command_text,
)
from tools.multi_position_sourcing.fleet_dispatch import FLEET_COMMANDS

logger = logging.getLogger("discord_direct_gateway")

_SNOWFLAKE_RE = re.compile(r"^[0-9]{15,22}$")

# response=None(침묵) 인 모든 사유에 공통으로 쓰는 무정보 ack — §6 참고. 내용을 절대
# 사유별로 분기하지 않는다(그 차이 자체가 신호가 됨).
_GENERIC_SILENT_ACK = "🔕"
_RESPONSE_CHAR_LIMIT = 1900  # goal §4 — 1,900자 분할 회신 계약과 동일 상한(단발 회신도 안전측 절단).


def slash_commands_to_register() -> list[dict[str, Any]]:
    """명령 소유권 일치(goal §3) — FLEET_COMMANDS 처리 로직이 실제 있는 명령만 등록."""
    return [p for p in discord_slash_command_payloads() if p.get("name") in FLEET_COMMANDS]


def _member_role_ids(user: Any) -> tuple[str, ...]:
    roles = getattr(user, "roles", None) or ()
    ids: list[str] = []
    for role in roles:
        rid = str(getattr(role, "id", ""))
        if _SNOWFLAKE_RE.fullmatch(rid):
            ids.append(rid)
    return tuple(ids)


def _options_to_raw_args(options: Sequence[Mapping[str, Any]] | None) -> str:
    """Discord 인터랙션 옵션 리스트 → parse_hermes_fleet_args 가 기대하는 'key:value' 문자열.

    shlex.quote 로 각 값을 감싸 왕복 안전(공백·따옴표 포함 값도 shlex.split 로 원본 그대로
    복원). 값을 게이트웨이가 미리 검증·정제하지 않는다 — 검증은 handle_envelope 안
    parse_hermes_fleet_args 1곳에서만 한다(INV-D3, 파싱 단일화).
    """
    tokens: list[str] = []
    for opt in options or []:
        name = str(opt.get("name", "")).strip()
        value = opt.get("value")
        if not name or value is None:
            continue
        tokens.append(f"{name}:{shlex.quote(str(value))}")
    return " ".join(tokens)


def interaction_to_envelope(interaction: Any) -> Optional[DiscordEnvelope]:
    """슬래시 인터랙션 → DiscordEnvelope. 명령명이 비어 있으면 None(무시)."""
    data = getattr(interaction, "data", None) or {}
    command = str(data.get("name") or "").strip().lower()
    if not command:
        return None
    guild_id = getattr(interaction, "guild_id", None)
    channel_id = getattr(interaction, "channel_id", None)
    is_dm = guild_id is None
    user = getattr(interaction, "user", None)
    user_id = str(getattr(user, "id", "")) if user is not None else ""
    role_ids = () if is_dm else _member_role_ids(user)
    raw_args = _options_to_raw_args(data.get("options"))
    return DiscordEnvelope(
        event_id=str(getattr(interaction, "id", "")),
        user_id=user_id,
        channel_id=str(channel_id or ""),
        command=command,
        raw_args=raw_args,
        is_dm=is_dm,
        guild_id=str(guild_id or ""),
        role_ids=role_ids,
    )


def message_to_envelope(message: Any, *, bot_user_id: str = "") -> Optional[DiscordEnvelope]:
    """봇 멘션/DM 텍스트 명령 → DiscordEnvelope. 기존 parse_discord_command_text 재사용.

    슬래시가 아니고 봇 멘션도 아닌 일반 텍스트는 항상 None(무시) — 길드 자유텍스트
    파싱은 Message Content 인텐트가 필요해 기본 범위 밖(goal §3).
    """
    content = getattr(message, "content", "") or ""
    parsed = parse_discord_command_text(content, bot_user_id=bot_user_id)
    if not parsed.should_route:
        return None
    guild = getattr(message, "guild", None)
    guild_id = getattr(guild, "id", None) if guild is not None else None
    is_dm = guild_id is None
    author = getattr(message, "author", None)
    user_id = str(getattr(author, "id", "")) if author is not None else ""
    role_ids = () if is_dm else _member_role_ids(author)
    channel = getattr(message, "channel", None)
    channel_id = getattr(channel, "id", None)
    raw_args = " ".join(
        f"{key}:{shlex.quote(str(value))}" for key, value in (parsed.options or {}).items()
    )
    return DiscordEnvelope(
        event_id=str(getattr(message, "id", "")),
        user_id=user_id,
        channel_id=str(channel_id or ""),
        command=parsed.command_name,
        raw_args=raw_args,
        is_dm=is_dm,
        guild_id=str(guild_id or ""),
        role_ids=role_ids,
    )


async def handle_slash_interaction(
    interaction: Any,
    *,
    queue: Any,
    authorized_users: Sequence[DiscordAuthorizedUser],
    config: DiscordAccessConfig,
    audit: Optional[Callable[[dict[str, Any]], Any]] = None,
    clock: Optional[Callable[[], float]] = None,
) -> dict[str, Any]:
    """슬래시 인터랙션 1건 처리 — 3초 규칙(goal §3) 준수: defer 가 항상 첫 호출.

    envelope 변환 실패(미지원 인터랙션 타입 등)도 discord API 요구사항상 무언가는
    응답해야 하므로 동일한 무정보 ack 를 보낸다(§6).
    """
    await interaction.response.defer(ephemeral=True)  # net I/O(handle_envelope) 전에 반드시 먼저.

    envelope = interaction_to_envelope(interaction)
    if envelope is None:
        await _safe_followup(interaction, _GENERIC_SILENT_ACK, event_id="?")
        return {"handled": False, "action": "unsupported_interaction", "response": None}

    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    result = handle_envelope(
        envelope, queue=queue, authorized_users=authorized_users,
        config=config, audit=audit, **kwargs,
    )

    response = result.get("response")
    outgoing = _GENERIC_SILENT_ACK if response is None else response[:_RESPONSE_CHAR_LIMIT]
    await _safe_followup(interaction, outgoing, event_id=envelope.event_id)
    return result


async def _safe_followup(interaction: Any, content: str, *, event_id: str) -> None:
    """followup.send 실패가 게이트웨이를 죽이면 안 됨 — 회신 유실은 로그로만 남긴다."""
    try:
        await interaction.followup.send(content, ephemeral=True)
    except Exception:  # noqa: BLE001 — 전송 실패를 게이트웨이 크래시로 번지게 하지 않는다.
        logger.warning("discord_direct_gateway: followup.send 실패 event_id=%s", event_id)


async def handle_text_message(
    message: Any,
    *,
    bot_user_id: str,
    queue: Any,
    authorized_users: Sequence[DiscordAuthorizedUser],
    config: DiscordAccessConfig,
    audit: Optional[Callable[[dict[str, Any]], Any]] = None,
    clock: Optional[Callable[[], float]] = None,
) -> Optional[dict[str, Any]]:
    """봇 멘션/DM 텍스트 명령 1건 처리. 지원 명령이 아니면 None(네트워크 접촉 0)."""
    envelope = message_to_envelope(message, bot_user_id=bot_user_id)
    if envelope is None:
        return None

    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    result = handle_envelope(
        envelope, queue=queue, authorized_users=authorized_users,
        config=config, audit=audit, **kwargs,
    )

    response = result.get("response")
    if response:
        try:
            await message.channel.send(response[:_RESPONSE_CHAR_LIMIT])
        except Exception:  # noqa: BLE001
            logger.warning(
                "discord_direct_gateway: channel.send 실패 event_id=%s", envelope.event_id)
    # response=None(텍스트 경로)은 discord API 요구사항이 없으므로 조용히 무시한다
    # (슬래시와 달리 인터랙션 응답 의무가 없음 — INV-D6 침묵 그대로).
    return result


class DirectGatewayClient(discord.Client):
    """운영 진입점 — 실 게이트웨이 접속 전용(단위테스트는 이 클래스를 기동하지 않는다).

    intents 는 기본값만 사용한다(Message Content 인텐트 off, goal §3 텍스트 명령 범위).
    """

    def __init__(
        self,
        *,
        authorized_users: Sequence[DiscordAuthorizedUser],
        config: DiscordAccessConfig,
        queue_factory: Callable[[], Any],
        audit: Optional[Callable[[dict[str, Any]], Any]] = None,
    ) -> None:
        super().__init__(intents=discord.Intents.default())
        self._authorized_users = authorized_users
        self._config = config
        self._queue_factory = queue_factory
        self._audit = audit

    async def on_interaction(self, interaction: discord.Interaction) -> None:  # pragma: no cover — 실 네트워크 진입점
        if getattr(interaction, "type", None) != discord.InteractionType.application_command:
            return
        await handle_slash_interaction(
            interaction, queue=self._queue_factory(),
            authorized_users=self._authorized_users, config=self._config, audit=self._audit,
        )

    async def on_message(self, message: discord.Message) -> None:  # pragma: no cover — 실 네트워크 진입점
        if message.author.bot:
            return
        bot_user = self.user
        bot_user_id = str(bot_user.id) if bot_user is not None else ""
        await handle_text_message(
            message, bot_user_id=bot_user_id, queue=self._queue_factory(),
            authorized_users=self._authorized_users, config=self._config, audit=self._audit,
        )


def _build_client() -> DirectGatewayClient:  # pragma: no cover — 실 기동 조립부
    from tools.multi_position_sourcing.job_queue import JobQueueClient

    config = load_discord_access_config()
    authorized_users = load_authorized_discord_users()
    return DirectGatewayClient(
        authorized_users=authorized_users, config=config,
        queue_factory=JobQueueClient,
    )


def main() -> None:  # pragma: no cover — 실 기동 진입점, 테스트에서 절대 호출하지 않는다.
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN 환경변수가 필요합니다")
    client = _build_client()
    client.run(token)


if __name__ == "__main__":  # pragma: no cover
    main()
