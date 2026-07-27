"""AC-3 — 검색 결과 페이지네이션(최대 20페이지) + 전량 저장 파이프라인.

근거: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-3, §3 D3·D4, §5 계약.

- D3: 최대 20페이지. 21페이지째 요청은 절대 나가지 않는다.
  20페이지 도달 시 그 키워드 조합 종료 → "switch_boolean_variant" 시그널로
  다음 불린 변형 전환을 알린다. 그 전에 소진되면 "exhausted".
- D4: 열어본 리스트 페이지 + 상세 프로필 페이지를 빠짐없이 저장한다.
  저장소는 주입식(store.upsert(table, row)) — 이 모듈은 Supabase 를 직접
  호출하지 않는다(네트워크 없음).
- 테이블: aisearch_pages_raw(가칭 — 오너 확정 필요, D12·§8-2).
  row: id, channel, page_type(list|detail), url, captured_at,
       raw_html_or_text, position_ref, machine.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

MAX_PAGES = 20  # D3 — 절대 상한. 이 값을 넘는 리스트 페이지 요청은 나가면 안 된다.
TABLE_NAME = "aisearch_pages_raw"  # 가칭 — 오너 확정 필요(D12·§8-2)

# next_action 시그널 값
NEXT_SWITCH_BOOLEAN_VARIANT = "switch_boolean_variant"  # 20페이지 도달 → 다음 불린 변형
NEXT_EXHAUSTED = "exhausted"  # cap 전에 결과 소진


class PageStore(Protocol):
    """주입식 저장소 계약. 실제 Supabase 어댑터는 별도 AC 에서 이 계약을 구현한다."""

    def upsert(self, table: str, row: dict) -> None: ...


@dataclass(frozen=True)
class PaginationResult:
    pages_crawled: int
    details_opened: int
    rows_saved: int
    next_action: str  # NEXT_SWITCH_BOOLEAN_VARIANT | NEXT_EXHAUSTED


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_row(
    *,
    channel: str,
    page_type: str,
    url: str,
    raw: str,
    position_ref: str,
    machine: str,
    captured_at: str,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "channel": channel,
        "page_type": page_type,
        "url": url,
        "captured_at": captured_at,
        "raw_html_or_text": raw,
        "position_ref": position_ref,
        "machine": machine,
    }


def paginate_and_store(
    fetch_list_page: Callable[[int], dict],
    fetch_detail_page: Callable[[str], dict],
    store: PageStore,
    *,
    channel: str,
    position_ref: str,
    machine: str,
) -> PaginationResult:
    """검색 결과를 1페이지부터 최대 MAX_PAGES 까지 순회하며 전량 저장한다.

    fetch_list_page(page) -> {"url", "content", "detail_refs", "has_next"}
    fetch_detail_page(ref) -> {"url", "content"}

    반환 next_action:
    - "switch_boolean_variant": 20페이지까지 다 돌았고 결과가 더 남아 있음(D3 종료 시그널)
    - "exhausted": cap 전에 결과 소진
    """
    pages_crawled = 0
    details_opened = 0
    rows_saved = 0
    next_action = NEXT_EXHAUSTED

    for page in range(1, MAX_PAGES + 1):
        list_page = fetch_list_page(page)
        pages_crawled += 1

        captured_at = _utcnow_iso()
        store.upsert(
            TABLE_NAME,
            _make_row(
                channel=channel,
                page_type="list",
                url=list_page["url"],
                raw=list_page["content"],
                position_ref=position_ref,
                machine=machine,
                captured_at=captured_at,
            ),
        )
        rows_saved += 1

        for ref in list_page.get("detail_refs", []):
            detail = fetch_detail_page(ref)
            details_opened += 1
            store.upsert(
                TABLE_NAME,
                _make_row(
                    channel=channel,
                    page_type="detail",
                    url=detail["url"],
                    raw=detail["content"],
                    position_ref=position_ref,
                    machine=machine,
                    captured_at=_utcnow_iso(),
                ),
            )
            rows_saved += 1

        if not list_page.get("has_next", False):
            next_action = NEXT_EXHAUSTED
            break
        if page == MAX_PAGES:
            # D3: 결과가 남아 있어도 여기서 끝. 21페이지 요청은 나가지 않는다.
            next_action = NEXT_SWITCH_BOOLEAN_VARIANT
            break

    return PaginationResult(
        pages_crawled=pages_crawled,
        details_opened=details_opened,
        rows_saved=rows_saved,
        next_action=next_action,
    )
