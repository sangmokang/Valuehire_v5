# Valuehire Search Ops Machine / Session / Discord Runbook

Date: 2026-06-08 KST  
Scope: Saramin, Jobkorea, LinkedIn, Mac mini always-on runner, Discord remote invocation  
Default posture: API/alert/manual approval first; no scraping, no bot-detection bypass, no automated LinkedIn profile clicking

## 1. Non-Negotiable Boundary

The phrase "work while the Mac mini sleeps" is technically wrong. The operating target is:

> Prevent system sleep and keep the background runner alive. Display sleep is allowed.

The phrase "click one profile every 10 minutes to keep the session alive" is rejected.

Risk assessment:
- It creates artificial profile views that are unrelated to recruiting judgment.
- It can look like automated browsing or scraping behavior.
- LinkedIn explicitly restricts crawlers, bots, automated methods, profile/data scraping, and unusually high profile viewing.
- It does not prove a session is healthy; it only creates noisy account activity.

Allowed replacement:
- Keep a user-owned browser profile or Playwright storage state.
- Check only session readiness, login-expiry signals, checkpoint/security pages, and queue health.
- If login is expired, pause the protected source and notify the operator for manual relogin.
- Do not auto-click candidate profiles, InMail, proposals, exports, or send buttons.

## 2. Official Source Check

Sources checked on 2026-06-08:

| Platform | Official evidence | Operating implication |
| --- | --- | --- |
| Saramin | Saramin Job Search API is `GET https://oapi.saramin.co.kr/job-search`, requires `access-key`, supports JSON/XML, and documents 500 calls/day. | Prefer approved API for job-posting search. Respect access-key scope and daily limit. |
| Saramin | Saramin API caution page says users receive only limited rights within the provided 채용정보 scope and must not share access keys or violate restrictions. | Do not treat Saramin API as a resume/candidate scraping license. |
| Jobkorea | Jobkorea API page describes approved 채용정보 API, max 500 postings, 2-hour update cycle, application/approval, registered IP, and issued unique call link. It prioritizes public institutions/schools and says general companies are reviewed. | Use Jobkorea API only after approval. Until then, use saved search/notification/manual review. |
| LinkedIn | LinkedIn Help says third-party crawlers/bots/extensions that scrape, modify, or automate LinkedIn website activity are not permitted. | Do not implement automated LinkedIn profile traversal, keepalive clicks, scraping, connection/message automation, or bypass logic. |
| LinkedIn Recruiter | LinkedIn Recruiter Help says unusually large profile viewing can trigger scraping-limit notifications and account restriction/suspension/termination. | Session keepalive must not open profiles. Use official UI alerts and manual review. |
| Discord | Discord application commands are slash commands of type `CHAT_INPUT`; commands can be scoped globally or per guild and configured for `GUILD` and `BOT_DM` contexts. | Use slash commands as the primary server-channel invocation surface. |
| Discord | Discord's migration guide says Message Content is privileged for verified apps, while apps can still access content in DMs and messages directly mentioning the bot. | Slash commands need no Message Content intent. Direct bot mention can be a fallback. Generic prefix/free-text channel commands are disabled by default. |

Reference URLs:
- https://oapi.saramin.co.kr/guide/info
- https://oapi.saramin.co.kr/caution
- https://oapi.saramin.co.kr/guide/job-search
- https://www.jobkorea.co.kr/service/api
- https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions
- https://www.linkedin.com/help/recruiter/answer/a1393432
- https://docs.discord.com/developers/interactions/application-commands
- https://docs.discord.com/developers/tutorials/upgrading-to-application-commands
- https://support-dev.discord.com/hc/en-us/articles/6207308062871-What-are-Privileged-Intents

## 3. Session Maintenance Strategy

Protected sources:
- `saramin`
- `jobkorea`
- `linkedin_rps`

Unprotected source:
- `public_web`

Implementation in this repo:
- `tools/multi_position_sourcing/portal_worker.py` owns worker-scoped persistent profiles, OS profile locks, and LinkedIn headed Chrome CDP attach.
- `tools/multi_position_sourcing/portal_snapshot.py` owns encrypted, validated snapshot capture and manual reinjection through `add_cookies` plus origin localStorage scripts.
- `tools/multi_position_sourcing/portal_ops.py` owns reauth event instrumentation, Discord reauth alerts, and pacing policies.
- `tools/multi_position_sourcing/portal_autologin.py` owns keychain-backed Saramin/Jobkorea relogin after snapshot recovery fails. LinkedIn is hard-blocked from automatic login.
- `tools/multi_position_sourcing/portal_runtime.py` composes pacing, one on-demand search, validated snapshot capture, reauth recovery, and one idempotent retry.
- `tools/multi_position_sourcing/portal_live_check.py` is the live validation entry point. It writes safe JSON only; it does not print cookies, storage state, encrypted bytes, service-role keys, portal passwords, or webhook URLs.
- `tools/multi_position_sourcing/portal_login.py` opens a visible browser preflight, checks whether the portal session is ready, waits for manual login/checkpoint resolution when needed, and writes status JSON.
- `tools/multi_position_sourcing/queue_runner.py` keeps protected queue items pending unless the matching session flag is ready.

Preflight command:

```bash
python3 -m tools.multi_position_sourcing.portal_login \
  --channels saramin,jobkorea,linkedin_rps \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --chrome-cdp-endpoint http://127.0.0.1:9222 \
  --output artifacts/portal_session_status_latest.json
```

Current safety rule:
- The preflight does not enter credentials.
- The preflight does not submit login forms.
- The preflight does not click LinkedIn profiles.
- Captcha, 2FA, checkpoint, IP security, or abnormal-access prompts are manual-only.
- Headless mode disables human intervention and leaves the channel not ready.

Baseline guarded live search command, not the restart-persistence DoD:

```bash
python3 -m tools.multi_position_sourcing.portal_live_check search \
  --channel saramin \
  --keyword "백엔드 개발자" \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --searches-today 0 \
  --output artifacts/portal_live_check_saramin.json
```

Use this for targeted debugging or profile-loss recovery artifacts. The restart-persistence DoD uses `restart-smoke` artifacts for all protected channels, as shown in the operator cheatsheet.

Required environment:

```bash
SUPABASE_URL=<project_url>
SUPABASE_SERVICE_ROLE_KEY=<server_only_service_role_key>
DISCORD_REAUTH_WEBHOOK_URL=<optional_linkedin_reauth_webhook>
```

Safe readiness and access checks, no portal/Discord calls and no secret output:

```bash
python3 -m tools.multi_position_sourcing.portal_live_check init-session-key \
  --output artifacts/portal_session_key_init_latest.json

python3 -m tools.multi_position_sourcing.portal_live_check init-portal-credentials \
  --channels saramin,jobkorea \
  --output artifacts/portal_credentials_init_latest.json

python3 -m tools.multi_position_sourcing.portal_live_check init-discord-webhook \
  --output artifacts/discord_webhook_init_latest.json

python3 -m tools.multi_position_sourcing.portal_live_check readiness \
  --output artifacts/portal_live_readiness_latest.json

python3 -m tools.multi_position_sourcing.portal_live_check supabase-access-check \
  --output artifacts/portal_supabase_access_latest.json
```

`init-session-key` creates or verifies the local Mac Keychain session encryption key and prints only safe status metadata. `init-portal-credentials` imports Saramin/Jobkorea env credentials into Mac Keychain and prints only key names plus ready/missing status; LinkedIn credentials are never imported. `init-discord-webhook` imports `DISCORD_REAUTH_WEBHOOK_URL` / `VALUEHIRE_DISCORD_REAUTH_WEBHOOK_URL` into Mac Keychain and prints only status metadata. The readiness artifact reports only pass/missing checks for env vars or Keychain fallback, local Playwright availability, Mac Keychain session encryption key, Saramin/Jobkorea Keychain credential presence, the LinkedIn no-auto-login policy, and safe Supabase access. It does not contact portals or Discord, but it does call Supabase REST/RPC probes and exits nonzero when `ready=false`. `supabase-access-check` probes `reauth_events` REST read plus `latest_validated_session_snapshot`, `validated_session_snapshots`, and `reauth_weekly_counts` RPC access, recording only HTTP status, error type, safe HTTP error hints, and safe key diagnostics such as JWT role/expiry/ref-match status. These commands never print env values, credentials, cookies, service-role keys, Supabase URLs, response bodies, or webhook URLs.

The live search uses Mac Keychain account `valuehire.session_state/session_state_v2` for the snapshot encryption key. Saramin/Jobkorea automatic relogin, used only after snapshot recovery fails, reads base64-encoded keychain secrets from service `valuehire.portal_credentials` accounts:

```text
saramin:username
saramin:password
jobkorea:username
jobkorea:password
```

Validated snapshot capture after login:

```bash
python3 -m tools.multi_position_sourcing.portal_live_check capture-snapshot \
  --channel saramin \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --output artifacts/portal_snapshot_capture_saramin.json
```

Run this immediately after `portal_login` reports `ready=true`, or after a human completes a login/checkpoint in the visible browser. The command reads the current persistent profile/CDP session, validates the captured state by reinjecting it into a fresh headless context and checking the portal login marker, then writes only safe metadata. The app rejects any snapshot payload that is not in the `VHSS1` encrypted envelope before calling Supabase, and the DB schema enforces the same envelope constraint. Restore reads current plus last-known-good candidates through `validated_session_snapshots` and falls back to LKG if current cannot be decrypted, decoded, or reinjected. It never writes raw `storage_state`, cookies, localStorage, encrypted bytes, or key material to the output artifact.

Profile-loss simulation, for DoD only, requires an exact path confirmation:

```bash
python3 -m tools.multi_position_sourcing.portal_live_check search \
  --channel saramin \
  --keyword "백엔드 개발자" \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --delete-profile-before-start \
  --confirm-delete-profile ~/.valuehire/portal_profiles/saramin/default \
  --disable-auto-relogin \
  --output artifacts/portal_live_check_saramin_profile_loss.json
```

Use `--disable-auto-relogin` for this proof when the claim is "validated snapshot reinjection alone recovered the damaged profile." Stop any active worker for the target profile first; the deletion path refuses to remove a profile whose `.profile.lock` is already held. If the result is `searched`, `reauth_cause=profile_corrupt`, `retried_after_recovery=true`, and `recovery.recovered_by=snapshot_reinject`, the profile-corruption recovery claim is proved for that channel/worker. If the result falls back to `auto_relogin`, that proves the policy path, not the snapshot-only DoD.

Discord alert proof:

```bash
python3 -m tools.multi_position_sourcing.portal_live_check discord-alert-test \
  --record-reauth-event \
  --output artifacts/portal_discord_alert_test_latest.json
```

This sends a synthetic LinkedIn `forced_logout` reauth alert through `DISCORD_REAUTH_WEBHOOK_URL`. With `--record-reauth-event`, it also records a `linkedin_rps/default/forced_logout/human` row in Supabase `reauth_events`, so the weekly-count artifact proves LinkedIn human reauth instrumentation. The output records only delivery/recording status and non-secret event metadata.

Weekly reauth observability:

```bash
python3 -m tools.multi_position_sourcing.portal_live_check reauth-weekly-counts \
  --week-start 2026-06-08T00:00:00+00:00 \
  --output artifacts/portal_reauth_weekly_counts_latest.json

python3 -m tools.multi_position_sourcing.portal_live_check reauth-weekly-trend \
  --latest-week-start 2026-06-08T00:00:00+00:00 \
  --weeks 4 \
  --output artifacts/portal_reauth_weekly_trend_latest.json
```

These commands read Supabase `reauth_events` using the service-role key and write aggregate rows only: `site`, `worker_id`, `cause`, `recovered_by`, and `count`. The trend artifact also records latest/previous totals, week-over-week delta, zero-event weeks, and whether the latest week is zero, without raw session state or secret values.

Recommended cadence:
- Session readiness check: on demand immediately before a protected portal search; do not run a timed heartbeat.
- Saramin API search: 30-60 minutes depending on key quota and query count.
- Jobkorea API search: 2 hours or slower, matching its documented update cycle, after approval.
- LinkedIn saved-search/alert review: daily or operator-triggered; no automated profile traversal.

## 4. Continuous Search Plan

| Platform | Allowed | Caution | Do Not |
| --- | --- | --- | --- |
| Saramin | Approved Job Search API, saved searches, manual Talent Pool review, visible-browser login status check, deduped result storage. | 500 API calls/day, access-key secrecy, API scope is 채용정보 not unrestricted candidate harvesting. | Share access keys, scrape protected pages, bypass captcha/2FA, auto-send proposals. |
| Jobkorea | Approved 채용정보 API, saved searches/alerts, manual candidate review, visible-browser login status check. | API approval may be denied for ordinary companies; update cycle is 2 hours; use registered IP/call link only. | Use unapproved API endpoints, scrape candidate data, bypass security tooling, automate proposal/contact actions. |
| LinkedIn | Official UI, Recruiter saved searches/alerts, manual review, operator-approved URL capture, public URL only as URL evidence when body is not opened. | Profile-view limits and account restriction risk; automation policies can change. | 10-minute profile clicks, automated profile traversal, scraping, InMail automation, checkpoint bypass, fake activity. |
| Public web | Search-engine handoff, public portfolio/GitHub/Scholar/company pages, contact only when explicitly public for work/recruiting. | Respect robots/terms, collect minimal data, record evidence URL and timestamp. | Bulk scraping, private-contact collection, do-not-contact violation. |

Queue and data rules:
- Queue item key: `group_id + channel + standard_keyword`.
- Dedup key: canonical profile URL where allowed, plus source and capture timestamp.
- TTL: 7 days for search-list duplicates, 30 days for saved detailed profiles unless the operator asks to refresh.
- Rate limit: never consume more than 70% of daily API quota in routine cycles.
- Retry: exponential backoff after network/API failures; immediate stop on captcha/security/account warnings.
- Storage: write dry-run artifacts under `artifacts/multi_position_sourcing/`; do not write ClickUp/Supabase without owner gates.
- Account protection: if any protected portal reports checkpoint/security warning, stop that source and send `/relogin-needed` status.

Dry-run command:

```bash
python3 -m tools.multi_position_sourcing.dry_run \
  --output artifacts/multi_position_sourcing/dry-run-latest.json
```

## 5. Mac Mini Always-On Operation

### macOS power setup

Separate display sleep from system sleep:

```bash
# AC-powered Mac mini: prevent system sleep, allow display sleep after 10 minutes.
sudo pmset -c sleep 0 displaysleep 10 disksleep 10 womp 1 tcpkeepalive 1

# Inspect current settings.
pmset -g custom
pmset -g assertions
```

Manual foreground run with sleep prevention:

```bash
cd /Users/kangsangmo/Desktop/Valuehire_v5
caffeinate -dimsu scripts/valuehire-search-loop.sh
```

### launchd install

The repo includes:
- `scripts/valuehire-search-loop.sh`
- `scripts/valuehire-search-healthcheck.sh`
- `scripts/launchd/com.valuehire.search-runner.plist`

Install:

```bash
cd /Users/kangsangmo/Desktop/Valuehire_v5
mkdir -p logs ~/Library/LaunchAgents
cp scripts/launchd/com.valuehire.search-runner.plist ~/Library/LaunchAgents/
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.valuehire.search-runner.plist
launchctl kickstart -k "gui/$(id -u)/com.valuehire.search-runner"
```

Check:

```bash
launchctl print "gui/$(id -u)/com.valuehire.search-runner"
tail -f logs/valuehire-search-runner.out.log
tail -f logs/valuehire-search-runner.err.log
scripts/valuehire-search-healthcheck.sh
```

Stop:

```bash
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.valuehire.search-runner.plist
```

Reboot behavior:
- `RunAtLoad` starts the runner after login.
- `KeepAlive` restarts it after crashes.
- `caffeinate -dimsu` keeps the system awake while the runner is alive.

Remote access:
- Prefer Tailscale/ZeroTier/VPN plus macOS Screen Sharing or SSH.
- Do not expose SSH, VNC, or a Discord control endpoint directly to the public internet.
- Keep FileVault recovery and an admin break-glass account documented outside the repo.

Failure alert path:
- Launchd logs go to `logs/valuehire-search-runner.*.log`.
- Healthcheck fails when the loop process is down or the dry-run artifact is stale.
- Wire healthcheck failure to Discord by the existing Hermes Gateway or a separate notifier; do not put webhook URLs in git.

## 6. Discord Server Channel Invocation

Implemented files:
- `tools/multi_position_sourcing/discord_routing.py`
- `tools/multi_position_sourcing/register_discord_commands.py`
- `docs/search-access.md`

Supported commands:
- `/search-status`
- `/run-search source:saramin keyword:"backend"`
- `/session-status`
- `/relogin-needed`
- `/register-position url:https://www.wanted.co.kr/wd/363433` if the existing position-registration lane is enabled

Environment:

```bash
DISCORD_BOT_TOKEN=<secret>
DISCORD_CLIENT_ID=1512101118543397056
DISCORD_GUILD_ID=<guild_id_for_fast_guild_command_registration>
DISCORD_ALLOWED_CHANNEL_IDS=<channel_id_1>,<channel_id_2>
DISCORD_ALLOWED_ROLE_IDS=<role_id_1>,<role_id_2>
DISCORD_ALLOW_DM_COMMANDS=1
```

Register slash commands dry-run:

```bash
python3 -m tools.multi_position_sourcing.register_discord_commands \
  --application-id "$DISCORD_CLIENT_ID" \
  --guild-id "$DISCORD_GUILD_ID"
```

Apply registration:

```bash
python3 -m tools.multi_position_sourcing.register_discord_commands \
  --application-id "$DISCORD_CLIENT_ID" \
  --guild-id "$DISCORD_GUILD_ID" \
  --apply
```

Routing rules:
- DM: allowed only for users in `docs/search-access.md` Discord Contacts.
- Server channel: channel ID must be allowlisted.
- Server channel identity: user must be in Discord Contacts or hold an allowlisted role.
- Slash command response: ephemeral.
- Bot mention response: public channel gets only a short acknowledgement; details move to DM.
- Sensitive values are never posted in a channel.

Privileged intents:
- Slash commands do not require Message Content intent.
- Direct bot mentions are the only message fallback in the safe default.
- Generic prefix commands such as `!run-search ...` in server channels are disabled because they would require broader Message Content access.
- Guild Members intent is not required if the interaction payload or bot runtime provides member role IDs. If the existing runtime cannot see role IDs, either use Discord command permissions or request/enable the relevant guild-member capability in the Developer Portal.

## 7. Operator Command Cheatsheet

```bash
# Run tests.
python3 -m unittest tests/test_multi_position_sourcing.py -v

# Generate current dry-run artifact.
python3 -m tools.multi_position_sourcing.dry_run \
  --output artifacts/multi_position_sourcing/dry-run-latest.json

# Check protected portal sessions in a visible browser.
python3 -m tools.multi_position_sourcing.portal_login \
  --channels saramin,jobkorea,linkedin_rps \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --chrome-cdp-endpoint http://127.0.0.1:9222 \
  --output artifacts/portal_session_status_latest.json

# Check local live DoD prerequisites without contacting portals or printing secrets.
python3 -m tools.multi_position_sourcing.portal_live_check init-session-key \
  --output artifacts/portal_session_key_init_latest.json
python3 -m tools.multi_position_sourcing.portal_live_check init-portal-credentials \
  --channels saramin,jobkorea \
  --output artifacts/portal_credentials_init_latest.json
python3 -m tools.multi_position_sourcing.portal_live_check init-discord-webhook \
  --output artifacts/discord_webhook_init_latest.json
python3 -m tools.multi_position_sourcing.portal_live_check readiness \
  --output artifacts/portal_live_readiness_latest.json
python3 -m tools.multi_position_sourcing.portal_live_check supabase-access-check \
  --output artifacts/portal_supabase_access_latest.json

# Prove restart persistence with two clean worker lifecycles per protected site.
python3 -m tools.multi_position_sourcing.portal_live_check restart-smoke \
  --channel saramin \
  --keyword "백엔드 개발자" \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --output artifacts/portal_restart_smoke_saramin.json
python3 -m tools.multi_position_sourcing.portal_live_check restart-smoke \
  --channel jobkorea \
  --keyword "백엔드 개발자" \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --output artifacts/portal_restart_smoke_jobkorea.json
python3 -m tools.multi_position_sourcing.portal_live_check restart-smoke \
  --channel linkedin_rps \
  --keyword "백엔드 개발자" \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --chrome-cdp-endpoint http://127.0.0.1:9222 \
  --output artifacts/portal_restart_smoke_linkedin_rps.json

# Capture a validated snapshot after a confirmed login session.
python3 -m tools.multi_position_sourcing.portal_live_check capture-snapshot \
  --channel saramin \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --output artifacts/portal_snapshot_capture_saramin.json

# Prove Discord reauth alert delivery.
python3 -m tools.multi_position_sourcing.portal_live_check discord-alert-test \
  --record-reauth-event \
  --output artifacts/portal_discord_alert_test_latest.json

# Observe weekly reauth counts.
python3 -m tools.multi_position_sourcing.portal_live_check reauth-weekly-counts \
  --week-start 2026-06-08T00:00:00+00:00 \
  --output artifacts/portal_reauth_weekly_counts_latest.json

# Observe whether weekly reauth counts are converging toward zero.
python3 -m tools.multi_position_sourcing.portal_live_check reauth-weekly-trend \
  --latest-week-start 2026-06-08T00:00:00+00:00 \
  --weeks 4 \
  --output artifacts/portal_reauth_weekly_trend_latest.json

# Read safe encrypted snapshot metadata from Supabase; no encrypted bytes or storage state are printed.
python3 -m tools.multi_position_sourcing.portal_live_check snapshot-metadata \
  --channel saramin \
  --worker-id default \
  --output artifacts/portal_snapshot_metadata_saramin.json
python3 -m tools.multi_position_sourcing.portal_live_check snapshot-metadata \
  --channel jobkorea \
  --worker-id default \
  --output artifacts/portal_snapshot_metadata_jobkorea.json

# Audit safe live artifacts against the session-persistence DoD.
python3 -m tools.multi_position_sourcing.portal_dod_audit \
  --session-status artifacts/portal_session_status_latest.json \
  --restart-smoke-artifact artifacts/portal_restart_smoke_saramin.json \
  --restart-smoke-artifact artifacts/portal_restart_smoke_jobkorea.json \
  --restart-smoke-artifact artifacts/portal_restart_smoke_linkedin_rps.json \
  --profile-recovery-artifact artifacts/portal_live_check_saramin_profile_loss.json \
  --profile-recovery-artifact artifacts/portal_live_check_jobkorea_profile_loss.json \
  --snapshot-metadata-artifact artifacts/portal_snapshot_metadata_saramin.json \
  --snapshot-metadata-artifact artifacts/portal_snapshot_metadata_jobkorea.json \
  --discord-alert artifacts/portal_discord_alert_test_latest.json \
  --weekly-counts artifacts/portal_reauth_weekly_counts_latest.json \
  --weekly-trend artifacts/portal_reauth_weekly_trend_latest.json \
  --secret-scan-path artifacts \
  --output artifacts/portal_session_dod_audit_latest.json

# Show slash command payload without calling Discord.
python3 -m tools.multi_position_sourcing.register_discord_commands \
  --application-id "$DISCORD_CLIENT_ID" \
  --guild-id "$DISCORD_GUILD_ID"

# Mac mini service health.
scripts/valuehire-search-healthcheck.sh
```

## 8. Remaining Risks

- Saramin API and Jobkorea API cover job postings, not unrestricted candidate/profile harvesting.
- Jobkorea API access can be denied after internal review.
- LinkedIn policies and enforcement can change; keep automation limited to manual UI/saved-alert workflows.
- The current v5 checkout is a dry-run/control layer, not the full production Hermes Gateway.
- Discord command registration is implemented, but the existing Hermes runtime still needs to call `discord_routing.py` decisions before executing queue operations.
