"""PC-F1 — owner-activity detector 순수모듈.

R4(양보·자동재개)의 코드강제. 무인 워커가 사장님과 같은 머신을 다투지 않도록 지금 양보할지(yield)를
결정한다. 판정 신호는 **앞창 앱 이름 + OS idle + (크롬 앞창일 때) 활성 탭 URL의 호스트**뿐이다 —
페이지 내용·키입력·쿠키·전체 URL 경로는 절대 보지도 기록하지도 않는다(SOT1 최소화).

2026-07-20 사장님 지시(SOT29 INV9 개정, goal: docs/engineering/owner-yield-60s-portal-scope-goal-2026-07-20.md):
  - 양보는 사장님이 **3사 포털(사람인·잡코리아·링크드인)을 만질 때만** 발동한다.
    유튜브 등 다른 화면 사용 중에는 idle 과 무관하게 양보하지 않는다.
  - 임계 180초 → **60초**. 3사를 만지던 중이라도 마지막 입력 후 60초면 자동 재개(로그인 포함).

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
from urllib.parse import urlsplit

RunCommand = Callable[..., subprocess.CompletedProcess[str]]

CHROME_APP_NAMES = frozenset(
    {
        "Google Chrome",
        "Google Chrome Canary",
        "Chromium",
    }
)
DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS = 60.0
# 사장님 개입으로 인정하는 3사 포털 도메인(서브도메인 포함 정확 매칭 — 유사 위장 호스트 배제).
PORTAL_HOSTS = ("saramin.co.kr", "jobkorea.co.kr", "linkedin.com")


@dataclass(frozen=True)
class OwnerActivitySnapshot:
    owner_activity_detected: bool
    foreground_app: str = ""
    idle_seconds: float | None = None
    detection_status: str = "ok"
    # True=크롬 활성 탭이 3사 포털 / False=포털 아님(다른 앱·유튜브 등) / None=판독 불가
    portal_site_active: bool | None = None
    # 프라이버시: 호스트만 기록(경로·쿼리·전체 URL 비기록)
    active_tab_host: str = ""


def compute_yield_decision(
    *,
    frontmost_is_chrome: bool,
    os_idle_seconds: float | None,
    idle_threshold_seconds: float = DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
    portal_site_active: bool | None = None,
) -> bool:
    """순수 결정: 무인 워커가 지금 양보(yield)해야 하는가? (True=양보, False=재개)

    - 2026-07-20 사장님 지시: ``portal_site_active=False``(3사 포털을 만지지 않음이 확정)면
      idle 과 무관하게 **재개(False)** — 유튜브 시청 등은 개입이 아니다.
    - ``portal_site_active=True``(3사 화면) 또는 ``None``(판독 불가)이면 idle 기준으로 판정:
      idle < threshold(60초) → 양보, idle >= threshold → 재개. 판독 불가여도 최대 60초 유계다.
    - idle 을 읽지 못하면(None) 판단 불가 → fail-closed 양보(True). 단 포털 아님이 확정이면 재개.
    - ``frontmost_is_chrome`` 은 호환용 관측 파라미터다(포털 판정은 snapshot 쪽에서 수행).
    """
    del frontmost_is_chrome  # 판정은 portal_site_active + idle. 시그니처는 호환 유지.
    if portal_site_active is False:
        return False
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


def _macos_active_chrome_tab_host(
    foreground_app: str, run_command: RunCommand = subprocess.run
) -> str | None:
    """앞창 크롬의 활성 탭 URL 에서 **호스트만** 추출한다. 실패는 None(판독 불가).

    전체 URL·경로·쿼리는 반환·기록하지 않는다(SOT1 최소화 — 3사 여부 판정에 호스트만 필요).
    """
    result = _run_text(
        [
            "osascript",
            "-e",
            f'tell application "{foreground_app}" to get URL of active tab of front window',
        ],
        run_command,
    )
    if result.returncode != 0:
        return None
    url = (result.stdout or "").strip()
    if not url:
        return None
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    return host or None


def _is_portal_host(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in PORTAL_HOSTS)


def detect_owner_activity_snapshot(
    *,
    idle_threshold_seconds: float = DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
    run_command: RunCommand = subprocess.run,
    system_name: str | None = None,
) -> OwnerActivitySnapshot:
    """앞창 앱·OS idle·(크롬이면) 활성 탭 호스트를 읽어 ``compute_yield_decision`` 에 위임한다.

    - 앞창이 크롬이 아니면 3사 개입 아님(portal_site_active=False) → 양보하지 않는다.
    - 앞창이 크롬이면 활성 탭 호스트로 3사 여부를 판정한다. 판독 실패는 None(60초 유계 양보).
    - 앞창/idle 자체를 못 읽으면 기존대로 fail-closed 양보(사장님을 앞지르지 않는다).
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

    frontmost_is_chrome = foreground_app in CHROME_APP_NAMES
    portal_site_active: bool | None
    active_tab_host = ""
    if not frontmost_is_chrome:
        portal_site_active = False
    else:
        try:
            host = _macos_active_chrome_tab_host(foreground_app, run_command)
        except Exception:
            host = None
        if host is None:
            portal_site_active = None
        else:
            portal_site_active = _is_portal_host(host)
            active_tab_host = host

    detected = compute_yield_decision(
        frontmost_is_chrome=frontmost_is_chrome,
        os_idle_seconds=idle_seconds,
        idle_threshold_seconds=idle_threshold_seconds,
        portal_site_active=portal_site_active,
    )
    return OwnerActivitySnapshot(
        owner_activity_detected=detected,
        foreground_app=foreground_app,
        idle_seconds=idle_seconds,
        portal_site_active=portal_site_active,
        active_tab_host=active_tab_host,
    )


def detect_owner_activity(**kwargs: Any) -> bool:
    return detect_owner_activity_snapshot(**kwargs).owner_activity_detected
