from __future__ import annotations

import json
import os
import plistlib
from pathlib import Path

import pytest

from tools.hermes_retirement.inventory import (
    InventoryConfig,
    InventoryVerificationError,
    RuntimeProbe,
    _probe_discord_commands,
    build_inventory,
    verify_inventory,
)


FAKE_SECRET = "discord-token-must-never-escape"


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _plist(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(payload))
    return path


def _fixture(tmp_path: Path) -> tuple[InventoryConfig, RuntimeProbe]:
    v4 = tmp_path / "v4"
    v5 = tmp_path / "v5"
    home = tmp_path / "home"
    hermes_home = home / ".hermes"
    launch_agents = home / "Library" / "LaunchAgents"
    external_plugin = tmp_path / "live-plugin" / "valuehire"

    outstanding = _write(
        v4 / "tools/hermes-agent/valuehire-outstanding-news.sh",
        "#!/bin/sh\nexec node tools/outstanding-news/run.mjs\n",
    )
    _write(v4 / "tools/hermes-agent/unused-hermes-helper.sh", "#!/bin/sh\n")
    _write(v4 / "tools/hermes-agent/README.md", "historical Hermes notes\n")
    _write(v4 / "tools/hermes-agent/valuehire/tests/test_skill.py", "# historical\n")
    _plist(
        v4 / "scripts/launchd/com.valuehire.outstanding-news.plist",
        {
            "Label": "com.valuehire.outstanding-news",
            "ProgramArguments": ["/bin/sh", str(outstanding)],
        },
    )

    plugin_init = _write(
        v5 / "ops/hermes-plugin/valuehire_fleet/__init__.py",
        "from tools.multi_position_sourcing.hermes_fleet_bridge import bridge\n",
    )
    _write(v5 / "ops/hermes-plugin/valuehire_fleet/plugin.yaml", "name: valuehire_fleet\n")
    _write(v5 / "tools/multi_position_sourcing/hermes_fleet_bridge.py", "bridge = object()\n")
    _write(v5 / "tools/multi_position_sourcing/hermes_position_context.py", "CONTEXT = {}\n")
    _write(v5 / "scripts/discord_command_listener.py", "# legacy listener\n")
    _write(v5 / "docs/engineering/hermes-history.md", "old Hermes design\n")
    _write(v5 / "tests/test_hermes_old.py", "# retirement coverage\n")

    _write(external_plugin / "__init__.py", "# enabled plugin\n")
    _write(external_plugin / "tests/test_plugin.py", "# historical test\n")

    plugin_dir = hermes_home / "plugins"
    plugin_dir.mkdir(parents=True)
    os.symlink(v5 / "ops/hermes-plugin/valuehire_fleet", plugin_dir / "valuehire_fleet")
    os.symlink(external_plugin, plugin_dir / "valuehire")

    _write(hermes_home / ".env", f"DISCORD_BOT_TOKEN={FAKE_SECRET}\n")
    _write(hermes_home / ".env.bak", f"DISCORD_BOT_TOKEN={FAKE_SECRET}\n")
    _write(hermes_home / "config.yaml", "model: test\n")
    _write(hermes_home / "state.db", "not-a-real-database\n")
    _write(hermes_home / "logs/errors.log", FAKE_SECRET)
    _write(hermes_home / "sessions/current.json", f'{{"token":"{FAKE_SECRET}"}}')
    _write(hermes_home / "hermes-agent/venv/lib/python/site.py", "# opaque vendor bundle\n")

    gateway_plist = _plist(
        launch_agents / "ai.hermes.gateway.plist",
        {
            "Label": "ai.hermes.gateway",
            "ProgramArguments": [
                str(hermes_home / "hermes-agent/venv/bin/python"),
                "-m",
                "hermes_cli.main",
            ],
            "EnvironmentVariables": {"DISCORD_BOT_TOKEN": FAKE_SECRET},
        },
    )

    config = InventoryConfig(
        v4_root=v4,
        v5_root=v5,
        hermes_home=hermes_home,
        launch_agents_dir=launch_agents,
        expected_paths=(
            v4 / "tools/hermes-agent",
            v5 / "ops/hermes-plugin",
            v5 / "tools/multi_position_sourcing/hermes_fleet_bridge.py",
            v5 / "tools/multi_position_sourcing/hermes_position_context.py",
            v5 / "scripts/discord_command_listener.py",
            plugin_dir,
            gateway_plist,
        ),
        generated_at="2026-07-22T00:00:00+00:00",
    )
    probe = RuntimeProbe(
        processes=(
            {
                "pid": 4242,
                "ppid": 1,
                "executable": "python",
                "path_refs": [str(hermes_home / "hermes-agent")],
                "command_fingerprint": "a" * 64,
            },
        ),
        launchd=({"label": "ai.hermes.gateway", "pid": 4242},),
        cron=(
            {
                "line": 3,
                "fingerprint": "b" * 64,
                "path_refs": [str(outstanding)],
                "raw_for_scan_only": f"TOKEN={FAKE_SECRET} /bin/sh {outstanding}",
            },
        ),
        discord_commands=(
            {"id": "123", "name": "aisearch", "type": 1, "scope": "global"},
        ),
        discord_probe={"status": "ok", "bot_id": "999"},
    )
    assert plugin_init.exists()
    return config, probe


def _by_path(inventory: dict) -> dict[str, dict]:
    return {item["path"]: item for item in inventory["items"]}


def test_inventory_classifies_every_related_item_without_unknown(tmp_path: Path) -> None:
    config, probe = _fixture(tmp_path)

    inventory = build_inventory(config, probe)

    verify_inventory(inventory)
    assert inventory["schema_version"] == "hermes-retirement-inventory/v1"
    assert inventory["summary"]["unknown_count"] == 0
    assert inventory["summary"]["item_count"] == len(inventory["items"])
    assert {item["classification"] for item in inventory["items"]} <= {
        "live caller",
        "historical-only",
        "removable",
    }
    assert all(
        item["move_first"] is True
        for item in inventory["items"]
        if item["classification"] == "live caller"
    )


def test_live_symlink_plugin_and_unrelated_cron_are_move_first(tmp_path: Path) -> None:
    config, probe = _fixture(tmp_path)
    inventory = build_inventory(config, probe)
    items = _by_path(inventory)

    outstanding = str(config.v4_root / "tools/hermes-agent/valuehire-outstanding-news.sh")
    external_plugin = str(config.hermes_home / "plugins/valuehire")
    external_init = str((config.hermes_home / "plugins/valuehire").resolve() / "__init__.py")
    bridge = str(
        config.v5_root / "tools/multi_position_sourcing/hermes_fleet_bridge.py"
    )
    gateway_plist = str(config.launch_agents_dir / "ai.hermes.gateway.plist")

    assert items[outstanding]["classification"] == "live caller"
    assert any("crontab:3" in caller for caller in items[outstanding]["callers"])
    assert items[external_plugin]["classification"] == "live caller"
    assert items[external_plugin]["move_first"] is True
    assert items[external_init]["classification"] == "live caller"
    assert items[bridge]["classification"] == "live caller"
    assert items[gateway_plist]["classification"] == "live caller"
    assert items[gateway_plist]["move_first"] is True
    assert items[gateway_plist]["callers"] == ["launchd:ai.hermes.gateway"]


def test_history_tests_and_uncalled_helper_are_not_live_callers(tmp_path: Path) -> None:
    config, probe = _fixture(tmp_path)
    items = _by_path(build_inventory(config, probe))

    readme = str(config.v4_root / "tools/hermes-agent/README.md")
    old_test = str(config.v5_root / "tests/test_hermes_old.py")
    unused = str(config.v4_root / "tools/hermes-agent/unused-hermes-helper.sh")
    env_backup = str(config.hermes_home / ".env.bak")

    assert items[readme]["classification"] == "historical-only"
    assert items[old_test]["classification"] == "historical-only"
    assert items[env_backup]["classification"] == "historical-only"
    assert items[unused]["classification"] == "removable"


def test_secret_values_and_raw_commands_never_enter_inventory(tmp_path: Path) -> None:
    config, probe = _fixture(tmp_path)

    payload = json.dumps(build_inventory(config, probe), ensure_ascii=False)

    assert FAKE_SECRET not in payload
    assert "raw_for_scan_only" not in payload
    assert "EnvironmentVariables" not in payload
    assert "DISCORD_BOT_TOKEN=" not in payload


def test_large_runtime_bundle_is_covered_by_inherited_classification(
    tmp_path: Path,
) -> None:
    config, probe = _fixture(tmp_path)
    inventory = build_inventory(config, probe)
    items = _by_path(inventory)
    bundle = str(config.hermes_home / "hermes-agent")
    child = str(config.hermes_home / "hermes-agent/venv/lib/python/site.py")

    assert items[bundle]["kind"] == "opaque-directory"
    assert items[bundle]["classification"] == "live caller"
    assert items[bundle]["descendant_count"] >= 1
    assert len(items[bundle]["tree_metadata_sha256"]) == 64
    assert child not in items
    assert inventory["coverage"]["inherited_items"] >= 1


def test_verifier_rejects_unknown_missing_coverage_and_unmoved_live_caller(
    tmp_path: Path,
) -> None:
    config, probe = _fixture(tmp_path)
    inventory = build_inventory(config, probe)

    inventory["items"][0]["classification"] = "UNKNOWN"
    with pytest.raises(InventoryVerificationError, match="UNKNOWN"):
        verify_inventory(inventory)

    inventory = build_inventory(config, probe)
    inventory["items"][0]["classification"] = "live caller"
    inventory["items"][0]["move_first"] = False
    with pytest.raises(InventoryVerificationError, match="move_first"):
        verify_inventory(inventory)

    inventory = build_inventory(config, probe)
    inventory["expected_paths"][0]["status"] = "UNKNOWN"
    with pytest.raises(InventoryVerificationError, match="expected path"):
        verify_inventory(inventory)


def test_runtime_sections_are_present_and_secret_free(tmp_path: Path) -> None:
    config, probe = _fixture(tmp_path)
    inventory = build_inventory(config, probe)

    assert inventory["runtime"]["processes"][0]["pid"] == 4242
    assert inventory["runtime"]["launchd"][0]["label"] == "ai.hermes.gateway"
    assert inventory["runtime"]["cron"][0] == {
        "line": 3,
        "fingerprint": "b" * 64,
        "path_refs": [
            str(config.v4_root / "tools/hermes-agent/valuehire-outstanding-news.sh")
        ],
    }
    assert inventory["runtime"]["discord_probe"]["status"] == "ok"
    assert inventory["runtime"]["discord_commands"][0]["name"] == "aisearch"


def test_discord_probe_derives_application_id_when_env_has_only_bot_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config, _probe = _fixture(tmp_path)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", FAKE_SECRET)
    monkeypatch.delenv("DISCORD_CLIENT_ID", raising=False)
    monkeypatch.delenv("DISCORD_GUILD_ID", raising=False)
    calls: list[str] = []

    def fake_get(url: str, token: str) -> object:
        assert token == FAKE_SECRET
        calls.append(url)
        if url.endswith("/oauth2/applications/@me"):
            return {"id": "999"}
        if url.endswith("/applications/999/commands"):
            return [{"id": "123", "name": "aisearch", "type": 1}]
        raise AssertionError(url)

    monkeypatch.setattr(
        "tools.hermes_retirement.inventory._discord_get", fake_get
    )

    commands, status = _probe_discord_commands(config)

    assert status == {"status": "ok", "bot_id": "999", "scope_count": 1}
    assert commands == (
        {"id": "123", "name": "aisearch", "type": 1, "scope": "global"},
    )
    assert calls == [
        "https://discord.com/api/v10/oauth2/applications/@me",
        "https://discord.com/api/v10/applications/999/commands",
    ]
