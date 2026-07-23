from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

from scripts.run_discord_hr1_live_acceptance import (
    build_hr1_receipt,
    cleanup_hr1_jobs,
    expected_hr1_messages,
    gateway_subprocess_argv,
    gateway_subprocess_env,
)
from tools.multi_position_sourcing.discord_hr1 import validate_hr1_receipt


OWNER = "814353841088757800"
BOT = "946740848018735114"
HERMES = "1512101118543397056"
POSITION = "https://app.clickup.com/t/9018789656/86eycec3a"
ROOT = Path(__file__).resolve().parents[1]


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_expected_messages_are_exact_three_paths_on_winpc() -> None:
    messages = expected_hr1_messages(POSITION)
    assert len(messages) == 3
    assert messages[0].startswith("/url ") and "engine:claude" in messages[0]
    assert messages[1].startswith("/url ") and "engine:codex" in messages[1]
    assert not messages[2].startswith("/")
    assert all(POSITION in message and "winpc" in message for message in messages)


def test_runner_is_directly_executable_from_repo_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_discord_hr1_live_acceptance.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_gateway_child_gets_minimal_key_but_no_service_role(tmp_path: Path) -> None:
    child = gateway_subprocess_env({
        "DISCORD_GATEWAY_SUPABASE_KEY": "anon-value",
        "SUPABASE_SERVICE_ROLE_KEY": "service-value",
        "SERVICE_ROLE_KEY": "second-service-value",
        "DISCORD_BOT_TOKEN": "isolated-value",
    }, tmp_path / "events.jsonl")
    assert child["DISCORD_GATEWAY_SUPABASE_KEY"] == "anon-value"
    assert child["DISCORD_GATEWAY_SYNC_COMMANDS"] == "0"
    assert child["DISCORD_HR1_REPLAY_FIRST_ENQUEUED"] == "1"
    assert "SUPABASE_SERVICE_ROLE_KEY" not in child
    assert "SERVICE_ROLE_KEY" not in child


def test_cleanup_cancels_only_nonterminal_hr1_jobs(monkeypatch) -> None:
    calls = []
    rows = [
        {"id": 70, "status": "paused_for_human"},
        {"id": 71, "status": "done"},
    ]

    def fake_rows(_url, _key, _path):
        return rows

    def fake_request(url, **kwargs):
        calls.append((url, kwargs.get("payload")))
        return [{"id": 70, "status": "cancelled"}]

    monkeypatch.setattr(
        "scripts.run_discord_hr1_live_acceptance._supabase_rows", fake_rows,
    )
    monkeypatch.setattr(
        "scripts.run_discord_hr1_live_acceptance._json_request", fake_request,
    )
    cleanup_hr1_jobs("https://example.supabase.co", "service", [70, 71])
    assert calls == [
        ("https://example.supabase.co/rest/v1/rpc/cancel_job",
         {"p_job_id": 70, "p_reason": "HR-1 live acceptance aborted"}),
    ]


def test_gateway_child_starts_as_repo_module() -> None:
    assert gateway_subprocess_argv("/venv/bin/python") == [
        "/venv/bin/python", "-m", "scripts.discord_direct_gateway",
    ]


def test_build_receipt_requires_and_combines_live_evidence() -> None:
    messages = expected_hr1_messages(POSITION)
    event_ids = (
        "1529267252160927202",
        "1529267252160927203",
        "1529267252160927204",
    )
    job_ids = (202, 203, 204)
    response_ids = (
        "1529267252160927302",
        "1529267252160927303",
        "1529267252160927304",
    )
    evidence = [{
        "kind": "gateway_started",
        "discord_bot_id": BOT,
        "hermes_bot_id": HERMES,
        "direct_gateway_pid": 1234,
        "direct_gateway_lease_id": "11111111-1111-4111-8111-111111111111",
        "direct_gateway_generation": 7,
        "readiness": {
            "minimal_rpc": True,
            "worker_ready": True,
            "worker_pid": 4242,
            "worker_machine": "winpc",
            "worker_heartbeat_age_seconds": 15,
            "claude_ready": True,
            "codex_ready": True,
            "killswitch_engaged": False,
        },
    }]
    for index, (event_id, job_id, response_id, message) in enumerate(zip(
        event_ids, job_ids, response_ids, messages, strict=True,
    )):
        evidence.append({
            "kind": "discord_delivery",
            "delivery": "original",
            "event_id": event_id,
            "requester_id": OWNER,
            "action": "enqueued",
            "job_id": job_id,
            "response_id": response_id,
            "content_fingerprint": _fingerprint(message),
        })
        if index == 0:
            evidence.append({
                "kind": "discord_delivery",
                "delivery": "replay",
                "event_id": event_id,
                "requester_id": OWNER,
                "action": "duplicate",
                "job_id": job_id,
                "content_fingerprint": _fingerprint(message),
            })
    evidence.append({
        "kind": "gateway_stopped",
        "direct_gateway_pid": 1234,
        "direct_gateway_lease_id": "11111111-1111-4111-8111-111111111111",
        "direct_gateway_generation": 7,
        "released": True,
    })
    jobs = {
        202: {"id": 202, "machine": "winpc", "skill": "url", "status": "done",
              "params": {"agent": "claude"}, "started_at": "2026-07-22T12:00:01Z",
              "finished_at": "2026-07-22T12:00:02Z"},
        203: {"id": 203, "machine": "winpc", "skill": "url", "status": "done",
              "params": {"agent": "codex"}, "started_at": "2026-07-22T12:00:03Z",
              "finished_at": "2026-07-22T12:00:04Z"},
        204: {"id": 204, "machine": "winpc", "skill": "url", "status": "done",
              "params": {}, "started_at": "2026-07-22T12:00:05Z",
              "finished_at": "2026-07-22T12:00:06Z"},
    }
    receipt = build_hr1_receipt(
        evidence=evidence,
        jobs=jobs,
        expected_messages=messages,
        discord_bot_message_ids=list(response_ids),
        duplicate_row_count=1,
        hermes_before={"pids": [4321], "launchctl_count": 1},
        hermes_after={"pids": [4321], "launchctl_count": 1},
        git_sha_v4="a" * 40,
        git_sha_v5="b" * 40,
        verifier_sha256="e" * 64,
        gateway_exit_code=0,
        final_readiness={
            "minimal_rpc": True,
            "worker_ready": True,
            "killswitch_engaged": False,
            "worker_heartbeat_age_seconds": 5,
            "worker_machine": "winpc",
            "worker_pid": 4242,
            "claude_ready": True,
            "codex_ready": True,
        },
    )
    assert validate_hr1_receipt(receipt)["phase"] == "HR-1"
    assert receipt["duplicate_response_count"] == 0
    assert receipt["queue_nonterminal_count"] == 0
    assert receipt["readiness_after"]["worker_pid"] == 4242
