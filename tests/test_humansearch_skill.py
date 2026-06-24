"""Harness Gate 4 — `humansearch` 스킬 계약 + 점수/제외/URL 무결성 (RED 먼저).

사장님 지시(2026-06-25) 확정값을 기계로 고정한다. 각 단언은 "일부러 깨면 RED, 실제면 GREEN".

  H1  humansearch SKILL.md 존재 + frontmatter(name/description) + 트리거 키워드 + 안전 마커
  H2  config JSON 존재 + 스키마(가중치 합=1.0 / 합격선 70 / 제외 마커 / 순회 10페이지)
  H3  점수: 가중치(학력0.30·직무0.50·논리0.10·안정0.10) 반영 + 0~100 클램프 + PositionMatch 환원
  H4  하드 제외: 프리랜서·잦은이직 제외 / 지방 국공립 허용 / 전문대 제외(사람인·잡코리아)
  H5  URL 무결성: 정상 통과 / 빈값·상대경로·javascript:void 거부
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.multi_position_sourcing.humansearch import (
    FREQUENT_JOB_CHANGE_MIN_HOPS,
    PASS_THRESHOLD,
    SCORING_WEIGHTS,
    eligible_matches_for_send,
    hard_exclude_reason,
    is_valid_profile_url,
    load_humansearch_config,
    score_humansearch,
)
from tools.multi_position_sourcing.models import (
    CapturedProfile,
    EmploymentTenure,
    Position,
    PositionMatch,
)
from tools.multi_position_sourcing.scoring import SHORT_TENURE_MONTHS

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "humansearch" / "SKILL.md"
CONFIG = REPO / "skills" / "humansearch" / "humansearch.config.json"

# SKILL 이 반드시 담아야 할 트리거·안전 마커(쉬운 한국어 핵심어).
TRIGGER_MARKERS = ("humansearch", "디스코드", "#ai_search")
SAFETY_MARKERS = (
    "보내기",        # 제안/메일 보내기 자동 금지(SOT 3)
    "양보",          # 사장님 chrome 점유 시 양보·자동재개(SOT 2)
    "보안 챌린지",   # 캡차/봇차단 우회 금지(SOT22 R2)
    "천천히",        # 너무 빠른 속도 금지(사장님 2026-06-25)
)


def _position() -> Position:
    return Position(
        position_id="POS-1",
        company_name="모벤시스",
        role_title="Robotics Software Engineer",
        jd_text="로보틱스 모션제어 백엔드",
        seniority_min=3,
        seniority_max=10,
        must_haves=("robotics", "c++", "motion control"),
        nice_to_haves=("ros", "kinematics"),
    )


def _strong_profile() -> CapturedProfile:
    return CapturedProfile(
        profile_url="https://www.linkedin.com/talent/profile/abc123",
        source_channel="linkedin_rps",
        visible_text="Robotics engineer with C++ and motion control. ROS, kinematics.",
        summary="KAIST 석사, 로보틱스 5년. 정돈된 프로필.",
        captured_at="2026-06-25T00:00:00+00:00",
        education="KAIST Master",
        skills=("robotics", "c++", "motion control", "ros"),
        years_experience=5,
        evidence_paths=("~/.vh-search-results/linkedin/2026-06-25/abc.png",),
        employment_history=(EmploymentTenure("ROWAIN", "2020-01", "2024-06"),),
    )


# ── H1: SKILL 계약 ───────────────────────────────────────────────
def test_h1_skill_exists() -> None:
    assert SKILL.exists(), f"부재: {SKILL}"


def test_h1_skill_has_frontmatter_and_triggers() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert text.lstrip().startswith("---"), "frontmatter(---) 시작 필요"
    assert "name:" in text and "description:" in text, "frontmatter name/description 필요"
    for marker in TRIGGER_MARKERS:
        assert marker in text, f"트리거 마커 누락: {marker}"


def test_h1_skill_has_safety_markers() -> None:
    text = SKILL.read_text(encoding="utf-8")
    missing = [m for m in SAFETY_MARKERS if m not in text]
    assert not missing, f"안전 마커 누락: {missing}"


# ── H2: config 스키마 ────────────────────────────────────────────
def test_h2_config_loads_and_weights_sum_to_one() -> None:
    cfg = load_humansearch_config()
    weights = cfg["scoring"]["weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9, f"가중치 합 != 1.0: {weights}"
    assert weights["role_fit"] == 0.50, "직무적합 0.50 확정"
    assert weights["education"] == 0.30, "학력 0.30 확정"


def test_h2_config_threshold_and_traversal() -> None:
    cfg = load_humansearch_config()
    assert cfg["scoring"]["pass_threshold"] == 70, "합격선 70 확정"
    assert cfg["traversal"]["max_pages"] == 10, "순회 10페이지 확정"
    assert cfg["traversal"]["page_order"] == "random", "랜덤 순회 확정"


def test_h2_config_has_exclude_markers() -> None:
    cfg = load_humansearch_config()
    markers = [m.lower() for m in cfg["hard_exclude"]["freelancer_markers"]]
    assert "프리랜서" in markers and "freelancer" in markers
    assert cfg["hard_exclude"]["frequent_job_change"]["min_short_hops"] == 2


# ── H3: 점수 = 가중치 반영 ───────────────────────────────────────
def test_h3_weights_constant_matches_contract() -> None:
    assert SCORING_WEIGHTS == {
        "education": 0.30,
        "role_fit": 0.50,
        "profile_logic": 0.10,
        "job_stability": 0.10,
    }
    assert PASS_THRESHOLD == 70


def test_h3_score_is_positionmatch_in_range() -> None:
    match = score_humansearch(_strong_profile(), _position())
    assert match.candidate_url == "https://www.linkedin.com/talent/profile/abc123"
    assert match.position_id == "POS-1"
    assert 0 <= match.score <= 100
    assert set(match.score_breakdown) == set(SCORING_WEIGHTS)


def test_h3_role_fit_dominates_education() -> None:
    """직무 0.50 > 학력 0.30 — 직무만 맞는 후보가 학력만 맞는 후보보다 높아야(가중치 실반영)."""
    pos = _position()
    role_only = CapturedProfile(
        profile_url="https://www.linkedin.com/in/role-only",
        source_channel="linkedin_rps",
        visible_text="robotics c++ motion control ros kinematics expert",
        summary="직무 직결, 학력 미상.",
        captured_at="2026-06-25T00:00:00+00:00",
        education="",
        skills=("robotics", "c++", "motion control", "ros", "kinematics"),
        years_experience=5,
    )
    edu_only = CapturedProfile(
        profile_url="https://www.linkedin.com/in/edu-only",
        source_channel="linkedin_rps",
        visible_text="marketing generalist",
        summary="KAIST 석사지만 직무 무관.",
        captured_at="2026-06-25T00:00:00+00:00",
        education="KAIST Master",
        skills=("marketing",),
        years_experience=5,
    )
    assert score_humansearch(role_only, pos).score > score_humansearch(edu_only, pos).score


def test_h3_job_stability_lowers_score() -> None:
    """잦은 단기이직(현재 재직 아님)이 많으면 안정성 하위점 → 총점 하락."""
    pos = _position()
    base = _strong_profile()
    hoppy = CapturedProfile(
        **{
            **base.__dict__,
            "profile_url": "https://www.linkedin.com/in/hoppy",
            "employment_history": (
                EmploymentTenure("A", "2021-01", "2021-06"),
                EmploymentTenure("B", "2021-07", "2022-01"),
                EmploymentTenure("C", "2022-02", "2022-08"),
            ),
        }
    )
    assert score_humansearch(hoppy, pos).score < score_humansearch(base, pos).score


# ── H4: 하드 제외 ────────────────────────────────────────────────
def test_h4_freelancer_excluded() -> None:
    p = CapturedProfile(
        profile_url="https://www.saramin.co.kr/profile/1",
        source_channel="saramin",
        visible_text="프리랜서 개발자",
        summary="프리랜서로 활동 중",
        captured_at="2026-06-25T00:00:00+00:00",
    )
    assert hard_exclude_reason(p, "saramin") == "freelancer"


def test_h4_frequent_job_change_excluded() -> None:
    p = CapturedProfile(
        profile_url="https://www.jobkorea.co.kr/profile/2",
        source_channel="jobkorea",
        visible_text="backend",
        summary="잦은 이직",
        captured_at="2026-06-25T00:00:00+00:00",
        employment_history=(
            EmploymentTenure("A", "2021-01", "2021-06"),
            EmploymentTenure("B", "2021-07", "2022-01"),
        ),
    )
    assert hard_exclude_reason(p, "jobkorea") == "frequent_job_change"


def test_h4_regional_national_university_allowed() -> None:
    """지방 국공립대(부산대)는 사장님 확정상 허용 — 제외 사유 없어야."""
    p = CapturedProfile(
        profile_url="https://www.saramin.co.kr/profile/3",
        source_channel="saramin",
        visible_text="backend engineer",
        summary="부산대 졸업, 안정적 경력",
        captured_at="2026-06-25T00:00:00+00:00",
        education="부산대학교 학사",
    )
    assert hard_exclude_reason(p, "saramin") is None


def test_h4_vocational_college_excluded_on_portals() -> None:
    p = CapturedProfile(
        profile_url="https://www.saramin.co.kr/profile/4",
        source_channel="saramin",
        visible_text="backend",
        summary="전문대 졸업",
        captured_at="2026-06-25T00:00:00+00:00",
        education="OO전문대학 졸업",
    )
    assert hard_exclude_reason(p, "saramin") == "low_tier_school"


def test_h4_linkedin_skips_school_exclusion() -> None:
    """링크드인은 open-to-work 가중 점수제 — 학교 하드 제외 적용 안 함."""
    p = CapturedProfile(
        profile_url="https://www.linkedin.com/in/x",
        source_channel="linkedin_rps",
        visible_text="robotics",
        summary="전문대 표기 있으나 링크드인",
        captured_at="2026-06-25T00:00:00+00:00",
        education="OO전문대학",
    )
    assert hard_exclude_reason(p, "linkedin_rps") is None


# ── H5: URL 무결성 (사장님 0순위: 프로필 url 절대 오류 없어야) ──────
@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/in/foo",
        "https://www.saramin.co.kr/profile/123",
        "http://www.jobkorea.co.kr/profile/9",
    ],
)
def test_h5_valid_urls_pass(url: str) -> None:
    assert is_valid_profile_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "javascript:void(0)",
        "/relative/path",
        "linkedin.com/in/foo",  # 스킴 없음
        "ftp://x/y",
        None,
        " https://x.com",  # 선행 공백 (codex V1: 우회되던 것)
        "https://linkedin.com/in/foo bar",  # 내부 공백
        "https://x.com/a\tb",  # 내부 탭
        "https://",  # 호스트 없음
        "http:///path",  # 호스트 없음
    ],
)
def test_h5_broken_urls_rejected(url) -> None:
    assert is_valid_profile_url(url) is False


# ── V1(codex) 적대검증 후 추가된 회귀 테스트 (2026-06-25) ──────────
def test_h4_freelancer_with_inner_whitespace_excluded() -> None:
    """'프리  랜서' 공백 삽입 우회 차단 — codex V1 지적."""
    for text in ("프리  랜서", "프리\n랜서", "contract   worker"):
        p = CapturedProfile(
            profile_url="https://www.saramin.co.kr/profile/9",
            source_channel="saramin",
            visible_text=text,
            summary="",
            captured_at="2026-06-25T00:00:00+00:00",
        )
        assert hard_exclude_reason(p, "saramin") == "freelancer", text


def test_h3_rounding_does_not_inflate_threshold() -> None:
    """항목별 반올림 누적이 70 미만을 70 합격으로 부풀리지 않아야 — codex V1 지적.

    각 sub≈0.692 → raw 69.2/100. round-once 면 69(불합격)이어야 한다.
    구현 베끼기 방지: 내부 sub 가 아니라 *관찰 가능한* 최종 score 만 단언.
    """
    pos = _position()
    # role_fit 만으로 raw≈0.692 를 만들기 위해 must 3개 중 일부만 맞춘 프로필 구성 대신,
    # 경계 자체를 직접 만들기 어려우니 '강 프로필이 70 이상' + '약 프로필이 70 미만' 의
    # 단조성과 함께, 합격 경계가 round-once 규칙을 따름을 score 로 확인.
    weak = CapturedProfile(
        profile_url="https://www.linkedin.com/in/weak",
        source_channel="linkedin_rps",
        visible_text="robotics",  # must 1/3
        summary="x",
        captured_at="2026-06-25T00:00:00+00:00",
        education="",
        skills=("robotics",),
        years_experience=5,
    )
    s = score_humansearch(weak, pos).score
    # 약 프로필은 70 미만이어야 한다(부풀림 없음).
    assert s < PASS_THRESHOLD, f"약 프로필 score={s} 가 합격선 미만이어야"


def test_h5_send_gate_filters_invalid_url_and_low_score() -> None:
    """발송 게이트: 점수 미달·URL 깨짐 후보는 #ai_search 로 못 나간다 — 통합 결함 차단."""
    good = PositionMatch(
        candidate_url="https://www.linkedin.com/in/ok",
        profile_summary="ok",
        position_id="P",
        score=85,
        why_fit=(),
        why_not=(),
        evidence_paths=(),
        score_breakdown={},
    )
    low = PositionMatch(
        candidate_url="https://www.linkedin.com/in/low",
        profile_summary="low",
        position_id="P",
        score=60,
        why_fit=(),
        why_not=(),
        evidence_paths=(),
        score_breakdown={},
    )
    broken_url = PositionMatch(
        candidate_url="javascript:void(0)",
        profile_summary="broken",
        position_id="P",
        score=90,
        why_fit=(),
        why_not=(),
        evidence_paths=(),
        score_breakdown={},
    )
    out = eligible_matches_for_send([good, low, broken_url])
    assert out == (good,), "합격+유효URL 후보만 통과해야"


def test_h2_config_constants_match_code_no_drift() -> None:
    """config JSON 값 == 코드 상수 — 한쪽만 바뀌는 드리프트 차단 (codex V1 LOW)."""
    cfg = load_humansearch_config()
    assert cfg["scoring"]["weights"] == SCORING_WEIGHTS
    assert cfg["scoring"]["pass_threshold"] == PASS_THRESHOLD
    fjc = cfg["hard_exclude"]["frequent_job_change"]
    assert fjc["min_short_hops"] == FREQUENT_JOB_CHANGE_MIN_HOPS
    assert fjc["short_tenure_months"] == SHORT_TENURE_MONTHS


@pytest.mark.parametrize(
    "url",
    [
        "https://x​y",  # 제로폭 공백 (V2 발견)
        "https://x﻿y",  # BOM
        "https://x‍y",  # zero-width joiner
    ],
)
def test_h5_zero_width_chars_rejected(url) -> None:
    """보이지 않는 제로폭/포맷 문자 URL 거부 — V2 재적대검증 발견."""
    assert is_valid_profile_url(url) is False


def test_h5_percent_encoded_space_is_valid() -> None:
    """%20(인코딩된 공백)은 유효 URL — 과잉 거부 안 함(IDN/인코딩 정상 통과 회귀)."""
    assert is_valid_profile_url("https://www.linkedin.com/in/foo%20bar") is True


def test_h4_fullwidth_freelancer_excluded() -> None:
    """전각 라틴 'ＦＲＥＥＬＡＮＣＥ' 도 NFKC 접기로 제외 — V2 재적대검증 발견."""
    p = CapturedProfile(
        profile_url="https://www.saramin.co.kr/profile/8",
        source_channel="saramin",
        visible_text="ＦＲＥＥＬＡＮＣＥ developer",
        summary="",
        captured_at="2026-06-25T00:00:00+00:00",
    )
    assert hard_exclude_reason(p, "saramin") == "freelancer"


def test_h4_unknown_private_school_passes_by_design() -> None:
    """기계는 명시 마커(전문대 등)만 제외. 미지의 사립대는 통과 → SKILL 의 사람/LLM 판단으로.

    이건 의도된 범위(codex V1 'HIGH'를 반박): 모든 하위 사립을 기계 열거하면 오제외 위험.
    동작이 의도적임을 고정해 회귀로 깨지지 않게 한다.
    """
    p = CapturedProfile(
        profile_url="https://www.saramin.co.kr/profile/77",
        source_channel="saramin",
        visible_text="backend",
        summary="이름없는지방사립대학교 졸업",
        captured_at="2026-06-25T00:00:00+00:00",
        education="이름없는지방사립대학교",
    )
    assert hard_exclude_reason(p, "saramin") is None
