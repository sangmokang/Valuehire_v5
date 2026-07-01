"""Harness Gate 4 — PC-C1a1: register dict → CapturedProfile 재구성 어댑터 (RED 먼저).

목적: 러너/results.json 의 dict 를 하드제외 판정용 CapturedProfile 로 되살린다.
  - 가용 필드(education·employment_history[EmploymentTenure]·visible_text·summary) 복원.
  - fail-closed: 하드제외를 신뢰성 있게 판정할 수 없는 결손 dict 는 None(→ 호출자가 '제외'로 처리).
  - 무손실 아님(ocr_text 등 원본 dict 에 없을 수 있음) — 가용 필드만 복원(2차검증 V2 재정의).
  - SOT: fail-open 금지 · models.CapturedProfile 재사용(제2 프로필 타입 금지).

각 단언은 "일부러 깨면 RED, 실제면 GREEN".
"""
from __future__ import annotations

from tools.multi_position_sourcing.humansearch import hard_exclude_reason
from tools.multi_position_sourcing.humansearch_register import eligible, reconstruct_captured_profile
from tools.multi_position_sourcing.models import CapturedProfile, EmploymentTenure


def _runner_dict(**over) -> dict:
    """humansearch_cdp_run.py 가 실제로 내보내는 results 항목 형상."""
    d = {
        "idx": 1,
        "name": "홍길동",
        "url": "https://www.saramin.co.kr/profile/1",
        "otw": False,
        "headline": "Backend Engineer",
        "education": "부산대학교 학사",
        "score": 82,
        "breakdown": {"education": 24, "role_fit": 40, "profile_logic": 10, "job_stability": 8},
        "why_fit": ["must-have 직결: python"],
        "why_not": [],
        "screenshot": "/x/1.png",
        "summary": "백엔드 8년",
        "visible_text": "python backend engineer, 안정적 경력",
        "skills": ["python", "backend"],
        "employment_history": [
            {"company": "A", "start_month": "2018-01", "end_month": "2024-06"},
        ],
    }
    d.update(over)
    return d


# ── 가용 필드 복원 ───────────────────────────────────────────────
def test_reconstruct_restores_available_fields() -> None:
    p = reconstruct_captured_profile(_runner_dict(), "saramin")
    assert isinstance(p, CapturedProfile)
    assert p.profile_url == "https://www.saramin.co.kr/profile/1"
    assert p.source_channel == "saramin"
    assert p.visible_text == "python backend engineer, 안정적 경력"
    assert p.summary == "백엔드 8년"
    assert p.education == "부산대학교 학사"
    assert p.skills == ("python", "backend")


def test_reconstruct_employment_history_becomes_tenure_tuples() -> None:
    hist = [
        {"company": "A", "start_month": "2021-01", "end_month": "2021-06"},
        {"company": "B", "start_month": "2021-07", "end_month": "2022-01"},
    ]
    p = reconstruct_captured_profile(_runner_dict(employment_history=hist), "jobkorea")
    assert p is not None
    assert isinstance(p.employment_history, tuple)
    assert all(isinstance(t, EmploymentTenure) for t in p.employment_history)
    assert p.employment_history[0] == EmploymentTenure("A", "2021-01", "2021-06")
    assert p.employment_history[1] == EmploymentTenure("B", "2021-07", "2022-01")


def test_reconstruct_channel_sets_source_channel() -> None:
    assert reconstruct_captured_profile(_runner_dict(), "linkedin_rps").source_channel == "linkedin_rps"


# ── fail-closed: 결손 dict 는 None (호출자가 '제외') ───────────────
def test_reconstruct_missing_url_is_fail_closed() -> None:
    d = _runner_dict()
    del d["url"]
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstruct_empty_url_is_fail_closed() -> None:
    assert reconstruct_captured_profile(_runner_dict(url=""), "saramin") is None
    assert reconstruct_captured_profile(_runner_dict(url="   "), "saramin") is None


def test_reconstruct_no_text_fields_is_fail_closed() -> None:
    """프리랜서 마커를 볼 텍스트원(본문·요약·헤드라인)이 전혀 없으면 판정불가 → fail-closed(제외)."""
    d = _runner_dict()
    del d["visible_text"]
    del d["summary"]
    d.pop("headline", None)
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstruct_none_text_values_is_fail_closed() -> None:
    """텍스트 필드가 None/빈값뿐이면 no-text → fail-closed (키 존재만으로 통과 금지)."""
    d = _runner_dict(visible_text=chr(0x200B), summary=chr(0xFEFF), headline=chr(0x200D), name="")
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstructed_profile_detects_freelancer_in_headline_only() -> None:
    """프리랜서 표기가 headline 에만 있어도 매처가 봐야 한다 — 자기 적대검증(fail-open 차단)."""
    d = _runner_dict(visible_text="", summary="", headline="프리랜서 개발자", name="")
    p = reconstruct_captured_profile(d, "saramin")
    assert hard_exclude_reason(p, "saramin") == "freelancer"


def test_reconstruct_non_dict_is_fail_closed() -> None:
    for bad in (None, [], "x", 3):
        assert reconstruct_captured_profile(bad, "saramin") is None


# ── 하드제외 신호 보존 (C1a 체이닝 근거): 재구성 프로필이 매처에서 그대로 걸림 ──
def test_reconstructed_profile_detects_freelancer() -> None:
    p = reconstruct_captured_profile(_runner_dict(visible_text="프리랜서 개발자", summary=""), "saramin")
    assert hard_exclude_reason(p, "saramin") == "freelancer"


def test_reconstructed_profile_detects_low_tier_school_on_portal() -> None:
    p = reconstruct_captured_profile(
        _runner_dict(education="OO전문대학 졸업", visible_text="backend", summary=""), "saramin"
    )
    assert hard_exclude_reason(p, "saramin") == "low_tier_school"


def test_reconstructed_profile_detects_frequent_job_change() -> None:
    hist = [
        {"company": "A", "start_month": "2021-01", "end_month": "2021-06"},
        {"company": "B", "start_month": "2021-07", "end_month": "2022-01"},
    ]
    p = reconstruct_captured_profile(
        _runner_dict(visible_text="backend", summary="", education="", employment_history=hist),
        "jobkorea",
    )
    assert hard_exclude_reason(p, "jobkorea") == "frequent_job_change"


def test_reconstructed_clean_profile_passes() -> None:
    """정상 후보(지방 국공립·안정 경력)는 재구성 후에도 제외 사유 없음(과잉제외 방지)."""
    assert hard_exclude_reason(reconstruct_captured_profile(_runner_dict(), "saramin"), "saramin") is None


# ── 게이트4b step2(Codex 2차 적대검증) 발견 회귀 ──────────────────
def test_reconstruct_name_marker_does_not_overexclude() -> None:
    """name 은 신원 필드 — 마커 스캔 대상 아님. 이름에 우연히 2글자 마커 부분문자열('외주' 등)이
    있어도 본문이 정상이면 제외하지 않는다 — Codex 재검증 과잉제외(김외주→freelancer) 차단.
    프리랜서 신호는 본문(visible_text·summary·headline)에서 잡는다."""
    d = _runner_dict(name="김외주", visible_text="backend engineer 안정적", summary="부산대 8년", headline="")
    assert hard_exclude_reason(reconstruct_captured_profile(d, "saramin"), "saramin") is None


def test_reconstruct_invisible_only_text_is_fail_closed() -> None:
    """제로폭(U+200B) 등 보이지 않는 문자뿐이면 판정 불가 → fail-closed — Codex fail-open."""
    d = _runner_dict(visible_text=chr(0x200B), summary=chr(0xFEFF), headline=chr(0x200D), name="")
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstruct_invalid_url_is_fail_closed() -> None:
    """무효 URL(스킴 없음·제로폭·내부공백)은 재구성 단계에서 fail-closed — Codex fail-open."""
    for bad in ("not-a-url", chr(0x200B), "https://x.com/a b", "javascript:void(0)"):
        assert reconstruct_captured_profile(_runner_dict(url=bad), "saramin") is None


def test_reconstruct_skills_non_list_does_not_crash() -> None:
    """skills 가 int/str 같은 비리스트여도 예외 없이 안전 복원(()) — Codex exception."""
    for bad in (123, "python", None, {"a": 1}):
        p = reconstruct_captured_profile(_runner_dict(skills=bad), "saramin")
        assert p is not None
        assert p.skills == ()


def test_reconstruct_positional_employment_history_detects_frequent() -> None:
    """employment_history 가 위치형 리스트/튜플로 와도 잦은이직을 놓치지 않음 — Codex fail-open."""
    hist = [["A", "2021-01", "2021-06"], ["B", "2021-07", "2022-01"]]
    p = reconstruct_captured_profile(
        _runner_dict(visible_text="backend", summary="", education="", employment_history=hist),
        "jobkorea",
    )
    assert hard_exclude_reason(p, "jobkorea") == "frequent_job_change"


# ── PC-C1a: 등록 경계 eligible() 에 하드제외 게이트 배선 (RED 먼저) ──────────────
# 현행 eligible() 은 score>=70 · 유효URL 만 보고 hard_exclude_reason 을 미호출 → 프리랜서·잦은이직·
# 전문대가 등록 브리핑으로 샌다. PC-C1a1 재구성 + PC-C0 매처로 채점 전 하드제외를 등록 경계에 강제한다.
_FREQ_HIST = [
    {"company": "A", "start_month": "2021-01", "end_month": "2021-06"},
    {"company": "B", "start_month": "2021-07", "end_month": "2022-01"},
]


def test_eligible_excludes_freelancer() -> None:
    r = _runner_dict(score=85, visible_text="프리랜서 개발자", summary="")
    assert eligible([r], "saramin") == []


def test_eligible_excludes_frequent_job_change() -> None:
    r = _runner_dict(score=85, visible_text="backend", summary="", education="", employment_history=_FREQ_HIST)
    assert eligible([r], "jobkorea") == []


def test_eligible_excludes_low_tier_school_on_portal() -> None:
    r = _runner_dict(score=85, education="OO전문대학 졸업", visible_text="backend", summary="")
    assert eligible([r], "saramin") == []


def test_eligible_keeps_clean_passer() -> None:
    r = _runner_dict(score=85, visible_text="backend engineer", summary="부산대 8년 안정적")
    assert eligible([r], "saramin") == [r]


def test_eligible_low_tier_school_kept_on_linkedin() -> None:
    """링크드인은 학교 하드제외 미적용(portal 채널만) — 회귀 보호."""
    r = _runner_dict(
        score=85, education="OO전문대학", visible_text="robotics", summary="x",
        url="https://www.linkedin.com/in/x",
    )
    assert eligible([r], "linkedin_rps") == [r]


def test_eligible_fail_closed_on_unreconstructable_dict() -> None:
    """재구성 불가(본문 전무) 후보는 등록 경계에서 fail-closed(제외)."""
    r = _runner_dict(score=85)
    del r["visible_text"]
    del r["summary"]
    r.pop("headline", None)
    assert eligible([r], "saramin") == []


def test_eligible_still_filters_low_score_and_bad_url() -> None:
    """기존 계약 유지(회귀): 점수 미달·URL 무효는 여전히 제외."""
    low = _runner_dict(score=60, visible_text="backend", summary="ok")
    bad = _runner_dict(score=90, url="javascript:void(0)", visible_text="backend", summary="ok")
    assert eligible([low, bad], "saramin") == []


def test_eligible_sorts_passers_by_score_desc() -> None:
    """정상 후보 다건은 점수 내림차순 정렬 유지(기존 계약)."""
    lo = _runner_dict(score=75, visible_text="backend", summary="부산대", url="https://x.co/a")
    hi = _runner_dict(score=95, visible_text="backend", summary="부산대", url="https://x.co/b")
    assert eligible([lo, hi], "saramin") == [hi, lo]


# ── 게이트4b step2(Codex 2차 적대검증) 발견 회귀 ──────────────────
def test_eligible_excludes_nan_score() -> None:
    """score=NaN 은 어떤 비교도 False → '<threshold' 를 통과하던 fail-open 차단(Codex)."""
    r = _runner_dict(score=float("nan"), visible_text="backend", summary="부산대")
    assert eligible([r], "saramin") == []


def test_eligible_accepts_profile_url_when_url_absent() -> None:
    """url 키 없이 profile_url 만 유효해도 통과(reconstruct 와 동일 해석) — Codex 과잉제외 차단."""
    r = _runner_dict(visible_text="backend", summary="부산대 8년")
    r["profile_url"] = r.pop("url")
    assert eligible([r], "saramin") == [r]


def test_eligible_skips_non_dict_items_without_crash() -> None:
    """results 에 비dict 항목이 섞여도 예외 없이 skip(fail-closed) — Codex exception."""
    clean = _runner_dict(visible_text="backend", summary="부산대", url="https://x.co/ok")
    assert eligible([clean, None, "bad-item", 123], "saramin") == [clean]
