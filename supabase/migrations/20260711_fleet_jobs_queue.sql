-- 함대 작업 큐 (2026-07-11) — Discord 명령 → 3대 머신 잡 분배.
-- 근거: docs/prompts/fleet-control-sequential-prompts-2026-07-11.md §프롬프트 A.
-- 패턴: 20260708_organization_analysis.sql (RLS + service_role 전용).

create table if not exists public.jobs (
  id                bigint generated always as identity primary key,
  machine           text not null check (machine in ('macmini','macbook','winpc')),
  skill             text not null check (skill in ('humansearch','aisearch','url')),
  position_url      text not null default '',
  params            jsonb not null default '{}',
  requested_by      text not null,
  role              text not null check (role in ('owner','member')),
  status            text not null default 'queued'
                    check (status in ('queued','running','paused_for_human','done','failed','cancelled')),
  discord_thread_id text not null default '',
  account_key       text not null default '',
  created_at        timestamptz not null default now(),
  started_at        timestamptz,
  finished_at       timestamptz,
  result_summary    text not null default '',
  error             text not null default ''
);

create index if not exists jobs_machine_status_idx on public.jobs (machine, status);
create index if not exists jobs_status_idx on public.jobs (status);

create table if not exists public.account_locks (
  account_key    text primary key,
  holder_machine text not null,
  job_id         bigint not null references public.jobs(id),
  acquired_at    timestamptz not null default now()
);

alter table public.jobs enable row level security;
alter table public.account_locks enable row level security;

revoke all on public.jobs from public, anon, authenticated;
revoke all on public.account_locks from public, anon, authenticated;
grant select, insert, update on public.jobs to service_role;
grant select, insert, update, delete on public.account_locks to service_role;

drop policy if exists service_role_jobs_all on public.jobs;
create policy service_role_jobs_all on public.jobs
  for all to service_role using (true) with check (true);

drop policy if exists service_role_account_locks_all on public.account_locks;
create policy service_role_account_locks_all on public.account_locks
  for all to service_role using (true) with check (true);

-- 잡 1건 클레임: 자기 머신 queued 를 FOR UPDATE SKIP LOCKED 로 집고,
-- account_locks 를 잡을 수 있는 잡만 running 전환(계정 글로벌 락 — 세션 밀어내기 방지).
create or replace function public.claim_next_job(p_machine text)
returns setof public.jobs
language plpgsql
security definer
set search_path = public
as $$
declare
  j public.jobs%rowtype;
  locked boolean;
begin
  if p_machine not in ('macmini','macbook','winpc') then
    raise exception 'unknown machine: %', p_machine;
  end if;
  for j in
    select * from public.jobs
    where machine = p_machine and status = 'queued'
    order by id
    for update skip locked
  loop
    if j.account_key = '' then
      locked := true;
    else
      begin
        insert into public.account_locks (account_key, holder_machine, job_id)
        values (j.account_key, p_machine, j.id);
        locked := true;
      exception when unique_violation then
        locked := false;  -- 다른 머신이 같은 계정 사용 중 → 이 잡은 건너뜀
      end;
    end if;
    if locked then
      update public.jobs
        set status = 'running', started_at = now()
        where id = j.id;
      return query select * from public.jobs where id = j.id;
      return;
    end if;
  end loop;
  return;  -- 집을 잡 없음 → 빈 결과
end;
$$;

-- 잡 종결/일시정지 + 락 해제. 재큐잉은 resume_job 전용.
create or replace function public.release_job(
  p_job_id bigint,
  p_status text,
  p_result_summary text default '',
  p_error text default ''
) returns setof public.jobs
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_status not in ('done','failed','cancelled','paused_for_human') then
    raise exception 'release 불가 상태: %', p_status;
  end if;
  update public.jobs
    set status = p_status,
        finished_at = case when p_status in ('done','failed','cancelled') then now() else finished_at end,
        result_summary = coalesce(p_result_summary, ''),
        error = coalesce(p_error, '')
    where id = p_job_id and status = 'running';
  if not found then
    raise exception 'running 상태의 잡 % 가 없습니다', p_job_id;
  end if;
  delete from public.account_locks where job_id = p_job_id;
  return query select * from public.jobs where id = p_job_id;
end;
$$;

-- /resume: paused_for_human → queued (사람 개입 완료 후 재개)
create or replace function public.resume_job(p_job_id bigint)
returns setof public.jobs
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.jobs
    set status = 'queued', started_at = null
    where id = p_job_id and status = 'paused_for_human';
  if not found then
    raise exception 'paused_for_human 상태의 잡 % 가 없습니다', p_job_id;
  end if;
  delete from public.account_locks where job_id = p_job_id;
  return query select * from public.jobs where id = p_job_id;
end;
$$;

revoke all on function public.claim_next_job(text) from public, anon, authenticated;
revoke all on function public.release_job(bigint, text, text, text) from public, anon, authenticated;
revoke all on function public.resume_job(bigint) from public, anon, authenticated;
grant execute on function public.claim_next_job(text) to service_role;
grant execute on function public.release_job(bigint, text, text, text) to service_role;
grant execute on function public.resume_job(bigint) to service_role;
