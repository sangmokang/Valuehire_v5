"""AC-2 (aisearch goal 2026-07-28) — 사람인/잡코리아 인재검색 요청 빌더 RED 테스트.

스펙: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-2 —
"docs/search-access.md 의 기존 DOM 계약(Saramin talent-pool, Jobkorea Corp/Person/Find)을
재사용해 동일 JD 기반 키워드로 검색한다."

여기서는 라이브 브라우징 없이, 순수 함수 `build_portal_search_descriptors` 가
두 채널의 검색 디스크립터(대상 URL, 입력 필드 셀렉터, 키워드 값, 실행 순서)를
docs/search-access.md 에 기록된 실제 URL/셀렉터 그대로 생성하는지 검증한다.

출처(docs/search-access.md, file:line):
- Saramin talent-pool URL ......... docs/search-access.md:106
- Saramin corporate login URL ..... docs/search-access.md:110
- Saramin OR input.search_input ... docs/search-access.md:162
- Saramin AND/NOT search_input.result docs/search-access.md:170,176
- Saramin #career_min/#career_max . docs/search-access.md:193,222 (값 0~20: :133)
- Jobkorea Corp/Person/Find URL ... docs/search-access.md:259
- Jobkorea #txtKeyword maxlength 300 docs/search-access.md:284-293
- Jobkorea #education1(대학교(4년) 졸업) docs/search-access.md:266,311-317
- Jobkorea #txtCareerStart/#txtCareerEnd docs/search-access.md:376-377
"""
from __future__ import annotations

from pathlib import Path

import pytest

from apps.aisearch.core.portal_search import build_portal_search_descriptors

_REPO = Path(__file__).resolve().parents[1]
_DOC = _REPO / "docs" / "search-access.md"

# docs/search-access.md 계약 상수(테스트 쪽 독립 사본 — 구현과 이중 기입해 오타 상쇄)
SARAMIN_SEARCH_URL = "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
SARAMIN_LOGIN_URL = (
    "https://www.saramin.co.kr/zf_user/auth?ut=c&url="
    "https%3A%2F%2Fwww.saramin.co.kr%2Fzf_user%2Fmemcom%2Ftalent-pool%2Fmain%2Fsearch"
)
JOBKOREA_SEARCH_URL = "https://www.jobkorea.co.kr/Corp/Person/Find"


def _jd_input(**overrides):
    base = dict(
        or_keywords=["product manager", "project manager"],
        and_keywords=["SaaS"],
        not_keywords=["intern"],
        career_min=3,
        career_max=10,
    )
    base.update(overrides)
    return base


def _by_channel(descriptors):
    return {d["channel"]: d for d in descriptors}


def _steps_by_field(descriptor):
    return {s["field"]: s for s in descriptor["steps"]}


# ── 문서 대조: 디스크립터가 참조하는 URL/셀렉터가 실제 문서에 있어야 한다 ──


def test_doc_contract_still_contains_urls_and_selectors():
    doc = _DOC.read_text(encoding="utf-8")
    for needle in (
        SARAMIN_SEARCH_URL,
        SARAMIN_LOGIN_URL,
        JOBKOREA_SEARCH_URL,
        'class="search_input"',
        'class="search_input result"',
        'id="career_min"',
        'id="career_max"',
        'id="txtKeyword"',
        'id="education1"',
        'id="txtCareerStart"',
        'id="txtCareerEnd"',
    ):
        assert needle in doc, f"docs/search-access.md 계약 유실: {needle}"


# ── 기본 모양: 두 채널, 사람인 → 잡코리아 순서 ──


def test_returns_two_channel_descriptors_in_order():
    descriptors = build_portal_search_descriptors(**_jd_input())
    assert [d["channel"] for d in descriptors] == ["saramin", "jobkorea"]


def test_execution_order_is_strictly_increasing_within_each_channel():
    for d in build_portal_search_descriptors(**_jd_input()):
        orders = [s["order"] for s in d["steps"]]
        assert orders == sorted(orders)
        assert len(orders) == len(set(orders))


# ── 사람인: URL/셀렉터/값 ──


def test_saramin_urls_match_doc():
    saramin = _by_channel(build_portal_search_descriptors(**_jd_input()))["saramin"]
    assert saramin["url"] == SARAMIN_SEARCH_URL
    assert saramin["login_url"] == SARAMIN_LOGIN_URL


def test_saramin_selectors_and_keyword_values():
    saramin = _by_channel(build_portal_search_descriptors(**_jd_input()))["saramin"]
    steps = _steps_by_field(saramin)
    assert steps["or_keywords"]["selector"] == "div.search_keyword input.search_input"
    assert steps["or_keywords"]["values"] == ["product manager", "project manager"]
    assert steps["and_keywords"]["selector"] == "input.search_input.result"
    assert steps["and_keywords"]["values"] == ["SaaS"]
    assert steps["not_keywords"]["selector"] == "input.search_input.result"
    assert steps["not_keywords"]["values"] == ["intern"]
    assert steps["career_min"]["selector"] == "#career_min"
    assert steps["career_min"]["values"] == ["3"]
    assert steps["career_max"]["selector"] == "#career_max"
    assert steps["career_max"]["values"] == ["10"]


def test_saramin_step_order_or_and_not_then_career():
    saramin = _by_channel(build_portal_search_descriptors(**_jd_input()))["saramin"]
    fields = [s["field"] for s in saramin["steps"]]
    assert fields == ["or_keywords", "and_keywords", "not_keywords", "career_min", "career_max"]


# ── 잡코리아: URL/셀렉터/값 ──


def test_jobkorea_url_and_selectors():
    jobkorea = _by_channel(build_portal_search_descriptors(**_jd_input()))["jobkorea"]
    assert jobkorea["url"] == JOBKOREA_SEARCH_URL
    steps = _steps_by_field(jobkorea)
    assert steps["keyword"]["selector"] == "#txtKeyword"
    assert steps["education"]["selector"] == "#education1"
    assert steps["career_min"]["selector"] == "#txtCareerStart"
    assert steps["career_min"]["values"] == ["3"]
    assert steps["career_max"]["selector"] == "#txtCareerEnd"
    assert steps["career_max"]["values"] == ["10"]


def test_jobkorea_keyword_is_same_jd_keywords_joined():
    jobkorea = _by_channel(build_portal_search_descriptors(**_jd_input()))["jobkorea"]
    steps = _steps_by_field(jobkorea)
    # 잡코리아 통합검색(#txtKeyword)은 자유 키워드 1필드 — 동일 JD의 OR+AND 키워드를 공백 결합
    assert steps["keyword"]["values"] == ["product manager project manager SaaS"]


def test_jobkorea_education_defaults_to_univ4():
    jobkorea = _by_channel(build_portal_search_descriptors(**_jd_input()))["jobkorea"]
    steps = _steps_by_field(jobkorea)
    assert steps["education"]["values"] == ["대학교(4년) 졸업"]


# ── 경력 미지정: 경력 스텝 생략 ──


def test_career_steps_omitted_when_unspecified():
    descriptors = build_portal_search_descriptors(
        **_jd_input(career_min=None, career_max=None)
    )
    for d in descriptors:
        fields = {s["field"] for s in d["steps"]}
        assert "career_min" not in fields
        assert "career_max" not in fields


# ── fail-closed 검증 ──


def test_rejects_empty_keywords():
    with pytest.raises(ValueError):
        build_portal_search_descriptors(
            **_jd_input(or_keywords=[], and_keywords=[], not_keywords=[])
        )


def test_rejects_saramin_keyword_over_30_chars():
    # docs/search-access.md:162 — 사람인 키워드 input maxlength=30
    with pytest.raises(ValueError):
        build_portal_search_descriptors(**_jd_input(or_keywords=["x" * 31]))


def test_rejects_sentence_style_keyword():
    # docs/search-access.md:121 — "Never enter full sentences."
    with pytest.raises(ValueError):
        build_portal_search_descriptors(
            **_jd_input(or_keywords=["저는 SaaS 경험이 많은 PM을 찾고 있습니다."])
        )


def test_rejects_career_out_of_range_or_inverted():
    # docs/search-access.md:133 — career select values 0~20
    with pytest.raises(ValueError):
        build_portal_search_descriptors(**_jd_input(career_min=21))
    with pytest.raises(ValueError):
        build_portal_search_descriptors(**_jd_input(career_min=-1))
    with pytest.raises(ValueError):
        build_portal_search_descriptors(**_jd_input(career_min=10, career_max=3))


# ── 순수성: 동일 입력 → 동일 출력, 입력 비파괴 ──


def test_pure_function_same_input_same_output_and_no_mutation():
    payload = _jd_input()
    snapshot = {k: (list(v) if isinstance(v, list) else v) for k, v in payload.items()}
    first = build_portal_search_descriptors(**payload)
    second = build_portal_search_descriptors(**payload)
    assert first == second
    assert payload == snapshot
