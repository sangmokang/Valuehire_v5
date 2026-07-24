"""단위3b — 워커가 job.params.model 을 실제 CLI 모델 플래그로 전달.

goal: docs/engineering/discord-deterministic-routing-login-first-goal-2026-07-24.md
CLI 플래그(실측): claude `--model <name>`, codex `-m/--model <MODEL>`.
전달 경로: job.params.model → env[VALUEHIRE_AGENT_MODEL] → 각 실행 인자.
없으면 플래그를 붙이지 않는다(기존 기본 모델 유지, fail-safe).
"""

from __future__ import annotations

from tools.multi_position_sourcing.fleet_worker import build_codex_exec_args


class _FakeRun:
    stdout = "ok"
    stderr = ""
    returncode = 0


def test_run_claude_includes_model_flag_from_env(monkeypatch):
    from tools.multi_position_sourcing import fleet_worker as fw
    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeRun()

    monkeypatch.setattr(fw.subprocess, "run", fake_run)
    monkeypatch.setattr(fw.shutil, "which",
                        lambda n: "/usr/bin/claude" if n == "claude" else None)
    fw._run_claude("hi", timeout=10, env={"VALUEHIRE_AGENT_MODEL": "claude-opus-4-8"})
    assert "--model" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "claude-opus-4-8"


def test_run_claude_omits_model_flag_when_env_absent(monkeypatch):
    from tools.multi_position_sourcing import fleet_worker as fw
    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeRun()

    monkeypatch.setattr(fw.subprocess, "run", fake_run)
    monkeypatch.setattr(fw.shutil, "which",
                        lambda n: "/usr/bin/claude" if n == "claude" else None)
    fw._run_claude("hi", timeout=10, env={})
    assert "--model" not in captured["cmd"]


def test_codex_args_include_model_from_env():
    args = build_codex_exec_args({"VALUEHIRE_AGENT_MODEL": "gpt-5.5"})
    assert "--model" in args
    assert args[args.index("--model") + 1] == "gpt-5.5"


def test_codex_args_omit_model_when_env_absent():
    args = build_codex_exec_args({})
    assert "--model" not in args
    assert "-m" not in args
