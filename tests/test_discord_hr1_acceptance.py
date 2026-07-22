from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from scripts import discord_direct_gateway as gateway
from tests.test_discord_direct_gateway import FakeMessage
from tools.multi_position_sourcing.access import DiscordAuthorizedUser
from tools.multi_position_sourcing.discord_hr1 import (
    GatewayLeaseGuard,
    Hr1ReceiptError,
    validate_hr1_receipt,
)
from tools.multi_position_sourcing.discord_routing import DiscordAccessConfig


ROOT = Path(__file__).resolve().parents[1]
OWNER = "814353841088757800"
BOT = "946740848018735114"
HERMES_BOT = "1512101118543397056"
POSITION = "https://app.clickup.com/t/9018789656/86eycec3a"


def _job(agent: str, event_id: str, job_id: int, response_id: str) -> dict:
    return {
        "agent": agent,
        "event_id": event_id,
        "job_id": job_id,
        "requester_id": OWNER,
        "transitions": ["queued", "running", "done"],
        "response_id": response_id,
        "response_count": 1,
    }


def _valid_receipt() -> dict:
    return {
        "schema_version": "discord-hr1/v1",
        "phase": "HR-1",
        "git_sha_v4": "a" * 40,
        "git_sha_v5": "b" * 40,
        "discord_bot_id": BOT,
        "hermes_bot_id": HERMES_BOT,
        "bot_identity_isolated": True,
        "command_fingerprint": "c" * 64,
        "direct_gateway_pid": 1234,
        "direct_gateway_lease_id": "11111111-1111-4111-8111-111111111111",
        "gateway_stopped_after_test": True,
        "readiness": {
            "minimal_rpc": True,
            "worker_machine": "macbook",
            "worker_heartbeat_age_seconds": 20,
        },
        "duplicate_event": {
            "event_id": "1529267252160927201",
            "first_job_id": 201,
            "replay_job_id": 201,
            "row_count": 1,
        },
        "jobs": [
            _job("claude", "1529267252160927202", 202, "1529267252160927302"),
            _job("codex", "1529267252160927203", 203, "1529267252160927303"),
        ],
        "natural_language": {
            **_job("claude", "1529267252160927204", 204, "1529267252160927304"),
            "text_fingerprint": "d" * 64,
        },
        "duplicate_response_count": 0,
        "verified_at": "2026-07-22T12:00:00+00:00",
        "verifier_sha256": "e" * 64,
    }


def test_hr1_receipt_requires_complete_live_evidence() -> None:
    assert validate_hr1_receipt(_valid_receipt())["phase"] == "HR-1"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda r: r.update(bot_identity_isolated=False),
        lambda r: r.update(gateway_stopped_after_test=False),
        lambda r: r["readiness"].update(worker_heartbeat_age_seconds=301),
        lambda r: r["jobs"][0].update(transitions=["queued", "done"]),
        lambda r: r["jobs"][1].update(response_count=2),
        lambda r: r["duplicate_event"].update(replay_job_id=999),
        lambda r: r.update(duplicate_response_count=1),
    ),
)
def test_hr1_receipt_fails_closed(mutate) -> None:
    receipt = _valid_receipt()
    mutate(receipt)
    with pytest.raises(Hr1ReceiptError):
        validate_hr1_receipt(receipt)


class _RuntimeQueue:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.calls: list[tuple] = []

    def gateway_readiness(self, machine: str, max_age_seconds: int) -> dict:
        self.calls.append(("ready", machine, max_age_seconds))
        return {"minimal_rpc": True, "worker_ready": self.ready}

    def acquire_gateway_lease(self, bot_id: str, instance_id: str, ttl_seconds: int) -> dict:
        self.calls.append(("acquire", bot_id, instance_id, ttl_seconds))
        return {"lease_id": "11111111-1111-4111-8111-111111111111"}

    def renew_gateway_lease(self, lease_id: str, instance_id: str, ttl_seconds: int) -> dict:
        self.calls.append(("renew", lease_id, instance_id, ttl_seconds))
        return {"lease_id": lease_id}

    def release_gateway_lease(self, lease_id: str, instance_id: str) -> dict:
        self.calls.append(("release", lease_id, instance_id))
        return {"released": True}


def test_gateway_guard_checks_readiness_acquires_and_releases() -> None:
    queue = _RuntimeQueue()
    guard = GatewayLeaseGuard(queue, bot_id=BOT, machine="macbook", pid=1234)
    with guard:
        assert guard.lease_id
    assert [call[0] for call in queue.calls] == ["ready", "acquire", "release"]


def test_gateway_guard_never_acquires_when_worker_is_stale() -> None:
    queue = _RuntimeQueue(ready=False)
    guard = GatewayLeaseGuard(queue, bot_id=BOT, machine="macbook", pid=1234)
    with pytest.raises(RuntimeError, match="heartbeat"):
        guard.start()
    assert [call[0] for call in queue.calls] == ["ready"]


def test_minimal_privilege_sql_defines_hr1_runtime_rpcs() -> None:
    sql = (ROOT / "supabase/migrations/20260722_discord_gateway_hr1_runtime.sql").read_text()
    for marker in (
        "discord_gateway_readiness",
        "discord_gateway_acquire_lease",
        "discord_gateway_renew_lease",
        "discord_gateway_release_lease",
        "grant execute",
        "to anon",
    ):
        assert marker in sql


def test_plain_natural_url_reaches_queue_without_clickup_searcher() -> None:
    class Queue:
        def __init__(self) -> None:
            self.enqueued: list[dict] = []

        def enqueue(self, payload: dict) -> dict:
            self.enqueued.append(payload)
            return {**payload, "id": 501}

    queue = Queue()
    message = FakeMessage(
        message_id="1529267252160927401",
        author_id=OWNER,
        content=f"이 포지션으로 후보 찾아줘 {POSITION}",
    )
    asyncio.run(gateway.handle_text_message(
        message,
        bot_user_id=BOT,
        queue=queue,
        authorized_users=(DiscordAuthorizedUser(
            name="owner", alias="owner", email="owner@example.com", discord_id=OWNER),),
        config=DiscordAccessConfig(allow_dm=True),
    ))
    assert len(queue.enqueued) == 1
    assert queue.enqueued[0]["skill"] == "aisearch"
    assert queue.enqueued[0]["position_url"] == POSITION
    assert queue.enqueued[0]["params"]["idempotency_key"] == (
        "discord:1529267252160927401"
    )
