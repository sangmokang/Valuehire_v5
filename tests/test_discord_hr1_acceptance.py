from __future__ import annotations

import asyncio
import ast
import hashlib
from pathlib import Path
import threading

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
TOKEN = "isolated-test-token.not-a-live-secret"
TOKEN_FINGERPRINT = hashlib.sha256(TOKEN.encode()).hexdigest()


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
        "direct_gateway_generation": 7,
        "gateway_stopped_after_test": True,
        "hermes_pid_count": 1,
        "hermes_launchctl_count": 1,
        "hermes_pids_before": [4321],
        "hermes_pids_after": [4321],
        "readiness": {
            "minimal_rpc": True,
            "worker_machine": "winpc",
            "worker_heartbeat_age_seconds": 20,
            "killswitch_engaged": False,
        },
        "duplicate_event": {
            "event_id": "1529267252160927202",
            "first_job_id": 202,
            "replay_job_id": 202,
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
        "queue_nonterminal_count": 0,
        "rollback_tested": True,
        "claude_job_id": 202,
        "claude_response_id": "1529267252160927302",
        "codex_job_id": 203,
        "codex_response_id": "1529267252160927303",
        "event_id": "1529267252160927202",
        "job_id": 202,
        "agent": "claude",
        "state_transitions": ["queued", "running", "done"],
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
        lambda r: r["readiness"].update(killswitch_engaged=True),
        lambda r: r.update(hermes_pids_after=[9999]),
        lambda r: r.update(queue_nonterminal_count=1),
        lambda r: r.update(rollback_tested=False),
        lambda r: r.update(claude_job_id=999),
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
    def __init__(self, *, ready: bool = True, killswitch: bool = False,
                 acquire: bool = True) -> None:
        self.ready = ready
        self.killswitch = killswitch
        self.acquire = acquire
        self.calls: list[tuple] = []

    def gateway_readiness(
        self, token_fingerprint: str, machine: str, max_age_seconds: int,
    ) -> dict:
        self.calls.append(("ready", token_fingerprint, machine, max_age_seconds))
        return {
            "minimal_rpc": True,
            "worker_machine": machine,
            "worker_ready": self.ready,
            "worker_heartbeat_age_seconds": 10 if self.ready else 999,
            "killswitch_engaged": self.killswitch,
        }

    def acquire_gateway_lease(
        self, token_fingerprint: str, holder_identity: str, pid: int,
        machine: str, ttl_seconds: int,
    ) -> dict:
        self.calls.append((
            "acquire", token_fingerprint, holder_identity, pid, machine, ttl_seconds,
        ))
        return {
            "acquired": self.acquire,
            "lease_id": (
                "11111111-1111-4111-8111-111111111111" if self.acquire else None
            ),
            "generation": 7 if self.acquire else None,
        }

    def renew_gateway_lease(
        self, lease_id: str, token_fingerprint: str, holder_identity: str,
        pid: int, generation: int, ttl_seconds: int,
    ) -> dict:
        self.calls.append((
            "renew", lease_id, token_fingerprint, holder_identity, pid,
            generation, ttl_seconds,
        ))
        return {"renewed": True, "lease_id": lease_id, "generation": generation}

    def release_gateway_lease(
        self, lease_id: str, token_fingerprint: str, holder_identity: str,
        pid: int, generation: int,
    ) -> dict:
        self.calls.append((
            "release", lease_id, token_fingerprint, holder_identity, pid, generation,
        ))
        return {"released": True}


def test_gateway_guard_checks_readiness_acquires_and_releases() -> None:
    queue = _RuntimeQueue()
    guard = GatewayLeaseGuard(
        queue,
        token_fingerprint=TOKEN_FINGERPRINT,
        bot_id=BOT,
        hermes_bot_id=HERMES_BOT,
        machine="winpc",
        pid=1234,
    )
    with guard:
        assert guard.lease_id and guard.generation == 7
    assert [call[0] for call in queue.calls] == ["ready", "acquire", "release"]
    assert queue.calls[0][1] == TOKEN_FINGERPRINT
    assert TOKEN not in repr(queue.calls)


def test_gateway_guard_never_acquires_when_worker_is_stale() -> None:
    queue = _RuntimeQueue(ready=False)
    guard = GatewayLeaseGuard(
        queue, token_fingerprint=TOKEN_FINGERPRINT, bot_id=BOT,
        hermes_bot_id=HERMES_BOT, machine="winpc", pid=1234,
    )
    with pytest.raises(RuntimeError, match="heartbeat"):
        guard.start()
    assert [call[0] for call in queue.calls] == ["ready"]


def test_gateway_guard_blocks_killswitch_and_same_hermes_identity() -> None:
    queue = _RuntimeQueue(killswitch=True)
    guard = GatewayLeaseGuard(
        queue, token_fingerprint=TOKEN_FINGERPRINT, bot_id=BOT,
        hermes_bot_id=HERMES_BOT, machine="winpc", pid=1234,
    )
    with pytest.raises(RuntimeError, match="killswitch"):
        guard.start()
    assert [call[0] for call in queue.calls] == ["ready"]

    with pytest.raises(ValueError, match="Hermes"):
        GatewayLeaseGuard(
            _RuntimeQueue(), token_fingerprint=TOKEN_FINGERPRINT, bot_id=BOT,
            hermes_bot_id=BOT, machine="winpc", pid=1234,
        )


def test_gateway_guard_blocks_second_holder_before_connect() -> None:
    queue = _RuntimeQueue(acquire=False)
    guard = GatewayLeaseGuard(
        queue, token_fingerprint=TOKEN_FINGERPRINT, bot_id=BOT,
        hermes_bot_id=HERMES_BOT, machine="winpc", pid=1234,
    )
    with pytest.raises(RuntimeError, match="already held"):
        guard.start()
    assert [call[0] for call in queue.calls] == ["ready", "acquire"]


def test_gateway_guard_disconnects_after_consecutive_renew_failures() -> None:
    class RenewFailureQueue(_RuntimeQueue):
        def renew_gateway_lease(self, *args) -> dict:
            self.calls.append(("renew", *args))
            return {"renewed": False}

    queue = RenewFailureQueue()
    lost = threading.Event()
    guard = GatewayLeaseGuard(
        queue, token_fingerprint=TOKEN_FINGERPRINT, bot_id=BOT,
        hermes_bot_id=HERMES_BOT, machine="winpc", pid=1234,
        renew_interval_seconds=0.01, max_consecutive_renew_failures=2,
        on_lease_lost=lambda _exc: lost.set(),
    )
    guard.start()
    assert lost.wait(0.5)
    guard.stop()
    assert [call[0] for call in queue.calls].count("renew") == 2
    assert [call[0] for call in queue.calls][-1] == "release"


def test_main_never_connects_when_killswitch_is_engaged(monkeypatch) -> None:
    queue = _RuntimeQueue(killswitch=True)

    class Client:
        run_calls: list[str] = []

        def run(self, token: str) -> None:
            self.run_calls.append(token)

        def stop_after_lease_loss(self, exc: Exception) -> None:
            raise AssertionError(f"unexpected lease loss: {exc}")

    client = Client()
    monkeypatch.setattr(gateway, "_minimal_privilege_queue_factory", lambda: lambda: queue)
    monkeypatch.setattr(gateway, "_build_client", lambda **_kwargs: client)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_CLIENT_ID", BOT)
    monkeypatch.setenv("HERMES_DISCORD_BOT_ID", HERMES_BOT)
    monkeypatch.setenv("DISCORD_GATEWAY_WORKER_MACHINE", "winpc")
    with pytest.raises(RuntimeError, match="killswitch"):
        gateway.main()
    assert client.run_calls == []


def test_gateway_module_has_no_direct_engine_execution() -> None:
    tree = ast.parse((ROOT / "scripts/discord_direct_gateway.py").read_text())
    forbidden = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            rendered = ast.unparse(node.func)
            if rendered in {"subprocess.run", "subprocess.Popen", "os.system", "os.execv"}:
                forbidden.append(rendered)
    assert forbidden == []


def test_receipt_rejects_raw_secret_values() -> None:
    receipt = _valid_receipt()
    receipt["diagnostic"] = TOKEN
    with pytest.raises(Hr1ReceiptError, match="secret"):
        validate_hr1_receipt(receipt, forbidden_values=(TOKEN, "service-role-test-value"))


def test_minimal_privilege_sql_defines_hr1_runtime_rpcs() -> None:
    sql = (ROOT / "supabase/migrations/20260722_discord_gateway_hr1_runtime.sql").read_text()
    for marker in (
        "discord_gateway_readiness",
        "discord_gateway_acquire_lease",
        "discord_gateway_renew_lease",
        "discord_gateway_release_lease",
        "discord_gateway_killswitches",
        "token_fingerprint",
        "holder_identity",
        "holder_pid",
        "generation",
        "released_at",
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
