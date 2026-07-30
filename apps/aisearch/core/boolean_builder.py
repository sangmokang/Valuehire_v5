"""AC-1 — LinkedIn RPS Boolean 키워드 생성기 + 서울 소재 대학 우선 검색 플래너.

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-1.

- ``build_rps_boolean(jd)``: JD의 한/영 혼합 키워드 그룹을
  ``("A" OR "B") AND ("C" OR "D")`` 형태의 RPS Keywords 필드용 문자열로 조합.
- ``build_search_plan(jd, location)``: 1차 = 서울 소재 4년제 대학(D2) 우선 필터 단계,
  소진 시 확장 단계(대학 제한 해제)로 전환하는 순서 있는 플랜.
  JD 필수요건(경력연차 등)은 **모든 단계에서 게이트로 유지**된다(Counter-AC).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from apps.aisearch.core.data.seoul_universities import SEOUL_UNIVERSITIES

DEFAULT_LOCATION = "South Korea"

STAGE_SEOUL_UNIVERSITY_PRIORITY = "seoul_university_priority"
STAGE_EXPANDED = "expanded"

# 단계 전환이 허용되는 사유. 캡차·rate limit 등은 전환 사유가 아니라
# 별도 복구 절차 대상이므로 여기서 fail-fast 로 거부한다(E8 catch-all 방지).
# V1 2차 결함 4 수정: D3 — 20페이지 cap 도달(switch_boolean_variant)도
# "다음 불린 변형 전환" 사유다(소진과 동급의 정상 전환).
ADVANCE_REASON_EXHAUSTED = "exhausted"
ADVANCE_REASON_CAP_REACHED = "cap_reached"
_ADVANCE_REASONS = frozenset({ADVANCE_REASON_EXHAUSTED, ADVANCE_REASON_CAP_REACHED})

# Boolean 구문 주입 문자: 따옴표·괄호는 위치와 무관하게 구문을 깨뜨린다.
_FORBIDDEN_CHARS = ('"', "(", ")")
# 대문자 단독 토큰 OR/AND/NOT 은 RPS Boolean 연산자로 해석된다.
_OPERATOR_TOKEN_RE = re.compile(r"(?:^|\s)(?:OR|AND|NOT)(?:\s|$)")


def _validate_term(term: Any, group: Any) -> str:
    """키워드 1개를 검증한다 — 비문자열·주입 문자·연산자 토큰은 명시적 거부."""
    if not isinstance(term, str):
        raise ValueError(
            f"키워드는 문자열이어야 합니다: {term!r} (그룹 {group!r})"
        )
    stripped = term.strip()
    for ch in _FORBIDDEN_CHARS:
        if ch in stripped:
            raise ValueError(
                f"키워드에 Boolean 구문 문자({ch!r})가 들어 있습니다 — "
                f"주입 위험이므로 거부합니다(이스케이프하지 않음): {term!r}"
            )
    if _OPERATOR_TOKEN_RE.search(stripped):
        raise ValueError(
            "키워드에 Boolean 연산자 토큰(OR/AND/NOT)이 들어 있습니다 — "
            f"주입 위험이므로 거부합니다: {term!r}"
        )
    return stripped


def build_rps_boolean(jd: dict[str, Any]) -> str:
    """JD 키워드 그룹을 RPS Keywords 필드용 Boolean 문자열로 조합한다.

    각 그룹(한/영 동의어)은 OR 로, 그룹끼리는 AND 로 묶고 괄호로 감싼다.
    """
    groups = jd.get("keyword_groups") or []
    if isinstance(groups, (str, bytes)) or not isinstance(groups, (list, tuple)):
        raise ValueError(
            "keyword_groups는 리스트의 리스트여야 합니다(문자열 금지): "
            f"{groups!r}"
        )
    if not groups:
        raise ValueError("keyword_groups가 비어 있습니다 — Boolean을 만들 수 없습니다")

    and_parts: list[str] = []
    for group in groups:
        if isinstance(group, (str, bytes)) or not isinstance(group, (list, tuple)):
            raise ValueError(
                "키워드 그룹은 문자열 리스트여야 합니다 — 문자열이 그룹 자리에 "
                f"오면 글자 단위로 분해되므로 거부합니다: {group!r}"
            )
        terms = [_validate_term(t, group) for t in group]
        terms = [t for t in terms if t]
        if not terms:
            raise ValueError(f"빈 키워드 그룹이 있습니다: {group!r}")
        or_part = " OR ".join(f'"{term}"' for term in terms)
        and_parts.append(f"({or_part})")
    boolean = " AND ".join(and_parts)

    # V1 2차 결함 2 수정: JD 제외어(not_keywords)를 NOT 절로 반영한다.
    not_keywords = jd.get("not_keywords")
    if not_keywords:
        if isinstance(not_keywords, (str, bytes)) or not isinstance(
            not_keywords, (list, tuple)
        ):
            raise ValueError(
                f"not_keywords는 문자열 리스트여야 합니다(문자열 단독 금지): {not_keywords!r}"
            )
        not_terms = [_validate_term(t, not_keywords) for t in not_keywords]
        not_terms = [t for t in not_terms if t]
        if not not_terms:
            raise ValueError(f"not_keywords가 빈 값뿐입니다: {not_keywords!r}")
        not_part = " OR ".join(f'"{term}"' for term in not_terms)
        boolean = f"{boolean} NOT ({not_part})"
    return boolean


@dataclass(frozen=True)
class SearchStage:
    """검색 플랜의 한 단계.

    ``required_filters``(경력연차 등 JD 필수요건)는 대학 필터와 무관하게
    모든 단계에 그대로 실려 게이트로 작동한다.
    """

    order: int
    name: str
    keywords: str
    location: str
    required_filters: dict[str, Any]
    universities: Optional[tuple[str, ...]] = None


@dataclass
class SearchPlan:
    """순서 있는 검색 플랜: 서울 소재 대학 우선 → 소진 시 확장."""

    location: str
    stages: Sequence[SearchStage]
    _index: int = field(default=0, repr=False)

    def current_stage(self) -> SearchStage:
        return self.stages[self._index]

    def advance(self, reason: str = ADVANCE_REASON_EXHAUSTED) -> Optional[SearchStage]:
        """소진(exhausted) 또는 20페이지 cap(cap_reached)일 때만 다음 단계로 전환한다.

        캡차·rate limit·오류 등은 전환 사유가 아니므로 명시적으로 거부한다
        (E8 catch-all 방지) — 단계는 그대로 유지된다. 더 없으면 None.
        """
        if reason not in _ADVANCE_REASONS:
            raise ValueError(
                f"단계 전환은 reason∈{sorted(_ADVANCE_REASONS)}만 허용합니다 — "
                f"{reason!r}는 전환 사유가 아닙니다(캡차·오류는 별도 복구 절차)"
            )
        if self._index + 1 >= len(self.stages):
            self._index = len(self.stages)
            return None
        self._index += 1
        return self.stages[self._index]

    def is_exhausted(self) -> bool:
        return self._index >= len(self.stages)


def build_search_plan(
    jd: dict[str, Any], location: str = DEFAULT_LOCATION
) -> SearchPlan:
    """JD + 위치로 2단계 검색 플랜을 만든다.

    Counter-AC 보증: JD 필수요건(requirements)이 없으면 게이트를 만들 수 없으므로
    fail-closed 로 거부하고, 있으면 방어적 복사본을 모든 단계에 동일하게 싣는다.
    """
    if not isinstance(location, str) or not location.strip():
        raise ValueError(
            f"location이 비어 있습니다 — 빈 위치로는 플랜을 만들지 않습니다: {location!r}"
        )

    requirements = jd.get("requirements") or {}
    if not requirements:
        raise ValueError(
            "구조화 필수요건(requirements: 경력연차 등)이 없습니다 — "
            "필수요건 게이트 없이는 플랜을 만들지 않습니다(fail-closed)"
        )

    keywords = build_rps_boolean(jd)

    def gates() -> dict[str, Any]:
        # 단계마다 독립 복사본 — 대학 필터 쪽 조작이 필수요건을 약화시킬 수 없다.
        return copy.deepcopy(requirements)

    stages = (
        SearchStage(
            order=1,
            name=STAGE_SEOUL_UNIVERSITY_PRIORITY,
            keywords=keywords,
            location=location,
            required_filters=gates(),
            universities=tuple(SEOUL_UNIVERSITIES),
        ),
        SearchStage(
            order=2,
            name=STAGE_EXPANDED,
            keywords=keywords,
            location=location,
            required_filters=gates(),
            universities=None,
        ),
    )
    return SearchPlan(location=location, stages=stages)
