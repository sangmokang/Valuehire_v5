from __future__ import annotations

import json
from pathlib import Path


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
    )
    for surface in surfaces:
        text = surface.read_text(encoding="utf-8")
        assert "docs/sot/24-position-jd-sot.json" in text, surface
        assert CONTRACT_VERSION in text, surface

