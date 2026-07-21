# Harness Engineering notes for Valuehire AI Search reimplementation

Use this reference when the user asks to rebuild, formalize, productize, or reimplement the `search` skill / Valuehire AI Search as a real system rather than running a one-off candidate search.

## Core lesson

A formal implementation should not be framed as “write a better prompt to find candidates.” It should be framed as a harnessed AI system with explicit contracts, artifacts, validation, privacy controls, regression tests, and observability around each stage.

## Required harnesses

1. Input Harness
- ClickUp task URL/task id intake through ClickUp API, not browser login.
- Normalize task name, status, list/folder, JD, company, role, must-have, nice-to-have, negative signals, target companies, process context.
- Test missing token, 401/403/404/429/5xx, empty JD, mixed Korean/English JD, missing company/role.

2. Strategy Harness
- Generate reproducible position strategy: normalized requirements, target pools, lower-priority pools, keyword matrix, Boolean/X-ray query set, channel plan, scoring rubric, evidence requirements, discovery handoff prompt.
- Convert sensitive/discriminatory conditions into capability- and experience-based requirements.

3. Discovery Harness
- Separate search adapters by channel: ChatGPT Search handoff, Bing/Brave/Google X-ray, LinkedIn public URL, GitHub, Google Scholar, arXiv, Notion, portfolio, tech blog.
- Store raw results separately from normalized leads.
- Classify channel failure as blocked_by_captcha, rate_limited, no_results, network_error, parser_error, insufficient_evidence. Do not confuse channel failure with “no candidates exist.”

4. Evidence Harness
- Verify source URLs and link each claim to evidence.
- If LinkedIn content cannot be opened, record only the URL; do not use it as evidence for career/education claims.
- Check GitHub profile/README/pinned profile repo, blog/homepage links, portfolio, Notion, Scholar, official pages.
- Collect recruiting/work contact only when publicly and appropriately listed; exclude private/personal/no-recruiting contacts, commit metadata, leaks, brokers, or scraped contact databases.

5. Scoring Harness
- Keep a 100-point rubric: Core Requirement Fit 30, Problem-Solving Fit 20, Production & MLOps Fit 15, Domain/Company Pool Fit 15, Seniority & Leadership Fit 10, Evidence Quality 10.
- Every score must have source_urls, fit_reason, risk_or_gap, and score_breakdown.
- Low evidence quality or missing required fields should block priority_contact.
- Freelancer/Freelance status is not an automatic rejection but should lower priority and be called out in risk_or_gap.

6. Privacy & Safety Harness
- Run a privacy scanner before output.
- Remove sensitive data and prohibited contacts.
- recruiting_contact requires contact_source_url.
- Outreach is out of scope and must not be sent automatically.

7. Output Harness
- Produce both human-readable Markdown and machine-readable JSON.
- Human-readable report comes first; JSON comes after.
- Candidate required fields: profile_url, summary, match_score, fit_reason.

8. Evaluation Harness
- Build golden fixtures before implementation.
- Evaluate intake parse accuracy, requirement normalization quality, query diversity, evidence coverage, duplicate rate, invalid URL rate, unsupported claim rate, privacy violation rate, schema pass rate, and human review usefulness.
- Use unit tests, integration tests, schema validation tests, privacy red-team tests, regression tests, and replay tests with frozen raw search results.

9. Observability Harness
- Assign a run_id to every run.
- Store artifacts separately: intake.json, strategy.json, queries.json, raw_results.jsonl, leads.jsonl, evidence.jsonl, scored_candidates.json, report.md, validation.json.
- Redact secrets from logs.
- Use status enums such as completed, partial_completed, stopped_by_scope_limit, failed_intake, failed_strategy, failed_discovery, failed_validation, failed_privacy_scan.

## Suggested module layout

```text
src/
  clickup/{client,intake}
  strategy/{normalize-requirements,build-keyword-matrix,generate-queries,build-rubric}
  discovery/adapters/{chatgpt-search-handoff,bing,brave,github,scholar,notion,portfolio}
  discovery/{dedupe,lead-normalizer}
  evidence/{fetch-url,extract-evidence,verify-claims,contact-policy}
  scoring/{score-candidate,score-guards}
  privacy/{privacy-scan,redact}
  output/{markdown-report,json-output}
  evaluation/{fixtures,golden-runner,metrics}
  observability/{run-artifacts,logger}
  validation/{schemas,validate}
```

## Definition of Done for implementation prompts

A reimplementation prompt should require:
- ClickUp URL/task id intake works and fails safely.
- Strategy JSON validates.
- At least 10 queries are generated.
- Discovery adapter failures are structured.
- Each candidate has at least one source URL.
- Missing required fields block priority_contact.
- Privacy scanner removes prohibited data.
- Markdown and JSON outputs are both produced.
- Golden fixture regression passes.
- Sample run artifacts are created.
- DB write, Kanban update, and outreach are off by default.

## Short prompt pattern

“Reimplement Valuehire AI Search as a fresh system. Do not depend on Valuehire_v4 code or automation. Build ClickUp API intake → search strategy → discovery → evidence verification → scoring → Markdown/JSON handoff. Treat this as Harness Engineering: define schemas, tests, artifacts, validation, privacy scan, regression fixtures, and observability first. Do not create fake candidates, do not record candidates without public URLs, do not auto-send outreach, do not log secrets, and do not report unrun tests as passed.”
