from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing.matching_score_contract import (
    MatchingContractError,
    calculate_final_score,
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
