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
2. `~/.hermes/plugins/valuehire_fleet` is a symlink to this worktree's tracked plugin directory.
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
- Live plugin link: pending.
- Hermes config: pending.
- Gateway restart and log check: pending.
- Local command registration smoke: pending.

