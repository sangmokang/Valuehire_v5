"""AC-3 — 페이지네이션 20페이지 cap + 전량 저장 파이프라인 (RED 먼저).

근거: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-3 / §3 D3·D4 / §5 계약.

인수 기준(기계 단언):
- 검색 결과 순회는 최대 20페이지(D3). 21페이지째 요청이 나가면 실패(Counter-AC —
  fetcher 호출 횟수를 직접 검증).
- 20페이지 도달 시 그 키워드 조합을 종료하고 다음 불린 변형으로 전환하라는
  시그널(next_action == "switch_boolean_variant")을 반환.
- 결과가 20페이지 전에 소진되면 next_action == "exhausted".
- 열어본 리스트 페이지 + 상세 프로필 페이지 전량을 주입식 저장소(store.upsert)에
  저장(D4). 실제 Supabase 호출 없음 — 테스트는 가짜 store 로 대조.
- 저장 row 수 == 순회한 리스트 페이지 수 + 열어본 상세 수.
- row 모양: id, channel, page_type(list|detail), url, captured_at,
  raw_html_or_text, position_ref, machine (테이블 aisearch_pages_raw, 가칭).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from apps.aisearch.core import pagination_store as ps


class FakeStore:
    """주입식 저장소 — upsert(table, row) 호출을 전부 기록만 한다(네트워크 없음)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def upsert(self, table: str, row: dict) -> None:
        self.calls.append((table, dict(row)))


def make_list_fetcher(total_pages: int, details_per_page: int = 2, hard_fail_after: int | None = None):
    """page 번호를 받아 리스트 페이지 dict 를 돌려주는 가짜 fetcher.

    hard_fail_after 가 있으면 그 페이지를 넘는 요청에서 즉시 AssertionError —
    Counter-AC(21페이지째 요청이 나가면 실패)를 fetcher 단에서 못박는다.
    """
    calls: list[int] = []

    def fetch(page: int) -> dict:
        if hard_fail_after is not None and page > hard_fail_after:
            raise AssertionError(f"page {page} 요청은 나가면 안 된다 (cap={hard_fail_after})")
        calls.append(page)
        return {
            "url": f"https://example.test/search?page={page}",
            "content": f"<html>list page {page}</html>",
            "detail_refs": [f"p{page}-cand{i}" for i in range(details_per_page)],
            "has_next": page < total_pages,
        }

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def fetch_detail(ref: str) -> dict:
    return {"url": f"https://example.test/profile/{ref}", "content": f"<html>detail {ref}</html>"}


class TestPaginationCap(unittest.TestCase):
    def test_max_pages_constant_is_20(self):
        self.assertEqual(ps.MAX_PAGES, 20)

    def test_table_name(self):
        self.assertEqual(ps.TABLE_NAME, "aisearch_pages_raw")

    def test_counter_ac_no_21st_page_request(self):
        """무한히 has_next=True 인 결과라도 fetcher 는 정확히 20번만 호출된다."""
        fetch = make_list_fetcher(total_pages=999, details_per_page=0, hard_fail_after=20)
        store = FakeStore()
        result = ps.paginate_and_store(
            fetch, fetch_detail, store,
            channel="saramin", position_ref="pos-1", machine="macmini",
        )
        self.assertEqual(len(fetch.calls), 20)
        self.assertEqual(max(fetch.calls), 20)
        self.assertNotIn(21, fetch.calls)
        self.assertEqual(result.pages_crawled, 20)

    def test_cap_reached_signals_switch_boolean_variant(self):
        fetch = make_list_fetcher(total_pages=999, details_per_page=0, hard_fail_after=20)
        result = ps.paginate_and_store(
            fetch, fetch_detail, FakeStore(),
            channel="saramin", position_ref="pos-1", machine="macmini",
        )
        self.assertEqual(result.next_action, "switch_boolean_variant")

    def test_exhausted_before_cap(self):
        fetch = make_list_fetcher(total_pages=3, details_per_page=1)
        result = ps.paginate_and_store(
            fetch, fetch_detail, FakeStore(),
            channel="jobkorea", position_ref="pos-2", machine="macbook",
        )
        self.assertEqual(result.pages_crawled, 3)
        self.assertEqual(len(fetch.calls), 3)
        self.assertEqual(result.next_action, "exhausted")


class TestFullCapture(unittest.TestCase):
    def test_row_count_equals_pages_plus_details(self):
        """저장 row 수 == 순회 페이지 수 + 열어본 상세 수 (D4 전량 저장)."""
        fetch = make_list_fetcher(total_pages=4, details_per_page=3)
        store = FakeStore()
        result = ps.paginate_and_store(
            fetch, fetch_detail, store,
            channel="linkedin_rps", position_ref="pos-3", machine="winpc",
        )
        self.assertEqual(result.pages_crawled, 4)
        self.assertEqual(result.details_opened, 12)
        self.assertEqual(result.rows_saved, 4 + 12)
        self.assertEqual(len(store.calls), 4 + 12)
        list_rows = [r for t, r in store.calls if r["page_type"] == "list"]
        detail_rows = [r for t, r in store.calls if r["page_type"] == "detail"]
        self.assertEqual(len(list_rows), 4)
        self.assertEqual(len(detail_rows), 12)

    def test_rows_go_to_aisearch_pages_raw_with_full_shape(self):
        fetch = make_list_fetcher(total_pages=2, details_per_page=1)
        store = FakeStore()
        ps.paginate_and_store(
            fetch, fetch_detail, store,
            channel="saramin", position_ref="pos-4", machine="macmini",
        )
        expected_keys = {
            "id", "channel", "page_type", "url", "captured_at",
            "raw_html_or_text", "position_ref", "machine",
        }
        self.assertTrue(store.calls)
        for table, row in store.calls:
            self.assertEqual(table, "aisearch_pages_raw")
            self.assertEqual(set(row.keys()), expected_keys)
            self.assertIn(row["page_type"], ("list", "detail"))
            self.assertEqual(row["channel"], "saramin")
            self.assertEqual(row["position_ref"], "pos-4")
            self.assertEqual(row["machine"], "macmini")
            self.assertTrue(row["url"].startswith("https://example.test/"))
            self.assertTrue(row["raw_html_or_text"])
            self.assertTrue(row["captured_at"])

    def test_row_ids_unique(self):
        fetch = make_list_fetcher(total_pages=5, details_per_page=2)
        store = FakeStore()
        ps.paginate_and_store(
            fetch, fetch_detail, store,
            channel="saramin", position_ref="pos-5", machine="macmini",
        )
        ids = [row["id"] for _, row in store.calls]
        self.assertEqual(len(ids), len(set(ids)))

    def test_zero_detail_refs_still_saves_list_pages(self):
        fetch = make_list_fetcher(total_pages=2, details_per_page=0)
        store = FakeStore()
        result = ps.paginate_and_store(
            fetch, fetch_detail, store,
            channel="jobkorea", position_ref="pos-6", machine="macbook",
        )
        self.assertEqual(result.details_opened, 0)
        self.assertEqual(result.rows_saved, 2)
        self.assertEqual(len(store.calls), 2)


if __name__ == "__main__":
    unittest.main()
