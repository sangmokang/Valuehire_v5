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
CAPABILITY_TARGET = MIGRATIONS / "20260723_discord_gateway_agent_readiness.sql"
GENERATION_TARGET = MIGRATIONS / "20260724_discord_gateway_worker_generation.sql"


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
                _apply(conn, CAPABILITY_TARGET)
                _apply(conn, GENERATION_TARGET)

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
                    "released_at", "target_worker_pid",
                } <= columns
                assert conn.execute(
                    "select relrowsecurity from pg_class where oid='public.discord_gateway_leases'::regclass"
                ).fetchone()[0]
                for table in ("discord_gateway_leases", "discord_gateway_killswitches"):
                    for role in ("public", "anon", "authenticated"):
                        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                            assert not conn.execute(
                                "select has_table_privilege(%s,%s,%s)",
                                (role, f"public.{table}", privilege),
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
                    """insert into public.machine_heartbeats(
                         machine,beat_at,worker_pid,claude_ready,codex_ready)
                       values ('winpc',now(),4242,true,true)"""
                )
                fingerprint = hashlib.sha256(b"isolated-test-token").hexdigest()
                readiness = conn.execute(
                    "select * from public.discord_gateway_readiness(%s,'winpc',300)",
                    (fingerprint,),
                ).fetchone()
                assert readiness[0:3] == (True, True, False)
                assert readiness[5:8] == (4242, True, True)

                conn.execute("select * from public.record_heartbeat('winpc',4242)")
                legacy = conn.execute(
                    "select claude_ready,codex_ready from public.machine_heartbeats where machine='winpc'"
                ).fetchone()
                assert legacy == (False, False)
                conn.execute(
                    "select * from public.record_heartbeat('winpc',4242,false,true,true)"
                )

                partial_fingerprint = hashlib.sha256(b"partial-worker-token").hexdigest()
                conn.execute(
                    "update public.machine_heartbeats set codex_ready=false where machine='winpc'"
                )
                partial = conn.execute(
                    "select * from public.discord_gateway_readiness(%s,'winpc',300)",
                    (partial_fingerprint,),
                ).fetchone()
                assert partial[1] is False and partial[5:8] == (4242, True, False)
                with __import__("pytest").raises(psycopg.Error):
                    conn.execute(
                        "select * from public.discord_gateway_acquire_lease(%s,'partial',998,'winpc',90)",
                        (partial_fingerprint,),
                    ).fetchone()
                conn.execute(
                    "update public.machine_heartbeats set codex_ready=true where machine='winpc'"
                )

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
                assert conn.execute(
                    "select acquired from public.discord_gateway_acquire_lease(%s,'blocked',999,'winpc',90)",
                    (fingerprint,),
                ).fetchone()[0] is False
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
                    "select holder_identity,holder_pid,target_worker_pid "
                    "from public.discord_gateway_leases where lease_id=%s",
                    (lease_id,),
                ).fetchone()
                assert held[2] == 4242
                conn.execute(
                    "update public.machine_heartbeats set claude_ready=false where machine='winpc'"
                )
                with __import__("pytest").raises(psycopg.Error):
                    conn.execute(
                        "select * from public.discord_gateway_renew_lease(%s,%s,%s,%s,%s,%s)",
                        (lease_id, fingerprint, held[0], held[1], generation, 90),
                    ).fetchone()
                conn.execute(
                    "update public.machine_heartbeats set claude_ready=true where machine='winpc'"
                )
                conn.execute(
                    "update public.machine_heartbeats set worker_pid=7777 where machine='winpc'"
                )
                with __import__("pytest").raises(psycopg.Error):
                    conn.execute(
                        "select * from public.discord_gateway_renew_lease(%s,%s,%s,%s,%s,%s)",
                        (lease_id, fingerprint, held[0], held[1], generation, 90),
                    ).fetchone()
                conn.execute(
                    "update public.machine_heartbeats set worker_pid=4242 where machine='winpc'"
                )
                renewed = conn.execute(
                    "select * from public.discord_gateway_renew_lease(%s,%s,%s,%s,%s,%s)",
                    (lease_id, fingerprint, held[0], held[1], generation, 90),
                ).fetchone()
                assert renewed[0:3] == (True, lease_id, generation)
                assert conn.execute(
                    "select released from public.discord_gateway_release_lease(%s,%s,%s,%s,%s)",
                    (lease_id, fingerprint, "wrong-holder", held[1], generation),
                ).fetchone()[0] is False
                conn.execute(
                    "update public.machine_heartbeats set claude_ready=false,codex_ready=false "
                    "where machine='winpc'"
                )
                assert conn.execute(
                    "select released from public.discord_gateway_release_lease(%s,%s,%s,%s,%s)",
                    (lease_id, fingerprint, held[0], held[1], generation),
                ).fetchone()[0] is True
                conn.execute(
                    "select * from public.record_heartbeat('winpc',4242,false,true,true)"
                )
                reclaimed = conn.execute(
                    "select * from public.discord_gateway_acquire_lease(%s,'holder-c',1003,'winpc',90)",
                    (fingerprint,),
                ).fetchone()
                assert reclaimed[0] is True and reclaimed[2] == generation + 1
                conn.execute(
                    """update public.discord_gateway_leases
                          set renewed_at=now()-interval '2 minutes',
                              expires_at=now()-interval '1 minute'
                        where lease_id=%s""",
                    (reclaimed[1],),
                )
                expired_reclaim = conn.execute(
                    "select * from public.discord_gateway_acquire_lease(%s,'holder-d',1004,'winpc',90)",
                    (fingerprint,),
                ).fetchone()
                assert expired_reclaim[0] is True
                assert expired_reclaim[2] == reclaimed[2] + 1

                conn.execute(
                    "update public.machine_heartbeats set beat_at=now()-interval '10 minutes' where machine='winpc'"
                )
                stale_fingerprint = hashlib.sha256(b"stale-worker-token").hexdigest()
                stale = conn.execute(
                    "select * from public.discord_gateway_readiness(%s,'winpc',300)",
                    (stale_fingerprint,),
                ).fetchone()
                assert stale[1] is False
                assert conn.execute(
                    "select acquired from public.discord_gateway_acquire_lease(%s,'stale',1005,'winpc',90)",
                    (stale_fingerprint,),
                ).fetchone()[0] is False
                conn.execute(
                    "update public.machine_heartbeats set beat_at=now()+interval '1 minute' where machine='winpc'"
                )
                future = conn.execute(
                    "select worker_ready from public.discord_gateway_readiness(%s,'winpc',300)",
                    (stale_fingerprint,),
                ).fetchone()
                assert future[0] is False
                conn.execute(
                    "update public.machine_heartbeats set beat_at=now() where machine='winpc'"
                )

                conn.execute("set role anon")
                try:
                    anon_ready = conn.execute(
                        "select minimal_rpc,worker_ready,killswitch_engaged from public.discord_gateway_readiness(%s,'winpc',300)",
                        (fingerprint,),
                    ).fetchone()
                    assert anon_ready == (True, True, False)
                finally:
                    conn.execute("reset role")

                event_key = "discord:1529267252160927999"
                params = psycopg.types.json.Jsonb({"idempotency_key": event_key})
                first_enqueue = conn.execute(
                    "select * from public.discord_gateway_enqueue('winpc','https://example.com/job','owner','aisearch',%s,'portal:winpc')",
                    (params,),
                ).fetchone()
                replay_enqueue = conn.execute(
                    "select * from public.discord_gateway_enqueue('winpc','https://example.com/job','owner','aisearch',%s,'portal:winpc')",
                    (params,),
                ).fetchone()
                assert first_enqueue[-1] is True
                assert replay_enqueue[-1] is False
                assert first_enqueue[0] == replay_enqueue[0]
                assert conn.execute(
                    "select count(*) from public.jobs where params->>'idempotency_key'=%s",
                    (event_key,),
                ).fetchone()[0] == 1
        finally:
            _drop_database(admin_dsn, name)
