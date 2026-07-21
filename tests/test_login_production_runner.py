"""Production wiring for exact-target HUMAN_AUTH and safe keepalive."""
from __future__ import annotations

import errno
import json
import os
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing import portal_worker
from tools.multi_position_sourcing.session_guard import (
    AuthObservation,
    BrowserTargetRef,
    LoginWindowLocator,
    SafeKeepaliveTarget,
    main,
    run_human_auth_episode,
    run_safe_keepalive_episode,
)
from tools.multi_position_sourcing.portal_worker import (
    PortalWorkerConfig,
    ProfileLock,
    ProfileLockError,
)


def _ref() -> BrowserTargetRef:
    return BrowserTargetRef(
        site="linkedin_rps",
        endpoint="http://127.0.0.1:9225",
        target_id="target-exact",
        websocket_url="ws://127.0.0.1:9225/devtools/page/target-exact",
        initial_url="https://www.linkedin.com/talent/home",
        profile_path="/tmp/linkedin-profile",
        browser_pid=4321,
    )


def _target() -> SafeKeepaliveTarget:
    return SafeKeepaliveTarget(
        target_id="target-exact",
        source_url="https://www.linkedin.com/talent/home",
        selector='a[href="https://www.linkedin.com/talent/projects"]',
        destination_url="https://www.linkedin.com/talent/projects",
        method="GET",
        target_attr="_self",
        dedicated_tab=True,
        clean_form=True,
        previously_opened_free=True,
    )


class _Lease:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.owned = False

    def acquire(self) -> None:
        self.trace.append("lease.acquire")
        self.owned = True

    def assert_owned(self) -> None:
        self.trace.append("lease.assert")
        if not self.owned:
            raise RuntimeError("lease lost")

    def release(self) -> None:
        self.trace.append("lease.release")
        self.owned = False


class _Tab:
    target_id = "target-exact"

    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    def disconnect(self) -> bool:
        self.trace.append("tab.disconnect")
        return True

    def close(self) -> None:
        raise AssertionError("runner must never call tab.close()")

    def mark_busy(self, label: str, *, expected_url: str) -> bool:
        self.trace.append(f"tab.mark_busy:{expected_url}")
        return bool(label)

    def send(self, method: str, _params: dict | None = None) -> dict:
        if method.startswith(("Storage.", "Network.getCookies")):
            raise AssertionError("runner must never inspect cookies")
        if method == "Page.getFrameTree":
            return {
                "frameTree": {
                    "frame": {
                        "id": "main-frame",
                        "loaderId": "loader-1",
                        "url": "https://www.linkedin.com/talent/home",
                    }
                }
            }
        raise AssertionError(method)


def _increasing_owner(trace: list[str]):
    idle = 179.0

    def snapshot() -> SimpleNamespace:
        nonlocal idle
        idle += 1.0
        trace.append(f"owner:{idle:.0f}")
        return SimpleNamespace(
            owner_activity_detected=False,
            idle_seconds=idle,
            detection_status="ok",
        )

    return snapshot


def _unauthenticated(_tab: object, _site: str) -> AuthObservation:
    return AuthObservation(
        authenticated=False,
        challenge=False,
        url="https://www.linkedin.com/login",
        proof_names=(),
    )


def _authenticated(_tab: object, _site: str) -> AuthObservation:
    return AuthObservation(
        authenticated=True,
        challenge=False,
        url="https://www.linkedin.com/talent/home",
        proof_names=("talent_surface", "recruiter_account"),
    )


def test_human_auth_runner_holds_lease_emits_locator_and_disconnects_only() -> None:
    trace: list[str] = []
    emitted: list[dict[str, object]] = []
    lease = _Lease(trace)
    tab = _Tab(trace)

    def resolver(site: str, *, target_id: str | None) -> BrowserTargetRef:
        trace.append(f"resolve:{site}:{target_id}")
        assert lease.owned
        return _ref()

    def attach(target: dict[str, object], *, badge: bool) -> _Tab:
        trace.append(f"attach:{target['id']}:{badge}")
        assert lease.owned
        return tab

    def present(
        current: _Tab,
        ref: BrowserTargetRef,
        *,
        agent: str,
        mutation_gate,
        episode_id: str,
    ) -> LoginWindowLocator:
        trace.append(f"present:{agent}:{episode_id != ''}")
        mutation_gate()
        return LoginWindowLocator(
            agent=agent,
            site=ref.site,
            browser_pid=ref.browser_pid,
            profile_path=ref.profile_path,
            cdp_endpoint=ref.endpoint,
            target_id_suffix="get-exact",
            sanitized_title="[LOGIN HERE][Codex][linkedin][get-exact] LinkedIn RPS login",
            sanitized_url="https://www.linkedin.com/login",
            cg_window_id=180,
            screenshot_sha256="a" * 64,
            screenshot_size_bytes=1234,
            _original_title="Candidate Name — private",
        )

    def wait(**kwargs: object) -> AuthObservation:
        trace.append("human.wait")
        assert "timeout" not in kwargs
        assert set(kwargs) == {
            "auth_probe",
            "owner_snapshot",
            "sleep",
            "stop_requested",
        }
        return AuthObservation(
            True,
            False,
            "https://www.linkedin.com/talent/home",
            ("talent_surface", "recruiter_account"),
        )

    result = run_human_auth_episode(
        "linkedin_rps",
        agent="Codex",
        target_id="target-exact",
        stop_requested=lambda: False,
        owner_snapshot=_increasing_owner(trace),
        mutation_sleep=lambda _seconds: trace.append("mutation.sleep"),
        wait_sleep=lambda _seconds: pytest.fail("fake waiter owns sleep"),
        locator_sink=lambda payload: emitted.append(dict(payload)),
        _lease_factory=lambda _site: lease,
        _target_resolver=resolver,
        _tab_attacher=attach,
        _auth_reader=_unauthenticated,
        _presenter=present,
        _auth_waiter=wait,
        _cleanup=lambda *_args, **_kwargs: {"status": "cleanup_not_needed"},
    )

    assert result["status"] == "authenticated"
    assert trace[0] == "lease.acquire"
    assert trace.index("resolve:linkedin_rps:target-exact") < trace.index("attach:target-exact:False")
    assert trace.index("tab.disconnect") < trace.index("lease.release")
    assert trace.count("tab.disconnect") == 1
    assert len(emitted) == 1
    assert emitted[0]["cg_window_id"] == 180
    assert "_original_title" not in emitted[0]
    assert "Candidate Name" not in json.dumps(emitted[0])


@pytest.mark.parametrize(
    "snapshot",
    [
        SimpleNamespace(
            owner_activity_detected=False,
            idle_seconds=None,
            detection_status="detector_error",
        ),
        SimpleNamespace(
            owner_activity_detected=True,
            idle_seconds=999,
            detection_status="ok",
        ),
    ],
)
def test_human_auth_runner_owner_gate_waits_read_only_before_attach(snapshot: object) -> None:
    trace: list[str] = []
    lease = _Lease(trace)
    stopped = False

    def wait_read_only(seconds: float) -> None:
        nonlocal stopped
        trace.append(f"wait:{seconds}")
        stopped = True

    result = run_human_auth_episode(
        "linkedin_rps",
        agent="Codex",
        stop_requested=lambda: stopped,
        owner_snapshot=lambda: snapshot,
        mutation_sleep=lambda _seconds: None,
        wait_sleep=wait_read_only,
        _lease_factory=lambda _site: lease,
        _target_resolver=lambda _site, **_kwargs: trace.append("resolve") or _ref(),
        _tab_attacher=lambda *_args, **_kwargs: pytest.fail("attach forbidden"),
    )

    assert result["status"] == "human_auth_stopped"
    assert trace[0:2] == ["lease.acquire", "resolve"]
    assert "wait:5.0" in trace
    assert trace[-1] == "lease.release"


def test_human_auth_runner_waits_for_lease_conflict_without_browser_action() -> None:
    trace: list[str] = []

    class ContendedLease(_Lease):
        attempts = 0

        def acquire(self) -> None:
            self.attempts += 1
            trace.append(f"lease.acquire:{self.attempts}")
            if self.attempts == 1:
                raise ProfileLockError("busy")
            self.owned = True

    lease = ContendedLease(trace)
    result = run_human_auth_episode(
        "linkedin_rps",
        agent="Codex",
        stop_requested=lambda: False,
        owner_snapshot=_increasing_owner(trace),
        mutation_sleep=lambda _seconds: None,
        wait_sleep=lambda seconds: trace.append(f"wait:{seconds}"),
        _lease_factory=lambda _site: lease,
        _target_resolver=lambda _site, **_kwargs: trace.append("resolve") or _ref(),
        _tab_attacher=lambda *_args, **_kwargs: trace.append("attach") or _Tab(trace),
        _auth_reader=_authenticated,
    )

    assert result["status"] == "authenticated"
    assert trace[:3] == ["lease.acquire:1", "wait:5.0", "lease.acquire:2"]
    assert trace.index("resolve") > trace.index("lease.acquire:2")


def test_linkedin_session_conflict_is_terminal_before_human_auth_presentation() -> None:
    trace: list[str] = []
    emitted: list[dict[str, object]] = []
    lease = _Lease(trace)
    tab = _Tab(trace)

    def conflict(_tab: object, _site: str) -> AuthObservation:
        trace.append("auth.conflict")
        return AuthObservation(
            authenticated=False,
            challenge=False,
            url="https://www.linkedin.com/enterprise-authentication/sessions",
            proof_names=("session_conflict",),
            auth_conflict=True,
        )

    result = run_human_auth_episode(
        "linkedin_rps",
        agent="Codex",
        target_id="target-exact",
        stop_requested=lambda: False,
        owner_snapshot=_increasing_owner(trace),
        mutation_sleep=lambda _seconds: trace.append("mutation.sleep"),
        wait_sleep=lambda _seconds: pytest.fail("terminal conflict must not wait"),
        locator_sink=lambda payload: emitted.append(dict(payload)),
        _lease_factory=lambda _site: lease,
        _target_resolver=lambda *_args, **_kwargs: _ref(),
        _tab_attacher=lambda *_args, **_kwargs: tab,
        _auth_reader=conflict,
        _presenter=lambda *_args, **_kwargs: pytest.fail(
            "terminal conflict must not present a human-auth window"
        ),
        _auth_waiter=lambda **_kwargs: pytest.fail(
            "terminal conflict must not enter HUMAN_AUTH polling"
        ),
        _cleanup=lambda *_args, **_kwargs: pytest.fail(
            "terminal conflict must not mutate the conflict page during cleanup"
        ),
    )

    assert result == {
        "status": "auth_conflict",
        "site": "linkedin_rps",
        "terminal": True,
        "reason": "linkedin_multiple_signin",
        "auth_url": "https://www.linkedin.com/enterprise-authentication/sessions",
    }
    assert emitted == []
    assert trace.count("auth.conflict") == 1
    assert trace.count("tab.disconnect") == 1
    assert trace[-1] == "lease.release"


def test_human_auth_production_detector_uses_fifteen_second_quiet_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[str] = []
    thresholds: list[float] = []
    counter = 0

    def detector(*, idle_threshold_seconds: float = 180.0):
        nonlocal counter
        counter += 1
        thresholds.append(idle_threshold_seconds)
        return SimpleNamespace(
            owner_activity_detected=False,
            idle_seconds=idle_threshold_seconds + counter,
            detection_status="ok",
        )

    monkeypatch.setattr(portal_worker, "detect_owner_activity_snapshot", detector, raising=False)
    monkeypatch.setattr(
        "tools.multi_position_sourcing.owner_activity.detect_owner_activity_snapshot",
        detector,
    )

    def waiter(**kwargs: object) -> AuthObservation:
        snapshot = kwargs["owner_snapshot"]()
        trace.append(f"auth-threshold:{thresholds[-1]}")
        assert snapshot.owner_activity_detected is False
        return _authenticated(None, "linkedin_rps")

    result = run_human_auth_episode(
        "linkedin_rps",
        agent="Codex",
        stop_requested=lambda: False,
        mutation_sleep=lambda _seconds: None,
        _lease_factory=lambda _site: _Lease(trace),
        _target_resolver=lambda *_args, **_kwargs: _ref(),
        _tab_attacher=lambda *_args, **_kwargs: _Tab(trace),
        _auth_reader=_unauthenticated,
        _presenter=lambda *_args, **_kwargs: LoginWindowLocator(
            "Codex", "linkedin_rps", 4321, "/tmp/p", "http://127.0.0.1:9225",
            "get-exact", "login", "https://www.linkedin.com/login", 180, "a" * 64, 1,
        ),
        _auth_waiter=waiter,
        _cleanup=lambda *_args, **_kwargs: {"status": "cleanup_ok"},
    )

    assert result["status"] == "authenticated"
    assert thresholds[-1] == 15.0


def test_human_auth_later_presentation_gate_waits_read_only_then_resumes() -> None:
    trace: list[str] = []
    lease = _Lease(trace)
    snapshots = iter(
        [
            (False, 180.0),
            (False, 181.0),
            (True, 0.0),
            (False, 180.0),
            (False, 181.0),
        ]
    )

    def owner():
        active, idle = next(snapshots)
        return SimpleNamespace(
            owner_activity_detected=active,
            idle_seconds=idle,
            detection_status="ok",
        )

    def presenter(_tab, ref, *, agent, mutation_gate, episode_id):
        trace.append("present.enter")
        mutation_gate()
        trace.append("present.mutated")
        return LoginWindowLocator(
            agent, ref.site, ref.browser_pid, ref.profile_path, ref.endpoint,
            "get-exact", "login", ref.initial_url, 180, "a" * 64, 1,
        )

    result = run_human_auth_episode(
        "linkedin_rps",
        agent="Codex",
        stop_requested=lambda: False,
        owner_snapshot=owner,
        mutation_sleep=lambda _seconds: None,
        wait_sleep=lambda seconds: trace.append(f"wait:{seconds}"),
        _lease_factory=lambda _site: lease,
        _target_resolver=lambda *_args, **_kwargs: _ref(),
        _tab_attacher=lambda *_args, **_kwargs: _Tab(trace),
        _auth_reader=_unauthenticated,
        _presenter=presenter,
        _auth_waiter=lambda **_kwargs: _authenticated(None, "linkedin_rps"),
        _cleanup=lambda *_args, **_kwargs: {"status": "cleanup_ok"},
    )

    assert result["status"] == "authenticated"
    assert "wait:5.0" in trace
    assert trace.index("wait:5.0") < trace.index("present.mutated")


def test_human_auth_stop_after_initial_gate_prevents_presentation() -> None:
    trace: list[str] = []
    checks = 0

    def stop() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    result = run_human_auth_episode(
        "linkedin_rps",
        agent="Codex",
        stop_requested=stop,
        owner_snapshot=_increasing_owner(trace),
        mutation_sleep=lambda _seconds: None,
        _lease_factory=lambda _site: _Lease(trace),
        _target_resolver=lambda *_args, **_kwargs: _ref(),
        _tab_attacher=lambda *_args, **_kwargs: _Tab(trace),
        _auth_reader=_unauthenticated,
        _presenter=lambda *_args, **_kwargs: pytest.fail("presentation forbidden after stop"),
    )

    assert result["status"] == "human_auth_stopped"


def test_human_auth_stop_during_presentation_gate_dwell_prevents_mutation() -> None:
    trace: list[str] = []
    stopped = False
    dwells = 0

    def mutation_sleep(_seconds: float) -> None:
        nonlocal stopped, dwells
        dwells += 1
        if dwells == 2:
            stopped = True

    def presenter(_tab, ref, *, agent, mutation_gate, episode_id):
        mutation_gate()
        trace.append("badge")
        return LoginWindowLocator(
            agent, ref.site, ref.browser_pid, ref.profile_path, ref.endpoint,
            "get-exact", "login", ref.initial_url, 180, "a" * 64, 1,
        )

    result = run_human_auth_episode(
        "linkedin_rps",
        agent="Codex",
        stop_requested=lambda: stopped,
        owner_snapshot=_increasing_owner(trace),
        mutation_sleep=mutation_sleep,
        wait_sleep=lambda _seconds: None,
        _lease_factory=lambda _site: _Lease(trace),
        _target_resolver=lambda *_args, **_kwargs: _ref(),
        _tab_attacher=lambda *_args, **_kwargs: _Tab(trace),
        _auth_reader=_unauthenticated,
        _presenter=presenter,
        _auth_waiter=lambda **_kwargs: _authenticated(None, "linkedin_rps"),
    )

    assert result["status"] == "human_auth_stopped"
    assert "badge" not in trace


def test_human_auth_presentation_lease_loss_is_not_retried() -> None:
    trace: list[str] = []

    class LostLease(_Lease):
        assertions = 0

        def assert_owned(self) -> None:
            self.assertions += 1
            trace.append(f"lease.assert:{self.assertions}")
            if self.assertions == 4:
                raise ProfileLockError("raw browser lease ownership was lost")

    def presenter(_tab, _ref, *, mutation_gate, **_kwargs):
        mutation_gate()
        pytest.fail("presentation mutation forbidden after lease loss")

    with pytest.raises(ProfileLockError, match="ownership was lost"):
        run_human_auth_episode(
            "linkedin_rps",
            agent="Codex",
            stop_requested=lambda: False,
            owner_snapshot=_increasing_owner(trace),
            mutation_sleep=lambda _seconds: None,
            wait_sleep=lambda _seconds: pytest.fail("lease loss must not be retried"),
            _lease_factory=lambda _site: LostLease(trace),
            _target_resolver=lambda *_args, **_kwargs: _ref(),
            _tab_attacher=lambda *_args, **_kwargs: _Tab(trace),
            _auth_reader=_unauthenticated,
            _presenter=presenter,
        )

    assert "tab.disconnect" in trace


def test_human_auth_missing_target_releases_without_launch_or_new_tab() -> None:
    trace: list[str] = []
    lease = _Lease(trace)

    with pytest.raises(LookupError, match="missing"):
        run_human_auth_episode(
            "linkedin_rps",
            agent="Codex",
            _lease_factory=lambda _site: lease,
            _target_resolver=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                LookupError("missing exact existing target")
            ),
            _tab_attacher=lambda *_args, **_kwargs: pytest.fail("no target creation or attach"),
        )

    assert trace == ["lease.acquire", "lease.release"]


def test_human_auth_keyboard_interrupt_still_disconnects_then_releases() -> None:
    trace: list[str] = []
    lease = _Lease(trace)

    with pytest.raises(KeyboardInterrupt):
        run_human_auth_episode(
            "linkedin_rps",
            agent="Codex",
            owner_snapshot=_increasing_owner(trace),
            mutation_sleep=lambda _seconds: None,
            _lease_factory=lambda _site: lease,
            _target_resolver=lambda *_args, **_kwargs: _ref(),
            _tab_attacher=lambda *_args, **_kwargs: _Tab(trace),
            _auth_reader=_unauthenticated,
            _presenter=lambda *_args, **_kwargs: LoginWindowLocator(
                "Codex", "linkedin_rps", 4321, "/tmp/p", "http://127.0.0.1:9225",
                "get-exact", "login", "https://www.linkedin.com/login", 180, "a" * 64, 1,
            ),
            _auth_waiter=lambda **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
            _cleanup=lambda *_args, **_kwargs: trace.append("presentation.cleanup") or {
                "status": "cleanup_ok"
            },
        )

    assert trace[-3:] == ["presentation.cleanup", "tab.disconnect", "lease.release"]


def test_human_auth_stopped_attempts_guarded_presentation_cleanup() -> None:
    trace: list[str] = []
    lease = _Lease(trace)

    result = run_human_auth_episode(
        "linkedin_rps",
        agent="Codex",
        stop_requested=lambda: False,
        owner_snapshot=_increasing_owner(trace),
        mutation_sleep=lambda _seconds: None,
        _lease_factory=lambda _site: lease,
        _target_resolver=lambda *_args, **_kwargs: _ref(),
        _tab_attacher=lambda *_args, **_kwargs: _Tab(trace),
        _auth_reader=_unauthenticated,
        _presenter=lambda *_args, **_kwargs: LoginWindowLocator(
            "Codex", "linkedin_rps", 4321, "/tmp/p", "http://127.0.0.1:9225",
            "get-exact", "login", "https://www.linkedin.com/login", 180, "a" * 64, 1,
        ),
        _auth_waiter=lambda **_kwargs: None,
        _cleanup=lambda *_args, **_kwargs: trace.append("presentation.cleanup") or {
            "status": "cleanup_ok"
        },
    )

    assert result["status"] == "human_auth_stopped"
    assert result["cleanup"]["status"] == "cleanup_ok"
    assert trace[-3:] == ["presentation.cleanup", "tab.disconnect", "lease.release"]


def test_human_auth_stop_immediately_after_success_probe_wins_status() -> None:
    trace: list[str] = []
    stopped = False

    def waiter(**_kwargs: object) -> AuthObservation:
        nonlocal stopped
        stopped = True
        return _authenticated(None, "linkedin_rps")

    result = run_human_auth_episode(
        "linkedin_rps",
        agent="Codex",
        stop_requested=lambda: stopped,
        owner_snapshot=_increasing_owner(trace),
        mutation_sleep=lambda _seconds: None,
        _lease_factory=lambda _site: _Lease(trace),
        _target_resolver=lambda *_args, **_kwargs: _ref(),
        _tab_attacher=lambda *_args, **_kwargs: _Tab(trace),
        _auth_reader=_unauthenticated,
        _presenter=lambda *_args, **_kwargs: LoginWindowLocator(
            "Codex", "linkedin_rps", 4321, "/tmp/p", "http://127.0.0.1:9225",
            "get-exact", "login", "https://www.linkedin.com/login", 180, "a" * 64, 1,
        ),
        _auth_waiter=waiter,
        _cleanup=lambda *_args, **_kwargs: trace.append("presentation.cleanup") or {
            "status": "cleanup_ok"
        },
    )

    assert result["status"] == "human_auth_stopped"
    assert result["cleanup"]["status"] == "cleanup_ok"
    assert trace[-3:] == ["presentation.cleanup", "tab.disconnect", "lease.release"]


def test_partial_lease_acquire_interrupt_still_attempts_release() -> None:
    trace: list[str] = []

    class InterruptedLease(_Lease):
        def acquire(self) -> None:
            trace.append("lease.acquire.partial")
            self.owned = True
            raise KeyboardInterrupt()

    lease = InterruptedLease(trace)
    with pytest.raises(KeyboardInterrupt):
        run_human_auth_episode(
            "linkedin_rps",
            agent="Codex",
            _lease_factory=lambda _site: lease,
            _target_resolver=lambda *_args, **_kwargs: pytest.fail("resolve forbidden"),
        )

    assert trace == ["lease.acquire.partial", "lease.release"]


def test_raw_login_lease_interrupt_removes_partial_lock_tree(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    monkeypatch.setattr(portal_worker, "RAW_SINGLE_TARGET_LOCK_ROOT", lock_root)
    monkeypatch.setattr(
        portal_worker.json,
        "dump",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    lock = ProfileLock(PortalWorkerConfig(
        channel="linkedin_rps",
        worker_id="default",
        profile_root=tmp_path / "profiles",
        mode="headed",
        connection_mode="raw_single_tab",
    ))

    with pytest.raises(KeyboardInterrupt):
        lock.acquire()

    assert not lock.config.lock_path.exists()


def test_raw_login_lease_interrupt_after_ambiguous_mkdir_leaves_fail_closed_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    monkeypatch.setattr(portal_worker, "RAW_SINGLE_TARGET_LOCK_ROOT", lock_root)
    lock = ProfileLock(PortalWorkerConfig(
        channel="linkedin_rps",
        worker_id="default",
        profile_root=tmp_path / "profiles",
        mode="headed",
        connection_mode="raw_single_tab",
    ))
    original_mkdir = portal_worker.os.mkdir

    def interrupt_after_lock_mkdir(path, *args, **kwargs):
        result = original_mkdir(path, *args, **kwargs)
        if path == lock.config.lock_path.name and kwargs.get("dir_fd") is not None:
            raise KeyboardInterrupt("immediately after lock mkdir")
        return result

    monkeypatch.setattr(portal_worker.os, "mkdir", interrupt_after_lock_mkdir)
    with pytest.raises(KeyboardInterrupt, match="immediately after lock mkdir"):
        lock.acquire()

    assert lock.config.lock_path.is_dir()
    assert not lock._raw_owner_path.exists()
    with pytest.raises(ProfileLockError, match="already locked"):
        ProfileLock(lock.config).acquire()


def test_raw_login_lease_interrupt_after_owner_flush_removes_owned_lock(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    monkeypatch.setattr(portal_worker, "RAW_SINGLE_TARGET_LOCK_ROOT", lock_root)

    class InterruptingProfileLock(ProfileLock):
        def __setattr__(self, name: str, value: object) -> None:
            if name == "_lease_token" and value is not None:
                owner_path = self._raw_owner_path
                if owner_path.exists():
                    payload = json.loads(owner_path.read_text(encoding="utf-8"))
                    assert payload["token"] == value
                    raise KeyboardInterrupt("after owner flush before token assignment")
            super().__setattr__(name, value)

    lock = InterruptingProfileLock(PortalWorkerConfig(
        channel="linkedin_rps",
        worker_id="default",
        profile_root=tmp_path / "profiles",
        mode="headed",
        connection_mode="raw_single_tab",
    ))

    with pytest.raises(KeyboardInterrupt, match="after owner flush"):
        lock.acquire()

    assert not lock.config.lock_path.exists()


def test_raw_login_lease_interrupt_before_fdopen_closes_descriptor(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    monkeypatch.setattr(portal_worker, "RAW_SINGLE_TARGET_LOCK_ROOT", lock_root)
    opened_fd: int | None = None

    def interrupt_fdopen(fd: int, *_args: object, **_kwargs: object):
        nonlocal opened_fd
        opened_fd = fd
        raise KeyboardInterrupt("before fdopen ownership transfer")

    monkeypatch.setattr(portal_worker.os, "fdopen", interrupt_fdopen)
    lock = ProfileLock(PortalWorkerConfig(
        channel="linkedin_rps",
        worker_id="default",
        profile_root=tmp_path / "profiles",
        mode="headed",
        connection_mode="raw_single_tab",
    ))

    with pytest.raises(KeyboardInterrupt, match="ownership transfer"):
        lock.acquire()

    assert opened_fd is not None
    try:
        os.fstat(opened_fd)
    except OSError as exc:
        descriptor_closed = exc.errno == errno.EBADF
    else:
        descriptor_closed = False
        os.close(opened_fd)
    assert descriptor_closed is True
    assert not lock.config.lock_path.exists()


def test_raw_login_lease_parent_symlink_swap_never_writes_external_owner_and_closes_fds(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "sentinel").write_text("keep", encoding="utf-8")
    parked_root = tmp_path / "parked-locks"
    monkeypatch.setattr(portal_worker, "RAW_SINGLE_TARGET_LOCK_ROOT", lock_root)
    lock = ProfileLock(PortalWorkerConfig(
        channel="linkedin_rps",
        worker_id="default",
        profile_root=tmp_path / "profiles",
        mode="headed",
        connection_mode="raw_single_tab",
    ))
    original_open = portal_worker.os.open
    opened_fds: list[int] = []
    swapped = False

    def swap_parent_before_owner_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "owner.json" and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            lock_root.rename(parked_root)
            lock_root.symlink_to(external, target_is_directory=True)
        descriptor = original_open(path, flags, *args, **kwargs)
        opened_fds.append(descriptor)
        return descriptor

    monkeypatch.setattr(portal_worker.os, "open", swap_parent_before_owner_open)
    with pytest.raises(ProfileLockError, match="path changed"):
        lock.acquire()

    assert swapped is True
    assert lock_root.is_symlink()
    assert (external / "sentinel").read_text(encoding="utf-8") == "keep"
    assert not (external / "owner.json").exists()
    assert not (external / lock.config.lock_path.name).exists()
    for descriptor in opened_fds:
        with pytest.raises(OSError) as closed:
            os.fstat(descriptor)
        assert closed.value.errno == errno.EBADF


def test_raw_login_lease_second_acquire_preserves_owner_and_leaks_no_fds(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    monkeypatch.setattr(portal_worker, "RAW_SINGLE_TARGET_LOCK_ROOT", lock_root)
    lock = ProfileLock(PortalWorkerConfig(
        channel="linkedin_rps",
        worker_id="default",
        profile_root=tmp_path / "profiles",
        mode="headed",
        connection_mode="raw_single_tab",
    ))
    baseline_fds = len(os.listdir("/dev/fd"))
    lock.acquire()
    retained_state = (
        lock._lease_token,
        lock._lease_parent_fd,
        lock._lease_dir_fd,
        lock._lease_parent_identity,
        lock._lease_dir_identity,
    )

    with pytest.raises(ProfileLockError, match="already acquired"):
        lock.acquire()

    assert (
        lock._lease_token,
        lock._lease_parent_fd,
        lock._lease_dir_fd,
        lock._lease_parent_identity,
        lock._lease_dir_identity,
    ) == retained_state
    lock.assert_owned()
    lock.release()
    assert not lock.config.lock_path.exists()
    assert len(os.listdir("/dev/fd")) == baseline_fds


def test_raw_login_lease_release_can_retry_after_interrupt_following_owner_unlink(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    monkeypatch.setattr(portal_worker, "RAW_SINGLE_TARGET_LOCK_ROOT", lock_root)
    lock = ProfileLock(PortalWorkerConfig(
        channel="linkedin_rps",
        worker_id="default",
        profile_root=tmp_path / "profiles",
        mode="headed",
        connection_mode="raw_single_tab",
    ))
    lock.acquire()
    retained_fds = (lock._lease_parent_fd, lock._lease_dir_fd)
    original_unlink = portal_worker.os.unlink
    interrupted = False

    def interrupt_after_owner_unlink(path, *args, **kwargs):
        nonlocal interrupted
        result = original_unlink(path, *args, **kwargs)
        if path == "owner.json" and kwargs.get("dir_fd") is not None and not interrupted:
            interrupted = True
            raise KeyboardInterrupt("after owner unlink")
        return result

    monkeypatch.setattr(portal_worker.os, "unlink", interrupt_after_owner_unlink)
    with pytest.raises(KeyboardInterrupt, match="after owner unlink"):
        lock.release()

    assert lock.config.lock_path.exists()
    assert not lock._raw_owner_path.exists()
    lock.release()
    lock.release()
    assert not lock.config.lock_path.exists()
    for descriptor in retained_fds:
        assert descriptor is not None
        with pytest.raises(OSError) as closed:
            os.fstat(descriptor)
        assert closed.value.errno == errno.EBADF


def test_non_contention_lease_error_is_not_retried_forever() -> None:
    trace: list[str] = []

    class BrokenLease(_Lease):
        def acquire(self) -> None:
            trace.append("lease.acquire")
            if trace.count("lease.acquire") > 1:
                raise AssertionError("non-contention lease error must not be retried")
            raise ProfileLockError("initialization failed")

    with pytest.raises(ProfileLockError, match="initialization"):
        run_human_auth_episode(
            "linkedin_rps",
            agent="Codex",
            stop_requested=lambda: False,
            wait_sleep=lambda seconds: trace.append(f"wait:{seconds}"),
            _lease_factory=lambda _site: BrokenLease(trace),
        )

    assert trace == ["lease.acquire", "lease.release"]


def test_raw_login_lease_mkdir_os_error_is_not_retried_as_contention(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    monkeypatch.setattr(portal_worker, "RAW_SINGLE_TARGET_LOCK_ROOT", lock_root)
    lock = ProfileLock(PortalWorkerConfig(
        channel="linkedin_rps",
        worker_id="default",
        profile_root=tmp_path / "profiles",
        mode="headed",
        connection_mode="raw_single_tab",
    ))
    original_mkdir = portal_worker.os.mkdir
    attempts = 0

    def fail_raw_lock_mkdir(path, *args, **kwargs):
        nonlocal attempts
        if path == lock.config.lock_path.name and kwargs.get("dir_fd") is not None:
            attempts += 1
            raise PermissionError(errno.EACCES, "permission denied")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(portal_worker.os, "mkdir", fail_raw_lock_mkdir)
    with pytest.raises(ProfileLockError, match="initialization failed"):
        run_human_auth_episode(
            "linkedin_rps",
            agent="Codex",
            wait_sleep=lambda _seconds: pytest.fail("non-contention error must not wait"),
            _lease_factory=lambda _site: lock,
            _target_resolver=lambda *_args, **_kwargs: pytest.fail("resolve forbidden"),
        )

    assert attempts == 1


def test_keepalive_runner_proves_auth_marks_badge_and_invokes_guarded_roundtrip() -> None:
    trace: list[str] = []
    lease = _Lease(trace)
    tab = _Tab(trace)

    def roundtrip(current, ref, target, *, auth_probe, mutation_gate, sleep):
        trace.append("roundtrip")
        assert current is tab and ref == _ref() and target == _target()
        assert auth_probe(tab).authenticated is True
        mutation_gate()
        mutation_gate()
        return {"status": "ok", "restore_pending": False}

    def cleanup_badge(
        _tab,
        _ref,
        _label,
        *,
        mutation_gate,
        document_loader_id,
        badge_bound_url,
    ):
        assert callable(mutation_gate)
        assert document_loader_id == "loader-1"
        assert badge_bound_url == "https://www.linkedin.com/talent/home"
        return {"status": "cleanup_not_needed"}

    result = run_safe_keepalive_episode(
        "linkedin_rps",
        _target(),
        agent="Codex",
        owner_snapshot=_increasing_owner(trace),
        mutation_sleep=lambda _seconds: trace.append("mutation.sleep"),
        navigation_sleep=lambda _seconds: None,
        _lease_factory=lambda _site: lease,
        _target_resolver=lambda site, *, target_id: (
            trace.append(f"resolve:{site}:{target_id}") or _ref()
        ),
        _tab_attacher=lambda *_args, **_kwargs: trace.append("attach") or tab,
        _auth_reader=_authenticated,
        _roundtrip=roundtrip,
        _cleanup_badge=cleanup_badge,
    )

    assert result["status"] == "ok"
    assert trace[0] == "lease.acquire"
    assert trace.index("resolve:linkedin_rps:target-exact") < trace.index("attach")
    assert trace.index("tab.mark_busy:https://www.linkedin.com/talent/home") < trace.index("roundtrip")
    assert trace[-2:] == ["tab.disconnect", "lease.release"]


def test_keepalive_roundtrip_interrupt_attempts_badge_cleanup_before_disconnect() -> None:
    trace: list[str] = []
    lease = _Lease(trace)
    tab = _Tab(trace)

    with pytest.raises(KeyboardInterrupt):
        run_safe_keepalive_episode(
            "linkedin_rps",
            _target(),
            agent="Codex",
            owner_snapshot=_increasing_owner(trace),
            mutation_sleep=lambda _seconds: None,
            _lease_factory=lambda _site: lease,
            _target_resolver=lambda *_args, **_kwargs: _ref(),
            _tab_attacher=lambda *_args, **_kwargs: tab,
            _auth_reader=_authenticated,
            _roundtrip=lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
            _cleanup_badge=lambda *_args, **_kwargs: trace.append("badge.cleanup") or {
                "status": "cleanup_ok"
            },
        )

    assert trace[-3:] == ["badge.cleanup", "tab.disconnect", "lease.release"]


def test_keepalive_badge_gate_owner_activity_returns_structured_skip() -> None:
    trace: list[str] = []
    snapshots = iter(
        [
            SimpleNamespace(owner_activity_detected=False, idle_seconds=180, detection_status="ok"),
            SimpleNamespace(owner_activity_detected=False, idle_seconds=181, detection_status="ok"),
            SimpleNamespace(owner_activity_detected=True, idle_seconds=0, detection_status="ok"),
        ]
    )

    result = run_safe_keepalive_episode(
        "linkedin_rps",
        _target(),
        agent="Codex",
        owner_snapshot=lambda: next(snapshots),
        mutation_sleep=lambda _seconds: None,
        _lease_factory=lambda _site: _Lease(trace),
        _target_resolver=lambda *_args, **_kwargs: _ref(),
        _tab_attacher=lambda *_args, **_kwargs: _Tab(trace),
        _auth_reader=_authenticated,
    )

    assert result["status"] == "skipped_owner_active"
    assert result["restore_pending"] is False


def test_keepalive_lease_loss_is_not_mislabeled_as_owner_activity() -> None:
    trace: list[str] = []

    class LostLease(_Lease):
        def assert_owned(self) -> None:
            raise ProfileLockError("raw browser lease ownership was lost")

    with pytest.raises(ProfileLockError, match="ownership was lost"):
        run_safe_keepalive_episode(
            "linkedin_rps",
            _target(),
            agent="Codex",
            owner_snapshot=_increasing_owner(trace),
            mutation_sleep=lambda _seconds: None,
            _lease_factory=lambda _site: LostLease(trace),
            _target_resolver=lambda *_args, **_kwargs: _ref(),
        )


def test_cli_exposes_and_dispatches_real_human_auth_subcommand(monkeypatch, capsys) -> None:
    calls: list[tuple[str, str, str | None]] = []

    def run(site: str, *, agent: str, target_id: str | None, **_kwargs: object):
        calls.append((site, agent, target_id))
        return {"status": "authenticated", "site": site}

    monkeypatch.setattr(
        "tools.multi_position_sourcing.session_guard.run_human_auth_episode",
        run,
    )

    assert main([
        "human-auth",
        "--site", "linkedin_rps",
        "--agent", "Codex",
        "--target-id", "target-exact",
    ]) == 0
    assert calls == [("linkedin_rps", "Codex", "target-exact")]
    assert json.loads(capsys.readouterr().out)["status"] == "authenticated"


def test_cli_help_lists_human_auth_and_keepalive(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "human-auth" in output
    assert "keepalive" in output
