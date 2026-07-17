"""디스코드 직결 수신기 — envelope 순수 처리 로직 (goal §5A, 2026-07-17).

Hermes LLM 계층 없이 우리 소유의 얇은 수신기가 슬래시·텍스트 명령을 받아
기존 해석기·권한·큐 계약을 재사용해 잡을 넣는다. 네트워크 의존은 전부 주입
(queue·audit·clock) — 이 모듈은 어떤 경우에도 스스로 서치·스킬·셸을 실행하지
않는다(INV-D1: 파싱→권한검사→enqueue→응답문 생성뿐).

계약 재사용·단일 파싱(INV-D3):
- 텍스트 인자 해석 = ``parse_hermes_fleet_args`` (재구현 금지)
- 권한검사 = ``dispatch_fleet_command`` 내부의 ``route_discord_invocation`` 1회.
  수신기는 성공 경로에서 스스로 route 를 또 부르지 않는다 — 파싱 실패 경로에서만
  "침묵 대상인지"를 정하기 위해 정확히 1회 부른다(경로당 1회 유지).
- 등록 = ``dispatch_fleet_command`` 경유(발송성 스킬은 큐 입구에서 거부됨, SOT28).

기존 Hermes 어댑터(hermes_fleet_bridge)와 달리 길드/채널/역할 컨텍스트를
DiscordInvocation 까지 그대로 보존한다 — 길드 allowlist(route_discord_invocation)가
처음으로 진짜로 동작한다(goal §3, DM 고정 금지).

fail-closed(INV-D6): 신원 미확인·비인가·검증 실패 이벤트는 조용히 무시하고
감사 이벤트만 남긴다(추측 실행·오류문 회신으로 명령 존재를 알려주는 것 금지).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from .access import DiscordAuthorizedUser
from .discord_routing import (
    DiscordAccessConfig,
    DiscordInvocation,
    route_discord_invocation,
)
from .fleet_dispatch import FLEET_COMMANDS, dispatch_fleet_command, is_owner
from . import fleet_dispatch as _fleet_dispatch
from .hermes_fleet_bridge import HermesFleetBridgeError, parse_hermes_fleet_args

_SNOWFLAKE_RE = re.compile(r"^[0-9]{15,22}$")

# 수신기 경유 표식 — discord_routing._response_visibility 가 모르는 kind 는
# 길드에서 public_ack_then_dm 로 떨어지지만, 실제 회신 표면은 게이트웨이(조각 C)가
# 항상 deferred ephemeral 로 강제하므로 여기 값은 감사·식별용이다.
DIRECT_INVOCATION_KIND = "direct"


@dataclass(frozen=True)
class DiscordEnvelope:
    """직결 수신기의 유일한 입구 타입 (goal §3).

    게이트웨이(조각 C)가 인터랙션/메시지를 이 모양으로 변환한다. 길드 이벤트는
    guild_id·role_ids 를 반드시 채운다 — 비우면 route 가 fail-closed 로 거부한다.
    """

    event_id: str
    user_id: str
    channel_id: str
    command: str
    raw_args: str = ""
    is_dm: bool = False
    guild_id: str = ""
    role_ids: tuple[str, ...] = ()
    platform: str = "discord"


def _render_response(result: Mapping[str, Any]) -> Optional[str]:
    """dispatch 결과 → 사람용 응답문. 비밀·원문 프롬프트·raw 예외는 싣지 않는다.

    denied(비인가)는 호출부에서 침묵 처리하므로 여기 오지 않는다.
    """
    action = result.get("action")
    if action == "enqueued":
        job = result.get("job") or {}
        job_id = job.get("id", "?") if isinstance(job, Mapping) else "?"
        machine = job.get("machine", "?") if isinstance(job, Mapping) else "?"
        skill = job.get("skill", "?") if isinstance(job, Mapping) else "?"
        return f"📥 접수 완료 — 잡 #{job_id} ({machine}/{skill}). 결과는 완료 시 보고됩니다."
    if action == "status":
        jobs = result.get("jobs") or []
        lines = [f"📊 최근 잡 {len(jobs)}건"]
        for job in jobs[:10]:
            if isinstance(job, Mapping):
                # 멤버 뷰 정보 노출 차단(goal §4): job_id/machine/skill/status 만.
                lines.append(
                    f"- #{job.get('id', '?')} {job.get('machine', '?')}/"
                    f"{job.get('skill', '?')} {job.get('status', '?')}"
                )
        return "\n".join(lines)
    if action == "resumed":
        job = result.get("job") or {}
        return f"▶️ 잡 #{job.get('id', '?') if isinstance(job, Mapping) else '?'} 재개."
    if action == "cancelled":
        job = result.get("job") or {}
        return f"⏹️ 잡 #{job.get('id', '?') if isinstance(job, Mapping) else '?'} 취소."
    if action == "denied_owner_only":
        # 인가된 멤버의 권한 부족 — 신원은 믿으므로 침묵이 아니라 안내(reason 은 자체 문구).
        return f"⛔ {result.get('reason', 'owner 전용 명령입니다')}"
    if action == "error":
        # dispatch 의 error reason 은 전부 자체 작성 안내문(fail-closed 보고) — raw 예외 아님.
        return f"⚠️ {result.get('reason', '요청을 처리하지 못했습니다')}"
    return None


def handle_envelope(
    envelope: DiscordEnvelope,
    *,
    queue: Any,
    authorized_users: Sequence[DiscordAuthorizedUser],
    config: DiscordAccessConfig,
    audit: Optional[Callable[[dict[str, Any]], Any]] = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """envelope 1건 처리 — 파싱→권한검사→enqueue→응답문. 예외를 밖으로 새지 않는다.

    반환: {handled, action, response(None=침묵), reason}.
    """

    audit_failures = 0

    def _audit(action: str, reason: str = "") -> None:
        # V1 C3 봉인: 감사 저장 실패가 수신기를 죽이면 안 된다(fail-soft 감사 —
        # 이벤트 처리·응답이 우선). 단, 유실이 조용히 사라지지도 않는다 —
        # audit_failed 로 결과에 드러내 게이트웨이가 경보를 올리게 한다(V1 재공격).
        nonlocal audit_failures
        if audit is None:
            return
        try:
            audit({
                "at": clock(), "event_id": envelope.event_id,
                "user_id": envelope.user_id, "command": envelope.command,
                "guild_id": envelope.guild_id, "channel_id": envelope.channel_id,
                "action": action, "reason": reason,
            })
        except Exception:  # noqa: BLE001
            audit_failures += 1

    def _result(action: str, response: Optional[str], reason: str) -> dict[str, Any]:
        return {
            "handled": True, "action": action, "response": response,
            "reason": reason, "audit_failed": audit_failures > 0,
        }

    def _silent(action: str, reason: str) -> dict[str, Any]:
        _audit(action, reason)
        return _result(action, None, reason)

    # ① 신원·이벤트 타입+모양 검증 — snowflake 꼴 문자열이 아니면 사장님으로도
    # 팀원으로도 간주하지 않는다. event_id 는 감사·멱등키(조각 B)의 뿌리라 같은
    # 기준(V1 C5). str() 강제변환으로 int 위조를 통과시키지 않는다(V1 재공격 item5) —
    # 게이트웨이가 아닌 타입을 보냈다는 것 자체가 버그/위조 신호다.
    typed_str_fields = (
        envelope.event_id, envelope.user_id, envelope.channel_id,
        envelope.guild_id, envelope.command, envelope.raw_args,
    )
    if (not all(isinstance(v, str) for v in typed_str_fields)
            or not all(isinstance(r, str) for r in envelope.role_ids)):
        return _silent("ignored_type", "envelope 필드 타입이 str 이 아님")
    if not _SNOWFLAKE_RE.fullmatch(envelope.user_id.strip()):
        return _silent("ignored_identity", "user_id 가 snowflake 형식이 아님")
    if not _SNOWFLAKE_RE.fullmatch(envelope.event_id.strip()):
        return _silent("ignored_event", "event_id 가 snowflake 형식이 아님")
    # V1 C4 봉인: DM 표식과 길드 컨텍스트가 동시에 오면 위조/게이트웨이 버그 신호 —
    # DM 완화 규칙으로 길드 allowlist 를 우회하지 못하게 통째로 무시한다.
    if envelope.is_dm and str(envelope.guild_id or "").strip():
        return _silent("ignored_inconsistent", "is_dm 인데 guild_id 존재")

    invocation_context = dict(
        user_id=str(envelope.user_id).strip(),
        channel_id=str(envelope.channel_id or "").strip(),
        is_dm=bool(envelope.is_dm),
        invocation_kind=DIRECT_INVOCATION_KIND,
        guild_id=str(envelope.guild_id or "").strip(),
        # 역할도 snowflake 꼴만 통과 — 이상한 형식의 권한값을 조용히 걸러낸다(V1 C5).
        member_role_ids=tuple(
            str(r) for r in envelope.role_ids if _SNOWFLAKE_RE.fullmatch(str(r))),
    )

    # ② 단일 파싱(INV-D3) — 실패 시 인가자에게만 안내(비인가자는 침묵, INV-D6).
    try:
        options = parse_hermes_fleet_args(envelope.command, envelope.raw_args)
    except HermesFleetBridgeError as exc:
        invocation = DiscordInvocation(
            command_name=envelope.command, **invocation_context)
        decision = route_discord_invocation(
            invocation, authorized_users=authorized_users, config=config)
        if not decision.allowed:
            return _silent("denied", decision.reason)
        # V1 C1 봉인: owner 전용 명령은 형식이 틀려도 비owner 에겐 정상 경로
        # (denied_owner_only)와 같은 안내 — 경로별 판정·응답이 갈라지지 않게.
        if envelope.command in _fleet_dispatch._OWNER_ONLY and not is_owner(invocation):
            _audit("denied_owner_only", str(exc))
            return _result(
                "denied_owner_only",
                f"⛔ {envelope.command} 은 owner 전용입니다", "owner 전용")
        # V1 C2 봉인: 오류 상세(사용자 입력 에코 가능)는 감사에만 — 회신은 일반 안내문.
        _audit("parse_error", str(exc))
        return _result(
            "parse_error", "⚠️ 명령 형식 오류 — 인자 형식을 확인해 주세요.", str(exc))

    # ③ 권한검사+등록 — 기존 dispatch_fleet_command 경유(권한검사는 이 안에서 1회).
    try:
        result = dispatch_fleet_command(
            DiscordInvocation(
                command_name=envelope.command, options=options, **invocation_context),
            authorized_users=authorized_users, config=config, queue=queue,
        )
    except Exception as exc:  # noqa: BLE001 — 수신기는 절대 죽지 않는다(fail-closed 보고).
        _audit("internal_error", f"{type(exc).__name__}")
        return _result(
            "internal_error",
            "⚠️ 내부 오류로 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            f"{type(exc).__name__}")

    if result is None:  # parse 가 명령을 걸렀으므로 도달 불가 — 방어적 침묵.
        return _silent("ignored_command", "미지원 명령")

    action = str(result.get("action") or "")
    if action == "denied":
        return _silent("denied", str(result.get("reason") or ""))

    _audit(action, str(result.get("reason") or ""))
    return _result(action, _render_response(result), str(result.get("reason") or ""))
