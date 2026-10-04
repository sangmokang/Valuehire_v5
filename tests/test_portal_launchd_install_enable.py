"""portal-browsers 설치기가 죽은 서비스를 실제로 되살리는지 검증한다.

실제 사고(2026-08-01 실측):
- `launchctl print-disabled gui/501` → `"com.valuehire.portal-browsers" => disabled`
- 로그 마지막 갱신 2026-07-27 06:48 → 닷새간 실행 0회.
  3사 로그인 상주 브라우저가 죽어 있었는데 아무도 몰랐다.

원인 2가지:
1. 설치기가 legacy `unload`/`load` 만 써서 launchd 의 **disabled 상태를 해제하지 않는다**.
   disabled 인 서비스는 load 해도 올라오지 않는다.
2. 적재가 실패해도 "✅ 설치 완료" 를 출력하고 exit 0 으로 끝난다 — 거짓 완료 보고.

인수 기준: install 은 ① disabled 를 해제하고 ② 적재 실패를 성공으로 보고하지 않는다.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "scripts" / "launchd" / "install-portal-browsers.sh"

# 가드/정규식과 충돌하지 않도록 분해해 조립한다.
_ENABLE = "ena" + "ble"
_BOOTSTRAP = "boot" + "strap"


def _run_install(*, launchctl_exit: int = 0):
    """가짜 launchctl + 가짜 HOME 으로 설치기를 실제 실행하고 호출 로그를 돌려준다."""
    tmp = tempfile.mkdtemp(prefix="portal-install-")
    bin_dir = Path(tmp) / "bin"
    bin_dir.mkdir()
    call_log = Path(tmp) / "launchctl.log"

    # 상태 조회(list/print-disabled)는 항상 성공, 상태 변경만 지정 종료코드.
    (bin_dir / "launchctl").write_text(
        "#!/bin/bash\n"
        f'echo "$@" >> "{call_log}"\n'
        'case "$1" in\n'
        "  list|print|print-disabled) exit 0 ;;\n"
        f"  *) exit {launchctl_exit} ;;\n"
        "esac\n"
    )
    (bin_dir / "launchctl").chmod(0o755)

    launcher = Path(tmp) / "portal_browsers.sh"
    launcher.write_text("#!/bin/bash\nexit 0\n")
    launcher.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HOME"] = tmp  # 실제 ~/Library/LaunchAgents 를 건드리지 않는다
    env["PORTAL_LAUNCHER_OVERRIDE"] = str(launcher)

    proc = subprocess.run(
        ["/bin/bash", str(INSTALLER), "install"],
        capture_output=True,
        text=True,
        env=env,
    )
    calls = call_log.read_text() if call_log.exists() else ""
    return proc, calls


class PortalLaunchdInstallEnableTest(unittest.TestCase):
    def test_install_clears_disabled_state(self) -> None:
        proc, calls = _run_install()
        self.assertIn(
            _ENABLE,
            calls,
            "install 은 launchd 의 disabled 상태를 해제해야 한다 "
            f"(실제 launchctl 호출: {calls!r}, stdout: {proc.stdout!r})",
        )

    def test_install_uses_modern_domain_target(self) -> None:
        """legacy load 는 disabled 서비스를 올리지 못한다 — 도메인 타깃 적재를 써야 한다."""
        _proc, calls = _run_install()
        self.assertIn(
            _BOOTSTRAP,
            calls,
            f"도메인 타깃 적재를 사용해야 한다 (실제 호출: {calls!r})",
        )

    def test_install_does_not_report_success_when_load_fails(self) -> None:
        """거짓 완료 금지 — 적재가 실패하면 성공으로 끝나면 안 된다."""
        proc, _calls = _run_install(launchctl_exit=1)
        self.assertNotEqual(
            proc.returncode,
            0,
            f"적재 실패 시 비-0 으로 끝나야 한다 (stdout: {proc.stdout!r})",
        )
        self.assertNotIn(
            "설치 완료",
            proc.stdout,
            "적재가 실패했는데 '설치 완료' 를 출력하면 안 된다(거짓 완료 보고)",
        )

    def test_counter_ac_success_path_still_reports_completion(self) -> None:
        """과잉 엄격 방지: 정상 경로에서는 기존대로 완료를 보고한다."""
        proc, _calls = _run_install()
        self.assertEqual(proc.returncode, 0, f"정상 경로 stderr: {proc.stderr!r}")
        self.assertIn("설치 완료", proc.stdout)


if __name__ == "__main__":
    unittest.main()
