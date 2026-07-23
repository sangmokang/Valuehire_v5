"""이슈 #190 — 디스코드 최소권한 경로에 login 허용(/login 라이브 접수).

인수 기준: 이 파일이 GREEN.
- (a) MinimalPrivilegeQueueClient.enqueue 가 login 페이로드(빈 URL)를 거부하지 않고
      RPC 로 전달한다. 공인 DNS(SSRF) 검사는 login 의 빈 URL 만 면제.
- (b) 기존 방어는 그대로: agent/미지정 스킬 거부, 검색 스킬의 SSRF 검사,
      login 에 URL 이 실리면 거부.
- (c) 라이브 RPC(discord_gateway_enqueue) 화이트리스트에 login 을 추가하는
      마이그레이션이 존재하며 기존 가드(role='member' 강제, discord 이벤트 기반
      idempotency 필수, advisory lock)를 유지한다.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, "scripts")

from discord_direct_gateway import MinimalPrivilegeQueueClient  # noqa: E402

from tools.multi_position_sourcing.job_queue import new_job_payload  # noqa: E402

OWNER_ID = "814353841088757800"
EVENT_KEY = "discord:1529896791565275137"


class _CapturingClient(MinimalPrivilegeQueueClient):
    """네트워크 대신 RPC 호출 페이로드만 기록."""

    def __init__(self):
        super().__init__(url="https://0.0.0.0.invalid", key="dummy")
        self.calls: list[tuple[str, dict]] = []

    def _rpc(self, name, payload):
        self.calls.append((name, payload))
        return [{"id": 1, "machine": payload.get("p_machine"),
                 "skill": payload.get("p_skill"), "status": "queued",
                 "created_at": "2026-07-24T00:00:00+00:00", "created": True}]


def _payload(skill="login", position_url="", params=None):
    params = dict(params or {})
    params.setdefault("idempotency_key", EVENT_KEY)
    payload = new_job_payload(
        machine="macmini", skill=skill, position_url=position_url,
        requested_by=OWNER_ID, role="member", params=params,
    )
    assert payload is not None, "테스트 전제: 페이로드 자체는 유효해야 한다"
    return payload


def test_minimal_client_enqueues_login_with_empty_url():
    client = _CapturingClient()
    job = client.enqueue(_payload())
    assert job["skill"] == "login"
    assert client.calls, "RPC 가 호출되어야 한다"
    name, sent = client.calls[0]
    assert name == "discord_gateway_enqueue"
    assert sent["p_skill"] == "login"
    assert sent["p_position_url"] == ""


def test_minimal_client_still_rejects_agent_before_network():
    client = _CapturingClient()
    with pytest.raises(PermissionError):
        client.enqueue({**_payload(), "skill": "agent"})
    assert client.calls == []


def test_minimal_client_search_ssrf_check_kept():
    client = _CapturingClient()
    bad = dict(_payload(skill="humansearch",
                        position_url="https://app.clickup.com/t/86eufjabc"))
    bad["position_url"] = "https://127.0.0.1/internal"
    with pytest.raises(ValueError):
        client.enqueue(bad)
    assert client.calls == []


def test_minimal_client_rejects_login_with_url():
    client = _CapturingClient()
    forged = dict(_payload())
    forged["position_url"] = "https://app.clickup.com/t/86eufjabc"
    with pytest.raises(ValueError):
        client.enqueue(forged)
    assert client.calls == []


def test_gateway_login_rpc_migration_exists_with_guards():
    files = sorted(pathlib.Path("supabase/migrations").glob(
        "*gateway_login*.sql"))
    assert files, "게이트웨이 RPC login 마이그레이션이 없습니다"
    sql = files[-1].read_text(encoding="utf-8")
    body = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    assert "discord_gateway_enqueue" in body
    assert "'login'" in body
    # 기존 가드 유지 — role 강제, discord 이벤트 idempotency, advisory lock.
    assert "'member'" in body
    assert "discord:[0-9]{15,22}" in body
    assert "pg_advisory_xact_lock" in body
    assert "security definer" in body.lower()
