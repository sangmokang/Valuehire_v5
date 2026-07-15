"""portal_browsers.sh start의 탭 무한 증식 방지 가드 (issue #71).

시나리오(2026-07-06 실사고): 크롬 프로세스는 프로필을 잡고 살아 있는데 CDP HTTP가
잠깐 무응답(절전·기동 중) → cdp_alive 오판 → 크롬 바이너리 재실행 → 같은 프로필의
기존 인스턴스에 **새 탭만 추가**. launchd StartInterval(5분)마다 반복돼 탭 십수 개.

인수 기준(기계 단언):
- 같은 프로필의 크롬 프로세스가 살아 있으면(CDP 무응답이어도) start 재실행이
  크롬을 다시 launch 하지 않는다 — fake CHROME 호출 로그가 채널당 정확히 1회.
- 기동 확인 대기는 PORTAL_BOOT_WAIT 로 단축 가능(테스트가 20초×3채널을 기다리지 않게).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "scripts" / "portal_browsers.sh"

# 실환경(9223~9225)과 절대 겹치지 않는 테스트 전용 포트.
TEST_PORTS = {"SARAMIN_PORT": "19223", "JOBKOREA_PORT": "19224", "LINKEDIN_PORT": "19225"}
MARKER = "portal-tab-guard-fake-chrome"


class PortalTabGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="portal_tab_guard_"))
        self.invoke_log = self.tmp / "invocations.log"
        # fake 크롬: 호출을 기록하고 포트는 절대 열지 않은 채 잠시 살아 있는다.
        self.fake_chrome = self.tmp / MARKER
        self.fake_chrome.write_text(
            "#!/bin/bash\n"
            f"echo \"$@\" >> '{self.invoke_log}'\n"
            "sleep 45\n",
            encoding="utf-8",
        )
        self.fake_chrome.chmod(0o755)
        self.env = {
            **os.environ,
            "PORTAL_CHROME": str(self.fake_chrome),
            "PORTAL_LOG_DIR": str(self.tmp / "logs"),
            "PORTAL_START_LOCK_DIR": str(self.tmp / "locks"),
            "PORTAL_BOOT_WAIT": "1",
            # 실환경 프로필과 격리 — 가드(pgrep --user-data-dir=…)가 진짜 포털 크롬을 잡지 않게.
            "SARAMIN_PROFILE": str(self.tmp / "prof_saramin"),
            "JOBKOREA_PROFILE": str(self.tmp / "prof_jobkorea"),
            "LINKEDIN_PROFILE": str(self.tmp / "prof_linkedin"),
            **TEST_PORTS,
        }

    def tearDown(self) -> None:
        subprocess.run(["pkill", "-f", MARKER], check=False)

    def _start(self, channel: str | None = None) -> subprocess.CompletedProcess[str]:
        argv = [str(LAUNCHER), "start"]
        if channel:
            argv.append(channel)
        return subprocess.run(
            argv,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def test_start_does_not_relaunch_when_process_alive_but_cdp_dead(self) -> None:
        self._start()
        time.sleep(1)
        first = self.invoke_log.read_text(encoding="utf-8").splitlines() if self.invoke_log.exists() else []
        self.assertEqual(len(first), 3, f"1차 start는 채널당 1회 launch여야 한다: {first}")

        # 프로세스는 살아 있고(CDP는 계속 무응답) start를 한 번 더 — 여기서 탭이 증식했었다.
        self._start()
        time.sleep(1)
        second = self.invoke_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            len(second), 3,
            f"프로세스 생존+CDP 무응답이면 재-launch 금지(새 탭 증식 방지). 호출 기록: {second}",
        )

    def test_boot_wait_is_env_tunable(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("PORTAL_BOOT_WAIT", text, "기동 대기 시간이 env로 조절 불가")

    def test_start_one_channel_launches_only_that_channel(self) -> None:
        result = self._start("linkedin")
        time.sleep(1)
        calls = self.invoke_log.read_text(encoding="utf-8").splitlines() if self.invoke_log.exists() else []
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(calls), 1, f"단일 채널 요청이 다른 포털 창까지 열면 안 됨: {calls}")
        self.assertIn(str(self.tmp / "prof_linkedin"), calls[0])
        self.assertNotIn(str(self.tmp / "prof_saramin"), calls[0])
        self.assertNotIn(str(self.tmp / "prof_jobkorea"), calls[0])

    def test_start_rejects_unknown_channel_without_launch(self) -> None:
        result = self._start("unknown")
        calls = self.invoke_log.read_text(encoding="utf-8").splitlines() if self.invoke_log.exists() else []
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_concurrent_start_same_channel_launches_once(self) -> None:
        argv = [str(LAUNCHER), "start", "linkedin"]
        procs = [
            subprocess.Popen(argv, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(2)
        ]
        outputs = [proc.communicate(timeout=180) for proc in procs]
        time.sleep(1)
        calls = self.invoke_log.read_text(encoding="utf-8").splitlines() if self.invoke_log.exists() else []
        self.assertTrue(all(proc.returncode == 0 for proc in procs), outputs)
        self.assertEqual(len(calls), 1, f"동시 start가 같은 프로필을 중복 launch함: {calls}")

    def test_start_path_never_recommends_restart(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertNotIn("계속 무응답이면 'restart'", text)


if __name__ == "__main__":
    unittest.main()
