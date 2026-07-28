"""AC-2 (aisearch goal 2026-07-28) — 사람인/잡코리아 인재검색 요청 빌더 테스트.

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
- Saramin AND search_input.result . docs/search-access.md:167-170
- Saramin NOT field ............... docs/search-access.md:173-176 — AND(170)와
  마크업이 완전히 동일해 셀렉터로 구분 불가 → NOT 키워드는 미지원(명시적 거부)
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


def test_doc_contract_and_not_fields_are_indistinguishable():
    """NOT 미지원 결정의 근거 고정 — docs/search-access.md:167-176 에서
    AND 필드와 NOT 필드의 마크업이 동일(구분 셀렉터 없음)해야
    '미지원 — 명시적 거부' 결정이 유효하다. 문서가 바뀌어 NOT 전용
    셀렉터가 생기면 이 테스트가 깨져 재검토를 강제한다."""
    lines = _DOC.read_text(encoding="utf-8").splitlines()
    and_field = lines[169].strip()  # docs/search-access.md:170
    not_field = lines[175].strip()  # docs/search-access.md:176
    assert and_field == '<input type="text" class="search_input result" maxlength="30">'
    assert and_field == not_field, "NOT 전용 셀렉터가 생겼다 — 미지원 결정을 재검토하라"


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
    assert steps["career_min"]["selector"] == "#career_min"
    assert steps["career_min"]["values"] == ["3"]
    assert steps["career_max"]["selector"] == "#career_max"
    assert steps["career_max"]["values"] == ["10"]


def test_saramin_step_order_or_and_then_career():
    saramin = _by_channel(build_portal_search_descriptors(**_jd_input()))["saramin"]
    fields = [s["field"] for s in saramin["steps"]]
    assert fields == ["or_keywords", "and_keywords", "career_min", "career_max"]


# ── V1 결함 3: NOT 키워드 — AND 와 동일 셀렉터라 구분 불가 → 미지원 명시 거부 ──
# 근거: docs/search-access.md:167-176 (AND field :170 == NOT field :176, 구분자 없음)


def test_not_keywords_are_explicitly_rejected_as_unsupported():
    with pytest.raises(ValueError, match="not_keywords"):
        build_portal_search_descriptors(**_jd_input(not_keywords=["intern"]))


def test_not_keywords_none_or_empty_list_is_ok():
    # NOT 을 아예 요구하지 않는 호출은 정상 동작해야 한다(조용한 오동작도, 과잉 거부도 없음)
    for value in (None, []):
        descriptors = build_portal_search_descriptors(**_jd_input(not_keywords=value))
        for d in descriptors:
            assert "not_keywords" not in {s["field"] for s in d["steps"]}


def test_no_step_ever_emits_not_keywords_field():
    # AND 셀렉터로 NOT 값이 흘러들어가는 조용한 오동작 자체가 불가능해야 한다
    for d in build_portal_search_descriptors(**_jd_input()):
        for s in d["steps"]:
            assert s["field"] != "not_keywords"


# ── V1 결함 1: keywords 타입 검증 — 문자열을 목록 대신 넣으면 글자별 분해 금지 ──


def test_rejects_bare_string_keywords_fail_fast():
    # "SaaS" 를 목록 대신 넣으면 ['S','a','a','S'] 로 분해되던 결함 — fail-fast 해야 한다
    with pytest.raises(ValueError, match="and_keywords"):
        build_portal_search_descriptors(**_jd_input(and_keywords="SaaS"))
    with pytest.raises(ValueError, match="or_keywords"):
        build_portal_search_descriptors(**_jd_input(or_keywords="product manager"))


def test_rejects_non_list_keyword_containers():
    for bad in (("PM",), {"PM"}, 123, {"kw": "PM"}):
        with pytest.raises(ValueError):
            build_portal_search_descriptors(**_jd_input(or_keywords=bad))


def test_rejects_non_string_keyword_items():
    with pytest.raises(ValueError):
        build_portal_search_descriptors(**_jd_input(or_keywords=["PM", 3]))
    with pytest.raises(ValueError):
        build_portal_search_descriptors(**_jd_input(and_keywords=[None]))


# ── V1 결함 2: 중복 키워드 — 순서 보존 중복 제거 ──


def test_duplicate_keywords_are_deduped_preserving_order():
    saramin = _by_channel(
        build_portal_search_descriptors(
            **_jd_input(or_keywords=["PM", "PM", "엔지니어", "PM", "엔지니어"])
        )
    )["saramin"]
    assert _steps_by_field(saramin)["or_keywords"]["values"] == ["PM", "엔지니어"]


def test_duplicate_keywords_after_strip_are_deduped():
    saramin = _by_channel(
        build_portal_search_descriptors(**_jd_input(and_keywords=["SaaS", " SaaS "]))
    )["saramin"]
    assert _steps_by_field(saramin)["and_keywords"]["values"] == ["SaaS"]


# ── V1 결함 4: 중복 제출 방지 — 결정론적 dedup 키(채널 + 정규화 키워드) ──


def test_each_descriptor_has_deterministic_dedup_key():
    first = build_portal_search_descriptors(**_jd_input())
    second = build_portal_search_descriptors(**_jd_input())
    for d1, d2 in zip(first, second):
        assert isinstance(d1["dedup_key"], str) and d1["dedup_key"]
        assert d1["dedup_key"] == d2["dedup_key"]
        assert d1["dedup_key"].startswith(d1["channel"])
    # 채널이 다르면 키도 달라야 같은 실행 계획에서 서로 충돌하지 않는다
    assert first[0]["dedup_key"] != first[1]["dedup_key"]


def test_dedup_key_is_stable_under_keyword_duplicates_and_case():
    base = build_portal_search_descriptors(**_jd_input(or_keywords=["PM"]))
    dup = build_portal_search_descriptors(**_jd_input(or_keywords=["PM", "PM"]))
    cased = build_portal_search_descriptors(**_jd_input(or_keywords=["pm"]))
    for a, b, c in zip(base, dup, cased):
        assert a["dedup_key"] == b["dedup_key"] == c["dedup_key"]


def test_dedup_key_differs_for_different_keywords():
    a = build_portal_search_descriptors(**_jd_input(or_keywords=["PM"]))
    b = build_portal_search_descriptors(**_jd_input(or_keywords=["designer"]))
    assert a[0]["dedup_key"] != b[0]["dedup_key"]


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
        build_portal_search_descriptors(**_jd_input(or_keywords=[], and_keywords=[]))


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
