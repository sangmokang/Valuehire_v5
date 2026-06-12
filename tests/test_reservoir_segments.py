"""저수지 모델 단계 1 — 세그먼트 taxonomy 고정 (segment_id).

인수 기준(기계 단언): 포지션 → 4~6개 캐노니컬 세그먼트로의 매핑이 결정론적이고,
모든 RoleFamily가 빠짐없이 매핑되며, PositionGroup이 일관된 segment_id를 운반한다.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.fixtures import SAMPLE_POSITIONS
from tools.multi_position_sourcing.grouping import group_positions
from tools.multi_position_sourcing.segments import (
    CANONICAL_SEGMENTS,
    SEGMENT_BY_FAMILY,
    SEGMENT_LABELS,
    segment_for_family,
    segment_for_position,
)

# 모든 RoleFamily(models.RoleFamily Literal과 1:1). 새 family를 추가하면 여기도 추가(자기확장).
ALL_ROLE_FAMILIES = (
    "backend",
    "frontend",
    "ai_ml",
    "product_po",
    "growth",
    "sales",
    "operations",
    "unknown",
)

# 4개 명명 세그먼트(목표 문서) + fail-closed용 unknown.
NAMED_SEGMENTS = ("it_ai_data", "marketing_growth", "sales_bd", "hr_finance_ops")

# 샘플 포지션의 기대 세그먼트(결정론 검증의 골든).
EXPECTED_SEGMENT_BY_POSITION = {
    "pos-backend-wrtn": "it_ai_data",
    "pos-backend-spoon": "it_ai_data",
    "pos-ai-madup": "it_ai_data",
    "pos-po-wrtn-ontology": "it_ai_data",
    "pos-growth-uglylab": "marketing_growth",
    "pos-sales-b2b-saas": "sales_bd",
}


class ReservoirSegmentTaxonomyTests(unittest.TestCase):
    def test_canonical_segments_are_four_to_six_and_include_named(self) -> None:
        self.assertGreaterEqual(len(CANONICAL_SEGMENTS), 4)
        self.assertLessEqual(len(CANONICAL_SEGMENTS), 6)
        self.assertEqual(len(set(CANONICAL_SEGMENTS)), len(CANONICAL_SEGMENTS))  # 중복 없음
        for named in NAMED_SEGMENTS:
            self.assertIn(named, CANONICAL_SEGMENTS)

    def test_every_role_family_maps_into_a_canonical_segment(self) -> None:
        for family in ALL_ROLE_FAMILIES:
            seg = segment_for_family(family)
            self.assertIn(seg, CANONICAL_SEGMENTS, f"family {family} -> {seg} not canonical")
            self.assertEqual(SEGMENT_BY_FAMILY[family], seg)
        # 매핑 표가 정확히 모든 family를 덮는다(빠짐/잉여 없음).
        self.assertEqual(set(SEGMENT_BY_FAMILY), set(ALL_ROLE_FAMILIES))

    def test_segment_for_position_is_deterministic(self) -> None:
        for position in SAMPLE_POSITIONS:
            first = segment_for_position(position)
            for _ in range(5):
                self.assertEqual(segment_for_position(position), first)

    def test_sample_positions_map_to_expected_segments(self) -> None:
        actual = {p.position_id: segment_for_position(p) for p in SAMPLE_POSITIONS}
        self.assertEqual(actual, EXPECTED_SEGMENT_BY_POSITION)

    def test_real_positions_never_fall_into_unknown(self) -> None:
        for position in SAMPLE_POSITIONS:
            self.assertNotEqual(
                segment_for_position(position),
                "unknown",
                f"{position.position_id} leaked into unknown segment",
            )

    def test_position_group_carries_consistent_segment_id(self) -> None:
        groups = group_positions(SAMPLE_POSITIONS)
        self.assertTrue(groups)
        for group in groups:
            self.assertEqual(group.segment_id, segment_for_family(group.role_family))
            self.assertIn(group.segment_id, CANONICAL_SEGMENTS)

    def test_segment_labels_cover_canonical_segments(self) -> None:
        for seg in CANONICAL_SEGMENTS:
            self.assertIn(seg, SEGMENT_LABELS)
            self.assertTrue(SEGMENT_LABELS[seg].strip())


if __name__ == "__main__":
    unittest.main()
