"""PC-K6 — search-runner 데몬 크래시-루프 회귀 봉인.

REPO_DIR 이 Desktop 하드코딩이었던 시절에는:
  1) 무효 경로에서 `cd`가 즉시 실패 → `set -e` 가 프로세스를 죽임 → launchd KeepAlive 무한 재시작.
  2) 스크립트/plist 어디에도 실제 checkout 경로가 없어 사장님 맥에서 항상 크래시.

이 테스트는 셸 스크립트 실제 동작(subprocess)과 plist 실제 내용을 직접 관측한다 —
파이썬으로 로직을 재구현해 단언하지 않는다(구현 베끼기 회피).
"""
import plistlib
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "valuehire-search-loop.sh"
PLIST = REPO_ROOT / "scripts" / "launchd" / "com.valuehire.search-runner.plist"


def test_invalid_repo_dir_does_not_crash_exit_immediately():
    """무효 REPO_DIR 을 줘도 즉시 crash-exit 하지 않아야 한다 (fail-soft)."""
    proc = subprocess.Popen(
        ["/bin/zsh", str(SCRIPT)],
        env={
            "VALUEHIRE_REPO_DIR": "/nonexistent/path/for/pc-k6-test",
            "VALUEHIRE_SEARCH_RETRY_BACKOFF_SECONDS": "30",
            "PATH": "/usr/bin:/bin",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(1.2)
        assert proc.poll() is None, (
            "무효 REPO_DIR 에서 프로세스가 즉시 종료됨 — KeepAlive 무한재시작을 유발하는 "
            "crash-exit 버그가 재발했습니다."
        )
    finally:
        proc.kill()
        _, stderr = proc.communicate(timeout=5)
        assert "REPO_DIR" in stderr
        assert "ERROR" in stderr.upper()


def test_no_desktop_literal_in_search_loop_script():
    """Desktop/Valuehire_v5 하드코딩 리터럴이 다시 들어오지 않게 봉인."""
    content = SCRIPT.read_text()
    assert "Desktop/Valuehire_v5" not in content


def test_repo_dir_self_derives_to_actual_checkout():
    """REPO_DIR 미지정 시 스크립트 자기 위치 기반으로 실제 repo 를 가리켜야 한다."""
    proc = subprocess.run(
        ["/bin/zsh", str(SCRIPT)],
        env={
            "VALUEHIRE_SEARCH_LOOP_PRINT_REPO_DIR": "1",
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert proc.returncode == 0
    resolved = proc.stdout.strip()
    assert resolved == str(REPO_ROOT)


def test_plist_has_no_desktop_literal_and_program_path_exists():
    """plist 4곳 모두 Desktop 리터럴 0건 + ProgramArguments 스크립트가 실존해야 한다."""
    with PLIST.open("rb") as f:
        data = plistlib.load(f)

    def _walk_strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from _walk_strings(v)
        elif isinstance(value, list):
            for v in value:
                yield from _walk_strings(v)

    for s in _walk_strings(data):
        assert "Desktop" not in s, f"plist 에 Desktop 리터럴 잔존: {s!r}"

    program_args = data["ProgramArguments"]
    script_path = next(a for a in program_args if a.endswith(".sh"))
    assert Path(script_path).exists(), f"ProgramArguments 스크립트가 실존하지 않음: {script_path}"
