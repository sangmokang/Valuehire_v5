-- 함대 heartbeat (2026-07-11, 단계 G) — 머신별 심장박동 + watchdog 조회.
-- 패턴: 20260711_fleet_jobs_queue.sql (RLS + service_role 전용).

create table if not exists public.machine_heartbeats (
  machine    text primary key check (machine in ('macmini','macbook','winpc')),
  beat_at    timestamptz not null default now(),
  worker_pid integer not null default 0
);

alter table public.machine_heartbeats enable row level security;
revoke all on public.machine_heartbeats from public, anon, authenticated;
grant select, insert, update on public.machine_heartbeats to service_role;

drop policy if exists service_role_machine_heartbeats_all on public.machine_heartbeats;
create policy service_role_machine_heartbeats_all on public.machine_heartbeats
  for all to service_role using (true) with check (true);

-- 워커가 1분마다 호출: 자기 머신 행을 upsert.
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
  insert into public.machine_heartbeats (machine, beat_at, worker_pid)
  values (p_machine, now(), coalesce(p_worker_pid, 0))
  on conflict (machine)
  do update set beat_at = now(), worker_pid = coalesce(p_worker_pid, 0);
  return query select * from public.machine_heartbeats where machine = p_machine;
end;
$$;

-- watchdog 조회: epoch 초 단위로 반환(파이썬 stale 판정과 정합).
create or replace function public.heartbeats_epoch()
returns table (machine text, beat_at_epoch bigint)
language sql
security definer
set search_path = public
as $$
  select machine, extract(epoch from beat_at)::bigint from public.machine_heartbeats;
$$;

revoke all on function public.record_heartbeat(text, integer) from public, anon, authenticated;
revoke all on function public.heartbeats_epoch() from public, anon, authenticated;
grant execute on function public.record_heartbeat(text, integer) to service_role;
grant execute on function public.heartbeats_epoch() to service_role;
