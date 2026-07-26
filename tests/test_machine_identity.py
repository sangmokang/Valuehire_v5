from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing import fleet_heartbeat
from tools.multi_position_sourcing import fleet_worker
from tools.multi_position_sourcing import login_barrier
from tools.multi_position_sourcing.fleet_dispatch import build_fleet_job_payload
from tools.multi_position_sourcing.job_queue import (
    JobQueueClient,
    default_account_key,
    new_job_payload,
)
from tools.multi_position_sourcing.slot_scheduler import (
    Job,
    Slot,
    plan_dispatches,
)

REPO = Path(__file__).resolve().parents[1]


def _identity():
    return importlib.import_module("tools.multi_position_sourcing.machine_identity")


def test_canonical_machine_type_and_alias_table_are_single_source() -> None:
    identity = _identity()
    assert identity.CANONICAL_MACHINE_IDS == ("macmini", "macbook", "winpc")
    assert identity.MACHINE_ID_ALIASES["macbook_pro"] == "macbook"
    assert identity.normalize_machine_id("macbook_pro") == "macbook"
    assert identity.require_machine_id("macbook") == "macbook"


@pytest.mark.parametrize(
    "value",
    ["", "server42", "MACBOOK", " macbook", "macbook ", "MacBook", None],
)
def test_unknown_or_ambiguous_machine_names_raise_structured_error(value) -> None:
    identity = _identity()
    with pytest.raises(identity.MachineIdentityError) as caught:
        identity.normalize_machine_id(value)
    assert caught.value.code in {"invalid_type", "unknown_machine"}
    assert caught.value.field == "machine"


def test_alias_and_canonical_machine_share_one_lock_region() -> None:
    identity = _identity()
    alias = identity.normalize_machine_id("macbook_pro")
    canonical = identity.normalize_machine_id("macbook")
    assert alias == canonical == "macbook"
    assert default_account_key("humansearch", alias) == default_account_key(
        "humansearch", canonical
    )
    with pytest.raises(identity.MachineIdentityError):
        default_account_key("humansearch", "macbook_pro")


def test_storage_boundary_rejects_alias_and_unknown_machine() -> None:
    base = {
        "skill": "humansearch",
        "position_url": "https://app.clickup.com/t/abc",
        "requested_by": "owner",
        "role": "owner",
    }
    assert new_job_payload(machine="macbook_pro", **base) is None
    assert new_job_payload(machine="server42", **base) is None


def test_discord_alias_reaches_queue_as_canonical_machine() -> None:
    payload = build_fleet_job_payload(
        {
            "skill": "humansearch",
            "url": "https://app.clickup.com/t/abc",
            "machine": "macbook_pro",
        },
        requested_by="owner",
        role="owner",
    )
    assert payload is not None
    assert payload["machine"] == "macbook"
    assert payload["account_key"] == "portal:macbook"


def test_unknown_or_missing_discord_machine_never_falls_back() -> None:
    base = {"skill": "humansearch", "url": "https://app.clickup.com/t/abc"}
    assert build_fleet_job_payload(base, requested_by="owner", role="owner") is None
    assert build_fleet_job_payload(
        {**base, "machine": "server42"}, requested_by="owner", role="owner"
    ) is None


def test_discord_queue_and_execution_environment_keep_one_canonical_machine() -> None:
    payload = build_fleet_job_payload(
        {
            "skill": "humansearch",
            "url": "https://app.clickup.com/t/abc",
            "machine": "macbook_pro",
        },
        requested_by="owner",
        role="owner",
    )
    assert payload is not None
    env_machine = fleet_worker.machine_from_env(
        {"VALUEHIRE_MACHINE": "macbook_pro"}
    )
    worker = fleet_worker.FleetWorker(
        env_machine, queue=object(), runner=lambda _prompt, _timeout: ("ok", 0)
    )
    assert payload["machine"] == env_machine == worker.machine == "macbook"


def test_queue_write_and_database_row_use_same_canonical_machine(monkeypatch) -> None:
    payload = build_fleet_job_payload(
        {
            "skill": "humansearch",
            "url": "https://app.clickup.com/t/abc",
            "machine": "macbook_pro",
        },
        requested_by="owner",
        role="owner",
    )
    assert payload is not None
    client = JobQueueClient(
        url="https://queue.example.com",
        key="test-key",
        getaddrinfo=lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("8.8.8.8", 0))
        ],
    )
    writes = []

    def fake_call(method, path, body=None, prefer="return=representation"):
        writes.append((method, path, body, prefer))
        return [{**body, "id": 7}]

    monkeypatch.setattr(client, "_call", fake_call)
    row = client.enqueue(payload)
    assert writes[0][2]["machine"] == row["machine"] == "macbook"


def test_read_compatibility_canonicalizes_legacy_rows_and_status(monkeypatch) -> None:
    client = JobQueueClient(url="https://queue.example.com", key="test-key")
    monkeypatch.setattr(
        client,
        "_call",
        lambda *_args, **_kwargs: [
            {"id": 1, "machine": "macbook_pro", "status": "queued"}
        ],
    )
    assert client.recent()[0]["machine"] == "macbook"
    assert fleet_heartbeat.heartbeat_ages(
        [{"machine": "macbook_pro", "beat_at_epoch": 95}],
        now_epoch=100,
    )["macbook"] == 5
    stalled = fleet_heartbeat.stalled_queued_jobs(
        [
            {
                "id": 1,
                "machine": "macbook_pro",
                "status": "queued",
                "created_at_epoch": 0,
            }
        ],
        now_epoch=1000,
        stall_seconds=10,
    )
    assert stalled[0]["machine"] == "macbook"


def test_heartbeat_and_worker_receipts_never_store_alias() -> None:
    assert fleet_heartbeat.heartbeat_payload(
        "macbook", worker_pid=1, now_iso="2026-07-27T00:00:00Z"
    )["machine"] == "macbook"
    with pytest.raises(ValueError):
        fleet_heartbeat.heartbeat_payload(
            "macbook_pro", worker_pid=1, now_iso="2026-07-27T00:00:00Z"
        )
    assert fleet_worker.machine_from_env(
        {"VALUEHIRE_MACHINE": "macbook_pro"}
    ) == "macbook"


def test_login_receipt_external_boundary_writes_canonical_host(
    tmp_path, monkeypatch
) -> None:
    captured = {}
    monkeypatch.setattr(
        "tools.multi_position_sourcing.browser_evidence.complete_evidence_payload",
        lambda _payload: True,
    )

    def validate(receipt, **_kwargs):
        captured.update(receipt)
        return None

    monkeypatch.setattr(login_barrier, "validate_channel_receipt", validate)
    episode = {
        "status": "authenticated",
        "site": "saramin",
        "endpoint": "http://127.0.0.1:9311",
        "profile_path": str(tmp_path),
        "browser_pid": 1,
        "proof_names": ["account"],
        "evidence": {
            "status": "saved",
            "capture_status": "saved",
            "site": "saramin",
            "task": "login",
            "mode": "evidence",
            "target_id": "T1",
        },
    }
    written = login_barrier.write_channel_receipt_from_episode(
        episode,
        machine="macbook_pro",
        receipt_dir=tmp_path / "receipts",
        now_epoch=1,
    )
    assert written is not None
    assert captured["host"] == "macbook"
    assert json.loads(Path(written).read_text(encoding="utf-8"))["host"] == "macbook"


def test_internal_scheduler_rejects_alias_machine_identity() -> None:
    jobs = [
        Job(
            requester_id="owner",
            job_id=1,
            created_at=1,
            resource_class="browser",
            requirements={},
            requested_machine="macbook_pro",
            account_key="portal:macbook",
        )
    ]
    slots = [
        Slot(
            slot_id="slot-1",
            machine_id="macbook",
            resource_class="browser",
            capabilities={},
            account_key="portal:macbook",
            state="ready",
            fresh=True,
        )
    ]
    with pytest.raises(ValueError, match="machine"):
        plan_dispatches(
            jobs,
            slots,
            requester_states={},
            account_capacities={"portal:macbook": 1},
            account_running={"portal:macbook": 0},
        )


def test_database_contract_blocks_noncanonical_new_rows_without_bulk_rewrite() -> None:
    migration = (
        REPO / "supabase/migrations/20260727090000_machine_identity_contract.sql"
    )
    sql = migration.read_text(encoding="utf-8").lower()
    for column in (
        "fleet_machines_machine_id_canonical_chk",
        "jobs_machine_canonical_chk",
        "jobs_requested_machine_canonical_chk",
        "jobs_assigned_machine_canonical_chk",
        "machine_heartbeats_machine_canonical_chk",
        "account_locks_holder_machine_canonical_chk",
        "browser_slots_machine_id_canonical_chk",
    ):
        assert column in sql
    assert "not valid" in sql
    assert "update public." not in sql


def test_no_machine_identity_copy_can_drift() -> None:
    identity = _identity()
    from tools.multi_position_sourcing import fleet_args
    from tools.multi_position_sourcing import hermes_fleet_bridge

    assert identity.CANONICAL_MACHINE_IDS == tuple(fleet_args.FLEET_MACHINES)
    assert (
        hermes_fleet_bridge.parse_hermes_fleet_args
        is fleet_args.parse_fleet_args
    )


def test_harvest_machine_copy_matches_canonical_source() -> None:
    identity = _identity()
    from tools.multi_position_sourcing.harvest_policy import HARVEST_MACHINES

    assert HARVEST_MACHINES == identity.CANONICAL_MACHINE_IDS


def test_harvest_queue_rejects_alias_internal_machine() -> None:
    identity = _identity()
    from tools.multi_position_sourcing.harvest_runner import (
        build_harvest_queue,
    )

    with pytest.raises(identity.MachineIdentityError):
        build_harvest_queue(
            ("it_ai_data",),
            machines=("macbook_pro",),
        )


def test_harvest_item_rejects_unknown_internal_machine() -> None:
    identity = _identity()
    from tools.multi_position_sourcing.harvest_runner import HarvestItem

    with pytest.raises(identity.MachineIdentityError):
        HarvestItem(
            segment_id="it_ai_data",
            channel="saramin",
            machine="server42",
        )


def test_reservoir_report_rejects_alias_machine() -> None:
    identity = _identity()
    from tools.multi_position_sourcing.reservoir_log import (
        make_reservoir_log_record,
    )

    with pytest.raises(identity.MachineIdentityError):
        make_reservoir_log_record(
            ts="2026-07-27T00:00:00Z",
            run_id="run",
            machine="macbook_pro",
            segment_id="it_ai_data",
            site="saramin",
            line="harvest",
            in_count=1,
            out_count=1,
            dropped_count=0,
            status="ok",
        )
