"""단계 C — 함대 Discord 명령 디스패처 (2026-07-11).

인가 통과한 fleet-* 인보케이션을 작업 큐(단계 A)로 잇는다. 새 로직을 만들지 않고
route_discord_invocation(인가) + job_queue(큐) 를 조합만 한다(재발명 금지).

권한(리서치 3-3):
- fleet-run / fleet-status: 인가된 멤버·owner.
- fleet-resume / fleet-cancel: owner 전용(멤버 거부).
발송 게이트(SOT28): 이 디스패처는 어떤 발송/아웃리치 함수도 부르지 않는다.
큐에는 검색 스킬(humansearch/aisearch/url)만 들어가고, 발송성 스킬은 build 단계에서 거부된다.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Sequence

from .access import DiscordAuthorizedUser
from .discord_routing import (
    DiscordAccessConfig,
    DiscordInvocation,
    route_discord_invocation,
)
from .job_queue import JobQueueClient, new_job_payload

__all__ = [
    "FLEET_COMMANDS", "OWNER_USER_IDS", "build_fleet_job_payload",
    "dispatch_fleet_command", "is_owner", "owner_user_ids_from_env",
]

FLEET_COMMANDS: tuple[str, ...] = ("fleet-run", "fleet-resume", "fleet-status", "fleet-cancel")
_OWNER_ONLY: frozenset[str] = frozenset({"fleet-resume", "fleet-cancel"})

# 사장님(밸류커넥트) Discord user id — discord_command_listener.OWNER_ID / dm_report.RECIPIENT_ID 와 동일.
# ⚠️ V1 지적: owner 는 *멤버 연락처 목록(authorized_users)* 과 분리한다. 인가된 DM 연락처는
# 팀원 3명이라, 그걸 owner 로 보면 팀원이 resume/cancel 을 얻고 사장님이 역전된다.
OWNER_USER_IDS: tuple[str, ...] = ("814353841088757800",)


def owner_user_ids_from_env(env: object = None) -> tuple[str, ...]:
    """FLEET_OWNER_DISCORD_IDS 로 owner 를 재정의(미설정 시 사장님 기본)."""
    source = os.environ if env is None else env
    raw = (source.get("FLEET_OWNER_DISCORD_IDS") or "").strip()  # type: ignore[union-attr]
    ids = tuple(x.strip() for x in raw.replace(",", " ").split() if x.strip().isdigit())
    return ids or OWNER_USER_IDS


def build_fleet_job_payload(
    options: Mapping[str, Any],
    *,
    requested_by: str,
    role: str,
) -> Optional[dict[str, Any]]:
    """fleet-run 옵션 → jobs enqueue 페이로드. 무효면 None(fail-closed).

    new_job_payload 를 그대로 재사용 — 발송성 스킬·잘못된 url/machine 은 거기서 거부된다.
    """
    skill = (options.get("skill") or "").strip()
    url = (options.get("url") or "").strip()
    params = options.get("params") or {}
    # SOT29 existing fleet default/account binding stays authoritative. Natural language
    # may select winpc only through an explicit win/windows/윈도우/winpc token.
    machine = (options.get("machine") or "macmini").strip()
    return new_job_payload(
        machine=machine, skill=skill, position_url=url,
        requested_by=requested_by, role=role, params=params,
    )


def is_owner(
    invocation: DiscordInvocation,
    *,
    owner_user_ids: Sequence[str] = OWNER_USER_IDS,
    owner_role_ids: Sequence[str] = (),
) -> bool:
    """owner 판정 = 명시적 owner user id(사장님) 또는 owner 역할 보유.

    V1: 멤버 연락처(authorized_users)와 무관하게 owner 를 결정한다 — 팀원이 owner 로 새는 것 차단.
    """
    if str(invocation.user_id) in set(owner_user_ids):
        return True
    return bool(set(invocation.member_role_ids) & set(owner_role_ids))


def _requested_by(invocation: DiscordInvocation, role: str) -> str:
    return f"{invocation.user_id}:{role}"


def dispatch_fleet_command(
    invocation: DiscordInvocation,
    *,
    authorized_users: Sequence[DiscordAuthorizedUser],
    config: DiscordAccessConfig,
    queue: Any | None = None,
    owner_user_ids: Sequence[str] = OWNER_USER_IDS,
    owner_role_ids: Sequence[str] = (),
) -> Optional[dict[str, Any]]:
    """fleet-* 인보케이션 1건 처리. 반환 dict(action=...) 또는 None(타 명령).

    action: enqueued | resumed | cancelled | status | denied | denied_owner_only | error
    """
    if invocation.command_name not in FLEET_COMMANDS:
        return None

    decision = route_discord_invocation(
        invocation, authorized_users=authorized_users, config=config)
    if not decision.allowed:
        return {"action": "denied", "reason": decision.reason}

    q = queue if queue is not None else JobQueueClient()
    owner = is_owner(invocation, owner_user_ids=owner_user_ids, owner_role_ids=owner_role_ids)
    role = "owner" if owner else "member"

    if invocation.command_name in _OWNER_ONLY and not owner:
        return {"action": "denied_owner_only",
                "reason": f"{invocation.command_name} 은 owner 전용입니다"}

    if invocation.command_name == "fleet-run":
        payload = build_fleet_job_payload(
            invocation.options or {}, requested_by=_requested_by(invocation, role), role=role)
        if payload is None:
            return {"action": "error", "reason": "잡 페이로드 무효(스킬/URL/머신 확인)"}
        job = q.enqueue(payload)
        try:
            from .fleet_worker import discord_notify
            discord_notify(
                job if isinstance(job, Mapping) else payload,
                f"📥 job enqueue 완료 — job #{(job or {}).get('id', '?')} "
                f"machine={payload['machine']} skill={payload['skill']}",
            )
        except Exception:
            # Queue success is authoritative; notification failures remain fail-soft.
            pass
        return {"action": "enqueued", "job": job}

    if invocation.command_name == "fleet-status":
        out: dict[str, Any] = {"action": "status", "jobs": q.recent(10)}
        # SOT30 인수기준 3 — 머신별 heartbeat 나이(초). 일꾼 생존을 명령 한 번으로.
        fetch_hb = getattr(q, "heartbeats_epoch", None)
        if callable(fetch_hb):
            import time as _time

            from .fleet_heartbeat import heartbeat_ages
            try:
                out["heartbeats"] = heartbeat_ages(
                    fetch_hb(), now_epoch=int(_time.time()))
            except Exception as exc:  # noqa: BLE001 — 표시 실패를 숨기지 않되 status 는 살림
                out["heartbeats"] = {"error": str(exc)[:200]}
        return out

    # resume / cancel — owner 확정됨
    job_id = _parse_job_id(invocation.options)
    if job_id is None:
        return {"action": "error", "reason": "job 옵션(양의 정수)이 필요합니다"}
    if invocation.command_name == "fleet-resume":
        return {"action": "resumed", "job": q.resume(job_id)}
    return {"action": "cancelled", "job": q.cancel(job_id, "Discord fleet-cancel")}


def _parse_job_id(options: Mapping[str, str] | None) -> Optional[int]:
    raw = (options or {}).get("job", "")
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None
