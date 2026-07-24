"""Deterministic Stage 4 for candidate-match-v2-2026-07-24.

The LLM owns extraction, gates, and evidence-backed D1-D8 subscores. This
module validates that output and is the only layer allowed to calculate the
final 0-100 score and action band.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


CONTRACT_VERSION = "candidate-match-v2-2026-07-24"
DIMENSION_IDS = tuple(f"D{index}" for index in range(1, 9))
_TOP_LEVEL_KEYS = {
    "contract_version",
    "gates",
    "dimensions",
    "total_years",
    "school_weight_enabled",
}
_VERDICTS = {"pass", "fail", "uncertain"}
_NOT_APPLICABLE_DIMENSIONS = {"D2", "D6"}


class MatchingContractError(ValueError):
    """Raised when Stage 3 output is outside the versioned contract."""


@lru_cache(maxsize=1)
def _stage4_contract() -> dict[str, Any]:
    repo = Path(__file__).resolve().parents[2]
    path = repo / "docs/sot/24-position-jd-sot.json"
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
        contract = root["evaluation_contract"]["matching_prompt_contract"]
        if contract["version"] != CONTRACT_VERSION:
            raise MatchingContractError(
                f"matching contract version mismatch in {path}: "
                f"{contract['version']!r}"
            )
        return contract["stages"]["stage_4_deterministic_total"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise MatchingContractError(f"cannot load matching contract: {path}") from exc


def _nonblank(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MatchingContractError(f"{field} must be a non-blank string")
    return value.strip()


def _validate_gates(value: object) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        raise MatchingContractError("gates must be a list")
    gates: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {
            "requirement",
            "verdict",
            "evidence",
        }:
            raise MatchingContractError(f"gates[{index}] has an invalid shape")
        requirement = _nonblank(
            item["requirement"], field=f"gates[{index}].requirement"
        )
        if requirement in seen:
            raise MatchingContractError(f"duplicate gate requirement: {requirement}")
        seen.add(requirement)
        verdict = item["verdict"]
        if verdict not in _VERDICTS:
            raise MatchingContractError(f"gates[{index}].verdict is invalid")
        evidence = _nonblank(item["evidence"], field=f"gates[{index}].evidence")
        gates.append(
            {
                "requirement": requirement,
                "verdict": verdict,
                "evidence": evidence,
            }
        )
    return tuple(gates)


def _validate_dimensions(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != set(DIMENSION_IDS):
        raise MatchingContractError("dimensions must contain D1-D8 exactly once")

    dimensions: dict[str, dict[str, Any]] = {}
    for dimension_id in DIMENSION_IDS:
        item = value[dimension_id]
        required = {"score", "evidence"}
        allowed = set(required)
        if dimension_id == "D7":
            allowed.add("needs_verification")
        if dimension_id == "D8":
            allowed.add("school_sensitive_client")
        if not isinstance(item, dict) or not required.issubset(item) or not set(
            item
        ).issubset(allowed):
            raise MatchingContractError(f"{dimension_id} has an invalid shape")

        score = item["score"]
        if score == "not_applicable":
            if dimension_id not in _NOT_APPLICABLE_DIMENSIONS:
                raise MatchingContractError(
                    f"{dimension_id} cannot be not_applicable"
                )
        elif (
            isinstance(score, bool)
            or not isinstance(score, int)
            or not 0 <= score <= 5
        ):
            raise MatchingContractError(
                f"{dimension_id}.score must be an integer from 0 to 5"
            )

        normalized: dict[str, Any] = {
            "score": score,
            "evidence": _nonblank(
                item["evidence"], field=f"{dimension_id}.evidence"
            ),
        }
        if dimension_id == "D7":
            needs = item.get("needs_verification", [])
            if not isinstance(needs, list) or any(
                not isinstance(entry, str) or not entry.strip() for entry in needs
            ):
                raise MatchingContractError(
                    "D7.needs_verification must be a list of non-blank strings"
                )
            normalized["needs_verification"] = tuple(
                entry.strip() for entry in needs
            )
        if dimension_id == "D8":
            sensitive = item.get("school_sensitive_client", False)
            if not isinstance(sensitive, bool):
                raise MatchingContractError(
                    "D8.school_sensitive_client must be boolean"
                )
            normalized["school_sensitive_client"] = sensitive
        dimensions[dimension_id] = normalized
    return dimensions


def _score_band(score: int, bands: Mapping[str, object]) -> str:
    for name in ("strong", "candidate", "conditional", "reject"):
        bounds = bands.get(name)
        if (
            isinstance(bounds, dict)
            and bounds.get("min") <= score <= bounds.get("max")
        ):
            return name
    raise MatchingContractError(f"score {score} is outside configured bands")


def calculate_final_score(payload: Mapping[str, object]) -> dict[str, object]:
    """Validate Stage 3 output and calculate the final score deterministically."""

    if not isinstance(payload, Mapping) or set(payload) - _TOP_LEVEL_KEYS:
        raise MatchingContractError("payload contains unknown fields")
    required = _TOP_LEVEL_KEYS - {"school_weight_enabled"}
    if not required.issubset(payload):
        raise MatchingContractError("payload is missing required fields")
    if payload["contract_version"] != CONTRACT_VERSION:
        raise MatchingContractError("contract_version mismatch")

    total_years = payload["total_years"]
    if (
        isinstance(total_years, bool)
        or not isinstance(total_years, (int, float))
        or not math.isfinite(total_years)
        or total_years < 0
    ):
        raise MatchingContractError("total_years must be a finite non-negative number")
    school_weight_enabled = payload.get("school_weight_enabled", True)
    if not isinstance(school_weight_enabled, bool):
        raise MatchingContractError("school_weight_enabled must be boolean")

    gates = _validate_gates(payload["gates"])
    dimensions = _validate_dimensions(payload["dimensions"])
    contract = _stage4_contract()
    weights = dict(contract["weights"])

    if dimensions["D2"]["score"] == "not_applicable":
        weights["D1"] += weights.pop("D2")
    if dimensions["D6"]["score"] == "not_applicable":
        d6_weight = weights.pop("D6")
        redistribution = contract["redistribution"]["D6_not_applicable"]
        if sum(redistribution.values()) != d6_weight:
            raise MatchingContractError("D6 redistribution does not conserve weight")
        for dimension_id, weight in redistribution.items():
            weights[dimension_id] += weight

    if school_weight_enabled:
        if dimensions["D8"]["school_sensitive_client"]:
            transfer = contract["school_sensitive_client"]
            weights["D8"] += transfer["D8"]
            weights["D1"] += transfer["D1"]
        if total_years >= 10:
            shift = weights["D8"] // 2
            weights["D8"] -= shift
            weights["D1"] += shift

    if sum(weights.values()) != 100:
        raise MatchingContractError("applied weights must sum to 100")

    raw = sum(
        weights[dimension_id] * (dimensions[dimension_id]["score"] / 5)
        for dimension_id in weights
    )
    score = round(raw)
    cap: int | None = None
    if any(gate["verdict"] == "fail" for gate in gates):
        cap = contract["gate_caps"]["fail"]
    elif sum(gate["verdict"] == "uncertain" for gate in gates) >= 2:
        cap = contract["gate_caps"]["uncertain_2_plus"]
    if cap is not None:
        score = min(score, cap)

    return {
        "contract_version": CONTRACT_VERSION,
        "score": score,
        "band": _score_band(score, contract["score_bands"]),
        "gate_cap": cap,
        "weights_applied": weights,
    }
