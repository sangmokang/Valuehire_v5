"""App 14 — Discord/Claude/Codex share one queue-only command gateway."""

from __future__ import annotations

import ast
from datetime import datetime, timezone

import pytest

from tools.multi_position_sourcing.common_command_gateway import (
    CommandGatewayError,
    enqueue_command,
    normalize_request,
)
from tools.multi_position_sourcing.fleet_worker import build_job_prompt


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
CLICKUP = "https://app.clickup.com/t/abc123"


class MemoryQueue:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.enqueue_calls = 0

    def job_by_idempotency_key(self, key: str):
        return self.rows.get(key)

    def enqueue(self, payload: dict):
        self.enqueue_calls += 1
        key = payload["params"]["idempotency_key"]
        if key in self.rows:
            return self.rows[key]
        row = {
            **payload,
            "id": len(self.rows) + 1,
            "created_at": NOW.isoformat(),
            "updated_at": NOW.isoformat(),
        }
        self.rows[key] = row
        return row


@pytest.mark.parametrize("alias", ("$login", "/login", "login"))
@pytest.mark.parametrize("source", ("discord", "claude", "codex"))
def test_login_aliases_share_one_canonical_envelope(alias, source):
    envelope = normalize_request(
        source=source,
        raw_command=alias,
        machine="macmini",
        channels=["saramin", "jobkorea", "linkedin_rps"],
        agent="codex",
        message_id="123456789012345678" if source == "discord" else "",
        uuid_factory=lambda: "local-request-1",
        clock=lambda: NOW,
    )
    assert tuple(envelope) == (
        "schema_version", "request_id", "source", "command", "machine",
        "channels", "agent", "idempotency_key", "created_at",
    )
    assert envelope["command"] == "login"
    assert envelope["source"] == source
    assert envelope["idempotency_key"] == (
        "discord:123456789012345678" if source == "discord"
        else "local:local-request-1"
    )


@pytest.mark.parametrize("command", ("aisearch", "/humansearch", "$url"))
def test_search_commands_normalize_without_agent_specific_execution_path(command):
    envelope = normalize_request(
        source="claude",
        raw_command=command,
        machine="macmini",
        channels=["linkedin_rps"] if "url" in command else ["saramin"],
        agent="claude",
        uuid_factory=lambda: "u1",
        clock=lambda: NOW,
    )
    assert envelope["command"] in {"aisearch", "humansearch", "url"}
    assert envelope["machine"] == "macmini"


def test_duplicate_delivery_enqueues_and_executes_one_job():
    queue = MemoryQueue()
    kwargs = dict(
        source="discord",
        raw_command="/login",
        machine="macmini",
        channels=["saramin"],
        agent="codex",
        message_id="123456789012345678",
        requested_by="814353841088757800",
        role="owner",
        clock=lambda: NOW,
    )
    first = enqueue_command(queue=queue, **kwargs)
    second = enqueue_command(queue=queue, **kwargs)
    assert first["job_id"] == second["job_id"] == 1
    assert first["existing_job"] is False
    assert second["existing_job"] is True
    assert queue.enqueue_calls == 1
    assert len(queue.rows) == 1  # one queued job means one worker execution


def test_same_key_with_different_payload_is_conflict():
    queue = MemoryQueue()
    base = dict(
        source="discord", raw_command="/login", machine="macmini",
        agent="codex", message_id="123456789012345678",
        requested_by="814353841088757800", role="owner", clock=lambda: NOW,
    )
    enqueue_command(queue=queue, channels=["saramin"], **base)
    with pytest.raises(CommandGatewayError, match="IDEMPOTENCY_CONFLICT") as error:
        enqueue_command(queue=queue, channels=["jobkorea"], **base)
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    assert queue.enqueue_calls == 1


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"raw_command": "/delete"}, "INVALID_COMMAND"),
        ({"channels": ["public_web"]}, "INVALID_CHANNEL"),
        ({"machine": "Mac Mini"}, "INVALID_MACHINE"),
        ({"machine": ""}, "NO_READY_MACHINE"),
    ],
)
def test_invalid_command_channel_and_machine_fail_closed(overrides, code):
    kwargs = dict(
        source="codex", raw_command="/login", machine="macmini",
        channels=["saramin"], agent="codex", uuid_factory=lambda: "u1",
        clock=lambda: NOW,
    )
    kwargs.update(overrides)
    with pytest.raises(CommandGatewayError) as error:
        normalize_request(**kwargs)
    assert error.value.code == code


def test_handler_has_no_browser_or_cdp_import_and_worker_starts_discover():
    import tools.multi_position_sourcing.common_command_gateway as gateway

    tree = ast.parse(open(gateway.__file__, encoding="utf-8").read())
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any("browser" in name or "cdp" in name for name in imports)

    queue = MemoryQueue()
    status = enqueue_command(
        queue=queue, source="codex", raw_command="aisearch",
        machine="macmini", channels=["saramin"], agent="codex",
        position_url=CLICKUP, requested_by="local-owner", role="owner",
        uuid_factory=lambda: "u1", clock=lambda: NOW,
    )
    job = queue.rows["local:u1"]
    assert status["selected_machine"] == "macmini"
    assert job["params"]["start_state"] == "DISCOVER"
    assert "DISCOVER" in build_job_prompt(job)


def test_queue_failure_is_redacted():
    class DeadQueue:
        def job_by_idempotency_key(self, _key):
            return None

        def enqueue(self, _payload):
            raise RuntimeError("postgres password=SECRET")

    with pytest.raises(CommandGatewayError) as error:
        enqueue_command(
            queue=DeadQueue(), source="codex", raw_command="login",
            machine="macmini", channels=["saramin"], agent="codex",
            uuid_factory=lambda: "u1", clock=lambda: NOW,
        )
    assert error.value.code == "QUEUE_WRITE_FAILED"
    assert "SECRET" not in str(error.value)
