"""저수지 모델 단계 5 — match() + 재랭킹.

인수 기준(기계 단언):
  - 세그먼트 필터 → JD 임베딩 vs 엔트리 코사인 top-K → scoring(4기준) 2차 정렬(우수 인재 상위).
  - 결정론: 같은 JD·같은 저수지면 입력 순서와 무관하게 같은 결과 순서.
  - 관측 로그 line="match" 1줄, dropped(top-K 밖) 기록.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.embed import embed_text
from tools.multi_position_sourcing.fixtures import SAMPLE_POSITIONS
from tools.multi_position_sourcing.match import (
    ReservoirEntry,
    match_jd_to_reservoir,
)
from tools.multi_position_sourcing.models import CapturedProfile, EmploymentTenure
from tools.multi_position_sourcing.reservoir_log import validate_reservoir_log_record

BACKEND_POS = next(p for p in SAMPLE_POSITIONS if p.position_id == "pos-backend-wrtn")
JD = BACKEND_POS.jd_text


def _profile(url: str, *, skills=(), companies=(), education="", history=()) -> CapturedProfile:
    return CapturedProfile(
        profile_url=url,
        source_channel="saramin",
        visible_text=" ".join(skills),
        summary="candidate",
        captured_at="2026-06-12T00:00:00+00:00",
        years_experience=6,
        skills=tuple(skills),
        current_or_past_companies=tuple(companies),
        education=education,
        employment_history=tuple(history),
    )


def _entry(url: str, segment: str, *, text: str, **pkw) -> ReservoirEntry:
    return ReservoirEntry(
        canonical_url=url,
        segment_id=segment,
        vector=embed_text(text),
        profile=_profile(url, **pkw),
    )


HIGH = _entry(
    "https://x/high", "it_ai_data",
    text="backend spring kotlin production cloud platform",
    skills=("spring", "backend api", "kotlin", "production", "cloud"),
    companies=("Toss",), education="KAIST Computer Science",
)
LOW = _entry(
    "https://x/low", "it_ai_data",
    text="backend spring",
    skills=("spring",), companies=("무명컴퍼니",), education="무명대학교",
    history=(
        EmploymentTenure("a", "2021-01", "2021-06"),
        EmploymentTenure("b", "2021-07", "2022-01"),
        EmploymentTenure("c", "2022-02", "2022-09"),
    ),
)
OTHER_SEG = _entry(
    "https://x/other", "marketing_growth", text="growth crm retention funnel", skills=("crm",)
)


class MatchTests(unittest.TestCase):
    def test_filters_to_segment(self) -> None:
        res = match_jd_to_reservoir(
            JD, BACKEND_POS, [HIGH, LOW, OTHER_SEG], segment_id="it_ai_data",
            run_id="r1", today="2026-06-12",
        )
        urls = {c.canonical_url for c in res.candidates}
        self.assertEqual(urls, {"https://x/high", "https://x/low"})  # 다른 세그먼트 제외

    def test_reranks_by_quality_high_first(self) -> None:
        res = match_jd_to_reservoir(
            JD, BACKEND_POS, [LOW, HIGH], segment_id="it_ai_data",
            run_id="r1", today="2026-06-12",
        )
        self.assertEqual(res.candidates[0].canonical_url, "https://x/high")  # 우수 인재 상위
        self.assertGreater(res.candidates[0].quality_score, res.candidates[-1].quality_score)

    def test_deterministic_regardless_of_input_order(self) -> None:
        a = match_jd_to_reservoir(JD, BACKEND_POS, [HIGH, LOW], segment_id="it_ai_data", run_id="r1", today="2026-06-12")
        b = match_jd_to_reservoir(JD, BACKEND_POS, [LOW, HIGH], segment_id="it_ai_data", run_id="r1", today="2026-06-12")
        self.assertEqual(
            [c.canonical_url for c in a.candidates],
            [c.canonical_url for c in b.candidates],
        )

    def test_top_k_limits_and_logs_dropped(self) -> None:
        entries = [
            _entry(f"https://x/{i:02d}", "it_ai_data", text=f"backend spring kotlin {i}", skills=("spring",))
            for i in range(30)
        ]
        res = match_jd_to_reservoir(
            JD, BACKEND_POS, entries, segment_id="it_ai_data", top_k=20,
            run_id="r1", today="2026-06-12",
        )
        self.assertEqual(len(res.candidates), 20)
        rec = res.log_records[0]
        self.assertEqual(rec["in_count"], 30)
        self.assertEqual(rec["out_count"], 20)
        self.assertEqual(rec["dropped_count"], 10)

    def test_logs_match_line(self) -> None:
        res = match_jd_to_reservoir(JD, BACKEND_POS, [HIGH], segment_id="it_ai_data", run_id="r1", today="2026-06-12")
        self.assertTrue(res.log_records)
        for rec in res.log_records:
            validate_reservoir_log_record(rec)
            self.assertEqual(rec["line"], "match")

    def test_empty_segment_returns_empty_with_log(self) -> None:
        res = match_jd_to_reservoir(JD, BACKEND_POS, [OTHER_SEG], segment_id="it_ai_data", run_id="r1", today="2026-06-12")
        self.assertEqual(res.candidates, ())
        self.assertTrue(res.log_records)


if __name__ == "__main__":
    unittest.main()
