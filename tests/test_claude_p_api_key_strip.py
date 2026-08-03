"""인수기준 — ``claude -p`` 를 subprocess 로 부를 때는 ``ANTHROPIC_API_KEY`` 가 제거된
환경으로 불러야 한다(호출부 전부).

왜: ``claude -p`` 는 Max 구독으로 도는 무료($0) 경로다. 그런데 부모 프로세스에
``ANTHROPIC_API_KEY`` 가 있으면 CLI 가 그 키를 집어 **유료 API 과금 경로**로 조용히
넘어간다. 실패도 경고도 없으니 청구서가 올 때까지 모른다. 문서·스킬에는
``env -u ANTHROPIC_API_KEY claude -p`` 규율이 널리 적혀 있었지만(``skills/st/SKILL.md``
등) 코드로 강제하는 호출부는 3곳 중 1곳뿐이었다 — 이 저장소의 fail-closed 원칙 위반.

검증 방식: mock 이 "불렸는지"만 보지 않는다. **실제로 subprocess 에 전달된 env dict**
를 캡처해 키가 없음을 단언한다. 동시에 호출자가 넘긴 다른 환경변수
(``VALUEHIRE_MACHINE`` 등)는 그대로 살아 있어야 한다 — 키만 빼고 나머지는 보존.
"""
from __future__ import annotations

import os
import subprocess

import pytest

from tools.multi_position_sourcing import fleet_worker as fw
from tools.multi_position_sourcing import llm_keywords as lk
from tools.multi_position_sourcing import matching_score_contract as msc


LIVE_KEY = "sk-ant-api03-DO-NOT-BILL-ME"


def _completed(stdout: str = '{"ok": true}'):
    class _Completed:
        returncode = 0
        stderr = ""

    _Completed.stdout = stdout
    return _Completed()


@pytest.fixture(autouse=True)
def _parent_env_has_live_key(monkeypatch):
    """부모 프로세스에 유료 키가 있는 라이브 상황을 재현한다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", LIVE_KEY)
    monkeypatch.setenv("VALUEHIRE_MACHINE", "macmini")


def _assert_free_tier_env(env, *, must_keep: dict[str, str]):
    """전달된 env 가 (1) 실재하는 dict 이고 (2) 키가 없고 (3) 나머지는 보존됐는지."""
    assert env is not None, (
        "env 를 넘기지 않으면 자식이 부모 환경을 통째로 상속한다 — 유료 키도 함께 간다"
    )
    assert "ANTHROPIC_API_KEY" not in env, f"유료 키가 그대로 전달됨: {sorted(env)[:20]}"
    assert LIVE_KEY not in set(env.values()), "키가 다른 이름으로 새어나감"
    for name, value in must_keep.items():
        assert env.get(name) == value, f"{name} 이 유실됨 — 키만 빼고 나머지는 보존해야 한다"


# ── 호출부 1: 매칭 채점(matching_score_contract.claude_json_client) ──────────

def test_matching_client_calls_claude_without_api_key(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        seen["env"] = kwargs.get("env")
        return _completed()

    monkeypatch.setattr(subprocess, "run", fake_run)
    msc.claude_json_client("prompt")

    assert seen["argv"][:2] == ["claude", "-p"]
    _assert_free_tier_env(seen["env"], must_keep={"VALUEHIRE_MACHINE": "macmini"})


# ── 호출부 2: 키워드 생성(llm_keywords.claude_keyword_client) ───────────────

def test_keyword_client_calls_claude_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(lk.shutil, "which", lambda name: "/usr/local/bin/claude")
    seen: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        seen["env"] = kwargs.get("env")
        return _completed("{}")

    client = lk.claude_keyword_client(run_command=fake_run)
    client("포지션 원문")

    assert seen["argv"][:2] == ["claude", "-p"]
    _assert_free_tier_env(seen["env"], must_keep={"VALUEHIRE_MACHINE": "macmini"})


# ── 호출부 3: 함대 워커(fleet_worker._run_claude) — 실행 경로 4개 전부 ──────

class _FakeCancelPopen:
    """poll() 로 즉시 종료하는 Popen 스텁(_native_agent_run 취소감지 경로용)."""

    instances: list["_FakeCancelPopen"] = []

    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 4242
        self.returncode = 0
        self.stdin = None
        _FakeCancelPopen.instances.append(self)

    def poll(self):
        return 0

    def communicate(self, input=None, timeout=None):
        return ("ok", "")


def test_run_claude_default_env_strips_api_key(monkeypatch) -> None:
    """env 미지정(기본값)이 가장 위험한 경로다 — 부모 환경을 그대로 상속했었다."""
    monkeypatch.setattr(fw.sys, "platform", "darwin")
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen["env"] = kwargs.get("env")
        return _completed("ok")

    monkeypatch.setattr(fw.subprocess, "run", fake_run)
    fw._run_claude("hi", timeout=10)

    assert "-p" in seen["cmd"]
    _assert_free_tier_env(seen["env"], must_keep={"VALUEHIRE_MACHINE": "macmini"})


def test_run_claude_preserves_caller_env_and_drops_only_the_key(monkeypatch) -> None:
    """워커가 넘기는 배지 env 는 그대로 살아야 한다 — 키 하나만 뺀다.

    부모 os.environ 으로 통째로 갈아치우는 '수정'은 배지 env 격리를 깨므로 가짜다.
    """
    monkeypatch.setattr(fw.sys, "platform", "darwin")
    monkeypatch.setenv("VH_ONLY_IN_PARENT", "leaked")
    seen: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen["env"] = kwargs.get("env")
        return _completed("ok")

    monkeypatch.setattr(fw.subprocess, "run", fake_run)
    fw._run_claude("hi", timeout=10, env={
        "VALUEHIRE_MACHINE": "winpc",
        "VALUEHIRE_AGENT_MODEL": "claude-haiku-4-5-20251001",
        "ANTHROPIC_API_KEY": LIVE_KEY,
    })

    env = seen["env"]
    _assert_free_tier_env(env, must_keep={
        "VALUEHIRE_MACHINE": "winpc",
        "VALUEHIRE_AGENT_MODEL": "claude-haiku-4-5-20251001",
    })
    assert "VH_ONLY_IN_PARENT" not in env, (
        "호출자가 준 env 를 부모 환경으로 확장하면 배지 격리가 깨진다"
    )
    assert seen["cmd"][seen["cmd"].index("--model") + 1] == "claude-haiku-4-5-20251001"


def test_run_claude_cancel_watch_path_strips_api_key(monkeypatch) -> None:
    """취소 감지 경로(_native_agent_run → Popen)도 같은 규율을 지켜야 한다."""
    monkeypatch.setattr(fw.sys, "platform", "darwin")
    _FakeCancelPopen.instances.clear()
    monkeypatch.setattr(fw.subprocess, "Popen", _FakeCancelPopen)

    fw._run_claude("hi", timeout=10, cancel_check=lambda: False)

    proc = _FakeCancelPopen.instances[0]
    _assert_free_tier_env(
        proc.kwargs.get("env"), must_keep={"VALUEHIRE_MACHINE": "macmini"})


def test_run_claude_windows_shim_path_strips_api_key(monkeypatch) -> None:
    """윈도우 .cmd shim(shell=True) 경로도 같은 규율을 지켜야 한다."""
    _FakeCancelPopen.instances.clear()
    monkeypatch.setattr(fw.subprocess, "Popen", _FakeCancelPopen)
    monkeypatch.setattr(fw.sys, "platform", "win32")
    monkeypatch.setattr(
        fw.shutil, "which",
        lambda name: r"C:\npm\claude.cmd" if name == "claude" else None,
    )

    fw._run_claude("hi", timeout=10)

    proc = _FakeCancelPopen.instances[0]
    assert proc.kwargs.get("shell") is True
    _assert_free_tier_env(
        proc.kwargs.get("env"), must_keep={"VALUEHIRE_MACHINE": "macmini"})


# ── 호출부 전수 확인: 새 `claude -p` 호출부가 규율 없이 생기면 잡는다 ────────

def test_no_claude_p_call_site_is_left_unprotected() -> None:
    """소스에서 ``"claude", "-p"`` argv 를 만드는 파일은 반드시 키 제거 코드를 갖는다."""
    import re
    from pathlib import Path

    root = Path(fw.__file__).resolve().parents[2]
    offenders: list[str] = []
    for path in sorted((root / "tools").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if not re.search(r'"claude"\s*,\s*"-p"', text) and '"-p"' not in text:
            continue
        if "claude" not in text:
            continue
        if not re.search(r'"claude"\s*,\s*"-p"|base_args\.append\("-p"\)', text):
            continue
        if "ANTHROPIC_API_KEY" not in text:
            offenders.append(str(path.relative_to(root)))
    assert not offenders, f"claude -p 호출부에 키 제거가 없습니다: {offenders}"
