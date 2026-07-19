#!/usr/bin/env python3
"""stop-evidence-gate.py 회귀 테스트 — V1 적대검증(F1~F7, 2026-07-18) 매트릭스 반영판.

차단 = 내부 sentinel exit 99 (settings 래퍼만 99→protocol exit 2로 승격).
최악의 실패 모드는 전 세션 잠금(과잉 가드)이므로 통과 케이스를 넓게 검증한다.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import datetime
import pathlib

HOOKS_DIR = pathlib.Path(__file__).resolve().parent.parent
GATE = HOOKS_DIR / "stop-evidence-gate.py"
BLOCK = 99
# settings.json 의 Stop 래퍼와 동일 계약: 99만 2로 승격, 그 외 전부 0.
WRAPPER = (
    'f="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}'
    '/.claude/hooks/stop-evidence-gate.py"; '
    'if [ -f "$f" ]; then python3 "$f"; rc=$?; [ "$rc" -eq 99 ] && exit 2; fi; exit 0'
)

results = []


def run(stdin_text, repo_root, extra_env=None, use_wrapper=False):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo_root))
    if extra_env:
        env.update(extra_env)
    cmd = ["sh", "-c", WRAPPER] if use_wrapper else [sys.executable, str(GATE)]
    p = subprocess.run(cmd, input=stdin_text.encode(), capture_output=True,
                       env=env, cwd=str(repo_root), timeout=30)
    return p.returncode, p.stderr.decode(errors="replace")


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))


def make_repo(base, name="repo"):
    repo = pathlib.Path(base) / name
    (repo / ".claude").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


GIT_ID = dict(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
              GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def make_worktree_dir(base, name, dirty):
    wt = pathlib.Path(base) / name
    wt.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(wt)], check=True)
    subprocess.run(["git", "-C", str(wt), "commit", "--allow-empty", "-q", "-m", "base"],
                   check=True, env=dict(os.environ, **GIT_ID))
    if dirty:
        (wt / "dirty.txt").write_text("uncommitted")
    return wt


def write_marker(repo, wt, created_at=None, session_id=None, worktree_override=None):
    data = {
        "slug": "demo-task",
        "worktree": worktree_override if worktree_override is not None else str(wt),
        "created_at": created_at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if session_id:
        data["session_id"] = session_id
    (repo / ".claude" / "strict-active.json").write_text(json.dumps(data))


PAYLOAD = json.dumps({"hook_event_name": "Stop", "stop_hook_active": False, "session_id": "sess-A"})
PAYLOAD_ACTIVE = json.dumps({"hook_event_name": "Stop", "stop_hook_active": True, "session_id": "sess-A"})

with tempfile.TemporaryDirectory() as tmp:
    repo = make_repo(tmp)
    wt_dirty = make_worktree_dir(tmp, "wt-dirty", dirty=True)
    wt_clean = make_worktree_dir(tmp, "wt-clean", dirty=False)

    # ── 기본선 ──
    rc, err = run(PAYLOAD, repo)
    check("no-marker allows (0)", rc == 0, f"rc={rc}")

    write_marker(repo, wt_dirty)
    rc, err = run(PAYLOAD, repo)
    check("dirty blocks (99)", rc == BLOCK, f"rc={rc}")
    check("reason names slug + release path", "demo-task" in err and "strict-active.json" in err, err[:200])

    rc, err = run(PAYLOAD_ACTIVE, repo)
    check("stop_hook_active allows (0)", rc == 0, f"rc={rc}")

    write_marker(repo, wt_clean)
    rc, err = run(PAYLOAD, repo)
    check("clean allows (0)", rc == 0, f"rc={rc}")

    # ── F3: 시간 경계 ──
    now = datetime.datetime.now(datetime.timezone.utc)
    write_marker(repo, wt_dirty, created_at=(now - datetime.timedelta(hours=25)).isoformat())
    rc, _ = run(PAYLOAD, repo)
    check("F3 stale 25h allows (0)", rc == 0, f"rc={rc}")

    write_marker(repo, wt_dirty, created_at=(now + datetime.timedelta(hours=2)).isoformat())
    rc, _ = run(PAYLOAD, repo)
    check("F3 far-future allows (0)", rc == 0, f"rc={rc}")

    write_marker(repo, wt_dirty, created_at=now.replace(tzinfo=None).isoformat())
    rc, _ = run(PAYLOAD, repo)
    check("F3 naive timestamp allows (0)", rc == 0, f"rc={rc}")

    write_marker(repo, wt_dirty, created_at=(now - datetime.timedelta(hours=23)).isoformat())
    rc, _ = run(PAYLOAD, repo)
    check("F3 23h-old still blocks (99)", rc == BLOCK, f"rc={rc}")

    # ── F4: 경로 스키마 ──
    for label, override in [("relative", "."), ("empty", ""), ("parent-relative", "../wt-dirty")]:
        write_marker(repo, wt_dirty, worktree_override=override)
        rc, _ = run(PAYLOAD, repo)
        check(f"F4 {label} worktree allows (0)", rc == 0, f"rc={rc}")

    write_marker(repo, wt_dirty, worktree_override=str(wt_dirty / "dirty.txt"))
    rc, _ = run(PAYLOAD, repo)
    check("F4 non-dir worktree allows (0)", rc == 0, f"rc={rc}")

    sub = wt_dirty / "subdir"; sub.mkdir()
    write_marker(repo, wt_dirty, worktree_override=str(sub))
    rc, _ = run(PAYLOAD, repo)
    check("F4 non-toplevel dir allows (0)", rc == 0, f"rc={rc}")

    # ── F2: GIT_* 환경 역전 무력화 ──
    write_marker(repo, wt_dirty)
    rc, _ = run(PAYLOAD, repo, extra_env={"GIT_DIR": str(wt_clean / ".git"), "GIT_WORK_TREE": str(wt_clean)})
    check("F2 GIT_DIR->clean still blocks dirty (99)", rc == BLOCK, f"rc={rc}")

    write_marker(repo, wt_clean)
    rc, _ = run(PAYLOAD, repo, extra_env={"GIT_DIR": str(wt_dirty / ".git"), "GIT_WORK_TREE": str(wt_dirty)})
    check("F2 GIT_DIR->dirty still allows clean (0)", rc == 0, f"rc={rc}")

    # ── F5: 세션 구속 ──
    write_marker(repo, wt_dirty, session_id="sess-B")
    rc, _ = run(PAYLOAD, repo)
    check("F5 other-session marker allows (0)", rc == 0, f"rc={rc}")
    write_marker(repo, wt_dirty, session_id="sess-A")
    rc, _ = run(PAYLOAD, repo)
    check("F5 same-session marker blocks (99)", rc == BLOCK, f"rc={rc}")

    # ── fail-open 잡탕 ──
    (repo / ".claude" / "strict-active.json").write_text("{broken json")
    rc, _ = run(PAYLOAD, repo)
    check("broken marker allows (0)", rc == 0, f"rc={rc}")
    write_marker(repo, pathlib.Path(tmp) / "gone")
    rc, _ = run(PAYLOAD, repo)
    check("missing worktree allows (0)", rc == 0, f"rc={rc}")
    rc, _ = run("not-json", repo)
    check("broken stdin allows (0)", rc == 0, f"rc={rc}")

    # ── 래퍼 계약(F6): 99만 protocol 2로, 크래시·부재는 0 ──
    fake = pathlib.Path(tmp) / "wrap-dirty"
    (fake / ".claude" / "hooks").mkdir(parents=True)
    import shutil
    shutil.copy(GATE, fake / ".claude" / "hooks" / "stop-evidence-gate.py")
    subprocess.run(["git", "init", "-q", str(fake)], check=True)
    write_marker(fake, wt_dirty)
    rc, err = run(PAYLOAD, fake, use_wrapper=True)
    check("F6 wrapper dirty -> protocol 2", rc == 2, f"rc={rc}")
    check("F6 wrapper passes stderr reason", "demo-task" in err, err[:150])

    write_marker(fake, wt_clean)
    rc, _ = run(PAYLOAD, fake, use_wrapper=True)
    check("F6 wrapper clean -> 0", rc == 0, f"rc={rc}")

    hook_copy = fake / ".claude" / "hooks" / "stop-evidence-gate.py"
    hook_copy.chmod(0)
    rc, err = run(PAYLOAD, fake, use_wrapper=True)
    check("F6 wrapper unreadable hook -> 0 (crash != block)", rc == 0, f"rc={rc} err={err[:100]}")
    hook_copy.chmod(stat.S_IRWXU)

    empty_root = pathlib.Path(tmp) / "no-hook"
    empty_root.mkdir()
    rc, _ = run(PAYLOAD, empty_root, use_wrapper=True)
    check("F6 wrapper missing hook -> 0", rc == 0, f"rc={rc}")

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} PASS")
sys.exit(1 if failed else 0)
