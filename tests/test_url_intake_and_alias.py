"""/url intake skill=url 정합 + $ 텍스트 별칭 정규화 (RED #639 — 프롬프트 RED 2·4).

기존 결함(실측): ops/hermes-plugin/valuehire_fleet/__init__.py 의
`fixed_skill = "humansearch" if command_name in {"url", "humansearch"} else "aisearch"`
— /url 이 humansearch 로 고정된다. url 스킬 의미와 일치해야 한다.
"""

from __future__ import annotations

import importlib.util
import time as _time
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
PLUGIN_PATH = REPO / "ops" / "hermes-plugin" / "valuehire_fleet" / "__init__.py"


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location(
        "valuehire_fleet_plugin_alias_test", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _event(text, *, user_id="42", message_id="123456789012345678"):
    source = SimpleNamespace(
        platform="discord", user_id=user_id, chat_type="dm", chat_id="777",
    )
    return SimpleNamespace(source=source, text=text, message_id=message_id)


def test_url_intake_fixes_skill_url():
    mod = _load_plugin_module()
    handler = mod._make_search_intake_handler("url")
    mod._GATEWAY_USER_ID.set("42")
    mod._GATEWAY_INVOCATION_CONTEXT.set({
        "channel_id": "777", "event_id": "123456789012345678",
    })
    handler("")
    (_ts, fixed_skill) = mod._PENDING_SEARCH_INTAKES[("42", "777")]
    assert fixed_skill == "url", "/url intake 는 skill=url 로 enqueue 돼야 한다"


def test_url_intake_followup_message_enqueues_url_skill():
    mod = _load_plugin_module()
    mod._PENDING_SEARCH_INTAKES[("42", "777")] = (_time.time(), "url")
    result = mod._capture_gateway_identity(
        event=_event("https://www.linkedin.com/talent/search?foo=1"))
    assert isinstance(result, dict) and result.get("action") == "rewrite"
    text = result["text"]
    assert "/fleet-run url " in text or text.startswith("url "), text
    assert "humansearch" not in text
    assert "idempotency:discord:123456789012345678" in text


def test_humansearch_intake_still_humansearch():
    mod = _load_plugin_module()
    handler = mod._make_search_intake_handler("humansearch")
    mod._GATEWAY_USER_ID.set("42")
    mod._GATEWAY_INVOCATION_CONTEXT.set({
        "channel_id": "777", "event_id": "123456789012345678",
    })
    handler("")
    (_ts, fixed_skill) = mod._PENDING_SEARCH_INTAKES[("42", "777")]
    assert fixed_skill == "humansearch"


def test_dollar_alias_rewrites_to_slash_command():
    mod = _load_plugin_module()
    mod._PENDING_SEARCH_INTAKES.clear()
    result = mod._capture_gateway_identity(event=_event("$aisearch"))
    assert isinstance(result, dict) and result.get("action") == "rewrite"
    assert result["text"].split()[0] == "/aisearch"


def test_dollar_alias_with_args_becomes_idempotent_fleet_run():
    mod = _load_plugin_module()
    mod._PENDING_SEARCH_INTAKES.clear()
    result = mod._capture_gateway_identity(
        event=_event("$ai-search https://app.clickup.com/t/86999xyz 후보 찾아줘"))
    assert isinstance(result, dict) and result.get("action") == "rewrite"
    text = result["text"]
    assert text.startswith("/fleet-run aisearch ")
    assert "idempotency:discord:123456789012345678" in text


def test_dollar_alias_same_event_id_yields_same_idempotency_key():
    mod = _load_plugin_module()
    outs = []
    for alias in ("$aisearch https://app.clickup.com/t/86999xyz",
                  "/aisearch https://app.clickup.com/t/86999xyz"):
        mod._PENDING_SEARCH_INTAKES.clear()
        r = mod._capture_gateway_identity(event=_event(alias))
        outs.append(r["text"] if isinstance(r, dict) else "")
    keys = {t.split("idempotency:")[-1].split()[0]
            for t in outs if "idempotency:" in t}
    assert keys == {"discord:123456789012345678"}, outs


def test_dollar_in_middle_of_text_is_not_command():
    mod = _load_plugin_module()
    mod._PENDING_SEARCH_INTAKES.clear()
    result = mod._capture_gateway_identity(
        event=_event("예산은 $100 입니다. url 검토 부탁"))
    if isinstance(result, dict):
        assert result.get("action") != "rewrite" or "/fleet-run" not in result.get("text", "")
