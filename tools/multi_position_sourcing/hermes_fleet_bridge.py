"""Hermes 게이트웨이 플러그인 어댑터 — fleet-* 명령을 기존 dispatch_fleet_command 로 위임.

Hermes 의 ``PluginContext.register_command()`` 핸들러 계약은 ``fn(raw_args: str) -> str | None``
뿐이라 발신자 식별자를 안 준다(hermes_cli/plugins.py:414 확인, 구조적 한계). 그래서 이 모듈은
발신자 식별자(``gateway_user_id``)를 **명시 인자로 강제**하고, 비어 있으면 사장님으로도 팀원으로도
간주하지 않고 무조건 거부한다(fail-closed) — Hermes 쪽 배선(``pre_gateway_dispatch`` 훅으로
``event.sender_id`` 를 미리 확보)이 이 값을 채우는 책임을 진다. 이 모듈 자체는 그 배선을 하지 않는다
(플러그인 ``__init__.py`` 쪽 책임 — 재검증은 여기서 fail-closed 게이트로만).

권한·큐 로직은 재구현하지 않는다 — discord_routing.route_discord_invocation +
fleet_dispatch.dispatch_fleet_command(단일출처)를 그대로 감싼다.
"""

from __future__ import annotations

import shlex
from typing import Any, Mapping, Sequence

from .access import DiscordAuthorizedUser, load_authorized_discord_users
from .discord_routing import DiscordAccessConfig, DiscordInvocation
from .fleet_dispatch import FLEET_COMMANDS, dispatch_fleet_command

FLEET_PLUGIN_COMMANDS: tuple[str, ...] = FLEET_COMMANDS  # ("fleet-run","fleet-resume","fleet-status","fleet-cancel")

_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "fleet-run": frozenset({"skill", "url", "machine"}),
    "fleet-status": frozenset(),
    "fleet-resume": frozenset({"job"}),
    "fleet-cancel": frozenset({"job"}),
}


class HermesFleetBridgeError(ValueError):
    """플러그인 입력이 계약을 벗어남(fail-closed) — 명령/필드/신원 검증 실패."""


def parse_hermes_fleet_args(command: str, raw_args: str) -> dict[str, str]:
    """``key:value key2:value2`` 형태만 허용. 모르는 명령/필드는 조용히 무시하지 않고 거부."""
    if command not in FLEET_PLUGIN_COMMANDS:
        raise HermesFleetBridgeError(f"알 수 없는 fleet 명령: {command!r}")
    allowed = _ALLOWED_FIELDS[command]
    try:
        tokens = shlex.split(raw_args or "")
    except ValueError as exc:
        # 따옴표 안 닫힘 등 shlex 파싱 실패 — 원본 ValueError 를 그대로 새지 않게 감싼다.
        raise HermesFleetBridgeError(f"입력을 파싱할 수 없음: {exc}") from exc
    options: dict[str, str] = {}
    for token in tokens:
        if ":" not in token:
            raise HermesFleetBridgeError(f"형식 오류(키:값 아님): {token!r}")
        key, _, value = token.partition(":")
        key = key.strip()
        if key not in allowed:
            raise HermesFleetBridgeError(f"'{command}' 에 허용 안 된 필드: {key!r}")
        if key in options:
            # 같은 필드 중복 지정은 "마지막 값으로 조용히 덮어쓰기"가 아니라 명시 거부한다 —
            # 뒤에 몰래 붙은 값으로 앞 값을 밀어내는 스머글링을 fail-closed 로 막는다.
            raise HermesFleetBridgeError(f"필드 중복 지정: {key!r}")
        options[key] = value.strip()
    return options


def dispatch_hermes_fleet_command(
    command: str,
    raw_args: str,
    *,
    gateway_user_id: str,
    queue: Any = None,
    authorized_users: Sequence[DiscordAuthorizedUser] | None = None,
) -> dict[str, Any]:
    """Hermes 플러그인 커맨드 1건 처리. 성공/거부 모두 JSON 직렬화 가능한 dict 반환.

    ``gateway_user_id`` 가 비어 있으면 즉시 예외(HermesFleetBridgeError) — 이건 "거부"가
    아니라 "신원 자체를 못 믿는다"는 상위 신호라 결과 dict 가 아니라 예외로 구분한다.
    """
    if not gateway_user_id or not str(gateway_user_id).strip():
        raise HermesFleetBridgeError(
            "gateway identity missing — 실행자 식별자 없이는 사장님으로도 팀원으로도 "
            "간주하지 않고 무조건 거부한다(fail-closed)"
        )

    options = parse_hermes_fleet_args(command, raw_args)

    users = (
        authorized_users
        if authorized_users is not None
        else load_authorized_discord_users("docs/search-access.md")
    )
    invocation = DiscordInvocation(
        user_id=str(gateway_user_id).strip(),
        channel_id="hermes-dm",
        command_name=command,
        is_dm=True,
        invocation_kind="hermes-plugin",
        options=options,
    )
    config = DiscordAccessConfig(allow_dm=True)

    result = dispatch_fleet_command(
        invocation, authorized_users=users, config=config, queue=queue
    )
    # command 는 parse_hermes_fleet_args 에서 이미 FLEET_PLUGIN_COMMANDS 검증을 통과했으므로
    # dispatch_fleet_command 가 None(미지원 명령)을 반환할 일은 없다.
    assert result is not None
    return result
