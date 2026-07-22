-- HR-1 direct gateway runtime: token-fingerprint lease, killswitch, and target-worker readiness.
-- The gateway uses the anon/minimal key and receives EXECUTE only; tables remain private.

create table if not exists public.discord_gateway_leases (
  token_fingerprint text primary key,
  lease_id uuid not null,
  holder_identity text not null,
  holder_pid integer not null,
  target_machine text not null,
  generation bigint not null,
  acquired_at timestamptz not null,
  renewed_at timestamptz not null,
  expires_at timestamptz not null,
  released_at timestamptz,
  constraint discord_gateway_leases_fingerprint_chk
    check (token_fingerprint ~ '^[0-9a-f]{64}$'),
  constraint discord_gateway_leases_holder_chk
    check (btrim(holder_identity) <> '' and char_length(holder_identity) <= 160),
  constraint discord_gateway_leases_pid_chk check (holder_pid > 0),
  constraint discord_gateway_leases_machine_chk
    check (target_machine in ('macmini','macbook','winpc')),
  constraint discord_gateway_leases_generation_chk check (generation > 0),
  constraint discord_gateway_leases_expiry_chk check (expires_at > renewed_at)
);

create table if not exists public.discord_gateway_killswitches (
  token_fingerprint text primary key,
  engaged boolean not null default false,
  engaged_by text not null default '',
  engaged_at timestamptz,
  note text not null default '',
  constraint discord_gateway_killswitches_fingerprint_chk
    check (token_fingerprint ~ '^[0-9a-f]{64}$')
);

-- Upgrade the abandoned bot_id/instance_id draft in place. A legacy live row
-- cannot be mapped to a token fingerprint, so fail closed instead of guessing.
alter table public.discord_gateway_leases
  add column if not exists token_fingerprint text,
  add column if not exists holder_identity text,
  add column if not exists holder_pid integer,
  add column if not exists target_machine text,
  add column if not exists generation bigint,
  add column if not exists released_at timestamptz;

do $$
declare
  old_primary_key text;
begin
  if exists (
    select 1 from public.discord_gateway_leases where token_fingerprint is null
  ) then
    raise exception 'legacy gateway lease rows must be released before HR-1 migration';
  end if;
  select conname into old_primary_key
    from pg_constraint
   where conrelid = 'public.discord_gateway_leases'::regclass
     and contype = 'p'
     and pg_get_constraintdef(oid) like 'PRIMARY KEY (bot_id)%';
  if old_primary_key is not null then
    execute format('alter table public.discord_gateway_leases drop constraint %I',
                   old_primary_key);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'discord_gateway_leases'
       and column_name = 'bot_id'
  ) then
    alter table public.discord_gateway_leases alter column bot_id drop not null;
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'discord_gateway_leases'
       and column_name = 'instance_id'
  ) then
    alter table public.discord_gateway_leases alter column instance_id drop not null;
  end if;
  if not exists (
    select 1 from pg_constraint
     where conrelid = 'public.discord_gateway_leases'::regclass and contype = 'p'
  ) then
    alter table public.discord_gateway_leases
      add constraint discord_gateway_leases_pkey primary key (token_fingerprint);
  end if;
end;
$$;

alter table public.discord_gateway_leases
  alter column token_fingerprint set not null,
  alter column holder_identity set not null,
  alter column holder_pid set not null,
  alter column target_machine set not null,
  alter column generation set not null;
create unique index if not exists discord_gateway_leases_lease_id_key
  on public.discord_gateway_leases(lease_id);

alter table public.discord_gateway_killswitches
  drop constraint if exists discord_gateway_killswitches_owner_chk;

alter table public.discord_gateway_leases enable row level security;
alter table public.discord_gateway_killswitches enable row level security;
revoke all on public.discord_gateway_leases from public, anon, authenticated;
revoke all on public.discord_gateway_killswitches from public, anon, authenticated;
grant select, insert, update, delete on public.discord_gateway_leases to service_role;
grant select, insert, update, delete on public.discord_gateway_killswitches to service_role;

drop policy if exists service_role_discord_gateway_leases_all
  on public.discord_gateway_leases;
create policy service_role_discord_gateway_leases_all
  on public.discord_gateway_leases for all to service_role
  using (true) with check (true);
drop policy if exists service_role_discord_gateway_killswitches_all
  on public.discord_gateway_killswitches;
create policy service_role_discord_gateway_killswitches_all
  on public.discord_gateway_killswitches for all to service_role
  using (true) with check (true);

-- Remove the abandoned pre-HR-1 overloads if a development database saw them.
drop function if exists public.discord_gateway_readiness(text, integer);
drop function if exists public.discord_gateway_acquire_lease(text, uuid, integer);
drop function if exists public.discord_gateway_renew_lease(uuid, uuid, integer);
drop function if exists public.discord_gateway_release_lease(uuid, uuid);

create or replace function public.discord_gateway_readiness(
  p_token_fingerprint text,
  p_machine text,
  p_max_age_seconds integer default 300
) returns table (
  minimal_rpc boolean,
  worker_ready boolean,
  killswitch_engaged boolean,
  worker_heartbeat_age_seconds integer,
  worker_machine text
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  heartbeat_age integer;
begin
  if p_token_fingerprint !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid gateway token fingerprint';
  end if;
  if p_machine not in ('macmini','macbook','winpc') then
    raise exception 'invalid target worker machine';
  end if;
  select extract(epoch from (clock_timestamp() - beat_at))::integer
    into heartbeat_age
    from public.machine_heartbeats
   where machine = p_machine;
  return query select
    true,
    coalesce(
      heartbeat_age between 0 and greatest(1, least(coalesce(p_max_age_seconds, 300), 600)),
      false
    ),
    coalesce((
      select engaged from public.discord_gateway_killswitches
       where token_fingerprint = p_token_fingerprint
    ), false),
    heartbeat_age,
    p_machine;
end;
$$;

create or replace function public.discord_gateway_acquire_lease(
  p_token_fingerprint text,
  p_holder_identity text,
  p_holder_pid integer,
  p_machine text,
  p_ttl_seconds integer default 90
) returns table (
  acquired boolean,
  lease_id uuid,
  generation bigint,
  acquired_at timestamptz,
  expires_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  ttl integer := greatest(30, least(coalesce(p_ttl_seconds, 90), 300));
  new_lease_id uuid := gen_random_uuid();
  at_time timestamptz := clock_timestamp();
begin
  if p_token_fingerprint !~ '^[0-9a-f]{64}$'
     or btrim(coalesce(p_holder_identity, '')) = ''
     or char_length(p_holder_identity) > 160
     or coalesce(p_holder_pid, 0) <= 0
     or p_machine not in ('macmini','macbook','winpc') then
    raise exception 'invalid gateway lease request';
  end if;
  if exists (
    select 1 from public.discord_gateway_killswitches
     where token_fingerprint = p_token_fingerprint and engaged
  ) or not exists (
    select 1 from public.machine_heartbeats
     where machine = p_machine
       and beat_at between at_time - interval '300 seconds' and at_time
  ) then
    return query select false, null::uuid, null::bigint, null::timestamptz, null::timestamptz;
    return;
  end if;

  return query
    insert into public.discord_gateway_leases as held (
      token_fingerprint, lease_id, holder_identity, holder_pid, target_machine,
      generation, acquired_at, renewed_at, expires_at, released_at
    ) values (
      p_token_fingerprint, new_lease_id, p_holder_identity, p_holder_pid,
      p_machine, 1, at_time, at_time, at_time + make_interval(secs => ttl), null
    )
    on conflict (token_fingerprint) do update set
      lease_id = case
        when held.released_at is null and held.expires_at > at_time
         and held.holder_identity = excluded.holder_identity
         and held.holder_pid = excluded.holder_pid
        then held.lease_id else excluded.lease_id end,
      holder_identity = excluded.holder_identity,
      holder_pid = excluded.holder_pid,
      target_machine = excluded.target_machine,
      generation = case
        when held.released_at is null and held.expires_at > at_time
         and held.holder_identity = excluded.holder_identity
         and held.holder_pid = excluded.holder_pid
        then held.generation else held.generation + 1 end,
      acquired_at = case
        when held.released_at is null and held.expires_at > at_time
         and held.holder_identity = excluded.holder_identity
         and held.holder_pid = excluded.holder_pid
        then held.acquired_at else excluded.acquired_at end,
      renewed_at = at_time,
      expires_at = at_time + make_interval(secs => ttl),
      released_at = null
    where held.released_at is not null
       or held.expires_at <= at_time
       or (held.holder_identity = excluded.holder_identity
           and held.holder_pid = excluded.holder_pid)
    returning true, held.lease_id, held.generation, held.acquired_at, held.expires_at;

  if not found then
    return query select false, null::uuid, null::bigint, null::timestamptz, null::timestamptz;
  end if;
end;
$$;

create or replace function public.discord_gateway_renew_lease(
  p_lease_id uuid,
  p_token_fingerprint text,
  p_holder_identity text,
  p_holder_pid integer,
  p_generation bigint,
  p_ttl_seconds integer default 90
) returns table (
  renewed boolean,
  lease_id uuid,
  generation bigint,
  expires_at timestamptz
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  ttl integer := greatest(30, least(coalesce(p_ttl_seconds, 90), 300));
  at_time timestamptz := clock_timestamp();
begin
  return query
    update public.discord_gateway_leases as held set
      renewed_at = at_time,
      expires_at = at_time + make_interval(secs => ttl)
    where held.lease_id = p_lease_id
      and held.token_fingerprint = p_token_fingerprint
      and held.holder_identity = p_holder_identity
      and held.holder_pid = p_holder_pid
      and held.generation = p_generation
      and held.released_at is null
      and held.expires_at > at_time
      and not exists (
        select 1 from public.discord_gateway_killswitches
         where token_fingerprint = p_token_fingerprint and engaged
      )
      and exists (
        select 1 from public.machine_heartbeats
         where machine = held.target_machine
           and beat_at between at_time - interval '300 seconds' and at_time
      )
    returning true, held.lease_id, held.generation, held.expires_at;
  if not found then
    return query select false, null::uuid, null::bigint, null::timestamptz;
  end if;
end;
$$;

create or replace function public.discord_gateway_release_lease(
  p_lease_id uuid,
  p_token_fingerprint text,
  p_holder_identity text,
  p_holder_pid integer,
  p_generation bigint
) returns table (released boolean)
language plpgsql
security definer
set search_path = ''
as $$
begin
  return query
    update public.discord_gateway_leases as held
       set released_at = clock_timestamp()
     where held.lease_id = p_lease_id
       and held.token_fingerprint = p_token_fingerprint
       and held.holder_identity = p_holder_identity
       and held.holder_pid = p_holder_pid
       and held.generation = p_generation
       and held.released_at is null
    returning true;
  if not found then
    return query select false;
  end if;
end;
$$;

create or replace function public.discord_gateway_queue_nonterminal_count()
returns bigint
language sql
security definer
set search_path = ''
as $$
  select count(*) from public.jobs
   where status in ('queued','running','paused_for_human');
$$;

-- Reassert event-level idempotency in the same runtime migration.
create unique index if not exists jobs_discord_idempotency_key_uidx
  on public.jobs ((params->>'idempotency_key'))
  where coalesce(params->>'idempotency_key', '') <> '';

revoke all on function public.discord_gateway_readiness(text,text,integer)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_acquire_lease(text,text,integer,text,integer)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_renew_lease(uuid,text,text,integer,bigint,integer)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_release_lease(uuid,text,text,integer,bigint)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_queue_nonterminal_count()
  from public, anon, authenticated;

grant execute on function public.discord_gateway_readiness(text,text,integer) to anon;
grant execute on function public.discord_gateway_acquire_lease(text,text,integer,text,integer) to anon;
grant execute on function public.discord_gateway_renew_lease(uuid,text,text,integer,bigint,integer) to anon;
grant execute on function public.discord_gateway_release_lease(uuid,text,text,integer,bigint) to anon;
grant execute on function public.discord_gateway_queue_nonterminal_count() to anon;
