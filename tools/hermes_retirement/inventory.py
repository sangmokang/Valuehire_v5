"""HR-0 Hermes dependency inventory.

This module is intentionally read-only with respect to Hermes, launchd, Discord,
and both repositories.  It may write only the requested secret-free inventory
artifact after verification succeeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "hermes-retirement-inventory/v1"
CLASSIFICATIONS = frozenset({"live caller", "historical-only", "removable"})
EXPECTED_STATUSES = frozenset({"present", "missing", "symlink"})

REFERENCE_TERMS = (
    "hermes_fleet_bridge",
    "hermes_position_context",
    "discord_command_listener",
    "tools/hermes-agent",
    "ops/hermes-plugin",
    "valuehire_fleet",
    "vh_code",
    "vh_skill_run",
    "ai.hermes.gateway",
    ".hermes/plugins",
)

TEXT_SUFFIXES = frozenset(
    {
        "",
        ".cjs",
        ".html",
        ".js",
        ".json",
        ".jsonl",
        ".md",
        ".mjs",
        ".plist",
        ".py",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)

SKIP_REPO_DIRS = frozenset(
    {
        ".git",
        ".next",
        ".venv",
        ".venv-playwright",
        "artifacts",
        "node_modules",
    }
)

OPAQUE_HOME_DIRS = frozenset({"hermes-agent", "lsp", "skills"})

SECRET_NAME_RE = re.compile(
    r"(^\.env(?:\.|$)|auth|cookie|credential|password|secret|token)", re.IGNORECASE
)
HISTORICAL_NAME_RE = re.compile(
    r"(\.bak(?:\.|$)|\.log$|history|snapshot|cache|\.pyc$)", re.IGNORECASE
)
PATH_RE = re.compile(r"/(?:[^\s;|&\"']+)")


class InventoryVerificationError(RuntimeError):
    """Raised when an HR-0 inventory cannot prove complete classification."""


@dataclass(frozen=True)
class InventoryConfig:
    v4_root: Path
    v5_root: Path
    hermes_home: Path
    launch_agents_dir: Path
    expected_paths: tuple[Path, ...]
    generated_at: str | None = None


@dataclass(frozen=True)
class RuntimeProbe:
    processes: tuple[Mapping[str, object], ...] = field(default_factory=tuple)
    launchd: tuple[Mapping[str, object], ...] = field(default_factory=tuple)
    cron: tuple[Mapping[str, object], ...] = field(default_factory=tuple)
    discord_commands: tuple[Mapping[str, object], ...] = field(default_factory=tuple)
    discord_probe: Mapping[str, object] = field(
        default_factory=lambda: {"status": "unavailable", "reason": "not probed"}
    )


def _absolute(path: Path | str) -> str:
    return os.path.abspath(os.fspath(path))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _metadata_fingerprint(path: Path) -> str:
    info = path.lstat()
    payload = "\0".join(
        (
            _absolute(path),
            str(stat.S_IFMT(info.st_mode)),
            str(stat.S_IMODE(info.st_mode)),
            str(info.st_size),
            str(info.st_mtime_ns),
        )
    )
    return hashlib.sha256(payload.encode("utf-8", "surrogateescape")).hexdigest()


def _tree_metadata(path: Path) -> tuple[int, str]:
    rows: list[str] = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames.sort()
        filenames.sort()
        current = Path(dirpath)
        for name in [*dirnames, *filenames]:
            entry = current / name
            try:
                info = entry.lstat()
            except OSError as error:
                rows.append(f"{entry.relative_to(path)}\0ERROR:{type(error).__name__}")
                continue
            count += 1
            rows.append(
                "\0".join(
                    (
                        os.fspath(entry.relative_to(path)),
                        str(stat.S_IFMT(info.st_mode)),
                        str(info.st_size),
                        str(info.st_mtime_ns),
                    )
                )
            )
    digest = hashlib.sha256("\n".join(rows).encode("utf-8", "surrogateescape"))
    return count, digest.hexdigest()


def _is_historical_repo_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    if parts & {"docs", "tests", "test", "__pycache__", ".harness", ".omc"}:
        return True
    return path.name.lower() == "readme.md" or bool(HISTORICAL_NAME_RE.search(path.name))


def _is_historical_home_path(path: Path) -> bool:
    relative = os.fspath(path).lower()
    return bool(HISTORICAL_NAME_RE.search(path.name)) or any(
        marker in relative
        for marker in ("/logs/", "/cache/", "/audio_cache/", "/image_cache/", "/images/")
    )


def _is_sensitive_path(path: Path, hermes_home: Path) -> bool:
    if _is_relative_to(path, hermes_home):
        return True
    return bool(SECRET_NAME_RE.search(path.name))


def _iter_repo_text(root: Path) -> dict[Path, str]:
    corpus: dict[Path, str] = {}
    if not root.is_dir():
        return corpus
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_REPO_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if SECRET_NAME_RE.search(path.name):
                continue
            try:
                if path.lstat().st_size > 2_000_000:
                    continue
                corpus[path] = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
    return corpus


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_symlink() or root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept: list[str] = []
        for name in sorted(dirnames):
            child = current / name
            if child.is_symlink():
                yield child
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            yield current / name


def _iter_home_items(root: Path) -> Iterable[tuple[Path, bool]]:
    """Yield (path, opaque_directory) without following symlinks."""
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept: list[str] = []
        for name in sorted(dirnames):
            child = current / name
            if child.is_symlink():
                yield child, False
            elif current == root and name in OPAQUE_HOME_DIRS:
                yield child, True
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            yield current / name, False


def _caller_tokens(path: Path, root: Path | None) -> tuple[str, ...]:
    tokens: set[str] = set()
    name = path.name
    stem = path.stem
    if "hermes" in name.lower() or name in {
        "discord_command_listener.py",
        "valuehire-outstanding-news.sh",
        "valuehire-position-priority.sh",
    }:
        tokens.add(name)
        tokens.add(stem)
    if root is not None and _is_relative_to(path, root):
        relative = path.relative_to(root).as_posix()
        tokens.add(relative)
        if relative.startswith("ops/hermes-plugin/"):
            tokens.update({"ops/hermes-plugin", "valuehire_fleet"})
    if "valuehire_fleet" in path.parts:
        tokens.add("valuehire_fleet")
    return tuple(sorted((token for token in tokens if len(token) >= 4), key=len, reverse=True))


def _find_callers(
    path: Path,
    corpus: Mapping[Path, str],
    roots: Sequence[Path],
    cron: Sequence[Mapping[str, object]],
) -> list[str]:
    root = next((candidate for candidate in roots if _is_relative_to(path, candidate)), None)
    tokens = _caller_tokens(path, root)
    callers: set[str] = set()
    if tokens:
        for caller_path, text in corpus.items():
            if caller_path == path:
                continue
            if any(token in text for token in tokens):
                callers.add(_absolute(caller_path))
    wanted = _absolute(path)
    for entry in cron:
        refs = {str(value) for value in entry.get("path_refs", [])}
        if wanted in refs:
            callers.add(f"crontab:{entry.get('line', '?')}")
    return sorted(callers)


def _repo_item(
    path: Path,
    *,
    callers: list[str],
    active_plugin_roots: Sequence[Path],
    corpus: Mapping[Path, str],
    dedicated_roots: Sequence[Path],
    hermes_home: Path,
) -> dict[str, object]:
    historical = _is_historical_repo_path(path)
    in_active_plugin = any(_is_relative_to(path, root) for root in active_plugin_roots)
    production_callers = [
        caller
        for caller in callers
        if caller.startswith("crontab:") or not _is_historical_repo_path(Path(caller))
    ]
    in_dedicated = any(_is_relative_to(path, root) for root in dedicated_roots)
    text = corpus.get(path, "")
    production_reference = (
        not historical
        and not in_dedicated
        and any(term.lower() in text.lower() for term in REFERENCE_TERMS)
    )
    if historical:
        classification = "historical-only"
        reason = "documentation, test, cache, or historical evidence"
    elif in_active_plugin:
        classification = "live caller"
        reason = "enabled ~/.hermes plugin symlink resolves into this runtime tree"
    elif production_callers or production_reference:
        classification = "live caller"
        reason = "production code, launchd, or cron still references this item"
    else:
        classification = "removable"
        reason = "dedicated Hermes item has no non-historical caller"
    item: dict[str, object] = {
        "path": _absolute(path),
        "kind": "symlink" if path.is_symlink() else "file",
        "classification": classification,
        "move_first": classification == "live caller",
        "callers": callers,
        "reason": reason,
        "sensitive": _is_sensitive_path(path, hermes_home),
        "metadata_sha256": _metadata_fingerprint(path),
    }
    if path.is_symlink():
        item["symlink_target"] = _absolute(path.resolve(strict=False))
    return item


def _home_item(
    path: Path,
    *,
    opaque: bool,
    gateway_live: bool,
    process_callers: Sequence[str],
    hermes_home: Path,
) -> dict[str, object]:
    historical = _is_historical_home_path(path)
    if historical:
        classification = "historical-only"
        reason = "Hermes log, backup, cache, or historical state"
        callers: list[str] = []
    elif gateway_live:
        classification = "live caller"
        reason = "active Hermes gateway may read this runtime state"
        callers = list(process_callers) or ["launchd:ai.hermes.gateway"]
    else:
        classification = "removable"
        reason = "Hermes runtime state with no active gateway caller"
        callers = []
    kind = "opaque-directory" if opaque else ("symlink" if path.is_symlink() else "file")
    item: dict[str, object] = {
        "path": _absolute(path),
        "kind": kind,
        "classification": classification,
        "move_first": classification == "live caller",
        "callers": callers,
        "reason": reason,
        "sensitive": _is_sensitive_path(path, hermes_home),
        "metadata_sha256": _metadata_fingerprint(path),
    }
    if opaque:
        count, digest = _tree_metadata(path)
        item["descendant_count"] = count
        item["tree_metadata_sha256"] = digest
    if path.is_symlink():
        item["symlink_target"] = _absolute(path.resolve(strict=False))
    return item


def _relevant_launch_agents(directory: Path) -> Iterable[tuple[Path, str]]:
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.plist")):
        try:
            payload = plistlib.loads(path.read_bytes())
        except (OSError, plistlib.InvalidFileException):
            continue
        if not isinstance(payload, Mapping):
            continue
        label = str(payload.get("Label", ""))
        arguments = payload.get("ProgramArguments", [])
        argument_text = "\n".join(str(value) for value in arguments)
        searchable = f"{label}\n{argument_text}".lower()
        if not any(
            marker in searchable
            for marker in ("hermes", "tools/hermes-agent", "outstanding")
        ):
            continue
        yield path, label


def _launch_agent_item(
    path: Path,
    *,
    label: str,
    loaded_labels: set[str],
) -> dict[str, object]:
    loaded = label in loaded_labels
    return {
        "path": _absolute(path),
        "kind": "symlink" if path.is_symlink() else "file",
        "classification": "live caller",
        "move_first": True,
        "callers": [
            f"launchd:{label}" if loaded else f"launchd-install:{label or path.stem}"
        ],
        "reason": (
            "launchd label is currently loaded"
            if loaded
            else "installed launchd activation surface can restart on login"
        ),
        "sensitive": True,
        "metadata_sha256": _metadata_fingerprint(path),
        "label": label,
    }


def _sanitize_probe(probe: RuntimeProbe) -> dict[str, object]:
    processes = []
    for record in probe.processes:
        processes.append(
            {
                "pid": int(record.get("pid", 0)),
                "ppid": int(record.get("ppid", 0)),
                "executable": str(record.get("executable", "")),
                "path_refs": [str(value) for value in record.get("path_refs", [])],
                "command_fingerprint": str(record.get("command_fingerprint", "")),
            }
        )
    launchd = [
        {"label": str(row.get("label", "")), "pid": int(row.get("pid", 0))}
        for row in probe.launchd
    ]
    cron = [
        {
            "line": int(row.get("line", 0)),
            "fingerprint": str(row.get("fingerprint", "")),
            "path_refs": [str(value) for value in row.get("path_refs", [])],
        }
        for row in probe.cron
    ]
    commands = [
        {
            "id": str(row.get("id", "")),
            "name": str(row.get("name", "")),
            "type": int(row.get("type", 0)),
            "scope": str(row.get("scope", "")),
        }
        for row in probe.discord_commands
    ]
    allowed_probe_keys = {"status", "bot_id", "error_kind", "http_status", "scope_count"}
    discord_probe = {
        key: value
        for key, value in probe.discord_probe.items()
        if key in allowed_probe_keys and isinstance(value, (str, int, bool))
    }
    return {
        "processes": sorted(processes, key=lambda row: row["pid"]),
        "launchd": sorted(launchd, key=lambda row: row["label"]),
        "cron": sorted(cron, key=lambda row: row["line"]),
        "discord_commands": sorted(
            commands, key=lambda row: (row["scope"], row["name"], row["id"])
        ),
        "discord_probe": discord_probe,
    }


def build_inventory(config: InventoryConfig, probe: RuntimeProbe) -> dict[str, object]:
    """Build a secret-free inventory without mutating any inspected runtime."""
    v4_root = Path(config.v4_root).absolute()
    v5_root = Path(config.v5_root).absolute()
    hermes_home = Path(config.hermes_home).absolute()
    roots = (v4_root, v5_root)
    runtime = _sanitize_probe(probe)
    process_callers = [
        f"process:{row['pid']}:{row['executable']}" for row in runtime["processes"]
    ]
    gateway_live = bool(process_callers) or any(
        row["label"] == "ai.hermes.gateway" and row["pid"] > 0
        for row in runtime["launchd"]
    )

    plugin_dir = hermes_home / "plugins"
    active_plugin_roots: list[Path] = []
    if plugin_dir.is_dir():
        for entry in plugin_dir.iterdir():
            if entry.is_symlink():
                target = entry.resolve(strict=False)
                if target.exists():
                    active_plugin_roots.append(target)

    corpus = {**_iter_repo_text(v4_root), **_iter_repo_text(v5_root)}
    dedicated_roots = (
        v4_root / "tools/hermes-agent",
        v5_root / "ops/hermes-plugin",
    )
    explicit_files = (
        v5_root / "tools/multi_position_sourcing/hermes_fleet_bridge.py",
        v5_root / "tools/multi_position_sourcing/hermes_position_context.py",
        v5_root / "scripts/discord_command_listener.py",
    )

    candidate_paths: set[Path] = set()
    for root in dedicated_roots:
        candidate_paths.update(_iter_files(root))
    candidate_paths.update(path for path in explicit_files if path.exists() or path.is_symlink())
    for path, text in corpus.items():
        if "hermes" in _absolute(path).lower() or any(
            term.lower() in text.lower() for term in REFERENCE_TERMS
        ):
            candidate_paths.add(path)
    for root in active_plugin_roots:
        candidate_paths.update(_iter_files(root))

    items: dict[str, dict[str, object]] = {}
    for path in sorted(candidate_paths, key=_absolute):
        try:
            callers = _find_callers(path, corpus, roots, probe.cron)
            item = _repo_item(
                path,
                callers=callers,
                active_plugin_roots=active_plugin_roots,
                corpus=corpus,
                dedicated_roots=dedicated_roots,
                hermes_home=hermes_home,
            )
        except OSError:
            continue
        items[item["path"]] = item

    inherited_count = 0
    if hermes_home.is_dir():
        for path, opaque in _iter_home_items(hermes_home):
            try:
                item = _home_item(
                    path,
                    opaque=opaque,
                    gateway_live=gateway_live,
                    process_callers=process_callers,
                    hermes_home=hermes_home,
                )
            except OSError:
                continue
            if opaque:
                inherited_count += int(item.get("descendant_count", 0))
            items[item["path"]] = item

    loaded_labels = {str(row["label"]) for row in runtime["launchd"]}
    for path, label in _relevant_launch_agents(Path(config.launch_agents_dir).absolute()):
        try:
            item = _launch_agent_item(
                path,
                label=label,
                loaded_labels=loaded_labels,
            )
        except OSError:
            continue
        items[item["path"]] = item

    # Enabled plugin symlink targets are first-class live runtime trees even when
    # they reside outside v4/v5 (as observed on the owner machine).
    for root in active_plugin_roots:
        for path in _iter_files(root):
            key = _absolute(path)
            if key in items:
                continue
            try:
                item = _repo_item(
                    path,
                    callers=[f"plugin-symlink:{_absolute(plugin_dir)}"],
                    active_plugin_roots=active_plugin_roots,
                    corpus=corpus,
                    dedicated_roots=dedicated_roots,
                    hermes_home=hermes_home,
                )
            except OSError:
                continue
            items[key] = item

    expected_paths = []
    for path in config.expected_paths:
        candidate = Path(path).absolute()
        if candidate.is_symlink():
            status_value = "symlink"
            kind_value = "symlink"
        elif candidate.exists():
            status_value = "present"
            kind_value = "directory" if candidate.is_dir() else "file"
        else:
            status_value = "missing"
            kind_value = "missing"
        expected_paths.append(
            {"path": _absolute(candidate), "status": status_value, "kind": kind_value}
        )

    classifications = {name: 0 for name in sorted(CLASSIFICATIONS)}
    for item in items.values():
        classification = str(item["classification"])
        if classification in classifications:
            classifications[classification] += 1
    unknown_count = sum(
        1 for item in items.values() if item.get("classification") not in CLASSIFICATIONS
    )
    generated_at = config.generated_at or datetime.now(timezone.utc).isoformat()
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "roots_scanned": [
            _absolute(v4_root),
            _absolute(v5_root),
            _absolute(hermes_home),
            _absolute(config.launch_agents_dir),
        ],
        "expected_paths": expected_paths,
        "runtime": runtime,
        "items": [items[key] for key in sorted(items)],
        "coverage": {
            "explicit_items": len(items),
            "inherited_items": inherited_count,
            "opaque_directories": sum(
                1 for item in items.values() if item.get("kind") == "opaque-directory"
            ),
        },
        "summary": {
            "item_count": len(items),
            "unknown_count": unknown_count,
            "classifications": classifications,
            "move_first_count": sum(
                1 for item in items.values() if item.get("move_first") is True
            ),
        },
    }
    return payload


def verify_inventory(inventory: Mapping[str, object]) -> None:
    errors: list[str] = []
    if inventory.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version mismatch")
    raw_items = inventory.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        errors.append("items missing or empty")
        raw_items = []
    paths: set[str] = set()
    unknown_count = 0
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, Mapping):
            errors.append(f"item {index} is not an object")
            continue
        path = str(raw_item.get("path", ""))
        if not path or path in paths:
            errors.append(f"item path missing or duplicate: {path!r}")
        paths.add(path)
        classification = raw_item.get("classification")
        if classification not in CLASSIFICATIONS:
            unknown_count += 1
            errors.append(f"UNKNOWN classification: {path}")
        if classification == "live caller" and raw_item.get("move_first") is not True:
            errors.append(f"live caller lacks move_first: {path}")
        if any(key in raw_item for key in ("raw", "content", "secret_value", "command")):
            errors.append(f"secret-bearing field forbidden: {path}")
    summary = inventory.get("summary")
    if not isinstance(summary, Mapping):
        errors.append("summary missing")
    else:
        if summary.get("item_count") != len(raw_items):
            errors.append("summary item_count mismatch")
        if summary.get("unknown_count") != unknown_count or unknown_count:
            errors.append(f"UNKNOWN count must be zero, got {unknown_count}")
    expected = inventory.get("expected_paths")
    if not isinstance(expected, list) or not expected:
        errors.append("expected paths missing")
    else:
        for row in expected:
            if not isinstance(row, Mapping) or row.get("status") not in EXPECTED_STATUSES:
                errors.append("expected path has UNKNOWN status")
                continue
            if row.get("kind") in {"file", "symlink"} and row.get("path") not in paths:
                errors.append(f"expected file lacks classification: {row.get('path')}")
    runtime = inventory.get("runtime")
    if not isinstance(runtime, Mapping):
        errors.append("runtime snapshot missing")
    else:
        for key in ("processes", "launchd", "cron", "discord_commands", "discord_probe"):
            if key not in runtime:
                errors.append(f"runtime section missing: {key}")
        probe = runtime.get("discord_probe")
        if not isinstance(probe, Mapping) or probe.get("status") != "ok":
            errors.append("live Discord command probe did not succeed")
    if errors:
        raise InventoryVerificationError("; ".join(errors))


def _command_fingerprint(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8", "surrogateescape")).hexdigest()


def _known_path_refs(command: str, roots: Sequence[Path]) -> list[str]:
    refs: set[str] = set()
    for root in roots:
        value = _absolute(root)
        if value in command:
            refs.add(value)
    for token in PATH_RE.findall(command):
        cleaned = token.rstrip(")]},")
        if "hermes" in cleaned.lower() or "outstanding" in cleaned.lower():
            refs.add(cleaned)
    return sorted(refs)


def _probe_processes(config: InventoryConfig) -> tuple[Mapping[str, object], ...]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,command="],
        check=False,
        capture_output=True,
        text=True,
    )
    rows = []
    ignored = {os.getpid(), os.getppid()}
    roots = (config.hermes_home, config.v4_root, config.v5_root)
    for line in result.stdout.splitlines():
        match = re.match(r"\s*(\d+)\s+(\d+)\s+(.*)", line)
        if not match:
            continue
        pid = int(match.group(1))
        command = match.group(3)
        if pid in ignored or "tools.hermes_retirement.inventory" in command:
            continue
        if "hermes" not in command.lower():
            continue
        executable = Path(command.split()[0]).name if command.split() else ""
        rows.append(
            {
                "pid": pid,
                "ppid": int(match.group(2)),
                "executable": executable,
                "path_refs": _known_path_refs(command, roots),
                "command_fingerprint": _command_fingerprint(command),
            }
        )
    return tuple(rows)


def _probe_launchd() -> tuple[Mapping[str, object], ...]:
    result = subprocess.run(
        ["launchctl", "list"], check=False, capture_output=True, text=True
    )
    rows = []
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) < 3 or "hermes" not in columns[-1].lower():
            continue
        try:
            pid = int(columns[0])
        except ValueError:
            pid = 0
        rows.append({"label": columns[-1], "pid": pid})
    return tuple(rows)


def _probe_cron(config: InventoryConfig) -> tuple[Mapping[str, object], ...]:
    result = subprocess.run(
        ["crontab", "-l"], check=False, capture_output=True, text=True
    )
    rows = []
    roots = (config.hermes_home, config.v4_root, config.v5_root)
    for line_number, line in enumerate(result.stdout.splitlines(), 1):
        if not re.search(r"(hermes|outstanding)", line, re.IGNORECASE):
            continue
        rows.append(
            {
                "line": line_number,
                "fingerprint": _command_fingerprint(line),
                "path_refs": _known_path_refs(line, roots),
                "raw_for_scan_only": line,
            }
        )
    return tuple(rows)


def _load_discord_credentials(hermes_home: Path) -> dict[str, str]:
    wanted = {"DISCORD_BOT_TOKEN", "DISCORD_CLIENT_ID", "DISCORD_GUILD_ID"}
    values = {key: os.environ[key] for key in wanted if os.environ.get(key)}
    env_path = hermes_home / ".env"
    if env_path.is_file():
        try:
            lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            lines = []
        for line in lines:
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in wanted and key not in values:
                values[key] = value.strip().strip('"').strip("'")
    return values


def _discord_get(url: str, token: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "ValueHire-Hermes-Retirement-Inventory/1",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _probe_discord_commands(
    config: InventoryConfig,
) -> tuple[tuple[Mapping[str, object], ...], Mapping[str, object]]:
    credentials = _load_discord_credentials(config.hermes_home)
    token = credentials.get("DISCORD_BOT_TOKEN", "")
    client_id = credentials.get("DISCORD_CLIENT_ID", "")
    if not token:
        return (), {"status": "error", "error_kind": "credentials_missing"}
    commands: list[Mapping[str, object]] = []
    try:
        if not client_id:
            application = _discord_get(
                "https://discord.com/api/v10/oauth2/applications/@me", token
            )
            if not isinstance(application, Mapping) or not application.get("id"):
                raise ValueError("Discord application identity is missing")
            client_id = str(application["id"])
        scopes: list[tuple[str, str]] = [
            ("global", f"https://discord.com/api/v10/applications/{client_id}/commands")
        ]
        guild_id = credentials.get("DISCORD_GUILD_ID", "")
        if guild_id:
            scopes.append(
                (
                    f"guild:{guild_id}",
                    f"https://discord.com/api/v10/applications/{client_id}/guilds/{guild_id}/commands",
                )
            )
        for scope, url in scopes:
            payload = _discord_get(url, token)
            if not isinstance(payload, list):
                raise ValueError("Discord commands payload is not a list")
            for row in payload:
                if not isinstance(row, Mapping):
                    continue
                commands.append(
                    {
                        "id": str(row.get("id", "")),
                        "name": str(row.get("name", "")),
                        "type": int(row.get("type", 0)),
                        "scope": scope,
                    }
                )
    except urllib.error.HTTPError as error:
        return (), {
            "status": "error",
            "error_kind": "HTTPError",
            "http_status": int(error.code),
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return (), {"status": "error", "error_kind": type(error).__name__}
    return tuple(commands), {
        "status": "ok",
        "bot_id": client_id,
        "scope_count": len(scopes),
    }


def probe_runtime(config: InventoryConfig) -> RuntimeProbe:
    commands, discord_probe = _probe_discord_commands(config)
    return RuntimeProbe(
        processes=_probe_processes(config),
        launchd=_probe_launchd(),
        cron=_probe_cron(config),
        discord_commands=commands,
        discord_probe=discord_probe,
    )


def _git_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", os.fspath(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else "unavailable"


def write_inventory(path: Path, inventory: Mapping[str, object]) -> None:
    verify_inventory(inventory)
    destination = Path(path).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(inventory, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.chmod(0o600)
    os.replace(temporary, destination)


def _default_config(args: argparse.Namespace) -> InventoryConfig:
    v4_root = Path(args.v4_root).absolute()
    v5_root = Path(args.v5_root).absolute()
    hermes_home = Path(args.hermes_home).expanduser().absolute()
    launch_agents = Path(args.launch_agents_dir).expanduser().absolute()
    return InventoryConfig(
        v4_root=v4_root,
        v5_root=v5_root,
        hermes_home=hermes_home,
        launch_agents_dir=launch_agents,
        expected_paths=(
            v4_root / "tools/hermes-agent",
            v5_root / "ops/hermes-plugin",
            v5_root / "tools/multi_position_sourcing/hermes_fleet_bridge.py",
            v5_root / "tools/multi_position_sourcing/hermes_position_context.py",
            v5_root / "scripts/discord_command_listener.py",
            hermes_home / "plugins",
            launch_agents / "ai.hermes.gateway.plist",
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Build and verify SOT 33 HR-0 inventory")
    parser.add_argument("--v4-root", default="/Volumes/SSD/valuehire_v4")
    parser.add_argument("--v5-root", default="/Volumes/SSD/valuehire_v5")
    parser.add_argument("--hermes-home", default=os.fspath(Path.home() / ".hermes"))
    parser.add_argument(
        "--launch-agents-dir", default=os.fspath(Path.home() / "Library/LaunchAgents")
    )
    parser.add_argument(
        "--output",
        default=os.fspath(
            repo_root / "artifacts/discord-cutover/hermes-dependency-inventory.json"
        ),
    )
    args = parser.parse_args(argv)
    config = _default_config(args)
    probe = probe_runtime(config)
    inventory = build_inventory(config, probe)
    inventory["git_sha_v4"] = _git_sha(config.v4_root)
    inventory["git_sha_v5"] = _git_sha(config.v5_root)
    inventory["scanner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    verify_inventory(inventory)
    write_inventory(Path(args.output), inventory)
    summary = inventory["summary"]
    print(
        "HR-0 inventory verified: "
        f"items={summary['item_count']} unknown={summary['unknown_count']} "
        f"move_first={summary['move_first_count']} output={_absolute(args.output)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
