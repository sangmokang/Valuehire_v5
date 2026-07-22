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


# 감지 서브프로세스 상한(초) — osascript/ioreg 가 멈춰도 감지가 무기한 hang 하지 않게(V1 HIGH2).
DETECTOR_SUBPROCESS_TIMEOUT_SECONDS = 5.0


def _run_text(argv: list[str], run_command: RunCommand) -> subprocess.CompletedProcess[str]:
    return run_command(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=DETECTOR_SUBPROCESS_TIMEOUT_SECONDS,
    )


def _macos_frontmost_app_and_pid(
    run_command: RunCommand = subprocess.run,
) -> tuple[str | None, int | None]:
    """앞창 앱 이름과 unix pid. 이름만 오는 구형 응답도 허용(pid=None)."""
    result = _run_text(
        [
            "osascript",
            "-e",
            'tell application "System Events" to get {name, unix id} of first application process whose frontmost is true',
        ],
        run_command,
    )
    if result.returncode == 0:
        raw = (result.stdout or "").strip()
        if raw:
            name, _, tail = raw.rpartition(", ")
            if name and tail.isdigit():
                return name, int(tail)
            return raw, None

    # Some macOS/System Events combinations reject the record expression above
    # (-1728) while the two scalar, read-only queries both work.  Falling back to
    # those queries preserves the same signals without inspecting page content or
    # weakening the fail-closed rule: either missing name still returns unknown,
    # and a missing PID merely disables PID-bound CDP inspection.
    name_result = _run_text(
        [
            "osascript",
            "-e",
            'tell application "System Events" to get name of first application process whose frontmost is true',
        ],
        run_command,
    )
    if name_result.returncode != 0 or not (name_result.stdout or "").strip():
        return None, None
    pid_result = _run_text(
        [
            "osascript",
            "-e",
            'tell application "System Events" to get unix id of first application process whose frontmost is true',
        ],
        run_command,
    )
    pid_raw = (pid_result.stdout or "").strip() if pid_result.returncode == 0 else ""
    return (name_result.stdout or "").strip(), int(pid_raw) if pid_raw.isdigit() else None


def _macos_frontmost_app(run_command: RunCommand = subprocess.run) -> str | None:
    return _macos_frontmost_app_and_pid(run_command)[0]


_DEBUG_PORT_RE = re.compile(r"--remote-debugging-port=(\d+)")


def _chrome_debug_port_for_pid(pid: int, run_command: RunCommand = subprocess.run) -> int | None:
    """앞창 크롬 프로세스의 CDP 포트 — 창과 인스턴스를 PID 로 1:1 결합(V1 2차 MED)."""
    result = _run_text(["ps", "-p", str(pid), "-o", "command="], run_command)
    if result.returncode != 0:
        return None
    match = _DEBUG_PORT_RE.search(result.stdout or "")
    return int(match.group(1)) if match else None


def _chrome_root_instance_count(run_command: RunCommand = subprocess.run) -> int | None:
    """크롬 루트 프로세스(헬퍼 --type= 제외) 수. 2개+면 AppleScript 응답 인스턴스 보장 불가."""
    result = _run_text(["ps", "-axo", "command="], run_command)
    if result.returncode != 0:
        return None
    count = 0
    for line in (result.stdout or "").splitlines():
        if "--type=" in line:
            continue
        if any(marker in line for marker in ("Google Chrome", "Chromium")):
            count += 1
    return count


def _default_fetch_json(url: str) -> Any:
    import json as _json
    from urllib.request import urlopen

    with urlopen(url, timeout=DETECTOR_SUBPROCESS_TIMEOUT_SECONDS) as resp:  # noqa: S310 — 127.0.0.1 고정
        return _json.load(resp)


def _host_from_url(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    return host or None


def _cdp_portal_state(port: int, fetch_json: Callable[[str], Any]) -> tuple[bool | None, str]:
    """(portal_state, host) — /json/list 는 활성 탭 순서를 보장하지 않는다(V1 3차 MED).

    - 첫 page 가 3사 → (True, host): 최상단 후보가 포털이므로 개입 가능으로 본다.
    - 어떤 page 도 3사 아님 → (False, 첫 page host): 그 인스턴스에 포털 탭 자체가 없어
      포털 개입이 불가능 — False 확정 안전.
    - 첫 page 는 비포털인데 뒤에 포털 page 존재 → (None, ""): 활성 탭 미보장 → 60초 유계.
    - 조회/파싱 실패 → (None, "").
    """
    try:
        tabs = fetch_json(f"http://127.0.0.1:{port}/json/list")
    except Exception:
        return None, ""
    if not isinstance(tabs, list):
        return None, ""
    page_hosts: list[str | None] = [
        _host_from_url(str(tab.get("url") or ""))
        for tab in tabs
        if isinstance(tab, dict) and tab.get("type") == "page"
    ]
    if not page_hosts:
        return None, ""
    first = page_hosts[0]
    if first is not None and _is_portal_host(first):
        return True, first
    if any(host is not None and _is_portal_host(host) for host in page_hosts[1:]):
        return None, ""
    if first is None:
        return None, ""
    return False, first


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
    # http(s) 외 스킴(javascript:/file: 등)은 포털 확정에 쓰지 않는다(V1 MED4) → None(60초 유계).
    return _host_from_url(url)


def _is_portal_host(host: str) -> bool:
    return any(host == d or host.endswith("." + d) for d in PORTAL_HOSTS)


def _windows_idle_from_ticks(tick_count: int, last_input_tick: int) -> float:
    """GetTickCount(DWORD, 49.7일 wrap)와 dwTime 의 32비트 모듈러 경과초.

    ctypes 기본 반환형(C int, signed)과 wrap 을 모두 32비트 마스크로 정규화한다(V1 3차 HIGH).
    """
    elapsed_ms = ((tick_count & 0xFFFFFFFF) - (last_input_tick & 0xFFFFFFFF)) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


def _windows_idle_seconds() -> float | None:
    """Windows GetLastInputInfo 기반 idle 초. 실패는 None(fail-closed)."""
    try:
        import ctypes

        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):  # type: ignore[attr-defined]
            return None
        get_tick = ctypes.windll.kernel32.GetTickCount  # type: ignore[attr-defined]
        get_tick.restype = ctypes.c_uint32  # DWORD — signed 해석 금지(V1 3차 HIGH)
        return _windows_idle_from_ticks(int(get_tick()), int(info.dwTime))
    except Exception:
        return None


def detect_owner_activity_snapshot(
    *,
    idle_threshold_seconds: float = DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
    run_command: RunCommand = subprocess.run,
    system_name: str | None = None,
    fetch_json: Callable[[str], Any] | None = None,
    windows_idle_reader: Callable[[], float | None] | None = None,
) -> OwnerActivitySnapshot:
    """앞창 앱·OS idle·(크롬이면) 활성 탭 호스트를 읽어 ``compute_yield_decision`` 에 위임한다.

    - 앞창이 크롬이 아니면 3사 개입 아님(portal_site_active=False) → 양보하지 않는다.
    - 앞창이 크롬이면 활성 탭 호스트로 3사 여부를 판정한다. 판독 실패는 None(60초 유계 양보).
    - 앞창/idle 자체를 못 읽으면 기존대로 fail-closed 양보(사장님을 앞지르지 않는다).
    """
    system = system_name or platform.system()
    if system == "Windows":
        # winpc: 포털 축 감지 미지원 → portal=None(60초 유계). idle 단독 게이트(V1 2차 HIGH).
        reader = windows_idle_reader or _windows_idle_seconds
        try:
            win_idle = reader()
        except Exception:
            win_idle = None
        detected = compute_yield_decision(
            frontmost_is_chrome=False,
            os_idle_seconds=win_idle,
            idle_threshold_seconds=idle_threshold_seconds,
            portal_site_active=None,
        )
        return OwnerActivitySnapshot(
            owner_activity_detected=detected,
            idle_seconds=win_idle,
            detection_status="ok" if win_idle is not None else "detector_unavailable",
            portal_site_active=None,
        )
    if system != "Darwin":
        return OwnerActivitySnapshot(
            owner_activity_detected=True,
            detection_status=f"unsupported_platform:{system or 'unknown'}",
        )

    try:
        foreground_app, foreground_pid = _macos_frontmost_app_and_pid(run_command)
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
        host: str | None = None
        try:
            # 1순위: 앞창 PID 의 CDP 포트로 그 인스턴스의 탭을 직접 읽는다(인스턴스 1:1 결합).
            port = (
                _chrome_debug_port_for_pid(foreground_pid, run_command)
                if foreground_pid is not None
                else None
            )
            if port is not None:
                portal_state, host = _cdp_portal_state(port, fetch_json or _default_fetch_json)
                if host is None:
                    host = ""
                portal_site_active = portal_state
                active_tab_host = host if portal_state is not None else ""
                detected = compute_yield_decision(
                    frontmost_is_chrome=True,
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
            else:
                # 2순위: CDP 포트가 없으면 크롬 루트가 1개일 때만 AppleScript 를 신뢰한다.
                # 2개+면 어느 인스턴스가 응답할지 보장 불가 → None(60초 유계, False 확정 금지).
                roots = _chrome_root_instance_count(run_command)
                if roots is not None and roots <= 1:
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
