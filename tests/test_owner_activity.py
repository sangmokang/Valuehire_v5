"""PC-F1 — owner-activity detector 순수모듈(compute_yield_decision).

R4(양보·자동재개)의 첫 코드강제. 무인 워커가 사장님과 "워커가 쓰는 브라우저(크롬)"를
다투지 않도록, 앞창 앱 + OS idle 을 함께 봐서 '지금 양보할지(yield)'를 결정론적으로
계산한다. 로그인 클릭·키입력·브라우저 내용은 절대 보지 않는다(SOT1). 감지 불가/실패는
fail-closed = 양보(사장님을 앞지르지 않는다).

(2026-07-13 사장님 정정, 2차 — 점유는 정확히 사장님이 지금 그 브라우저를 손으로 만지고
있을 때만이다.
1차 수정("크롬 앞창이면 무조건 양보")은 워커 자신의 ``Page.bringToFront`` 호출만으로도
크롬이 앞창이 돼 스스로에게 양보하는 자기유발 오탐을 만들었다. 실측 결과 CDP
``Page.bringToFront``/``Input.dispatch*`` 는 macOS ``HIDIdleTime`` 을 갱신하지 않으므로,
idle 값은 여전히 "진짜 사람 입력"만 반영하는 신뢰 가능한 신호다. 최종 규칙은 크롬이
앞창이고 AND 최근 진짜 입력(idle<threshold)이 둘 다일 때만 양보.)

인수기준(compute_yield_decision):
  (a) frontmost_is_chrome=True  & idle<threshold  → yield=True  (사장님이 지금 크롬을 만짐)
  (b) frontmost_is_chrome=True  & idle>=threshold → yield=False (크롬은 떠 있지만 사람 입력 없음
                                                      — 워커 자신의 bringToFront 뿐일 수 있음)
  (c) frontmost_is_chrome=False                   → yield=False (크롬이 아니면 idle 무관 즉시 재개)
  (d) frontmost_is_chrome=True  & idle=None        → yield=True  (판단 불가 → fail-closed)
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
    def test_a_chrome_frontmost_recent_input_yields(self) -> None:
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=0.0)
        )
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=179.999)
        )

    def test_b_chrome_frontmost_but_idle_resumes(self) -> None:
        # 크롬이 앞창이어도 사람 입력이 오래 없었으면(워커 자신의 bringToFront 뿐) 재개.
        self.assertFalse(
            compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=180.0)
        )
        self.assertFalse(
            compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=9999.0)
        )

    def test_c_non_chrome_always_resumes_regardless_of_idle(self) -> None:
        self.assertFalse(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=0.0)
        )
        self.assertFalse(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=600.0)
        )
        self.assertFalse(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=None)
        )

    def test_d_chrome_frontmost_unknown_idle_failcloses_to_yield(self) -> None:
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=None)
        )

    def test_boundary_exactly_threshold_resumes(self) -> None:
        self.assertFalse(
            compute_yield_decision(
                frontmost_is_chrome=True,
                os_idle_seconds=DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
            )
        )

    def test_custom_threshold_respected(self) -> None:
        self.assertTrue(
            compute_yield_decision(
                frontmost_is_chrome=True, os_idle_seconds=100.0, idle_threshold_seconds=120.0
            )
        )
        self.assertFalse(
            compute_yield_decision(
                frontmost_is_chrome=True, os_idle_seconds=100.0, idle_threshold_seconds=60.0
            )
        )


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class OwnerActivitySnapshotTests(unittest.TestCase):
    """detect_owner_activity_snapshot 이 compute_yield_decision 계약으로 위임되는지(값 일치)."""

    def test_chrome_frontmost_recent_input_yields(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "osascript":
                return _completed("Google Chrome\n")
            return _completed('    "HIDIdleTime" = 1000000000\n')  # 1s idle

        snapshot = detect_owner_activity_snapshot(system_name="Darwin", run_command=fake_run)

        self.assertTrue(snapshot.owner_activity_detected)
        self.assertEqual(snapshot.foreground_app, "Google Chrome")

    def test_chrome_frontmost_but_idle_resumes(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "osascript":
                return _completed("Google Chrome\n")
            return _completed('    "HIDIdleTime" = 300000000000\n')  # 300s idle — worker-only bringToFront

        snapshot = detect_owner_activity_snapshot(system_name="Darwin", run_command=fake_run)

        # 크롬이 앞창이어도 사람 입력이 300s 없었으면 재개(False) — 자기유발 오탐 방지.
        self.assertFalse(snapshot.owner_activity_detected)

    def test_non_chrome_recently_active_resumes(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "osascript":
                return _completed("Terminal\n")
            return _completed('    "HIDIdleTime" = 1000000000\n')  # 1s idle

        snapshot = detect_owner_activity_snapshot(system_name="Darwin", run_command=fake_run)

        # 터미널 앞창이면 방금 활동(1s)이어도 재개(False) — 크롬이 아니므로 워커 브라우저와 무관.
        self.assertFalse(snapshot.owner_activity_detected)

    def test_non_chrome_idle_long_resumes(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "osascript":
                return _completed("Terminal\n")
            return _completed('    "HIDIdleTime" = 300000000000\n')  # 300s idle

        snapshot = detect_owner_activity_snapshot(system_name="Darwin", run_command=fake_run)

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
