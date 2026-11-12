#!/usr/bin/env python3
"""strict-exit-gate — Codex 종료 등가 게이트 (v5, SOT-30 overlay).

Codex 등 Stop 훅이 없는 실행기는 세션 마지막 단계에서 이 러너를 의무 실행하고,
exit 0 + "[strict-exit-gate] PASS" 출력이 없으면 "완료"라고 선언하지 못한다.
검사(기계 판정 가능한 것만 — 정직 표기):
  1) .claude/strict-active.json 마커가 있으면 그 워크트리에 미커밋 변경이 없어야 한다.
  2) .claude/runner-lease.json 잔존 시 경고(러너 미반납 흔적).
  3) fail-closed(2026-11-12): 마커 판독 불가·스키마 위반·워크트리 없음·다른 레포·git rc≠0·타임아웃은
     전부 FAIL. "검사 못 함"을 "통과"로 세지 않는다(goal strict-unify 입력영역표).
"불필요 질문 0건" 같은 의미 검증은 기계가 못 한다 — V1 적대검증 체크리스트 몫.
v4 tools/harness/strict-exit-gate.mjs 와 같은 계약의 v5(python) 구현.
"""
import datetime
import json
import os
import pathlib
import subprocess
import sys


def repo_root():
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return pathlib.Path(env)
    p = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       capture_output=True, text=True)
    if p.returncode == 0 and p.stdout.strip():
        return pathlib.Path(p.stdout.strip()).parent
    return pathlib.Path.cwd()


def _timeout():
    try:
        return float(os.environ.get("STRICT_EXIT_GATE_TIMEOUT", "15"))
    except ValueError:
        return 15.0


def _git(args, timeout):
    """git 실행. rc≠0·타임아웃은 호출자가 FAIL로 처리한다(fail-closed)."""
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=timeout)


def check_marker(root, marker):
    """마커 판독 → 문제 목록. 판독·검사 불가는 전부 문제로 본다(fail-closed, goal 입력영역표)."""
    try:
        data = json.loads(marker.read_text())
    except (OSError, ValueError) as e:
        return [f"마커 판독 불가({type(e).__name__}) — 마커를 고치거나 사유와 함께 해제하세요: {marker}"]
    if not isinstance(data, dict):
        return ["마커 최상위가 객체가 아님"]
    slug, wt_s = data.get("slug"), data.get("worktree")
    if not isinstance(slug, str) or not slug.strip():
        return ["마커 slug 누락/빈값/비문자열"]
    if not isinstance(wt_s, str) or not wt_s.strip():
        return [f"strict 작업 '{slug}' 마커 worktree 누락/빈값/비문자열"]
    wt = pathlib.Path(wt_s)
    if not wt.is_dir():
        return [f"strict 작업 '{slug}' 워크트리 경로 없음({wt}) — 정리했다면 사유와 함께 마커를 해제하세요"]
    t = _timeout()
    try:
        common = _git(["-C", str(wt), "rev-parse", "--path-format=absolute", "--git-common-dir"], t)
        if common.returncode != 0 or not common.stdout.strip():
            return [f"strict 작업 '{slug}' 워크트리({wt}) git 판독 실패 rc={common.returncode}"]
        wt_repo = pathlib.Path(common.stdout.strip()).resolve().parent
        if wt_repo != pathlib.Path(root).resolve():
            return [f"strict 작업 '{slug}' 워크트리({wt})가 이 레포({root})가 아님({wt_repo})"]
        st = _git(["-C", str(wt), "status", "--porcelain"], t)
    except subprocess.TimeoutExpired:
        return [f"strict 작업 '{slug}' 워크트리({wt}) git 타임아웃({t}s)"]
    if st.returncode != 0:
        return [f"strict 작업 '{slug}' git status 실패 rc={st.returncode}"]
    if st.stdout.strip():
        lines = st.stdout.strip().splitlines()[:20]
        return [f"strict 작업 '{slug}' 워크트리({wt})에 미커밋(uncommitted) 변경 잔존:\n"
                + "\n".join(f"    {l}" for l in lines)]
    return []


def main():
    root = repo_root()
    marker = root / ".claude" / "strict-active.json"
    lease = root / ".claude" / "runner-lease.json"
    problems = []

    if marker.exists():
        try:
            problems += check_marker(root, marker)
        except Exception as e:  # 표 밖 예외 — catch-all 행: FAIL(fail-closed)
            problems.append(f"예상하지 못한 판독 오류({type(e).__name__}: {e})")

    if lease.is_file():
        print("[strict-exit-gate] WARN runner-lease.json 잔존 — 러너가 release를 부르지 않았습니다.", file=sys.stderr)

    if problems:
        print(f"[strict-exit-gate] FAIL — {len(problems)}건. 커밋+검증(게이트 4)을 마치거나, "
              "중단이면 사유 보고 후 마커를 해제하세요.", file=sys.stderr)
        for p in problems:
            print(f"- {p}", file=sys.stderr)
        return 1

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"[strict-exit-gate] PASS — 미커밋 잔존 0 · 마커 상태 일치 ({now})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
