"""관리 브라우저 발견을 macOS·Windows 양쪽에서 코드가 직접 판정한다.

goal: docs/engineering/managed-chrome-discovery-cross-os-goal-2026-07-31.md

각 테스트는 goal §4 입력 영역 표의 한 행 이상에 대응한다. 모델이 브라우저를
추측하지 못하도록, 발견 실패는 빈 목록이 아니라 고정 상태 코드로 보존한다.
"""
from __future__ import annotations

import os
import platform
import subprocess
import unittest
from typing import Any
from unittest import mock

from tools.multi_position_sourcing import session_guard
from tools.multi_position_sourcing.portal_worker import (
    MANAGED_BROWSER_STATUS_MESSAGES,
    ManagedBrowserDiscoveryError,
    discover_local_chrome_cdp_endpoints,
    resolve_managed_channel_cdp_endpoint,
)
from tools.multi_position_sourcing.session_guard import resolve_managed_browser_process

CHROME = r'"C:\Program Files\Google\Chrome\Application\chrome.exe"'
REGISTERED_LINKEDIN = r"C:\Users\owner\AppData\Local\Valuehire\portal_profiles\sm002\linkedin"
REGISTERED_SARAMIN = r"C:\Users\owner\AppData\Local\Valuehire\portal_profiles\sm002\saramin"
PERSONAL = r"C:\Users\owner\AppData\Local\Google\Chrome\User Data"
TALENT_URL = "https://www.linkedin.com/talent/hire/1763661452/discover/recruiterSearch"


def win_process(pid: int, command_line: str) -> dict[str, Any]:
    return {"ProcessId": pid, "CommandLine": command_line}


def chrome_command(
    *, port: str | int, profile: str, extra: str = "", executable: str = CHROME
) -> str:
    return f'{executable} {extra} --remote-debugging-port={port} --user-data-dir="{profile}"'.replace(
        "  ", " "
    )


class FakeRunner:
    """PowerShell 조회만 흉내내는 러너. 호출 인자를 그대로 기록한다."""

    def __init__(self, payload: Any, *, returncode: int = 0, raw: str | None = None) -> None:
        self.payload = payload
        self.returncode = returncode
        self.raw = raw
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any):
        self.calls.append((args, kwargs))
        import json

        stdout = self.raw if self.raw is not None else json.dumps(self.payload)

        class Result:
            pass

        result = Result()
        result.returncode = self.returncode
        result.stdout = stdout
        result.stderr = ""
        return result

    @property
    def argv(self) -> list[str]:
        return list(self.calls[0][0][0])


# VH-SM-002(Windows PC1) 등록부가 선언한 프로필이 실제로 만들어지는 환경.
WIN_ENV = {
    "LOCALAPPDATA": r"C:\Users\owner\AppData\Local",
    "VALUEHIRE_SEARCH_MACHINE_ID": "VH-SM-002",
}


class RegisteredWindowsMachine(unittest.TestCase):
    """등록된 Windows 검색기(VH-SM-002)에서 실행되는 상황을 만든다."""

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, WIN_ENV, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)


def talent_tabs(port_suffix: str):
    def list_tabs(endpoint: str) -> list[dict]:
        if endpoint.endswith(port_suffix):
            return [
                {
                    "id": "recruiter-search",
                    "type": "page",
                    "url": TALENT_URL,
                    "webSocketDebuggerUrl": f"ws://127.0.0.1:{port_suffix}/devtools/page/recruiter-search",
                }
            ]
        return []

    return list_tabs


class WindowsDiscoveryTest(RegisteredWindowsMachine):
    """goal §4 행 2·5·7·8·9·10·11·13·20"""

    def test_finds_windows_chrome_with_real_port_and_registered_profile(self) -> None:
        """행 2 — chrome.exe + 실제 포트 + 등록 프로필을 찾는다."""
        runner = FakeRunner(
            [win_process(4242, chrome_command(port=9425, profile=REGISTERED_LINKEDIN))]
        )

        endpoints = discover_local_chrome_cdp_endpoints(
            channel="linkedin_rps", runner=runner, system_name="Windows"
        )

        self.assertEqual(endpoints, ["http://127.0.0.1:9425"])

    def test_windows_query_uses_fixed_argv_without_shell(self) -> None:
        """제약 — 고정 PowerShell 인자 배열, shell=False, 사용자 입력 미삽입."""
        runner = FakeRunner([])

        discover_local_chrome_cdp_endpoints(
            channel="linkedin_rps", runner=runner, system_name="Windows"
        )

        argv = runner.argv
        self.assertEqual(argv[0], "powershell.exe")
        self.assertIn("-NoProfile", argv)
        self.assertIn("-NonInteractive", argv)
        self.assertNotEqual(runner.calls[0][1].get("shell"), True)
        joined = " ".join(argv)
        self.assertNotIn("linkedin_rps", joined)
        self.assertNotIn("Valuehire", joined)

    def test_quoted_windows_path_with_spaces_is_read_exactly(self) -> None:
        """행 9 — 공백이 포함된 인용 경로를 정확히 해석한다."""
        spaced = r"C:\Users\Kang Sang Mo\AppData\Local\Valuehire\portal_profiles\sm002\linkedin"
        runner = FakeRunner([win_process(11, chrome_command(port=9425, profile=spaced))])

        endpoints = discover_local_chrome_cdp_endpoints(
            channel="linkedin_rps",
            runner=runner,
            system_name="Windows",
            env={**WIN_ENV, "LOCALAPPDATA": r"C:\Users\Kang Sang Mo\AppData\Local"},
        )

        self.assertEqual(endpoints, ["http://127.0.0.1:9425"])

    def test_renderer_and_gpu_children_are_excluded(self) -> None:
        """행 5 — 루트 1개와 자식 다수면 루트만 채택한다."""
        runner = FakeRunner(
            [
                win_process(1, chrome_command(port=9425, profile=REGISTERED_LINKEDIN)),
                win_process(
                    2,
                    chrome_command(
                        port=9425, profile=REGISTERED_LINKEDIN, extra="--type=renderer"
                    ),
                ),
                win_process(
                    3,
                    chrome_command(
                        port=9425, profile=REGISTERED_LINKEDIN, extra="--type=gpu-process"
                    ),
                ),
            ]
        )

        endpoints = discover_local_chrome_cdp_endpoints(
            channel="linkedin_rps", runner=runner, system_name="Windows"
        )

        self.assertEqual(endpoints, ["http://127.0.0.1:9425"])

    def test_personal_chrome_profile_is_excluded(self) -> None:
        """행 10 — 개인 Chrome 프로필은 후보가 아니다."""
        runner = FakeRunner([win_process(9, chrome_command(port=9425, profile=PERSONAL))])

        endpoints = discover_local_chrome_cdp_endpoints(
            channel="linkedin_rps", runner=runner, system_name="Windows"
        )

        self.assertEqual(endpoints, [])

    def test_lookalike_valuehire_root_is_excluded(self) -> None:
        """행 10 보강 — 접두사만 같은 폴더(Valuehire2)는 등록 경계가 아니다."""
        lookalike = r"C:\Users\owner\AppData\Local\Valuehire2\portal_profiles\sm002\linkedin"
        runner = FakeRunner([win_process(9, chrome_command(port=9425, profile=lookalike))])

        endpoints = discover_local_chrome_cdp_endpoints(
            channel="linkedin_rps", runner=runner, system_name="Windows"
        )

        self.assertEqual(endpoints, [])

    def test_valuehire_folder_outside_local_app_data_is_excluded(self) -> None:
        """행 10 보강 — 이름만 Valuehire인 다른 위치 폴더는 등록 경계가 아니다."""
        outside = r"D:\temp\Valuehire\linkedin"
        runner = FakeRunner([win_process(9, chrome_command(port=9425, profile=outside))])

        self.assertEqual(
            discover_local_chrome_cdp_endpoints(
                channel="linkedin_rps", runner=runner, system_name="Windows"
            ),
            [],
        )

    def test_registered_root_is_bound_to_local_app_data_when_declared(self) -> None:
        """행 10 보강 — LOCALAPPDATA가 있으면 그 실제 폴더 아래만 인정한다."""
        env = {"LOCALAPPDATA": r"C:\Users\owner\AppData\Local"}
        inside = FakeRunner(
            [win_process(9, chrome_command(port=9425, profile=REGISTERED_LINKEDIN))]
        )
        elsewhere = FakeRunner(
            [
                win_process(
                    9,
                    chrome_command(
                        port=9425,
                        profile=r"C:\Users\other\AppData\Local\Valuehire\portal_profiles\sm002\linkedin",
                    ),
                )
            ]
        )

        self.assertEqual(
            discover_local_chrome_cdp_endpoints(
                channel="linkedin_rps", runner=inside, system_name="Windows", env=env
            ),
            ["http://127.0.0.1:9425"],
        )
        self.assertEqual(
            discover_local_chrome_cdp_endpoints(
                channel="linkedin_rps", runner=elsewhere, system_name="Windows", env=env
            ),
            [],
        )

    def test_other_channel_profile_is_excluded(self) -> None:
        """행 11 — ValueHire 경로지만 다른 채널이면 제외한다."""
        runner = FakeRunner(
            [win_process(9, chrome_command(port=9423, profile=REGISTERED_SARAMIN))]
        )

        endpoints = discover_local_chrome_cdp_endpoints(
            channel="linkedin_rps", runner=runner, system_name="Windows"
        )

        self.assertEqual(endpoints, [])

    def test_duplicate_port_or_profile_flags_are_rejected(self) -> None:
        """행 7·8 — 포트·프로필 인자가 중복되면 그 프로세스를 거부한다."""
        duplicated_port = (
            f'{CHROME} --remote-debugging-port=9425 --remote-debugging-port=9426 '
            f'--user-data-dir="{REGISTERED_LINKEDIN}"'
        )
        duplicated_profile = (
            f'{CHROME} --remote-debugging-port=9425 '
            f'--user-data-dir="{REGISTERED_LINKEDIN}" --user-data-dir="{PERSONAL}"'
        )
        for command in (duplicated_port, duplicated_profile):
            with self.subTest(command=command[:60]):
                runner = FakeRunner([win_process(9, command)])
                self.assertEqual(
                    discover_local_chrome_cdp_endpoints(
                        channel="linkedin_rps", runner=runner, system_name="Windows"
                    ),
                    [],
                )

    def test_out_of_range_or_missing_port_is_rejected(self) -> None:
        """행 7 — 포트 누락·범위 오류는 후보가 아니다."""
        cases = (
            f'{CHROME} --user-data-dir="{REGISTERED_LINKEDIN}"',
            chrome_command(port=0, profile=REGISTERED_LINKEDIN),
            chrome_command(port=65536, profile=REGISTERED_LINKEDIN),
            chrome_command(port="９４２５", profile=REGISTERED_LINKEDIN),
        )
        for command in cases:
            with self.subTest(command=command[-40:]):
                runner = FakeRunner([win_process(9, command)])
                self.assertEqual(
                    discover_local_chrome_cdp_endpoints(
                        channel="linkedin_rps", runner=runner, system_name="Windows"
                    ),
                    [],
                )

    def test_relative_or_control_character_profile_is_rejected(self) -> None:
        """행 8 — 상대경로·제어문자 프로필은 거부한다."""
        cases = (
            r"portal_profiles\sm002\linkedin",
            r"C:\Users\owner\AppData\Local\Valuehire\..\Google\Chrome",
            "C:\\Users\\owner\\AppData\\Local\\Valuehire\\portal_profiles\\sm002\\link\x07edin",
        )
        for profile in cases:
            with self.subTest(profile=profile[-30:]):
                runner = FakeRunner(
                    [win_process(9, chrome_command(port=9425, profile=profile))]
                )
                self.assertEqual(
                    discover_local_chrome_cdp_endpoints(
                        channel="linkedin_rps", runner=runner, system_name="Windows"
                    ),
                    [],
                )

    def test_query_failure_is_a_fixed_status_not_an_empty_list(self) -> None:
        """행 20 — 조회 실패·잘못된 JSON은 고정 오류 코드로 중단한다."""
        failing = FakeRunner([], returncode=1)
        broken_json = FakeRunner(None, raw="{not json")

        for runner in (failing, broken_json):
            with self.subTest(runner=runner.returncode):
                with self.assertRaises(ManagedBrowserDiscoveryError) as caught:
                    discover_local_chrome_cdp_endpoints(
                        channel="linkedin_rps", runner=runner, system_name="Windows"
                    )
                self.assertEqual(caught.exception.code, "BROWSER_QUERY_FAILED")

    def test_launch_failure_on_windows_is_a_fixed_status(self) -> None:
        """행 20 — 조회 명령 자체가 실행되지 않아도 후보 0개로 흡수하지 않는다."""

        def exploding(*_args: Any, **_kwargs: Any):
            raise OSError("powershell not found")

        with self.assertRaises(ManagedBrowserDiscoveryError) as caught:
            discover_local_chrome_cdp_endpoints(
                channel="linkedin_rps", runner=exploding, system_name="Windows"
            )
        self.assertEqual(caught.exception.code, "BROWSER_QUERY_FAILED")

    def test_unsupported_operating_system_stops_with_fixed_status(self) -> None:
        """행 3 — 지원하지 않는 운영체제는 고정 상태 코드로 중단한다."""
        runner = FakeRunner([])

        with self.assertRaises(ManagedBrowserDiscoveryError) as caught:
            discover_local_chrome_cdp_endpoints(
                channel="linkedin_rps", runner=runner, system_name="Linux"
            )
        self.assertEqual(caught.exception.code, "UNSUPPORTED_OS")
        self.assertEqual(runner.calls, [])

    def test_single_process_is_returned_once_for_duplicate_endpoints(self) -> None:
        """행 4 대비 — 프로세스 0개면 빈 목록(정상 판정)이다."""
        runner = FakeRunner([])

        self.assertEqual(
            discover_local_chrome_cdp_endpoints(
                channel="linkedin_rps", runner=runner, system_name="Windows"
            ),
            [],
        )


class WindowsEndpointResolutionTest(RegisteredWindowsMachine):
    """goal §4 행 6·12·13·14·15·16"""

    def test_live_port_wins_over_configured_port(self) -> None:
        """행 12 — 설정 포트가 죽어도 살아 있는 실제 포트를 찾는다."""
        runner = FakeRunner(
            [win_process(4242, chrome_command(port=9427, profile=REGISTERED_LINKEDIN))]
        )

        endpoint = resolve_managed_channel_cdp_endpoint(
            "linkedin_rps",
            runner=runner,
            system_name="Windows",
            env={**WIN_ENV, "LINKEDIN_PORT": "9425"},
            list_tabs=talent_tabs("9427"),
        )

        self.assertEqual(endpoint, "http://127.0.0.1:9427")

    def test_windows_never_runs_the_unix_shell_launcher(self) -> None:
        """제약 — Windows에서는 ps·Bash·portal_browsers.sh를 실행하지 않는다."""
        runner = FakeRunner(
            [win_process(4242, chrome_command(port=9425, profile=REGISTERED_LINKEDIN))]
        )

        resolve_managed_channel_cdp_endpoint(
            "linkedin_rps",
            runner=runner,
            system_name="Windows",
            list_tabs=talent_tabs("9425"),
        )

        for args, _kwargs in runner.calls:
            argv = list(args[0])
            self.assertEqual(argv[0], "powershell.exe")
            self.assertFalse(any("portal_browsers.sh" in str(item) for item in argv))
            self.assertFalse(any(str(item) in {"ps", "bash", "sh"} for item in argv))

    def test_two_managed_browsers_select_nothing(self) -> None:
        """행 6·15 — 후보가 두 개면 어느 것도 선택하지 않는다."""
        runner = FakeRunner(
            [
                win_process(1, chrome_command(port=9425, profile=REGISTERED_LINKEDIN)),
                win_process(2, chrome_command(port=9427, profile=REGISTERED_LINKEDIN)),
            ]
        )

        def both_have_talent(endpoint: str) -> list[dict]:
            return [{"id": endpoint, "type": "page", "url": TALENT_URL}]

        with self.assertRaises(LookupError):
            resolve_managed_channel_cdp_endpoint(
                "linkedin_rps",
                runner=runner,
                system_name="Windows",
                list_tabs=both_have_talent,
            )

    def test_no_official_target_stops_before_search(self) -> None:
        """행 14·16 — 공식 Talent 화면이 없으면(룩얼라이크·일반 피드 포함) 중단한다."""
        runner = FakeRunner(
            [win_process(1, chrome_command(port=9425, profile=REGISTERED_LINKEDIN))]
        )

        def not_official(_endpoint: str) -> list[dict]:
            return [
                {"id": "a", "type": "page", "url": "https://www.linkedin.com/feed/"},
                {
                    "id": "b",
                    "type": "page",
                    "url": "https://www.linkedin.com.evil.io/talent/search",
                },
            ]

        with self.assertRaises(LookupError):
            resolve_managed_channel_cdp_endpoint(
                "linkedin_rps",
                runner=runner,
                system_name="Windows",
                list_tabs=not_official,
            )

    def test_non_local_debugging_address_is_refused(self) -> None:
        """행 13 — 로컬이 아닌 디버깅 주소는 거부한다."""
        runner = FakeRunner([])

        with self.assertRaises(LookupError):
            resolve_managed_channel_cdp_endpoint(
                "linkedin_rps",
                runner=runner,
                system_name="Windows",
                endpoint_discoverer=lambda: ["http://10.0.0.5:9425"],
                list_tabs=lambda _endpoint: [
                    {"id": "x", "type": "page", "url": TALENT_URL}
                ],
            )


class WindowsBrowserProcessBindingTest(RegisteredWindowsMachine):
    """goal §4 행 2·5·6 — endpoint를 하나의 루트 프로세스에 묶는다."""

    def test_binds_endpoint_to_single_windows_root_process(self) -> None:
        runner = FakeRunner(
            [
                win_process(4242, chrome_command(port=9425, profile=REGISTERED_LINKEDIN)),
                win_process(
                    4243,
                    chrome_command(
                        port=9425, profile=REGISTERED_LINKEDIN, extra="--type=renderer"
                    ),
                ),
            ]
        )

        process = resolve_managed_browser_process(
            "linkedin_rps",
            "http://127.0.0.1:9425",
            runner=runner,
            system_name="Windows",
        )

        self.assertEqual(process.browser_pid, 4242)
        self.assertEqual(process.profile_path, REGISTERED_LINKEDIN)

    def test_two_roots_on_same_port_fail_closed(self) -> None:
        runner = FakeRunner(
            [
                win_process(1, chrome_command(port=9425, profile=REGISTERED_LINKEDIN)),
                win_process(2, chrome_command(port=9425, profile=REGISTERED_LINKEDIN)),
            ]
        )

        with self.assertRaises(LookupError):
            resolve_managed_browser_process(
                "linkedin_rps",
                "http://127.0.0.1:9425",
                runner=runner,
                system_name="Windows",
            )

    def test_windows_binding_never_uses_ps_or_lsof(self) -> None:
        runner = FakeRunner(
            [win_process(4242, chrome_command(port=9425, profile=REGISTERED_LINKEDIN))]
        )

        resolve_managed_browser_process(
            "linkedin_rps",
            "http://127.0.0.1:9425",
            runner=runner,
            system_name="Windows",
        )

        for args, _kwargs in runner.calls:
            argv = list(args[0])
            self.assertNotIn(argv[0], {"ps", "lsof", "bash", "sh"})


class V1CounterExampleTest(RegisteredWindowsMachine):
    """Codex V1(2026-07-31) 적대검증이 재현한 반례. 모두 fail-closed 여야 한다."""

    def _endpoints(self, profile: str, *, env: dict | None = None) -> list[str]:
        runner = FakeRunner([win_process(9, chrome_command(port=9425, profile=profile))])
        return discover_local_chrome_cdp_endpoints(
            channel="linkedin_rps",
            runner=runner,
            system_name="Windows",
            env={"LOCALAPPDATA": r"C:\Users\owner\AppData\Local"} if env is None else env,
        )

    def test_decoy_folder_under_another_channel_is_refused(self) -> None:
        """V1-F1 — 다른 채널 폴더 아래 linkedin-decoy 는 등록 프로필이 아니다."""
        decoy = r"C:\Users\owner\AppData\Local\Valuehire\portal_profiles\sm002\saramin\linkedin-decoy"
        self.assertEqual(self._endpoints(decoy), [])

    def test_remote_unc_profile_is_refused(self) -> None:
        """V1-F1 — 원격 UNC 경로는 이 컴퓨터의 등록 프로필이 아니다."""
        unc = r"\\server\share\AppData\Local\Valuehire\portal_profiles\sm002\linkedin"
        self.assertEqual(self._endpoints(unc), [])

    def test_nested_duplicate_valuehire_segment_is_refused(self) -> None:
        """V1-F1 — Valuehire 조각이 두 번 나오는 경로도 등록값과 다르면 거부한다."""
        nested = r"C:\Users\owner\AppData\Local\Valuehire\x\Valuehire\linkedin"
        self.assertEqual(self._endpoints(nested), [])

    def test_single_quoted_value_is_not_silently_rewritten(self) -> None:
        """V1-F7 — Windows에서 의미 없는 작은따옴표를 벗겨 등록 경로로 바꾸지 않는다."""
        quoted = "'" + REGISTERED_LINKEDIN + "'"
        self.assertEqual(self._endpoints(quoted), [])

    def test_two_managed_roots_stop_even_when_only_one_shows_talent(self) -> None:
        """V1-F2 — 루트가 2개면 공식 화면이 한쪽에만 있어도 선택하지 않는다."""
        runner = FakeRunner(
            [
                win_process(1, chrome_command(port=9425, profile=REGISTERED_LINKEDIN)),
                win_process(2, chrome_command(port=9427, profile=REGISTERED_LINKEDIN)),
            ]
        )

        with self.assertRaises(ManagedBrowserDiscoveryError) as caught:
            resolve_managed_channel_cdp_endpoint(
                "linkedin_rps",
                runner=runner,
                system_name="Windows",
                list_tabs=talent_tabs("9425"),
            )
        self.assertEqual(caught.exception.code, "AMBIGUOUS_MANAGED_BROWSER")

    def test_each_failure_mode_carries_its_own_fixed_status_code(self) -> None:
        """V1-F4 — 후보 0개·공식화면 0개·공식화면 2개가 서로 다른 고정 코드로 멈춘다."""
        none_running = FakeRunner([])
        one_root = FakeRunner(
            [win_process(1, chrome_command(port=9425, profile=REGISTERED_LINKEDIN))]
        )

        with self.assertRaises(ManagedBrowserDiscoveryError) as no_browser:
            resolve_managed_channel_cdp_endpoint(
                "linkedin_rps",
                runner=none_running,
                system_name="Windows",
                list_tabs=lambda _e: [],
            )
        self.assertEqual(no_browser.exception.code, "NO_MANAGED_BROWSER")

        with self.assertRaises(ManagedBrowserDiscoveryError) as no_target:
            resolve_managed_channel_cdp_endpoint(
                "linkedin_rps",
                runner=one_root,
                system_name="Windows",
                list_tabs=lambda _e: [
                    {"id": "a", "type": "page", "url": "https://www.linkedin.com/feed/"}
                ],
            )
        self.assertEqual(no_target.exception.code, "NO_OFFICIAL_TARGET")

        with self.assertRaises(ManagedBrowserDiscoveryError) as two_browsers:
            resolve_managed_channel_cdp_endpoint(
                "linkedin_rps",
                runner=one_root,
                system_name="Windows",
                endpoint_discoverer=lambda: [
                    "http://127.0.0.1:9425",
                    "http://127.0.0.1:9427",
                ],
                list_tabs=lambda _e: [
                    {"id": "a", "type": "page", "url": TALENT_URL}
                ],
            )
        self.assertEqual(two_browsers.exception.code, "AMBIGUOUS_MANAGED_BROWSER")

        # 한 브라우저 안에 공식 화면이 여럿이면 별도 코드로 멈춘다(target id 미지정).
        with self.assertRaises(ManagedBrowserDiscoveryError) as ambiguous_target:
            session_guard.resolve_existing_target(
                "linkedin_rps",
                managed_endpoint_resolver=lambda _s: "http://127.0.0.1:9425",
                list_pages=lambda _e: [
                    {
                        "id": f"tab-{index}",
                        "type": "page",
                        "url": TALENT_URL,
                        "webSocketDebuggerUrl": (
                            f"ws://127.0.0.1:9425/devtools/page/tab-{index}"
                        ),
                    }
                    for index in (1, 2)
                ],
            )
        self.assertEqual(ambiguous_target.exception.code, "AMBIGUOUS_OFFICIAL_TARGET")

    def test_structurally_invalid_json_is_not_absorbed_as_empty(self) -> None:
        """V1-F5 — [1,2,3] 같은 구조 파손은 빈 목록이 아니라 조회 실패다."""
        runner = FakeRunner(None, raw="[1,2,3]")

        with self.assertRaises(ManagedBrowserDiscoveryError) as caught:
            discover_local_chrome_cdp_endpoints(
                channel="linkedin_rps", runner=runner, system_name="Windows"
            )
        self.assertEqual(caught.exception.code, "BROWSER_QUERY_FAILED")

    def test_child_process_without_type_flag_is_excluded_by_parent(self) -> None:
        """V1-F6 — --type 이 없어도 부모가 chrome 이면 루트로 채택하지 않는다."""
        rows = [
            {
                "ProcessId": 1,
                "ParentProcessId": 900,
                "CommandLine": chrome_command(port=9425, profile=REGISTERED_LINKEDIN),
            },
            {
                "ProcessId": 2,
                "ParentProcessId": 1,
                "CommandLine": chrome_command(port=9425, profile=REGISTERED_LINKEDIN),
            },
        ]
        runner = FakeRunner(rows)

        process = resolve_managed_browser_process(
            "linkedin_rps",
            "http://127.0.0.1:9425",
            runner=runner,
            system_name="Windows",
        )

        self.assertEqual(process.browser_pid, 1)

    def test_registered_profile_must_match_the_machine_registry_exactly(self) -> None:
        """V1-F1 근본 — 등록부(search_machine)의 값과 정확히 일치해야 한다."""
        from tools.multi_position_sourcing.search_machine import get_search_machine

        machine = get_search_machine("VH-SM-002")
        expected = machine.profile("linkedin").replace(
            "%LOCALAPPDATA%", r"C:\Users\owner\AppData\Local"
        )

        self.assertEqual(self._endpoints(expected), ["http://127.0.0.1:9425"])


class MacOsRegressionTest(unittest.TestCase):
    """goal §4 행 1 — 기존 macOS 성공·개인 Chrome 제외 동작이 유지된다."""

    def test_macos_root_discovery_still_reads_real_port(self) -> None:
        class PsResult:
            returncode = 0
            stderr = ""
            stdout = (
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
                "--remote-debugging-port=9338 "
                "--user-data-dir=/Users/test/.valuehire/cdp_profiles/linkedin-standby\n"
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
                "--type=renderer --remote-debugging-port=9338 "
                "--user-data-dir=/Users/test/.valuehire/cdp_profiles/linkedin-standby\n"
            )

        endpoints = discover_local_chrome_cdp_endpoints(
            runner=lambda *_a, **_k: PsResult(),
            system_name="Darwin",
            env={"HOME": "/Users/test"},
        )

        self.assertEqual(endpoints, ["http://127.0.0.1:9338"])

    def test_macos_personal_chrome_still_excluded(self) -> None:
        class PsResult:
            returncode = 0
            stderr = ""
            stdout = (
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
                "--remote-debugging-port=9448 "
                "--user-data-dir=/Users/test/Library/Application Support/Google/Chrome\n"
            )

        endpoints = discover_local_chrome_cdp_endpoints(
            channel="linkedin_rps",
            runner=lambda *_a, **_k: PsResult(),
            system_name="Darwin",
            env={"HOME": "/Users/test"},
        )

        self.assertEqual(endpoints, [])


class MacOsManagedBoundaryTest(unittest.TestCase):
    """행 10·11 의 macOS 대칭 — 이름 스침만으로 통과하던 구멍을 막는다.

    macOS는 등록부 정확일치를 걸 수 없다(라이브 브라우저가 ``-standby`` 처럼 등록
    이름과 다르게 떠 있는 것이 정상 — PR#249). 그래서 홈 경계·마지막 조각·다른 채널
    토큰 세 가지로 좁힌다.
    """

    CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    def _accepted(self, profile: str) -> bool:
        class PsResult:
            returncode = 0
            stderr = ""
            stdout = (
                f"{MacOsManagedBoundaryTest.CHROME} "
                f"--remote-debugging-port=9225 --user-data-dir={profile}\n"
            )

        return bool(
            discover_local_chrome_cdp_endpoints(
                channel="linkedin_rps",
                runner=lambda *_a, **_k: PsResult(),
                system_name="Darwin",
                env={"HOME": "/Users/x"},
            )
        )

    def test_live_standby_profile_stays_accepted(self) -> None:
        self.assertTrue(self._accepted("/Users/x/.valuehire/cdp_profiles/linkedin"))
        self.assertTrue(
            self._accepted("/Users/x/.valuehire/cdp_profiles/linkedin-standby")
        )

    def test_profile_outside_a_user_home_is_refused(self) -> None:
        for profile in (
            "/tmp/.valuehire/linkedin",
            "/Volumes/USB/.valuehire/linkedin",
            "/opt/.valuehire/linkedin",
        ):
            with self.subTest(profile=profile):
                self.assertFalse(self._accepted(profile))

    def test_decoy_under_another_channel_is_refused(self) -> None:
        self.assertFalse(
            self._accepted("/Users/x/.valuehire/portal_profiles/saramin/linkedin-decoy")
        )

    def test_channel_token_must_be_the_last_component(self) -> None:
        self.assertFalse(self._accepted("/Users/x/.valuehire/linkedin/cache"))


class V2CounterExampleTest(unittest.TestCase):
    """Claude V2(리셋 컨텍스트, 2026-07-31) 재검증이 잡은 3건."""

    def test_another_users_home_profile_is_refused(self) -> None:
        """V2-1 — 남의 계정 홈 아래 프로필은 이 기기의 관리 브라우저가 아니다."""

        class PsResult:
            returncode = 0
            stderr = ""
            stdout = (
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
                "--remote-debugging-port=9225 "
                "--user-data-dir=/Users/intruder/.valuehire/cdp_profiles/linkedin\n"
            )

        self.assertEqual(
            discover_local_chrome_cdp_endpoints(
                channel="linkedin_rps",
                runner=lambda *_a, **_k: PsResult(),
                system_name="Darwin",
                env={"HOME": "/Users/owner"},
            ),
            [],
        )

    def test_own_home_profile_is_still_accepted(self) -> None:
        """V2-1 회귀 방지 — 내 홈 아래 라이브 프로필은 그대로 채택된다."""

        class PsResult:
            returncode = 0
            stderr = ""
            stdout = (
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
                "--remote-debugging-port=9225 "
                "--user-data-dir=/Users/owner/.valuehire/cdp_profiles/linkedin-standby\n"
            )

        self.assertEqual(
            discover_local_chrome_cdp_endpoints(
                channel="linkedin_rps",
                runner=lambda *_a, **_k: PsResult(),
                system_name="Darwin",
                env={"HOME": "/Users/owner"},
            ),
            ["http://127.0.0.1:9225"],
        )

    def test_owner_message_reaches_the_humansearch_failure(self) -> None:
        """V2-2 — 고정 문구가 실제 사용자 경로까지 전달된다(뭉개지지 않는다)."""
        from tools.multi_position_sourcing import humansearch_cdp_run as runner_module

        def failing_resolver(_site: str, *, target_id: str | None = None):
            raise ManagedBrowserDiscoveryError("NO_MANAGED_BROWSER", "count was 0")

        with self.assertRaises(Exception) as caught:
            runner_module.resolve_exact_recruiter_target(
                target_id="x", target_resolver=failing_resolver
            )
        message = str(caught.exception)
        self.assertIn(MANAGED_BROWSER_STATUS_MESSAGES["NO_MANAGED_BROWSER"], message)
        self.assertEqual(
            getattr(caught.exception, "owner_status_code", None), "NO_MANAGED_BROWSER"
        )

    def test_no_status_code_is_unreachable(self) -> None:
        """V2-3 — 표의 8개 코드가 모두 실제 발생 지점을 가진다(고아 금지)."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "tools" / "multi_position_sourcing"
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in root.glob("*.py")
            if path.name != "windows_chrome.py"
        )
        table = (root / "windows_chrome.py").read_text(encoding="utf-8")
        producers = sources + table.split("MANAGED_BROWSER_STATUS_MESSAGES", 2)[-1]
        for code in MANAGED_BROWSER_STATUS_MESSAGES:
            with self.subTest(code=code):
                self.assertIn(
                    f'"{code}"',
                    producers,
                    f"{code} 는 표에만 있고 발생 지점이 없다(고아 코드)",
                )

    def test_authenticated_and_human_auth_carry_the_fixed_message(self) -> None:
        """V2-3 — AUTHENTICATED·HUMAN_AUTH 도 같은 표에서 문구를 가져온다."""
        from tools.multi_position_sourcing.portal_selfservice_login import (
            PortalCreds,
            perform_autologin,
        )

        class AlreadyLoggedIn:
            def eval(self, _script: str):
                return "Expand the user menu 강상모"

            def current_url(self) -> str:
                return TALENT_URL

            def navigate(self, _url: str):  # pragma: no cover - 호출되면 계약 위반
                raise AssertionError("이미 로그인된 화면에서 이동이 발생했다")

        result = perform_autologin(
            AlreadyLoggedIn(), "linkedin_rps", PortalCreds("id", "pw")
        )

        self.assertEqual(result["state"], "AUTHENTICATED")
        self.assertEqual(result["mutations"], 0)
        self.assertEqual(
            result.get("owner_message"),
            MANAGED_BROWSER_STATUS_MESSAGES["AUTHENTICATED"],
        )


class RealCallPathTest(RegisteredWindowsMachine):
    """실제 호출 경로 — resolve_existing_target과 humansearch 준비 경로."""

    def _install_windows_world(self, monkey: list, *, tab_url: str) -> FakeRunner:
        """OS 경계(프로세스 조회·플랫폼 이름·탭 목록)만 가짜로 바꾼다."""
        from tools.multi_position_sourcing import raw_cdp

        runner = FakeRunner(
            [win_process(4242, chrome_command(port=9425, profile=REGISTERED_LINKEDIN))]
        )
        page = {
            "id": "recruiter-search",
            "type": "page",
            "url": tab_url,
            "webSocketDebuggerUrl": "ws://127.0.0.1:9425/devtools/page/recruiter-search",
        }
        originals = {
            "run": subprocess.run,
            "system": platform.system,
            "list_pages": raw_cdp.list_pages,
        }
        subprocess.run = runner  # type: ignore[assignment]
        platform.system = lambda: "Windows"  # type: ignore[assignment]
        raw_cdp.list_pages = lambda endpoint: (  # type: ignore[assignment]
            [dict(page)] if endpoint == "http://127.0.0.1:9425" else []
        )
        monkey.append(lambda: setattr(subprocess, "run", originals["run"]))
        monkey.append(lambda: setattr(platform, "system", originals["system"]))
        monkey.append(lambda: setattr(raw_cdp, "list_pages", originals["list_pages"]))
        return runner

    def test_resolve_existing_target_invokes_windows_discovery(self) -> None:
        """필수검사 11 — resolve_existing_target에서 Windows 탐색기가 실제 호출된다."""
        undo: list = []
        runner = self._install_windows_world(undo, tab_url=TALENT_URL)
        try:
            ref = session_guard.resolve_existing_target(
                "linkedin_rps", target_id="recruiter-search"
            )
        finally:
            for restore in undo:
                restore()

        self.assertTrue(runner.calls, "Windows 조회기가 호출되지 않았다")
        self.assertEqual(runner.argv[0], "powershell.exe")
        self.assertEqual(ref.endpoint, "http://127.0.0.1:9425")
        self.assertEqual(ref.browser_pid, 4242)
        self.assertEqual(ref.profile_path, REGISTERED_LINKEDIN)

    def test_humansearch_preparation_consumes_authenticated_target(self) -> None:
        """필수검사 12·13 — humansearch 준비 경로가 무조작으로 다음 단계로 넘어간다."""
        from tools.multi_position_sourcing import humansearch_cdp_run as runner_module

        undo: list = []
        query_runner = self._install_windows_world(
            undo, tab_url=runner_module.SEARCH_URL_BASE
        )
        try:
            target = runner_module.resolve_exact_recruiter_target(
                target_id="recruiter-search"
            )
        finally:
            for restore in undo:
                restore()

        self.assertEqual(target["id"], "recruiter-search")
        self.assertEqual(target["_endpoint"], "http://127.0.0.1:9425")
        self.assertEqual(target["_profile_path"], REGISTERED_LINKEDIN)
        self.assertEqual(target["_browser_pid"], 4242)
        self.assertEqual(target["url"], runner_module.SEARCH_URL_BASE)
        # 필수검사 13 — 실행된 OS 명령은 읽기 전용 조회뿐이다(브라우저 실행·종료 0회).
        self.assertTrue(query_runner.calls)
        for args, kwargs in query_runner.calls:
            argv = [str(item) for item in args[0]]
            self.assertEqual(argv[0], "powershell.exe")
            self.assertNotIn("Start-Process", " ".join(argv))
            self.assertNotIn("Stop-Process", " ".join(argv))
            self.assertNotEqual(kwargs.get("shell"), True)


class AuthenticationPriorityTest(unittest.TestCase):
    """goal §4 행 17·18·19 — 챌린지·다중로그인이 인증 마커보다 우선한다."""

    def test_already_authenticated_talent_page_needs_zero_mutations(self) -> None:
        from tools.multi_position_sourcing.portal_selfservice_login import (
            decide_login_step,
        )

        step = decide_login_step(
            "linkedin_rps",
            "Expand the user menu 강상모",
            TALENT_URL,
        )

        self.assertEqual(step, "already_authenticated")

    def test_challenge_and_session_conflict_outrank_auth_marker(self) -> None:
        from tools.multi_position_sourcing.portal_selfservice_login import (
            decide_login_step,
        )

        challenge = decide_login_step(
            "linkedin_rps",
            "Expand the user menu 강상모 Let's do a quick security check",
            "https://www.linkedin.com/checkpoint/challenge/",
        )
        self.assertEqual(challenge, "security_challenge")


class FixedUserFacingMessageTest(unittest.TestCase):
    """제약 — 상태 코드→고정 문구 표를 코드가 소유한다(모델 재작성 금지)."""

    def test_every_status_code_has_one_fixed_korean_message(self) -> None:
        required = {
            "AUTHENTICATED",
            "NO_MANAGED_BROWSER",
            "AMBIGUOUS_MANAGED_BROWSER",
            "NO_OFFICIAL_TARGET",
            "AMBIGUOUS_OFFICIAL_TARGET",
            "HUMAN_AUTH",
            "UNSUPPORTED_OS",
            "BROWSER_QUERY_FAILED",
        }

        self.assertEqual(required, set(MANAGED_BROWSER_STATUS_MESSAGES))
        for code, message in MANAGED_BROWSER_STATUS_MESSAGES.items():
            with self.subTest(code=code):
                self.assertTrue(message.strip())
                self.assertRegex(message, r"[가-힣]")


class NoEnvironmentSpecificLiteralsTest(unittest.TestCase):
    """필수검사 14 — 사용자명·저장소 절대경로·고정 실제 포트를 코드에 넣지 않는다."""

    def test_implementation_files_have_no_machine_specific_literals(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        files = [
            root / "tools" / "multi_position_sourcing" / "portal_worker.py",
            root / "tools" / "multi_position_sourcing" / "session_guard.py",
            root / "tools" / "multi_position_sourcing" / "windows_chrome.py",
        ]
        for path in files:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("kangsangmo", text.casefold())
                self.assertNotIn("/volumes/ssd/", text.casefold())
                self.assertNotIn("c:\\users\\owner", text.casefold())


if __name__ == "__main__":
    unittest.main()
