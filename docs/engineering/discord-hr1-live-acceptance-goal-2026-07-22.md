# Discord direct gateway HR-1 live acceptance goal

- Issue: https://github.com/sangmokang/Valuehire_v5/issues/184
- Acceptance criterion: HR-1 direct-path live acceptance only. HR-2 and later retirement phases are out of scope.
- Risk: L3 (production migration, Discord writes, credential boundary, external replies).

## Current-state evidence and root cause

Live attempt 2026-07-22 produced jobs 65-67 on `winpc`; all failed with the same
secret-free error fingerprint `3621eeed6e313ec2afcfc5b7a458d52f581abcaa748142df13dbff1cab1b2ebf`,
which matches `[WinError 2] 지정된 파일을 찾을 수 없습니다`. The worker heartbeat was fresh,
but its scheduled-task environment did not expose the Claude/Codex executable. This is a
worker executable-resolution failure, not a gateway lease, RPC, deduplication, or Hermes failure.

The worker now accepts an explicit `VALUEHIRE_CLAUDE_BIN`/`VALUEHIRE_CODEX_BIN` path from its
task environment or `.env.local`, including Windows `.cmd`/`.bat` shims. The WinPC worker must
be restarted with the installed CLI path before the next live attempt.

- SOT 33 requires the startup path to prove minimal RPC access, the target worker heartbeat,
  killswitch state, and one shared lease before Discord connect (`docs/sot/33-hermes-retirement.md`).
- The inherited first implementation checks readiness and acquires a lease before `client.run`, but
  its migration keys the lease by bot id and omits holder pid, generation, released_at, killswitch,
  and token fingerprint (`supabase/migrations/20260722_discord_gateway_hr1_runtime.sql:4-17`).
- Lease acquire/renew accepts any fresh worker heartbeat instead of the requested worker
  (`supabase/migrations/20260722_discord_gateway_hr1_runtime.sql:62-66,102-106`).
- Startup defaults to `macmini`, while the owner supplied `target_machine=winpc`, and does not
  compare the isolated direct identity with the live Hermes identity
  (`scripts/discord_direct_gateway.py:975-989`).
- No `discord-e2e-cutover.py` guard exists under the shared dispatcher.
- The receipt validator omits Hermes process/launchd counts, queue nonterminal count, rollback
  result, and the required top-level duplicate evidence.

Root cause: HR-1 was implemented as a receipt helper plus a partial lease, not as a complete
fail-closed startup and live-evidence boundary. Static SQL marker tests allowed the missing database
semantics and hook wiring to pass.

## Input/output contract

Startup input:

```text
DISCORD_BOT_TOKEN: secret string, read only to compute SHA-256 fingerprint and connect
DISCORD_CLIENT_ID: direct bot snowflake
HERMES_DISCORD_BOT_ID: live Hermes bot snowflake; must differ from direct bot
DISCORD_GATEWAY_WORKER_MACHINE: exact fleet machine, HR-1 requires winpc
DISCORD_GATEWAY_SUPABASE_URL/KEY: minimal endpoint/key only
DISCORD_GATEWAY_LEASE_TTL_SECONDS: integer 30..300
```

RPC output shapes:

```text
discord_gateway_readiness(machine,max_age) ->
  {minimal_rpc, worker_ready, killswitch_engaged, worker_heartbeat_age_seconds}
acquire(token_fingerprint,holder_identity,pid,ttl) ->
  {lease_id,generation,acquired_at,expires_at}
renew(lease_id,holder_identity,pid,generation,ttl) -> same ownership tuple
release(lease_id,holder_identity,pid,generation) -> {released}
```

Queue invariant: every Discord enqueue has a snowflake `event_id` and the derived
`idempotency_key=discord:<event_id>`. An owner `skill=agent` job additionally carries the existing
approval fields and may not be created by the gateway's anonymous RPC path without that owner proof.
The gateway process never calls Claude or Codex; fleet worker owns execution.

State transitions:

```text
gateway: configured -> ready -> leased -> connected -> renewing -> released/stopped
job: queued -> running -> done
lease: absent/expired -> acquired(generation+1) -> renewed* -> released
```

## Acceptance assertions

1. Configuration, distinct bot identities, minimal RPC, `winpc` heartbeat, killswitch-off, then
   atomic lease acquisition occur in that order; any failure prevents `client.run()`.
2. Two holders cannot own one token fingerprint concurrently; acquire/renew/release are atomic;
   an expired lease is reclaimable with a higher generation.
3. Renewal ownership failures close the Discord client; shutdown attempts release. Raw token,
   service-role key, and secret file content never enter logs, receipts, DB rows, or Git.
4. The shared hook blocks startup without readiness, enqueue without event id, direct engine
   execution in the gateway, and unsigned `skill=agent`. Production code enforces the same core
   boundaries when hooks are absent.
5. The production migration is applied only after focused unit/database integration tests and the
   full verifier pass. Safe-field RPC readback proves the deployed grants and current `winpc` state.
6. The isolated bot processes exactly one Claude, one Codex, and one natural-language request plus
   one replay of an existing event. Each original job records `queued -> running -> done` and one
   requester response id; replay resolves to one job and adds no response.
7. Hermes PID/launchd counts and identities remain unchanged. The direct gateway is stopped after
   HR-1. Queue nonterminal count is zero and the secret-free canonical receipt passes an independent
   recheck.

## Non-scope

- No Hermes bootout, stop, restart, move, delete, plugin/config mutation, or token rotation.
- No HR-2 queue freeze/drain, HR-3 cutover, HR-4 quarantine, or later cleanup.
- No portal/search behavior changes beyond the already-required natural-language queue route.
- No service-role credential in the direct gateway process.

## Verification commands

```bash
python3 -m pytest tests/test_discord_hr1_acceptance.py tests/test_discord_direct_gateway.py -q
python3 -m pytest tests/test_discord_hr1_postgres.py -q
python3 -m pytest tests/test_discord_e2e_cutover_hook.py -q
./verify.sh
python3 scripts/verify_discord_hr1.py artifacts/discord-cutover/hermes-retirement-receipt.json
make strict-exit-gate
```

The production RPC readback and live Discord checks run only after the local commands above pass.

## L3 owner signoff record

- Source: owner current-turn Codex instruction on 2026-07-22; direct user message, not an ambient
  environment flag. TTY confirmation is not applicable to this API turn and is not fabricated.
- Target/channel/count: production Supabase migration once; isolated Discord bot identity; Claude
  request once, Codex request once, natural-language request once, one duplicate delivery of an
  existing event; exactly one reply per original request; Hermes mutations zero.
- Normalized payload SHA-256: `a91f8e4b153f48bafd6f7ee647b0ef88e59f4d8a986f4a895a4356f21721e65e`.
- One-time nonce: `60c9e34d87d2415cb67e355526df803a`.
- GitHub issue write: one issue (#184), no other external write before local validation.

## Exception table

| Condition | Required action |
|---|---|
| Missing/ambiguous isolated identity | Stop before Discord connect; record safe reason. |
| Minimal RPC/grant/readiness failure | Stop before Discord connect; do not fall back to service role. |
| `winpc` heartbeat stale/missing | Stop before Discord connect. |
| Killswitch engaged | Stop before lease/connect. |
| Lease held or ownership lost | Do not connect, or close an existing client and release best-effort. |
| Duplicate response or Hermes response observed | Stop direct gateway and mark HR-1 failed. |
| CAPTCHA/2FA/identity checkpoint | Stop the affected job and require human resolution. |
| Any condition not listed above | Explicitly stop, record it, and update this table before resuming. |

## SOT checklist

- [x] Read v4 strict core: `docs/sot/19-harness-loop.md`, `30-strict-mode-contract.md`,
  `31-strict-recurrence-ledger.md`, and shared hook SOT 27.
- [x] Read v5 `AGENTS.md`, `CLAUDE.md`, `docs/harness.md`, SOT 29/30/31/33, existing direct-gateway
  goals, migration, gateway entrypoint, receiver, queue, worker, and tests.
- [x] Reuse the existing HR-1 worktree and RED commit rather than creating a duplicate runner.
- [x] Focused RED additions prove every missing boundary.
- [x] Local unit/database integration and full verification pass before production migration.
- [ ] Production safe readback, isolated live round trips, receipt, rollback stop, and independent
  verification pass before HR-1 is called GREEN.
