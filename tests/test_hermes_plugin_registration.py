"""ops/hermes-plugin/valuehire_fleet/__init__.py — 프레임워크 없이도 검증 가능한 부분만.

실제 Hermes 게이트웨이 프로세스는 이 레포 밖(~/.hermes)에 있어 여기서 못 띄운다.
대신 register(ctx)/pre_gateway_dispatch 훅/커맨드 핸들러는 순수 파이썬(덕타이핑)이라
가짜 ctx·event·source 로 이 파일만 독립적으로 검증한다 — 재발명 금지: 실제 인가/큐
로직은 hermes_fleet_bridge.py(이미 검증됨)를 그대로 감싸는지만 본다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
PLUGIN_PATH = REPO / "ops" / "hermes-plugin" / "valuehire_fleet" / "__init__.py"


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location("valuehire_fleet_plugin_under_test", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeCtx:
    def __init__(self) -> None:
        self.hooks: dict[str, list] = {}
        self.commands: dict[str, dict] = {}

    def register_hook(self, hook_name, callback):
        self.hooks.setdefault(hook_name, []).append(callback)

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = {"handler": handler, "description": description, "args_hint": args_hint}


def _discord_event(user_id: str | None):
    source = SimpleNamespace(platform=SimpleNamespace(value="discord"), user_id=user_id)
    return SimpleNamespace(source=source)


def _telegram_event(user_id: str):
    source = SimpleNamespace(platform=SimpleNamespace(value="telegram"), user_id=user_id)
    return SimpleNamespace(source=source)


def test_register_wires_pre_gateway_hook_and_all_four_commands() -> None:
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)
    assert "pre_gateway_dispatch" in ctx.hooks
    assert set(ctx.commands) == {"fleet-run", "fleet-status", "fleet-resume", "fleet-cancel"}


def test_discord_identity_is_captured_and_used_by_handler(monkeypatch) -> None:
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)

    hook = ctx.hooks["pre_gateway_dispatch"][0]
    hook(event=_discord_event("814353841088757800"))

    calls = []

    def fake_dispatch(command, raw_args, *, gateway_user_id, queue=None, authorized_users=None):
        calls.append((command, raw_args, gateway_user_id))
        return {"action": "status", "jobs": []}

    monkeypatch.setattr(
        "tools.multi_position_sourcing.hermes_fleet_bridge.dispatch_hermes_fleet_command",
        fake_dispatch,
    )

    result = ctx.commands["fleet-status"]["handler"]("")
    assert calls == [("fleet-status", "", "814353841088757800")]
    assert json.loads(result) == {"action": "status", "jobs": []}


def test_non_discord_platform_never_leaks_into_gateway_user_id() -> None:
    # self-attack: 텔레그램 등 다른 플랫폼의 숫자 id 가 Discord id 처럼 신뢰되면 안 된다.
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)
    hook = ctx.hooks["pre_gateway_dispatch"][0]

    hook(event=_discord_event("814353841088757800"))  # 이전 요청이 크롬(디스코드) 신원을 남겼다 치고
    hook(event=_telegram_event("814353841088757800"))  # 같은 프로세스에서 텔레그램 메시지가 온 경우

    assert plugin._GATEWAY_USER_ID.get() == ""  # 텔레그램이면 무조건 빈 값으로 리셋(fail-closed)


def test_missing_or_empty_source_resets_to_empty_identity() -> None:
    plugin = _load_plugin_module()
    plugin._GATEWAY_USER_ID.set("814353841088757800")
    plugin._capture_gateway_identity(event=SimpleNamespace(source=None))
    assert plugin._GATEWAY_USER_ID.get() == ""


def test_handler_denies_with_no_stack_trace_when_identity_missing() -> None:
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)
    plugin._GATEWAY_USER_ID.set("")

    result = ctx.commands["fleet-run"]["handler"]("skill:humansearch url:https://x.test machine:macmini")
    assert result.startswith("거부됨:")
    assert "identity" in result
