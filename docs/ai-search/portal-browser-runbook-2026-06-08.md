# Portal Browser Movement Runbook Draft

Date: 2026-06-08 KST  
Scope: Saramin, Jobkorea, LinkedIn RPS sourcing movement only  
Default mode: dry-run/read-only

Safety update: this runbook is not a session keepalive recipe. Do not use repeated
profile opens such as "one profile every 10 minutes" to keep a portal session
alive. Session maintenance is limited to readiness checks, login-expiry detection,
and manual relogin alerts. Run readiness on demand immediately before protected
portal search, not as a timed heartbeat. LinkedIn profile traversal/click
automation is out of scope.

Read-only implementation basis:

- `../Valuehire_v4/docs/sot/10-ai-search-sourcing.md`: Saramin/Jobkorea candidate search is a target rail but not wired to production save today; RPS is the currently recognized recruiter-profile candidate channel.
- `../Valuehire_v4/tools/position-batch/lib/skill-a-source-runner.mjs`: live portal source delegation requires `OWNER_SIGNOFF_SOURCE=approved`, `ENABLE_SKILL_A_SOURCE_RUNNER=1`, `SKILL_A_SOURCE_NO_LIVE_CONTACT=1`, per-channel commands, and stop flags.
- `../Valuehire_v4/tools/profile-archiver/README.md`: profile capture is manual/person-following and stores local SQLite/screenshots before optional sync.

## Common Flow

1. Confirm login state in the existing Chrome CDP session.
2. Pass confirmed portal session flags into `run_queue_cycle(..., portal_sessions=...)`.
3. Keep Saramin, Jobkorea, and LinkedIn RPS queue items pending when the matching login session is not confirmed.
4. On captcha, 2FA, checkpoint, IP security warning, or abnormal access warning, pause in the visible browser for human intervention and revalidate the same session after the user resolves it.
5. Clear existing portal keywords, chips, and filters before every keyword session.
6. Enter one standard job keyword.
7. Apply channel filters.
8. For dry-run, stop at planned query/session output.
9. For live portal work, open a detailed profile page only after explicit operator approval and source-specific gates.
10. Save detailed profile URL, visible text, screenshot, OCR text, source channel, and captured timestamp through Profile Archiver when available.
11. Dedup by canonical URL before any approved profile open.
12. Reverse-match the saved profile against every position in the role group.

Never click:

- InMail Send
- proposal/send buttons
- message/email/DM buttons
- RPS export write unless `RPS_EXPORT_ALLOW_WRITE` is explicitly present
- ClickUp/Supabase/comment write unless owner signoff gate is present

Live portal sourcing gates:

- `OWNER_SIGNOFF_SOURCE=approved`
- `ENABLE_SKILL_A_SOURCE_RUNNER=1`
- `SKILL_A_SOURCE_NO_LIVE_CONTACT=1`
- channel command configured for the requested channel
- captcha/2FA/checkpoint human-intervention detection enabled
- owner Chrome guard not bypassed

If any gate is absent, keep queue items pending and produce dry-run artifacts only.
If the portal login session is absent or unconfirmed, keep that protected channel pending even when credentials exist.

Portal session preflight command:

```bash
python3 -m tools.multi_position_sourcing.portal_live_check readiness \
  --output artifacts/portal_live_readiness_latest.json

python3 -m tools.multi_position_sourcing.portal_login \
  --channels saramin,jobkorea,linkedin_rps \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --chrome-cdp-endpoint http://127.0.0.1:9222 \
  --output artifacts/portal_session_status_latest.json
```

The readiness command does not contact portals or Discord, but it does perform a safe Supabase REST/RPC access probe so a rejected service-role key fails before live DoD work. It writes safe status/action-hint metadata only, never response bodies or secrets, and exits nonzero when `ready=false`. The login preflight writes channel-level status only. Do not print cookies, passwords, raw storage-state content, or encrypted snapshot bytes. Saramin/Jobkorea use worker-scoped persistent profile directories as the primary session layer; `storage_state` is not passed as a launch option. LinkedIn attaches to the already-open headed Chrome over CDP and, per the SOT invariant (docs/search-access.md), auto-logs in from the secret store like the other portals when no reusable session exists; it is constrained to the single `worker_id=default` profile and that profile is still protected by the OS file lock. A captcha/2FA/checkpoint is never bypassed — LinkedIn auto-login stops and hands off to human resolution on detection. In non-headless mode, captcha/2FA/checkpoint pages wait for human resolution and then resume automatically after the portal session is revalidated. In headless mode, human intervention is disabled and the channel remains not ready.

Guarded live restart/session persistence check:

```bash
python3 -m tools.multi_position_sourcing.portal_live_check restart-smoke \
  --channel saramin \
  --keyword "백엔드 개발자" \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --output artifacts/portal_restart_smoke_saramin.json
```

This command composes two separate guarded worker lifecycles. Each lifecycle runs on-demand liveness, paced search, validated encrypted snapshot capture, reauth event instrumentation, snapshot reinjection, Saramin/Jobkorea keychain auto-relogin fallback, and LinkedIn Discord alert fallback. It requires `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`; it writes safe status JSON only. `passed=true` means both lifecycles reached `status=searched` without a reauth cause. For profile-corruption DoD, stop any active worker for that profile, then run `portal_live_check search` with `--delete-profile-before-start --confirm-delete-profile ~/.valuehire/portal_profiles/<site>/<worker_id> --disable-auto-relogin` after a validated snapshot exists. The deletion path refuses a profile whose `.profile.lock` is already held. Confirm `reauth_cause=profile_corrupt` and `recovery.recovered_by=snapshot_reinject`.

Validated snapshot after login:

```bash
python3 -m tools.multi_position_sourcing.portal_live_check capture-snapshot \
  --channel saramin \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --output artifacts/portal_snapshot_capture_saramin.json
```

Use this after a confirmed login or after a human resolves a checkpoint. It captures the current persistent profile/CDP state only if reinjection into a fresh context still shows the login marker. Output is safe metadata only; raw storage state and encrypted bytes are not printed.

## Saramin

Movement:

1. Use existing Chrome CDP tab.
2. Confirm login.
3. Clear existing search keywords and chips.
4. Put Korean keyword into `.search_default input.search_input` through OS clipboard paste.
5. Press Enter to confirm the chip.
6. Apply career filter as JD years plus buffer.
7. Apply education filter: default `4년제 졸업`.
8. Click left-side search button.
9. Open only operator-approved detail profile pages; never as a keepalive action.
10. Save detail profile through Profile Archiver.

Stop conditions:

- `.search_default input.search_input` and all fallback selectors fail.
- Search button fallback chain fails.
- Profile body is missing and OCR route is unavailable.
- Human intervention timeout after captcha/2FA/checkpoint/security warning.

## Jobkorea

Movement:

1. Use existing Chrome CDP tab.
2. Confirm login.
3. Clear existing search keywords and chips.
4. Paste standard keyword into `#txtKeyword` through OS clipboard.
5. Select the standard term from autocomplete dropdown to confirm chip/filter.
6. Set `#txtCareerStart` and `#txtCareerEnd`.
7. Apply detailed education filter.
8. Run `.btnSearchFilter`.
9. Open only operator-approved detail profile pages; never as a keepalive action.
10. Save detail profile through Profile Archiver.

Stop conditions:

- `#txtKeyword` and fallback chain fail.
- Career fields fail and no equivalent stable selector is available.
- Detailed profile URL cannot be canonicalized.
- Human intervention timeout after captcha/2FA/checkpoint/security warning.

## LinkedIn RPS

Movement:

1. Use LinkedIn RPS saved-search/alert/manual review workflow first. Existing RPS export notes are historical evidence, not approval for automated profile traversal.
2. Only accept URLs containing `/talent/profile/` as candidate evidence.
3. Do not use public `/in/` body as RPS evidence unless separately opened and saved as public-source evidence.
4. Never click InMail Send or equivalent localized send controls.
5. Never run automated profile-open loops, keepalive clicks, or checkpoint bypass.
6. RPS export write requires `RPS_EXPORT_ALLOW_WRITE`; otherwise record dry-run export preview only.

Stop conditions:

- `/talent/profile/` URL is not available.
- Human intervention timeout after RPS security challenge or account warning.
- Export gate is missing for write mode.

## Speed and Resume Rules

- Prefer slow, deterministic movement over rapid automation.
- Add random delay in live implementation; dry-run records the planned queue only.
- Enforce hourly profile-open limits by channel.
- Claim one queue item at a time.
- Persist queue status after each item.
- On failure, isolate the failed item and continue later items unless a global stop condition occurred.
- If Chrome is disconnected, preserve pending items and resume after reconnect.
