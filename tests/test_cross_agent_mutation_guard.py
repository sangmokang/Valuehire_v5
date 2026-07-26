from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing.mutation_guard import guarded_mutation


NOW = datetime(2026, 7, 26, 3, 0, tzinfo=timezone.utc)


class LocalLock:
    def __init__(self, owned=True):
        self.owned = owned
        self.checks = 0

    def assert_owned(self):
        self.checks += 1
        if not self.owned:
            raise RuntimeError("lost")


def _lease(token="winner", **changes):
    row = {
        "lease_key": "login:macmini:linkedin_rps:account-hash",
        "token": token,
        "owner_pid": 100,
        "owner_job": "job-7",
        "heartbeat_at": (NOW - timedelta(seconds=5)).isoformat(),
        "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
        "released": False,
    }
    row.update(changes)
    return row


def _snap(*, idle=61, portal=True, status="ok"):
    return SimpleNamespace(
        detection_status=status,
        foreground_app="Google Chrome",
        portal_site_active=portal,
        idle_seconds=idle,
        owner_activity_detected=portal is True and idle < 60,
    )


def _run(*, leases=None, snaps=None, token="winner", machine="macmini", **changes):
    rows = iter(leases or [_lease(token), _lease(token)])
    snapshots = iter(snaps or [_snap(), _snap(idle=62)])
    mutations = []
    result = guarded_mutation(
        lease_key="login:macmini:linkedin_rps:account-hash",
        expected_token=token,
        local_lock=LocalLock(),
        central_lease_reader=lambda _key: next(rows),
        owner_snapshot=lambda: next(snapshots),
        command=lambda: mutations.append("command") or "ok",
        now=lambda: NOW,
        sleep=lambda seconds: None,
        machine=machine,
        request_id=changes.get("request_id", "req-7"),
        delegated_for_request_id=changes.get("delegated_for_request_id"),
    )
    return result, mutations


def test_two_agent_race_only_token_owner_mutates_once():
    winner, winner_mutations = _run(token="winner")
    loser, loser_mutations = _run(
        token="loser", leases=[_lease("winner"), _lease("winner")],
    )

    assert winner["decision"]["allowed"] is True
    assert winner["mutation_count"] == 1
    assert winner_mutations == ["command"]
    assert loser["decision"]["reason"] == "LEASE_CONFLICT"
    assert loser["mutation_count"] == 0
    assert loser_mutations == []


def test_token_swap_and_second_idle_deterioration_block_before_command():
    swapped, mutations = _run(leases=[_lease(), _lease("other")])
    assert swapped["decision"]["reason"] == "LEASE_TOKEN_LOST"
    assert mutations == []

    active, mutations = _run(snaps=[_snap(idle=61), _snap(idle=10)])
    assert active["decision"]["reason"] == "HUMAN_ACTIVE"
    assert len(active["decision"]["idle_checks"]) == 2
    assert mutations == []


def test_detection_failure_is_owner_activity_unknown_fail_closed():
    snapshots = iter([RuntimeError("detector down")])

    def broken_snapshot():
        value = next(snapshots)
        raise value

    mutations = []
    result = guarded_mutation(
        lease_key="login:macmini:linkedin_rps:account-hash",
        expected_token="winner",
        local_lock=LocalLock(),
        central_lease_reader=lambda _key: _lease(),
        owner_snapshot=broken_snapshot,
        command=lambda: mutations.append(1),
        now=lambda: NOW,
        sleep=lambda _seconds: None,
        machine="macmini",
        request_id="req-7",
        delegated_for_request_id=None,
    )
    assert result["decision"]["reason"] == "OWNER_ACTIVITY_UNKNOWN"
    assert mutations == []


def test_non_portal_activity_passes_but_portal_idle_under_60_blocks():
    outside, mutations = _run(snaps=[_snap(idle=1, portal=False)] * 2)
    assert outside["decision"]["allowed"] is True
    assert mutations == ["command"]

    portal, mutations = _run(snaps=[_snap(idle=59, portal=True)] * 2)
    assert portal["decision"]["reason"] == "HUMAN_ACTIVE"
    assert mutations == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"expires_at": (NOW - timedelta(seconds=1)).isoformat()}, "LEASE_CONFLICT"),
        ({"heartbeat_at": (NOW - timedelta(seconds=31)).isoformat()}, "LEASE_CONFLICT"),
        ({"released": True}, "LEASE_CONFLICT"),
    ],
)
def test_central_ttl_and_heartbeat_fail_closed(changes, reason):
    result, mutations = _run(leases=[_lease(**changes), _lease(**changes)])
    assert result["decision"]["reason"] == reason
    assert mutations == []


def test_winpc_requires_exact_explicit_delegation_window():
    blocked, mutations = _run(machine="winpc", delegated_for_request_id="old")
    assert blocked["decision"]["reason"] == "LEASE_CONFLICT"
    assert mutations == []
    allowed, mutations = _run(
        machine="winpc", delegated_for_request_id="req-7",
    )
    assert allowed["decision"]["allowed"] is True
    assert mutations == ["command"]


def test_existing_local_lock_is_atomic_and_has_no_stale_delete_path():
    import inspect
    from tools.multi_position_sourcing.portal_worker import ProfileLock

    source = inspect.getsource(ProfileLock._acquire_raw_lease)
    assert "os.mkdir" in source
    assert "FileExistsError" in source
    for banned in ("rmtree", "stale", "unlink"):
        assert banned not in source
