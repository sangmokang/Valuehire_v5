"""RED-first tests for the Codex skill sync tool.

계약은 docs/engineering/codex-skill-sync-goal-2026-07-07.md 참조.
실제 ~/.claude, ~/.codex 를 절대 건드리지 않도록 전부 tmp_path 로 격리한다.
"""
from pathlib import Path

import pytest

from tools.codex_skill_sync.sync import sync_skills


def _make_skill(root: Path, name: str, body: str = "hello") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test {name}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return d


def test_copies_skill_that_has_skill_md(tmp_path):
    src = tmp_path / "claude"
    dest = tmp_path / "codex"
    _make_skill(src, "brand-guidelines")
    res = sync_skills([src], dest)
    assert "brand-guidelines" in res["copied"]
    assert (dest / "brand-guidelines" / "SKILL.md").is_file()


def test_ignores_dir_without_skill_md(tmp_path):
    src = tmp_path / "claude"
    dest = tmp_path / "codex"
    (src / "not-a-skill").mkdir(parents=True)
    (src / "not-a-skill" / "README.md").write_text("x", encoding="utf-8")
    res = sync_skills([src], dest)
    assert "not-a-skill" not in res["copied"]
    assert not (dest / "not-a-skill").exists()


def test_never_touches_dot_system_in_dest(tmp_path):
    src = tmp_path / "claude"
    dest = tmp_path / "codex"
    system_marker = dest / ".system" / "marker.txt"
    system_marker.parent.mkdir(parents=True)
    system_marker.write_text("KEEP", encoding="utf-8")
    # a hidden source skill must be ignored too
    _make_skill(src, ".hidden-skill")
    _make_skill(src, "harness")
    sync_skills([src], dest)
    assert system_marker.read_text(encoding="utf-8") == "KEEP"
    assert not (dest / ".hidden-skill").exists()
    assert (dest / "harness").exists()


def test_adapted_aliases_are_skipped_by_default(tmp_path):
    src = tmp_path / "claude"
    dest = tmp_path / "codex"
    for n in ("strict", "aisearch", "weekly-update"):
        _make_skill(src, n)
    res = sync_skills([src], dest)
    for n in ("strict", "aisearch", "weekly-update"):
        assert n not in res["copied"]
        assert not (dest / n).exists()
    skipped_names = {name for name, _reason in res["skipped"]}
    assert {"strict", "aisearch", "weekly-update"} <= skipped_names


def test_force_aliases_copies_them(tmp_path):
    src = tmp_path / "claude"
    dest = tmp_path / "codex"
    _make_skill(src, "strict")
    res = sync_skills([src], dest, force_aliases=True)
    assert "strict" in res["copied"]


def test_collision_first_source_wins(tmp_path):
    src_a = tmp_path / "a"
    src_b = tmp_path / "b"
    dest = tmp_path / "codex"
    _make_skill(src_a, "humansearch", body="FROM_A")
    _make_skill(src_b, "humansearch", body="FROM_B")
    res = sync_skills([src_a, src_b], dest)
    assert (dest / "humansearch" / "SKILL.md").read_text(encoding="utf-8").find("FROM_A") != -1
    assert any(c[0] == "humansearch" for c in res["collisions"])


def test_classification_full_vs_partial(tmp_path):
    src = tmp_path / "claude"
    dest = tmp_path / "codex"
    _make_skill(src, "docx", body="pure knowledge, no tools")
    _make_skill(src, "saramin", body="uses mcp__claude-in-chrome__computer to click")
    res = sync_skills([src], dest)
    assert res["classification"]["docx"] == "full"
    assert res["classification"]["saramin"] == "partial"


def test_idempotent_mirror_prunes_stale_and_keeps_neighbors(tmp_path):
    src = tmp_path / "claude"
    dest = tmp_path / "codex"
    # neighbor that sync must never delete
    (dest / ".system").mkdir(parents=True)
    (dest / ".system" / "keep").write_text("k", encoding="utf-8")
    skill = _make_skill(src, "pdf")
    (skill / "old.txt").write_text("stale", encoding="utf-8")
    sync_skills([src], dest)
    assert (dest / "pdf" / "old.txt").exists()
    # remove the stale file at source, re-sync -> must be pruned in dest
    (skill / "old.txt").unlink()
    sync_skills([src], dest)
    assert not (dest / "pdf" / "old.txt").exists()
    assert (dest / "pdf" / "SKILL.md").exists()
    assert (dest / ".system" / "keep").read_text(encoding="utf-8") == "k"


def test_excludes_junk_dirs(tmp_path):
    src = tmp_path / "claude"
    dest = tmp_path / "codex"
    skill = _make_skill(src, "xlsx")
    (skill / "__pycache__").mkdir()
    (skill / "__pycache__" / "x.pyc").write_text("bin", encoding="utf-8")
    (skill / "node_modules").mkdir()
    (skill / "node_modules" / "dep.js").write_text("j", encoding="utf-8")
    sync_skills([src], dest)
    assert not (dest / "xlsx" / "__pycache__").exists()
    assert not (dest / "xlsx" / "node_modules").exists()
    assert (dest / "xlsx" / "SKILL.md").exists()


def test_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "claude"
    dest = tmp_path / "codex"
    _make_skill(src, "harness")
    res = sync_skills([src], dest, dry_run=True)
    assert "harness" in res["copied"]
    assert not dest.exists() or not (dest / "harness").exists()


def test_missing_source_is_tolerated(tmp_path):
    dest = tmp_path / "codex"
    res = sync_skills([tmp_path / "does-not-exist"], dest)
    assert res["copied"] == []


def test_source_symlink_loop_does_not_crash(tmp_path):
    """V1(Codex) counterexample: 자기참조 심볼릭 링크가 있어도 크래시하면 안 됨.

    한 스킬 폴더의 나쁜 링크 하나 때문에 전체 동기화가 통째로 죽으면 안 된다.
    """
    src = tmp_path / "claude"
    dest = tmp_path / "codex"
    skill = _make_skill(src, "loopskill")
    (skill / "loop").symlink_to(".", target_is_directory=True)
    res = sync_skills([src], dest)  # must not raise
    assert "loopskill" in res["copied"]
    assert (dest / "loopskill" / "SKILL.md").is_file()
    # 링크 자체를 dest 로 옮기지 않는다(옮기면 Codex 가 그 폴더를 훑을 때 같은 무한루프에 빠짐)
    assert not (dest / "loopskill" / "loop").exists()
    assert not (dest / "loopskill" / "loop" / "loop").exists()
