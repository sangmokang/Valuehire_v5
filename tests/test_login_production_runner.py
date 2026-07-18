"""Production wiring for exact-target HUMAN_AUTH and safe keepalive."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing.session_guard import (
    AuthObservation,
    BrowserTargetRef,
    LoginWindowLocator,
    SafeKeepaliveTarget,
    main,
    run_human_auth_episode,
    run_safe_keepalive_episode,
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
def test_human_auth_runner_owner_gate_fails_closed_before_attach(snapshot: object) -> None:
    trace: list[str] = []
    lease = _Lease(trace)

    with pytest.raises(Exception, match="owner activity"):
        run_human_auth_episode(
            "linkedin_rps",
            agent="Codex",
            owner_snapshot=lambda: snapshot,
            mutation_sleep=lambda _seconds: None,
            _lease_factory=lambda _site: lease,
            _target_resolver=lambda _site, **_kwargs: trace.append("resolve") or _ref(),
            _tab_attacher=lambda *_args, **_kwargs: pytest.fail("attach forbidden"),
        )

    assert trace[0:2] == ["lease.acquire", "resolve"]
    assert trace[-1] == "lease.release"


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
        )

    assert trace[-2:] == ["tab.disconnect", "lease.release"]


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
        _cleanup_badge=lambda *_args, **_kwargs: {"status": "cleanup_not_needed"},
    )

    assert result["status"] == "ok"
    assert trace[0] == "lease.acquire"
    assert trace.index("resolve:linkedin_rps:target-exact") < trace.index("attach")
    assert trace.index("tab.mark_busy:https://www.linkedin.com/talent/home") < trace.index("roundtrip")
    assert trace[-2:] == ["tab.disconnect", "lease.release"]


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

