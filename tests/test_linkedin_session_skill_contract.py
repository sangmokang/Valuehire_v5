from __future__ import annotations

import json
from pathlib import Path

from tools.codex_skill_sync.sync import sync_skills
from tools.install_login_skill import install_login_skill


ROOT = Path(__file__).resolve().parents[1]


def test_codex_and_claude_entry_skills_share_session_context_rule() -> None:
    skill_paths = (
        "skills/login/SKILL.md",
        ".claude/skills/login/SKILL.md",
        "skills/humansearch/SKILL.md",
        ".claude/skills/humansearch/SKILL.md",
        "skills/ai-search/SKILL.md",
        ".claude/skills/aisearch/SKILL.md",
        ".claude/skills/url/SKILL.md",
    )
    for relative in skill_paths:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "SESSION_CONTEXT_PRESERVATION" in text, relative
        assert "AUTH_CONFLICT" in text, relative
        assert "navigation_url" in text, relative


def test_login_contract_separates_session_conflict_from_auth_lost() -> None:
    contract_paths = (
        "skills/login/browser-control-contract.json",
        ".claude/skills/login/browser-control-contract.json",
    )
    payloads = [
        json.loads((ROOT / relative).read_text(encoding="utf-8"))
        for relative in contract_paths
    ]
    assert payloads[0] == payloads[1]
    conflict = payloads[0]["state_machine"]["AUTH_CONFLICT"]
    assert conflict["terminal"] is True
    assert conflict["repeat_handoff"] is False
    assert "autologin" in conflict["forbidden_actions"]
    assert "confirm_session_choice" in conflict["forbidden_actions"]
    assert "enterprise-authentication/sessions" in conflict["reason_markers"]
    assert "AUTH_CONFLICT" in payloads[0]["state_machine"]["DISCOVER"]["next"]


def test_login_skill_has_one_terminal_session_conflict_instruction() -> None:
    text = (ROOT / "skills/login/SKILL.md").read_text(encoding="utf-8")

    assert "세션 충돌이면 즉시 `HUMAN_AUTH`" not in text
    assert "세션 충돌, LinkedIn multiple-sign-in 화면은 즉시 사람에게 넘긴다" not in text
    assert "사람이 사용할 세션을 결정" not in text
    assert "LinkedIn 세션 충돌 | 계속 클릭 금지; 다른 로그인 머신/세션 탐색 후 사람 결정" not in text
    assert "자동 로그인·Continue/Confirm 클릭·세션 종료 선택" in text
    assert "terminal `AUTH_CONFLICT`" in text


def test_real_install_paths_receive_the_same_session_conflict_contract(tmp_path: Path) -> None:
    installed_login = install_login_skill(repo_root=ROOT, home=tmp_path)
    for target in installed_login.values():
        installed = Path(target)
        assert (installed / "SKILL.md").read_bytes() == (
            ROOT / "skills/login/SKILL.md"
        ).read_bytes()
        assert json.loads(
            (installed / "browser-control-contract.json").read_text(encoding="utf-8")
        )["state_machine"]["AUTH_CONFLICT"]["terminal"] is True

    codex_dest = tmp_path / ".codex-session-context" / "skills"
    sync_skills(
        [ROOT / "skills", ROOT / ".claude/skills"],
        codex_dest,
    )
    for skill_name in ("login", "humansearch", "ai-search", "url"):
        text = (codex_dest / skill_name / "SKILL.md").read_text(encoding="utf-8")
        assert "SESSION_CONTEXT_PRESERVATION" in text, skill_name
        assert "AUTH_CONFLICT" in text, skill_name


def test_session_context_regression_fixtures_never_persist_auth_tokens() -> None:
    fixture = (ROOT / "tests/test_linkedin_rps_session_context.py").read_text(
        encoding="utf-8"
    )
    assert "authToken" not in fixture


def test_login_skill_mirrors_are_byte_identical() -> None:
    assert (ROOT / "skills/login/SKILL.md").read_bytes() == (
        ROOT / ".claude/skills/login/SKILL.md"
    ).read_bytes()
    assert (ROOT / "skills/login/browser-control-contract.json").read_bytes() == (
        ROOT / ".claude/skills/login/browser-control-contract.json"
    ).read_bytes()
