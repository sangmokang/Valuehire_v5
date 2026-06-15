"""Harness Gate 4a — 기계 단언 (machine assertions)

대상: 거버넌스 문서 3종
  - CLAUDE.md                                  (SOT 불변식)
  - docs/harness.md                            (게이트 절차)
  - docs/prompts/goal-full-codebase-review.md  (전체 코드 재리뷰 Goal 프롬프트)

사장님 지시(2026-06-15)를 SOT/하니스에 '박았는지'를 코드로 고정한다.
세 원리가 문구로 살아있어야 GREEN, 약화/삭제되면 RED.

  P1  불신 원칙        — "내가 만든 코드는 믿지 않는다 → 두 번 깐다"가 SOT 운영 규칙에 존재
  P2  2패스 적대검증   — (1) 작은 기능 단위 자기 적대검증 (2) Codex Rescue 2차 검증
  P3  과거 지시 회수   — 코딩 시작 시 '전에 시킨 것이 이미 있는지' 먼저 점검 (게이트)
  P4  Goal 프롬프트    — 전체 코드 재리뷰 프롬프트가 실존 + 세 원리 + 하니스 게이트 포함

게이트 4b(독립 검증자)의 반복 지적은 4a 로 승격한다(harness 진화 규칙).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLAUDE = REPO / "CLAUDE.md"
HARNESS = REPO / "docs" / "harness.md"
GOAL = REPO / "docs" / "prompts" / "goal-full-codebase-review.md"


def _squash(text: str) -> str:
    """공백·줄바꿈을 제거해 '문구가 살아있는가'만 본다(서식 변동에 강함)."""
    return re.sub(r"\s+", "", text)


# ── P1 · 불신 원칙이 SOT(CLAUDE.md)에 박혀 있다 ──────────────
def test_p1_distrust_principle_in_sot() -> None:
    c = _squash(CLAUDE.read_text(encoding="utf-8"))
    assert "믿지않는다" in c or "믿지말고" in c, \
        "SOT 불신 원칙('내 코드를 믿지 않는다') 문구 부재/약화"
    assert "두번깐다" in c or "두번검증" in c or "적대적" in c, \
        "SOT '두 번 깐다(적대적 검증)' 문구 부재/약화"


def test_p1_distrust_is_numbered_invariant() -> None:
    """불신 원칙은 '운영 규칙' 번호 목록에 SOT 불변식으로 들어가야 한다(약화 금지)."""
    text = CLAUDE.read_text(encoding="utf-8")
    assert "SOT 불변식" in text, "SOT 불변식 섹션 부재"
    # 기존 4개 + 신규 1개 = 최소 5개 번호 규칙
    numbered = re.findall(r"^\s*\d+\.\s+\*\*", text, re.MULTILINE)
    assert len(numbered) >= 5, f"운영 규칙 번호 항목이 5개 미만({len(numbered)}) — 신규 불변식 미추가"


# ── P2 · 2패스 적대검증 (자기 → Codex Rescue) ───────────────
def test_p2_two_pass_in_sot() -> None:
    c = _squash(CLAUDE.read_text(encoding="utf-8"))
    assert "CodexRescue" in c, "SOT 에 'Codex Rescue' 2차 검증자 명시 부재"
    assert "작은기능단위" in c or "작은단위" in c or "기능단위" in c, \
        "SOT 에 '작은 기능 단위' 자기검증 문구 부재"


def test_p2_two_pass_operationalized_in_harness() -> None:
    """harness 게이트 4b 가 2패스(자기 적대검증 + Codex Rescue 독립검증)로 구체화돼야 한다."""
    h = HARNESS.read_text(encoding="utf-8")
    hs = _squash(h)
    assert "Codex Rescue" in h, "harness 4b 에 Codex Rescue 명시 부재"
    assert "자기적대검증" in hs or "자기검증" in hs or "스스로반증" in hs, \
        "harness 4b 에 '자기 적대검증(스스로 반증)' 단계 부재"


# ── P3 · 과거 지시 회수가 게이트로 박혀 있다 ─────────────────
def test_p3_prior_intent_recall_gate_in_harness() -> None:
    h = HARNESS.read_text(encoding="utf-8")
    hs = _squash(h)
    assert "과거지시" in hs or "기존지시" in hs or "이미있는지" in hs, \
        "harness 에 '과거 지시 회수(이미 있는지 점검)' 게이트 부재"
    # 어디를 뒤지는지 — 메모리/코드/스킬·문서 중 최소 2축 명시
    axes = sum(kw in hs for kw in ("memory", "메모리", "grep", "코드베이스", "스킬", "기존코드"))
    assert axes >= 2, f"과거 지시 회수의 탐색 대상(메모리/코드/스킬)이 2축 미만({axes})"


def test_p3_prior_intent_recall_in_sot() -> None:
    c = _squash(CLAUDE.read_text(encoding="utf-8"))
    assert "전에" in c and ("시킨" in c or "지시" in c or "명령" in c), \
        "SOT 에 '전에 시킨 것 먼저 점검' 문구 부재"


# ── P4 · Goal 프롬프트 실존 + 세 원리 + 하니스 게이트 ────────
def test_p4_goal_prompt_exists() -> None:
    assert GOAL.exists(), f"Goal 프롬프트 부재: {GOAL}"


def test_p4_goal_prompt_contains_three_principles() -> None:
    g = GOAL.read_text(encoding="utf-8")
    gs = _squash(g)
    assert "Codex Rescue" in g, "Goal 프롬프트에 Codex Rescue 2차 검증 부재"
    assert "적대적" in gs, "Goal 프롬프트에 적대적 검증 부재"
    assert "과거지시" in gs or "이미있는지" in gs or "기존지시" in gs, \
        "Goal 프롬프트에 과거 지시 회수 부재"
    assert "TDD" in g or "RED" in g, "Goal 프롬프트에 TDD/RED 원칙 부재"


def test_p4_goal_prompt_references_harness_gates() -> None:
    """Goal 프롬프트는 임의 리뷰가 아니라 하니스 게이트(0~6) 위에서 돈다."""
    g = GOAL.read_text(encoding="utf-8")
    gs = _squash(g)
    assert "게이트" in gs or "harness" in gs.lower() or "하니스" in gs, \
        "Goal 프롬프트가 harness 게이트를 참조하지 않음"
    assert "verify" in g or "RED" in g, "Goal 프롬프트가 verify/RED 게이트 미참조"


def test_p4_goal_prompt_no_auto_send() -> None:
    """SOT 불변식: 전체 재리뷰 중에도 자동 발송 금지가 유지돼야 한다."""
    gs = _squash(GOAL.read_text(encoding="utf-8"))
    assert "자동발송" in gs and ("금지" in gs or "않는다" in gs), \
        "Goal 프롬프트에 '자동 발송 금지' 안전장치 부재"
