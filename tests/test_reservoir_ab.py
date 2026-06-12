"""저수지 모델 단계 6 — A/B 측정 하니스.

인수 기준(기계 단언):
  - build_blind_ab_batch: [실시간] vs [저수지] 후보를 합쳐 블라인드 처리(arm 숨김, blind_id가
    arm을 누설하지 않음), 결정론 순서, 전수 포함.
  - score_purity: 블라인드 적합도 채점 → arm별 top-N 적합도≥85 비율 + winner. 관측 로그 line="calibrate".
  - 결정론.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.ab_harness import (
    build_blind_ab_batch,
    score_purity,
)
from tools.multi_position_sourcing.reservoir_log import validate_reservoir_log_record

# 랭크된 후보 id 리스트(랭크 = 인덱스). 실시간/저수지 각 arm.
REALTIME = [f"rt-{i}" for i in range(5)]
RESERVOIR = [f"rv-{i}" for i in range(5)]


class BlindBatchTests(unittest.TestCase):
    def test_blind_items_do_not_leak_arm(self) -> None:
        batch = build_blind_ab_batch(REALTIME, RESERVOIR)
        for item in batch.blind_items:
            self.assertFalse(hasattr(item, "arm"))
            self.assertNotIn("realtime", item.blind_id)
            self.assertNotIn("reservoir", item.blind_id)
            self.assertNotIn("rt-", item.blind_id)
            self.assertNotIn("rv-", item.blind_id)

    def test_blind_batch_covers_all_candidates(self) -> None:
        batch = build_blind_ab_batch(REALTIME, RESERVOIR)
        self.assertEqual(len(batch.blind_items), len(REALTIME) + len(RESERVOIR))
        covered = {batch.key[item.blind_id][2] for item in batch.blind_items}
        self.assertEqual(covered, set(REALTIME) | set(RESERVOIR))

    def test_blind_batch_deterministic(self) -> None:
        a = build_blind_ab_batch(REALTIME, RESERVOIR)
        b = build_blind_ab_batch(REALTIME, RESERVOIR)
        self.assertEqual(
            [i.blind_id for i in a.blind_items],
            [i.blind_id for i in b.blind_items],
        )
        self.assertEqual(
            [a.key[i.blind_id][2] for i in a.blind_items],
            [b.key[i.blind_id][2] for i in b.blind_items],
        )


class PurityReportTests(unittest.TestCase):
    def _scores_favoring_reservoir(self, batch) -> dict[str, int]:
        # 저수지 후보는 높은 적합도(>=85), 실시간은 낮게 → 저수지 순도 우위.
        scores: dict[str, int] = {}
        for blind_id, (arm, rank, cid) in batch.key.items():
            scores[blind_id] = 90 if arm == "reservoir" else 60
        return scores

    def test_score_purity_ratio_and_winner(self) -> None:
        batch = build_blind_ab_batch(REALTIME, RESERVOIR)
        report = score_purity(batch, self._scores_favoring_reservoir(batch))
        self.assertAlmostEqual(report.reservoir_top20_ge85_ratio, 1.0)
        self.assertAlmostEqual(report.realtime_top20_ge85_ratio, 0.0)
        self.assertEqual(report.winner, "reservoir")

    def test_score_purity_logs_calibrate_line(self) -> None:
        batch = build_blind_ab_batch(REALTIME, RESERVOIR)
        report = score_purity(batch, self._scores_favoring_reservoir(batch))
        self.assertTrue(report.log_records)
        for rec in report.log_records:
            validate_reservoir_log_record(rec)
            self.assertEqual(rec["line"], "calibrate")

    def test_top_n_window_limits_count(self) -> None:
        # top_n=2 → arm별 상위 2명만 비율 계산.
        rt = [f"rt-{i}" for i in range(4)]
        rv = [f"rv-{i}" for i in range(4)]
        batch = build_blind_ab_batch(rt, rv)
        # 저수지: rank0,1 만 >=85, rank2,3 은 낮게 → top_n=2 면 비율 1.0, 전체면 0.5.
        scores: dict[str, int] = {}
        for blind_id, (arm, rank, cid) in batch.key.items():
            if arm == "reservoir":
                scores[blind_id] = 90 if rank < 2 else 50
            else:
                scores[blind_id] = 50
        report = score_purity(batch, scores, top_n=2)
        self.assertAlmostEqual(report.reservoir_top20_ge85_ratio, 1.0)

    def test_score_purity_deterministic(self) -> None:
        batch = build_blind_ab_batch(REALTIME, RESERVOIR)
        scores = self._scores_favoring_reservoir(batch)
        r1 = score_purity(batch, scores)
        r2 = score_purity(batch, scores)
        self.assertEqual(r1.reservoir_top20_ge85_ratio, r2.reservoir_top20_ge85_ratio)
        self.assertEqual(r1.winner, r2.winner)


if __name__ == "__main__":
    unittest.main()
