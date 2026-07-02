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


# ── V1(Codex 2026-07-03) 적발 결함 회귀봉인 ──
def test_h7_v1_no_korean_substring_false_positive() -> None:
    """'제어판'은 '제어'가 아니다 — 부분문자열 오확장 금지."""
    r = expand_search_terms(["제어판 설계"], "")
    assert "control" not in " ".join(r.expanded).lower() or "제어" in "제어판 설계".split()


def test_h7_v1_short_token_does_not_cover_cpp() -> None:
    """검색어 'c' 가 JD 의 'C++' 을 덮은 척하면 안 됨 — 갭으로 남아야."""
    jd = "자격요건: C++ 능숙"
    r = expand_search_terms(["c"], jd)
    assert any("c++" == m.lower() for m in r.missing), f"C++ 갭 미검출: {r.missing}"


def test_h7_v1_none_input_does_not_crash() -> None:
    """None/비문자 입력은 크래시가 아니라 빈 결과로(fail-safe)."""
    r = expand_search_terms([None, "  "], None)  # type: ignore[list-item, arg-type]
    assert r.expanded == () and r.missing == ()


def test_h7_v1_jd_noise_words_not_core() -> None:
    """'Requirements'·'modern'·'Hard' 같은 잡음은 핵심 키워드가 아니다."""
    jd = "Requirements: modern C++, Hard RTOS 경험"
    r = expand_search_terms(["로봇"], jd)
    low = {t.lower() for t in r.jd_core}
    assert "requirements" not in low and "modern" not in low and "hard" not in low
    assert "c++" in low and "rtos" in low
