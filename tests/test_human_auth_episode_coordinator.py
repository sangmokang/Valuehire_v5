from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing.session_guard import (
    AuthObservation,
    BrowserTargetRef,
    LoginWindowLocator,
    run_human_auth_episode,
    wait_for_human_auth,
)


class EpisodeStore:
    def __init__(self) -> None:
        self.claims: set[tuple[str, str]] = set()
        self.locators: dict[str, LoginWindowLocator] = {}

    def claim(self, episode_id: str, event: str) -> bool:
        key = (episode_id, event)
        if key in self.claims:
            return False
        self.claims.add(key)
        return True

    def count(self, episode_id: str, event: str) -> int:
        return int((episode_id, event) in self.claims)

    def save_locator(self, episode_id: str, locator: LoginWindowLocator) -> None:
        self.locators[episode_id] = locator

    def load_locator(self, episode_id: str) -> LoginWindowLocator | None:
        return self.locators.get(episode_id)


class Lease:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.owned = False

    def acquire(self) -> None:
        self.owned = True
        self.trace.append("lease.acquire")

    def assert_owned(self) -> None:
        if not self.owned:
            raise RuntimeError("lease lost")

    def release(self) -> None:
        self.owned = False
        self.trace.append("lease.release")


class Tab:
    target_id = "target-exact"

    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    def disconnect(self) -> bool:
        self.trace.append("disconnect")
        return True

    def close(self) -> None:
        raise AssertionError("HUMAN_AUTH must never close browser/page")


def ref() -> BrowserTargetRef:
    return BrowserTargetRef(
        site="linkedin_rps",
        endpoint="http://127.0.0.1:9225",
        target_id="target-exact",
        websocket_url="ws://target-exact",
        initial_url="https://www.linkedin.com/authwall",
        profile_path="/tmp/linkedin",
        browser_pid=4321,
    )


def observation(state: str) -> AuthObservation:
    return AuthObservation(
        authenticated=state == "AUTHENTICATED",
        challenge=state == "HUMAN_AUTH_REQUIRED",
        url="https://www.linkedin.com/talent/home"
        if state == "AUTHENTICATED" else "https://www.linkedin.com/authwall",
        proof_names=("talent_surface", "recruiter_marker")
        if state == "AUTHENTICATED" else (),
        auth_conflict=state == "AUTH_CONFLICT",
        state=state,
        observed_at="2026-07-26T05:00:00+00:00",
        target_id="target-exact",
    )


def locator() -> LoginWindowLocator:
    return LoginWindowLocator(
        agent="Codex",
        site="linkedin_rps",
        browser_pid=4321,
        profile_path="/tmp/linkedin",
        cdp_endpoint="http://127.0.0.1:9225",
        target_id_suffix="arget-exact",
        sanitized_title="[LOGIN HERE][Codex][linkedin][arget-exact] Sign in",
        sanitized_url="https://www.linkedin.com/authwall",
        cg_window_id=180,
        screenshot_sha256="a" * 64,
        screenshot_size_bytes=123,
    )


def owner():
    return SimpleNamespace(
        owner_activity_detected=False,
        idle_seconds=20.0,
        detection_status="ok",
        portal_site_active=False,
    )


def run(
    trace: list[str],
    store: EpisodeStore,
    notifications: list[dict[str, str]],
    **changes,
):
    options = {
        "agent": "Codex",
        "machine": "Macmini",
        "episode_id": "episode-11",
        "target_id": "target-exact",
        "stop_requested": lambda: False,
        "owner_snapshot": owner,
        "mutation_sleep": lambda _seconds: None,
        "wait_sleep": lambda _seconds: None,
        "notification_sink": lambda payload: notifications.append(dict(payload)),
        "_episode_store": store,
        "_lease_factory": lambda _site: Lease(trace),
        "_target_resolver": lambda *_args, **_kwargs: ref(),
        "_tab_attacher": lambda *_args, **_kwargs: Tab(trace),
        "_auth_reader": lambda *_args: observation("HUMAN_AUTH_REQUIRED"),
        "_presenter": lambda *_args, **_kwargs: trace.append("focus") or locator(),
        "_auth_waiter": lambda **_kwargs: observation("AUTHENTICATED"),
        "_cleanup": lambda *_args, **_kwargs: {"status": "cleanup_ok"},
        "_evidence_capture": lambda *_args, **_kwargs: {
            "status": "saved", "capture_status": "saved", "artifact": "private",
        },
        "_evidence_validator": lambda _payload: True,
    }
    options.update(changes)
    return run_human_auth_episode("linkedin_rps", **options)


def test_presentation_and_notification_are_deduplicated_per_episode() -> None:
    trace: list[str] = []
    notifications: list[dict[str, str]] = []
    store = EpisodeStore()

    first = run(trace, store, notifications)
    second = run(trace, store, notifications)

    assert trace.count("focus") == 1
    assert len(notifications) == 1
    assert notifications[0] == {
        "machine": "Macmini",
        "site": "linkedin_rps",
        "agent": "Codex",
        "target_suffix": "arget-exact",
        "sanitized_title": "[LOGIN HERE][Codex][linkedin][arget-exact] Sign in",
    }
    for result in (first, second):
        assert result["episode_id"] == "episode-11"
        assert result["presentation_count"] == 1
        assert result["notification_count"] == 1
        assert result["state"] == "AUTHENTICATED"


def test_waiter_never_resumes_at_fourteen_seconds_and_polls_at_least_five() -> None:
    idle = iter((14.0, 15.0))
    sleeps: list[float] = []
    result = wait_for_human_auth(
        auth_probe=lambda: observation("AUTHENTICATED"),
        owner_snapshot=lambda: SimpleNamespace(
            owner_activity_detected=False,
            idle_seconds=next(idle),
            detection_status="ok",
        ),
        sleep=sleeps.append,
        stop_requested=lambda: False,
        utc_now=lambda: datetime(2026, 7, 26, 5, 1, tzinfo=timezone.utc),
    )

    assert result is not None
    assert result.owner_quiet_seconds == 15.0
    assert result.last_probe_at == "2026-07-26T05:01:00+00:00"
    assert sleeps == [5.0]


def test_auth_conflict_never_presents_notifies_or_waits() -> None:
    trace: list[str] = []
    notifications: list[dict[str, str]] = []
    result = run(
        trace,
        EpisodeStore(),
        notifications,
        _auth_reader=lambda *_args: observation("AUTH_CONFLICT"),
        _presenter=lambda *_args, **_kwargs: pytest.fail("conflict must not focus"),
        _auth_waiter=lambda **_kwargs: pytest.fail("conflict must not wait"),
    )
    assert result["state"] == "AUTH_CONFLICT"
    assert result["presentation_count"] == 0
    assert result["notification_count"] == 0
    assert notifications == []


def test_keyboard_interrupt_disconnects_websocket_without_browser_close() -> None:
    trace: list[str] = []
    with pytest.raises(KeyboardInterrupt):
        run(
            trace,
            EpisodeStore(),
            [],
            _auth_waiter=lambda **_kwargs: (_ for _ in ()).throw(
                KeyboardInterrupt()
            ),
        )
    assert trace[-2:] == ["disconnect", "lease.release"]
