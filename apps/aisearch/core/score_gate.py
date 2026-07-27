"""AC-4 registration score gate for AI Search.

Reuses the existing candidate-match-v2-2026-07-24 contract as-is (no clone):
``calculate_final_score`` from ``tools.multi_position_sourcing`` is the only
scoring authority. This module adds exactly one policy on top — candidates
scoring below 60 are excluded from registration (goal doc AC-4 / D5).
Contract violations are not swallowed: ``MatchingContractError`` propagates
unchanged (fail-fast).
"""

from __future__ import annotations

from typing import Mapping

from tools.multi_position_sourcing.matching_score_contract import (
    calculate_final_score,
)

#: Minimum 0-100 score required for registration. Exactly 60 passes.
SCORE_GATE_THRESHOLD = 60


def apply_score_gate(payload: Mapping[str, object]) -> dict[str, object]:
    """Score ``payload`` via the existing contract and apply the 60-point cut.

    Returns the contract result plus ``eligible``/``threshold``. Any invalid
    payload raises ``MatchingContractError`` from the reused contract.
    """

    result = dict(calculate_final_score(payload))
    score = result["score"]
    result["threshold"] = SCORE_GATE_THRESHOLD
    result["eligible"] = score >= SCORE_GATE_THRESHOLD
    return result
