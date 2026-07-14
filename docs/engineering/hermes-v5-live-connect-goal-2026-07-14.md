# Hermes v5 fleet live connection goal (2026-07-14)

## Mode and risk

- Mode: mixed
- Risk: L3 (live Discord gateway configuration and restart)
- Owner instruction: connect the verified Win PC fleet work to the current Hermes runtime.

## Current state

- `~/.hermes/plugins/valuehire` points to an old Valuehire_v4 worktree.
- `~/.hermes/plugins/valuehire_fleet` is absent.
- `~/.hermes/config.yaml` enables only `valuehire` under `plugins.enabled`.
- Hermes Gateway is running, but `/fleet-run` was previously logged as an unknown command.
- The Win PC implementation is on PR #96, not on `main` yet.

## Goal

Connect the verified PR #96 source to the live Hermes Gateway without copying plugin code or
removing the existing Valuehire plugin. Natural Discord search requests and `/fleet-run` must be
handled by `valuehire_fleet`, with authorization and queue logic delegated to the v5 repository.

## Acceptance criteria

1. PR #96 targeted fleet tests pass locally.
2. `~/.hermes/plugins/valuehire_fleet` is a symlink to the clean `deploy/hermes-live` worktree's
   tracked plugin directory.
3. `valuehire_fleet` is present exactly once in `plugins.enabled`.
4. Hermes Gateway restarts once and logs a successful Discord connection without plugin load error.
5. A local plugin registration smoke check exposes the four fleet commands and natural-message hook.
6. No search job, portal action, ClickUp write, outreach, or candidate message is triggered by validation.

## Evidence before change

- PR #96 GitHub checks: two `verify` jobs passed.
- Local targeted suite: `91 passed in 0.90s`.
- Existing production process: `python -m hermes_cli.main gateway run --replace`.

## Rollback

1. Remove `valuehire_fleet` from `plugins.enabled`.
2. Remove only the `~/.hermes/plugins/valuehire_fleet` symlink.
3. Restart Hermes Gateway once.

## Non-scope

- Do not run a real candidate search during connection validation.
- Do not merge or overwrite the user's dirty local `main` worktree.
- Do not install or modify the Win PC scheduler remotely from this Mac.
- Do not implement the separate ClickUp registration and detailed Discord result-reporting handoff.

## Verification ledger

- Targeted tests: PASS, 91 tests.
- PR #96: MERGED as `f29c0df`; GitHub `verify` passed twice before merge.
- Live plugin link: PASS, points to
  `/Users/kangsangmo/Desktop/Valuehire_v5-hermes-live/ops/hermes-plugin/valuehire_fleet`.
- Queue secret source: PASS, deploy worktree `.env.local` links to the existing v5 `.env.local`;
  values were never copied or printed.
- Hermes config: PASS, `plugins.enabled` contains `valuehire_fleet` exactly once alongside `valuehire`.
- Gateway restart: PASS, one service restart; PID changed from `3352` to `32113` and Discord reconnected
  as `hermes_v5#7466`.
- Plugin discovery: PASS, Hermes reports both `valuehire` and `valuehire_fleet` enabled.
- Local command registration smoke: PASS, four fleet commands plus `pre_gateway_dispatch` registered.
- Discord API readback: PASS, global commands contain `fleet-run`, `fleet-status`, `fleet-resume`, and
  `fleet-cancel`.
- Natural-message smoke: PASS, `aisearch <ClickUp URL> win` rewrites to one `/fleet-run aisearch ...
  winpc` command with an idempotency key; no queue insert was executed.
- Queue readback: PASS, `fleet-status` returned `action=status` and 10 recent jobs after the deploy
  worktree secret link was added.
- Worker availability: BLOCKED for end-to-end search. Heartbeat ages at verification time were about
  `macmini=82h`, `macbook=41m`, `winpc=2h`; recent jobs were `macmini queued=7/cancelled=1` and
  `macbook failed=2`. This Mac is a MacBook Pro, so it must not consume the `macmini` queue.
- Remote Win PC recovery: NOT VERIFIED. Local Tailscale status did not return and was terminated;
  no remote scheduler or portal action was attempted.
- External adversarial review: NOT AVAILABLE. The first Claude run produced no output for over four
  minutes and was terminated; two bounded retries ended at their turn limits without a verdict.
  Empty output was not treated as PASS. Existing PR adversarial evidence plus CI and local tests were
  reproduced, and the missing deploy `.env.local` wiring was found and corrected during local attack.
- Audit-branch full pre-push suite: `1410 passed, 6 failed, 2 skipped, 4 xfailed, 14 subtests passed`.
  The failures are environment-only and unrelated to this documentation change: one existing test
  rejects any checkout path containing `Desktop`, and five tests cannot import Playwright from the
  Hermes Python environment. The targeted fleet suite remains `91 passed`; remote CI is the final
  gate for the audit-only pull request.
