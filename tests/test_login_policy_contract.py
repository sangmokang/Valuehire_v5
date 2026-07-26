from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs/sot/26-portal-login-spec.json"
CONTROL_PATH = ROOT / "skills/login/browser-control-contract.json"
SKILL_PATH = ROOT / "skills/login/SKILL.md"
WORKER_PATH = ROOT / "tools/multi_position_sourcing/fleet_worker.py"
POLICY_ID = "26-portal-login-spec@1.5.0"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_site_authentication_methods_are_explicit_and_mutation_bounded() -> None:
    policy = _json(POLICY_PATH)
    control = _json(CONTROL_PATH)

    assert policy["policy_id"] == POLICY_ID
    assert control["login_policy_id"] == POLICY_ID
    assert policy["authentication_policy"] == control["authentication_policy"]

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
    }
    assert decisions["zero_authenticated_machines"]["action"] == (
        "apply_li_at_once_on_selected_machine_exact_existing_target"
    )
    assert decisions["zero_authenticated_machines"]["missing_exact_target"] == "HANDOFF"
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
        (
            _text(POLICY_PATH),
            _text(CONTROL_PATH),
            _text(SKILL_PATH),
            _text(WORKER_PATH),
        )
    )
    forbidden_phrases = (
        "LINKEDIN_USERNAME/LINKEDIN_PASSWORD",
        "LinkedIn `/uas/login-cap`에 username/password",
        "기존 `login-cap` 폼이면 그 폼에서만 자격증명 1회 제출",
        "linkedin_rps_logged_in=true인 머신을 먼저 찾아 이 잡에 배정",
        "저장 자격증명으로 자동 로그인·재로그인을 항상 수행할 것",
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


def test_login_and_search_entrypoints_reference_the_new_policy() -> None:
    entrypoints = (
        WORKER_PATH,
        SKILL_PATH,
        ROOT / "skills/ai-search/references/spec-procedure.md",
        ROOT / ".codex/skills/ai-search/references/spec-procedure.md",
    )
    for path in entrypoints:
        text = _text(path)
        assert "26-portal-login-spec" in text, path

    worker = _text(WORKER_PATH)
    skill = _text(SKILL_PATH)
    assert POLICY_ID in worker
    assert POLICY_ID in skill
    assert "APP 30/31" in worker
    assert "APP 30/31" in skill
