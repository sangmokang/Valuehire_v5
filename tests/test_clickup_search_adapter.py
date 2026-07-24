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


# ── Codex V2 봉인 ────────────────────────────────────────────────────────


def test_f5_list_id_path_traversal_rejected():
    urlopen, _ = _capture_urlopen({"tasks": []})
    search = clickup_search.make_clickup_search_tasks("tok", urlopen=urlopen)
    with pytest.raises(ValueError):
        search(list_id="../team/123", query="x", parent=None)


def test_f5_factory_none_for_nonnumeric_list_id():
    assert clickup_search.production_nl_searcher_factory(
        env={"CLICKUP_API_TOKEN": "tok",
             "CLICKUP_POSITIONS_LIST_ID": "../team/9"}) is None


def test_f2_task_with_unsafe_id_is_dropped():
    urlopen, _ = _capture_urlopen({"tasks": [
        {"id": "86abc", "name": "good"},
        {"id": "../../evil", "name": "bad"},
        {"id": "", "name": "empty"},
    ]})
    search = clickup_search.make_clickup_search_tasks("tok", urlopen=urlopen)
    ids = [t["id"] for t in search(list_id="1", query="x", parent=None)]
    assert ids == ["86abc"]


def test_f2r_task_url_field_not_trusted_canonical_link_built():
    """Codex V2 2R — task['url'] 이 악성이어도 검증된 id 로 만든 정식 링크로 대체."""
    urlopen, _ = _capture_urlopen({"tasks": [
        {"id": "86exwz89j", "name": "PM", "url": "https://evil.example.com/x"}]})
    search = clickup_search.make_clickup_search_tasks("tok", urlopen=urlopen)
    task = search(list_id="1", query="x", parent=None)[0]
    assert task["url"] == "https://app.clickup.com/t/86exwz89j"
    assert "evil.example.com" not in task["url"]


def test_f2r_task_name_sanitized_for_display():
    """Codex V2 2R — 이름의 개행·마크다운/멘션 트리거를 안전화(표시 주입 차단)."""
    urlopen, _ = _capture_urlopen({"tasks": [
        {"id": "86a", "name": "PM\n@everyone [click](http://x)"}]})
    search = clickup_search.make_clickup_search_tasks("tok", urlopen=urlopen)
    name = search(list_id="1", query="x", parent=None)[0]["name"]
    assert "\n" not in name  # 개행 제거(멀티라인 주입 차단)
    assert "\\@everyone" in name  # @ 이스케이프(멘션 트리거 무력화)
    assert "](" not in name  # 마크다운 링크 문법 깨짐(] · ( 각각 이스케이프)


def test_f1_adapter_error_sanitized_no_token_or_url():
    def boom_urlopen(req, timeout=None):
        raise RuntimeError(f"connect to {req.full_url} with tok_SECRET failed")

    factory = clickup_search.production_nl_searcher_factory(
        env={"CLICKUP_API_TOKEN": "tok_SECRET",
             "CLICKUP_POSITIONS_LIST_ID": "901814621569"},
        urlopen=boom_urlopen)
    searcher = factory()
    with pytest.raises(RuntimeError) as ei:
        searcher("clickup", "PM")
    msg = str(ei.value)
    assert "tok_SECRET" not in msg and "api.clickup.com" not in msg
    assert "ClickUp" in msg  # 일반 안내만
