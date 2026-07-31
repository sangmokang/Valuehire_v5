"""Windows에서 관리 Chrome 프로세스를 코드가 직접 판정하기 위한 순수 함수 모음.

goal: docs/engineering/managed-chrome-discovery-cross-os-goal-2026-07-31.md

여기에는 브라우저를 여는 기능도, 창을 닫는 기능도 없다. 읽기 전용 조회 1회와
문자열 판정만 한다. 조회 실패는 빈 목록으로 흡수하지 않고 고정 상태 코드로
보존한다 — 모델이 그 공백을 추측으로 메우지 못하게 하기 위해서다.
"""
from __future__ import annotations

import json
import ntpath
import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Any

# 상태 코드 → 사장님께 보여줄 고정 문구. 모델이 다시 쓰지 못하도록 코드가 소유한다.
MANAGED_BROWSER_STATUS_MESSAGES: dict[str, str] = {
    "AUTHENTICATED": "이미 로그인된 전용 크롬을 그대로 씁니다. 조작 없이 검색으로 넘어갑니다.",
    "NO_MANAGED_BROWSER": "이 컴퓨터에서 밸류하이어 전용 크롬을 찾지 못했습니다. 검색을 시작하지 않습니다.",
    "AMBIGUOUS_MANAGED_BROWSER": "전용 크롬이 두 개 이상이라 어느 것도 고르지 않았습니다.",
    "NO_OFFICIAL_TARGET": "전용 크롬에 공식 링크드인 탤런트 화면이 없습니다.",
    "AMBIGUOUS_OFFICIAL_TARGET": "공식 화면이 여러 브라우저에 있어 선택하지 않았습니다.",
    "HUMAN_AUTH": "본인확인·보안 화면입니다. 사장님이 직접 처리해 주셔야 합니다. 검색은 하지 않았습니다.",
    "UNSUPPORTED_OS": "지원하지 않는 컴퓨터 환경입니다.",
    "BROWSER_QUERY_FAILED": "브라우저 조회 명령이 실패했습니다. 추측하지 않고 멈춥니다.",
}


class ManagedBrowserDiscoveryError(LookupError):
    """발견 단계의 명시적 중단. ``code``는 위 표의 키 하나다."""

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in MANAGED_BROWSER_STATUS_MESSAGES:
            raise ValueError(f"unknown managed browser status code: {code!r}")
        self.code = code
        self.owner_message = MANAGED_BROWSER_STATUS_MESSAGES[code]
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class WindowsChromeProcess:
    """루트 Chrome 하나가 선언한 (pid, 디버깅 포트, 프로필 경로)."""

    pid: int
    port: int
    profile_path: str


# 고정 인자 배열. 사용자 입력을 여기에 끼워 넣지 않는다(주입 차단).
_WINDOWS_PROCESS_QUERY_ARGV: tuple[str, ...] = (
    "powershell.exe",
    "-NoProfile",
    "-NonInteractive",
    "-Command",
    "& { Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" "
    "| Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress }",
)

_MANAGED_EXECUTABLE_BASENAMES = frozenset({
    "chrome.exe",
    "chromium.exe",
    "chrome",
    "chromium",
})

# 등록된 기기·채널 프로필의 루트 폴더 이름(%LOCALAPPDATA%\Valuehire\...).
MANAGED_PROFILE_ROOT_NAME = "valuehire"


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def parse_windows_command_line(command_line: str) -> list[str]:
    """``Win32_Process.CommandLine``을 셸 없이 argv로 나눈다.

    ``shlex``는 쓸 수 없다 — 토큰 중간에서 시작하는 따옴표
    (``--user-data-dir="C:\\Users\\Kang Sang Mo\\..."``)를 공백에서 잘라
    프로필 경로를 두 조각으로 만든다(2026-07-31 RED 반례). 그래서 Windows의
    ``CommandLineToArgvW`` 규칙(따옴표 토글, 역슬래시는 따옴표 앞에서만 escape)을
    그대로 구현한다.
    """
    argv: list[str] = []
    current: list[str] = []
    started = False
    in_quotes = False
    pending_backslashes = 0
    for character in str(command_line or ""):
        if character == "\\":
            pending_backslashes += 1
            started = True
            continue
        if character == '"':
            current.append("\\" * (pending_backslashes // 2))
            if pending_backslashes % 2 == 1:
                current.append('"')  # \" 는 literal 따옴표.
            else:
                in_quotes = not in_quotes
            pending_backslashes = 0
            started = True
            continue
        current.append("\\" * pending_backslashes)
        pending_backslashes = 0
        if character in " \t" and not in_quotes:
            if started:
                argv.append("".join(current))
                current = []
                started = False
            continue
        current.append(character)
        started = True
    current.append("\\" * pending_backslashes)
    if started or current:
        token = "".join(current)
        if token or started:
            argv.append(token)
    return argv


def windows_chrome_options(argv: list[str]) -> dict[str, list[str | None]]:
    """argv에서 ``--flag[=value]``를 이름별 다중값으로 모은다(중복 보존)."""
    options: dict[str, list[str | None]] = {}
    index = 1
    while index < len(argv):
        item = argv[index]
        if not item.startswith("--"):
            index += 1
            continue
        name, separator, value = item[2:].partition("=")
        if separator:
            options.setdefault(name, []).append(_unquote(value))
        else:
            following: str | None = None
            if index + 1 < len(argv) and not argv[index + 1].startswith("--"):
                index += 1
                following = _unquote(argv[index])
            options.setdefault(name, []).append(following)
        index += 1
    return options


def is_managed_windows_executable(token: str) -> bool:
    """argv[0]이 Chrome 실행 파일 하나인지 본다(경로 길이·대소문자 무관)."""
    value = _unquote(token)
    if not value:
        return False
    basename = ntpath.basename(value.replace("/", "\\")) or value
    return basename.casefold() in _MANAGED_EXECUTABLE_BASENAMES


def normalize_windows_profile(profile: str) -> str:
    """Windows 규칙(대소문자·구분자)으로 정규화한 비교용 경로."""
    return ntpath.normcase(ntpath.normpath(_unquote(profile)))


def _profile_parts(profile: str) -> tuple[str, ...]:
    return tuple(
        part.casefold()
        for part in PureWindowsPath(profile).parts
        if part not in {"\\", "/"}
    )


def is_registered_windows_profile(
    profile: str,
    channel_token: str = "",
    *,
    local_app_data: str = "",
) -> bool:
    """등록된 기기·채널 프로필 경계 안인지 판정한다.

    ``%LOCALAPPDATA%\\Valuehire`` 아래여야 하고, 채널을 지정하면 그 채널 폴더여야
    한다. ``Valuehire2`` 같은 접두사만 같은 폴더는 경로 조각이 정확히 일치하지
    않으므로 탈락한다. ``local_app_data``를 주면 그 실제 폴더 아래인지까지 본다
    (없으면 ``...\\AppData\\Local\\Valuehire`` 조각 순서로 대체 판정).
    """
    value = _unquote(profile)
    if not value or not PureWindowsPath(value).is_absolute():
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    parts = _profile_parts(value)
    if any(part in {".", ".."} for part in parts):
        return False
    if MANAGED_PROFILE_ROOT_NAME not in parts:
        return False
    root = _unquote(local_app_data)
    if root:
        expected = normalize_windows_profile(
            ntpath.join(root, MANAGED_PROFILE_ROOT_NAME)
        )
        current = normalize_windows_profile(value)
        if not current.startswith(expected + ntpath.sep):
            return False
    else:
        index = parts.index(MANAGED_PROFILE_ROOT_NAME)
        if parts[max(0, index - 2):index] != ("appdata", "local"):
            return False
    if not channel_token:
        return True
    token = channel_token.casefold()
    return any(part == token or part.startswith(token + "-") for part in parts)


def is_valid_debug_port(value: str | None) -> bool:
    text = str(value or "").strip()
    return bool(text.isascii() and text.isdigit() and 1 <= int(text) <= 65535)


def query_windows_chrome_processes(
    *, runner: Callable[..., Any] | None = None
) -> list[Mapping[str, Any]]:
    """PowerShell 읽기 전용 조회 1회. 실패는 ``BROWSER_QUERY_FAILED``로 보존한다."""
    run = runner or subprocess.run
    try:
        result = run(
            list(_WINDOWS_PROCESS_QUERY_ARGV),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:  # 실행 자체 실패도 후보 0개로 흡수하지 않는다.
        raise ManagedBrowserDiscoveryError(
            "BROWSER_QUERY_FAILED", "windows process query did not run"
        ) from exc
    if int(getattr(result, "returncode", 1)) != 0:
        raise ManagedBrowserDiscoveryError(
            "BROWSER_QUERY_FAILED", "windows process query returned non-zero"
        )
    stdout = str(getattr(result, "stdout", "") or "").strip()
    if not stdout:
        return []
    try:
        payload = json.loads(stdout)
    except ValueError as exc:
        raise ManagedBrowserDiscoveryError(
            "BROWSER_QUERY_FAILED", "windows process query returned invalid JSON"
        ) from exc
    if isinstance(payload, Mapping):
        return [payload]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    raise ManagedBrowserDiscoveryError(
        "BROWSER_QUERY_FAILED", "windows process query payload was not a process list"
    )


def list_managed_windows_chrome_processes(
    *,
    channel_token: str = "",
    port: int | None = None,
    runner: Callable[..., Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> list[WindowsChromeProcess]:
    """등록 프로필로 뜬 루트 Chrome만 돌려준다(자식·개인 프로필·모호 인자 제외)."""
    source = os.environ if env is None else env
    local_app_data = str(source.get("LOCALAPPDATA") or "").strip()
    processes: list[WindowsChromeProcess] = []
    for row in query_windows_chrome_processes(runner=runner):
        try:
            pid = int(row.get("ProcessId"))
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        argv = parse_windows_command_line(str(row.get("CommandLine") or ""))
        if not argv or not is_managed_windows_executable(argv[0]):
            continue
        options = windows_chrome_options(argv)
        if "type" in options:  # 렌더러·GPU 등 자식 프로세스.
            continue
        ports = options.get("remote-debugging-port", [])
        profiles = options.get("user-data-dir", [])
        if len(ports) != 1 or len(profiles) != 1:
            continue
        if not is_valid_debug_port(ports[0]):
            continue
        profile = str(profiles[0] or "").strip()
        if not is_registered_windows_profile(
            profile, channel_token, local_app_data=local_app_data
        ):
            continue
        declared_port = int(str(ports[0]).strip())
        if port is not None and declared_port != int(port):
            continue
        processes.append(WindowsChromeProcess(pid, declared_port, profile))
    return processes
