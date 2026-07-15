"""공용 login 스킬 계약 — 사람/AI 브라우저 충돌과 로그인 세션 유실을 막는다."""
from __future__ import annotations

from pathlib import Path

from tools.codex_skill_sync.sync import sync_skills


REPO = Path(__file__).resolve().parent.parent
CANONICAL = REPO / "skills" / "login" / "SKILL.md"
CLAUDE = REPO / ".claude" / "skills" / "login" / "SKILL.md"


def _text(path: Path) -> str:
    assert path.is_file(), f"login 스킬 부재: {path}"
    return path.read_text(encoding="utf-8")


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
    claude = _text(CLAUDE)
    assert canonical == claude
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
        "새 탭 1개",
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
        "최소 10분",
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
