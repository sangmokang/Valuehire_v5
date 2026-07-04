"""PC-A3 — register-position Discord 디스패처 (end-to-end 글루).

인가 통과한 register-position 인보케이션을 포지션 등록 흐름으로 잇는다:
  route_discord_invocation(인가) → parse_discord_position_registration_request(파싱)
  → run_position_registration(등록, 목적지 FY26ClientsPosition 기본).

새 로직을 만들지 않고 기존 3모듈을 조합만 한다(SOT5). 부작용/발송 없음(SOT3):
run_position_registration 은 external_posting_sent=False·secret_emitted=False 를 항상 유지하며,
자동 "보내기"는 없다. 미인가·타명령·무포지션은 디스패치하지 않는다(fail-closed, DM 인가 게이트 유지).
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from .access import DiscordAuthorizedUser
from .discord_routing import (
    DiscordAccessConfig,
    DiscordInvocation,
    route_discord_invocation,
)
from .position_registration import (
    FY26_CLIENTS_POSITION_LIST_ID,
    RegistrationOutcome,
    run_position_registration,
)
from .request_parser import parse_discord_position_registration_request

__all__ = ["REGISTER_POSITION_COMMAND", "dispatch_register_position"]

REGISTER_POSITION_COMMAND = "register-position"

# 등록 파서는 "포지션 … 등록" 의도어를 요구한다(request_parser.REGISTRATION_WORD_RE). 슬래시커맨드
# 옵션(url/text/jd)을 그 파서가 인식하는 메시지로 조립한다 — 파서를 재구현하지 않는다(SOT5).
RegisterPositionFn = Callable[..., RegistrationOutcome]


def _registration_message_from_invocation(invocation: DiscordInvocation) -> str:
    options = invocation.options or {}
    url = (options.get("url") or "").strip()
    if url:
        return f"포지션 등록 {url}"
    text = (options.get("text") or options.get("jd") or "").strip()
    if text:
        return f"포지션 등록\n{text}"
    return ""


def dispatch_register_position(
    invocation: DiscordInvocation,
    *,
    authorized_users: Sequence[DiscordAuthorizedUser],
    config: DiscordAccessConfig,
    register_position: RegisterPositionFn = run_position_registration,
    clickup_list_id: str = FY26_CLIENTS_POSITION_LIST_ID,
    dry_run: bool = True,
    **registration_deps: object,
) -> Optional[RegistrationOutcome]:
    """인가 통과한 register-position 인보케이션을 등록 흐름으로 정확히 1회 디스패치.

    반환: 등록 결과(RegistrationOutcome) 또는 None(디스패치 안 함 — 미인가/타명령/무포지션).
    - 인가/라우팅은 route_discord_invocation 재사용(약화 금지). decision.allowed 아니면 None.
    - 목적지는 FY26ClientsPosition 기본(PC-A1). dry_run 기본 True(부작용 없는 안전 기본).
    - run_position_registration 은 발송을 하지 않는다(SOT3) — 이 디스패처도 "보내기" 없음.
    """
    if invocation.command_name != REGISTER_POSITION_COMMAND:
        return None

    decision = route_discord_invocation(
        invocation, authorized_users=authorized_users, config=config
    )
    if not decision.allowed:
        return None

    message = _registration_message_from_invocation(invocation)
    parse_result = parse_discord_position_registration_request(message)
    if not parse_result.should_route_to_registration:
        return None

    return register_position(
        parse_result,
        clickup_list_id=clickup_list_id,
        dry_run=dry_run,
        **registration_deps,
    )
