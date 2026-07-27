# AC-7 — 사람 개입 감지(30초 자동재개) + 캡차 감지·중단·알림
# 근거: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-7, §6 E1/E2/E8, D1=30초.
# 시계·알림(notifier)은 주입식 — 실제 sleep/실제 Discord 발신 없이 결정론적으로 검증한다.

import pytest

from apps.aisearch.core.intervention import (
    RESUME_DELAY_SECONDS,
    InterventionMonitor,
    MonitorState,
)


class FakeClock:
    """주입식 시계 — 테스트가 타임스탬프를 직접 전진시킨다."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeNotifier:
    """주입식 Discord 알림 — 실제 발신 없이 메시지만 수집한다."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def notify(self, message: str) -> None:
        self.messages.append(message)


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def notifier() -> FakeNotifier:
    return FakeNotifier()


@pytest.fixture()
def monitor(clock: FakeClock, notifier: FakeNotifier) -> InterventionMonitor:
    return InterventionMonitor(clock=clock, notifier=notifier)


# --- D1 상수 ---------------------------------------------------------------


def test_d1_resume_delay_is_30_seconds() -> None:
    # SOT29의 60초와 별개인 이 서비스 전용 상수(D1).
    assert RESUME_DELAY_SECONDS == 30.0


# --- E2: 사람 개입 → 즉시 정지, 30초 무입력 시 자동 재개 --------------------


def test_initial_state_allows_automation(monitor: InterventionMonitor) -> None:
    assert monitor.state is MonitorState.RUNNING
    assert monitor.automation_allowed() is True


def test_human_input_pauses_immediately(monitor: InterventionMonitor) -> None:
    monitor.on_human_input()
    assert monitor.state is MonitorState.PAUSED_HUMAN
    assert monitor.automation_allowed() is False


def test_no_resume_at_29_9_seconds(
    monitor: InterventionMonitor, clock: FakeClock
) -> None:
    monitor.on_human_input()
    clock.advance(29.9)
    monitor.poll()
    assert monitor.state is MonitorState.PAUSED_HUMAN
    assert monitor.automation_allowed() is False


def test_resumes_at_exactly_30_seconds(
    monitor: InterventionMonitor, clock: FakeClock
) -> None:
    monitor.on_human_input()
    clock.advance(30.0)
    monitor.poll()
    assert monitor.state is MonitorState.RUNNING
    assert monitor.automation_allowed() is True


def test_resumes_after_more_than_30_seconds(
    monitor: InterventionMonitor, clock: FakeClock
) -> None:
    monitor.on_human_input()
    clock.advance(31.5)
    monitor.poll()
    assert monitor.state is MonitorState.RUNNING


def test_new_input_during_pause_resets_timer(
    monitor: InterventionMonitor, clock: FakeClock
) -> None:
    monitor.on_human_input()
    clock.advance(20.0)
    monitor.on_human_input()  # 마지막 입력 기준으로 다시 30초
    clock.advance(29.0)  # 첫 입력으로부터 49초, 마지막 입력으로부터 29초
    monitor.poll()
    assert monitor.state is MonitorState.PAUSED_HUMAN
    clock.advance(1.0)  # 마지막 입력으로부터 정확히 30초
    monitor.poll()
    assert monitor.state is MonitorState.RUNNING


# --- E1: 캡차/클라우드플레어/2FA/체크포인트 → 중단 + 알림, 우회 금지 --------


@pytest.mark.parametrize("signal", ["captcha", "cloudflare", "2fa", "checkpoint"])
def test_blocking_signal_aborts_and_notifies(
    signal: str, clock: FakeClock
) -> None:
    notifier = FakeNotifier()
    monitor = InterventionMonitor(clock=clock, notifier=notifier)
    monitor.on_signal(signal)
    assert monitor.state is MonitorState.ABORTED
    assert monitor.automation_allowed() is False
    assert len(notifier.messages) == 1
    assert signal in notifier.messages[0]


def test_abort_never_auto_resumes(
    monitor: InterventionMonitor, clock: FakeClock
) -> None:
    monitor.on_signal("captcha")
    clock.advance(3_600.0)
    monitor.poll()
    assert monitor.state is MonitorState.ABORTED
    assert monitor.automation_allowed() is False


def test_no_bypass_attempt_hook_exists(monitor: InterventionMonitor) -> None:
    # 자동 우회 시도 금지 — 우회용 API 자체가 없어야 한다.
    assert not hasattr(monitor, "attempt_bypass")
    assert not hasattr(monitor, "solve_captcha")


# --- E8: 표에 없는 신호 → 명시적 중단(catch-all) ---------------------------


def test_unknown_signal_aborts_explicitly(
    monitor: InterventionMonitor, notifier: FakeNotifier
) -> None:
    monitor.on_signal("mystery-popup")
    assert monitor.state is MonitorState.ABORTED
    assert monitor.automation_allowed() is False
    assert len(notifier.messages) == 1
    assert "mystery-popup" in notifier.messages[0]


def test_human_input_after_abort_does_not_revive(
    monitor: InterventionMonitor, clock: FakeClock
) -> None:
    monitor.on_signal("2fa")
    monitor.on_human_input()
    clock.advance(30.0)
    monitor.poll()
    assert monitor.state is MonitorState.ABORTED
