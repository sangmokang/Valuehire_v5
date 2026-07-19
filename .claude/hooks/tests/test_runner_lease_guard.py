#!/usr/bin/env python3
"""runner-lease 가드(R3) 기계 검증 — SOT-30 §4.5 R3 ③(Claude 한정 추가 잠금).

러너 리스 마커(.claude/runner-lease.json, 러너만 발급) 없이 직접 브라우저
타이핑/클릭/JS 도구를 호출하면 차단(exit 2). 읽기 도구·비브라우저 도구·유효 리스는 통과.
판정 본체는 tools/harness/runner_lease.py(공용 모듈) — 가드는 그것을 호출만 한다.
실행: python3 .claude/hooks/tests/test_runner_lease_guard.py   (exit 0 = 전부 통과)
"""
import datetime
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HOOKS = pathlib.Path(__file__).resolve().parent.parent
DISPATCH = HOOKS / "harness-dispatch.py"
REPO_ROOT = HOOKS.parent.parent

results = []


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))


def run(payload, project_dir):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir))
    p = subprocess.run(["python3", str(DISPATCH)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, cwd=str(project_dir))
    return p.returncode, p.stderr


def tool(name, **kw):
    return {"tool_name": name, "tool_input": kw}


def write_lease(root, minutes_ago=0, ttl=120, naive=False, corrupt=False):
    p = pathlib.Path(root) / ".claude" / "runner-lease.json"
    if corrupt:
        p.write_text("{broken")
        return
    now = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago)
    created = now.replace(tzinfo=None).isoformat() if naive else now.isoformat()
    p.write_text(json.dumps({"runner": "test-runner", "scope": "browser-typing",
                             "created_at": created, "ttl_minutes": ttl}))


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp) / "proj"
    (root / ".claude").mkdir(parents=True)
    # 공용 판정 모듈을 가드가 레포에서 찾도록 실제 모듈을 복사 배치
    (root / "tools" / "harness").mkdir(parents=True)
    mod_src = REPO_ROOT / "tools" / "harness" / "runner_lease.py"
    if mod_src.is_file():
        (root / "tools" / "harness" / "runner_lease.py").write_text(mod_src.read_text())

    # --- 리스 없음: 타이핑/클릭/JS 계열 차단 ---
    for name, payload in [
        ("BLOCK-playwright-type", tool("mcp__playwright__browser_type", element="e", ref="r", text="boolean query")),
        ("BLOCK-playwright-click", tool("mcp__playwright__browser_click", element="e", ref="r")),
        ("BLOCK-playwright-fill", tool("mcp__playwright__browser_fill_form", fields=[])),
        ("BLOCK-playwright-evaluate", tool("mcp__playwright__browser_evaluate", function="() => 1")),
        ("BLOCK-chrome-form-input", tool("mcp__claude-in-chrome__form_input", tabId=1)),
        ("BLOCK-chrome-js", tool("mcp__claude-in-chrome__javascript_tool", tabId=1)),
        ("BLOCK-chrome-computer-type", tool("mcp__claude-in-chrome__computer", tabId=1, action="type", text="x")),
        ("BLOCK-chrome-computer-click", tool("mcp__claude-in-chrome__computer", tabId=1, action="left_click")),
    ]:
        rc, err = run(payload, root)
        check(f"{name} -> 2", rc == 2, f"rc={rc} err={err[:120]}")

    rc, err = run(tool("mcp__playwright__browser_type", text="x"), root)
    check("BLOCK stderr mentions 러너/리스", ("러너" in err or "리스" in err or "lease" in err.lower()), err[:150])

    # --- 리스 없음: 읽기·비브라우저 도구 통과 ---
    for name, payload in [
        ("PASS-read-page", tool("mcp__claude-in-chrome__read_page", tabId=1)),
        ("PASS-snapshot", tool("mcp__playwright__browser_snapshot")),
        ("PASS-computer-screenshot", tool("mcp__claude-in-chrome__computer", tabId=1, action="screenshot")),
        ("PASS-bash", tool("Bash", command="ls")),
        ("PASS-read", tool("Read", file_path="/tmp/x")),
    ]:
        rc, err = run(payload, root)
        check(f"{name} -> 0", rc == 0, f"rc={rc} err={err[:120]}")

    # --- 유효 리스: 통과 ---
    write_lease(root)
    rc, err = run(tool("mcp__playwright__browser_type", text="x"), root)
    check("PASS-valid-lease-type -> 0", rc == 0, f"rc={rc} err={err[:120]}")

    # --- 만료 리스: 차단 ---
    write_lease(root, minutes_ago=999, ttl=120)
    rc, _ = run(tool("mcp__playwright__browser_type", text="x"), root)
    check("BLOCK-expired-lease -> 2", rc == 2, f"rc={rc}")

    # --- naive 시각(계약 위반) 리스: 차단(deny-by-default) ---
    write_lease(root, naive=True)
    rc, _ = run(tool("mcp__playwright__browser_type", text="x"), root)
    check("BLOCK-naive-lease -> 2", rc == 2, f"rc={rc}")

    # --- 깨진 리스 파일: 차단(deny-by-default, 가드 크래시 아님) ---
    write_lease(root, corrupt=True)
    rc, _ = run(tool("mcp__playwright__browser_type", text="x"), root)
    check("BLOCK-corrupt-lease -> 2", rc == 2, f"rc={rc}")

    # --- 깨진 리스여도 읽기 도구는 통과 ---
    rc, _ = run(tool("mcp__playwright__browser_snapshot"), root)
    check("PASS-corrupt-lease-read -> 0", rc == 0, f"rc={rc}")

    # --- V1 반례(2026-07-19) 회귀 봉인 ---
    # runner 빈 문자열 리스 = 무효(발급 주체 불명) → 차단
    p = pathlib.Path(root) / ".claude" / "runner-lease.json"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    p.write_text(json.dumps({"runner": "", "scope": "browser-typing", "created_at": now, "ttl_minutes": 120}))
    rc, _ = run(tool("mcp__playwright__browser_type", text="x"), root)
    check("BLOCK-empty-runner-lease -> 2", rc == 2, f"rc={rc}")

    # scope 빈값/비문자열 리스 = 무효 → 차단
    p.write_text(json.dumps({"runner": "r", "scope": "", "created_at": now, "ttl_minutes": 120}))
    rc, _ = run(tool("mcp__playwright__browser_type", text="x"), root)
    check("BLOCK-empty-scope-lease -> 2", rc == 2, f"rc={rc}")

    # 창 파괴 도구(원장 4행 '로그인창 임의 닫기')도 손 조작 — 리스 없으면 차단
    p.unlink()
    for name, payload in [
        ("BLOCK-playwright-close", tool("mcp__playwright__browser_close")),
        ("BLOCK-playwright-tabs-close", tool("mcp__playwright__browser_tabs", action="close")),
        ("BLOCK-chrome-tabs-close", tool("mcp__claude-in-chrome__tabs_close_mcp", tabIds=[1])),
    ]:
        rc, _ = run(payload, root)
        check(f"{name} -> 2", rc == 2, f"rc={rc}")
    # 탭 목록 조회(action=list)는 파괴가 아님 → 통과
    rc, _ = run(tool("mcp__playwright__browser_tabs", action="list"), root)
    check("PASS-playwright-tabs-list -> 0", rc == 0, f"rc={rc}")

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} PASS")
sys.exit(1 if failed else 0)
