"""Harness Gate 4a — 기계 단언 (machine assertions)

대상: 거버넌스 문서 3종
  - CLAUDE.md                                  (SOT 불변식)
  - AGENTS.md                                  (Codex 사용자 브리핑 계약)
  - docs/harness.md                            (게이트 절차)
  - docs/prompts/goal-full-codebase-review.md  (전체 코드 재리뷰 Goal 프롬프트)
  - docs/prompts/fix-107-then-resume-dongtan-ai-search-2026-07-15.md

사장님 지시(2026-06-15)를 SOT/하니스에 '박았는지'를 코드로 고정한다.
세 원리가 문구로 살아있어야 GREEN, 약화/삭제되면 RED.

  P1  불신 원칙        — "내가 만든 코드는 믿지 않는다 → 두 번 깐다"가 SOT 운영 규칙에 존재
  P2  2패스 적대검증   — (1) 작은 기능 단위 자기 적대검증 (2) Codex Rescue 2차 검증
  P3  과거 지시 회수   — 코딩 시작 시 '전에 시킨 것이 이미 있는지' 먼저 점검 (게이트)
  P4  Goal 프롬프트    — 전체 코드 재리뷰 프롬프트가 실존 + 세 원리 + 하니스 게이트 포함
  P5  사용자 브리핑    — 중간·차단·최종 쉬운 보고 + #107/동탄 AI Search 복구 프롬프트

게이트 4b(독립 검증자)의 반복 지적은 4a 로 승격한다(harness 진화 규칙).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLAUDE = REPO / "CLAUDE.md"
AGENTS = REPO / "AGENTS.md"
HARNESS = REPO / "docs" / "harness.md"
GOAL = REPO / "docs" / "prompts" / "goal-full-codebase-review.md"
RECOVERY_PROMPT = (
    REPO / "docs" / "prompts"
    / "fix-107-then-resume-dongtan-ai-search-2026-07-15.md"
)


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


# ── P5 · 모든 사용자 브리핑 + 두 단계 복구 프롬프트 ──────────
def test_p5_all_owner_briefings_and_two_stage_recovery_prompt() -> None:
    """중간·차단·최종 보고와 #107→동탄 검색 복구가 한 계약으로 살아 있어야 한다."""
    agents = AGENTS.read_text(encoding="utf-8")
    compact_agents = _squash(agents)
    semantic_agents = re.sub(r"[*_`]", "", compact_agents)
    compact_harness = _squash(HARNESS.read_text(encoding="utf-8"))

    assert "모든사용자브리핑(중간·차단·최종)" in semantic_agents
    assert "중간·차단보고는1~3문장으로현재상태/이유/다음행동만말한다" in semantic_agents
    assert "내부상태근거와사용자설명은1:1로대조" in semantic_agents
    assert "근거를빼거나과장하지않고" in semantic_agents
    assert "사장님께보이는메시지에는이쉬운보고규칙이우선" in semantic_agents
    for forbidden in ("근거를빼고", "과장해도", "기술형식이우선"):
        assert forbidden not in semantic_agents
    final_sections = (
        "## 1. 뭘 요청받았나", "## 2. 뭘 했나", "## 3. 확인은 어떻게 했나",
        "## 4. 놓친 부분 / 다음에 봐야 할 것", "## 5. 다음 행동",
    )
    assert all(section in agents for section in final_sections), \
        "최종 보고 5칸 실제 템플릿이 모두 있어야 함"
    assert "모든사용자브리핑(중간·차단·최종)" in compact_harness

    assert RECOVERY_PROMPT.exists(), f"복구 프롬프트 부재: {RECOVERY_PROMPT}"
    prompt = RECOVERY_PROMPT.read_text(encoding="utf-8")
    required = (
        "이슈 #107", "검사", "독립 재검토", "PR", "병합 후", "작업 장부",
        "1200초", "180초", "코드 작업용 미완료 장부", "다시 계속 여부를 묻지 않는다",
        "화성·동탄", "사람인", "LinkedIn", "좌측", "위치 필터",
        "상단 전역 검색창은 사용하지 않는다",
        "profile_url", "score", "why_fit", "profile_summary", "발송하지 않는다",
        "내부 상태 근거", "1:1",
    )
    missing = [marker for marker in required if marker not in prompt]
    assert not missing, f"복구 프롬프트 필수 계약 누락: {missing}"
    assert "/Volumes/SSD/Valuehire_v5-owner-yield-3min" not in prompt, \
        "병합 전 과거 작업 공간을 재사용하라는 낡은 지시가 남음"
    assert "/Volumes/SSD/Valuehire_v5-" not in prompt, "기존 보조 작업공간 절대경로 재사용 금지"
    assert "task/owner-yield" not in prompt and "task/linkedin-login-guidance" not in prompt
    assert "git fetch origin main" in prompt
    assert "a090640" in prompt and "PR #117" in prompt
    assert "완료 조건과 읽기 전용 대조가 모두 맞으면 저장소 파일·작업 장부를 수정하지 않고" in prompt
    assert "새 브랜치·커밋·PR을 만들지 않은 채 즉시 2단계" in prompt
    assert "1200초" in prompt and "최소 300초" in prompt and "서로 다른 범위" in prompt
    assert "문서 간 어긋남" in prompt and "최상위 180초 규칙을 따르고" in prompt
    forbidden_send = ("제안을 발송한다", "메일을 발송한다", "InMail을 발송한다", "Send를 누른다")
    assert not [text for text in forbidden_send if text in prompt], "복구 프롬프트가 발송을 지시함"
    forbidden_mutations = (
        "병합 완료여도 새 코드", "새 코드/PR 반드시 생성", "Send 버튼 클릭",
        "계속 여부 재질문", "계속 여부를 다시 묻는다", "기존 보조 작업 공간을 재사용한다",
        "발송 버튼을 클릭한다", "진행할까요?", "사용자에게 다시 확인한다",
    )
    assert not [text for text in forbidden_mutations if text in prompt]
    assert not re.search(r"(?:Send|발송|보내기|제안).{0,12}(클릭|누른다)", prompt)
    reconfirm_scan = prompt.replace("다시 계속 여부를 묻지 않는다", "")
    reconfirm_scan = re.sub(
        r"실제 사람 개입이 필요한 차단 외에는 “계속할까요\?”를\s*묻지 말고",
        "",
        reconfirm_scan,
    )
    assert not re.search(r"(?:진행|계속).{0,12}(물어|묻|확인)", reconfirm_scan)
    stage_one = re.search(r"^## 1단계\b", prompt, re.MULTILINE)
    stage_two = re.search(r"^## 2단계\b", prompt, re.MULTILINE)
    assert stage_one and stage_two and stage_one.start() < stage_two.start(), \
        "#107 마감 뒤 동탄 AI Search를 재개하는 순서여야 함"
    stage_one_body = prompt[stage_one.start():stage_two.start()]
    ordered_stage_one_markers = (
        "완료 증거와 함께 아래 계약",
        "`tests/test_owner_yield_3min.py` 전체 통과",
        "SOT25의 1200초·최소 300초",
        "완료 조건과 읽기 전용 대조가 모두 맞으면",
    )
    marker_positions = [stage_one_body.index(marker) for marker in ordered_stage_one_markers]
    assert marker_positions == sorted(marker_positions), \
        "계약→검사기록→시간차이→무변경 완료 분기 순서가 바뀜"

    executable = re.search(r"```text\n(?P<body>.*?)\n```", prompt, re.DOTALL)
    assert executable, "복구 프롬프트 실행 블록이 없거나 형식이 바뀜"
    executable_sha256 = hashlib.sha256(executable.group("body").encode("utf-8")).hexdigest()
    assert executable_sha256 == "e92126fc7dd65b6fbc28e12d515994314cc1c2fc24168326902f2867479ea5b4", \
        "검증되지 않은 지시 추가·삭제·순서 변경: 실행 프롬프트 계약 해시 불일치"
