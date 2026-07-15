"""Issue #126 contract tests against a disposable PostgreSQL 16 server."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import uuid

import psycopg
from psycopg import sql
import pytest

from tools.multi_position_sourcing.job_queue import claim_next_job_payload, new_job_payload

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"
BASE_MIGRATIONS = (
    "20260711_fleet_jobs_queue.sql",
    "20260711_fleet_heartbeat.sql",
    "20260713_fleet_job_idempotency.sql",
    "20260715_fleet_linkedin_routing.sql",
    "20260715233000_fleet_account_pause_barrier.sql",
)
TARGET_MIGRATION = MIGRATIONS / "20260716090000_fleet_dynamic_machine_slots.sql"
LOCAL_PG16 = Path("/opt/homebrew/opt/postgresql@16/bin")


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


def _program(name: str) -> str:
    local = LOCAL_PG16 / name
    found = str(local) if local.is_file() and os.access(local, os.X_OK) else shutil.which(name)
    if not found:
        pytest.fail(
            f"PostgreSQL 16 실행기 {name!r}를 찾지 못했습니다: {local}. "
            "실제 DB 검사는 skip하지 않습니다."
        )
    return found


@contextmanager
def _postgres_server():
    external_dsn = os.environ.get("TEST_DATABASE_URL")
    if external_dsn:
        with psycopg.connect(external_dsn, autocommit=True) as probe:
            version = str(probe.execute("show server_version_num").fetchone()[0])
            assert version.startswith("16"), f"PostgreSQL 16이 필요하지만 {version}입니다"
        yield external_dsn
        return

    initdb, pg_ctl = (_program(name) for name in ("initdb", "pg_ctl"))
    with tempfile.TemporaryDirectory(prefix="valuehire-pg16-") as temporary:
        root = Path(temporary)
        data, socket_dir = root / "data", root / "socket"
        socket_dir.mkdir()
        port = _free_port()
        subprocess.run(
            [
                initdb,
                "-D",
                str(data),
                "-A",
                "trust",
                "-U",
                "postgres",
                "--no-locale",
                "--encoding=UTF8",
            ],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            [
                pg_ctl,
                "-D",
                str(data),
                "-l",
                str(root / "postgres.log"),
                "-o",
                f"-F -p {port} -k {socket_dir}",
                "-w",
                "start",
            ],
            check=True, capture_output=True, text=True,
        )
        try:
            yield f"host={socket_dir} port={port} user=postgres dbname=postgres"
        finally:
            subprocess.run(
                [pg_ctl, "-D", str(data), "-m", "fast", "-w", "stop"],
                check=True, capture_output=True, text=True,
            )


def _create_roles(admin_dsn: str) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        for role in ("anon", "authenticated", "service_role"):
            conn.execute(
                sql.SQL(
                    "do $$ begin create role {} nologin; "
                    "exception when duplicate_object then null; end $$"
                ).format(sql.Identifier(role))
            )


def _new_database(admin_dsn: str) -> tuple[str, str]:
    name = f"fleet_slot_{uuid.uuid4().hex}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    info = psycopg.conninfo.conninfo_to_dict(admin_dsn)
    info["dbname"] = name
    return name, psycopg.conninfo.make_conninfo(**info)


def _drop_database(admin_dsn: str, name: str) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(name)))


def _apply(conn: psycopg.Connection, path: Path, *, suffix: str = "") -> None:
    statement = path.read_text(encoding="utf-8") + suffix
    with conn.transaction():
        conn.execute(statement)


def _apply_base(conn: psycopg.Connection) -> None:
    for migration in BASE_MIGRATIONS:
        _apply(conn, MIGRATIONS / migration)


def _seed_legacy_fixture(conn: psycopg.Connection) -> dict[str, int]:
    for index, machine in enumerate(("macmini", "macbook", "winpc"), start=1):
        conn.execute(
            "select * from public.record_heartbeat(%s, %s, %s)",
            (machine, 100 + index, index == 1),
        )
    ids = {}
    for machine in ("macmini", "macbook", "winpc"):
        ids[machine] = conn.execute(
            """insert into public.jobs
               (machine, skill, position_url, requested_by, role, account_key)
               values (%s, 'humansearch', 'https://example.com/job',
                       'fixture-user', 'owner', %s) returning id""",
            (machine, f"portal:{machine}"),
        ).fetchone()[0]
    assert conn.execute("select id from public.claim_next_job('macmini')").fetchone()[0] == ids["macmini"]
    return ids


def _snapshot(conn: psycopg.Connection):
    heartbeats = conn.execute(
        """select machine, beat_at, worker_pid, linkedin_rps_logged_in
           from public.machine_heartbeats order by machine"""
    ).fetchall()
    queued = conn.execute(
        """select id, status, machine, account_key, created_at
           from public.jobs order by id"""
    ).fetchall()
    locks = conn.execute(
        "select account_key, holder_machine, job_id, acquired_at from public.account_locks order by account_key"
    ).fetchall()
    return heartbeats, queued, locks


def _expect_error(conn, error, statement: str, params=()) -> None:
    with pytest.raises(error):
        with conn.transaction():
            conn.execute(statement, params)


def _machine_values(machine_id: str):
    return (machine_id, True, "linux", 50, False, "test-worker", 0)


def _insert_machine(conn, machine_id: str) -> None:
    conn.execute(
        """insert into public.fleet_machines
           (machine_id, enabled, os, reliability_rank, draining, worker_version,
            heartbeat_generation, last_seen_at)
           values (%s,%s,%s,%s,%s,%s,%s,now())""",
        _machine_values(machine_id),
    )


def _insert_slot(
    conn,
    slot_id: str,
    machine_id: str,
    account_key="portal:test",
    state="ready",
    resource_class="browser",
):
    conn.execute(
        """insert into public.browser_slots
           (slot_id,machine_id,resource_class,portal,profile_key,logical_target_key,
            account_key,state,generation,observed_at)
           values (%s,%s,%s,'test','profile-1',%s,%s,%s,1,now())""",
        (slot_id, machine_id, resource_class, f"logical:{slot_id}", account_key, state),
    )


def _assert_security(conn) -> None:
    tables = ("fleet_machines", "browser_slots", "slot_leases", "account_permits")
    rows = conn.execute(
        """select relname, relrowsecurity from pg_class
           join pg_namespace on pg_namespace.oid=pg_class.relnamespace
           where nspname='public' and relname=any(%s)""",
        (list(tables),),
    ).fetchall()
    assert dict(rows) == {table: True for table in tables}
    service_privileges = {
        "fleet_machines": ("SELECT", "INSERT", "UPDATE"),
        "browser_slots": ("SELECT", "INSERT", "UPDATE", "DELETE"),
        "slot_leases": ("SELECT", "INSERT", "UPDATE", "DELETE"),
        "account_permits": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    }
    for table in tables:
        qualified = f"public.{table}"
        for role in ("public", "anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert not conn.execute(
                    "select has_table_privilege(%s,%s,%s)",
                    (role, qualified, privilege),
                ).fetchone()[0]
        for privilege in service_privileges[table]:
            assert conn.execute(
                "select has_table_privilege('service_role',%s,%s)",
                (qualified, privilege),
            ).fetchone()[0]


def _exercise_schema(conn, legacy_ids: dict[str, int], before) -> None:
    assert _snapshot(conn) == before
    assert conn.execute("select count(*) from public.fleet_machines").fetchone()[0] == 3
    expected_job_columns = {
        "requester_platform", "requester_user_id", "request_channel_id",
        "request_message_id", "resource_class", "requested_machine",
        "assigned_machine", "assigned_slot_id", "lease_id", "dispatch_seq",
        "not_before", "attempt", "max_attempts", "requirements", "scheduler_version",
    }
    job_columns = {
        row[0] for row in conn.execute(
            """select column_name from information_schema.columns
               where table_schema='public' and table_name='jobs'"""
        ).fetchall()
    }
    assert expected_job_columns <= job_columns
    fleet_columns = {
        row[0] for row in conn.execute(
            """select column_name from information_schema.columns
               where table_schema='public' and table_name='fleet_machines'"""
        ).fetchall()
    }
    assert "labels" in fleet_columns
    browser_columns = {
        row[0] for row in conn.execute(
            """select column_name from information_schema.columns
               where table_schema='public' and table_name='browser_slots'"""
        ).fetchall()
    }
    assert {"current_cdp_target_id", "login_verified_at", "login_proof_kind"} <= browser_columns
    assert conn.execute(
        """select count(*) from information_schema.columns
           where table_schema='public' and
                 ((table_name='fleet_machines' and column_name='capabilities') or
                  (table_name='browser_slots' and column_name='enabled'))"""
    ).fetchone()[0] == 0

    for machine in ("vh-win-04", "office-linux-05"):
        _insert_machine(conn, machine)
    conn.execute("select * from public.record_heartbeat('vh-win-04',404,true)")
    dynamic_job = conn.execute(
        """insert into public.jobs
           (machine,skill,position_url,requested_by,role,account_key,requested_machine)
           values ('office-linux-05','humansearch','https://example.com/new','requester-4',
                   'member','portal:office-linux-05','office-linux-05') returning id"""
    ).fetchone()[0]
    assert conn.execute("select id from public.claim_next_job('office-linux-05')").fetchone()[0] == dynamic_job
    conn.execute("select * from public.release_job(%s,'done','ok','')", (dynamic_job,))

    conn.execute("select * from public.record_heartbeat('macbook',202)")
    conn.execute("select * from public.record_heartbeat('macbook',203,true)")
    claimed = conn.execute("select id from public.claim_next_job('winpc')").fetchone()[0]
    conn.execute("select * from public.release_job(%s,'paused_for_human','','')", (claimed,))
    conn.execute("select * from public.resume_job(%s)", (claimed,))
    conn.execute("select * from public.cancel_job(%s,'test')", (claimed,))

    _expect_error(conn, psycopg.errors.RaiseException, "select * from public.record_heartbeat('ghost-99',1)")
    _expect_error(
        conn, psycopg.errors.ForeignKeyViolation,
        """insert into public.jobs(machine,skill,position_url,requested_by,role,account_key)
           values ('ghost-99','humansearch','https://example.com/x','u','member','portal:ghost')""",
    )
    _expect_error(
        conn, psycopg.errors.ForeignKeyViolation,
        "insert into public.machine_heartbeats(machine,worker_pid) values ('ghost-99',1)",
    )

    conn.execute(
        """insert into public.fleet_machines
           (machine_id,enabled,os,reliability_rank,draining,worker_version,
            heartbeat_generation,last_seen_at)
           values ('disabled-01',false,'linux',50,false,'test',0,now()),
                  ('draining-01',true,'linux',50,true,'test',0,now())"""
    )
    for stored_state in ("disabled-01", "draining-01"):
        job_id = conn.execute(
            """insert into public.jobs
               (machine,skill,position_url,requested_by,role,account_key)
               values (%s,'humansearch','https://example.com/stored-state','u','member',%s)
               returning id""",
            (stored_state, f"portal:{stored_state}"),
        ).fetchone()[0]
        conn.execute("select * from public.record_heartbeat(%s,1)", (stored_state,))
        assert conn.execute(
            "select id from public.claim_next_job(%s)", (stored_state,)
        ).fetchone()[0] == job_id
        conn.execute("select * from public.release_job(%s,'done','','')", (job_id,))

    _insert_slot(conn, "vh-win-04:browser", "vh-win-04")
    _insert_slot(
        conn, "office-linux-05:rps-a", "office-linux-05",
        "portal:linkedin_rps", "ready", "linkedin_rps",
    )
    _insert_slot(
        conn, "office-linux-05:rps-b", "office-linux-05",
        "portal:linkedin_rps", "parked", "linkedin_rps",
    )

    lease1 = str(uuid.uuid4())
    conn.execute(
        """insert into public.slot_leases
           (lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at)
           values (%s,'vh-win-04:browser',%s,'worker-1',1,now(),now(),now()+interval '5 min')""",
        (lease1, legacy_ids["macbook"]),
    )
    _expect_error(
        conn, psycopg.errors.UniqueViolation,
        """insert into public.slot_leases
           (lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at)
           values (%s,'vh-win-04:browser',%s,'worker-2',2,now(),now(),now()+interval '5 min')""",
        (str(uuid.uuid4()), legacy_ids["winpc"]),
    )
    _expect_error(
        conn, psycopg.errors.UniqueViolation,
        """insert into public.slot_leases
           (lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at)
           values (%s,'office-linux-05:rps-a',%s,'worker-2',2,now(),now(),now()+interval '5 min')""",
        (str(uuid.uuid4()), legacy_ids["macbook"]),
    )
    conn.execute(
        "update public.slot_leases set released_at=now(),release_reason='done' where lease_id=%s",
        (lease1,),
    )
    conn.execute(
        """insert into public.slot_leases
           (lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at)
           values (%s,'vh-win-04:browser',%s,'worker-3',3,now(),now(),now()+interval '5 min')""",
        (str(uuid.uuid4()), legacy_ids["winpc"]),
    )
    conn.execute(
        """insert into public.slot_leases
           (lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at)
           values (%s,'office-linux-05:rps-a',%s,'worker-4',4,now(),now(),now()+interval '5 min')""",
        (str(uuid.uuid4()), legacy_ids["macbook"]),
    )

    assert conn.execute(
        "select array_agg(permit_no order by permit_no) from public.account_permits where account_key='portal:linkedin_rps'"
    ).fetchone()[0] == [1]
    _expect_error(
        conn, psycopg.errors.CheckViolation,
        "insert into public.account_permits(account_key,permit_no) values ('portal:bad',0)",
    )
    _expect_error(
        conn, psycopg.errors.UniqueViolation,
        "insert into public.account_permits(account_key,permit_no) values ('portal:linkedin_rps',1)",
    )
    assert conn.execute(
        "select count(*) from public.account_permits where account_key='portal:linkedin_rps'"
    ).fetchone()[0] == 1

    bad_checks = (
        "insert into public.fleet_machines(machine_id,enabled,os,reliability_rank,worker_version,heartbeat_generation,last_seen_at) values (' bad ',true,'linux',1,'w',0,now())",
        "insert into public.fleet_machines(machine_id,enabled,os,reliability_rank,worker_version,heartbeat_generation,last_seen_at) values ('bad'||chr(10),true,'linux',1,'w',0,now())",
        "insert into public.fleet_machines(machine_id,enabled,os,reliability_rank,worker_version,heartbeat_generation,last_seen_at) values ('bad'||chr(160)||'id',true,'linux',1,'w',0,now())",
        "insert into public.fleet_machines(machine_id,enabled,os,reliability_rank,worker_version,heartbeat_generation,last_seen_at) values (repeat('a',65),true,'linux',1,'w',0,now())",
        "insert into public.fleet_machines(machine_id,enabled,os,reliability_rank,worker_version,heartbeat_generation,last_seen_at,labels) values ('bad-json',true,'linux',1,'w',0,now(),'[]')",
        "insert into public.browser_slots(slot_id,machine_id,resource_class,portal,profile_key,logical_target_key,account_key,state,generation,observed_at) values ('','vh-win-04','browser','test','p','l','a','ready',0,now())",
        "insert into public.browser_slots(slot_id,machine_id,resource_class,portal,profile_key,logical_target_key,account_key,state,generation,observed_at) values ('blank-profile','vh-win-04','browser','test','','l','a','ready',0,now())",
        "insert into public.browser_slots(slot_id,machine_id,resource_class,portal,profile_key,logical_target_key,account_key,state,generation,observed_at) values ('blank-logical','vh-win-04','browser','test','p','','a','ready',0,now())",
        "insert into public.browser_slots(slot_id,machine_id,resource_class,portal,profile_key,logical_target_key,account_key,state,generation,observed_at) values ('blank-account','vh-win-04','browser','test','p','l','','ready',0,now())",
        "insert into public.browser_slots(slot_id,machine_id,resource_class,portal,profile_key,logical_target_key,account_key,state,generation,observed_at,capabilities) values ('bad-capabilities','vh-win-04','browser','test','p','l','a','ready',0,now(),'[]')",
        "insert into public.browser_slots(slot_id,machine_id,resource_class,portal,profile_key,logical_target_key,account_key,state,generation,observed_at) values ('bad-state','vh-win-04','browser','test','p','l','a','unknown',0,now())",

        "insert into public.account_permits(account_key,permit_no) values ('',1)",
        "insert into public.account_permits(account_key,permit_no) values ('portal:linkedin_rps',2)",
        f"insert into public.slot_leases(lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at) values ('{uuid.uuid4()}','office-linux-05:rps-b',{legacy_ids['macmini']},'w',0,now(),now(),now()+interval '1 min')",
        f"insert into public.slot_leases(lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at) values ('{uuid.uuid4()}','office-linux-05:rps-b',{legacy_ids['macmini']},'',1,now(),now(),now()+interval '1 min')",
        f"insert into public.slot_leases(lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at) values ('{uuid.uuid4()}','office-linux-05:rps-b',{legacy_ids['macmini']},'w',1,now(),now()-interval '1 sec',now()+interval '1 min')",
        f"insert into public.slot_leases(lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at) values ('{uuid.uuid4()}','office-linux-05:rps-b',{legacy_ids['macmini']},'w',1,now(),now(),now()-interval '1 sec')",
        f"insert into public.slot_leases(lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at,released_at) values ('{uuid.uuid4()}','office-linux-05:rps-b',{legacy_ids['macmini']},'w',1,now(),now(),now()+interval '1 min',now()-interval '1 sec')",

    )
    for statement in bad_checks:
        _expect_error(conn, psycopg.errors.CheckViolation, statement)
    bad_foreign_keys = (
        f"""insert into public.slot_leases
            (lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at)
            values ('{uuid.uuid4()}','missing-slot',{legacy_ids['macmini']},'w',1,now(),now(),now()+interval '1 min')""",
        f"""insert into public.slot_leases
            (lease_id,slot_id,job_id,worker_id,fencing_token,acquired_at,renewed_at,expires_at)
            values ('{uuid.uuid4()}','office-linux-05:rps-b',999999,'w',1,now(),now(),now()+interval '1 min')""",
        """insert into public.browser_slots
            (slot_id,machine_id,resource_class,portal,profile_key,logical_target_key,
             account_key,state,generation,observed_at)
            values ('ghost:slot','ghost-99','browser','test','p','l','a','ready',0,now())""",
    )
    for statement in bad_foreign_keys:
        _expect_error(conn, psycopg.errors.ForeignKeyViolation, statement)
    _expect_error(
        conn, psycopg.errors.NotNullViolation,
        """insert into public.fleet_machines
            (machine_id,enabled,os,reliability_rank,worker_version,
             heartbeat_generation,last_seen_at,labels)
            values ('null-labels',true,'linux',1,'w',0,now(),null)""",
    )
    _assert_security(conn)


def test_python_machine_ids_are_dynamic_but_strict():
    payload = new_job_payload(
        machine="office-linux-04", skill="humansearch", position_url="https://example.com/job",
        requested_by="user", role="member",
    )
    assert payload and payload["machine"] == "office-linux-04"
    assert claim_next_job_payload("office-linux-04") == {"p_machine": "office-linux-04"}
    for bad in ("", " bad", "bad ", "bad\n", "bad\u00a0id", "A" * 65):
        assert new_job_payload(
            machine=bad, skill="humansearch", position_url="https://example.com/job",
            requested_by="user", role="member",
        ) is None
        with pytest.raises(ValueError):
            claim_next_job_payload(bad)


def test_dynamic_fleet_slot_migration_on_postgresql_16():
    with _postgres_server() as admin_dsn:
        _create_roles(admin_dsn)
        database, dsn = _new_database(admin_dsn)
        rollback_database = None
        try:
            with psycopg.connect(dsn, autocommit=True) as conn:
                _apply_base(conn)
                legacy_ids = _seed_legacy_fixture(conn)
                before = _snapshot(conn)
                assert TARGET_MIGRATION.exists(), (
                    "Issue #126 migration이 아직 없습니다: "
                    f"{TARGET_MIGRATION.relative_to(ROOT)}"
                )
                _apply(conn, TARGET_MIGRATION)
                _exercise_schema(conn, legacy_ids, before)
                _apply(conn, TARGET_MIGRATION)
                assert conn.execute("select count(*) from public.account_locks").fetchone()[0] == 1

            rollback_database, rollback_dsn = _new_database(admin_dsn)
            with psycopg.connect(rollback_dsn, autocommit=True) as rollback_conn:
                _apply_base(rollback_conn)
                _seed_legacy_fixture(rollback_conn)
                with pytest.raises(psycopg.errors.RaiseException, match="forced migration failure"):
                    _apply(
                        rollback_conn, TARGET_MIGRATION,
                        suffix="\ndo $$ begin raise exception 'forced migration failure'; end $$;",
                    )
                assert rollback_conn.execute(
                    "select to_regclass('public.fleet_machines')"
                ).fetchone()[0] is None
                assert rollback_conn.execute("select count(*) from public.jobs").fetchone()[0] == 3
        finally:
            if rollback_database:
                _drop_database(admin_dsn, rollback_database)
            _drop_database(admin_dsn, database)


@pytest.mark.parametrize("legacy_shape", ("empty", "jobs_only", "heartbeat_only"))
def test_partial_legacy_shapes_preserve_rows(legacy_shape):
    with _postgres_server() as admin_dsn:
        _create_roles(admin_dsn)
        database, dsn = _new_database(admin_dsn)
        try:
            with psycopg.connect(dsn, autocommit=True) as conn:
                _apply_base(conn)
                if legacy_shape == "jobs_only":
                    conn.execute(
                        """insert into public.jobs
                           (machine,skill,position_url,requested_by,role,account_key)
                           values ('macbook','humansearch','https://example.com/only-job',
                                   'fixture','owner','portal:macbook')"""
                    )
                elif legacy_shape == "heartbeat_only":
                    conn.execute("select * from public.record_heartbeat('winpc',707,true)")
                jobs_before = conn.execute("select count(*) from public.jobs").fetchone()[0]
                heartbeats_before = conn.execute(
                    "select count(*) from public.machine_heartbeats"
                ).fetchone()[0]
                _apply(conn, TARGET_MIGRATION)
                assert conn.execute(
                    "select count(*) from public.fleet_machines"
                ).fetchone()[0] == 3
                assert conn.execute("select count(*) from public.jobs").fetchone()[0] == jobs_before
                assert conn.execute(
                    "select count(*) from public.machine_heartbeats"
                ).fetchone()[0] == heartbeats_before
        finally:
            _drop_database(admin_dsn, database)
