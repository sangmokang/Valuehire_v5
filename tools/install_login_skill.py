"""`login` 스킬을 Claude, Codex, Hermes의 로컬 스킬 폴더에 동일하게 설치한다."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
import shutil
import stat
import tempfile
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


def _staged_tree(
    source: Path,
    staging_root: Path,
    agent: str,
    expected_files: Mapping[str, bytes],
) -> Path:
    """Copy only allowlisted files, then prove staging matches the source snapshot."""
    staged = staging_root / agent
    staged.mkdir()
    for relative_name in REQUIRED_FILES:
        destination = staged / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative_name, destination)
    _verify_tree_matches(staged, expected_files, label=f"{agent} staging")
    return staged


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


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


def _verify_source_unchanged(source: Path, expected_files: Mapping[str, bytes]) -> None:
    try:
        current_files = _validate_source_tree(source)
    except (OSError, ValueError) as exc:
        raise RuntimeError("login skill source changed during installation") from exc
    if current_files != dict(expected_files):
        raise RuntimeError("login skill source changed during installation")


def _optional_tree_snapshot(
    target: Path,
) -> tuple[dict[str, bytes], frozenset[str]] | None:
    if not _path_exists(target):
        return None
    return _tree_snapshot(target)


def _rollback_install(
    *,
    targets: Mapping[str, Path],
    backups: Mapping[str, Path],
    install_attempts: frozenset[str],
    original_snapshots: Mapping[
        str, tuple[dict[str, bytes], frozenset[str]] | None
    ],
) -> tuple[str, ...]:
    """Best-effort rollback, returning every failure for an explicit verdict."""
    failures: list[str] = []
    quarantines: list[Path] = []
    for agent in reversed(tuple(AGENT_DIRS)):
        target = targets[agent]
        backup = backups.get(agent)
        backup_exists = backup is not None and _path_exists(backup)
        # An agent not yet backed up or installed is untouched and must never
        # be mistaken for a partially installed replacement.
        should_remove_target = agent in install_attempts or backup_exists
        if should_remove_target and _path_exists(target):
            try:
                _remove_path(target)
            except BaseException:
                # A failed recursive removal must not stop restoration of the
                # other agents. An atomic quarantine rename often still works.
                quarantine = target.parent / f".login-failed-{uuid.uuid4().hex}"
                try:
                    target.replace(quarantine)
                    quarantines.append(quarantine)
                except BaseException as exc:
                    failures.append(
                        f"{agent} target removal and quarantine failed: {type(exc).__name__}"
                    )
        if backup_exists and backup is not None and not _path_exists(target):
            try:
                backup.replace(target)
            except BaseException as exc:
                # Leave the uniquely named backup in place for manual recovery.
                failures.append(f"{agent} backup restore failed: {type(exc).__name__}")

    for quarantine in quarantines:
        try:
            _remove_path(quarantine)
        except BaseException as exc:
            failures.append(
                f"quarantine cleanup failed for {quarantine}: {type(exc).__name__}"
            )

    for agent, target in targets.items():
        expected = original_snapshots[agent]
        try:
            actual = _optional_tree_snapshot(target)
        except (OSError, ValueError) as exc:
            failures.append(f"{agent} rollback verification failed: {type(exc).__name__}")
            continue
        if actual != expected:
            failures.append(f"{agent} rollback verification failed: tree differs")

    for agent, backup in backups.items():
        if _path_exists(backup):
            failures.append(f"{agent} backup residue remains: {backup}")
    return tuple(failures)


def _reject_target_symlink(target: Path, *, home: Path) -> None:
    if target.is_symlink():
        raise ValueError(f"login skill target symlink rejected: {target}")
    current = target.parent
    while current != home and current != current.parent:
        if current.is_symlink():
            raise ValueError(f"login skill target parent symlink rejected: {current}")
        current = current.parent


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


def install_login_skill(*, repo_root: Path, home: Path) -> dict[str, str]:
    """정본 login 트리 전체를 세 에이전트 폴더에 멱등·stale-free 설치한다."""
    source = Path(repo_root).expanduser().resolve() / "skills" / "login"
    home = Path(home).expanduser().resolve()
    # Preflight before creating anything in the requested home.
    _validate_source_tree(source)

    home.mkdir(parents=True, exist_ok=True)
    with _installation_lock(home):
        # Re-read under the install lock and use these bytes as the immutable
        # transaction snapshot. Staging verifies concurrent source drift.
        expected_files = _validate_source_tree(source)
        preexisting_residues = _find_install_residues(home)
        if preexisting_residues:
            raise RuntimeError(
                "login skill installer residue requires manual recovery: "
                + ", ".join(str(path) for path in preexisting_residues)
            )
        staging_root = Path(tempfile.mkdtemp(prefix=".login-skill-stage-", dir=home))
        targets = {
            agent: home / hidden_dir / "skills" / "login"
            for agent, hidden_dir in AGENT_DIRS.items()
        }
        staged: dict[str, Path] = {}
        backups: dict[str, Path] = {}
        install_attempts: set[str] = set()
        original_snapshots: dict[
            str, tuple[dict[str, bytes], frozenset[str]] | None
        ] = {}

        # Preparation is still non-mutating with respect to all three target
        # trees. A staging cleanup failure is nevertheless an install failure,
        # never a successful return with a hidden residue.
        try:
            for agent in AGENT_DIRS:
                staged[agent] = _staged_tree(source, staging_root, agent, expected_files)

            # Reject source additions or edits that raced the staging copy.
            _verify_source_unchanged(source, expected_files)

            # Reject every unsafe destination before moving the first target.
            for target in targets.values():
                _reject_target_symlink(target, home=home)
                if _path_exists(target) and not target.is_dir():
                    raise ValueError(f"login skill target must be a directory: {target}")
            for target in targets.values():
                target.parent.mkdir(parents=True, exist_ok=True)
                _reject_target_symlink(target, home=home)
            original_snapshots = {
                agent: _optional_tree_snapshot(target)
                for agent, target in targets.items()
            }
        except BaseException as exc:
            try:
                _remove_path(staging_root)
            except BaseException as cleanup_exc:
                raise RuntimeError(
                    "login skill preparation cleanup incomplete: "
                    f"{type(cleanup_exc).__name__}"
                ) from exc
            raise

        try:
            for agent, target in targets.items():
                if target.exists():
                    backup = target.parent / f".login-backup-{uuid.uuid4().hex}"
                    # Record the planned path before replace so rollback also
                    # handles an interrupt raised just after the rename.
                    backups[agent] = backup
                    target.replace(backup)

            for agent, target in targets.items():
                # Mark the attempt before replace in case a wrapper raises
                # after the atomic rename completed.
                install_attempts.add(agent)
                staged[agent].replace(target)

            # Verify all replacements and then re-read the canonical source.
            # This late check closes source drift after the first target swap.
            for agent, target in targets.items():
                _verify_tree_matches(target, expected_files, label=f"{agent} post-install")
            _verify_source_unchanged(source, expected_files)
        except BaseException as exc:
            rollback_failures = list(
                _rollback_install(
                    targets=targets,
                    backups=backups,
                    install_attempts=frozenset(install_attempts),
                    original_snapshots=original_snapshots,
                )
            )
            try:
                _remove_path(staging_root)
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
            if rollback_failures:
                raise RuntimeError(
                    "login skill rollback incomplete; manual recovery required: "
                    + "; ".join(rollback_failures)
                ) from exc
            raise

        # Replacement is committed only if every cleanup succeeds and a final
        # source/target/residue gate still proves one exact canonical tree.
        cleanup_failures: list[str] = []
        for backup in backups.values():
            try:
                _remove_path(backup)
            except BaseException as exc:
                cleanup_failures.append(
                    f"backup cleanup failed for {backup}: {type(exc).__name__}"
                )
        try:
            _remove_path(staging_root)
        except BaseException as exc:
            cleanup_failures.append(
                f"staging cleanup failed for {staging_root}: {type(exc).__name__}"
            )

        final_failures: list[str] = []
        try:
            _verify_source_unchanged(source, expected_files)
        except RuntimeError as exc:
            final_failures.append(str(exc))
        for agent, target in targets.items():
            try:
                _verify_tree_matches(target, expected_files, label=f"{agent} final")
            except RuntimeError as exc:
                final_failures.append(str(exc))
        residues = _find_install_residues(home)
        if residues:
            cleanup_failures.append(
                "transaction residue remains: "
                + ", ".join(str(path) for path in residues)
            )

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
