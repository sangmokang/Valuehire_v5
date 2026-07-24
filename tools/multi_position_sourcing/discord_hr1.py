"""HR-1 direct Discord gateway runtime gate and secret-free receipt verifier."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


_SNOWFLAKE = re.compile(r"^[0-9]{15,22}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_TERMINAL_TRANSITIONS = ["queued", "running", "done"]
_FORBIDDEN_KEY_PARTS = ("token", "secret", "password", "cookie", "service_role")


class Hr1ReceiptError(ValueError):
    """The receipt cannot prove the HR-1 live acceptance claim."""


def gateway_token_fingerprint(token: str) -> str:
    """Derive the lease identity without letting the raw token leave the caller."""
    if not isinstance(token, str) or not token:
        raise ValueError("gateway token is required")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def discord_bot_id_from_token(token: str) -> str:
    """Recover the public bot snowflake locally without logging the token."""
    if not isinstance(token, str) or not token:
        raise ValueError("gateway token is required")
    encoded = token.split(".", 1)[0]
    try:
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        bot_id = base64.urlsafe_b64decode(encoded + padding).decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Discord token identity is invalid") from exc
    if _SNOWFLAKE.fullmatch(bot_id) is None:
        raise ValueError("Discord token identity is invalid")
    return bot_id


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Hr1ReceiptError(message)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _secret_free(
    value: Any,
    path: str = "receipt",
    *,
    forbidden_values: tuple[str, ...] = (),
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            _require(
                not any(part in normalized for part in _FORBIDDEN_KEY_PARTS),
                f"secret-like field is forbidden: {path}.{key}",
            )
            _secret_free(child, f"{path}.{key}", forbidden_values=forbidden_values)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _secret_free(child, f"{path}[{index}]", forbidden_values=forbidden_values)
    elif isinstance(value, str):
        _require(
            not any(secret and secret in value for secret in forbidden_values),
            f"secret value is forbidden: {path}",
        )


class Hr1EvidenceRecorder:
    """Append-only, secret-free JSONL evidence for one isolated HR-1 run.

    A run must use a fresh path.  Refusing an existing file prevents evidence from
    two attempts being combined into a receipt that neither attempt earned.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        os.close(descriptor)
        self._lock = threading.Lock()

    def record(self, kind: str, **fields: Any) -> dict[str, Any]:
        if not isinstance(kind, str) or not kind.strip():
            raise Hr1ReceiptError("evidence kind is required")
        payload = {
            "kind": kind.strip(),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        _secret_free(payload)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return payload


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
    forbidden_values: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Validate actual HR-1 evidence; missing or synthetic-looking fields fail closed."""

    _require(isinstance(payload, dict), "receipt must be an object")
    _secret_free(
        payload,
        forbidden_values=tuple(str(value) for value in forbidden_values if str(value)),
    )
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
    _require(_positive_int(payload.get("direct_gateway_generation")),
             "gateway generation is invalid")
    _require(payload.get("gateway_stopped_after_test") is True,
             "direct gateway must stop after HR-1")
    hermes_before = payload.get("hermes_pids_before")
    hermes_after = payload.get("hermes_pids_after")
    _require(payload.get("hermes_pid_count") == 1,
             "exactly one Hermes process must remain live")
    _require(payload.get("hermes_launchctl_count") == 1,
             "exactly one Hermes launchd service must remain live")
    _require(
        isinstance(hermes_before, list)
        and hermes_before == hermes_after
        and len(hermes_before) == 1
        and _positive_int(hermes_before[0]),
        "Hermes process identity changed during HR-1",
    )

    readiness = payload.get("readiness")
    _require(isinstance(readiness, Mapping), "readiness evidence is missing")
    _require(readiness.get("minimal_rpc") is True, "minimal privilege RPC was not proven")
    _require(readiness.get("worker_machine") == "winpc",
             "HR-1 requires the winpc worker")
    _require(readiness.get("worker_ready") is True, "winpc worker was not ready")
    _require(_positive_int(readiness.get("worker_pid")),
             "winpc worker PID was not proven")
    _require(readiness.get("claude_ready") is True, "winpc Claude CLI was not ready")
    _require(readiness.get("codex_ready") is True, "winpc Codex CLI was not ready")
    _require(readiness.get("killswitch_engaged") is False,
             "gateway killswitch is engaged")
    age = readiness.get("worker_heartbeat_age_seconds")
    _require(isinstance(age, int) and not isinstance(age, bool) and 0 <= age <= 300,
             "worker heartbeat is stale")

    readiness_after = payload.get("readiness_after")
    _require(isinstance(readiness_after, Mapping),
             "final readiness evidence is missing")
    _require(readiness_after.get("minimal_rpc") is True,
             "final minimal privilege RPC was not proven")
    _require(readiness_after.get("worker_machine") == readiness.get("worker_machine"),
             "worker machine changed during HR-1")
    _require(readiness_after.get("worker_pid") == readiness.get("worker_pid"),
             "worker process changed during HR-1")
    _require(readiness_after.get("worker_ready") is True,
             "winpc worker was not ready after HR-1")
    _require(readiness_after.get("claude_ready") is True,
             "winpc Claude CLI was not ready after HR-1")
    _require(readiness_after.get("codex_ready") is True,
             "winpc Codex CLI was not ready after HR-1")
    _require(readiness_after.get("killswitch_engaged") is False,
             "gateway killswitch was engaged after HR-1")
    final_age = readiness_after.get("worker_heartbeat_age_seconds")
    _require(
        isinstance(final_age, int) and not isinstance(final_age, bool)
        and 0 <= final_age <= 300,
        "worker heartbeat was stale after HR-1",
    )

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
    _require(
        payload.get("claude_job_id") == claude.get("job_id")
        and payload.get("claude_response_id") == claude.get("response_id"),
        "top-level Claude evidence is inconsistent",
    )
    _require(
        payload.get("codex_job_id") == codex.get("job_id")
        and payload.get("codex_response_id") == codex.get("response_id"),
        "top-level Codex evidence is inconsistent",
    )
    _require(_SHA256.fullmatch(str(natural.get("text_fingerprint") or "")) is not None,
             "natural language text fingerprint is invalid")

    response_ids = [
        str(claude["response_id"]),
        str(codex["response_id"]),
        str(natural["response_id"]),
    ]
    _require(len(set(response_ids)) == 3, "live jobs must have distinct Discord responses")
    _require(payload.get("claude_job_id") == claude.get("job_id"),
             "claude_job_id does not match live evidence")
    _require(payload.get("claude_response_id") == claude.get("response_id"),
             "claude_response_id does not match live evidence")
    _require(payload.get("codex_job_id") == codex.get("job_id"),
             "codex_job_id does not match live evidence")
    _require(payload.get("codex_response_id") == codex.get("response_id"),
             "codex_response_id does not match live evidence")
    _require(payload.get("duplicate_response_count") == 0, "duplicate response detected")
    _require(payload.get("queue_nonterminal_count") == 0,
             "HR-1 queue still has nonterminal jobs")
    _require(payload.get("rollback_tested") is True,
             "direct gateway stop/rollback was not tested")
    _require(payload.get("event_id") == duplicate.get("event_id"),
             "top-level duplicate event evidence is inconsistent")
    _require(payload.get("job_id") == duplicate.get("first_job_id"),
             "top-level duplicate job evidence is inconsistent")
    _require(payload.get("agent") in {"claude", "codex"},
             "top-level agent evidence is invalid")
    _require(payload.get("state_transitions") == _TERMINAL_TRANSITIONS,
             "top-level job transitions are incomplete")
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
        token_fingerprint: str,
        bot_id: str,
        hermes_bot_id: str,
        machine: str,
        pid: int,
        ttl_seconds: int = 90,
        max_heartbeat_age_seconds: int = 300,
        renew_interval_seconds: float = 0,
        max_consecutive_renew_failures: int = 2,
        on_lease_lost: Callable[[Exception], None] | None = None,
    ) -> None:
        if _SHA256.fullmatch(str(token_fingerprint)) is None:
            raise ValueError("token_fingerprint must be a SHA-256 digest")
        if _SNOWFLAKE.fullmatch(str(bot_id)) is None:
            raise ValueError("bot_id must be a Discord snowflake")
        if _SNOWFLAKE.fullmatch(str(hermes_bot_id)) is None:
            raise ValueError("hermes_bot_id must be a Discord snowflake")
        if str(bot_id) == str(hermes_bot_id):
            raise ValueError("direct bot identity must differ from Hermes")
        if not machine.strip() or not _positive_int(pid):
            raise ValueError("machine and pid are required")
        if not 30 <= ttl_seconds <= 300:
            raise ValueError("lease ttl must be between 30 and 300 seconds")
        if not _positive_int(max_consecutive_renew_failures):
            raise ValueError("max_consecutive_renew_failures must be positive")
        self.queue = queue
        self.token_fingerprint = str(token_fingerprint)
        self.bot_id = str(bot_id)
        self.hermes_bot_id = str(hermes_bot_id)
        self.machine = machine.strip()
        self.pid = pid
        self.ttl_seconds = ttl_seconds
        self.max_heartbeat_age_seconds = max_heartbeat_age_seconds
        self.renew_interval_seconds = renew_interval_seconds
        self.max_consecutive_renew_failures = max_consecutive_renew_failures
        self.on_lease_lost = on_lease_lost
        self.holder_identity = f"discord-direct:{self.machine}:{self.bot_id}:{uuid.uuid4()}"
        self.lease_id = ""
        self.generation = 0
        self.readiness: dict[str, Any] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "GatewayLeaseGuard":
        if self.lease_id:
            raise RuntimeError("gateway lease is already held")
        readiness = self.queue.gateway_readiness(
            self.token_fingerprint, self.machine, self.max_heartbeat_age_seconds)
        if not isinstance(readiness, Mapping) or readiness.get("minimal_rpc") is not True:
            raise RuntimeError("minimal privilege RPC readiness failed")
        if readiness.get("worker_ready") is not True:
            raise RuntimeError("worker heartbeat is missing or stale")
        if not _positive_int(readiness.get("worker_pid")):
            raise RuntimeError("worker PID is missing from readiness")
        if readiness.get("claude_ready") is not True:
            raise RuntimeError("worker claude CLI is not ready")
        if readiness.get("codex_ready") is not True:
            raise RuntimeError("worker codex CLI is not ready")
        if readiness.get("worker_machine") != self.machine:
            raise RuntimeError("worker readiness returned a different machine")
        if readiness.get("killswitch_engaged") is not False:
            raise RuntimeError("gateway killswitch is engaged")
        acquired = self.queue.acquire_gateway_lease(
            self.token_fingerprint,
            self.holder_identity,
            self.pid,
            self.machine,
            self.ttl_seconds,
        )
        if not isinstance(acquired, Mapping) or acquired.get("acquired") is not True:
            raise RuntimeError("gateway lease is already held")
        lease_id = str((acquired or {}).get("lease_id") or "")
        try:
            uuid.UUID(lease_id)
        except ValueError as exc:
            raise RuntimeError("gateway lease acquisition returned no valid lease") from exc
        generation = acquired.get("generation")
        if not _positive_int(generation):
            raise RuntimeError("gateway lease acquisition returned no generation")
        self.readiness = dict(readiness)
        self.lease_id = lease_id
        self.generation = int(generation)
        if self.renew_interval_seconds > 0:
            self._thread = threading.Thread(
                target=self._renew_loop,
                name=f"discord-gateway-lease-{self.pid}",
                daemon=True,
            )
            self._thread.start()
        return self

    def _renew_loop(self) -> None:
        failures = 0
        while not self._stop.wait(self.renew_interval_seconds):
            try:
                renewed = self.queue.renew_gateway_lease(
                    self.lease_id,
                    self.token_fingerprint,
                    self.holder_identity,
                    self.pid,
                    self.generation,
                    self.ttl_seconds,
                )
                if (
                    not isinstance(renewed, Mapping)
                    or renewed.get("renewed") is not True
                    or str(renewed.get("lease_id") or "") != self.lease_id
                    or renewed.get("generation") != self.generation
                ):
                    raise RuntimeError("gateway lease renewal lost ownership")
                failures = 0
            except Exception as exc:  # noqa: BLE001 - lease loss must stop the gateway.
                failures += 1
                if failures >= self.max_consecutive_renew_failures:
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
        generation, self.generation = self.generation, 0
        if lease_id:
            released = self.queue.release_gateway_lease(
                lease_id,
                self.token_fingerprint,
                self.holder_identity,
                self.pid,
                generation,
            )
            if not isinstance(released, Mapping) or released.get("released") is not True:
                raise RuntimeError("gateway lease release was not acknowledged")

    def __enter__(self) -> "GatewayLeaseGuard":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()
