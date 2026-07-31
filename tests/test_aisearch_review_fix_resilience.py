"""2026-07-31 전수 리뷰 — M2 채널 협조적 중단 · M3 알림 재발신 · F8~F10 세션락 (U9/U10/U17).

goal: docs/engineering/aisearch-review-fix-goal-2026-07-31.md

- M2: 한 채널이 E8 예외로 죽으면 다른 채널에 중단 신호를 보내고, 리포트에는
  **모든** 채널 오류를 남긴다(예전에는 첫 예외만 재발생하고 나머지는 사라짐).
- M3: 발신 실패로 pending_notifications 에 쌓인 차단 알림을 파이프라인 종료 전
  다시 보낸다. 끝내 실패하면 리포트에 표면화한다(조용히 버리지 않는다).
- F8: 크래시로 남은 락을 절대 자동 회수하지 않아, 한 번 죽으면 링크드인 채널이
  영구 실패하고 파이프라인 전체가 aborted 가 됐다(사람인·잡코리아 결과까지 폐기).
- F9: mkdir 성공과 메타 기록 사이 창 때문에, 정상 경합이 "손상된 락 — 수동 해제"
  로 오진단됐다.
- F10: owner.json 이 dict 가 아니면 AttributeError 로 터졌다.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from apps.aisearch.core.intervention import InterventionMonitor, MonitorState
from apps.aisearch.core.session_lock import (
    LinkedInSessionLock,
    LinkedInSessionLockError,
)


# ── M2 — 채널 협조적 중단 + 전체 오류 보고 ────────────────────────────────


def test_m2_reports_every_channel_error_not_just_the_first():
    from apps.aisearch.core.orchestrator import run_search_pipeline
    from tests.test_aisearch_orchestrator import Harness, _jd

    h = Harness(pages=1)

    def boom(channel: str, page: int) -> None:
        raise RuntimeError(f"{channel} 드라이버 폭발")

    h.list_side_effect = boom

    report = run_search_pipeline(_jd(), h.deps())

    assert report.status == "aborted"
    assert len(report.channel_errors) >= 2, (
        f"채널 오류가 전부 보고되지 않았다: {report.channel_errors}"
    )
    channels = {e["channel"] for e in report.channel_errors}
    assert channels & {"linkedin_rps", "saramin", "jobkorea"}
    for entry in report.channel_errors:
        assert entry["error"]


def test_m2_one_channel_failure_signals_others_to_stop():
    """협조적 중단 — 한 채널이 죽으면 남은 채널이 새 작업을 시작하지 않는다."""
    from apps.aisearch.core.orchestrator import run_search_pipeline
    from tests.test_aisearch_orchestrator import Harness, _jd

    h = Harness(pages=20)  # 채널당 20페이지 — 중단 신호가 없으면 계속 돈다
    calls: list[tuple[str, int]] = []

    def side_effect(channel: str, page: int) -> None:
        calls.append((channel, page))
        if channel == "saramin" and page == 1:
            raise RuntimeError("saramin 폭발")

    h.list_side_effect = side_effect

    report = run_search_pipeline(_jd(), h.deps())

    assert report.status == "aborted"
    total_pages = len(calls)
    assert total_pages < 3 * 20, (
        f"다른 채널이 중단 신호를 받지 못하고 끝까지 돌았다(요청 {total_pages}건)"
    )


# ── M3 — 알림 재발신(flush) ───────────────────────────────────────────────


class _FlakyNotifier:
    """처음 N회는 실패하고 그 뒤 성공하는 알림기."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.sent: list[str] = []
        self.attempts = 0

    def notify(self, message: str) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise RuntimeError("Discord 발신 실패")
        self.sent.append(message)


def test_m3_flush_resends_pending_notifications():
    notifier = _FlakyNotifier(fail_times=3)  # 최초 3회(=NOTIFY_MAX_ATTEMPTS) 실패
    monitor = InterventionMonitor(lambda: 0.0, notifier)

    monitor.on_signal("captcha")
    assert monitor.pending_notifications, "실패한 알림이 보존되지 않았다"

    still_failing = monitor.flush_pending_notifications()

    assert still_failing == []
    assert monitor.pending_notifications == []
    assert notifier.sent, "재발신이 실제로 나가지 않았다"


def test_m3_flush_reports_what_still_fails():
    notifier = _FlakyNotifier(fail_times=999)
    monitor = InterventionMonitor(lambda: 0.0, notifier)
    monitor.on_signal("captcha")

    still_failing = monitor.flush_pending_notifications()

    assert len(still_failing) == 1
    assert monitor.pending_notifications == still_failing  # 계속 보존(유실 금지)


def test_m3_pipeline_surfaces_undeliverable_notifications():
    from apps.aisearch.core.orchestrator import run_search_pipeline
    from tests.test_aisearch_orchestrator import Harness, _jd

    class _DeadNotifier:
        def notify(self, message: str) -> None:
            raise RuntimeError("Discord 죽음")

    h = Harness(pages=1)
    h.monitor = InterventionMonitor(lambda: h.now[0], _DeadNotifier())
    h.driver_events = [{"type": "signal", "kind": "captcha"}]

    report = run_search_pipeline(_jd(), h.deps())

    assert report.status == "blocked"
    assert report.notification_failures, (
        "보내지 못한 차단 알림이 리포트에 표면화되지 않았다(조용한 유실)"
    )


# ── F8/F9/F10 — 링크드인 세션 락 ──────────────────────────────────────────


def test_f8_stale_lock_is_reclaimed_automatically(tmp_path):
    """크래시로 남은 오래된 락은 사람 손 없이 회수된다(영구 정지 금지)."""
    lock_dir = tmp_path / "linkedin_rps"
    lock_dir.mkdir(parents=True)
    (lock_dir / "owner.json").write_text(
        json.dumps({"owner": "죽은프로세스@macmini", "acquired_at": 0.0, "pid": 1}),
        encoding="utf-8",
    )

    lock = LinkedInSessionLock(lock_dir=lock_dir, owner="새프로세스@macbook", stale_seconds=1.0)
    with lock:  # 예외 없이 획득돼야 한다
        meta = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
        assert meta["owner"] == "새프로세스@macbook"
    assert not lock_dir.exists()


def test_f8_live_lock_is_never_stolen(tmp_path):
    lock_dir = tmp_path / "linkedin_rps"
    holder = LinkedInSessionLock(lock_dir=lock_dir, owner="맥미니", stale_seconds=3600.0)
    holder.acquire()
    try:
        other = LinkedInSessionLock(lock_dir=lock_dir, owner="맥북", stale_seconds=3600.0)
        with pytest.raises(LinkedInSessionLockError) as exc:
            other.acquire()
        assert "보유" in str(exc.value)
    finally:
        holder.release()


def test_f9_metadata_race_is_reported_as_contention_not_corruption(tmp_path):
    """mkdir 직후 메타 기록 전 창 — 정상 경합이지 '손상'이 아니다."""
    lock_dir = tmp_path / "linkedin_rps"
    lock_dir.mkdir(parents=True)  # 메타 없이 디렉터리만 존재(경합 순간 재현)

    lock = LinkedInSessionLock(
        lock_dir=lock_dir, owner="맥북", stale_seconds=3600.0, meta_grace_seconds=0.05
    )
    with pytest.raises(LinkedInSessionLockError) as exc:
        lock.acquire()

    message = str(exc.value)
    assert "수동" not in message, f"정상 경합을 수동 개입 사건으로 승격했다: {message}"
    assert "보유" in message or "경합" in message


def test_f10_non_dict_metadata_does_not_crash(tmp_path):
    lock_dir = tmp_path / "linkedin_rps"
    lock_dir.mkdir(parents=True)
    (lock_dir / "owner.json").write_text("[]", encoding="utf-8")

    lock = LinkedInSessionLock(
        lock_dir=lock_dir, owner="맥북", stale_seconds=3600.0, meta_grace_seconds=0.01
    )
    with pytest.raises(LinkedInSessionLockError):  # AttributeError 가 아니어야 한다
        lock.acquire()


def test_f8_lock_failure_does_not_abort_other_channels():
    """링크드인 락 실패가 사람인·잡코리아 결과까지 버리지 않는다."""
    from apps.aisearch.core.orchestrator import run_search_pipeline
    from tests.test_aisearch_orchestrator import Harness, _jd

    class _AlwaysHeld:
        def __enter__(self):
            raise LinkedInSessionLockError("다른 기기 보유 중")

        def __exit__(self, *exc):
            return False

    h = Harness(pages=1, linkedin_session_lock=_AlwaysHeld())
    report = run_search_pipeline(_jd(), h.deps())

    # 링크드인은 실패로 보고되지만, 포털 두 채널의 변형은 실제로 돌아야 한다.
    assert any("linkedin" in e["channel"] for e in report.channel_errors)
    portal_variants = [v for v in report.variants if v.channel in ("saramin", "jobkorea")]
    assert portal_variants, "락 실패 때문에 다른 채널 결과까지 버려졌다"
    assert report.status in ("partial", "aborted")
