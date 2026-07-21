"""공용 login 스킬 계약 — 사람/AI 브라우저 충돌과 로그인 세션 유실을 막는다."""
from __future__ import annotations

import json
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from tools.codex_skill_sync.sync import sync_skills
import tools.install_login_skill as installer_module
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


def _copy_canonical_source(tmp_path: Path) -> Path:
    fake_repo = tmp_path / "repo"
    shutil.copytree(CANONICAL_DIR, fake_repo / "skills" / "login")
    return fake_repo


def _seed_agent_installs(home: Path) -> dict[str, dict[str, bytes]]:
    expected: dict[str, dict[str, bytes]] = {}
    for agent in ("claude", "codex", "hermes"):
        target = home / f".{agent}" / "skills" / "login"
        target.mkdir(parents=True)
        (target / "sentinel.txt").write_text(f"old-{agent}", encoding="utf-8")
        expected[agent] = _tree_bytes(target)
    return expected


def _installer_residues(home: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in home.rglob("*")
            if path.name.startswith(
                (".login-backup-", ".login-failed-", ".login-skill-stage-")
            )
        ),
        key=str,
    )


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
    assert canonical["schema_version"] == "1.3.0"
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
    assert canonical["exact_window"][
        "require_exact_cg_window_id_frontmost_layer0_after_activation"
    ] is True
    assert canonical["exact_window"]["capture_cleanup_failure"] == "fail_closed"
    assert canonical["human_auth"]["max_presentations_per_episode"] == 1
    assert canonical["human_auth"]["minimum_poll_seconds"] == 5
    assert canonical["human_auth"]["quiet_after_owner_input_seconds"] == 15
    assert canonical["human_auth"]["timeout_seconds"] is None
    assert canonical["human_auth"]["success_requires_owner_activity_detected_false"] is True
    assert canonical["human_auth"]["cleanup_attempted_on_stop_or_base_exception"] is True
    assert canonical["badge"]["required_before_first_mutation"] is True
    assert canonical["ownership_lease"]["acquire"] == "atomic_mkdir"
    assert canonical["ownership_lease"]["required_before_discover_or_create"] is True
    assert canonical["managed_process"]["profile_flag_parser"] == (
        "macos_ps_unquoted_long_option_boundaries"
    )
    assert canonical["keepalive"]["safe_link"]["unsafe_url_decode_passes"] == 4
    assert canonical["keepalive"]["stable_consecutive_target_auth_history_proofs"] == 2
    assert canonical["mutation_guard"] == {
        "required_before_every_mutation": True,
        "idle_checks": 2,
        "quiet_dwell_seconds": 1,
        "minimum_idle_seconds": 60,
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
    assert _installer_residues(tmp_path) == []


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


def test_installer_rejects_unknown_canonical_file_before_mutation(tmp_path: Path) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    source = fake_repo / "skills" / "login"
    (source / "unexpected-secret.txt").write_text("must not be copied", encoding="utf-8")
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)

    with pytest.raises(ValueError, match="unknown"):
        install_login_skill(repo_root=fake_repo, home=home)

    for agent, tree in expected.items():
        assert _tree_bytes(home / f".{agent}" / "skills" / "login") == tree


@pytest.mark.parametrize(
    ("relative_name", "invalid_bytes"),
    [
        ("browser-control-contract.json", b"{not-json"),
        ("SKILL.md", b"---\nname: not-login\ndescription: wrong\n---\n"),
        ("scripts/macos_window_locator.swift", b'import Foundation\nprint("not a locator")\n'),
    ],
)
def test_installer_validates_canonical_payloads_before_mutation(
    tmp_path: Path,
    relative_name: str,
    invalid_bytes: bytes,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    (fake_repo / "skills" / "login" / relative_name).write_bytes(invalid_bytes)
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)

    with pytest.raises(ValueError):
        install_login_skill(repo_root=fake_repo, home=home)

    for agent, tree in expected.items():
        assert _tree_bytes(home / f".{agent}" / "skills" / "login") == tree


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("stop"), SystemExit(17)])
def test_installer_rolls_back_all_agents_on_base_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)
    original_replace = installer_module._replace_path

    def interrupted_replace(
        self: Path,
        target: Path,
        **kwargs: object,
    ) -> Path:
        if ".login-skill-stage-" in str(self) and self.name == "codex":
            raise interruption
        return original_replace(self, target, **kwargs)

    monkeypatch.setattr(installer_module, "_replace_path", interrupted_replace)
    with pytest.raises(type(interruption)):
        install_login_skill(repo_root=fake_repo, home=home)

    for agent, tree in expected.items():
        assert _tree_bytes(home / f".{agent}" / "skills" / "login") == tree


def test_installer_preserves_untouched_targets_when_backup_phase_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)
    original_replace = installer_module._replace_path
    codex_target = home / ".codex" / "skills" / "login"

    def interrupted_backup(
        self: Path,
        target: Path,
        **kwargs: object,
    ) -> Path:
        if self == codex_target and Path(target).name.startswith(".login-backup-"):
            raise KeyboardInterrupt("backup interrupted")
        return original_replace(self, target, **kwargs)

    monkeypatch.setattr(installer_module, "_replace_path", interrupted_backup)
    with pytest.raises(KeyboardInterrupt, match="backup interrupted"):
        install_login_skill(repo_root=fake_repo, home=home)

    for agent, tree in expected.items():
        assert _tree_bytes(home / f".{agent}" / "skills" / "login") == tree


def test_installer_restores_when_interrupted_immediately_after_backup_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)
    original_replace = installer_module._replace_path
    codex_target = home / ".codex" / "skills" / "login"

    def interrupt_after_backup_rename(
        source: Path,
        destination: Path,
        **kwargs: object,
    ) -> Path:
        result = original_replace(source, destination, **kwargs)
        if source == codex_target and destination.name.startswith(".login-backup-"):
            raise KeyboardInterrupt("interrupted after backup rename")
        return result

    monkeypatch.setattr(
        installer_module,
        "_replace_path",
        interrupt_after_backup_rename,
    )
    with pytest.raises(KeyboardInterrupt, match="after backup rename"):
        install_login_skill(repo_root=fake_repo, home=home)

    for agent, tree in expected.items():
        assert _tree_bytes(home / f".{agent}" / "skills" / "login") == tree
    assert _installer_residues(home) == []


def test_installer_verifies_installed_bytes_before_deleting_backups(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)
    original_replace = installer_module._replace_path

    def corrupting_replace(
        self: Path,
        target: Path,
        **kwargs: object,
    ) -> Path:
        result = original_replace(self, target, **kwargs)
        if ".login-skill-stage-" in str(self) and self.name == "codex":
            (Path(target) / "SKILL.md").write_text("corrupted after replace", encoding="utf-8")
        return result

    monkeypatch.setattr(installer_module, "_replace_path", corrupting_replace)
    with pytest.raises(RuntimeError, match="verification"):
        install_login_skill(repo_root=fake_repo, home=home)

    for agent, tree in expected.items():
        assert _tree_bytes(home / f".{agent}" / "skills" / "login") == tree


def test_installer_rechecks_canonical_source_after_all_target_swaps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    source_skill = fake_repo / "skills" / "login" / "SKILL.md"
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)
    original_replace = installer_module._replace_path
    changed_source = False

    def source_drift_after_first_swap(
        self: Path,
        target: Path,
        **kwargs: object,
    ) -> Path:
        nonlocal changed_source
        result = original_replace(self, target, **kwargs)
        if (
            not changed_source
            and ".login-skill-stage-" in str(self)
            and self.name == "claude"
        ):
            source_skill.write_text(
                source_skill.read_text(encoding="utf-8")
                + "\n동시 변경은 설치 성공으로 오인하면 안 된다.\n",
                encoding="utf-8",
            )
            changed_source = True
        return result

    monkeypatch.setattr(installer_module, "_replace_path", source_drift_after_first_swap)
    with pytest.raises(RuntimeError, match="source changed"):
        install_login_skill(repo_root=fake_repo, home=home)

    for agent, tree in expected.items():
        assert _tree_bytes(home / f".{agent}" / "skills" / "login") == tree
    assert _installer_residues(home) == []


def test_installer_backup_cleanup_failure_never_returns_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    _seed_agent_installs(home)
    original_remove_path = installer_module._remove_path
    cleanup_failed = False

    def fail_first_backup_cleanup(path: Path, **kwargs: object) -> None:
        nonlocal cleanup_failed
        if path.name.startswith(".login-backup-") and not cleanup_failed:
            cleanup_failed = True
            raise OSError("injected backup cleanup failure")
        original_remove_path(path, **kwargs)

    monkeypatch.setattr(installer_module, "_remove_path", fail_first_backup_cleanup)
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        install_login_skill(repo_root=fake_repo, home=home)

    assert cleanup_failed is True
    for agent in ("claude", "codex", "hermes"):
        target = home / f".{agent}" / "skills" / "login"
        assert _tree_bytes(target) == _tree_bytes(CANONICAL_DIR)
    assert any(path.name.startswith(".login-backup-") for path in _installer_residues(home))


def test_installer_rejects_preexisting_transaction_residue_before_mutation(
    tmp_path: Path,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)
    residue = home / ".claude" / "skills" / ".login-backup-abandoned"
    residue.mkdir()
    (residue / "sentinel").write_text("manual recovery required", encoding="utf-8")

    with pytest.raises(RuntimeError, match="residue"):
        install_login_skill(repo_root=fake_repo, home=home)

    for agent, tree in expected.items():
        assert _tree_bytes(home / f".{agent}" / "skills" / "login") == tree
    assert residue.is_dir()


def test_installer_reverifies_final_target_bytes_after_backup_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    _seed_agent_installs(home)
    original_remove_path = installer_module._remove_path
    corrupted = False
    codex_skill = home / ".codex" / "skills" / "login" / "SKILL.md"

    def corrupt_after_backup_cleanup(path: Path, **kwargs: object) -> None:
        nonlocal corrupted
        original_remove_path(path, **kwargs)
        if path.name.startswith(".login-backup-") and not corrupted:
            codex_skill.write_text("corrupted during commit cleanup", encoding="utf-8")
            corrupted = True

    monkeypatch.setattr(installer_module, "_remove_path", corrupt_after_backup_cleanup)
    with pytest.raises(RuntimeError, match="final verification"):
        install_login_skill(repo_root=fake_repo, home=home)

    assert corrupted is True


def test_installer_detects_backup_renamed_during_commit_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    _seed_agent_installs(home)
    original_remove_path = installer_module._remove_path
    renamed_backup: Path | None = None

    def rename_instead_of_deleting(path: Path, **kwargs: object) -> None:
        nonlocal renamed_backup
        if path.name.startswith(".login-backup-") and renamed_backup is None:
            renamed_backup = path.parent / "old-login-tree-hidden-by-rename"
            path.replace(renamed_backup)
            return
        original_remove_path(path, **kwargs)

    monkeypatch.setattr(installer_module, "_remove_path", rename_instead_of_deleting)
    with pytest.raises(RuntimeError, match="backup|commit|cleanup"):
        install_login_skill(repo_root=fake_repo, home=home)

    assert renamed_backup is not None and renamed_backup.is_dir()


def test_installer_rejects_final_parent_symlink_swap_even_when_bytes_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    _seed_agent_installs(home)
    original_remove_path = installer_module._remove_path
    swapped = False

    def swap_parent_after_staging_cleanup(path: Path, **kwargs: object) -> None:
        nonlocal swapped
        original_remove_path(path, **kwargs)
        if path.name.startswith(".login-skill-stage-") and not swapped:
            skills_parent = home / ".codex" / "skills"
            replacement = home / "codex-skills-replacement"
            skills_parent.replace(replacement)
            skills_parent.symlink_to(replacement, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(installer_module, "_remove_path", swap_parent_after_staging_cleanup)
    with pytest.raises(RuntimeError, match="parent|symlink|final|commit"):
        install_login_skill(repo_root=fake_repo, home=home)

    assert swapped is True


def test_installer_never_mutates_external_tree_after_parent_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)
    codex_target = home / ".codex" / "skills" / "login"
    skills_parent = codex_target.parent
    detached_parent = home / "codex-skills-detached"
    external_parent = tmp_path / "external-codex-skills"
    external_login = external_parent / "login"
    external_login.mkdir(parents=True)
    sentinel = external_login / "sentinel.txt"
    sentinel.write_text("outside installer scope", encoding="utf-8")
    original_replace = installer_module._replace_path
    swapped = False

    def swap_before_backup(
        source: Path,
        destination: Path,
        **kwargs: object,
    ) -> Path:
        nonlocal swapped
        if (
            not swapped
            and source == codex_target
            and destination.name.startswith(".login-backup-")
        ):
            skills_parent.replace(detached_parent)
            skills_parent.symlink_to(external_parent, target_is_directory=True)
            swapped = True
        return original_replace(source, destination, **kwargs)

    monkeypatch.setattr(installer_module, "_replace_path", swap_before_backup)
    with pytest.raises(RuntimeError, match="directory|rollback|install"):
        install_login_skill(repo_root=fake_repo, home=home)

    assert swapped is True
    assert sentinel.read_text(encoding="utf-8") == "outside installer scope"
    assert sorted(path.name for path in external_login.iterdir()) == ["sentinel.txt"]
    assert _tree_bytes(detached_parent / "login") == expected["codex"]


def test_installer_staging_writes_stay_in_anchored_directory_after_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    external_stage = tmp_path / "external-stage"
    external_stage.mkdir()
    detached_stage = home / "detached-original-stage"
    original_staged_tree = installer_module._staged_tree
    swapped = False

    def swap_live_stage(
        staging_anchor: object,
        agent: str,
        expected_files: dict[str, bytes],
    ) -> Path:
        nonlocal swapped
        if not swapped:
            stage_path = staging_anchor.path
            stage_path.replace(detached_stage)
            stage_path.symlink_to(external_stage, target_is_directory=True)
            swapped = True
        return original_staged_tree(staging_anchor, agent, expected_files)

    monkeypatch.setattr(installer_module, "_staged_tree", swap_live_stage)
    with pytest.raises(RuntimeError, match="staging|preparation|directory"):
        install_login_skill(repo_root=fake_repo, home=home)

    assert swapped is True
    assert list(external_stage.iterdir()) == []
    assert (detached_stage / "claude" / "SKILL.md").is_file()


def test_installer_rejects_stage_renamed_instead_of_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    _seed_agent_installs(home)
    original_remove_path = installer_module._remove_path
    renamed_stage = home / "renamed-staging-tree"
    renamed = False

    def rename_stage(path: Path, **kwargs: object) -> None:
        nonlocal renamed
        if path.name.startswith(".login-skill-stage-") and not renamed:
            path.replace(renamed_stage)
            renamed = True
            return
        original_remove_path(path, **kwargs)

    monkeypatch.setattr(installer_module, "_remove_path", rename_stage)
    with pytest.raises(RuntimeError, match="staging|cleanup|commit"):
        install_login_skill(repo_root=fake_repo, home=home)

    assert renamed is True
    assert renamed_stage.is_dir()


def test_installer_never_restores_replaced_backup_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)
    codex_target = home / ".codex" / "skills" / "login"
    hidden_original = home / ".codex" / "skills" / "hidden-original-login"
    external_login = tmp_path / "external-login"
    external_login.mkdir()
    sentinel = external_login / "sentinel.txt"
    sentinel.write_text("outside installer scope", encoding="utf-8")
    original_replace = installer_module._replace_path
    tampered = False

    def replace_backup_then_fail_install(
        source: Path,
        destination: Path,
        **kwargs: object,
    ) -> Path:
        nonlocal tampered
        if (
            not tampered
            and ".login-skill-stage-" in str(source)
            and source.name == "codex"
        ):
            backups = sorted(codex_target.parent.glob(".login-backup-*"))
            assert len(backups) == 1
            backups[0].replace(hidden_original)
            backups[0].symlink_to(external_login, target_is_directory=True)
            tampered = True
            raise RuntimeError("forced install failure after backup replacement")
        return original_replace(source, destination, **kwargs)

    monkeypatch.setattr(
        installer_module,
        "_replace_path",
        replace_backup_then_fail_install,
    )
    with pytest.raises(RuntimeError, match="rollback incomplete"):
        install_login_skill(repo_root=fake_repo, home=home)

    assert tampered is True
    assert sentinel.read_text(encoding="utf-8") == "outside installer scope"
    assert not codex_target.exists() and not codex_target.is_symlink()
    assert _tree_bytes(hidden_original) == expected["codex"]


def test_installer_quarantines_backup_swapped_after_rollback_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)
    codex_target = home / ".codex" / "skills" / "login"
    hidden_original = home / ".codex" / "skills" / "hidden-original-login"
    external_login = tmp_path / "external-login"
    external_login.mkdir()
    sentinel = external_login / "sentinel.txt"
    sentinel.write_text("outside installer scope", encoding="utf-8")
    original_replace = installer_module._replace_path
    installation_failed = False
    tampered = False

    def swap_after_verification(
        source: Path,
        destination: Path,
        **kwargs: object,
    ) -> Path:
        nonlocal installation_failed, tampered
        if ".login-skill-stage-" in str(source) and source.name == "codex":
            installation_failed = True
            raise RuntimeError("forced install failure")
        if (
            installation_failed
            and not tampered
            and source.name.startswith(".login-backup-")
            and destination == codex_target
        ):
            source.replace(hidden_original)
            source.symlink_to(external_login, target_is_directory=True)
            tampered = True
        return original_replace(source, destination, **kwargs)

    monkeypatch.setattr(installer_module, "_replace_path", swap_after_verification)
    with pytest.raises(RuntimeError, match="rollback incomplete"):
        install_login_skill(repo_root=fake_repo, home=home)

    assert tampered is True
    assert sentinel.read_text(encoding="utf-8") == "outside installer scope"
    assert not codex_target.exists() and not codex_target.is_symlink()
    assert _tree_bytes(hidden_original) == expected["codex"]
    quarantines = list(codex_target.parent.glob(".login-failed-*"))
    assert len(quarantines) == 1
    assert quarantines[0].is_symlink()
    assert quarantines[0].resolve() == external_login


def test_installer_second_commit_snapshot_catches_source_drift_after_first_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    source_skill = fake_repo / "skills" / "login" / "SKILL.md"
    home = tmp_path / "home"
    _seed_agent_installs(home)
    original_verify_source = installer_module._verify_source_unchanged
    verification_count = 0

    def drift_after_first_final_source_pass(
        source: Path,
        expected_files: dict[str, bytes],
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal verification_count
        original_verify_source(source, expected_files, *args, **kwargs)
        verification_count += 1
        if verification_count == 3:
            source_skill.write_text(
                source_skill.read_text(encoding="utf-8")
                + "\n첫 최종 검사 뒤의 변경도 성공으로 처리하면 안 된다.\n",
                encoding="utf-8",
            )

    monkeypatch.setattr(
        installer_module,
        "_verify_source_unchanged",
        drift_after_first_final_source_pass,
    )
    with pytest.raises(RuntimeError, match="source changed|stable|commit|final"):
        install_login_skill(repo_root=fake_repo, home=home)


def test_installer_second_commit_snapshot_catches_target_drift_after_first_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    _seed_agent_installs(home)
    original_verify_tree = installer_module._verify_tree_matches
    hermes_verification_count = 0
    drifted = False

    def drift_after_first_final_target_pass(
        root: Path,
        expected_files: dict[str, bytes],
        *,
        label: str,
    ) -> None:
        nonlocal hermes_verification_count, drifted
        original_verify_tree(root, expected_files, label=label)
        if label.startswith("hermes "):
            hermes_verification_count += 1
            if hermes_verification_count == 3:
                (home / ".codex" / "skills" / "login" / "SKILL.md").write_text(
                    "drift after the first final target pass",
                    encoding="utf-8",
                )
                drifted = True

    monkeypatch.setattr(
        installer_module,
        "_verify_tree_matches",
        drift_after_first_final_target_pass,
    )
    with pytest.raises(RuntimeError, match="tree bytes differ|stable|commit|final"):
        install_login_skill(repo_root=fake_repo, home=home)

    assert drifted is True


def test_installer_rollback_verification_baseexception_never_skips_stage_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    _seed_agent_installs(home)
    original_replace = installer_module._replace_path
    original_optional_snapshot = installer_module._optional_tree_snapshot
    installation_failed = False
    interrupted_rollback_verification = False

    def fail_install(
        self: Path,
        target: Path,
        **kwargs: object,
    ) -> Path:
        nonlocal installation_failed
        if ".login-skill-stage-" in str(self) and self.name == "codex":
            installation_failed = True
            raise RuntimeError("original install failure")
        return original_replace(self, target, **kwargs)

    def interrupt_rollback_verification(
        target: Path,
    ) -> tuple[dict[str, bytes], frozenset[str]] | None:
        nonlocal interrupted_rollback_verification
        if installation_failed and not interrupted_rollback_verification:
            interrupted_rollback_verification = True
            raise KeyboardInterrupt("rollback verification interrupted")
        return original_optional_snapshot(target)

    monkeypatch.setattr(installer_module, "_replace_path", fail_install)
    monkeypatch.setattr(
        installer_module,
        "_optional_tree_snapshot",
        interrupt_rollback_verification,
    )
    with pytest.raises(RuntimeError, match="rollback incomplete") as caught:
        install_login_skill(repo_root=fake_repo, home=home)

    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "original install failure" in str(caught.value.__cause__)
    assert interrupted_rollback_verification is True
    assert not any(
        path.name.startswith(".login-skill-stage-")
        for path in home.iterdir()
    )


def test_installer_reports_incomplete_rollback_when_remove_and_quarantine_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)
    original_replace = installer_module._replace_path
    original_remove_path = installer_module._remove_path
    claude_target = home / ".claude" / "skills" / "login"

    def fail_install_and_quarantine(
        self: Path,
        target: Path,
        **kwargs: object,
    ) -> Path:
        if ".login-skill-stage-" in str(self) and self.name == "codex":
            raise RuntimeError("injected install failure")
        if self == claude_target and Path(target).name.startswith(".login-failed-"):
            raise OSError("injected quarantine failure")
        return original_replace(self, target, **kwargs)

    def fail_installed_target_removal(path: Path, **kwargs: object) -> None:
        if path == claude_target:
            raise OSError("injected target removal failure")
        original_remove_path(path, **kwargs)

    monkeypatch.setattr(installer_module, "_replace_path", fail_install_and_quarantine)
    monkeypatch.setattr(installer_module, "_remove_path", fail_installed_target_removal)
    with pytest.raises(RuntimeError, match="rollback incomplete") as caught:
        install_login_skill(repo_root=fake_repo, home=home)

    assert caught.value.__cause__ is not None
    assert "injected install failure" in str(caught.value.__cause__)
    for agent in ("codex", "hermes"):
        assert _tree_bytes(home / f".{agent}" / "skills" / "login") == expected[agent]
    assert _tree_bytes(claude_target) == _tree_bytes(CANONICAL_DIR)
    assert any(path.name.startswith(".login-backup-") for path in _installer_residues(home))


def test_installer_rollback_continues_after_one_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo = _copy_canonical_source(tmp_path)
    home = tmp_path / "home"
    expected = _seed_agent_installs(home)
    original_replace = installer_module._replace_path
    original_rmtree = installer_module.shutil.rmtree
    failed_once = False

    def interrupted_replace(
        self: Path,
        target: Path,
        **kwargs: object,
    ) -> Path:
        if ".login-skill-stage-" in str(self) and self.name == "codex":
            raise RuntimeError("injected install failure")
        return original_replace(self, target, **kwargs)

    def flaky_rmtree(path: object, *args: object, **kwargs: object) -> None:
        nonlocal failed_once
        if Path(path).name == "login" and kwargs.get("dir_fd") is not None and not failed_once:
            failed_once = True
            raise OSError("injected cleanup failure")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(installer_module, "_replace_path", interrupted_replace)
    monkeypatch.setattr(installer_module.shutil, "rmtree", flaky_rmtree)
    with pytest.raises(RuntimeError, match="injected install failure"):
        install_login_skill(repo_root=fake_repo, home=home)

    for agent, tree in expected.items():
        assert _tree_bytes(home / f".{agent}" / "skills" / "login") == tree


def test_installer_serializes_cross_process_installs_with_home_lock(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    lock_path = home / ".login-skill-install.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    code = (
        "from pathlib import Path; "
        "from tools.install_login_skill import install_login_skill; "
        "import sys; "
        "install_login_skill(repo_root=Path(sys.argv[1]), home=Path(sys.argv[2]))"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(REPO), str(home)],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(REPO)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(0.25)
        assert process.poll() is None, "installer ignored the held cross-process lock"
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0, (stdout, stderr)
