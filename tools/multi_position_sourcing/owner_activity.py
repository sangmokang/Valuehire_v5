"""PC-F1 — owner-activity detector 순수모듈.

R4(양보·자동재개)의 첫 코드강제. 무인 워커가 사장님과 같은 머신을 다투지 않도록, **앞창 앱 이름과
OS idle 시간만** 읽어 지금 양보할지(yield)를 결정한다. 키입력·브라우저 내용·URL·쿠키·창 텍스트는
절대 보지 않는다(SOT1). 감지 실패/불가는 fail-closed = 양보(사장님을 앞지르지 않는다, SOT2).

결정 규칙은 순수함수 ``compute_yield_decision`` 하나로 모았다(OS 읽기와 분리 → 결정론 테스트).
``detect_owner_activity_snapshot`` 은 OS 신호를 읽어 이 순수계약에 위임한다(로직 중복 없음).
이 모듈은 브라우저 스택(Playwright/raw CDP)에 결합하지 않는다 — 소비측은 harvest_policy의
``worker_should_yield(owner_activity_detected=...)`` 계약으로만 연결한다(라이브 배선은 PC-F2).
"""

from __future__ import annotations

import platform
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

RunCommand = Callable[..., subprocess.CompletedProcess[str]]

CHROME_APP_NAMES = frozenset(
    {
        "Google Chrome",
        "Google Chrome Canary",
        "Chromium",
    }
)
DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS = 180.0


@dataclass(frozen=True)
class OwnerActivitySnapshot:
    owner_activity_detected: bool
    foreground_app: str = ""
    idle_seconds: float | None = None
    detection_status: str = "ok"


def compute_yield_decision(
    *,
    frontmost_is_chrome: bool,
    os_idle_seconds: float | None,
    idle_threshold_seconds: float = DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
) -> bool:
    """순수 결정: 무인 워커가 지금 양보(yield)해야 하는가? (True=양보, False=재개)

    - 크롬이 앞창이면 사장님이 크롬을 쓰는 중으로 보고 idle 과 무관하게 양보(True).
    - 크롬이 앞창이 아니면 OS idle 로 판단: 최근 활동(idle<threshold)이면 양보(True),
      오래 자리를 비웠으면(idle>=threshold) 재개(False).
    - idle 을 읽지 못하면(None) 판단 불가 → fail-closed 양보(True). 사장님을 앞지르지 않는다.
    """
    if frontmost_is_chrome:
        return True
    if os_idle_seconds is None:
        return True
    return os_idle_seconds < idle_threshold_seconds


def _run_text(argv: list[str], run_command: RunCommand) -> subprocess.CompletedProcess[str]:
    return run_command(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def _macos_frontmost_app(run_command: RunCommand = subprocess.run) -> str | None:
    result = _run_text(
        [
            "osascript",
            "-e",
            'tell application "System Events" to get name of first application process whose frontmost is true',
        ],
        run_command,
    )
    if result.returncode != 0:
        return None
    app = (result.stdout or "").strip()
    return app or None


def _macos_idle_seconds(run_command: RunCommand = subprocess.run) -> float | None:
    result = _run_text(["ioreg", "-c", "IOHIDSystem"], run_command)
    if result.returncode != 0:
        return None
    match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', result.stdout or "")
    if not match:
        return None
    return int(match.group(1)) / 1_000_000_000


def detect_owner_activity_snapshot(
    *,
    idle_threshold_seconds: float = DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
    run_command: RunCommand = subprocess.run,
    system_name: str | None = None,
) -> OwnerActivitySnapshot:
    """앞창 앱 이름과 OS idle 을 읽어 ``compute_yield_decision`` 으로 양보 여부를 낸다.

    읽는 신호는 앞창 앱 이름과 idle 시간뿐이다(키입력·브라우저 내용 미열람). 감지 실패는 fail-closed:
    무인 워커는 사장님과 경쟁하기보다 양보한다.
    """
    system = system_name or platform.system()
    if system != "Darwin":
        return OwnerActivitySnapshot(
            owner_activity_detected=True,
            detection_status=f"unsupported_platform:{system or 'unknown'}",
        )

    try:
        foreground_app = _macos_frontmost_app(run_command)
        idle_seconds = _macos_idle_seconds(run_command)
    except Exception:
        return OwnerActivitySnapshot(owner_activity_detected=True, detection_status="detector_error")

    if foreground_app is None or idle_seconds is None:
        return OwnerActivitySnapshot(
            owner_activity_detected=True,
            foreground_app=foreground_app or "",
            idle_seconds=idle_seconds,
            detection_status="detector_unavailable",
        )

    detected = compute_yield_decision(
        frontmost_is_chrome=foreground_app in CHROME_APP_NAMES,
        os_idle_seconds=idle_seconds,
        idle_threshold_seconds=idle_threshold_seconds,
    )
    return OwnerActivitySnapshot(
        owner_activity_detected=detected,
        foreground_app=foreground_app,
        idle_seconds=idle_seconds,
    )


def detect_owner_activity(**kwargs: Any) -> bool:
    return detect_owner_activity_snapshot(**kwargs).owner_activity_detected
