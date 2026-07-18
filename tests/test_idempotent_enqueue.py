"""조각 B — 원자적 enqueue-or-get (discord-direct-connect goal §5 B).

DB 에는 idempotency_key 유니크 인덱스(20260713_fleet_job_idempotency.sql)가 있으나,
클라이언트 enqueue 는 중복 삽입 시 PostgREST 409(23505)를 그대로 던져 (a) 기존 잡을
회수하지 못하고 (b) raw DB 에러 문자열을 상위로 흘린다. 조각 B 는 이를 봉인한다:

인수 기준(기계 단언):
- 같은 idempotency_key 로 2회 enqueue → HTTP POST 는 2번째에 409 → 기존 잡 1개를 회수해
  반환(잡 1개·응답 1개). 두 번째 호출이 새 잡을 만들지 않는다.
- 409 충돌 시 raw DB 에러 본문/체인을 노출하지 않는다(redact — 코드만).
- idempotency_key 가 없는 payload 의 409 는 회수 불가 → redact 된 예외(원문 미노출).
- job_by_idempotency_key(key): 키로 기존 잡 1건 조회(없으면 None), 키는 URL 인코딩.
"""

from __future__ import annotations

import io
import socket
import urllib.error

import pytest

from tools.multi_position_sourcing.job_queue import (
    JobQueueClient,
    JobQueueConflictError,
    new_job_payload,
)


_PUBLIC = ("93.184.216.34",)


def _resolver(*ips):
    def fake(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in (ips or _PUBLIC)]
    return fake


def _client():
    return JobQueueClient(url="https://example.supabase.co", key="k",
                          getaddrinfo=_resolver())


def _payload(idem="discord:111222333444555666"):
    return new_job_payload(
        machine="macmini", skill="aisearch",
        position_url="https://app.clickup.com/t/abc",
        requested_by="814353841088757800:owner", role="owner",
        params={"idempotency_key": idem} if idem else {},
    )


def _http_409(body: bytes = b'{"code":"23505","message":"duplicate key value","details":"SECRET raw"}'):
    return urllib.error.HTTPError(
        "https://example.supabase.co/rest/v1/jobs", 409, "Conflict",
        {"Content-Type": "application/json"}, io.BytesIO(body))


def test_duplicate_idempotency_returns_existing_job_not_a_second_insert(monkeypatch):
    c = _client()
    existing = {"id": 42, "status": "queued", "params": {"idempotency_key": "discord:111222333444555666"}}
    calls: list = []

    def fake_call(method, path, payload=None, prefer="return=representation"):
        calls.append((method, path))
        if method == "POST" and path == "/jobs":
            raise _http_409()
        if method == "GET" and "idempotency_key" in path:
            return [existing]
        raise AssertionError(f"unexpected call {method} {path}")

    monkeypatch.setattr(c, "_call", fake_call)
    job = c.enqueue(_payload())
    assert job == existing, "중복 이벤트는 기존 잡을 회수해 반환해야 한다(새 잡 생성 금지)"
    assert [m for m, _ in calls] == ["POST", "GET"], "POST 409 후 GET 회수 정확히 1회"


def test_conflict_does_not_leak_raw_db_error(monkeypatch):
    # idempotency_key 없는 payload 가 409 → 회수 불가 → redact 예외(원문 SECRET 미노출).
    c = _client()

    def fake_call(method, path, payload=None, prefer="return=representation"):
        if method == "POST":
            raise _http_409()
        return []

    monkeypatch.setattr(c, "_call", fake_call)
    with pytest.raises(JobQueueConflictError) as ei:
        c.enqueue(_payload(idem=None))
    msg = str(ei.value)
    assert "SECRET" not in msg and "23505" not in msg and "duplicate key" not in msg, msg
    assert "409" in msg  # 코드만 노출


def test_idempotency_conflict_but_no_existing_row_is_redacted_error(monkeypatch):
    # 409 인데 키로 조회해도 기존 잡이 없으면(다른 유니크 위반 등) 회수 대신 redact 예외.
    c = _client()

    def fake_call(method, path, payload=None, prefer="return=representation"):
        if method == "POST":
            raise _http_409()
        if method == "GET":
            return []  # 기존 잡 없음
        raise AssertionError

    monkeypatch.setattr(c, "_call", fake_call)
    with pytest.raises(JobQueueConflictError) as ei:
        c.enqueue(_payload())
    assert "SECRET" not in str(ei.value)


def test_job_by_idempotency_key_encodes_and_returns_single(monkeypatch):
    c = _client()
    captured = {}

    def fake_call(method, path, payload=None, prefer="return=representation"):
        captured["path"] = path
        return [{"id": 7}]

    monkeypatch.setattr(c, "_call", fake_call)
    got = c.job_by_idempotency_key("discord:999")
    assert got == {"id": 7}
    assert "idempotency_key" in captured["path"]
    assert "discord%3A999" in captured["path"], "키는 URL 인코딩되어야 한다(: → %3A)"


def test_job_by_idempotency_key_missing_returns_none(monkeypatch):
    c = _client()
    monkeypatch.setattr(c, "_call", lambda *a, **k: [])
    assert c.job_by_idempotency_key("discord:none") is None


def test_non_conflict_http_error_still_propagates_redacted(monkeypatch):
    # 500 등 다른 HTTP 오류도 raw 미노출로 감싼다(회수는 409 에만).
    c = _client()

    def fake_call(method, path, payload=None, prefer="return=representation"):
        raise urllib.error.HTTPError(
            "u", 500, "Server Error", {}, io.BytesIO(b"SECRET internal trace"))

    monkeypatch.setattr(c, "_call", fake_call)
    with pytest.raises(JobQueueConflictError) as ei:
        c.enqueue(_payload())
    assert "SECRET" not in str(ei.value) and "500" in str(ei.value)
