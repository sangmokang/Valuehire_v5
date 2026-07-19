#!/usr/bin/env python3
"""runner_lease — 러너 리스 마커 판정 공용 모듈 + CLI (SOT-30 §4.5 R3).

"판단은 모델, 실행은 코드": 브라우저 손 조작(타이핑·클릭·JS)은 레포 러너가 수행한다.
러너는 작업 시작 시 리스(.claude/runner-lease.json)를 발급하고 끝나면 해제한다.
- Claude PreToolUse 가드(.claude/hooks/guards/runner-lease.py)가 이 모듈을 호출해
  리스 없는 직접 브라우저 타이핑 도구 호출을 차단한다(H4).
- Codex 등 훅 없는 실행기는 도구 계층이 스스로 이 모듈(check_lease/require_lease 또는
  CLI `python3 tools/harness/runner_lease.py check`)을 호출해 자기를 지킨다(도구 내장 가드).
로직 본체는 이 파일 한 곳 — 다른 곳에 판정 로직을 복제하지 않는다(SOT-30 R-장치).

정직 표기: 이 장치는 우회 가능하다(Bash 직접 CDP 등) — 목적은 원천 봉쇄가 아니라
주요 경로를 좁히는 것이다. 판정 불능·계약 위반 리스는 전부 불허(deny-by-default).

CLI:
  python3 tools/harness/runner_lease.py check              # exit 0 = 유효 리스, 3 = 없음/무효
  python3 tools/harness/runner_lease.py issue --runner X [--ttl 120] [--scope browser-typing]
  python3 tools/harness/runner_lease.py release
"""
import argparse
import datetime
import json
import os
import pathlib
import sys

MARKER_PARTS = (".claude", "runner-lease.json")
DEFAULT_TTL_MIN = 120
FUTURE_SKEW = datetime.timedelta(minutes=5)
EXIT_NO_LEASE = 3


def marker_path(root):
    return pathlib.Path(root).joinpath(*MARKER_PARTS)


def check_lease(root):
    """(ok: bool, reason: str). 마커 없음·판독 불가·naive 시각·만료·미래 = 전부 불허."""
    p = marker_path(root)
    if not p.is_file():
        return False, "리스 마커 없음"
    try:
        data = json.loads(p.read_text())
        # V1 반례(2026-07-19): 발급 주체·범위 불명 리스는 무효 — runner/scope 필수 비어있지 않은 문자열.
        runner = data.get("runner")
        scope = data.get("scope")
        if not isinstance(runner, str) or not runner.strip():
            return False, "runner 불명(빈값) 리스 — 발급 주체 없는 리스는 무효"
        if not isinstance(scope, str) or not scope.strip():
            return False, "scope 불명 리스"
        created = datetime.datetime.fromisoformat(str(data["created_at"]))
        if created.tzinfo is None:
            return False, "created_at naive(계약 위반)"
        ttl = float(data.get("ttl_minutes", DEFAULT_TTL_MIN))
        if not (0 < ttl <= 24 * 60):
            return False, f"ttl_minutes 비정상({ttl!r})"
        age = datetime.datetime.now(datetime.timezone.utc) - created
        if age < -FUTURE_SKEW:
            return False, "미래 시각 리스"
        if age > datetime.timedelta(minutes=ttl):
            return False, f"리스 만료(TTL {ttl:g}분 경과)"
        return True, f"유효 리스: runner={data.get('runner', '?')}"
    except Exception as e:  # 깨진 리스 = 무효(가드 크래시가 아니라 명시적 불허)
        return False, f"리스 판독 불가({type(e).__name__})"


def require_lease(root=None, action="browser-typing"):
    """도구 내장 가드용: 유효 리스 없으면 사유를 stderr에 남기고 exit 3."""
    root = root or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    ok, reason = check_lease(root)
    if not ok:
        sys.stderr.write(
            f"[runner-lease] 거부: {action} — {reason}. "
            "손 조작은 리스를 발급한 정식 러너로만 실행하세요 "
            "(러너가 시작 시 issue, 종료 시 release — SOT-30 §4.5 R3).\n")
        sys.exit(EXIT_NO_LEASE)
    return True


def _issue(root, runner, ttl, scope):
    p = marker_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "runner": runner,
        "scope": scope,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "ttl_minutes": ttl,
        "pid": os.getpid(),
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.rename(p)
    print(f"[runner-lease] 발급: {runner} (TTL {ttl}분) → {p}")


def _release(root):
    p = marker_path(root)
    if p.is_file():
        p.unlink()
        print(f"[runner-lease] 해제: {p}")
    else:
        print("[runner-lease] 해제할 리스 없음")


def main(argv=None):
    ap = argparse.ArgumentParser(description="runner lease (SOT-30 R3)")
    ap.add_argument("cmd", choices=["check", "issue", "release"])
    ap.add_argument("--root", default=None)
    ap.add_argument("--runner", default=None)
    ap.add_argument("--ttl", type=float, default=DEFAULT_TTL_MIN)
    ap.add_argument("--scope", default="browser-typing")
    a = ap.parse_args(argv)
    root = a.root or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if a.cmd == "check":
        ok, reason = check_lease(root)
        print(f"[runner-lease] {reason}")
        return 0 if ok else EXIT_NO_LEASE
    if a.cmd == "issue":
        if not a.runner:
            ap.error("issue에는 --runner 필수")
        _issue(root, a.runner, a.ttl, a.scope)
        return 0
    _release(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
