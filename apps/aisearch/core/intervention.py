"""AC-7 — 사람 개입 감지(30초 자동재개) + 캡차 감지·차단(BLOCKED)·알림.

근거: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-7, §6 E1/E2/E8.

설계 원칙:
- 시계(clock)와 알림(notifier)은 주입식 — 실제 sleep·실제 Discord 발신 없이
  테스트에서 타임스탬프로 결정론적으로 검증한다.
- 캡차/클라우드플레어/2FA/체크포인트는 자동 우회를 시도하지 않는다(E1).
  우회용 API 자체를 제공하지 않는다.
- 표에 없는 신호도 명시적 차단한다(E8 catch-all — 임의 추정 금지).
- BLOCKED는 종단 상태 — 사람의 명시적 human_reset 전까지 어떤 재개
  점검(poll)도 덮어쓰지 못한다.
- 상태 전이는 명시적 유효 전이 표(VALID_TRANSITIONS)로만 허용하고,
  표 밖 전이는 InvalidTransitionError(E8)로 막는다.
- 알림기 예외 시 재시도(최초 1회 + 재시도 2회)하고, 최종 실패하면
  pending_notifications 큐에 보존한다 — 차단 이벤트 알림은 절대 유실 금지.
"""

from __future__ import annotations

import enum
from typing import Callable, Optional, Protocol

#: D1 — 마지막 사람 입력으로부터 자동 재개까지의 무입력 대기시간(초).
#: SOT29의 60초와 별개인 이 서비스(aisearch) 전용 상수.
RESUME_DELAY_SECONDS: float = 30.0

#: 알림 총 시도 횟수 — 최초 1회 + 재시도 2회(최소 2회 재시도 계약).
NOTIFY_MAX_ATTEMPTS: int = 3

#: E1 — 자동 우회 금지 + 즉시 차단 + Discord 알림 대상 신호(표에 있는 것).
BLOCKING_SIGNALS: frozenset[str] = frozenset(
    {"captcha", "cloudflare", "2fa", "checkpoint"}
)


class Notifier(Protocol):
    """주입식 알림 인터페이스 — 실제 발신 구현은 호출자가 주입한다."""

    def notify(self, message: str) -> None: ...


class MonitorState(enum.Enum):
    RUNNING = "running"  # 자동 조작 허용
    PAUSED_HUMAN = "paused_human"  # 사람 개입 감지 — 30초 무입력 대기(E2)
    BLOCKED = "blocked"  # 차단 신호 — 종단 상태, human_reset 전까지 유지(E1/E8)


class InvalidTransitionError(Exception):
    """유효 전이 표 밖의 상태 전이 시도(E8 catch-all)."""


#: 명시적 유효 전이 표 — 여기 없는 전이는 전부 예외(E8).
#: BLOCKED → RUNNING 은 human_reset(사람의 명시적 해제) 전용 경로다.
VALID_TRANSITIONS: dict[MonitorState, frozenset[MonitorState]] = {
    MonitorState.RUNNING: frozenset(
        {MonitorState.PAUSED_HUMAN, MonitorState.BLOCKED}
    ),
    MonitorState.PAUSED_HUMAN: frozenset(
        {MonitorState.RUNNING, MonitorState.PAUSED_HUMAN, MonitorState.BLOCKED}
    ),
    MonitorState.BLOCKED: frozenset({MonitorState.RUNNING}),
}


def validate_transition(src: MonitorState, dst: MonitorState) -> None:
    """표 밖 전이는 임의 추정 없이 예외로 막는다(E8 catch-all)."""
    if dst not in VALID_TRANSITIONS.get(src, frozenset()):
        raise InvalidTransitionError(
            f"표 밖 상태 전이 {src.value} → {dst.value} — 허용 안 함(E8)"
        )


#: V1 2차 결함 10 — 드라이버 이벤트 타입 → 모니터 공급 규격.
DRIVER_EVENT_HUMAN_INPUT = "human_input"
DRIVER_EVENT_SIGNAL = "signal"


def feed_driver_events(monitor: "InterventionMonitor", events: list[dict]) -> None:
    """드라이버가 관측한 이벤트를 InterventionMonitor 에 공급하는 어댑터.

    - {"type": "human_input"} → on_human_input() (사람 입력 → 정지)
    - {"type": "signal", "kind": "captcha"|...} → on_signal(kind) (→ BLOCKED)
    - 그 밖의 타입은 표에 없는 이벤트 — E8 catch-all 로 명시적 차단한다
      (임의 추정으로 무시하지 않는다, fail-closed).
    """
    for event in events:
        etype = event.get("type") if isinstance(event, dict) else None
        if etype == DRIVER_EVENT_HUMAN_INPUT:
            monitor.on_human_input()
        elif etype == DRIVER_EVENT_SIGNAL:
            monitor.on_signal(str(event.get("kind")))
        else:
            monitor.on_signal(f"unknown_driver_event:{etype!r}")


class InterventionMonitor:
    """사람 개입·차단 신호 상태 기계.

    clock: 현재 시각(초, 단조 증가)을 돌려주는 주입식 시계.
    notifier: 차단 사유를 전달할 주입식 알림 채널(Discord 등).
    """

    def __init__(self, clock: Callable[[], float], notifier: Notifier) -> None:
        self._clock = clock
        self._notifier = notifier
        self._state = MonitorState.RUNNING
        self._last_human_input_at: Optional[float] = None
        self._pending_notifications: list[str] = []

    @property
    def state(self) -> MonitorState:
        return self._state

    @property
    def pending_notifications(self) -> list[str]:
        """발신에 최종 실패해 보존 중인 알림들 — 복사본(외부 변조 차단)."""
        return list(self._pending_notifications)

    def automation_allowed(self) -> bool:
        """자동 조작을 계속해도 되는지 — RUNNING일 때만 True."""
        return self._state is MonitorState.RUNNING

    def _transition(
        self, dst: MonitorState, *, via_human_reset: bool = False
    ) -> None:
        """유효 전이 표 검증을 통과한 전이만 수행한다.

        BLOCKED에서 나가는 전이는 human_reset 경유일 때만 허용 —
        재개 점검(poll) 등 다른 경로가 종단 상태를 덮어쓸 수 없다.
        """
        if self._state is MonitorState.BLOCKED and not via_human_reset:
            raise InvalidTransitionError(
                "BLOCKED는 종단 상태 — human_reset 없이 벗어날 수 없다(E8)"
            )
        validate_transition(self._state, dst)
        self._state = dst

    def on_human_input(self) -> None:
        """사람 마우스/키보드 입력 감지 — 즉시 정지, 재개 타이머 리셋(E2).

        BLOCKED 이후에는 상태를 되살리지 않는다(입력만으로 해제 불가).
        """
        if self._state is MonitorState.BLOCKED:
            return
        self._last_human_input_at = self._clock()
        self._transition(MonitorState.PAUSED_HUMAN)

    def on_signal(self, kind: str) -> None:
        """차단 신호 처리 — 표에 있든 없든 명시적 차단(E1/E8).

        자동 우회를 시도하지 않고 즉시 BLOCKED + 알림(재시도 포함).
        """
        if self._state is MonitorState.BLOCKED:
            return
        self._transition(MonitorState.BLOCKED)
        if kind in BLOCKING_SIGNALS:
            reason = f"차단 신호 감지({kind}) — 자동 우회 금지, 즉시 차단(E1)"
        else:
            reason = f"표에 없는 신호 감지({kind}) — 명시적 차단(E8 catch-all)"
        self._notify_with_retry(reason)

    def _notify_with_retry(self, message: str) -> None:
        """알림 발신 — 실패 시 재시도, 최종 실패 시 pending 큐 보존.

        차단 이벤트 알림은 절대 유실하지 않고, 예외를 밖으로 전파하지 않는다
        (알림 실패가 차단 상태 유지를 방해하면 안 된다).
        """
        for _ in range(NOTIFY_MAX_ATTEMPTS):
            try:
                self._notifier.notify(message)
                return
            except Exception:
                continue
        self._pending_notifications.append(message)

    def flush_pending_notifications(self) -> list[str]:
        """M3(2026-07-31 리뷰) — 보존된 알림을 다시 보낸다.

        예전에는 pending_notifications 에 쌓아 두기만 하고 다시 보내는 경로가
        없어서, 차단 알림이 조용히 사라졌다(사장님이 캡차를 모른 채 지나감).
        파이프라인 종료 전에 이 함수를 불러 재발신하고, **끝내 실패한 것만**
        돌려준다 — 호출자가 리포트에 표면화한다. 실패한 알림은 계속 보존한다.
        """
        if not self._pending_notifications:
            return []
        queued, self._pending_notifications = self._pending_notifications, []
        still_failing: list[str] = []
        for message in queued:
            for _ in range(NOTIFY_MAX_ATTEMPTS):
                try:
                    self._notifier.notify(message)
                    break
                except Exception:
                    continue
            else:
                still_failing.append(message)
        self._pending_notifications.extend(still_failing)
        return list(still_failing)

    def poll(self) -> MonitorState:
        """주기 점검 — 마지막 입력 후 30초(D1) 무입력이면 자동 재개.

        29.9초처럼 30초 미만이면 재개하지 않는다.
        BLOCKED는 종단 상태 — poll이 절대 덮어쓰지 않는다.
        """
        if self._state is MonitorState.PAUSED_HUMAN:
            assert self._last_human_input_at is not None
            idle = self._clock() - self._last_human_input_at
            if idle >= RESUME_DELAY_SECONDS:
                self._transition(MonitorState.RUNNING)
                self._last_human_input_at = None
        return self._state

    def human_reset(self) -> None:
        """사람의 명시적 해제 — BLOCKED에서 벗어나는 유일한 경로.

        BLOCKED가 아닌 상태에서 부르면 표 밖 전이로 예외(E8).
        """
        if self._state is not MonitorState.BLOCKED:
            raise InvalidTransitionError(
                f"human_reset은 BLOCKED에서만 유효 — 현재 {self._state.value}(E8)"
            )
        self._transition(MonitorState.RUNNING, via_human_reset=True)
        self._last_human_input_at = None
