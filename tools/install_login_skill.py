"""`login` 스킬을 Claude, Codex, Hermes의 로컬 스킬 폴더에 동일하게 설치한다."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


AGENT_DIRS = {
    "claude": ".claude",
    "codex": ".codex",
    "hermes": ".hermes",
}
REQUIRED_FILES = ("SKILL.md", "browser-control-contract.json")


def install_login_skill(*, repo_root: Path, home: Path) -> dict[str, str]:
    """정본 두 파일만 세 에이전트의 `skills/login`에 멱등 설치한다."""
    source = Path(repo_root).resolve() / "skills" / "login"
    home = Path(home).expanduser().resolve()
    for name in REQUIRED_FILES:
        path = source / name
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"login skill source missing or empty: {path}")

    installed: dict[str, str] = {}
    for agent, hidden_dir in AGENT_DIRS.items():
        target = home / hidden_dir / "skills" / "login"
        target.mkdir(parents=True, exist_ok=True)
        for name in REQUIRED_FILES:
            src = source / name
            dst = target / name
            tmp = target / f".{name}.tmp"
            shutil.copyfile(src, tmp)
            tmp.replace(dst)
        installed[agent] = str(target)
    return installed


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
