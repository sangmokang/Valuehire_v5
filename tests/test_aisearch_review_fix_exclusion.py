"""2026-07-31 전수 리뷰 — H2 제외어 스캔 범위 (U4).

goal: docs/engineering/aisearch-review-fix-goal-2026-07-31.md

결함: 제외어 매칭을 후보 payload **전체**에서 재귀 스캔해, JD 공통 텍스트
(draft_inputs 의 jd_summary·briefing_elements)에 제외어가 한 번만 들어 있어도
그 채널의 **모든 후보**가 제외됐다. 제외어는 후보를 거르는 장치지 JD 를 거르는
장치가 아니다.

계약: 스캔 범위 = 후보 고유 필드(record 의 경력·학력·프로필 + score_payload 의
점수 근거 evidence). draft_inputs 는 스캔하지 않는다.
"""
from __future__ import annotations

from apps.aisearch.core.orchestrator import (
    EXCLUSION_SCAN_ROOTS,
    _find_exclusion_match,
)


def _cand(*, record_extra=None, evidence="기구설계 10년 근거", draft_text="일반 JD 요약"):
    record = {
        "profile_url": "https://linkedin.com/in/x",
        "why_fit": "필수요건 충족",
        "profile_summary": "기구설계 10년",
        "education": "서울 소재 4년제",
        "career_brief": "현대로템 파트리더",
        "saved_profile_evidence": "manifest: /m.json | screenshot_sha256: " + "c" * 64,
    }
    if record_extra:
        record.update(record_extra)
    return {
        "score_payload": {"score": 88, "dimensions": {"D3": {"evidence": evidence}}},
        "record": record,
        "draft_inputs": {
            "jd_summary": draft_text,
            "briefing_elements": [draft_text, "매출 300억"],
        },
    }


def test_h2_scan_roots_exclude_jd_common_text():
    # V1 3라운드 이후: 최상위 뿌리는 record 하나이고, score_payload 는 evidence 칸만,
    # draft_inputs 는 후보 고유 칸(candidate_*)만 훑는다.
    assert "draft_inputs" not in EXCLUSION_SCAN_ROOTS
    assert set(EXCLUSION_SCAN_ROOTS) == {"record"}


def test_h2_jd_text_containing_exclusion_does_not_exclude_a_clean_candidate():
    """counter-AC: JD 에 '인턴' 포함 + 정상 후보 → 제외 0."""
    cand = _cand(draft_text="인턴 채용은 별도 트랙입니다")
    assert _find_exclusion_match(cand, ["인턴"]) is None


def test_h2_candidate_career_containing_exclusion_is_excluded():
    """counter-AC: 후보 경력에 '인턴' → 제외 1."""
    cand = _cand(record_extra={"career_brief": "A사 인턴 6개월"})
    matched = _find_exclusion_match(cand, ["인턴"])
    assert matched is not None
    term, path = matched
    assert term == "인턴"
    assert path.startswith("candidate.record")


def test_h2_score_evidence_is_still_scanned():
    cand = _cand(evidence="인턴 경험 위주")
    matched = _find_exclusion_match(cand, ["인턴"])
    assert matched is not None
    assert matched[1].startswith("candidate.score_payload")


def test_h2_no_exclusions_matches_nothing():
    assert _find_exclusion_match(_cand(), []) is None


def test_h2_casefold_partial_match_preserved():
    cand = _cand(record_extra={"profile_summary": "Freelance Designer"})
    matched = _find_exclusion_match(cand, ["freelance"])
    assert matched is not None
    assert matched[0] == "freelance"


def test_h2_unknown_top_level_keys_are_not_scanned():
    """스캔 뿌리는 명시 목록뿐 — 표 밖 키가 조용히 제외를 유발하지 않는다."""
    cand = _cand()
    cand["debug_notes"] = "인턴 관련 메모"
    assert _find_exclusion_match(cand, ["인턴"]) is None


def test_h2_pipeline_level_jd_exclusion_does_not_drop_candidates():
    """배선 증명 — 파이프라인 경로에서도 JD 문구가 정상 후보를 떨구지 않는다."""
    from apps.aisearch.core.orchestrator import run_search_pipeline
    from tests.test_aisearch_orchestrator import (  # 픽스처 재사용
        PAYLOAD_60,
        Harness,
        _candidate,
        _jd,
    )

    h = Harness(pages=1)
    jd = _jd()
    jd["not_keywords"] = ["인턴"]
    cand = _candidate(PAYLOAD_60, "https://saramin.example/p/1")
    # JD 공통 텍스트(초안 입력)에 제외어가 들어 있다 — 후보 자신은 깨끗하다.
    cand["draft_inputs"] = dict(cand["draft_inputs"])
    cand["draft_inputs"]["jd_summary"] = (
        "인턴 채용은 별도 트랙입니다. " + cand["draft_inputs"]["jd_summary"]
    )
    for channel in ("linkedin_rps", "saramin", "jobkorea"):
        h.candidates[channel] = [dict(cand)]

    report = run_search_pipeline(jd, h.deps())

    assert report.excluded == [], f"JD 문구 때문에 후보가 제외됐다: {report.excluded}"
    assert report.registered, "정상 후보가 한 명도 등록되지 않았다"
