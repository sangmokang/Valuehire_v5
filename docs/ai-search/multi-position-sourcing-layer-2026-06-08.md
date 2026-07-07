# ValueHire AI Search Multi-Position Sourcing Layer

Date: 2026-06-08 KST  
Mode: dry-run/read-only by default  
Owner write gates: `OWNER_SIGNOFF`, `RPS_EXPORT_ALLOW_WRITE`, Supabase/ClickUp write gates required before live writes

Safety update: the v5 layer must not implement 10-minute profile-click keepalives,
LinkedIn automated profile traversal, bot-detection bypass, or automated outreach.
Protected portal sessions are maintained by readiness checks and manual relogin
alerts only. Run readiness on demand immediately before protected portal search,
not as a timed heartbeat.

## 1. Current Implementation Inventory

### Repository reality in this checkout

This workspace does not contain the full ValueHire application source tree. The requested paths were searched first and are absent in this checkout:

- `src/lib/aiSearch`
- `app/api/kanban/ai-search/*`
- `app/api/pipeline/position-cards/*/ai-search`
- `tools/position-batch`
- `tools/ai-search-rps-*`
- `tools/profile-archiver`
- Hermes app/runtime source beyond the portable `skills/search` copy

The requested SOT/engineering docs were also not present under this v5 `docs/sot`, `docs/engineering`, or `docs/operations`.

### Read-only sibling implementation evidence

Because sibling checkouts exist on this machine, `../Valuehire_v4` was inspected read-only for the exact requested paths and documents. No files outside this v5 workspace were changed.

Requested implementation paths found in `../Valuehire_v4`:

- `src/lib/aiSearch`
- `app/api/kanban/ai-search`
- `app/api/pipeline/position-cards/[id]/ai-search`
- `tools/position-batch`
- `tools/profile-archiver`
- `tools/hermes-agent`
- `docs/sot`
- `docs/engineering`
- `docs/operations`

Requested SOT/engineering docs found and read in `../Valuehire_v4`:

- `docs/sot/09-job-posting-publishing.md`
- `docs/sot/10-ai-search-sourcing.md`
- `docs/sot/10-auto-login.md`
- `docs/sot/11-channel-dom-selectors.md`
- `docs/engineering/profile-archiver-ocr-and-human-following-capture-goal-2026-06-05.md`
- `docs/engineering/chrome-extension-position-body-copy-and-reverse-match-goal-2026-06-05.md`
- `docs/operations/hermes-agent-dev-manager-usecases-prompting-2026-05-30.md`
- `docs/engineering/qa/issue-log.md` entries QA-467, QA-468, QA-486, QA-493

Available local evidence:

- `skills/search/SKILL.md`: ClickUp-first AI Search process, no outreach, no DB/Kanban write by default, public URL/evidence requirements.
- `skills/search/references/harness-engineering-reimplementation.md`: harness architecture, scoring/evidence/privacy/output contracts.
- `skills/search/references/chatgpt-search-cdp-handoff.md`: single existing Chrome/CDP pattern for ChatGPT Search capture.
- `skills/search/references/clickup-ai-search-channel-fallbacks.md`: channel failure handling, captcha/rate-limit reporting, GitHub/Scholar fallback guidance.
- `docs/search-access.md`: local access reference and secret handling rules.
- Existing AI Search result markdown files: candidate output shape, side-effect reporting, and verification style.

### What the v4 implementation says

- `docs/sot/10-ai-search-sourcing.md` defines AI Search as always-on, queue/resume oriented, human-like, and fail-closed on captcha/2FA/IP security/account warning. It also explicitly states Saramin/Jobkorea candidate search is currently not wired as a production candidate-search save rail.
- `src/lib/aiSearch/sourceValidation.ts` allows candidate save channels `linkedin`, `github`, `scholar`, `notion`, `web`, and `rps`. It does not allow `saramin` or `jobkorea` candidate channels today.
- `src/lib/aiSearch/canonicalUrl.ts` builds canonical identity keys for LinkedIn `/in` and RPS `/talent/profile`, GitHub, Scholar, Notion, and web. Saramin/Jobkorea canonical candidate keys are not production save keys yet.
- `app/api/pipeline/position-cards/[id]/ai-search/route.ts` is the production save API. It validates channel/profile URL, enforces candidate evidence, canonical-dedups existing rows, stores `source=ai_search:<channel>`, and exposes AI Search candidates in position views.
- `app/api/kanban/ai-search/run/route.ts` starts ChatGPT/CDP-backed AI Search jobs and calls the same save API. Hybrid merge can use `src/lib/aiSearch/mergeForSave.ts`.
- `src/lib/aiSearch/multiEngine.ts` has pure multi-engine merge/dedup/cross-validation logic, but QA-467 says production adapter wiring is still open.
- `tools/position-batch/lib/skill-a-source-runner.mjs` defines a live portal sourcing gate: `OWNER_SIGNOFF_SOURCE=approved`, `ENABLE_SKILL_A_SOURCE_RUNNER=1`, `SKILL_A_SOURCE_NO_LIVE_CONTACT=1`, per-channel commands, captcha/2FA stop flags, random delays, and direct HTTP scraping guard for LinkedIn/RPS.
- `tools/profile-archiver` stores detailed profile screenshots and DOM text locally first. Its server already has `ocr_text`, OCR status columns, `profile_archives` Supabase sync payload, and `/api/reverse-match`. Its README states manual/person-following capture, not autonomous list crawling.
- `docs/engineering/profile-archiver-ocr-and-human-following-capture-goal-2026-06-05.md` and QA-493 document Saramin iframe text loss and OCR reinforcement through Claude vision, with human-following capture and stop-on-human-intervention.
- `docs/operations/ai-search-rps-channel-goal-2026-05-29.md` documents RPS `/talent/profile/` harvesting, virtual-scroll accumulation, interest extraction, dedup, throttle, owner Chrome guard, and InMail/send prohibition. Direct `tools/ai-search-rps-safe-run` and `tools/ai-search-rps-export` files were not found in the inspected v4 root, though RPS goal artifacts exist under `.omc`.
- `docs/operations/hermes-agent-dev-manager-usecases-prompting-2026-05-30.md` says Hermes should trigger/monitor the shared AI Search queue rather than bypass it; live AI Search remains gated and queue-dependent.

QA entries read:

- QA-467: multi-engine core exists but production adapters/import path are open.
- QA-468: `position-batch:source` is still `live-source-not-wired`; env gates alone would not create real candidates.
- QA-486: registration/JD/Gmail/AI Search end-to-end seams are broken; enqueue/trigger wiring is a known gap.
- QA-493: Profile Archiver Saramin iframe text loss and OCR/human-following capture are open.

### Confirmed gaps

- Saramin/Jobkorea candidate search is not connected to the v4 production candidate save rail yet. Adding them as `ai_search:saramin`/`ai_search:jobkorea` would require extending `sourceValidation.ts`, canonical identity keys, storage mapper, and evidence policy first.
- Profile Archiver extension/server/SQLite implementation is not present in this v5 checkout, but it exists in `../Valuehire_v4/tools/profile-archiver`. This v5 layer defines the adapter contract and dry-run behavior only.
- RPS integration is documented and partially artifacted in v4, but direct `tools/ai-search-rps-safe-run` / `tools/ai-search-rps-export` files were not found in the inspected root. LinkedIn RPS must not export/write unless `RPS_EXPORT_ALLOW_WRITE` or the equivalent owner gate is present.
- ClickUp candidate/position data remains the recruiting operations SSOT. This dry-run code uses fixtures only and must not be treated as repo SOT.

## 2. Position Grouping Schema

Implemented in `tools/multi_position_sourcing/models.py` and `tools/multi_position_sourcing/grouping.py`.

`position_groups` output:

```json
{
  "group_id": "backend-3to10-...",
  "role_family": "backend",
  "seniority_range": [3, 10],
  "core_keywords": ["backend api", "spring", "node/nest", "platform", "infra", "production"],
  "portal_keywords_by_channel": {
    "saramin": ["백엔드 개발자", "Java Spring 개발자"],
    "jobkorea": ["백엔드 개발자", "Java Spring"],
    "linkedin_rps": ["Backend Engineer", "Java Spring Engineer"]
  },
  "filters_by_channel": {
    "saramin": {"career_years": {"min": 2, "max": 11}, "education": "4년제 졸업"},
    "jobkorea": {"career_years": {"min": 2, "max": 11}, "education": "대학교 졸업"},
    "linkedin_rps": {"profile_url_must_match": "/talent/profile/", "allow_inmail_send": false}
  },
  "position_ids": ["pos-backend-wrtn", "pos-backend-spoon"],
  "company_similarity_notes": ["company size, industry, stage, talent-density notes"]
}
```

Grouping uses role family plus seniority bucket plus company context. Company size, investment stage bucket, industry segment, organization analysis, and talent-density notes are preserved in the group notes so human reviewers can reject weak grouping.

## 3. Sample Groups

Fixture source: `tools/multi_position_sourcing/fixtures.py`.

1. Backend group
   - Positions: `pos-backend-wrtn`, `pos-backend-spoon`
   - Rationale: mid/senior scaleup backend/platform roles with Java/Spring, Node/Nest, infra/platform, production reliability.

2. AI/ML group
   - Position: `pos-ai-madup`
   - Rationale: production ML/LLM/adtech role with Python/PyTorch/MLOps/recsys requirements.

3. Product/PO group
   - Position: `pos-po-wrtn-ontology`
   - Rationale: AI product owner/manager with ontology, service planning, platform planning, stakeholder delivery.

4. Growth group
   - Position: `pos-growth-uglylab`
   - Rationale: senior consumer growth/performance/CRM/retention/referral leader.

5. Sales group
   - Position: `pos-sales-b2b-saas`
   - Rationale: Korean B2B SaaS sales/pipeline/CRM/enterprise sales owner.

## 4. Portal Keyword Preset Draft

Implemented in `tools/multi_position_sourcing/keywords.py`.

Rules:

- Saramin/Jobkorea sessions reset existing chips and filters before each keyword.
- One search session uses one standard portal job word only.
- Niche terms such as `서브컬쳐`, `미연시`, `ontology`, `settlement`, `short-form` stay in `llm_screening_keywords`, not the first portal query.
- Backend variants are sequential sessions: `백엔드 개발자`, `Java Spring 개발자`, `Node.js 개발자`, `플랫폼 개발자`, `인프라 개발자`.
- PO/PM variants are portal-specific: `Product Owner`, `Product Manager`, `서비스기획`, `플랫폼기획`.
- LinkedIn RPS sessions accept only `/talent/profile/` URLs as candidate evidence.

## 5. Profile Save, Dedup, Reverse-Match Design

### Save adapter contract

Use existing `tools/profile-archiver` when available. This v5 checkout does not contain it, but `../Valuehire_v4/tools/profile-archiver` confirms the local server, SQLite, screenshots, `ocr_text`, Supabase sync payload, and `/api/reverse-match` shape. The required adapter input for this dry-run layer is:

```json
{
  "profile_url": "string",
  "canonical_url": "string",
  "source_channel": "saramin|jobkorea|linkedin_rps",
  "visible_text": "string",
  "screenshot_path": "string",
  "ocr_text": "string",
  "captured_at": "ISO-8601",
  "evidence_paths": ["string"]
}
```

Save only detailed profile pages. Do not save list pages. For Saramin/Jobkorea iframe/body misses, the adapter must attach OCR text and mark `ocr_text` as evidence. If `visible_text` and `ocr_text` are both empty, stop before scoring.

### Dedup contract

Implemented in `tools/multi_position_sourcing/dedup.py` as a dry-run extension contract.

- Canonicalize LinkedIn `/talent/profile/<id>` and `/in/<slug>` URLs.
- Canonicalize Saramin/Jobkorea profile IDs from stable query keys where possible. This is not yet a v4 production save contract because current v4 `sourceValidation.ts` excludes Saramin/Jobkorea candidate channels.
- Drop query strings/fragments.
- If a canonical profile was captured within TTL, do not reopen it.

### Reverse-match contract

Implemented in `tools/multi_position_sourcing/scoring.py`.

For one saved candidate, return top 3-5 positions with:

- candidate URL
- profile summary
- recommended position ID
- score
- why fit
- why not
- evidence paths
- score breakdown

Score categories:

- JD must-have direct match
- years/seniority
- education/major
- current/past company tier
- company stage/industry/culture fit
- Korea/language/region signals
- evidence quality
- risk penalty

## 6. Hermes Queue Design

Implemented dry-run shell in `tools/multi_position_sourcing/queue_runner.py`. This mirrors v4 SOT 10 and Hermes guidance: Hermes claims a shared queue; it does not directly improvise browser control.

Queue item:

```json
{
  "group_id": "string",
  "channel": "saramin|jobkorea|linkedin_rps",
  "keyword_plan": [],
  "status": "pending|claimed|done|failed|stopped",
  "attempts": 0,
  "last_error": "",
  "next_run_at": "ISO-8601"
}
```

Cycle behavior:

- If Chrome CDP is not connected, keep pending items unchanged for resume.
- If Saramin, Jobkorea, or LinkedIn RPS login session is not confirmed, keep that protected channel pending for resume.
- If owner activity is detected, stop the cycle and keep pending items unchanged.
- If captcha, 2FA, checkpoint, IP security, or abnormal access appears during portal login preflight, wait for human intervention in the visible browser, then revalidate the persistent profile and capture only a validated encrypted snapshot. Runtime automatic login for Saramin/Jobkorea loads credentials from macOS Keychain, not from env; LinkedIn RPS never auto-logins.
- If human intervention times out, headless mode disables intervention, selector failure occurs, or a write gate is missing, record a stopped reason and do not retry immediately.
- Each cycle reports searched groups, opened profiles, saved profiles, matched profiles, stopped reasons, and updated queue items.
- Live browser operations must use a single existing Chrome CDP session; do not launch a new browser.

## 7. Dry-Run Implementation

New files:

- `tools/multi_position_sourcing/models.py`
- `tools/multi_position_sourcing/fixtures.py`
- `tools/multi_position_sourcing/grouping.py`
- `tools/multi_position_sourcing/keywords.py`
- `tools/multi_position_sourcing/dedup.py`
- `tools/multi_position_sourcing/scoring.py`
- `tools/multi_position_sourcing/selectors.py`
- `tools/multi_position_sourcing/queue_runner.py`
- `tools/multi_position_sourcing/dry_run.py`
- `tools/multi_position_sourcing/discord_routing.py`
- `tools/multi_position_sourcing/register_discord_commands.py`
- `scripts/valuehire-search-loop.sh`
- `scripts/valuehire-search-healthcheck.sh`
- `scripts/launchd/com.valuehire.search-runner.plist`
- `tests/test_multi_position_sourcing.py`

Dry-run command:

```bash
python3 -m tools.multi_position_sourcing.dry_run --output artifacts/multi_position_sourcing/dry-run-latest.json
```

Generated artifact:

- `artifacts/multi_position_sourcing/dry-run-latest.json`

This artifact contains 5 groups, Backend/PO keyword plans, canonical URL output, one sample candidate matched to multiple positions, queue summary, Discord DM/server routing decisions, and zero side-effect flags.
