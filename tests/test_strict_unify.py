"""strict 단일화 + GitOps 배포 위생 — 행위 테스트.

goal: docs/engineering/strict-unify-goal-2026-11-12.md
- exit gate fail-closed (입력영역표의 FAIL 행 전부)
- 양 엔진 positive discovery + core 패리티 + st 별칭 부재
- sync-strict-skill.sh: --check 드리프트 감지(쓰기 0) / --install 승인 리비전 외 거부 / 설치 행위
"""
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts/harness/strict-exit-gate.py"
SYNC = ROOT / "tools/sync-strict-skill.sh"
CLAUDE_ENTRY = ROOT / "skills/strict/SKILL.md"
CODEX_ENTRY = ROOT / ".codex/skills/strict/SKILL.md"
CORE_RE = re.compile(r"<!-- strict-core:begin -->\n(.*?)<!-- strict-core:end -->", re.S)


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / "README").write_text("x")
    _git(path, "add", "README")
    _git(path, "commit", "-qm", "init")
    return path


def _worktree(root, name="wt"):
    """마커가 가리킬 실제 워크트리(메인 체크아웃과 분리 — 실운영 형태 그대로)."""
    wt = root.parent / name
    _git(root, "worktree", "add", "-q", "-b", f"task/{name}", str(wt))
    return wt


def _run_gate(root, marker=None, env_extra=None):
    (root / ".claude").mkdir(exist_ok=True)
    if marker is not None:
        (root / ".claude/strict-active.json").write_text(marker)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(GATE)], capture_output=True, text=True,
                          env=env, cwd=root, timeout=60)


# ---------------- exit gate: PASS 행 ----------------

def test_gate_pass_without_marker(tmp_path):
    root = _init_repo(tmp_path / "repo")
    r = _run_gate(root)
    assert r.returncode == 0 and "PASS" in r.stdout


def test_gate_pass_clean_same_repo_worktree(tmp_path):
    root = _init_repo(tmp_path / "repo")
    wt = _worktree(root)
    r = _run_gate(root, json.dumps({"slug": "s", "worktree": str(wt)}))
    assert r.returncode == 0, r.stderr
    assert "PASS" in r.stdout


def test_gate_fail_dirty_worktree(tmp_path):
    root = _init_repo(tmp_path / "repo")
    wt = _worktree(root)
    (wt / "dirty.txt").write_text("d")
    r = _run_gate(root, json.dumps({"slug": "s", "worktree": str(wt)}))
    assert r.returncode != 0 and "PASS" not in r.stdout


# ---------------- exit gate: fail-closed 행 ----------------

def test_gate_fail_on_broken_marker_json(tmp_path):
    root = _init_repo(tmp_path / "repo")
    r = _run_gate(root, "{not json")
    assert r.returncode != 0 and "PASS" not in r.stdout


@pytest.mark.parametrize("marker", [
    json.dumps(["list"]),
    json.dumps({"slug": "s"}),
    json.dumps({"worktree": "/tmp"}),
    json.dumps({"slug": "", "worktree": "/tmp"}),
    json.dumps({"slug": "s", "worktree": 3}),
])
def test_gate_fail_on_invalid_marker_schema(tmp_path, marker):
    root = _init_repo(tmp_path / "repo")
    r = _run_gate(root, marker)
    assert r.returncode != 0 and "PASS" not in r.stdout


def test_gate_fail_on_missing_worktree_path(tmp_path):
    root = _init_repo(tmp_path / "repo")
    r = _run_gate(root, json.dumps({"slug": "s", "worktree": str(tmp_path / "nope")}))
    assert r.returncode != 0 and "PASS" not in r.stdout


def test_gate_fail_on_git_nonzero(tmp_path):
    root = _init_repo(tmp_path / "repo")
    not_git = tmp_path / "plain"
    not_git.mkdir()
    r = _run_gate(root, json.dumps({"slug": "s", "worktree": str(not_git)}))
    assert r.returncode != 0 and "PASS" not in r.stdout


def test_gate_fail_on_foreign_repo_worktree(tmp_path):
    root = _init_repo(tmp_path / "repo")
    other = _init_repo(tmp_path / "other")
    r = _run_gate(root, json.dumps({"slug": "s", "worktree": str(other)}))
    assert r.returncode != 0 and "PASS" not in r.stdout


def test_gate_fail_on_git_timeout(tmp_path):
    root = _init_repo(tmp_path / "repo")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    fake = fakebin / "git"
    fake.write_text("#!/bin/sh\nsleep 5\n")
    fake.chmod(0o755)
    wt = _worktree(root)
    r = _run_gate(root, json.dumps({"slug": "s", "worktree": str(wt)}),
                  {"PATH": f"{fakebin}:{os.environ['PATH']}", "STRICT_EXIT_GATE_TIMEOUT": "0.5"})
    assert r.returncode != 0 and "PASS" not in r.stdout


# ---------------- 진입점: positive discovery + 패리티 + 별칭 부재 ----------------

def _front(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path} frontmatter 없음"
    return m.group(1), text


@pytest.mark.parametrize("entry", [CLAUDE_ENTRY, CODEX_ENTRY])
def test_strict_entry_discoverable_both_engines(entry):
    assert entry.is_file(), f"strict 진입점 없음: {entry}"
    front, _ = _front(entry)
    assert re.search(r"^name:\s*strict\s*$", front, re.M), "name: strict 아님"
    assert "st 별칭은 폐지" in front, "description에 st 폐지·통합 명시 없음"


def test_codex_agent_yaml_points_to_strict():
    y = ROOT / ".codex/skills/strict/agents/openai.yaml"
    assert y.is_file()
    body = y.read_text(encoding="utf-8")
    assert "$strict" in body and "$st " not in body


def test_core_block_parity_between_engines():
    cores = []
    for entry in (CLAUDE_ENTRY, CODEX_ENTRY):
        m = CORE_RE.search(entry.read_text(encoding="utf-8"))
        assert m, f"{entry} core 블록 없음"
        cores.append(hashlib.sha256(m.group(1).encode()).hexdigest())
    assert cores[0] == cores[1], "엔진 간 core 블록 해시 불일치(드리프트)"


def test_core_keeps_strongest_controls_and_no_false_gate_claim():
    core = CORE_RE.search(CLAUDE_ENTRY.read_text(encoding="utf-8")).group(1)
    for marker in ["입력 영역 표", "예외 케이스 표", "R1", "R8", "read-back", "배선 증명",
                   "G→V1→V2", "planned", "Secret", "드리프트"]:
        assert marker in core, f"core에서 통제 누락: {marker}"
    # 옛 st 사본의 거짓 주장: strict:gate 가 goal/verdict/signoff 를 막는다
    assert not re.search(r"strict:gate.{0,40}(goal 문서|verdict\.json).{0,80}(막는|검사라고 본다)", core)


def test_st_alias_copies_removed():
    assert not (ROOT / "skills/st").exists(), "skills/st 잔존"
    assert not (ROOT / ".codex/skills/st").exists(), ".codex/skills/st 잔존"


# ---------------- sync-strict-skill.sh ----------------

def _homes(tmp_path):
    return {"CLAUDE_HOME": str(tmp_path / "claude"), "CODEX_HOME": str(tmp_path / "codex")}


def _run_sync(cwd, args, env_extra):
    env = dict(os.environ, **env_extra)
    return subprocess.run(["bash", str(cwd / "tools/sync-strict-skill.sh"), *args],
                          capture_output=True, text=True, env=env, cwd=cwd, timeout=60)


def test_sync_usage_on_bad_args(tmp_path):
    r = _run_sync(ROOT, ["--nope"], _homes(tmp_path))
    assert r.returncode == 2


def test_sync_check_reports_missing_and_writes_nothing(tmp_path):
    homes = _homes(tmp_path)
    r = _run_sync(ROOT, ["--check"], homes)
    assert r.returncode == 1
    assert "MISSING" in r.stdout
    assert not (tmp_path / "claude").exists() and not (tmp_path / "codex").exists()


def _mini_repo(tmp_path, merged=True):
    """정본 파일만 담은 임시 레포. merged=True 면 origin/main == HEAD (병합 상태 모사)."""
    repo = tmp_path / "mini"
    for rel in ["tools/sync-strict-skill.sh", "skills/strict", ".codex/skills/strict"]:
        src = ROOT / rel
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    _init_repo(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "strict")
    if merged:
        _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def test_sync_install_refused_off_origin_main(tmp_path):
    repo = _mini_repo(tmp_path, merged=False)
    homes = _homes(tmp_path)
    r = _run_sync(repo, ["--install"], homes)
    assert r.returncode == 3
    assert not (tmp_path / "claude").exists()


def test_sync_install_refused_when_canonical_dirty(tmp_path):
    repo = _mini_repo(tmp_path, merged=True)
    (repo / "skills/strict/SKILL.md").write_text("tampered")
    r = _run_sync(repo, ["--install"], _homes(tmp_path))
    assert r.returncode == 3
    assert not (tmp_path / "claude").exists()


def test_sync_install_then_check_clean_with_record_and_backup(tmp_path):
    repo = _mini_repo(tmp_path, merged=True)
    homes = _homes(tmp_path)
    old = tmp_path / "claude/skills/strict"
    old.mkdir(parents=True)
    (old / "SKILL.md").write_text("old copy")
    legacy = tmp_path / "codex/skills/st"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text("legacy")

    r = _run_sync(repo, ["--install", "--remove-legacy"], homes)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "claude/skills/strict/SKILL.md").read_bytes() == \
        (repo / "skills/strict/SKILL.md").read_bytes()
    assert (tmp_path / "codex/skills/strict/SKILL.md").read_bytes() == \
        (repo / ".codex/skills/strict/SKILL.md").read_bytes()
    rec = json.loads((tmp_path / "claude/skills/strict/.strict-install.json").read_text())
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    assert rec["commit"] == head
    # 백업은 skills/ 밖(.strict-backups/) — 스킬 로더가 백업을 중복 스킬로 읽지 않게
    assert not list((tmp_path / "claude/skills").glob(".strict-backup*"))
    backups = list((tmp_path / "claude/.strict-backups").glob("*/strict"))
    assert backups and (backups[0] / "SKILL.md").read_text() == "old copy"
    assert not legacy.exists(), "legacy st 가 이동되지 않음"
    assert list((tmp_path / "codex/.strict-backups").glob("*/st/SKILL.md")), "legacy 백업 없음(삭제 금지)"

    c = _run_sync(repo, ["--check"], homes)
    assert c.returncode == 0, c.stdout
    assert "DRIFT" not in c.stdout and "MISSING" not in c.stdout


def _run_gate_from(project_dir, env_extra=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir))
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(GATE)], capture_output=True, text=True,
                          env=env, cwd=project_dir, timeout=60)


def test_gate_finds_main_checkout_marker_when_project_dir_is_worktree(tmp_path):
    """V1#1: task.sh 는 마커를 메인 체크아웃에 쓴다 — CLAUDE_PROJECT_DIR 가 워크트리여도 그 마커를 찾아야 한다."""
    root = _init_repo(tmp_path / "repo")
    wt = _worktree(root, "wt")
    (root / ".claude").mkdir()
    (root / ".claude/strict-active.json").write_text(json.dumps({"slug": "s", "worktree": str(wt)}))
    (wt / "dirty.txt").write_text("d")
    r = _run_gate_from(wt)
    assert r.returncode != 0 and "PASS" not in r.stdout
    (wt / "dirty.txt").unlink()
    r = _run_gate_from(wt)
    assert r.returncode == 0, r.stderr


def test_gate_fail_on_dangling_marker_symlink(tmp_path):
    """V1#5: 깨진 심링크 마커는 '마커 없음'이 아니라 판독 불가(FAIL)."""
    root = _init_repo(tmp_path / "repo")
    (root / ".claude").mkdir()
    (root / ".claude/strict-active.json").symlink_to(tmp_path / "gone.json")
    r = _run_gate_from(root)
    assert r.returncode != 0 and "PASS" not in r.stdout


def test_gate_fail_when_marker_is_directory(tmp_path):
    root = _init_repo(tmp_path / "repo")
    (root / ".claude/strict-active.json").mkdir(parents=True)
    r = _run_gate_from(root)
    assert r.returncode != 0 and "PASS" not in r.stdout


def test_sync_check_fails_when_hash_tool_fails(tmp_path):
    """V1#4: 해시 도구 실패를 빈 해시 == 빈 해시 'OK'로 세면 안 된다."""
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    (fakebin / "shasum").write_text("#!/bin/sh\nexit 127\n")
    (fakebin / "shasum").chmod(0o755)
    homes = _homes(tmp_path)
    for h in ("claude", "codex"):
        (tmp_path / h / "skills/strict").mkdir(parents=True)
        (tmp_path / h / "skills/strict/SKILL.md").write_text("x")
    r = _run_sync(ROOT, ["--check"], dict(homes, PATH=f"{fakebin}:{os.environ['PATH']}"))
    assert r.returncode not in (0,), r.stdout
    assert "드리프트 0" not in r.stdout and " OK " not in r.stdout


def test_sync_install_uses_commit_content_only(tmp_path):
    """V1#2: ignored·숨은 untracked 파일이 설치본에 섞이면 안 된다(커밋 객체 기준 설치)."""
    repo = _mini_repo(tmp_path, merged=True)
    (repo / ".gitignore").write_text("skills/strict/.env\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / "skills/strict/.env").write_text("SECRET=1")
    _git(repo, "config", "status.showUntrackedFiles", "no")
    (repo / "skills/strict/untracked.md").write_text("u")
    r = _run_sync(repo, ["--install"], _homes(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    dest = tmp_path / "claude/skills/strict"
    assert not (dest / ".env").exists(), "ignored 파일이 설치됨"
    assert not (dest / "untracked.md").exists(), "untracked 파일이 설치됨"


def test_sync_install_second_target_failure_changes_nothing(tmp_path):
    """V1#3: 두 번째 대상 준비 실패 시 첫 번째 대상도 바뀌지 않아야 한다(엔진 간 리비전 불일치 금지)."""
    repo = _mini_repo(tmp_path, merged=True)
    homes = _homes(tmp_path)
    old = tmp_path / "claude/skills/strict"
    old.mkdir(parents=True)
    (old / "SKILL.md").write_text("old copy")
    (tmp_path / "codex").mkdir()
    (tmp_path / "codex/skills").write_text("not a dir")  # codex 대상 준비 실패 유도
    r = _run_sync(repo, ["--install"], homes)
    assert r.returncode != 0
    assert (old / "SKILL.md").read_text() == "old copy", "첫 대상이 부분 설치됨"
    assert not (tmp_path / "claude/.strict-backups").exists()


def test_sync_install_refused_when_locked(tmp_path):
    repo = _mini_repo(tmp_path, merged=True)
    homes = _homes(tmp_path)
    (tmp_path / "claude/.strict-sync.lock").mkdir(parents=True)
    r = _run_sync(repo, ["--install"], homes)
    assert r.returncode != 0
    assert not (tmp_path / "claude/skills").exists()


def test_sync_backup_ids_unique_on_rapid_reinstall(tmp_path):
    repo = _mini_repo(tmp_path, merged=True)
    homes = _homes(tmp_path)
    for _ in range(3):
        r = _run_sync(repo, ["--install"], homes)
        assert r.returncode == 0, r.stdout + r.stderr
    backups = list((tmp_path / "claude/.strict-backups").glob("*/strict"))
    assert len(backups) == 2, backups  # 두 번째·세 번째 설치가 각각 이전본을 백업(이름 충돌 없음)


def test_gate_pass_when_project_dir_is_another_worktree_of_same_repo(tmp_path):
    """CLAUDE_PROJECT_DIR 가 같은 레포의 다른 워크트리여도 동일 레포로 판정(오탐 FAIL 금지)."""
    root = _init_repo(tmp_path / "repo")
    proj = _worktree(root, "proj")
    wt = _worktree(root, "wt")
    (proj / ".gitignore").write_text(".claude/\n")
    _git(proj, "add", ".gitignore")
    _git(proj, "commit", "-qm", "ignore")
    r = _run_gate(proj, json.dumps({"slug": "s", "worktree": str(wt)}))
    assert r.returncode == 0, r.stderr
