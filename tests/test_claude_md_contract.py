"""CLAUDE.md 계약 검사 — 규칙서가 실제 저장소와 어긋나면 빨개진다.

배경(2026-08-03): 규칙서를 개편하면서 파일 이름만 보고 역할을 적었다가 오분류가 나왔다.
`dedup.py`를 발송 게이트라 적었으나 실제로는 수집 단계 모듈이고 `auto_send.py`는 그 파일을
import조차 하지 않았다. `grouping.py`도 후보가 아니라 채용 포지션을 묶는 모듈이었다.
사람이 눈으로 보고 적은 지도는 반드시 낡는다 — 그래서 기계가 지킨다.

이 검사가 지키는 것:
1. 규칙서가 가리키는 저장소 경로는 전부 실존해야 한다 (죽은 링크 금지).
2. 규칙서가 코드에 대해 주장하는 것은 코드로 반증 가능해야 하고, 실제와 일치해야 한다.
3. 사장님이 약화 금지라 못박은 불변식(말하기 규칙 + 금지선)이 사라지지 않아야 한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CLAUDE_MD = REPO / "CLAUDE.md"
SRC = REPO / "tools" / "multi_position_sourcing"


def _text() -> str:
    assert CLAUDE_MD.is_file(), "CLAUDE.md 가 저장소 루트에 없다"
    return CLAUDE_MD.read_text(encoding="utf-8")


# ── AC-1: 지도가 가리키는 경로는 전부 실존한다 ──────────────────────────────

_BACKTICK = re.compile(r"`([^`\n]+)`")


def _repo_path_candidates(text: str) -> list[str]:
    """규칙서 본문의 백틱 조각 중 '이 저장소 안 경로'로 볼 것만 추린다.

    제외: 홈 경로(~/), 상위 경로(../), 플레이스홀더(<slug> 등), 명령줄(공백 포함).
    """
    out: list[str] = []
    for raw in _BACKTICK.findall(text):
        item = raw.strip()
        if not item or "/" not in item:
            continue
        if item.startswith(("~", "..", "/")) or "<" in item or " " in item:
            continue
        # `scripts/harness/task.sh:10` 처럼 줄번호가 붙은 경우 잘라낸다.
        item = re.split(r":\d", item, maxsplit=1)[0].rstrip(":")
        out.append(item)
    return sorted(set(out))


def test_map_paths_exist() -> None:
    """규칙서가 가리키는 파일·디렉터리가 실제로 있어야 한다."""
    missing = []
    for rel in _repo_path_candidates(_text()):
        if "*" in rel:
            if not list(REPO.glob(rel)):
                missing.append(rel)
        elif not (REPO / rel).exists():
            missing.append(rel)
    assert not missing, f"규칙서가 없는 경로를 가리킨다: {missing}"


def test_map_covers_core_engine() -> None:
    """핵심 엔진 디렉터리가 지도에 있어야 한다 — 없으면 지도가 아니다."""
    assert "tools/multi_position_sourcing/" in _text(), (
        "규칙서에 핵심 엔진 경로가 없다 — 어디에 뭐가 있는지 매번 다시 찾게 된다"
    )


# ── AC-2: 규칙서의 코드 주장은 실제와 일치한다 ──────────────────────────────


def test_auto_send_does_not_import_dedup() -> None:
    """규칙서 주장: 발송 중복 방지는 dedup.py 가 아니라 원장이 한다.

    이 관계가 뒤집히면(= auto_send 가 dedup 을 쓰기 시작하면) 규칙서 설명이 거짓이 되므로
    함께 고쳐야 한다.
    """
    src = (SRC / "auto_send.py").read_text(encoding="utf-8")
    imports_dedup = re.search(r"^\s*(from\s+\.?dedup\s+import|import\s+\.?dedup)", src, re.M)
    assert imports_dedup is None, (
        "auto_send.py 가 dedup.py 를 import 하기 시작했다 — CLAUDE.md 지도 설명을 고쳐야 한다"
    )
    assert "dedupe_window_days" in src, (
        "발송 중복 방지 근거(dedupe_window_days)가 사라졌다 — 지도 설명 재확인 필요"
    )


def test_grouping_groups_positions_not_candidates() -> None:
    """규칙서 주장: grouping.py 는 후보가 아니라 채용 포지션을 묶는다."""
    src = (SRC / "grouping.py").read_text(encoding="utf-8")
    assert "def group_positions(" in src, "grouping.py 의 진입 함수가 바뀌었다"
    assert "def infer_role_family(position" in src, (
        "grouping.py 가 더 이상 Position 을 받지 않는다 — 지도 설명을 고쳐야 한다"
    )


def test_login_barrier_verifies_receipt_rather_than_logging_in() -> None:
    """규칙서 주장: login_barrier.py 는 로그인을 하지 않고 영수증을 검증한다."""
    src = (SRC / "login_barrier.py").read_text(encoding="utf-8")
    assert "receipt" in src.lower(), "login_barrier.py 에서 영수증 검증 흔적이 사라졌다"


def test_claude_p_callsites_listed_in_map() -> None:
    """규칙서가 지목한 LLM 호출부 파일에 실제로 `claude -p` 호출이 있어야 한다."""
    text = _text()
    listed = [name for name in ("llm_keywords.py", "matching_score_contract.py", "fleet_worker.py")
              if name in text]
    assert listed, "규칙서에 LLM 호출부가 하나도 적혀 있지 않다"
    for name in listed:
        src = (SRC / name).read_text(encoding="utf-8")
        assert re.search(r'"claude",\s*"-p"', src) or "claude -p" in src, (
            f"{name} 에 claude -p 호출이 없다 — 규칙서의 호출부 목록이 낡았다"
        )


# ── AC-3: 사장님이 약화 금지라 못박은 불변식이 살아 있다 ────────────────────


@pytest.mark.parametrize(
    ("needle", "why"),
    [
        ("한국어", "0번 규칙(쉬운 한국어로 보고)이 사라졌다"),
        ("자동 로그인", "3사 자동 로그인 금지선(A)이 사라졌다"),
        ("자동 재개", "잠깐 양보·자동 재개 금지선(B)이 사라졌다"),
        ("킬스위치", "자동 발송 게이트 금지선(C)이 사라졌다"),
        ("main", "main 직접 수정 금지선(E)이 사라졌다"),
        ("Codex", "두 번 깨기(독립 2차 검증) 규율이 사라졌다"),
    ],
)
def test_invariants_survive(needle: str, why: str) -> None:
    assert needle in _text(), why


def test_gate_commands_present() -> None:
    """작업 루프 명령이 규칙서 안에 있어야 한다 — 매번 찾아 헤매지 않도록."""
    text = _text()
    for cmd in ("make red-ledger", "make task", "./verify.sh", "make ship"):
        assert cmd in text, f"규칙서에 작업 명령 `{cmd}` 이 없다"


def test_known_traps_documented() -> None:
    """반복해서 물리는 함정이 규칙서에 적혀 있어야 한다."""
    text = _text()
    assert "numpy" in text, "검사 환경에 numpy 가 없다는 함정이 규칙서에 없다"
    assert "ANTHROPIC_API_KEY" in text, "LLM 호출 시 유료 키 제거 규칙이 규칙서에 없다"
    assert "strict-active.json" in text or "make task" in text, (
        "Stop 훅 발동 조건이 규칙서에 없다"
    )
