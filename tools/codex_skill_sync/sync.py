"""Claude 저작 스킬을 Codex(`$CODEX_HOME/skills`)로 미러링하는 재실행 가능한 동기화 도구.

계약: docs/engineering/codex-skill-sync-goal-2026-07-07.md
안전 원칙:
- dest 의 `.`(dot) 자식(`.system` 등)은 절대 건드리지 않는다.
- 관리하는 스킬 디렉토리 하나(dest/<name>)만 미러하며, 그 밖으로 나가지 않는다.
- 손이식된 별칭(strict/aisearch/weekly-update)은 기본 skip — Codex 의 st/ai-search/weekly 보존.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

# Codex 에 이미 이름을 바꿔 손이식한 스킬 → 기본 skip (덮어쓰기 방지)
ADAPTED_ALIASES = {
    "strict": "st",
    "aisearch": "ai-search",
    "weekly-update": "weekly",
}

# Codex 에 그 도구가 없어 절반만 도는 스킬을 표시하기 위한 Claude 전용 마커
CLAUDE_ONLY_MARKERS = (
    "claude-in-chrome",
    "mcp__",
    "Task(",
    "subagent",
    "oh-my-claudecode",
    "Skill 툴",
    "Skill tool",
)

# 복사에서 제외할 잡음
_IGNORE_PATTERNS = shutil.ignore_patterns(
    ".git", "node_modules", "__pycache__", ".pytest_cache", "*.pyc"
)


def _ignore(dirpath, names):
    """잡음 글롭 + 모든 심볼릭 링크를 복사 대상에서 제외.

    심볼릭 링크(특히 자기참조 loop→.)를 dest 로 옮기면 Codex 가 그 폴더를 훑을 때
    무한 재귀로 터질 수 있다. 실제 스킬 폴더엔 링크가 없으므로 제외해도 손실 없음.
    """
    ignored = set(_IGNORE_PATTERNS(dirpath, names))
    for n in names:
        if os.path.islink(os.path.join(dirpath, n)):
            ignored.add(n)
    return ignored


def _classify(skill_md: Path) -> str:
    """SKILL.md 본문에 Claude 전용 도구 마커가 있으면 partial, 없으면 full."""
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "full"
    return "partial" if any(m in text for m in CLAUDE_ONLY_MARKERS) else "full"


def _mirror(src_dir: Path, dst_dir: Path) -> None:
    """dst_dir 를 src_dir 로 깨끗이 미러(재실행 시 stale 제거). dst_dir 하위만 건드림.

    _ignore 가 심볼릭 링크를 전부 제외하므로 링크를 따라가지 않는다
    (자기참조 loop→. 를 따라가다 무한재귀로 전체 동기화가 죽는 것도, 그 링크를 dest 로
    옮겨 Codex 쪽에서 터지는 것도 막음 — V1 결함).
    """
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src_dir, dst_dir, ignore=_ignore)


def sync_skills(
    sources,
    dest,
    *,
    force_aliases: bool = False,
    dry_run: bool = False,
) -> dict:
    """Claude 스킬 소스들을 dest 로 동기화한다. 반환은 goal 문서의 계약 참조."""
    dest = Path(dest)
    copied: list[str] = []
    skipped: list[list[str]] = []
    collisions: list[list[str]] = []
    classification: dict[str, str] = {}
    claimed: dict[str, str] = {}  # name -> 이긴 skill 디렉토리 경로

    for source in sources:
        source = Path(source)
        if not source.is_dir():
            continue
        for child in sorted(source.iterdir()):
            name = child.name
            if name.startswith("."):
                continue  # .system 등 dot 디렉토리는 대상 아님
            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue

            # 별칭 skip
            if name in ADAPTED_ALIASES and not force_aliases:
                if name not in {s[0] for s in skipped}:
                    skipped.append(
                        [name, f"codex 손이식본 존재({ADAPTED_ALIASES[name]}) — 보존"]
                    )
                continue

            # 충돌: 먼저 온 source 가 이김
            if name in claimed:
                collisions.append([name, claimed[name], str(source)])
                continue
            claimed[name] = str(child)

            classification[name] = _classify(skill_md)
            copied.append(name)

            if not dry_run:
                target = dest / name
                # 가드: 관리 대상은 반드시 dest 바로 아래의 non-dot 디렉토리
                resolved = target.resolve()
                if resolved.parent != dest.resolve() or name.startswith("."):
                    raise ValueError(f"unsafe target rejected: {target}")
                dest.mkdir(parents=True, exist_ok=True)
                _mirror(child, target)

    return {
        "copied": copied,
        "skipped": skipped,
        "collisions": collisions,
        "classification": classification,
        "provenance": dict(claimed),
    }


def default_sources(
    repo_root: Path | None = None,
    *,
    v4_root: Path | None = None,
    home: Path | None = None,
) -> list[Path]:
    """v5/v4 정본과 전역 fallback을 결정적 우선순위로 반환.

    현재 v5의 Codex-native ``skills``를 가장 먼저 두고, v4의 완전한
    ``.codex/skills``를 Claude adapter보다 먼저 둔다. 사용자 전역 스킬은
    두 버전에 없는 이름만 채우는 마지막 fallback이다.
    """
    home = Path.home() if home is None else Path(home)
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    if v4_root is None:
        configured = (os.environ.get("VALUEHIRE_V4_REPO") or "").strip()
        v4_root = Path(configured) if configured else root.parent / "valuehire_v4"
    else:
        v4_root = Path(v4_root)
    return [
        root / "skills",
        root / ".claude" / "skills",
        v4_root / ".codex" / "skills",
        v4_root / ".claude" / "skills",
        v4_root / "tools",
        home / ".claude" / "skills",
    ]


def default_dest() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home) if codex_home else Path.home() / ".codex"
    return base / "skills"


def _main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Claude 스킬을 Codex(~/.codex/skills)로 동기화"
    )
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 계획만 출력")
    parser.add_argument(
        "--force-aliases",
        action="store_true",
        help="strict/aisearch/weekly-update 도 강제 복사(손이식본 덮어씀)",
    )
    parser.add_argument("--dest", default=None, help="대상 폴더(기본 ~/.codex/skills)")
    args = parser.parse_args(argv)

    dest = Path(args.dest) if args.dest else default_dest()
    res = sync_skills(
        default_sources(),
        dest,
        force_aliases=args.force_aliases,
        dry_run=args.dry_run,
    )

    full = [n for n, c in res["classification"].items() if c == "full"]
    partial = [n for n, c in res["classification"].items() if c == "partial"]
    mode = "(모의실행) " if args.dry_run else ""
    print(f"{mode}Codex 동기화 대상: {dest}")
    print(f"  복사: {len(res['copied'])}개")
    print(f"    - Codex 완전동작(full): {len(full)}개")
    print(f"    - 부분동작(partial, Claude 도구 필요): {len(partial)}개")
    if partial:
        print(f"      {', '.join(sorted(partial))}")
    if res["skipped"]:
        print(f"  건너뜀: {len(res['skipped'])}개")
        for name, reason in res["skipped"]:
            print(f"    - {name}: {reason}")
    if res["collisions"]:
        print(f"  이름충돌(먼저 온 소스 사용): {len(res['collisions'])}개")
        for name, kept, dropped in res["collisions"]:
            print(f"    - {name}: 사용={kept}  무시={dropped}")
    if not args.dry_run:
        print("완료. Codex 를 재시작하면 새 스킬을 인식합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
