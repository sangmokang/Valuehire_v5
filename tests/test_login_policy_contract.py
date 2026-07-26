from __future__ import annotations

import json
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "docs/sot/26-portal-login-spec.json"
CONTROL_PATH = ROOT / "skills/login/browser-control-contract.json"
SKILL_PATH = ROOT / "skills/login/SKILL.md"
WORKER_PATH = ROOT / "tools/multi_position_sourcing/fleet_worker.py"
SEARCH_CONTRACT_PATH = ROOT / "docs/prompts/login-search-execution-contract.md"
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
MULTISEARCH_SKILL_PATHS = (
    ROOT / "skills/multisearch/SKILL.md",
    ROOT / ".codex/skills/multisearch/SKILL.md",
)
AI_SEARCH_SKILL_PATHS = (
    ROOT / "skills/ai-search/SKILL.md",
    ROOT / ".codex/skills/ai-search/SKILL.md",
    ROOT / ".claude/skills/aisearch/SKILL.md",
)
HUMANSEARCH_SKILL_PATHS = (
    ROOT / "skills/humansearch/SKILL.md",
    ROOT / ".codex/skills/humansearch/SKILL.md",
    ROOT / ".claude/skills/humansearch/SKILL.md",
)
POLICY_ENTRYPOINTS = (
    ROOT / "CLAUDE.md",
    ROOT / "docs/sot/25-ai-search-execution-process.json",
    ROOT / "docs/prompts/goal-full-codebase-review.md",
    ROOT / "docs/prompts/login-search-execution-contract.md",
    ROOT / "docs/search-access.md",
    ROOT / "skills/ai-search/references/spec-procedure.md",
    ROOT / "skills/ai-search/SKILL.md",
    ROOT / ".codex/skills/ai-search/references/spec-procedure.md",
    ROOT / ".codex/skills/ai-search/SKILL.md",
    ROOT / ".claude/skills/aisearch/SKILL.md",
    *HUMANSEARCH_SKILL_PATHS,
    ROOT / "skills/multisearch/SKILL.md",
    ROOT / ".codex/skills/multisearch/SKILL.md",
    ROOT / ".codex/skills/url/SKILL.md",
    ROOT / ".claude/skills/url/SKILL.md",
    WORKER_PATH,
)
SUPERSEDED_PROMPTS = (
    ROOT / "docs/prompts/hermes-login-gate-before-search-skills-2026-07-21.md",
    ROOT / "docs/prompts/linkedin-rps-login-session-fix-2026-07-18.md",
    ROOT / "docs/engineering/linkedin-managed-autologin-goal-2026-07-26.md",
    ROOT / "docs/engineering/login-policy-recement-goal-2026-07-08.md",
    ROOT / "docs/ai-search/qa-linkedin-autologin-sot-2026-06-09.md",
    ROOT / "docs/ai-search/three-mac-account-coordinator-goal-prompt.md",
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
    assert "HANDOFF" in control["state_machine"]["DISCOVER"]["next"]
    multi_device = control["multi_device"]
    assert multi_device["authenticated_machine_count_requires_sealed_fleet_evidence"] is True
    assert multi_device["evidence_unavailable"] == "HANDOFF"
    assert multi_device["owner_authorization_is_not_machine_count_evidence"] is True

    methods = policy["authentication_policy"]
    assert methods["saramin"] == {
        "provider": "stored_username_password",
        "max_submissions_per_episode": 1,
        "exact_existing_target_required": True,
        "exact_target_candidate_count": 1,
        "otherwise": "HANDOFF",
        "challenge_action": "HUMAN_AUTH",
    }
    assert methods["jobkorea"] == {
        "provider": "stored_username_password",
        "max_submissions_per_episode": 1,
        "exact_existing_target_required": True,
        "exact_target_candidate_count": 1,
        "otherwise": "HANDOFF",
        "challenge_action": "HUMAN_AUTH",
    }
    linkedin = methods["linkedin_rps"]
    assert linkedin["provider"] == "secret_store_li_at"
    assert linkedin["secret_reference"] == "LINKEDIN_LI_AT"
    assert linkedin["max_cookie_applications_per_episode"] == 1
    assert linkedin["exact_existing_target_required"] is True
    assert linkedin["exact_target_candidate_count"] == 1
    assert linkedin["otherwise"] == "HANDOFF"
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
    assert (
        decisions["zero_authenticated_machines"][
            "exact_target_candidate_count_not_one"
        ]
        == "HANDOFF"
    )
    assert decisions["zero_authenticated_machines"]["required_apps"] == [
        "APP30",
        "APP31",
    ]
    assert (
        decisions["zero_authenticated_machines"][
            "selected_machine_requires_current_turn_owner_authorization"
        ]
        is True
    )
    assert (
        decisions["zero_authenticated_machines"][
            "selected_machine_requires_app17_route_decision"
        ]
        is True
    )
    assert (
        decisions["zero_authenticated_machines"]["provider_or_injector_unavailable"]
        == "HANDOFF"
    )
    assert decisions["one_authenticated_machine"] == {
        "action": "reuse_authenticated_machine_and_exact_target",
        "authentication_mutations": 0,
        "exact_target_candidate_count_not_one": "HANDOFF",
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

    from tools.multi_position_sourcing.login_barrier import validate_channel_receipt

    for key in ("li_at", "cookie_value", "password", "secret", "token"):
        for receipt in (
            {"schema_version": 1, key: "must-not-escape"},
            {"schema_version": 1, "nested": {"items": [{key: "must-not-escape"}]}},
        ):
            error = validate_channel_receipt(
                receipt,
                channel="linkedin_rps",
                machine="macmini",
                now_epoch=0,
            )
            assert error is not None and "secret_material" in error, (key, receipt)


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
        "로그인은 내(자동화)가 무조건 한다",
        "이를 막는 코드·규칙이 있으면 SOT 위반이므로 삭제한다",
        "단순 로그아웃 화면(예: `/uas/login-cap`)은 차단이 아니므로 시크릿 저장소 자동 로그인을 1회 시도한다",
        "로그인 필요→자동 로그인",
        "자동 로그인 1회 또는 사람 인계",
        "60초 뒤 자동 로그인",
        "live session host 우선, 없으면 표 순서",
        "/uas/login-cap·li.protechts 단독 신호는 자동 로그인 대상",
        "사람인·잡코리아·링크드인 모두 시크릿 저장소 creds",
        '"channel_logged_out": "preflight_batch_login으로 자동 로그인 후 READY"',
        "로그아웃 채널은 선제 일괄 로그인 완료",
        "scripts/rps_switch.sh + 사람 결정",
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
        "docs/engineering/linkedin-managed-autologin-goal-2026-07-26.md": (
            "historical_input_not_executable"
        ),
        "docs/engineering/login-policy-recement-goal-2026-07-08.md": (
            "historical_input_not_executable"
        ),
        "docs/ai-search/qa-linkedin-autologin-sot-2026-06-09.md": (
            "historical_input_not_executable"
        ),
        "docs/ai-search/three-mac-account-coordinator-goal-prompt.md": (
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
        text = _text(path)
        assert "APP 30/31" in text, path
        assert "tools.install_login_skill" not in text, path
        assert "금지 경로 강제 Hook" not in text, path
        assert "레거시·불완전" in text, path
        for marker in (
            "사이트별 허용·금지·인계 표",
            "| 사람인 |",
            "| 잡코리아 |",
            "| LinkedIn RPS |",
            "기기 수 미증명은 인증 조작 0회",
        ):
            assert marker in text, (path, marker)


def test_login_search_execution_contract_cannot_restore_legacy_login() -> None:
    text = _text(SEARCH_CONTRACT_PATH)
    for forbidden in (
        "Hermes",
        "tools.multi_position_sourcing.portal_login",
        "정상 로그아웃이면 정식 `portal_login` 러너가 저장 자격증명을 1회만 제출",
        "ready=true`가 아니면 검색 잡은 `paused_for_human`",
        "Hook 차단은 작업 포기 신호가 아닙니다",
    ):
        assert forbidden not in text
    for required in (
        POLICY_ID,
        "APP 17",
        "APP 30/31",
        "LINKEDIN_LI_AT",
        "인증 기기 수 미증명",
        "HANDOFF",
        "2개 이상",
        "AUTH_CONFLICT",
        "PAUSED_FOR_HUMAN은 실제 HUMAN_AUTH에서만",
        "HANDOFF·AUTH_CONFLICT에는 사용하지 않는다",
    ):
        assert required in text


def test_multisearch_entrypoint_uses_the_site_specific_policy() -> None:
    for path in MULTISEARCH_SKILL_PATHS:
        text = _text(path)
        for forbidden in (
            "Hermes",
            "3사 모두 자동 로그인합니다",
            "`linkedin_rps:username`",
            "`linkedin_rps:password`",
            "tools.multi_position_sourcing.portal_login",
            "LinkedIn은 열린 headed Chrome에 CDP로 attach하고, 기존 세션이 없으면 "
            "`.env.local`/Keychain 자격증명으로 자동 로그인",
        ):
            assert forbidden not in text, (path, forbidden)
        for required in (
            POLICY_ID,
            "APP 17",
            "APP 30/31",
            "LINKEDIN_LI_AT",
            "인증 기기 수 미증명",
            "인증 조작 0회",
            "HANDOFF",
            "AUTH_CONFLICT",
        ):
            assert required in text, (path, required)


def test_ai_search_skills_do_not_collapse_policy_states() -> None:
    for path in AI_SEARCH_SKILL_PATHS:
        text = _text(path)
        for forbidden in (
            "classify each channel as `READY`, `OCCUPIED`, or `BLOCKED`",
            "각 채널을 `READY`/`OCCUPIED`/`BLOCKED`로 분류",
            "Auto-login is allowed only for a proven ordinary logout",
            "캡차·2FA·봇차단·로그인캡·LinkedIn 멀티세션락 → 해당 채널 STOP",
        ):
            assert forbidden not in text, (path, forbidden)
        for required in (
            POLICY_ID,
            "READY",
            "OCCUPIED",
            "HUMAN_AUTH",
            "HANDOFF",
            "AUTH_CONFLICT",
            "APP 17",
            "APP 30/31",
            "인증 기기 수 미증명",
        ):
            assert required in text, (path, required)


def test_search_access_cannot_authorize_linkedin_password_login() -> None:
    text = _text(ROOT / "docs/search-access.md")
    for forbidden in (
        "auto-login is never disabled",
        "LINKEDIN_USERNAME",
        "LINKEDIN_PASSWORD",
        "runner auto-logs in like the other portals",
        "Auto-login + search/collect is always allowed",
    ):
        assert forbidden not in text
    for required in (
        POLICY_ID,
        "APP 17",
        "APP 30/31",
        "LINKEDIN_LI_AT",
        "인증 기기 수 미증명",
        "HANDOFF",
        "AUTH_CONFLICT",
    ):
        assert required in text


def test_humansearch_entrypoints_preserve_handoff_vs_conflict() -> None:
    for path in HUMANSEARCH_SKILL_PATHS:
        text = _text(path)
        for forbidden in (
            "target/profile/endpoint가 맞지 않으면 `AUTH_CONFLICT`",
            "target/profile/endpoint 불일치는 `AUTH_CONFLICT`",
            "캡차·2FA·세션충돌이면 STOP",
        ):
            assert forbidden not in text, (path, forbidden)
        for required in (
            POLICY_ID,
            "APP 17",
            "APP 30/31",
            "LINKEDIN_LI_AT",
            "인증 기기 수 미증명",
            "HANDOFF",
            "인증 기기 2개 이상",
            "AUTH_CONFLICT",
            "HUMAN_AUTH",
        ):
            assert required in text, (path, required)


def test_ai_search_status_vocabulary_matches_the_login_policy() -> None:
    process = _json(ROOT / "docs/sot/25-ai-search-execution-process.json")
    assert process["version"] == "1.2.0"
    assert process["updated_at"] == "2026-07-26"

    stage1 = next(stage for stage in process["stages"] if stage["id"] == "1_occupancy_captcha_gate")
    stage9 = next(stage for stage in process["stages"] if stage["id"] == "9_report")
    assert "status=BLOCKED" not in "\n".join(stage1["actions"])
    assert "HUMAN_AUTH" in stage1["decision_tree"]["channel_captcha_detected"]
    assert "AUTH_CONFLICT" in stage1["decision_tree"]["linkedin_multiple_authenticated_or_multisession"]
    for status in ("READY", "OCCUPIED", "HUMAN_AUTH", "HANDOFF", "AUTH_CONFLICT"):
        assert status in stage9["pass_criteria"]
    assert "BLOCKED" not in stage9["pass_criteria"]
    assert "HUMAN_AUTH" in process["gates"]["G_captcha"]
    assert "BLOCKED" not in process["gates"]["G_captcha"]


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
        assert "AUTH_CONFLICT" in prompt
        assert "인증 기기가 정확히 1개" in prompt
        assert "인증 조작 0회" in prompt
        assert "신뢰도 기반 선택" in prompt
        assert "인증 기기 수 미증명" in prompt
        assert "APP 17" in prompt
    assert "저장 자격증명으로 자동 로그인·재로그인을 항상 수행할 것" not in login_prompt
    assert "linkedin_rps_logged_in=true인 머신을 먼저 찾아" not in url_prompt
    assert "HUMAN_AUTH일 때만 다음 형식" in url_prompt
    assert (
        "HANDOFF 또는 AUTH_CONFLICT면 PAUSED_FOR_HUMAN 마커와 "
        "완료 영수증을 출력하지 말고"
    ) in url_prompt


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

    active = "\n".join(
        _text(path) for path in (*LOGIN_SKILL_PATHS, *CONTROL_PATHS, POLICY_PATH)
    )
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
