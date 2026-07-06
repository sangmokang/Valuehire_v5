# AI Search Goal: Madup AI PO 6-15y Review

Date: 2026-07-05
Mode: `$st` strict mode + ai-search SOT
Risk: L3, because live portal and ClickUp/Discord write actions are possible. This run is read-only plus local artifact only.

## Target

- ClickUp task: `86ex3ur1n`
- Position: `[포지션]매드업, AI PO`
- ClickUp URL: `https://app.clickup.com/t/86ex3ur1n`
- User override: use 6 years minimum and 15 years maximum.
- Required output fields: `profile_url`, `score`, `why_fit`, `summary`.
- Required scoring axes: 직무직결성, 학교, 이직안정성, 도메인적합.
- Listing threshold: 80+ only.
- Exclusion notes required for current employees, overseas-only profiles, and under-minimum seniority.

## Evidence Read

- `make red-ledger`: clean.
- SOT checker: `status=OK`.
- ClickUp read-only task/comment fetch:
  - Task `86ex3ur1n` is open under `po/pm/기획`.
  - JD: Madup LEVER Xpert AI product owner/product manager role for digital marketing AI product.
  - Previous AI Search comment exists with three 80+ candidates under the older condition.
  - Previous status comment used `Location=South Korea` and default `3~12년`; latest user override supersedes it.
- Browser/CDP state:
  - `127.0.0.1:9222`: unavailable.
  - `127.0.0.1:9224`: available, but only Jobkorea pages are open.
  - Jobkorea pages include reCAPTCHA iframes; treat Jobkorea as blocked/suspect.
  - No open LinkedIn RPS or Saramin tab was available for live re-validation.

## Decision

Use the ClickUp history as the continuation source and re-filter it under the 6-15 year rule. Do not post to ClickUp or Discord without explicit approval. Do not open LinkedIn RPS profiles in this strict run because profile viewing can create external recruiting activity, and the current approval is not explicit for portal-side writes.

## Acceptance

- Produce a local result draft for ClickUp.
- Include only candidates whose 6-15 year fit is supported by the existing task evidence.
- Move candidates with insufficient seniority evidence to `보류/제외`, even if previous score was 80+.
- State channel blockers honestly.
