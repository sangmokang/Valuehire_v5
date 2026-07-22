"""HR-1 direct Discord gateway runtime gate and secret-free receipt verifier."""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Callable


_SNOWFLAKE = re.compile(r"^[0-9]{15,22}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_TERMINAL_TRANSITIONS = ["queued", "running", "done"]
_FORBIDDEN_KEY_PARTS = ("token", "secret", "password", "cookie", "service_role")


class Hr1ReceiptError(ValueError):
    """The receipt cannot prove the HR-1 live acceptance claim."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Hr1ReceiptError(message)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _secret_free(value: Any, path: str = "receipt") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            _require(
                not any(part in normalized for part in _FORBIDDEN_KEY_PARTS),
                f"secret-like field is forbidden: {path}.{key}",
            )
            _secret_free(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _secret_free(child, f"{path}[{index}]")


def _validate_job(value: Any, *, expected_agent: str | None = None) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), "job evidence must be an object")
    if expected_agent is not None:
        _require(value.get("agent") == expected_agent, f"missing {expected_agent} live job")
    else:
        _require(value.get("agent") in {"claude", "codex"}, "invalid natural job agent")
    _require(_SNOWFLAKE.fullmatch(str(value.get("event_id") or "")) is not None,
             "job event_id is invalid")
    _require(_positive_int(value.get("job_id")), "job_id must be positive")
    _require(_SNOWFLAKE.fullmatch(str(value.get("requester_id") or "")) is not None,
             "requester_id is invalid")
    _require(value.get("transitions") == _TERMINAL_TRANSITIONS,
             "job must transition queued -> running -> done")
    _require(_SNOWFLAKE.fullmatch(str(value.get("response_id") or "")) is not None,
             "Discord response_id is invalid")
    _require(value.get("response_count") == 1, "requester response count must be exactly one")
    return value


def validate_hr1_receipt(
    payload: Any,
    *,
    expected_verifier_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate actual HR-1 evidence; missing or synthetic-looking fields fail closed."""

    _require(isinstance(payload, dict), "receipt must be an object")
    _secret_free(payload)
    _require(payload.get("schema_version") == "discord-hr1/v1", "schema_version mismatch")
    _require(payload.get("phase") == "HR-1", "phase must be HR-1")
    for field in ("git_sha_v4", "git_sha_v5"):
        _require(_GIT_SHA.fullmatch(str(payload.get(field) or "")) is not None,
                 f"{field} must be a full git sha")
    bot_id = str(payload.get("discord_bot_id") or "")
    hermes_bot_id = str(payload.get("hermes_bot_id") or "")
    _require(_SNOWFLAKE.fullmatch(bot_id) is not None, "discord_bot_id is invalid")
    _require(_SNOWFLAKE.fullmatch(hermes_bot_id) is not None, "hermes_bot_id is invalid")
    _require(payload.get("bot_identity_isolated") is True and bot_id != hermes_bot_id,
             "HR-1 requires an isolated bot identity")
    _require(_SHA256.fullmatch(str(payload.get("command_fingerprint") or "")) is not None,
             "command_fingerprint is invalid")
    _require(_positive_int(payload.get("direct_gateway_pid")), "gateway pid is invalid")
    try:
        uuid.UUID(str(payload.get("direct_gateway_lease_id") or ""))
    except ValueError as exc:
        raise Hr1ReceiptError("gateway lease_id is invalid") from exc
    _require(payload.get("gateway_stopped_after_test") is True,
             "direct gateway must stop after HR-1")

    readiness = payload.get("readiness")
    _require(isinstance(readiness, Mapping), "readiness evidence is missing")
    _require(readiness.get("minimal_rpc") is True, "minimal privilege RPC was not proven")
    _require(isinstance(readiness.get("worker_machine"), str)
             and bool(str(readiness.get("worker_machine")).strip()),
             "worker machine is missing")
    age = readiness.get("worker_heartbeat_age_seconds")
    _require(isinstance(age, int) and not isinstance(age, bool) and 0 <= age <= 300,
             "worker heartbeat is stale")

    duplicate = payload.get("duplicate_event")
    _require(isinstance(duplicate, Mapping), "duplicate event evidence is missing")
    _require(_SNOWFLAKE.fullmatch(str(duplicate.get("event_id") or "")) is not None,
             "duplicate event_id is invalid")
    _require(_positive_int(duplicate.get("first_job_id")), "duplicate first job is invalid")
    _require(duplicate.get("first_job_id") == duplicate.get("replay_job_id")
             and duplicate.get("row_count") == 1,
             "same Discord event must resolve to exactly one job")

    jobs = payload.get("jobs")
    _require(isinstance(jobs, list) and len(jobs) == 2,
             "exactly one Claude and one Codex job are required")
    by_agent = {
        str(job.get("agent") or ""): job
        for job in jobs
        if isinstance(job, Mapping)
    }
    claude = _validate_job(by_agent.get("claude"), expected_agent="claude")
    codex = _validate_job(by_agent.get("codex"), expected_agent="codex")
    natural = _validate_job(payload.get("natural_language"))
    _require(_SHA256.fullmatch(str(natural.get("text_fingerprint") or "")) is not None,
             "natural language text fingerprint is invalid")

    response_ids = [
        str(claude["response_id"]),
        str(codex["response_id"]),
        str(natural["response_id"]),
    ]
    _require(len(set(response_ids)) == 3, "live jobs must have distinct Discord responses")
    _require(payload.get("duplicate_response_count") == 0, "duplicate response detected")
    try:
        verified = datetime.fromisoformat(
            str(payload.get("verified_at") or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise Hr1ReceiptError("verified_at is invalid") from exc
    _require(verified.tzinfo is not None, "verified_at must include a timezone")
    verifier_hash = str(payload.get("verifier_sha256") or "")
    _require(_SHA256.fullmatch(verifier_hash) is not None, "verifier_sha256 is invalid")
    if expected_verifier_sha256 is not None:
        _require(verifier_hash == expected_verifier_sha256, "verifier code hash mismatch")
    return payload


class GatewayLeaseGuard:
    """Acquire one shared gateway lease only after RPC and worker readiness pass."""

    def __init__(
        self,
        queue: Any,
        *,
        bot_id: str,
        machine: str,
        pid: int,
        ttl_seconds: int = 90,
        max_heartbeat_age_seconds: int = 300,
        renew_interval_seconds: float = 0,
        on_lease_lost: Callable[[Exception], None] | None = None,
    ) -> None:
        if _SNOWFLAKE.fullmatch(str(bot_id)) is None:
            raise ValueError("bot_id must be a Discord snowflake")
        if not machine.strip() or not _positive_int(pid):
            raise ValueError("machine and pid are required")
        if not 30 <= ttl_seconds <= 300:
            raise ValueError("lease ttl must be between 30 and 300 seconds")
        self.queue = queue
        self.bot_id = str(bot_id)
        self.machine = machine.strip()
        self.pid = pid
        self.ttl_seconds = ttl_seconds
        self.max_heartbeat_age_seconds = max_heartbeat_age_seconds
        self.renew_interval_seconds = renew_interval_seconds
        self.on_lease_lost = on_lease_lost
        self.instance_id = str(uuid.uuid4())
        self.lease_id = ""
        self.readiness: dict[str, Any] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "GatewayLeaseGuard":
        if self.lease_id:
            raise RuntimeError("gateway lease is already held")
        readiness = self.queue.gateway_readiness(
            self.machine, self.max_heartbeat_age_seconds)
        if not isinstance(readiness, Mapping) or readiness.get("minimal_rpc") is not True:
            raise RuntimeError("minimal privilege RPC readiness failed")
        if readiness.get("worker_ready") is not True:
            raise RuntimeError("worker heartbeat is missing or stale")
        acquired = self.queue.acquire_gateway_lease(
            self.bot_id, self.instance_id, self.ttl_seconds)
        lease_id = str((acquired or {}).get("lease_id") or "")
        try:
            uuid.UUID(lease_id)
        except ValueError as exc:
            raise RuntimeError("gateway lease acquisition returned no valid lease") from exc
        self.readiness = dict(readiness)
        self.lease_id = lease_id
        if self.renew_interval_seconds > 0:
            self._thread = threading.Thread(
                target=self._renew_loop,
                name=f"discord-gateway-lease-{self.pid}",
                daemon=True,
            )
            self._thread.start()
        return self

    def _renew_loop(self) -> None:
        while not self._stop.wait(self.renew_interval_seconds):
            try:
                renewed = self.queue.renew_gateway_lease(
                    self.lease_id, self.instance_id, self.ttl_seconds)
                if str((renewed or {}).get("lease_id") or "") != self.lease_id:
                    raise RuntimeError("gateway lease renewal lost ownership")
            except Exception as exc:  # noqa: BLE001 - lease loss must stop the gateway.
                self._stop.set()
                if self.on_lease_lost is not None:
                    self.on_lease_lost(exc)
                return

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.renew_interval_seconds + 1.0))
            self._thread = None
        lease_id, self.lease_id = self.lease_id, ""
        if lease_id:
            released = self.queue.release_gateway_lease(lease_id, self.instance_id)
            if not isinstance(released, Mapping) or released.get("released") is not True:
                raise RuntimeError("gateway lease release was not acknowledged")

    def __enter__(self) -> "GatewayLeaseGuard":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()
