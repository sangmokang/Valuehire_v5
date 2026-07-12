"""저수지 모델 단계 3 — 품질 스코어링 4기준 확장.

인수 기준(기계 단언):
  1) 우수 대학(university_tier) 가점
  2) 직무 직결성(role_direct) 가점
  3) 좋은 회사(company_tier) 가점
  4) 이직 안정성: 1년 미만 재직 후 이직(완료된 짧은 재직)이 2회부터 감점, 3회 이상 더 크게.
경력 이력(employment_history)을 결정론적으로 계산. 같은 프로필·포지션 → 같은 breakdown.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.fixtures import SAMPLE_POSITIONS, SAMPLE_PROFILE_JOB_HOPPER
from tools.multi_position_sourcing.models import CapturedProfile, EmploymentTenure, Position
from tools.multi_position_sourcing.scoring import (
    count_short_tenure_hops,
    job_stability_penalty,
    score_profile_for_position,
    tenure_months,
)

BACKEND_POS = next(p for p in SAMPLE_POSITIONS if p.position_id == "pos-backend-wrtn")


def _profile(**overrides) -> CapturedProfile:
    base = dict(
        profile_url="u",
        source_channel="saramin",
        visible_text="backend engineer spring",
        summary="s",
        captured_at="2026-06-12T00:00:00+00:00",
        years_experience=5,
    )
    base.update(overrides)
    return CapturedProfile(**base)


class TenureMathTests(unittest.TestCase):
    def test_completed_and_current(self) -> None:
        self.assertEqual(tenure_months("2020-01", "2020-08"), 7)
        self.assertEqual(tenure_months("2019-01", "2021-01"), 24)
        self.assertIsNone(tenure_months("2020-01", ""))  # 현재 재직 → 감점 대상 아님

    def test_count_short_hops_only_completed_under_year(self) -> None:
        history = (
            EmploymentTenure("A", "2018-01", "2018-09"),  # 8개월, 퇴사
            EmploymentTenure("B", "2018-10", "2019-05"),  # 7개월, 퇴사
            EmploymentTenure("C", "2019-06", ""),         # 현재(짧지만 미카운트)
        )
        self.assertEqual(count_short_tenure_hops(history), 2)
        long_only = (EmploymentTenure("X", "2015-01", "2020-01"),)  # 5년
        self.assertEqual(count_short_tenure_hops(long_only), 0)


class JobStabilityPenaltyTests(unittest.TestCase):
    def test_penalty_tiers(self) -> None:
        self.assertEqual(job_stability_penalty(0), 0)
        self.assertEqual(job_stability_penalty(1), 0)
        self.assertLess(job_stability_penalty(2), 0)
        # 3회 이상은 더 크게(더 음수).
        self.assertLess(job_stability_penalty(3), job_stability_penalty(2))


class ScoringCriteriaTests(unittest.TestCase):
    def test_job_hop_penalty_stepwise_in_score(self) -> None:
        h0 = _profile()
        h2 = _profile(employment_history=(
            EmploymentTenure("A", "2018-01", "2018-09"),
            EmploymentTenure("B", "2018-10", "2019-05"),
        ))
        h3 = _profile(employment_history=(
            EmploymentTenure("A", "2017-01", "2017-08"),
            EmploymentTenure("B", "2017-09", "2018-04"),
            EmploymentTenure("C", "2018-05", "2019-01"),
        ))
        s0 = score_profile_for_position(h0, BACKEND_POS)
        s2 = score_profile_for_position(h2, BACKEND_POS)
        s3 = score_profile_for_position(h3, BACKEND_POS)
        self.assertEqual(s0.score_breakdown["job_stability"], 0)
        self.assertLess(s2.score_breakdown["job_stability"], 0)
        self.assertLess(
            s3.score_breakdown["job_stability"], s2.score_breakdown["job_stability"]
        )
        self.assertLess(s2.score, s0.score)  # 감점이 총점에 반영

    def test_university_tier_bonus(self) -> None:
        top = _profile(education="KAIST Computer Science BS")
        plain = _profile(education="무명대학교 경영학")
        self.assertGreater(
            score_profile_for_position(top, BACKEND_POS).score_breakdown["university_tier"],
            score_profile_for_position(plain, BACKEND_POS).score_breakdown["university_tier"],
        )

    def test_role_direct_bonus(self) -> None:
        direct = _profile(skills=("spring", "backend api", "kotlin", "production"))
        unrelated = _profile(skills=("figma", "copywriting", "sales"))
        self.assertGreater(
            score_profile_for_position(direct, BACKEND_POS).score_breakdown["role_direct"],
            score_profile_for_position(unrelated, BACKEND_POS).score_breakdown["role_direct"],
        )

    def test_company_tier_bonus(self) -> None:
        good = _profile(current_or_past_companies=("Toss",))
        noname = _profile(current_or_past_companies=("무명컴퍼니",))
        self.assertGreater(
            score_profile_for_position(good, BACKEND_POS).score_breakdown["company_tier"],
            score_profile_for_position(noname, BACKEND_POS).score_breakdown["company_tier"],
        )

    def test_company_tier_reasons_deterministically_ordered(self) -> None:
        # 여러 고티어 신호 → 회사 신호 문구가 정렬(결정론, 프로세스/PYTHONHASHSEED 무관).
        # 사장님 브리핑에 노출되므로 표시 텍스트도 재현 가능해야 한다.
        p = _profile(current_or_past_companies=("Naver Kakao Toss Coupang Line",))
        reasons = [
            r
            for r in score_profile_for_position(p, BACKEND_POS).why_fit
            if r.startswith("company tier signal")
        ]
        self.assertTrue(reasons)
        self.assertEqual(reasons, sorted(reasons))

    def test_organization_context_penalizes_big_org_background_for_startup_role(self) -> None:
        startup_pos = next(p for p in SAMPLE_POSITIONS if p.position_id == "pos-growth-uglylab")
        big_org = _profile(
            current_or_past_companies=("29CM", "CJ ENM Commerce Division", "Woowa Bros"),
            visible_text="Growth lead with live commerce and CRM experience at a large platform company.",
            summary="Big-org growth operator.",
        )
        builder = _profile(
            current_or_past_companies=("Early-stage startup",),
            visible_text="Growth lead from an early-stage startup owning funnel experiments and CRM.",
            summary="Founder-adjacent growth operator.",
        )
        big_scored = score_profile_for_position(big_org, startup_pos)
        builder_scored = score_profile_for_position(builder, startup_pos)
        self.assertLess(big_scored.score, builder_scored.score)
        self.assertIn("organization_context", big_scored.score_breakdown)
        self.assertTrue(
            any("대형 조직/플랫폼 출신" in reason for reason in big_scored.why_not),
            big_scored.why_not,
        )

    def test_organization_company_signals_require_token_boundaries(self) -> None:
        """line/sk 같은 짧은 회사 신호가 Online/Taskworld 내부 문자열에 오탐하면 안 된다."""
        startup_pos = next(p for p in SAMPLE_POSITIONS if p.position_id == "pos-growth-uglylab")
        for company in ("Online Foods", "Taskworld"):
            scored = score_profile_for_position(
                _profile(
                    current_or_past_companies=(company,),
                    visible_text=f"Growth manager at {company}.",
                    summary="Growth operator.",
                ),
                startup_pos,
            )
            self.assertNotEqual(scored.org_fit, "builder-mismatch", company)
            self.assertFalse(
                any("대형 조직/플랫폼 출신" in reason for reason in scored.why_not),
                (company, scored.why_not),
            )

    def test_client_mentions_do_not_become_employer_history(self) -> None:
        """후보 서술 속 고객사 Naver/Kakao를 재직 회사로 오인해 감점하면 안 된다."""
        startup_pos = next(p for p in SAMPLE_POSITIONS if p.position_id == "pos-growth-uglylab")
        scored = score_profile_for_position(
            _profile(
                current_or_past_companies=("Tiny Labs",),
                visible_text="Built integrations for Naver and Kakao clients.",
                summary="Growth manager at Tiny Labs.",
            ),
            startup_pos,
        )
        self.assertNotEqual(scored.org_fit, "builder-mismatch")
        self.assertFalse(any("대형 조직/플랫폼 출신" in reason for reason in scored.why_not))

    def test_generic_product_owner_is_not_startup_builder_evidence(self) -> None:
        """직함 Product Owner의 owner만으로 초기조직 경험을 만들지 않는다."""
        startup_pos = next(p for p in SAMPLE_POSITIONS if p.position_id == "pos-growth-uglylab")
        scored = score_profile_for_position(
            _profile(
                current_or_past_companies=("29CM",),
                visible_text="Product Owner leading roadmap and CRM platform delivery.",
                summary="Product Owner at 29CM.",
            ),
            startup_pos,
        )
        self.assertEqual(scored.org_fit, "builder-mismatch")
        self.assertFalse(any("초기조직/실행형 경험" in reason for reason in scored.why_fit))

    def test_startup_client_mention_is_not_builder_employment_evidence(self) -> None:
        startup_pos = next(p for p in SAMPLE_POSITIONS if p.position_id == "pos-growth-uglylab")
        scored = score_profile_for_position(
            _profile(
                current_or_past_companies=("29CM",),
                visible_text="Product Manager at 29CM serving startup clients.",
                summary="Built products for startup customers.",
            ),
            startup_pos,
        )
        self.assertEqual(scored.org_fit, "builder-mismatch")
        self.assertFalse(any("초기조직/실행형 경험" in reason for reason in scored.why_fit))

    def test_builder_environment_takes_precedence_over_b2b_customer_context(self) -> None:
        """scaleup+B2B owner는 초기조직 환경이다. 상반된 builder/enterprise 판정을 함께 내지 않는다."""
        position = Position(
            position_id="scaleup-b2b-owner",
            company_name="Example",
            role_title="B2B Sales Owner",
            jd_text="Scaleup owner who closes B2B deals hands-on.",
            company_size="scaleup",
        )
        big_org = score_profile_for_position(
            _profile(
                current_or_past_companies=("29CM",),
                visible_text="B2B sales lead at 29CM",
                summary="Large-platform sales operator",
            ),
            position,
        )
        self.assertEqual(big_org.org_fit, "builder-mismatch")
        self.assertFalse(any("엔터프라이즈 맥락과 맞음" in reason for reason in big_org.why_fit))

        builder = score_profile_for_position(
            _profile(
                current_or_past_companies=("Early-stage startup",),
                visible_text="Founder-adjacent B2B sales owner at an early-stage startup",
                summary="Hands-on builder",
            ),
            position,
        )
        self.assertEqual(builder.org_fit, "builder-fit")
        self.assertFalse(any("enterprise 운영 맥락" in reason for reason in builder.why_not))

    def test_breakdown_is_deterministic(self) -> None:
        p = _profile(employment_history=(EmploymentTenure("A", "2018-01", "2018-09"),))
        first = score_profile_for_position(p, BACKEND_POS).score_breakdown
        second = score_profile_for_position(p, BACKEND_POS).score_breakdown
        self.assertEqual(first, second)


class FixtureJobHopperTests(unittest.TestCase):
    def test_sample_job_hopper_fixture_is_penalized(self) -> None:
        self.assertTrue(SAMPLE_PROFILE_JOB_HOPPER.employment_history)
        scored = score_profile_for_position(SAMPLE_PROFILE_JOB_HOPPER, BACKEND_POS)
        self.assertLess(scored.score_breakdown["job_stability"], 0)


if __name__ == "__main__":
    unittest.main()
