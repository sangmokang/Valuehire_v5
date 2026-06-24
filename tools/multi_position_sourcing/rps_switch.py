"""LinkedIn RPS 수동 점유 스위치.

LinkedIn Recruiter(RPS)는 한 계정 = 한 브라우저 세션만 허용한다. 사장님이 다른 PC에서
RPS 를 직접 쓰는 동안 이 맥의 자동화가 같은 계정에 attach 하면 세션 충돌/보안 체크포인트가
난다. RPS 사용 시간이 들쭉날쭉하므로 시간표가 아니라 **수동 스위치**로 양보한다.

스위치는 플래그 파일 하나로 표현한다(있으면 ON = 사장님이 RPS 쓰는 중 → 자동화는 linkedin_rps
큐 항목을 건너뛴다). 사람인·잡코리아는 영향받지 않는다. 켜고 끄기는 ``scripts/rps_switch.sh``.

설계 원칙(SOT 불변식 1·2):
- linkedin_rps 만 양보, 다른 채널은 계속(전체 정지 아님).
- ``plan_queue_cycle`` 은 부수효과 없는 순수 게이트이므로 파일 I/O 를 하지 않는다 —
  스위치 상태(불리언)를 주입받는다. 파일 읽기는 이 모듈이 담당한다.
"""

from __future__ import annotations

import os
from pathlib import Path

# 플래그 파일 경로 override(사장님이 위치를 바꾸면 env 로 지정).
RPS_FLAG_ENV = "VALUEHIRE_RPS_IN_USE_FLAG"
# 기본 위치: 포털 프로필과 같은 ~/.valuehire 아래(상주 데몬·런처와 한 곳).
DEFAULT_RPS_FLAG_PATH: Path = Path.home() / ".valuehire" / "rps_in_use.flag"


def default_rps_flag_path() -> Path:
    """스위치 플래그 파일 경로(env override > 기본)."""
    override = os.environ.get(RPS_FLAG_ENV)
    return Path(override) if override else DEFAULT_RPS_FLAG_PATH


def rps_in_use_from_flag(path: Path | str | None = None) -> bool:
    """플래그 파일이 있으면 ON(True). 경로 미지정 시 기본 경로를 본다.

    파일 접근 자체가 실패하면(권한 등) 보수적으로 OFF(False) — 자동화를 막지 않되,
    충돌이 의심되면 사장님이 명시적으로 스위치를 켜는 쪽이 안전 기본값이다.
    """
    flag_path = Path(path) if path is not None else default_rps_flag_path()
    try:
        return flag_path.exists()
    except OSError:
        return False


def rps_in_use() -> bool:
    """현재 RPS 점유 스위치 상태(기본 경로 기준). 라이브 큐 호출부 배선용."""
    return rps_in_use_from_flag(default_rps_flag_path())


def rps_pause_reason() -> str:
    """linkedin_rps 항목을 양보(보류)할 때 큐에 남기는 사유(단일 출처)."""
    return "linkedin_rps paused by owner manual switch — resume when switch off"
