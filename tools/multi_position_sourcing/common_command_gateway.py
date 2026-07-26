"""One queue-only command entrypoint for Discord, Claude, and Codex.

The gateway normalizes source-specific spelling, adds immutable request metadata,
and writes an existing ``jobs`` row.  Browser discovery and execution remain the
selected worker's responsibility and always begin at ``DISCOVER``.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from .job_queue import FLEET_AGENTS, is_valid_machine_id, new_job_payload
from .login_barrier import CHANNELS, normalize_command, required_channels

SCHEMA_VERSION = 1
SOURCES = ("discord", "claude", "codex")
_DISCORD_ID = re.compile(r"^[0-9]{15,22}$")
_SECRET_KEYS = ("password", "passwd", "cookie", "credential", "secret", "token", "li_at")


class CommandGatewayError(ValueError):
    """Public, secret-free fail-closed gateway error."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            any(marker in str(key).lower() for marker in _SECRET_KEYS)
            or _contains_secret_key(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_secret_key(child) for child in value)
    return False


def _now(clock: Callable[[], Any]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CommandGatewayError("INVALID_REQUEST")
    return value.astimezone(timezone.utc)


def _channels(command: str, channels: Sequence[str] | None) -> list[str]:
    if channels:
        normalized = [
            "linkedin_rps" if channel == "linkedin" else channel
            for channel in channels
        ]
        if any(channel not in CHANNELS for channel in normalized):
            raise CommandGatewayError("INVALID_CHANNEL")
    if command == "login" and channels:
        return list(dict.fromkeys(normalized))
    try:
        return list(required_channels(command, channels=channels))
    except (TypeError, ValueError):
        raise CommandGatewayError("INVALID_CHANNEL") from None


def normalize_request(
    *,
    source: str,
    raw_command: Any,
    machine: str,
    channels: Sequence[str] | None = None,
    agent: str | None = None,
    message_id: str = "",
    ready_machines: Sequence[str] | None = None,
    uuid_factory: Callable[[], Any] = uuid.uuid4,
    clock: Callable[[], Any] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """Return the canonical nine-field request envelope, without side effects."""
    if source not in SOURCES:
        raise CommandGatewayError("INVALID_SOURCE")
    command = normalize_command(raw_command)
    if command is None:
        raise CommandGatewayError("INVALID_COMMAND")
    if not machine:
        raise CommandGatewayError("NO_READY_MACHINE")
    if not is_valid_machine_id(machine):
        raise CommandGatewayError("INVALID_MACHINE")
    if ready_machines is not None and machine not in ready_machines:
        raise CommandGatewayError("NO_READY_MACHINE")
    selected_agent = agent or (source if source != "discord" else "codex")
    if selected_agent not in FLEET_AGENTS:
        raise CommandGatewayError("INVALID_AGENT")
    if source == "discord":
        if not isinstance(message_id, str) or not _DISCORD_ID.fullmatch(message_id):
            raise CommandGatewayError("INVALID_REQUEST")
        request_id = message_id
        idempotency_key = f"discord:{message_id}"
    else:
        request_id = str(uuid_factory())
        if not request_id or any(char.isspace() for char in request_id):
            raise CommandGatewayError("INVALID_REQUEST")
        idempotency_key = f"local:{request_id}"
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "source": source,
        "command": command,
        "machine": machine,
        "channels": _channels(command, channels),
        "agent": selected_agent,
        "idempotency_key": idempotency_key,
        "created_at": _now(clock).isoformat(),
    }


def _payload_digest(
    envelope: Mapping[str, Any], position_url: str, requested_by: str, role: str,
    job_params: Mapping[str, Any],
) -> str:
    # Delivery time is observational, not semantic: a retry of the same event may
    # arrive later and must still compare equal.
    semantic = {key: value for key, value in envelope.items() if key != "created_at"}
    semantic.update(
        position_url=position_url, requested_by=requested_by, role=role,
        job_params=job_params)
    material = json.dumps(
        semantic, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _status(row: Mapping[str, Any], envelope: Mapping[str, Any], existing: bool) -> dict[str, Any]:
    job_id = row.get("id")
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise CommandGatewayError("QUEUE_WRITE_FAILED")
    created = str(row.get("created_at") or envelope["created_at"])
    updated = str(row.get("updated_at") or created)
    return {
        "job_id": job_id,
        "state": str(row.get("status") or "queued"),
        "selected_machine": envelope["machine"],
        "existing_job": existing,
        "created_at": created,
        "updated_at": updated,
    }


def enqueue_command(
    *,
    queue: Any,
    source: str,
    raw_command: Any,
    machine: str,
    channels: Sequence[str] | None = None,
    agent: str | None = None,
    message_id: str = "",
    ready_machines: Sequence[str] | None = None,
    position_url: str = "",
    requested_by: str = "local",
    role: str = "owner",
    job_params: Mapping[str, Any] | None = None,
    uuid_factory: Callable[[], Any] = uuid.uuid4,
    clock: Callable[[], Any] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """Normalize and enqueue once; never discovers or operates a browser."""
    envelope = normalize_request(
        source=source, raw_command=raw_command, machine=machine,
        channels=channels, agent=agent, message_id=message_id,
        ready_machines=ready_machines, uuid_factory=uuid_factory, clock=clock,
    )
    extras = dict(job_params or {})
    for reserved in (
        "agent", "channels", "idempotency_key", "request_envelope",
        "request_payload_sha256", "start_state",
    ):
        extras.pop(reserved, None)
    if _contains_secret_key(extras):
        raise CommandGatewayError("INVALID_REQUEST")
    try:
        digest = _payload_digest(envelope, position_url, requested_by, role, extras)
    except (TypeError, ValueError, UnicodeError):
        raise CommandGatewayError("INVALID_REQUEST") from None
    key = envelope["idempotency_key"]
    try:
        existing = queue.job_by_idempotency_key(key)
    except Exception:
        raise CommandGatewayError("QUEUE_WRITE_FAILED") from None
    if existing is not None:
        stored = (existing.get("params") or {}).get("request_payload_sha256")
        if stored != digest:
            raise CommandGatewayError("IDEMPOTENCY_CONFLICT")
        return _status(existing, envelope, True)
    params = {
        **extras,
        "agent": envelope["agent"],
        "channels": envelope["channels"],
        "idempotency_key": key,
        "request_envelope": envelope,
        "request_payload_sha256": digest,
        "start_state": "DISCOVER",
    }
    payload = new_job_payload(
        machine=envelope["machine"], skill=envelope["command"],
        position_url=position_url, requested_by=requested_by, role=role,
        params=params,
    )
    if payload is None:
        raise CommandGatewayError("INVALID_REQUEST")
    try:
        row = queue.enqueue(payload)
    except Exception:
        raise CommandGatewayError("QUEUE_WRITE_FAILED") from None
    if not isinstance(row, Mapping):
        raise CommandGatewayError("QUEUE_WRITE_FAILED")
    stored = (row.get("params") or {}).get("request_payload_sha256")
    if stored != digest:
        raise CommandGatewayError("IDEMPOTENCY_CONFLICT")
    return _status(
        row, envelope, bool(getattr(queue, "last_enqueue_existing", False)))
