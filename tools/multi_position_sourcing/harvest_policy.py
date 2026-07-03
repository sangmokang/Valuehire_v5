"""저수지 모델 — 3머신 멀티사이트 Harvest 정책 (단계 2).

머신·로그인 정책(사이트 전담 고정 폐기):
- 맥북·맥미니·맥에어 3대 모두 사람인·잡코리아에 로그인한다. 한 머신이 한 사이트 전담이 아니라
  셋 다 두 사이트를 돈다(부하만 분산). 가동 시작 우선순위는 맥미니부터.
- 사장님 Chrome 점유가 감지되면 그 머신 무인 워커 즉시 정지(R4). 비는 시간에만 무인 Harvest.
- LinkedIn RPS 시프트: 사장님 재석(낮~밤)=맥북 유인, 퇴근 후=맥미니 야간. 동시에 두 머신이 같은
  RPS 세션에 로그인하지 않는다(세션 충돌 방지).

순수 결정론 함수다. SOT 불변식(3사 자동로그인 안 막음 · R4 · Send 자동발송 금지)을 약화하지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from .models import Channel

# 가동 시작 우선순위 순서(맥미니 먼저).
HARVEST_MACHINES: tuple[str, ...] = ("macmini", "macbook", "macair")
# 모든 머신이 도는 두 사이트(전담 없음).
HARVEST_SITES: tuple[Channel, ...] = ("saramin", "jobkorea")


def startup_priority() -> tuple[str, ...]:
    """가동 시작 우선순위(맥미니 먼저)."""
    return HARVEST_MACHINES


def sites_for_machine(machine: str) -> tuple[Channel, ...]:
    """머신이 도는 사이트. 전담 고정이 없으므로 셋 다 사람인+잡코리아."""
    return HARVEST_SITES


def worker_should_yield(*, owner_activity_detected: bool) -> bool:
    """R4 — 사장님 Chrome 점유가 감지된 머신의 무인 워커는 즉시 양보(정지)한다."""
    return bool(owner_activity_detected)


def linkedin_rps_operator(*, owner_present: bool) -> str:
    """LinkedIn RPS 시프트 — 사장님 재석=맥북(유인), 퇴근 후=맥미니(야간)."""
    return "macbook" if owner_present else "macmini"


def rps_session_conflict(operators: Iterable[str]) -> bool:
    """동시에 서로 다른 두 머신 이상이 RPS 세션을 점유하면 충돌(금지)."""
    return len({operator for operator in operators}) > 1


# ── 봇방지 페이싱 primitive (PC-E1) ────────────────────────────────────
# 무인 라이브 루프가 봇처럼 굴지 않도록(SOT2 — URL 연타·알람 후 무한재시도 구조적 차단) 페이싱을
# 결정론 순수함수로 제공한다. delay 상수는 docs/sot/22 에서 읽어 이중정의를 막는다(SOT5 단일 출처).
# 이 primitive 는 PC-B5·C3·D2a·F4a 가 재사용한다 — 채널마다 제각각 재구현 금지.

_SOT22_PATH = Path(__file__).resolve().parents[2] / "docs" / "sot" / "22-talent-search-filters.json"

_PACING_KIND_KEY = {
    "between_keywords": "random_delay_between_keywords_ms",  # SOT22: RPS 키워드 간 20~60초
    "short": "short_delay_ms",  # SOT22: 짧은 대기 2~5초
}


@lru_cache(maxsize=1)
def _bot_protection() -> dict:
    """SOT22 의 linkedin.bot_protection 블록(단일 출처)."""
    data = json.loads(_SOT22_PATH.read_text(encoding="utf-8"))
    return data["channels"]["linkedin"]["bot_protection"]


def pacing_bounds_ms(kind: str) -> tuple[int, int]:
    """SOT22 에서 delay 경계 [min,max](ms)를 읽는다 — 하드코딩 이중정의 금지(SOT5)."""
    try:
        key = _PACING_KIND_KEY[kind]
    except KeyError:
        raise ValueError(f"unknown pacing kind: {kind!r}")
    band = _bot_protection()[key]
    return int(band["min"]), int(band["max"])


def _mix(seed: int, step: int) -> int:
    """결정론 지터용 32-bit 정수 믹서. Python hash() 랜덤화에 의존하지 않아 실행 간 재현된다."""
    x = ((int(seed) & 0xFFFFFFFF) * 2654435761 + (int(step) & 0xFFFFFFFF) * 40503 + 0x9E3779B1) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x85EBCA6B) & 0xFFFFFFFF
    x ^= x >> 13
    return x & 0xFFFFFFFF


def deterministic_delay_ms(*, kind: str, step: int, seed: int) -> int:
    """[min,max] 안의 결정론 지터 delay(ms). 같은 (kind,step,seed) → 같은 값.

    고정 간격은 봇 탐지 신호이므로 step 마다 값을 흩되(지터), 재현성을 위해 결정론으로 만든다.
    라이브 호출부는 seed 를 run_id 해시 등으로 주입해 사람처럼 불규칙하게 편다.
    """
    lo, hi = pacing_bounds_ms(kind)
    span = hi - lo
    if span <= 0:
        return lo
    return lo + _mix(seed, step) % (span + 1)


def max_keyword_steps() -> int:
    """무한재시도 방지 캡 — SOT22 keyword_limit_per_run(단일 출처)."""
    return int(_bot_protection()["keyword_limit_per_run"])


def should_continue_pacing(*, step: int, max_steps: int | None = None) -> bool:
    """step 이 캡 미만이면 계속(True), 캡 도달/초과면 정지(False).

    알람 후 같은 시도를 무한 반복하거나 URL 을 연타하는 봇 행동을 구조적으로 차단한다(SOT2).
    """
    cap = max_keyword_steps() if max_steps is None else int(max_steps)
    return int(step) < cap
