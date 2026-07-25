# Hermes retirement HR-1 on current main

- Mode: mixed
- Risk: L3
- Owner signoff: the 2026-07-26 instruction authorizes HR-1 live acceptance and,
  only after its success, the ordered HR-2/HR-3 production cutover. HR-4 still
  requires the full 24-hour observation before HR-5.
- One acceptance criterion for this worktree: current `main` contains the
  fail-closed HR-1 direct-gateway lease/readiness boundary and passes the
  required local and adversarial checks. Live HR-1 evidence is a subsequent
  gate, not something a local test may fabricate.

## Current evidence and root cause

- `main` is `0aa9d5b`; commits `c96d137` and `30a8e0f` are not ancestors of
  `main`.
- The clean worktree `task/hermes-retirement-hr1-main-lease` contains those two
  commits and is the existing isolated Harness workspace to continue.
- `main` currently runs Hermes through `ai.hermes.gateway`; a fleet worker
  process is present; no direct gateway process or canonical retirement receipt
  is present.
- The dependency inventory exists with the previously completed HR-0 result,
  but HR-1 cannot be inferred from that inventory.
- A full verifier run on `main` produced one timing-test failure among 2,730
  tests; the exact failed test passed immediately when rerun alone. This
  intermittent result remains open until the post-merge focused and full runs.

Root cause: the current production branch lacks the HR-1 database lease,
engine-readiness, and gateway startup enforcement already developed in the two
unmerged commits. Blindly merging their old base would risk discarding newer
gateway, login, model, and natural-language work now present on `main`.

## Unit decomposition

| Unit | Contract | Verification | Dependency |
|---|---|---|---|
| U1 | Review the two commits against current `main`; preserve all newer behavior. | merge-tree plus named-file diff | none |
| U2 | Integrate current `main` into the existing HR-1 workspace without rewriting either history. | clean merge and focused HR-1 tests | U1 |
| U3 | Prove local gateway, receiver, engine selection, and bot-console behavior. | six user-required focused suites | U2 |
| U4 | Attack duplicate intake, dual receiver, missing lease, stale/forged readiness, queue bypass, direct engine execution, and secret exposure. | explicit regression/adversarial commands | U3 |
| U5 | Run the full verifier and independent fresh-engine review. | `./verify.sh`, verdict artifact | U4 |
| U6 | Perform isolated HR-1 live acceptance and create a secret-free receipt. | live runner plus receipt verifier | U5 and real bot/worker readiness |

No later unit may begin before the previous unit passes. HR-2 and later phases
must use separate Harness workspaces after U6.

## Input domain

Inputs include explicit Discord event fields and configuration plus implicit
database state, worker heartbeat/capability state, process identity, lease
generation, time, concurrent starts, queue availability, and Discord identity.

| Input class | Required handling | Test/evidence |
|---|---|---|
| Valid isolated bot, fresh ready worker, available lease, unique event | acquire lease, enqueue once, worker executes, reply once | HR-1 live receipt |
| Missing/empty/malformed event id or identity | reject before enqueue/connect | focused tests |
| Duplicate/retried event | return the original job and suppress a second response | HR-1 acceptance tests |
| Hermes and direct identity equal or two receivers present | reject before connect | identity/receiver tests |
| Missing, expired, stolen, or generation-mismatched lease | reject or close the client | lease tests |
| Missing/stale/future heartbeat or replaced worker PID | readiness false; no connect | readiness tests |
| Claude or Codex probe absent, false, forged, or stale | readiness false; no connect | readiness tests |
| Queue/RPC outage or malformed response | explicit failure; no silent fallback | gateway tests |
| Queue insertion outside the minimal gateway RPC | deny by grants and production guard | SQL/guard tests |
| Gateway attempts Claude/Codex execution | reject; worker remains sole executor | hook and production tests |
| Token, cookie, password, service-role value in output | reject receipt/log; never print value | secret-scan tests |
| Partial live run or unrelated nonterminal queue rows | stop, clean only run-owned jobs, do not claim success | live runner contract |
| Any other input/state | fail closed, record a secret-free reason, update this table before resuming | adversarial review |

## Fixed decisions

- Event identity is the exact Discord event snowflake.
- Engine names are exactly `claude` or `codex`; no silent fallback.
- Both engine readiness signals and a fresh worker heartbeat are mandatory for
  HR-1.
- Gateway startup order is configuration, distinct identity, minimal RPC
  readiness, process-bound lease, then Discord connect.
- The gateway only enqueues; direct engine execution is forbidden.
- Same-token Hermes/direct concurrency is forbidden. HR-1 uses an isolated bot
  or a controlled single-connection window.
- Never print or persist raw secrets. Receipts contain identifiers and hashes
  only.

## Counter-acceptance and non-scope

- Passing local tests without actual Discord responses is not HR-1 success.
- A fabricated readiness row, replayed old receipt, or run-local queue count is
  not live evidence.
- This worktree does not stop, quarantine, delete, or rotate Hermes.
- It does not cancel unrelated queue work.
- It does not perform HR-2 through HR-7.

## Required verification

```bash
python3 -m pytest -q tests/test_discord_hr1_acceptance.py
python3 -m pytest -q tests/test_discord_direct_gateway.py
python3 -m pytest -q tests/test_direct_receiver.py
python3 -m pytest -q tests/test_engine_select_e2e.py
python3 -m pytest -q tests/test_discord_bot_console_ac1.py
./verify.sh
make strict-exit-gate
```

Relevant recurrence-ledger controls: do not reconfirm an already approved
execution; do not improvise outside this input/exception table; use the
repository runner for live operations and compare dangerous inputs before any
write.
