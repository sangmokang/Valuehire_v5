"""H7 (2026-07-03 사장님) — 서치 후 검색어 확장·갭 점검 (RED 먼저).

사장님 검색어를 한↔영·띄어쓰기 변형으로 확장하고, JD 핵심 키워드 중
사장님 검색어(+확장)가 못 덮는 것(missing)을 찾아 재검색 후보를 만든다.
"""
from __future__ import annotations

from tools.multi_position_sourcing.humansearch_keyword_expand import (
    expand_search_terms,
)


def test_h7_ko_en_bidirectional_expansion() -> None:
    """한→영, 영→한 양방향 확장."""
    r = expand_search_terms(["로봇 제어"], "")
    joined = " ".join(r.expanded).lower()
    assert "robot" in joined and "control" in joined
    r2 = expand_search_terms(["Product Manager"], "")
    assert any("프로덕트 매니저" in t or "기획" in t for t in r2.expanded)


def test_h7_spacing_variants() -> None:
    """띄어쓰기 변형 — '머신 러닝'↔'머신러닝' 양쪽 생성."""
    r = expand_search_terms(["머신 러닝"], "")
    assert "머신러닝" in r.expanded
    r2 = expand_search_terms(["머신러닝"], "")
    assert "머신 러닝" in r2.expanded


def test_h7_missing_jd_core_keywords_detected() -> None:
    """JD 필수 키워드 중 사장님 검색어(+확장)가 못 덮는 것을 missing 으로 보고."""
    jd = "자격요건: SAP FI/CO 모듈 경험, K-IFRS 이해, 재무 회계 도메인. 우대: ontology 기반 워크플로우"
    r = expand_search_terms(["Product Manager"], jd)
    low = " ".join(r.missing).lower()
    assert "sap" in low, f"SAP 갭 미검출: {r.missing}"
    assert r.research_queries, "재검색 후보가 비어 있으면 안 됨"


def test_h7_covered_keywords_not_missing() -> None:
    """사장님 검색어가 이미 덮는 키워드는 missing 에 들어가면 안 됨(과잉 경보 금지)."""
    jd = "자격: 로봇 제어 경험, C++ 능숙"
    r = expand_search_terms(["robot control", "C++"], jd)
    low = " ".join(r.missing).lower()
    assert "robot" not in low and "c++" not in low


def test_h7_empty_inputs_fail_closed() -> None:
    """빈 입력은 조용한 성공이 아니라 빈 결과 + missing 없음(추측 금지)."""
    r = expand_search_terms([], "")
    assert r.expanded == () and r.missing == () and r.research_queries == ()
