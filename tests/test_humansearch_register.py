"""Harness Gate 4 — PC-C1a1: register dict → CapturedProfile 재구성 어댑터 (RED 먼저).

목적: 러너/results.json 의 dict 를 하드제외 판정용 CapturedProfile 로 되살린다.
  - 가용 필드(education·employment_history[EmploymentTenure]·visible_text·summary) 복원.
  - fail-closed: 하드제외를 신뢰성 있게 판정할 수 없는 결손 dict 는 None(→ 호출자가 '제외'로 처리).
  - 무손실 아님(ocr_text 등 원본 dict 에 없을 수 있음) — 가용 필드만 복원(2차검증 V2 재정의).
  - SOT: fail-open 금지 · models.CapturedProfile 재사용(제2 프로필 타입 금지).

각 단언은 "일부러 깨면 RED, 실제면 GREEN".
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.multi_position_sourcing import humansearch_register as register_module
from tools.multi_position_sourcing.humansearch import hard_exclude_reason
from tools.multi_position_sourcing.humansearch_register import (
    FY26_AI_SEARCH_LIST_ID,
    FY26_AI_SEARCH_LIST_URL,
    PROFILE_SAVE_EVIDENCE_FIELDS,
    _candidate_task_description,
    _candidate_spec_evaluation,
    _parent_task_description,
    candidate_spec_hook_cli,
    candidate_spec_hook_reason,
    clickup_registration_eligible,
    eligible,
    has_required_candidate_output_fields,
    has_saved_profile_evidence,
    reconstruct_captured_profile,
    register_clickup_fy26_ai_search,
)
from tools.multi_position_sourcing.models import CapturedProfile, EmploymentTenure


def _contract_evaluation(score: int = 4) -> dict:
    return {
        "contract_version": "candidate-match-v2-2026-07-24",
        "gates": [
            {
                "requirement": "Python 실무",
                "verdict": "pass",
                "evidence": "A사 Python 백엔드",
            }
        ],
        "dimensions": {
            f"D{i}": {
                "score": score,
                "evidence": f"resume evidence D{i}",
                **({"needs_verification": []} if i == 7 else {}),
                **({"school_sensitive_client": False} if i == 8 else {}),
            }
            for i in range(1, 9)
        },
        "total_years": 8,
    }


def _runner_dict(**over) -> dict:
    """humansearch_cdp_run.py 가 실제로 내보내는 results 항목 형상."""
    d = {
        "idx": 1,
        "name": "홍길동",
        "url": "https://www.saramin.co.kr/profile/1",
        "otw": False,
        "headline": "Backend Engineer",
        "education": "부산대학교 학사",
        "score": 80,
        "breakdown": {f"D{i}": 4 for i in range(1, 9)},
        "contract_version": "candidate-match-v2-2026-07-24",
        "evaluation": _contract_evaluation(),
        "why_fit": ["must-have 직결: python"],
        "why_not": [],
        "screenshot": "/x/1.png",
        "summary": "백엔드 8년",
        "visible_text": "python backend engineer, 안정적 경력",
        "skills": ["python", "backend"],
        "employment_history": [
            {"company": "A", "start_month": "2018-01", "end_month": "2024-06"},
        ],
    }
    d.update(over)
    return d


def _with_structured_evidence(
    candidate: dict, *, position_id: str = "86abc", channel: str = "linkedin_rps"
) -> dict:
    result = dict(candidate)
    result["evidence"] = {
        "status": "saved",
        "capture_status": "saved",
        "site": channel,
        "task": "humansearch",
        "mode": "profile",
        "profile_url": result["url"],
        "position_id": position_id,
        "manifest_path": "/private/valuehire-test/manifest.json",
        "screenshot_sha256": "a" * 64,
    }
    return result


_ESCAPED_SHORT_HISTORY = [
    {"company": "FreelancerCoin", "start_month": "2017-11", "end_month": "2018-06"},
    {"company": "tutto", "start_month": "2017-06", "end_month": "2018-03"},
    {"company": "o2palm", "start_month": "2016-11", "end_month": "2017-04"},
    {"company": "treport", "start_month": "2016-08", "end_month": "2016-11"},
]


def _linkedin_raw(*ranges: str) -> str:
    return "Experience\n" + "\n".join(
        f"Dates employed and Duration\n{date_range} • duration" for date_range in ranges
    )


def _hook_event(
    *, model: str, tool_name: str, description: str, description_key: str = "description"
) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "model": model,
        "tool_name": tool_name,
        "tool_input": {
            "list_id": FY26_AI_SEARCH_LIST_ID,
            "parent": "86ey7gzp5",
            "name": "Candidate — 87 strong recommendation",
            description_key: description,
        },
    }


@pytest.mark.parametrize(
    ("model", "tool_name", "description_key"),
    [
        ("claude-opus-4-8", "mcp__claude_ai_ClickUp__clickup_create_task", "markdown_description"),
        ("gpt-5.6", "mcp__clickup__clickup_create_task", "description"),
    ],
)
def test_candidate_spec_hook_blocks_escaped_short_tenure_for_both_engines(
    model: str, tool_name: str, description_key: str
) -> None:
    escaped = _with_structured_evidence(_runner_dict(
        name="DongJun Kwon",
        url="https://www.linkedin.com/talent/profile/escaped-short-tenure",
        score=87,
        summary="AI Solutions Architect and full-stack engineer",
        visible_text=_linkedin_raw(
            "Nov 2017 – Jun 2018",
            "Jun 2017 – Mar 2018",
            "Nov 2016 – Apr 2017",
            "Aug 2016 – Nov 2016",
        ),
        employment_history=_ESCAPED_SHORT_HISTORY,
    ), position_id="bist-pool")
    description = _candidate_task_description(
        escaped, position_id="bist-pool", channel="linkedin_rps"
    )
    event = _hook_event(
        model=model,
        tool_name=tool_name,
        description=description,
        description_key=description_key,
    )

    assert candidate_spec_hook_reason(event) == "frequent_job_change"
    assert candidate_spec_hook_cli(json.dumps(event)) == (2, "frequent_job_change")


def test_candidate_spec_hook_fails_closed_on_exact_manual_bypass_shape() -> None:
    manual_description = """- **profile_url**: https://www.linkedin.com/talent/profile/manual-bypass
- **score**: 87 (strong recommendation)
- **why_fit**: AI solutions architect
- **profile_summary**: RAG and LLM Agent
- **evidence**: SQLite ai_search_candidates + Supabase profile_archives"""
    event = _hook_event(
        model="claude-opus-4-8",
        tool_name="mcp__claude_ai_ClickUp__clickup_create_task",
        description=manual_description,
    )

    raw = json.dumps(event)
    assert candidate_spec_hook_cli(raw) == (2, "candidate_spec_missing")
    script = Path(__file__).resolve().parents[1] / "tools/multi_position_sourcing/humansearch_register.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--candidate-spec-hook"],
        input=raw,
        text=True,
        capture_output=True,
        check=False,
    )
    assert (completed.returncode, completed.stderr.strip()) == (2, "candidate_spec_missing")
    score_only_update = {
        "hook_event_name": "PreToolUse",
        "tool_name": "mcp__clickup__clickup_update_task",
        "tool_input": {"task_id": "86ey7gzrr", "name": "Candidate — 99점 강력추천"},
    }
    assert candidate_spec_hook_cli(json.dumps(score_only_update)) == (2, "candidate_spec_missing")
    for tool_name, tool_input, reason in (
        ("mcp__clickup__clickup_create_task", {"list_id": FY26_AI_SEARCH_LIST_ID, "name": "홍길동 후보"}, "candidate_parent_missing"),
        ("mcp__clickup__clickup_update_task", {"task_id": "86ey7gzrr", "name": "홍길동 후보"}, "candidate_spec_missing"),
    ):
        assert candidate_spec_hook_cli(json.dumps({
            "hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input,
        })) == (2, reason)
    parent_description = _parent_task_description(
        position_name="홍길동", position_id="position-1", channel="linkedin_rps"
    )
    for name, description in (
        ("홍길동 — AI Search", parent_description +
         "\nProfile: https://www.linkedin.com/talent/profile/disguised\n점수: 99/100"),
        ("홍길동", "AI Engineer"),
    ):
        disguised = {
            "hook_event_name": "PreToolUse",
            "tool_name": "mcp__clickup__clickup_create_task",
            "tool_input": {
                "list_id": FY26_AI_SEARCH_LIST_ID, "name": name, "description": description,
            },
        }
        assert candidate_spec_hook_cli(json.dumps(disguised)) == (2, "candidate_parent_missing")
    extra_fields = {
        "hook_event_name": "PreToolUse",
        "tool_name": "mcp__clickup__clickup_create_task",
        "tool_input": {
            "list_id": FY26_AI_SEARCH_LIST_ID,
            "name": "홍길동 — AI Search",
            "description": parent_description,
            "custom_fields": [
                {"id": "profile", "value": "https://www.linkedin.com/talent/profile/x"},
                {"id": "score", "value": 99},
            ],
        },
    }
    assert candidate_spec_hook_cli(json.dumps(extra_fields)) == (2, "candidate_parent_missing")


def test_candidate_spec_hook_rejects_history_omitted_from_source_dates() -> None:
    partial = _with_structured_evidence(_runner_dict(
        url="https://www.linkedin.com/talent/profile/partial-history",
        visible_text=_linkedin_raw(
            "Nov 2017 – Jun 2018",
            "Jun 2017 – Mar 2018",
            "Nov 2016 – Apr 2017",
            "Aug 2016 – Nov 2016",
        ),
        employment_history=[
            {"company": "Stable", "start_month": "2019-01", "end_month": "2024-01"},
        ],
    ), position_id="position-1")
    event = _hook_event(
        model="gpt-5.6",
        tool_name="mcp__clickup__clickup_create_task",
        description=_candidate_task_description(
            partial, position_id="position-1", channel="linkedin_rps"
        ),
    )

    assert candidate_spec_hook_cli(json.dumps(event)) == (2, "candidate_history_incomplete")


@pytest.mark.parametrize(
    ("channel", "visible_text"),
    [
        ("linkedin_rps", _linkedin_raw(
            "Jan 2010 – Jan 2020", "January 2021 – June 2021", "July 2021 – November 2021"
        )),
        ("jobkorea", "경력\n2020.01 ~ 2025.01\n2021.01 ~ 2021.06\n2022.01 ~ 2022.06"),
    ],
)
def test_candidate_spec_hook_rejects_partial_history_in_all_source_formats(
    channel: str, visible_text: str
) -> None:
    partial = _with_structured_evidence(_runner_dict(
        url="https://www.jobkorea.co.kr/profile/partial" if channel == "jobkorea" else
            "https://www.linkedin.com/talent/profile/full-month-partial",
        visible_text=visible_text,
        employment_history=[
            {"company": "Stable", "start_month": "2020-01", "end_month": "2025-01"}
            if channel == "jobkorea" else
            {"company": "Stable", "start_month": "2010-01", "end_month": "2020-01"},
        ],
    ), position_id="position-1", channel=channel)
    event = _hook_event(
        model="gpt-5.6",
        tool_name="mcp__clickup__clickup_create_task",
        description=_candidate_task_description(partial, position_id="position-1", channel=channel),
    )
    assert candidate_spec_hook_cli(json.dumps(event)) == (2, "candidate_history_incomplete")


def test_candidate_spec_hook_rejects_reversed_tenure_ranges() -> None:
    invalid = _with_structured_evidence(_runner_dict(
        url="https://www.linkedin.com/talent/profile/reversed",
        visible_text=_linkedin_raw("Dec 2023 – Jan 2023", "Jun 2024 – Mar 2024"),
        employment_history=[
            {"company": "A", "start_month": "2023-12", "end_month": "2023-01"},
            {"company": "B", "start_month": "2024-06", "end_month": "2024-03"},
        ],
    ), position_id="position-1")
    event = _hook_event(
        model="gpt-5.6",
        tool_name="mcp__clickup__clickup_create_task",
        description=_candidate_task_description(invalid, position_id="position-1", channel="linkedin_rps"),
    )
    assert candidate_spec_hook_cli(json.dumps(event)) == (2, "candidate_history_invalid")

    bad_month = _with_structured_evidence(_runner_dict(
        url="https://www.jobkorea.co.kr/profile/bad-month",
        visible_text="경력\n2023.00 ~ 2023.05",
        employment_history=[
            {"company": "A", "start_month": "2023-00", "end_month": "2023-05"},
        ],
    ), position_id="position-1", channel="jobkorea")
    bad_month_event = _hook_event(
        model="gpt-5.6",
        tool_name="mcp__clickup__clickup_create_task",
        description=_candidate_task_description(bad_month, position_id="position-1", channel="jobkorea"),
    )
    assert candidate_spec_hook_cli(json.dumps(bad_month_event)) == (2, "candidate_history_invalid")


def test_candidate_spec_hook_allows_clean_canonical_candidate_and_parent_task() -> None:
    clean = _with_structured_evidence(_runner_dict(
        url="https://www.linkedin.com/talent/profile/stable-candidate",
        visible_text=_linkedin_raw(
            "Jan 2019 – Jan 2024",
            "Jan 2024 – Present",
        ),
        employment_history=[
            {"company": "Stable", "start_month": "2019-01", "end_month": "2024-01"},
            {"company": "Current", "start_month": "2024-01", "end_month": ""},
        ],
    ), position_id="position-1")
    candidate_event = _hook_event(
        model="gpt-5.6",
        tool_name="mcp__clickup__clickup_create_task",
        description=_candidate_task_description(
            clean, position_id="position-1", channel="linkedin_rps"
        ),
    )
    assert candidate_spec_hook_cli(json.dumps(candidate_event)) == (0, "")
    for position_name in ("Candidate Experience Manager", "후보자 경험 담당자"):
        parent_event = {
            **candidate_event,
            "tool_input": {
                "list_id": FY26_AI_SEARCH_LIST_ID,
                "name": f"{position_name} — AI Search",
                "description": _parent_task_description(
                    position_name=position_name, position_id="position-1", channel="linkedin_rps"
                ),
                "caller": {"type": "direct"},
            },
        }
        assert candidate_spec_hook_cli(json.dumps(parent_event)) == (0, "")
    code, reason, updated_input = _candidate_spec_evaluation(json.dumps(candidate_event))
    assert (code, reason) == (0, "")
    assert "VALUEHIRE_CANDIDATE_SPEC" not in updated_input["description"]
    script = Path(__file__).resolve().parents[1] / "tools/multi_position_sourcing/humansearch_register.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--candidate-spec-hook"],
        input=json.dumps(candidate_event),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "VALUEHIRE_CANDIDATE_SPEC" not in json.loads(completed.stdout)["hookSpecificOutput"]["updatedInput"]["description"]

    wrong_list = {**candidate_event, "tool_input": {**candidate_event["tool_input"], "list_id": "wrong"}}
    no_parent = {**candidate_event, "tool_input": {**candidate_event["tool_input"], "parent": ""}}
    assert candidate_spec_hook_cli(json.dumps(wrong_list)) == (2, "wrong_list_id")
    assert candidate_spec_hook_cli(json.dumps(no_parent)) == (2, "candidate_parent_missing")


def test_candidate_spec_hook_deduplicates_titles_and_excludes_current_tenure() -> None:
    edge = _with_structured_evidence(_runner_dict(
        url="https://www.linkedin.com/talent/profile/date-edge",
        visible_text=_linkedin_raw(
            "Jan 2023 – Jun 2023",
            "Jan 2023 – Jun 2023",
            "Jan 2020 – Jan 2021",
            "Jan 2024 – Present",
        ),
        employment_history=[
            {"company": "Same company", "start_month": "2023-01", "end_month": "2023-06"},
            {"company": "Same company", "start_month": "2023-01", "end_month": "2023-06"},
            {"company": "Twelve months", "start_month": "2020-01", "end_month": "2021-01"},
            {"company": "Current", "start_month": "2024-01", "end_month": ""},
        ],
    ), position_id="position-1")
    event = _hook_event(
        model="gpt-5.6",
        tool_name="mcp__clickup__clickup_update_task",
        description=_candidate_task_description(edge, position_id="position-1", channel="linkedin_rps"),
    )

    assert candidate_spec_hook_cli(json.dumps(event)) == (0, "")

    two_companies = {**edge, "visible_text": _linkedin_raw(
        "Jan 2023 – Jun 2023", "Jan 2023 – Jun 2023"
    ), "employment_history": [
        {"company": "Company A", "start_month": "2023-01", "end_month": "2023-06"},
        {"company": "Company B", "start_month": "2023-01", "end_month": "2023-06"},
    ]}
    two_company_event = _hook_event(
        model="gpt-5.6",
        tool_name="mcp__clickup__clickup_create_task",
        description=_candidate_task_description(
            two_companies, position_id="position-1", channel="linkedin_rps"
        ),
    )
    assert candidate_spec_hook_cli(json.dumps(two_company_event)) == (2, "frequent_job_change")


def test_claude_and_codex_hooks_share_the_same_fail_closed_command() -> None:
    repo = Path(__file__).resolve().parents[1]
    configs = [repo / ".claude/settings.json", repo / ".codex/hooks.json"]
    commands = []
    for path in configs:
        data = json.loads(path.read_text())
        groups = data["hooks"]["PreToolUse"]
        assert groups[0]["matcher"] == "mcp__.*__clickup_(create|update)_task"
        commands.append(groups[0]["hooks"][0]["command"])

    assert commands[0] == commands[1]
    assert "--candidate-spec-hook" in commands[0]


# ── 가용 필드 복원 ───────────────────────────────────────────────
def test_reconstruct_restores_available_fields() -> None:
    p = reconstruct_captured_profile(_runner_dict(), "saramin")
    assert isinstance(p, CapturedProfile)
    assert p.profile_url == "https://www.saramin.co.kr/profile/1"
    assert p.source_channel == "saramin"
    assert p.visible_text == "python backend engineer, 안정적 경력"
    assert p.summary == "백엔드 8년"
    assert p.education == "부산대학교 학사"
    assert p.skills == ("python", "backend")


def test_reconstruct_employment_history_becomes_tenure_tuples() -> None:
    hist = [
        {"company": "A", "start_month": "2021-01", "end_month": "2021-06"},
        {"company": "B", "start_month": "2021-07", "end_month": "2022-01"},
    ]
    p = reconstruct_captured_profile(_runner_dict(employment_history=hist), "jobkorea")
    assert p is not None
    assert isinstance(p.employment_history, tuple)
    assert all(isinstance(t, EmploymentTenure) for t in p.employment_history)
    assert p.employment_history[0] == EmploymentTenure("A", "2021-01", "2021-06")
    assert p.employment_history[1] == EmploymentTenure("B", "2021-07", "2022-01")


def test_reconstruct_channel_sets_source_channel() -> None:
    assert reconstruct_captured_profile(_runner_dict(), "linkedin_rps").source_channel == "linkedin_rps"


# ── fail-closed: 결손 dict 는 None (호출자가 '제외') ───────────────
def test_reconstruct_missing_url_is_fail_closed() -> None:
    d = _runner_dict()
    del d["url"]
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstruct_empty_url_is_fail_closed() -> None:
    assert reconstruct_captured_profile(_runner_dict(url=""), "saramin") is None
    assert reconstruct_captured_profile(_runner_dict(url="   "), "saramin") is None


def test_reconstruct_no_text_fields_is_fail_closed() -> None:
    """프리랜서 마커를 볼 텍스트원(본문·요약·헤드라인)이 전혀 없으면 판정불가 → fail-closed(제외)."""
    d = _runner_dict()
    del d["visible_text"]
    del d["summary"]
    d.pop("headline", None)
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstruct_none_text_values_is_fail_closed() -> None:
    """텍스트 필드가 None/빈값뿐이면 no-text → fail-closed (키 존재만으로 통과 금지)."""
    d = _runner_dict(visible_text=chr(0x200B), summary=chr(0xFEFF), headline=chr(0x200D), name="")
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstructed_profile_detects_freelancer_in_headline_only() -> None:
    """프리랜서 표기가 headline 에만 있어도 매처가 봐야 한다 — 자기 적대검증(fail-open 차단)."""
    d = _runner_dict(visible_text="", summary="", headline="프리랜서 개발자", name="")
    p = reconstruct_captured_profile(d, "saramin")
    assert hard_exclude_reason(p, "saramin") == "freelancer"


def test_reconstruct_non_dict_is_fail_closed() -> None:
    for bad in (None, [], "x", 3):
        assert reconstruct_captured_profile(bad, "saramin") is None


# ── 하드제외 신호 보존 (C1a 체이닝 근거): 재구성 프로필이 매처에서 그대로 걸림 ──
def test_reconstructed_profile_detects_freelancer() -> None:
    p = reconstruct_captured_profile(_runner_dict(visible_text="프리랜서 개발자", summary=""), "saramin")
    assert hard_exclude_reason(p, "saramin") == "freelancer"


def test_reconstructed_profile_detects_low_tier_school_on_portal() -> None:
    p = reconstruct_captured_profile(
        _runner_dict(education="OO전문대학 졸업", visible_text="backend", summary=""), "saramin"
    )
    assert hard_exclude_reason(p, "saramin") == "low_tier_school"


def test_reconstructed_profile_detects_frequent_job_change() -> None:
    hist = [
        {"company": "A", "start_month": "2021-01", "end_month": "2021-06"},
        {"company": "B", "start_month": "2021-07", "end_month": "2022-01"},
    ]
    p = reconstruct_captured_profile(
        _runner_dict(visible_text="backend", summary="", education="", employment_history=hist),
        "jobkorea",
    )
    assert hard_exclude_reason(p, "jobkorea") == "frequent_job_change"


def test_reconstructed_clean_profile_passes() -> None:
    """정상 후보(지방 국공립·안정 경력)는 재구성 후에도 제외 사유 없음(과잉제외 방지)."""
    assert hard_exclude_reason(reconstruct_captured_profile(_runner_dict(), "saramin"), "saramin") is None


# ── 게이트4b step2(Codex 2차 적대검증) 발견 회귀 ──────────────────
def test_reconstruct_name_marker_does_not_overexclude() -> None:
    """name 은 신원 필드 — 마커 스캔 대상 아님. 이름에 우연히 2글자 마커 부분문자열('외주' 등)이
    있어도 본문이 정상이면 제외하지 않는다 — Codex 재검증 과잉제외(김외주→freelancer) 차단.
    프리랜서 신호는 본문(visible_text·summary·headline)에서 잡는다."""
    d = _runner_dict(name="김외주", visible_text="backend engineer 안정적", summary="부산대 8년", headline="")
    assert hard_exclude_reason(reconstruct_captured_profile(d, "saramin"), "saramin") is None


def test_reconstruct_invisible_only_text_is_fail_closed() -> None:
    """제로폭(U+200B) 등 보이지 않는 문자뿐이면 판정 불가 → fail-closed — Codex fail-open."""
    d = _runner_dict(visible_text=chr(0x200B), summary=chr(0xFEFF), headline=chr(0x200D), name="")
    assert reconstruct_captured_profile(d, "saramin") is None


def test_reconstruct_invalid_url_is_fail_closed() -> None:
    """무효 URL(스킴 없음·제로폭·내부공백)은 재구성 단계에서 fail-closed — Codex fail-open."""
    for bad in ("not-a-url", chr(0x200B), "https://x.com/a b", "javascript:void(0)"):
        assert reconstruct_captured_profile(_runner_dict(url=bad), "saramin") is None


def test_reconstruct_skills_non_list_does_not_crash() -> None:
    """skills 가 int/str 같은 비리스트여도 예외 없이 안전 복원(()) — Codex exception."""
    for bad in (123, "python", None, {"a": 1}):
        p = reconstruct_captured_profile(_runner_dict(skills=bad), "saramin")
        assert p is not None
        assert p.skills == ()


def test_reconstruct_positional_employment_history_detects_frequent() -> None:
    """employment_history 가 위치형 리스트/튜플로 와도 잦은이직을 놓치지 않음 — Codex fail-open."""
    hist = [["A", "2021-01", "2021-06"], ["B", "2021-07", "2022-01"]]
    p = reconstruct_captured_profile(
        _runner_dict(visible_text="backend", summary="", education="", employment_history=hist),
        "jobkorea",
    )
    assert hard_exclude_reason(p, "jobkorea") == "frequent_job_change"


# ── PC-C1a: 등록 경계 eligible() 에 하드제외 게이트 배선 (RED 먼저) ──────────────
# 현행 eligible() 은 score>=70 · 유효URL 만 보고 hard_exclude_reason 을 미호출 → 프리랜서·잦은이직·
# 전문대가 등록 브리핑으로 샌다. PC-C1a1 재구성 + PC-C0 매처로 채점 전 하드제외를 등록 경계에 강제한다.
_FREQ_HIST = [
    {"company": "A", "start_month": "2021-01", "end_month": "2021-06"},
    {"company": "B", "start_month": "2021-07", "end_month": "2022-01"},
]


def test_eligible_excludes_freelancer() -> None:
    r = _runner_dict(score=85, visible_text="프리랜서 개발자", summary="")
    assert eligible([r], "saramin") == []


def test_eligible_excludes_frequent_job_change() -> None:
    r = _runner_dict(score=85, visible_text="backend", summary="", education="", employment_history=_FREQ_HIST)
    assert eligible([r], "jobkorea") == []


def test_eligible_excludes_low_tier_school_on_portal() -> None:
    r = _runner_dict(score=85, education="OO전문대학 졸업", visible_text="backend", summary="")
    assert eligible([r], "saramin") == []


def test_eligible_keeps_clean_passer() -> None:
    r = _runner_dict(score=85, visible_text="backend engineer", summary="부산대 8년 안정적")
    assert eligible([r], "saramin") == [r]


def test_eligible_rejects_legacy_direct_total_without_contract_version() -> None:
    r = _runner_dict(score=99, visible_text="backend engineer", summary="부산대")
    r.pop("contract_version")
    r["breakdown"] = {
        "education": 30,
        "role_fit": 50,
        "profile_logic": 10,
        "job_stability": 9,
    }

    assert eligible([r], "saramin") == []


def test_eligible_recomputes_and_rejects_forged_llm_total() -> None:
    forged = _runner_dict(
        score=99,
        visible_text="backend engineer",
        summary="부산대 8년 안정적",
    )

    assert eligible([forged], "saramin") == []


def test_eligible_low_tier_school_kept_on_linkedin() -> None:
    """링크드인은 학교 하드제외 미적용(portal 채널만) — 회귀 보호."""
    r = _runner_dict(
        score=85, education="OO전문대학", visible_text="robotics", summary="x",
        url="https://www.linkedin.com/in/x",
    )
    assert eligible([r], "linkedin_rps") == [r]


def test_eligible_fail_closed_on_unreconstructable_dict() -> None:
    """재구성 불가(본문 전무) 후보는 등록 경계에서 fail-closed(제외)."""
    r = _runner_dict(score=85)
    del r["visible_text"]
    del r["summary"]
    r.pop("headline", None)
    assert eligible([r], "saramin") == []


def test_eligible_still_filters_low_score_and_bad_url() -> None:
    """기존 계약 유지(회귀): 점수 미달·URL 무효는 여전히 제외."""
    low = _runner_dict(score=60, visible_text="backend", summary="ok")
    bad = _runner_dict(score=90, url="javascript:void(0)", visible_text="backend", summary="ok")
    assert eligible([low, bad], "saramin") == []


def test_eligible_sorts_passers_by_score_desc() -> None:
    """정상 후보 다건은 점수 내림차순 정렬 유지(기존 계약)."""
    lo = _runner_dict(score=75, visible_text="backend", summary="부산대", url="https://x.co/a")
    hi = _runner_dict(score=95, visible_text="backend", summary="부산대", url="https://x.co/b")
    assert eligible([lo, hi], "saramin") == [hi, lo]


# ── 게이트4b step2(Codex 2차 적대검증) 발견 회귀 ──────────────────
def test_eligible_excludes_nan_score() -> None:
    """score=NaN 은 어떤 비교도 False → '<threshold' 를 통과하던 fail-open 차단(Codex)."""
    r = _runner_dict(score=float("nan"), visible_text="backend", summary="부산대")
    assert eligible([r], "saramin") == []


def test_eligible_excludes_profile_url_only_schema_drift() -> None:
    """register 스키마 URL 키는 'url' — url 없이 profile_url 만 있는 dict 는 제외(fail-closed).
    하류 build_message/clickup 이 r['url'] 을 읽으므로 통과시키면 KeyError — Codex 재검증 재현 차단."""
    r = _runner_dict(visible_text="backend", summary="부산대 8년")
    r["profile_url"] = r.pop("url")
    assert eligible([r], "saramin") == []


def test_eligible_excludes_non_finite_score() -> None:
    """score=inf/-inf/nan 비유한 값은 제외 — inf>=threshold 로 통과하던 fail-open 차단(Codex 재검증)."""
    for bad in (float("inf"), float("-inf"), float("nan")):
        r = _runner_dict(score=bad, visible_text="backend", summary="부산대")
        assert eligible([r], "saramin") == []


def test_eligible_skips_non_dict_items_without_crash() -> None:
    """results 에 비dict 항목이 섞여도 예외 없이 skip(fail-closed) — Codex exception."""
    clean = _runner_dict(visible_text="backend", summary="부산대", url="https://x.co/ok")
    assert eligible([clean, None, "bad-item", 123], "saramin") == [clean]


# ── ClickUp FY26AI_Search 등록 계약: 중복검사·칸반 Task/Subtask·프로필 저장 증거 ──
class _FakeClickUp:
    def __init__(
        self,
        *,
        parent_hits: list[dict] | None = None,
        duplicate_profile_urls: set[str] | None = None,
    ) -> None:
        self.parent_hits = parent_hits or []
        self.duplicate_profile_urls = duplicate_profile_urls or set()
        self.searches: list[tuple[str, str, str | None]] = []
        self.creates: list[tuple[str, str, str, str | None]] = []

    def search_tasks(self, *, list_id: str, query: str, parent: str | None = None) -> list[dict]:
        self.searches.append((list_id, query, parent))
        if parent is None:
            return self.parent_hits
        if query in self.duplicate_profile_urls:
            return [{"id": "SUB-EXISTING", "url": "https://app.clickup.com/t/SUB-EXISTING"}]
        return []

    def create_task(
        self,
        *,
        list_id: str,
        name: str,
        description: str,
        parent: str | None = None,
    ) -> dict:
        task_id = f"TASK-{len(self.creates) + 1}"
        self.creates.append((list_id, name, description, parent))
        return {"id": task_id, "url": f"https://app.clickup.com/t/{task_id}"}


def test_clickup_registration_eligible_requires_saved_profile_evidence(monkeypatch) -> None:
    """ClickUp 등록은 프로필 저장 증거가 있는 후보만 통과 — 단순 URL/점수 통과와 분리."""
    saved = _with_structured_evidence(
        _runner_dict(url="https://www.linkedin.com/talent/profile/saved")
    )
    unsaved = _runner_dict(url="https://www.linkedin.com/in/not-saved")
    forged = _runner_dict(
        url=saved["url"], screenshot="/tmp/profile.png", db_row_id="row-1"
    )

    monkeypatch.setattr(register_module, "complete_evidence_payload", lambda _value: False)
    assert has_saved_profile_evidence(
        saved, channel="linkedin_rps", position_id="86abc"
    ) is False
    monkeypatch.setattr(register_module, "complete_evidence_payload", lambda _value: True)
    assert has_saved_profile_evidence(
        saved, channel="linkedin_rps", position_id="86abc"
    ) is True
    assert has_saved_profile_evidence(
        unsaved, channel="linkedin_rps", position_id="86abc"
    ) is False
    assert has_saved_profile_evidence(
        forged, channel="linkedin_rps", position_id="86abc"
    ) is False
    assert clickup_registration_eligible(
        [saved, unsaved], "linkedin_rps", position_id="86abc"
    ) == [saved]


def test_clickup_registration_eligible_requires_output_contract_fields(monkeypatch) -> None:
    """Subtask 후보는 profile_url·score·why_fit·profile_summary 계약을 만족해야 한다."""
    base = _with_structured_evidence(_runner_dict(
        url="https://www.linkedin.com/talent/profile/abc",
        score=91,
        why_fit=["직무 직결"],
        summary="프로필 요약",
    ))
    no_why_fit = dict(base, url="https://www.linkedin.com/talent/profile/no-why", why_fit=[])
    no_summary = dict(base, url="https://www.linkedin.com/talent/profile/no-summary", summary="")

    assert has_required_candidate_output_fields(base) is True
    assert has_required_candidate_output_fields(no_why_fit) is False
    assert has_required_candidate_output_fields(no_summary) is False
    monkeypatch.setattr(register_module, "complete_evidence_payload", lambda _value: True)
    assert clickup_registration_eligible(
        [base, no_why_fit, no_summary], "linkedin_rps", position_id="86abc"
    ) == [base]


def test_clickup_fy26_registration_checks_duplicates_before_creating_tasks(monkeypatch) -> None:
    """부모 Task 와 후보 profile_url Subtask 를 먼저 검색한 뒤 FY26AI_Search 리스트에만 생성."""
    fake = _FakeClickUp()
    candidate = _with_structured_evidence(_runner_dict(
        name="홍길동",
        url="https://www.linkedin.com/talent/profile/abc",
        score=91,
    ))
    monkeypatch.setattr(register_module, "complete_evidence_payload", lambda _value: True)

    plan = register_clickup_fy26_ai_search(
        position_name="Acme Backend",
        position_id="86abc",
        passers=[candidate],
        channel="linkedin_rps",
        clickup_search_tasks=fake.search_tasks,
        clickup_create_task=fake.create_task,
        dry_run=False,
    )

    assert plan.list_id == FY26_AI_SEARCH_LIST_ID
    assert plan.list_url == FY26_AI_SEARCH_LIST_URL
    assert fake.searches[0] == (FY26_AI_SEARCH_LIST_ID, "Acme Backend", None)
    assert (FY26_AI_SEARCH_LIST_ID, candidate["url"], plan.parent_task_id) in fake.searches
    assert len(fake.creates) == 2
    assert fake.creates[0][0] == FY26_AI_SEARCH_LIST_ID
    assert fake.creates[0][3] is None
    assert fake.creates[1][0] == FY26_AI_SEARCH_LIST_ID
    assert fake.creates[1][3] == plan.parent_task_id
    assert candidate["url"] in fake.creates[1][1]
    assert candidate["url"] in fake.creates[1][2]


def test_clickup_fy26_registration_skips_duplicate_candidate_subtask(monkeypatch) -> None:
    """같은 부모 아래 이미 profile_url 이 있으면 후보 Subtask 를 새로 만들지 않는다."""
    candidate = _with_structured_evidence(_runner_dict(
        name="홍길동",
        url="https://www.linkedin.com/talent/profile/dup",
        score=88,
    ))
    monkeypatch.setattr(register_module, "complete_evidence_payload", lambda _value: True)
    fake = _FakeClickUp(duplicate_profile_urls={candidate["url"]})

    plan = register_clickup_fy26_ai_search(
        position_name="Acme Backend",
        position_id="86abc",
        passers=[candidate],
        channel="linkedin_rps",
        clickup_search_tasks=fake.search_tasks,
        clickup_create_task=fake.create_task,
        dry_run=False,
    )

    assert len(fake.creates) == 1  # parent only
    assert plan.candidates[0].action == "skipped_duplicate"
    assert plan.candidates[0].profile_url == candidate["url"]


def test_clickup_fy26_registration_requires_duplicate_checker() -> None:
    """중복검사 어댑터가 없으면 dry-run 이어도 등록 계획을 만들지 않는다."""
    with pytest.raises(RuntimeError, match="duplicate_check_required"):
        register_clickup_fy26_ai_search(
            position_name="Acme Backend",
            position_id="86abc",
            passers=[_runner_dict(screenshot="/tmp/profile.png")],
            channel="linkedin_rps",
            clickup_search_tasks=None,
            clickup_create_task=None,
            dry_run=True,
        )


def test_clickup_fy26_registration_dry_run_never_creates_tasks(monkeypatch) -> None:
    """dry-run 은 중복검사만 하고 create_task 를 호출하지 않는다."""
    fake = _FakeClickUp()
    candidate = _with_structured_evidence(_runner_dict(
        url="https://www.linkedin.com/talent/profile/dry",
        score=82,
    ))
    monkeypatch.setattr(register_module, "complete_evidence_payload", lambda _value: True)

    plan = register_clickup_fy26_ai_search(
        position_name="Acme Backend",
        position_id="86abc",
        passers=[candidate],
        channel="linkedin_rps",
        clickup_search_tasks=fake.search_tasks,
        clickup_create_task=fake.create_task,
        dry_run=True,
    )

    assert fake.creates == []
    assert plan.parent_action == "planned_create"
    assert plan.candidates[0].action == "planned_create"


def test_clickup_fy26_registration_live_requires_create_adapter() -> None:
    """live 모드에서 create 어댑터가 없으면 created 라고 주장하지 않고 fail-closed."""
    fake = _FakeClickUp()
    with pytest.raises(RuntimeError, match="clickup_create_task_required"):
        register_clickup_fy26_ai_search(
            position_name="Acme Backend",
            position_id="86abc",
            passers=[_runner_dict(screenshot="/tmp/profile.png")],
            channel="linkedin_rps",
            clickup_search_tasks=fake.search_tasks,
            clickup_create_task=None,
            dry_run=False,
        )


def test_clickup_fy26_registration_live_requires_parent_task_id() -> None:
    """부모 Task id 를 받지 못하면 후보를 top-level task 로 만들지 않는다."""
    fake = _FakeClickUp()

    def bad_create_task(**_kwargs) -> dict:
        return {"id": "", "url": "https://app.clickup.com/t/EMPTY"}

    with pytest.raises(RuntimeError, match="parent_task_id_required"):
        register_clickup_fy26_ai_search(
            position_name="Acme Backend",
            position_id="86abc",
            passers=[_runner_dict(screenshot="/tmp/profile.png")],
            channel="linkedin_rps",
            clickup_search_tasks=fake.search_tasks,
            clickup_create_task=bad_create_task,
            dry_run=False,
        )


def test_profile_save_evidence_contract_requires_structured_receipt() -> None:
    """스크린샷 경로나 DB id 단독 값은 더 이상 등록 증거가 아니다."""
    assert PROFILE_SAVE_EVIDENCE_FIELDS == ("evidence",)
    for forged in (
        _runner_dict(screenshot="/tmp/profile.png"),
        _runner_dict(sourcing_result_id="src-1"),
        _runner_dict(db_row_id="row-1"),
    ):
        assert has_saved_profile_evidence(
            forged, channel="linkedin_rps", position_id="86abc"
        ) is False
