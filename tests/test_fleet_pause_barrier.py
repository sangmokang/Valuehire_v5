"""계정 단위 paused_for_human 장벽의 DB 계약을 고정한다.

이 장벽은 워커 메모리나 시간 제한이 아니라 claim_next_job RPC 안에서 동작해야 한다.
그래야 다른 워커·다른 머신도 같은 계정으로 캡차 처리 중 재진입하지 못한다.
"""

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
MIGRATION = REPO / "supabase/migrations/20260715233000_fleet_account_pause_barrier.sql"


def _sql() -> str:
    assert MIGRATION.exists(), "계정 pause 장벽 마이그레이션이 없습니다"
    raw = MIGRATION.read_text()
    return "\n".join(line.split("--", 1)[0] for line in raw.splitlines()).lower()


def _compact(value: str) -> str:
    return " ".join(value.split())


def _claim_body() -> str:
    sql = _sql()
    start = sql.index("create or replace function public.claim_next_job")
    end = sql.index("revoke all on function public.claim_next_job", start)
    return sql[start:end]


def _pause_predicate() -> str:
    claim = _claim_body()
    start = claim.index("from public.jobs paused")
    end = claim.index("order by q.id", start)
    return claim[start:end]


def test_migration_version_is_unique_and_timestamped():
    version = MIGRATION.name.split("_", 1)[0]
    versions = [
        path.name.split("_", 1)[0]
        for path in (REPO / "supabase/migrations").glob("*.sql")
    ]
    assert len(version) == 14 and version.isdigit()
    assert versions.count(version) == 1, "Supabase migration version 충돌"


def test_migration_replaces_server_claim_rpc_and_keeps_it_service_role_only():
    sql = _compact(_sql())
    assert "create or replace function public.claim_next_job(p_machine text)" in sql
    assert "security definer set search_path = public" in sql
    assert (
        "revoke all on function public.claim_next_job(text) "
        "from public, anon, authenticated"
    ) in sql
    assert "grant execute on function public.claim_next_job(text) to service_role" in sql


def test_queued_insert_is_not_blocked_by_an_existing_pause():
    """장벽은 enqueue가 아니라 claim/execute 경계에만 있어야 한다."""
    sql = _sql()
    assert "create or replace function public.jobs_insert_guard" not in sql
    assert "before insert" not in sql
    assert "paused.account_key" not in sql[: sql.index("create or replace function public.claim_next_job")]


def test_legacy_blank_keys_are_handled_before_validated_constraint():
    sql = _compact(_sql())
    assert "jobs_active_account_key_nonblank_chk" in sql
    assert "status = 'running' and btrim(account_key) = ''" in sql
    assert "raise exception 'running 상태의 공백 account_key" in sql
    assert "where status in ('queued','paused_for_human')" in sql
    assert "when skill = 'url' then 'portal:linkedin_rps'" in sql
    assert "else 'portal:' || machine" in sql
    assert (
        "status not in ('queued','running','paused_for_human') or ( "
        "btrim(account_key) <> '' and account_key = btrim(account_key) "
        "and account_key !~ '[[:space:]]' )"
    ) in sql
    assert "not valid" not in sql
    # 보정 뒤에도 claim 경계는 공백 키를 fail-closed로 거부한다.
    assert "q.status = 'queued' and btrim(q.account_key) <> ''" in _compact(_claim_body())


def test_claim_skips_any_nonblank_account_with_a_paused_job():
    predicate = _compact(_pause_predicate())
    assert "from public.jobs paused" in predicate
    assert "paused.status = 'paused_for_human'" in predicate
    assert "btrim(paused.account_key) <> ''" in predicate
    assert "paused.account_key = q.account_key" in predicate
    assert "not exists" in _compact(_claim_body())


def test_pause_barrier_has_no_ttl_or_machine_scope():
    predicate = _pause_predicate()
    for forbidden in (
        "paused.machine",
        "created_at",
        "started_at",
        "finished_at",
        "interval",
        "extract(epoch",
        "clock_timestamp",
    ):
        assert forbidden not in predicate


def test_every_paused_row_for_the_key_must_be_cleared_before_claim():
    """NOT EXISTS 전체집합 검사여야 pause 여러 건 중 하나만 풀어 우회할 수 없다."""
    predicate = _pause_predicate()
    assert "limit" not in predicate
    assert "paused.id" not in predicate
    assert "account_locks" not in predicate


def test_unpaused_accounts_still_use_the_existing_global_lock_and_skip_locked():
    claim = _compact(_claim_body())
    assert "al.account_key = q.account_key" in claim
    assert "insert into public.account_locks (account_key, holder_machine, job_id)" in claim
    assert "for update of q skip locked" in claim


def test_sot_documents_cross_machine_linkedin_and_manual_unblock_only():
    control_json = (REPO / "docs/sot/29-fleet-control.json").read_text()
    control_md = (REPO / "docs/sot/29-fleet-control.md").read_text()
    reliability = (REPO / "docs/sot/30-fleet-run-reliability.md").read_text()
    joined = "\n".join((control_json, control_md, reliability))
    assert "계정 단위 pause 장벽" in joined
    assert "portal:linkedin_rps" in joined
    assert "시간 만료" in joined
    assert "모든 paused_for_human" in joined
    assert "resume_job" in joined and "cancel_job" in joined
