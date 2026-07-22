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
