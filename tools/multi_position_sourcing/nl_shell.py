"""nl_shell — 디스코드 자연어를 셸 명령처럼 해석하는 정본 모듈 (AC-N1).

정본 계약: docs/sot/32-nl-shell-routing.json  ← 어휘·라우팅표의 **단일 출처**
목표 문서: docs/prompts/discord-nl-shell-routing-goal-2026-07-22.md

왜 이 모듈이 필요한가(2026-07-22 실측):
    디스코드 입구는 URL 을 가진 명령만 통과시킨다 — fleet_args._classify_bare_fleet_run_token
    은 맨 토큰이 모호하면 추측하지 않고 거부하고(fail-closed), 자연어 우회로도
    본문에 URL 이 0개면 즉시 포기한다. 그래서 "클릭업에서 번개장터 PM 찾아"는
    입구에서 버려졌다.

설계(SOT-32 §3):
    그 fail-closed 를 **풀지 않는다.** 이 모듈은 파서 **앞단**에서 자연어를
    (장소·대상·동사) 3요소로 해석할 뿐이고, 대상을 실제 URL 로 바꾸는 해소(resolve)를
    거친 뒤에야 기존 `/fleet-run <url> …` 계약으로 되돌린다. 파서에는 항상 완성된
    key:value 명령만 들어간다.

범위(정직 표기):
    이 모듈은 **해석만** 한다. 해소(ClickUp/웹 검색)는 AC-N2·AC-N3, 게이트웨이
    배선은 AC-N4 소관이다. 3요소가 다 안 잡히면 추측하지 않고 None 을 돌려준다.
"""

from __future__ import annotations

import functools
import json
import pathlib
import re
from dataclasses import dataclass
from typing import Any

_CONTRACT_REL = "docs/sot/32-nl-shell-routing.json"

# 가드(.claude/hooks/guards/nl-shell-routing.py)를 켜는 스위치.
# fleet_worker 가 VH_BUSY_TASK 를 하위 프로세스에 주입하는 것과 동일 패턴.
BADGE_ENV_KEY = "VH_NL_SHELL"


def _repo_root() -> pathlib.Path:
    # tools/multi_position_sourcing/nl_shell.py → 레포 루트
    return pathlib.Path(__file__).resolve().parent.parent.parent


@functools.lru_cache(maxsize=1)
def load_contract() -> dict[str, Any]:
    """SOT-32 계약을 읽는다. 어휘를 코드에 복제하지 않기 위한 단일 출처."""
    return json.loads((_repo_root() / _CONTRACT_REL).read_text(encoding="utf-8"))


def _loci() -> dict[str, list[str]]:
    return load_contract()["loci"]


def _verbs() -> dict[str, dict[str, Any]]:
    return load_contract()["verbs"]


# 모듈 상수처럼 쓰이지만 실체는 계약에서 온다(테스트가 드리프트를 봉인).
class _ContractKeys:
    def __init__(self, getter):
        self._getter = getter

    def __iter__(self):
        return iter(self._getter())

    def __contains__(self, key):
        return key in self._getter()

    def __getitem__(self, key):
        return self._getter()[key]


LOCI = _ContractKeys(_loci)
VERBS = _ContractKeys(_verbs)


@dataclass(frozen=True)
class NlCommand:
    """해석 결과. 아직 대상이 URL 로 해소되지 않은 상태다."""

    locus: str
    target: str
    verb: str
    route: dict[str, Any]
    raw: str

    @property
    def risk(self) -> str:
        return str(_verbs()[self.verb]["risk"])

    @property
    def requires_confirmation(self) -> bool:
        return bool(_verbs()[self.verb]["requires_confirmation"])


# 장소를 여는 조사 — "클릭업에서", "웹에선" 등. 조사 없이 붙은 장소는 인정하지 않는다
# (평범한 명사와 구별이 안 되어 오탐을 만든다).
_LOCUS_PARTICLE = r"(?:에서|에선|에서는)"

# 장소 뒤에 붙는 수식어(대상이 아니다). "웹에서 공식 채용페이지에서 …" 의 가운데 토막.
_LOCUS_MODIFIER_RE = re.compile(
    r"(공식\s*)?(채용\s*(페이지|공고|사이트)|커리어\s*페이지|홈페이지)" + _LOCUS_PARTICLE + r"?\s*"
)

# 위험 동사 — 자연어로는 절대 발동할 수 없다(F-NL5). 어휘에 없을 뿐 아니라
# 문장에 나타나면 통째로 거부한다(다른 동사와 함께 와도 실행되지 않게).
_DANGEROUS_RE = re.compile(
    r"(발송|보내|전송|삭제|지워|없애|계산서|세금계산서|인보이스|발행)"
)


def _find_locus(text: str) -> tuple[str, str] | None:
    """가장 앞에 나오는 장소를 찾아 (locus, 나머지 문장) 반환.

    두 형태를 인정한다:
      ① `<장소>에서 …`        — 문장 어디서나. 조사가 장소임을 확정해 준다.
      ② `<장소> …`(문장 맨 앞) — 조사 없이. `작업목록 보여줘` 처럼 조사를 붙이면
                                 어색해지는 말을 살리기 위함(V1 2026-07-22: 이걸
                                 막았더니 계약된 queue 경로가 통째로 도달 불가였다).

    ②를 문장 맨 앞으로 제한하는 이유: 중간의 같은 낱말은 대상 이름의 일부일 수
    있다(`번개장터 잡 찾아` 의 '잡'). 애매하면 장소로 보지 않는다 — 추측 금지.
    """
    best: tuple[int, str, int] | None = None  # (시작위치, locus, 끝위치)
    for locus, aliases in _loci().items():
        for alias in aliases:
            # 별칭 자체가 조사를 포함하면("클릭업에서") 조사를 다시 요구하지 않는다.
            has_particle = bool(re.search(_LOCUS_PARTICLE + r"$", alias))
            pattern = re.escape(alias) + ("" if has_particle else _LOCUS_PARTICLE)
            m = re.search(pattern, text)
            if m is None and not has_particle:
                # ② 조사 없는 형태 — 문장 맨 앞 + 뒤에 공백이 오는 경우만.
                m = re.match(re.escape(alias) + r"(?=\s)", text)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), locus, m.end())
    if best is None:
        return None
    _, locus, end = best
    return locus, text[end:]


def _find_verb(text: str) -> tuple[str, str] | None:
    """문장 **끝**의 동사를 찾아 (verb, 동사를 걷어낸 앞부분) 반환.

    끝에서만 찾는 이유: 한국어 명령문은 동사가 뒤에 오고, 중간의 같은 글자가
    대상 이름의 일부일 수 있다(예: 회사명에 '확인'이 들어가는 경우).
    """
    tail = text.rstrip(" .!?~요")
    best: tuple[int, str] | None = None  # (시작위치, verb)
    for verb, spec in _verbs().items():
        for alias in spec["aliases"]:
            if tail.endswith(alias):
                start = len(tail) - len(alias)
                # 더 긴 별칭을 우선(“찾아줘” > “찾아”) — 시작이 더 앞이면 더 김.
                if best is None or start < best[0]:
                    best = (start, verb)
    if best is None:
        return None
    start, verb = best
    return verb, tail[:start]


def _route_for(locus: str, verb: str) -> dict[str, Any] | None:
    for route in load_contract()["routes"]:
        if route["locus"] == locus and route["verb"] == verb:
            return route
    return None


def parse(message: str) -> NlCommand | None:
    """자연어 한 줄을 (장소·대상·동사) 로 해석한다. 3요소 미충족이면 None.

    None 은 "모르겠다"가 아니라 **"추측해서 실행하지 않는다"** 는 뜻이다
    (CLAUDE.md §0.2). 호출부는 None 을 받으면 문법을 안내하고 멈춰야 한다.
    """
    if not isinstance(message, str) or not message.strip():
        return None
    raw = message.strip()

    # F-NL5 — 위험 동사가 섞여 있으면 통째로 거부(슬래시 명령 전용).
    if _DANGEROUS_RE.search(raw):
        return None

    found_locus = _find_locus(raw)
    if found_locus is None:
        return None
    locus, rest = found_locus

    # 장소 수식어("공식 채용페이지에서")는 대상이 아니므로 걷어낸다.
    rest = _LOCUS_MODIFIER_RE.sub(" ", rest)

    found_verb = _find_verb(rest)
    if found_verb is None:
        return None
    verb, target_part = found_verb

    route = _route_for(locus, verb)
    if route is None:
        # 어휘는 맞지만 계약된 동작이 없다 — 임의로 다른 스킬에 태우지 않는다.
        return None

    target = " ".join(target_part.split())
    # 대상이 필요 없는 경로가 있다 — 계약의 resolver 가 "none" 인 것(예: queue 조회).
    # `큐 보여줘` 에는 해소할 대상이 아예 없으므로 3요소 규칙을 여기에만 완화한다.
    # 판정 근거는 코드 상수가 아니라 계약 필드다(드리프트 0).
    if not target and route.get("resolver") != "none":
        return None

    return NlCommand(locus=locus, target=target, verb=verb, route=route, raw=raw)


@dataclass(frozen=True)
class Candidate:
    """해소 후보 하나 — 사람이 고를 이름 + 실제 대상 URL."""

    name: str
    url: str


@dataclass(frozen=True)
class Resolution:
    """해소 결과. `may_execute` 가 False 면 호출부는 **절대** 실행하면 안 된다."""

    status: str  # zero | one | many | error
    may_execute: bool
    url: str = ""
    candidates: tuple[Candidate, ...] = ()
    truncated: int = 0  # 상한을 넘어 잘라낸 후보 수 — 숨기지 않는다
    error: str = ""


def policy_for(status: str) -> dict[str, Any]:
    """계약의 resolution_policy 를 status 이름으로 읽는다(숫자·플래그 하드코딩 금지)."""
    key = {"zero": "zero_hits", "one": "one_hit", "many": "many_hits"}[status]
    return load_contract()["resolution_policy"][key]


def resolve(command: NlCommand, searcher) -> Resolution:
    """대상 이름을 실제 URL 로 해소한다. 정책은 전부 계약(SOT-32 §4)에서 읽는다.

    ``searcher(locus, target) -> list[Candidate]`` 를 주입받는다 — 이 함수는 검색
    수단을 모른다(ClickUp API·웹검색은 호출부 소관). 그래서 정책만 순수하게 시험된다.

    핵심 불변식:
      - 0건 → 실행 금지. **다른 장소로 임의 확장하지 않는다**(E-NL2). 검색은 지정된
        locus 로 딱 한 번만 호출한다.
      - N건 → 실행 금지. 고를 수 있게 후보를 돌려주고, 상한을 넘겨 잘랐다면 그 수를
        `truncated` 로 드러낸다(조용한 절삭 금지).
      - 검색기 예외 → `error`. **0건으로 둔갑시키지 않는다** — "못 찾았다"와 "못 물어봤다"는
        전혀 다른 사실이고, 후자를 전자로 보고하면 사장님이 헛물을 켠다.
    """
    # 해소가 필요 없는 경로(queue 조회 등) — 검색기를 아예 부르지 않는다.
    if command.route.get("resolver") == "none":
        return Resolution(status="one", may_execute=True)

    try:
        found = list(searcher(command.locus, command.target))
    except Exception as exc:  # 검색 실패를 성공(0건)으로 위장하지 않는다
        return Resolution(status="error", may_execute=False, error=str(exc))

    if not found:
        return Resolution(status="zero",
                          may_execute=bool(policy_for("zero")["may_execute"]))
    if len(found) == 1:
        return Resolution(status="one",
                          may_execute=bool(policy_for("one")["may_execute"]),
                          url=found[0].url,
                          candidates=(found[0],))

    cap = int(policy_for("many")["max_choices"])
    return Resolution(status="many",
                      may_execute=bool(policy_for("many")["may_execute"]),
                      candidates=tuple(found[:cap]),
                      truncated=max(0, len(found) - cap))


def badge_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """자연어 셸 컨텍스트 표식을 붙인 env 사본.

    `.claude/hooks/guards/nl-shell-routing.py` 가 이 스위치가 켜졌을 때만 문을 건다.
    AC-N0 의 V1 적대검증에서 "가드는 만들었는데 아무도 안 켠다"가 드러났고(SOT-32 §7.1),
    이 함수가 그 스위치다. 원본 dict 는 건드리지 않는다.
    """
    import os

    env = dict(os.environ if base is None else base)
    env[BADGE_ENV_KEY] = "1"
    return env
