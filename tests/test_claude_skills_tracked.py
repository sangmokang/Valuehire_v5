"""레포 안 `.claude/skills/` 가 git에 실제로 추적되는지 지킨다.

`.gitignore` 가 `.claude/` 를 통째로 무시하면, `.claude/skills/` 아래 스킬 파일이
git 밖으로 새어나가 버전관리·CI 보호를 못 받는다(과거 aisearch 가 그렇게 새어나갔다).
동시에 OMC 런타임 상태(`.omc/`)는 머신 전용 쓰레기라 절대 추적되면 안 된다.

이 테스트는 세 가지를 동시에 강제한다:
  1. pull 직후 Claude Code 가 읽는 repo-local `.claude/skills/*/SKILL.md` 묶음이 있다.
  2. 모든 repo-local Claude skill 파일은 git 이 추적한다(=커밋되어 CI 가 본다).
  3. `.omc/` 런타임 파일과 local settings 는 git 이 추적하지 않는다.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent

CLAUDE_SKILLS = REPO / ".claude" / "skills"

AISEARCH = ".claude/skills/aisearch"
MUST_BE_TRACKED = (
    f"{AISEARCH}/SKILL.md",
    f"{AISEARCH}/candidate-output-contract.json",
    f"{AISEARCH}/vendor/SOURCES.json",
    f"{AISEARCH}/vendor/check_self_contained.py",
    f"{AISEARCH}/vendor/ai_search_sot_check.py",
)

REQUIRED_PORTABLE_SKILLS = {
    "aisearch",
    "humansearch",
    "url",
    "talent-search",
    "saramin-talent-sourcing",
    "jobkorea-talent-sourcing",
    "linkedin-rps-jd-set-builder",
    "harness",
}


def _git_tracked(pathspec: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", pathspec],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def test_project_local_claude_skills_are_present_for_pull_and_use() -> None:
    skill_files = sorted(CLAUDE_SKILLS.glob("*/SKILL.md"))
    names = {p.parent.name for p in skill_files}
    assert len(skill_files) >= 40
    assert REQUIRED_PORTABLE_SKILLS <= names


def test_all_project_local_claude_skill_files_are_git_tracked() -> None:
    skill_files = sorted(CLAUDE_SKILLS.glob("*/SKILL.md"))
    assert skill_files
    for path in skill_files:
        rel = path.relative_to(REPO).as_posix()
        assert _git_tracked(rel), f"Claude skill 이 git 추적 밖에 있음: {rel}"


def test_aisearch_skill_files_are_git_tracked() -> None:
    for rel in MUST_BE_TRACKED:
        assert _git_tracked(rel), (
            f"스킬 파일이 git 추적 밖에 있음 (gitignore 가 .claude/ 를 통째로 막는 중): {rel}"
        )


def test_omc_runtime_state_is_not_tracked() -> None:
    leaked = _git_tracked(f"{AISEARCH}/.omc/**")
    assert not leaked, f".omc 런타임 상태가 git 에 새어들어감(머신 전용 쓰레기여야 함): {leaked}"


def test_local_claude_settings_are_not_tracked() -> None:
    leaked = []
    for rel in (".claude/settings.local.json", ".claude/scheduled_tasks.lock"):
        leaked.extend(_git_tracked(rel))
    assert not leaked, f"머신 전용 Claude local 설정이 git 에 새어들어감: {leaked}"
