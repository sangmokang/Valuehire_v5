# PC-F2 Goal — humansearch live runner R4 wiring

## Current Evidence
- Base branch is `task/humansearch-multipage-full` because PC-C3b is local-verified but not merged to `main`.
- `tools/multi_position_sourcing/owner_activity.py:42` provides `compute_yield_decision(...) -> bool`.
- `tools/multi_position_sourcing/owner_activity.py:97` provides `detect_owner_activity_snapshot(...) -> OwnerActivitySnapshot`.
- `tools/multi_position_sourcing/harvest_policy.py:38` provides `worker_should_yield(owner_activity_detected=...) -> bool`.
- `tools/multi_position_sourcing/humansearch_cdp_run.py:373` calls `iter_planned_cards(...)` and `:383` opens each profile through `process_profile(tab, card, i)`.
- `tools/multi_position_sourcing/humansearch_cdp_run.py` currently has no `owner_activity` or `worker_should_yield` call in the profile loop, so the live runner can keep opening profiles while the owner is using Chrome.
- `tools/multi_position_sourcing/humansearch_preflight.py:144` provides `assert_live_or_abort(tab)` and `PreflightError`; current runner calls it only before traversal, not between profile opens.

## Root Cause
PC-F1 created the owner activity detector, but the live humansearch runner never consumes it. The runner also does not re-run the existing preflight guard during profile iteration, so a mid-run captcha/session lock can be missed.

## Contract
Add runner-level helpers and wire them from `main()`:

```python
def should_yield_for_owner(owner_snapshot=detect_owner_activity_snapshot) -> bool: ...

def process_cards_with_r4(
    tab,
    cards: list[dict],
    *,
    owner_snapshot=detect_owner_activity_snapshot,
    live_check=assert_not_blocked_or_abort,
) -> list[dict]: ...

def main(max_profiles: int = 25, start: int = 0, *, owner_snapshot=detect_owner_activity_snapshot) -> None: ...
```

Input shape:
- `owner_snapshot`: callable returning an object with `owner_activity_detected: bool`.
- `live_check`: callable accepting `tab`, raising `PreflightError` when captcha/session/login gate fails.
- `cards`: list of existing card dicts from PC-C3b planned traversal.

Output/state:
- If `worker_should_yield(owner_activity_detected=snapshot.owner_activity_detected)` is true before a profile, stop before calling `process_profile`.
- If `live_check(tab)` raises `PreflightError` after a profile, save rows collected so far and stop without opening remaining cards.
- Start-of-run checking remains `assert_live_or_abort(tab)` because the tab is on a search page. Mid-run checking uses `assert_not_blocked_or_abort(tab)` because after `process_profile` the tab is on a profile page, where a full search-results preflight would falsely fail on missing result cards.
- Results are written through the existing `collect_results` filter after every processed profile and again at the end.
- No send/outreach/browser-login/launchd behavior is changed.

## Acceptance Criteria
- Owner activity before the first profile opens zero profiles.
- Owner activity after one profile preserves the first row and opens no later profiles.
- No owner activity processes all cards.
- Mid-run `PreflightError` stops immediately after the failing check and does not open remaining cards.
- The runner uses `worker_should_yield`, not a reimplemented Chrome/idle rule.
- `main()` passes injected `owner_snapshot` into the profile loop so tests do not read OS state.
- PC-C3b traversal remains wired; R4 does not reintroduce `cards[:max_profiles]`.

## Non-Scope
- Auto-resume daemon decision and launchd operation; those are PC-F4a/F4b.
- GitHub push/PR/merge.
- Live portal execution.
- Send or outreach automation.

## Verification Commands
- Focused:
  `PYTHONSAFEPATH=1 PYTHONPATH=/Users/kangsangmo/Valuehire_v5-humansearch-r4-wiring /Users/kangsangmo/Valuehire_v5/.venv/bin/python -m pytest /Users/kangsangmo/Valuehire_v5-humansearch-r4-wiring/tests/test_humansearch_r4_wiring.py -q`
- Related:
  `PYTHONSAFEPATH=1 PYTHONPATH=/Users/kangsangmo/Valuehire_v5-humansearch-r4-wiring /Users/kangsangmo/Valuehire_v5/.venv/bin/python -m pytest /Users/kangsangmo/Valuehire_v5-humansearch-r4-wiring/tests/test_humansearch_r4_wiring.py /Users/kangsangmo/Valuehire_v5-humansearch-r4-wiring/tests/test_humansearch_multipage_full.py /Users/kangsangmo/Valuehire_v5-humansearch-r4-wiring/tests/test_owner_activity.py /Users/kangsangmo/Valuehire_v5-humansearch-r4-wiring/tests/test_humansearch_preflight.py -q`
- Full:
  `PYTHONSAFEPATH=1 PYTHONPATH=/Users/kangsangmo/Valuehire_v5-humansearch-r4-wiring /Users/kangsangmo/Valuehire_v5/.venv/bin/python -m pytest /Users/kangsangmo/Valuehire_v5-humansearch-r4-wiring/tests/ -q`

## SOT Checklist
- `CLAUDE.md`: owner Chrome use must yield; no send weakening; concise Korean reporting.
- `docs/harness.md`: RED -> GREEN, real tests, adversarial verification.
- `docs/sot/22-talent-search-filters.json`: stop on captcha/block; no bot retry.
- `docs/sot/27-humansearch-browsing-preflight.json`: reuse `assert_live_or_abort`.
- `docs/sot/27-humansearch-browsing-preflight.json`: reuse preflight block tokens; full search-result preflight only on search pages.
- `docs/sot/28-auto-send-policy.json`: no send path touched.
