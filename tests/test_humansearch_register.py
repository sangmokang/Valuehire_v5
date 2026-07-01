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
