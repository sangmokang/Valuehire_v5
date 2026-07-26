from datetime import datetime, timedelta, timezone

import pytest

from tools.multi_position_sourcing.fleet_heartbeat import (
    CAPABILITY_ALLOWLIST,
    evaluate_machine_readiness,
    readiness_candidates,
)


NOW = datetime(2026, 7, 26, 3, 0, tzinfo=timezone.utc)


def machine(
    machine_id="macmini",
    *,
    platform="macos",
    aliases=(),
    capabilities=("linkedin_rps",),
    heartbeat=None,
    agent_version="1.2.3",
    delegated_for_request_id=None,
):
    return {
        "machine_id": machine_id,
        "platform": platform,
        "hostname_aliases": list(aliases),
        "agent_version": agent_version,
        "capabilities": list(capabilities),
        "last_heartbeat_at": heartbeat or (NOW - timedelta(seconds=10)).isoformat(),
        "delegated_for_request_id": delegated_for_request_id,
    }


def test_readiness_accepts_only_contract_shape_and_allowlisted_capability():
    result = evaluate_machine_readiness(
        machine(), required_capability="linkedin_rps", request_id="req-1", now=NOW
    )

    assert result == {
        "registered": True,
        "online": True,
        "heartbeat_age_seconds": 10,
        "capabilities": ["linkedin_rps"],
        "delegation_valid": True,
        "reason": None,
    }
    assert CAPABILITY_ALLOWLIST == frozenset({"saramin", "jobkorea", "linkedin_rps"})
    assert set(result) == {
        "registered", "online", "heartbeat_age_seconds", "capabilities",
        "delegation_valid", "reason",
    }


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (machine(machine_id="ghost"), "UNREGISTERED_MACHINE"),
        (machine(platform="linux"), "UNREGISTERED_MACHINE"),
        (machine(agent_version=""), "UNREGISTERED_MACHINE"),
        (
            machine(heartbeat=(NOW - timedelta(seconds=301)).isoformat()),
            "STALE_HEARTBEAT",
        ),
        (
            machine(heartbeat=(NOW + timedelta(seconds=1)).isoformat()),
            "CLOCK_SKEW",
        ),
        (
            machine(heartbeat="2026-07-26T02:59:50"),
            "CLOCK_SKEW",
        ),
        (
            machine(heartbeat="2026-07-26T11:59:50+09:00"),
            "CLOCK_SKEW",
        ),
        (
            machine(capabilities=("browser_cookie",)),
            "CAPABILITY_MISSING",
        ),
        (
            machine(capabilities=("saramin",)),
            "CAPABILITY_MISSING",
        ),
    ],
)
def test_readiness_fails_closed(row, reason):
    result = evaluate_machine_readiness(
        row, required_capability="linkedin_rps", request_id="req-1", now=NOW
    )
    assert result["online"] is False
    assert result["reason"] == reason


def test_winpc_delegation_is_exact_and_cannot_be_reused():
    row = machine(
        "winpc",
        platform="windows",
        delegated_for_request_id="req-1",
    )
    assert evaluate_machine_readiness(
        row, required_capability="linkedin_rps", request_id="req-1", now=NOW
    )["online"] is True

    wrong = evaluate_machine_readiness(
        row, required_capability="linkedin_rps", request_id="req-2", now=NOW
    )
    missing = evaluate_machine_readiness(
        {**row, "delegated_for_request_id": None},
        required_capability="linkedin_rps",
        request_id="req-1",
        now=NOW,
    )
    assert wrong["reason"] == "WINPC_NOT_DELEGATED"
    assert missing["reason"] == "WINPC_NOT_DELEGATED"


def test_alias_collision_blocks_every_colliding_candidate():
    rows = [
        machine("macmini", aliases=("shared-host",)),
        machine("macbook_pro", aliases=("shared-host",)),
    ]
    ready, rejected = readiness_candidates(
        rows,
        required_capability="linkedin_rps",
        request_id="req-1",
        now=NOW,
    )
    assert ready == []
    assert [item["readiness"]["reason"] for item in rejected] == [
        "MACHINE_ALIAS_CONFLICT",
        "MACHINE_ALIAS_CONFLICT",
    ]


def test_only_ready_rows_reach_existing_selector_input():
    rows = [
        machine("macmini"),
        machine(
            "winpc",
            platform="windows",
            delegated_for_request_id="old-request",
        ),
        machine(
            "macbook_pro",
            heartbeat=(NOW - timedelta(seconds=999)).isoformat(),
        ),
    ]
    ready, rejected = readiness_candidates(
        rows,
        required_capability="linkedin_rps",
        request_id="current-request",
        now=NOW,
    )
    assert [row["machine_id"] for row in ready] == ["macmini"]
    assert {row["readiness"]["reason"] for row in rejected} == {
        "WINPC_NOT_DELEGATED",
        "STALE_HEARTBEAT",
    }


def test_dispatch_passes_request_id_and_refuses_empty_ready_set(monkeypatch):
    from tools.multi_position_sourcing import fleet_dispatch

    observed = {}

    class Queue:
        def machine_readiness_candidates(self):
            return [machine("winpc", platform="windows", delegated_for_request_id="evt-7")]

    def fake_pick(rows, *, now_epoch):
        observed["rows"] = rows
        return rows[0]["machine_id"] if rows else ""

    monkeypatch.setattr(
        "tools.multi_position_sourcing.fleet_heartbeat.pick_linkedin_machine",
        fake_pick,
    )
    assert fleet_dispatch._route_linkedin_machine(Queue(), request_id="evt-7") == "winpc"
    assert observed["rows"][0]["readiness"]["online"] is True

    class EmptyQueue:
        def machine_readiness_candidates(self):
            return []

    assert fleet_dispatch._route_linkedin_machine(EmptyQueue(), request_id="evt-7") == ""
