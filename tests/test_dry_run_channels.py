"""W3 wiring: a single search run must fan out to all search channels.

사장님 지시(2026-06-23): "search 하나로 사람인·잡코리아·링크드인·챗지피티(공개웹)
모두 풀로서치". 큐를 만드는 진입점(`build_dry_run_payload`)이 사람인 한 채널만
담으면, 실행 계층이 4채널을 돌 수 있어도 검색은 사람인만 된다.

이 테스트는 큐 구성(관측 가능한 동작)을 단언한다 — 구현 베끼기가 아니라
"한 번의 검색이 4채널을 담는가"를 본다.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.dry_run import build_dry_run_payload

# public_web = ChatGPT/공개웹 X-ray 레인 (llm_keywords.DEFAULT_CHANNELS 와 동일 집합)
EXPECTED_SEARCH_CHANNELS = {"saramin", "jobkorea", "linkedin_rps", "public_web"}


class DryRunChannelCoverageTest(unittest.TestCase):
    def test_single_search_queue_covers_all_channels(self) -> None:
        payload = build_dry_run_payload()
        summary = payload["queue_cycle_summary"]
        channels = {item["channel"] for item in summary["updated_items"]}
        self.assertTrue(
            EXPECTED_SEARCH_CHANNELS <= channels,
            msg=(
                "한 번의 검색 큐가 4채널 모두 담아야 한다 "
                f"(기대 {sorted(EXPECTED_SEARCH_CHANNELS)}, 실제 {sorted(channels)})"
            ),
        )

    def test_every_queued_item_carries_its_own_channel_keywords(self) -> None:
        """채널만 늘리고 키워드는 비면 가짜 GREEN — 각 항목이 자기 채널 키워드를 갖는지."""
        payload = build_dry_run_payload()
        summary = payload["queue_cycle_summary"]
        for item in summary["updated_items"]:
            channel = item["channel"]
            sessions = item["keyword_plan"]
            self.assertTrue(
                sessions,
                msg=f"{channel} 큐 항목에 키워드 세션이 비어 있다",
            )
            self.assertTrue(
                all(session["channel"] == channel for session in sessions),
                msg=f"{channel} 항목의 키워드 세션 채널이 항목 채널과 불일치",
            )


if __name__ == "__main__":
    unittest.main()
