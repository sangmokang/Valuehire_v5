"""guards/nl-shell-routing.py — H-NL1~H-NL3: 자연어 셸 라우팅 강제 (SOT-32).

정본 계약: docs/sot/32-nl-shell-routing.json (+ .md)
목표 문서: docs/prompts/discord-nl-shell-routing-goal-2026-07-22.md

사장님 자연어("클릭업에서 번개장터 PM 찾아")를 쉘처럼 처리하되, 그 편의가
우회로가 되지 않게 문을 건다. 자연어 셸 컨텍스트(env VH_NL_SHELL)에서만 동작한다.

  H-NL1  정본 모듈(nl_shell.py) 밖에서 자연어 파서·라우팅 즉석 자작 차단   (F-NL4)
  H-NL2  대상 미해소(URL 미확정) 상태의 실행형 큐 적재 차단              (F-NL3)
  H-NL3  자연어 경로에서 포털 raw 조작·제안 발송으로 새는 것 차단         (F-NL1·F-NL2)

정직 표기: 훅은 fail-open(로드 실패 시 통과)이라 최종 방어선이 아니다. 본체는
해소층 코드 안의 정책(SOT-32 §4)이며 이 가드는 2층이다.
"""
import os
import re

NAME = "nl-shell-routing"

# ── 정본 경로 ──────────────────────────────────────────────────────────────
# 자연어 파싱·해소는 오직 이 모듈에서만 구현한다(SOT-32 canonical_module).
_CANONICAL_MODULE = "tools/multi_position_sourcing/nl_shell.py"
# 계약·문서·테스트·가드 자신은 당연히 자유롭게 쓸 수 있어야 한다.
_ALWAYS_WRITABLE = (
    _CANONICAL_MODULE,
    "docs/sot/32-nl-shell-routing",
    "docs/prompts/discord-nl-shell-routing",
    "tests/test_nl_shell_routing.py",
    ".claude/hooks/guards/nl-shell-routing.py",
    ".claude/hooks/tests/",
)

# ── H-NL1: 즉석 자연어 파서 자작 신호 ──────────────────────────────────────
# "장소 어휘를 코드에서 직접 문자열 매칭한다" = 라우팅을 새로 짜고 있다는 신호.
_LOCUS_LITERALS = ("클릭업에서", "클릭업", "웹에서", "잡코리아", "사람인", "링크드인")
_NL_PARSER_SIGNALS = (
    r"def\s+\w*(parse|classify|route|resolve)\w*natural\w*",
    r"def\s+\w*natural\w*(parse|classify|route|resolve)\w*",
    r"def\s+parse_natural_language",
    r"def\s+\w*(intent|nl)_(parse|classify|router?)\w*",
)

# ── H-NL2: 실행형 큐 적재 ──────────────────────────────────────────────────
_ENQUEUE_SIGNALS = (
    r"enqueue_job\s*\(",
    r"discord_gateway_enqueue",
    r"new_job_payload\s*\(",
    r"/fleet-run\b",
)
# 해소가 끝났다는 증거 = 실제 URL 이 인자에 박혀 있다.
_RESOLVED_URL = re.compile(r"https?://[^\s'\"]+")

# ── H-NL3: 포털 raw 조작 · 발송 ────────────────────────────────────────────
_PORTAL_HOSTS = ("saramin.co.kr", "jobkorea.co.kr", "linkedin.com")
_RAW_AUTOMATION = (
    r"devtools/page/",           # raw CDP 웹소켓 직결
    r"Page\.navigate",
    r"Runtime\.evaluate",
    r"Input\.dispatch",
    r"--remote-debugging-port",
)
_SEND_SIGNALS = (
    r"\bsend_inmail\b",
    r"--send\b",
    r"\bsend_offer\b",
    r"\bcreate_draft\b",
    r"\bsend_message\b",
)

# 정식 러너는 항상 통과시킨다(false positive 로 자기 작업을 막지 않는다).
_OFFICIAL_RUNNERS = (
    r"npm\s+run\s+position-batch:",
    r"python3?\s+-m\s+tools\.multi_position_sourcing\.",
    r"\bdirect_receiver\b",
)


def _in_nl_shell() -> bool:
    return bool((os.environ.get("VH_NL_SHELL") or "").strip())


def _any(patterns, text) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _is_official(cmd: str) -> bool:
    return _any(_OFFICIAL_RUNNERS, cmd)


def check(tool, tool_input):
    if not _in_nl_shell():
        return None
    tool_input = tool_input or {}

    # ── H-NL1 ── 정본 모듈 밖에서 자연어 파서를 즉석 자작하는가
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = str(tool_input.get("file_path") or "")
        if path and not any(ok in path for ok in _ALWAYS_WRITABLE):
            body = "\n".join(str(tool_input.get(k) or "")
                             for k in ("content", "new_string", "new_source"))
            looks_like_parser = _any(_NL_PARSER_SIGNALS, body) or (
                sum(lit in body for lit in _LOCUS_LITERALS) >= 2
            )
            if looks_like_parser:
                return (
                    f"⛔ 차단({NAME} / H-NL1): 자연어 파서·라우팅은 정본 모듈 "
                    f"`{_CANONICAL_MODULE}` 에서만 구현합니다. "
                    f"'{path}' 에 즉석 파서를 만들지 마세요 — 계약은 "
                    f"docs/sot/32-nl-shell-routing.json (F-NL4, CLAUDE.md §0.2 새 러너 금지)."
                )

    if tool != "Bash":
        return None
    cmd = str(tool_input.get("command") or "")
    if not cmd:
        return None

    # ── H-NL3 ── 포털 raw 조작 (정식 러너는 예외 없이 먼저 통과)
    if not _is_official(cmd):
        if _any(_RAW_AUTOMATION, cmd) and any(h in cmd.lower() for h in _PORTAL_HOSTS):
            return (
                f"⛔ 차단({NAME} / H-NL3): 자연어 경로에서 채용사이트를 raw CDP·즉석 "
                f"스크립트로 직접 조작할 수 없습니다. 정식 러너(각 SKILL.md)로 가세요 "
                f"— F-NL2, SOT-25 §0(2026-07-09 지아이텍 사고 재발방지)."
            )
        # ── H-NL3 ── 제안·메일 발송
        if _any(_SEND_SIGNALS, cmd):
            return (
                f"⛔ 차단({NAME} / H-NL3): 자연어로는 제안·메일 발송에 도달할 수 "
                f"없습니다. 발송은 슬래시 명령 + 사장님 확인 게이트 전용입니다 "
                f"— F-NL1·F-NL5, SOT-28."
            )

    # ── H-NL2 ── 대상 미해소 상태로 실행형 큐에 적재하는가
    if _any(_ENQUEUE_SIGNALS, cmd) and not _RESOLVED_URL.search(cmd):
        return (
            f"⛔ 차단({NAME} / H-NL2): 대상이 아직 해소되지 않았습니다(URL 없음). "
            f"자연어를 큐에 바로 넣지 말고 먼저 `{_CANONICAL_MODULE}` 의 resolve() 로 "
            f"ClickUp/웹에서 대상 URL 을 확정하세요. 0건이면 실행 금지, 여러 건이면 "
            f"사장님께 '어느 것?'을 여쭙니다 — F-NL3, SOT-32 §4."
        )

    return None
