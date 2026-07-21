# Gmail Resume ClickUp Match Runbook

## Purpose

This runbook covers the Gmail resume attachment pipeline:

```text
member Gmail attachments
-> local SQLite stage
-> optional Supabase mirror/write
-> position rematch
-> optional ClickUp task creation
```

Recommended mode narrows Gmail input to sent `[추천]` messages and names ClickUp tasks with `[기추천리스트역매칭]`.

## Read-Only Checks

Run Supabase/Gmail/ClickUp readiness without external writes:

```bash
node tools/gmail-resume-clickup-match/preflight.mjs \
  --json \
  --timeout-ms 7000 \
  --output tools/gmail-resume-clickup-match/_tmp/latest-recommended-preflight-report.json
```

Run the recommended cron dry-run:

```bash
OWNER_SIGNOFF_RESUME_MATCH_SUPABASE= \
OWNER_SIGNOFF_RESUME_MATCH_CLICKUP= \
GMAIL_RESUME_MATCH_MODE=recommended \
GMAIL_RESUME_EXTERNAL_READ_TIMEOUT_MS=7000 \
/bin/bash scripts/cron-gmail-resume-clickup-match.sh
```

Expected safe outcome before approval:
- `readyForCronDryRun=true`
- `readyForProductionWrites=false`
- `clickupTasksWritten=0`
- `supabaseAttachmentsWritten=0`
- pending Supabase/ClickUp counts are reported for owner review.

If the run must prove company-wide member coverage, first generate a local owner-editable draft from env configuration:

```bash
node tools/gmail-resume-clickup-match/member-roster-template.mjs --json \
  --output /secure/path/valuehire-gmail-member-roster.draft.json
```

The draft file contains raw emails and is not approval evidence. The command prints only masked email evidence. The owner must edit the file, add any missing Gmail members, remove non-members, then set `authority` to `owner_approved_complete_gmail_member_roster` and `ownerApproved` to `true`.

After owner approval, provide the local roster artifact and rerun the cron dry-run:

```bash
GMAIL_MEMBER_ROSTER_PATH=/secure/path/valuehire-gmail-member-roster.json \
OWNER_SIGNOFF_RESUME_MATCH_SUPABASE= \
OWNER_SIGNOFF_RESUME_MATCH_CLICKUP= \
GMAIL_RESUME_MATCH_MODE=recommended \
GMAIL_RESUME_EXTERNAL_READ_TIMEOUT_MS=7000 \
/bin/bash scripts/cron-gmail-resume-clickup-match.sh
```

The roster artifact is local-only and should not be committed. Supported shape:

```json
{
  "authority": "owner_approved_complete_gmail_member_roster",
  "ownerApproved": true,
  "approvedAt": "2026-07-05",
  "approvedBy": "owner",
  "emails": ["member1@example.com", "member2@example.com"]
}
```

The cron writes `tools/gmail-resume-clickup-match/_tmp/latest-member-roster-audit-recommended.json` and passes it into readiness. A passing audit requires exact equality across the owner roster, `GMAIL_EXPECTED_MEMBER_EMAILS`, configured Gmail accounts, and Gmail profile-readable accounts. Reports mask member emails.

Completion audit must still block if the current recommended run has pending Supabase work. `pendingSupabaseAttachments` and `pendingSupabaseMatches` both need to be `0`; seeing older rows in Supabase or a ready diagnostics report is not enough to claim the current run is persisted.

Build the owner approval package from the latest read-only run:

```bash
node tools/gmail-resume-clickup-match/approval-package.mjs --json \
  --report tools/gmail-resume-clickup-match/_tmp/latest-cron-report-recommended.json \
  --readiness-report tools/gmail-resume-clickup-match/_tmp/latest-readiness-report-recommended.json \
  --output tools/gmail-resume-clickup-match/_tmp/latest-approval-package-recommended.json
```

The approval package preserves `--recommended` in suggested approval commands and refuses to mark ClickUp write ready when readiness says the company-wide member roster is not independently audited.

For recommended runs, do not use an approval package that was generated without `--readiness-report`. When company-wide roster proof is missing, `approvalCommands.supabaseThenClickUpWriteAfterApproval` and `approvalCommands.clickUpWriteForAlreadySyncedRows` must be `null`; only the Supabase-only command may remain visible.

## Recommended Mode Contract

Relevant files:
- `tools/gmail-resume-clickup-match/lib/constants.mjs`
- `tools/gmail-resume-clickup-match/run.mjs`
- `tools/gmail-resume-clickup-match/lib/matcher.mjs`
- `tools/gmail-resume-clickup-match/lib/clickup-payload.mjs`
- `scripts/cron-gmail-resume-clickup-match.sh`
- `scripts/launchd/com.valuehire.recommended-rematch.plist`

Contract:
- `--recommended` changes the default Gmail query to sent recommendation mail.
- Non-`[추천]` subjects are filtered after Gmail search.
- Stage rows carry `metadata.match_mode="recommended"`.
- ClickUp task names use `[기추천리스트역매칭]`.
- Cron only adds write flags when the owner signoff env vars are already present.
- Cron runs `member-roster-audit.mjs` only when `GMAIL_MEMBER_ROSTER_PATH` is set, then forwards the report to readiness with `--member-roster-audit-report`.

## Owner Signoff Gates

Do not set these vars unless the owner explicitly approves the exact operation:

```bash
OWNER_SIGNOFF_RESUME_MATCH_SUPABASE=approved
OWNER_SIGNOFF_RESUME_MATCH_CLICKUP=approved
```

Approval request must state:
- target Supabase tables/storage bucket
- target ClickUp list ID
- expected attachment/match/task counts
- whether launchd will be loaded
- owner-approved complete Gmail roster proof status

## Launchd

The recommended plist is a template only until owner approval:

```text
scripts/launchd/com.valuehire.recommended-rematch.plist
```

Install/load only after:
- the branch is merged into the main checkout path used by the plist
- read-only cron dry-run passes
- owner approves launchd registration

## Verification

Focused checks:

```bash
npx vitest run tools/gmail-resume-clickup-match/tests/recommended-mode.test.mjs \
  tools/gmail-resume-clickup-match/tests/readiness.test.mjs \
  tools/gmail-resume-clickup-match/tests/member-roster-audit.test.mjs \
  tools/gmail-resume-clickup-match/tests/approval-package.test.mjs
```

Full tool checks:

```bash
npx vitest run tools/gmail-resume-clickup-match/tests/*.test.mjs
```

Syntax and plist checks:

```bash
for f in tools/gmail-resume-clickup-match/*.mjs tools/gmail-resume-clickup-match/lib/*.mjs tools/gmail-resume-clickup-match/tests/*.test.mjs tools/lib/supabase-batch.mjs; do
  node --check "$f" || exit 1
done
bash -n scripts/cron-gmail-resume-clickup-match.sh
plutil -lint scripts/launchd/com.valuehire.recommended-rematch.plist scripts/com.valuehire.gmail-resume-clickup-match.plist
```
