"""PC-C3a — 러너면 하드제외 (humansearch_cdp_run, results.json 면).

하드제외 3면(매처 PC-C0 · 등록면 PC-C1a · 러너면 PC-C3a) 중 러너/results.json 면. 러너가 프로필을
캡처한 직후 기존 hard_exclude_reason(단일 출처, 재구현 금지)을 적용해, 프리랜서·단기이직 2회+·
전문대(포털 학교컷 채널) 프로필이 results.json 산출에 0건이 되게 한다. 링크드인은 학교컷 미적용.

인수기준: runner_hard_exclude(prof)가 하드제외 사유를 돌려주고, collect_results(rows)가 하드제외
표시된 행을 results.json 에서 빼 프리랜서·단기이직·전문대 대상 0건임을 러너 레벨 테스트로 단언.
"""

from __future__ import annotations

from pathlib import Path

from tools.multi_position_sourcing import humansearch_cdp_run as hcr
from tools.multi_position_sourcing.humansearch_cdp_run import (
    collect_results,
    runner_hard_exclude,
)
from tools.multi_position_sourcing.models import CapturedProfile, EmploymentTenure


def _prof(
    *,
    channel: str = "linkedin_rps",
    text: str = "Product Manager at Coupang",
    education: str = "Seoul National University",
    emp: tuple[EmploymentTenure, ...] = (),
) -> CapturedProfile:
    return CapturedProfile(
        profile_url="https://www.linkedin.com/talent/profile/AEMAAABtest",
        source_channel=channel,  # type: ignore[arg-type]
        visible_text=text,
        summary=text,
        captured_at="2026-07-04",
        education=education,
        employment_history=emp,
    )


def test_freelancer_excluded() -> None:
    prof = _prof(text="프리랜서 Product Manager, 개인사업자")
    assert runner_hard_exclude(prof) == "freelancer"


def test_short_tenure_two_hops_excluded() -> None:
    emp = (
        EmploymentTenure(company="A", start_month="2023-01", end_month="2023-06"),  # 5mo
        EmploymentTenure(company="B", start_month="2024-01", end_month="2024-05"),  # 4mo
        EmploymentTenure(company="C", start_month="2025-01", end_month=""),  # 현재(카운트 제외)
    )
    prof = _prof(emp=emp)
    assert runner_hard_exclude(prof) == "frequent_job_change"


def test_low_tier_school_excluded_on_portal_channel() -> None:
    prof = _prof(channel="saramin", education="전문대학 졸업")
    assert runner_hard_exclude(prof) == "low_tier_school"


def test_low_tier_school_not_excluded_on_linkedin() -> None:
    # 링크드인은 학교컷 미적용 — 전문대여도 하드제외 아님(가중점수제).
    prof = _prof(channel="linkedin_rps", education="전문대학 졸업")
    assert runner_hard_exclude(prof) is None


def test_normal_profile_not_excluded() -> None:
    assert runner_hard_exclude(_prof()) is None


def test_collect_results_drops_hard_excluded_rows() -> None:
    rows = [
        {"name": "정상1", "score": 82, "hard_exclude": None},
        {"name": "프리랜서", "score": 90, "hard_exclude": "freelancer"},
        {"name": "정상2", "score": 71},  # hard_exclude 키 없음 = 통과
        {"name": "단기이직", "score": 88, "hard_exclude": "frequent_job_change"},
        {"name": "전문대", "score": 75, "hard_exclude": "low_tier_school"},
    ]
    out = collect_results(rows)
    names = [r["name"] for r in out]
    assert names == ["정상1", "정상2"]
    # results.json 산출에 하드제외 대상 0건
    assert all(not r.get("hard_exclude") for r in out)


def test_collect_results_preserves_order_and_full_rows() -> None:
    rows = [{"name": "a", "score": 70}, {"name": "b", "score": 99, "hard_exclude": "freelancer"}]
    out = collect_results(rows)
    assert out == [{"name": "a", "score": 70}]


def test_process_profile_exposes_briefing_and_org_fit_fields(tmp_path, monkeypatch) -> None:
    class FakeTab:
        def navigate(self, _url, wait_ms=0):
            return None

        def eval(self, _expr):
            return {
                "name": "핵심 후보",
                "headline": "Enterprise Sales Lead",
                "otw": True,
                "summary": "B2B SaaS 영업 8년, 대형 고객 클로징과 팀 리딩 경험",
                "education": "연세대학교",
                "dates": [],
                "companies": ["29CM"],
                "full": "29CM Enterprise Sales Lead, B2B deal closing and team leadership",
            }

        def screenshot(self, path):
            Path(path).write_bytes(b"png")

    monkeypatch.setattr(hcr, "OUT_DIR", tmp_path)
    monkeypatch.setattr(hcr, "LOG", tmp_path / "run.log")
    row = hcr.process_profile(
        FakeTab(),
        {
            "url": "https://www.linkedin.com/talent/profile/fully-qualified-candidate",
            "name": "핵심 후보",
            "snippet": "Enterprise Sales Lead at 29CM",
        },
        1,
    )

    assert row["profile_summary"] == "B2B SaaS 영업 8년, 대형 고객 클로징과 팀 리딩 경험"
    assert "Enterprise Sales Lead" in row["career_summary"]
    assert "29CM" in row["career_summary"]
    assert row["profile_summary"] in row["career_summary"]
    assert row["current_or_past_companies"] == ["29CM"]
    assert row["org_fit"] == "enterprise-fit"


def test_process_profile_screenshot_failure_has_no_fake_save_evidence(tmp_path, monkeypatch) -> None:
    class FailingScreenshotTab:
        def navigate(self, _url, wait_ms=0):
            return None

        def eval(self, _expr):
            return {
                "name": "후보",
                "headline": "Sales Lead",
                "otw": False,
                "summary": "B2B 영업 8년",
                "education": "연세대학교",
                "dates": [],
                "full": "B2B sales leadership",
            }

        def screenshot(self, _path):
            raise RuntimeError("capture failed")

    monkeypatch.setattr(hcr, "OUT_DIR", tmp_path)
    monkeypatch.setattr(hcr, "LOG", tmp_path / "run.log")
    row = hcr.process_profile(
        FailingScreenshotTab(),
        {"url": "https://www.linkedin.com/talent/profile/no-shot", "name": "후보"},
        1,
    )

    assert row["screenshot"] == ""
    assert row["screenshot"] != "."


def test_extract_js_collects_structured_company_links() -> None:
    from playwright.sync_api import sync_playwright

    html = """
      <h1>후보</h1>
      <p>고객사 <a href="https://www.linkedin.com/company/naver/">Naver</a> 연동 경험</p>
      <section><h2>Experience</h2>
        <a href="https://www.linkedin.com/company/29cm/">29CM</a>
        <a href="https://www.linkedin.com/company/29cm/">29CM</a>
        <a href="https://www.linkedin.com/company/tiny-labs/">Tiny Labs</a>
      </section>
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html)
            info = page.evaluate(hcr.EXTRACT_JS)
        finally:
            browser.close()
    assert info["companies"] == ["29CM", "Tiny Labs"]
