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

from collections.abc import Iterable

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
