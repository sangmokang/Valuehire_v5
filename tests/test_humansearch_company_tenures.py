"""LinkedIn RPS 경력 추출은 '회사' 단위여야 한다 (2026-08-01 라이브 사고).

사고: humansearch 링크드인 순회에서 상위 후보가 연달아 frequent_job_change 로 자동 제외됐다.
원인은 채점이 아니라 추출이었다. 러너가 프로필 본문에서 'Mon YYYY – Mon YYYY' 날짜를 전부 긁어
한 줄씩 별개 재직으로 만들었기 때문에, **같은 회사 안의 승진(직책 변경)이 이직으로 계산**됐다.

실제 사례(컬리): 회사 총 재직 1년 2개월인데 직책이 두 개라
  Lead of Data Service Tribe            Jul 2026 – Present • 1 mo
  Lead of ... & AI Product Manager      Jun 2025 – Jul 2026 • 1 yr 2 mos
'1개월 재직 후 이직'으로 세어져 단기이직 횟수가 부풀고 하드제외됐다.

인수기준: RPS 프로필 본문에서 회사 단위 재직기간을 뽑아, 같은 회사 안의 여러 직책은 하나의
재직(가장 이른 시작 ~ 가장 늦은 종료)으로 합쳐야 한다.
"""

from __future__ import annotations

from tools.multi_position_sourcing.humansearch_cdp_run import build_company_tenures
from tools.multi_position_sourcing.scoring import count_short_tenure_hops

# 라이브 캡처본의 구조를 그대로 축약한 것(레이아웃 2종: 회사헤더형 / 'Company name' 라벨형).
PROFILE_TEXT = """\
Open to work
Experience
Kurly
1 yr 2 mos
Position title
Lead of Data Service Tribe
Position employment status
Full-time
Dates employed and Duration
Jul 2026 – Present • 1 mo
Position location
Seoul
Position title
Lead of Data Service Tribe & AI Product Manager Tribe
Position employment status
Full-time
Dates employed and Duration
Jun 2025 – Jul 2026 • 1 yr 2 mos
Position location
Seoul, South Korea
(주)우아한형제들 (Woowa Bros.)
7 yrs
Position title
Staff Data Scientist for Growth Analytics
Dates employed and Duration
Oct 2024 – Jun 2025 • 9 mos
Position title
Time Estimation Service Platform Lead
Dates employed and Duration
Jun 2023 – Sep 2024 • 1 yr 4 mos
Position title
Data Science Team Lead
Dates employed and Duration
May 2022 – Jul 2023 • 1 yr 3 mos
Position title
CEO Staff & Senior Data Scientist
Dates employed and Duration
Jul 2018 – Apr 2022 • 3 yrs 10 mos
Position title
Managing Analyst
Company name
ZOYI
Dates employed and Duration
Nov 2017 – Jun 2018 • 8 mos
Education
Alliance Manchester Business School
"""


def _by_company(text: str) -> dict[str, tuple[str, str]]:
    return {t.company: (t.start_month, t.end_month) for t in build_company_tenures(text)}


def test_positions_in_one_company_merge_into_a_single_tenure() -> None:
    tenures = _by_company(PROFILE_TEXT)
    assert tenures["Kurly"] == ("2025-06", "")  # 승진 2건 → 재직중 1건
    assert tenures["(주)우아한형제들 (Woowa Bros.)"] == ("2018-07", "2025-06")


def test_company_name_labelled_entry_is_kept_separate() -> None:
    assert _by_company(PROFILE_TEXT)["ZOYI"] == ("2017-11", "2018-06")


def test_experience_section_only_education_dates_are_not_jobs() -> None:
    assert len(build_company_tenures(PROFILE_TEXT)) == 3


def test_promotions_no_longer_inflate_short_tenure_hops() -> None:
    """승진을 이직으로 세던 버그가 사라져 단기이직은 ZOYI 1회뿐이다(제외 기준 2회 미만)."""
    hops = count_short_tenure_hops(build_company_tenures(PROFILE_TEXT))
    assert hops == 1


def test_empty_or_missing_experience_section_is_safe() -> None:
    assert build_company_tenures("") == ()
    assert build_company_tenures("Open to work\nEducation\nSeoul National University\n") == ()


# --- 러너 배선: 실제 채점 입력이 회사 단위여야 한다 ---

from tools.multi_position_sourcing.humansearch_cdp_run import tenures_for_profile


def test_runner_uses_company_grouped_tenures() -> None:
    tenures = tenures_for_profile({"full": PROFILE_TEXT, "dates": []})
    assert [t.company for t in tenures] == [
        "Kurly", "(주)우아한형제들 (Woowa Bros.)", "ZOYI"
    ]
    assert count_short_tenure_hops(tenures) == 1


def test_runner_falls_back_to_date_list_when_experience_section_is_missing() -> None:
    info = {
        "full": "Open to work\nEducation\nSeoul National University\n",
        "dates": [{"start": "Jan 2020", "end": "Present"}],
    }
    tenures = tenures_for_profile(info)
    assert len(tenures) == 1
    assert tenures[0].start_month == "2020-01"
