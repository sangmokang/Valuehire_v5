"""PC-F1 — owner-activity detector 순수모듈(compute_yield_decision).

R4(양보·자동재개)의 첫 코드강제. 무인 워커가 사장님과 머신을 다투지 않도록, 앞창 앱과 OS idle
시간만 읽어 '지금 양보할지(yield)'를 결정론적으로 계산한다. 로그인 클릭·키입력·브라우저 내용은
절대 보지 않는다(SOT1). 감지 불가/실패는 fail-closed = 양보(사장님을 앞지르지 않는다).

인수기준(compute_yield_decision):
  (a) frontmost_is_chrome=True                         → yield=True  (사장님이 크롬 앞창)
  (b) frontmost_is_chrome=False & os_idle_seconds>=180 → yield=False (자리 비움 → 재개)
  (c) frontmost_is_chrome=False & os_idle_seconds<180  → yield=True  (다른 앱 활성 → 양보)
"""

from __future__ import annotations

import subprocess
import unittest

from tools.multi_position_sourcing.owner_activity import (
    DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
    compute_yield_decision,
    detect_owner_activity_snapshot,
)


class ComputeYieldDecisionTests(unittest.TestCase):
    def test_a_chrome_frontmost_yields(self) -> None:
        # 크롬이 앞창이면 idle 과 무관하게 양보(True).
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=0.0)
        )
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=9999.0)
        )
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=None)
        )

    def test_b_non_chrome_idle_long_resumes(self) -> None:
        # 크롬 아님 + 오래 자리 비움 → 재개(False).
        self.assertFalse(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=180.0)
        )
        self.assertFalse(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=600.0)
        )

    def test_c_non_chrome_recently_active_yields(self) -> None:
        # 크롬 아님 + 최근 활동(idle<180) → 양보(True).
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=0.0)
        )
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=179.999)
        )

    def test_boundary_exactly_threshold_resumes(self) -> None:
        # idle == threshold 는 '자리 비움'으로 재개(>=).
        self.assertFalse(
            compute_yield_decision(
                frontmost_is_chrome=False,
                os_idle_seconds=DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
            )
        )

    def test_failclosed_unknown_idle_yields(self) -> None:
        # 크롬 아님인데 idle 을 못 읽으면(None) 판단 불가 → fail-closed 양보(True).
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=None)
        )

    def test_custom_threshold_respected(self) -> None:
        self.assertTrue(
            compute_yield_decision(
                frontmost_is_chrome=False, os_idle_seconds=100.0, idle_threshold_seconds=120.0
            )
        )
        self.assertFalse(
            compute_yield_decision(
                frontmost_is_chrome=False, os_idle_seconds=100.0, idle_threshold_seconds=60.0
            )
        )


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class OwnerActivitySnapshotTests(unittest.TestCase):
    """detect_owner_activity_snapshot 이 compute_yield_decision 계약으로 위임되는지(값 일치)."""

    def test_chrome_frontmost_detected_regardless_of_idle(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "osascript":
                return _completed("Google Chrome\n")
            return _completed('    "HIDIdleTime" = 300000000000\n')  # 300s idle

        snapshot = detect_owner_activity_snapshot(system_name="Darwin", run_command=fake_run)

        # 크롬 앞창 → idle 300s 여도 양보(True) — compute_yield_decision (a) 위임.
        self.assertTrue(snapshot.owner_activity_detected)
        self.assertEqual(snapshot.foreground_app, "Google Chrome")

    def test_non_chrome_recently_active_yields(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "osascript":
                return _completed("Terminal\n")
            return _completed('    "HIDIdleTime" = 1000000000\n')  # 1s idle

        snapshot = detect_owner_activity_snapshot(system_name="Darwin", run_command=fake_run)

        # 터미널 앞창이지만 방금 활동(1s) → 양보(True) — compute_yield_decision (c).
        self.assertTrue(snapshot.owner_activity_detected)

    def test_non_chrome_idle_long_resumes(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "osascript":
                return _completed("Terminal\n")
            return _completed('    "HIDIdleTime" = 300000000000\n')  # 300s idle

        snapshot = detect_owner_activity_snapshot(system_name="Darwin", run_command=fake_run)

        # 크롬 아님 + 오래 비움 → 재개(False) — compute_yield_decision (b).
        self.assertFalse(snapshot.owner_activity_detected)

    def test_detector_failure_is_fail_closed(self) -> None:
        def fake_run(_argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return _completed("", returncode=1)

        snapshot = detect_owner_activity_snapshot(system_name="Darwin", run_command=fake_run)

        self.assertTrue(snapshot.owner_activity_detected)
        self.assertEqual(snapshot.detection_status, "detector_unavailable")

    def test_unsupported_platform_is_fail_closed(self) -> None:
        snapshot = detect_owner_activity_snapshot(system_name="Linux")

        self.assertTrue(snapshot.owner_activity_detected)
        self.assertIn("unsupported_platform", snapshot.detection_status)


if __name__ == "__main__":
    unittest.main()
