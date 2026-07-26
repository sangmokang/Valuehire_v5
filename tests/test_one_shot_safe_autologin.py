from __future__ import annotations

import json
import inspect
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing.portal_worker import ProfileLockError
from tools.multi_position_sourcing.session_guard import (
    AuthObservation,
    BrowserTargetRef,
    run_auto_login_episode,
)
from tools.multi_position_sourcing.safe_autologin import (
    LoginFormObservation,
    submit_login_form_once,
)


URL = "https://www.linkedin.com/uas/login-cap"


class Lease:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.owned = False

    def acquire(self) -> None:
        self.trace.append("lease.acquire")
        self.owned = True

    def assert_owned(self) -> None:
        if not self.owned:
            raise RuntimeError("not owned")

    def release(self) -> None:
        self.trace.append("lease.release")
        self.owned = False


class Tab:
    target_id = "target-exact"

    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    def current_url(self) -> str:
        return URL

    def mark_busy(self, _label: str, *, expected_url: str) -> bool:
        assert expected_url == URL
        self.trace.append("badge")
        return True

    def disconnect(self) -> bool:
        self.trace.append("disconnect")
        return True


def ref() -> BrowserTargetRef:
    return BrowserTargetRef(
        site="linkedin_rps",
        endpoint="http://127.0.0.1:9225",
        target_id="target-exact",
        websocket_url="ws://target-exact",
        initial_url=URL,
    )


def auth(state: str) -> AuthObservation:
    return AuthObservation(
        authenticated=state == "AUTHENTICATED",
        challenge=state == "HUMAN_AUTH_REQUIRED",
        url=URL,
        proof_names=("talent_surface", "recruiter_marker")
        if state == "AUTHENTICATED" else (),
        auth_conflict=state == "AUTH_CONFLICT",
        state=state,
        target_id="target-exact",
        url_before=URL,
        url_after=URL,
    )


def owner(*, active: bool = False):
    return SimpleNamespace(
        detection_status="ok",
        owner_activity_detected=active,
        idle_seconds=120.0,
        portal_site_active=False,
    )


def run(trace: list[str], **changes):
    tab = changes.pop("tab", Tab(trace))
    observations = iter(changes.pop("observations", [auth("AUTH_LOST"), auth("AUTHENTICATED")]))
    options = {
        "agent": "Codex",
        "target_id": "target-exact",
        "episode_id": "episode-10",
        "linkedin_request_id": "request-10",
        "selected_machine": "macmini",
        "linkedin_fleet_observations": {
            "request_id": "request-10",
            "complete": True,
            "eligible_machines": ["macmini"],
            "missing_machines": [],
            "observations_by_machine": {
                "macmini": {
                    "state": "AUTH_LOST",
                    "ready": True,
                    "target_id": "target-exact",
                    "evidence_ref": "snapshot:macmini",
                }
            },
        },
        "_owner_snapshot": lambda: owner(),
        "_lease_factory": lambda _site: Lease(trace),
        "_target_resolver": lambda *_args, **_kwargs: ref(),
        "_tab_attacher": lambda *_args, **_kwargs: tab,
        "_auth_reader": lambda *_args: next(observations),
        "_form_reader": lambda *_args, **_kwargs: {
            "valid": True,
            "fingerprint": "linkedin-login-cap-v1",
            "url": URL,
            "badge_present": "badge" in trace,
        },
        "_credential_provider": SimpleNamespace(
            load=lambda _site: SimpleNamespace(
                username="credential-user",
                password="credential-secret",
            )
        ),
        "_submitter": lambda *_args, **_kwargs: trace.append("submit") or {
            "submitted": True,
            "reason": "submitted",
        },
        "_mutation_gate": lambda *_args, **_kwargs: trace.append("gate"),
    }
    options.update(changes)
    return run_auto_login_episode("linkedin_rps", **options)


def test_authenticated_target_loads_no_credentials_and_mutates_zero_times() -> None:
    trace: list[str] = []
    provider = SimpleNamespace(
        load=lambda _site: pytest.fail("authenticated target must not load Keychain")
    )

    result = run(
        trace,
        observations=[auth("AUTHENTICATED")],
        _credential_provider=provider,
        _form_reader=lambda *_args, **_kwargs: pytest.fail("must not inspect form"),
        _submitter=lambda *_args, **_kwargs: pytest.fail("must not submit"),
    )

    assert result["attempted"] is False
    assert result["submission_count"] == 0
    assert result["state"] == "AUTHENTICATED"
    assert "badge" not in trace and "submit" not in trace


def test_selector_drift_and_human_activity_mutate_zero_times() -> None:
    trace: list[str] = []
    drift = run(
        trace,
        _form_reader=lambda *_args, **_kwargs: {
            "valid": False, "fingerprint": "", "url": URL,
        },
    )
    assert drift["state"] == "SELECTOR_DRIFT"
    assert drift["submission_count"] == 0
    assert "badge" not in trace and "submit" not in trace

    trace.clear()
    active = run(trace, _owner_snapshot=lambda: owner(active=True))
    assert active["state"] == "HUMAN_ACTIVE"
    assert trace == []


def test_fresh_gates_badge_and_form_precede_exactly_one_submission() -> None:
    trace: list[str] = []
    result = run(trace)

    assert result["attempted"] is True
    assert result["submission_count"] == 1
    assert result["state"] == "AUTHENTICATED"
    assert trace.index("badge") < trace.index("submit")
    assert trace.count("gate") == 2
    assert trace.count("submit") == 1


def test_fresh_owner_guard_rejection_mutates_zero_times() -> None:
    trace: list[str] = []
    result = run(
        trace,
        _mutation_gate=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ProfileLockError("owner activity blocks raw browser mutation")
        ),
    )
    assert result["state"] == "HUMAN_ACTIVE"
    assert result["submission_count"] == 0
    assert "badge" not in trace and "submit" not in trace


def test_challenge_and_conflict_post_observations_are_terminal() -> None:
    for state in ("HUMAN_AUTH_REQUIRED", "AUTH_CONFLICT"):
        trace: list[str] = []
        result = run(trace, observations=[auth("AUTH_LOST"), auth(state)])
        assert result["state"] == state
        assert result["submission_count"] == 1
        assert result["post_observation"]["state"] == state
        assert trace.count("submit") == 1


def test_same_episode_second_call_never_submits_twice() -> None:
    trace: list[str] = []
    tab = Tab(trace)

    first = run(trace, tab=tab, observations=[auth("AUTH_LOST"), auth("AUTH_LOST")])
    second = run(trace, tab=tab, observations=[auth("AUTH_LOST")])

    assert first["submission_count"] == 1
    assert second["submission_count"] == 0
    assert second["reason"] == "EPISODE_ALREADY_SUBMITTED"
    assert trace.count("submit") == 1


def test_secret_is_absent_from_result_repr_and_process_boundary() -> None:
    trace: list[str] = []
    result = run(trace)
    encoded = json.dumps(result, ensure_ascii=False) + repr(result)

    assert "credential-user" not in encoded
    assert "credential-secret" not in encoded
    assert result.keys() >= {
        "attempted", "submission_count", "state", "reason", "post_observation",
    }

    source = inspect.getsource(run_auto_login_episode)
    assert "portal_selfservice_login" not in source
    assert "portal_login" not in source
    assert "subprocess" not in source
    assert "os.environ" not in source


def test_atomic_runtime_submission_marks_episode_without_navigation_or_secret_output() -> None:
    scripts: list[str] = []

    class RuntimeTab:
        def eval(self, script: str):
            scripts.append(script)
            return {"submitted": True, "reason": "submitted"}

    form = LoginFormObservation(
        valid=True,
        fingerprint="fingerprint",
        url=URL,
        badge_present=True,
        selectors=("#username", "#password", 'button[type="submit"]'),
        signature="INPUT|text|session_key|username|::INPUT|password|session_password|current-password|::BUTTON|submit|||",
    )
    result = submit_login_form_once(
        RuntimeTab(),
        form=form,
        episode_id="episode-10",
        username="credential-user",
        password="credential-secret",
    )

    assert result == {"submitted": True, "reason": "submitted"}
    assert "credential-user" not in repr(result)
    assert "credential-secret" not in repr(result)
    assert "dataset.vhLoginEpisode" in scripts[0]
    assert "location.href" in scripts[0]
    assert "navigate" not in scripts[0]
