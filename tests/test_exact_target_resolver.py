from __future__ import annotations

import hashlib
import json

import pytest

from tools.multi_position_sourcing.exact_target import (
    ExactTargetError,
    exact_target_session_guard_args,
    inventory_hash,
    resolve_exact_target,
)


def _target(target_id, *, site="linkedin_rps", markers=(), url=None):
    return {
        "target_id": target_id,
        "type": "page",
        "sanitized_url": url or {
            "linkedin_rps": "https://www.linkedin.com/talent/home",
            "saramin": "https://www.saramin.co.kr/zf_user/member/talent-manage",
        }[site],
        "site": site,
        "marker_names": list(markers),
    }


def _browser(pid, profile, endpoint, targets, *, live=True):
    return {
        "browser_pid": pid,
        "executable": "Google Chrome",
        "profile_path": profile,
        "declared_port": int(endpoint.rsplit(":", 1)[1]),
        "listen_pid": pid,
        "endpoint": endpoint,
        "endpoint_live": live,
        "targets": targets,
        "issues": [],
    }


def _resolve(inventory, *, observations=None, **changes):
    args = {
        "machine": "macmini",
        "site": "linkedin_rps",
        "target_id": None,
        "expected_profile": None,
        "expected_role": None,
        "browser_inventory": inventory,
        "expected_inventory_hash": inventory_hash(inventory),
        "endpoint_observations": observations or {
            browser["endpoint"]: {"targets": browser["targets"]}
            for browser in inventory if browser["endpoint"]
        },
    }
    args.update(changes)
    return resolve_exact_target(**args)


def test_one_authenticated_marker_target_wins_and_returns_attach_record_only():
    inventory = [
        _browser(10, "/profiles/a", "http://127.0.0.1:9225", [
            _target("form", markers=["verified_login_form"]),
            _target("auth", markers=["authenticated_shell"]),
        ])
    ]

    target = _resolve(inventory)

    assert target == {
        "machine": "macmini",
        "browser_pid": 10,
        "profile_path": "/profiles/a",
        "cdp_endpoint": "http://127.0.0.1:9225",
        "target_id": "auth",
        "site": "linkedin_rps",
        "sanitized_url": "https://www.linkedin.com/talent/home",
        "selection_reason": "FRESH_AUTH_MARKER",
        "inventory_hash": inventory_hash(inventory),
    }
    assert set(target).isdisjoint({"websocket_url", "page", "browser", "cookies"})


def test_verified_login_form_then_exact_profile_priority():
    inventory = [
        _browser(10, "/profiles/a", "http://127.0.0.1:9225", [
            _target("profile-only"),
        ]),
        _browser(20, "/profiles/b", "http://127.0.0.1:9226", [
            _target("form", markers=["verified_login_form"]),
        ]),
    ]
    assert _resolve(
        inventory, expected_profile="/profiles/a",
    )["target_id"] == "form"

    no_form = [inventory[0]]
    selected = _resolve(no_form, expected_profile="/profiles/a")
    assert selected["target_id"] == "profile-only"
    assert selected["selection_reason"] == "EXACT_PROFILE"


@pytest.mark.parametrize(
    ("inventory", "reason"),
    [
        ([], "TARGET_MISSING"),
        (
            [_browser(10, "/a", "http://127.0.0.1:9225", [
                _target("a", markers=["authenticated_shell"]),
                _target("b", markers=["authenticated_shell"]),
            ])],
            "TARGET_AMBIGUOUS",
        ),
        (
            [_browser(10, "/a", "http://127.0.0.1:9225", [
                _target("wrong", site="saramin", markers=["authenticated_shell"]),
            ])],
            "TARGET_SITE_MISMATCH",
        ),
    ],
)
def test_zero_two_and_wrong_site_fail_closed(inventory, reason):
    with pytest.raises(ExactTargetError, match=reason):
        _resolve(inventory)


def test_explicit_target_id_revalidates_site_profile_and_live_identity():
    inventory = [_browser(10, "/profiles/a", "http://127.0.0.1:9225", [
        _target("exact", markers=["authenticated_shell"]),
    ])]
    with pytest.raises(ExactTargetError, match="TARGET_SITE_MISMATCH"):
        _resolve(inventory, target_id="exact", site="saramin")
    with pytest.raises(ExactTargetError, match="TARGET_IDENTITY_CHANGED"):
        _resolve(inventory, target_id="exact", expected_profile="/profiles/other")
    with pytest.raises(ExactTargetError, match="TARGET_IDENTITY_CHANGED"):
        _resolve(
            inventory,
            target_id="exact",
            observations={"http://127.0.0.1:9225": {"targets": []}},
        )


def test_endpoint_recheck_and_inventory_hash_conflicts_fail_closed():
    inventory = [_browser(10, "/a", "http://127.0.0.1:9225", [
        _target("exact", markers=["authenticated_shell"]),
    ])]
    with pytest.raises(ExactTargetError, match="ENDPOINT_CONFLICT"):
        _resolve(inventory, observations={})
    with pytest.raises(ExactTargetError, match="TARGET_IDENTITY_CHANGED"):
        _resolve(inventory, expected_inventory_hash="0" * 64)


def test_same_url_in_different_profiles_is_ambiguous_without_exact_profile():
    inventory = [
        _browser(10, "/a", "http://127.0.0.1:9225", [_target("same-a")]),
        _browser(20, "/b", "http://127.0.0.1:9226", [_target("same-b")]),
    ]
    with pytest.raises(ExactTargetError, match="TARGET_AMBIGUOUS"):
        _resolve(inventory)
    assert _resolve(inventory, expected_profile="/b")["target_id"] == "same-b"


def test_session_guard_wiring_passes_only_exact_target_id_and_rechecks_identity():
    inventory = [_browser(10, "/a", "http://127.0.0.1:9225", [
        _target("exact", markers=["authenticated_shell"]),
    ])]
    exact = _resolve(inventory)

    assert exact_target_session_guard_args(exact, agent="Codex") == [
        "human-auth", "--site", "linkedin_rps", "--agent", "Codex",
        "--target-id", "exact",
    ]
    source = json.dumps(exact, sort_keys=True).encode()
    assert hashlib.sha256(source).hexdigest()
