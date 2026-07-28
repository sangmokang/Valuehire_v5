# AC-7 — 사람 개입 감지(30초 자동재개) + 캡차 감지·차단(BLOCKED)·알림
# 근거: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-7, §6 E1/E2/E8, D1=30초.
# 시계·알림(notifier)은 주입식 — 실제 sleep/실제 Discord 발신 없이 결정론적으로 검증한다.
#
# V1 결함 반증(이번 RED가 증명해야 하는 것):
#  결함1 — BLOCKED(차단)는 종단 상태: 30초 재개 점검(poll)이 절대 RUNNING으로
#          덮어쓰지 못하고, 사람의 명시적 human_reset 전까지 유지된다.
#  결함2 — 알림기 예외 시 재시도(최소 2회) + 최종 실패 시 pending_notifications
#          큐 보존(차단 이벤트 알림은 절대 유실 금지).
#  결함3 — 명시적 유효 전이 표(VALID_TRANSITIONS) + validate_transition:
#          표 밖 전이는 InvalidTransitionError(E8 catch-all).

import pytest

from apps.aisearch.core.intervention import (
    NOTIFY_MAX_ATTEMPTS,
    RESUME_DELAY_SECONDS,
    VALID_TRANSITIONS,
    InterventionMonitor,
    InvalidTransitionError,
    MonitorState,
    validate_transition,
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


class FlakyNotifier:
    """처음 fail_times 번은 예외, 그 뒤부터 성공하는 주입식 알림."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.attempts = 0
        self.messages: list[str] = []

    def notify(self, message: str) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise RuntimeError("notify 실패(주입)")
        self.messages.append(message)


class AlwaysFailNotifier:
    """항상 예외를 던지는 주입식 알림 — 유실 금지 검증용."""

    def __init__(self) -> None:
        self.attempts = 0

    def notify(self, message: str) -> None:
        self.attempts += 1
        raise RuntimeError("notify 영구 실패(주입)")


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


# --- E1: 캡차/클라우드플레어/2FA/체크포인트 → BLOCKED + 알림, 우회 금지 -----


@pytest.mark.parametrize("signal", ["captcha", "cloudflare", "2fa", "checkpoint"])
def test_blocking_signal_blocks_and_notifies(
    signal: str, clock: FakeClock
) -> None:
    notifier = FakeNotifier()
    monitor = InterventionMonitor(clock=clock, notifier=notifier)
    monitor.on_signal(signal)
    assert monitor.state is MonitorState.BLOCKED
    assert monitor.automation_allowed() is False
    assert len(notifier.messages) == 1
    assert signal in notifier.messages[0]


def test_blocked_never_auto_resumes(
    monitor: InterventionMonitor, clock: FakeClock
) -> None:
    monitor.on_signal("captcha")
    clock.advance(3_600.0)
    monitor.poll()
    assert monitor.state is MonitorState.BLOCKED
    assert monitor.automation_allowed() is False


def test_no_bypass_attempt_hook_exists(monitor: InterventionMonitor) -> None:
    # 자동 우회 시도 금지 — 우회용 API 자체가 없어야 한다.
    assert not hasattr(monitor, "attempt_bypass")
    assert not hasattr(monitor, "solve_captcha")


# --- 결함1: BLOCKED는 종단 상태 — 재개 점검이 절대 덮어쓰지 못한다 ----------


def test_captcha_during_resume_window_final_state_stays_blocked(
    monitor: InterventionMonitor, clock: FakeClock
) -> None:
    # 사람 개입으로 PAUSED_HUMAN → 30초 재개 점검 카운트다운 도중 캡차 인입.
    monitor.on_human_input()
    clock.advance(15.0)
    monitor.on_signal("captcha")  # 재개 대기 중 차단 신호
    assert monitor.state is MonitorState.BLOCKED
    # 마지막 사람 입력으로부터 30초가 넘은 시점의 재개 점검(poll)이
    # BLOCKED를 RUNNING으로 덮어쓰면 안 된다(결함1 반증 핵심).
    clock.advance(30.0)
    assert monitor.poll() is MonitorState.BLOCKED
    assert monitor.state is MonitorState.BLOCKED
    assert monitor.automation_allowed() is False


def test_repeated_polls_never_overwrite_blocked(
    monitor: InterventionMonitor, clock: FakeClock
) -> None:
    monitor.on_signal("cloudflare")
    for _ in range(10):
        clock.advance(RESUME_DELAY_SECONDS)
        assert monitor.poll() is MonitorState.BLOCKED


def test_human_input_after_block_does_not_revive(
    monitor: InterventionMonitor, clock: FakeClock
) -> None:
    monitor.on_signal("2fa")
    monitor.on_human_input()
    clock.advance(30.0)
    monitor.poll()
    assert monitor.state is MonitorState.BLOCKED


def test_human_reset_is_the_only_way_out_of_blocked(
    monitor: InterventionMonitor, clock: FakeClock
) -> None:
    monitor.on_signal("captcha")
    assert monitor.state is MonitorState.BLOCKED
    monitor.human_reset()  # 사람의 명시적 해제만 허용
    assert monitor.state is MonitorState.RUNNING
    assert monitor.automation_allowed() is True


def test_human_reset_outside_blocked_raises(
    monitor: InterventionMonitor,
) -> None:
    # RUNNING에서 human_reset은 표 밖 전이 — 예외(E8).
    with pytest.raises(InvalidTransitionError):
        monitor.human_reset()


# --- 결함2: 알림 재시도 + pending 큐 보존(차단 이벤트 유실 금지) ------------


def test_notify_retries_at_least_twice_then_delivers(clock: FakeClock) -> None:
    # 1·2번째 시도는 실패, 3번째에 성공 — 최소 2회 재시도가 있어야 전달된다.
    notifier = FlakyNotifier(fail_times=2)
    monitor = InterventionMonitor(clock=clock, notifier=notifier)
    monitor.on_signal("captcha")
    assert notifier.attempts == 3  # 최초 1회 + 재시도 2회
    assert len(notifier.messages) == 1
    assert "captcha" in notifier.messages[0]
    assert monitor.pending_notifications == []  # 전달됐으니 큐는 비어 있다
    assert monitor.state is MonitorState.BLOCKED


def test_notify_max_attempts_contract() -> None:
    # 최초 1회 + 재시도 최소 2회 = 총 3회 이상.
    assert NOTIFY_MAX_ATTEMPTS >= 3


def test_failed_notification_preserved_in_pending_queue(
    clock: FakeClock,
) -> None:
    notifier = AlwaysFailNotifier()
    monitor = InterventionMonitor(clock=clock, notifier=notifier)
    monitor.on_signal("captcha")  # 예외가 밖으로 새면 안 된다
    assert notifier.attempts == NOTIFY_MAX_ATTEMPTS
    # 차단 이벤트 알림은 절대 유실 금지 — pending 큐에 보존.
    assert len(monitor.pending_notifications) == 1
    assert "captcha" in monitor.pending_notifications[0]
    # 알림 실패와 무관하게 차단 상태는 유지된다.
    assert monitor.state is MonitorState.BLOCKED
    assert monitor.automation_allowed() is False


def test_pending_queue_keeps_order_and_is_copy(clock: FakeClock) -> None:
    notifier = AlwaysFailNotifier()
    monitor = InterventionMonitor(clock=clock, notifier=notifier)
    monitor.on_signal("captcha")
    snapshot = monitor.pending_notifications
    snapshot.append("오염 시도")  # 외부 변조가 내부 큐를 못 건드려야 한다
    assert len(monitor.pending_notifications) == 1


# --- 결함3 + E8: 명시적 유효 전이 표, 표 밖 전이는 예외 ---------------------


def test_valid_transition_table_shape() -> None:
    assert set(VALID_TRANSITIONS) == {
        MonitorState.RUNNING,
        MonitorState.PAUSED_HUMAN,
        MonitorState.BLOCKED,
    }
    assert MonitorState.BLOCKED in VALID_TRANSITIONS[MonitorState.RUNNING]
    assert MonitorState.BLOCKED in VALID_TRANSITIONS[MonitorState.PAUSED_HUMAN]
    # BLOCKED에서 나가는 길은 human_reset(→RUNNING) 단 하나.
    assert VALID_TRANSITIONS[MonitorState.BLOCKED] == frozenset(
        {MonitorState.RUNNING}
    )


def test_validate_transition_accepts_table_entries() -> None:
    validate_transition(MonitorState.RUNNING, MonitorState.PAUSED_HUMAN)
    validate_transition(MonitorState.PAUSED_HUMAN, MonitorState.RUNNING)
    validate_transition(MonitorState.RUNNING, MonitorState.BLOCKED)


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (MonitorState.BLOCKED, MonitorState.PAUSED_HUMAN),
        (MonitorState.RUNNING, MonitorState.RUNNING),
    ],
)
def test_validate_transition_rejects_out_of_table(
    src: MonitorState, dst: MonitorState
) -> None:
    # 표 밖 전이는 임의 추정 없이 예외(E8 catch-all).
    with pytest.raises(InvalidTransitionError):
        validate_transition(src, dst)


# --- E8: 표에 없는 신호 → 명시적 차단(catch-all) ----------------------------


def test_unknown_signal_blocks_explicitly(
    monitor: InterventionMonitor, notifier: FakeNotifier
) -> None:
    monitor.on_signal("mystery-popup")
    assert monitor.state is MonitorState.BLOCKED
    assert monitor.automation_allowed() is False
    assert len(notifier.messages) == 1
    assert "mystery-popup" in notifier.messages[0]
