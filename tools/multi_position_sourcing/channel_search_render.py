"""채널 검색필터 소비측 — 세션의 검색필터를 '실제 입력 계획'으로 변환.

슬라이스 B 의 고아(orphan) 해소. ``inject_channel_search_filters`` 가 세션 ``filters`` 에 심은
채널별 검색식(boolean_query / saramin_search / jobkorea_chips)을 **읽어** 라이브 브라우저
렌더러가 그대로 칠 수 있는 구체 입력 계획으로 바꾼다. 이 모듈이 그 단일 소비 지점이다.

순수함수(브라우저·네트워크 없음). 라이브 렌더러는 이 결과를 받아:
  - kind="keyword" → 검색창에 value 한 줄(링크드인/공개웹: searchKeyword=, 평문 폴백 포함)
  - kind="fields"  → 사람인 인재검색 AND/OR/NOT 칸에 분배 입력
      (include=div.search_word_include, default=div.search_default, exclude=div.search_word_except)
  - kind="chips"   → 잡코리아 통합검색에 키워드 하나씩 입력 후 Enter 로 칩 등록(OR 누적)
실제 셀렉터·키 입력은 보류된 라이브 렌더러 소관(봇탐지). 여기는 '무엇을 어디에' 까지.
"""

from __future__ import annotations

from typing import Any

from .portal_queue_executor import _query_for_session


def saramin_field_inputs(session) -> dict[str, list[str]]:
    """사람인 ``saramin_search`` → AND/OR/NOT 칸별 입력값(없으면 ``None``)."""
    search = session.filters.get("saramin_search")
    if not search:
        return None
    return {
        "include": list(search.get("and", [])),
        "default": list(search.get("or", [])),
        "exclude": list(search.get("not", [])),
    }


def jobkorea_chip_sequence(session) -> list[str]:
    """잡코리아 ``jobkorea_chips`` → 칩으로 하나씩 등록할 키워드 순서(없으면 ``None``)."""
    chips = session.filters.get("jobkorea_chips")
    if not chips:
        return None
    return list(chips)


def render_search_for_session(session) -> dict[str, Any]:
    """세션 → 그 채널 검색칸에 넣을 구체 입력 계획(라이브 렌더러 소비측 계약).

    채널별 검색식 키를 실제로 읽어 분기한다. 검색식 키가 없으면 평문 ``standard_keyword``
    (또는 boolean_query) 로 폴백해 깨지지 않게 한다(``_query_for_session`` 재사용).
    """
    if session.channel == "saramin":
        fields = saramin_field_inputs(session)
        if fields is not None:
            return {"kind": "fields", **fields}
    elif session.channel == "jobkorea":
        chips = jobkorea_chip_sequence(session)
        if chips is not None:
            return {"kind": "chips", "chips": chips}
    return {"kind": "keyword", "value": _query_for_session(session)}
