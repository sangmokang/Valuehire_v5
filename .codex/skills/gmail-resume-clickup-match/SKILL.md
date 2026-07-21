---
name: gmail-resume-clickup-match
description: Operate, audit, or modify the ValueHire Gmail resume to ClickUp matching pipeline, including recommended-list rematch mode, Supabase readiness, SQLite staging, cron/launchd wiring, and owner-signoff-gated Supabase or ClickUp writes. Use when asked about Gmail resume matching, 기추천 리스트 역매칭, [기추천리스트역매칭] ClickUp tasks, or gmail-resume-clickup-match readiness.
---

# Gmail Resume ClickUp Match

## Scope

Use this skill for `tools/gmail-resume-clickup-match`, `scripts/cron-gmail-resume-clickup-match.sh`, and the recommended-list rematch workflow.

Treat production writes as L3:
- Do not create ClickUp tasks without `OWNER_SIGNOFF_RESUME_MATCH_CLICKUP=approved`.
- Do not write Supabase rows/storage without `OWNER_SIGNOFF_RESUME_MATCH_SUPABASE=approved`.
- Do not install or load launchd plists without explicit owner approval and current-main path confirmation.

## Required Reading

Before acting, read:
- `AGENTS.md`
- `docs/README.md`
- `docs/sot/13-scheduled-agents-registry.md` when cron/launchd is involved
- `docs/sot/17-candidate-position-matching.md` when discussing scoring
- `docs/engineering/recommended-list-rematch-goal-2026-07-05.md`
- `docs/engineering/reverse-match-code-inventory-2026-07-05.md`
- `references/runbook.md`

## Default Workflow

1. Inspect `git status --short` and avoid touching unrelated user changes.
2. Run read-only preflight/readiness first; never jump straight to write flags.
3. For recommended mode, use `GMAIL_RESUME_MATCH_MODE=recommended` or `--recommended`.
4. Verify the reports show `externalWrites=0` unless explicit owner signoff is present.
5. If production approval is missing, report exact pending counts and required env vars.

## Key Commands

Read-only recommended cron dry-run:

```bash
OWNER_SIGNOFF_RESUME_MATCH_SUPABASE= \
OWNER_SIGNOFF_RESUME_MATCH_CLICKUP= \
GMAIL_RESUME_MATCH_MODE=recommended \
/bin/bash scripts/cron-gmail-resume-clickup-match.sh
```

Focused tests:

```bash
npx vitest run tools/gmail-resume-clickup-match/tests/*.test.mjs
```

Completion audit:

```bash
node tools/gmail-resume-clickup-match/completion-audit.mjs --json \
  --readiness-report tools/gmail-resume-clickup-match/_tmp/latest-readiness-report-recommended.json \
  --match-report tools/gmail-resume-clickup-match/_tmp/latest-cron-report-recommended.json
```

Completion requires current-run `pendingSupabaseAttachments=0` and `pendingSupabaseMatches=0`; Supabase REST/schema readiness alone is not enough.

Approval package:

```bash
node tools/gmail-resume-clickup-match/approval-package.mjs --json \
  --report tools/gmail-resume-clickup-match/_tmp/latest-cron-report-recommended.json \
  --readiness-report tools/gmail-resume-clickup-match/_tmp/latest-readiness-report-recommended.json \
  --output tools/gmail-resume-clickup-match/_tmp/latest-approval-package-recommended.json
```

For recommended runs, the approval package must include readiness evidence. If the company-wide roster is not owner-approved, it may show a Supabase-only approval command but must keep ClickUp write commands null.

Owner-editable roster draft:

```bash
node tools/gmail-resume-clickup-match/member-roster-template.mjs --json \
  --output /secure/path/valuehire-gmail-member-roster.draft.json
```

Owner-approved roster audit:

```bash
node tools/gmail-resume-clickup-match/member-roster-audit.mjs --json \
  --roster /secure/path/valuehire-gmail-member-roster.json \
  --preflight-report tools/gmail-resume-clickup-match/_tmp/latest-preflight-report-recommended.json \
  --output tools/gmail-resume-clickup-match/_tmp/latest-member-roster-audit-recommended.json
```

The draft contains raw member emails and is not approval evidence. Set `GMAIL_MEMBER_ROSTER_PATH` for cron dry-runs only after the owner verifies the complete Gmail member roster, sets `authority=owner_approved_complete_gmail_member_roster` and `ownerApproved=true`, and stores the artifact outside git. Do not commit roster artifacts.
