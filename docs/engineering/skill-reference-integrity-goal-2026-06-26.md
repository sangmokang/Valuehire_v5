# Skill Reference Integrity Goal — 2026-06-26

## Current Evidence

- Repo SOT requires skills/doc changes to use contract tests: `docs/harness.md:49`.
- Current execution SOT references repo-local `skills/ai-search-position-pipeline/SKILL.md` and `skills/ai-search-position-pipeline/candidate-output-contract.json`, but those files are not present in this repo: `docs/sot/25-ai-search-execution-process.json:7`.
- Human-readable SOT repeats the missing candidate contract path: `docs/sot/25-ai-search-execution-process.md:46`.
- The Codex AI Search skill already documents this as a known gap instead of normalizing it: `/Users/kangsangmo/.codex/skills/ai-search/references/spec-procedure.md:157`.
- `skills/search/SKILL.md` and `skills/multisearch/SKILL.md` carry nonessential frontmatter keys beyond `name` and `description`: `skills/search/SKILL.md:4`, `skills/multisearch/SKILL.md:4`.
- `docs/sot/22-talent-search-filters.json` and `.md` refer to historical repo-relative skill paths while the actual historical copies are under `~/.claude/skills/`.

## Root Cause

The repo has evolved from older Claude skills and v4-era path names to current Codex skills and `tools/multi_position_sourcing/`, but several SOT/skill references were left as repo-relative historical paths or documented as gaps. That lets future agents hit INV10 dead-reference handling even though usable current paths exist.

## Acceptance Criteria

- A focused pytest test fails on the current broken references before edits.
- Repo skills under `skills/*/SKILL.md` and the Codex AI Search skill references point only to existing bundled references, repo SOT files, current repo implementation files, or explicitly marked historical `~/.claude/skills/...` sources.
- `docs/sot/25-ai-search-execution-process.json` uses the current Codex AI Search skill and an in-file/typed output contract instead of missing repo-local pipeline files.
- `docs/sot/25-ai-search-execution-process.md` no longer points users to a missing repo-local contract.
- `skills/search/SKILL.md` and `skills/multisearch/SKILL.md` frontmatter contains only `name` and `description`.
- No empty files exist under repo skills or `~/.codex/skills/ai-search`.
- JSON SOT files still parse.

## Non-Scope

- Do not edit system skills under `/Users/kangsangmo/.codex/skills/.system`.
- Do not run live portal, ClickUp, Discord, Gmail, or browser writes.
- Do not delete or rewrite historical `~/.claude/skills` sources.
- Do not weaken safety gates, output contract requirements, or SOT invariants.

## Verification Commands

- `.venv-playwright/bin/python -m pytest tests/test_skill_reference_integrity.py -q`
- `.venv-playwright/bin/python -m pytest tests/test_skill_sot_preflight_gate.py tests/test_search_skill_stability.py tests/test_humansearch_skill.py -q`
- `python3 /Users/kangsangmo/.codex/skills/ai-search/scripts/ai_search_sot_check.py --repo /Users/kangsangmo/Valuehire_v5`
- `./verify.sh`
- `python3 /Users/kangsangmo/.codex/skills/.system/skill-creator/scripts/quick_validate.py <skill-folder>` if `PyYAML` is available.

## SOT Checklist

- [x] Read `CLAUDE.md`.
- [x] Read `docs/harness.md`.
- [x] Read `docs/sot/22-talent-search-filters.md` and `.json`.
- [x] Read `docs/sot/23-channel-dom-selectors.md`.
- [x] Read `docs/sot/24-position-jd-sot.json`.
- [x] Read `docs/sot/25-ai-search-execution-process.md` and `.json`.
- [x] Read `docs/sot/26-portal-login-spec.json`.
- [x] Read `package.json`, `Makefile`, and `verify.sh`.
- [x] Read target `SKILL.md` files and bundled references.
