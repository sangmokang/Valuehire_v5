from __future__ import annotations

import inspect
import json

import pytest

from tools.multi_position_sourcing.linkedin_session_guardian import (
    decide_linkedin_session,
)
from tools.multi_position_sourcing.fleet_route import decide_fleet_route
from tools.multi_position_sourcing.session_guard import run_auto_login_episode


MACHINES = ("macmini", "macbook_pro", "winpc")


def observations(states, *, complete=True, missing=()):
    return {
        "request_id": "request-12",
        "complete": complete,
        "eligible_machines": list(MACHINES),
        "missing_machines": list(missing),
        "observations_by_machine": {
            machine: {
                "state": states.get(machine, "AUTH_LOST"),
                "ready": True,
                "target_id": f"{machine}-target",
                "evidence_ref": f"snapshot:{machine}",
            }
            for machine in MACHINES
            if machine not in missing
        },
    }


@pytest.mark.parametrize(
    ("states", "selected", "state", "host", "reason", "mutation"),
    [
        (
            {}, "macmini", "LOGIN_ALLOWED", None,
            "NO_AUTHENTICATED_HOST", True,
        ),
        (
            {"winpc": "AUTHENTICATED"}, "macmini", "SESSION_REUSE",
            "winpc", "EXISTING_AUTHENTICATED_HOST", False,
        ),
        (
            {"macmini": "AUTHENTICATED", "winpc": "AUTHENTICATED"},
            "macmini", "AUTH_CONFLICT", None,
            "MULTIPLE_AUTHENTICATED_HOSTS", False,
        ),
    ],
)
def test_zero_one_two_authenticated_host_truth_table(
    states, selected, state, host, reason, mutation
) -> None:
    decision = decide_linkedin_session(
        request_id="request-12",
        fleet_observations=observations(states),
        selected_machine=selected,
    )
    assert decision == {
        "state": state,
        "session_host": host,
        "reason": reason,
        "evidence_refs": decision["evidence_refs"],
        "login_mutation_allowed": mutation,
    }
    assert all(ref.startswith("snapshot:") for ref in decision["evidence_refs"])


@pytest.mark.parametrize(
    ("payload", "selected", "state", "reason"),
    [
        (
            observations({}, complete=False),
            "macmini", "DISCOVERY_INCOMPLETE", "DISCOVERY_INCOMPLETE",
        ),
        (
            observations({}, missing=("winpc",)),
            "macmini", "DISCOVERY_INCOMPLETE", "DISCOVERY_INCOMPLETE",
        ),
        (
            observations({"winpc": "AUTH_CONFLICT"}),
            "macmini", "AUTH_CONFLICT", "MULTIPLE_SIGN_IN",
        ),
        (
            observations({}),
            "ghost", "SESSION_HOST_UNREADY", "SELECTED_MACHINE_UNREADY",
        ),
        (
            observations({"winpc": "AUTH_UNKNOWN"}),
            "macmini", "DISCOVERY_INCOMPLETE", "DISCOVERY_INCOMPLETE",
        ),
        (
            observations({"macmini": "HUMAN_AUTH_REQUIRED"}),
            "macmini", "SESSION_HOST_UNREADY", "HUMAN_AUTH_PENDING",
        ),
    ],
)
def test_incomplete_conflict_and_unready_are_fail_closed(
    payload, selected, state, reason
) -> None:
    decision = decide_linkedin_session(
        request_id="request-12",
        fleet_observations=payload,
        selected_machine=selected,
    )
    assert decision["state"] == state
    assert decision["reason"] == reason
    assert decision["login_mutation_allowed"] is False


def test_authenticated_but_unready_host_is_not_reused() -> None:
    payload = observations({"winpc": "AUTHENTICATED"})
    payload["observations_by_machine"]["winpc"]["ready"] = False
    decision = decide_linkedin_session(
        request_id="request-12",
        fleet_observations=payload,
        selected_machine="macmini",
    )
    assert decision["state"] == "SESSION_HOST_UNREADY"
    assert decision["session_host"] == "winpc"
    assert decision["login_mutation_allowed"] is False


def test_guardian_never_echoes_cookie_material_or_defines_takeover_actions() -> None:
    payload = observations({})
    payload["observations_by_machine"]["macmini"]["cookie"] = "cookie-secret"
    payload["observations_by_machine"]["winpc"]["session_token"] = "token-secret"
    decision = decide_linkedin_session(
        request_id="request-12",
        fleet_observations=payload,
        selected_machine="macmini",
    )
    encoded = json.dumps(decision) + inspect.getsource(decide_linkedin_session)
    for forbidden in (
        "cookie-secret", "token-secret", "Continue", "Confirm",
        "terminate-session", "Network.getCookies", "Storage.getCookies",
    ):
        assert forbidden not in encoded


def test_auto_login_rechecks_guardian_before_owner_browser_or_credentials() -> None:
    result = run_auto_login_episode(
        "linkedin_rps",
        agent="Codex",
        linkedin_request_id="request-12",
        linkedin_fleet_observations=observations({}, complete=False),
        selected_machine="macmini",
        _owner_snapshot=lambda: pytest.fail("must stop before owner probe"),
        _credential_provider=pytest.fail,
        _target_resolver=lambda *_args, **_kwargs: pytest.fail(
            "must stop before browser resolution"
        ),
    )
    assert result["state"] == "DISCOVERY_INCOMPLETE"
    assert result["submission_count"] == 0


def test_guardian_is_wired_before_enqueue_route_and_auto_login_mutation() -> None:
    assert "decide_linkedin_session" in inspect.getsource(decide_fleet_route)
    source = inspect.getsource(run_auto_login_episode)
    assert source.index("decide_linkedin_session") < source.index("owner_snapshot()")
    assert source.index("decide_linkedin_session") < source.index("mark_busy")
