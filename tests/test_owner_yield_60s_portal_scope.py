"""owner-yield 60초 + 3사 포털 한정 판정 (2026-07-20 사장님 지시 — SOT29 INV9 개정).

goal: docs/engineering/owner-yield-60s-portal-scope-goal-2026-07-20.md
입력 영역 표의 각 행 = 아래 테스트 1개 이상.

핵심 개정:
  - 양보(점유) 판정은 사장님이 **사람인·잡코리아·링크드인을 만질 때만** 발동한다.
    유튜브 등 다른 화면 사용 중에는 idle 값과 무관하게 양보하지 않는다(표 1·3).
  - 임계 180초 → 60초. 3사를 만지던 중이라도 마지막 입력 후 60초면 자동 재개(표 2).
"""

from __future__ import annotations

import subprocess
import unittest

from tools.multi_position_sourcing.owner_activity import (
    DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
    compute_yield_decision,
    detect_owner_activity_snapshot,
)


class ThresholdSpecTests(unittest.TestCase):
    def test_default_threshold_is_60(self) -> None:
        # AC2 — "3분이 너무 길으니 1분으로" (2026-07-20)
        self.assertEqual(DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS, 60.0)

    def test_fleet_worker_resume_is_60(self) -> None:
        from tools.multi_position_sourcing.fleet_worker import (
            OWNER_YIELD_RESUME_SECONDS,
            PAUSE_COOLDOWN_SECONDS,
        )

        self.assertEqual(OWNER_YIELD_RESUME_SECONDS, 60)
        self.assertEqual(PAUSE_COOLDOWN_SECONDS, OWNER_YIELD_RESUME_SECONDS)


class PortalScopePureRuleTests(unittest.TestCase):
    def test_row3_non_portal_recent_input_does_not_yield(self) -> None:
        # 표 1·3 — 유튜브 시청(비포털) + 방금 입력 → 양보 안 함 (AC1)
        self.assertFalse(
            compute_yield_decision(
                frontmost_is_chrome=True,
                os_idle_seconds=1.0,
                portal_site_active=False,
            )
        )

    def test_row2_portal_recent_input_yields(self) -> None:
        # counter-AC — 3사 화면 + idle<60 → 양보
        self.assertTrue(
            compute_yield_decision(
                frontmost_is_chrome=True,
                os_idle_seconds=30.0,
                portal_site_active=True,
            )
        )

    def test_row2_portal_idle_60_resumes(self) -> None:
        # 표 2·8 — 3사 화면이라도 idle>=60 → 재개(로그인 진행)
        self.assertFalse(
            compute_yield_decision(
                frontmost_is_chrome=True,
                os_idle_seconds=60.0,
                portal_site_active=True,
            )
        )

    def test_row4_unknown_portal_state_is_bounded_by_60(self) -> None:
        # 표 4 — URL 판독 불가(None) → idle 기준 60초 유계 양보
        self.assertTrue(
            compute_yield_decision(
                frontmost_is_chrome=True,
                os_idle_seconds=10.0,
                portal_site_active=None,
            )
        )
        self.assertFalse(
            compute_yield_decision(
                frontmost_is_chrome=True,
                os_idle_seconds=61.0,
                portal_site_active=None,
            )
        )

    def test_row5_idle_none_fail_closed_even_if_portal_unknown(self) -> None:
        # 표 5 — idle 판독 불가 → fail-closed 양보 유지
        self.assertTrue(
            compute_yield_decision(
                frontmost_is_chrome=True,
                os_idle_seconds=None,
                portal_site_active=None,
            )
        )

    def test_row5_idle_none_but_non_portal_does_not_yield(self) -> None:
        # 비포털 확정이면 idle 을 못 읽어도 진행(포털을 안 만지는 게 확정이므로)
        self.assertFalse(
            compute_yield_decision(
                frontmost_is_chrome=False,
                os_idle_seconds=None,
                portal_site_active=False,
            )
        )


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _fake_run(front_app: str, idle_ns: int, chrome_tab_url: str | None):
    """osascript 앞창/크롬탭 + ioreg idle 을 흉내내는 run_command."""

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[0] == "osascript":
            script = " ".join(argv)
            if "active tab" in script:
                if chrome_tab_url is None:
                    return _completed("", returncode=1)
                return _completed(chrome_tab_url + "\n")
            return _completed(front_app + "\n")
        return _completed(f'    "HIDIdleTime" = {idle_ns}\n')

    return run


class SnapshotPortalScopeTests(unittest.TestCase):
    def test_row1_non_chrome_frontmost_never_yields(self) -> None:
        # 표 1 — Slack 앞창 + 방금 입력(1s) → 진행
        snap = detect_owner_activity_snapshot(
            system_name="Darwin",
            run_command=_fake_run("Slack", 1_000_000_000, None),
        )
        self.assertFalse(snap.owner_activity_detected)
        self.assertIs(snap.portal_site_active, False)

    def test_row3_chrome_youtube_never_yields(self) -> None:
        # 표 3 — 크롬 유튜브 시청 + 방금 입력 → 진행 (사장님 신고 케이스 회귀)
        snap = detect_owner_activity_snapshot(
            system_name="Darwin",
            run_command=_fake_run(
                "Google Chrome", 1_000_000_000, "https://www.youtube.com/watch?v=abc"
            ),
        )
        self.assertFalse(snap.owner_activity_detected)
        self.assertIs(snap.portal_site_active, False)

    def test_row2_chrome_saramin_recent_yields(self) -> None:
        snap = detect_owner_activity_snapshot(
            system_name="Darwin",
            run_command=_fake_run(
                "Google Chrome",
                1_000_000_000,
                "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            ),
        )
        self.assertTrue(snap.owner_activity_detected)
        self.assertIs(snap.portal_site_active, True)

    def test_row2_chrome_linkedin_idle61_resumes(self) -> None:
        snap = detect_owner_activity_snapshot(
            system_name="Darwin",
            run_command=_fake_run(
                "Google Chrome", 61_000_000_000, "https://www.linkedin.com/talent/home"
            ),
        )
        self.assertFalse(snap.owner_activity_detected)
        self.assertIs(snap.portal_site_active, True)

    def test_row4_chrome_url_unreadable_bounded_yield(self) -> None:
        # URL 실패 → portal None → idle 1s 양보 / idle 61s 재개
        snap_recent = detect_owner_activity_snapshot(
            system_name="Darwin",
            run_command=_fake_run("Google Chrome", 1_000_000_000, None),
        )
        self.assertTrue(snap_recent.owner_activity_detected)
        self.assertIsNone(snap_recent.portal_site_active)
        snap_idle = detect_owner_activity_snapshot(
            system_name="Darwin",
            run_command=_fake_run("Google Chrome", 61_000_000_000, None),
        )
        self.assertFalse(snap_idle.owner_activity_detected)

    def test_row9_lookalike_host_is_not_portal(self) -> None:
        # 표 9 — evilinkedin.com 위장 → 3사 아님 → 진행
        snap = detect_owner_activity_snapshot(
            system_name="Darwin",
            run_command=_fake_run(
                "Google Chrome", 1_000_000_000, "https://evilinkedin.com/talent"
            ),
        )
        self.assertFalse(snap.owner_activity_detected)
        self.assertIs(snap.portal_site_active, False)

    def test_row9_subdomain_of_portal_is_portal(self) -> None:
        snap = detect_owner_activity_snapshot(
            system_name="Darwin",
            run_command=_fake_run(
                "Google Chrome", 1_000_000_000, "https://m.jobkorea.co.kr/Corp"
            ),
        )
        self.assertTrue(snap.owner_activity_detected)
        self.assertIs(snap.portal_site_active, True)

    def test_privacy_snapshot_records_host_only(self) -> None:
        # AC3 — 스냅샷에 전체 URL(경로·쿼리)을 남기지 않는다
        snap = detect_owner_activity_snapshot(
            system_name="Darwin",
            run_command=_fake_run(
                "Google Chrome",
                1_000_000_000,
                "https://www.saramin.co.kr/secret/path?q=token",
            ),
        )
        for value in vars(snap).values():
            if isinstance(value, str):
                self.assertNotIn("secret", value)
                self.assertNotIn("token", value)


if __name__ == "__main__":
    unittest.main()


class HarvestDriverPortalWiringTests(unittest.TestCase):
    """decide_tick/decide_resume 가 portal_site_active 를 순수계약으로 통과시키는지(배선)."""

    def test_decide_tick_non_portal_runs_despite_recent_input(self) -> None:
        from tools.multi_position_sourcing.harvest_driver import decide_tick

        decision = decide_tick(
            frontmost_is_chrome=True,
            os_idle_seconds=1.0,
            portal_site_active=False,
        )
        self.assertTrue(decision.run)

    def test_decide_resume_portal_recent_input_yields(self) -> None:
        from tools.multi_position_sourcing.harvest_driver import decide_resume

        decision = decide_resume(
            frontmost_is_chrome=True,
            os_idle_seconds=1.0,
            ticks_yielded=0,
            seed=7,
            portal_site_active=True,
        )
        self.assertFalse(decision.resume)
