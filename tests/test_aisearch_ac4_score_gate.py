"""AC-4 — matching score gate: reuse candidate-match-v2-2026-07-24 + 60-point cut.

The gate must import and call the existing contract (no clone) and exclude
candidates scoring below 60 from registration.
"""

from __future__ import annotations

import pytest

from tools.multi_position_sourcing.matching_score_contract import (
    CONTRACT_VERSION,
    MatchingContractError,
    calculate_final_score,
)

from apps.aisearch.core.score_gate import (
    SCORE_GATE_THRESHOLD,
    apply_score_gate,
)


def _payload(
    scores: dict[str, object] | None = None,
    gates: list[dict[str, str]] | None = None,
    total_years: float = 5,
) -> dict[str, object]:
    dimensions: dict[str, dict[str, object]] = {}
    for index in range(1, 9):
        dimension_id = f"D{index}"
        entry: dict[str, object] = {
            "score": (scores or {}).get(dimension_id, 3),
            "evidence": f"{dimension_id} evidence",
        }
        if dimension_id == "D7":
            entry["needs_verification"] = []
        if dimension_id == "D8":
            entry["school_sensitive_client"] = False
        dimensions[dimension_id] = entry
    return {
        "contract_version": CONTRACT_VERSION,
        "gates": gates
        or [{"requirement": "req-1", "verdict": "pass", "evidence": "met"}],
        "dimensions": dimensions,
        "total_years": total_years,
    }


def test_threshold_is_60() -> None:
    assert SCORE_GATE_THRESHOLD == 60


def test_gate_scores_identical_to_direct_contract_call() -> None:
    payloads = [
        _payload(),  # uniform 3s -> 60
        _payload({"D1": 2}),  # below 60
        _payload({"D3": 5}),  # above 60
        _payload({"D2": "not_applicable"}),  # weight redistribution path
        _payload(
            gates=[
                {"requirement": "req-1", "verdict": "fail", "evidence": "missing"}
            ]
        ),  # gate cap 49
    ]
    for payload in payloads:
        direct = calculate_final_score(payload)
        gated = apply_score_gate(payload)
        assert gated["score"] == direct["score"]
        assert gated["band"] == direct["band"]
        assert gated["contract_version"] == CONTRACT_VERSION


def test_exactly_60_passes_the_gate() -> None:
    payload = _payload()  # all dimensions 3 -> 100 * 3/5 = 60
    assert calculate_final_score(payload)["score"] == 60
    result = apply_score_gate(payload)
    assert result["score"] == 60
    assert result["eligible"] is True


def test_59_is_excluded_from_registration() -> None:
    payload = _payload({"D5": 2})  # 60 - 7/5 = 58.6 -> 59
    assert calculate_final_score(payload)["score"] == 59
    result = apply_score_gate(payload)
    assert result["score"] == 59
    assert result["eligible"] is False


def test_gate_fail_cap_is_excluded() -> None:
    payload = _payload(
        gates=[{"requirement": "req-1", "verdict": "fail", "evidence": "missing"}]
    )
    result = apply_score_gate(payload)
    assert result["score"] == 49  # contract gate cap
    assert result["eligible"] is False


def test_above_60_passes() -> None:
    payload = _payload({"D3": 5})  # 60 + 14*2/5 = 65.6 -> 66
    result = apply_score_gate(payload)
    assert result["score"] == 66
    assert result["eligible"] is True


def test_contract_violation_fails_fast_through_the_gate() -> None:
    bad_version = _payload()
    bad_version["contract_version"] = "candidate-match-v1"
    with pytest.raises(MatchingContractError):
        apply_score_gate(bad_version)

    missing_fields = {"contract_version": CONTRACT_VERSION}
    with pytest.raises(MatchingContractError):
        apply_score_gate(missing_fields)

    bad_dimension = _payload({"D1": 9})
    with pytest.raises(MatchingContractError):
        apply_score_gate(bad_dimension)
