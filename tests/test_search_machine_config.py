from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace

import pytest

import tools.multi_position_sourcing.search_machine as search_machine_module
from tools.multi_position_sourcing.search_machine import (
    ACTIVE_SEARCH_MACHINE_IDS,
    SearchMachineConfigError,
    get_search_machine,
    machine_env,
    validate_machine_registry,
)


def test_registered_machine_ids_are_stable_and_active_pair_is_two_nodes() -> None:
    assert ACTIVE_SEARCH_MACHINE_IDS == ("VH-SM-001", "VH-SM-002")
    assert get_search_machine("VH-SM-000").role == "compat_mac_mini"
    assert get_search_machine("VH-SM-001").label == "MacBook Pro"
    assert get_search_machine("VH-SM-002").label == "Windows PC1"


def test_rejects_unknown_machine_id() -> None:
    with pytest.raises(SearchMachineConfigError, match="unknown search machine id"):
        get_search_machine("macbook")


def test_rejects_registered_machine_id_with_surrounding_whitespace() -> None:
    with pytest.raises(SearchMachineConfigError, match="surrounding whitespace"):
        machine_env(" VH-SM-001 ")


def test_worker_env_rejects_inactive_compat_machine() -> None:
    with pytest.raises(SearchMachineConfigError, match="inactive search machine id"):
        machine_env("VH-SM-000")


def test_active_machines_have_unique_ports_and_profiles() -> None:
    validate_machine_registry()
    envs = [machine_env(machine_id) for machine_id in ACTIVE_SEARCH_MACHINE_IDS]

    seen_ports: set[str] = set()
    seen_profiles: set[str] = set()
    for env in envs:
        for key in ("SARAMIN_PORT", "JOBKOREA_PORT", "LINKEDIN_PORT"):
            assert env[key] not in seen_ports
            seen_ports.add(env[key])
        for key in ("SARAMIN_PROFILE", "JOBKOREA_PROFILE", "LINKEDIN_PROFILE"):
            assert env[key] not in seen_profiles
            seen_profiles.add(env[key])


@pytest.mark.parametrize(
    ("duplicate_field", "duplicate_value"),
    [
        ("saramin_port", get_search_machine("VH-SM-001").saramin_port),
        ("jobkorea_profile", get_search_machine("VH-SM-002").saramin_profile),
    ],
)
def test_registry_rejects_active_machine_port_or_profile_collision(
    monkeypatch: pytest.MonkeyPatch, duplicate_field: str, duplicate_value: object
) -> None:
    machines = tuple(
        replace(machine, **{duplicate_field: duplicate_value})
        if machine.machine_id == "VH-SM-002"
        else machine
        for machine in search_machine_module.SEARCH_MACHINES
    )
    monkeypatch.setattr(search_machine_module, "SEARCH_MACHINES", machines)

    with pytest.raises(SearchMachineConfigError, match="duplicate active"):
        validate_machine_registry()


def test_registry_rejects_windows_machine_with_macos_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machines = tuple(
        replace(machine, saramin_profile="$HOME/.valuehire/wrong-windows-profile")
        if machine.machine_id == "VH-SM-002"
        else machine
        for machine in search_machine_module.SEARCH_MACHINES
    )
    monkeypatch.setattr(search_machine_module, "SEARCH_MACHINES", machines)

    with pytest.raises(SearchMachineConfigError, match="Windows profile"):
        validate_machine_registry()


@pytest.mark.parametrize(
    ("machine_id", "field", "mixed_profile", "error_pattern"),
    [
        (
            "VH-SM-002",
            "saramin_profile",
            "%LOCALAPPDATA%\\Valuehire\\$HOME\\mixed",
            "Windows profile",
        ),
        (
            "VH-SM-001",
            "saramin_profile",
            "$HOME/.valuehire/C:\\Users\\mixed",
            "macOS profile",
        ),
    ],
)
def test_registry_rejects_profiles_that_mix_windows_and_macos_syntax(
    monkeypatch: pytest.MonkeyPatch,
    machine_id: str,
    field: str,
    mixed_profile: str,
    error_pattern: str,
) -> None:
    machines = tuple(
        replace(machine, **{field: mixed_profile})
        if machine.machine_id == machine_id
        else machine
        for machine in search_machine_module.SEARCH_MACHINES
    )
    monkeypatch.setattr(search_machine_module, "SEARCH_MACHINES", machines)

    with pytest.raises(SearchMachineConfigError, match=error_pattern):
        validate_machine_registry()


def test_registry_rejects_macos_case_only_profile_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = get_search_machine("VH-SM-001")
    machines = tuple(
        replace(machine, jobkorea_profile=primary.saramin_profile.upper())
        if machine.machine_id == "VH-SM-001"
        else machine
        for machine in search_machine_module.SEARCH_MACHINES
    )
    monkeypatch.setattr(search_machine_module, "SEARCH_MACHINES", machines)

    with pytest.raises(SearchMachineConfigError, match="duplicate active profile"):
        validate_machine_registry()


@pytest.mark.parametrize(
    ("machine_id", "alias_profile"),
    [
        (
            "VH-SM-001",
            "$HOME/.valuehire/portal_profiles/tmp/../saramin/default",
        ),
        (
            "VH-SM-002",
            "%LOCALAPPDATA%\\Valuehire\\portal_profiles\\sm002\\tmp\\..\\saramin",
        ),
    ],
)
def test_registry_rejects_relative_profile_aliases(
    monkeypatch: pytest.MonkeyPatch, machine_id: str, alias_profile: str
) -> None:
    machines = tuple(
        replace(machine, jobkorea_profile=alias_profile)
        if machine.machine_id == machine_id
        else machine
        for machine in search_machine_module.SEARCH_MACHINES
    )
    monkeypatch.setattr(search_machine_module, "SEARCH_MACHINES", machines)

    with pytest.raises(SearchMachineConfigError, match="relative segments"):
        validate_machine_registry()


@pytest.mark.parametrize(
    ("machine_id", "alias_profile"),
    [
        (
            "VH-SM-001",
            "$HOME/.valuehire/portal_profiles/saramin/default/",
        ),
        (
            "VH-SM-002",
            "%LOCALAPPDATA%\\Valuehire\\portal_profiles\\sm002\\saramin\\",
        ),
    ],
)
def test_registry_canonicalizes_trailing_separator_profile_aliases(
    monkeypatch: pytest.MonkeyPatch, machine_id: str, alias_profile: str
) -> None:
    machines = tuple(
        replace(machine, jobkorea_profile=alias_profile)
        if machine.machine_id == machine_id
        else machine
        for machine in search_machine_module.SEARCH_MACHINES
    )
    monkeypatch.setattr(search_machine_module, "SEARCH_MACHINES", machines)

    with pytest.raises(SearchMachineConfigError, match="duplicate active profile"):
        validate_machine_registry()


@pytest.mark.parametrize("suffix", [".", " "])
def test_registry_rejects_windows_trailing_dot_or_space_alias(
    monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    secondary = get_search_machine("VH-SM-002")
    machines = tuple(
        replace(machine, jobkorea_profile=secondary.saramin_profile + suffix)
        if machine.machine_id == "VH-SM-002"
        else machine
        for machine in search_machine_module.SEARCH_MACHINES
    )
    monkeypatch.setattr(search_machine_module, "SEARCH_MACHINES", machines)

    with pytest.raises(SearchMachineConfigError, match="dot or space"):
        validate_machine_registry()


def test_windows_pc1_uses_windows_paths_and_macbook_uses_posix_paths() -> None:
    macbook = machine_env("VH-SM-001")
    windows = machine_env("VH-SM-002")

    assert macbook["VALUEHIRE_SEARCH_MACHINE_OS"] == "macos"
    assert macbook["SARAMIN_PROFILE"] == "$HOME/.valuehire/portal_profiles/saramin/default"
    assert macbook["JOBKOREA_PROFILE"] == "$HOME/.valuehire/portal_profiles/jobkorea/default"
    assert macbook["LINKEDIN_PROFILE"] == "$HOME/.valuehire/cdp_profiles/linkedin"

    assert windows["VALUEHIRE_SEARCH_MACHINE_OS"] == "windows"
    assert windows["SARAMIN_PROFILE"].startswith("%LOCALAPPDATA%\\")


def test_cli_validate_and_env_output() -> None:
    validate = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.multi_position_sourcing.search_machine",
            "validate",
            "--machine-id",
            "VH-SM-001",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert validate.returncode == 0
    assert "VH-SM-001" in validate.stdout

    env = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.multi_position_sourcing.search_machine",
            "env",
            "--machine-id",
            "VH-SM-002",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert env.returncode == 0
    assert "VALUEHIRE_SEARCH_MACHINE_ID=VH-SM-002" in env.stdout
    env_keys = {line.split("=", 1)[0] for line in env.stdout.splitlines()}
    assert env_keys == {
        "VALUEHIRE_SEARCH_MACHINE_ID",
        "VALUEHIRE_SEARCH_MACHINE_LABEL",
        "VALUEHIRE_SEARCH_MACHINE_ROLE",
        "VALUEHIRE_SEARCH_MACHINE_OS",
        "SARAMIN_PORT",
        "JOBKOREA_PORT",
        "LINKEDIN_PORT",
        "SARAMIN_PROFILE",
        "JOBKOREA_PROFILE",
        "LINKEDIN_PROFILE",
    }
    assert not {"SECRET", "PASSWORD", "TOKEN", "API_KEY"} & {
        key.upper() for key in env_keys
    }


@pytest.mark.parametrize("bad_machine_id", [None, " ", "unknown", "VH-SM-000"])
def test_healthcheck_fails_closed_for_missing_or_invalid_machine_id(
    tmp_path, bad_machine_id: str | None
) -> None:
    env = os.environ.copy()
    if bad_machine_id is None:
        env.pop("VALUEHIRE_SEARCH_MACHINE_ID", None)
    else:
        env["VALUEHIRE_SEARCH_MACHINE_ID"] = bad_machine_id
    env["VALUEHIRE_DRY_RUN_ARTIFACT"] = str(tmp_path / "missing.json")

    result = subprocess.run(
        ["bash", "scripts/valuehire-search-healthcheck.sh"],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert result.returncode != 0
    assert "VALUEHIRE_SEARCH_MACHINE_ID is required" in result.stderr


@pytest.mark.parametrize("bad_machine_id", [None, " ", "unknown", "VH-SM-000"])
def test_search_loop_fails_closed_for_missing_or_invalid_machine_id(
    tmp_path, bad_machine_id: str | None
) -> None:
    env = os.environ.copy()
    if bad_machine_id is None:
        env.pop("VALUEHIRE_SEARCH_MACHINE_ID", None)
    else:
        env["VALUEHIRE_SEARCH_MACHINE_ID"] = bad_machine_id
    env["VALUEHIRE_REPO_DIR"] = str(os.getcwd())
    env["VALUEHIRE_ARTIFACT_DIR"] = str(tmp_path / "artifacts")
    env["VALUEHIRE_LOG_DIR"] = str(tmp_path / "logs")

    result = subprocess.run(
        ["bash", "scripts/valuehire-search-loop.sh"],
        check=False,
        text=True,
        capture_output=True,
        env=env,
        timeout=5,
    )

    assert result.returncode == 2
    assert "VALUEHIRE_SEARCH_MACHINE_ID is required" in result.stderr


def test_portal_browsers_status_uses_machine_specific_ports_and_profiles() -> None:
    result = subprocess.run(
        ["bash", "scripts/portal_browsers.sh", "status"],
        check=False,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "VALUEHIRE_SEARCH_MACHINE_ID": "VH-SM-002",
            "PATH": os.environ.get("PATH", ""),
        },
    )

    assert result.returncode == 0
    assert "saramin :9423" in result.stdout
    assert "jobkorea :9424" in result.stdout
    assert "linkedin :9425" in result.stdout


def test_portal_browsers_status_warns_without_machine_identity_but_keeps_login_launcher_alive() -> None:
    result = subprocess.run(
        ["bash", "scripts/portal_browsers.sh", "status"],
        check=False,
        text=True,
        capture_output=True,
        env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
    )

    assert result.returncode == 0
    assert "VALUEHIRE_SEARCH_MACHINE_ID is not set" in result.stderr
    assert "saramin :9223" in result.stdout


def test_portal_browsers_status_warns_on_bad_machine_id_but_keeps_login_launcher_alive() -> None:
    result = subprocess.run(
        ["bash", "scripts/portal_browsers.sh", "status"],
        check=False,
        text=True,
        capture_output=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "VALUEHIRE_SEARCH_MACHINE_ID": "bad",
        },
    )

    assert result.returncode == 0
    assert "could not be applied" in result.stderr
    assert "saramin :9223" in result.stdout


def test_launchd_portal_browsers_wires_machine_id() -> None:
    text = open("scripts/launchd/com.valuehire.portal-browsers.plist", encoding="utf-8").read()

    assert "VALUEHIRE_SEARCH_MACHINE_ID" in text
    assert "VH-SM-001" in text
