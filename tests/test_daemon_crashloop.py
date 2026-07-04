"""PC-K6 — search-runner 데몬 크래시-루프 회귀 봉인.

REPO_DIR 이 Desktop 하드코딩이었던 시절에는:
  1) 무효 경로에서 `cd`가 즉시 실패 → `set -e` 가 프로세스를 죽임 → launchd KeepAlive 무한 재시작.
  2) 스크립트/plist 어디에도 실제 checkout 경로가 없어 사장님 맥에서 항상 크래시.

이 테스트는 셸 스크립트 실제 동작(subprocess)과 plist 실제 내용을 직접 관측한다 —
파이썬으로 로직을 재구현해 단언하지 않는다(구현 베끼기 회피).
"""
import os
import plistlib
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

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
        start_new_session=True,
    )
    try:
        time.sleep(1.2)
        assert proc.poll() is None, (
            "무효 REPO_DIR 에서 프로세스가 즉시 종료됨 — KeepAlive 무한재시작을 유발하는 "
            "crash-exit 버그가 재발했습니다."
        )
    finally:
        # sleep(30) 자식이 stderr 파이프를 물고 있어 zsh 부모만 kill 하면 communicate()가
        # 자식 종료까지 블록된다 — 프로세스 그룹 전체를 죽여야 파이프가 닫힌다.
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        _, stderr = proc.communicate(timeout=5)
        assert "REPO_DIR" in stderr
        assert "ERROR" in stderr.upper()


def test_invalid_repo_dir_retry_honors_backoff_interval():
    """RETRY_BACKOFF_SECONDS 를 무시한 busy-retry(무한 즉시재시도)가 아님을 확인한다.

    V1(Codex) 지적: "1.2초 뒤에도 살아있음"만으로는 하드코딩 sleep 이나 빠른
    busy-retry 도 통과할 수 있다 — 실제 백오프 간격이 지켜지는지 ERROR 로그
    타임스탬프 간격으로 직접 측정한다.
    """
    backoff = 1
    proc = subprocess.Popen(
        ["/bin/zsh", str(SCRIPT)],
        env={
            "VALUEHIRE_REPO_DIR": "/nonexistent/path/for/pc-k6-test",
            "VALUEHIRE_SEARCH_RETRY_BACKOFF_SECONDS": str(backoff),
            "PATH": "/usr/bin:/bin",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        time.sleep(3.3)
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        _, stderr = proc.communicate(timeout=5)

    error_lines = [line for line in stderr.splitlines() if "ERROR" in line.upper()]
    # 3.3초 동안 backoff=1s 면 최대 4회 정도 재시도한다. busy-retry(무시)였다면
    # 수백~수천 줄이 찍힌다 — 넉넉히 10줄 미만이면 백오프가 지켜진 것으로 본다.
    assert 1 <= len(error_lines) <= 10, (
        f"백오프 간격이 지켜지지 않음(busy-retry 의심): {len(error_lines)}줄 발생\n{stderr}"
    )


def test_artifact_dir_prepare_failure_fails_soft_not_silently():
    """V1(Codex) 지적: REPO_DIR 은 유효해도 ARTIFACT_DIR/LOG_DIR 준비(mkdir)나
    cd 자체가 실패하면(예: 권한 문제) `set -e` 없이 조용히 다음 명령으로 넘어가
    잘못된 경로에서 계속 도는 회귀가 있었다 — fail-soft 로그로 걸러야 한다."""
    try:
        readonly_parent = tempfile.mkdtemp(prefix="pc-k6-readonly-")
    except OSError as exc:
        pytest.skip(f"이 환경엔 쓰기 가능한 임시 디렉터리가 없음(제한된 샌드박스): {exc}")
    os.chmod(readonly_parent, stat.S_IRUSR | stat.S_IXUSR)  # r-x, 쓰기 불가
    try:
        proc = subprocess.Popen(
            ["/bin/zsh", str(SCRIPT)],
            env={
                "VALUEHIRE_REPO_DIR": str(REPO_ROOT),
                "VALUEHIRE_ARTIFACT_DIR": f"{readonly_parent}/artifacts",
                "VALUEHIRE_LOG_DIR": f"{readonly_parent}/logs",
                "VALUEHIRE_SEARCH_RETRY_BACKOFF_SECONDS": "1",
                "PATH": "/usr/bin:/bin",
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            time.sleep(1.5)
        finally:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            _, stderr = proc.communicate(timeout=5)
        # 일반 "ERROR" 부분일치는 python traceback(예: ModuleNotFoundError)에도
        # 우연히 걸려 뮤테이션을 못 잡는다 — fail-soft 전용 문구를 정확히 확인한다.
        assert "failed to prepare artifact/log dir or cd into REPO_DIR" in stderr, (
            "ARTIFACT_DIR/LOG_DIR 준비 실패가 조용히 무시됨 — fail-soft 로그가 없다:\n" + stderr
        )
    finally:
        os.chmod(readonly_parent, stat.S_IRWXU)
        os.rmdir(readonly_parent)


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
