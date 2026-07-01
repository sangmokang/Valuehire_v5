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
from tools.multi_position_sourcing.humansearch_register import reconstruct_captured_profile
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
    """프리랜서 마커를 볼 텍스트가 전혀 없으면 판정불가 → fail-closed(제외)."""
    d = _runner_dict()
    del d["visible_text"]
    del d["summary"]
    assert reconstruct_captured_profile(d, "saramin") is None


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
