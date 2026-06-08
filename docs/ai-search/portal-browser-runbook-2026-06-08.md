# Portal Browser Movement Runbook Draft

Date: 2026-06-08 KST  
Scope: Saramin, Jobkorea, LinkedIn RPS sourcing movement only  
Default mode: dry-run/read-only

Read-only implementation basis:

- `../Valuehire_v4/docs/sot/10-ai-search-sourcing.md`: Saramin/Jobkorea candidate search is a target rail but not wired to production save today; RPS is the currently recognized recruiter-profile candidate channel.
- `../Valuehire_v4/tools/position-batch/lib/skill-a-source-runner.mjs`: live portal source delegation requires `OWNER_SIGNOFF_SOURCE=approved`, `ENABLE_SKILL_A_SOURCE_RUNNER=1`, `SKILL_A_SOURCE_NO_LIVE_CONTACT=1`, per-channel commands, and stop flags.
- `../Valuehire_v4/tools/profile-archiver/README.md`: profile capture is manual/person-following and stores local SQLite/screenshots before optional sync.

## Common Flow

1. Confirm login state in the existing Chrome CDP session.
2. Stop immediately on captcha, 2FA, IP security warning, abnormal access warning, or owner activity.
3. Clear existing portal keywords, chips, and filters before every keyword session.
4. Enter one standard job keyword.
5. Apply channel filters.
6. Scan result list slowly.
7. Open detailed profile page.
8. Save detailed profile URL, visible text, screenshot, OCR text, source channel, and captured timestamp through Profile Archiver when available.
9. Dedup by canonical URL before opening again.
10. Reverse-match the saved profile against every position in the role group.

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
- captcha/2FA stop detection enabled
- owner Chrome guard not bypassed

If any gate is absent, keep queue items pending and produce dry-run artifacts only.

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
9. Open only detail profile pages.
10. Save detail profile through Profile Archiver.

Stop conditions:

- `.search_default input.search_input` and all fallback selectors fail.
- Search button fallback chain fails.
- Profile body is missing and OCR route is unavailable.

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
9. Open only detail profile pages.
10. Save detail profile through Profile Archiver.

Stop conditions:

- `#txtKeyword` and fallback chain fail.
- Career fields fail and no equivalent stable selector is available.
- Detailed profile URL cannot be canonicalized.

## LinkedIn RPS

Movement:

1. Reuse the existing safe path when present: `tools/ai-search-rps-safe-run` then `tools/ai-search-rps-export`. In the inspected v4 root these exact files were not found; the RPS goal doc and `.omc` export artifacts remain the current evidence.
2. Only accept URLs containing `/talent/profile/` as candidate evidence.
3. Do not use public `/in/` body as RPS evidence unless separately opened and saved as public-source evidence.
4. Never click InMail Send or equivalent localized send controls.
5. RPS export write requires `RPS_EXPORT_ALLOW_WRITE`; otherwise record dry-run export preview only.

Stop conditions:

- `/talent/profile/` URL is not available.
- RPS security challenge or account warning appears.
- Export gate is missing for write mode.

## Speed and Resume Rules

- Prefer slow, deterministic movement over rapid automation.
- Add random delay in live implementation; dry-run records the planned queue only.
- Enforce hourly profile-open limits by channel.
- Claim one queue item at a time.
- Persist queue status after each item.
- On failure, isolate the failed item and continue later items unless a global stop condition occurred.
- If Chrome is disconnected, preserve pending items and resume after reconnect.
