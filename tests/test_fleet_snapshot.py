from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tools.multi_position_sourcing.fleet_snapshot import (
    FleetSnapshotError,
    aggregate_fleet_snapshot,
    seal_browser_report,
)


NOW = datetime(2026, 7, 26, 3, 0, tzinfo=timezone.utc)
EXPECTED = ["macmini", "macbook_pro", "winpc"]


def _readiness(machine_id: str) -> dict:
    return {
        "machine_id": machine_id,
        "registered": True,
        "online": True,
        "capabilities": ["linkedin_rps"],
        "reason": None,
    }


def _report(machine_id: str, *, request_id: str = "req-4", captured_at=None) -> dict:
    payload = {
        "machine_id": machine_id,
        "captured_at": (captured_at or (NOW - timedelta(seconds=5))).isoformat(),
        "schema_version": 1,
        "request_id": request_id,
        "inventory": [
            {
                "browser_pid": 100,
                "profile_path": f"/profiles/{machine_id}",
                "endpoint": "http://127.0.0.1:9225",
                "targets": [{
                    "target_id": "page-1",
                    "type": "page",
                    "sanitized_url": "https://www.linkedin.com/talent/home",
                    "site": "linkedin_rps",
                    "marker_names": ["authenticated_shell"],
                }],
                "issues": [],
            }
        ],
    }
    return {"source_machine_id": machine_id, "payload": seal_browser_report(payload)}


def _aggregate(reports, **changes):
    args = {
        "expected_machine_ids": EXPECTED,
        "machine_readiness": [_readiness(machine) for machine in EXPECTED],
        "reports": reports,
        "request_id": "req-4",
        "requested_at": NOW,
        "required_capability": "linkedin_rps",
    }
    args.update(changes)
    return aggregate_fleet_snapshot(**args)


def test_three_machine_snapshot_is_complete_deterministic_and_secret_free():
    reports = [_report(machine) for machine in reversed(EXPECTED)]
    first = _aggregate(reports)
    second = _aggregate(list(reversed(reports)))

    assert first == second
    assert first["complete"] is True
    assert first["missing_machines"] == []
    assert first["stale_machines"] == []
    assert first["blocking_reasons"] == []
    assert list(first["reports_by_machine"]) == EXPECTED
    assert first["snapshot_id"].startswith("fleet_")
    assert len(first["sanitized_hash"]) == 64
    assert "integrity_hash" not in repr(first["reports_by_machine"])
    assert "secret" not in repr(first)


def test_one_machine_timeout_and_linkedin_partial_report_never_complete():
    snapshot = _aggregate([_report("macmini"), _report("macbook_pro")])

    assert snapshot["complete"] is False
    assert snapshot["missing_machines"] == ["winpc"]
    assert snapshot["stale_machines"] == []
    assert snapshot["blocking_reasons"] == ["DISCOVERY_INCOMPLETE"]


@pytest.mark.parametrize(
    ("captured_at", "expected_stale"),
    [
        (NOW - timedelta(seconds=121), ["macmini"]),
        (NOW + timedelta(seconds=1), ["macmini"]),
    ],
)
def test_stale_and_future_reports_fail_closed(captured_at, expected_stale):
    snapshot = _aggregate([
        _report("macmini", captured_at=captured_at),
        _report("macbook_pro"),
        _report("winpc"),
    ])

    assert snapshot["complete"] is False
    assert snapshot["stale_machines"] == expected_stale
    assert "REPORT_STALE" in snapshot["blocking_reasons"]
    assert "macmini" not in snapshot["reports_by_machine"]


def test_past_request_report_is_not_reused():
    snapshot = _aggregate([
        _report("macmini", request_id="old"),
        _report("macbook_pro"),
        _report("winpc"),
    ])

    assert snapshot["complete"] is False
    assert snapshot["missing_machines"] == ["macmini"]


def test_host_spoof_and_schema_mismatch_are_explicit():
    spoofed = _report("macmini")
    spoofed["source_machine_id"] = "winpc"
    with pytest.raises(FleetSnapshotError, match="REPORT_HOST_MISMATCH"):
        _aggregate([spoofed])

    wrong_schema = _report("macmini")
    wrong_schema["payload"]["schema_version"] = 2
    wrong_schema["payload"] = seal_browser_report(
        {k: v for k, v in wrong_schema["payload"].items() if k != "integrity_hash"}
    )
    with pytest.raises(FleetSnapshotError, match="REPORT_SCHEMA_MISMATCH"):
        _aggregate([wrong_schema])


def test_duplicate_identical_report_is_idempotent_but_different_payload_conflicts():
    first = _report("macmini")
    assert _aggregate([first, first])["missing_machines"] == [
        "macbook_pro", "winpc",
    ]

    different = _report("macmini", captured_at=NOW - timedelta(seconds=4))
    with pytest.raises(FleetSnapshotError, match="SNAPSHOT_CONFLICT"):
        _aggregate([first, different])


def test_integrity_tampering_is_snapshot_conflict():
    tampered = _report("macmini")
    tampered["payload"]["inventory"][0]["browser_pid"] = 999

    with pytest.raises(FleetSnapshotError, match="SNAPSHOT_CONFLICT"):
        _aggregate([tampered])


def test_queue_status_store_wiring_uses_exact_snapshot_id():
    from tools.multi_position_sourcing.job_queue import JobQueueClient

    calls = []
    client = JobQueueClient("https://example.supabase.co", "key")
    client._call = lambda *args: calls.append(args) or [{"accepted": True}]

    sealed = _report("macmini")["payload"]
    assert client.publish_browser_inventory(
        "macmini", sealed,
    ) == [{"accepted": True}]
    assert client.browser_inventory_reports("req-4") == [{"accepted": True}]
    assert calls == [
        (
            "POST",
            "/rpc/record_browser_inventory",
            {"p_source_machine_id": "macmini", "p_report": sealed},
        ),
        (
            "GET",
            "/fleet_browser_inventory"
            "?request_id=eq.req-4&select=source_machine_id,report&order=source_machine_id",
        ),
    ]


def test_status_store_is_sanitized_and_conflict_safe():
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[1]
        / "supabase/migrations/20260726100000_fleet_browser_inventory.sql"
    ).read_text(encoding="utf-8").lower()

    assert "create table public.fleet_browser_inventory" in sql
    assert "unique (request_id, source_machine_id)" in sql
    assert "record_browser_inventory" in sql
    assert "integrity_hash = excluded.integrity_hash" in sql
    assert "cookie" in sql and "password" in sql and "websocketdebuggerurl" in sql
    assert "grant select on table public.fleet_browser_inventory to service_role" in sql
    assert "to anon" not in sql


def test_status_store_migration_runs_on_postgres16_and_is_idempotent():
    import psycopg
    from psycopg.types.json import Jsonb
    from test_fleet_slot_schema_postgres import (
        MIGRATIONS,
        TARGET_MIGRATION,
        _apply,
        _apply_base,
        _create_roles,
        _drop_database,
        _new_database,
        _postgres_server,
    )

    migration = MIGRATIONS / "20260726100000_fleet_browser_inventory.sql"
    with _postgres_server() as admin_dsn:
        _create_roles(admin_dsn)
        database, dsn = _new_database(admin_dsn)
        try:
            with psycopg.connect(dsn, autocommit=True) as connection:
                _apply_base(connection)
                _apply(connection, TARGET_MIGRATION)
                _apply(connection, migration)
                assert connection.execute(
                    "select has_table_privilege("
                    "'service_role','public.fleet_browser_inventory','select')"
                ).fetchone()[0] is True
                sealed = _report("macmini")["payload"]
                first = connection.execute(
                    "select * from public.record_browser_inventory(%s, %s)",
                    ("macmini", Jsonb(sealed)),
                ).fetchone()
                second = connection.execute(
                    "select * from public.record_browser_inventory(%s, %s)",
                    ("macmini", Jsonb(sealed)),
                ).fetchone()
                assert first == second == (True, sealed["integrity_hash"])

                conflicting = _report(
                    "macmini", captured_at=NOW - timedelta(seconds=4)
                )["payload"]
                with pytest.raises(psycopg.errors.RaiseException):
                    connection.execute(
                        "select * from public.record_browser_inventory(%s, %s)",
                        ("macmini", Jsonb(conflicting)),
                    )
                stored = connection.execute(
                    "select report from public.fleet_browser_inventory"
                ).fetchone()[0]
                assert "secret" not in repr(stored)
        finally:
            _drop_database(admin_dsn, database)


def test_sealing_re_sanitizes_url_endpoint_and_extra_secret_fields():
    raw = _report("macmini")["payload"]
    raw.pop("integrity_hash")
    raw["inventory"][0]["endpoint"] = "http://10.0.0.8:9225"
    raw["inventory"][0]["targets"][0]["sanitized_url"] = (
        "https://user:secret@www.linkedin.com/talent/home?token=secret#private"
    )
    raw["inventory"][0]["cookie"] = "secret"

    sealed = seal_browser_report(raw)

    assert sealed["inventory"][0]["endpoint"] is None
    assert sealed["inventory"][0]["targets"][0]["sanitized_url"] == (
        "https://www.linkedin.com/talent/home"
    )
    assert "secret" not in repr(sealed)
