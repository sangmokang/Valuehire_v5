"""AC-6 — admin.valuehire.cc HTTP 어댑터 (goal: aisearch-register-api-goal-2026-07-31.md).

실제 네트워크는 만들지 않는다 — requests.post 를 monkeypatch 로 대체해 요청 모양만 검증한다.
"""
from __future__ import annotations

import pytest

from apps.aisearch.core.admin_api_client import (
    AdminApiConfigError,
    AdminApiRegisterError,
    HttpAdminApiClient,
)


def test_missing_config_fails_closed(monkeypatch):
    monkeypatch.delenv("ADMIN_API_BASE_URL", raising=False)
    monkeypatch.delenv("ADMIN_API_INTERNAL_KEY", raising=False)
    with pytest.raises(AdminApiConfigError):
        HttpAdminApiClient()


class _FakeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_register_candidate_sends_internal_key_header_and_payload(monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _FakeResponse(201, {"ok": True, "candidate": {"id": "x"}, "deduped": False})

    import types
    fake_requests = types.SimpleNamespace(post=fake_post)
    monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)

    client = HttpAdminApiClient(base_url="https://admin.valuehire.cc", internal_key="k" * 32)
    result = client.register_candidate({"name": "홍길동"})

    assert result["ok"] is True
    assert captured["url"] == "https://admin.valuehire.cc/api/aisearch/register"
    assert captured["headers"]["x-internal-key"] == "k" * 32
    assert captured["json"] == {"name": "홍길동"}


def test_register_candidate_raises_on_error_status(monkeypatch):
    def fake_post(url, json, headers, timeout):
        return _FakeResponse(400, {"ok": False, "error": "match_score below threshold"})

    import types
    fake_requests = types.SimpleNamespace(post=fake_post)
    monkeypatch.setitem(__import__("sys").modules, "requests", fake_requests)

    client = HttpAdminApiClient(base_url="https://admin.valuehire.cc", internal_key="k" * 32)
    with pytest.raises(AdminApiRegisterError):
        client.register_candidate({"name": "홍길동"})
