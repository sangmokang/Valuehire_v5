"""Deterministic Stage 4 for candidate-match-v2-2026-07-24.

The LLM owns extraction, gates, and evidence-backed D1-D8 subscores. This
module validates that output and is the only layer allowed to calculate the
final 0-100 score and action band.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import unicodedata
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
# 차원을 건너뛸 때 코드가 채우는 고정 근거 문구. 모델이 근거를 지어내지 못하게 코드가 소유한다.
_NOT_APPLICABLE_EVIDENCE = "해당 없음 — 비교할 근거가 JD/이력서/티어맵에 없어 이 차원은 채점에서 제외"
# D7 이 boolean 으로 올 때 코드가 채우는 고정 문구. 확인 항목을 모델이 지어내지 않게 한다.
_NEEDS_VERIFICATION_UNSPECIFIED = "확인 필요 항목 미지정 — 사람이 직접 확인"


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


def _gate_key(value: object) -> str:
    """필수요건 문자열의 표기 흔들림을 흡수한 비교용 키.

    Stage 3 는 Stage 1 의 요건을 그대로 돌려주는 것이 계약이지만, LLM 은 공백을
    다듬거나 대소문자를 바꾸는 정도의 흔들림을 낸다. 그 정도로 후보를 버리면
    근거가 멀쩡한 사람이 유실된다(2026-08-01 라이브). 의미가 달라지는 차이는
    그대로 남겨 fail-closed 가 유지되도록, 유니코드 정규화·소문자화·공백 축약만 한다.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.casefold().split())


def _validate_gates(value: object) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        raise MatchingContractError("gates must be a list")
    if not value:
        raise MatchingContractError("gates must contain at least one must-have")
    gates: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        # 필요한 세 필드가 있으면 받는다. LLM 이 min_years·note 같은 키를 하나 더 붙였다고
        # 근거가 멀쩡한 후보를 버리지 않는다(2026-08-01 라이브). 세 필드의 의미 검증
        # (비어있지 않은 요건·정해진 verdict·비어있지 않은 근거)은 아래에서 그대로 한다.
        required = {"requirement", "verdict", "evidence"}
        if not isinstance(item, dict) or not required.issubset(item):
            saw = sorted(item) if isinstance(item, dict) else type(item).__name__
            missing = sorted(required - set(item)) if isinstance(item, dict) else sorted(required)
            raise MatchingContractError(
                f"gates[{index}] has an invalid shape — 빠진 필드: {missing}, 받은 키: {saw}"
            )
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


def _integral_score(value: object) -> int | None:
    """0~5 정수와 **정확히 같은 값**이면 그 정수를, 아니면 None 을 돌려준다.

    LLM 은 같은 점수를 4, 4.0, "4" 로 번갈아 낸다. 표기가 달라도 값이 같으면 같은 점수이므로
    후보를 버릴 이유가 없다. 반대로 4.5 처럼 정수가 아니거나 범위를 벗어나면 반올림해서
    받아주지 않는다 — 없는 판단을 코드가 만들어내는 셈이 되기 때문이다(fail-closed 유지).
    bool 은 int 서브클래스라 True 가 1점으로 새지 않게 먼저 막는다.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number: float = value
    elif isinstance(value, float):
        number = value
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if number != int(number):
        return None
    result = int(number)
    return result if 0 <= result <= 5 else None


def _validate_dimensions(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != set(DIMENSION_IDS):
        raise MatchingContractError("dimensions must contain D1-D8 exactly once")

    dimensions: dict[str, dict[str, Any]] = {}
    for dimension_id in DIMENSION_IDS:
        item = value[dimension_id]
        # LLM 은 건너뛸 수 있는 차원을 객체가 아니라 문자열 "not_applicable" 로 낸다
        # (2026-08-01 라이브 응답 실측). 프롬프트가 그렇게 읽히기 때문이며, 그 표기 하나로
        # 후보를 통째로 버리지 않는다. 근거 문구는 지어내지 않고 코드가 소유한 고정 문구를 쓴다.
        if item == "not_applicable" and dimension_id in _NOT_APPLICABLE_DIMENSIONS:
            item = {
                "score": "not_applicable",
                "evidence": _NOT_APPLICABLE_EVIDENCE,
            }
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
        else:
            coerced = _integral_score(score)
            if coerced is None:
                # 값과 타입을 남긴다 — 간헐적 표기 흔들림은 다음 발생이 곧 증거여야 한다.
                raise MatchingContractError(
                    f"{dimension_id}.score must be an integer from 0 to 5: "
                    f"{score!r} ({type(score).__name__})"
                )
            score = coerced

        normalized: dict[str, Any] = {
            "score": score,
            "evidence": _nonblank(
                item["evidence"], field=f"{dimension_id}.evidence"
            ),
        }
        if dimension_id == "D7":
            needs = item.get("needs_verification", [])
            # 라이브 LLM 은 이름 그대로 boolean 을 낸다(2026-08-01 실측: true).
            # 그 표기 하나로 후보를 버리지 않되, 확인 항목을 지어내지 않고
            # 코드가 소유한 고정 문구로 바꾼다.
            if isinstance(needs, bool):
                needs = [_NEEDS_VERIFICATION_UNSPECIFIED] if needs else []
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
        d2_weight = weights.pop("D2")
        redistribution = contract["redistribution"]["D2_not_applicable"]
        if sum(redistribution.values()) != d2_weight:
            raise MatchingContractError("D2 redistribution does not conserve weight")
        for dimension_id, weight in redistribution.items():
            weights[dimension_id] += weight
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
    senior = contract["senior_10_years_plus"]
    if (
        not isinstance(senior, dict)
        or senior.get("transfer") != "floor_half_current_weight"
    ):
        raise MatchingContractError("senior weight transfer is malformed")
    if total_years >= senior["minimum_total_years"]:
        source = senior["source_dimension"]
        target = senior["target_dimension"]
        shift = weights[source] // 2
        weights[source] -= shift
        weights[target] += shift

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


MATCHING_STAGE_TIMEOUT_ENV = "VH_MATCHING_TIMEOUT_SECONDS"
DEFAULT_MATCHING_STAGE_TIMEOUT_SECONDS = 180.0


def matching_stage_timeout_seconds() -> float:
    """Stage 1~3 LLM 호출 시간제한(초).

    2026-08-01 라이브 사고: 60초 고정이라 이력서 전문(최대 8,000자)+JD 프롬프트가
    장비 부하에서 초과해 후보가 채점 없이 유실됐다. 운영 중 조정할 수 있어야 한다.
    값이 없거나 숫자가 아니거나 0 이하·유한하지 않으면 조용히 기본값으로 넘어가지
    않고 fail-closed 로 거부한다(잘못된 설정이 무한 대기로 둔갑하지 않도록).
    """
    raw = os.environ.get(MATCHING_STAGE_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_MATCHING_STAGE_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise MatchingContractError(
            f"{MATCHING_STAGE_TIMEOUT_ENV} 는 초 단위 숫자여야 함: {raw!r}"
        ) from exc
    if not math.isfinite(value) or value <= 0:
        raise MatchingContractError(
            f"{MATCHING_STAGE_TIMEOUT_ENV} 는 0보다 큰 유한한 값이어야 함: {raw!r}"
        )
    return value


# 추출 호출 전용 시스템 프롬프트. 에이전트 지침(CLAUDE.md·스킬)을 대체해 되묻기·설명·
# 도구사용을 막는다. 영어로 두는 이유는 CLI 기본 지침과 섞였을 때도 우선순위가 분명하기 때문.
_MATCHING_SYSTEM_PROMPT = (
    "You are a strict JSON extraction function, not an assistant. "
    "Read the user message and reply with exactly one JSON object and nothing else. "
    "Never ask a clarifying question. Never explain. Never use tools. "
    "Never read or write files. Never emit markdown fences or prose."
)
# 설명만 돌아오는 일시적 흔들림에 대비한 시도 횟수(재시도 1회). 무한 재시도는 하지 않는다.
_MATCHING_LLM_ATTEMPTS = 2


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

    timeout_seconds = matching_stage_timeout_seconds()
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)

    # 이 호출은 '에이전트에게 일을 시키는' 것이 아니라 순수 추출 함수다. 기본 시스템
    # 프롬프트를 그대로 두면 프로젝트·전역 CLAUDE.md 와 스킬이 실려서 추출 요청을 작업
    # 지시로 읽고 되묻는다 — JSON 이 없으니 그 후보가 통째로 버려진다(2026-08-01 라이브).
    # 그래서 지침을 대체하고, 저장소 밖 빈 디렉터리에서 실행한다.
    last_error = "claude matching stage returned no JSON object"
    for attempt in range(_MATCHING_LLM_ATTEMPTS):
        try:
            with tempfile.TemporaryDirectory(prefix="vh-matching-") as workdir:
                completed = subprocess.run(
                    [
                        "claude", "-p",
                        "--model", model,
                        "--system-prompt", _MATCHING_SYSTEM_PROMPT,
                        prompt,
                    ],
                    cwd=workdir,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=timeout_seconds,
                )
        except FileNotFoundError as exc:
            raise MatchingContractError("claude CLI is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise MatchingContractError(
                f"claude matching stage timed out after {timeout_seconds:g}s"
            ) from exc
        if completed.returncode != 0:
            raise MatchingContractError(
                f"claude matching stage failed: {(completed.stderr or '')[:240]}"
            )
        raw = (completed.stdout or "").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < start:
            # 일시적 흔들림(설명만 오는 응답)은 한 번 더 시도한다. 무한 재시도는 하지 않는다.
            last_error = "claude matching stage returned no JSON object"
            continue
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            last_error = "claude matching stage returned invalid JSON"
            continue
        if not isinstance(parsed, dict):
            last_error = "claude matching stage JSON must be an object"
            continue
        return parsed
    raise MatchingContractError(last_error)


def default_tier_maps() -> tuple[dict[str, str], dict[str, str]]:
    """Return the repository-owned deterministic tier signals for Stage 3."""

    from .scoring import HIGH_TIER_COMPANY_SIGNALS, HIGH_TIER_SCHOOL_SIGNALS

    return (
        {name: "high" for name in sorted(HIGH_TIER_COMPANY_SIGNALS)},
        {name: "high" for name in sorted(HIGH_TIER_SCHOOL_SIGNALS)},
    )


def assert_live_evaluator_ready() -> None:
    if shutil.which("claude") is None:
        raise MatchingContractError("claude CLI is required for live candidate-match-v2")


def evaluate_candidate_contract(
    profile: object,
    position: object,
    *,
    llm_json_client: Callable[[str], dict[str, object]] = claude_json_client,
    company_tier_map: Mapping[str, object] | None = None,
    school_tier_map: Mapping[str, object] | None = None,
    stage_boundary_check: Callable[[], None] | None = None,
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

    if stage_boundary_check is not None:
        stage_boundary_check()
    jd_json = llm_json_client(templates["stage_1"].format(jd_raw_text=jd_text))
    if stage_boundary_check is not None:
        stage_boundary_check()
    resume_json = llm_json_client(
        templates["stage_2"].format(resume_raw_text=resume_text)
    )
    if stage_boundary_check is not None:
        stage_boundary_check()
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
    gates = evaluation["gates"] if isinstance(evaluation["gates"], list) else []
    if not expected:
        raise MatchingContractError(
            "Stage 3 gates must match Stage 1 must-have requirements in order"
        )
    # 요건 **집합**이 같으면 같은 심사다. 공백·대소문자·순서만 다른 표기 때문에 근거가
    # 멀쩡한 후보를 통째로 버리지 않는다(2026-08-01 라이브: 후보 절반 유실). 대신
    # 저장값은 Stage 1 정본 표기·정본 순서로 되돌려 하류 비교가 흔들리지 않게 한다.
    # 요건이 빠지거나 남거나 짝이 안 맞으면 지금까지처럼 fail-closed 다.
    remaining: dict[str, list[dict]] = {}
    for item in gates:
        if not isinstance(item, dict):
            raise MatchingContractError(
                "Stage 3 gates must match Stage 1 must-have requirements in order"
            )
        remaining.setdefault(_gate_key(item.get("requirement")), []).append(item)
    aligned: list[dict] = []
    for requirement in expected:
        bucket = remaining.get(_gate_key(requirement))
        if not bucket:
            raise MatchingContractError(
                "Stage 3 gates must match Stage 1 must-have requirements in order"
            )
        item = dict(bucket.pop(0))
        item["requirement"] = requirement
        aligned.append(item)
    if any(bucket for bucket in remaining.values()):
        raise MatchingContractError(
            "Stage 3 gates must match Stage 1 must-have requirements in order"
        )
    evaluation["gates"] = aligned
    calculate_final_score(evaluation)
    return evaluation


def evaluate_candidate_with_claude(
    profile: object,
    position: object,
    *,
    stage_boundary_check: Callable[[], None] | None = None,
) -> dict[str, object]:
    """Production adapter used by the live Human Search traversal."""

    company_tiers, school_tiers = default_tier_maps()
    return evaluate_candidate_contract(
        profile,
        position,
        company_tier_map=company_tiers,
        school_tier_map=school_tiers,
        stage_boundary_check=stage_boundary_check,
    )
