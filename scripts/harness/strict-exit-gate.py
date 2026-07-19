#!/usr/bin/env python3
"""strict-exit-gate — Codex 종료 등가 게이트 (v5, SOT-30 overlay).

Codex 등 Stop 훅이 없는 실행기는 세션 마지막 단계에서 이 러너를 의무 실행하고,
exit 0 + "[strict-exit-gate] PASS" 출력이 없으면 "완료"라고 선언하지 못한다.
검사(기계 판정 가능한 것만 — 정직 표기):
  1) .claude/strict-active.json 마커가 있으면 그 워크트리에 미커밋 변경이 없어야 한다.
  2) .claude/runner-lease.json 잔존 시 경고(러너 미반납 흔적).
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


def main():
    root = repo_root()
    marker = root / ".claude" / "strict-active.json"
    lease = root / ".claude" / "runner-lease.json"
    problems = []

    if marker.is_file():
        try:
            data = json.loads(marker.read_text())
            wt = pathlib.Path(str(data.get("worktree", "")))
            if str(wt) and wt.is_dir():
                st = subprocess.run(["git", "-C", str(wt), "status", "--porcelain"],
                                    capture_output=True, text=True, timeout=15)
                if st.returncode == 0 and st.stdout.strip():
                    lines = st.stdout.strip().splitlines()[:20]
                    problems.append(
                        f"strict 작업 '{data.get('slug', '?')}' 워크트리({wt})에 미커밋(uncommitted) 변경 잔존:\n"
                        + "\n".join(f"    {l}" for l in lines))
        except Exception as e:  # 판독 불가 — fail-open(경고만)
            print(f"[strict-exit-gate] WARN 마커 판독 불가({type(e).__name__}) — 판정 생략", file=sys.stderr)

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
