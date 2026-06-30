from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent
CODEx_AI_SEARCH = Path.home() / ".codex" / "skills" / "ai-search"
CLAUDE_SKILLS = Path.home() / ".claude" / "skills"

# HOME 에 설치된 스킬 파일(~/.codex, ~/.claude)은 사장님 머신에만 있고 CI 러너엔 없다.
# 이 픽스처가 없는 환경에서는 HOME 의존 검사를 skip 한다(레포 내 검사는 항상 수행 — 약화 아님).
_CODEX_AI_SEARCH_PRESENT = (CODEx_AI_SEARCH / "SKILL.md").exists()
_CLAUDE_TALENT_SKILL_PRESENT = (CLAUDE_SKILLS / "talent-search" / "SKILL.md").exists()

REPO_SKILL_DIRS = (
    REPO / "skills" / "search",
    REPO / "skills" / "multisearch",
    REPO / "skills" / "position-registration",
    REPO / "skills" / "humansearch",
)

SKILL_DIRS = REPO_SKILL_DIRS + ((CODEx_AI_SEARCH,) if _CODEX_AI_SEARCH_PRESENT else ())


def _top_level_frontmatter_keys(skill_md: Path) -> set[str]:
    text = skill_md.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"missing frontmatter: {skill_md}"
    end = text.find("\n---", 4)
    assert end != -1, f"unterminated frontmatter: {skill_md}"
    keys: set[str] = set()
    for line in text[4:end].splitlines():
        if not line.strip() or line.startswith((" ", "\t", "-")):
            continue
        if ":" in line:
            keys.add(line.split(":", 1)[0].strip())
    return keys


def test_skill_frontmatter_uses_only_codex_trigger_fields() -> None:
    for skill_dir in SKILL_DIRS:
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.exists(), f"missing skill: {skill_md}"
        assert _top_level_frontmatter_keys(skill_md) == {"name", "description"}


def test_skill_bundled_reference_files_exist_and_are_nonempty() -> None:
    expected_paths = [
        REPO / "skills/search/references/boolean-strategy.md",
        REPO / "skills/search/references/chatgpt-search-cdp-handoff.md",
        REPO / "skills/search/references/clickup-ai-search-channel-fallbacks.md",
        REPO / "skills/search/references/content-ops-settlement-sourcing.md",
        REPO / "skills/search/references/greetinghr-career-page-intake.md",
        REPO / "skills/search/references/harness-engineering-reimplementation.md",
        REPO / "skills/humansearch/humansearch.config.json",
    ]
    # HOME 의존(~/.codex) 참조는 설치된 환경에서만 검사.
    if _CODEX_AI_SEARCH_PRESENT:
        expected_paths += [
            CODEx_AI_SEARCH / "references/spec-procedure.md",
            CODEx_AI_SEARCH / "references/code-map.md",
            CODEx_AI_SEARCH / "scripts/ai_search_sot_check.py",
        ]
    for path in expected_paths:
        assert path.exists(), f"missing referenced file: {path}"
        assert path.stat().st_size > 0, f"empty referenced file: {path}"


def test_no_empty_skill_files() -> None:
    for skill_dir in SKILL_DIRS:
        for path in skill_dir.rglob("*"):
            if path.is_file():
                assert path.stat().st_size > 0, f"empty skill file: {path}"


def test_sot25_uses_current_codex_skill_and_embedded_output_contract() -> None:
    sot25 = json.loads((REPO / "docs/sot/25-ai-search-execution-process.json").read_text(encoding="utf-8"))
    text = json.dumps(sot25, ensure_ascii=False)
    assert "skills/ai-search-position-pipeline" not in text
    assert "~/.claude/skills/ai-search-position-pipeline" not in text
    assert "/Users/kangsangmo/.codex/skills/ai-search/SKILL.md" in text
    assert "tools/multi_position_sourcing/models.py" in text

    output_contract = sot25.get("output_contract")
    assert isinstance(output_contract, dict)
    assert output_contract.get("required_fields") == [
        "profile_url",
        "score",
        "why_fit",
        "profile_summary",
    ]

    human_entry = (REPO / "docs/sot/25-ai-search-execution-process.md").read_text(encoding="utf-8")
    assert "skills/ai-search-position-pipeline" not in human_entry
    assert "profile_url" in human_entry and "profile_summary" in human_entry


def test_sot22_historical_skill_sources_are_explicit_paths() -> None:
    sot22 = json.loads((REPO / "docs/sot/22-talent-search-filters.json").read_text(encoding="utf-8"))
    source = sot22["source_of_truth"]
    assert source["owner_authored_primary"]["file"] == "~/.claude/skills/talent-search/SKILL.md"
    assert source["historical_skill_sources"] == [
        "~/.claude/skills/saramin-talent-sourcing/SKILL.md",
        "~/.claude/skills/jobkorea-talent-sourcing/SKILL.md",
        "~/.claude/skills/linkedin-rps-jd-set-builder/SKILL.md",
    ]
    # 파일 존재 검사는 HOME 스킬이 설치된 환경에서만(레포 외부 ~/.claude 의존 → CI 러너엔 없음).
    if _CLAUDE_TALENT_SKILL_PRESENT:
        for raw_path in (source["owner_authored_primary"]["file"], *source["historical_skill_sources"]):
            assert Path(raw_path).expanduser().exists(), f"missing historical skill source: {raw_path}"

    human_entry = (REPO / "docs/sot/22-talent-search-filters.md").read_text(encoding="utf-8")
    assert "`~/.claude/skills/talent-search/SKILL.md`" in human_entry
    assert "현재 실행 스킬" in human_entry


@pytest.mark.skipif(
    not _CODEX_AI_SEARCH_PRESENT,
    reason="~/.codex/skills/ai-search 미설치 환경(CI) — HOME 픽스처 없음, 설치된 곳에서만 검사",
)
def test_codex_ai_search_reference_no_longer_documents_dead_gap() -> None:
    spec = (CODEx_AI_SEARCH / "references/spec-procedure.md").read_text(encoding="utf-8")
    assert "Known Spec Gaps" not in spec
    assert "skills/ai-search-position-pipeline" not in spec
    assert "PositionMatch" in spec
