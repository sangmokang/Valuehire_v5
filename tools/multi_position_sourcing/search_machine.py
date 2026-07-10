"""Search machine registry and startup contract.

This module is intentionally local-only: it validates which physical computer is
allowed to run a Valuehire search worker and renders non-secret environment
variables for launchd or Windows Task Scheduler.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal


MachineOS = Literal["macos", "windows"]


class SearchMachineConfigError(ValueError):
    """Raised when a search worker starts without a known machine identity."""


@dataclass(frozen=True)
class SearchMachine:
    machine_id: str
    label: str
    role: str
    os: MachineOS
    active: bool
    saramin_port: int
    jobkorea_port: int
    linkedin_port: int
    saramin_profile: str
    jobkorea_profile: str
    linkedin_profile: str

    def profile(self, channel: str) -> str:
        if channel == "saramin":
            return self.saramin_profile
        if channel == "jobkorea":
            return self.jobkorea_profile
        if channel == "linkedin":
            return self.linkedin_profile
        raise SearchMachineConfigError(f"unknown portal channel: {channel}")


SEARCH_MACHINES: tuple[SearchMachine, ...] = (
    SearchMachine(
        machine_id="VH-SM-000",
        label="Mac mini",
        role="compat_mac_mini",
        os="macos",
        active=False,
        saramin_port=9223,
        jobkorea_port=9224,
        linkedin_port=9225,
        saramin_profile="$HOME/.valuehire/portal_profiles/saramin/default",
        jobkorea_profile="$HOME/.valuehire/portal_profiles/jobkorea/default",
        linkedin_profile="$HOME/.valuehire/cdp_profiles/linkedin",
    ),
    SearchMachine(
        machine_id="VH-SM-001",
        label="MacBook Pro",
        role="primary_search_worker",
        os="macos",
        active=True,
        saramin_port=9223,
        jobkorea_port=9224,
        linkedin_port=9225,
        saramin_profile="$HOME/.valuehire/portal_profiles/saramin/default",
        jobkorea_profile="$HOME/.valuehire/portal_profiles/jobkorea/default",
        linkedin_profile="$HOME/.valuehire/cdp_profiles/linkedin",
    ),
    SearchMachine(
        machine_id="VH-SM-002",
        label="Windows PC1",
        role="secondary_search_worker",
        os="windows",
        active=True,
        saramin_port=9423,
        jobkorea_port=9424,
        linkedin_port=9425,
        saramin_profile="%LOCALAPPDATA%\\Valuehire\\portal_profiles\\sm002\\saramin",
        jobkorea_profile="%LOCALAPPDATA%\\Valuehire\\portal_profiles\\sm002\\jobkorea",
        linkedin_profile="%LOCALAPPDATA%\\Valuehire\\portal_profiles\\sm002\\linkedin",
    ),
)

ACTIVE_SEARCH_MACHINE_IDS = tuple(m.machine_id for m in SEARCH_MACHINES if m.active)


def get_search_machine(machine_id: str) -> SearchMachine:
    normalized = machine_id.strip()
    if normalized != machine_id:
        raise SearchMachineConfigError(
            f"search machine id must not contain surrounding whitespace: {machine_id!r}"
        )
    for machine in SEARCH_MACHINES:
        if machine.machine_id == normalized:
            return machine
    known = ", ".join(m.machine_id for m in SEARCH_MACHINES)
    raise SearchMachineConfigError(f"unknown search machine id: {machine_id!r}; known: {known}")


def require_search_machine(machine_id: str | None) -> SearchMachine:
    if not machine_id or not machine_id.strip():
        raise SearchMachineConfigError(
            "VALUEHIRE_SEARCH_MACHINE_ID is required; use one of: "
            + ", ".join(m.machine_id for m in SEARCH_MACHINES)
        )
    machine = get_search_machine(machine_id)
    if not machine.active:
        raise SearchMachineConfigError(f"inactive search machine id: {machine.machine_id}")
    return machine


def machine_env(machine_id: str) -> dict[str, str]:
    machine = require_search_machine(machine_id)
    return {
        "VALUEHIRE_SEARCH_MACHINE_ID": machine.machine_id,
        "VALUEHIRE_SEARCH_MACHINE_LABEL": machine.label,
        "VALUEHIRE_SEARCH_MACHINE_ROLE": machine.role,
        "VALUEHIRE_SEARCH_MACHINE_OS": machine.os,
        "SARAMIN_PORT": str(machine.saramin_port),
        "JOBKOREA_PORT": str(machine.jobkorea_port),
        "LINKEDIN_PORT": str(machine.linkedin_port),
        "SARAMIN_PROFILE": machine.profile("saramin"),
        "JOBKOREA_PROFILE": machine.profile("jobkorea"),
        "LINKEDIN_PROFILE": machine.profile("linkedin"),
    }


def validate_machine_registry() -> None:
    ids: set[str] = set()
    ports: set[int] = set()
    profiles: set[str] = set()
    active = [m for m in SEARCH_MACHINES if m.active]
    if tuple(m.machine_id for m in active) != ("VH-SM-001", "VH-SM-002"):
        raise SearchMachineConfigError("active search pair must be VH-SM-001 + VH-SM-002")

    for machine in SEARCH_MACHINES:
        if machine.machine_id in ids:
            raise SearchMachineConfigError(f"duplicate machine id: {machine.machine_id}")
        ids.add(machine.machine_id)
        for port in (machine.saramin_port, machine.jobkorea_port, machine.linkedin_port):
            if not 1024 <= port <= 65535:
                raise SearchMachineConfigError(f"invalid port for {machine.machine_id}: {port}")
            if machine.active and port in ports:
                raise SearchMachineConfigError(f"duplicate active CDP port: {port}")
            if machine.active:
                ports.add(port)
        for profile in (machine.profile("saramin"), machine.profile("jobkorea"), machine.profile("linkedin")):
            path_separator = "\\" if machine.os == "windows" else "/"
            if any(part in {".", ".."} for part in profile.split(path_separator)):
                raise SearchMachineConfigError(
                    f"profile path must not contain relative segments for {machine.machine_id}: {profile}"
                )
            if machine.os == "windows" and any(
                part.rstrip(" .") != part for part in PureWindowsPath(profile).parts
            ):
                raise SearchMachineConfigError(
                    f"Windows profile components must not end with dot or space for {machine.machine_id}: {profile}"
                )
            if machine.os == "macos" and (
                not profile.startswith("$HOME/")
                or "\\" in profile
                or "%LOCALAPPDATA%" in profile.upper()
            ):
                raise SearchMachineConfigError(
                    f"macOS profile must use an unmixed $HOME path for {machine.machine_id}: {profile}"
                )
            if machine.os == "windows" and (
                not profile.upper().startswith("%LOCALAPPDATA%\\")
                or "/" in profile
                or "$HOME" in profile.upper()
            ):
                raise SearchMachineConfigError(
                    f"Windows profile must use an unmixed %LOCALAPPDATA% path for {machine.machine_id}: {profile}"
                )
            path_type = PureWindowsPath if machine.os == "windows" else PurePosixPath
            normalized_profile = str(path_type(profile)).casefold()
            if machine.active and normalized_profile in profiles:
                raise SearchMachineConfigError(f"duplicate active profile path: {profile}")
            if machine.active:
                profiles.add(normalized_profile)


def _print_env(machine_id: str) -> None:
    for key, value in machine_env(machine_id).items():
        print(f"{key}={value}")


def _validate(machine_id: str) -> None:
    validate_machine_registry()
    machine = require_search_machine(machine_id)
    print(f"ok: {machine.machine_id} {machine.label} ({machine.role}, {machine.os})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Valuehire search machine identity.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "env"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--machine-id", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            _validate(args.machine_id)
        elif args.command == "env":
            validate_machine_registry()
            _print_env(args.machine_id)
        else:  # pragma: no cover - argparse prevents this.
            raise SearchMachineConfigError(f"unsupported command: {args.command}")
    except SearchMachineConfigError as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
