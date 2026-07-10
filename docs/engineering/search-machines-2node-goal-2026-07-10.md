# Search Machines 2-Node Goal — 2026-07-10

## Issue
- https://github.com/sangmokang/Valuehire_v5/issues/81

## Current Evidence
- Existing resident loop: `scripts/valuehire-search-loop.sh`
- Existing healthcheck: `scripts/valuehire-search-healthcheck.sh`
- Existing portal browser launcher: `scripts/portal_browsers.sh`
- Existing harvest queue already records `HarvestItem.machine` in `tools/multi_position_sourcing/harvest_runner.py`.
- Existing queue runner can pause only LinkedIn RPS while Saramin/Jobkorea continue via `rps_in_use` in `tools/multi_position_sourcing/queue_runner.py`.

## Root Cause
Search work has machine fields in some queue/log paths, but there is no strict local machine registry or startup gate. A MacBook Pro worker and Windows PC worker can therefore be started with ambiguous IDs, shared profile paths, or wrong OS assumptions.

## Acceptance Criteria
One machine contract exists and is machine-checkable:
- Only registered `VALUEHIRE_SEARCH_MACHINE_ID` values are accepted.
- `VH-SM-001` is MacBook Pro and `VH-SM-002` is Windows PC1.
- Mac mini remains registered for compatibility as `VH-SM-000`, but the active two-node search pair is `VH-SM-001` + `VH-SM-002`.
- Each active machine has unique channel CDP ports and profile paths.
- Existing search loop and healthcheck fail closed when the machine ID is missing or invalid.
- A cross-platform CLI prints env lines for launchd/Task Scheduler without exposing secrets.

## Contract Shape
- Input: `VALUEHIRE_SEARCH_MACHINE_ID: str` or CLI `--machine-id <str>`.
- Registry: immutable `SearchMachine` records with `machine_id`, label, role, OS, active flag, three integer ports, and three profile strings.
- Output: `validate` prints one non-secret `ok:` line; `env` prints only the ten allowlisted `KEY=value` lines consumed by the launcher.
- State transition: missing, blank, padded, unknown, or inactive ID -> exit 2 before a search cycle/health result; valid active ID -> machine-specific settings -> search cycle or healthcheck.
- Path safety: active ports are globally unique; profiles are OS-correct, canonicalized case-insensitively, and reject mixed syntax, relative aliases, and Windows trailing-dot/space aliases.

## Non-Scope
- No portal login, Chrome control, ClickUp/Supabase/Discord write, or outreach sending.
- No remote installation on the Windows PC.
- No queue persistence migration.

## Verification Commands
- `PYTHONSAFEPATH=1 PYTHONPATH=. python -m pytest tests/test_search_machine_config.py -q`
- `bash -n scripts/valuehire-search-loop.sh scripts/valuehire-search-healthcheck.sh scripts/portal_browsers.sh`
- `PYTHONPATH=. python -m tools.multi_position_sourcing.search_machine validate --machine-id VH-SM-001`
- `PYTHONPATH=. python -m tools.multi_position_sourcing.search_machine validate --machine-id VH-SM-002`
- `VALUEHIRE_SEARCH_MACHINE_ID=VH-SM-002 bash scripts/portal_browsers.sh status`
- `./verify.sh`

## Latest Evidence
- RED: on a safe `git archive HEAD` baseline copy with only `tests/test_search_machine_config.py` added, focused pytest failed collection with `ModuleNotFoundError`; exit 2.
- Focused: `31 passed`; exit 0.
- Shell syntax, both machine validations, and Windows launcher status: exit 0.
- Existing fail-soft daemon regression: `6 passed`; exit 0.
- Full after rebasing onto current `origin/main`: `1177 passed, 4 xfailed, 14 subtests passed`; exit 0.
- Independent adversarial review: PASS after directly rejecting 11 path alias/OS-mixing attacks and all missing/invalid/inactive ID cases.

## Scope Accounting
- Runtime implementation: 4 files (`search_machine.py`, loop, healthcheck, launcher), about 282 added lines.
- Deployment configuration: 2 launchd plists, 8 added lines.
- Test, goal, and verdict are verification artifacts. Runtime implementation remains within the 5-file/300-line limit.

## SOT Checklist
- v5 only.
- Do not weaken captcha/2FA/security gates.
- Do not auto-send.
- Keep LinkedIn RPS isolated from Saramin/Jobkorea progress.
- Speak to owner in short Korean.
