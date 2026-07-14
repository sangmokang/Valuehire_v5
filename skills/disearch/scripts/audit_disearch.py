#!/usr/bin/env python3
"""Read-only static audit for Valuehire Discord-to-search control planes."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


EXPECTED = (
    "ops/hermes-plugin/valuehire_fleet/__init__.py",
    "tools/multi_position_sourcing/hermes_fleet_bridge.py",
    "tools/multi_position_sourcing/discord_routing.py",
    "tools/multi_position_sourcing/fleet_dispatch.py",
    "tools/multi_position_sourcing/job_queue.py",
    "tools/multi_position_sourcing/fleet_worker.py",
    "tools/multi_position_sourcing/fleet_heartbeat.py",
    "tools/multi_position_sourcing/register_discord_commands.py",
    "scripts/discord_command_listener.py",
)

SEARCH_ROOTS = ("ops", "tools", "scripts")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _line_of(text: str, needle: str) -> int | None:
    for number, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return number
    return None


def _evidence(repo: Path, relative: str, needle: str) -> dict[str, Any]:
    text = _read(repo / relative)
    return {"path": relative, "line": _line_of(text, needle), "needle": needle}


def _python_files(repo: Path) -> list[Path]:
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        base = repo / root
        if base.exists():
            files.extend(path for path in base.rglob("*.py") if "__pycache__" not in path.parts)
    return files


def _consumer_hits(repo: Path, symbol: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    definition = re.compile(rf"^\s*def\s+{re.escape(symbol)}\b")
    for path in _python_files(repo):
        relative = path.relative_to(repo).as_posix()
        if relative.endswith("dry_run.py") or relative.endswith("discord_routing.py"):
            continue
        for number, line in enumerate(_read(path).splitlines(), 1):
            if symbol in line and not definition.search(line) and not line.lstrip().startswith(("#", '"""')):
                hits.append({"path": relative, "line": number, "text": line.strip()[:180]})
    return hits


def audit(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    artifacts = {relative: (repo / relative).is_file() for relative in EXPECTED}
    plugin_rel = "ops/hermes-plugin/valuehire_fleet/__init__.py"
    bridge_rel = "tools/multi_position_sourcing/hermes_fleet_bridge.py"
    routing_rel = "tools/multi_position_sourcing/discord_routing.py"
    dispatch_rel = "tools/multi_position_sourcing/fleet_dispatch.py"
    queue_rel = "tools/multi_position_sourcing/job_queue.py"
    worker_rel = "tools/multi_position_sourcing/fleet_worker.py"
    legacy_rel = "scripts/discord_command_listener.py"

    plugin = _read(repo / plugin_rel)
    bridge = _read(repo / bridge_rel)
    routing = _read(repo / routing_rel)
    dispatch = _read(repo / dispatch_rel)
    queue = _read(repo / queue_rel)
    worker = _read(repo / worker_rel)
    legacy = _read(repo / legacy_rel)
    ai_search_skill = _read(repo / "skills/ai-search/SKILL.md")

    parser_consumers = _consumer_hits(repo, "parse_discord_command_text")
    findings: list[dict[str, Any]] = []

    def add(fid: str, severity: str, title: str, evidence: dict[str, Any], note: str) -> None:
        findings.append({
            "id": fid,
            "severity": severity,
            "title": title,
            "evidence": evidence,
            "note": note,
            "status": "static-lead-needs-source-confirmation",
        })

    if plugin and "register_command" in plugin and "pre_gateway_dispatch" in plugin:
        hermes_class = "WIRED_IN_REPO"
    else:
        hermes_class = "UNKNOWN"

    native_schema = "discord_slash_command_payloads" in routing
    native_receiver = bool(parser_consumers)
    native_class = "WIRED_IN_REPO" if native_receiver else ("SCHEMA_ONLY" if native_schema else "UNKNOWN")
    legacy_class = "LEGACY" if legacy else "UNKNOWN"

    if "is_dm=True" in bridge and 'channel_id="hermes-dm"' in bridge:
        add(
            "transport-context-collapsed",
            "high",
            "Hermes bridge statically forces every invocation to DM context",
            _evidence(repo, bridge_rel, "is_dm=True"),
            "Confirm whether guild/channel/role context is lost and server allowlists are bypassed.",
        )
    if 'f"internal error: {exc}"' in bridge or 'return f"오류: {exc}"' in plugin:
        add(
            "raw-exception-response",
            "medium",
            "Raw exception text can be returned to Discord",
            _evidence(repo, bridge_rel, 'f"internal error: {exc}"'),
            "Redact token-like values, URLs with credentials, local paths, and upstream response bodies.",
        )
    if "discord_notify(" in dispatch:
        add(
            "dispatch-notifier-coupling",
            "medium",
            "Queue dispatch directly calls Discord notification code",
            _evidence(repo, dispatch_rel, "discord_notify("),
            "Inject a notifier so fake-queue tests and dry runs cannot touch the network.",
        )
    if "127.0.0.1" not in queue and "parsed.hostname" not in queue and "parsed.netloc" in queue:
        add(
            "broad-url-trust",
            "high",
            "Job URL validation appears to accept arbitrary HTTP(S) hosts",
            _evidence(repo, queue_rel, "def _valid_url"),
            "Confirm loopback/private/link-local/userinfo/redirect handling and add purpose-specific host policy.",
        )
    if '["claude", "-p", prompt]' in worker:
        add(
            "agent-permission-boundary",
            "high",
            "Discord-triggered jobs launch a local coding agent without a visible permission profile",
            _evidence(repo, worker_rel, '["claude", "-p", prompt]'),
            "Document and enforce tool/filesystem/network permissions; treat remote page content as untrusted.",
        )
    if (
        "channels 는 saramin,jobkorea 만 허용합니다" in bridge
        and "LinkedIn RPS" in ai_search_skill
        and 'params.get("channels") or ["saramin", "jobkorea"]' in worker
    ):
        add(
            "three-channel-contract-drift",
            "high",
            "Discord aisearch can complete with only Saramin and Jobkorea evidence while the AI Search skill requires LinkedIn RPS",
            _evidence(repo, bridge_rel, "channels 는 saramin,jobkorea 만 허용합니다"),
            "Align the command manifest, worker prompt, and completion receipt with the three-channel SOT or explicitly name this as a two-channel mode.",
        )
    if (
        "requester DM" in worker
        and 'os.environ.get("FLEET_REPORT_CHANNEL", DEFAULT_REPORT_CHANNEL)' in worker
        and "requested_by" not in worker[worker.find("def discord_notify"):worker.find("class FleetWorker")]
    ):
        add(
            "requester-reply-mismatch",
            "medium",
            "Worker notification claims requester DM delivery but uses a fixed report channel and OPS webhook",
            _evidence(repo, worker_rel, "def discord_notify"),
            "Resolve the requester ID to a DM destination, and separate requester, public acknowledgement, and operations alerts.",
        )
    if "os.kill(int(old), 0)" in legacy:
        add(
            "legacy-pid-probe",
            "medium",
            "Legacy single-instance PID probe is platform-sensitive and non-atomic",
            _evidence(repo, legacy_rel, "os.kill(int(old), 0)"),
            "Use an atomic OS lock and a Windows-safe process-liveness check; add simultaneous-start coverage.",
        )
    if legacy and 'subprocess.run(' in legacy and '["claude", "-p", prompt]' in legacy:
        add(
            "legacy-freeform-agent",
            "high",
            "Legacy owner DM text is passed directly to a local coding agent",
            _evidence(repo, legacy_rel, '["claude", "-p", prompt]'),
            "Quarantine this bridge or route it through the same typed envelope, authorization, idempotency, and queue gates.",
        )
    if native_schema and not native_receiver:
        add(
            "native-schema-without-receiver",
            "medium",
            "Native Discord command payloads have no production parser consumer in scanned Python code",
            _evidence(repo, routing_rel, "def discord_slash_command_payloads"),
            "Do not advertise these commands as live until an interaction receiver is found and deployed.",
        )
    if "params->>'idempotency_key'" in _read(repo / "supabase/migrations/20260713_fleet_job_idempotency.sql") and "idempotency" not in queue[queue.find("def enqueue"):queue.find("def claim_next")]:
        add(
            "idempotency-conflict-ux",
            "medium",
            "Database uniqueness exists but enqueue does not visibly recover the existing job",
            _evidence(repo, "supabase/migrations/20260713_fleet_job_idempotency.sql", "idempotency_key"),
            "On duplicate event IDs, fetch and return the existing job instead of surfacing a raw conflict.",
        )

    migration = _read(repo / "supabase/migrations/20260713_fleet_job_idempotency.sql")
    return {
        "repo": str(repo),
        "artifacts": artifacts,
        "control_planes": {
            "hermes_fleet_plugin": hermes_class,
            "native_discord_schema": native_class,
            "legacy_freeform_dm_listener": legacy_class,
        },
        "signals": {
            "native_parser_consumers": parser_consumers,
            "discord_event_id_unique_index": "idempotency_key" in migration,
            "worker_launches_local_agent": '["claude", "-p", prompt]' in worker,
        },
        "findings": findings,
        "safe_test_command": (
            "python -m pytest -q tests/test_hermes_fleet_bridge.py "
            "tests/test_hermes_plugin_registration.py tests/test_fleet_dispatch.py "
            "tests/test_job_queue.py tests/test_fleet_worker.py "
            "tests/test_fleet_heartbeat.py tests/test_fleet_reliability.py"
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Disearch static audit",
        "",
        f"- Repo: `{report['repo']}`",
        "- Scope: read-only static evidence; runtime/deployment remains unverified",
        "",
        "## Control planes",
        "",
    ]
    for name, state in report["control_planes"].items():
        lines.append(f"- `{name}`: **{state}**")
    lines.extend(["", "## Findings", ""])
    if not report["findings"]:
        lines.append("- No configured static leads found.")
    for finding in report["findings"]:
        evidence = finding["evidence"]
        location = evidence["path"] + (f":{evidence['line']}" if evidence.get("line") else "")
        lines.extend([
            f"- **{finding['severity'].upper()} · {finding['id']}** — {finding['title']}",
            f"  - Evidence: `{location}`",
            f"  - Next check: {finding['note']}",
        ])
    lines.extend(["", "## Safe focused tests", "", f"```text\n{report['safe_test_command']}\n```"])
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Valuehire repository root")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    report = audit(Path(args.repo))
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
