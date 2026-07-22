-- HR-1 worker capability readiness.  A fresh PID heartbeat alone is not proof that the
-- scheduled worker can execute Claude and Codex.  Only booleans cross the database boundary;
-- executable paths and version output remain local to the worker.

alter table public.machine_heartbeats
  add column if not exists linkedin_rps_logged_in boolean not null default false,
  add column if not exists claude_ready boolean not null default false,
  add column if not exists codex_ready boolean not null default false;

-- New workers publish both bounded CLI probes.  Older overloads explicitly clear them so an
-- old worker cannot refresh beat_at while preserving stale true capability values.
create or replace function public.record_heartbeat(
  p_machine text,
  p_worker_pid integer,
  p_linkedin_rps_logged_in boolean,
  p_claude_ready boolean,
  p_codex_ready boolean
)
returns setof public.machine_heartbeats
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_machine not in ('macmini','macbook','winpc') then
    raise exception 'unknown machine: %', p_machine;
  end if;
  insert into public.machine_heartbeats (
    machine, beat_at, worker_pid, linkedin_rps_logged_in, claude_ready, codex_ready
  ) values (
    p_machine, now(), coalesce(p_worker_pid, 0),
    coalesce(p_linkedin_rps_logged_in, false),
    coalesce(p_claude_ready, false), coalesce(p_codex_ready, false)
  )
  on conflict (machine) do update set
    beat_at = now(),
    worker_pid = coalesce(p_worker_pid, 0),
    linkedin_rps_logged_in = coalesce(p_linkedin_rps_logged_in, false),
    claude_ready = coalesce(p_claude_ready, false),
    codex_ready = coalesce(p_codex_ready, false);
  return query select * from public.machine_heartbeats where machine = p_machine;
end;
$$;

create or replace function public.record_heartbeat(
  p_machine text, p_worker_pid integer, p_linkedin_rps_logged_in boolean
)
returns setof public.machine_heartbeats
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_machine not in ('macmini','macbook','winpc') then
    raise exception 'unknown machine: %', p_machine;
  end if;
  insert into public.machine_heartbeats (
    machine, beat_at, worker_pid, linkedin_rps_logged_in, claude_ready, codex_ready
  ) values (
    p_machine, now(), coalesce(p_worker_pid, 0),
    coalesce(p_linkedin_rps_logged_in, false), false, false
  )
  on conflict (machine) do update set
    beat_at = now(),
    worker_pid = coalesce(p_worker_pid, 0),
    linkedin_rps_logged_in = coalesce(p_linkedin_rps_logged_in, false),
    claude_ready = false,
    codex_ready = false;
  return query select * from public.machine_heartbeats where machine = p_machine;
end;
$$;

create or replace function public.record_heartbeat(p_machine text, p_worker_pid integer)
returns setof public.machine_heartbeats
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_machine not in ('macmini','macbook','winpc') then
    raise exception 'unknown machine: %', p_machine;
  end if;
  insert into public.machine_heartbeats (
    machine, beat_at, worker_pid, linkedin_rps_logged_in, claude_ready, codex_ready
  ) values (p_machine, now(), coalesce(p_worker_pid, 0), false, false, false)
  on conflict (machine) do update set
    beat_at = now(),
    worker_pid = coalesce(p_worker_pid, 0),
    linkedin_rps_logged_in = false,
    claude_ready = false,
    codex_ready = false;
  return query select * from public.machine_heartbeats where machine = p_machine;
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
  claude_ready boolean,
  codex_ready boolean
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  heartbeat_age integer;
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
    coalesce(machine_heartbeats.claude_ready, false),
    coalesce(machine_heartbeats.codex_ready, false)
  into heartbeat_age, heartbeat_claude_ready, heartbeat_codex_ready
  from public.machine_heartbeats
  where machine = p_machine;
  return query select
    true,
    coalesce(
      heartbeat_age between 0 and greatest(1, least(coalesce(p_max_age_seconds, 300), 600))
      and heartbeat_claude_ready and heartbeat_codex_ready,
      false
    ),
    coalesce((
      select engaged from public.discord_gateway_killswitches
       where token_fingerprint = p_token_fingerprint
    ), false),
    heartbeat_age,
    p_machine,
    coalesce(heartbeat_claude_ready, false),
    coalesce(heartbeat_codex_ready, false);
end;
$$;

-- Close the readiness/acquire race inside the lease row write.  Release remains possible after
-- capability loss so a failed run never leaves an unreleasable active lease.
create or replace function public.enforce_discord_gateway_agent_readiness()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.released_at is not null then
    return new;
  end if;
  if not exists (
    select 1 from public.machine_heartbeats
     where machine = new.target_machine
       and beat_at between clock_timestamp() - interval '300 seconds' and clock_timestamp()
       and claude_ready
       and codex_ready
  ) then
    raise exception 'target worker agent readiness failed';
  end if;
  return new;
end;
$$;

drop trigger if exists discord_gateway_agent_readiness_guard
  on public.discord_gateway_leases;
create trigger discord_gateway_agent_readiness_guard
before insert or update of renewed_at, expires_at, released_at
on public.discord_gateway_leases
for each row execute function public.enforce_discord_gateway_agent_readiness();

revoke all on function public.record_heartbeat(text,integer,boolean,boolean,boolean)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_readiness(text,text,integer)
  from public, anon, authenticated;
revoke all on function public.enforce_discord_gateway_agent_readiness()
  from public, anon, authenticated;
grant execute on function public.record_heartbeat(text,integer,boolean,boolean,boolean)
  to service_role;
grant execute on function public.discord_gateway_readiness(text,text,integer) to anon;

notify pgrst, 'reload schema';
