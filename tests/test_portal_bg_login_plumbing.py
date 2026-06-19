"""백그라운드 3사 로그인 상주 배관(plumbing)에 대한 스모크 테스트.

검증 대상(게이트2 RED → 게이트4a GREEN):
- scripts/portal_browsers.sh: 사람인·잡코리아·링크드인 디버그 크롬을 띄우는 런처.
  CDP(브라우저 원격조종) 포트는 반드시 127.0.0.1 에만 묶는다(SOT 보안 불변식 5 — 외부 노출 금지).
- scripts/launchd/com.valuehire.portal-browsers.plist: 로그인 시 자동 시작(RunAtLoad) +
  주기적으로 죽은 창을 되살림(StartInterval). start 는 멱등(이미 떠 있으면 건너뜀).
- scripts/launchd/install-portal-browsers.sh: 위 서비스를 설치/해제하는 도우미.

이 테스트는 파일의 "관찰 가능한 계약"(존재·구조·바인딩 주소·자동시작 키)을 잠그며,
런처 구현을 그대로 베끼지 않는다.
"""

from __future__ import annotations

import os
import plistlib
import stat
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "scripts" / "portal_browsers.sh"
PLIST = REPO / "scripts" / "launchd" / "com.valuehire.portal-browsers.plist"
INSTALLER = REPO / "scripts" / "launchd" / "install-portal-browsers.sh"


def _is_executable(p: Path) -> bool:
    return bool(p.stat().st_mode & stat.S_IXUSR)


class PortalLauncherContractTests(unittest.TestCase):
    def test_launcher_exists_and_executable(self) -> None:
        self.assertTrue(LAUNCHER.exists(), f"런처 없음: {LAUNCHER}")
        self.assertTrue(_is_executable(LAUNCHER), "런처에 실행 권한이 없다")

    def test_launcher_has_required_subcommands(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8")
        for sub in ("start", "status", "stop", "restart", "health"):
            self.assertIn(f"{sub})", text, f"서브커맨드 누락: {sub}")

    def test_launcher_binds_cdp_to_loopback_only(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8")
        # 보안 SOT: 원격 디버깅 주소는 반드시 127.0.0.1.
        self.assertIn("--remote-debugging-address=127.0.0.1", text)
        # 외부에 여는 주소(0.0.0.0)는 절대 등장하지 않는다.
        self.assertNotIn("0.0.0.0", text)

    def test_launcher_covers_three_portals(self) -> None:
        text = LAUNCHER.read_text(encoding="utf-8").lower()
        for portal in ("saramin", "jobkorea", "linkedin"):
            self.assertIn(portal, text, f"채널 누락: {portal}")


class PortalLaunchAgentPlistTests(unittest.TestCase):
    def test_plist_is_valid_and_autostarts(self) -> None:
        self.assertTrue(PLIST.exists(), f"plist 없음: {PLIST}")
        with PLIST.open("rb") as fh:
            data = plistlib.load(fh)  # 깨진 plist면 여기서 예외
        self.assertEqual(data.get("Label"), "com.valuehire.portal-browsers")
        # 로그인 시 자동 시작.
        self.assertIs(data.get("RunAtLoad"), True)
        # 죽으면 되살리도록 주기 재실행(초). 양수여야 한다.
        interval = data.get("StartInterval")
        self.assertIsInstance(interval, int)
        self.assertGreater(interval, 0)

    def test_plist_runs_launcher_start(self) -> None:
        with PLIST.open("rb") as fh:
            data = plistlib.load(fh)
        args = data.get("ProgramArguments")
        self.assertIsInstance(args, list)
        self.assertTrue(args, "ProgramArguments 비어 있음")
        joined = " ".join(args)
        self.assertIn("portal_browsers.sh", joined, "런처를 가리키지 않음")
        self.assertIn("start", args, "start 인자 없음")


class PortalInstallerTests(unittest.TestCase):
    def test_installer_exists_and_executable(self) -> None:
        self.assertTrue(INSTALLER.exists(), f"설치 도우미 없음: {INSTALLER}")
        self.assertTrue(_is_executable(INSTALLER), "설치 도우미에 실행 권한이 없다")

    def test_installer_supports_install_and_uninstall(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("launchctl", text)
        for verb in ("install", "uninstall"):
            self.assertIn(verb, text, f"동작 누락: {verb}")


if __name__ == "__main__":
    unittest.main()
