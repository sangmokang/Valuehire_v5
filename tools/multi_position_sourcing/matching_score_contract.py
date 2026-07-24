"""Deterministic Stage 4 for candidate-match-v2-2026-07-24.

The LLM owns extraction, gates, and evidence-backed D1-D8 subscores. This
module validates that output and is the only layer allowed to calculate the
final 0-100 score and action band.
"""

from __future__ import annotations

import json
import math
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping


CONTRACT_VERSION = "candidate-match-v2-2026-07-24"
DIMENSION_IDS = tuple(f"D{index}" for index in range(1, 9))
_TOP_LEVEL_KEYS = {
    "contract_version",
    "gates",
    "dimensions",
    "total_years",
}
_VERDICTS = {"pass", "fail", "uncertain"}
_NOT_APPLICABLE_DIMENSIONS = {"D2", "D6"}


class MatchingContractError(ValueError):
    """Raised when Stage 3 output is outside the versioned contract."""


@lru_cache(maxsize=1)
def _matching_contract() -> dict[str, Any]:
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
        return contract
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise MatchingContractError(f"cannot load matching contract: {path}") from exc


def _stage4_contract() -> dict[str, Any]:
    return _matching_contract()["stages"]["stage_4_deterministic_total"]


def _nonblank(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MatchingContractError(f"{field} must be a non-blank string")
    return value.strip()


def _validate_gates(value: object) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        raise MatchingContractError("gates must be a list")
    if not value:
        raise MatchingContractError("gates must contain at least one must-have")
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
        if not isinstance(bounds, dict):
            raise MatchingContractError(f"score band {name} is malformed")
        minimum = bounds.get("min")
        maximum = bounds.get("max")
        if (
            isinstance(minimum, bool)
            or isinstance(maximum, bool)
            or not isinstance(minimum, int)
            or not isinstance(maximum, int)
        ):
            raise MatchingContractError(f"score band {name} bounds are malformed")
        if minimum <= score <= maximum:
            return name
    raise MatchingContractError(f"score {score} is outside configured bands")


def calculate_final_score(payload: Mapping[str, object]) -> dict[str, object]:
    """Validate Stage 3 output and calculate the final score deterministically."""

    if not isinstance(payload, Mapping) or set(payload) - _TOP_LEVEL_KEYS:
        raise MatchingContractError("payload contains unknown fields")
    if not _TOP_LEVEL_KEYS.issubset(payload):
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


def claude_json_client(prompt: str, *, model: str = "haiku") -> dict[str, object]:
    """Run one temperature-zero-equivalent local Claude JSON extraction step."""

    # Import lazily: when a sibling runner is executed by path, its directory
    # contains selectors.py and would otherwise shadow the stdlib module.
    module_dir = str(Path(__file__).resolve().parent)
    removed = [entry for entry in sys.path if str(Path(entry or ".").resolve()) == module_dir]
    sys.path[:] = [
        entry for entry in sys.path if str(Path(entry or ".").resolve()) != module_dir
    ]
    try:
        import subprocess
    finally:
        sys.path[:0] = removed

    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    completed = subprocess.run(
        ["claude", "-p", "--model", model, prompt],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    if completed.returncode != 0:
        raise MatchingContractError(
            f"claude matching stage failed: {(completed.stderr or '')[:240]}"
        )
    raw = completed.stdout.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise MatchingContractError("claude matching stage returned no JSON object")
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise MatchingContractError("claude matching stage returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise MatchingContractError("claude matching stage JSON must be an object")
    return parsed


def evaluate_candidate_contract(
    profile: object,
    position: object,
    *,
    llm_json_client: Callable[[str], dict[str, object]] = claude_json_client,
    company_tier_map: Mapping[str, object] | None = None,
    school_tier_map: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Execute SOT Stage 1-3 and return the validated Stage 4 input payload."""

    templates = _matching_contract()["prompt_templates"]
    jd_text = str(getattr(position, "jd_text", "") or "")
    resume_text = "\n".join(
        part
        for part in (
            str(getattr(profile, "visible_text", "") or ""),
            str(getattr(profile, "summary", "") or ""),
            str(getattr(profile, "education", "") or ""),
        )
        if part.strip()
    )
    if not jd_text.strip() or not resume_text.strip():
        raise MatchingContractError("JD and resume source text are required")

    jd_json = llm_json_client(templates["stage_1"].format(jd_raw_text=jd_text))
    resume_json = llm_json_client(
        templates["stage_2"].format(resume_raw_text=resume_text)
    )
    stage3 = llm_json_client(
        templates["stage_3"].format(
            jd_json=json.dumps(jd_json, ensure_ascii=False),
            resume_json=json.dumps(resume_json, ensure_ascii=False),
            company_tier_map=json.dumps(company_tier_map or {}, ensure_ascii=False),
            school_tier_map=json.dumps(school_tier_map or {}, ensure_ascii=False),
        )
    )
    evaluation: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "gates": stage3.get("gates"),
        "dimensions": stage3.get("dimensions"),
        "total_years": resume_json.get("total_years"),
    }

    must_have = jd_json.get("must_have")
    if not isinstance(must_have, list) or not must_have:
        raise MatchingContractError("Stage 1 must return at least one must-have")
    expected = [
        str(item.get("requirement", "")).strip()
        for item in must_have
        if isinstance(item, dict)
    ]
    gates = evaluation["gates"]
    actual = (
        [
            str(item.get("requirement", "")).strip()
            for item in gates
            if isinstance(item, dict)
        ]
        if isinstance(gates, list)
        else []
    )
    if not expected or actual != expected:
        raise MatchingContractError(
            "Stage 3 gates must match Stage 1 must-have requirements in order"
        )
    calculate_final_score(evaluation)
    return evaluation


def evaluate_candidate_with_claude(
    profile: object,
    position: object,
) -> dict[str, object]:
    """Production adapter used by the live Human Search traversal."""

    return evaluate_candidate_contract(profile, position)
