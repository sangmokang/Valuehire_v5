"""RPS 수동 점유 스위치 — 계약 테스트.

사장님이 다른 PC에서 LinkedIn Recruiter(RPS)를 쓸 때, 같은 계정을 이 맥 자동화가
동시에 attach 하면 세션 충돌/보안 체크포인트가 난다(RPS는 한 계정 = 한 세션).
RPS는 들쭉날쭉하게 쓰므로 시간표가 아니라 **수동 스위치**로 양보한다.

계약:
  1. 스위치 ON(플래그 파일 존재) → 큐 사이클은 ``linkedin_rps`` 항목만 건너뛰고
     pending 보존(사유 기록). ``saramin``/``jobkorea`` 는 영향 0(정상 처리).
  2. 스위치 OFF → ``linkedin_rps`` 도 정상 처리.
  3. 플래그 판정은 파일 존재 여부 하나로 결정(있으면 ON, 없으면 OFF).

순수성: ``plan_queue_cycle`` 은 부수효과 없는 게이트 함수이므로 파일 I/O 를 하지 않는다.
스위치 상태는 ``rps_in_use`` 불리언으로 주입받고, 파일 읽기는 ``rps_in_use_from_flag`` 가 한다.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.models import QueueItem
from tools.multi_position_sourcing.queue_runner import plan_queue_cycle
from tools.multi_position_sourcing.rps_switch import rps_in_use_from_flag

NOW = "2026-06-25T00:00:00+00:00"


def _item(group_id: str, channel: str) -> QueueItem:
    return QueueItem(
        group_id=group_id,
        channel=channel,
        keyword_plan=(),
        status="pending",
        next_run_at="",
    )


def _sessions() -> dict[str, bool]:
    return {"linkedin_rps": True, "saramin": True, "jobkorea": True}


class RpsManualSwitchTest(unittest.TestCase):
    def test_switch_on_skips_only_linkedin(self) -> None:
        """스위치 ON: linkedin_rps 만 keep, saramin 은 process."""
        queue = [_item("g1", "linkedin_rps"), _item("g2", "saramin")]
        plan = plan_queue_cycle(
            queue,
            now_iso=NOW,
            chrome_connected=True,
            portal_sessions=_sessions(),
            rps_in_use=True,
        )
        self.assertEqual(plan.decisions, ("keep", "process"))
        self.assertTrue(
            any(
                "linkedin" in reason.lower() or "rps" in reason.lower()
                for reason in plan.stopped_reasons
            ),
            f"RPS 양보 사유가 기록돼야 한다: {plan.stopped_reasons}",
        )

    def test_switch_on_does_not_stop_other_channels(self) -> None:
        """스위치 ON 이어도 사람인·잡코리아 둘 다 process(전체 정지 아님)."""
        queue = [_item("g1", "saramin"), _item("g2", "jobkorea")]
        plan = plan_queue_cycle(
            queue,
            now_iso=NOW,
            chrome_connected=True,
            portal_sessions=_sessions(),
            rps_in_use=True,
        )
        self.assertEqual(plan.decisions, ("process", "process"))

    def test_switch_off_processes_linkedin(self) -> None:
        """스위치 OFF: linkedin_rps 도 정상 process."""
        queue = [_item("g1", "linkedin_rps"), _item("g2", "saramin")]
        plan = plan_queue_cycle(
            queue,
            now_iso=NOW,
            chrome_connected=True,
            portal_sessions=_sessions(),
            rps_in_use=False,
        )
        self.assertEqual(plan.decisions, ("process", "process"))

    def test_default_is_off(self) -> None:
        """rps_in_use 미지정(기본) 이면 OFF — linkedin 처리."""
        queue = [_item("g1", "linkedin_rps")]
        plan = plan_queue_cycle(
            queue,
            now_iso=NOW,
            chrome_connected=True,
            portal_sessions=_sessions(),
        )
        self.assertEqual(plan.decisions, ("process",))

    def test_flag_file_presence_decides(self) -> None:
        """플래그 파일 있으면 ON, 없으면 OFF."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "rps_in_use.flag"
            self.assertFalse(rps_in_use_from_flag(flag))
            flag.write_text("", encoding="utf-8")
            self.assertTrue(rps_in_use_from_flag(flag))


if __name__ == "__main__":
    unittest.main()
