#!/usr/bin/env python3
"""
harness-dispatch — 모든 스킬 공용 PreToolUse 가드 디스패처.

목적: "스킬별 가드"를 한 곳에서 자동 발견·실행해, 모든 툴 호출에 하네스 강제를 건다.
새 스킬을 강제하려면 `guards/<skill>.py` 한 파일만 추가하면 된다(이 파일 수정 불필요).

동작:
  1) PreToolUse 로 넘어온 JSON({tool_name, tool_input, ...})을 stdin 으로 읽는다.
  2) `.claude/hooks/guards/*.py`(밑줄로 시작하는 파일 제외)를 알파벳 순으로 로드해
     각 모듈의 check(tool, tool_input) 를 호출한다.
  3) 어떤 가드든 '사유 문자열'을 반환하면 그 사유로 차단(stderr + exit 2).
  4) 전부 None 이면 통과(exit 0).
  5) 가드 로드/실행이 예외를 던지면 그 가드만 건너뛴다(fail-open) — 정상 작업은 절대 막지 않는다.
  6) 입력 JSON 파싱 불가도 fail-open(exit 0).

계약(가드 인터페이스): `guards/_template.py` 참조.
규약(새 스킬 등록법): `.claude/hooks/README.md`, docs/sot/27-harness-skill-guards.md.
"""
import sys, os, json, importlib.util, glob

GUARDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guards")


def load_guards():
    guards = []
    for path in sorted(glob.glob(os.path.join(GUARDS_DIR, "*.py"))):
        base = os.path.basename(path)
        if base.startswith("_"):  # _template.py, __init__.py 등 제외
            continue
        try:
            spec = importlib.util.spec_from_file_location("guard_" + base[:-3], path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "check"):
                guards.append((base[:-3], mod))
        except Exception:
            sys.stderr.write("[harness-dispatch] guard load skipped (error): %s\n" % base)
    return guards


def main():
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)  # 파싱 불가 → fail-open
    if not isinstance(data, dict):
        sys.exit(0)  # 최상위가 dict 가 아님(list/str/null) → fail-open (크래시 방지)
    tool = data.get("tool_name", "") or ""
    tool_input = data.get("tool_input", {}) or {}
    for name, mod in load_guards():
        try:
            reason = mod.check(tool, tool_input)
        except Exception:
            sys.stderr.write("[harness-dispatch] guard '%s' raised, skipped\n" % name)
            continue
        if reason:
            sys.stderr.write(reason if str(reason).endswith("\n") else str(reason) + "\n")
            sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
