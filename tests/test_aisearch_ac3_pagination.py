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


class UpsertFakeStore:
    """진짜 upsert 의미의 가짜 저장소 — (table, id) 키로 덮어쓴다(중복 행 불가능)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}
        self.upsert_calls = 0

    def upsert(self, table: str, row: dict) -> None:
        self.upsert_calls += 1
        self.rows[(table, row["id"])] = dict(row)


class FlakyAckStore(UpsertFakeStore):
    """저장은 됐지만 확인(ack)이 유실된 상황 — N번째 호출에서 저장 후 예외."""

    def __init__(self, fail_on_call: int) -> None:
        super().__init__()
        self._fail_on_call = fail_on_call
        self._failed = False

    def upsert(self, table: str, row: dict) -> None:
        super().upsert(table, row)  # 저장 자체는 성공
        if not self._failed and self.upsert_calls == self._fail_on_call:
            self._failed = True
            raise ConnectionError("저장확인 응답 유실 (row 는 이미 저장됨)")


class TestIdempotentIds(unittest.TestCase):
    """V1 결함 1 — 매 실행 임의 UUID → 재실행/재시도 시 중복 행."""

    def _run(self, store, *, total_pages=3, details=2):
        fetch = make_list_fetcher(total_pages=total_pages, details_per_page=details)
        return ps.paginate_and_store(
            fetch, fetch_detail, store,
            channel="saramin", position_ref="pos-idem", machine="macmini",
        )

    def test_id_is_deterministic_across_runs(self):
        """같은 channel+url+page_type 이면 실행이 달라도 id 가 같다."""
        s1, s2 = FakeStore(), FakeStore()
        self._run(s1)
        self._run(s2)
        ids1 = sorted(row["id"] for _, row in s1.calls)
        ids2 = sorted(row["id"] for _, row in s2.calls)
        self.assertEqual(ids1, ids2)

    def test_same_run_twice_zero_duplicates(self):
        """같은 실행을 2회 반복해도 upsert 의미로 중복 행 0."""
        store = UpsertFakeStore()
        self._run(store)
        first = len(store.rows)
        self._run(store)
        self.assertEqual(len(store.rows), first)
        self.assertEqual(first, 3 + 3 * 2)

    def test_retry_after_lost_ack_zero_duplicates(self):
        """저장확인 유실로 파이프라인이 죽은 뒤 전체 재시도해도 중복 행 0."""
        store = FlakyAckStore(fail_on_call=4)
        with self.assertRaises(ConnectionError):
            self._run(store)
        self._run(store)  # 재시도
        self.assertEqual(len(store.rows), 3 + 3 * 2)

    def test_different_page_type_same_url_ids_differ(self):
        row_a = ps.make_row_id(
            channel="saramin", page_type="list", url="https://x.test/a",
            position_ref="pos-idem",
        )
        row_b = ps.make_row_id(
            channel="saramin", page_type="detail", url="https://x.test/a",
            position_ref="pos-idem",
        )
        self.assertNotEqual(row_a, row_b)


class TestPositionRefInIdempotencyKey(unittest.TestCase):
    """V1 2차 결함 6 — 멱등키에 position_ref 미포함 → 두 포지션이 서로 덮어씀."""

    def test_same_profile_two_positions_do_not_overwrite(self):
        """같은 프로필(같은 url)을 두 포지션에서 저장해도 행이 따로 남는다."""
        store = UpsertFakeStore()
        for pos in ("pos-A", "pos-B"):
            fetch = make_list_fetcher(total_pages=1, details_per_page=1)
            ps.paginate_and_store(
                fetch, fetch_detail, store,
                channel="saramin", position_ref=pos, machine="macmini",
            )
        # (list 1 + detail 1) × 포지션 2 = 4행 — 덮어쓰기 0
        self.assertEqual(len(store.rows), 4)
        by_pos = {row["position_ref"] for row in store.rows.values()}
        self.assertEqual(by_pos, {"pos-A", "pos-B"})

    def test_make_row_id_differs_by_position_ref(self):
        a = ps.make_row_id(
            channel="saramin", page_type="detail", url="https://x.test/p/1",
            position_ref="pos-A",
        )
        b = ps.make_row_id(
            channel="saramin", page_type="detail", url="https://x.test/p/1",
            position_ref="pos-B",
        )
        self.assertNotEqual(a, b)

    def test_regression_same_position_retry_zero_duplicates(self):
        """회귀 — 같은 포지션 재시도는 여전히 중복 0."""
        store = UpsertFakeStore()
        for _ in range(2):
            fetch = make_list_fetcher(total_pages=1, details_per_page=1)
            ps.paginate_and_store(
                fetch, fetch_detail, store,
                channel="saramin", position_ref="pos-A", machine="macmini",
            )
        self.assertEqual(len(store.rows), 2)


class TestHasNextFailFast(unittest.TestCase):
    """V1 결함 2 — has_next 누락을 exhausted 로 조용히 처리하면 안 된다."""

    def test_missing_has_next_is_rejected(self):
        def fetch(page: int) -> dict:
            return {
                "url": f"https://example.test/search?page={page}",
                "content": "<html>x</html>",
                "detail_refs": [],
            }

        with self.assertRaises(ValueError):
            ps.paginate_and_store(
                fetch, fetch_detail, FakeStore(),
                channel="saramin", position_ref="pos-hn", machine="macmini",
            )

    def test_non_bool_has_next_is_rejected(self):
        def fetch(page: int) -> dict:
            return {
                "url": f"https://example.test/search?page={page}",
                "content": "<html>x</html>",
                "detail_refs": [],
                "has_next": "yes",
            }

        with self.assertRaises(ValueError):
            ps.paginate_and_store(
                fetch, fetch_detail, FakeStore(),
                channel="saramin", position_ref="pos-hn2", machine="macmini",
            )


class TestCapBeatsExhausted(unittest.TestCase):
    """V1 결함 3 — D3: 20페이지 도달이면 has_next 와 무관하게 CAP_REACHED 전환."""

    def test_page20_has_next_false_still_switch_boolean_variant(self):
        fetch = make_list_fetcher(total_pages=20, details_per_page=0, hard_fail_after=20)
        result = ps.paginate_and_store(
            fetch, fetch_detail, FakeStore(),
            channel="saramin", position_ref="pos-cap", machine="macmini",
        )
        self.assertEqual(result.pages_crawled, 20)
        self.assertEqual(result.next_action, "switch_boolean_variant")

    def test_exhausted_only_before_cap(self):
        fetch = make_list_fetcher(total_pages=19, details_per_page=0)
        result = ps.paginate_and_store(
            fetch, fetch_detail, FakeStore(),
            channel="saramin", position_ref="pos-cap2", machine="macmini",
        )
        self.assertEqual(result.pages_crawled, 19)
        self.assertEqual(result.next_action, "exhausted")


class TestPipelineInputFailFast(unittest.TestCase):
    """V1 결함 5 — channel/position_ref/machine 빈 값은 파이프라인 진입부터 거부."""

    def _assert_rejected(self, **kwargs):
        fetch = make_list_fetcher(total_pages=1, details_per_page=0)
        args = {"channel": "saramin", "position_ref": "pos-9", "machine": "macmini"}
        args.update(kwargs)
        with self.assertRaises(ValueError):
            ps.paginate_and_store(fetch, fetch_detail, FakeStore(), **args)
        self.assertEqual(fetch.calls, [])  # fetch 가 나가기 전에 막아야 한다

    def test_empty_channel(self):
        self._assert_rejected(channel="")

    def test_blank_position_ref(self):
        self._assert_rejected(position_ref="   ")

    def test_empty_machine(self):
        self._assert_rejected(machine="")


class TestSchemaDraftLocation(unittest.TestCase):
    """V1 결함 4 — 오너 미확정 SQL 은 migrations 밖 draft 로만 존재해야 한다."""

    MIGRATION = REPO / "supabase" / "migrations" / "20260728120000_aisearch_pages_raw_draft.sql"
    DRAFT = REPO / "apps" / "aisearch" / "schema" / "aisearch_pages_raw.draft.sql"

    def test_not_in_supabase_migrations(self):
        self.assertFalse(self.MIGRATION.exists(), "오너 미확정 스키마가 자동 적용 경로에 있으면 안 된다")

    def test_draft_exists_with_guard_and_idempotency_unique(self):
        self.assertTrue(self.DRAFT.exists())
        text = self.DRAFT.read_text(encoding="utf-8")
        self.assertIn("적용 금지", text)  # 오너 확정 전 적용 금지 명시
        self.assertIn("unique", text.lower())  # 멱등키 unique 제약
        for col in ("channel", "url", "page_type"):
            self.assertIn(col, text)

    def test_unique_constraint_columns_match_python_identity_key_exactly(self):
        """V1 독립검증 결함10 — 문자열 'unique' 존재만으론 실제 컬럼 구성을 못 잡는다.

        make_row_id()가 (channel, page_type, url, position_ref) 로 id 를 만드는데
        SQL unique 제약에서 position_ref 가 빠지면, 같은 프로필을 서로 다른
        포지션에서 만났을 때(앱은 별개 행 의도) DB가 (channel,page_type,url) 만
        보고 중복으로 오판해 두 번째 삽입을 거부한다 — 실제 제약 컬럼 목록을
        파싱해 파이썬 식별키와 정확히 같은 집합인지 비교한다.
        """
        import re

        text = self.DRAFT.read_text(encoding="utf-8")
        match = re.search(r"unique\s*\(([^)]+)\)", text, re.IGNORECASE)
        self.assertIsNotNone(match, "unique 제약 정의를 찾지 못함")
        sql_columns = {c.strip() for c in match.group(1).split(",")}

        import inspect

        from apps.aisearch.core.pagination_store import make_row_id

        # make_row_id 시그니처의 인자 이름을 실제 식별키로 삼는다(키워드 전용
        # 포함 — 하드코딩 두 벌을 유지하지 않고 함수 자체에서 회수).
        python_identity_fields = set(inspect.signature(make_row_id).parameters)
        self.assertEqual(
            sql_columns,
            python_identity_fields,
            f"SQL unique 컬럼({sql_columns})과 파이썬 식별키({python_identity_fields})가 다르다",
        )


if __name__ == "__main__":
    unittest.main()
