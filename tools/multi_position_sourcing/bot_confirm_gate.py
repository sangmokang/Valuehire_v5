"""bot_confirm_gate.py — 쓰기형 명령 확인 게이트 G5 (AC-7, 2026-07-22).

goal §7 G5: 쓰기형 명령(/weekly·/invoice·/priority set·/job resume|cancel)은 "무엇을
바꾸는지" 요약을 먼저 보여주고, 사장님이 확인 버튼을 누른 뒤에만 실행한다. 확인 없이
시간이 지나면 만료(미실행). 확인 사실은 감사로그에 남긴다.

이 모듈은 그 불변식을 강제하는 순수 상태기다 — 부작용 0. 실제 실행/DB 변경은 호출부가
``confirm().execute is True`` 를 받은 뒤에만 수행한다. 게이트를 우회하는 실행 경로가
코드에 존재하지 않도록, "실행해도 되는가"의 유일한 판정 지점을 여기로 모은다.

fail-closed 규율:
- 알 수 없는 nonce·빈 nonce·타입 오류·만료·재사용·타인 확인 = execute=False.
- 시계는 주입(now) — 자동 만료를 위한 백그라운드 타이머 없음(만료는 confirm 시점 판정).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

# 확인 유효 시간(초). 이 시간이 지나면 확인해도 실행하지 않는다(goal §7 G5 "미확인 시 미실행").
CONFIRM_TTL_SECONDS = 300


@dataclass(frozen=True)
class PendingConfirmation:
    nonce: str
    action: str
    summary: str
    actor: str
    created_at: float


@dataclass(frozen=True)
class PendingHandle:
    """create_pending 반환 — 호출부가 사장님께 보여줄 nonce·요약."""
    nonce: str
    action: str
    summary: str


@dataclass(frozen=True)
class ConfirmResult:
    execute: bool
    action: Optional[str]
    reason: str
    audit: dict[str, Any] = field(default_factory=dict)


class ConfirmGateStore:
    """대기 확인 건 저장소. 프로세스 메모리(봇 단일 프로세스 상주 전제).

    단일 사용·만료는 confirm() 이 판정하고, 사용/만료된 건은 즉시 제거해 재사용을 막는다.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingConfirmation] = {}

    def put(self, pending: PendingConfirmation) -> None:
        self._pending[pending.nonce] = pending

    def get(self, nonce: str) -> Optional[PendingConfirmation]:
        return self._pending.get(nonce)

    def remove(self, nonce: str) -> None:
        self._pending.pop(nonce, None)


def _make_nonce(action: str, actor: str, now: float, seed: str) -> str:
    # 결정적(테스트에서 Math.random 류 불가) — action·actor·시각·seed 로 해시.
    raw = f"{action}|{actor}|{now}|{seed}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def create_pending(
    store: ConfirmGateStore, *, action: str, summary: str, actor: str,
    now: float, seed: str = "",
) -> PendingHandle:
    """변경 요약을 담은 대기 건 생성. 호출부는 nonce·summary 를 사장님께 보여준다."""
    if not action or not str(actor).strip():
        raise ValueError("action·actor 는 필수입니다(확인 게이트 대기 건).")
    nonce = _make_nonce(action, actor, now, seed or summary)
    store.put(PendingConfirmation(
        nonce=nonce, action=action, summary=summary, actor=str(actor), created_at=float(now)))
    return PendingHandle(nonce=nonce, action=action, summary=summary)


def confirm(
    store: ConfirmGateStore, nonce: Any, *, actor: str, now: float,
) -> ConfirmResult:
    """확인 1건 판정. execute=True 일 때만 호출부가 실제 실행한다(그 외 전부 미실행)."""
    def _deny(reason: str) -> ConfirmResult:
        return ConfirmResult(execute=False, action=None, reason=reason, audit={
            "action": None, "actor": str(actor), "executed": False,
            "reason": reason, "at": float(now),
        })

    if not isinstance(nonce, str) or not nonce.strip():
        return _deny("확인 토큰이 없습니다.")
    pending = store.get(nonce)
    if pending is None:
        return _deny("확인 대기 건을 찾을 수 없습니다(이미 처리됐거나 만료).")
    # 타인 확인 — 대기 건을 소모하지 않는다(올바른 사람이 이후 확인 가능).
    if str(actor) != pending.actor:
        return _deny("이 확인은 요청한 사장님 본인만 누를 수 있습니다.")
    # 만료 — 소모 후 거부(재판정 방지).
    if float(now) - pending.created_at > CONFIRM_TTL_SECONDS:
        store.remove(nonce)
        return _deny("확인 시간이 만료되었습니다. 명령을 다시 실행해 주세요.")
    # 유효 — 단일 사용: 즉시 제거해 두 번째 확인을 막는다.
    store.remove(nonce)
    return ConfirmResult(execute=True, action=pending.action, reason="확인됨", audit={
        "action": pending.action, "actor": pending.actor, "executed": True,
        "summary": pending.summary, "at": float(now),
    })
