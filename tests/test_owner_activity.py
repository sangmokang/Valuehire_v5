"""PC-F1 — owner-activity detector 순수모듈(compute_yield_decision).

R4(양보·자동재개)의 첫 코드강제. 판정 신호는 앞창 앱·OS idle·(크롬 앞창일 때) 활성 탭
호스트의 포털 축(2026-07-20 개정)이다. 이 파일의 순수함수 호출은 portal_site_active 를
생략(=None, '포털 여부 불명')한 하위호환 경로를 검증한다 — 실전 snapshot 은 비포털 확정 시
False 를 전달해 즉시 진행한다(전용 검증: tests/test_owner_yield_60s_portal_scope.py).
감지 불가/실패는 fail-closed = 양보(사장님을 앞지르지 않는다).

인수기준(compute_yield_decision, 2026-07-20 포털 축 개정):
  (a) portal_site_active=False(3사 포털 아님 확정)      → yield=False (idle 무관 재개)
  (b) portal_site_active∈{True,None} & idle>=60         → yield=False (자리 비움 → 재개)
  (c) portal_site_active∈{True,None} & idle<60 또는 None → yield=True (양보, 60초 유계)
  ※ frontmost_is_chrome 은 호환용 관측 파라미터(판정은 snapshot 의 포털 축이 담당).
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
    def test_a_chrome_frontmost_recent_or_unknown_yields(self) -> None:
        # INV9(2026-07-15 사장님 지시, #107): 판단 신호는 idle. 크롬 앞창 + 최근 활동/판단불가는
        # 양보하되, 크롬을 앞창에 둔 채 60초 이상 자리를 비우면 재개(구 "앞창=영구 양보" 폐기).
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=0.0)
        )
        self.assertFalse(
            compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=9999.0)
        )
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=None)
        )

    def test_b_non_chrome_idle_long_resumes(self) -> None:
        # portal 불명(None 기본값) + 오래 자리 비움 → 재개(False).
        self.assertFalse(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=60.0)
        )
        self.assertFalse(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=600.0)
        )

    def test_c_non_chrome_recently_active_yields(self) -> None:
        # portal 불명(None 기본값) + 최근 활동(idle<60) → 60초 유계 양보(True).
        # (실전에서 앞창이 Slack/터미널이면 snapshot 이 portal=False 를 줘 즉시 진행 — 포털 스코프 테스트 참조)
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=0.0)
        )
        self.assertTrue(
            compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=59.999)
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
        # portal 불명 + idle 판독 불가(None) → fail-closed 양보(True).
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

    def test_chrome_frontmost_long_idle_resumes_inv9(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "osascript":
                return _completed("Google Chrome\n")
            return _completed('    "HIDIdleTime" = 300000000000\n')  # 300s idle

        snapshot = detect_owner_activity_snapshot(system_name="Darwin", run_command=fake_run)

        # INV9(#107): 크롬을 앞창에 둔 채 60초 이상 자리 비움(idle 300s) → 재개(감지 False).
        # 구 스펙("앞창=영구 양보")은 사장님 자동 재개 지시(2026-07-20 60초 개정)로 폐기.
        self.assertFalse(snapshot.owner_activity_detected)
        self.assertEqual(snapshot.foreground_app, "Google Chrome")

    def test_chrome_frontmost_recent_activity_yields(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "osascript":
                return _completed("Google Chrome\n")
            return _completed('    "HIDIdleTime" = 1000000000\n')  # 1s idle

        snapshot = detect_owner_activity_snapshot(system_name="Darwin", run_command=fake_run)
        self.assertTrue(snapshot.owner_activity_detected)

    def test_non_chrome_recently_active_proceeds(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "osascript":
                return _completed("Terminal\n")
            return _completed('    "HIDIdleTime" = 1000000000\n')  # 1s idle

        snapshot = detect_owner_activity_snapshot(system_name="Darwin", run_command=fake_run)

        # 2026-07-20 개정: 크롬(3사 포털) 아님이 확정이면 방금 활동(1s)이어도 진행(False).
        # 3사 포털을 만질 때만 개입으로 본다 — 표 1(goal 문서).
        self.assertFalse(snapshot.owner_activity_detected)

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

    def test_combined_frontmost_query_failure_falls_back_to_two_read_only_queries(self) -> None:
        def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if argv[0] == "osascript":
                script = " ".join(argv)
                if "{name, unix id}" in script:
                    return _completed("", returncode=1)
                if "unix id" in script:
                    return _completed("38999\n")
                return _completed("Safari\n")
            return _completed('    "HIDIdleTime" = 1000000000\n')

        snapshot = detect_owner_activity_snapshot(
            system_name="Darwin", run_command=fake_run)

        self.assertEqual(snapshot.foreground_app, "Safari")
        self.assertEqual(snapshot.detection_status, "ok")
        self.assertFalse(snapshot.owner_activity_detected)

    def test_unsupported_platform_is_fail_closed(self) -> None:
        snapshot = detect_owner_activity_snapshot(system_name="Linux")

        self.assertTrue(snapshot.owner_activity_detected)
        self.assertIn("unsupported_platform", snapshot.detection_status)


if __name__ == "__main__":
    unittest.main()
