from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PROMPT = REPO / "docs" / "prompts" / "goal-coding-sot-preflight.md"

REQUIRED_SNIPPETS = (
    "코딩용 Goal Prompt",
    "작업·코딩·브라우저 조작·외부 쓰기 전에 먼저 기존 정의를 회수한다",
    "CLAUDE.md",
    "docs/harness.md",
    "docs/sot/",
    "기존 구현 진입점",
    "새 파일",
    "새 러너",
    "새 등록 스크립트",
    "스펙을 사후에 추가해 현재 행동을 정당화 금지",
    "STOP",
    "Discord",
    "ClickUp",
    "이메일",
    "채용사이트",
    "L3",
    "명시 승인",
    "RED",
    "GREEN",
    "두 번",
)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def test_goal_coding_sot_preflight_prompt_exists_and_is_strict() -> None:
    assert PROMPT.exists(), f"missing coding goal prompt: {PROMPT}"
    text = PROMPT.read_text(encoding="utf-8")
    compact = _squash(text)

    missing = [snippet for snippet in REQUIRED_SNIPPETS if snippet not in text]
    assert not missing, f"prompt lacks required snippets: {missing}"
    assert "추측진행금지" in compact, "prompt must forbid proceeding by guess"
    assert "테스트약화·삭제금지" in compact, "prompt must forbid weakening tests"
