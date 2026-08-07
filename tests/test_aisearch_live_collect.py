"""AI Search 라이브 포털 수집 배선 — RED 먼저.

배경: aisearch/humansearch 라이브 실행 중 raw CDP 즉흥 타이핑(문자별
dispatchKeyEvent, clipboard API)이 실패해 (1) 입력이 아예 반영 안 되거나
(2) clipboard 권한 프롬프트로 Runtime.evaluate 가 멈추는 사고가 있었다.
apps/aisearch/core/cdp_driver.CdpDriver 는 이미 신뢰 입력(Input.insertText)
+ 로드 대기 + 캡차/2FA 감지까지 테스트·적대검증(Codex 5라운드) 통과된
드라이버다. 이 모듈은 그 드라이버의 이미 검증된 메서드
(fetch_list_page/fetch_detail_page)만 조합해 "채널 하나를 N페이지까지
수집"하는 아주 얇은 오케스트레이션을 추가한다 — 셀렉터·입력 로직은 전혀
새로 만들지 않는다(재사용, 복제 금지).

인수 기준(기계 단언):
- collect_channel_pages(driver, channel, descriptor, max_pages=N) 은
  fetch_list_page 를 페이지 1..N 순서로 호출하고, 각 리스트 결과의
  detail_refs 를 fetch_detail_page 로 전부 열어 pages[i]['details'] 에 담는다.
- has_next=False 인 페이지를 만나면 그 이후 페이지를 요청하지 않는다
  (Counter-AC — 초과 호출 시 페이크 driver 가 즉시 실패).
- max_pages 도달 시에도 더 이상 요청하지 않는다(has_next=True 여도).
- max_pages < 1 이면 ValueError(fail-closed).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from apps.aisearch.core.live_collect import collect_channel_pages


class FakeDriver:
    """주입식 페이크 드라이버 — 실 CDP/웹소켓 0. 호출 시퀀스만 기록."""

    def __init__(self, total_pages: int, refs_per_page: int = 2, hard_fail_after: int | None = None):
        self.total_pages = total_pages
        self.refs_per_page = refs_per_page
        self.hard_fail_after = hard_fail_after
        self.list_calls: list[tuple[str, int]] = []
        self.detail_calls: list[tuple[str, str]] = []

    def fetch_list_page(self, channel: str, page: int, payload) -> dict:
        if self.hard_fail_after is not None and page > self.hard_fail_after:
            raise AssertionError(
                f"page {page} 요청은 나가면 안 된다(cap={self.hard_fail_after})"
            )
        self.list_calls.append((channel, page))
        refs = [f"{channel}-p{page}-ref{i}" for i in range(self.refs_per_page)]
        return {
            "url": f"https://example/{channel}?page={page}",
            "content": f"<html>list-{page}</html>",
            "detail_refs": refs,
            "has_next": page < self.total_pages,
        }

    def fetch_detail_page(self, channel: str, ref: str) -> dict:
        self.detail_calls.append((channel, ref))
        return {"url": ref, "content": f"<html>detail:{ref}</html>"}


class CollectChannelPagesTests(unittest.TestCase):
    def test_stops_at_has_next_false(self) -> None:
        driver = FakeDriver(total_pages=2, hard_fail_after=2)
        pages = collect_channel_pages(driver, "jobkorea", {"url": "x"}, max_pages=20)
        self.assertEqual([p for _, p in driver.list_calls], [1, 2])
        self.assertEqual(len(pages), 2)
        self.assertFalse(pages[-1]["has_next"])

    def test_stops_at_max_pages_even_if_has_next_true(self) -> None:
        driver = FakeDriver(total_pages=20, hard_fail_after=3)
        pages = collect_channel_pages(driver, "saramin", {"url": "x"}, max_pages=3)
        self.assertEqual([p for _, p in driver.list_calls], [1, 2, 3])
        self.assertEqual(len(pages), 3)

    def test_fetches_every_detail_ref_in_order(self) -> None:
        driver = FakeDriver(total_pages=1, refs_per_page=3)
        pages = collect_channel_pages(driver, "jobkorea", {"url": "x"}, max_pages=1)
        self.assertEqual(
            driver.detail_calls,
            [("jobkorea", "jobkorea-p1-ref0"), ("jobkorea", "jobkorea-p1-ref1"), ("jobkorea", "jobkorea-p1-ref2")],
        )
        self.assertEqual(len(pages[0]["details"]), 3)
        self.assertEqual(pages[0]["details"][0]["url"], "jobkorea-p1-ref0")

    def test_rejects_max_pages_below_one(self) -> None:
        driver = FakeDriver(total_pages=1)
        with self.assertRaises(ValueError):
            collect_channel_pages(driver, "jobkorea", {"url": "x"}, max_pages=0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
