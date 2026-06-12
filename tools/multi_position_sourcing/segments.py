"""저수지 모델 단계 1 — 세그먼트 taxonomy (segment_id).

ClickUp active 포지션을 소수의 고정 세그먼트로 결정론적으로 분류한다. 세그먼트는 단계 2의
연속 Harvest 단위(포지션 트리거 없이 ``segment_id``만으로 도는)가 된다.

설계 원칙
- 결정론(재현성): 같은 포지션 → 항상 같은 ``segment_id``. 분류 로직을 스킬 텍스트가 아닌
  코드로 고정한다.
- 캐노니컬 세그먼트는 4~6개. 목표 문서의 4개(IT·AI·데이터 / 마케팅·그로스 / 세일즈·BD /
  HR·재무·운영) + fail-closed용 ``unknown``.
- ``segment_id``는 ``grouping.infer_role_family`` 위에 올린 상위 레이어다. family→segment는
  전사(全射) 함수이므로 기존 그룹 파티션/``group_id`` 해시를 바꾸지 않는다(무회귀).
"""

from __future__ import annotations

from .models import Position, RoleFamily, SegmentId

# 캐노니컬 세그먼트(고정). 명명 4개 + fail-closed unknown = 5 (목표 문서 "4~6" 충족).
CANONICAL_SEGMENTS: tuple[SegmentId, ...] = (
    "it_ai_data",
    "marketing_growth",
    "sales_bd",
    "hr_finance_ops",
    "unknown",
)

# 사장님 보고용 한국어 라벨(쉬운 말, SOT 0번 규칙).
SEGMENT_LABELS: dict[SegmentId, str] = {
    "it_ai_data": "IT·AI·데이터",
    "marketing_growth": "마케팅·그로스",
    "sales_bd": "세일즈·BD",
    "hr_finance_ops": "HR·재무·운영",
    "unknown": "미분류",
}

# RoleFamily → SegmentId. 모든 family를 빠짐없이 덮는다.
# 자기확장 규칙: 새 RoleFamily를 추가하면 이 표와 테스트(ALL_ROLE_FAMILIES)에 같은 커밋에서 추가한다.
SEGMENT_BY_FAMILY: dict[RoleFamily, SegmentId] = {
    "backend": "it_ai_data",
    "frontend": "it_ai_data",
    "ai_ml": "it_ai_data",
    "product_po": "it_ai_data",
    "growth": "marketing_growth",
    "sales": "sales_bd",
    "operations": "hr_finance_ops",
    "unknown": "unknown",
}


def segment_for_family(family: RoleFamily) -> SegmentId:
    """RoleFamily를 캐노니컬 세그먼트로 결정론적으로 매핑한다.

    표에 없는 값은 fail-closed로 ``unknown``(조용히 다른 세그먼트로 흘리지 않는다).
    """
    return SEGMENT_BY_FAMILY.get(family, "unknown")


def segment_for_position(position: Position) -> SegmentId:
    """포지션을 캐노니컬 세그먼트로 결정론적으로 매핑한다.

    ``grouping.infer_role_family``로 role_family를 먼저 추론한 뒤 세그먼트로 올린다. 순환
    import를 피하려 함수 안에서 지연 import한다(grouping이 keywords→models를 당기는 비용을
    import 시점에 지지 않기 위함).
    """
    from .grouping import infer_role_family

    return segment_for_family(infer_role_family(position))
