"""WinPC managed-browser and exact-target login runtime contract."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing import browser_evidence, portal_worker, session_guard
from tools.multi_position_sourcing.winpc_portal_browser import _StartLease, winpc_environment


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


def test_winpc_environment_discards_legacy_global_endpoint(tmp_path: Path) -> None:
    env = winpc_environment(
        {
            "LOCALAPPDATA": str(tmp_path),
            "VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT": "http://127.0.0.1:9222",
        }
    )

    assert "VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT" not in env
    assert portal_worker.resolve_channel_cdp_endpoint("saramin", env=env).endswith(":9423")


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


def test_windows_raw_directory_lease_release_can_retry_after_transient_failure(
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
    lock = portal_worker.ProfileLock(config)
    portal_worker._ensure_real_profile_dir(config)
    lock._acquire_raw_lease_windows()
    original_rmdir = Path.rmdir
    original_rename = portal_worker.os.rename
    rmdir_attempts = 0
    rename_attempts = 0

    def transient_rmdir(path: Path) -> None:
        nonlocal rmdir_attempts
        if path == config.lock_path and rmdir_attempts == 0:
            rmdir_attempts += 1
            raise PermissionError("transient Windows scanner handle")
        original_rmdir(path)

    def transient_rename(source: object, target: object) -> None:
        nonlocal rename_attempts
        if Path(source) == lock._raw_owner_path and rename_attempts == 0:
            rename_attempts += 1
            raise PermissionError("transient Windows reader handle")
        original_rename(source, target)

    monkeypatch.setattr(Path, "rmdir", transient_rmdir)
    monkeypatch.setattr(portal_worker.os, "rename", transient_rename)
    lock._release_raw_lease_windows()

    assert rename_attempts == 1
    assert rmdir_attempts == 1
    assert not config.lock_path.exists()


def test_browser_start_lease_is_process_locked_and_reusable(tmp_path: Path) -> None:
    path = tmp_path / "start-saramin.lock"

    with _StartLease(path):
        with pytest.raises(RuntimeError, match="already in progress"):
            with _StartLease(path):
                pass

    with _StartLease(path):
        assert path.is_file()


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


def test_browser_evidence_low_level_io_preserves_windows_binary_bytes(
    tmp_path: Path,
) -> None:
    payload = b"\x89PNG\r\n\x1a\nbinary\npayload\x00\xff"
    target = tmp_path / "evidence.bin"

    browser_evidence._write_private(target, payload)

    assert browser_evidence._read_private_regular(target, len(payload)) == payload
