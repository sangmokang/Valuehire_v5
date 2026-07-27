from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tools.multi_position_sourcing.fleet_route import decide_fleet_route


NOW = datetime(2026, 7, 26, 3, 0, tzinfo=timezone.utc)
MACHINES = ("macmini", "macbook_pro", "winpc")


def _snapshot(*, complete=True, targets=()):
    reports = {
        machine: {
            "machine_id": machine,
            "inventory": [{
                "targets": [
                    {
                        "target_id": f"{machine}-page",
                        "type": "page",
                        "site": site,
                        "marker_names": list(markers),
                    }
                    for host, site, markers in targets if host == machine
                ]
            }],
        }
        for machine in MACHINES
    }
    return {
        "snapshot_id": "fleet_exact",
        "requested_at": NOW.isoformat(),
        "complete": complete,
        "reports_by_machine": reports,
    }


def _receipt(host, *, site="saramin", age=5, state="AUTHENTICATED"):
    return {
        "schema_version": 1,
        "channel": site,
        "state": state,
        "ready": state == "AUTHENTICATED",
        "host": host,
        "target_id": f"{host}-receipt",
        "last_verified_at": (NOW - timedelta(seconds=age)).isoformat(),
    }


def _decide(
    *,
    site="saramin",
    requested_machine=None,
    delegated_for_request_id=None,
    receipts=(),
    targets=(),
    defaults=None,
    complete=True,
    lookup_error=False,
):
    request = {
        "request_id": "req-5",
        "site": site,
        "requested_machine": requested_machine,
        "delegated_for_request_id": delegated_for_request_id,
        "lookup_error": lookup_error,
    }
    return decide_fleet_route(
        normalized_request=request,
        fleet_snapshot=_snapshot(complete=complete, targets=targets),
        login_receipts=list(receipts),
        site_role_defaults=defaults or {},
    )


@pytest.mark.parametrize(
    ("kwargs", "selected", "reason"),
    [
        (
            {"requested_machine": "macbook_pro", "defaults": {"saramin": "macmini"}},
            "macbook_pro", "EXPLICIT_MACHINE",
        ),
        (
            {"receipts": [_receipt("winpc")], "defaults": {"saramin": "macmini"}},
            "winpc", "FRESH_RECEIPT",
        ),
        (
            {
                "targets": [("macbook_pro", "saramin", ["gnb_profile_badge"])],
                "defaults": {"saramin": "macmini"},
            },
            "macbook_pro", "AUTHENTICATED_EXACT_TARGET",
        ),
        (
            {"defaults": {"saramin": "macmini"}},
            "macmini", "SITE_ROLE_DEFAULT",
        ),
        ({}, None, "NO_READY_MACHINE"),
    ],
)
def test_route_priority_truth_table(kwargs, selected, reason):
    decision = _decide(**kwargs)
    assert decision["selected_machine"] == selected
    assert decision["reason"] == reason
    assert decision["snapshot_id"] == "fleet_exact"
    assert isinstance(decision["evidence_refs"], list)


def test_priority_pairs_and_linkedin_existing_host_special_case():
    receipt = _receipt("winpc")
    assert _decide(
        requested_machine="macbook_pro", receipts=[receipt],
    )["selected_machine"] == "macbook_pro"
    assert _decide(
        receipts=[receipt],
        targets=[("macbook_pro", "saramin", ["gnb_profile_badge"])],
    )["selected_machine"] == "winpc"

    linkedin_receipt = _receipt("winpc", site="linkedin_rps")
    decision = _decide(
        site="linkedin_rps",
        requested_machine="macmini",
        receipts=[linkedin_receipt],
    )
    assert decision["selected_machine"] == "macmini"
    assert decision["reason"] == "EXPLICIT_MACHINE"


def test_explicit_winpc_requires_current_request_delegation():
    assert _decide(
        requested_machine="winpc", delegated_for_request_id="req-5",
    )["selected_machine"] == "winpc"
    assert _decide(
        requested_machine="winpc", delegated_for_request_id="old",
    )["reason"] == "INVALID_MACHINE"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"complete": False, "site": "linkedin_rps"}, "DISCOVERY_INCOMPLETE"),
        ({"lookup_error": True}, "DISCOVERY_INCOMPLETE"),
        ({"requested_machine": "ghost"}, "INVALID_MACHINE"),
        (
            {"receipts": [_receipt("macmini", age=1801)]},
            "STALE_RECEIPT",
        ),
        (
            {"receipts": [_receipt("macmini", state="AUTH_CONFLICT")]},
            "AUTH_CONFLICT",
        ),
        (
            {"receipts": [{**_receipt("macmini"), "schema_version": 99}]},
            "ROUTE_AMBIGUOUS",
        ),
    ],
)
def test_fail_closed_reasons(kwargs, reason):
    decision = _decide(**kwargs)
    assert decision["selected_machine"] is None
    assert decision["reason"] == reason


@pytest.mark.parametrize(
    ("site", "reason"),
    [
        ("linkedin_rps", "AUTH_CONFLICT"),
        ("saramin", "ROUTE_AMBIGUOUS"),
    ],
)
def test_equal_priority_different_receipt_hosts_are_ambiguous(site, reason):
    decision = _decide(
        site=site,
        receipts=[_receipt("macmini", site=site), _receipt("winpc", site=site)],
    )
    assert decision["selected_machine"] is None
    assert decision["reason"] == reason


def test_identical_inputs_are_side_effect_free_and_deterministic():
    kwargs = {
        "site": "linkedin_rps",
        "receipts": [_receipt("macbook_pro", site="linkedin_rps")],
    }
    assert _decide(**kwargs) == _decide(**kwargs)
