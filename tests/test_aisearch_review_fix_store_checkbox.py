"""2026-07-31 전수 리뷰 — H4 체크박스 목표상태 · H5 저장 멱등키/원자성 (U6/U7).

goal: docs/engineering/aisearch-review-fix-goal-2026-07-31.md

- H4: 체크박스 스텝에 목표 상태(desired_state)가 없어서, 이미 체크된 항목을
  다시 눌러 **해제**했다(학력 필터가 조용히 풀림). 드라이버는 현재 상태를
  확인하고 목표와 다를 때만 클릭해야 한다.
- H5: JsonlPageStore 의 저장 키에 page_type 이 빠져 make_row_id 계약과 어긋났다
  (같은 URL 의 목록/상세가 서로 덮어씀). 저장도 비원자적이라 쓰기 도중 죽으면
  파일 전체가 깨질 수 있었다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.aisearch.core.cdp_driver import CdpDriver
from apps.aisearch.core.pagination_store import TABLE_NAME, make_row_id
from apps.aisearch.core.portal_search import (
    STEP_KIND_CHECKBOX,
    build_portal_search_descriptors,
)
from apps.aisearch.run import JsonlPageStore


# ── H4 — 체크박스 계약 ─────────────────────────────────────────────────────


def _jobkorea_checkbox_step():
    descriptors = build_portal_search_descriptors(
        or_keywords=["백엔드"], and_keywords=["Python"]
    )
    jk = next(d for d in descriptors if d["channel"] == "jobkorea")
    return next(s for s in jk["steps"] if s["kind"] == STEP_KIND_CHECKBOX)


def test_h4_checkbox_step_declares_desired_state():
    step = _jobkorea_checkbox_step()
    assert step["desired_state"] is True, (
        "체크박스 스텝은 '클릭'이 아니라 '목표 상태'를 선언해야 한다"
    )


class _CheckboxTransport:
    """체크박스 현재 상태를 흉내내는 페이크 — 클릭 횟수를 센다."""

    def __init__(self, initially_checked: bool):
        self.checked = initially_checked
        self.clicks = 0

    def __call__(self, method: str, params: dict) -> dict:
        if method == "Page.navigate":
            return {"frameId": "F1"}
        if method == "Input.dispatchMouseEvent":
            if params.get("type") == "mousePressed":
                self.clicks += 1
                self.checked = not self.checked
            return {}
        if method.startswith("Input."):
            return {}
        expr = params.get("expression", "")
        value: object = True
        if "/*vh:ready*/" in expr:
            value = "complete"
        elif "/*vh:rect*/" in expr:
            value = {"x": 10.0, "y": 10.0}
        elif "/*vh:checked*/" in expr:
            value = self.checked
        elif "/*vh:html*/" in expr:
            value = "<html></html>"
        elif "/*vh:url*/" in expr:
            value = "https://fake.test/list"
        return {"result": {"value": value}}


def _descriptor_with_checkbox():
    return {
        "url": "https://www.jobkorea.co.kr/Corp/Person/Find",
        "steps": [
            {
                "order": 1,
                "field": "education",
                "selector": "#education1",
                "values": ["대학교(4년) 졸업"],
                "kind": STEP_KIND_CHECKBOX,
                "desired_state": True,
            }
        ],
    }


def test_h4_already_checked_box_is_not_clicked():
    """counter-AC: 이미 checked 면 클릭 0회(다시 눌러 해제하지 않는다)."""
    transport = _CheckboxTransport(initially_checked=True)
    CdpDriver(transport).run_descriptor(_descriptor_with_checkbox())

    assert transport.clicks == 0, "이미 체크된 항목을 다시 눌러 해제했다"
    assert transport.checked is True


def test_h4_unchecked_box_is_clicked_once():
    transport = _CheckboxTransport(initially_checked=False)
    CdpDriver(transport).run_descriptor(_descriptor_with_checkbox())

    assert transport.clicks == 1
    assert transport.checked is True


def test_h4_missing_checkbox_fails_closed():
    class _MissingTransport(_CheckboxTransport):
        def __call__(self, method, params):
            if "/*vh:checked*/" in params.get("expression", ""):
                return {"result": {"value": None}}  # 셀렉터 미발견
            return super().__call__(method, params)

    from apps.aisearch.core.cdp_driver import CdpDriverError

    with pytest.raises(CdpDriverError):
        CdpDriver(_MissingTransport(False)).run_descriptor(_descriptor_with_checkbox())


# ── H5 — 저장 멱등키 + 원자적 쓰기 ─────────────────────────────────────────


def _row(page_type: str, url: str = "https://p.example/1") -> dict:
    return {
        "id": make_row_id(
            channel="saramin", page_type=page_type, url=url, position_ref="P1"
        ),
        "channel": "saramin",
        "page_type": page_type,
        "url": url,
        "position_ref": "P1",
        "raw_html_or_text": f"<html>{page_type}</html>",
        "machine": "macmini",
        "captured_at": "2026-07-31T00:00:00+00:00",
    }


def test_h5_list_and_detail_of_same_url_are_separate_rows(tmp_path):
    """counter-AC: page_type 만 다른 동일 URL 은 서로 다른 행이어야 한다."""
    store = JsonlPageStore(tmp_path / "pages.jsonl")
    store.upsert(TABLE_NAME, _row("list"))
    store.upsert(TABLE_NAME, _row("detail"))

    rows = [
        json.loads(line)
        for line in (tmp_path / "pages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 2, f"page_type 이 키에 없어 행이 덮어써졌다: {rows}"
    assert {r["page_type"] for r in rows} == {"list", "detail"}


def test_h5_same_key_upserts_in_place(tmp_path):
    store = JsonlPageStore(tmp_path / "pages.jsonl")
    store.upsert(TABLE_NAME, _row("list"))
    updated = _row("list")
    updated["raw_html_or_text"] = "<html>갱신</html>"
    store.upsert(TABLE_NAME, updated)

    rows = [
        json.loads(line)
        for line in (tmp_path / "pages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["raw_html_or_text"] == "<html>갱신</html>"


def test_h5_store_key_matches_make_row_id_contract(tmp_path):
    store = JsonlPageStore(tmp_path / "pages.jsonl")
    key = store._key(TABLE_NAME, _row("detail"))
    assert "detail" in key, f"저장 키에 page_type 이 없다: {key}"
    assert "saramin" in key and "P1" in key and "https://p.example/1" in key


def test_h5_crash_during_write_leaves_previous_file_intact(tmp_path, monkeypatch):
    """counter-AC: 저장 도중 크래시에도 기존 행 유실 0."""
    path = tmp_path / "pages.jsonl"
    store = JsonlPageStore(path)
    store.upsert(TABLE_NAME, _row("list"))
    before = path.read_text(encoding="utf-8")
    assert before.strip()

    import os as os_mod

    def boom(src, dst):
        raise OSError("디스크 가득 참 — 교체 직전 크래시")

    monkeypatch.setattr(os_mod, "replace", boom)

    with pytest.raises(OSError):
        store.upsert(TABLE_NAME, _row("detail"))

    assert path.read_text(encoding="utf-8") == before, "크래시로 기존 저장분이 손상됐다"


def test_h5_no_temp_files_left_behind(tmp_path):
    path = tmp_path / "pages.jsonl"
    store = JsonlPageStore(path)
    store.upsert(TABLE_NAME, _row("list"))
    store.upsert(TABLE_NAME, _row("detail"))

    leftovers = [
        p.name
        for p in Path(tmp_path).iterdir()
        if p.name != "pages.jsonl" and not p.name.endswith(".lock")
    ]
    assert leftovers == [], f"임시파일이 남았다: {leftovers}"
