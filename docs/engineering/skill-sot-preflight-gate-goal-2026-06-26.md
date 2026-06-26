# Skill SOT Preflight Gate Goal — 2026-06-26

## Current Evidence

- `CLAUDE.md:33` says code must not be trusted and prior instructions must be found before coding.
- `docs/harness.md:16` says skipping prior-instruction recovery before new code is an SOT violation.
- Repo skills exist at `skills/search/SKILL.md`, `skills/multisearch/SKILL.md`, `skills/position-registration/SKILL.md`, and `skills/humansearch/SKILL.md`.
- A prior failure mode occurred when an agent wrote new runner/registration code and added SOT after the fact instead of first recovering existing definitions.

## Root Cause

The repo has strong SOT text, but individual skills do not all carry an explicit start gate that forces the agent to read repo SOT, related docs, previous instructions, and existing code entrypoints before acting.

## Acceptance Criteria

- Every repo skill `SKILL.md` contains the same hard "common SOT start gate".
- The gate requires reading `CLAUDE.md`, `docs/harness.md`, related `docs/sot/*`, skill configs/references, existing code entrypoints, and prior memory/logs before coding or external work.
- The gate forbids new runners, new registration scripts, or new files before proving existing paths are insufficient.
- The gate marks Discord, ClickUp, email, portal posting/registration/comment/field updates as L3 external writes requiring explicit approval.
- A focused pytest test fails when a repo skill lacks the gate.

## Non-Scope

- Do not edit system skills under `.codex/skills/.system`.
- Do not weaken any existing skill-specific safety rule.
- Do not perform any external write, portal action, Discord send, ClickUp write, or email send.

## Verification

- `python3 -m pytest tests/test_skill_sot_preflight_gate.py -q`
- `python3 -m pytest tests/test_sot_distrust_doublecheck_doc.py -q`
- Skill quick validation where available.
