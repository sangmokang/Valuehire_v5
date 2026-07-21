"""`login` 스킬을 Claude, Codex, Hermes의 로컬 스킬 폴더에 동일하게 설치한다."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
import shutil
import stat
import uuid
from collections.abc import Iterator, Mapping
from pathlib import Path


AGENT_DIRS = {
    "claude": ".claude",
    "codex": ".codex",
    "hermes": ".hermes",
}
REQUIRED_FILES = (
    "SKILL.md",
    "browser-control-contract.json",
    "scripts/macos_window_locator.swift",
)
ALLOWED_DIRECTORIES = frozenset(
    parent.as_posix()
    for relative_name in REQUIRED_FILES
    for parent in Path(relative_name).parents
    if parent != Path(".")
)
INSTALL_LOCK_NAME = ".login-skill-install.lock"
PathIdentity = tuple[int, int, int]
TreeIdentitySnapshot = tuple[
    tuple[tuple[str, bytes], ...],
    tuple[str, ...],
    tuple[tuple[str, PathIdentity], ...],
]


@dataclass(frozen=True)
class _DirectoryAnchor:
    path: Path
    identity: PathIdentity
    descriptor: int


@dataclass(frozen=True)
class _TrackedBackup:
    path: Path
    identity: PathIdentity
    descriptor: int
    parent_descriptor: int
    entry_name: str


def _identity_from_stat(metadata: os.stat_result) -> PathIdentity:
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode)


def _path_identity(path: Path, *, require_directory: bool = False) -> PathIdentity:
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"login skill path symlink rejected: {path}")
    if require_directory and not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"login skill path must be a directory: {path}")
    return _identity_from_stat(metadata)


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_directory_anchor(path: Path) -> _DirectoryAnchor:
    descriptor = os.open(path, _directory_open_flags())
    try:
        descriptor_identity = _identity_from_stat(os.fstat(descriptor))
        path_identity = _path_identity(path, require_directory=True)
        if descriptor_identity != path_identity:
            raise RuntimeError(f"login skill directory identity raced: {path}")
        return _DirectoryAnchor(path, path_identity, descriptor)
    except BaseException:
        os.close(descriptor)
        raise


def _open_or_create_child_directory(
    parent: _DirectoryAnchor,
    name: str,
    *,
    mode: int = 0o777,
) -> _DirectoryAnchor:
    if not name or name in {".", ".."} or "/" in name or "\0" in name:
        raise ValueError("login skill child directory name is unsafe")
    created = False
    try:
        os.mkdir(name, mode, dir_fd=parent.descriptor)
        created = True
    except FileExistsError:
        pass
    try:
        descriptor = os.open(name, _directory_open_flags(), dir_fd=parent.descriptor)
    except BaseException:
        if created:
            try:
                os.rmdir(name, dir_fd=parent.descriptor)
            except OSError:
                pass
        raise
    path = parent.path / name
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"login skill path must be a directory: {path}")
        return _DirectoryAnchor(path, _identity_from_stat(metadata), descriptor)
    except BaseException:
        os.close(descriptor)
        raise


def _verify_directory_anchor(anchor: _DirectoryAnchor) -> None:
    try:
        descriptor_identity = _identity_from_stat(os.fstat(anchor.descriptor))
    except BaseException as exc:
        raise RuntimeError(
            f"login skill directory anchor unavailable: {anchor.path}"
        ) from exc
    if descriptor_identity != anchor.identity:
        raise RuntimeError(f"login skill directory anchor changed: {anchor.path}")


def _verify_live_directory_anchor(anchor: _DirectoryAnchor) -> None:
    _verify_directory_anchor(anchor)
    try:
        live_identity = _path_identity(anchor.path, require_directory=True)
    except BaseException as exc:
        raise RuntimeError(
            f"login skill live directory path changed: {anchor.path}"
        ) from exc
    if live_identity != anchor.identity:
        raise RuntimeError(f"login skill live directory identity changed: {anchor.path}")


def _close_directory_anchors(
    anchors: Mapping[str, _DirectoryAnchor],
) -> tuple[str, ...]:
    failures: list[str] = []
    closed: set[int] = set()
    for label, anchor in anchors.items():
        if anchor.descriptor in closed:
            continue
        closed.add(anchor.descriptor)
        try:
            os.close(anchor.descriptor)
        except BaseException as exc:
            failures.append(
                f"{label} directory anchor cleanup failed: {type(exc).__name__}"
            )
    return tuple(failures)


def _anchored_metadata(
    parent: _DirectoryAnchor,
    name: str,
) -> os.stat_result | None:
    _verify_directory_anchor(parent)
    try:
        return os.stat(name, dir_fd=parent.descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _anchored_exists(parent: _DirectoryAnchor, name: str) -> bool:
    return _anchored_metadata(parent, name) is not None


def _replace_path(
    source: Path,
    destination: Path,
    *,
    source_parent: _DirectoryAnchor | None = None,
    destination_parent: _DirectoryAnchor | None = None,
    require_live_parents: bool = True,
) -> Path:
    """Atomically rename through retained directory descriptors when provided."""
    if source_parent is None and destination_parent is None:
        return source.replace(destination)
    if source_parent is None or destination_parent is None:
        raise ValueError("login skill anchored replace requires both parents")
    verifier = (
        _verify_live_directory_anchor
        if require_live_parents
        else _verify_directory_anchor
    )
    verifier(source_parent)
    verifier(destination_parent)
    os.replace(
        source.name,
        destination.name,
        src_dir_fd=source_parent.descriptor,
        dst_dir_fd=destination_parent.descriptor,
    )
    return destination


def _tree_snapshot(root: Path) -> tuple[dict[str, bytes], frozenset[str]]:
    """Return exact file bytes and directory names, rejecting links/special files."""
    if root.is_symlink():
        raise ValueError(f"login skill tree symlink rejected: {root}")
    if not root.is_dir():
        raise FileNotFoundError(f"login skill tree missing: {root}")

    files: dict[str, bytes] = {}
    directories: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative_name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"login skill tree symlink rejected: {path}")
        if path.is_dir():
            directories.add(relative_name)
        elif path.is_file():
            files[relative_name] = path.read_bytes()
        else:
            raise ValueError(f"login skill special file rejected: {path}")
    return files, frozenset(directories)


def _tree_identity_snapshot(root: Path) -> TreeIdentitySnapshot:
    """Capture bytes plus exact inodes for a fail-closed stability proof."""
    files, directories = _tree_snapshot(root)
    identities: list[tuple[str, PathIdentity]] = [
        (".", _path_identity(root, require_directory=True))
    ]
    for path in sorted(root.rglob("*")):
        relative_name = path.relative_to(root).as_posix()
        identities.append(
            (
                relative_name,
                _path_identity(path, require_directory=path.is_dir()),
            )
        )
    return (
        tuple(sorted(files.items())),
        tuple(sorted(directories)),
        tuple(identities),
    )


def _decode_utf8(payload: bytes, *, label: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"login skill {label} must be UTF-8") from exc


def _validate_skill_frontmatter(payload: bytes) -> None:
    text = _decode_utf8(payload, label="SKILL.md")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("login skill SKILL.md frontmatter missing")
    try:
        closing_index = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("login skill SKILL.md frontmatter is not closed") from exc

    values: dict[str, str] = {}
    for line in lines[1:closing_index]:
        if not line or line[:1].isspace() or ":" not in line:
            raise ValueError("login skill SKILL.md frontmatter is malformed")
        key, value = (part.strip() for part in line.split(":", 1))
        if not key or key in values:
            raise ValueError("login skill SKILL.md frontmatter has duplicate/empty key")
        values[key] = value
    if set(values) != {"name", "description"}:
        raise ValueError("login skill SKILL.md frontmatter keys are invalid")
    if values["name"] != "login":
        raise ValueError("login skill SKILL.md must declare name: login")
    if not values["description"].strip(" \t\"'"):
        raise ValueError("login skill SKILL.md description must not be empty")


def _validate_machine_contract(payload: bytes) -> None:
    text = _decode_utf8(payload, label="browser-control-contract.json")
    try:
        contract = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("login skill browser contract is invalid JSON") from exc
    if not isinstance(contract, dict):
        raise ValueError("login skill browser contract must be a JSON object")
    if contract.get("skill") != "login":
        raise ValueError("login skill browser contract has the wrong skill identity")
    if not isinstance(contract.get("schema_version"), str) or not contract["schema_version"]:
        raise ValueError("login skill browser contract schema_version is missing")
    supported_agents = contract.get("supported_agents")
    if supported_agents != list(AGENT_DIRS):
        raise ValueError("login skill browser contract supported_agents are invalid")


def _validate_swift_locator(payload: bytes) -> None:
    text = _decode_utf8(payload, label="macos_window_locator.swift")
    required_markers = (
        "import AppKit",
        "import CoreGraphics",
        "CGWindowListCopyWindowInfo",
        "kCGWindowOwnerPID",
        "kCGWindowNumber",
        "frontmost_layer0",
        "NSRunningApplication",
        "--activate-pid",
    )
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        raise ValueError(f"login skill Swift window locator markers missing: {missing}")


def _validate_source_tree(source: Path) -> dict[str, bytes]:
    """Validate the canonical allowlisted tree and return its immutable bytes."""
    files, directories = _tree_snapshot(source)
    expected_files = set(REQUIRED_FILES)
    unknown_files = sorted(set(files) - expected_files)
    if unknown_files:
        raise ValueError(f"login skill source has unknown canonical files: {unknown_files}")
    missing_files = sorted(expected_files - set(files))
    if missing_files:
        raise FileNotFoundError(f"login skill source missing files: {missing_files}")
    empty_files = sorted(name for name, payload in files.items() if not payload)
    if empty_files:
        raise FileNotFoundError(f"login skill source has empty files: {empty_files}")
    unknown_directories = sorted(set(directories) - set(ALLOWED_DIRECTORIES))
    missing_directories = sorted(set(ALLOWED_DIRECTORIES) - set(directories))
    if unknown_directories:
        raise ValueError(
            f"login skill source has unknown canonical directories: {unknown_directories}"
        )
    if missing_directories:
        raise FileNotFoundError(f"login skill source missing directories: {missing_directories}")

    _validate_skill_frontmatter(files["SKILL.md"])
    _validate_machine_contract(files["browser-control-contract.json"])
    _validate_swift_locator(files["scripts/macos_window_locator.swift"])
    return files


def _verify_tree_matches(
    root: Path,
    expected_files: Mapping[str, bytes],
    *,
    label: str,
) -> None:
    try:
        actual_files, actual_directories = _tree_snapshot(root)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"login skill {label} verification failed") from exc
    if actual_files != dict(expected_files) or actual_directories != ALLOWED_DIRECTORIES:
        raise RuntimeError(f"login skill {label} verification failed: tree bytes differ")


def _write_anchored_file(
    parent: _DirectoryAnchor,
    name: str,
    payload: bytes,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(name, flags, 0o644, dir_fd=parent.descriptor)
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("login skill staging write made no progress")
            remaining = remaining[written:]
    finally:
        os.close(descriptor)


def _staged_tree(
    staging_root: _DirectoryAnchor,
    agent: str,
    expected_files: Mapping[str, bytes],
) -> Path:
    """Write the immutable snapshot only below the retained staging dirfd."""
    staged_anchor = _open_or_create_child_directory(
        staging_root,
        agent,
        mode=0o700,
    )
    nested_anchors: list[_DirectoryAnchor] = []
    try:
        for relative_name in REQUIRED_FILES:
            relative = Path(relative_name)
            parent = staged_anchor
            for component in relative.parts[:-1]:
                child = _open_or_create_child_directory(parent, component)
                nested_anchors.append(child)
                parent = child
            _write_anchored_file(
                parent,
                relative.name,
                bytes(expected_files[relative_name]),
            )
        _verify_live_directory_anchor(staging_root)
        _verify_live_directory_anchor(staged_anchor)
        _verify_tree_matches(
            staged_anchor.path,
            expected_files,
            label=f"{agent} staging",
        )
        return staged_anchor.path
    finally:
        for anchor in reversed(nested_anchors):
            os.close(anchor.descriptor)
        os.close(staged_anchor.descriptor)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_directory_contents_fd(directory_fd: int, display_path: Path) -> None:
    """Recursively remove one already-open directory without resolving its parent path.

    Python 3.9's ``shutil.rmtree`` has no ``dir_fd`` argument.  Keeping the
    traversal descriptor-relative preserves the installer's symlink/race
    boundary on every supported Python version.
    """
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.scandir(directory_fd) as entries:
        for entry in entries:
            child_path = display_path / entry.name
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                child_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                try:
                    if not os.path.samestat(metadata, os.fstat(child_fd)):
                        raise RuntimeError(
                            f"login skill directory changed during removal: {child_path}"
                        )
                    _remove_directory_contents_fd(child_fd, child_path)
                finally:
                    os.close(child_fd)
                os.rmdir(entry.name, dir_fd=directory_fd)
            elif stat.S_ISLNK(metadata.st_mode) or stat.S_ISREG(metadata.st_mode):
                os.unlink(entry.name, dir_fd=directory_fd)
            else:
                raise ValueError(
                    f"login skill special path removal rejected: {child_path}"
                )


def _remove_path(
    path: Path,
    *,
    parent: _DirectoryAnchor | None = None,
    require_live_parent: bool = True,
) -> None:
    if parent is None:
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        return

    if require_live_parent:
        _verify_live_directory_anchor(parent)
    else:
        _verify_directory_anchor(parent)
    metadata = _anchored_metadata(parent, path.name)
    if metadata is None:
        return
    if stat.S_ISLNK(metadata.st_mode) or stat.S_ISREG(metadata.st_mode):
        os.unlink(path.name, dir_fd=parent.descriptor)
    elif stat.S_ISDIR(metadata.st_mode):
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_fd = os.open(path.name, flags, dir_fd=parent.descriptor)
        try:
            if not os.path.samestat(metadata, os.fstat(directory_fd)):
                raise RuntimeError(
                    f"login skill directory changed during removal: {path}"
                )
            _remove_directory_contents_fd(directory_fd, path)
        finally:
            os.close(directory_fd)
        os.rmdir(path.name, dir_fd=parent.descriptor)
    else:
        raise ValueError(f"login skill special path removal rejected: {path}")


def _find_install_residues(home: Path) -> tuple[Path, ...]:
    """Return only installer-owned transaction artifacts in known locations."""
    residues: list[Path] = []
    if home.is_dir():
        residues.extend(
            path
            for path in home.iterdir()
            if path.name.startswith(".login-skill-stage-")
        )
    for hidden_dir in AGENT_DIRS.values():
        skills_root = home / hidden_dir / "skills"
        if not skills_root.is_dir() or skills_root.is_symlink():
            continue
        residues.extend(
            path
            for path in skills_root.iterdir()
            if path.name.startswith((".login-backup-", ".login-failed-"))
        )
    return tuple(sorted(residues, key=str))


def _verify_source_unchanged(
    source: Path,
    expected_files: Mapping[str, bytes],
    *,
    expected_identity: TreeIdentitySnapshot | None = None,
) -> TreeIdentitySnapshot:
    try:
        current_files = _validate_source_tree(source)
        current_identity = _tree_identity_snapshot(source)
    except BaseException as exc:
        raise RuntimeError("login skill source changed during installation") from exc
    if current_files != dict(expected_files):
        raise RuntimeError("login skill source changed during installation")
    if expected_identity is not None and current_identity != expected_identity:
        raise RuntimeError(
            "login skill source changed during installation: path identity differs"
        )
    return current_identity


def _optional_tree_snapshot(
    target: Path,
) -> tuple[dict[str, bytes], frozenset[str]] | None:
    if not _path_exists(target):
        return None
    return _tree_snapshot(target)


def _rollback_install(
    *,
    targets: Mapping[str, Path],
    target_parents: Mapping[str, _DirectoryAnchor],
    backups: Mapping[str, Path],
    tracked_backups: Mapping[str, _TrackedBackup],
    install_attempts: frozenset[str],
    original_snapshots: Mapping[
        str, tuple[dict[str, bytes], frozenset[str]] | None
    ],
) -> tuple[str, ...]:
    """Best-effort rollback, returning every failure for an explicit verdict."""
    failures: list[str] = []
    quarantines: list[tuple[Path, _DirectoryAnchor]] = []
    for agent in reversed(tuple(AGENT_DIRS)):
        target = targets[agent]
        parent = target_parents[agent]
        backup = backups.get(agent)
        backup_exists = backup is not None and _anchored_exists(parent, backup.name)
        backup_valid = False
        if backup_exists:
            tracked = tracked_backups.get(agent)
            if tracked is None:
                failures.append(f"{agent} backup identity was never established")
            else:
                try:
                    _verify_tracked_backup_present(tracked)
                    backup_valid = True
                except BaseException as exc:
                    failures.append(
                        f"{agent} backup identity verification failed: "
                        f"{type(exc).__name__}"
                    )
        # An agent not yet backed up or installed is untouched and must never
        # be mistaken for a partially installed replacement.
        original_existed = original_snapshots[agent] is not None
        should_remove_target = (
            agent in install_attempts or backup_exists
        ) and (not original_existed or backup_valid)
        if should_remove_target and _anchored_exists(parent, target.name):
            try:
                _remove_path(
                    target,
                    parent=parent,
                    require_live_parent=False,
                )
            except BaseException:
                # A failed recursive removal must not stop restoration of the
                # other agents. An atomic quarantine rename often still works.
                quarantine = target.parent / f".login-failed-{uuid.uuid4().hex}"
                try:
                    _replace_path(
                        target,
                        quarantine,
                        source_parent=parent,
                        destination_parent=parent,
                        require_live_parents=False,
                    )
                    quarantines.append((quarantine, parent))
                except BaseException as exc:
                    failures.append(
                        f"{agent} target removal and quarantine failed: {type(exc).__name__}"
                    )
        if (
            backup_valid
            and backup is not None
            and not _anchored_exists(parent, target.name)
        ):
            tracked = tracked_backups[agent]
            try:
                _replace_path(
                    backup,
                    target,
                    source_parent=parent,
                    destination_parent=parent,
                    require_live_parents=False,
                )
                # The backup name can be exchanged after the pre-rename proof.
                # Prove that the entry actually restored at the target is the
                # inode retained by our descriptor before accepting rollback.
                _verify_tracked_backup_at_entry(tracked, target.name)
            except BaseException as exc:
                failures.append(f"{agent} backup restore failed: {type(exc).__name__}")
                # Never leave an unverified replacement (especially a symlink)
                # at the public login path. Move it aside atomically and retain
                # the quarantine for manual recovery instead of risking deletion
                # of the tracked original during another concurrent exchange.
                if _anchored_exists(parent, target.name):
                    quarantine = target.parent / f".login-failed-{uuid.uuid4().hex}"
                    try:
                        _replace_path(
                            target,
                            quarantine,
                            source_parent=parent,
                            destination_parent=parent,
                            require_live_parents=False,
                        )
                    except BaseException as quarantine_exc:
                        failures.append(
                            f"{agent} unverified restore quarantine failed: "
                            f"{type(quarantine_exc).__name__}"
                        )

    for quarantine, parent in quarantines:
        try:
            _remove_path(
                quarantine,
                parent=parent,
                require_live_parent=False,
            )
        except BaseException as exc:
            failures.append(
                f"quarantine cleanup failed for {quarantine}: {type(exc).__name__}"
            )

    for agent, target in targets.items():
        expected = original_snapshots[agent]
        try:
            _verify_live_directory_anchor(target_parents[agent])
            actual = _optional_tree_snapshot(target)
        except BaseException as exc:
            failures.append(f"{agent} rollback verification failed: {type(exc).__name__}")
            continue
        if actual != expected:
            failures.append(f"{agent} rollback verification failed: tree differs")

    for agent, backup in backups.items():
        if _anchored_exists(target_parents[agent], backup.name):
            failures.append(f"{agent} backup residue remains: {backup}")
    return tuple(failures)


def _reject_target_symlink(target: Path, *, home: Path) -> None:
    if target.is_symlink():
        raise ValueError(f"login skill target symlink rejected: {target}")
    current = target.parent
    while True:
        if current.is_symlink():
            raise ValueError(f"login skill target parent symlink rejected: {current}")
        if current == home:
            break
        if current == current.parent:
            raise ValueError(f"login skill target escaped install home: {target}")
        current = current.parent


def _safe_parent_identity_snapshot(
    targets: Mapping[str, Path],
    *,
    home: Path,
) -> tuple[tuple[str, PathIdentity], ...]:
    """Prove every target parent remains the same real directory chain."""
    parents: set[Path] = {home}
    for target in targets.values():
        _reject_target_symlink(target, home=home)
        current = target.parent
        while True:
            parents.add(current)
            if current == home:
                break
            if current == current.parent:
                raise ValueError(f"login skill target escaped install home: {target}")
            current = current.parent
    return tuple(
        (
            "." if path == home else path.relative_to(home).as_posix(),
            _path_identity(path, require_directory=True),
        )
        for path in sorted(parents, key=str)
    )


def _track_backup(
    path: Path,
    *,
    parent: _DirectoryAnchor,
    current_name: str | None = None,
) -> _TrackedBackup:
    opened_name = current_name or path.name
    descriptor = os.open(
        opened_name,
        _directory_open_flags(),
        dir_fd=parent.descriptor,
    )
    try:
        descriptor_identity = _identity_from_stat(os.fstat(descriptor))
        anchored_metadata = _anchored_metadata(parent, opened_name)
        if anchored_metadata is None or not stat.S_ISDIR(anchored_metadata.st_mode):
            raise RuntimeError(f"login skill backup disappeared: {path}")
        anchored_identity = _identity_from_stat(anchored_metadata)
        if descriptor_identity != anchored_identity:
            raise RuntimeError(f"login skill backup identity raced: {path}")
        return _TrackedBackup(
            path=path,
            identity=anchored_identity,
            descriptor=descriptor,
            parent_descriptor=parent.descriptor,
            entry_name=path.name,
        )
    except BaseException:
        os.close(descriptor)
        raise


def _verify_tracked_backup_at_entry(
    tracked: _TrackedBackup,
    entry_name: str,
) -> None:
    try:
        path_metadata = os.stat(
            entry_name,
            dir_fd=tracked.parent_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(path_metadata.st_mode):
            raise RuntimeError("tracked backup is not a directory")
        path_identity = _identity_from_stat(path_metadata)
        descriptor_metadata = os.fstat(tracked.descriptor)
    except BaseException as exc:
        raise RuntimeError(
            f"login skill tracked backup disappeared: {tracked.path}"
        ) from exc
    if path_identity != tracked.identity:
        raise RuntimeError(
            f"login skill tracked backup identity changed: {tracked.path}"
        )
    if _identity_from_stat(descriptor_metadata) != tracked.identity:
        raise RuntimeError(
            f"login skill tracked backup descriptor changed: {tracked.path}"
        )
    if descriptor_metadata.st_nlink == 0:
        raise RuntimeError(
            f"login skill tracked backup was unlinked early: {tracked.path}"
        )


def _verify_tracked_backup_present(tracked: _TrackedBackup) -> None:
    _verify_tracked_backup_at_entry(tracked, tracked.entry_name)


def _live_descriptor_path(descriptor: int) -> Path | None:
    """Return the descriptor's extant path, or None after a real unlink."""
    getpath = getattr(fcntl, "F_GETPATH", None)
    if getpath is not None:
        raw_path = fcntl.fcntl(descriptor, getpath, b"\0" * 1024)
        if isinstance(raw_path, bytes):
            encoded_path = raw_path.split(b"\0", 1)[0]
            if encoded_path:
                candidate = Path(os.fsdecode(encoded_path))
                return candidate if _path_exists(candidate) else None

    descriptor_link = Path("/proc/self/fd") / str(descriptor)
    if descriptor_link.is_symlink():
        candidate = Path(os.readlink(descriptor_link))
        return candidate if _path_exists(candidate) else None
    raise RuntimeError("login skill cannot prove tracked backup removal")


def _verify_tracked_backup_removed(tracked: _TrackedBackup) -> None:
    try:
        os.stat(
            tracked.entry_name,
            dir_fd=tracked.parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError(f"login skill tracked backup still exists: {tracked.path}")
    try:
        descriptor_metadata = os.fstat(tracked.descriptor)
    except BaseException as exc:
        raise RuntimeError(
            f"login skill tracked backup descriptor unavailable: {tracked.path}"
        ) from exc
    if _identity_from_stat(descriptor_metadata) != tracked.identity:
        raise RuntimeError(
            f"login skill tracked backup descriptor changed: {tracked.path}"
        )
    live_path = _live_descriptor_path(tracked.descriptor)
    if live_path is not None:
        try:
            live_identity = _path_identity(live_path, require_directory=True)
        except BaseException as exc:
            raise RuntimeError(
                f"login skill tracked backup has an unsafe live path: {live_path}"
            ) from exc
        detail = "renamed" if live_identity == tracked.identity else "replaced"
        raise RuntimeError(
            "login skill tracked backup was "
            f"{detail} instead of removed: {tracked.path} -> {live_path}"
        )


def _close_tracked_backups(
    tracked_backups: Mapping[str, _TrackedBackup],
) -> tuple[str, ...]:
    failures: list[str] = []
    for agent, tracked in tracked_backups.items():
        try:
            os.close(tracked.descriptor)
        except BaseException as exc:
            failures.append(
                f"{agent} backup descriptor cleanup failed: {type(exc).__name__}"
            )
    return tuple(failures)


@contextmanager
def _installation_lock(home: Path) -> Iterator[None]:
    """Serialize installers in separate processes that share the same home."""
    lock_path = home / INSTALL_LOCK_NAME
    if lock_path.is_symlink():
        raise ValueError(f"login skill install lock symlink rejected: {lock_path}")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"login skill install lock is not a regular file: {lock_path}")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _commit_state_snapshot(
    *,
    source: Path,
    expected_files: Mapping[str, bytes],
    expected_source_identity: TreeIdentitySnapshot,
    targets: Mapping[str, Path],
    expected_target_identities: Mapping[str, TreeIdentitySnapshot],
    home: Path,
    expected_parent_identities: tuple[tuple[str, PathIdentity], ...],
    tracked_backups: Mapping[str, _TrackedBackup],
    pass_number: int,
) -> tuple[
    TreeIdentitySnapshot,
    tuple[tuple[str, TreeIdentitySnapshot], ...],
    tuple[tuple[str, PathIdentity], ...],
    tuple[str, ...],
]:
    """Capture one complete fail-closed commit state."""
    _verify_source_unchanged(
        source,
        expected_files,
        expected_identity=expected_source_identity,
    )
    source_identity = _tree_identity_snapshot(source)
    if source_identity != expected_source_identity:
        raise RuntimeError(
            "login skill source changed during commit-state snapshot"
        )

    target_identities: list[tuple[str, TreeIdentitySnapshot]] = []
    for agent, target in targets.items():
        _reject_target_symlink(target, home=home)
        _verify_tree_matches(
            target,
            expected_files,
            label=f"{agent} final-{pass_number}",
        )
        identity = _tree_identity_snapshot(target)
        if identity != expected_target_identities[agent]:
            raise RuntimeError(
                f"login skill {agent} final verification failed: path identity differs"
            )
        target_identities.append((agent, identity))

    parent_identities = _safe_parent_identity_snapshot(targets, home=home)
    if parent_identities != expected_parent_identities:
        raise RuntimeError(
            "login skill final parent verification failed: directory identity differs"
        )

    for tracked in tracked_backups.values():
        _verify_tracked_backup_removed(tracked)

    residues = tuple(str(path) for path in _find_install_residues(home))
    if residues:
        raise RuntimeError(
            "login skill final verification failed: transaction residue remains: "
            + ", ".join(residues)
        )
    return (
        source_identity,
        tuple(target_identities),
        parent_identities,
        residues,
    )


def install_login_skill(*, repo_root: Path, home: Path) -> dict[str, str]:
    """정본 login 트리 전체를 세 에이전트 폴더에 멱등·stale-free 설치한다."""
    source = Path(repo_root).expanduser().resolve() / "skills" / "login"
    home = Path(home).expanduser().resolve()
    # Preflight before creating anything in the requested home.
    _validate_source_tree(source)

    home.mkdir(parents=True, exist_ok=True)
    with _installation_lock(home), ExitStack() as anchor_stack:
        directory_anchors: dict[str, _DirectoryAnchor] = {}

        def retain_anchor(label: str, anchor: _DirectoryAnchor) -> _DirectoryAnchor:
            directory_anchors[label] = anchor
            anchor_stack.callback(os.close, anchor.descriptor)
            return anchor

        home_anchor = retain_anchor("home", _open_directory_anchor(home))
        # Re-read under the install lock and use these bytes as the immutable
        # transaction snapshot. Staging verifies concurrent source drift.
        expected_files = _validate_source_tree(source)
        preexisting_residues = _find_install_residues(home)
        if preexisting_residues:
            raise RuntimeError(
                "login skill installer residue requires manual recovery: "
                + ", ".join(str(path) for path in preexisting_residues)
            )
        targets = {
            agent: home / hidden_dir / "skills" / "login"
            for agent, hidden_dir in AGENT_DIRS.items()
        }
        target_parents: dict[str, _DirectoryAnchor] = {}
        for agent, hidden_dir in AGENT_DIRS.items():
            agent_root = retain_anchor(
                f"{agent}-root",
                _open_or_create_child_directory(home_anchor, hidden_dir),
            )
            target_parents[agent] = retain_anchor(
                f"{agent}-skills",
                _open_or_create_child_directory(agent_root, "skills"),
            )
        staging_name = f".login-skill-stage-{uuid.uuid4().hex}"
        staging_anchor = retain_anchor(
            "staging",
            _open_or_create_child_directory(
                home_anchor,
                staging_name,
                mode=0o700,
            ),
        )
        staging_root = staging_anchor.path
        tracked_staging = _track_backup(
            staging_root,
            parent=home_anchor,
        )
        anchor_stack.callback(os.close, tracked_staging.descriptor)
        staged: dict[str, Path] = {}
        backups: dict[str, Path] = {}
        tracked_backups: dict[str, _TrackedBackup] = {}
        install_attempts: set[str] = set()
        expected_source_identity: TreeIdentitySnapshot | None = None
        expected_target_identities: dict[str, TreeIdentitySnapshot] = {}
        expected_parent_identities: tuple[tuple[str, PathIdentity], ...] = ()
        original_snapshots: dict[
            str, tuple[dict[str, bytes], frozenset[str]] | None
        ] = {}

        # Preparation is still non-mutating with respect to all three target
        # trees. A staging cleanup failure is nevertheless an install failure,
        # never a successful return with a hidden residue.
        try:
            for agent in AGENT_DIRS:
                staged[agent] = _staged_tree(
                    staging_anchor,
                    agent,
                    expected_files,
                )

            # Reject source additions or edits that raced the staging copy.
            _verify_source_unchanged(source, expected_files)
            expected_source_identity = _tree_identity_snapshot(source)

            # Reject every unsafe destination before moving the first target.
            for agent, target in targets.items():
                parent = target_parents[agent]
                _verify_live_directory_anchor(parent)
                metadata = _anchored_metadata(parent, target.name)
                if metadata is not None and not stat.S_ISDIR(metadata.st_mode):
                    raise ValueError(f"login skill target must be a directory: {target}")
            expected_parent_identities = _safe_parent_identity_snapshot(
                targets,
                home=home,
            )
            original_snapshots = {
                agent: _optional_tree_snapshot(target)
                for agent, target in targets.items()
            }
        except BaseException as exc:
            try:
                _verify_tracked_backup_present(tracked_staging)
                _remove_path(staging_root, parent=home_anchor)
                _verify_tracked_backup_removed(tracked_staging)
            except BaseException as cleanup_exc:
                raise RuntimeError(
                    "login skill preparation cleanup incomplete: "
                    f"{type(cleanup_exc).__name__}"
                ) from exc
            raise

        try:
            for agent, target in targets.items():
                parent = target_parents[agent]
                metadata = _anchored_metadata(parent, target.name)
                if metadata is not None:
                    if not stat.S_ISDIR(metadata.st_mode):
                        raise ValueError(
                            f"login skill target must be a directory: {target}"
                        )
                    backup = target.parent / f".login-backup-{uuid.uuid4().hex}"
                    # Open and register the original inode under its planned
                    # backup name before rename.  Rollback can therefore prove
                    # the backup even if interruption lands after the atomic
                    # rename but before the next Python instruction.
                    backups[agent] = backup
                    tracked_backups[agent] = _track_backup(
                        backup,
                        parent=parent,
                        current_name=target.name,
                    )
                    _replace_path(
                        target,
                        backup,
                        source_parent=parent,
                        destination_parent=parent,
                    )

            for tracked in tracked_backups.values():
                _verify_tracked_backup_present(tracked)

            for agent, target in targets.items():
                # Mark the attempt before replace in case a wrapper raises
                # after the atomic rename completed.
                install_attempts.add(agent)
                _replace_path(
                    staged[agent],
                    target,
                    source_parent=staging_anchor,
                    destination_parent=target_parents[agent],
                )

            # Verify all replacements and then re-read the canonical source.
            # This late check closes source drift after the first target swap.
            for agent, target in targets.items():
                _verify_tree_matches(target, expected_files, label=f"{agent} post-install")
                expected_target_identities[agent] = _tree_identity_snapshot(target)
            if expected_source_identity is None:
                raise RuntimeError("login skill source identity snapshot is missing")
            _verify_source_unchanged(
                source,
                expected_files,
                expected_identity=expected_source_identity,
            )
        except BaseException as exc:
            rollback_failures = list(
                _rollback_install(
                    targets=targets,
                    target_parents=target_parents,
                    backups=backups,
                    tracked_backups=tracked_backups,
                    install_attempts=frozenset(install_attempts),
                    original_snapshots=original_snapshots,
                )
            )
            try:
                _verify_tracked_backup_present(tracked_staging)
                _remove_path(
                    staging_root,
                    parent=home_anchor,
                    require_live_parent=False,
                )
                _verify_tracked_backup_removed(tracked_staging)
            except BaseException as cleanup_exc:
                rollback_failures.append(
                    f"staging cleanup failed: {type(cleanup_exc).__name__}"
                )
            rollback_residues = _find_install_residues(home)
            if rollback_residues:
                rollback_failures.append(
                    "transaction residue remains: "
                    + ", ".join(str(path) for path in rollback_residues)
                )
            rollback_failures.extend(_close_tracked_backups(tracked_backups))
            tracked_backups.clear()
            if rollback_failures:
                raise RuntimeError(
                    "login skill rollback incomplete; manual recovery required: "
                    + "; ".join(rollback_failures)
                ) from exc
            raise

        # Replacement is committed only if every cleanup succeeds and a final
        # source/target/residue gate still proves one exact canonical tree.
        cleanup_failures: list[str] = []
        for agent, backup in backups.items():
            try:
                parent = target_parents[agent]
                tracked = tracked_backups.get(agent)
                if tracked is not None:
                    _verify_tracked_backup_present(tracked)
                _remove_path(backup, parent=parent)
                if tracked is not None:
                    _verify_tracked_backup_removed(tracked)
            except BaseException as exc:
                cleanup_failures.append(
                    f"backup cleanup failed for {backup}: {type(exc).__name__}"
                )
        try:
            _verify_tracked_backup_present(tracked_staging)
            _remove_path(staging_root, parent=home_anchor)
            _verify_tracked_backup_removed(tracked_staging)
        except BaseException as exc:
            cleanup_failures.append(
                f"staging cleanup failed for {staging_root}: {type(exc).__name__}"
            )

        final_failures: list[str] = []
        if not cleanup_failures:
            try:
                if expected_source_identity is None:
                    raise RuntimeError("login skill source identity snapshot is missing")
                if set(expected_target_identities) != set(targets):
                    raise RuntimeError("login skill target identity snapshot is incomplete")
                first_commit_state = _commit_state_snapshot(
                    source=source,
                    expected_files=expected_files,
                    expected_source_identity=expected_source_identity,
                    targets=targets,
                    expected_target_identities=expected_target_identities,
                    home=home,
                    expected_parent_identities=expected_parent_identities,
                    tracked_backups=tracked_backups,
                    pass_number=1,
                )
                second_commit_state = _commit_state_snapshot(
                    source=source,
                    expected_files=expected_files,
                    expected_source_identity=expected_source_identity,
                    targets=targets,
                    expected_target_identities=expected_target_identities,
                    home=home,
                    expected_parent_identities=expected_parent_identities,
                    tracked_backups=tracked_backups,
                    pass_number=2,
                )
                if second_commit_state != first_commit_state:
                    raise RuntimeError(
                        "login skill final commit state was not stable across checks"
                    )
            except BaseException as exc:
                final_failures.append(
                    "login skill commit verification failed: "
                    f"{type(exc).__name__}: {exc}"
                )
        residues = _find_install_residues(home)
        if residues:
            cleanup_failures.append(
                "transaction residue remains: "
                + ", ".join(str(path) for path in residues)
            )
        cleanup_failures.extend(_close_tracked_backups(tracked_backups))
        tracked_backups.clear()

        if final_failures:
            details = final_failures + cleanup_failures
            raise RuntimeError(
                "login skill final verification failed: " + "; ".join(details)
            )
        if cleanup_failures:
            raise RuntimeError(
                "login skill cleanup incomplete; manual recovery required: "
                + "; ".join(cleanup_failures)
            )
        return {agent: str(target) for agent, target in targets.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="공용 login 스킬을 Claude/Codex/Hermes에 설치")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Valuehire_v5 저장소 루트",
    )
    parser.add_argument("--home", type=Path, default=Path.home(), help="설치 대상 사용자 홈")
    args = parser.parse_args(argv)
    result = install_login_skill(repo_root=args.repo_root, home=args.home)
    for agent, path in result.items():
        print(f"{agent}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
