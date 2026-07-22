-- HR-1: direct Discord gateway shared lease and worker-readiness RPCs.
-- The gateway uses the project anon key and receives no direct table privilege.

create table if not exists public.discord_gateway_leases (
  bot_id text primary key,
  lease_id uuid not null,
  instance_id uuid not null,
  acquired_at timestamptz not null default now(),
  renewed_at timestamptz not null default now(),
  expires_at timestamptz not null,
  constraint discord_gateway_leases_bot_id_chk check (bot_id ~ '^[0-9]{15,22}$'),
  constraint discord_gateway_leases_expiry_chk check (expires_at > renewed_at)
);

alter table public.discord_gateway_leases enable row level security;
revoke all on public.discord_gateway_leases from public, anon, authenticated;
grant select, insert, update, delete on public.discord_gateway_leases to service_role;

create or replace function public.discord_gateway_readiness(
  p_machine text,
  p_max_age_seconds int default 300
) returns table (
  minimal_rpc boolean,
  worker_ready boolean,
  worker_heartbeat_age_seconds int
)
language sql
security definer
set search_path = ''
as $$
  with latest as (
    select extract(epoch from (now() - max(beat_at)))::int as age_seconds
    from public.machine_heartbeats
    where machine = p_machine
  )
  select
    true,
    coalesce(
      age_seconds between 0 and greatest(1, least(coalesce(p_max_age_seconds, 300), 600)),
      false
    ),
    age_seconds
  from latest;
$$;

create or replace function public.discord_gateway_acquire_lease(
  p_bot_id text,
  p_instance_id uuid,
  p_ttl_seconds int default 90
) returns table (lease_id uuid, expires_at timestamptz)
language plpgsql
security definer
set search_path = ''
as $$
declare
  ttl int := greatest(30, least(coalesce(p_ttl_seconds, 90), 300));
  new_lease uuid := gen_random_uuid();
begin
  if p_bot_id !~ '^[0-9]{15,22}$' then
    raise exception 'invalid Discord bot id';
  end if;
  if not exists (
    select 1 from public.machine_heartbeats
    where beat_at between now() - interval '300 seconds' and now()
  ) then
    raise exception 'no fresh fleet worker heartbeat';
  end if;

  return query
    insert into public.discord_gateway_leases as held (
      bot_id, lease_id, instance_id, acquired_at, renewed_at, expires_at
    ) values (
      p_bot_id, new_lease, p_instance_id, now(), now(), now() + make_interval(secs => ttl)
    )
    on conflict (bot_id) do update
      set lease_id = excluded.lease_id,
          instance_id = excluded.instance_id,
          acquired_at = excluded.acquired_at,
          renewed_at = excluded.renewed_at,
          expires_at = excluded.expires_at
      where held.expires_at <= now() or held.instance_id = excluded.instance_id
    returning held.lease_id, held.expires_at;

  if not found then
    raise exception 'gateway lease is already held';
  end if;
end;
$$;

create or replace function public.discord_gateway_renew_lease(
  p_lease_id uuid,
  p_instance_id uuid,
  p_ttl_seconds int default 90
) returns table (lease_id uuid, expires_at timestamptz)
language plpgsql
security definer
set search_path = ''
as $$
declare
  ttl int := greatest(30, least(coalesce(p_ttl_seconds, 90), 300));
begin
  if not exists (
    select 1 from public.machine_heartbeats
    where beat_at between now() - interval '300 seconds' and now()
  ) then
    raise exception 'no fresh fleet worker heartbeat';
  end if;

  return query
    update public.discord_gateway_leases as held
       set renewed_at = now(), expires_at = now() + make_interval(secs => ttl)
     where held.lease_id = p_lease_id
       and held.instance_id = p_instance_id
       and held.expires_at > now()
    returning held.lease_id, held.expires_at;

  if not found then
    raise exception 'gateway lease ownership was lost';
  end if;
end;
$$;

create or replace function public.discord_gateway_release_lease(
  p_lease_id uuid,
  p_instance_id uuid
) returns table (released boolean)
language plpgsql
security definer
set search_path = ''
as $$
begin
  delete from public.discord_gateway_leases as held
   where held.lease_id = p_lease_id and held.instance_id = p_instance_id;
  return query select found;
end;
$$;

revoke all on function public.discord_gateway_readiness(text, int)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_acquire_lease(text, uuid, int)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_renew_lease(uuid, uuid, int)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_release_lease(uuid, uuid)
  from public, anon, authenticated;

grant execute on function public.discord_gateway_readiness(text, int) to anon;
grant execute on function public.discord_gateway_acquire_lease(text, uuid, int) to anon;
grant execute on function public.discord_gateway_renew_lease(uuid, uuid, int) to anon;
grant execute on function public.discord_gateway_release_lease(uuid, uuid) to anon;
