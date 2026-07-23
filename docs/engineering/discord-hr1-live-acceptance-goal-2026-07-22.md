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

Continuation baseline (2026-07-23): worktree HEAD is `c639581` with no tracked or untracked
changes. Hermes remains launchd `running` at PID 22367, process start
`2026-07-22 15:33:44`, and has not been stopped, restarted, moved, or deleted. The first
connectivity probe resolved WinPC as `192.168.219.124`, but SSH/WinRM were not reachable;
the direct gateway remains stopped while the local fail-closed readiness unit is completed.

Continuation observation (2026-07-23 00:41 JST): the two fail-closed migrations were applied once
through the linked Supabase CLI after an exact one-file dry-run. Safe-field production readback
reported `winpc` worker PID 14080, heartbeat age 26 seconds, queue nonterminal count 0,
`claude_ready=false`, `codex_ready=false`, and therefore `worker_ready=false`. Hermes was still the
same launchd process at PID 22367 (`runs=2`), and no direct gateway process was running. Because no
existing WinPC management endpoint was reachable, U3 remains blocked and no Discord message was
sent. This is an explicit HR-1 RED/blocked state, not a partial GREEN.

After the PID-binding and final-readiness changes, focused verification passed 150 tests and the
full verifier passed 2495 tests with 4 expected failures and 105 Node subtests. A fresh read-only
adversarial review returned `LOCAL_SAFEGUARDS: PASS`, `HR1_LIVE: RED`, with no additional blocking
code finding. The live verdict deliberately remains RED until U3-U5 execute.

The relevant strict recurrence-ledger rows are the repeated command/SOT-violation row and the
reconfirmation row. This continuation follows their promoted controls: the exception table owns
unexpected states, and the owner's current instruction is not reconfirmed.

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
  {minimal_rpc, worker_ready, killswitch_engaged, worker_heartbeat_age_seconds,
   worker_machine, worker_pid, claude_ready, codex_ready}
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

## Continuation decomposition and agent-readiness contract

| Unit | One contract / acceptance check | Dependency |
|---|---|---|
| U1 | Worker probes configured Claude and Codex CLIs with a bounded `--version`; heartbeat reports only booleans, never paths or output. Focused worker tests pass. | Existing `c639581` |
| U2 | Database readiness, lease acquire, and renewal require a fresh heartbeat with both booleans true and bind the lease to that heartbeat's worker PID; legacy/null capability rows and replacement-process renewals fail closed. PostgreSQL tests pass. | U1 |
| U3 | WinPC `Get-Command` read-back, user worker environment update, one scheduled-worker restart, new PID, and fresh all-ready heartbeat are observed. | U2 deployed |
| U4 | The formal runner sends exactly three originals plus the first-event replay and observes one job/one reply per original. | U3 + gateway preflight |
| U5 | Gateway is stopped, queue nonterminal count is zero, receipt verifier/full verify/independent adversarial recheck pass. | U4 |

Input domain (explicit input: configured CLI name/path; implicit input: worker process environment,
PATH, platform shim rules, filesystem, subprocess timeout/exit code, heartbeat freshness, database
row version, and concurrent lease acquisition):

| Input class | Required result | Test mapping |
|---|---|---|
| Explicit configured executable exists and bounded `--version` exits 0 | Report that agent ready; do not persist path/output | worker probe success |
| No explicit value, PATH resolves an executable and `--version` exits 0 | Report that agent ready | worker PATH success |
| Empty/missing path and PATH miss | Report false; heartbeat continues so the failure is visible | worker missing executable |
| File/shim exists but execution is missing, non-zero, or times out | Report false without leaking stderr or path | worker nonzero/timeout |
| Windows `.cmd`/`.bat` shim | Use the existing quoted `cmd.exe` boundary with empty stdin | worker Windows shim |
| One of Claude/Codex false | `worker_ready=false`; readiness and lease fail before Discord connect | PostgreSQL partial readiness |
| Both true but heartbeat stale/future/absent | `worker_ready=false` | PostgreSQL freshness boundaries |
| Legacy row with capability columns false/null | `worker_ready=false`; no compatibility fallback | PostgreSQL legacy row |
| Capability changes after readiness but before acquire/renew | Database lease write is rejected atomically | PostgreSQL race guard |
| Worker restarts after lease acquisition | New PID cannot renew the old process-bound lease; a fresh acquisition binds the new PID | PostgreSQL generation guard |
| Duplicate event/retry | Existing `discord:<event_id>` job is returned; no second reply | live replay |
| Any other input/state | Explicitly stop, record a secret-free reason, update this table before resuming | adversarial review |

Decisions fixed by this contract: executable readiness means a bounded local `--version` with exit
code 0; both engines are mandatory for HR-1; the capability sample has the same age as its heartbeat;
missing/legacy values are false; probe exceptions never stop heartbeat publication but can never
produce readiness; ordering remains configuration -> distinct identity -> database readiness ->
process-bound lease -> Discord connect. A successful receipt also requires a final minimal-RPC
readiness read after gateway shutdown with the same positive worker PID and both engines still true.

## Acceptance assertions

1. Configuration, distinct bot identities, minimal RPC, `winpc` heartbeat, killswitch-off, then
   atomic lease acquisition occur in that order; any failure prevents `client.run()`.
2. Two holders cannot own one token fingerprint concurrently; acquire/renew/release are atomic;
   an expired lease is reclaimable with a higher generation, and renewal cannot cross a worker PID
   change.
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
   recheck. Receipt construction re-reads readiness after shutdown and proves the same worker PID.

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
- Continuation source: owner current-turn Codex instruction on 2026-07-23. Target/channel/count are
  unchanged: WinPC scheduled worker environment/restart once; isolated Discord bot three originals
  plus one replay; Hermes mutations zero; HR-2+ excluded. Normalized payload SHA-256:
  `3900906dca71fb4ac06f0cbd81daf1014066f649a0aa48550885dac2320ac21a`; one-time nonce:
  `f5146870237f471f9f4688ab196d73bc`. TTY confirmation remains inapplicable and is not fabricated.

## Exception table

| Condition | Required action |
|---|---|
| Missing/ambiguous isolated identity | Stop before Discord connect; record safe reason. |
| Minimal RPC/grant/readiness failure | Stop before Discord connect; do not fall back to service role. |
| `winpc` heartbeat stale/missing | Stop before Discord connect. |
| Killswitch engaged | Stop before lease/connect. |
| Lease held or ownership lost | Do not connect, or close an existing client and release best-effort. |
| Duplicate response or Hermes response observed | Stop direct gateway and mark HR-1 failed. |
| Discord client rewrites or line-wraps an approved command | Stop and release the gateway; use the parser-equivalent compact one-line command on a fresh run. Never reuse mixed evidence. |
| CAPTCHA/2FA/identity checkpoint | Stop the affected job and require human resolution. |
| WinPC remote administration unavailable | Keep the gateway stopped; complete local fail-closed work, record connectivity evidence, and resume U3 only when the existing managed path is reachable. |
| Any condition not listed above | Explicitly stop, record it, and update this table before resuming. |

## SOT checklist

- [x] Read v4 strict core: `docs/sot/19-harness-loop.md`, `30-strict-mode-contract.md`,
  `31-strict-recurrence-ledger.md`, and shared hook SOT 27.
- [x] Read v5 `AGENTS.md`, `CLAUDE.md`, `docs/harness.md`, SOT 29/30/31/33, existing direct-gateway
  goals, migration, gateway entrypoint, receiver, queue, worker, and tests.
- [x] Reuse the existing HR-1 worktree and RED commit rather than creating a duplicate runner.
- [x] Focused RED additions prove every missing boundary.
- [x] Local unit/database integration and full verification pass before production migration.
- [x] Production safe readback proves the deployed RPC is fail-closed for the current unready
  WinPC worker; both migration hashes and the blocked state are recorded without secrets.
- [ ] WinPC CLI discovery/environment/restart, isolated live round trips, receipt, rollback stop,
  and final independent verification pass before HR-1 is called GREEN.
