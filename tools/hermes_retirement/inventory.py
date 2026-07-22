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
import shlex
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
STATIC_EXPECTED_ROLES = (
    "v4_hermes_agent",
    "v5_hermes_plugin",
    "hermes_fleet_bridge",
    "hermes_position_context",
    "discord_command_listener",
    "hermes_home",
    "hermes_plugins",
    "hermes_gateway_plist",
)
PROBE_NAMES = frozenset({"cron", "discord", "launchd", "processes"})
ITEM_REASONS = frozenset(
    {
        "active Hermes gateway may read this runtime state",
        "active process references this path",
        "active runtime configuration references this path",
        "active crontab references this path",
        "dedicated Hermes item has no non-historical caller",
        "documentation, test, cache, or historical evidence",
        "enabled ~/.hermes plugin symlink resolves into this runtime tree",
        "Hermes log, backup, cache, or historical state",
        "Hermes runtime state with no active gateway caller",
        "installed launchd activation surface can restart on login",
        "launchd label is currently loaded",
        "production code, launchd, or cron still references this item",
    }
)

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


def _raise_walk_error(error: OSError) -> None:
    raise InventoryVerificationError(
        f"filesystem walk failed: {type(error).__name__}"
    ) from error


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
    probe_status: Mapping[str, str] = field(
        default_factory=lambda: {
            "cron": "ok",
            "discord": "ok",
            "launchd": "ok",
            "processes": "ok",
        }
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
    for dirpath, dirnames, filenames in os.walk(
        path, followlinks=False, onerror=_raise_walk_error
    ):
        dirnames.sort()
        filenames.sort()
        current = Path(dirpath)
        for name in [*dirnames, *filenames]:
            entry = current / name
            try:
                info = entry.lstat()
            except OSError as error:
                raise InventoryVerificationError(
                    f"metadata scan failed: {type(error).__name__}"
                ) from error
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


def _tree_identity(path: Path) -> tuple[int, str]:
    rows: list[str] = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(
        path, followlinks=False, onerror=_raise_walk_error
    ):
        dirnames.sort()
        filenames.sort()
        current = Path(dirpath)
        for name in [*dirnames, *filenames]:
            entry = current / name
            try:
                info = entry.lstat()
            except OSError as error:
                raise InventoryVerificationError(
                    f"identity scan failed: {type(error).__name__}"
                ) from error
            count += 1
            target = (
                _absolute(entry.resolve(strict=False)) if entry.is_symlink() else ""
            )
            rows.append(
                "\0".join(
                    (
                        os.fspath(entry.relative_to(path)),
                        str(stat.S_IFMT(info.st_mode)),
                        target,
                    )
                )
            )
    return count, _evidence_digest(rows)


def _is_historical_repo_path(path: Path) -> bool:
    lowered = tuple(part.lower() for part in path.parts)
    parts = set(lowered)
    if parts & {"docs", "tests", "test", "__pycache__", ".harness", ".omc"}:
        return True
    joined = "/".join(lowered)
    if any(
        marker in joined
        for marker in (
            "/.claude/worktrees/",
            "/.hermes/plans/",
            "/.omx/logs/",
            "/data/outstanding-news-runs/",
            "/worktrees/",
        )
    ):
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
    for dirpath, dirnames, filenames in os.walk(
        root, followlinks=False, onerror=_raise_walk_error
    ):
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
            except OSError as error:
                raise InventoryVerificationError(
                    f"repository scan failed: {type(error).__name__}"
                ) from error
    return corpus


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_symlink() or root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(
        root, followlinks=False, onerror=_raise_walk_error
    ):
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
    for dirpath, dirnames, filenames in os.walk(
        root, followlinks=False, onerror=_raise_walk_error
    ):
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
    active_plugin_callers: Mapping[Path, str],
    corpus: Mapping[Path, str],
    dedicated_roots: Sequence[Path],
    hermes_home: Path,
) -> dict[str, object]:
    historical = _is_historical_repo_path(path)
    in_active_plugin = any(_is_relative_to(path, root) for root in active_plugin_roots)
    effective_callers = set(callers)
    for root, caller in active_plugin_callers.items():
        if _is_relative_to(path, root):
            effective_callers.add(caller)
    production_callers = [
        caller
        for caller in effective_callers
        if caller.startswith("crontab:") or not _is_historical_repo_path(Path(caller))
    ]
    in_dedicated = any(_is_relative_to(path, root) for root in dedicated_roots)
    text = corpus.get(path, "")
    production_reference = (
        not historical
        and not in_dedicated
        and any(term.lower() in text.lower() for term in REFERENCE_TERMS)
    )
    if production_reference:
        effective_callers.add("self:production-reference")
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
        "callers": sorted(effective_callers),
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
        except (OSError, plistlib.InvalidFileException) as error:
            raise InventoryVerificationError(
                f"launch agent plist scan failed: {type(error).__name__}"
            ) from error
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
            "reference_mode": str(
                row.get(
                    "reference_mode",
                    "path" if row.get("path_refs") else "text-only",
                )
            ),
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
    allowed_probe_keys = {
        "status",
        "bot_id",
        "error_kind",
        "guild_count",
        "http_status",
        "scope_count",
    }
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
        "probe_status": {
            key: str(probe.probe_status.get(key, "missing"))
            for key in sorted(PROBE_NAMES)
        },
    }


def _path_reference_item(
    path: str,
    *,
    caller: str,
    hermes_home: Path,
) -> dict[str, object]:
    return {
        "path": _absolute(path),
        "kind": "path-reference",
        "classification": "live caller",
        "move_first": True,
        "callers": [caller],
        "reason": "active runtime configuration references this path",
        "sensitive": _is_sensitive_path(Path(path), hermes_home),
        "reference_sha256": hashlib.sha256(
            _absolute(path).encode("utf-8", "surrogateescape")
        ).hexdigest(),
    }


def _evidence_digest(records: Iterable[str]) -> str:
    return hashlib.sha256(
        "\n".join(sorted(records)).encode("utf-8", "surrogateescape")
    ).hexdigest()


def _path_evidence_record(path: Path, *, opaque: bool = False) -> tuple[int, str]:
    kind = "opaque-directory" if opaque else ("symlink" if path.is_symlink() else "file")
    descendant_count = 0
    tree_sha = ""
    if opaque:
        descendant_count, tree_sha = _tree_identity(path)
    symlink_target = _absolute(path.resolve(strict=False)) if path.is_symlink() else ""
    record = "\0".join(
        (
            _absolute(path),
            kind,
            str(descendant_count),
            tree_sha,
            symlink_target,
        )
    )
    return 1 + descendant_count, record


def _observed_scope_evidence(role: str, root: Path) -> tuple[int, str]:
    candidate = Path(root).absolute()
    if not candidate.exists() and not candidate.is_symlink():
        return 0, _evidence_digest(())
    records: list[str] = []
    count = 0
    if candidate.is_file() or candidate.is_symlink():
        increment, record = _path_evidence_record(candidate)
        return increment, _evidence_digest((record,))
    entries: Iterable[tuple[Path, bool]]
    if role == "hermes_home":
        entries = _iter_home_items(candidate)
    else:
        entries = ((path, False) for path in _iter_files(candidate))
    for path, opaque in entries:
        increment, record = _path_evidence_record(path, opaque=opaque)
        count += increment
        records.append(record)
    return count, _evidence_digest(records)


def _classified_scope_evidence(
    root: Path, items: Mapping[str, Mapping[str, object]]
) -> tuple[int, str]:
    root_text = _absolute(root)
    total = 0
    records: list[str] = []
    for item in items.values():
        path_text = str(item.get("path", ""))
        if path_text != root_text and not path_text.startswith(f"{root_text}{os.sep}"):
            continue
        if item.get("kind") == "path-reference":
            continue
        total += 1
        if item.get("kind") == "opaque-directory":
            total += int(item.get("descendant_count", 0))
        records.append(
            # Scope binding uses stable topology, not mutable size/mtime.
            "\0".join(
                (
                    path_text,
                    str(item.get("kind", "")),
                    str(item.get("descendant_count", 0)),
                    (
                        _tree_identity(Path(path_text))[1]
                        if item.get("kind") == "opaque-directory"
                        else ""
                    ),
                    str(item.get("symlink_target", "")),
                )
            )
        )
    return total, _evidence_digest(records)


def _repo_candidate_paths(
    v4_root: Path,
    v5_root: Path,
    active_plugin_roots: Sequence[Path],
    corpus: Mapping[Path, str],
) -> set[Path]:
    dedicated_roots = (
        v4_root / "tools/hermes-agent",
        v5_root / "ops/hermes-plugin",
    )
    explicit_files = (
        v5_root / "tools/multi_position_sourcing/hermes_fleet_bridge.py",
        v5_root / "tools/multi_position_sourcing/hermes_position_context.py",
        v5_root / "scripts/discord_command_listener.py",
    )
    candidates: set[Path] = set()
    for root in dedicated_roots:
        candidates.update(_iter_files(root))
    candidates.update(
        path for path in explicit_files if path.exists() or path.is_symlink()
    )
    for path, text in corpus.items():
        if "hermes" in _absolute(path).lower() or any(
            term.lower() in text.lower() for term in REFERENCE_TERMS
        ):
            candidates.add(path)
    for root in active_plugin_roots:
        candidates.update(_iter_files(root))
    return candidates


def _path_set_digest(paths: Iterable[Path | str]) -> str:
    return _evidence_digest(_absolute(path) for path in paths)


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
    active_plugin_callers: dict[Path, str] = {}
    if plugin_dir.is_dir():
        for entry in plugin_dir.iterdir():
            if entry.is_symlink():
                target = entry.resolve(strict=False)
                if target.exists():
                    active_plugin_roots.append(target)
                    active_plugin_callers[target] = (
                        f"plugin-symlink:{_absolute(entry)}"
                    )

    corpus = {**_iter_repo_text(v4_root), **_iter_repo_text(v5_root)}
    caller_corpus = {
        path: text
        for path, text in corpus.items()
        if not _is_historical_repo_path(path)
    }
    dedicated_roots = (
        v4_root / "tools/hermes-agent",
        v5_root / "ops/hermes-plugin",
    )
    candidate_paths = _repo_candidate_paths(
        v4_root, v5_root, active_plugin_roots, corpus
    )

    items: dict[str, dict[str, object]] = {}
    for path in sorted(candidate_paths, key=_absolute):
        try:
            callers = _find_callers(path, caller_corpus, roots, probe.cron)
            item = _repo_item(
                path,
                callers=callers,
                active_plugin_roots=active_plugin_roots,
                active_plugin_callers=active_plugin_callers,
                corpus=corpus,
                dedicated_roots=dedicated_roots,
                hermes_home=hermes_home,
            )
        except OSError as error:
            raise InventoryVerificationError(
                f"candidate metadata scan failed: {type(error).__name__}"
            ) from error
        items[item["path"]] = item

    for row in runtime["cron"]:
        caller = f"crontab:{row['line']}"
        for reference in row["path_refs"]:
            key = _absolute(str(reference))
            if key in items:
                item = items[key]
                item["classification"] = "live caller"
                item["move_first"] = True
                item["callers"] = sorted({*item["callers"], caller})
                item["reason"] = "active crontab references this path"
            else:
                items[key] = _path_reference_item(
                    key, caller=caller, hermes_home=hermes_home
                )

    for row in runtime["processes"]:
        caller = f"process:{row['pid']}:{row['executable']}"
        for reference in row["path_refs"]:
            key = _absolute(str(reference))
            if key in items:
                item = items[key]
                item["classification"] = "live caller"
                item["move_first"] = True
                item["callers"] = sorted({*item["callers"], caller})
                item["reason"] = "active process references this path"
            else:
                items[key] = _path_reference_item(
                    key, caller=caller, hermes_home=hermes_home
                )

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
            except OSError as error:
                raise InventoryVerificationError(
                    f"Hermes home scan failed: {type(error).__name__}"
                ) from error
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
        except OSError as error:
            raise InventoryVerificationError(
                f"launch agent scan failed: {type(error).__name__}"
            ) from error
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
                    callers=[],
                    active_plugin_roots=active_plugin_roots,
                    active_plugin_callers=active_plugin_callers,
                    corpus=corpus,
                    dedicated_roots=dedicated_roots,
                    hermes_home=hermes_home,
                )
            except OSError as error:
                raise InventoryVerificationError(
                    f"active plugin scan failed: {type(error).__name__}"
                ) from error
            items[key] = item

    if len(config.expected_paths) != len(STATIC_EXPECTED_ROLES):
        raise InventoryVerificationError(
            "expected path configuration does not match required HR-0 roles"
        )
    expected_specs = list(zip(STATIC_EXPECTED_ROLES, config.expected_paths))
    for root in sorted(active_plugin_roots, key=_absolute):
        suffix = hashlib.sha256(_absolute(root).encode()).hexdigest()[:12]
        expected_specs.append((f"active_plugin_target:{suffix}", root))

    expected_paths = []
    for role, path in expected_specs:
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
        observed_count, observed_sha = _observed_scope_evidence(role, candidate)
        classified_count, classified_sha = _classified_scope_evidence(candidate, items)
        expected_paths.append(
            {
                "role": role,
                "path": _absolute(candidate),
                "status": status_value,
                "kind": kind_value,
                "observed_descendant_count": observed_count,
                "classified_descendant_count": classified_count,
                "observed_tree_sha256": observed_sha,
                "classified_path_sha256": classified_sha,
            }
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
        "git_sha_v4": _git_sha(v4_root),
        "git_sha_v5": _git_sha(v5_root),
        "scanner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "roots_scanned": {
            "hermes_home": _absolute(hermes_home),
            "launch_agents_dir": _absolute(config.launch_agents_dir),
            "v4_root": _absolute(v4_root),
            "v5_root": _absolute(v5_root),
        },
        "expected_paths": expected_paths,
        "runtime": runtime,
        "items": [items[key] for key in sorted(items)],
        "coverage": {
            "explicit_items": len(items),
            "inherited_items": inherited_count,
            "opaque_directories": sum(
                1 for item in items.values() if item.get("kind") == "opaque-directory"
            ),
            "expected_scope_count": len(expected_paths),
            "repo_candidate_count": len(candidate_paths),
            "repo_candidate_sha256": _path_set_digest(candidate_paths),
        },
        "summary": {
            "item_count": len(items),
            "unknown_count": unknown_count,
            "classifications": classifications,
            "move_first_count": sum(
                1 for item in items.values() if item.get("move_first") is True
            ),
            "runtime_counts": {
                key: len(runtime[key])
                for key in ("cron", "discord_commands", "launchd", "processes")
            },
        },
    }
    return payload


def verify_inventory(inventory: Mapping[str, object]) -> None:
    errors: list[str] = []
    top_keys = {
        "coverage",
        "expected_paths",
        "generated_at",
        "git_sha_v4",
        "git_sha_v5",
        "items",
        "roots_scanned",
        "runtime",
        "scanner_sha256",
        "schema_version",
        "summary",
    }
    actual_top_keys = set(inventory)
    if actual_top_keys != top_keys:
        errors.append(
            f"top-level schema mismatch missing={sorted(top_keys - actual_top_keys)} "
            f"extra={sorted(actual_top_keys - top_keys)}"
        )
    if inventory.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version mismatch")
    generated_at = inventory.get("generated_at")
    try:
        parsed_generated_at = datetime.fromisoformat(str(generated_at))
    except ValueError:
        errors.append("generated_at is not ISO-8601")
    else:
        if parsed_generated_at.tzinfo is None:
            errors.append("generated_at must include a timezone")
    current_scanner_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if inventory.get("scanner_sha256") != current_scanner_sha:
        errors.append("scanner_sha256 does not match the running verifier")
    for key in ("git_sha_v4", "git_sha_v5"):
        value = inventory.get(key)
        if value != "unavailable" and not (
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value)
        ):
            errors.append(f"{key} is not a git SHA")

    roots = inventory.get("roots_scanned")
    root_keys = {"hermes_home", "launch_agents_dir", "v4_root", "v5_root"}
    if not isinstance(roots, Mapping) or set(roots) != root_keys:
        errors.append("roots_scanned must contain the four exact HR-0 roots")
        roots = {}
    else:
        for key, value in roots.items():
            if not isinstance(value, str) or not os.path.isabs(value):
                errors.append(f"root is not absolute: {key}")

    raw_items = inventory.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        errors.append("items missing or empty")
        raw_items = []
    paths: set[str] = set()
    unknown_count = 0
    classification_counts = {name: 0 for name in sorted(CLASSIFICATIONS)}
    opaque_descendants = 0
    opaque_count = 0
    launchd_item_labels: set[str] = set()
    item_allowed_keys = {
        "callers",
        "classification",
        "descendant_count",
        "kind",
        "label",
        "metadata_sha256",
        "move_first",
        "path",
        "reason",
        "reference_sha256",
        "sensitive",
        "symlink_target",
        "tree_metadata_sha256",
    }
    item_required_keys = {
        "callers",
        "classification",
        "kind",
        "move_first",
        "path",
        "reason",
        "sensitive",
    }
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, Mapping):
            errors.append(f"item {index} is not an object")
            continue
        item_keys = set(raw_item)
        if not item_required_keys <= item_keys or not item_keys <= item_allowed_keys:
            errors.append(f"item schema mismatch at index {index}")
        path = str(raw_item.get("path", ""))
        if not path or not os.path.isabs(path) or path in paths:
            errors.append(f"item path missing or duplicate: {path!r}")
        paths.add(path)
        classification = raw_item.get("classification")
        if classification not in CLASSIFICATIONS:
            unknown_count += 1
            errors.append(f"UNKNOWN classification: {path}")
        else:
            classification_counts[str(classification)] += 1
        if raw_item.get("move_first") is not (classification == "live caller"):
            errors.append(f"move_first does not match classification: {path}")
        callers = raw_item.get("callers")
        if not isinstance(callers, list) or not all(
            isinstance(caller, str) and caller for caller in callers
        ):
            errors.append(f"callers must be a string array: {path}")
            callers = []
        if classification == "live caller" and not callers:
            errors.append(f"live caller has no caller evidence: {path}")
        if raw_item.get("reason") not in ITEM_REASONS:
            errors.append(f"classification reason missing: {path}")
        if not isinstance(raw_item.get("sensitive"), bool):
            errors.append(f"sensitive marker missing: {path}")
        kind = raw_item.get("kind")
        if kind not in {"file", "opaque-directory", "path-reference", "symlink"}:
            errors.append(f"unsupported item kind: {path}")
        fingerprint_key = (
            "reference_sha256" if kind == "path-reference" else "metadata_sha256"
        )
        if not isinstance(raw_item.get(fingerprint_key), str) or not re.fullmatch(
            r"[0-9a-f]{64}", str(raw_item.get(fingerprint_key, ""))
        ):
            errors.append(f"item fingerprint missing: {path}")
        if kind == "opaque-directory":
            opaque_count += 1
            descendant_count = raw_item.get("descendant_count")
            if not isinstance(descendant_count, int) or descendant_count < 0:
                errors.append(f"opaque descendant count invalid: {path}")
            else:
                opaque_descendants += descendant_count
            if not re.fullmatch(
                r"[0-9a-f]{64}", str(raw_item.get("tree_metadata_sha256", ""))
            ):
                errors.append(f"opaque tree fingerprint missing: {path}")
        if kind == "symlink" and (
            not isinstance(raw_item.get("symlink_target"), str)
            or not os.path.isabs(str(raw_item.get("symlink_target", "")))
        ):
            errors.append(f"symlink target missing: {path}")
        label = raw_item.get("label")
        if label is not None:
            if not isinstance(label, str) or not label:
                errors.append(f"launchd item label invalid: {path}")
            else:
                launchd_item_labels.add(label)

    summary = inventory.get("summary")
    summary_keys = {
        "classifications",
        "item_count",
        "move_first_count",
        "runtime_counts",
        "unknown_count",
    }
    if not isinstance(summary, Mapping) or set(summary) != summary_keys:
        errors.append("summary missing")
    else:
        if summary.get("item_count") != len(raw_items):
            errors.append("summary item_count mismatch")
        if summary.get("unknown_count") != unknown_count or unknown_count:
            errors.append(f"UNKNOWN count must be zero, got {unknown_count}")
        if summary.get("classifications") != classification_counts:
            errors.append("summary classification counts mismatch")
        move_first_count = sum(
            1
            for item in raw_items
            if isinstance(item, Mapping) and item.get("move_first") is True
        )
        if summary.get("move_first_count") != move_first_count:
            errors.append("summary move_first_count mismatch")

    expected = inventory.get("expected_paths")
    expected_by_role: dict[str, Mapping[str, object]] = {}
    active_target_paths: set[str] = set()
    if not isinstance(expected, list) or not expected:
        errors.append("expected paths missing")
        expected = []
    else:
        expected_roles: set[str] = set()
        expected_row_keys = {
            "classified_path_sha256",
            "classified_descendant_count",
            "kind",
            "observed_descendant_count",
            "observed_tree_sha256",
            "path",
            "role",
            "status",
        }
        for row in expected:
            if not isinstance(row, Mapping) or set(row) != expected_row_keys:
                errors.append("expected path schema mismatch")
                continue
            role = row.get("role")
            if not isinstance(role, str) or not role or role in expected_roles:
                errors.append(f"expected path role missing or duplicate: {role}")
                continue
            expected_roles.add(role)
            expected_by_role[role] = row
            if row.get("status") not in EXPECTED_STATUSES:
                errors.append("expected path has UNKNOWN status")
                continue
            path = row.get("path")
            if not isinstance(path, str) or not os.path.isabs(path):
                errors.append(f"expected path is not absolute: {role}")
                continue
            observed = row.get("observed_descendant_count")
            classified = row.get("classified_descendant_count")
            if not isinstance(observed, int) or observed < 1:
                errors.append(f"expected scope has no observed items: {role}")
            classified_count, classified_sha = _classified_scope_evidence(
                Path(path),
                {
                    str(item.get("path", "")): item
                    for item in raw_items
                    if isinstance(item, Mapping)
                },
            )
            try:
                observed_count, observed_sha = _observed_scope_evidence(
                    role, Path(path)
                )
            except (OSError, InventoryVerificationError) as error:
                errors.append(
                    f"filesystem observation failed for {role}: {type(error).__name__}"
                )
                observed_count, observed_sha = -1, ""
            if (
                classified != classified_count
                or observed != observed_count
                or observed != classified
                or row.get("classified_path_sha256") != classified_sha
                or row.get("observed_tree_sha256") != observed_sha
                or classified_sha != observed_sha
            ):
                errors.append(f"expected scope coverage mismatch: {role}")
            if row.get("kind") in {"file", "symlink"} and path not in paths:
                errors.append(f"expected file lacks classification: {row.get('path')}")
        missing_roles = set(STATIC_EXPECTED_ROLES) - expected_roles
        unexpected_roles = {
            role
            for role in expected_roles - set(STATIC_EXPECTED_ROLES)
            if not role.startswith("active_plugin_target:")
        }
        if missing_roles or unexpected_roles:
            errors.append(
                f"expected path roles mismatch missing={sorted(missing_roles)} "
                f"unexpected={sorted(unexpected_roles)}"
            )
        active_target_paths = {
            str(row["path"])
            for role, row in expected_by_role.items()
            if role.startswith("active_plugin_target:")
        }
        plugin_root = expected_by_role.get("hermes_plugins", {}).get("path")
        plugin_targets = {
            str(item.get("symlink_target"))
            for item in raw_items
            if isinstance(item, Mapping)
            and item.get("kind") == "symlink"
            and isinstance(plugin_root, str)
            and str(item.get("path", "")).startswith(f"{plugin_root}{os.sep}")
        }
        if not active_target_paths or active_target_paths != plugin_targets:
            errors.append("active plugin target coverage mismatch")
        if isinstance(roots, Mapping) and roots:
            path_expectations = {
                "hermes_home": roots.get("hermes_home"),
                "v4_hermes_agent": os.path.join(
                    str(roots.get("v4_root", "")), "tools", "hermes-agent"
                ),
                "v5_hermes_plugin": os.path.join(
                    str(roots.get("v5_root", "")), "ops", "hermes-plugin"
                ),
            }
            for role, wanted_path in path_expectations.items():
                if expected_by_role.get(role, {}).get("path") != wanted_path:
                    errors.append(f"root/expected path mismatch: {role}")
            gateway_path = expected_by_role.get("hermes_gateway_plist", {}).get("path")
            if isinstance(gateway_path, str) and os.path.dirname(gateway_path) != roots.get(
                "launch_agents_dir"
            ):
                errors.append("launch agent root/expected path mismatch")

    coverage = inventory.get("coverage")
    coverage_keys = {
        "expected_scope_count",
        "explicit_items",
        "inherited_items",
        "opaque_directories",
        "repo_candidate_count",
        "repo_candidate_sha256",
    }
    if not isinstance(coverage, Mapping) or set(coverage) != coverage_keys:
        errors.append("coverage schema missing or invalid")
    else:
        if coverage.get("explicit_items") != len(raw_items):
            errors.append("coverage explicit_items mismatch")
        if coverage.get("inherited_items") != opaque_descendants:
            errors.append("coverage inherited_items mismatch")
        if coverage.get("opaque_directories") != opaque_count:
            errors.append("coverage opaque_directories mismatch")
        if coverage.get("expected_scope_count") != len(expected):
            errors.append("coverage expected_scope_count mismatch")
        if isinstance(roots, Mapping) and roots and active_target_paths:
            try:
                v4_root = Path(str(roots["v4_root"]))
                v5_root = Path(str(roots["v5_root"]))
                repo_corpus = {
                    **_iter_repo_text(v4_root),
                    **_iter_repo_text(v5_root),
                }
                repo_candidates = _repo_candidate_paths(
                    v4_root,
                    v5_root,
                    tuple(Path(path) for path in sorted(active_target_paths)),
                    repo_corpus,
                )
            except (OSError, InventoryVerificationError) as error:
                errors.append(
                    f"repository candidate verification failed: {type(error).__name__}"
                )
                repo_candidates = set()
            if (
                coverage.get("repo_candidate_count") != len(repo_candidates)
                or coverage.get("repo_candidate_sha256")
                != _path_set_digest(repo_candidates)
                or not {_absolute(path) for path in repo_candidates} <= paths
            ):
                errors.append("repository candidate coverage mismatch")

    runtime = inventory.get("runtime")
    runtime_keys = {
        "cron",
        "discord_commands",
        "discord_probe",
        "launchd",
        "probe_status",
        "processes",
    }
    if not isinstance(runtime, Mapping) or set(runtime) != runtime_keys:
        errors.append("runtime snapshot missing")
    else:
        list_schemas = {
            "processes": {
                "command_fingerprint",
                "executable",
                "path_refs",
                "pid",
                "ppid",
            },
            "launchd": {"label", "pid"},
            "cron": {"fingerprint", "line", "path_refs", "reference_mode"},
            "discord_commands": {"id", "name", "scope", "type"},
        }
        for key, keys in list_schemas.items():
            rows = runtime.get(key)
            if not isinstance(rows, list):
                errors.append(f"runtime {key} must be an array")
                continue
            for index, row in enumerate(rows):
                if not isinstance(row, Mapping) or set(row) != keys:
                    errors.append(f"runtime {key}[{index}] schema mismatch")
                    continue
                if key == "processes":
                    executable = row.get("executable")
                    if (
                        not isinstance(row.get("pid"), int)
                        or row.get("pid", 0) < 1
                        or not isinstance(row.get("ppid"), int)
                        or row.get("ppid", -1) < 0
                        or not isinstance(executable, str)
                        or not re.fullmatch(r"[A-Za-z0-9._+-]+", str(executable))
                        or re.search(
                            r"token|secret|password|credential|api[_-]?key",
                            str(executable),
                            re.IGNORECASE,
                        )
                        or not re.fullmatch(
                            r"[0-9a-f]{64}", str(row.get("command_fingerprint", ""))
                        )
                    ):
                        errors.append(f"runtime processes[{index}] value invalid")
                elif key == "launchd":
                    if (
                        not isinstance(row.get("label"), str)
                        or not row.get("label")
                        or not isinstance(row.get("pid"), int)
                        or row.get("pid", -1) < 0
                    ):
                        errors.append(f"runtime launchd[{index}] value invalid")
                elif key == "cron":
                    if (
                        not isinstance(row.get("line"), int)
                        or row.get("line", 0) < 1
                        or not re.fullmatch(
                            r"[0-9a-f]{64}", str(row.get("fingerprint", ""))
                        )
                        or row.get("reference_mode") not in {"path", "text-only"}
                    ):
                        errors.append(f"runtime cron[{index}] value invalid")
                elif key == "discord_commands":
                    command_id = row.get("id")
                    command_name = row.get("name")
                    command_scope = row.get("scope")
                    if (
                        not isinstance(command_id, str)
                        or not command_id.isdigit()
                        or not isinstance(command_name, str)
                        or not re.fullmatch(r"[a-z0-9_-]{1,32}", command_name)
                        or not isinstance(row.get("type"), int)
                        or not isinstance(command_scope, str)
                        or not (
                            command_scope == "global"
                            or re.fullmatch(r"guild:[0-9]+", command_scope)
                        )
                    ):
                        errors.append(f"runtime discord_commands[{index}] value invalid")
                path_refs = row.get("path_refs")
                if key in {"processes", "cron"} and (
                    not isinstance(path_refs, list)
                    or not all(
                        isinstance(path, str) and os.path.isabs(path)
                        for path in path_refs
                    )
                ):
                    errors.append(f"runtime {key}[{index}] path_refs invalid")
        statuses = runtime.get("probe_status")
        if not isinstance(statuses, Mapping) or set(statuses) != PROBE_NAMES:
            errors.append("runtime probe_status schema mismatch")
        elif any(value != "ok" for value in statuses.values()):
            errors.append("one or more runtime probes failed")
        probe = runtime.get("discord_probe")
        allowed_probe_keys = {"bot_id", "guild_count", "scope_count", "status"}
        if (
            not isinstance(probe, Mapping)
            or set(probe) != allowed_probe_keys
            or probe.get("status") != "ok"
        ):
            errors.append("live Discord command probe did not succeed")
        else:
            guild_count = probe.get("guild_count")
            scope_count = probe.get("scope_count")
            if (
                not isinstance(probe.get("bot_id"), str)
                or not str(probe.get("bot_id")).isdigit()
                or not isinstance(guild_count, int)
                or guild_count < 0
                or scope_count != guild_count + 1
            ):
                errors.append("Discord guild command scope coverage mismatch")

        processes = runtime.get("processes")
        launchd = runtime.get("launchd")
        cron = runtime.get("cron")
        if isinstance(processes, list) and isinstance(launchd, list):
            gateway_rows = [
                row
                for row in launchd
                if isinstance(row, Mapping)
                and row.get("label") == "ai.hermes.gateway"
                and isinstance(row.get("pid"), int)
                and row.get("pid", 0) > 0
            ]
            process_pids = {
                row.get("pid") for row in processes if isinstance(row, Mapping)
            }
            if not gateway_rows or gateway_rows[0]["pid"] not in process_pids:
                errors.append("active Hermes gateway PID/launchd evidence missing")
            loaded_labels = {
                str(row.get("label"))
                for row in launchd
                if isinstance(row, Mapping)
            }
            if not loaded_labels <= launchd_item_labels:
                errors.append("loaded launchd label lacks classified plist evidence")
        if isinstance(cron, list):
            by_path = {
                str(item.get("path")): item
                for item in raw_items
                if isinstance(item, Mapping)
            }
            for row in cron:
                if not isinstance(row, Mapping):
                    continue
                line = row.get("line")
                refs = row.get("path_refs")
                mode = row.get("reference_mode")
                if (
                    not isinstance(line, int)
                    or line < 1
                    or not isinstance(refs, list)
                    or (mode == "path" and not refs)
                    or (mode == "text-only" and refs)
                ):
                    errors.append("cron row lacks line/path_refs evidence")
                    continue
                for reference in refs:
                    item = by_path.get(_absolute(str(reference)))
                    if not item or f"crontab:{line}" not in item.get("callers", []):
                        errors.append(f"cron path lacks classified caller: line {line}")

        runtime_counts = summary.get("runtime_counts") if isinstance(summary, Mapping) else None
        expected_runtime_counts = {
            key: len(runtime[key])
            for key in ("cron", "discord_commands", "launchd", "processes")
            if isinstance(runtime.get(key), list)
        }
        if runtime_counts != expected_runtime_counts:
            errors.append("summary runtime_counts mismatch")

    serialized = json.dumps(inventory, ensure_ascii=False)
    for marker in (
        "Authorization: Bot ",
        "DISCORD_BOT_TOKEN=",
        "SUPABASE_SERVICE_ROLE=",
        "raw_for_scan_only",
    ):
        if marker in serialized:
            errors.append(f"secret-bearing marker forbidden: {marker}")
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
    try:
        shell_tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        shell_tokens = []
    candidates = shell_tokens or PATH_RE.findall(command)
    for token in candidates:
        cleaned = token.rstrip(")]},")
        if "=" in cleaned and not cleaned.startswith("/"):
            key, cleaned = cleaned.split("=", 1)
            if key.upper() == "PATH":
                continue
        cleaned = re.sub(r"^\d*(?:>>?|<)", "", cleaned)
        cleaned = cleaned.strip('"\'')
        if not cleaned.startswith("/"):
            continue
        if any(
            cleaned == _absolute(root)
            or cleaned.startswith(f"{_absolute(root)}{os.sep}")
            for root in roots
        ) or any(marker in cleaned.lower() for marker in ("hermes", "outstanding")):
            refs.add(cleaned)
    return sorted(refs)


def _probe_processes(
    config: InventoryConfig,
) -> tuple[tuple[Mapping[str, object], ...], str]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,command="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return (), "error"
    if result.returncode != 0:
        return (), "error"
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
        lowered = command.lower()
        if not any(
            marker in lowered
            for marker in (
                "hermes",
                "outstanding-news",
                _absolute(config.hermes_home).lower(),
                _absolute(config.v4_root / "tools/hermes-agent").lower(),
            )
        ):
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
    return tuple(rows), "ok"


def _probe_launchd() -> tuple[tuple[Mapping[str, object], ...], str]:
    try:
        result = subprocess.run(
            ["launchctl", "list"], check=False, capture_output=True, text=True
        )
    except OSError:
        return (), "error"
    if result.returncode != 0:
        return (), "error"
    rows = []
    for line in result.stdout.splitlines():
        columns = line.split()
        label = columns[-1].lower() if columns else ""
        if len(columns) < 3 or not any(
            marker in label for marker in ("hermes", "outstanding-news", "position-priority")
        ):
            continue
        try:
            pid = int(columns[0])
        except ValueError:
            pid = 0
        rows.append({"label": columns[-1], "pid": pid})
    return tuple(rows), "ok"


def _probe_cron(
    config: InventoryConfig,
) -> tuple[tuple[Mapping[str, object], ...], str]:
    try:
        result = subprocess.run(
            ["crontab", "-l"], check=False, capture_output=True, text=True
        )
    except OSError:
        return (), "error"
    if result.returncode not in {0, 1}:
        return (), "error"
    rows = []
    roots = (config.hermes_home, config.v4_root, config.v5_root)
    for line_number, line in enumerate(result.stdout.splitlines(), 1):
        if not re.search(r"(hermes|outstanding)", line, re.IGNORECASE):
            continue
        path_refs = _known_path_refs(line, roots)
        rows.append(
            {
                "line": line_number,
                "fingerprint": _command_fingerprint(line),
                "path_refs": path_refs,
                "reference_mode": "path" if path_refs else "text-only",
                "raw_for_scan_only": line,
            }
        )
    return tuple(rows), "ok"


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
        guild_payload = _discord_get(
            "https://discord.com/api/v10/users/@me/guilds", token
        )
        if not isinstance(guild_payload, list):
            raise ValueError("Discord guilds payload is not a list")
        guild_ids = {
            str(row["id"])
            for row in guild_payload
            if isinstance(row, Mapping) and row.get("id")
        }
        configured_guild_id = credentials.get("DISCORD_GUILD_ID", "")
        if configured_guild_id:
            guild_ids.add(configured_guild_id)
        scopes: list[tuple[str, str]] = [
            ("global", f"https://discord.com/api/v10/applications/{client_id}/commands")
        ]
        for guild_id in sorted(guild_ids):
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
        "guild_count": len(guild_ids),
        "scope_count": len(scopes),
    }


def probe_runtime(config: InventoryConfig) -> RuntimeProbe:
    commands, discord_probe = _probe_discord_commands(config)
    processes, processes_status = _probe_processes(config)
    launchd, launchd_status = _probe_launchd()
    cron, cron_status = _probe_cron(config)
    return RuntimeProbe(
        processes=processes,
        launchd=launchd,
        cron=cron,
        discord_commands=commands,
        discord_probe=discord_probe,
        probe_status={
            "cron": cron_status,
            "discord": "ok" if discord_probe.get("status") == "ok" else "error",
            "launchd": launchd_status,
            "processes": processes_status,
        },
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
            hermes_home,
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
