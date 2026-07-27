"""AC-7 — 사람 개입 감지(30초 자동재개) + 캡차 감지·중단·알림.

근거: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-7, §6 E1/E2/E8.

설계 원칙:
- 시계(clock)와 알림(notifier)은 주입식 — 실제 sleep·실제 Discord 발신 없이
  테스트에서 타임스탬프로 결정론적으로 검증한다.
- 캡차/클라우드플레어/2FA/체크포인트는 자동 우회를 시도하지 않는다(E1).
  우회용 API 자체를 제공하지 않는다.
- 표에 없는 신호도 명시적 중단한다(E8 catch-all — 임의 추정 금지).
"""

from __future__ import annotations

import enum
from typing import Callable, Optional, Protocol

#: D1 — 마지막 사람 입력으로부터 자동 재개까지의 무입력 대기시간(초).
#: SOT29의 60초와 별개인 이 서비스(aisearch) 전용 상수.
RESUME_DELAY_SECONDS: float = 30.0

#: E1 — 자동 우회 금지 + 즉시 중단 + Discord 알림 대상 신호(표에 있는 것).
BLOCKING_SIGNALS: frozenset[str] = frozenset(
    {"captcha", "cloudflare", "2fa", "checkpoint"}
)


class Notifier(Protocol):
    """주입식 알림 인터페이스 — 실제 발신 구현은 호출자가 주입한다."""

    def notify(self, message: str) -> None: ...


class MonitorState(enum.Enum):
    RUNNING = "running"  # 자동 조작 허용
    PAUSED_HUMAN = "paused_human"  # 사람 개입 감지 — 30초 무입력 대기(E2)
    ABORTED = "aborted"  # 명시적 중단 — 자동 재개 없음(E1/E8)


class InterventionMonitor:
    """사람 개입·차단 신호 상태 기계.

    clock: 현재 시각(초, 단조 증가)을 돌려주는 주입식 시계.
    notifier: 중단 사유를 전달할 주입식 알림 채널(Discord 등).
    """

    def __init__(self, clock: Callable[[], float], notifier: Notifier) -> None:
        self._clock = clock
        self._notifier = notifier
        self._state = MonitorState.RUNNING
        self._last_human_input_at: Optional[float] = None

    @property
    def state(self) -> MonitorState:
        return self._state

    def automation_allowed(self) -> bool:
        """자동 조작을 계속해도 되는지 — RUNNING일 때만 True."""
        return self._state is MonitorState.RUNNING

    def on_human_input(self) -> None:
        """사람 마우스/키보드 입력 감지 — 즉시 정지, 재개 타이머 리셋(E2).

        ABORTED 이후에는 상태를 되살리지 않는다.
        """
        if self._state is MonitorState.ABORTED:
            return
        self._last_human_input_at = self._clock()
        self._state = MonitorState.PAUSED_HUMAN

    def on_signal(self, kind: str) -> None:
        """차단 신호 처리 — 표에 있든 없든 명시적 중단(E1/E8).

        자동 우회를 시도하지 않고 즉시 중단 + 알림 1회.
        """
        if self._state is MonitorState.ABORTED:
            return
        self._state = MonitorState.ABORTED
        if kind in BLOCKING_SIGNALS:
            reason = f"차단 신호 감지({kind}) — 자동 우회 금지, 즉시 중단(E1)"
        else:
            reason = f"표에 없는 신호 감지({kind}) — 명시적 중단(E8 catch-all)"
        self._notifier.notify(reason)

    def poll(self) -> MonitorState:
        """주기 점검 — 마지막 입력 후 30초(D1) 무입력이면 자동 재개.

        29.9초처럼 30초 미만이면 재개하지 않는다. ABORTED는 절대 재개하지 않는다.
        """
        if self._state is MonitorState.PAUSED_HUMAN:
            assert self._last_human_input_at is not None
            idle = self._clock() - self._last_human_input_at
            if idle >= RESUME_DELAY_SECONDS:
                self._state = MonitorState.RUNNING
                self._last_human_input_at = None
        return self._state
