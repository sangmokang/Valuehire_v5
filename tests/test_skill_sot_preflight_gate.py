from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parent.parent

REPO_SKILLS = (
    REPO / "skills" / "position-registration" / "SKILL.md",
    REPO / "skills" / "humansearch" / "SKILL.md",
)

CUSTOM_SKILLS = (
    Path.home() / ".codex" / "skills" / "ai-search" / "SKILL.md",
)

REQUIRED_SNIPPETS = (
    "## ⛔ 공통 SOT 시작 게이트",
    "CLAUDE.md",
    "docs/harness.md",
    "docs/sot/",
    "기존 구현 진입점",
    "새 파일",
    "새 러너",
    "새 등록 스크립트",
    "STOP",
    "Discord",
    "ClickUp",
    "이메일",
    "채용사이트",
    "L3",
    "명시 승인",
)


def test_all_repo_skills_have_hard_sot_preflight_gate() -> None:
    missing = [path for path in REPO_SKILLS if not path.exists()]
    assert not missing, f"missing skill files: {missing}"

    failures: list[str] = []
    for path in REPO_SKILLS:
        text = path.read_text(encoding="utf-8")
        for snippet in REQUIRED_SNIPPETS:
            if snippet not in text:
                failures.append(f"{path.relative_to(REPO)} lacks {snippet!r}")

    assert not failures, "\n".join(failures)


def test_custom_ai_search_skill_has_hard_sot_preflight_gate() -> None:
    missing = [path for path in CUSTOM_SKILLS if not path.exists()]
    assert not missing, f"missing custom skill files: {missing}"

    failures: list[str] = []
    for path in CUSTOM_SKILLS:
        text = path.read_text(encoding="utf-8")
        for snippet in REQUIRED_SNIPPETS:
            if snippet not in text:
                failures.append(f"{path} lacks {snippet!r}")

    assert not failures, "\n".join(failures)
