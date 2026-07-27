from __future__ import annotations

import json
import inspect
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing.portal_worker import ProfileLockError
from tools.multi_position_sourcing.portal_autologin import login_url_for_channel
from tools.multi_position_sourcing.session_guard import (
    AuthObservation,
    BrowserTargetRef,
    run_auto_login_episode,
)
from tools.multi_position_sourcing.safe_autologin import (
    LoginFormObservation,
    prepare_jobkorea_searchfirm,
    read_login_form,
    submit_login_form_once,
)


URL = "https://www.linkedin.com/login"


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
        self.url = URL

    def current_url(self) -> str:
        return self.url

    def mark_busy(self, _label: str, *, expected_url: str) -> bool:
        assert expected_url == self.url
        self.trace.append("badge")
        return True

    def navigate(self, url: str) -> None:
        self.trace.append(f"navigate:{url}")
        self.url = url

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
        "_form_read_attempts": 1,
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


def test_linkedin_starts_from_primary_linkedin_login_surface() -> None:
    assert login_url_for_channel("linkedin_rps") == "https://www.linkedin.com/login"


def test_linkedin_reuses_same_target_and_navigates_to_primary_login_first() -> None:
    trace: list[str] = []
    tab = Tab(trace)
    tab.url = "https://www.linkedin.com/uas/login-cap"
    login_cap_ref = BrowserTargetRef(
        site="linkedin_rps",
        endpoint="http://127.0.0.1:9225",
        target_id="target-exact",
        websocket_url="ws://target-exact",
        initial_url=tab.url,
    )
    result = run(
        trace,
        tab=tab,
        _target_resolver=lambda *_args, **_kwargs: login_cap_ref,
        _retry_sleep=lambda _seconds: trace.append("wait"),
    )
    assert result["state"] == "AUTHENTICATED"
    assert tab.url == "https://www.linkedin.com/login"
    assert trace.count("navigate:https://www.linkedin.com/login") == 1
    assert trace.count("submit") == 1


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
        _mutation_gate_attempts=1,
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


@pytest.mark.parametrize(
    ("site", "url", "site_context"),
    [
        (
            "saramin",
            "https://www.saramin.co.kr/zf_user/auth?ut=c",
            {"saraminCorporate": True},
        ),
        (
            "jobkorea",
            "https://www.jobkorea.co.kr/Login/Login_Tot.asp",
            {"jobkoreaCorporate": True, "jobkoreaSearchFirm": True},
        ),
        (
            "linkedin_rps",
            "https://www.linkedin.com/login",
            {"linkedinPrimaryLogin": True},
        ),
    ],
)
def test_form_requires_official_surface_same_visible_enabled_form_and_site_context(
    site: str, url: str, site_context: dict[str, bool],
) -> None:
    base = {
        "url": url,
        "bodyPresent": True,
        "selectors": ["#username", "#password", 'button[type="submit"]'],
        "signature": "strict-signature",
        "badgePresent": True,
        "sameForm": True,
        "visible": True,
        "enabled": True,
        "passwordType": True,
        "formMethod": "POST",
        "formAction": url,
        **site_context,
    }

    class FormTab:
        def __init__(self, payload):
            self.payload = payload

        def eval(self, _script):
            return self.payload

    assert read_login_form(FormTab(base), site).valid is True
    for change in (
        {"url": "https://attacker.invalid/login"},
        {"sameForm": False},
        {"visible": False},
        {"enabled": False},
        {"passwordType": False},
        {"formMethod": "GET"},
        {"formAction": "https://attacker.invalid/collect"},
    ):
        assert read_login_form(FormTab({**base, **change}), site).valid is False

    context_key = next(iter(site_context))
    assert read_login_form(
        FormTab({**base, context_key: False}), site,
    ).valid is False


def test_jobkorea_requires_both_corporate_tab_and_searchfirm_toggle() -> None:
    payload = {
        "url": "https://www.jobkorea.co.kr/Login/Login_Tot.asp",
        "bodyPresent": True,
        "selectors": ["#M_ID", "#M_PWD", 'button[type="submit"]'],
        "signature": "jobkorea-strict",
        "badgePresent": True,
        "sameForm": True,
        "visible": True,
        "enabled": True,
        "passwordType": True,
        "formMethod": "POST",
        "formAction": "https://www.jobkorea.co.kr/Login/Login.asp",
        "jobkoreaCorporate": True,
        "jobkoreaSearchFirm": True,
    }

    class FormTab:
        def __init__(self, value):
            self.value = value

        def eval(self, _script):
            return self.value

    assert read_login_form(FormTab(payload), "jobkorea").valid is True
    assert read_login_form(
        FormTab({**payload, "jobkoreaCorporate": False}), "jobkorea",
    ).valid is False
    assert read_login_form(
        FormTab({**payload, "jobkoreaSearchFirm": False}), "jobkorea",
    ).valid is False


def test_jobkorea_preparer_targets_corporate_tab_and_searchfirm_checkbox() -> None:
    scripts: list[str] = []

    class Tab:
        def eval(self, script):
            scripts.append(script)
            return True

    assert prepare_jobkorea_searchfirm(Tab()) is True
    assert 'a[data-m-type="Co"]' in scripts[0]
    assert "#btnCorpMemberType" in scripts[0]
    assert "checkbox.click()" in scripts[0]


def test_temporary_owner_activity_retries_before_mutation_but_never_resubmits() -> None:
    trace: list[str] = []
    attempts = iter(("blocked", "blocked", "allowed", "allowed"))

    def gate():
        trace.append("gate")
        if next(attempts) == "blocked":
            raise ProfileLockError("owner activity blocks raw browser mutation")

    result = run(
        trace,
        _mutation_gate=gate,
        _retry_sleep=lambda _seconds: trace.append("wait"),
        _mutation_gate_attempts=3,
    )

    assert result["state"] == "AUTHENTICATED"
    assert result["submission_count"] == 1
    assert trace.count("wait") == 2
    assert trace.count("submit") == 1


def test_temporarily_incomplete_form_retries_read_only_then_succeeds() -> None:
    trace: list[str] = []
    forms = iter((
        {"valid": False, "fingerprint": "", "url": URL},
        {"valid": False, "fingerprint": "", "url": URL},
        {
            "valid": True,
            "fingerprint": "linkedin-primary-login-v1",
            "url": URL,
            "badge_present": "badge" in trace,
        },
        {
            "valid": True,
            "fingerprint": "linkedin-primary-login-v1",
            "url": URL,
            "badge_present": True,
        },
    ))
    result = run(
        trace,
        _form_reader=lambda *_args, **_kwargs: next(forms),
        _form_read_attempts=3,
        _retry_sleep=lambda _seconds: trace.append("wait"),
    )
    assert result["state"] == "AUTHENTICATED"
    assert result["submission_count"] == 1
    assert trace.count("wait") == 2
    assert trace.count("submit") == 1
