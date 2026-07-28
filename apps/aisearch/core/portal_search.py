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
# AND 키워드 입력: <input class="search_input result" maxlength="30">
# — docs/search-access.md:167-170
SARAMIN_AND_SELECTOR = "input.search_input.result"
# ⛔ NOT 키워드는 미지원(명시적 거부) — docs/search-access.md:173-176 의 NOT 필드는
# AND 필드(docs/search-access.md:167-170)와 마크업이 완전히 동일한
# <input type="text" class="search_input result" maxlength="30"> 이라 NOT 전용
# 셀렉터가 존재하지 않는다. 같은 셀렉터로 NOT 값을 넣으면 AND 필드에 들어가
# 조용한 오동작(제외어가 필수어로 검색됨)이 되므로, fail-closed 로 거부한다.
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


def _validate_keywords(name: str, keywords: object) -> list[str]:
    # V1 결함 1 수정: 문자열 "SaaS" 를 목록 대신 넣으면 글자별로 분해되던 결함 —
    # 리스트(원소는 비어있지 않은 str)만 허용하고 그 외 타입은 fail-fast.
    if keywords is None:
        return []
    if not isinstance(keywords, list):
        raise ValueError(
            f"{name}: 키워드는 list[str] 만 허용(문자열 단독 입력 금지): {keywords!r}"
        )
    cleaned: list[str] = []
    seen: set[str] = set()
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
        # V1 결함 2 수정: 중복 키워드는 순서를 보존하며 제거한다.
        if kw in seen:
            continue
        seen.add(kw)
        cleaned.append(kw)
    return cleaned


def _dedup_key(channel: str, or_kw: list[str], and_kw: list[str]) -> str:
    """V1 결함 4 수정: 같은 디스크립터의 중복 제출을 막는 결정론적 dedup 키.

    채널 + 정규화(casefold·정렬·중복제거) 키워드로만 만들어, 같은 검색 의도면
    호출 시점·키워드 표기(대소문자·중복·순서)와 무관하게 항상 같은 키가 나온다.
    """
    norm_or = ",".join(sorted({kw.casefold() for kw in or_kw}))
    norm_and = ",".join(sorted({kw.casefold() for kw in and_kw}))
    return f"{channel}|or={norm_or}|and={norm_and}"


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
    NOT(제외) 키워드는 미지원 — 값이 오면 명시적으로 거부한다(아래 주석 참조).
    """
    # V1 결함 3 수정: NOT 키워드는 명시적 거부(미지원). 근거 —
    # docs/search-access.md:173-176 NOT 필드가 AND 필드(docs/search-access.md:167-170)와
    # 동일 마크업(input.search_input.result)이라 구분 셀렉터가 없고, 같은 셀렉터로
    # 넣으면 제외어가 필수어(AND)로 들어가는 조용한 오동작이 되기 때문.
    if not_keywords:
        raise ValueError(
            "not_keywords: 미지원 — 사람인 NOT 필드는 AND 필드와 셀렉터가 동일해 "
            "(docs/search-access.md:167-176) 안전하게 구분 입력할 수 없다. "
            "제외 조건 없이 검색한 뒤 후처리로 걸러라."
        )
    or_kw = _validate_keywords("or_keywords", or_keywords)
    and_kw = _validate_keywords("and_keywords", and_keywords)
    if not (or_kw or and_kw):
        raise ValueError("키워드가 하나도 없다 — 검색 디스크립터를 만들 수 없다")
    _validate_career(career_min, career_max)

    # ── 사람인: OR → AND → 경력 순 입력 (docs/search-access.md:122 준비된
    # 키워드를 불린 의도대로 각 필드에 배치) ──
    saramin_specs: list[tuple[str, str, list[str]]] = []
    if or_kw:
        saramin_specs.append(("or_keywords", SARAMIN_OR_SELECTOR, or_kw))
    if and_kw:
        saramin_specs.append(("and_keywords", SARAMIN_AND_SELECTOR, and_kw))
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
            # V1 결함 4 수정: 실행 계획 쪽에서 이 키로 중복 제출을 걸러낸다.
            "dedup_key": _dedup_key("saramin", or_kw, and_kw),
            "steps": _steps(*saramin_specs),
        },
        {
            "channel": "jobkorea",
            "url": JOBKOREA_SEARCH_URL,
            "dedup_key": _dedup_key("jobkorea", or_kw, and_kw),
            "steps": _steps(*jobkorea_specs),
        },
    ]
