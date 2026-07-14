---
name: disearch
description: "Trace, audit, test, and improve Valuehire Discord-to-search command workflows. Use when the user mentions disearch, Discord search commands, /fleet-run, /run-search, /aisearch from Discord, Hermes search routing, a Discord search that is ignored/duplicated/stuck, or asks for a detailed process briefing, refactoring plan, tests, code vulnerabilities, functional vulnerabilities, authorization, queue, worker, or result-delivery review for Discord-triggered candidate search."
---

# Disearch

Audit the Discord control plane that starts Valuehire candidate search. Distinguish the live path from schemas, dry-runs, and legacy bridges before making any operational claim.

## Start safely

1. Locate the active Valuehire checkout from the current directory. Do not assume a macOS-only path.
2. Read `CLAUDE.md`, `docs/search-access.md`, and the relevant SOT files, especially `docs/sot/25-ai-search-execution-process.*`, `29-fleet-control.*`, and `30-fleet-run-reliability.md` when present.
3. Inspect `git status --short` and preserve unrelated or in-progress changes.
4. State whether the request is read-only analysis or authorizes implementation. Do not refactor code for an audit-only request.
5. Keep all external writes off by default. Do not register Discord commands, enqueue live jobs, restart gateways/workers, send Discord messages, or run portal searches without explicit approval.
6. Never print bot tokens, webhooks, Supabase keys, cookies, credentials, or raw `.env*` content.

## Recover the real control plane

Classify every discovered path as one of:

- `LIVE_CONFIRMED`: code plus deployment/runtime evidence proves it receives commands.
- `WIRED_IN_REPO`: a receiver calls the parser/dispatcher, but live deployment is unverified.
- `SCHEMA_ONLY`: command registration payload or parser exists without a receiver/consumer.
- `DRY_RUN_OR_TEST_ONLY`: referenced only by examples, dry-runs, or tests.
- `LEGACY`: older bridge that bypasses the current queue/worker contract.
- `UNKNOWN`: evidence is insufficient; say what is missing.

Trace the current Valuehire path in this order:

1. Discord event reception and sender/platform/channel capture.
2. Natural-language or slash-command normalization.
3. Command argument validation.
4. User, DM/guild channel, and role authorization.
5. Search-only skill and outbound-action gates.
6. Idempotency and queue enqueue.
7. Machine/account selection and worker claim.
8. Prompt construction and `aisearch`/`humansearch` execution.
9. Captcha/2FA pause, resume, cancel, timeout, and orphan handling.
10. Completion-receipt validation, queue release, and Discord result delivery.

For this repository, inspect at minimum:

- `ops/hermes-plugin/valuehire_fleet/__init__.py`
- `tools/multi_position_sourcing/hermes_fleet_bridge.py`
- `tools/multi_position_sourcing/discord_routing.py`
- `tools/multi_position_sourcing/fleet_dispatch.py`
- `tools/multi_position_sourcing/job_queue.py`
- `tools/multi_position_sourcing/fleet_worker.py`
- `tools/multi_position_sourcing/fleet_heartbeat.py`
- `tools/multi_position_sourcing/register_discord_commands.py`
- `scripts/discord_command_listener.py`
- their focused tests and Supabase migrations

Do not treat `discord_slash_command_payloads()` as a live receiver. Find the interaction webhook, gateway handler, or plugin registration that actually consumes the event.

## Run the reusable audit

Run the bundled read-only scanner before forming conclusions:

```bash
python3 ".claude/skills/disearch/scripts/audit_disearch.py" --repo . --format markdown
```

Use `--format json` when a machine-readable artifact is useful. Treat scanner findings as leads that require source confirmation, not as proof by themselves.

For the detailed review rubric and current Valuehire hypotheses to re-check, read `references/review-checklist.md`.

## Test in layers

1. Run parser, authorization, bridge, dispatcher, queue, worker, heartbeat, and reliability unit tests without network credentials.
2. Run adversarial cases for unauthorized users, guild-channel allowlist bypass, duplicate events, malformed quoting/options, unsupported URLs/hosts, exception redaction, and result visibility.
3. Run integration tests with fake queues/notifiers. Patch or inject the notifier; a fake queue alone does not isolate `dispatch_fleet_command()` because enqueue success may call Discord notification code.
4. On Windows, isolate the legacy listener lock test before running the whole file. Verify its PID-liveness implementation does not signal the target process.
5. Require explicit approval before live Discord, Supabase, gateway, worker, or portal tests. Record the exact external effects and rollback.

Report pass counts, skipped tests, interrupted tests, and what was not tested. Never infer live health from unit tests alone.

## Judge vulnerabilities

Separate findings into:

- **Code/security**: authorization bypass, cross-channel identity confusion, secret/error leakage, unrestricted local agent execution, unsafe URL trust, race conditions, non-atomic idempotency, notification side effects, and platform-specific process handling.
- **Functional/operational**: dead commands, duplicate control planes, queued/running stalls, wrong skill/machine/channel routing, missing requester reply, public response leakage, stale docs, incomplete receipts, and unverified deployment.

For every finding include severity, confidence, evidence path and line, impact, minimal reproduction, and the smallest safe remediation. Label a hypothesis as `needs reproduction`; do not present it as confirmed.

## Refactor only when authorized

Prefer this order:

1. Define one transport-neutral command envelope containing event ID, user ID, platform, DM/guild context, channel/guild IDs, roles, command, and options.
2. Centralize command definitions, defaults, aliases, and schemas in one manifest used by Hermes, native Discord registration, parsers, and docs.
3. Keep transport adapters thin; reuse one authorization and dispatch service.
4. Make enqueue idempotent by event ID and return the existing job on conflict.
5. Inject notifier, queue, clock, and runner dependencies. Keep dispatch tests free of external I/O.
6. Separate requester DM, operations alert, and public acknowledgement policies.
7. Quarantine or remove the legacy free-form listener after proving no live dependency.
8. Add an end-to-end replay harness from recorded/synthetic Discord event through queue payload and response formatting.

Write failing regression tests before implementing each confirmed fix. Preserve SOT safety gates and do not weaken tests.

## Briefing contract

Lead with a one-line verdict, then provide:

1. The recommended user-facing command and examples.
2. A numbered end-to-end process with actual file/function evidence.
3. A control-plane classification table.
4. Test results and coverage gaps.
5. Code/security findings, then functional/operational findings.
6. A prioritized refactor plan: immediate containment, structural cleanup, and live verification.
7. Explicit external effects, unresolved assumptions, and the next safe action.

Use concise Korean unless the user requests another language.
