#!/usr/bin/env python3
"""aisearch self-containment gate.

aisearch가 자기 폴더(.claude/skills/aisearch) 밖의 HOME 스코프 폴더
(~/.codex/skills/*, 다른 ~/.claude/skills/*)에 런타임 의존하지 않음을 강제한다.

검사:
  1) SKILL.md 본문에 금지 패턴(~/.codex, 다른 ~/.claude 스킬 경로)이 0건.
  2) vendor/ 의 필수 들여온 파일이 존재 + 비어있지 않음.
  3) vendor/SOURCES.json 이 유효한 JSON.

repo-internal 참조(docs/sot/*, tools/*, skills/* 등 같은 레포 경로)는 공유 자산이라
허용한다 — 이 게이트가 막는 건 '레포 밖·다른 머신엔 없을 수 있는' HOME 의존뿐이다.

exit 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
VENDOR = SKILL_DIR / "vendor"

# SKILL.md 에서 금지: HOME 스코프 외부 스킬/코드 폴더 참조.
FORBIDDEN = (
    re.compile(r"~/\.codex/"),
    re.compile(r"~/\.claude/skills/"),
    re.compile(r"/Users/[^/]+/\.codex/"),
    re.compile(r"/Users/[^/]+/\.claude/skills/"),
)

REQUIRED_VENDOR = (
    "ai_search_sot_check.py",
    "linkedin-rps-jd-set-builder.md",
    "SOURCES.json",
)


def main() -> int:
    failures: list[str] = []

    skill_md = SKILL_DIR / "SKILL.md"
    if not skill_md.exists():
        print(f"FAIL missing {skill_md}")
        return 1
    text = skill_md.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pat in FORBIDDEN:
            if pat.search(line):
                failures.append(f"SKILL.md:{line_no} HOME 외부 참조 금지: {line.strip()[:120]}")

    for name in REQUIRED_VENDOR:
        path = VENDOR / name
        if not path.exists():
            failures.append(f"vendor/{name} 없음")
        elif path.stat().st_size == 0:
            failures.append(f"vendor/{name} 비어있음")

    sources = VENDOR / "SOURCES.json"
    if sources.exists():
        try:
            json.loads(sources.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - diagnostics
            failures.append(f"vendor/SOURCES.json JSON 오류: {exc}")

    if failures:
        print("status=FAIL")
        for f in failures:
            print("  - " + f)
        return 1

    print("status=OK aisearch self-contained (HOME 외부 의존 0, vendor 파일 완비)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
