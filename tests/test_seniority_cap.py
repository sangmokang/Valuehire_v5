"""PC-I1 + PC-I2 — 졸업연도 파생 경력상한 컷(seniority cap).

PC-I1: humansearch.hard_exclude_reason 에 seniority_over_cap 추가 — JD seniority_max 를 넘는
       경력(years_experience)은 오버스펙으로 하드제외.
PC-I2: 러너 humansearch_cdp_run.compute_years_experience — 졸업연도 있으면 정확 산출(오늘-졸업),
       없으면 근속합산(tenure_months 재사용) 폴백, 둘 다 없으면 None(fail-closed, 미상은 컷 안 함).
"""

from __future__ import annotations

from tools.multi_position_sourcing.humansearch import hard_exclude_reason
from tools.multi_position_sourcing.humansearch_cdp_run import compute_years_experience
from tools.multi_position_sourcing.models import CapturedProfile, EmploymentTenure


def _prof(**kw) -> CapturedProfile:
    return CapturedProfile(
        profile_url="https://www.linkedin.com/talent/profile/AEMAAAtest",
        source_channel=kw.get("channel", "linkedin_rps"),  # type: ignore[arg-type]
        visible_text=kw.get("text", "Product Manager at Coupang"),
        summary=kw.get("text", "Product Manager"),
        captured_at="2026-07-04",
        education=kw.get("education", ""),
        years_experience=kw.get("years"),
        employment_history=kw.get("emp", ()),
    )


# ── PC-I1: hard_exclude_reason seniority_over_cap ──────────────────────
def test_over_cap_excluded() -> None:
    prof = _prof(years=12)
    assert hard_exclude_reason(prof, "linkedin_rps", seniority_max=5) == "seniority_over_cap"


def test_at_cap_not_excluded() -> None:
    # 경계: years == seniority_max 는 통과(초과만 컷).
    assert hard_exclude_reason(_prof(years=5), "linkedin_rps", seniority_max=5) is None


def test_under_cap_not_excluded() -> None:
    assert hard_exclude_reason(_prof(years=3), "linkedin_rps", seniority_max=5) is None


def test_no_seniority_max_skips_cap() -> None:
    # seniority_max 미지정 → 경력상한 컷 안 함(기존 동작 유지).
    assert hard_exclude_reason(_prof(years=99), "linkedin_rps") is None


def test_none_years_not_excluded_failopen() -> None:
    # 경력 미상(None)이면 상한 컷 안 함 — 잘못 제외하지 않는다(PC-I2 가 fail-closed 로 None 산출).
    assert hard_exclude_reason(_prof(years=None), "linkedin_rps", seniority_max=5) is None


def test_backward_compat_two_arg_call() -> None:
    # 기존 (prof, channel) 2인자 호출 여전히 동작(프리랜서 등).
    assert hard_exclude_reason(_prof(text="프리랜서 개인사업자"), "linkedin_rps") == "freelancer"


def test_freelancer_takes_precedence_over_cap() -> None:
    prof = _prof(text="프리랜서", years=12)
    assert hard_exclude_reason(prof, "linkedin_rps", seniority_max=5) == "freelancer"


# ── PC-I2: compute_years_experience ───────────────────────────────────
def test_years_from_graduation_year() -> None:
    edu = "Seoul National University, 학사 · 2014 – 2020"
    # 졸업연도 2020, 오늘 2026 → 6년
    assert compute_years_experience(edu, (), today_year=2026) == 6


def test_years_from_latest_graduation_when_multiple() -> None:
    edu = "Korea University 학사 2010 – 2014 · Yonsei 석사 2014 – 2016"
    assert compute_years_experience(edu, (), today_year=2026) == 10  # 최신 졸업 2016


def test_years_tenure_fallback_when_no_grad_year() -> None:
    emp = (
        EmploymentTenure(company="A", start_month="2018-01", end_month="2021-01"),  # 36mo
        EmploymentTenure(company="B", start_month="2021-01", end_month="2023-01"),  # 24mo
    )
    # 졸업연도 없음 → 근속합산 60mo = 5년
    assert compute_years_experience("경력만 있음", emp, today_year=2026) == 5


def test_years_tenure_fallback_includes_current_employment() -> None:
    # 졸업연도 없음 + 현재 재직(end 빈값) → start~오늘 을 근속에 포함(2020~2026 = 6년).
    emp = (EmploymentTenure(company="X", start_month="2020-01", end_month=""),)
    assert compute_years_experience("", emp, today_year=2026) == 6


def test_years_current_employment_is_month_precise() -> None:
    # V1(Codex): 현재재직은 월까지 봐야 함 — 2020-12~2026-07 = 5년7개월 → floor 5년(6 아님).
    emp = (EmploymentTenure(company="X", start_month="2020-12", end_month=""),)
    assert compute_years_experience("", emp, today_year=2026, today_month=7) == 5


def test_future_graduation_range_not_counted_as_experience() -> None:
    # V1(Codex): "BS 2023 – 2027"은 2027 졸업예정(재학) — 시작연도 2023 을 졸업으로 오인 금지 → None.
    assert compute_years_experience("University BS 2023 - 2027", (), today_year=2026) is None


def test_ongoing_education_not_counted_as_graduation() -> None:
    # V1(Codex 2차): "2023 - Present"/"현재"는 재학중 — 시작연도를 졸업으로 오인 금지 → None.
    assert compute_years_experience("University BS 2023 - Present", (), today_year=2026) is None
    assert compute_years_experience("서울대 2023 - 현재", (), today_year=2026) is None


def test_tenure_end_present_literal_treated_as_current() -> None:
    # V1(Codex 2차): end_month 에 'Present'/'현재' 리터럴이 직접 들어와도 현재재직으로 계산(방어).
    for marker in ("Present", "현재"):
        emp = (EmploymentTenure(company="X", start_month="2020-12", end_month=marker),)
        assert compute_years_experience("", emp, today_year=2026, today_month=7) == 5


def test_years_none_when_no_grad_no_tenure() -> None:
    assert compute_years_experience("", (), today_year=2026) is None


def test_years_ignores_implausible_year() -> None:
    # 1950 미만·미래 연도는 졸업연도로 안 봄(오탐 방지) → 폴백/None.
    assert compute_years_experience("random 1801 text", (), today_year=2026) is None
