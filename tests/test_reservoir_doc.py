"""Harness Gate 4a — 기계 단언 (machine assertions)

대상: docs/ai-search/ai-search-reservoir-strategy-2026-06-12.html

산문(prose) 아티팩트는 pytest로 '품질'을 직접 못 잰다. 그래서 *검사 가능한 것*만
기계 단언으로 고정한다. 각 단언은 "일부러 깨면 RED, 실제 문서는 GREEN".

  A1  구조      — DOCTYPE 존재, <div> 개폐 균형, 섹션 수/순서(11) 불변
  A2  근거경로  — 문서가 '근거(이미 있는 것)'로 인용하는 코드경로가 실제로 존재
  A3  앵커      — 끊긴 내부 앵커(href="#..." → 대응 id 부재) 0

게이트 4b(독립 검증자)의 반복 지적은 4a로 '승격'한다(harness 진화 규칙).
아래 셋은 문서의 핵심 사실주장(B1)을 코드 상태에 고정한 것 — 코드가 바뀌어
주장이 거짓이 되면 RED 로 잡는다(escaped-defect 보호):

  A4  grouping.py 의 유사도는 규칙 기반 키 — 벡터/임베딩/코사인 아님
  A5  임베딩/pgvector 벡터 레이어가 embed.py + embeddings.sql 에 구현됨(단계 4) —
      grouping.py 는 여전히 규칙 기반(진화: 이전엔 "아직 없음"을 보호했음)
  A6  session_state 스키마가 3사(saramin/jobkorea/linkedin_rps) 암호화 세션 지속
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOC = REPO / "docs" / "ai-search" / "ai-search-reservoir-strategy-2026-06-12.html"
MPS = REPO / "tools" / "multi_position_sourcing"
SCHEMA = REPO / "docs" / "ai-search" / "session-state-supabase-schema-2026-06-09.sql"

# 문서가 '근거(이미 있는 것 / 재사용)'로 인용하는 코드경로 — 반드시 실존.
# 신규/후속으로 표기된 embed.py·match.py·embeddings.sql 은 제외(제안이지 근거가 아님).
EVIDENCE_PATHS = (
    "tools/multi_position_sourcing/models.py",
    "tools/multi_position_sourcing/grouping.py",
    "tools/multi_position_sourcing/scoring.py",
    "tools/multi_position_sourcing/keywords.py",
    "tools/multi_position_sourcing/queue_runner.py",
    "tools/multi_position_sourcing/portal_queue_executor.py",
    "tools/multi_position_sourcing/portal_worker.py",
    "tools/multi_position_sourcing/portal_recovery.py",
    "tools/multi_position_sourcing/dry_run.py",
    "tools/multi_position_sourcing/selectors.py",
    "docs/ai-search/session-state-supabase-schema-2026-06-09.sql",
    # 저수지 단계 4에서 구현됨 — '신규(아직 없음)' → 실존 근거로 승격.
    "tools/multi_position_sourcing/embed.py",
    "docs/ai-search/embeddings.sql",
)

# 문서가 '신규(아직 없음)'로 명시한 제안 파일 — 실존 단언 대상이 아니다.
# 단계 4에서 embed.py 구현 → FUTURE 에서 제외(EVIDENCE_PATHS 로 이동). match.py 는 단계 5까지 미래.
FUTURE_FILES = frozenset({"match.py"})

EXPECTED_SECTION_IDS = [
    "diagnosis", "pivot", "pipeline", "actors", "machines",
    "vector", "b2c", "roadmap", "metrics", "actions", "close",
]


@pytest.fixture(scope="module")
def html() -> str:
    assert DOC.exists(), f"대상 문서 부재: {DOC}"
    return DOC.read_text(encoding="utf-8")


# ── A1 · 구조 ────────────────────────────────────────────────
def test_a1_doctype_present(html: str) -> None:
    assert re.match(r"\s*<!DOCTYPE html>", html, re.IGNORECASE), "DOCTYPE 선언 부재"


def test_a1_div_balance(html: str) -> None:
    opens = len(re.findall(r"<div\b", html))
    closes = len(re.findall(r"</div>", html))
    assert opens == closes, f"<div> 개폐 불균형: open={opens} close={closes}"


def test_a1_section_count_and_order_invariant(html: str) -> None:
    ids = re.findall(r'<section\s+id="([^"]+)"', html)
    assert ids == EXPECTED_SECTION_IDS, f"섹션 회귀: {ids} != {EXPECTED_SECTION_IDS}"
    opens = len(re.findall(r"<section\b", html))
    closes = len(re.findall(r"</section>", html))
    assert opens == closes == len(EXPECTED_SECTION_IDS), (
        f"<section> 개폐 불균형: open={opens} close={closes}"
    )


# ── A3 · 끊긴 내부 앵커 0 ────────────────────────────────────
def test_a3_no_broken_internal_anchors(html: str) -> None:
    anchors = [a for a in re.findall(r'href="#([^"]*)"', html) if a]
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    broken = sorted({a for a in anchors if a not in ids})
    assert broken == [], f"끊긴 내부 앵커(대응 id 부재): {broken}"


# ── A2 · 근거 코드경로 실존 ──────────────────────────────────
@pytest.mark.parametrize("rel", EVIDENCE_PATHS)
def test_a2_evidence_path_exists(rel: str) -> None:
    assert (REPO / rel).exists(), f"근거 코드경로 부재(끊긴 참조): {rel}"


def test_a2_cited_py_evidence_is_covered(html: str) -> None:
    """자기확장 규칙: 문서가 <code>x.py</code> 로 '근거' 인용한 파일은
    EVIDENCE_PATHS(실존 단언) 에 빠짐없이 들어 있어야 한다. 신규 표기는 제외."""
    cited = set(re.findall(r"<code>([A-Za-z0-9_]+\.py)</code>", html))
    evidence_basenames = {Path(p).name for p in EVIDENCE_PATHS}
    uncovered = sorted(c for c in cited if c not in FUTURE_FILES and c not in evidence_basenames)
    assert not uncovered, f"근거 인용됐으나 실존 단언 없는 .py: {uncovered} (EVIDENCE_PATHS 에 추가하라)"


def test_a2_future_files_are_marked_not_present(html: str) -> None:
    """미구현 제안 파일(embed.py·match.py)은 (1)문서에 등장하고 (2)실제로는 없어야 한다.
    하나라도 실재하면 문서의 '신규/빠진 한 겹' 서술이 거짓이 된 것."""
    for name in FUTURE_FILES:
        assert name in html, f"제안 파일 표기 사라짐: {name}"
        assert not (MPS / name).exists(), (
            f"{name} 가 실재함 — 문서는 이를 '신규(아직 없음)'로 서술 중. 문서 갱신 필요."
        )


# ── A4 · grouping.py 는 규칙 기반 키 — 벡터 아님 (4b B1 → 승격) ──
def test_a4_grouping_is_rule_based_not_vector() -> None:
    src = (MPS / "grouping.py").read_text(encoding="utf-8")
    forbidden = re.findall(r"(?i)\b(pgvector|cosine|embedding|ivfflat|hnsw)\b", src)
    assert not forbidden, (
        "문서 주장: grouping.py 는 '규칙 기반 키이지 벡터가 아니다'. "
        f"그러나 벡터/임베딩 토큰 발견: {forbidden}"
    )
    assert "_similarity_key" in src, "규칙 기반 _similarity_key 함수 부재 — 문서 주장 불성립"


# ── A5 · 임베딩/pgvector 벡터 레이어가 embed.py 에 구현됨 (단계 4 — "빠진 한 겹" 채움) ──
# 진화(harness): 단계 4 이전에는 "벡터 매칭 아직 없음"을 보호했다. 단계 4가 그 레이어를
# embed.py + embeddings.sql 로 구현했으므로, 가드를 뒤집어 "벡터 레이어는 embed.py(+match.py)에만
# 있고 grouping.py 는 여전히 규칙 기반(A4)"을 고정한다.
def test_a5_vector_layer_lives_in_embed_not_grouping() -> None:
    embed = MPS / "embed.py"
    assert embed.exists(), "embed.py 부재 — 단계 4 임베딩 레이어 미구현"
    embed_src = embed.read_text(encoding="utf-8")
    assert "cosine_similarity" in embed_src, "embed.py 에 cosine_similarity 부재 — 벡터 레이어 불성립"
    assert (REPO / "docs" / "ai-search" / "embeddings.sql").exists(), "embeddings.sql(pgvector 스키마) 부재"
    # 벡터화는 embed.py 에만 — grouping.py 는 규칙 기반 유지(A4 가 별도 보증, 여기서도 교차 확인).
    grouping_src = (MPS / "grouping.py").read_text(encoding="utf-8")
    assert not re.search(r"(?i)\b(pgvector|cosine|embedding|ivfflat|hnsw)\b", grouping_src), (
        "grouping.py 가 벡터화됨 — '규칙 기반 키' 주장(A4) 위반"
    )


# ── A6 · session_state 3사 암호화 세션 지속 (4b B1c → 승격) ──
def test_a6_session_state_schema_encrypted_3sites() -> None:
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "public.session_state" in sql, "session_state 테이블 부재"
    for site in ("saramin", "jobkorea", "linkedin_rps"):
        assert site in sql, f"3사 중 '{site}' 누락 — '3사 세션 지속' 주장 불성립"
    assert re.search(r"(?i)encrypt", sql), "암호화(encrypt) 흔적 부재 — '암호화 세션' 주장 불성립"


# ── A7 · SOT 불변식 문구 보존 — 어떤 편집에서도 약화 금지 (4b 구조/red-team → 승격) ──
def test_a7_sot_invariants_present(html: str) -> None:
    c = re.sub(r"\s+", "", html)
    assert "자동로그인" in c and ("막지않는다" in c or "비차단" in c), \
        "SOT(i) 3사 자동로그인 비차단 — 약화/삭제됨"
    assert "R4" in c and ("양보" in c or "정지" in c), \
        "SOT(ii) Chrome 점유 시 무인 워커 즉시 정지(R4 양보) — 약화/삭제됨"
    assert "사람게이트" in c, "SOT(iii) Send 사람 게이트 — 약화/삭제됨"


# ── A8 · 3사 표기 일관성 — 마스트헤드 범위 축소가 SOT 3사와 어긋나지 않게 (4b → 승격) ──
def test_a8_three_sites_named(html: str) -> None:
    for site in ("사람인", "잡코리아", "링크드인"):
        assert site in html, f"3사 중 '{site}' 미표기 — 마스트헤드/SOT 3사 일관성 회귀"
