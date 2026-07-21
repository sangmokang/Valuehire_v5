---
name: weekly
description: ValueHire weekly operations workflow for ClickUp/Gmail/Notion/admin weekly reporting. Use when Codex is asked to update or audit weekly metrics, check Gmail [추천]/[포지션] to ClickUp sync, monitor customer Gmail for new positions or candidate progress, prepare Notion/admin.valuehire.cc weekly updates, or explain/operate the weekly skill.
---

# Weekly

## Scope

Use this skill for ValueHire weekly operating checks. Default to Korean reporting and evidence-backed numbers. Treat ClickUp as the recruiting operations source of truth and Gmail as intake/progress evidence.

Do not run external writes, sends, deployment, or launchd registration without explicit owner approval. In `$st`, treat those as L3.

## Required Reading

In `/Users/kangsangmo/Desktop/valuehire_v4`, read the relevant current files before acting:

- `docs/sot/14-weekly-screen-columns.md`
- `docs/sot/13-scheduled-agents-registry.md` when automation/cron is involved
- `docs/engineering/weekly-gmail-position-monitor-skill-goal-2026-07-02.md`
- `tools/gmail-recommendation-clickup-sync/run.mjs`
- `tools/weekly-monitor/gmail-customer-monitor.mjs` when monitoring customer mail

## Quick Commands

Read-only weekly Gmail/customer monitor:

```bash
node --env-file=.env.local tools/weekly-monitor/gmail-customer-monitor.mjs --since-hours 72 --limit 100
```

Read-only `[추천]/[포지션]` sync preview:

```bash
node --env-file=.env.local tools/gmail-recommendation-clickup-sync/run.mjs --dry-run --since-hours 72 --sync-positions
```

Apply `[추천]` candidate tasks only:

```bash
node --env-file=.env.local tools/gmail-recommendation-clickup-sync/run.mjs --apply --since-hours 2
```

Apply `[포지션]` ClickUp + Kanban writes only after owner approval:

```bash
OWNER_SIGNOFF_GMAIL_REC_POSITION_SYNC=approved \
node --env-file=.env.local tools/gmail-recommendation-clickup-sync/run.mjs --apply --sync-positions --since-hours 2
```

Do not persist `OWNER_SIGNOFF_GMAIL_REC_POSITION_SYNC=approved` in launchd or shell startup files.

## Operating Workflow

1. Run the read-only monitor first. Summarize `counts`, `needsAction`, and any mismatches with task IDs.
2. For `[추천]`, apply only if the user asks to create candidate tasks. Re-run dry-run after apply and confirm `alreadyProcessed` or duplicate matching.
3. For `[포지션]`, keep writes blocked unless the user explicitly approves the L3 command. Use dry-run/monitor output to identify whether each item is duplicate, similar, create, or needs review.
4. For weekly KPI/admin updates, collect ClickUp numbers with existing weekly tools and update Markdown/Notion/admin only after the relevant write/deploy approval.
5. Report remaining risks: team Gmail coverage, noisy Gmail signals, ClickUp duplicate candidates, stale active positions, and any disabled cron.

## Interpretation Rules

- `[포지션]` auto-write being off is intentional unless both `--sync-positions` and `OWNER_SIGNOFF_GMAIL_REC_POSITION_SYNC=approved` are present.
- The root safety rule is: monitor continuously, write only with explicit approval.
- A direct `[추천]` subject is a candidate task signal.
- A direct `[포지션]` subject is a position intake signal.
- `Re:`/`FW:` `[추천]` threads are progress/reply signals, not new recommendation create signals.
- Platform/no-reply/newsletter/promotional mail should not be counted as customer evidence unless the user specifically asks to inspect it.

## Verification

Use focused tests before broad checks:

```bash
npm run gmail-rec-clickup-sync:review
npx vitest run tools/weekly-monitor/tests/
```

For live read-only evidence, run the monitor command above and quote only the counts and action rows needed for the decision.
