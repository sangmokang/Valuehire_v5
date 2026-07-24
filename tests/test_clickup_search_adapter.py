"""이슈 #200 — ClickUp 포지션 검색 REST 어댑터 + 운영 게이트웨이 NL 배선.

라이브(2026-07-24): DM 자연어가 안 먹는 이유는 nl_shell 로직이 아니라 *배선* —
운영 클라이언트가 searcher 를 안 넘겨 searcher=None 으로 NL 이 죽고, ClickUp REST
어댑터도 repo 에 없다. 이 파일은 그 두 구멍을 계약으로 고정한다.

인수 기준(이 파일 + test_gateway_nl_connect.py 가 GREEN):
- make_clickup_search_tasks(token) → callable(list_id=, query=, parent=) 가
  GET https://api.clickup.com/api/v2/list/{list_id}/task 를 호출(Authorization
  헤더=token)하고 응답 JSON 의 tasks 배열을 반환한다.
- clickup_position_searcher 와 결합하면 nl_shell 이 후보를 만들 수 있다.
- 토큰/list_id 미설정이면 운영 팩토리가 None → NL 조용히 비활성(회귀 없음).
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from tools.multi_position_sourcing import clickup_search
from tools.multi_position_sourcing import nl_shell


class _FakeResp:
    def __init__(self, payload: Any):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture_urlopen(payload):
    seen = {}

    def urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return _FakeResp(payload)

    return urlopen, seen


def test_adapter_calls_list_task_endpoint_with_token():
    urlopen, seen = _capture_urlopen(
        {"tasks": [{"id": "86abc", "name": "PM (Core)"}]})
    search = clickup_search.make_clickup_search_tasks("tok_XYZ", urlopen=urlopen)
    tasks = search(list_id="901814621569", query="PM", parent=None)
    assert "api.clickup.com/api/v2/list/901814621569/task" in seen["url"]
    assert seen["auth"] == "tok_XYZ"
    assert isinstance(tasks, list) and tasks[0]["id"] == "86abc"


def test_adapter_returns_empty_on_no_tasks_key():
    urlopen, _ = _capture_urlopen({"other": []})
    search = clickup_search.make_clickup_search_tasks("tok", urlopen=urlopen)
    assert search(list_id="1", query="x", parent=None) == []


def test_adapter_composes_with_position_searcher():
    urlopen, _ = _capture_urlopen(
        {"tasks": [{"id": "86exwz89j", "name": "번개장터 PM (Core Product)"}]})
    searcher = nl_shell.clickup_position_searcher(
        clickup_search.make_clickup_search_tasks("tok", urlopen=urlopen),
        list_id="901814621569")
    hits = searcher("clickup", "번개장터 PM")
    assert len(hits) == 1
    assert hits[0].url == "https://app.clickup.com/t/86exwz89j"


def test_production_factory_none_when_unconfigured():
    """ClickUp 미설정이면 팩토리는 None — NL 비활성(기존 명령 경로 불변, fail-safe)."""
    assert clickup_search.production_nl_searcher_factory(env={}) is None
    assert clickup_search.production_nl_searcher_factory(
        env={"CLICKUP_API_TOKEN": "tok"}) is None  # list_id 없음
    assert clickup_search.production_nl_searcher_factory(
        env={"CLICKUP_POSITIONS_LIST_ID": "1"}) is None  # 토큰 없음


def test_production_factory_builds_callable_when_configured():
    factory = clickup_search.production_nl_searcher_factory(
        env={"CLICKUP_API_TOKEN": "tok", "CLICKUP_POSITIONS_LIST_ID": "901814621569"})
    assert callable(factory)
    assert callable(factory())  # 팩토리() → searcher 콜러블
