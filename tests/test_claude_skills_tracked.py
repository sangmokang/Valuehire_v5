"""레포 안 `.claude/skills/` 가 git에 실제로 추적되는지 지킨다.

`.gitignore` 가 `.claude/` 를 통째로 무시하면, `.claude/skills/` 아래 스킬 파일이
git 밖으로 새어나가 버전관리·CI 보호를 못 받는다(과거 aisearch 가 그렇게 새어나갔다).
동시에 OMC 런타임 상태(`.omc/`)는 머신 전용 쓰레기라 절대 추적되면 안 된다.

이 테스트는 두 가지를 동시에 강제한다:
  1. aisearch 스킬의 핵심 파일은 git 이 추적한다(=커밋되어 CI 가 본다).
  2. `.omc/` 런타임 파일은 git 이 추적하지 않는다(세션 replay 로그 유출 방지).
"""
from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent

AISEARCH = ".claude/skills/aisearch"

MUST_BE_TRACKED = (
    f"{AISEARCH}/SKILL.md",
    f"{AISEARCH}/candidate-output-contract.json",
    f"{AISEARCH}/vendor/SOURCES.json",
    f"{AISEARCH}/vendor/check_self_contained.py",
    f"{AISEARCH}/vendor/ai_search_sot_check.py",
)


def _git_tracked(pathspec: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", pathspec],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def test_aisearch_skill_files_are_git_tracked() -> None:
    for rel in MUST_BE_TRACKED:
        assert _git_tracked(rel), (
            f"스킬 파일이 git 추적 밖에 있음 (gitignore 가 .claude/ 를 통째로 막는 중): {rel}"
        )


def test_omc_runtime_state_is_not_tracked() -> None:
    leaked = _git_tracked(f"{AISEARCH}/.omc/**")
    assert not leaked, f".omc 런타임 상태가 git 에 새어들어감(머신 전용 쓰레기여야 함): {leaked}"
