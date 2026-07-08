# Valuehire AI Search Code Map

Use this map to find implementation code quickly. Prefer current repo files over copied assumptions.

Repo root: `/Users/kangsangmo/Valuehire_v5`

## Entrypoints and Scripts

- `scripts/run_portal_search.py`: human-in-the-loop live portal search runner.
- `scripts/collect_linkedin.py`: LinkedIn collection helper.
- `scripts/probe_linkedin_dom.py`: LinkedIn DOM probing.
- `scripts/rps_switch.sh`: LinkedIn RPS multi-session/manual switch helper.
- `scripts/valuehire-search-healthcheck.sh`: search machine healthcheck.
- `scripts/valuehire-search-loop.sh`: search loop wrapper.
- `scripts/portal_browsers.sh`: portal browser session helper.
- `scripts/launchd/com.valuehire.portal-browsers.plist`: portal browser launchd config.
- `scripts/launchd/com.valuehire.search-runner.plist`: search runner launchd config.

## Core Data Models and Output

- `tools/multi_position_sourcing/models.py`: `CapturedProfile`, `PositionMatch`, queue/search result models, channel types.
- `tools/multi_position_sourcing/scoring.py`: generic candidate-to-position scoring.
- `tools/multi_position_sourcing/humansearch.py`: humansearch scoring and send eligibility.
- `tools/multi_position_sourcing/clickup_activity.py`: ClickUp Activity/comment formatter.
- `tools/multi_position_sourcing/discord_briefing.py`: Discord candidate briefing formatter.
- `tools/multi_position_sourcing/dedup.py`: candidate deduplication.

## Portal Operation and Safety

- `tools/multi_position_sourcing/portal_autologin.py`: portal auto-login and drift handling.
- `tools/multi_position_sourcing/portal_login.py`: portal login orchestration; delegates security challenge handling.
- `tools/multi_position_sourcing/portal_live_check.py`: live readiness checks, Discord alert tests, operational artifacts.
- `tools/multi_position_sourcing/portal_safety.py`: safety classification and guards.
- `tools/multi_position_sourcing/portal_recovery.py`: recovery/backoff and reauth alerts.
- `tools/multi_position_sourcing/portal_runtime.py`: runtime orchestration for portal attempts.
- `tools/multi_position_sourcing/portal_session.py`: browser/session lifecycle helpers.
- `tools/multi_position_sourcing/portal_snapshot.py`: page/session snapshots.
- `tools/multi_position_sourcing/portal_worker.py`: bounded portal worker execution and candidate cards.
- `tools/multi_position_sourcing/portal_queue_executor.py`: queue item to portal execution adapter.
- `tools/multi_position_sourcing/portal_dod_audit.py`: definition-of-done audit for portal readiness.
- `tools/multi_position_sourcing/portal_ops.py`: portal operation helpers.
- `tools/multi_position_sourcing/browser_policy.py` and `browser_policy.json`: browser policy checks.
- `tools/multi_position_sourcing/rps_switch.py`: RPS session switch logic.
- `tools/multi_position_sourcing/timeout_recovery.py`: timeout recovery and side-effect-zero checks.

## Search Planning and Queue

- `tools/multi_position_sourcing/channel_search_render.py`: channel-specific keyword/filter rendering.
- `tools/multi_position_sourcing/keywords.py`: keyword planning.
- `tools/multi_position_sourcing/llm_keywords.py`: LLM-assisted keyword extraction with enforced NOT terms.
- `tools/multi_position_sourcing/selectors.py`: selector utilities.
- `tools/multi_position_sourcing/queue_runner.py`: queue planning and `run_live_queue_cycle`.
- `tools/multi_position_sourcing/dry_run.py`: dry-run sample workflow and no-side-effect checks.

## Reservoir and Matching

- `tools/multi_position_sourcing/segments.py`: deterministic segment taxonomy.
- `tools/multi_position_sourcing/grouping.py`: grouping logic.
- `tools/multi_position_sourcing/embed.py`: deterministic embedding and profile text.
- `tools/multi_position_sourcing/match.py`: segment filter, vector top-K, scoring rerank.
- `tools/multi_position_sourcing/harvest_policy.py`: harvest policy.
- `tools/multi_position_sourcing/harvest_runner.py`: harvest execution.
- `tools/multi_position_sourcing/reservoir_log.py`: reservoir logging.
- `tools/multi_position_sourcing/ab_harness.py`: blind A/B comparison harness.
- `docs/ai-search/embeddings.sql`: pgvector schema.

## Discord, Access, and Intake

- `tools/multi_position_sourcing/access.py`: authorized Discord DM guard.
- `tools/multi_position_sourcing/discord_routing.py`: slash/free-text routing.
- `tools/multi_position_sourcing/register_discord_commands.py`: Discord command registration.
- `tools/multi_position_sourcing/request_parser.py`: distinguishes AI Search from position registration.
- `tools/multi_position_sourcing/position_registration.py`: position registration workflow, separate from AI Search.
- `tools/multi_position_sourcing/position_dedup.py`: position deduplication.
- `tools/multi_position_sourcing/posting_extractor.py`: hiring page extraction.
- `tools/multi_position_sourcing/posting_recognizer.py`: posting recognition.
- `tools/multi_position_sourcing/posting_models.py`: posting data models.

## Fixtures and Tests

- `tools/multi_position_sourcing/fixtures.py`: sample positions/profiles.
- `tests/test_search_skill_stability.py`: search skill stability.
- `tests/test_channel_search_filters.py`: channel filter rendering.
- `tests/test_channel_search_render.py`: channel search rendering.
- `tests/test_portal_preflight_autologin.py`: portal preflight and autologin.
- `tests/test_portal_bg_login_plumbing.py`: background login plumbing.
- `tests/test_live_queue_cycle.py`: live queue cycle orchestration.
- `tests/test_multi_position_sourcing.py`: broad integration-style unit coverage.
- `tests/test_reservoir_scoring.py`: scoring behavior.
- `tests/test_reservoir_match.py`: reservoir matching.
- `tests/test_reservoir_embeddings.py`: embedding behavior.
- `tests/test_reservoir_segments.py`: segment classification.
- `tests/test_reservoir_harvest.py`: harvest flow.
- `tests/test_reservoir_ab.py`: A/B harness.
- `tests/test_reservoir_doc.py`: reservoir docs.
- `tests/test_humansearch_skill.py`: humansearch scoring and output.
- `tests/test_position_registration.py`: registration routing and safety.
- `tests/test_position_dedup.py`: position deduplication.

## Related Skill and Spec Files

- `skills/search/SKILL.md`: older fresh-core AI Search procedure; useful but not the strongest execution spec.
- `skills/search/references/boolean-strategy.md`: Boolean/X-ray query rules.
- `skills/search/references/chatgpt-search-cdp-handoff.md`: ChatGPT Search via CDP.
- `skills/search/references/clickup-ai-search-channel-fallbacks.md`: fallback channels and reporting.
- `skills/search/references/greetinghr-career-page-intake.md`: career page intake for GreetingHR.
- `skills/search/references/harness-engineering-reimplementation.md`: formal system reimplementation guide.
- `skills/multisearch/SKILL.md`: multi-position AI Search and operations rules.
- `skills/humansearch/SKILL.md`: humansearch skill, config-driven scoring.

## Useful Checks

Run targeted tests after related changes:

```bash
pytest tests/test_search_skill_stability.py tests/test_channel_search_filters.py tests/test_channel_search_render.py tests/test_portal_preflight_autologin.py tests/test_live_queue_cycle.py
```

For scoring/matching changes:

```bash
pytest tests/test_reservoir_scoring.py tests/test_reservoir_match.py tests/test_humansearch_skill.py
```

For a broader but still relevant pass:

```bash
pytest tests/test_multi_position_sourcing.py tests/test_search_skill_stability.py tests/test_portal_preflight_autologin.py
```
