"""AC-2 — 사람인/잡코리아 인재검색 요청 빌더 (순수 함수, 라이브 브라우징 없음).

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-2 —
동일 JD 기반 키워드로 두 채널(사람인 talent-pool, 잡코리아 Corp/Person/Find) 검색을
기술하는 디스크립터(대상 URL, 입력 필드 셀렉터, 키워드 값, 실행 순서)를 생성한다.

모든 URL/셀렉터/제약의 출처는 docs/search-access.md 의 기존 DOM 계약이며,
각 상수 옆에 file:line 을 명시한다. 이 모듈은 네트워크/브라우저/파일 I/O 를 하지 않는다.
"""
from __future__ import annotations

from typing import Any

# ── Saramin talent-pool 계약 (docs/search-access.md) ──
# 검색 URL — docs/search-access.md:106
SARAMIN_SEARCH_URL = "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
# 기업회원(ut=c) 로그인 URL — docs/search-access.md:110
SARAMIN_LOGIN_URL = (
    "https://www.saramin.co.kr/zf_user/auth?ut=c&url="
    "https%3A%2F%2Fwww.saramin.co.kr%2Fzf_user%2Fmemcom%2Ftalent-pool%2Fmain%2Fsearch"
)
# OR 키워드 입력: <input class="search_input" maxlength="30"> in div.search_keyword
# — docs/search-access.md:142,162
SARAMIN_OR_SELECTOR = "div.search_keyword input.search_input"
# AND/NOT 키워드 입력: <input class="search_input result" maxlength="30">
# — docs/search-access.md:170,176
SARAMIN_AND_SELECTOR = "input.search_input.result"
SARAMIN_NOT_SELECTOR = "input.search_input.result"
# 경력 select: #career_min / #career_max — docs/search-access.md:193,222
SARAMIN_CAREER_MIN_SELECTOR = "#career_min"
SARAMIN_CAREER_MAX_SELECTOR = "#career_max"
# 키워드 input maxlength=30 — docs/search-access.md:162,170,176
SARAMIN_KEYWORD_MAXLEN = 30
# 경력 select 값 범위 0~20 — docs/search-access.md:133,193-216,222-245
CAREER_VALUE_MIN = 0
CAREER_VALUE_MAX = 20

# ── Jobkorea Corp/Person/Find 계약 (docs/search-access.md) ──
# 검색 URL — docs/search-access.md:259
JOBKOREA_SEARCH_URL = "https://www.jobkorea.co.kr/Corp/Person/Find"
# 통합검색: <input id="txtKeyword" maxlength="300"> — docs/search-access.md:284-293
JOBKOREA_KEYWORD_SELECTOR = "#txtKeyword"
JOBKOREA_KEYWORD_MAXLEN = 300
# 학력: 상세검색은 "대학교(4년) 졸업"(#education1)만 — docs/search-access.md:266,311-317
JOBKOREA_EDUCATION_SELECTOR = "#education1"
JOBKOREA_EDUCATION_VALUE = "대학교(4년) 졸업"
# 경력 범위: #txtCareerStart / #txtCareerEnd (maxlength=2) — docs/search-access.md:376-377
JOBKOREA_CAREER_MIN_SELECTOR = "#txtCareerStart"
JOBKOREA_CAREER_MAX_SELECTOR = "#txtCareerEnd"


def _validate_keywords(name: str, keywords: list[str]) -> list[str]:
    cleaned: list[str] = []
    for kw in keywords:
        if not isinstance(kw, str) or not kw.strip():
            raise ValueError(f"{name}: 빈 키워드는 허용되지 않는다: {kw!r}")
        kw = kw.strip()
        if len(kw) > SARAMIN_KEYWORD_MAXLEN:
            # docs/search-access.md:162 — input maxlength=30 (fail-closed)
            raise ValueError(f"{name}: 키워드 30자 초과(사람인 maxlength=30): {kw!r}")
        # docs/search-access.md:121 — "OR and AND conditions must receive keywords only.
        # Never enter full sentences." (문장형 입력 fail-closed)
        if kw.endswith((".", "。")) or "습니다" in kw or "합니다" in kw:
            raise ValueError(f"{name}: 문장형 입력 금지(키워드만 허용): {kw!r}")
        cleaned.append(kw)
    return cleaned


def _validate_career(career_min: int | None, career_max: int | None) -> None:
    for name, value in (("career_min", career_min), ("career_max", career_max)):
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name}: 정수만 허용: {value!r}")
        if not (CAREER_VALUE_MIN <= value <= CAREER_VALUE_MAX):
            # docs/search-access.md:133 — select values 0~20
            raise ValueError(f"{name}: 0~20 범위 밖: {value!r}")
    if career_min is not None and career_max is not None and career_min > career_max:
        raise ValueError(f"경력 범위 역전: min={career_min} > max={career_max}")


def _steps(*specs: tuple[str, str, list[str]]) -> list[dict[str, Any]]:
    return [
        {"order": i, "field": field, "selector": selector, "values": list(values)}
        for i, (field, selector, values) in enumerate(specs, start=1)
    ]


def build_portal_search_descriptors(
    *,
    or_keywords: list[str] | None = None,
    and_keywords: list[str] | None = None,
    not_keywords: list[str] | None = None,
    career_min: int | None = None,
    career_max: int | None = None,
) -> list[dict[str, Any]]:
    """동일 JD 키워드로 사람인 → 잡코리아 검색 디스크립터 2건을 생성한다.

    순수 함수: 같은 입력이면 항상 같은 출력, 입력을 변형하지 않으며 I/O 가 없다.
    검증 실패 시 ValueError (fail-closed — 부분 디스크립터를 반환하지 않는다).
    """
    or_kw = _validate_keywords("or_keywords", list(or_keywords or []))
    and_kw = _validate_keywords("and_keywords", list(and_keywords or []))
    not_kw = _validate_keywords("not_keywords", list(not_keywords or []))
    if not (or_kw or and_kw or not_kw):
        raise ValueError("키워드가 하나도 없다 — 검색 디스크립터를 만들 수 없다")
    _validate_career(career_min, career_max)

    # ── 사람인: OR → AND → NOT → 경력 순 입력 (docs/search-access.md:122 준비된
    # 키워드를 불린 의도대로 각 필드에 배치) ──
    saramin_specs: list[tuple[str, str, list[str]]] = []
    if or_kw:
        saramin_specs.append(("or_keywords", SARAMIN_OR_SELECTOR, or_kw))
    if and_kw:
        saramin_specs.append(("and_keywords", SARAMIN_AND_SELECTOR, and_kw))
    if not_kw:
        saramin_specs.append(("not_keywords", SARAMIN_NOT_SELECTOR, not_kw))
    if career_min is not None:
        saramin_specs.append(("career_min", SARAMIN_CAREER_MIN_SELECTOR, [str(career_min)]))
    if career_max is not None:
        saramin_specs.append(("career_max", SARAMIN_CAREER_MAX_SELECTOR, [str(career_max)]))

    # ── 잡코리아: 통합검색 1필드 — 동일 JD 의 OR+AND 키워드를 공백 결합
    # (NOT 제외는 잡코리아 통합검색이 지원하지 않으므로 넣지 않는다) ──
    jk_query = " ".join(or_kw + and_kw).strip()
    if not jk_query:
        raise ValueError("잡코리아 통합검색 키워드가 비었다(OR/AND 키워드 필요)")
    if len(jk_query) > JOBKOREA_KEYWORD_MAXLEN:
        # docs/search-access.md:287 — #txtKeyword maxlength=300
        raise ValueError(f"잡코리아 통합검색 300자 초과: {len(jk_query)}자")
    jobkorea_specs: list[tuple[str, str, list[str]]] = [
        ("keyword", JOBKOREA_KEYWORD_SELECTOR, [jk_query]),
        ("education", JOBKOREA_EDUCATION_SELECTOR, [JOBKOREA_EDUCATION_VALUE]),
    ]
    if career_min is not None:
        jobkorea_specs.append(("career_min", JOBKOREA_CAREER_MIN_SELECTOR, [str(career_min)]))
    if career_max is not None:
        jobkorea_specs.append(("career_max", JOBKOREA_CAREER_MAX_SELECTOR, [str(career_max)]))

    return [
        {
            "channel": "saramin",
            "url": SARAMIN_SEARCH_URL,
            "login_url": SARAMIN_LOGIN_URL,
            "steps": _steps(*saramin_specs),
        },
        {
            "channel": "jobkorea",
            "url": JOBKOREA_SEARCH_URL,
            "steps": _steps(*jobkorea_specs),
        },
    ]
