from __future__ import annotations

import json
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs/sot/26-portal-login-spec.json"
CONTROL_PATH = ROOT / "skills/login/browser-control-contract.json"
SKILL_PATH = ROOT / "skills/login/SKILL.md"
WORKER_PATH = ROOT / "tools/multi_position_sourcing/fleet_worker.py"
POLICY_ID = "26-portal-login-spec@1.5.0"
HISTORICAL_MARKER = "historical_input_not_executable"

LOGIN_SKILL_PATHS = (
    ROOT / "skills/login/SKILL.md",
    ROOT / ".codex/skills/login/SKILL.md",
    ROOT / ".claude/skills/login/SKILL.md",
)
CONTROL_PATHS = (
    ROOT / "skills/login/browser-control-contract.json",
    ROOT / ".codex/skills/login/browser-control-contract.json",
    ROOT / ".claude/skills/login/browser-control-contract.json",
)
POLICY_ENTRYPOINTS = (
    ROOT / "CLAUDE.md",
    ROOT / "docs/sot/25-ai-search-execution-process.json",
    ROOT / "docs/prompts/goal-full-codebase-review.md",
    ROOT / "docs/ai-search/three-mac-account-coordinator-goal-prompt.md",
    ROOT / "skills/ai-search/references/spec-procedure.md",
    ROOT / "skills/ai-search/SKILL.md",
    ROOT / ".codex/skills/ai-search/references/spec-procedure.md",
    ROOT / ".codex/skills/ai-search/SKILL.md",
    ROOT / ".claude/skills/aisearch/SKILL.md",
    ROOT / ".codex/skills/url/SKILL.md",
    ROOT / ".claude/skills/url/SKILL.md",
    WORKER_PATH,
)
SUPERSEDED_PROMPTS = (
    ROOT / "docs/prompts/hermes-login-gate-before-search-skills-2026-07-21.md",
    ROOT / "docs/prompts/linkedin-rps-login-session-fix-2026-07-18.md",
)


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_site_authentication_methods_are_explicit_and_mutation_bounded() -> None:
    policy = _json(POLICY_PATH)
    control = _json(CONTROL_PATH)

    assert policy["policy_id"] == POLICY_ID
    assert control["login_policy_id"] == POLICY_ID
    assert policy["authentication_policy"] == control["authentication_policy"]
    assert policy["linkedin_session_decision"] == control["linkedin_session_decision"]
    assert policy["supported_agents"] == control["supported_agents"] == [
        "claude",
        "codex",
    ]
    assert control["source_priority"][0] == "docs/sot/26-portal-login-spec.json"
    assert control["policy_authority"] == POLICY_ID

    methods = policy["authentication_policy"]
    assert methods["saramin"] == {
        "provider": "stored_username_password",
        "max_submissions_per_episode": 1,
        "exact_existing_target_required": True,
        "challenge_action": "HUMAN_AUTH",
    }
    assert methods["jobkorea"] == {
        "provider": "stored_username_password",
        "max_submissions_per_episode": 1,
        "exact_existing_target_required": True,
        "challenge_action": "HUMAN_AUTH",
    }
    linkedin = methods["linkedin_rps"]
    assert linkedin["provider"] == "secret_store_li_at"
    assert linkedin["secret_reference"] == "LINKEDIN_LI_AT"
    assert linkedin["max_cookie_applications_per_episode"] == 1
    assert linkedin["exact_existing_target_required"] is True
    assert linkedin["username_password_submit"] is False
    assert linkedin["auto_logout_other_machine"] is False
    assert linkedin["new_target"] is False


def test_linkedin_machine_decision_table_is_complete_and_fail_closed() -> None:
    policy = _json(POLICY_PATH)
    decisions = policy["linkedin_session_decision"]

    assert set(decisions) == {
        "zero_authenticated_machines",
        "one_authenticated_machine",
        "two_or_more_authenticated_machines",
        "unproven_or_invalid_count",
    }
    assert decisions["zero_authenticated_machines"]["action"] == (
        "apply_li_at_once_on_selected_machine_exact_existing_target"
    )
    assert decisions["zero_authenticated_machines"]["missing_exact_target"] == "HANDOFF"
    assert decisions["zero_authenticated_machines"]["required_apps"] == [
        "APP30",
        "APP31",
    ]
    assert (
        decisions["zero_authenticated_machines"]["provider_or_injector_unavailable"]
        == "HANDOFF"
    )
    assert decisions["one_authenticated_machine"] == {
        "action": "reuse_authenticated_machine_and_exact_target",
        "authentication_mutations": 0,
    }
    conflict = decisions["two_or_more_authenticated_machines"]
    assert conflict["action"] == "AUTH_CONFLICT"
    assert conflict["terminal"] is True
    assert set(conflict["forbidden_actions"]) >= {
        "auto_logout_other_machine",
        "continue",
        "confirm",
        "choose_by_reliability",
        "retry",
    }
    assert decisions["unproven_or_invalid_count"] == {
        "action": "HANDOFF",
        "authentication_mutations": 0,
    }


def test_li_at_cannot_enter_logs_receipts_or_model_output() -> None:
    policy = _json(POLICY_PATH)
    control = _json(CONTROL_PATH)

    assert policy["secret_handling"] == control["secret_handling"]
    secret = policy["secret_handling"]
    assert secret["secret_reference_only"] is True
    assert secret["secret_value_readable_by_model"] is False
    assert secret["derived_secret_output"] is False
    assert set(secret["forbidden_output_destinations"]) == {
        "stdout",
        "stderr",
        "logs",
        "receipts",
        "artifacts",
        "model_messages",
        "shell_arguments",
    }
    assert set(secret["forbidden_receipt_fields"]) >= {
        "li_at",
        "cookie",
        "cookie_value",
        "password",
        "secret",
        "token",
    }
    barrier = _text(ROOT / "tools/multi_position_sourcing/login_barrier.py")
    assert '"li_at"' in barrier


def test_active_instructions_forbid_legacy_linkedin_form_login_and_logout() -> None:
    active = "\n".join(
        _text(path)
        for path in (
            POLICY_PATH,
            *CONTROL_PATHS,
            *LOGIN_SKILL_PATHS,
            *POLICY_ENTRYPOINTS,
        )
    )
    forbidden_phrases = (
        "LINKEDIN_USERNAME/LINKEDIN_PASSWORD",
        "LinkedIn `/uas/login-cap`에 username/password",
        "기존 `login-cap` 폼이면 그 폼에서만 자격증명 1회 제출",
        "linkedin_rps_logged_in=true인 머신을 먼저 찾아 이 잡에 배정",
        "저장 자격증명으로 자동 로그인·재로그인을 항상 수행할 것",
        "3사 자동 로그인을 막지 않는다",
        "/uas/login-cap current target이면 시크릿 저장소 자동 로그인 1회",
    )
    assert not [phrase for phrase in forbidden_phrases if phrase in active]

    required = (
        "LINKEDIN_LI_AT",
        "자동 로그아웃 금지",
        "정확한 기존 탭",
        "AUTH_CONFLICT",
    )
    assert not [marker for marker in required if marker not in active]


def test_policy_supersedes_historical_prompts_without_new_hermes_runtime() -> None:
    policy = _json(POLICY_PATH)
    replacements = policy["supersedes"]
    assert replacements == {
        "docs/prompts/hermes-login-gate-before-search-skills-2026-07-21.md": (
            "historical_input_not_executable"
        ),
        "docs/prompts/linkedin-rps-login-session-fix-2026-07-18.md": (
            "historical_input_not_executable"
        ),
    }
    route = policy["current_execution_route"]
    assert route == ["Discord", "queue", "worker", "Codex_or_Claude"]
    assert "Hermes" not in route

    for prompt in SUPERSEDED_PROMPTS:
        text = _text(prompt)
        first_screen = "\n".join(text.splitlines()[:20])
        assert HISTORICAL_MARKER in first_screen, prompt
        assert POLICY_ID in first_screen, prompt
        assert "실행 금지" in first_screen, prompt


def test_login_and_search_entrypoints_reference_the_new_policy() -> None:
    for path in (*LOGIN_SKILL_PATHS, *POLICY_ENTRYPOINTS):
        text = _text(path)
        assert POLICY_ID in text, path

    for path in LOGIN_SKILL_PATHS:
        assert "APP 30/31" in _text(path), path


def test_worker_generated_prompts_reference_the_new_policy() -> None:
    from tools.multi_position_sourcing.fleet_worker import build_job_prompt

    login_prompt = build_job_prompt(
        {
            "id": 1,
            "skill": "login",
            "position_url": "",
            "requested_by": "owner",
            "role": "owner",
            "machine": "macmini",
        }
    )
    url_prompt = build_job_prompt(
        {
            "id": 2,
            "skill": "url",
            "position_url": "https://app.clickup.com/t/abc123",
            "requested_by": "owner",
            "role": "owner",
            "machine": "macmini",
        }
    )
    for prompt in (login_prompt, url_prompt):
        assert POLICY_ID in prompt
        assert "APP 30/31" in prompt
        assert "LINKEDIN_LI_AT" in prompt
        assert "자동 로그아웃" in prompt
    assert "저장 자격증명으로 자동 로그인·재로그인을 항상 수행할 것" not in login_prompt
    assert "linkedin_rps_logged_in=true인 머신을 먼저 찾아" not in url_prompt


def test_current_route_does_not_keep_hermes_as_an_active_agent() -> None:
    policy = _json(POLICY_PATH)
    assert policy["current_execution_route"] == [
        "Discord",
        "queue",
        "worker",
        "Codex_or_Claude",
    ]
    for path in CONTROL_PATHS:
        assert _json(path)["supported_agents"] == ["claude", "codex"]

    active = "\n".join(_text(path) for path in (*LOGIN_SKILL_PATHS, POLICY_PATH))
    forbidden_active_markers = (
        "Claude, Codex, Hermes",
        "Claude·Codex·Hermes",
        "Codex 또는 Hermes",
        "~/.hermes/skills/login/",
        "Hermes login preflight",
        "<Claude|Codex|Hermes>",
    )
    assert not [
        marker for marker in forbidden_active_markers if marker in active
    ]


def test_policy_contract_mirrors_are_byte_identical() -> None:
    assert len({_sha256(path) for path in CONTROL_PATHS}) == 1
    assert len({_sha256(path) for path in LOGIN_SKILL_PATHS}) == 1


def test_app01_forbidden_runtime_scope_is_declared() -> None:
    briefing = _text(
        ROOT
        / "docs/engineering/login-machine-browser-decomposition-briefing-2026-07-26.html"
    )
    goal = _text(
        ROOT
        / "docs/engineering/login-machine-browser-implementation-goal-2026-07-26.md"
    )
    assert 'forbid: ["로그인 코드 구현", "실제 쿠키 입력"' in briefing
    assert "실제 자격증명 또는 `li_at` 읽기·입력" in goal
    assert "함대 조사·기기 자동 선택" in goal
