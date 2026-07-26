# Valuehire AI Search SOT Procedure

This reference consolidates the AI Search specs. It does not replace the repo files; always prefer live repo content when editing or executing.

## Canonical Files

- Main execution spec: `/Users/kangsangmo/Valuehire_v5/docs/sot/25-ai-search-execution-process.json`
- Human-readable entry: `/Users/kangsangmo/Valuehire_v5/docs/sot/25-ai-search-execution-process.md`
- Channel filters and DOM SSOT: `/Users/kangsangmo/Valuehire_v5/docs/sot/22-talent-search-filters.json`
- Channel summary: `/Users/kangsangmo/Valuehire_v5/docs/sot/22-talent-search-filters.md`
- JD and scoring SOT: `/Users/kangsangmo/Valuehire_v5/docs/sot/24-position-jd-sot.json`
- Portal login/blocking SOT: `/Users/kangsangmo/Valuehire_v5/docs/sot/26-portal-login-spec.json` (`26-portal-login-spec@1.5.0`)
- Top repo invariants: `/Users/kangsangmo/Valuehire_v5/CLAUDE.md`

## Non-Negotiable Invariants

- Use v5 only. Do not run Valuehire v4 or legacy npm automation.
- Do not perform ad-hoc search. AI Search must be anchored to a user-provided position ID, ClickUp task URL, hiring URL, JD text, or explicit stage-limited instruction.
- Do not begin generic web search, portal search, ChatGPT Search, LinkedIn/Saramin/Jobkorea search, or candidate discovery before stage 0-4 establish scope, channel state, JD source, and keyword strategy.
- Do not weaken, skip, reorder, or silently replace SOT gates for convenience. If a shortcut conflicts with SOT 25/22/24/26, the shortcut is forbidden.
- Do not improvise around `OCCUPIED`, `HUMAN_AUTH`, `HANDOFF`, or `AUTH_CONFLICT`. Report the exact state and follow `26-portal-login-spec@1.5.0`.
- Authentication is site-specific: Saramin and Jobkorea may submit stored username/password once on the only exact existing target. LinkedIn must never submit username/password; it may reuse the only authenticated machine with zero authentication mutations, or use APP 30/31 `LINKEDIN_LI_AT` once only after a proven zero-machine count, current-turn owner authorization, and the APP 17 route decision select the same exact target.
- If owner Chrome is occupied, do zero automation and resume only after it is clear.
- A real captcha, 2FA, bot block, or checkpoint is `HUMAN_AUTH`. A LinkedIn multi-session lock or two-or-more authenticated machines is terminal `AUTH_CONFLICT`; automatic logout, Continue/Confirm, reliability selection, and retry are forbidden. An unproven machine count or a missing/non-unique exact target is `HANDOFF` with zero authentication mutations.
- Do not route channels by role type. Search all target portal channels for every role when live search is in scope.
- Detailed profile entry/save is treated as zero-credit, but credit-consuming search/send actions require human confirmation.
- Never auto-send proposal, mail, InMail, Send, 보내기, or 제안 발송.
- `profile_url` must be a channel full URL. Do not use internal IDs such as Saramin `residx` as `profile_url`.
- Speak to the owner in short, plain Korean.

## Stage Contract

### 0. Preflight

Inputs: position ID, ClickUp task URL, hiring URL, or JD text.

Required actions:
- Confirm work is in `/Users/kangsangmo/Valuehire_v5` or equivalent v5 checkout.
- Check only the exact endpoint/profile/target proven by `26-portal-login-spec@1.5.0`
  and APP 17. 포트·프로필 추측 금지.
- If no authenticated browser path exists, report live-search unavailable and continue only with non-live strategy/dry-run.

### 1. Occupancy, Captcha, Login Gate

Required actions:
- Read the CDP tab list only from the proven exact endpoint/profile/target.
  포트·프로필 추측 금지.
- Detect blocks using the unified regex from SOT 26: captcha, recaptcha, 보안문자, 자동입력 방지, checkpoint, unusual activity, multiple sign-ins, Only one session, enterprise-authentication, 2단계, authwall, challenge, etc. Do not classify `/uas/login-cap` or `li.protechts` alone as a hard block.
- Before declaring a terminal or human state, cross-check with screenshot or direct page evidence to avoid plain-text false positives.
- Run preflight batch state inspection: check all target channels and exact-target candidate counts before any allowed site-specific authentication.
- Classify each target channel as `READY`, `OCCUPIED`, `HUMAN_AUTH`, `HANDOFF`, or `AUTH_CONFLICT`.

Decision rules:
- Captcha/2FA/checkpoint: affected channel is `HUMAN_AUTH`; no automatic bypass or repeat submission.
- Logged-out Saramin/Jobkorea: submit stored credentials at most once only when there is exactly one existing target that matches the site policy; otherwise `HANDOFF`.
- LinkedIn authenticated-machine count unproven: `HANDOFF` with zero authentication mutations.
- LinkedIn count one: reuse that machine and its only exact target with zero authentication mutations.
- LinkedIn count zero: only APP 30/31 may apply `LINKEDIN_LI_AT` at most once when current-turn owner authorization and the APP 17 route decision identify the same machine and there is exactly one existing target; otherwise `HANDOFF`.
- LinkedIn count two or more or multi-session: terminal `AUTH_CONFLICT`; do not log out another machine, Continue/Confirm, choose by reliability, or retry.
- Owner occupied: go to stage 2.

### 2. Yield and Resume

Required actions:
- While `OCCUPIED`, perform zero browser automation.
- Poll and rerun stage 1.
- Resume only when occupancy clears and no block is present.
- Do not behave mechanically: no repeated window open/close loops, URL hammering, or endless alert retries.

### 3. JD Intake

Source order:
1. If position is in `docs/sot/24-position-jd-sot.json`, use that structured JD.
2. If ClickUp task is provided, fetch ClickUp task description via API.
3. If ClickUp JD is missing/stale and a hiring page exists, extract official career page content.
4. If only pasted JD text is available, use it and mark source accordingly.

Pass condition: role, must-have, nice-to-have, location/employment, and context are available enough to search.

### 4. Keyword Strategy

Split JD into five axes:
- Industry/domain: AND, usually one term.
- Role: OR synonyms.
- Skill/tool: OR, one or two high-signal terms.
- Experience: left-side filter with +/- 1 to 2 years.
- Exclude: NOT terms.

Important: one AND term normally narrows sharply. Multiple specific AND terms can collapse results to zero.

### 5. Channel Search and Save

Execution mode: parallel across ready channels. Do not do Saramin, then Jobkorea, then LinkedIn serially unless constrained by tooling; if serial fallback is unavoidable, report it as a deviation.

Portal entry URLs:
- Saramin: `https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search`
- Jobkorea: `https://www.jobkorea.co.kr/corp/person/find`
- LinkedIn RPS: `https://www.linkedin.com/talent/search`

Channel-specific basics:
- Saramin: OR/AND/NOT boxes; `keyboard.type` + Enter; `fill()` is forbidden for chip creation; full profile URL may be credit-gated.
- Jobkorea: use `#txtKeyword` clipboard paste; `window.searchcondition` mutation alone is not enough.
- LinkedIn RPS: natural-language search is primary; wait 20 to 60 seconds between keywords.

Result bands:
- Saramin/Jobkorea: 5-80 = process all; 81-300 = top 40; 300+ = add one AND term then reassess.
- LinkedIn RPS: 5-60 = process all; 61-200 = top 20; 200+ = narrow then reassess.
- 0-4 = stop that scenario and move to another scenario.

### 6. Evaluation

Use SOT 24 contract `candidate-match-v2-2026-07-24`:
- LLM: must-have gates plus evidence-backed D1-D8 integer subscores only.
- D1 role capabilities, D2 domain, D3 seniority, D4 trajectory/stability,
  D5 measurable outcomes, D6 company-tier delta, D7 closing realism, D8 school.
- Deterministic Stage 4 code alone calculates the total, gate caps, and band.
- Reject a scored dimension without resume evidence; never score prose quality.

Score bands:
- `85+`: strong
- `70-84`: candidate
- `<70`: drop/exclude recommendation

### 7. Output Contract

Required candidate fields:
- `profile_url`
- `score`
- `why_fit`
- `profile_summary`

If any required field is missing, hold the candidate and do not send or record it as complete.

Useful implementation mapping:
- `profile_url` maps to `PositionMatch.candidate_url`.
- `profile_summary` maps to `PositionMatch.profile_summary`.
- `why_fit` maps to `PositionMatch.why_fit`.
- `score` maps to `PositionMatch.score`.

### 8. LinkedIn/RPS JD Template Lane

For new or currently open positions:
- Include the LinkedIn/RPS JD template checkpoint.
- Body must stay within the configured template limit.
- Remove raw placeholders and HTML comments.
- Save/update template only when in scope.
- Never click Send.

Valid states: `saved`, `updated`, `local-package-only`, `blocked`, `not-requested-by-scope`.

### 9. Report

Report in Korean:
- Channel counts: `saramin: N / jobkorea: N / linkedin: N`
- Channel terminal status and reason.
- LinkedIn/RPS JD template status.
- Next recommended keywords.
- Markdown/JSON artifact paths.
- Side effects: whether ClickUp/Supabase/Discord/portal save/outreach happened.

## Output Contract Location

`docs/sot/25-ai-search-execution-process.json` owns the AI Search output contract in `output_contract.required_fields`: `profile_url`, `score`, `why_fit`, and `profile_summary`. The live code model remains `tools/multi_position_sourcing.models.PositionMatch`; map `candidate_url` to `profile_url` when serializing candidate output.
