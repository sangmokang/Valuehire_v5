"""Visible managed portal browser launcher for owner-explicit WinPC runs."""

from __future__ import annotations

import json
import ntpath
import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping
from urllib import request as urllib_request
from urllib.parse import urlsplit

from .portal_worker import resolve_channel_cdp_endpoint
from .search_machine import get_search_machine
from .session_guard import (
    list_windows_managed_browser_processes,
    resolve_managed_browser_process,
)


WINPC_REGISTRY_ID = "VH-SM-002"
WINPC_ALIAS = "winpc"
_SITE_ENV = {
    "saramin": ("SARAMIN_PORT", "SARAMIN_PROFILE"),
    "jobkorea": ("JOBKOREA_PORT", "JOBKOREA_PROFILE"),
    "linkedin_rps": ("LINKEDIN_PORT", "LINKEDIN_PROFILE"),
}
_SITE_URL = {
    "saramin": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
    "jobkorea": "https://www.jobkorea.co.kr/Corp/Person/Find",
    "linkedin_rps": "https://www.linkedin.com/talent/home",
}
_WINDOWS_ENV_RE = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


@dataclass(frozen=True)
class ManagedBrowserState:
    site: str
    endpoint: str
    profile_path: str
    browser_pid: int
    started: bool
    shown: bool


def _expand_windows_env(value: str, environ: Mapping[str, str]) -> str:
    folded = {str(key).casefold(): str(item) for key, item in environ.items()}

    def replace(match: re.Match[str]) -> str:
        key = match.group(1).casefold()
        if key not in folded:
            raise RuntimeError(f"Windows environment variable is missing: {match.group(1)}")
        return folded[key]

    expanded = _WINDOWS_ENV_RE.sub(replace, value)
    if "%" in expanded or not PureWindowsPath(expanded).is_absolute():
        raise RuntimeError("managed Windows profile path is not absolute")
    if any(ord(character) < 32 or ord(character) == 127 for character in expanded):
        raise RuntimeError("managed Windows profile path contains control characters")
    return ntpath.normpath(expanded)


def winpc_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Materialize the registry's WinPC ports/profiles into one process environment."""

    source = dict(os.environ if environ is None else environ)
    # A legacy single-browser endpoint would override all channel-specific ports
    # in resolve_channel_cdp_endpoint.  WinPC owns one managed profile per portal,
    # so retaining it silently routes Saramin to the wrong browser.
    source.pop("VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT", None)
    machine = get_search_machine(WINPC_REGISTRY_ID)
    source.update(
        {
            "VALUEHIRE_MACHINE": WINPC_ALIAS,
            "VALUEHIRE_SEARCH_MACHINE_ID": machine.machine_id,
            "VALUEHIRE_SEARCH_MACHINE_LABEL": machine.label,
            "VALUEHIRE_SEARCH_MACHINE_ROLE": machine.role,
            "VALUEHIRE_SEARCH_MACHINE_OS": machine.os,
            "SARAMIN_PORT": str(machine.saramin_port),
            "JOBKOREA_PORT": str(machine.jobkorea_port),
            "LINKEDIN_PORT": str(machine.linkedin_port),
        }
    )
    for key, raw in (
        ("SARAMIN_PROFILE", machine.saramin_profile),
        ("JOBKOREA_PROFILE", machine.jobkorea_profile),
        ("LINKEDIN_PROFILE", machine.linkedin_profile),
    ):
        source[key] = _expand_windows_env(raw, source)
    return source


def find_chrome_executable(environ: Mapping[str, str] | None = None) -> Path:
    source = os.environ if environ is None else environ
    candidates = [
        str(source.get("PORTAL_CHROME") or "").strip(),
        str(Path(source.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(source.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(source.get("LOCALAPPDATA", ""))
            / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise FileNotFoundError("Google Chrome executable was not found")


def build_chrome_launch_args(
    executable: Path,
    *,
    port: int,
    profile_path: str,
    site: str,
) -> list[str]:
    if site not in _SITE_URL or not 1 <= int(port) <= 65_535:
        raise ValueError("invalid managed browser launch request")
    return [
        str(executable),
        f"--remote-debugging-port={int(port)}",
        f"--user-data-dir={profile_path}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        _SITE_URL[site],
    ]


def _endpoint_ready(
    endpoint: str,
    *,
    urlopen: Callable[..., Any] = urllib_request.urlopen,
) -> bool:
    try:
        with urlopen(f"{endpoint}/json/version", timeout=2.0) as response:
            payload = json.loads(response.read(65_537).decode("utf-8"))
        websocket = str(payload.get("webSocketDebuggerUrl") or "")
        parsed = urlsplit(websocket)
        return (
            parsed.scheme == "ws"
            and parsed.hostname in {"127.0.0.1", "localhost"}
            and parsed.port == urlsplit(endpoint).port
        )
    except Exception:
        return False


class _StartLease:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any | None = None

    def __enter__(self) -> "_StartLease":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError("managed browser start is already in progress") from exc
        self._handle = handle
        return self

    def __exit__(self, *_exc: object) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def bring_windows_process_to_front(browser_pid: int) -> bool:
    """Show the unique visible top-level window owned by the managed root PID."""

    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        windows: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) == int(browser_pid) and user32.IsWindowVisible(hwnd):
                windows.append(int(hwnd))
            return True

        user32.EnumWindows(callback_type(callback), 0)
        unique = list(dict.fromkeys(windows))
        if len(unique) != 1:
            return False
        hwnd = unique[0]
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        return False


def ensure_windows_portal_browser(
    site: str,
    *,
    environ: Mapping[str, str],
    system_name: str | None = None,
    process_runner: Callable[..., Any] = subprocess.run,
    popen: Callable[..., Any] = subprocess.Popen,
    urlopen: Callable[..., Any] = urllib_request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    timeout_seconds: float = 20.0,
) -> ManagedBrowserState:
    """Reuse one exact managed browser or start one visible owner-requested window."""

    if (system_name or platform.system()) != "Windows":
        raise RuntimeError("WinPC managed browser launcher requires Windows")
    if site not in _SITE_ENV:
        raise ValueError(f"unsupported portal site: {site!r}")
    port_key, profile_key = _SITE_ENV[site]
    port = int(str(environ.get(port_key) or "0"))
    profile = str(environ.get(profile_key) or "")
    if not PureWindowsPath(profile).is_absolute():
        raise RuntimeError("managed portal profile is not an absolute Windows path")
    endpoint = resolve_channel_cdp_endpoint(site, env=environ)

    def current_state(*, started: bool) -> ManagedBrowserState:
        process = resolve_managed_browser_process(
            site,
            endpoint,
            runner=process_runner,
            system_name="Windows",
        )
        if ntpath.normcase(ntpath.normpath(process.profile_path)) != ntpath.normcase(
            ntpath.normpath(profile)
        ):
            raise RuntimeError("managed browser profile does not match WinPC registry")
        return ManagedBrowserState(
            site=site,
            endpoint=endpoint,
            profile_path=profile,
            browser_pid=process.browser_pid,
            started=started,
            shown=bring_windows_process_to_front(process.browser_pid),
        )

    if _endpoint_ready(endpoint, urlopen=urlopen):
        return current_state(started=False)

    start_lock = Path.home() / ".valuehire" / "browser_locks" / f"start-{site}.lock"
    with _StartLease(start_lock):
        if _endpoint_ready(endpoint, urlopen=urlopen):
            return current_state(started=False)
        existing = list_windows_managed_browser_processes(
            port,
            expected_profile=profile,
            runner=process_runner,
        )
        if existing:
            # Chrome can briefly drop the debugging listener while the first-run
            # profile finishes initialization.  The exact process/profile still
            # owns the slot, so wait the full bounded startup window and never
            # create a duplicate browser.
            deadline = time.monotonic() + float(timeout_seconds)
            while time.monotonic() < deadline:
                if _endpoint_ready(endpoint, urlopen=urlopen):
                    return current_state(started=False)
                sleep(0.25)
            raise RuntimeError("managed browser process exists but its local endpoint is unavailable")

        profile_path = Path(profile)
        profile_path.mkdir(parents=True, exist_ok=True)
        executable = find_chrome_executable(environ)
        args = build_chrome_launch_args(
            executable,
            port=port,
            profile_path=profile,
            site=site,
        )
        popen(
            args,
            cwd=str(executable.parent),
            env=dict(environ),
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        deadline = time.monotonic() + float(timeout_seconds)
        while time.monotonic() < deadline:
            if _endpoint_ready(endpoint, urlopen=urlopen):
                return current_state(started=True)
            sleep(0.25)
    raise RuntimeError("managed browser did not expose its local endpoint in time")
