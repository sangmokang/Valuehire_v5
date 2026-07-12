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
.venv-playwright/bin/python -m pytest tests/test_humansearch_register.py -q
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

## Verification evidence

- RED: `61ca8fc` failed import because the shared hook validator and both hook configs did not exist.
- Focused: `49 passed` in `tests/test_humansearch_register.py`.
- Full: `1303 passed, 4 xfailed, 14 subtests passed`; `./verify.sh` exit 0.
- Self-attack: altered history, source text, and source ranges returned `candidate_history_incomplete`, `candidate_source_hash_mismatch`, and `candidate_source_ranges_mismatch`.
- Independent verifier first returned FAIL for date formats, cross-company duplicate periods, malformed dates, and parent-task disguises. Every counterexample became a regression test and was fixed. Final verdict on the behavior-changing code: PASS.
- Separate Claude CLI review attempts did not produce a usable verdict (one execution error, one budget limit), so the required fallback was the independent Codex review plus direct command reproduction.
- Local `codex-cli 0.137.0` could not boot with the owner's newer global `model_reasoning_effort = "ultra"`; live Codex-client discovery is therefore a remaining environment check. Repo hook schema, exact command process, exit 2, and input rewrite were tested directly.
- Artifact SHA-256: validator `b6175d989c09cb7772e2a41e7c5c49e2b86d363ca6650db52740f3a832848645`; both hook configs `76f84c62b284981288a830e44437f643c7e1a9d0815e7b444b366730a9ef9994`; focused test `d9c21ea78fb268a0f4eeaa864c2ddc83d2d360e079545ceb70e1091ad7789ed5`.
