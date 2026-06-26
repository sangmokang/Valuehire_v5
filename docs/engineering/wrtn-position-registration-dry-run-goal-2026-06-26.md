# Wrtn Position Registration Dry Run Goal 2026-06-26

## Current Evidence

- Root SOT requires Korean, short reporting and blocks automatic send: `CLAUDE.md:29`, `CLAUDE.md:31`.
- Harness requires prior instruction recovery, focused checks, and evidence before completion: `docs/harness.md:16`, `docs/harness.md:60`.
- Position registration skill requires reading repo SOT and existing implementation before browser work or external writes: `skills/position-registration/SKILL.md:8`, `skills/position-registration/SKILL.md:13`.
- Position registration skill states Saramin, Jobkorea, LinkedIn/RPS, and Gmail posting/sending are out of default scope until explicit owner approval: `skills/position-registration/SKILL.md:36`, `skills/position-registration/SKILL.md:59`.
- AI Search SOT blocks automatic proposal, mail, and InMail send: `docs/sot/25-ai-search-execution-process.json:23`, `docs/sot/25-ai-search-execution-process.json:190`.
- Portal/JD template SOT requires LinkedIn/RPS template body <= 1,899 chars, no raw `{{...}}`, no HTML comments, save/update only through the template lane, and never Send: `docs/sot/25-ai-search-execution-process.json:165`, `docs/sot/22-talent-search-filters.json:337`.
- Channel DOM/input SOT requires fresh DOM evidence before action and separates Saramin, Jobkorea, LinkedIn URLs/input methods: `docs/sot/22-talent-search-filters.md:12`, `docs/sot/22-talent-search-filters.md:34`.
- Wrtn/GreetingHR intake fallback says to parse `#__NEXT_DATA__`, read `openingsInfo` fields, strip `detail` HTML, and keep source URL provenance: `skills/search/references/greetinghr-career-page-intake.md:7`.
- Existing registration pipeline is ClickUp intake only and reports `external_posting_sent=False`: `tools/multi_position_sourcing/position_registration.py:191`, `tools/multi_position_sourcing/position_registration.py:207`.

## Root Cause

The user requested live portal registration and Gmail sending for all Wrtn positions, but the current SOT splits this into two lanes:

- ClickUp/FY26 position intake (`position-registration`) with dedupe and dry-run support.
- Portal/RPS/Gmail delivery, which is L3 external write/send and blocked until explicit owner approval.

Therefore the safe executable scope is a dry-run package: recover the live public Wrtn list, compare against SOT24/local evidence, prepare portal-fitting JD/template material, and report exactly what is blocked.

## Acceptance Criteria

- Read and report SOT paths before action.
- Recover current public Wrtn career list from `https://career.wrtn.io/ko/career`.
- Compare current opening IDs against local SOT24/local repo evidence and mark already registered vs unregistered dry-run candidates.
- For unregistered public openings, recover detail/JD from public GreetingHR/Next data where available.
- Build a local/dry-run report schema:
  - `opening_id`
  - `title`
  - `source_url`
  - `field`
  - `employment`
  - `registration_state`
  - `jd_chars`
  - `portal_package_status`
  - `blocked_external_actions`
- Verify portal constraints before any package claim:
  - Saramin/Jobkorea/Gmail text sections must be local draft only.
  - LinkedIn/RPS body must be <= 1,899 chars and contain no raw `{{...}}` or HTML comments.
  - No Send/register/write action is executed.

## Non-Scope

- No Saramin/Jobkorea/LinkedIn live posting.
- No Gmail sending or Gmail draft creation.
- No ClickUp task/comment write.
- No captcha, login-cap, or multi-session bypass.
- No new portal runner or ad-hoc browser automation.

## Verification Commands

- `python3 -m unittest tests.test_posting_extractor tests.test_posting_recognizer tests.test_position_dedup tests.test_position_registration`
- `.venv-playwright/bin/python -m pytest tests/test_skill_sot_preflight_gate.py -q`
- `make verify` only if the focused checks and current repo state make a full run appropriate.
- `node <inline dry-run extractor>` for Wrtn public list/JD extraction and local package validation.

## SOT Checklist

- [x] Root SOT read.
- [x] Harness read.
- [x] Related `docs/sot/**` read.
- [x] Position registration skill read.
- [x] Existing implementation entrypoints read.
- [x] Wrtn public list extracted.
- [x] Details/JD recovered.
- [x] Dry-run package validated.
- [x] External writes/sends blocked with reason.
