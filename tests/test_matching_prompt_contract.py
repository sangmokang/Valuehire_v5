from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing.matching_score_contract import (
    MatchingContractError,
    calculate_final_score,
    default_tier_maps,
    evaluate_candidate_contract,
)
from tools.multi_position_sourcing.humansearch import (
    eligible_matches_for_send,
    score_humansearch_contract,
)
from tools.multi_position_sourcing.models import (
    CapturedProfile,
    EmploymentTenure,
    Position,
    PositionMatch,
)


REPO = Path(__file__).resolve().parent.parent
CONTRACT_VERSION = "candidate-match-v2-2026-07-24"


def _contract() -> dict:
    sot = json.loads(
        (REPO / "docs/sot/24-position-jd-sot.json").read_text(encoding="utf-8")
    )
    return sot["evaluation_contract"]["matching_prompt_contract"]


def test_u1_sot24_owns_complete_llm_subscore_contract() -> None:
    contract = _contract()

    assert contract["version"] == CONTRACT_VERSION
    assert contract["llm_must_not_output"] == ["final_score", "score_band"]
    assert contract["llm_invocation"] == {
        "temperature": 0,
        "json_mode": True,
    }
    assert set(contract["stages"]) == {
        "stage_1_jd_structure",
        "stage_2_resume_structure",
        "stage_3_gate_and_dimensions",
        "stage_4_deterministic_total",
    }

    stage3 = contract["stages"]["stage_3_gate_and_dimensions"]
    assert stage3["dimension_ids"] == [f"D{i}" for i in range(1, 9)]
    assert stage3["evidence_required"] is True
    assert stage3["prose_quality_scoring_forbidden"] is True
    assert stage3["gate_verdicts"] == ["pass", "fail", "uncertain"]

    stage4 = contract["stages"]["stage_4_deterministic_total"]
    assert stage4["weights"] == {
        "D1": 27,
        "D2": 10,
        "D3": 14,
        "D4": 9,
        "D5": 7,
        "D6": 10,
        "D7": 14,
        "D8": 9,
    }
    assert stage4["gate_caps"] == {"fail": 49, "uncertain_2_plus": 69}
    assert stage4["senior_10_years_plus"] == {
        "minimum_total_years": 10,
        "source_dimension": "D8",
        "target_dimension": "D1",
        "transfer": "floor_half_current_weight",
    }
    assert stage4["score_bands"] == {
        "strong": {"min": 85, "max": 100},
        "candidate": {"min": 70, "max": 84},
        "conditional": {"min": 50, "max": 69},
        "reject": {"min": 0, "max": 49},
    }


def test_u1_prompt_templates_forbid_direct_total_and_require_json_evidence() -> None:
    contract = _contract()
    prompts = contract["prompt_templates"]

    assert set(prompts) == {"stage_1", "stage_2", "stage_3"}
    for prompt in prompts.values():
        assert "JSON" in prompt

    stage3 = prompts["stage_3"]
    assert "총점을 계산하지 마세요" in stage3
    assert "evidence" in stage3
    assert all(f"D{i}" in stage3 for i in range(1, 9))
    assert "문장력" in stage3
    assert "D6는 not_applicable" in stage3


def test_u1_named_agent_surfaces_resolve_sot24() -> None:
    surfaces = (
        REPO / ".claude/skills/aisearch/SKILL.md",
        REPO / ".claude/skills/humansearch/SKILL.md",
        REPO / ".claude/skills/url/SKILL.md",
        REPO / "skills/ai-search/SKILL.md",
        REPO / "skills/humansearch/SKILL.md",
        REPO / ".codex/skills/ai-search/SKILL.md",
        REPO / ".codex/skills/humansearch/SKILL.md",
        REPO / ".codex/skills/url/SKILL.md",
    )
    for surface in surfaces:
        text = surface.read_text(encoding="utf-8")
        assert "docs/sot/24-position-jd-sot.json" in text, surface
        assert CONTRACT_VERSION in text, surface

    codex_config = json.loads(
        (
            REPO / ".codex/skills/humansearch/humansearch.config.json"
        ).read_text(encoding="utf-8")
    )
    assert codex_config["scoring"]["contract_version"] == CONTRACT_VERSION


def test_u2_active_output_copy_has_no_legacy_rubric_label() -> None:
    source = (
        REPO / "tools/multi_position_sourcing/humansearch_register.py"
    ).read_text(encoding="utf-8")

    assert "학력30·직무50·논리10·이직안정10" not in source
    assert "D1~D8" in source


def test_u2_ai_search_stage6_and_codex_references_use_v2_contract() -> None:
    sot25 = json.loads(
        (
            REPO / "docs/sot/25-ai-search-execution-process.json"
        ).read_text(encoding="utf-8")
    )
    stage6 = next(stage for stage in sot25["stages"] if stage["id"] == "6_evaluation")
    assert stage6["matching_contract_version"] == CONTRACT_VERSION
    assert stage6["scoring_axes"] == [f"D{i}" for i in range(1, 9)]
    assert "final score" not in stage6["llm_output"].lower()

    references = (
        REPO / "skills/ai-search/references/spec-procedure.md",
        REPO / ".codex/skills/ai-search/references/spec-procedure.md",
    )
    for reference in references:
        text = reference.read_text(encoding="utf-8")
        assert CONTRACT_VERSION in text, reference
        assert "D1" in text and "D8" in text, reference
        assert "Score with the SOT 24 axes" not in text, reference


def _payload(
    *,
    score: int = 4,
    verdicts: tuple[str, ...] = ("pass",),
    total_years: float = 5,
) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "gates": [
            {
                "requirement": f"must-{index}",
                "verdict": verdict,
                "evidence": f"resume evidence {index}",
            }
            for index, verdict in enumerate(verdicts, start=1)
        ],
        "dimensions": {
            f"D{index}": {
                "score": score,
                "evidence": f"resume evidence D{index}",
                **(
                    {"needs_verification": []}
                    if index == 7
                    else {"school_sensitive_client": False}
                    if index == 8
                    else {}
                ),
            }
            for index in range(1, 9)
        },
        "total_years": total_years,
    }


def test_u4_calculates_weighted_score_and_band_without_llm_total() -> None:
    result = calculate_final_score(_payload(score=4))

    assert result == {
        "contract_version": CONTRACT_VERSION,
        "score": 80,
        "band": "candidate",
        "gate_cap": None,
        "weights_applied": {
            "D1": 27,
            "D2": 10,
            "D3": 14,
            "D4": 9,
            "D5": 7,
            "D6": 10,
            "D7": 14,
            "D8": 9,
        },
    }


def test_u4_redistributes_not_applicable_dimensions() -> None:
    payload = _payload(score=5)
    payload["dimensions"]["D2"]["score"] = "not_applicable"
    payload["dimensions"]["D6"]["score"] = "not_applicable"

    result = calculate_final_score(payload)

    assert result["score"] == 100
    assert result["weights_applied"] == {
        "D1": 44,
        "D3": 17,
        "D4": 9,
        "D5": 7,
        "D7": 14,
        "D8": 9,
    }


def test_u4_applies_school_sensitive_and_senior_weight_transfers() -> None:
    payload = _payload(score=4, total_years=10)
    payload["dimensions"]["D8"]["school_sensitive_client"] = True

    result = calculate_final_score(payload)

    assert result["score"] == 80
    assert result["weights_applied"]["D8"] == 7
    assert result["weights_applied"]["D1"] == 29
    assert sum(result["weights_applied"].values()) == 100


@pytest.mark.parametrize(
    ("verdicts", "expected_score", "expected_cap", "expected_band"),
    [
        (("fail",), 49, 49, "reject"),
        (("uncertain", "uncertain"), 69, 69, "conditional"),
        (("uncertain",), 100, None, "strong"),
    ],
)
def test_u4_applies_gate_caps(
    verdicts: tuple[str, ...],
    expected_score: int,
    expected_cap: int | None,
    expected_band: str,
) -> None:
    result = calculate_final_score(_payload(score=5, verdicts=verdicts))

    assert result["score"] == expected_score
    assert result["gate_cap"] == expected_cap
    assert result["band"] == expected_band


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(contract_version="stale"),
        lambda payload: payload.update(extra="unknown"),
        lambda payload: payload["dimensions"].pop("D8"),
        lambda payload: payload["dimensions"]["D1"].update(score=6),
        lambda payload: payload["dimensions"]["D1"].update(score=4.5),
        lambda payload: payload["dimensions"]["D1"].update(evidence=" "),
        lambda payload: payload["gates"].append(
            {
                "requirement": "must-1",
                "verdict": "pass",
                "evidence": "duplicate",
            }
        ),
        lambda payload: payload["gates"][0].update(verdict="maybe"),
    ],
)
def test_u4_rejects_inputs_outside_the_contract(mutate) -> None:
    payload = _payload()
    mutate(payload)

    with pytest.raises(MatchingContractError):
        calculate_final_score(payload)


def test_u4_rejects_missing_must_have_gate_evidence() -> None:
    payload = _payload()
    payload["gates"] = []

    with pytest.raises(MatchingContractError, match="at least one"):
        calculate_final_score(payload)


def test_u2_humansearch_builds_only_versioned_final_matches() -> None:
    profile = CapturedProfile(
        profile_url="https://www.linkedin.com/in/contract",
        source_channel="linkedin_rps",
        visible_text="Python API 4년, 처리량 30% 개선",
        summary="backend engineer",
        captured_at="2026-07-24T00:00:00+09:00",
        years_experience=4,
        evidence_paths=("profile.png",),
        employment_history=(EmploymentTenure("A", "2022-01", "present"),),
    )
    position = Position(
        position_id="P1",
        company_name="B",
        role_title="Backend Engineer",
        jd_text="Python 3년 이상",
        seniority_min=3,
        seniority_max=7,
        must_haves=("Python 3년",),
        nice_to_haves=(),
    )
    evaluation = _payload(score=4)

    match = score_humansearch_contract(profile, position, evaluation)

    assert match.score == 80
    assert match.contract_version == CONTRACT_VERSION
    assert set(match.score_breakdown) == {f"D{i}" for i in range(1, 9)}
    assert eligible_matches_for_send((match,)) == (match,)


def test_u3_live_evaluator_runs_stage_1_to_3_and_returns_stage_4_input() -> None:
    profile = CapturedProfile(
        profile_url="https://www.linkedin.com/in/contract",
        source_channel="linkedin_rps",
        visible_text="A사 Python API 4년, 처리량 30% 개선",
        summary="backend engineer",
        captured_at="2026-07-24T00:00:00+09:00",
        years_experience=4,
        education="부산대학교 학사",
    )
    position = Position(
        position_id="P1",
        company_name="B",
        role_title="Backend Engineer",
        jd_text="Python 3년 이상",
        must_haves=("Python 3년",),
    )
    responses = [
        {
            "position_title": "Backend Engineer",
            "must_have": [
                {"type": "skill", "requirement": "Python 3년", "min_years": 3}
            ],
            "nice_to_have": [],
        },
        {"total_years": 4, "careers": [], "skills": [], "achievements": []},
        {
            "gates": [
                {
                    "requirement": "Python 3년",
                    "verdict": "pass",
                    "evidence": "A사 Python API 4년",
                }
            ],
            "dimensions": _payload(score=4)["dimensions"],
            "one_line_verdict": "직무 직결",
        },
    ]
    prompts: list[str] = []

    def fake_llm(prompt: str) -> dict:
        prompts.append(prompt)
        return responses.pop(0)

    evaluation = evaluate_candidate_contract(
        profile,
        position,
        llm_json_client=fake_llm,
        company_tier_map={},
        school_tier_map={},
    )

    assert len(prompts) == 3
    assert "총점을 계산하지 마세요" in prompts[2]
    assert evaluation["contract_version"] == CONTRACT_VERSION
    assert evaluation["total_years"] == 4
    assert calculate_final_score(evaluation)["score"] == 80


def test_u3_default_tier_maps_are_grounded_and_nonempty() -> None:
    company_tiers, school_tiers = default_tier_maps()

    assert company_tiers["naver"] == "high"
    assert school_tiers["서울대"] == "high"


def test_u3_active_humansearch_runner_wires_live_v2_evaluator() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "tools/multi_position_sourcing/humansearch_cdp_run.py"
    ).read_text()

    assert "evaluate_candidate_with_claude" in source
    assert "evaluation_client=evaluate_candidate_with_claude" in source
    assert "evaluation_client=evaluation_client" in source
    assert "evaluation_stage_check" in source
    assert '"evaluation": evaluation' in source


def test_u2_send_gate_rejects_legacy_or_unversioned_total() -> None:
    legacy = PositionMatch(
        candidate_url="https://www.linkedin.com/in/legacy",
        profile_summary="legacy direct total",
        position_id="P1",
        score=99,
        why_fit=("legacy",),
        why_not=(),
        evidence_paths=("legacy.png",),
        score_breakdown={"education": 30, "role_fit": 50},
    )

    assert eligible_matches_for_send((legacy,)) == ()


# --- Stage 1~3 LLM 호출 시간제한 (2026-08-01 라이브 사고) ---
#
# humansearch 링크드인 순회에서 후보 5명 중 2명이
# MatchingContractError("claude matching stage timed out after 60s") 로 유실됐다.
# 이력서 전문(최대 8,000자)+JD 를 넣은 프롬프트는 장비 부하에 따라 60초를 넘긴다.
# 시간제한이 상수로 박혀 있어 현장에서 늘릴 방법이 없었다.

import subprocess as _subprocess

from tools.multi_position_sourcing import matching_score_contract as _msc
from tools.multi_position_sourcing.matching_score_contract import MatchingContractError


def test_matching_stage_timeout_defaults_to_180_seconds(monkeypatch) -> None:
    monkeypatch.delenv("VH_MATCHING_TIMEOUT_SECONDS", raising=False)
    assert _msc.matching_stage_timeout_seconds() == 180.0


def test_matching_stage_timeout_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv("VH_MATCHING_TIMEOUT_SECONDS", "300")
    assert _msc.matching_stage_timeout_seconds() == 300.0


@pytest.mark.parametrize("bad", ["", "abc", "0", "-5", "nan", "inf"])
def test_matching_stage_timeout_rejects_bad_values(monkeypatch, bad: str) -> None:
    monkeypatch.setenv("VH_MATCHING_TIMEOUT_SECONDS", bad)
    with pytest.raises(MatchingContractError):
        _msc.matching_stage_timeout_seconds()


def test_claude_client_passes_the_configured_timeout(monkeypatch) -> None:
    monkeypatch.setenv("VH_MATCHING_TIMEOUT_SECONDS", "240")
    seen: dict[str, object] = {}

    class _Completed:
        returncode = 0
        stdout = '{"ok": true}'
        stderr = ""

    def fake_run(argv, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return _Completed()

    monkeypatch.setattr(_subprocess, "run", fake_run)
    _msc.claude_json_client("prompt")
    assert seen["timeout"] == 240.0


def test_timeout_error_message_reports_the_actual_limit(monkeypatch) -> None:
    monkeypatch.setenv("VH_MATCHING_TIMEOUT_SECONDS", "240")

    def fake_run(argv, **kwargs):
        raise _subprocess.TimeoutExpired(cmd=argv, timeout=240.0)

    monkeypatch.setattr(_subprocess, "run", fake_run)
    with pytest.raises(MatchingContractError) as err:
        _msc.claude_json_client("prompt")
    assert "240" in str(err.value)


# --- Stage 3 게이트 정렬: LLM 표기 흔들림에 후보를 버리지 않는다 (2026-08-01 라이브 사고) ---
#
# 사고: 공간의가치·번개장터 라이브 순회에서 후보 절반이
# "Stage 3 gates must match Stage 1 must-have requirements in order" 로 통째로 버려졌다.
# 원인은 채점이 아니라 계약이었다. stage_3 프롬프트가 "필수요건 문자열을 그대로,
# 같은 순서로 돌려달라"고 지시하지 않는데 코드는 정확일치·동일순서를 요구했다.
# LLM 이 공백/대소문자를 다듬거나 순서를 바꾸면 근거가 멀쩡한 후보도 유실된다.


def _stage_responses(gates: list[dict]) -> list[dict]:
    return [
        {
            "position_title": "Backend Engineer",
            "must_have": [
                {"type": "skill", "requirement": "Python 3년", "min_years": 3},
                {"type": "skill", "requirement": "PostgreSQL", "min_years": None},
            ],
            "nice_to_have": [],
        },
        {"total_years": 4, "careers": [], "skills": [], "achievements": []},
        {
            "gates": gates,
            "dimensions": _payload(score=4)["dimensions"],
            "one_line_verdict": "직무 직결",
        },
    ]


def _run_stages(gates: list[dict]) -> dict:
    profile = CapturedProfile(
        profile_url="https://www.linkedin.com/in/contract",
        source_channel="linkedin_rps",
        visible_text="A사 Python API 4년, PostgreSQL 운영",
        summary="backend engineer",
        captured_at="2026-07-24T00:00:00+09:00",
        years_experience=4,
        education="부산대학교 학사",
    )
    position = Position(
        position_id="P1",
        company_name="B",
        role_title="Backend Engineer",
        jd_text="Python 3년 이상, PostgreSQL",
        must_haves=("Python 3년", "PostgreSQL"),
    )
    responses = _stage_responses(gates)
    return evaluate_candidate_contract(
        profile,
        position,
        llm_json_client=lambda prompt: responses.pop(0),
        company_tier_map={},
        school_tier_map={},
    )


def test_stage3_gates_survive_cosmetic_whitespace_and_case_drift() -> None:
    """공백·대소문자만 다른 표기는 같은 요건이다 — 후보를 버리지 않는다."""
    evaluation = _run_stages(
        [
            {"requirement": " Python  3년 ", "verdict": "pass", "evidence": "Python API 4년"},
            {"requirement": "postgresql", "verdict": "pass", "evidence": "PostgreSQL 운영"},
        ]
    )

    # 저장되는 값은 Stage 1 의 정본 표기로 정규화된다(하류 비교가 흔들리지 않게).
    assert [gate["requirement"] for gate in evaluation["gates"]] == [
        "Python 3년",
        "PostgreSQL",
    ]


def test_stage3_gates_are_reordered_to_stage1_order() -> None:
    """순서만 뒤바뀐 응답은 Stage 1 순서로 되돌린다 — 유실 사유가 아니다."""
    evaluation = _run_stages(
        [
            {"requirement": "PostgreSQL", "verdict": "uncertain", "evidence": "간접"},
            {"requirement": "Python 3년", "verdict": "pass", "evidence": "Python API 4년"},
        ]
    )

    assert [gate["requirement"] for gate in evaluation["gates"]] == [
        "Python 3년",
        "PostgreSQL",
    ]
    assert [gate["verdict"] for gate in evaluation["gates"]] == ["pass", "uncertain"]


def test_stage3_missing_or_extra_gate_still_fails_closed() -> None:
    """진짜로 요건이 빠지거나 남으면 여전히 fail-closed — 검증을 약화하지 않는다."""
    with pytest.raises(MatchingContractError):
        _run_stages(
            [
                {"requirement": "Python 3년", "verdict": "pass", "evidence": "Python API 4년"},
            ]
        )


def test_stage3_prompt_orders_llm_to_copy_must_have_verbatim() -> None:
    """근본 예방: 프롬프트가 '그대로 복사, 같은 순서'를 명시해야 한다."""
    stage3_prompt = _contract()["prompt_templates"]["stage_3"]

    assert "must_have" in stage3_prompt
    assert "그대로" in stage3_prompt
    assert "같은 순서" in stage3_prompt


def test_stage3_duplicate_requirement_keys_do_not_change_the_score() -> None:
    """Stage 1 이 사실상 같은 요건을 두 번 낸 병리 케이스에서도 총점은 흔들리지 않는다.

    "Python"/"python" 처럼 정규화하면 같은 키가 되는 요건이 둘이면 verdict 를 어느 쪽에
    붙일지는 원리적으로 정할 수 없다. 그래도 verdict **멀티셋**은 보존되므로 하드제외와
    총점은 동일하다 — 예전처럼 후보를 통째로 버리는 것보다 낫다는 것을 여기서 고정한다.
    """
    profile = CapturedProfile(
        profile_url="https://www.linkedin.com/in/dup",
        source_channel="linkedin_rps",
        visible_text="A사 Python API 4년",
        summary="backend engineer",
        captured_at="2026-07-24T00:00:00+09:00",
        years_experience=4,
        education="부산대학교 학사",
    )
    position = Position(
        position_id="P1",
        company_name="B",
        role_title="Backend Engineer",
        jd_text="Python",
        must_haves=("Python", "python"),
    )

    def _run(gates: list[dict]) -> int:
        responses = [
            {
                "position_title": "Backend Engineer",
                "must_have": [
                    {"type": "skill", "requirement": "Python", "min_years": None},
                    {"type": "skill", "requirement": "python", "min_years": None},
                ],
                "nice_to_have": [],
            },
            {"total_years": 4, "careers": [], "skills": [], "achievements": []},
            {
                "gates": gates,
                "dimensions": _payload(score=4)["dimensions"],
                "one_line_verdict": "v",
            },
        ]
        evaluation = evaluate_candidate_contract(
            profile,
            position,
            llm_json_client=lambda prompt: responses.pop(0),
            company_tier_map={},
            school_tier_map={},
        )
        assert [gate["requirement"] for gate in evaluation["gates"]] == ["Python", "python"]
        return calculate_final_score(evaluation)["score"]

    forward = _run(
        [
            {"requirement": "Python", "verdict": "pass", "evidence": "e2"},
            {"requirement": "python", "verdict": "fail", "evidence": "e1"},
        ]
    )
    reversed_ = _run(
        [
            {"requirement": "python", "verdict": "fail", "evidence": "e1"},
            {"requirement": "Python", "verdict": "pass", "evidence": "e2"},
        ]
    )

    assert forward == reversed_


def test_stage3_distinct_requirements_are_never_merged_by_normalization() -> None:
    """의미가 다른 표기는 절대 같은 요건으로 합쳐지지 않는다(정규화 과잉 방지)."""
    from tools.multi_position_sourcing.matching_score_contract import _gate_key

    assert _gate_key("5년 이상") != _gate_key("5년이상")
    assert _gate_key("Python 3년") != _gate_key("Python 3 년")
    # 반대로 전각·공백·대소문자만 다른 것은 같은 요건이다.
    assert _gate_key("Ｐython") == _gate_key("Python")
    assert _gate_key("Python  3년") == _gate_key("python 3년")


# --- D2/D6 not_applicable 표기: 후보를 통째로 버리지 않는다 (2026-08-01 라이브 사고) ---
#
# 사고: 게이트 정렬을 고치자 곧바로 "D6 has an invalid shape" 로 후보가 다시 유실됐다.
# 라이브 LLM 응답을 직접 받아 확인한 실제 값(2026-08-01 재현):
#     "D2": "not_applicable", "D6": "not_applicable"
# 즉 LLM 은 not_applicable 을 **차원 값 자체**로 낸다. stage_3 프롬프트가
# "D2는 not_applicable ... D6는 not_applicable로 출력하세요" 라고 지시하니 자연스러운 해석인데,
# 코드는 {"score": "not_applicable", "evidence": ...} 객체만 받아 예외를 던졌다.


def test_dimension_bare_not_applicable_string_is_accepted_for_d2_and_d6() -> None:
    """D2·D6 는 문자열 not_applicable 로 와도 객체로 정규화해 받는다."""
    payload = _payload(score=4)
    payload["dimensions"]["D2"] = "not_applicable"
    payload["dimensions"]["D6"] = "not_applicable"

    result = calculate_final_score(payload)

    assert result["dimensions"]["D2"]["score"] == "not_applicable"
    assert result["dimensions"]["D6"]["score"] == "not_applicable"
    # 근거 문구는 코드가 소유한다 — LLM 이 안 준 자리를 지어내지 않는다.
    assert result["dimensions"]["D2"]["evidence"]
    assert result["dimensions"]["D6"]["evidence"]


def test_bare_not_applicable_is_rejected_for_dimensions_that_cannot_skip() -> None:
    """D1 등 건너뛸 수 없는 차원은 문자열로 와도 그대로 fail-closed."""
    payload = _payload(score=4)
    payload["dimensions"]["D1"] = "not_applicable"

    with pytest.raises(MatchingContractError):
        calculate_final_score(payload)


def test_other_bare_strings_are_still_rejected() -> None:
    """not_applicable 이 아닌 문자열은 계속 거부한다(검증 약화 금지)."""
    payload = _payload(score=4)
    payload["dimensions"]["D6"] = "unknown"

    with pytest.raises(MatchingContractError):
        calculate_final_score(payload)


def test_stage3_prompt_states_not_applicable_is_the_score_value() -> None:
    """근본 예방: not_applicable 은 score 의 값이며 객체 형태를 유지해야 한다고 명시."""
    stage3_prompt = _contract()["prompt_templates"]["stage_3"]

    assert "score" in stage3_prompt
    assert "not_applicable" in stage3_prompt
    assert '"score":"not_applicable"' in stage3_prompt.replace(" ", "")
