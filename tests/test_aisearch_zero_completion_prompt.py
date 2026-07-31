from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PROMPT = (
    REPO
    / "docs"
    / "prompts"
    / "aisearch-zero-completion-goal-2026-07-31.md"
)


def _text() -> str:
    assert PROMPT.is_file(), f"missing aisearch-zero completion prompt: {PROMPT}"
    return PROMPT.read_text(encoding="utf-8")


def test_prompt_is_self_contained_and_portable() -> None:
    text = _text()
    required = (
        "apps/aisearch-zero",
        "clean clone",
        "두 번째 Mac",
        "doctor",
        "bootstrap",
        "Python 표준 라이브러리",
        "숨은 fallback 금지",
        "절대경로 금지",
        "외부 서비스 write 0건",
    )
    missing = [marker for marker in required if marker not in text]
    assert not missing, f"portable contract markers missing: {missing}"
    forbidden = ("/Users/", "/Volumes/", "~/.claude", "~/.codex", "Valuehire_v4")
    assert not [marker for marker in forbidden if marker in text]


def test_prompt_requires_controller_owned_fail_closed_state() -> None:
    text = _text()
    required = (
        "controller-owned",
        "manifest.json",
        "state.json",
        "final.json",
        "run_id",
        "machine_id",
        "원자적 write",
        "동시 실행",
        "증거 없는 완료 금지",
        "그 외 전부 → 명시적 중단",
    )
    missing = [marker for marker in required if marker not in text]
    assert not missing, f"fail-closed state contract markers missing: {missing}"


def test_prompt_defines_review_product_and_staged_completion() -> None:
    text = _text()
    required = (
        "target_repo",
        "base_revision",
        "review_scope",
        "acceptance_criteria",
        "verification_commands",
        "findings.json",
        "report.md",
        "한 단위 = 인수 기준 1개",
        "별도 이슈",
        "별도 작업 공간",
        "독립 재검토",
        "전체 검사",
        "병합",
    )
    missing = [marker for marker in required if marker not in text]
    assert not missing, f"review product or staged completion markers missing: {missing}"
    assert re.search(r"^## 입력 영역 표$", text, re.MULTILINE)
    assert re.search(r"^## 작업 분해와 순서$", text, re.MULTILINE)
    assert re.search(r"^## 최종 완료 조건$", text, re.MULTILINE)


def test_prompt_forbids_false_completion_and_live_side_effects() -> None:
    compact = re.sub(r"\s+", "", _text())
    required = (
        "runtime-code:none",
        "enforced:false",
        "문서만작성하고완료선언금지",
        "테스트삭제·약화금지",
        "브라우저조작금지",
        "자동발송금지",
        "배포금지",
    )
    missing = [marker for marker in required if marker not in compact]
    assert not missing, f"false-completion or side-effect guards missing: {missing}"
