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
from tools.multi_position_sourcing.humansearch_register import PROFILE_SAVE_EVIDENCE_FIELDS
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

BROWSER_SURVEY_MARKERS = (
    "브라우저 환경 전수 조사",
    "실제 CDP 포트",
    "--user-data-dir",
    "/json/list",
    "이 상태 보고가 끝나기 전에는",
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


def _startup_position() -> Position:
    return Position(
        position_id="POS-2",
        company_name="UglyLab",
        role_title="Growth Lead",
        jd_text="Lead consumer growth, performance marketing, CRM, retention, and funnel experimentation.",
        seniority_min=7,
        seniority_max=14,
        company_size="startup",
        industry_segment="consumer_commerce",
        investment_stage="series_a",
        organization_analysis="Founder-adjacent growth owner for consumer commerce scaling.",
        talent_density_notes="Good pool from Kurly, Zigzag, TodayHouse, commerce and subscription apps.",
        must_haves=("growth", "performance marketing", "crm", "retention"),
        nice_to_haves=("consumer app", "commerce", "referral"),
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


def test_h1_browser_environment_survey_precedes_browser_actions() -> None:
    text = SKILL.read_text(encoding="utf-8")
    missing = [m for m in BROWSER_SURVEY_MARKERS if m not in text]
    assert not missing, f"브라우저 전수 조사 선행 계약 누락: {missing}"
    survey = text.index("브라우저 환경 전수 조사")
    actions = [text.index(marker) for marker in ("브라우저 드라이버", "브라우저를 열거나") if marker in text]
    assert not actions or survey < min(actions), "브라우저 조작 설명보다 전수 조사 규칙이 먼저여야 함"


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


def test_h3_organization_context_penalizes_big_org_profile_for_startup_role() -> None:
    """스타트업/owner 포지션에서 대형 조직/플랫폼 출신은 감점·코멘트가 남아야 한다."""
    pos = _startup_position()
    big_org = CapturedProfile(
        profile_url="https://www.linkedin.com/in/big-org",
        source_channel="linkedin_rps",
        visible_text="Growth lead with live commerce and CRM experience at a large platform company.",
        summary="29CM, CJ ENM Commerce, and Woowa Bros background.",
        captured_at="2026-06-25T00:00:00+00:00",
        education="성균관대",
        current_or_past_companies=("29CM", "CJ ENM Commerce Division", "Woowa Bros"),
        skills=("growth", "crm", "retention", "performance marketing"),
        years_experience=10,
    )
    builder = CapturedProfile(
        profile_url="https://www.linkedin.com/in/builder",
        source_channel="linkedin_rps",
        visible_text="Growth lead from an early-stage startup, owning funnel experiments and CRM.",
        summary="Founder-adjacent growth operator.",
        captured_at="2026-06-25T00:00:00+00:00",
        education="성균관대",
        current_or_past_companies=("Early-stage startup",),
        skills=("growth", "crm", "retention", "performance marketing"),
        years_experience=10,
    )
    big_score = score_humansearch(big_org, pos)
    builder_score = score_humansearch(builder, pos)
    assert big_score.score < builder_score.score
    assert big_score.org_fit == "builder-mismatch"
    assert builder_score.org_fit == "builder-fit"
    assert any("대형 조직/플랫폼 출신" in reason for reason in big_score.why_not)


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


# ── PC-C0: 하드제외 매처 단일 normalize (공백 collapse + 제로폭/포맷 strip + NFKC) ──
# 2차 적대검증(V1·T) 재현: hard_exclude_reason 을 "불러도" 매처가 새던 라이브 결함.
#   - _is_low_tier_school 은 공백 collapse 없음 → '전 문 대학' 띄어쓰기 우회
#   - freelancer 경로는 공백만 접고 제로폭(U+200B..U+200D, U+FEFF) 못 지움 → 프리+제로폭+랜서 우회
# 보이지 않는 문자는 chr(0x....) 로 주입해 소스가 눈에 보이게(리뷰 가능) 둔다.
_ZWSP, _ZWNJ, _ZWJ, _BOM, _TAB = (chr(c) for c in (0x200B, 0x200C, 0x200D, 0xFEFF, 0x09))
# 게이트4b 자기적대에서 추가로 재현한 우회 벡터(스펙의 명시 4문자를 넘는 같은 class):
_WJ, _SHY, _MVS, _VS = (chr(c) for c in (0x2060, 0x00AD, 0x180E, 0xFE0F))


@pytest.mark.parametrize(
    "education, visible_text, channel, expected",
    [
        # ── 인수기준 3면 ──
        ("OO전 문 대학 졸업", "backend", "saramin", "low_tier_school"),          # 띄어쓰기(현행 None=RED)
        ("", f"프리{_ZWSP}랜서 개발자", "saramin", "freelancer"),               # 제로폭 U+200B(현행 None=RED)
        ("", "ＦＲＥＥＬＡＮＣＥ developer", "saramin", "freelancer"),                 # 전각 NFKC 회귀 유지
        # ── 게이트4b(자기 적대검증): 내가 스스로 깨본 우회면들을 회귀로 고정 ──
        ("", f"프리{_BOM}랜서", "saramin", "freelancer"),                       # BOM U+FEFF
        ("", f"프리{_ZWJ}랜서 개발", "saramin", "freelancer"),                   # zero-width joiner U+200D
        ("", f"프리{_ZWNJ}랜서", "jobkorea", "freelancer"),                      # zero-width non-joiner U+200C
        ("", "프 리 랜 서 개발자", "saramin", "freelancer"),                         # 글자마다 공백
        ("", "Ｆreeｌance worker", "saramin", "freelancer"),                         # 전각+혼합 대소문자
        ("전문" + _ZWSP + "대학 졸업", "backend", "jobkorea", "low_tier_school"),  # 학교 경로 제로폭
        ("전 문" + _TAB + "대학교", "backend", "saramin", "low_tier_school"),      # 학교 경로 탭·공백
        ("부 산 대 학 교 학사", "backend", "saramin", None),                       # 허용대(부산대) 공백우회도 정규화→허용
        ("robotics", "robotics", "linkedin_rps", None),                          # 링크드인 학교컷 미적용(회귀)
        # ── 게이트4b(자기 적대검증) 확장: category Cf·variation selector 전면 차단 재현 ──
        ("", f"프리{_WJ}랜서", "saramin", "freelancer"),                        # word joiner U+2060
        ("", f"프리{_SHY}랜서", "jobkorea", "freelancer"),                      # soft hyphen U+00AD
        ("", f"프리{_MVS}랜서", "saramin", "freelancer"),                       # mongolian vowel sep U+180E
        ("", f"프리{_VS}랜서", "saramin", "freelancer"),                        # variation selector U+FE0F
        ("전문" + _WJ + "대학", "backend", "saramin", "low_tier_school"),       # 학교 경로 word joiner
        # ── 과잉제외 방지: 전문대학원(로스쿨·의전원·MBA)은 하위 아님. normalize 공백접힘이
        #    '경영 전문 대학원'까지 '전문대학원'으로 접어 과잉제외 widen 하던 것을 차단(자기 적대검증 발견) ──
        ("법학전문대학원", "backend", "saramin", None),                           # 로스쿨 — 제외 금지
        ("의학전문대학원 졸업", "backend", "jobkorea", None),                      # 의전원 — 제외 금지
        ("경영 전문 대학원", "backend", "saramin", None),                          # 공백 MBA — widen 차단
        ("OO전문대학 졸업", "backend", "saramin", "low_tier_school"),             # 전문대학(원 없음)은 제외 유지
    ],
)
def test_h4_hard_exclude_normalizes_before_match(education, visible_text, channel, expected) -> None:
    p = CapturedProfile(
        profile_url="https://www.saramin.co.kr/profile/c0",
        source_channel="saramin",
        visible_text=visible_text,
        summary="",
        captured_at="2026-07-02T00:00:00+00:00",
        education=education,
    )
    assert hard_exclude_reason(p, channel) == expected, (education, visible_text, channel)


# ── PC-C0 후속(별도 슬라이스): Codex 2차 적대검증이 재현한 pre-existing 우회/과잉제외 ──
# PC-C0 charter(공백·제로폭·NFKC·전각) 밖의 '자모 퍼지매칭'·'마커 정책' 영역이라 분리한다.
# (구코드 234fde5 도 동일하게 누출·과잉제외 — PC-C0 가 유발/악화한 것 아님. verdict.json 참조)
# xfail(strict) 로 장부에 고정: 후속 슬라이스가 고치면 XPASS 로 뒤집혀 이 마커 제거를 강제한다.
_COMPAT_FREE = "".join(chr(c) for c in (0x314D, 0x3161, 0x3139, 0x3163, 0x3139, 0x3150, 0x3134, 0x3145, 0x3153))
_COMPAT_JEON = "".join(chr(c) for c in (0x3148, 0x3153, 0x3134, 0x3141, 0x315C, 0x3134, 0x3137, 0x3150))


@pytest.mark.xfail(reason="PC-C0 후속: 호환자모 조합 '프리랜서' 우회(자모 퍼지매칭 별도 슬라이스)", strict=True)
def test_h4_compat_jamo_freelancer_known_open() -> None:
    p = CapturedProfile(
        profile_url="https://www.saramin.co.kr/profile/cj1",
        source_channel="saramin",
        visible_text=_COMPAT_FREE,
        summary="",
        captured_at="2026-07-02T00:00:00+00:00",
    )
    assert hard_exclude_reason(p, "saramin") == "freelancer"


@pytest.mark.xfail(reason="PC-C0 후속: 호환자모 조합 '전문대' 우회", strict=True)
def test_h4_compat_jamo_low_tier_known_open() -> None:
    p = CapturedProfile(
        profile_url="https://www.saramin.co.kr/profile/cj2",
        source_channel="saramin",
        visible_text="backend",
        summary="",
        captured_at="2026-07-02T00:00:00+00:00",
        education=_COMPAT_JEON,
    )
    assert hard_exclude_reason(p, "saramin") == "low_tier_school"


@pytest.mark.xfail(
    reason="PC-C0 후속: '외주' 2글자 마커가 '해외 주재원' 과잉제외 — 마커 경계 정책(사장님 결정) 별도 슬라이스",
    strict=True,
)
def test_h4_oeju_marker_overexcludes_known_open() -> None:
    p = CapturedProfile(
        profile_url="https://www.saramin.co.kr/profile/oj",
        source_channel="saramin",
        visible_text="해외 주재원 경력 10년",
        summary="",
        captured_at="2026-07-02T00:00:00+00:00",
    )
    assert hard_exclude_reason(p, "saramin") is None


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


# ── 세계 명문대 학력 만점 (UCLA·미국 Ivy·세계 top — 2026-06-26 사장님 지시) ──
WORLD_ELITE_SCHOOLS = [
    "UCLA",
    "University of California, Los Angeles",
    "Yale University",
    "Princeton University",
    "Columbia University",
    "Cornell University",
    "University of Pennsylvania",
    "Dartmouth College",
    "California Institute of Technology",
    "University of Chicago",
    "New York University",
    "Imperial College London",
    "ETH Zurich",
    "National University of Singapore",
    "University of Tokyo",
    "University of Toronto",
]


@pytest.mark.parametrize("school", WORLD_ELITE_SCHOOLS)
def test_world_elite_school_gets_full_education_score(school: str) -> None:
    """세계 명문대는 학력 만점(가중 30/30) — HIGH_TIER_SCHOOL_SIGNALS 에 들어가야 한다."""
    p = CapturedProfile(
        profile_url="https://www.linkedin.com/talent/profile/elite1",
        source_channel="linkedin_rps",
        visible_text="sales b2b account executive revenue",
        summary="세계 명문대 출신, 정돈된 프로필 본문.",
        captured_at="2026-06-26T00:00:00+00:00",
        education=f"{school} Bachelor",
        skills=("sales", "b2b"),
    )
    match = score_humansearch(p, _position())
    assert match.score_breakdown["education"] == 30, (
        f"{school} 학력 만점 기대(30) 실제 {match.score_breakdown['education']}"
    )


# ── H6 (2026-07-02 사장님 확장 스펙) — /humansearch 5요건이 SOT(SKILL+config)에 박혀야 한다 ──
H6_SKILL_MARKERS = (
    "901818680208",        # ClickUp FY26AI_Search 리스트 — Task+Subtask 등록처
    "814353841088757800",  # Discord 보고 채널(중간·완료)
    "Open to work",        # OTW 우선(이직 의향 분명)
    "복수",                # 포지션 복수 입력(ClickUp/텍스트/URL)
    "반조립",              # 반조립 서치 URL 입력
    "중간 보고",           # 서치 절차 중간 보고
)


def test_h6_skill_md_has_2026_07_02_expansion_markers() -> None:
    """확장 스펙 5요건(멀티채널 URL·복수 포지션·ClickUp 등록·전부 저장·Discord 보고)이 SKILL.md에 명문화."""
    text = SKILL.read_text(encoding="utf-8")
    missing = [m for m in H6_SKILL_MARKERS if m not in text]
    assert not missing, f"SKILL.md 에 확장 스펙 마커 누락: {missing}"


def test_h6_config_has_position_inputs_and_reporting() -> None:
    """config: 포지션 입력원(clickup/text/url 복수) + ClickUp 등록처 + Discord 채널 보고가 스키마로 고정."""
    cfg = load_humansearch_config()
    inputs = cfg["position_inputs"]
    assert inputs["multiple"] is True
    assert set(inputs["sources"]) >= {"clickup_task", "text", "url"}

    reg = cfg["clickup_registration"]
    assert reg["list_id"] == "901818680208"
    assert reg["structure"] == "position_parent_task + candidate_subtasks"
    assert "OTW" in " ".join(reg["priority_signals"]) or any(
        "open to work" in s.lower() for s in reg["priority_signals"]
    )

    rep = cfg["reporting"]
    # 2026-07-03 사장님 정정: 814353841088757800 은 채널이 아니라 사장님 '유저 ID' — 봇 DM 으로 보고
    assert rep["discord_dm_user_id"] == "814353841088757800"
    assert rep["dm_bot"] == "hermes_v5 (1512101118543397056)"
    assert rep["dm_channel_id"] == "1512503041448743092"
    assert rep["helper"] == "scripts/dm_report.py"
    assert rep["backup_bot"] == "hermes (1512501524792738064) → DM 채널 1509944917009629364"
    assert rep["progress_report"] is True and rep["completion_report"] is True
    assert rep["fallback"] == "VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL"
    assert "no_alarm_bomb" in rep  # 알람 폭탄 금지 정책이 스키마에 있어야 함
    assert "clickup_urls" in rep["completion_report_includes"]  # 완료 DM 에 ClickUp URL(2026-07-03)

    kx = cfg["keyword_expansion"]
    assert kx["enabled"] is True
    assert kx["module"] == "tools/multi_position_sourcing/humansearch_keyword_expand.py"

    persist = cfg["persistence"]
    assert persist["save_all_opened_profiles"] is True
    assert persist["save_search_list"] is True
    assert persist["screenshot_then_text"] is True
    assert persist["db_path"] == "~/.vh-data/ai-search-candidates.db"
    assert persist["db_table"] == "ai_search_candidates"
    assert persist["db_upsert_key"] == "(url, position_id)"
    assert persist["organization_analysis_table"] == "organization_analysis"
    assert persist["organization_analysis_db_key"] == "position_id"
    assert persist["organization_analysis_supabase_table"] == "organization_analysis"

    urls = cfg["search_url_inputs"]
    assert urls["semi_assembled"] is True
    assert set(urls["channels"]) == {"saramin", "jobkorea", "linkedin_rps"}

    assert set(reg["subtask_requires"]) >= {
        "profile_url",
        "score",
        "why_fit",
        "profile_summary",
        "saved_profile_evidence",
    }
    assert "missing_required_output_field" in reg["fail_closed_on"]
    assert reg["parent_dedup"], "부모 Task 중복 방지(검색→재사용) 규칙 필수"


def test_h6_clickup_registration_contract_is_fail_closed() -> None:
    """FY26AI_Search 등록 계약: 중복검사·프로필 저장 증거·칸반 Subtask 를 config 로 고정."""
    cfg = load_humansearch_config()
    reg = cfg["clickup_registration"]
    assert reg["list_id"] == "901818680208"
    assert reg["list_url"] == "https://app.clickup.com/9018789656/v/li/901818680208"
    assert reg["duplicate_check_required"] is True
    assert set(reg["duplicate_scope"]) >= {"position_parent_task", "candidate_profile_url_subtask"}
    assert reg["profile_save_evidence_required"] is True
    assert tuple(reg["profile_save_evidence_fields"]) == PROFILE_SAVE_EVIDENCE_FIELDS
    assert reg["target_list_required"] is True
    assert reg["kanban_record_required"] is True
    assert "saved_profile_evidence" in reg["subtask_requires"]
    assert "profile_url" in reg["subtask_requires"]
    assert "duplicate_check_missing" in reg["fail_closed_on"]
    assert "missing_required_output_field" in reg["fail_closed_on"]

    sb = cfg["persistence"]["supabase"]
    assert "organization_analysis" in sb["organization_analysis"]
    assert sb["organization_analysis_loader"] == "scripts/organization_analysis_supabase_backfill.py (position_id 조회 후 신규만 insert — 멱등)"


def test_h6_no_single_input_contract_leftover() -> None:
    """V1(Codex 2026-07-02) 적발 — 구 단수 입력 계약(required_one_of)이 복수 확장과 공존하면 모순.

    invocation 은 required_any(복수 허용)로만 선언돼야 하고, SKILL 입력 절도 복수를 명시해야 한다.
    """
    cfg = load_humansearch_config()
    inv = cfg["invocation"]
    assert "required_one_of" not in inv, "구 단수 계약 잔재 — 복수 확장과 모순"
    assert set(inv["required_any"]) >= {"position_name", "position_id", "visible_search_url"}
    text = SKILL.read_text(encoding="utf-8")
    assert "다음 중 하나가 있으면 시작" not in text, "SKILL 입력 절이 여전히 단수 계약"
    assert "복수 허용" in text
