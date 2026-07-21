from __future__ import annotations

import json
from pathlib import Path


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


def test_login_skill_mirrors_are_byte_identical() -> None:
    assert (ROOT / "skills/login/SKILL.md").read_bytes() == (
        ROOT / ".claude/skills/login/SKILL.md"
    ).read_bytes()
    assert (ROOT / "skills/login/browser-control-contract.json").read_bytes() == (
        ROOT / ".claude/skills/login/browser-control-contract.json"
    ).read_bytes()
