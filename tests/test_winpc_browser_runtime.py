"""WinPC managed-browser and exact-target login runtime contract."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing import portal_worker, session_guard


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self._payload


def test_windows_managed_endpoint_uses_configured_port_without_unix_launcher() -> None:
    seen: list[str] = []

    def urlopen(url: str, timeout: float = 0) -> _Response:
        seen.append(url)
        assert timeout > 0
        return _Response(
            {"webSocketDebuggerUrl": "ws://127.0.0.1:9423/devtools/browser/abc"}
        )

    endpoint = portal_worker.resolve_managed_channel_cdp_endpoint(
        "saramin",
        system_name="Windows",
        env={"SARAMIN_PORT": "9423"},
        urlopen=urlopen,
    )

    assert endpoint == "http://127.0.0.1:9423"
    assert seen == ["http://127.0.0.1:9423/json/version"]


def test_windows_managed_process_binds_exact_port_and_profile() -> None:
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "ProcessId": 3210,
                        "CommandLine": (
                            '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
                            "--remote-debugging-port=9423 "
                            '--user-data-dir="C:\\Users\\DELL\\AppData\\Local\\Valuehire'
                            '\\portal_profiles\\sm002\\saramin"'
                        ),
                    },
                    {
                        "ProcessId": 3211,
                        "CommandLine": (
                            '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
                            "--type=renderer --remote-debugging-port=9423"
                        ),
                    },
                ]
            ),
            stderr="",
        )

    process = session_guard.resolve_managed_browser_process(
        "saramin",
        "http://127.0.0.1:9423",
        runner=runner,
        system_name="Windows",
    )

    assert process.browser_pid == 3210
    assert process.profile_path.endswith(r"\Valuehire\portal_profiles\sm002\saramin")
    assert calls and calls[0][0].lower().endswith("powershell.exe")


def test_windows_raw_directory_lease_is_atomic_and_owner_checked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        portal_worker,
        "RAW_SINGLE_TARGET_LOCK_ROOT",
        tmp_path / "browser_locks",
    )
    config = portal_worker.PortalWorkerConfig(
        channel="saramin",
        worker_id="default",
        profile_root=tmp_path / "profiles",
        mode="headed",
        connection_mode="raw_single_tab",
    )
    first = portal_worker.ProfileLock(config)
    second = portal_worker.ProfileLock(config)

    portal_worker._ensure_real_profile_dir(config)
    first._acquire_raw_lease_windows()
    try:
        first._assert_raw_lease_owned_windows()
        with pytest.raises(portal_worker.ProfileLockError, match="already locked"):
            second._acquire_raw_lease_windows()
    finally:
        first._release_raw_lease_windows()

    assert not config.lock_path.exists()


def test_windows_credentials_come_from_process_environment_not_macos_keychain() -> None:
    credentials = session_guard._load_runtime_login_credentials(
        "saramin",
        system_name="Windows",
        environ={
            "SARAMIN_USERNAME": "portal-user",
            "SARAMIN_PASSWORD": "portal-password",
        },
    )

    assert credentials == ("portal-user", "portal-password")


def test_owner_explicit_winpc_autologin_bypasses_only_initial_idle_gate() -> None:
    class Lease:
        acquired = False

        def acquire(self):
            self.acquired = True

        def release(self):
            self.acquired = False

    lease = Lease()
    ref = session_guard.BrowserTargetRef(
        site="saramin",
        endpoint="http://127.0.0.1:9423",
        target_id="target-1",
        websocket_url="ws://127.0.0.1:9423/devtools/page/target-1",
        initial_url="https://www.saramin.co.kr/zf_user/auth?ut=c",
        profile_path=r"C:\Valuehire\saramin",
        browser_pid=100,
    )

    class Tab:
        def close(self):
            return None

    result = session_guard.run_auto_login_episode(
        "saramin",
        agent="Codex",
        owner_explicit_local=True,
        system_name="Windows",
        environ={"VALUEHIRE_MACHINE": "winpc"},
        _credential_provider=SimpleNamespace(
            load=lambda _site: SimpleNamespace(
                username="portal-user",
                password="portal-password",
            )
        ),
        _lease_factory=lambda _site: lease,
        _target_resolver=lambda *_args, **_kwargs: ref,
        _tab_attacher=lambda *_args, **_kwargs: Tab(),
        _autologin=lambda _tab, _site, _creds: {
            "state": "AUTHENTICATED",
            "mutations": 1,
        },
    )

    assert result["state"] == "AUTHENTICATED"
    assert result["host"] == "winpc"
    assert result["target_id"] == "target-1"

