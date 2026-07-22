"""HR-1 lease, readiness, privilege, and event-dedup checks on PostgreSQL 16."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading

import psycopg

from tests.test_fleet_slot_schema_postgres import (
    _apply,
    _create_roles,
    _drop_database,
    _new_database,
    _postgres_server,
)


MIGRATIONS = __import__("pathlib").Path(__file__).resolve().parents[1] / "supabase/migrations"
BASE = (
    "20260711_fleet_jobs_queue.sql",
    "20260711_fleet_heartbeat.sql",
    "20260713_fleet_job_idempotency.sql",
    "20260719_discord_gateway_minimal_privilege_rpc.sql",
)
TARGET = MIGRATIONS / "20260722_discord_gateway_hr1_runtime.sql"


def _acquire(dsn: str, fingerprint: str, holder: str, pid: int, barrier) -> tuple:
    with psycopg.connect(dsn, autocommit=True) as conn:
        barrier.wait()
        return conn.execute(
            "select * from public.discord_gateway_acquire_lease(%s,%s,%s,%s,%s)",
            (fingerprint, holder, pid, "winpc", 90),
        ).fetchone()


def test_hr1_migration_is_atomic_minimal_and_reclaimable() -> None:
    with _postgres_server() as admin_dsn:
        _create_roles(admin_dsn)
        name, dsn = _new_database(admin_dsn)
        try:
            with psycopg.connect(dsn, autocommit=True) as conn:
                for path in BASE:
                    _apply(conn, MIGRATIONS / path)
                _apply(conn, TARGET)

                columns = {
                    row[0] for row in conn.execute(
                        """select column_name from information_schema.columns
                           where table_schema='public'
                             and table_name='discord_gateway_leases'"""
                    ).fetchall()
                }
                assert {
                    "token_fingerprint", "lease_id", "holder_identity", "holder_pid",
                    "target_machine", "generation", "acquired_at", "expires_at",
                    "released_at",
                } <= columns
                assert conn.execute(
                    "select relrowsecurity from pg_class where oid='public.discord_gateway_leases'::regclass"
                ).fetchone()[0]
                for table in ("discord_gateway_leases", "discord_gateway_killswitches"):
                    for role in ("public", "anon", "authenticated"):
                        assert not conn.execute(
                            "select has_table_privilege(%s,%s,'SELECT')",
                            (role, f"public.{table}"),
                        ).fetchone()[0]

                signatures = (
                    "public.discord_gateway_readiness(text,text,integer)",
                    "public.discord_gateway_acquire_lease(text,text,integer,text,integer)",
                    "public.discord_gateway_renew_lease(uuid,text,text,integer,bigint,integer)",
                    "public.discord_gateway_release_lease(uuid,text,text,integer,bigint)",
                )
                for signature in signatures:
                    assert conn.execute(
                        "select has_function_privilege('anon',%s,'EXECUTE')", (signature,),
                    ).fetchone()[0]

                conn.execute(
                    """insert into public.machine_heartbeats(machine,beat_at,worker_pid)
                       values ('winpc',now(),4242)"""
                )
                fingerprint = hashlib.sha256(b"isolated-test-token").hexdigest()
                readiness = conn.execute(
                    "select * from public.discord_gateway_readiness(%s,'winpc',300)",
                    (fingerprint,),
                ).fetchone()
                assert readiness[0:3] == (True, True, False)

                conn.execute(
                    """insert into public.discord_gateway_killswitches
                       (token_fingerprint,engaged,engaged_by,note)
                       values (%s,true,'owner','test')""",
                    (fingerprint,),
                )
                assert conn.execute(
                    "select killswitch_engaged from public.discord_gateway_readiness(%s,'winpc',300)",
                    (fingerprint,),
                ).fetchone()[0] is True
                conn.execute(
                    "update public.discord_gateway_killswitches set engaged=false where token_fingerprint=%s",
                    (fingerprint,),
                )

            barrier = threading.Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda args: _acquire(dsn, fingerprint, *args, barrier),
                    (("holder-a", 1001), ("holder-b", 1002)),
                ))
            assert sum(row[0] is True for row in results) == 1
            winner = next(row for row in results if row[0] is True)
            lease_id, generation = winner[1], winner[2]

            with psycopg.connect(dsn, autocommit=True) as conn:
                held = conn.execute(
                    "select holder_identity,holder_pid from public.discord_gateway_leases where lease_id=%s",
                    (lease_id,),
                ).fetchone()
                renewed = conn.execute(
                    "select * from public.discord_gateway_renew_lease(%s,%s,%s,%s,%s,%s)",
                    (lease_id, fingerprint, held[0], held[1], generation, 90),
                ).fetchone()
                assert renewed[0:3] == (True, lease_id, generation)
                assert conn.execute(
                    "select released from public.discord_gateway_release_lease(%s,%s,%s,%s,%s)",
                    (lease_id, fingerprint, "wrong-holder", held[1], generation),
                ).fetchone()[0] is False
                assert conn.execute(
                    "select released from public.discord_gateway_release_lease(%s,%s,%s,%s,%s)",
                    (lease_id, fingerprint, held[0], held[1], generation),
                ).fetchone()[0] is True
                reclaimed = conn.execute(
                    "select * from public.discord_gateway_acquire_lease(%s,'holder-c',1003,'winpc',90)",
                    (fingerprint,),
                ).fetchone()
                assert reclaimed[0] is True and reclaimed[2] == generation + 1

                event_key = "discord:1529267252160927999"
                params = psycopg.types.json.Jsonb({"idempotency_key": event_key})
                conn.execute(
                    "select * from public.discord_gateway_enqueue('winpc','https://example.com/job','owner','aisearch',%s,'portal:winpc')",
                    (params,),
                )
                try:
                    conn.execute(
                        "select * from public.discord_gateway_enqueue('winpc','https://example.com/job','owner','aisearch',%s,'portal:winpc')",
                        (params,),
                    )
                except psycopg.errors.UniqueViolation:
                    pass
                assert conn.execute(
                    "select count(*) from public.jobs where params->>'idempotency_key'=%s",
                    (event_key,),
                ).fetchone()[0] == 1
        finally:
            _drop_database(admin_dsn, name)
