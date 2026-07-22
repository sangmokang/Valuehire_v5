#!/usr/bin/env python3
"""Formal HR-1 isolated Discord live-acceptance runner.

The runner owns orchestration and evidence only.  The direct gateway remains the
canonical enqueue path and the winpc fleet worker remains the only executor.
Exactly three owner-authored Discord messages are required; the first accepted
event is delivered to the gateway handler twice and must yield one job/reply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.multi_position_sourcing.discord_hr1 import validate_hr1_receipt


DEFAULT_RECEIPT = ROOT / "artifacts/discord-cutover/hermes-retirement-receipt.json"
DEFAULT_OWNER_ID = "814353841088757800"
_TERMINAL = {"done", "failed", "cancelled"}
_SERVICE_ENV_KEYS = {
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SERVICE_KEY",
    "SERVICE_ROLE_KEY",
    "SUPABASE_ACCESS_TOKEN",
}


def _sha256(value: str | bytes) -> str:
    data = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def expected_hr1_messages(position_url: str) -> tuple[str, str, str]:
    url = str(position_url or "").strip()
    _require(url.startswith(("https://", "http://")), "position URL is required")
    return (
        f"/url url:{url} machine:winpc engine:claude",
        f"/url url:{url} machine:winpc engine:codex",
        f"이 포지션으로 LinkedIn 검색 URL 만들어줘 {url} winpc",
    )


def gateway_subprocess_env(
    environ: Mapping[str, str], evidence_path: str | Path,
) -> dict[str, str]:
    child = {str(key): str(value) for key, value in environ.items()}
    for key in _SERVICE_ENV_KEYS:
        child.pop(key, None)
    child.update({
        "DISCORD_GATEWAY_WORKER_MACHINE": "winpc",
        "DISCORD_GATEWAY_SYNC_COMMANDS": "0",
        "DISCORD_HR1_EVIDENCE_PATH": str(evidence_path),
        "DISCORD_HR1_REPLAY_FIRST_ENQUEUED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return child


def gateway_subprocess_argv(executable: str) -> list[str]:
    """Start from the repository import boundary, not a script-local sys.path."""
    return [str(executable), "-m", "scripts.discord_direct_gateway"]


def _one(rows: Sequence[Mapping[str, Any]], kind: str) -> Mapping[str, Any]:
    matching = [row for row in rows if row.get("kind") == kind]
    _require(len(matching) == 1, f"expected one {kind} evidence row")
    return matching[0]


def build_hr1_receipt(
    *,
    evidence: Sequence[Mapping[str, Any]],
    jobs: Mapping[int, Mapping[str, Any]],
    expected_messages: Sequence[str],
    discord_bot_message_ids: Sequence[str],
    duplicate_row_count: int,
    hermes_before: Mapping[str, Any],
    hermes_after: Mapping[str, Any],
    git_sha_v4: str,
    git_sha_v5: str,
    verifier_sha256: str,
    gateway_exit_code: int,
    final_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    _require(len(expected_messages) == 3, "HR-1 requires exactly three messages")
    started = _one(evidence, "gateway_started")
    stopped = _one(evidence, "gateway_stopped")
    originals = [
        row for row in evidence
        if row.get("kind") == "discord_delivery" and row.get("delivery") == "original"
    ]
    replays = [
        row for row in evidence
        if row.get("kind") == "discord_delivery" and row.get("delivery") == "replay"
    ]
    _require(len(originals) == 3, "exactly three original deliveries are required")
    _require(len(replays) == 1, "exactly one duplicate delivery is required")
    expected_fingerprints = [_sha256(message) for message in expected_messages]
    _require(
        [row.get("content_fingerprint") for row in originals] == expected_fingerprints,
        "Discord messages do not match the approved HR-1 inputs",
    )
    replay = replays[0]
    first = originals[0]
    _require(
        replay.get("event_id") == first.get("event_id")
        and replay.get("job_id") == first.get("job_id")
        and replay.get("content_fingerprint") == first.get("content_fingerprint")
        and replay.get("action") == "duplicate"
        and not replay.get("response_id"),
        "duplicate delivery did not suppress its response",
    )
    _require(duplicate_row_count == 1, "duplicate event created more than one queue row")

    response_ids = [str(row.get("response_id") or "") for row in originals]
    _require(
        len(set(response_ids)) == 3
        and sorted(str(value) for value in discord_bot_message_ids) == sorted(response_ids),
        "isolated bot response count or IDs do not match the three original requests",
    )

    job_evidence: list[dict[str, Any]] = []
    expected_agents = ("claude", "codex", "claude")
    for delivery, expected_agent in zip(originals, expected_agents, strict=True):
        job_id = delivery.get("job_id")
        _require(isinstance(job_id, int) and not isinstance(job_id, bool), "job id missing")
        job = jobs.get(job_id)
        _require(isinstance(job, Mapping), f"job #{job_id} was not observed")
        params = job.get("params") if isinstance(job.get("params"), Mapping) else {}
        agent = str(params.get("agent") or "claude")
        _require(agent == expected_agent, f"job #{job_id} agent mismatch")
        _require(
            job.get("machine") == "winpc"
            and job.get("skill") == "url"
            and job.get("status") == "done"
            and bool(job.get("started_at"))
            and bool(job.get("finished_at")),
            f"job #{job_id} did not prove queued -> running -> done on winpc",
        )
        job_evidence.append({
            "agent": agent,
            "event_id": str(delivery.get("event_id") or ""),
            "job_id": job_id,
            "requester_id": str(delivery.get("requester_id") or ""),
            "transitions": ["queued", "running", "done"],
            "response_id": str(delivery.get("response_id") or ""),
            "response_count": 1,
        })

    before_pids = list(hermes_before.get("pids") or [])
    after_pids = list(hermes_after.get("pids") or [])
    before_launch = hermes_before.get("launchctl_count")
    after_launch = hermes_after.get("launchctl_count")
    _require(
        before_pids == after_pids and len(before_pids) == 1
        and before_launch == after_launch == 1,
        "Hermes process or launchd identity changed during HR-1",
    )
    _require(
        gateway_exit_code == 0
        and stopped.get("released") is True
        and stopped.get("direct_gateway_pid") == started.get("direct_gateway_pid")
        and stopped.get("direct_gateway_lease_id") == started.get("direct_gateway_lease_id")
        and stopped.get("direct_gateway_generation") == started.get("direct_gateway_generation"),
        "direct gateway did not stop and release its lease cleanly",
    )
    readiness = dict(started.get("readiness") or {})
    _require(readiness.get("worker_ready") is True, "winpc worker was not ready")

    natural = {
        **job_evidence[2],
        "text_fingerprint": expected_fingerprints[2],
    }
    receipt: dict[str, Any] = {
        "schema_version": "discord-hr1/v1",
        "phase": "HR-1",
        "git_sha_v4": git_sha_v4,
        "git_sha_v5": git_sha_v5,
        "discord_bot_id": str(started.get("discord_bot_id") or ""),
        "hermes_bot_id": str(started.get("hermes_bot_id") or ""),
        "bot_identity_isolated": started.get("discord_bot_id") != started.get("hermes_bot_id"),
        "command_fingerprint": _sha256("\0".join(expected_messages)),
        "direct_gateway_pid": started.get("direct_gateway_pid"),
        "direct_gateway_lease_id": started.get("direct_gateway_lease_id"),
        "direct_gateway_generation": started.get("direct_gateway_generation"),
        "gateway_stopped_after_test": True,
        "hermes_pid_count": len(after_pids),
        "hermes_launchctl_count": after_launch,
        "hermes_pids_before": before_pids,
        "hermes_pids_after": after_pids,
        "readiness": readiness,
        "readiness_after": dict(final_readiness),
        "duplicate_event": {
            "event_id": str(first.get("event_id") or ""),
            "first_job_id": first.get("job_id"),
            "replay_job_id": replay.get("job_id"),
            "row_count": duplicate_row_count,
        },
        "jobs": job_evidence[:2],
        "natural_language": natural,
        "duplicate_response_count": 0,
        "queue_nonterminal_count": sum(
            1 for job in jobs.values() if job.get("status") not in _TERMINAL),
        "rollback_tested": True,
        "claude_job_id": job_evidence[0]["job_id"],
        "claude_response_id": job_evidence[0]["response_id"],
        "codex_job_id": job_evidence[1]["job_id"],
        "codex_response_id": job_evidence[1]["response_id"],
        "event_id": str(first.get("event_id") or ""),
        "job_id": first.get("job_id"),
        "agent": "claude",
        "state_transitions": ["queued", "running", "done"],
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "verifier_sha256": verifier_sha256,
    }
    validate_hr1_receipt(receipt, expected_verifier_sha256=verifier_sha256)
    return receipt


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: int = 30,
) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **dict(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from required HR-1 endpoint") from None
    return json.loads(body) if body else None


def _discord_request(
    token: str, path: str, *, method: str = "GET", payload: Mapping[str, Any] | None = None,
) -> Any:
    return _json_request(
        f"https://discord.com/api/v10{path}",
        method=method,
        payload=payload,
        headers={"Authorization": f"Bot {token}", "User-Agent": "Valuehire-HR1/1.0"},
    )


def _supabase_rows(
    url: str, service_key: str, path: str,
) -> list[dict[str, Any]]:
    rows = _json_request(
        f"{url.rstrip('/')}/rest/v1/{path}",
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
    )
    _require(isinstance(rows, list), "Supabase returned an invalid row shape")
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _gateway_readiness(
    supabase_url: str, minimal_key: str, token_fingerprint: str,
) -> dict[str, Any]:
    """Re-read readiness through the same minimal RPC boundary as the gateway."""
    rows = _json_request(
        f"{supabase_url.rstrip('/')}/rest/v1/rpc/discord_gateway_readiness",
        method="POST",
        payload={
            "p_token_fingerprint": token_fingerprint,
            "p_machine": "winpc",
            "p_max_age_seconds": 300,
        },
        headers={"apikey": minimal_key, "Authorization": f"Bearer {minimal_key}"},
    )
    _require(
        isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], Mapping),
        "final gateway readiness RPC returned an invalid shape",
    )
    return dict(rows[0])


def _read_evidence(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            _require(isinstance(value, dict), "HR-1 evidence row is not an object")
            rows.append(value)
    return rows


def _hermes_state() -> dict[str, Any]:
    target = f"gui/{os.getuid()}/ai.hermes.gateway"
    result = subprocess.run(
        ["launchctl", "print", target],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        return {"pids": [], "launchctl_count": 0}
    pids = [int(value) for value in re.findall(r"(?m)^\s*pid\s*=\s*(\d+)\s*$", result.stdout)]
    return {"pids": pids, "launchctl_count": 1}


def _git_sha(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    value = result.stdout.strip()
    _require(re.fullmatch(r"[0-9a-f]{40}", value) is not None, "invalid git SHA")
    return value


def _stop_gateway(process: subprocess.Popen[Any]) -> int:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            return process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                return process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    return process.wait(timeout=10)


def _wait_for_gateway(evidence_path: Path, process: subprocess.Popen[Any], timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("direct gateway exited before Discord connect")
        rows = _read_evidence(evidence_path)
        if any(row.get("kind") == "gateway_connected" for row in rows):
            return
        time.sleep(0.5)
    raise RuntimeError("timed out waiting for isolated Discord gateway connect")


def _wait_for_deliveries(
    evidence_path: Path,
    process: subprocess.Popen[Any],
    messages: Sequence[str],
    timeout: int,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    fingerprints = [_sha256(message) for message in messages]
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("direct gateway exited while waiting for Discord requests")
        rows = _read_evidence(evidence_path)
        originals = [
            row for row in rows
            if row.get("kind") == "discord_delivery" and row.get("delivery") == "original"
        ]
        replays = [
            row for row in rows
            if row.get("kind") == "discord_delivery" and row.get("delivery") == "replay"
        ]
        if len(originals) > 3 or len(replays) > 1:
            raise RuntimeError("received more Discord deliveries than HR-1 authorized")
        if len(originals) == 3 and len(replays) == 1:
            _require(
                [row.get("content_fingerprint") for row in originals] == fingerprints,
                "received Discord inputs differ from the approved three-message sequence",
            )
            return rows
        time.sleep(0.5)
    raise RuntimeError("timed out waiting for the three owner Discord requests")


def _fetch_jobs(
    supabase_url: str, service_key: str, job_ids: Sequence[int],
) -> dict[int, dict[str, Any]]:
    ids = ",".join(str(value) for value in job_ids)
    select = "id,machine,skill,status,params,requested_by,started_at,finished_at"
    rows = _supabase_rows(
        supabase_url,
        service_key,
        f"jobs?select={select}&id=in.({ids})",
    )
    return {int(row["id"]): row for row in rows if isinstance(row.get("id"), int)}


def _wait_for_jobs(
    *,
    supabase_url: str,
    service_key: str,
    job_ids: Sequence[int],
    process: subprocess.Popen[Any],
    timeout: int,
) -> dict[int, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last: tuple[tuple[int, str], ...] = ()
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("direct gateway exited before jobs completed")
        jobs = _fetch_jobs(supabase_url, service_key, job_ids)
        statuses = tuple(sorted((job_id, str(row.get("status") or "")) for job_id, row in jobs.items()))
        if statuses != last:
            print("HR-1 job states:", ", ".join(f"#{job_id}={status}" for job_id, status in statuses), flush=True)
            last = statuses
        bad = [
            (job_id, row.get("status")) for job_id, row in jobs.items()
            if row.get("status") in {"failed", "cancelled", "paused_for_human"}
        ]
        if bad:
            raise RuntimeError(f"HR-1 job did not complete: {bad}")
        if len(jobs) == len(job_ids) and all(row.get("status") == "done" for row in jobs.values()):
            return jobs
        time.sleep(1)
    raise RuntimeError("timed out waiting for winpc jobs to complete")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="run isolated Discord HR-1 live acceptance")
    parser.add_argument("--position-url", required=True)
    parser.add_argument("--owner-id", default=DEFAULT_OWNER_ID)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--request-timeout", type=int, default=1800)
    parser.add_argument("--job-timeout", type=int, default=7200)
    parser.add_argument("--startup-timeout", type=int, default=90)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    messages = expected_hr1_messages(args.position_url)
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    bot_id = os.environ.get("DISCORD_CLIENT_ID", "").strip()
    hermes_bot_id = os.environ.get("HERMES_DISCORD_BOT_ID", "").strip()
    minimal_key = os.environ.get("DISCORD_GATEWAY_SUPABASE_KEY", "").strip()
    supabase_url = (
        os.environ.get("SUPABASE_URL", "").strip()
        or os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "").strip()
        or os.environ.get("DISCORD_GATEWAY_SUPABASE_URL", "").strip()
    )
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    _require(all((token, bot_id, hermes_bot_id, minimal_key, supabase_url, service_key)),
             "required Discord/Supabase environment is incomplete")
    _require(bot_id != hermes_bot_id, "isolated bot identity equals Hermes")
    _require(minimal_key != service_key, "gateway key must not be the service-role key")

    me = _discord_request(token, "/users/@me")
    _require(isinstance(me, Mapping) and str(me.get("id")) == bot_id,
             "Discord token identity does not match DISCORD_CLIENT_ID")
    dm = _discord_request(token, "/users/@me/channels", method="POST",
                          payload={"recipient_id": args.owner_id})
    _require(isinstance(dm, Mapping) and str(dm.get("id") or "").isdigit(),
             "could not open owner DM channel")
    channel_id = str(dm["id"])
    baseline_rows = _discord_request(token, f"/channels/{channel_id}/messages?limit=1")
    baseline_id = str(baseline_rows[0]["id"]) if isinstance(baseline_rows, list) and baseline_rows else ""

    hermes_before = _hermes_state()
    _require(hermes_before.get("launchctl_count") == 1 and len(hermes_before.get("pids") or []) == 1,
             "Hermes must remain live and singular before HR-1")

    run_dir = ROOT / "artifacts/discord-cutover/hr1-runs" / (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(run_dir, 0o700)
    evidence_path = run_dir / "gateway-events.jsonl"
    log_path = run_dir / "gateway.log"
    log_handle = log_path.open("x", encoding="utf-8")
    os.chmod(log_path, 0o600)
    child_env = gateway_subprocess_env(os.environ, evidence_path)
    process = subprocess.Popen(
        gateway_subprocess_argv(sys.executable),
        cwd=str(ROOT),
        env=child_env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    gateway_exit_code: int | None = None
    jobs: dict[int, dict[str, Any]] = {}
    try:
        _wait_for_gateway(evidence_path, process, args.startup_timeout)
        print(
            f"HR-1 isolated bot connected: {me.get('username')} ({bot_id}), DM channel {channel_id}",
            flush=True,
        )
        print("아래 3개 메시지를 순서대로 정확히 보내주세요:", flush=True)
        for index, message in enumerate(messages, 1):
            print(f"{index}. {message}", flush=True)
        evidence = _wait_for_deliveries(
            evidence_path, process, messages, args.request_timeout)
        originals = [
            row for row in evidence
            if row.get("kind") == "discord_delivery" and row.get("delivery") == "original"
        ]
        job_ids = [int(row["job_id"]) for row in originals]
        jobs = _wait_for_jobs(
            supabase_url=supabase_url,
            service_key=service_key,
            job_ids=job_ids,
            process=process,
            timeout=args.job_timeout,
        )
    finally:
        gateway_exit_code = _stop_gateway(process)
        log_handle.close()

    evidence = _read_evidence(evidence_path)
    hermes_after = _hermes_state()
    query = f"?limit=100" + (f"&after={baseline_id}" if baseline_id else "")
    discord_rows = _discord_request(token, f"/channels/{channel_id}/messages{query}")
    _require(isinstance(discord_rows, list), "Discord messages response is invalid")
    bot_message_ids = [
        str(row.get("id") or "") for row in discord_rows
        if isinstance(row, Mapping)
        and str((row.get("author") or {}).get("id") or "") == bot_id
    ]
    owner_fingerprints = [
        _sha256(str(row.get("content") or "")) for row in reversed(discord_rows)
        if isinstance(row, Mapping)
        and str((row.get("author") or {}).get("id") or "") == str(args.owner_id)
    ]
    _require(owner_fingerprints == [_sha256(message) for message in messages],
             "owner Discord message count/content differs from the approved HR-1 inputs")

    first_event = next(
        str(row.get("event_id")) for row in evidence
        if row.get("kind") == "discord_delivery" and row.get("delivery") == "original"
    )
    duplicate_filter = urllib.parse.urlencode({
        "select": "id",
        "params->>idempotency_key": f"eq.discord:{first_event}",
    })
    duplicate_rows = _supabase_rows(supabase_url, service_key, f"jobs?{duplicate_filter}")
    final_readiness = _gateway_readiness(
        supabase_url, minimal_key, _sha256(token),
    )
    v4_root = Path(os.environ.get("VALUEHIRE_V4_REPO", "/Volumes/SSD/valuehire_v4"))
    verifier = ROOT / "scripts/verify_discord_hr1.py"
    receipt = build_hr1_receipt(
        evidence=evidence,
        jobs=jobs,
        expected_messages=messages,
        discord_bot_message_ids=bot_message_ids,
        duplicate_row_count=len(duplicate_rows),
        hermes_before=hermes_before,
        hermes_after=hermes_after,
        git_sha_v4=_git_sha(v4_root),
        git_sha_v5=_git_sha(ROOT),
        verifier_sha256=_sha256(verifier.read_bytes()),
        gateway_exit_code=gateway_exit_code,
        final_readiness=final_readiness,
    )
    validate_hr1_receipt(
        receipt,
        expected_verifier_sha256=receipt["verifier_sha256"],
        forbidden_values=(token, service_key, minimal_key),
    )
    _write_json_atomic(args.receipt, receipt)
    print(f"HR-1 GREEN receipt: {args.receipt}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"HR-1 RED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
