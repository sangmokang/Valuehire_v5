-- Bind every active direct-gateway lease to the exact worker process generation.
-- A fresh heartbeat from a replacement process must not silently keep an old lease alive.

alter table public.discord_gateway_leases
  add column if not exists target_worker_pid integer;

do $$
begin
  if not exists (
    select 1 from pg_constraint
     where conrelid = 'public.discord_gateway_leases'::regclass
       and conname = 'discord_gateway_leases_worker_pid_chk'
  ) then
    alter table public.discord_gateway_leases
      add constraint discord_gateway_leases_worker_pid_chk
      check (target_worker_pid is null or target_worker_pid > 0);
  end if;
end;
$$;

drop function if exists public.discord_gateway_readiness(text,text,integer);
create function public.discord_gateway_readiness(
  p_token_fingerprint text,
  p_machine text,
  p_max_age_seconds integer default 300
) returns table (
  minimal_rpc boolean,
  worker_ready boolean,
  killswitch_engaged boolean,
  worker_heartbeat_age_seconds integer,
  worker_machine text,
  worker_pid integer,
  claude_ready boolean,
  codex_ready boolean
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  heartbeat_age integer;
  heartbeat_worker_pid integer;
  heartbeat_claude_ready boolean := false;
  heartbeat_codex_ready boolean := false;
begin
  if p_token_fingerprint !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid gateway token fingerprint';
  end if;
  if p_machine not in ('macmini','macbook','winpc') then
    raise exception 'invalid target worker machine';
  end if;
  select
    extract(epoch from (clock_timestamp() - beat_at))::integer,
    machine_heartbeats.worker_pid,
    coalesce(machine_heartbeats.claude_ready, false),
    coalesce(machine_heartbeats.codex_ready, false)
  into heartbeat_age, heartbeat_worker_pid,
       heartbeat_claude_ready, heartbeat_codex_ready
  from public.machine_heartbeats
  where machine = p_machine;
  return query select
    true,
    coalesce(
      heartbeat_age between 0 and greatest(1, least(coalesce(p_max_age_seconds, 300), 600))
      and coalesce(heartbeat_worker_pid, 0) > 0
      and heartbeat_claude_ready and heartbeat_codex_ready,
      false
    ),
    coalesce((
      select engaged from public.discord_gateway_killswitches
       where token_fingerprint = p_token_fingerprint
    ), false),
    heartbeat_age,
    p_machine,
    heartbeat_worker_pid,
    coalesce(heartbeat_claude_ready, false),
    coalesce(heartbeat_codex_ready, false);
end;
$$;

create or replace function public.enforce_discord_gateway_agent_readiness()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  heartbeat_worker_pid integer;
begin
  -- A lease must always be releasable after a worker or capability failure.
  if new.released_at is not null then
    return new;
  end if;

  select worker_pid into heartbeat_worker_pid
    from public.machine_heartbeats
   where machine = new.target_machine
     and worker_pid > 0
     and beat_at between clock_timestamp() - interval '300 seconds' and clock_timestamp()
     and claude_ready
     and codex_ready;
  if heartbeat_worker_pid is null then
    raise exception 'target worker agent readiness failed';
  end if;

  if tg_op = 'INSERT' then
    new.target_worker_pid := heartbeat_worker_pid;
  elsif old.released_at is not null
        or new.lease_id is distinct from old.lease_id
        or new.generation is distinct from old.generation
        or new.acquired_at is distinct from old.acquired_at then
    new.target_worker_pid := heartbeat_worker_pid;
  elsif old.target_worker_pid is null
        or old.target_worker_pid is distinct from heartbeat_worker_pid then
    raise exception 'target worker process generation changed';
  else
    new.target_worker_pid := old.target_worker_pid;
  end if;
  return new;
end;
$$;

drop trigger if exists discord_gateway_agent_readiness_guard
  on public.discord_gateway_leases;
create trigger discord_gateway_agent_readiness_guard
before insert or update of target_machine, lease_id, generation, acquired_at,
  renewed_at, expires_at, released_at
on public.discord_gateway_leases
for each row execute function public.enforce_discord_gateway_agent_readiness();

revoke all on function public.discord_gateway_readiness(text,text,integer)
  from public, anon, authenticated;
revoke all on function public.enforce_discord_gateway_agent_readiness()
  from public, anon, authenticated;
grant execute on function public.discord_gateway_readiness(text,text,integer) to anon;

notify pgrst, 'reload schema';
