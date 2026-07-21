"""ops/hermes-plugin/valuehire_fleet/__init__.py — 프레임워크 없이도 검증 가능한 부분만.

실제 Hermes 게이트웨이 프로세스는 이 레포 밖(~/.hermes)에 있어 여기서 못 띄운다.
대신 register(ctx)/pre_gateway_dispatch 훅/커맨드 핸들러는 순수 파이썬(덕타이핑)이라
가짜 ctx·event·source 로 이 파일만 독립적으로 검증한다 — 재발명 금지: 실제 인가/큐
로직은 hermes_fleet_bridge.py(이미 검증됨)를 그대로 감싸는지만 본다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
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


def _discord_event(
    user_id: str | None,
    *,
    chat_id: str = "1512503041448743092",
    chat_type: str = "dm",
    guild_id: str | None = None,
    message_id: str = "1512503999999999999",
    role_ids: tuple[str, ...] = (),
):
    source = SimpleNamespace(
        platform=SimpleNamespace(value="discord"),
        user_id=user_id,
        chat_id=chat_id,
        chat_type=chat_type,
        guild_id=guild_id,
        message_id=message_id,
    )
    raw_message = SimpleNamespace(
        id=message_id,
        guild_id=guild_id,
        user=SimpleNamespace(
            roles=[SimpleNamespace(id=role_id) for role_id in role_ids]
        ),
    )
    return SimpleNamespace(source=source, raw_message=raw_message, message_id=message_id)


def _telegram_event(user_id: str):
    source = SimpleNamespace(platform=SimpleNamespace(value="telegram"), user_id=user_id)
    return SimpleNamespace(source=source)


def test_register_wires_pre_gateway_hook_and_all_search_commands() -> None:
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)
    assert "pre_gateway_dispatch" in ctx.hooks
    assert set(ctx.commands) == {
        "fleet-run", "fleet-status", "fleet-resume", "fleet-cancel",
        "url", "aisearch", "humansearch",
    }
    assert all(
        ctx.commands[name]["args_hint"] == ""
        for name in ("url", "aisearch", "humansearch")
    )


def test_direct_search_handlers_arm_zero_option_followup_without_dispatch(monkeypatch) -> None:
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)
    ctx.hooks["pre_gateway_dispatch"][0](event=_discord_event("814353841088757800"))
    calls = []

    def fake_dispatch(
        command, raw_args, *, gateway_user_id, queue=None, authorized_users=None,
        invocation_context=None,
    ):
        calls.append((command, raw_args, gateway_user_id))
        return {"action": "enqueued"}

    bridge = plugin._load_bridge_module()
    monkeypatch.setattr(bridge, "dispatch_hermes_fleet_command", fake_dispatch)

    aisearch_prompt = ctx.commands["aisearch"]["handler"]("")
    assert "포지션" in aisearch_prompt
    assert "args" not in aisearch_prompt.lower()
    human_prompt = ctx.commands["url"]["handler"]("")
    assert "URL" in human_prompt
    assert "humansearch" in human_prompt
    assert calls == []


def test_pending_aisearch_followup_rewrites_to_fixed_fleet_skill() -> None:
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)
    hook = ctx.hooks["pre_gateway_dispatch"][0]
    hook(event=_discord_event("814353841088757800"))
    ctx.commands["aisearch"]["handler"]("")

    followup = _discord_event(
        "814353841088757800", message_id="1512503999999999988"
    )
    followup.text = "https://app.clickup.com/t/abc"
    result = hook(event=followup)
    assert result == {
        "action": "rewrite",
        "text": (
            "/fleet-run url https://app.clickup.com/t/abc "
            "channels:saramin,jobkorea followup:aisearch "
            "idempotency:discord:1512503999999999988"
        ),
    }


def test_url_followup_uses_position_context_and_routes_to_humansearch(monkeypatch) -> None:
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)
    hook = ctx.hooks["pre_gateway_dispatch"][0]
    slash = _discord_event(
        "814353841088757800",
        chat_id="1512503041448743092",
        chat_type="group",
        guild_id="1512503000000000000",
        message_id="1512503999999999999",
        role_ids=("1512503111111111111",),
    )
    hook(event=slash)
    bridge = plugin._load_bridge_module()
    store = plugin._position_context_store(bridge)
    monkeypatch.setattr(store, "get", lambda *_: SimpleNamespace(
        position_url="https://app.clickup.com/t/abc", channels=("jobkorea",)
    ))
    ctx.commands["url"]["handler"]("")

    followup = _discord_event(
        "814353841088757800",
        chat_id="1512503041448743092",
        chat_type="group",
        guild_id="1512503000000000000",
        message_id="1512503999999999988",
        role_ids=("1512503111111111111",),
    )
    followup.text = "https://www.jobkorea.co.kr/Search/?stext=kotlin 경력7년 서울"
    result = hook(event=followup)
    assert result["action"] == "rewrite"
    assert result["text"].startswith(
        "/fleet-run humansearch https://app.clickup.com/t/abc "
        "https://www.jobkorea.co.kr/Search/?stext=kotlin"
    )
    assert "channels:jobkorea" in result["text"]
    assert "idempotency:discord:1512503999999999988" in result["text"]


def test_pending_search_is_scoped_to_same_user_and_channel() -> None:
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)
    hook = ctx.hooks["pre_gateway_dispatch"][0]
    hook(event=_discord_event("814353841088757800", chat_id="1512503041448743092"))
    ctx.commands["aisearch"]["handler"]("")

    other_channel = _discord_event(
        "814353841088757800",
        chat_id="1512503041448743999",
        message_id="1512503999999999988",
    )
    other_channel.text = "그냥 대화"
    assert hook(event=other_channel) is None
    assert ("814353841088757800", "1512503041448743092") in plugin._PENDING_SEARCH_INTAKES


def test_expired_search_intake_does_not_consume_later_message(monkeypatch) -> None:
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)
    hook = ctx.hooks["pre_gateway_dispatch"][0]
    slash = _discord_event("814353841088757800")
    hook(event=slash)
    ctx.commands["aisearch"]["handler"]("")
    monkeypatch.setattr(plugin.time, "time", lambda: 10_000.0)
    key = ("814353841088757800", "1512503041448743092")
    plugin._PENDING_SEARCH_INTAKES[key] = (0.0, "aisearch")

    later = _discord_event(
        "814353841088757800", message_id="1512503999999999988"
    )
    later.text = "URL 없는 일반 대화"
    assert hook(event=later) is None
    assert key not in plugin._PENDING_SEARCH_INTAKES


def test_discord_identity_is_captured_and_used_by_handler(monkeypatch) -> None:
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)

    hook = ctx.hooks["pre_gateway_dispatch"][0]
    hook(event=_discord_event("814353841088757800"))

    calls = []

    def fake_dispatch(
        command, raw_args, *, gateway_user_id, queue=None, authorized_users=None,
        invocation_context=None,
    ):
        calls.append((command, raw_args, gateway_user_id))
        return {"action": "status", "jobs": []}

    bridge = plugin._load_bridge_module()
    monkeypatch.setattr(bridge, "dispatch_hermes_fleet_command", fake_dispatch)

    result = ctx.commands["fleet-status"]["handler"]("")
    assert calls == [("fleet-status", "", "814353841088757800")]
    assert json.loads(result) == {"action": "status", "jobs": []}


def test_natural_discord_search_is_rewritten_to_fleet_run() -> None:
    # 2026-07-14: 잡코리아 검색결과 URL이 섞여 있으면 humansearch로 바뀌어야 한다 —
    # 예전엔 항상 aisearch로 고정돼 있었다(버그, tools/.../hermes_fleet_bridge.py
    # _default_skill_for_urls 도입으로 수정).
    plugin = _load_plugin_module()
    event = _discord_event("814353841088757800")
    event.text = (
        "humansearch https://app.clickup.com/t/abc "
        "https://www.jobkorea.co.kr/Search/?stext=cto win"
    )
    result = plugin._capture_gateway_identity(event=event)
    assert result == {
        "action": "rewrite",
        "text": (
            "/fleet-run humansearch https://app.clickup.com/t/abc "
            "https://www.jobkorea.co.kr/Search/?stext=cto channels:jobkorea winpc "
            "idempotency:discord:1512503999999999999"
        ),
    }


def test_plugin_loads_correctly_even_when_hermes_own_tools_package_is_already_imported() -> None:
    # 라이브 적대검증(2026-07-13)에서 실제 발견한 버그의 재현: Hermes 자신도 최상위
    # 패키지 이름 "tools" 를 쓴다. 우리 플러그인이 "tools.multi_position_sourcing..." 로
    # import 하면, 이미 sys.modules 에 캐시된 Hermes 자신의 "tools" 가 우선돼
    # "No module named 'tools.multi_position_sourcing'" 로 조용히 죽는다(gateway/run.py
    # 의 except Exception 이 삼켜 실사용자에겐 무응답으로만 보임). 별도 서브프로세스에서
    # 가짜 "tools" 패키지를 먼저 import 시켜 그 충돌 조건을 실제로 재현하고, 그래도
    # 플러그인이 정상 동작하는지 확인한다.
    script = textwrap.dedent(
        f"""
        import sys, types
        # Hermes 자신의 tools 패키지 흉내 — 우리 코드와 무관한 내용물
        fake_tools = types.ModuleType("tools")
        fake_tools.__path__ = []
        sys.modules["tools"] = fake_tools

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "valuehire_fleet_plugin_under_test", {str(PLUGIN_PATH)!r}
        )
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)

        class FakeCtx:
            def __init__(self):
                self.hooks = {{}}
                self.commands = {{}}
            def register_hook(self, n, cb):
                self.hooks.setdefault(n, []).append(cb)
            def register_command(self, name, handler, description="", args_hint=""):
                self.commands[name] = handler

        ctx = FakeCtx()
        plugin.register(ctx)

        from types import SimpleNamespace
        hook = ctx.hooks["pre_gateway_dispatch"][0]
        hook(event=SimpleNamespace(
            source=SimpleNamespace(
                platform=SimpleNamespace(value="discord"),
                user_id="814353841088757800",
            )
        ))
        result = ctx.commands["fleet-status"]("")
        assert "No module named" not in result, result
        print("OK:", result[:80])
        """
    )
    # 이 테스트의 관심사는 "tools" 패키지 이름 충돌뿐인데, fleet-status 는 잡큐(Supabase)
    # 를 실제 HTTPS 로 조회한다. 자격증명이 보이는 환경(본 레포 .env.local)에서는 원격
    # 응답 지연 30초가 그대로 subprocess timeout=30 을 넘겨 네트워크 상태에 따라
    # 널뛰는 테스트가 된다(2026-07-17 실측: TimeoutExpired). 즉시 connection refused 가
    # 나는 로컬 주소를 짝으로 주입해 오프라인·결정적으로 만든다 — 핸들러가 오류를
    # 문자열로 돌려줘도 "No module named" 검증에는 영향이 없다.
    offline_env = {
        **os.environ,
        "NEXT_PUBLIC_SUPABASE_URL": "http://127.0.0.1:9",
        "SUPABASE_SERVICE_ROLE_KEY": "offline-test-dummy",
    }
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=30, env=offline_env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK:" in proc.stdout


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


def test_zero_option_alias_fails_closed_without_discord_event_identity() -> None:
    plugin = _load_plugin_module()
    ctx = FakeCtx()
    plugin.register(ctx)
    plugin._GATEWAY_USER_ID.set("814353841088757800")
    plugin._GATEWAY_INVOCATION_CONTEXT.set({})

    result = ctx.commands["url"]["handler"]("")
    assert result.startswith("거부됨:")
    assert "event identity" in result
