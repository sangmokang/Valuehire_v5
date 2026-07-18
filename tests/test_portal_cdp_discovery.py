"""링크드인 CDP 포트 자동 탐지 — 9225 하드코딩 제거 회귀 테스트.

실사고(2026-07-08): portal_browsers.sh 는 링크드인을 9225 로 못박아 두는데, 실제 로그인
프로필로 살아있는 크롬은 다른 포트(9338)로 떠 있었다. 도구가 죽은 9225 로 붙어 "브라우저가
죽었다"로 오진. 근본 고침 = 프로필로 살아있는 크롬의 실제 포트를 찾아 붙는다.

인수 기준(기계 단언):
- `portal_browsers.sh cdp linkedin` 은 설정된 LINKEDIN_PORT 와 무관하게, 그 프로필로 실제
  살아있는 크롬의 remote-debugging-port 를 찾아 http://127.0.0.1:<실제포트> 를 출력한다.
- raw_cdp 는 CDP_HTTP 환경변수를 호출 시점에 읽어 그 엔드포인트로 붙는다(미설정 시 9222 폴백).
"""

from __future__ import annotations

import http.server
import importlib
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "scripts" / "portal_browsers.sh"

# fake 크롬: --remote-debugging-port 를 파싱해 그 포트에 CDP 흉내 HTTP 서버를 띄우고 살아있는다.
FAKE_CHROME_SRC = """
import sys, http.server, socketserver
port = 0
udd = ""
for a in sys.argv[1:]:
    if a.startswith("--remote-debugging-port="):
        port = int(a.split("=", 1)[1])
    if a.startswith("--user-data-dir="):
        udd = a.split("=", 1)[1]
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if self.path.startswith("/json/version"):
            self.wfile.write(b'{"Browser":"Chrome/fake"}')
        else:
            self.wfile.write(b'[]')
    def log_message(self, *a):
        pass
# TIME_WAIT 소켓이 재실행 bind 를 막지 않게 재사용 허용(테스트 결정성).
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", port), H) as srv:
    srv.serve_forever()
"""
FAKE_HTTP_ONLY_SRC = FAKE_CHROME_SRC.replace(
    "self.wfile.write(b'{\"Browser\":\"Chrome/fake\"}')",
    "self.wfile.write(b'{}')",
)


def _free_port() -> int:
    """OS 가 할당하는 빈 포트를 잡아 돌려준다(하드코딩 포트 충돌 방지)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(port: int, timeout: float = 8.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class CdpDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cdp_discovery_"))
        self.fake_chrome = self.tmp / "fake_chrome.py"
        self.fake_chrome.write_text(FAKE_CHROME_SRC, encoding="utf-8")
        self.fake_http_only = self.tmp / "fake_http_only.py"
        self.fake_http_only.write_text(FAKE_HTTP_ONLY_SRC, encoding="utf-8")
        self.procs: list[subprocess.Popen] = []
        self._old_portal_chrome = os.environ.get("PORTAL_CHROME")
        self.process_executable = subprocess.check_output(
            ["ps", "-p", str(os.getpid()), "-o", "comm="], text=True
        ).strip()
        os.environ["PORTAL_CHROME"] = self.process_executable

    def tearDown(self) -> None:
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        if self._old_portal_chrome is None:
            os.environ.pop("PORTAL_CHROME", None)
        else:
            os.environ["PORTAL_CHROME"] = self._old_portal_chrome

    def _launch_fake(self, profile: Path, port: int) -> None:
        profile.mkdir(parents=True, exist_ok=True)
        p = subprocess.Popen(
            [sys.executable, str(self.fake_chrome),
             f"--user-data-dir={profile}",
             f"--remote-debugging-port={port}"],
        )
        self.procs.append(p)
        self.assertTrue(_wait_port(port), f"fake 크롬 포트 {port} 안 뜸")

    def _launch_http_only(self, profile: Path, port: int) -> None:
        profile.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(
            [
                sys.executable,
                str(self.fake_http_only),
                f"--user-data-dir={profile}",
                f"--remote-debugging-port={port}",
            ],
        )
        self.procs.append(process)
        self.assertTrue(_wait_port(port), f"fake HTTP port {port} 안 뜸")

    def _launch_hung(self, profile: Path, port: int) -> None:
        profile.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(60)",
                f"--user-data-dir={profile}",
                f"--remote-debugging-port={port}",
            ],
        )
        self.procs.append(process)

    def _launch_hung_without_port(self, profile: Path) -> None:
        profile.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(60)",
                f"--user-data-dir={profile}",
            ],
        )
        self.procs.append(process)

    def _launch_renderer_helper(self, profile: Path, port: int) -> None:
        """Chrome child processes inherit profile/CDP args but are not browsers."""
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(60)",
                "--type=renderer",
                f"--user-data-dir={profile}",
                f"--remote-debugging-port={port}",
            ],
        )
        self.procs.append(process)

    def test_cdp_discovers_actual_running_port_over_config(self) -> None:
        # 설정 포트와 다른 실제 포트로 크롬이 떠 있는 상황(9225 vs 9338 재현).
        actual = _free_port()
        cfg = _free_port()
        prof = self.tmp / "prof_linkedin"
        self._launch_fake(prof, actual)
        env = {
            **os.environ,
            "LINKEDIN_PORT": str(cfg),          # 설정은 틀린(빈) 포트
            "LINKEDIN_PROFILE": str(prof),
        }
        out = subprocess.run(
            [str(LAUNCHER), "cdp", "linkedin"],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(out.returncode, 0, f"stderr={out.stderr}")
        self.assertEqual(
            out.stdout.strip(), f"http://127.0.0.1:{actual}",
            f"설정({cfg}) 아닌 실제 살아있는 포트({actual})를 출력해야 한다. stdout={out.stdout!r} stderr={out.stderr!r}",
        )

    def test_cdp_does_not_count_renderer_helper_as_second_browser(self) -> None:
        profile = self.tmp / "profile_with_renderer"
        actual = _free_port()
        self._launch_fake(profile, actual)
        self._launch_renderer_helper(profile, actual)
        env = {
            **os.environ,
            "LINKEDIN_PROFILE": str(profile),
            "LINKEDIN_PORT": str(_free_port()),
        }

        out = subprocess.run(
            [str(LAUNCHER), "cdp", "linkedin"],
            env=env, capture_output=True, text=True, timeout=30,
        )

        self.assertEqual(out.returncode, 0, f"stderr={out.stderr}")
        self.assertEqual(out.stdout.strip(), f"http://127.0.0.1:{actual}")

    def test_cdp_ignores_prefix_overlapping_profile(self) -> None:
        # V1 지적: /linkedin 이 /linkedin2 에도 접두 매칭돼 엉뚱한 브라우저 포트를 잡으면 안 된다.
        # 겹치는 프로필(linkedin2)을 먼저 띄워도(=ps 에 먼저 등장) 정확히 linkedin 것만 골라야 한다.
        prof = self.tmp / "prof_linkedin"
        prof2 = self.tmp / "prof_linkedin2"   # 접두가 prof 를 포함
        self.assertTrue(str(prof2).startswith(str(prof)), "테스트 전제: prof2 가 prof 접두 포함")
        wrong = _free_port()
        right = _free_port()
        self._launch_fake(prof2, wrong)       # 겹치는 놈 먼저
        self._launch_fake(prof, right)
        env = {
            **os.environ,
            "LINKEDIN_PORT": str(_free_port()),
            "LINKEDIN_PROFILE": str(prof),
        }
        out = subprocess.run(
            [str(LAUNCHER), "cdp", "linkedin"],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(out.returncode, 0, f"stderr={out.stderr}")
        self.assertEqual(
            out.stdout.strip(), f"http://127.0.0.1:{right}",
            f"정확히 linkedin 프로필 포트({right})만 골라야 한다(linkedin2={wrong} 아님). "
            f"stdout={out.stdout!r} stderr={out.stderr!r}",
        )

    def test_cdp_exits_nonzero_when_no_live_chrome(self) -> None:
        # 프로필로 뜬 크롬이 없으면 재실행 없이 비정상 종료(사람 게이트 존중).
        prof = self.tmp / "prof_empty"
        prof.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "LINKEDIN_PORT": str(_free_port()),  # 아무도 안 듣는 빈 포트
            "LINKEDIN_PROFILE": str(prof),
        }
        out = subprocess.run(
            [str(LAUNCHER), "cdp", "linkedin"],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(out.returncode, 0, "살아있는 크롬 없을 때 0 종료 금지")
        self.assertEqual(out.stdout.strip(), "", "엔드포인트를 지어내면 안 됨")

    def test_cdp_rejects_non_configured_executable_with_chrome_shaped_args(self) -> None:
        profile = self.tmp / "impostor_profile"
        actual = _free_port()
        self._launch_fake(profile, actual)
        env = {
            **os.environ,
            "PORTAL_CHROME": str(self.tmp / "expected-real-chrome"),
            "LINKEDIN_PROFILE": str(profile),
            "LINKEDIN_PORT": str(_free_port()),
        }

        out = subprocess.run(
            [str(LAUNCHER), "cdp", "linkedin"],
            env=env, capture_output=True, text=True, timeout=30,
        )

        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(out.stdout.strip(), "")

    def test_cdp_rejects_plain_http_200_without_browser_version_proof(self) -> None:
        profile = self.tmp / "plain_http_profile"
        actual = _free_port()
        self._launch_http_only(profile, actual)
        env = {
            **os.environ,
            "PORTAL_CHROME": self.process_executable,
            "LINKEDIN_PROFILE": str(profile),
            "LINKEDIN_PORT": str(_free_port()),
        }

        out = subprocess.run(
            [str(LAUNCHER), "cdp", "linkedin"],
            env=env, capture_output=True, text=True, timeout=30,
        )

        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(out.stdout.strip(), "")

    def test_cdp_fails_closed_when_two_exact_profile_processes_are_live(self) -> None:
        profile = self.tmp / "ambiguous_profile"
        first = _free_port()
        second = _free_port()
        self._launch_fake(profile, first)
        self._launch_fake(profile, second)
        env = {
            **os.environ,
            "LINKEDIN_PROFILE": str(profile),
            "LINKEDIN_PORT": str(_free_port()),
        }

        out = subprocess.run(
            [str(LAUNCHER), "cdp", "linkedin"],
            env=env, capture_output=True, text=True, timeout=30,
        )

        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(out.stdout.strip(), "")
        self.assertIn("여러", out.stderr)

    def test_cdp_fails_closed_when_duplicate_exact_profile_has_one_hung_port(self) -> None:
        profile = self.tmp / "ambiguous_hung_profile"
        live = _free_port()
        hung = _free_port()
        self._launch_fake(profile, live)
        self._launch_hung(profile, hung)
        env = {
            **os.environ,
            "LINKEDIN_PROFILE": str(profile),
            "LINKEDIN_PORT": str(_free_port()),
        }

        out = subprocess.run(
            [str(LAUNCHER), "cdp", "linkedin"],
            env=env, capture_output=True, text=True, timeout=30,
        )

        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(out.stdout.strip(), "")
        self.assertIn("여러", out.stderr)

    def test_cdp_fails_closed_when_duplicate_exact_profile_has_no_port(self) -> None:
        profile = self.tmp / "ambiguous_no_port_profile"
        live = _free_port()
        self._launch_fake(profile, live)
        self._launch_hung_without_port(profile)
        env = {
            **os.environ,
            "LINKEDIN_PROFILE": str(profile),
            "LINKEDIN_PORT": str(_free_port()),
        }

        out = subprocess.run(
            [str(LAUNCHER), "cdp", "linkedin"],
            env=env, capture_output=True, text=True, timeout=30,
        )

        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(out.stdout.strip(), "")
        self.assertIn("여러", out.stderr)

    def test_cdp_rejects_unrelated_profile_on_configured_port(self) -> None:
        configured = _free_port()
        wanted = self.tmp / "wanted_profile"
        unrelated = self.tmp / "unrelated_profile"
        wanted.mkdir(parents=True, exist_ok=True)
        self._launch_fake(unrelated, configured)
        env = {
            **os.environ,
            "SARAMIN_PORT": str(configured),
            "SARAMIN_PROFILE": str(wanted),
        }

        out = subprocess.run(
            [str(LAUNCHER), "cdp", "saramin"],
            env=env, capture_output=True, text=True, timeout=30,
        )

        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(out.stdout.strip(), "")


class RawCdpEnvTests(unittest.TestCase):
    """raw_cdp 가 CDP_HTTP env 를 호출 시점에 읽는지(관측가능 동작으로 단언)."""

    def _serve_recording(self):
        hits: list[str] = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"[]")

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return srv, hits

    def test_list_pages_uses_cdp_http_env(self) -> None:
        srv, hits = self._serve_recording()
        port = srv.server_address[1]
        try:
            os.environ["CDP_HTTP"] = f"http://127.0.0.1:{port}"
            # env 를 세팅한 뒤 import/reload → 호출 시점 읽기면 이 엔드포인트로 붙어야 한다.
            sys.path.insert(0, str(REPO))
            from tools.multi_position_sourcing import raw_cdp
            importlib.reload(raw_cdp)
            raw_cdp.list_pages()
            self.assertTrue(
                any(p.startswith("/json") for p in hits),
                f"raw_cdp 가 CDP_HTTP env 엔드포인트로 붙지 않음. hits={hits}",
            )
        finally:
            os.environ.pop("CDP_HTTP", None)
            srv.shutdown()

    def test_list_pages_explicit_endpoint_wins_without_global_env_mutation(self) -> None:
        srv, hits = self._serve_recording()
        port = srv.server_address[1]
        try:
            os.environ["CDP_HTTP"] = "http://127.0.0.1:1"
            from tools.multi_position_sourcing import raw_cdp
            raw_cdp.list_pages(f"http://127.0.0.1:{port}")
            self.assertTrue(any(path.startswith("/json") for path in hits))
            self.assertEqual(os.environ["CDP_HTTP"], "http://127.0.0.1:1")
        finally:
            os.environ.pop("CDP_HTTP", None)
            srv.shutdown()

    def test_default_fallback_9222(self) -> None:
        os.environ.pop("CDP_HTTP", None)
        sys.path.insert(0, str(REPO))
        from tools.multi_position_sourcing import raw_cdp
        importlib.reload(raw_cdp)
        # 미설정 시 기존 기본값 유지(회귀 방지).
        base = raw_cdp._cdp_base()  # noqa: SLF001
        self.assertEqual(base, "http://localhost:9222")


if __name__ == "__main__":
    unittest.main()
