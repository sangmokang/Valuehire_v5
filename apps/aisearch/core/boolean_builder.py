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
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from apps.aisearch.core.data.seoul_universities import SEOUL_UNIVERSITIES

DEFAULT_LOCATION = "South Korea"

STAGE_SEOUL_UNIVERSITY_PRIORITY = "seoul_university_priority"
STAGE_EXPANDED = "expanded"


def build_rps_boolean(jd: dict[str, Any]) -> str:
    """JD 키워드 그룹을 RPS Keywords 필드용 Boolean 문자열로 조합한다.

    각 그룹(한/영 동의어)은 OR 로, 그룹끼리는 AND 로 묶고 괄호로 감싼다.
    """
    groups = jd.get("keyword_groups") or []
    if not groups:
        raise ValueError("keyword_groups가 비어 있습니다 — Boolean을 만들 수 없습니다")

    and_parts: list[str] = []
    for group in groups:
        terms = [t.strip() for t in group if isinstance(t, str) and t.strip()]
        if not terms:
            raise ValueError(f"빈 키워드 그룹이 있습니다: {group!r}")
        or_part = " OR ".join(f'"{term}"' for term in terms)
        and_parts.append(f"({or_part})")
    return " AND ".join(and_parts)


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

    def advance(self, reason: str = "exhausted") -> Optional[SearchStage]:
        """현재 단계가 소진되면 다음 단계로 전환한다. 더 없으면 None."""
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
