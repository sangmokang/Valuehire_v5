"""`login` 스킬을 Claude, Codex, Hermes의 로컬 스킬 폴더에 동일하게 설치한다."""
from __future__ import annotations

import argparse
import shutil
import tempfile
import uuid
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


def _validate_source_tree(source: Path) -> None:
    for relative_name in REQUIRED_FILES:
        path = source / relative_name
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"login skill source missing or empty: {path}")
    for path in (source, *source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"login skill source symlink rejected: {path}")


def _staged_tree(source: Path, staging_root: Path, agent: str) -> Path:
    staged = staging_root / agent
    shutil.copytree(source, staged, copy_function=shutil.copy2)
    return staged


def install_login_skill(*, repo_root: Path, home: Path) -> dict[str, str]:
    """정본 login 트리 전체를 세 에이전트 폴더에 멱등·stale-free 설치한다."""
    source = Path(repo_root).resolve() / "skills" / "login"
    home = Path(home).expanduser().resolve()
    # Validate the complete source before touching any agent installation.
    _validate_source_tree(source)

    home.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".login-skill-stage-", dir=home))
    targets = {
        agent: home / hidden_dir / "skills" / "login"
        for agent, hidden_dir in AGENT_DIRS.items()
    }
    staged: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    installed_agents: list[str] = []
    try:
        # Build every replacement first so a copy failure cannot partially
        # update one agent while leaving the others on the previous version.
        for agent in AGENT_DIRS:
            staged[agent] = _staged_tree(source, staging_root, agent)

        try:
            for agent, target in targets.items():
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_symlink():
                    raise ValueError(f"login skill target symlink rejected: {target}")
                if target.exists():
                    backup = target.parent / f".login-backup-{uuid.uuid4().hex}"
                    target.replace(backup)
                    backups[agent] = backup

            for agent, target in targets.items():
                staged[agent].replace(target)
                installed_agents.append(agent)
        except Exception:
            for agent in reversed(installed_agents):
                target = targets[agent]
                if target.exists():
                    shutil.rmtree(target)
            for agent, backup in backups.items():
                if backup.exists():
                    backup.replace(targets[agent])
            raise

        for backup in backups.values():
            shutil.rmtree(backup)
        return {agent: str(target) for agent, target in targets.items()}
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


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
