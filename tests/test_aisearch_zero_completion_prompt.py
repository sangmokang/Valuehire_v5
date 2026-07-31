from __future__ import annotations

import hashlib
import re
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
PROMPT = REPO / "docs/prompts/aisearch-zero-completion-goal-2026-07-31.md"
EXPECTED_SHA256 = "pending-independent-review"
SECTIONS = {
    "실행 지시": ("본문 자체가 실행 계약", "make red-ledger", "make task NAME="),
    "먼저 읽고 회수할 것": ("재발 원장", "저장소 밖의 필수 근거가 없으면", "선행 이슈 `#255`(엄격 재발 근거 휴대성)"),
    "제품 목표": ("controller-owned", "manifest.json", "state.json", "final.json", "proofs/portability.json", "proofs/external-effects.json"),
    "입력 영역 표": ("동시 실행", "두 번째 Mac 검증 불가 | 로컬 검사는 남기되 휴대 가능 완료 선언 금지", "그 외 전부 → 명시적 중단"),
    "작업 분해와 순서": ("한 단위 = 인수 기준 1개", "다른 도구"),
    "기계 검증": ("./verify.sh", "정적 검사와 동적 차단", "외부 호출 횟수 0", "두 기계 대조 증거", "안정 해시를 대조", "proofs/portability.json`에 커밋"),
    "독립 재검토": ("1차 자기 반증", "2차 독립 검토", "다른 도구"),
    "최종 완료 조건": (
        "1. 모든 파일이 저장소에 추적되고 clean clone에서 실행됩니다.", "2. CLI 여섯 명령이 도움말과 실제 동작 검사를 통과합니다.",
        "3. manifest·state·findings·final schema가 유효하고 controller만 최종본을 씁니다.", "4. 누락·손상·충돌·동시성·부분 쓰기·재시도 검사가 모두 통과합니다.",
        "5. 관련 검사와 전체 검사가 통과하고 테스트 약화가 0건입니다.", "6. 1차 자기 반증과 다른 도구의 2차 독립 검토 지적이 재현·해소됐습니다.",
        "7. clean clone과 두 번째 Mac의 추적되는 증거 `proofs/portability.json`과 안정 해시가 일치합니다.",
        "8. `proofs/external-effects.json`이 외부 서비스 write, 브라우저 조작, 발송, 배포 0건을 증명합니다.",
        "9. 모든 변경이 검토 요청과 자동 검사를 통과해 기본 브랜치에 병합됐습니다.",
    ),
    "최종 보고": (
        "## 1. 뭘 요청받았나 (한 문장)", "## 2. 뭘 했나 (사람 말로, 불릿 3~5개)",
        "## 3. 확인은 어떻게 했나 (검증 — 쉬운 말로)",
        "## 4. 놓친 부분 / 다음에 봐야 할 것 (있으면)",
        "## 5. 다음 행동 (사장님이 뭘 해야 하는지)",
    ),
}
FORBIDDEN = ("$HOME", "${HOME}", "%USERPROFILE%", "~/", "~/.claude", "~/.codex", "Valuehire_v4", "이 문서는 강제력이 없습니다")
ABSOLUTE_PATH = re.compile(r"(?<![.\w])(?:/(?!/)[^\s`|]+|[A-Za-z]:\\|\\\\)")


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
        headings = re.findall(rf"^## {re.escape(name)}.*$", text, re.MULTILINE)
        if not body or headings != [f"## {name}"]:
            errors.append(f"missing or duplicate section: {name}")
        errors.extend(f"{name}: {marker}" for marker in markers if marker not in body)
    errors.extend(f"forbidden: {marker}" for marker in FORBIDDEN if marker in text)
    errors.extend(f"absolute path: {match.group()}" for match in ABSOLUTE_PATH.finditer(text))
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
        "proofs/external-effects.json",
        "manifest.md", "manifest.schema.json", "숨은 fallback 금지", "절대경로 금지",
    ):
        assert marker in text, marker
    for relative in ("CLAUDE.md", "AGENTS.md", "docs/harness.md",
                     "docs/sot/30-strict-mode-contract.md"):
        assert (REPO / relative).is_file(), relative


def test_prompt_matches_independently_reviewed_snapshot() -> None:
    digest = hashlib.sha256(_text().encode("utf-8")).hexdigest()
    assert digest == EXPECTED_SHA256
