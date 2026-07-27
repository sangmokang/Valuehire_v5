"""AC-1 — LinkedIn RPS Boolean 키워드 생성기 + 서울 소재 대학 우선 검색 플래너.

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-1
- JD(텍스트 + 구조화 필수요건) + 기본 위치 South Korea 입력.
- 한국어/영어 혼합 Boolean(AND/OR/괄호) 문자열을 RPS Keywords 필드용으로 생성.
- 검색 플랜: 1차 = 서울 소재 4년제 대학(D2, 캠퍼스 소재지 기준) 우선 단계,
  소진되면 확장 단계(대학 제한 해제)로 전환하는 순서 있는 플랜.
- Counter-AC: 대학 우선순위가 JD 필수요건(경력연차 등)을 어느 단계에서도 약화시키지 않는다.
"""

import re

import pytest

from apps.aisearch.core.boolean_builder import (
    SearchPlan,
    SearchStage,
    build_rps_boolean,
    build_search_plan,
)
from apps.aisearch.core.data.seoul_universities import SEOUL_UNIVERSITIES


def make_jd(**overrides):
    jd = {
        "title": "백엔드 엔지니어",
        "text": "Python 기반 커머스 백엔드 서버 개발 및 운영. Django/AWS 경험 우대.",
        "keyword_groups": [
            ["백엔드", "Backend Engineer"],
            ["Python", "파이썬"],
            ["Django", "장고"],
        ],
        "requirements": {"min_years": 5, "max_years": 10},
    }
    jd.update(overrides)
    return jd


# ---------------------------------------------------------------------------
# Boolean 문자열 생성
# ---------------------------------------------------------------------------


class TestBuildRpsBoolean:
    def test_returns_nonempty_string(self):
        out = build_rps_boolean(make_jd())
        assert isinstance(out, str)
        assert out.strip()

    def test_uses_and_or_and_parentheses(self):
        out = build_rps_boolean(make_jd())
        assert " AND " in out
        assert " OR " in out
        assert "(" in out and ")" in out

    def test_parentheses_balanced(self):
        out = build_rps_boolean(make_jd())
        depth = 0
        for ch in out:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            assert depth >= 0, out
        assert depth == 0, out

    def test_one_and_group_per_keyword_group(self):
        jd = make_jd()
        out = build_rps_boolean(jd)
        # AND 로 묶인 최상위 그룹 수 == 키워드 그룹 수
        assert out.count(" AND ") == len(jd["keyword_groups"]) - 1

    def test_all_terms_present_and_quoted(self):
        jd = make_jd()
        out = build_rps_boolean(jd)
        for group in jd["keyword_groups"]:
            for term in group:
                assert f'"{term}"' in out, (term, out)

    def test_mixes_korean_and_english(self):
        out = build_rps_boolean(make_jd())
        assert re.search(r"[가-힣]", out), out
        assert re.search(r"[A-Za-z]", out.replace("AND", "").replace("OR", "")), out

    def test_synonyms_joined_with_or_inside_group(self):
        out = build_rps_boolean(make_jd())
        assert re.search(r'\(\s*"백엔드"\s+OR\s+"Backend Engineer"\s*\)', out), out

    def test_empty_keyword_groups_rejected(self):
        with pytest.raises(ValueError):
            build_rps_boolean(make_jd(keyword_groups=[]))

    def test_blank_terms_rejected(self):
        with pytest.raises(ValueError):
            build_rps_boolean(make_jd(keyword_groups=[["  ", ""]]))


# ---------------------------------------------------------------------------
# 서울 소재 4년제 대학 데이터 (D2: 캠퍼스 소재지 기준, 서열 아님)
# ---------------------------------------------------------------------------


class TestSeoulUniversitiesData:
    def test_at_least_30_universities(self):
        assert len(SEOUL_UNIVERSITIES) >= 30

    def test_no_duplicates_and_no_blanks(self):
        assert len(set(SEOUL_UNIVERSITIES)) == len(SEOUL_UNIVERSITIES)
        assert all(isinstance(u, str) and u.strip() for u in SEOUL_UNIVERSITIES)

    def test_contains_major_seoul_campuses(self):
        expected = {
            "서울대학교",
            "연세대학교",
            "고려대학교",
            "서강대학교",
            "성균관대학교",
            "한양대학교",
            "중앙대학교",
            "경희대학교",
            "한국외국어대학교",
            "서울시립대학교",
            "이화여자대학교",
            "건국대학교",
            "동국대학교",
            "홍익대학교",
        }
        assert expected <= set(SEOUL_UNIVERSITIES)

    def test_excludes_non_seoul_campuses(self):
        # 소재지 기준: 대전(KAIST)·포항(POSTECH)·인천(인하대)은 서울이 아니다.
        banned = {"한국과학기술원", "KAIST", "포항공과대학교", "POSTECH", "인하대학교"}
        assert banned.isdisjoint(set(SEOUL_UNIVERSITIES))


# ---------------------------------------------------------------------------
# 검색 플랜: 서울 소재 대학 우선 → 소진 시 확장
# ---------------------------------------------------------------------------


class TestSearchPlan:
    def test_default_location_is_south_korea(self):
        plan = build_search_plan(make_jd())
        assert isinstance(plan, SearchPlan)
        assert plan.location == "South Korea"

    def test_two_ordered_stages(self):
        plan = build_search_plan(make_jd())
        assert len(plan.stages) == 2
        assert all(isinstance(s, SearchStage) for s in plan.stages)
        assert [s.order for s in plan.stages] == [1, 2]
        assert plan.stages[0].name == "seoul_university_priority"
        assert plan.stages[1].name == "expanded"

    def test_stage1_filters_by_seoul_universities(self):
        plan = build_search_plan(make_jd())
        assert list(plan.stages[0].universities) == list(SEOUL_UNIVERSITIES)

    def test_stage2_lifts_university_restriction(self):
        plan = build_search_plan(make_jd())
        assert plan.stages[1].universities is None

    def test_both_stages_share_same_boolean_keywords(self):
        jd = make_jd()
        plan = build_search_plan(jd)
        expected = build_rps_boolean(jd)
        assert plan.stages[0].keywords == expected
        assert plan.stages[1].keywords == expected

    def test_starts_at_priority_stage_and_advances_on_exhaustion(self):
        plan = build_search_plan(make_jd())
        assert plan.current_stage().name == "seoul_university_priority"
        nxt = plan.advance(reason="exhausted")
        assert nxt is not None and nxt.name == "expanded"
        assert plan.current_stage().name == "expanded"
        assert plan.advance(reason="exhausted") is None
        assert plan.is_exhausted()


# ---------------------------------------------------------------------------
# Counter-AC: 대학 우선순위가 JD 필수요건을 약화시키면 안 된다
# ---------------------------------------------------------------------------


class TestCounterAcRequiredGates:
    def test_required_filters_present_in_every_stage(self):
        jd = make_jd()
        plan = build_search_plan(jd)
        for stage in plan.stages:
            assert stage.required_filters == jd["requirements"], stage.name

    def test_university_priority_stage_keeps_experience_gate(self):
        plan = build_search_plan(make_jd(requirements={"min_years": 7}))
        stage1 = plan.stages[0]
        assert stage1.universities is not None  # 대학 필터가 걸린 단계에서도
        assert stage1.required_filters["min_years"] == 7  # 경력 게이트 그대로

    def test_expanded_stage_keeps_experience_gate(self):
        plan = build_search_plan(make_jd(requirements={"min_years": 7}))
        assert plan.stages[1].required_filters["min_years"] == 7

    def test_mutating_stage_universities_does_not_touch_requirements(self):
        jd = make_jd()
        plan = build_search_plan(jd)
        # 플랜이 JD 원본 dict를 공유-변조하지 않는다(방어적 복사)
        jd["requirements"]["min_years"] = 0
        assert plan.stages[0].required_filters["min_years"] == 5
        assert plan.stages[1].required_filters["min_years"] == 5

    def test_jd_without_structured_requirements_rejected(self):
        # 필수요건(경력연차 등)이 없으면 게이트를 만들 수 없으므로 거부(fail-closed)
        with pytest.raises(ValueError):
            build_search_plan(make_jd(requirements={}))
