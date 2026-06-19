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

    def test_plist_uses_launcher_placeholder_and_start(self) -> None:
        # plist는 템플릿이다: 설치 스크립트가 __LAUNCHER_PATH__ 를 실제 경로로 치환한다.
        # 경로를 하드코딩하지 않아 레포 이동/worktree merge 후에도 깨지지 않는다.
        with PLIST.open("rb") as fh:
            data = plistlib.load(fh)
        args = data.get("ProgramArguments")
        self.assertEqual(args, ["__LAUNCHER_PATH__", "start"])

    def test_resolved_launcher_exists_next_to_installer(self) -> None:
        # 설치 스크립트가 의존하는 레포 레이아웃: scripts/portal_browsers.sh 가 실재해야 한다.
        # (이전 결함: plist가 옛 버전 경로를 가리켜도 통과하던 사각지대를 막는다.)
        resolved = INSTALLER.parent.parent / "portal_browsers.sh"
        self.assertTrue(resolved.exists(), f"설치가 가리킬 런처 없음: {resolved}")
        self.assertEqual(resolved.resolve(), LAUNCHER.resolve())


class PortalInstallerTests(unittest.TestCase):
    def test_installer_exists_and_executable(self) -> None:
        self.assertTrue(INSTALLER.exists(), f"설치 도우미 없음: {INSTALLER}")
        self.assertTrue(_is_executable(INSTALLER), "설치 도우미에 실행 권한이 없다")

    def test_installer_supports_install_and_uninstall(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("launchctl", text)
        for verb in ("install", "uninstall"):
            self.assertIn(verb, text, f"동작 누락: {verb}")

    def test_installer_renders_path_robustly_and_verifies(self) -> None:
        # 설치 스크립트는 sed가 아니라 plistlib 로 경로를 기록(특수문자 안전)하고,
        # 기록 후 되읽어 실제 경로가 실행가능·일치하는지 검증해야 한다.
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("plistlib", text, "plistlib 기반 기록이 아님")
        self.assertIn("portal_browsers.sh", text, "런처 경로 산출 없음")
        self.assertIn('-x "$LAUNCHER"', text, "런처 실행가능 사전 확인 없음")
        self.assertIn("PlistBuddy", text, "기록 후 경로 되읽기 검증 없음")

    def test_render_preserves_exact_launcher_path_with_special_chars(self) -> None:
        # 실제 설치 코드(render)를 공백·& 가 든 경로로 돌려, 기록된 plist가 그 경로를
        # 정확히 보존하는지 확인한다. (sed였다면 깨졌을 케이스 — 회귀 방지)
        import os
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tricky = Path(td) / "a b & c"
            tricky.mkdir()
            fake = tricky / "portal_browsers.sh"
            fake.write_text("#!/bin/sh\nexit 0\n")
            fake.chmod(0o755)
            dest = Path(td) / "out.plist"
            env = {**os.environ, "PORTAL_LAUNCHER_OVERRIDE": str(fake)}
            proc = subprocess.run(
                ["bash", str(INSTALLER), "render", str(dest)],
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            with dest.open("rb") as fh:
                data = plistlib.load(fh)
            self.assertEqual(data["ProgramArguments"], [str(fake), "start"])


if __name__ == "__main__":
    unittest.main()
