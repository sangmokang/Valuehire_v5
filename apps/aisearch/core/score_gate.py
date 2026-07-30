"""AC-4 registration score gate for AI Search.

Reuses the existing candidate-match-v2-2026-07-24 contract as-is (no clone):
``calculate_final_score`` from ``tools.multi_position_sourcing`` is the only
scoring authority. This module adds exactly one policy on top — candidates
scoring below 60 are excluded from registration (goal doc AC-4 / D5).
Contract violations are not swallowed: ``MatchingContractError`` propagates
unchanged (fail-fast).
"""

from __future__ import annotations

from typing import Callable, Mapping, TypeVar

from tools.multi_position_sourcing.matching_score_contract import (
    calculate_final_score,
)

#: Minimum 0-100 score required for registration. Exactly 60 passes.
SCORE_GATE_THRESHOLD = 60

_T = TypeVar("_T")


class BelowThresholdError(Exception):
    """Raised when a candidate scores below ``SCORE_GATE_THRESHOLD``.

    Carries ``score`` and ``threshold`` so callers can log/report the block
    without re-scoring.
    """

    def __init__(self, score: object, threshold: int = SCORE_GATE_THRESHOLD):
        super().__init__(
            f"registration blocked: score {score} < threshold {threshold}"
        )
        self.score = score
        self.threshold = threshold


def apply_score_gate(payload: Mapping[str, object]) -> dict[str, object]:
    """Score ``payload`` via the existing contract and apply the 60-point cut.

    Returns the contract result plus ``eligible``/``threshold``. Any invalid
    payload raises ``MatchingContractError`` from the reused contract.

    .. note:: **Informational API only.** The returned ``eligible`` bool can
       be ignored by callers, so registration code paths MUST NOT branch on
       this function alone — use :func:`register_if_eligible` (the sole
       registration entry point) or :func:`enforce_registration_gate`, which
       raise :class:`BelowThresholdError` instead of returning a flag.
    """

    result = dict(calculate_final_score(payload))
    score = result["score"]
    result["threshold"] = SCORE_GATE_THRESHOLD
    result["eligible"] = score >= SCORE_GATE_THRESHOLD
    return result


def enforce_registration_gate(result: Mapping[str, object]) -> dict[str, object]:
    """Enforcing gate: raise ``BelowThresholdError`` for sub-60 results.

    Takes a result produced by :func:`apply_score_gate` (or any mapping with
    a 0-100 ``score``) and returns it unchanged when the score is at or above
    ``SCORE_GATE_THRESHOLD``. Below the threshold it raises, so a registration
    path cannot proceed by ignoring a boolean — the exception blocks it.
    """

    score = result["score"]
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise TypeError(f"score must be numeric, got {type(score).__name__}")
    if score < SCORE_GATE_THRESHOLD:
        raise BelowThresholdError(score)
    return dict(result)


def register_if_eligible(
    payload: Mapping[str, object],
    register_fn: Callable[[dict[str, object]], _T],
) -> _T:
    """Sole registration entry point: score, enforce the gate, then register.

    Orchestrators MUST register candidates only through this helper. It scores
    ``payload`` with the reused contract, enforces the 60-point cut via
    :func:`enforce_registration_gate` (raising :class:`BelowThresholdError`
    below 60 — ``register_fn`` is never called in that case), and only then
    invokes ``register_fn`` exactly once with the gated result. Contract
    violations (``MatchingContractError``) also propagate before any
    registration side effect.
    """

    gated = enforce_registration_gate(apply_score_gate(payload))
    return register_fn(gated)
