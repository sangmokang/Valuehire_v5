---
name: match
description: Operate ValueHire matching shortcuts for Gmail resume matching fixtures and cron, reverse matching fixtures, and the local vector matching screen. Use when asked for match, scripts/match.sh, Gmail resume matching shortcuts, reverse fixtures, vector matching, or owner-signoff-gated matching runs.
---

# Match

## Commands

- Show help: `scripts/match.sh help`
- Gmail fixture dry run: `scripts/match.sh gmail:fixture`
- Gmail fixture execution: `scripts/match.sh gmail:fixture --exec`
- Gmail cron preflight: `scripts/match.sh gmail:cron`
- Gmail cron execution: `scripts/match.sh gmail:cron --exec`
- Reverse matching fixture preflight: `scripts/match.sh reverse:fixture`
- Reverse matching fixture execution: `scripts/match.sh reverse:fixture --exec`
- Vector screen preflight: `scripts/match.sh vector`
- Vector screen execution: `scripts/match.sh vector --exec`

## Safety

The canonical shell entrypoint is `scripts/match.sh`.

Production writes are blocked unless the owner sign-off environment variables are explicitly approved:

- `OWNER_SIGNOFF_RESUME_MATCH_SUPABASE=approved`
- `OWNER_SIGNOFF_RESUME_MATCH_CLICKUP=approved`

Without those approvals, Gmail cron remains read-only or dry-run oriented and writes only local readiness reports.
