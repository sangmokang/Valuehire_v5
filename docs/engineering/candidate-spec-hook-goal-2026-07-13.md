# Candidate Spec Hook Goal — 2026-07-13

Issue: #89

## Current-state evidence

- `skills/humansearch/humansearch.config.json:61-71` says hard exclusion runs before scoring and two completed tenures under 12 months exclude the whole profile.
- `tools/multi_position_sourcing/humansearch.py:250-265` implements the canonical decision in `hard_exclude_reason()`.
- `tools/multi_position_sourcing/humansearch_register.py:143-168` enforces that decision only when callers use `eligible()`.
- `tools/multi_position_sourcing/humansearch_register.py:341-363` builds ClickUp descriptions without a machine-readable hard-exclude proof, so a direct MCP task call can bypass `eligible()`.

## Root cause

The escaped candidate was scored and sent through a direct ClickUp MCP call. The model supplied `87` manually and never invoked the existing canonical hard-exclude function. Prompt instructions and the normal registration function existed, but no lifecycle hook guarded the final tool boundary.

## Acceptance criterion (one)

Claude and Codex repo-local `PreToolUse` hooks invoke the same validator. A FY26AI_Search candidate Task/Subtask create or update is denied before tool execution when its machine-readable candidate proof is missing, malformed, or causes canonical `hard_exclude_reason()` to return a reason. The exact escaped shape—score 87 with at least two completed tenures under 12 months—must exit 2 for both engine event payloads.

## Contract

Input:

- stdin JSON hook event with `tool_name: str` and `tool_input: object`.
- Candidate writes are ClickUp create/update task calls targeting list `901818680208` with a parent/profile URL/score signal.
- Canonical candidate descriptions contain a compact versioned JSON proof generated from the already-eligible result: `profile_url`, `channel`, `score`, `education`, structured `employment_history`, independently extracted source date ranges, and a source-text SHA-256. Full profile text is not copied to ClickUp.

Output/state transition:

- non-candidate tool call -> exit 0 (unchanged).
- candidate write + valid proof + `hard_exclude_reason(...) is None` -> exit 0.
- candidate write + missing/malformed proof, wrong list, identity mismatch, incomplete history versus source date ranges, or hard-exclude reason -> reason on stderr and exit 2; ClickUp tool does not run.

## Non-goals

- Editing or deleting existing ClickUp candidates.
- Changing scoring weights or the two-hop/12-month rule.
- Sending outreach or writing candidate data to any production service.
- Claiming hooks are a complete security sandbox; they are deterministic lifecycle guardrails.

## Verification commands

```bash
python3 -m pytest tests/test_humansearch_register.py -q
./verify.sh
python3 tools/multi_position_sourcing/humansearch_register.py --candidate-spec-hook < fixture.json
```

## SOT checklist

- [x] Reuse `hard_exclude_reason()`; do not create a second tenure policy.
- [x] Fail closed at the candidate ClickUp write boundary.
- [x] Same validator for Claude and Codex.
- [x] No production ClickUp write in tests or verification.
- [x] Preserve parent-task creation and unrelated tools.
- [x] Do not trust the model-supplied score or a partial structured history.
