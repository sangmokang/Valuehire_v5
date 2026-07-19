"""디스코드 직결 게이트웨이 — 조각 C (얇은 수신기, goal §5C).

Discord 실 게이트웨이(websocket)에 discord.py(버전 고정, requirements-dev.txt)로 접속해
슬래시/텍스트 인터랙션을 받아 ``DiscordEnvelope`` 로 변환 → 기존
``tools.multi_position_sourcing.direct_receiver.handle_envelope()`` 를 호출 → 응답
전송까지만 한다. 이 스크립트는 스스로 서치·스킬·셸을 실행하지 않는다(INV-D1,
enqueue-only — 실행 능력은 handle_envelope 안 주입된 큐에만 있다).

지킬 것(goal §2·§3·§6·§9 그대로), Codex Rescue 2차 적대검증(NEEDS-FIX 5건) 반영 후:

1. **슬래시 3초 규칙**: ``interaction.response.defer(ephemeral=True)`` 를 항상 함수의
   첫 줄에서 호출한다. 큐 생성(``queue_factory()``)이 실패해도 defer 는 이미 끝난 뒤라
   discord 쪽 3초 마감을 어기지 않는다 — 운영 배선(``DirectGatewayClient.on_interaction``)
   도 큐를 미리 만들지 않고 ``queue_factory`` 콜러블만 넘겨 defer 이후에 지연 평가한다
   (V1 지적: 예전엔 인터랙션 호출 인자 평가 시점에 큐가 먼저 만들어져 defer 도달 전에
   예외가 날 수 있었다).
2. **이벤트 루프 비차단**: ``handle_envelope()`` 는 동기 함수이고 내부 큐 net I/O 가
   최대 30초 걸릴 수 있어(``job_queue.py`` 참고), 그대로 부르면 같은 프로세스의 다른
   인터랙션 응답이 그동안 막힌다. ``asyncio.to_thread()`` 로 스레드에 위임한다.
3. **최소권한(INV-D5)**: 게이트웨이 프로세스는 ``job_queue.JobQueueClient()`` 기본
   생성자(=SUPABASE_SERVICE_ROLE_KEY, 관리자급)를 절대 쓰지 않는다.
   ``DISCORD_GATEWAY_SUPABASE_URL``/``DISCORD_GATEWAY_SUPABASE_KEY`` 전용 최소권한
   자격만 읽고, 없으면 기동을 거부한다(fail-closed) — 관리자급 키로 조용히 폴백하지
   않는다.
4. **감사 기록 기본 배선**: 운영 조립부(``_build_client``)는 ``_default_audit`` 를
   기본으로 주입한다 — 침묵(response=None) 이벤트도 로그에는 남는다(사용자에게만 숨김).
5. **명령 소유권 일치**: 등록하는 슬래시 명령 = ``fleet_dispatch.FLEET_COMMANDS`` 처리
   로직이 실제로 있는 것만. ``slash_commands_to_register()`` 는 ``FLEET_COMMANDS`` 를
   직접 참조해 동적으로 따라간다(하드코딩 목록 아님). 기동 시(``setup_hook``)
   ``register_discord_commands.bulk_register_discord_commands`` 를 이 필터된 목록으로
   호출해 실제로 배선한다(예전엔 함수만 있고 아무도 안 부르는 죽은 코드였음).
6. **envelope 필드 보존**: 길드 인터랙션이면 guild_id/channel_id/role_ids 를 실제로
   채운다(기존 hermes_fleet_bridge 어댑터처럼 DM 고정 금지).
7. **텍스트 명령 범위(goal §3)**: 기본은 owner DM + 봇 멘션만 — 인가된 일반 멤버의
   자유 DM 은 처리하지 않는다(``handle_text_message`` 가 owner_user_ids 로 명시 필터).
8. **fail-closed 침묵의 discord.py 요구사항 절충**: defer 로 1차 응답을 이미 보냈으므로
   discord API 는 그 인터랙션에 최종 응답을 요구한다. response=None(=침묵 대상,
   비인가/신원미상/미지원 전부 포함) 케이스는 사유와 무관하게 항상 동일한 무정보
   ack(``_GENERIC_SILENT_ACK``)만 보낸다 — 사유별 회신 차이가 "명령이 적용된다/안
   된다"는 신호가 되는 것을 막는다. 첫 회신은 discord 공식 문서가 권고하는
   ``interaction.edit_original_response()`` 로 보낸다(defer 후 첫 followup 을 원응답
   수정으로 취급하는 하위호환 동작에 기대지 않음).
9. **비밀 미노출(INV-D5)**: 봇 토큰·예외 원문을 디스코드로 보내지 않는다.
10. **네트워크 0 in 단위테스트**: tests/test_discord_direct_gateway.py 는 discord.py 실
    websocket/HTTP 를 켜지 않는다. 단, 인가된 fleet-run 성공 경로는 기존
    ``fleet_dispatch.dispatch_fleet_command`` → ``fleet_worker.discord_notify`` 를
    그대로 통과하므로(조각 A/B 기존 코드, 알림 주입 분리는 조각 F 범위), 로컬에
    ``DISCORD_BOT_TOKEN``/``DISCORD_WEBHOOK_URL_OPS_HEALTH`` 가 실재하면 진짜 HTTP 가
    나갈 수 있다 — 테스트는 ``fleet_worker.discord_notify`` 를 패치해 무조건 무력화한다
    (``tests/test_direct_receiver.py`` 의 ``_NotifySilencedCase`` 와 동일 패턴 재사용).
"""

from __future__ import annotations

import asyncio
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
from tools.multi_position_sourcing.fleet_dispatch import FLEET_COMMANDS, OWNER_USER_IDS

logger = logging.getLogger("discord_direct_gateway")
# Codex 2차검증 재재현: logger.info() 만으로는 루트 로거에 핸들러가 없으면(기본 파이썬
# 상태) 아무 것도 출력되지 않아 "감사 배선"이 이름뿐이었다 — 이 모듈 전용 핸들러를
# 붙여 외부 logging.basicConfig() 호출 여부와 무관하게 항상 보이게 한다(중복 부착 방지).
if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False  # 루트 로거 설정에 좌우되지 않고 항상 자기 핸들러로만 출력.

_SNOWFLAKE_RE = re.compile(r"^[0-9]{15,22}$")

# response=None(침묵) 인 모든 사유에 공통으로 쓰는 무정보 ack — §8 참고. 내용을 절대
# 사유별로 분기하지 않는다(그 차이 자체가 신호가 됨).
_GENERIC_SILENT_ACK = "🔕"
_RESPONSE_CHAR_LIMIT = 1900  # goal §4 — 1,900자 분할 회신 계약과 동일 상한(단발 회신도 안전측 절단).

# INV-D5 — 게이트웨이 자신의 큐 자격증명은 job_queue.JobQueueClient() 기본값
# (SUPABASE_SERVICE_ROLE_KEY, 관리자급)을 절대 쓰지 않는다. 전용 최소권한 env 만.
QUEUE_URL_ENV = "DISCORD_GATEWAY_SUPABASE_URL"
QUEUE_KEY_ENV = "DISCORD_GATEWAY_SUPABASE_KEY"


def backup_current_discord_commands(
    *, application_id: str, bot_token: str, guild_id: str = "",
    backup_dir: str = ".harness/discord-command-backups",
) -> Optional[str]:
    """goal §3 "등록 롤백" — 전체 PUT 교체 전에 기존 명령 payload 를 파일로 백업한다.

    ``register_discord_commands.discord_command_registration_url()`` 를 그대로 재사용해
    같은 엔드포인트를 GET 한다(URL 조립 로직 복제 금지). 실패(네트워크·권한 등)하면
    None 을 반환 — 호출부는 백업 없이는 PUT 을 진행하지 않는다(fail-closed 롤백 안전망).
    """
    import json
    import time
    import urllib.error
    import urllib.request
    from pathlib import Path

    from tools.multi_position_sourcing.register_discord_commands import (
        discord_command_registration_url,
    )

    url = discord_command_registration_url(application_id, guild_id)
    req = urllib.request.Request(
        url, method="GET",
        headers={"Authorization": f"Bot {bot_token}", "User-Agent": "Valuehire-Multisearch/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            current_commands = json.loads(body) if body else []
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None

    out_dir = Path(backup_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        out_path = out_dir / f"discord-commands-{application_id}-{guild_id or 'global'}-{stamp}.json"
        out_path.write_text(json.dumps(current_commands, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return None
    return str(out_path)


def slash_commands_to_register() -> list[dict[str, Any]]:
    """명령 소유권 일치(goal §3) — FLEET_COMMANDS 처리 로직이 실제 있는 명령만 등록.

    ``FLEET_COMMANDS`` 를 하드코딩 복제하지 않고 직접 참조한다 — 그 값이 바뀌면
    등록 대상도 같이 따라간다(정적 목록 고정 아님, Codex 2차검증 반박 반영).
    """
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
    파싱은 Message Content 인텐트가 필요해 기본 범위 밖(goal §3). owner DM 전용 제한은
    이 함수가 아니라 호출부(``handle_text_message``)의 정책이다 — 이 함수는 순수 변환만.
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


async def _safe_first_reply(interaction: Any, content: str, *, event_id: str) -> None:
    """defer 이후 첫(그리고 유일한) 회신 — discord 권고대로 원응답 수정을 우선 시도.

    ``edit_original_response`` 가 없는(구버전/기타) 대상이면 followup.send 로 대체.
    전송 실패가 게이트웨이를 죽이면 안 되므로 예외는 로그로만 남긴다.
    """
    try:
        editor = getattr(interaction, "edit_original_response", None)
        if callable(editor):
            await editor(content=content)
        else:
            await interaction.followup.send(content, ephemeral=True)
    except Exception:  # noqa: BLE001 — 전송 실패를 게이트웨이 크래시로 번지게 하지 않는다.
        logger.warning("discord_direct_gateway: 회신 전송 실패 event_id=%s", event_id)


async def handle_slash_interaction(
    interaction: Any,
    *,
    queue: Any = None,
    queue_factory: Optional[Callable[[], Any]] = None,
    authorized_users: Sequence[DiscordAuthorizedUser],
    config: DiscordAccessConfig,
    audit: Optional[Callable[[dict[str, Any]], Any]] = None,
    clock: Optional[Callable[[], float]] = None,
) -> dict[str, Any]:
    """슬래시 인터랙션 1건 처리 — 3초 규칙(goal §3) 준수: defer 가 항상 첫 호출.

    ``queue`` 를 직접 주면(테스트) 그걸 쓰고, 없으면 ``queue_factory()`` 를 defer *뒤*에
    지연 호출한다 — 큐 생성 실패가 3초 데드라인 안쪽에서 나든 밖에서 나든 defer 는 이미
    끝난 뒤라 무관하다(V1 지적 반영: 예전엔 호출부가 인자 평가 시점에 큐를 미리 만들어
    defer 도달 전에 예외가 날 수 있었다).
    """
    await interaction.response.defer(ephemeral=True)  # net I/O(handle_envelope) 전에 반드시 먼저.

    envelope = interaction_to_envelope(interaction)
    if envelope is None:
        await _safe_first_reply(interaction, _GENERIC_SILENT_ACK, event_id="?")
        return {"handled": False, "action": "unsupported_interaction", "response": None}

    try:
        resolved_queue = queue if queue is not None else queue_factory()  # type: ignore[misc]
    except Exception:  # noqa: BLE001 — 큐 생성 실패도 fail-closed 보고, 크래시 금지.
        logger.warning(
            "discord_direct_gateway: queue_factory 실패 event_id=%s", envelope.event_id)
        await _safe_first_reply(interaction, _GENERIC_SILENT_ACK, event_id=envelope.event_id)
        return {"handled": False, "action": "internal_error", "response": None}

    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    # handle_envelope 는 동기(최대 30초 큐 net I/O) — 이벤트 루프를 막지 않도록 스레드 위임.
    result = await asyncio.to_thread(
        handle_envelope, envelope, queue=resolved_queue, authorized_users=authorized_users,
        config=config, audit=audit, **kwargs,
    )

    response = result.get("response")
    outgoing = _GENERIC_SILENT_ACK if response is None else response[:_RESPONSE_CHAR_LIMIT]
    await _safe_first_reply(interaction, outgoing, event_id=envelope.event_id)
    return result


async def handle_text_message(
    message: Any,
    *,
    bot_user_id: str,
    queue: Any = None,
    queue_factory: Optional[Callable[[], Any]] = None,
    authorized_users: Sequence[DiscordAuthorizedUser],
    config: DiscordAccessConfig,
    audit: Optional[Callable[[dict[str, Any]], Any]] = None,
    clock: Optional[Callable[[], float]] = None,
    owner_user_ids: Sequence[str] = OWNER_USER_IDS,
) -> Optional[dict[str, Any]]:
    """봇 멘션/DM 텍스트 명령 1건 처리. 지원 명령이 아니면 None(네트워크 접촉 0).

    goal §3 — 텍스트 명령 기본 범위는 owner DM + 봇 멘션만. 인가된 일반 멤버의 DM
    자유텍스트는 여기서 걸러 큐에 닿지 않게 한다(길드 멘션은 route_discord_invocation
    의 채널/역할 allowlist 가 이미 걸러주므로 이 함수에서 추가 제한하지 않는다).
    """
    envelope = message_to_envelope(message, bot_user_id=bot_user_id)
    if envelope is None:
        return None
    if envelope.is_dm and str(envelope.user_id) not in set(str(u) for u in owner_user_ids):
        return None

    try:
        resolved_queue = queue if queue is not None else queue_factory()  # type: ignore[misc]
    except Exception:  # noqa: BLE001
        logger.warning(
            "discord_direct_gateway: queue_factory 실패(text) event_id=%s", envelope.event_id)
        return {"handled": False, "action": "internal_error", "response": None}

    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    result = await asyncio.to_thread(
        handle_envelope, envelope, queue=resolved_queue, authorized_users=authorized_users,
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


def _default_audit(event: Mapping[str, Any]) -> None:
    """운영 기본 감사 배선(§4) — 사용자에게는 숨겨도(§8) 로그에는 남긴다."""
    logger.info("discord_direct_gateway audit: %s", dict(event))


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
        owner_user_ids: Sequence[str] = OWNER_USER_IDS,
    ) -> None:
        super().__init__(intents=discord.Intents.default())
        self._authorized_users = authorized_users
        self._config = config
        self._queue_factory = queue_factory
        self._audit = audit if audit is not None else _default_audit
        self._owner_user_ids = owner_user_ids

    async def setup_hook(self) -> None:  # pragma: no cover — 실 기동 전용
        await self._sync_commands()

    async def _sync_commands(self) -> None:  # pragma: no cover — 실 네트워크 진입점
        """명령 소유권 일치(goal §3) — FLEET_COMMANDS 교집합만 실제로 등록한다.

        register_discord_commands.py 를 새로 만들지 않고 그 함수를 그대로 재사용(단일
        출처) — payloads 만 slash_commands_to_register() 로 필터해서 넘긴다.

        goal §3 "등록 롤백": 전체 PUT 교체 전에 기존 명령 payload 를 파일로 백업한다
        (Codex 2차검증 재재현 지적 — 예전엔 백업 없이 바로 덮어썼다).
        """
        application_id = os.environ.get("DISCORD_CLIENT_ID", "").strip()
        if not application_id:
            logger.warning("discord_direct_gateway: DISCORD_CLIENT_ID 미설정 — 명령 등록 생략")
            return
        token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
        guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
        backup_path = backup_current_discord_commands(
            application_id=application_id, bot_token=token, guild_id=guild_id)
        if backup_path is None:
            logger.warning(
                "discord_direct_gateway: 명령 등록 전 백업 실패 — 롤백 안전망 없이 "
                "PUT 을 진행하지 않고 등록을 건너뜁니다(fail-closed).")
            return
        logger.info("discord_direct_gateway: 기존 명령 백업 완료 %s", backup_path)

        from tools.multi_position_sourcing.register_discord_commands import (
            bulk_register_discord_commands,
        )
        result = bulk_register_discord_commands(
            application_id=application_id, bot_token=token, guild_id=guild_id,
            payloads=slash_commands_to_register(),
        )
        if not result.get("ok"):
            logger.warning("discord_direct_gateway: 명령 등록 실패 %s", result)

    async def on_interaction(self, interaction: discord.Interaction) -> None:  # pragma: no cover
        if getattr(interaction, "type", None) != discord.InteractionType.application_command:
            return
        # queue 를 여기서 미리 만들지 않는다 — handle_slash_interaction 이 defer 뒤에
        # queue_factory() 를 호출해야 3초 규칙이 큐 생성 실패와 무관하게 지켜진다.
        await handle_slash_interaction(
            interaction, queue_factory=self._queue_factory,
            authorized_users=self._authorized_users, config=self._config, audit=self._audit,
        )

    async def on_message(self, message: discord.Message) -> None:  # pragma: no cover
        if message.author.bot:
            return
        bot_user = self.user
        bot_user_id = str(bot_user.id) if bot_user is not None else ""
        await handle_text_message(
            message, bot_user_id=bot_user_id, queue_factory=self._queue_factory,
            authorized_users=self._authorized_users, config=self._config, audit=self._audit,
            owner_user_ids=self._owner_user_ids,
        )


class MinimalPrivilegeQueueClient:
    """INV-D5 최소권한 큐 클라이언트 — ``public.jobs`` 테이블에 직접 닿지 않는다.

    ``job_queue.JobQueueClient``(관리자급, 테이블 직접 SELECT/INSERT)와 달리 이
    클라이언트는 ``supabase/migrations/20260719_discord_gateway_minimal_privilege_rpc.sql``
    이 만드는 4개 RPC 함수(``discord_gateway_enqueue``/``discord_gateway_recent_jobs``/
    ``discord_gateway_job_by_idempotency_key``/``resume_job``/``cancel_job``)만 호출한다.
    그 마이그레이션이 anon 키에게 이 함수들 밖의 모든 직접 테이블 권한을 revoke 해두므로,
    이 키가 유출돼도 블라스트 반경은 "이 RPC 호출"로 좁혀진다(전체 DB 관리자 권한이
    아님) — Codex Rescue 4차 재검증이 지적한 "문자열 비교만으로는 실제 제한을 증명 못
    한다"는 결함을 DB grant 로 실제로 해소한다.

    ``handle_envelope`` → ``dispatch_fleet_command`` 가 기대하는 큐 인터페이스
    (enqueue/recent/resume/cancel)만 구현한다 — claim_next/release/heartbeats_epoch 등
    워커 전용 메서드는 이 클라이언트가 아예 갖지 않는다(게이트웨이가 워커 역할을 할
    이유가 없음, INV-D1).

    정직한 한계(verdict 에도 명시): 이 마이그레이션은 코드로만 존재하며, 이 worktree
    에서 라이브 Supabase 에 자동 적용되지 않는다(``supabase db push`` 는 별도 배포
    단계, goal §7 조각 J 라이브 검증 게이트). 적용 전에는 이 클라이언트의 모든 호출이
    "함수를 찾을 수 없음" 으로 실패한다 — 안전측 실패(관리자 키로 자동 폴백 없음)이지
    기능 동작을 보장하지 않는다.
    """

    def __init__(self, url: str, key: str) -> None:
        self.url = url.rstrip("/")
        self.key = key

    def _rpc(self, name: str, payload: dict[str, Any]) -> Any:
        import json as _json
        import urllib.error as _urllib_error
        import urllib.request as _urllib_request

        req = _urllib_request.Request(
            f"{self.url}/rest/v1/rpc/{name}",
            data=_json.dumps(payload).encode(),
            method="POST",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
        )
        try:
            with _urllib_request.urlopen(req, timeout=30) as response:
                body = response.read().decode() or "null"
            return _json.loads(body)
        except _urllib_error.HTTPError:
            raise  # 호출부(enqueue)가 409(idempotency 충돌)를 구분해서 처리한다.

    def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        """조각 B(원자적 enqueue-or-get, INV-D2) 를 RPC 경로에서도 유지한다.

        ``new_job_payload`` 재검증은 이미 ``fleet_dispatch.build_fleet_job_payload`` 가
        호출단에서 했지만, ``JobQueueClient.enqueue`` 와 동일하게 여기서도 다시
        재검증한다(신뢰 경계마다 재확인, V1 결함 6 패턴 재사용) — 최종 강제는 RPC 안
        SQL 검증이다. SSRF 방지(``url_host_resolves_public``)도 그대로 재사용.
        """
        import urllib.error

        from tools.multi_position_sourcing.job_queue import (
            JobQueueConflictError,
            new_job_payload,
            url_host_resolves_public,
        )

        if not isinstance(payload, dict):
            raise ValueError("new_job_payload 로 만든 페이로드만 enqueue 가능")
        revalidated = new_job_payload(
            machine=payload.get("machine"), skill=payload.get("skill"),
            position_url=payload.get("position_url"), requested_by=payload.get("requested_by"),
            role=payload.get("role"), params=payload.get("params"),
            account_key=payload.get("account_key", ""),
        )
        if revalidated is None or payload.get("status") != "queued":
            raise ValueError("무효 페이로드 — new_job_payload 검증 실패")
        if not url_host_resolves_public(revalidated["position_url"]):
            raise ValueError(
                "position_url 호스트가 공인 주소로 해석되지 않음(사설/loopback/메타데이터 거부)")

        idem_raw = (revalidated.get("params") or {}).get("idempotency_key")
        idem = "" if idem_raw is None else str(idem_raw)
        try:
            rows = self._rpc("discord_gateway_enqueue", {
                "p_machine": revalidated["machine"], "p_skill": revalidated["skill"],
                "p_position_url": revalidated["position_url"],
                "p_requested_by": revalidated["requested_by"], "p_role": revalidated["role"],
                "p_params": revalidated.get("params") or {},
                "p_account_key": revalidated.get("account_key", ""),
            })
        except urllib.error.HTTPError as exc:
            if exc.code == 409 and idem:
                existing = self.job_by_idempotency_key(idem)
                if existing is not None:
                    return existing
            raise JobQueueConflictError(f"enqueue 실패(HTTP {exc.code})") from None
        return rows[0] if isinstance(rows, list) and rows else rows

    def job_by_idempotency_key(self, key: str) -> Optional[dict[str, Any]]:
        rows = self._rpc("discord_gateway_job_by_idempotency_key", {"p_key": str(key)})
        return rows[0] if isinstance(rows, list) and rows else None

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._rpc("discord_gateway_recent_jobs", {"p_limit": max(1, min(int(limit), 50))})
        return rows if isinstance(rows, list) else []

    def resume(self, job_id: int) -> Any:
        if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
            raise ValueError(f"invalid job_id: {job_id!r}")
        rows = self._rpc("resume_job", {"p_job_id": job_id})
        return rows[0] if isinstance(rows, list) and rows else rows

    def cancel(self, job_id: int, reason: str = "") -> Any:
        rows = self._rpc("cancel_job", {"p_job_id": job_id, "p_reason": reason})
        return rows[0] if isinstance(rows, list) and rows else rows


def _minimal_privilege_queue_factory() -> Callable[[], Any]:  # pragma: no cover — 실 기동 조립부
    """INV-D5 — SUPABASE_SERVICE_ROLE_KEY(관리자급)를 이 프로세스에 절대 주지 않는다.

    전용 최소권한 자격(``DISCORD_GATEWAY_SUPABASE_URL``/``DISCORD_GATEWAY_SUPABASE_KEY``
    — 운영에서는 프로젝트의 표준 anon 키를 넣는다, 커스텀 JWT 발급 불필요)만 읽는다.
    미설정이면 ``JobQueueClient()`` 기본 생성자(관리자급 키 자동 폴백)로 조용히
    넘어가지 않고 기동 자체를 거부한다. 반환 클라이언트는 ``JobQueueClient`` 가 아니라
    ``MinimalPrivilegeQueueClient`` — DB 레벨에서 실제로 4개 RPC 함수만 호출 가능하도록
    제한된다(문자열 비교 방어만으로는 부족하다는 Codex 4차 재검증 지적 반영).
    """
    url = os.environ.get(QUEUE_URL_ENV, "").strip()
    key = os.environ.get(QUEUE_KEY_ENV, "").strip()
    if not url or not key:
        raise SystemExit(
            f"{QUEUE_URL_ENV}/{QUEUE_KEY_ENV} 환경변수가 필요합니다 — 게이트웨이는 "
            "SUPABASE_SERVICE_ROLE_KEY(관리자급)를 직접 쓰지 않는다(INV-D5 최소권한)."
        )
    # 방어적 2중 검사(Codex 2차검증 재재현 지적: "관리자급 키를 전용 env 에 넣어도 그대로
    # 수용") — 이름만 다른 변수에 관리자 키를 그대로 복붙하는 흔한 설정 실수를 최소한
    # 문자열 비교로 걸러낸다. 이건 방어의 1층일 뿐이고, 진짜 강제는
    # MinimalPrivilegeQueueClient 가 RPC 밖 테이블에 절대 안 닿는다는 것(2층, DB grant).
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if service_role_key and key == service_role_key:
        raise SystemExit(
            f"{QUEUE_KEY_ENV} 값이 SUPABASE_SERVICE_ROLE_KEY(관리자급)와 동일합니다 — "
            "전용 최소권한 키를 발급해 주입하라(INV-D5). 이 방어는 문자열 일치만 잡으며, "
            "실제 DB 쪽 제한 역할/RLS 를 대체하지 않는다."
        )
    return lambda: MinimalPrivilegeQueueClient(url=url, key=key)


def _build_client() -> DirectGatewayClient:  # pragma: no cover — 실 기동 조립부
    config = load_discord_access_config()
    authorized_users = load_authorized_discord_users()
    # Codex 2차검증 재재현 CRITICAL: owner_user_ids_from_env()(FLEET_OWNER_DISCORD_IDS)
    # 를 여기서만 쓰면, 이 값이 게이트웨이의 텍스트 DM 범위 필터에는 반영되는데
    # direct_receiver.handle_envelope → dispatch_fleet_command 내부의 owner 판정(resume/
    # cancel 등 owner 전용 명령 허용 여부)은 fleet_dispatch.OWNER_USER_IDS 고정값만 보고
    # 전혀 이 값을 받지 않는다(그 경로는 이 조각 밖 — direct_receiver.py 수정은 범위
    # 밖). 두 지점이 다른 owner 를 참조하면 "새 owner 는 DM 은 통과하지만 resume/cancel
    # 은 거부당하는" 불일치가 실제로 재현된다. 이 조각은 fleet_dispatch 쪽을 못 고치므로,
    # 대신 게이트웨이 전역에서 항상 같은 고정 OWNER_USER_IDS 를 쓰게 해 최소한 자기
    # 안에서는 일관되게 만든다 — FLEET_OWNER_DISCORD_IDS 로 owner 를 바꾸고 싶다면
    # fleet_dispatch/direct_receiver 쪽까지 같이 배선하는 별도 작업이 필요하다(한계로
    # verdict 에 명시).
    return DirectGatewayClient(
        authorized_users=authorized_users, config=config,
        queue_factory=_minimal_privilege_queue_factory(),
        audit=_default_audit,
        owner_user_ids=OWNER_USER_IDS,
    )


def main() -> None:  # pragma: no cover — 실 기동 진입점, 테스트에서 절대 호출하지 않는다.
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN 환경변수가 필요합니다")
    client = _build_client()
    client.run(token)


if __name__ == "__main__":  # pragma: no cover
    main()
