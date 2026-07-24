# Unified candidate-matching prompt goal (Issue #198)

## Goal and current-state evidence

One versioned matching contract must drive the v5 `aisearch`/`humansearch`/`url`
agent surfaces and the v4 reverse-matching Claude/Codex runners.

Current conflicts:

- `tools/multi_position_sourcing/humansearch.py:33-38` defines the legacy
  education/role/prose-logic/stability weights.
- `tools/multi_position_sourcing/humansearch.py:330-340` scores profile prose
  quality, which the owner-provided contract explicitly forbids.
- `docs/sot/24-position-jd-sot.json:10-14` exposes only four legacy axes.
- v4 `tools/profile-archiver/server/index.js:1096-1120` asks the LLM to emit a
  direct 0-100 total.

Root cause: score semantics are copied across skills and runners instead of
being split into one LLM subscore contract plus one deterministic total
calculator.

## Acceptance criterion (single)

When the focused contract verifier and each repository's normal verification
command run, every named surface resolves matching-contract version
`candidate-match-v2-2026-07-24`; LLM prompts emit evidence-backed gates and
D1-D8 subscores only, deterministic code emits the final 0-100 score and band,
gate caps are enforced, and legacy direct-total/prose-quality instructions are
absent from active adapters.

Counter-AC: a stored but unreferenced prompt, a stale agent adapter, a direct
LLM total, or a total accepted without evidence does not pass.

## Unit decomposition and contracts

| Unit | Dependency | Contract | Verification gate |
|---|---|---|---|
| U1 v5 prompt SOT | none | JSON prompt contract contains Stage 1-3 schemas, D1-D8, weights, caps, bands | focused contract test |
| U2 v5 agent wiring | U1 | Claude/Codex aisearch and humansearch plus url handoff resolve U1 | focused reference test |
| U3 v4 reverse wiring | U1 | Claude/Codex reverse runners receive the same contract version and never request a total | focused v4 test |
| U4 deterministic total | U1 | validated gates/dimensions produce score, cap, band; invalid input fails fast | table-driven scorer tests |
| U5 mirrors and audit | U2-U4 | installed/global adapters match repository sources; adversarial review finds no stale active rubric | hash/reference checks + V1/V2 |

No later unit starts until its dependency's focused verification passes.

## Input domain and exception table

The explicit input is `{gates, dimensions, total_years}` plus the versioned
weight map. The implicit inputs are the prompt-contract version and tier maps.
Time, DB state, channel, and model vendor must not affect Stage 4.

| Input class | Required handling | Test |
|---|---|---|
| Valid gates; D1-D8 integer scores 0-5 | deterministic weighted score | valid baseline |
| D2 `not_applicable` | move its full weight to D1 | D2 redistribution |
| D6 `not_applicable` | move 7 points to D1 and 3 to D3 | D6 redistribution |
| `school_sensitive_client=true` | move 4 points from D1 to D8 | school-sensitive case |
| `total_years >= 10` | move floor-half of current D8 weight to D1 | 10-year boundary |
| One or more gate `fail` | cap final score at 49 | fail cap |
| No fail and at least two `uncertain` | cap final score at 69 | uncertain cap |
| Missing/blank evidence for a scored dimension | reject before totaling | evidence guard |
| Empty/null payload or missing D key | reject | schema guard |
| Score outside 0-5, non-integer, unknown verdict/type | reject | malformed guard |
| Duplicate gate requirements | reject (ambiguous evidence identity) | duplicate guard |
| Tier map missing a company/school | D6 evidence must say unknown and may be N/A; live runners load repository-owned company/school maps | missing-tier cases |
| Repeated identical input | identical output, no state mutation | retry/idempotence |
| External LLM/tier-map failure before Stage 4 | no inferred score; explicit incomplete result | failure fixture |
| Concurrent/out-of-order evaluations | pure Stage 4 remains order-independent | permutation test |
| Contract version mismatch | reject | version guard |
| All other inputs | reject explicitly; no normalization or silent fallback | catch-all guard |

## Decisions fixed from the owner prompt

1. The “7 dimensions” phrase is a count typo: the enumerated schema and weight
   map define eight dimensions, D1-D8.
2. The operating note says an unknown company tier is `not_applicable`, not
   zero. Its 10 points are redistributed to D1/D3 in their relative importance;
   integer largest-remainder allocation is D1 +7, D3 +3.
3. LLMs never emit the final score or band. Stage 4 is pure code.
4. “Evidence citation” means a non-blank resume-derived evidence string on
   every applicable D1-D8 result. A scored dimension without evidence is
   invalid rather than silently downgraded.
5. Temperature 0 and JSON mode are invocation requirements where the provider
   exposes them; schema validation remains mandatory because CLI surfaces may
   not expose both controls.

## Output shape

```json
{
  "contract_version": "candidate-match-v2-2026-07-24",
  "score": 0,
  "band": "strong|candidate|conditional|reject",
  "gate_cap": null,
  "weights_applied": {"D1": 27, "D2": 10, "D3": 14, "D4": 9, "D5": 7, "D6": 10, "D7": 14, "D8": 9}
}
```

The calculator API is pure:

```python
calculate_final_score(payload: Mapping[str, object]) -> FinalScore
```

The v4 JavaScript equivalent must accept and return the same JSON field names.

## Non-scope

- Live portal browsing, ClickUp/Discord writes, outreach, or candidate contact.
- Historical candidate rescoring or database migration.
- Few-shot anchors and outcome-feedback calibration, which need real owner data.
- Changing the 70/85 operating thresholds beyond the supplied four bands.

## Verification commands

```bash
# v5 focused
pytest -q tests/test_matching_prompt_contract.py tests/test_humansearch_skill.py tests/test_reservoir_scoring.py

# v5 full
./verify.sh

# v4 focused
npm test -- --run tests/matching/matchingPromptContract.test.ts

# v4 full
npm run check

# strict exits
make strict-exit-gate
npm run strict:exit-gate
```

## SOT checklist

- [x] SOT-30 strict contract and recurrence ledger read.
- [x] v4 SOT-17 and v5 SOT-24/25 current scoring definitions recovered.
- [x] Existing v4 reverse prompts and v5 scoring entrypoints recovered.
- [x] U1-U5 focused gates pass (v5 350 passed/3 xfailed; v4 22 relevant tests passed).
- [x] No test deletion, skip/only/todo addition, or assertion weakening.
- [x] Claude/Codex mirrors and hashes checked; skill validator passed all eight repository adapters.
- [x] Independent adversarial verdict and generator re-attack recorded in
  `docs/engineering/unified-matching-prompt.verdict.json`.
