"""App 16 — fail-closed three-machine release verification conductor."""

from __future__ import annotations

import pytest

from tools.multi_position_sourcing.live_verification import (
    CORE_SCENARIOS,
    LiveVerificationError,
    conduct_verification,
)


def _matrix():
    return {name: "PASS" for name in CORE_SCENARIOS}


def test_fixture_matrix_must_cover_all_sixteen_scenarios_before_preflight():
    calls = []
    matrix = _matrix()
    matrix.pop(next(iter(matrix)))
    with pytest.raises(LiveVerificationError, match="DISCOVERY_INCOMPLETE"):
        conduct_verification(
            run_id="run-1", owner_signoff=True, scenario_matrix=matrix,
            preflight=lambda machine: calls.append(machine),
        )
    assert len(CORE_SCENARIOS) == 16
    assert calls == []


def test_macmini_then_macbook_and_non_delegated_winpc_zero_touch():
    calls = []
    bundle = conduct_verification(
        run_id="run-1", owner_signoff=True, scenario_matrix=_matrix(),
        preflight=lambda machine: calls.append(machine) or {
            "machine": machine, "state": "READY", "mutation_count": 0,
            "close_count": 0, "receipt": f"{machine}-receipt",
        },
        winpc_delegated=False,
    )
    assert calls == ["macmini", "macbook_pro"]
    assert [row["machine"] for row in bundle["per_machine"]] == [
        "macmini", "macbook_pro", "winpc"]
    assert bundle["per_machine"][2]["state"] == "NOT_DELEGATED"
    assert bundle["per_machine"][2]["mutation_count"] == 0
    assert bundle["mutation_counts"]["winpc"] == 0
    assert bundle["close_counts"] == {
        "macmini": 0, "macbook_pro": 0, "winpc": 0}
    assert bundle["verdict"] == "PASS"


def test_owner_signoff_missing_stops_before_discovery():
    calls = []
    with pytest.raises(LiveVerificationError, match="OWNER_SIGNOFF_MISSING"):
        conduct_verification(
            run_id="run-1", owner_signoff=False, scenario_matrix=_matrix(),
            preflight=lambda machine: calls.append(machine),
        )
    assert calls == []


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"state": "READY", "mutation_count": 1, "close_count": 0},
         "UNEXPECTED_MUTATION"),
        ({"state": "READY", "mutation_count": 0, "close_count": 1},
         "BROWSER_CLOSED"),
        ({"state": "READY", "mutation_count": 0, "close_count": 0,
          "cookie": "li_at=SECRET"}, "SECRET_LEAK"),
    ],
)
def test_forbidden_actions_and_secret_scanner_fail_before_success(payload, code):
    with pytest.raises(LiveVerificationError, match=code):
        conduct_verification(
            run_id="run-1", owner_signoff=True, scenario_matrix=_matrix(),
            preflight=lambda machine: {"machine": machine, **payload},
        )


def test_expected_fail_closed_states_are_valid_evidence_not_fake_success():
    bundle = conduct_verification(
        run_id="run-expected-block", owner_signoff=True,
        scenario_matrix={
            **_matrix(),
            "challenge_handoff": "EXPECTED_BLOCK",
            "auth_conflict": "EXPECTED_BLOCK",
        },
        preflight=lambda machine: {
            "machine": machine, "state": "DISCOVERY_INCOMPLETE",
            "mutation_count": 0, "close_count": 0,
        },
    )
    assert bundle["verdict"] == "EXPECTED_BLOCK"
    assert bundle["logs_hash"]
    assert len(bundle["per_scenario"]) == 16
