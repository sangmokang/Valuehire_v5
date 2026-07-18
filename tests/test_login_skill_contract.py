"""공용 login 스킬 계약 — 사람/AI 브라우저 충돌과 로그인 세션 유실을 막는다."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.codex_skill_sync.sync import sync_skills
from tools.install_login_skill import install_login_skill


REPO = Path(__file__).resolve().parent.parent
CANONICAL_DIR = REPO / "skills" / "login"
CANONICAL = CANONICAL_DIR / "SKILL.md"
CONTRACT = CANONICAL_DIR / "browser-control-contract.json"
CLAUDE_DIR = REPO / ".claude" / "skills" / "login"
CLAUDE = CLAUDE_DIR / "SKILL.md"
CLAUDE_CONTRACT = CLAUDE_DIR / "browser-control-contract.json"


def _text(path: Path) -> str:
    assert path.is_file(), f"login 스킬 부재: {path}"
    return path.read_text(encoding="utf-8")


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _frontmatter_keys(text: str) -> set[str]:
    assert text.startswith("---\n")
    end = text.find("\n---", 4)
    assert end > 0
    return {
        line.split(":", 1)[0].strip()
        for line in text[4:end].splitlines()
        if line and not line.startswith((" ", "\t", "-")) and ":" in line
    }


def test_login_skill_is_portable_and_has_single_repo_source() -> None:
    canonical = _text(CANONICAL)
    assert _tree_bytes(CANONICAL_DIR) == _tree_bytes(CLAUDE_DIR)
    assert _frontmatter_keys(canonical) == {"name", "description"}
    assert "name: login" in canonical
    assert all(agent in canonical for agent in ("Claude", "Codex", "Hermes"))


def test_login_skill_defines_strict_browser_ownership_state_machine() -> None:
    text = _text(CANONICAL)
    markers = (
        "DISCOVER",
        "HUMAN_ACTIVE",
        "AI_ATTACHED",
        "HUMAN_AUTH",
        "AUTHENTICATED",
        "KEEPALIVE",
        "HANDOFF",
        "15초",
        "키 입력",
        "마우스",
        "무조작",
    )
    missing = [marker for marker in markers if marker not in text]
    assert not missing, f"점유 상태기계 마커 누락: {missing}"


def test_login_skill_reuses_browser_and_never_closes_human_session() -> None:
    text = _text(CANONICAL)
    markers = (
        "CDP",
        "기존 브라우저",
        "새 브라우저를 열지 않는다",
        "새 창 0개",
        "새 탭 0개",
        "context.close()",
        "browser.close()",
        "창을 닫지 않는다",
        "탭을 닫지 않는다",
        "프로필을 삭제하지 않는다",
        "vh-automation-badge",
        "VH_BUSY_AGENT",
        "VH_BUSY_TASK",
    )
    missing = [marker for marker in markers if marker not in text]
    assert not missing, f"브라우저/세션 보호 마커 누락: {missing}"


def test_login_skill_defines_auth_proof_lifetime_and_safe_keepalive() -> None:
    text = _text(CANONICAL)
    markers = (
        "authenticated_at",
        "last_verified_at",
        "session_age_seconds",
        "last_keepalive_at",
        "30분",
        "프로필 상세",
        "읽기 전용",
        "30분 하나",
        "로그인 마커",
        "로그아웃",
        "AUTH_LOST",
    )
    missing = [marker for marker in markers if marker not in text]
    assert not missing, f"세션 수명/유지 마커 누락: {missing}"


def test_login_skill_has_site_specific_proof_and_challenge_stop_rules() -> None:
    text = _text(CANONICAL)
    markers = (
        "사람인",
        "input.search_input",
        "#career_min",
        "잡코리아",
        "/Corp/Person/Find",
        "LinkedIn",
        "/talent/",
        "captcha",
        "2FA",
        "checkpoint",
        "자동 우회하지 않는다",
        "세션 충돌",
    )
    missing = [marker for marker in markers if marker not in text]
    assert not missing, f"사이트별 로그인 증명/보안 중단 마커 누락: {missing}"


def test_codex_sync_classifies_login_as_full(tmp_path: Path) -> None:
    result = sync_skills([REPO / ".claude" / "skills", REPO / "skills"], tmp_path / "codex")
    assert result["classification"].get("login") == "full"
    assert (tmp_path / "codex" / "login" / "SKILL.md").read_text(encoding="utf-8") == _text(CANONICAL)


def test_machine_contract_is_identical_and_fail_closed() -> None:
    canonical = json.loads(_text(CONTRACT))
    assert _text(CONTRACT) == _text(CLAUDE_CONTRACT)
    assert canonical["state_machine"]["HUMAN_AUTH"]["allowed_actions"] == ["read_state", "wait"]
    assert canonical["state_machine"]["HUMAN_AUTH"]["timeout_seconds"] is None
    assert canonical["browser_limits"] == {
        "max_new_windows_when_browser_exists": 0,
        "max_new_tabs_per_site": 0,
        "max_attached_targets_per_site": 1,
    }
    assert set(canonical["forbidden_calls"]) >= {
        "connectOverCDP",
        "new_page",
        "page.close",
        "context.close",
        "browser.close",
        "kill_browser",
    }
    assert canonical["keepalive"]["navigation_default"] == "skip"
    assert canonical["keepalive"]["require_fresh_owner_idle_check"] is True
    assert canonical["keepalive"]["require_dedicated_safe_tab"] is True
    assert canonical["keepalive"]["interval_seconds"] == {
        "saramin": 900,
        "jobkorea": 900,
        "linkedin_rps": 1800,
    }
    assert canonical["keepalive"]["restore_method"] == "Page.navigateToHistoryEntry"
    assert canonical["keepalive"]["goto_fallback"] is False
    assert canonical["exact_window"]["resolver"] == "Swift CoreGraphics"
    assert canonical["exact_window"]["ambiguity"] == "fail_closed"
    assert canonical["exact_window"]["capture"] == "screencapture -x -l <CGWindowID>"
    assert canonical["human_auth"]["max_presentations_per_episode"] == 1
    assert canonical["human_auth"]["minimum_poll_seconds"] == 5
    assert canonical["human_auth"]["quiet_after_owner_input_seconds"] == 15
    assert canonical["human_auth"]["timeout_seconds"] is None
    assert canonical["badge"]["required_before_first_mutation"] is True
    assert canonical["ownership_lease"]["acquire"] == "atomic_mkdir"
    assert canonical["ownership_lease"]["required_before_discover_or_create"] is True
    assert canonical["mutation_guard"] == {
        "required_before_every_mutation": True,
        "idle_checks": 2,
        "quiet_dwell_seconds": 1,
        "minimum_idle_seconds": 180,
        "lease_token_recheck": True,
        "failure_state": "HUMAN_ACTIVE",
    }


def test_skill_does_not_recommend_unsafe_legacy_login_runner() -> None:
    text = _text(CANONICAL)
    assert "python3 -m tools.multi_position_sourcing.portal_login" not in text
    assert "보존 모드가 아니므로 사용 금지" in text
    assert "--human-timeout-seconds 1800" not in text
    assert "`HUMAN_AUTH` 중 navigate" in text and "금지" in text
    assert "모든 변경 조작 직전" in text
    assert "1초" in text and "두 번" in text
    assert "원자적 디렉터리" in text
    assert "점유권을 얻지 못하면" in text


def test_installer_targets_only_three_agent_skill_directories(tmp_path: Path) -> None:
    for agent in ("claude", "codex", "hermes"):
        target = tmp_path / f".{agent}" / "skills" / "login"
        target.mkdir(parents=True)
        (target / "stale.txt").write_text("remove me", encoding="utf-8")
        sibling = tmp_path / f".{agent}" / "skills" / "sibling"
        sibling.mkdir(parents=True)
        (sibling / "sentinel").write_text("keep me", encoding="utf-8")
    result = install_login_skill(repo_root=REPO, home=tmp_path)
    assert set(result) == {"claude", "codex", "hermes"}
    for agent, path in result.items():
        target = Path(path)
        assert target == tmp_path / f".{agent}" / "skills" / "login"
        assert _tree_bytes(target) == _tree_bytes(CANONICAL_DIR)
        assert not (target / "stale.txt").exists()
        assert (target.parent / "sibling" / "sentinel").read_text() == "keep me"


def test_login_tree_contains_bundled_swift_window_locator() -> None:
    locator = CANONICAL_DIR / "scripts" / "macos_window_locator.swift"
    assert locator.is_file() and locator.stat().st_size > 0
    assert b"CoreGraphics" in locator.read_bytes()


def test_installer_preflights_nested_asset_before_mutating_any_agent(tmp_path: Path) -> None:
    fake_repo = tmp_path / "repo"
    source = fake_repo / "skills" / "login"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("x", encoding="utf-8")
    (source / "browser-control-contract.json").write_text("{}", encoding="utf-8")
    home = tmp_path / "home"
    before: dict[str, bytes] = {}
    for agent in ("claude", "codex", "hermes"):
        target = home / f".{agent}" / "skills" / "login"
        target.mkdir(parents=True)
        sentinel = target / "sentinel"
        sentinel.write_text(agent, encoding="utf-8")
        before[agent] = sentinel.read_bytes()
    with pytest.raises(FileNotFoundError):
        install_login_skill(repo_root=fake_repo, home=home)
    for agent, expected in before.items():
        assert (home / f".{agent}" / "skills" / "login" / "sentinel").read_bytes() == expected
