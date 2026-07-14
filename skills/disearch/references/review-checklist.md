# Disearch review checklist

Use this reference for detailed Valuehire Discord-search audits. Re-check every item against the current checkout; this file records review targets, not permanent facts.

## Contents

1. Expected process map
2. Control-plane distinctions
3. Security review
4. Functional review
5. Test matrix
6. Refactor decision record

## 1. Expected process map

The intended Fleet path is usually:

1. Discord delivers a message/event to Hermes.
2. `ops/hermes-plugin/valuehire_fleet/__init__.py` captures the Discord identity and may rewrite a narrow natural-language request to `/fleet-run`.
3. The registered command handler calls `hermes_fleet_bridge.dispatch_hermes_fleet_command()`.
4. `parse_hermes_fleet_args()` validates command fields, defaults, aliases, URLs, channels, and idempotency input.
5. `dispatch_fleet_command()` reuses `route_discord_invocation()` for authorization and enforces owner-only resume/cancel.
6. `new_job_payload()` validates the search-only job and `JobQueueClient.enqueue()` writes it to Supabase.
7. The machine worker claims the job, builds a bounded prompt, and runs the approved search skill.
8. Captcha/2FA produces `paused_for_human`; `/fleet-resume` returns it to the queue.
9. Successful AI Search must emit a completion receipt before the worker marks the job done.
10. Status and results are reported through Discord/OPS notification paths.

Confirm each arrow. A function existing on both sides does not prove that the call is wired or deployed.

## 2. Control-plane distinctions

Keep these paths separate:

- Hermes Fleet plugin: likely current in-repo receiver for `/fleet-run`, `/fleet-status`, `/fleet-resume`, and `/fleet-cancel`.
- Native Discord application-command payloads: `discord_slash_command_payloads()` and `register_discord_commands.py` define/register schemas. They are not a receiver by themselves.
- Legacy free-form DM bridge: `scripts/discord_command_listener.py` polls one DM and passes owner text directly to `claude -p`; it bypasses the Fleet envelope and should be treated as legacy until runtime evidence says otherwise.
- Dry-run and test paths: imports from `dry_run.py` or tests do not count as production consumption.

Recommended human command for a new position search:

```text
/fleet-run https://app.clickup.com/t/<position-id>
```

Use explicit options only when needed:

```text
/fleet-run aisearch https://app.clickup.com/t/<position-id> winpc
/fleet-status
/fleet-resume job:<id>
/fleet-cancel job:<id>
```

Do not recommend `/run-search` or `/aisearch` as live commands until their actual receiver and deployment are proven. A rewrite compatibility path is not the same as a registered command.

## 3. Security review

Verify these hypotheses:

| Review target | Evidence to seek | Desired property |
|---|---|---|
| Transport context | Whether the bridge preserves DM/guild, channel ID, guild ID, and role IDs | Server commands cannot be reclassified as DM |
| Identity binding | Whether hook identity belongs to the exact event handled | No stale/cross-event identity |
| Channel visibility | Where command JSON, status, errors, and candidate data are posted | Public ack is minimal; details go to authorized DM |
| Error handling | Raw exception strings returned to Discord | Secrets and internal paths are redacted |
| Agent permissions | Exact `claude -p` permission/tool boundary | Discord input cannot become unrestricted workstation control |
| URL trust | Accepted schemes, hosts, loopback/private IPs, redirects | Only required position/search origins are accepted |
| External content | Prompt-injection handling for JD/search pages | Remote content cannot override system/SOT rules |
| Idempotency | Event ID propagation and duplicate-conflict behavior | Replays return the same job, not a duplicate/error |
| Process locking | Atomic lock acquisition and PID-liveness checks | Cross-platform, race-safe, no process signalling |
| Notification isolation | Whether fake queue tests still send notifications | Notifier is injected and off in tests |

Severity guide:

- Critical: unauthenticated or cross-tenant code execution/secret disclosure.
- High: authorization boundary bypass, unrestricted remote workstation action, repeated external actions, or silent permanent queue deadlock.
- Medium: sensitive error/public response leakage, requester/result routing failure, recoverable duplicate/stall, or platform-specific service failure.
- Low: documentation drift, poor diagnostics, confusing aliases, or maintainability risk without current security impact.

## 4. Functional review

Check:

- Which command is actually registered in the live Hermes configuration.
- Whether one bot token has exactly one active gateway.
- Whether `/fleet-run <url>` produces one response and one queue job.
- Whether a default skill/machine/channel is consistent across code, schema, docs, and UI help.
- Whether Discord `aisearch` covers all SOT-required channels, including LinkedIn RPS, and validates completion evidence for each one.
- Whether queued and running stalls are alerted and whether paused account locks prevent re-entry.
- Whether `fleet-status` reports heartbeats for every machine.
- Whether completion reaches the original requester, not only a fixed operations channel.
- Whether a long result is split or summarized without losing terminal reason/artifact paths.
- Whether legacy listeners can consume the same intent and cause double execution.
- Whether Windows launch, encoding, PID locks, paths, and scheduled-task behavior are tested separately from macOS.

Known architectural follow-ups in SOT30 should remain visible until code and migrations prove closure: running-job lease recovery, paused-account lock retention, and live gateway single-instance enforcement.

## 5. Test matrix

Minimum read-only suite:

```powershell
python -m pytest -q `
  tests/test_hermes_fleet_bridge.py `
  tests/test_hermes_plugin_registration.py `
  tests/test_fleet_dispatch.py `
  tests/test_job_queue.py `
  tests/test_fleet_worker.py `
  tests/test_fleet_heartbeat.py `
  tests/test_fleet_reliability.py
```

Add focused adversarial tests for:

- authorized contact in an unallowlisted guild channel;
- missing/stale sender identity;
- same event delivered twice;
- native command retry after a successful enqueue;
- raw exception containing a token-like value;
- loopback, link-local, private-IP, userinfo, redirect, and unsupported-host URLs;
- notifier accidentally invoking the network under a fake queue;
- public channel response containing job params or candidate details;
- worker crash after side effects but before queue release;
- Windows PID liveness and simultaneous lock acquisition.

Live acceptance requires approval and evidence from the deployed gateway, queue, worker, and Discord response. Unit tests alone cannot satisfy it.

## 6. Refactor decision record

For each proposed refactor record:

- duplicated responsibility being removed;
- current callers and compatibility impact;
- new single source of truth;
- failing regression test;
- migration/rollback plan;
- external write or restart required;
- proof that authorization, no-outreach, login-preservation, and human-intervention gates remain unchanged.
