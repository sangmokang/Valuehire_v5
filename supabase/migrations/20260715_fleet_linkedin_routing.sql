-- 이슈 D (2026-07-15, 사장님 SOT29 §2 개정 승인) — LinkedIn RPS 로그인 머신 라우팅.
-- machine_heartbeats 에 linkedin_rps_logged_in 을 실어 중앙에서 "어느 머신이
-- LinkedIn 로그인 상태인지" 조회 가능하게 한다. 패턴: 20260711_fleet_heartbeat.sql.

alter table public.machine_heartbeats
  add column if not exists linkedin_rps_logged_in boolean not null default false;

-- 3인자 record_heartbeat (기존 2인자 함수는 그대로 두어 구버전 워커 하위호환).
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
  insert into public.machine_heartbeats (machine, beat_at, worker_pid, linkedin_rps_logged_in)
  values (p_machine, now(), coalesce(p_worker_pid, 0), coalesce(p_linkedin_rps_logged_in, false))
  on conflict (machine)
  do update set beat_at = now(),
                worker_pid = coalesce(p_worker_pid, 0),
                linkedin_rps_logged_in = coalesce(p_linkedin_rps_logged_in, false);
  return query select * from public.machine_heartbeats where machine = p_machine;
end;
$$;

-- 디스패처 라우팅 조회: epoch 초 단위(파이썬 pick_linkedin_machine 과 정합).
create or replace function public.linkedin_ready_machines()
returns table (machine text, beat_at_epoch bigint, linkedin_rps_logged_in boolean)
language sql
security definer
set search_path = public
as $$
  select machine, extract(epoch from beat_at)::bigint, linkedin_rps_logged_in
  from public.machine_heartbeats;
$$;

-- V1 blocker 수용: 구버전 워커(2인자)가 beat 만 갱신하면 낡은 linkedin=true 가
-- '신선한 로그인'으로 영구 위장된다 — 2인자 경로는 플래그를 false 로 리셋(fail-closed).
-- (로그인 상태를 보고할 줄 모르는 워커 = 로그인 검증 안 된 머신으로 취급)
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
  insert into public.machine_heartbeats (machine, beat_at, worker_pid, linkedin_rps_logged_in)
  values (p_machine, now(), coalesce(p_worker_pid, 0), false)
  on conflict (machine)
  do update set beat_at = now(),
                worker_pid = coalesce(p_worker_pid, 0),
                linkedin_rps_logged_in = false;
  return query select * from public.machine_heartbeats where machine = p_machine;
end;
$$;

revoke all on function public.record_heartbeat(text, integer, boolean) from public, anon, authenticated;
revoke all on function public.linkedin_ready_machines() from public, anon, authenticated;
grant execute on function public.record_heartbeat(text, integer, boolean) to service_role;
grant execute on function public.linkedin_ready_machines() to service_role;
