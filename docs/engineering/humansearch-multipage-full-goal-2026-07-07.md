# PC-C3b Goal — humansearch multipage full traversal

## Current Evidence
- `tools/multi_position_sourcing/humansearch_cdp_run.py:115` defines `collect_cards(tab, start)` and navigates one LinkedIn RPS page with `&start={start}`.
- `tools/multi_position_sourcing/humansearch_cdp_run.py:250` defines `main(max_profiles=25, start=0)`.
- `tools/multi_position_sourcing/humansearch_cdp_run.py:258` collects only one page, then `:265` iterates `cards[:max_profiles]`; 26+ GOLD results are cut at the page/local cap.
- `tools/multi_position_sourcing/humansearch.py:152` already provides `plan_result_count_traversal(channel, result_count) -> TraversalPlan`; PC-C3b must consume it, not reimplement result-count bands.
- `tools/multi_position_sourcing/harvest_policy.py:92` provides `deterministic_delay_ms(kind, step, seed)`; page-to-page pacing must reuse it.
- `task/humansearch-multipos` was checked before implementation. It contains broad multiposition/facet work and a fixed multipage idea, but not the PC-C2 traversal-plan consumption required here; it is not safe to merge wholesale.

## Root Cause
The live LinkedIn RPS runner has a single-page loop and a default local cap. It ignores the SOT22/PC-C2 decision that says GOLD bands must be fully traversed, so 26-60 LinkedIn GOLD results can be silently missed.

## Contract
New runner-level helper:

```python
def iter_planned_cards(
    tab,
    *,
    result_count: int,
    channel: str = "linkedin",
    start: int = 0,
    page_size: int = 25,
    pacing_seed: int = 0,
) -> list[dict]:
```

Input shape:
- `tab`: object accepted by existing `collect_cards(tab, start)`.
- `result_count`: `int`; passed to `plan_result_count_traversal`. Non-int/negative values fail closed through that function.
- `channel`: SOT22 channel key. For current runner default is `"linkedin"`.
- `start`: first result offset. Must be non-negative.
- `page_size`: LinkedIn page offset increment, positive integer. Default 25.
- `pacing_seed`: deterministic seed for `deterministic_delay_ms(kind="short", step=N, seed=pacing_seed)`.

Output shape:
- A list of card dicts in traversal order.
- Duplicates by `url` are removed while preserving first occurrence.
- `TraversalPlan(action="full", limit=None)` keeps paging until `result_count` cards or a short/empty page.
- `TraversalPlan(action="top_n", limit=N)` returns at most `N` cards.
- `abort` and `add_condition` return `[]` and do not call `collect_cards`.

State transitions:
- `result_count -> plan_result_count_traversal -> action`.
- `abort/add_condition`: stop before live collection.
- `full/top_n`: collect page offsets `start, start+page_size, ...`.
- Between page fetches, use `deterministic_delay_ms` and sleep once; no fixed delay constants in this helper.
- `main()` must call this helper after `assert_live_or_abort(tab)` and process returned cards. This proves PC-C2 is wired into the production path.

## Acceptance Criteria
- RED test proves a 60-result LinkedIn GOLD run collects more than one 25-card page and opens all 60 candidates.
- Top-N band, for LinkedIn 61-200, stops at 20 candidates and does not fetch extra pages.
- Abort band collects zero cards and does not call the collector.
- Page-to-page pacing calls `deterministic_delay_ms(kind="short", step=page_index, seed=pacing_seed)`.
- `main()` uses the new planned traversal path instead of `cards[:max_profiles]`.
- Existing hard-exclude output filtering remains unchanged.

## Non-Scope
- R4 owner Chrome yield wiring; that is PC-F2.
- Live portal login, captcha solving, launchd start/load, GitHub push/PR/merge.
- Multiposition config and left-panel keyword facet work from `task/humansearch-multipos`.
- Send or outreach automation.

## Verification Commands
- Focused RED/GREEN:
  `PYTHONSAFEPATH=1 PYTHONPATH=/Users/kangsangmo/Valuehire_v5-humansearch-multipage-full /Users/kangsangmo/Valuehire_v5/.venv/bin/python -m pytest /Users/kangsangmo/Valuehire_v5-humansearch-multipage-full/tests/test_humansearch_multipage_full.py -q`
- Full repo verification from worktree:
  `PYTHONSAFEPATH=1 PYTHONPATH=/Users/kangsangmo/Valuehire_v5-humansearch-multipage-full /Users/kangsangmo/Valuehire_v5/.venv/bin/python -m pytest /Users/kangsangmo/Valuehire_v5-humansearch-multipage-full/tests/ -q`
- Main harness fallback from repo root:
  `./verify.sh`

## SOT Checklist
- `CLAUDE.md`: Korean concise reporting; do not weaken auto-login/R4/send gates; test before done.
- `docs/harness.md`: worktree, RED -> GREEN, focused and full verification, adversarial checks.
- `docs/sot/22-talent-search-filters.json`: LinkedIn 5-60 full, 61-200 top 20, 0-4 abort, 200+ add condition; bot pacing from SOT22.
- `docs/sot/27-humansearch-browsing-preflight.json`: keep `assert_live_or_abort` as the fail-closed live gate before traversal.
- `docs/sot/28-auto-send-policy.json`: no send path touched.
