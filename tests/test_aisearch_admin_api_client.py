"""AC-6 — admin.valuehire.cc HTTP 어댑터 (goal: aisearch-register-api-goal-2026-07-31.md).

2026-07-31 전수 리뷰(AC-1b) 이후: 이 파일이 유일한 admin 클라이언트이며,
전송 전 계약검증(필수 필드·https·키 16자)을 통과해야 요청이 나간다.
실제 네트워크는 만들지 않는다 — requests 를 monkeypatch 로 대체해 요청 모양만 검증한다.
"""
from __future__ import annotations

import json
import types

import pytest

from apps.aisearch.core.admin_api_client import (
    AdminApiConfigError,
    AdminApiRegisterError,
    AdminApiResponseError,
    HttpAdminApiClient,
)

VALID_KEY = "k" * 32
BASE = "https://admin.valuehire.cc"

#: 서버(route.ts)가 요구하는 최소 유효 payload — 이보다 적으면 전송 전에 거부된다.
VALID_PAYLOAD = {
    "name": "홍길동",
    "profile_url": "https://linkedin.com/in/hong",
    "match_score": 87,
    "why_fit": "직무 직결 경력 8년",
    "channel": "linkedin_rps",
}


def test_missing_config_fails_closed(monkeypatch):
    monkeypatch.delenv("ADMIN_API_BASE_URL", raising=False)
    monkeypatch.delenv("ADMIN_API_INTERNAL_KEY", raising=False)
    with pytest.raises(AdminApiConfigError):
        HttpAdminApiClient()


class _FakeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.text = json.dumps(body)
        self._body = body

    def json(self):
        return self._body


def _fake_requests(monkeypatch, status: int, body: dict, captured: dict):
    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return _FakeResponse(status, body)

    monkeypatch.setitem(
        __import__("sys").modules, "requests", types.SimpleNamespace(post=fake_post)
    )


def test_register_candidate_sends_internal_key_header_and_payload(monkeypatch):
    captured: dict = {}
    _fake_requests(
        monkeypatch,
        201,
        {"ok": True, "candidate": {"id": "x"}, "deduped": False},
        captured,
    )

    client = HttpAdminApiClient(base_url=BASE, internal_key=VALID_KEY, live=True)
    result = client.register_candidate(dict(VALID_PAYLOAD))

    assert result["ok"] is True
    assert captured["url"] == f"{BASE}/api/aisearch/register"
    assert captured["headers"]["x-internal-key"] == VALID_KEY
    assert captured["json"]["name"] == "홍길동"
    assert captured["json"]["match_score"] == 87


def test_register_candidate_raises_on_error_status(monkeypatch):
    captured: dict = {}
    _fake_requests(
        monkeypatch, 400, {"ok": False, "error": "match_score below threshold"}, captured
    )

    client = HttpAdminApiClient(base_url=BASE, internal_key=VALID_KEY, live=True)
    with pytest.raises((AdminApiRegisterError, AdminApiResponseError)):
        client.register_candidate(dict(VALID_PAYLOAD))
