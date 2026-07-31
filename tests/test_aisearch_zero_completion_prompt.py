from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PROMPT = REPO / "docs/prompts/aisearch-zero-completion-goal-2026-07-31.md"
SECTIONS = {
    "실행 지시": ("본문 자체가 실행 계약", "make red-ledger", "make task NAME="),
    "먼저 읽고 회수할 것": ("재발 원장", "저장소 밖의 필수 근거가 없으면"),
    "제품 목표": ("controller-owned", "manifest.json", "state.json", "final.json"),
    "입력 영역 표": ("동시 실행", "그 외 전부 → 명시적 중단"),
    "작업 분해와 순서": ("한 단위 = 인수 기준 1개", "다른 도구"),
    "기계 검증": ("./verify.sh", "정적 검사와 동적 차단", "외부 호출 횟수 0"),
    "독립 재검토": ("1차 자기 반증", "2차 독립 검토", "다른 도구"),
    "최종 완료 조건": ("proofs/portability.json", "안정 해시", "기본 브랜치에 병합"),
    "최종 보고": tuple(f"## {number}." for number in range(1, 6)),
}
FORBIDDEN = (
    "/Users/", "/Volumes/", "/opt/", "/tmp/", "/private/", "$HOME/", "~/",
    "~/.claude", "~/.codex", "Valuehire_v4", "로컬 검사만으로 완료를 선언",
    "이 문서는 강제력이 없습니다",
)


def _text() -> str:
    assert PROMPT.is_file(), f"missing prompt: {PROMPT}"
    return PROMPT.read_text(encoding="utf-8")


def _section(text: str, name: str) -> str:
    match = re.search(
        rf"^## {re.escape(name)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    return match.group(1) if match else ""


def _contract_errors(text: str) -> list[str]:
    errors = []
    for name, markers in SECTIONS.items():
        body = _section(text, name)
        if not body:
            errors.append(f"missing section: {name}")
        errors.extend(f"{name}: {marker}" for marker in markers if marker not in body)
    errors.extend(f"forbidden: {marker}" for marker in FORBIDDEN if marker in text)
    return errors


def test_prompt_has_structured_fail_closed_contract() -> None:
    text = _text()
    assert not _contract_errors(text), _contract_errors(text)
    compact = re.sub(r"\s+", "", text)
    for marker in (
        "runtime-code:none", "enforced:false", "문서만작성하고완료선언금지",
        "테스트삭제·약화금지", "증거없는완료금지", "브라우저조작금지",
        "자동발송금지", "배포금지",
    ):
        assert marker in compact, marker


def test_prompt_defines_portable_review_product_and_proof() -> None:
    text = _text()
    for marker in (
        "apps/aisearch-zero", "target_repo", "base_revision", "review_scope",
        "acceptance_criteria", "verification_commands", "findings.json", "report.md",
        "run_id", "machine_id", "원자적 write", "Python 표준 라이브러리",
        "clean clone", "두 번째 Mac", "doctor", "bootstrap", "추적되는 증거",
        "manifest.md", "manifest.schema.json", "숨은 fallback 금지", "절대경로 금지",
    ):
        assert marker in text, marker
    for relative in ("CLAUDE.md", "AGENTS.md", "docs/harness.md",
                     "docs/sot/30-strict-mode-contract.md"):
        assert (REPO / relative).is_file(), relative


def test_contract_checker_rejects_deleted_gate_and_fail_open_mutation() -> None:
    text = _text()
    without_machine_checks = re.sub(
        r"^## 기계 검증\n.*?(?=^## |\Z)", "", text, flags=re.MULTILINE | re.DOTALL
    )
    assert _contract_errors(without_machine_checks)
    fail_open = text.replace(
        "두 번째 Mac 검증 불가 | 로컬 검사는 남기되 휴대 가능 완료 선언 금지",
        "두 번째 Mac 검증 불가 | 로컬 검사만으로 완료를 선언합니다",
    )
    assert _contract_errors(fail_open)
