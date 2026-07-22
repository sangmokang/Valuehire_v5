from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import plistlib
import subprocess
from pathlib import Path

import pytest

from tools.hermes_retirement.inventory import (
    InventoryConfig,
    InventoryVerificationError,
    RuntimeProbe,
    _classified_scope_evidence,
    _iter_repo_text,
    _known_path_refs,
    _probe_discord_commands,
    _probe_launchd,
    _relevant_launch_agents,
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
    _write(v5 / ".hermes/plans/old-hermes-plan.md", "retired plan\n")
    _write(
        v5 / ".codex/skills/vhskill/SKILL.md",
        "production caller uses hermes_fleet_bridge\n",
    )
    _write(v4 / ".omx/logs/hermes-run.json", "{}\n")
    _write(
        v4 / "worktrees/stale/tools/hermes-agent/valuehire/plugin.yaml",
        "historical worktree copy\n",
    )
    _write(
        v4 / "data/outstanding-news-runs/hermes-20260722/texts/result.txt",
        "historical output\n",
    )

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
    _plist(
        launch_agents / "com.valuehire.outstanding-news.plist",
        {
            "Label": "com.valuehire.outstanding-news",
            "ProgramArguments": ["/bin/sh", str(outstanding)],
        },
    )
    legacy_gateway = tmp_path / "legacy/tools/hermes-agent/hermes-gateway.sh"

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
            hermes_home,
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
        launchd=(
            {"label": "ai.hermes.gateway", "pid": 4242},
            {"label": "com.valuehire.outstanding-news", "pid": 0},
        ),
        cron=(
            {
                "line": 3,
                "fingerprint": "b" * 64,
                "path_refs": [str(outstanding)],
                "raw_for_scan_only": f"TOKEN={FAKE_SECRET} /bin/sh {outstanding}",
            },
            {
                "line": 4,
                "fingerprint": "c" * 64,
                "path_refs": [str(legacy_gateway)],
                "raw_for_scan_only": f"/bin/sh {legacy_gateway}",
            },
        ),
        discord_commands=(
            {"id": "123", "name": "aisearch", "type": 1, "scope": "global"},
        ),
        discord_probe={
            "status": "ok",
            "bot_id": "999",
            "guild_count": 0,
            "scope_count": 1,
        },
    )
    assert plugin_init.exists()
    return config, probe


def _by_path(inventory: dict) -> dict[str, dict]:
    return {item["path"]: item for item in inventory["items"]}


def test_inventory_classifies_every_related_item_without_unknown(tmp_path: Path) -> None:
    config, probe = _fixture(tmp_path)

    inventory = build_inventory(config, probe)

    verify_inventory(inventory, live_probe=probe)
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
    outstanding_plist = str(
        config.launch_agents_dir / "com.valuehire.outstanding-news.plist"
    )
    legacy_gateway = str(
        tmp_path / "legacy/tools/hermes-agent/hermes-gateway.sh"
    )

    assert items[outstanding]["classification"] == "live caller"
    assert any("crontab:3" in caller for caller in items[outstanding]["callers"])
    assert items[external_plugin]["classification"] == "live caller"
    assert items[external_plugin]["move_first"] is True
    assert items[external_init]["classification"] == "live caller"
    assert items[external_init]["callers"] == [f"plugin-symlink:{external_plugin}"]
    assert items[bridge]["classification"] == "live caller"
    assert items[gateway_plist]["classification"] == "live caller"
    assert items[gateway_plist]["move_first"] is True
    assert items[gateway_plist]["callers"] == ["launchd:ai.hermes.gateway"]
    assert items[outstanding_plist]["callers"] == [
        "launchd:com.valuehire.outstanding-news"
    ]
    assert items[legacy_gateway]["kind"] == "path-reference"
    assert items[legacy_gateway]["classification"] == "live caller"
    assert items[legacy_gateway]["callers"] == ["crontab:4"]


def test_history_tests_and_uncalled_helper_are_not_live_callers(tmp_path: Path) -> None:
    config, probe = _fixture(tmp_path)
    items = _by_path(build_inventory(config, probe))

    readme = str(config.v4_root / "tools/hermes-agent/README.md")
    old_test = str(config.v5_root / "tests/test_hermes_old.py")
    unused = str(config.v4_root / "tools/hermes-agent/unused-hermes-helper.sh")
    env_backup = str(config.hermes_home / ".env.bak")
    repo_plan = str(config.v5_root / ".hermes/plans/old-hermes-plan.md")
    omx_log = str(config.v4_root / ".omx/logs/hermes-run.json")
    stale_worktree = str(
        config.v4_root
        / "worktrees/stale/tools/hermes-agent/valuehire/plugin.yaml"
    )
    run_output = str(
        config.v4_root
        / "data/outstanding-news-runs/hermes-20260722/texts/result.txt"
    )

    assert items[readme]["classification"] == "historical-only"
    assert items[old_test]["classification"] == "historical-only"
    assert items[env_backup]["classification"] == "historical-only"
    assert items[repo_plan]["classification"] == "historical-only"
    assert items[omx_log]["classification"] == "historical-only"
    assert items[stale_worktree]["classification"] == "historical-only"
    assert items[run_output]["classification"] == "historical-only"
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
        verify_inventory(inventory, live_probe=probe)

    inventory = build_inventory(config, probe)
    inventory["items"][0]["classification"] = "live caller"
    inventory["items"][0]["move_first"] = False
    with pytest.raises(InventoryVerificationError, match="move_first"):
        verify_inventory(inventory, live_probe=probe)

    inventory = build_inventory(config, probe)
    inventory["expected_paths"][0]["status"] = "UNKNOWN"
    with pytest.raises(InventoryVerificationError, match="expected path"):
        verify_inventory(inventory, live_probe=probe)


def _recompute_summary(inventory: dict) -> None:
    classifications = {
        name: sum(item["classification"] == name for item in inventory["items"])
        for name in ("historical-only", "live caller", "removable")
    }
    inventory["summary"].update(
        {
            "item_count": len(inventory["items"]),
            "unknown_count": 0,
            "classifications": classifications,
            "move_first_count": sum(
                item.get("move_first") is True for item in inventory["items"]
            ),
        }
    )


def _recompute_scope_evidence(inventory: dict) -> None:
    items = {item["path"]: item for item in inventory["items"]}
    for row in inventory["expected_paths"]:
        count, digest = _classified_scope_evidence(Path(row["path"]), items)
        row["classified_descendant_count"] = count
        row["observed_descendant_count"] = count
        row["classified_path_sha256"] = digest
        row["observed_tree_sha256"] = digest


@pytest.mark.parametrize(
    "mutation",
    (
        "drop_v4_subtree",
        "drop_reason_callers",
        "drop_roots",
        "drop_coverage",
        "empty_live_runtime",
        "invalid_cron_shape",
        "drop_expected_paths",
        "corrupt_summary",
        "nested_secret_field",
        "stale_scanner_sha",
        "drop_one_and_recompute_scope",
        "secret_discord_id",
        "secret_reason",
        "secret_executable",
        "drop_repo_wide_caller",
    ),
)
def test_verifier_rejects_material_inventory_omissions(
    tmp_path: Path, mutation: str
) -> None:
    config, probe = _fixture(tmp_path)
    inventory = copy.deepcopy(build_inventory(config, probe))

    if mutation == "drop_v4_subtree":
        prefix = f"{config.v4_root / 'tools/hermes-agent'}/"
        inventory["items"] = [
            item for item in inventory["items"] if not item["path"].startswith(prefix)
        ]
        _recompute_summary(inventory)
    elif mutation == "drop_reason_callers":
        inventory["items"][0].pop("reason")
        inventory["items"][0].pop("callers")
    elif mutation == "drop_roots":
        inventory.pop("roots_scanned")
    elif mutation == "drop_coverage":
        inventory.pop("coverage")
    elif mutation == "empty_live_runtime":
        inventory["runtime"]["processes"] = []
        inventory["runtime"]["launchd"] = []
    elif mutation == "invalid_cron_shape":
        inventory["runtime"]["cron"] = "not-an-array"
    elif mutation == "drop_expected_paths":
        inventory["expected_paths"] = inventory["expected_paths"][:1]
    elif mutation == "corrupt_summary":
        inventory["summary"]["classifications"]["removable"] += 1
    elif mutation == "nested_secret_field":
        inventory["runtime"]["discord_probe"]["raw_command"] = FAKE_SECRET
    elif mutation == "stale_scanner_sha":
        inventory["scanner_sha256"] = "0" * 64
    elif mutation == "drop_one_and_recompute_scope":
        target = str(
            config.v4_root
            / "tools/hermes-agent/valuehire-outstanding-news.sh"
        )
        inventory["items"] = [
            item for item in inventory["items"] if item["path"] != target
        ]
        _recompute_summary(inventory)
        _recompute_scope_evidence(inventory)
    elif mutation == "secret_discord_id":
        inventory["runtime"]["discord_commands"][0]["id"] = (
            "synthetic-raw-secret-token-value"
        )
    elif mutation == "secret_reason":
        inventory["items"][0]["reason"] = "synthetic-raw-secret-token-value"
    elif mutation == "secret_executable":
        inventory["runtime"]["processes"][0]["executable"] = (
            "synthetic-raw-secret-token-value"
        )
    elif mutation == "drop_repo_wide_caller":
        target = str(config.v5_root / ".codex/skills/vhskill/SKILL.md")
        inventory["items"] = [
            item for item in inventory["items"] if item["path"] != target
        ]
        _recompute_summary(inventory)
        inventory["coverage"]["explicit_items"] = len(inventory["items"])
        inventory["coverage"]["repo_candidate_count"] -= 1
        inventory["coverage"]["repo_candidate_sha256"] = "0" * 64

    with pytest.raises(InventoryVerificationError):
        verify_inventory(inventory, live_probe=probe)


def test_verifier_rejects_actual_known_secret_in_free_string_field(
    tmp_path: Path,
) -> None:
    config, probe = _fixture(tmp_path)
    inventory = build_inventory(config, probe)
    live_item = next(
        item for item in inventory["items"] if item["classification"] == "live caller"
    )
    live_item["callers"].append(FAKE_SECRET)

    with pytest.raises(InventoryVerificationError, match="secret"):
        verify_inventory(inventory, live_probe=probe)


@pytest.mark.parametrize(
    "mutation",
    (
        "process_fingerprint",
        "cron_fingerprint",
        "launchd_pid",
        "discord_command_id",
        "cron_path_downgrade",
    ),
)
def test_verifier_rejects_valid_shape_runtime_tampering(
    tmp_path: Path, mutation: str
) -> None:
    config, probe = _fixture(tmp_path)
    inventory = build_inventory(config, probe)

    if mutation == "process_fingerprint":
        inventory["runtime"]["processes"][0]["command_fingerprint"] = "f" * 64
    elif mutation == "cron_fingerprint":
        inventory["runtime"]["cron"][0]["fingerprint"] = "f" * 64
    elif mutation == "launchd_pid":
        inventory["runtime"]["launchd"][1]["pid"] = 9999
    elif mutation == "discord_command_id":
        inventory["runtime"]["discord_commands"][0]["id"] = "456"
    elif mutation == "cron_path_downgrade":
        inventory["runtime"]["cron"][0]["reference_mode"] = "text-only"
        inventory["runtime"]["cron"][0]["path_refs"] = []

    with pytest.raises(InventoryVerificationError, match="runtime"):
        verify_inventory(inventory, live_probe=probe)


def test_verifier_rejects_live_plugin_classification_forgery(tmp_path: Path) -> None:
    config, probe = _fixture(tmp_path)
    inventory = build_inventory(config, probe)
    target = str(tmp_path / "live-plugin/valuehire/__init__.py")
    item = next(item for item in inventory["items"] if item["path"] == target)
    item.update(
        {
            "classification": "removable",
            "move_first": False,
            "callers": [],
            "reason": "dedicated Hermes item has no non-historical caller",
        }
    )
    _recompute_summary(inventory)

    with pytest.raises(InventoryVerificationError, match="classification"):
        verify_inventory(inventory, live_probe=probe)


def test_production_verifier_has_no_runtime_probe_override() -> None:
    assert "live_probe" not in inspect.signature(verify_inventory).parameters


def test_verifier_rejects_noncanonical_inventory_roots(tmp_path: Path) -> None:
    config, probe = _fixture(tmp_path)
    inventory = build_inventory(config, probe)

    with pytest.raises(InventoryVerificationError, match="roots_scanned"):
        verify_inventory(inventory, live_probe=probe)


def test_runtime_sections_are_present_and_secret_free(tmp_path: Path) -> None:
    config, probe = _fixture(tmp_path)
    inventory = build_inventory(config, probe)

    assert inventory["runtime"]["processes"][0]["pid"] == 4242
    assert inventory["runtime"]["launchd"][0]["label"] == "ai.hermes.gateway"
    assert inventory["runtime"]["cron"][0] == {
        "reference_mode": "path",
        "line": 3,
        "fingerprint": "b" * 64,
        "path_refs": [
            str(config.v4_root / "tools/hermes-agent/valuehire-outstanding-news.sh")
        ],
    }
    assert inventory["runtime"]["discord_probe"]["status"] == "ok"
    assert inventory["runtime"]["discord_commands"][0]["name"] == "aisearch"
    assert inventory["runtime"]["probe_status"] == {
        "cron": "ok",
        "discord": "ok",
        "launchd": "ok",
        "processes": "ok",
    }
    assert inventory["scanner_sha256"] == hashlib.sha256(
        Path("tools/hermes_retirement/inventory.py").read_bytes()
    ).hexdigest()


def test_dynamic_home_metadata_drift_does_not_invalidate_path_topology(
    tmp_path: Path,
) -> None:
    config, probe = _fixture(tmp_path)
    inventory = build_inventory(config, probe)

    _write(config.hermes_home / "config.yaml", "model: changed-after-snapshot\n")

    verify_inventory(inventory, live_probe=probe)


def test_invalid_launch_agent_plist_fails_closed(tmp_path: Path) -> None:
    launch_agents = tmp_path / "Library/LaunchAgents"
    _write(launch_agents / "broken-hermes.plist", "not a plist")

    with pytest.raises(InventoryVerificationError, match="launch agent"):
        list(_relevant_launch_agents(launch_agents))


def test_repo_walk_error_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "v5"
    root.mkdir()

    def failing_walk(*args, **kwargs):
        callback = kwargs.get("onerror")
        assert callback is not None
        callback(PermissionError("synthetic unreadable subtree"))
        return []

    monkeypatch.setattr(os, "walk", failing_walk)

    with pytest.raises(InventoryVerificationError, match="filesystem walk"):
        _iter_repo_text(root)


def test_launchd_probe_includes_loaded_unrelated_hermes_agent_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = subprocess.CompletedProcess(
        args=["launchctl", "list"],
        returncode=0,
        stdout=(
            "4242\t0\tai.hermes.gateway\n"
            "-\t0\tcom.valuehire.outstanding-news\n"
            "-\t0\tcom.example.unrelated\n"
        ),
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)

    rows, status = _probe_launchd()

    assert status == "ok"
    assert rows == (
        {"label": "ai.hermes.gateway", "pid": 4242},
        {"label": "com.valuehire.outstanding-news", "pid": 0},
    )


def test_cron_path_parser_keeps_real_paths_without_path_environment_blob(
    tmp_path: Path,
) -> None:
    root = tmp_path / "valuehire_v4"
    command = (
        "PATH=/usr/local/bin:/usr/bin /usr/bin/env "
        f"'{root}/tools/hermes-agent/hermes gateway.sh' "
        ">> /tmp/hermes-gateway.log"
    )

    refs = _known_path_refs(command, (root,))

    assert "/usr/local/bin:/usr/bin" not in refs
    assert "/usr/bin/env" not in refs
    assert str(root) in refs
    assert f"{root}/tools/hermes-agent/hermes gateway.sh" in refs
    assert "/tmp/hermes-gateway.log" in refs


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
        if url.endswith("/users/@me/guilds"):
            return [{"id": "777", "name": "must-not-be-retained"}]
        if url.endswith("/applications/999/commands"):
            return [{"id": "123", "name": "aisearch", "type": 1}]
        if url.endswith("/applications/999/guilds/777/commands"):
            return [{"id": "456", "name": "fleet-run", "type": 1}]
        raise AssertionError(url)

    monkeypatch.setattr(
        "tools.hermes_retirement.inventory._discord_get", fake_get
    )

    commands, status = _probe_discord_commands(config)

    assert status == {
        "status": "ok",
        "bot_id": "999",
        "guild_count": 1,
        "scope_count": 2,
    }
    assert commands == (
        {"id": "123", "name": "aisearch", "type": 1, "scope": "global"},
        {"id": "456", "name": "fleet-run", "type": 1, "scope": "guild:777"},
    )
    assert calls == [
        "https://discord.com/api/v10/oauth2/applications/@me",
        "https://discord.com/api/v10/users/@me/guilds",
        "https://discord.com/api/v10/applications/999/commands",
        "https://discord.com/api/v10/applications/999/guilds/777/commands",
    ]
