#!/usr/bin/env python3
"""stop-evidence-gate.py R2(질문 금지) 확장 회귀 테스트 — SOT-30 §4.5 R2.

strict 마커가 유효한 세션에서, 마지막 어시스턴트 메시지가 스펙 내 확인 질문
("~할까요?")으로 끝나면 Stop 게이트가 1턴 저지(sentinel 99)해야 한다.
허용 질문(2FA·캡차·본인확인·파괴적/비가역)과 무마커·오류는 전부 통과(fail-open).
실행: python3 .claude/hooks/tests/test_stop_gate_question.py   (exit 0 = 전부 통과)
"""
import datetime
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HOOKS_DIR = pathlib.Path(__file__).resolve().parent.parent
GATE = HOOKS_DIR / "stop-evidence-gate.py"
BLOCK = 99

results = []


def check(name, cond, detail=""):
    results.append((name, cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))


def make_repo(base, name):
    repo = pathlib.Path(base) / name
    (repo / ".claude").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def make_wt(base, name, dirty=False):
    wt = pathlib.Path(base) / name
    wt.mkdir()
    subprocess.run(["git", "init", "-q", str(wt)], check=True)
    if dirty:
        (wt / "x.txt").write_text("dirty\n")
    return wt


def write_marker(repo, wt):
    marker = {
        "slug": "demo-question-task",
        "worktree": str(wt),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    (repo / ".claude" / "strict-active.json").write_text(json.dumps(marker))


def write_transcript(base, name, last_assistant_text):
    path = pathlib.Path(base) / name
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": "작업 지시"}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "중간 진행 보고입니다."}]}}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": last_assistant_text}]}}),
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def run(repo, transcript_path=None, stop_hook_active=False):
    payload = {"cwd": str(repo), "session_id": "sess-q", "stop_hook_active": stop_hook_active}
    if transcript_path is not None:
        payload["transcript_path"] = str(transcript_path)
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(repo))
    p = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload).encode(),
                       capture_output=True, env=env, cwd=str(repo), timeout=30)
    return p.returncode, p.stderr.decode(errors="replace")


with tempfile.TemporaryDirectory() as tmp:
    repo = make_repo(tmp, "repo")
    wt_clean = make_wt(tmp, "wt-clean")

    # Q1 스펙 내 확인 질문 + 유효 마커 + clean 워크트리 → 저지(99)
    write_marker(repo, wt_clean)
    t = write_transcript(tmp, "t1.jsonl", "테스트를 추가했습니다. 이제 커밋을 진행할까요?")
    rc, err = run(repo, t)
    check("Q1 spec-internal question -> 99", rc == BLOCK, f"rc={rc} err={err[:150]}")
    check("Q1 stderr mentions R2/질문", ("질문" in err or "R2" in err), err[:150])

    # Q2 stop_hook_active 재시도 턴 → 통과(1턴 저지 계약)
    rc, _ = run(repo, t, stop_hook_active=True)
    check("Q2 stop_hook_active -> 0", rc == 0, f"rc={rc}")

    # Q3 평서문 종료 → 통과
    t3 = write_transcript(tmp, "t3.jsonl", "검증 완료했습니다. exit 0 출력 그대로 첨부합니다.")
    rc, _ = run(repo, t3)
    check("Q3 statement -> 0", rc == 0, f"rc={rc}")

    # Q4 허용 질문(캡차/2FA/본인확인) → 통과
    t4 = write_transcript(tmp, "t4.jsonl", "캡차가 떴습니다. 직접 풀어주시겠어요?")
    rc, _ = run(repo, t4)
    check("Q4 captcha question allowed -> 0", rc == 0, f"rc={rc}")

    # Q5 파괴적·비가역 확인 질문 → 통과
    t5 = write_transcript(tmp, "t5.jsonl", "main 브랜치를 삭제하는 비가역 작업입니다. 정말 삭제할까요?")
    rc, _ = run(repo, t5)
    check("Q5 destructive question allowed -> 0", rc == 0, f"rc={rc}")

    # Q6 마커 없음 + 질문 → 통과 (strict 세션 아님)
    (repo / ".claude" / "strict-active.json").unlink()
    rc, _ = run(repo, t)
    check("Q6 no marker -> 0", rc == 0, f"rc={rc}")

    # Q7 transcript 없음/깨짐 → fail-open
    write_marker(repo, wt_clean)
    rc, _ = run(repo, pathlib.Path(tmp) / "missing.jsonl")
    check("Q7 missing transcript -> 0", rc == 0, f"rc={rc}")
    bad = pathlib.Path(tmp) / "bad.jsonl"
    bad.write_text("{not-json\n")
    rc, _ = run(repo, bad)
    check("Q7b corrupt transcript -> 0", rc == 0, f"rc={rc}")

    # Q8 transcript_path 필드 자체가 없음 → fail-open
    rc, _ = run(repo, None)
    check("Q8 no transcript field -> 0", rc == 0, f"rc={rc}")

    # --- V1 반례(2026-07-19) 회귀 봉인 ---
    # Q9 2단계 인증/MFA 동의어 허용 질문 → 통과 (V1 FN_allowed_synonym)
    rc, _ = run(repo, write_transcript(tmp, "t9.jsonl", "2단계 인증 화면입니다. 직접 승인해 주시겠어요?"))
    check("Q9 2FA synonym allowed -> 0", rc == 0, f"rc={rc}")
    rc, _ = run(repo, write_transcript(tmp, "t9b.jsonl", "MFA 알림을 승인해 주시겠어요?"))
    check("Q9b MFA allowed -> 0", rc == 0, f"rc={rc}")

    # Q10 비복구/덮어쓰기(파괴적 동의어) 확인 질문 → 통과
    rc, _ = run(repo, write_transcript(tmp, "t10.jsonl", "운영 DB를 덮어쓰는 비복구 작업입니다. 진행할까요?"))
    check("Q10 irreversible synonym allowed -> 0", rc == 0, f"rc={rc}")

    # Q11 허용 키워드의 부정문 우회 → 저지 (V1 FN_allow_keyword_negated)
    rc, _ = run(repo, write_transcript(tmp, "t11.jsonl", "캡차는 없습니다. 이제 커밋을 진행할까요?"))
    check("Q11 negated captcha still blocked -> 99", rc == BLOCK, f"rc={rc}")
    rc, _ = run(repo, write_transcript(tmp, "t11b.jsonl", "파괴적 변경은 아닙니다. 저장할까요?"))
    check("Q11b negated destructive still blocked -> 99", rc == BLOCK, f"rc={rc}")

    # Q12 수사적 질문("왜 …까요?")은 확인 질문이 아님 → 통과 (V1 FP_rhetorical)
    rc, _ = run(repo, write_transcript(tmp, "t12.jsonl", "왜 이 설계가 괜찮을까요?"))
    check("Q12 rhetorical -> 0", rc == 0, f"rc={rc}")

    # Q13 "~해도 되나요?" 변형 확인 질문 → 저지 (V1 FN_spec_variant)
    rc, _ = run(repo, write_transcript(tmp, "t13.jsonl", "검증도 끝났습니다. 이대로 진행해도 되나요?"))
    check("Q13 spec variant blocked -> 99", rc == BLOCK, f"rc={rc}")

    # Q14 허용키워드가 본문 "앞부분"에만 있고 끝은 금지 질문 → 저지 (V2 반례: 전체검사 우회)
    rc, _ = run(repo, write_transcript(
        tmp, "t14.jsonl",
        "앞서 캡차 처리 로직을 고쳤습니다.\n\n테스트도 통과했습니다. 이제 커밋을 진행할까요?"))
    check("Q14 early-allow-keyword bypass blocked -> 99", rc == BLOCK, f"rc={rc}")
    # Q14b 허용키워드가 마지막 문단에 있으면 여전히 허용
    rc, _ = run(repo, write_transcript(
        tmp, "t14b.jsonl",
        "작업 정리했습니다.\n\n캡차가 떠서 멈췄습니다. 직접 풀어주시겠어요?"))
    check("Q14b tail allow keyword -> 0", rc == 0, f"rc={rc}")

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} PASS")
sys.exit(1 if failed else 0)
