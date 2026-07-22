"""bot_intent.py — 자유 문장 의도 분류기 (AC-5, 2026-07-22).

goal §6.4 + §5.1 핵심 원칙: 자유 문장은 반드시 "허용된 명령 집합" 안으로만 사상된다.
사상 실패 = 실행 금지. 평문이 곧바로 임의 실행이 되는 경로를 절대 만들지 않는다.

규칙 기반(E15 결정 — LLM 호출 없이 비용·지연 0). 확신/애매/모름/거부 4분기:
- CONFIDENT : 명확한 동사·대상 → 명령 하나로 사상(command 채움). 호출부가 "이렇게
  이해했습니다" 표기 후 실행.
- AMBIGUOUS : 대상은 있으나 어느 스킬인지 갈림 → 후보(candidates) 제시, 실행 안 함.
- UNKNOWN   : 잡담·빈 입력 → 실행 안 함.
- REFUSED   : 발송 요구(SOT28)·프롬프트 인젝션·셸 실행 요구 → 명시 거부, 실행 안 함.

이 모듈은 순수(부작용 0). 실제 실행은 호출부가 command/args 를 기존 명령 경로로만 흘린다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# 자유 문장이 사상될 수 있는 유일한 명령 집합(화이트리스트). 이 밖으로는 절대 안 나간다.
ALLOWED_INTENT_COMMANDS: frozenset[str] = frozenset({
    "aisearch", "humansearch", "url", "login", "jobs", "kpi",
})

_URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_SEARCH_HOST_MARKERS = ("linkedin.com", "saramin.co.kr", "jobkorea.co.kr")

# 발송 요구(SOT28) — 명시 거부. "보내/발송/send/inmail 발송/메일 보내" 등.
_SEND_RE = re.compile(
    r"(메일|이메일|인메일|제안|offer|inmail|mail)\s*\S{0,6}?(보내|발송|send)"
    r"|(보내|발송|send)\s*\S{0,6}?(메일|이메일|인메일|제안|offer|inmail|mail)"
    r"|\bsend\b",
    re.IGNORECASE,
)
# 프롬프트 인젝션·셸 실행 요구 — 명시 거부.
_INJECTION_RE = re.compile(
    r"(앞의?\s*지시\s*무시|이전\s*지시\s*무시|ignore\s+previous|시스템\s*프롬프트"
    r"|system\s*prompt|관리자\s*권한|admin\s*권한|sudo\b)",
    re.IGNORECASE,
)
_SHELL_RE = re.compile(
    r"\b(rm\s+-rf|git\s+(push|reset|rebase|commit)|shell|bash|sh\s+-c|npm\s+run|"
    r"curl\b|wget\b|chmod\b|kill\b|launchctl\b)\b",
    re.IGNORECASE,
)

# 검색 동사(사상 신호). 있으면 URL 종류에 따라 aisearch/humansearch 확정.
_SEARCH_VERB_RE = re.compile(
    r"(후보|찾아|서치|검색|소싱|순회|채점|뽑아|리스트\s*돌)", re.IGNORECASE)
# humansearch 쪽 강한 신호(걸어둔 결과 순회·채점).
_HUMAN_VERB_RE = re.compile(r"(순회|채점|걸어둔|검색결과|리스트\s*돌)", re.IGNORECASE)
# 로그인·상태·KPI·작업 조회 신호.
_LOGIN_RE = re.compile(r"(로그인|login|재로그인|세션\s*확인)", re.IGNORECASE)
_KPI_RE = re.compile(r"(kpi|지표|실적|매출\s*지표|주간\s*지표)", re.IGNORECASE)
_JOBS_RE = re.compile(r"(작업\s*(상태|현황|목록)|잡\s*(상태|목록)|돌아가는\s*(작업|일)|큐\s*상태|진행\s*상황)", re.IGNORECASE)
_URL_PREP_RE = re.compile(r"(rps|검색\s*url|서치\s*url|url\s*(세팅|준비|만들))", re.IGNORECASE)

_MACHINE_MARKERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<!\w)(?:winpc|windows?|윈도우(?:pc)?)(?!\w)", re.IGNORECASE), "winpc"),
    (re.compile(r"(?<!\w)(?:macmini|맥미니)(?!\w)", re.IGNORECASE), "macmini"),
    (re.compile(r"(?<!\w)(?:macbook|맥북)(?!\w)", re.IGNORECASE), "macbook"),
)


class ClassifyOutcome(str, Enum):
    CONFIDENT = "confident"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"
    REFUSED = "refused"


@dataclass(frozen=True)
class ClassifyResult:
    outcome: ClassifyOutcome
    command: Optional[str] = None          # CONFIDENT 일 때만 채워짐(허용 집합 안)
    args: dict[str, str] = field(default_factory=dict)
    candidates: tuple[str, ...] = ()       # AMBIGUOUS 일 때 2~3개
    reason: str = ""

    def __post_init__(self) -> None:
        # 불변식(안전): command 는 None 이거나 허용 집합 안. 그리고 command 는 CONFIDENT 전용.
        if self.command is not None:
            assert self.command in ALLOWED_INTENT_COMMANDS, self.command
            assert self.outcome is ClassifyOutcome.CONFIDENT


def _is_search_url(url: str) -> bool:
    import urllib.parse
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    # 검색결과 페이지는 경로에 talent-search/search/result 등이 들어간다.
    if any(host == m or host.endswith("." + m) for m in _SEARCH_HOST_MARKERS):
        path = urllib.parse.urlparse(url).path.lower()
        return any(k in path for k in ("search", "result", "talent"))
    return False


def _url_args(raw: str, url: str) -> dict[str, str]:
    args = {"url": url}
    for pattern, machine in _MACHINE_MARKERS:
        if pattern.search(raw):
            args["machine"] = machine
            break
    return args


def classify_free_text(text: str) -> ClassifyResult:
    """자유 문장 1건을 허용 명령으로 사상(실패 시 실행 금지)."""
    raw = (text or "").strip()
    if not raw:
        return ClassifyResult(ClassifyOutcome.UNKNOWN, reason="빈 입력")

    # ① 거부 먼저(가장 위험한 신호부터) — 발송·인젝션·셸.
    if _SEND_RE.search(raw):
        return ClassifyResult(ClassifyOutcome.REFUSED,
                              reason="발송 요구는 자동 실행하지 않습니다(SOT28 — 사장님 수동 게이트).")
    if _INJECTION_RE.search(raw):
        return ClassifyResult(ClassifyOutcome.REFUSED,
                              reason="지시 무시·권한 상승·시스템 프롬프트 요구는 실행하지 않습니다.")
    if _SHELL_RE.search(raw):
        return ClassifyResult(ClassifyOutcome.REFUSED,
                              reason="임의 셸/깃 명령은 실행하지 않습니다(디스코드 셸 실행 금지).")

    urls = [m.group(0).rstrip(".,);]}") for m in _URL_RE.finditer(raw)]

    # ② URL 이 있는 경우 — 검색 계열로 사상.
    if urls:
        url = urls[0]
        search_url = _is_search_url(url)
        has_search_verb = bool(_SEARCH_VERB_RE.search(raw))
        has_human_verb = bool(_HUMAN_VERB_RE.search(raw))
        if _URL_PREP_RE.search(raw):
            return ClassifyResult(ClassifyOutcome.CONFIDENT, "url", _url_args(raw, url),
                                  reason="RPS 검색 URL 준비로 이해")
        if search_url or has_human_verb:
            if has_search_verb or has_human_verb:
                return ClassifyResult(
                    ClassifyOutcome.CONFIDENT, "humansearch", _url_args(raw, url),
                                      reason="검색결과 순회·채점(humansearch)으로 이해")
            # 검색결과 URL 인데 동사 없음 — humansearch/aisearch 갈림.
            return ClassifyResult(ClassifyOutcome.AMBIGUOUS,
                                  candidates=("humansearch", "aisearch"),
                                  reason="검색결과 URL 이지만 무엇을 할지 불명확")
        if has_search_verb:
            return ClassifyResult(
                ClassifyOutcome.CONFIDENT, "aisearch", _url_args(raw, url),
                                  reason="포지션 AI Search 로 이해")
        # 포지션 URL 만 있고 동사 없음 — aisearch/humansearch/url 갈림.
        return ClassifyResult(ClassifyOutcome.AMBIGUOUS,
                              candidates=("aisearch", "humansearch", "url"),
                              reason="URL 만 있어 무슨 작업인지 불명확")

    # ③ URL 이 없는 조회·상태 계열.
    if _JOBS_RE.search(raw):
        return ClassifyResult(ClassifyOutcome.CONFIDENT, "jobs", reason="작업 상태 조회로 이해")
    if _KPI_RE.search(raw):
        return ClassifyResult(ClassifyOutcome.CONFIDENT, "kpi", reason="KPI 조회로 이해")
    if _LOGIN_RE.search(raw):
        return ClassifyResult(ClassifyOutcome.CONFIDENT, "login", reason="로그인 상태 확인으로 이해")

    # ④ 검색 동사만 있고 대상(URL)이 없음 — 대상 불명확(실행 금지, 되물음).
    if _SEARCH_VERB_RE.search(raw):
        return ClassifyResult(ClassifyOutcome.AMBIGUOUS,
                              candidates=("aisearch", "humansearch"),
                              reason="검색 의도는 보이나 대상 URL 이 없습니다")

    # ⑤ 그 외 전부 — 못 알아들음(추측 실행 금지).
    return ClassifyResult(ClassifyOutcome.UNKNOWN, reason="명령으로 사상 실패")
