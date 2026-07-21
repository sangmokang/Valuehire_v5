#!/usr/bin/env python3
"""Stop 증거 게이트 — strict 작업 중 미커밋 변경을 남긴 채 응답을 끝내는 것을 차단.

계약: docs/sot/30-strict-mode-contract.md §4 / goal: stop-evidence-gate-goal-2026-07-18.md
V1 적대검증(2026-07-18, F1~F7) 반영판.

정직한 범위 선언: 이 게이트는 "유효 마커 + 미커밋 잔존" 종료에 **한 턴 계속 프롬프트**를
넣는 장치다(공식 사양상 stop_hook_active 재시도 턴은 통과 — 무한루프 방지가 우선).
완료의 의미 검증(테스트·배선·증거)은 G→V1→V2 적대검증의 몫이다.

설계 원칙:
- 마커 수명주기는 러너(tools/harness/wt.mjs)가 소유(H3) — 생성: npm run wt, 해제: npm run wt:done.
- 마커 위치는 항상 **메인 레포** .claude/strict-active.json — 워크트리 세션도
  git-common-dir 기준으로 메인 마커를 본다(F1 위치 불일치 제거).
- 차단은 내부 sentinel exit 99 로만 표현하고, settings 래퍼가 99만 protocol exit 2로
  승격한다 — 인터프리터 크래시(1,2)는 차단으로 오인되지 않는다(F6).
- git 하위호출은 GIT_* 환경을 제거한 새 환경에서 실행하고, 마커의 worktree가 실제
  그 저장소 최상위인지 재확인한다(F2).
- created_at은 timezone 명시 필수, 미래 5분 초과·24h 경과·naive 시각은 전부 통과(F3).
- worktree는 비어있지 않은 절대경로만 인정(F4). 세션 구속: 마커와 payload 양쪽에
  session_id가 있고 다르면 남의 작업이므로 통과(F5).
- 그 외 모든 모호·예외는 fail-open(exit 0) — 최악의 실패 모드는 전 세션 잠금이다.
"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

BLOCK_EXIT = 99  # settings 래퍼만 이 값을 exit 2로 승격한다
TTL_HOURS = 24
FUTURE_SKEW = datetime.timedelta(minutes=5)

# --- R2 질문 금지 (SOT-30 §4.5, 2026-07-19) -------------------------------
# strict 마커가 유효한 세션에서, 마지막 어시스턴트 메시지가 스펙 내 확인 질문으로
# 끝나면 1턴 저지한다. 정직 표기: 정규식 휴리스틱이라 의미 판정은 불가(D5) —
# 허용 질문(2FA·캡차·본인확인·파괴적/비가역)은 키워드로 통과, 모호하면 통과(fail-open).
_QUESTION_RE = re.compile(
    r"(할까요|할가요|드릴까요|볼까요|될까요|되나요|괜찮을까요|괜찮은가요|괜찮으신가요"
    r"|어떻게 ?(할까요|진행)|어떤 ?(걸|것|쪽)으?로|어느 ?(쪽|것)"
    r"|선택해 ?주|알려 ?주(세요|시겠)|진행 ?여부|주실래요|주시겠어요)"
    r"[^\n?？]{0,15}[?？][\s'\"`*_)\]]*$"
)
# 수사적 질문("왜 …까요?")은 확인 질문이 아니다 — V1 FP 반례(2026-07-19).
_RHETORICAL_RE = re.compile(r"^\s*[('\"`*_]*\s*(왜|어째서)\b|^\s*[('\"`*_]*\s*(왜|어째서)")
# 허용 키워드 뒤 8자 내 부정(없/아니)이 붙으면 허용이 아니다 — V1 부정문 우회 반례.
_QUESTION_ALLOW_RE = re.compile(
    r"(2FA|캡차|CAPTCHA|본인 ?확인|본인 ?인증|인증 ?번호|OTP|2단계 ?인증|MFA|체크포인트"
    r"|파괴적|비가역|비복구|되돌리기 어려|되돌릴 수 없|삭제하는|영구 ?삭제|덮어쓰"
    r"|force ?push|rm -rf|디스크 ?포맷)"
    r"(?![^\n]{0,8}(없|아니|아닙|않))",  # '아닙니다'는 '아니'가 아니라 '아닙'으로 시작(음절 조합)
    re.I,
)


def _last_assistant_text(transcript_path):
    """transcript(JSONL)에서 마지막 assistant 텍스트. 실패는 전부 None(fail-open)."""
    try:
        last = None
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") != "assistant":
                    continue
                content = (obj.get("message") or {}).get("content")
                if isinstance(content, list):
                    texts = [c.get("text", "") for c in content
                             if isinstance(c, dict) and c.get("type") == "text"]
                    if any(texts):
                        last = "\n".join(t for t in texts if t)
                elif isinstance(content, str) and content:
                    last = content
        return last
    except Exception:
        return None


def question_violation(payload):
    """R2: 스펙 내 확인 질문으로 끝나는 턴이면 사유 문자열, 아니면 None."""
    tp = payload.get("transcript_path")
    if not tp:
        return None
    text = _last_assistant_text(tp)
    if not text:
        return None
    # V2 반례(2026-07-19): 허용키워드를 본문 전체에서 찾으면 앞부분 언급("앞서 캡차…")으로
    # 금지 질문 종료가 통과한다 — 마지막 2줄(질문 문맥)에서만 허용키워드를 인정한다.
    tail_ctx = "\n".join(text.rstrip().splitlines()[-2:])
    if _QUESTION_ALLOW_RE.search(tail_ctx):
        return None  # 허용 질문(2FA·캡차·본인확인·파괴적/비가역)
    tail = text.rstrip()
    last_line = tail.splitlines()[-1].strip() if tail else ""
    if _RHETORICAL_RE.match(last_line):
        return None  # 수사적 질문 — 확인 질문 아님(V1 FP)
    if _QUESTION_RE.search(last_line):
        return (
            "[stop-evidence-gate/R2] 질문 금지 게이트 — 턴이 스펙 내 확인 질문으로 끝났습니다. "
            "스펙·SOT·예외 케이스 표에 답이 있으면 되묻지 말고 그대로 실행하세요. "
            "예외 표에 없는 신규 상황이면 질문이 아니라 '중단 보고 + 표 갱신안 제시'로 끝내세요. "
            "(허용 질문 = 2FA·캡차·본인확인 / 파괴적·비가역 확인뿐 — SOT-30 §4.5 R2. "
            "이 게이트는 1턴 저지입니다.)"
        )
    return None


# --- AC-3 H4: fleet 잡 완료 주장 증거 게이트 (goal: discord-single-bot-console §9) ---
# fleet 잡 세션(워커가 주입하는 env VH_BUSY_TASK) 한정. 마지막 응답이 완료를 주장하는데
# 증거 토큰(영수증 마커·건수·잡 번호)이 하나도 없으면 1턴 저지한다. 휴리스틱이므로
# 모호하면 통과(fail-open) — 완결 검증은 워커의 영수증 계약(validate_aisearch_receipt)이 1층.
_FLEET_DONE_RE = re.compile(r"(완료|끝났|마쳤|모두 처리|done\b)", re.I)
_FLEET_EVIDENCE_RE = re.compile(
    r"FLEET_SEARCH_RECEIPT:|\d+\s*건|\d+\s*명|잡\s*#\d+|job\s*#\d+|영수증|paused_for_human|실패|중단",
    re.I,
)


def fleet_job_violation(payload):
    if not (os.environ.get("VH_BUSY_TASK") or "").strip():
        return None
    text = _last_assistant_text(payload.get("transcript_path") or "")
    if not text:
        return None
    if _FLEET_DONE_RE.search(text) and not _FLEET_EVIDENCE_RE.search(text):
        return (
            "[stop-evidence-gate/H4] fleet 잡 완료 보고에 증거가 없습니다 — 결과 요약"
            "(처리 건수·후보 수·잡 번호·FLEET_SEARCH_RECEIPT)을 포함해 다시 보고하세요. "
            "증거 없는 '완료'는 인정되지 않습니다(goal §9 H4, 1턴 저지)."
        )
    return None


def _git(args, timeout):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          timeout=timeout, env=env)


def find_marker(cwd):
    """메인 레포 루트의 마커 경로(없으면 None). 워크트리 cwd여도 메인을 본다."""
    p = _git(["-C", cwd or ".", "rev-parse", "--path-format=absolute", "--git-common-dir"], 10)
    if p.returncode == 0 and p.stdout.strip():
        root = pathlib.Path(p.stdout.strip()).parent
    else:
        env_root = os.environ.get("CLAUDE_PROJECT_DIR")
        if not env_root:
            return None
        root = pathlib.Path(env_root)
    marker = root / ".claude" / "strict-active.json"
    return marker if marker.is_file() else None


def judge(payload):
    """차단이면 사유 문자열, 통과면 None. 예외는 호출부에서 fail-open."""
    if payload.get("stop_hook_active"):
        return None
    # AC-3 H4 — fleet 잡 세션은 strict 마커와 무관하게 증거 게이트를 먼저 검사.
    reason_fleet = fleet_job_violation(payload)
    if reason_fleet:
        return reason_fleet
    marker_path = find_marker(payload.get("cwd", "."))
    if marker_path is None:
        return None
    data = json.loads(marker_path.read_text())

    # 세션 구속(F5): 양쪽에 session_id가 있고 다르면 남의 strict 작업 — 간섭하지 않는다.
    m_sess, p_sess = data.get("session_id"), payload.get("session_id")
    if m_sess and p_sess and m_sess != p_sess:
        return None

    created = datetime.datetime.fromisoformat(str(data["created_at"]))
    if created.tzinfo is None:
        return None  # 계약 위반(naive) 마커는 판정하지 않는다(F3)
    age = datetime.datetime.now(datetime.timezone.utc) - created
    if age < -FUTURE_SKEW or age > datetime.timedelta(hours=TTL_HOURS):
        return None  # 미래 시계·stale — 영구잠금 방지(F3)

    # R2 질문 금지 — 유효한 strict 마커 세션이면 미커밋 잔존 여부와 무관하게 검사.
    reason_q = question_violation(payload)
    if reason_q:
        return reason_q

    raw_wt = data.get("worktree")
    if not isinstance(raw_wt, str) or not raw_wt or not os.path.isabs(raw_wt):
        return None  # 절대경로 스키마 강제(F4)
    wt = pathlib.Path(raw_wt).resolve()
    if not wt.is_dir():
        return None
    top = _git(["-C", str(wt), "rev-parse", "--show-toplevel"], 10)
    if top.returncode != 0 or pathlib.Path(top.stdout.strip()).resolve() != wt:
        return None  # 마커 대상이 저장소 최상위가 아니면 판정 불가(F2/F4)

    status = _git(["-C", str(wt), "status", "--porcelain"], 15)
    if status.returncode != 0 or not status.stdout.strip():
        return None  # 판정 불가 또는 clean — 막지 않는다

    slug = str(data.get("slug", "?"))[:80]
    slug = "".join(ch if ch.isprintable() else "?" for ch in slug)
    return (
        f"[stop-evidence-gate] strict 작업 '{slug}' 미종결 — 워크트리({wt})에 미커밋 변경이 남아 있습니다. "
        "종료 전에 ① 변경을 커밋하고 검증(게이트 4)까지 진행하거나, "
        f"② 사용자가 중단·보류를 지시했다면 그 사실을 보고에 남기고 마커를 해제(rm {marker_path} 또는 npm run wt:done)한 뒤 종료하세요. "
        "(이 게이트는 한 턴 계속 프롬프트입니다 — 준비만 하고 멈추는 종료(패턴 J)를 1회 저지하고 올바른 경로를 안내합니다.)"
    )


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        reason = judge(payload)
    except Exception:
        return 0  # fail-open — 안전장치가 정상 업무를 잠그지 않는다
    if reason:
        print(reason, file=sys.stderr)
        return BLOCK_EXIT
    return 0


if __name__ == "__main__":
    sys.exit(main())
