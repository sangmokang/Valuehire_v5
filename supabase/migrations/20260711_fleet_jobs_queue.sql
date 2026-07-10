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

-- 무결성 보강(V1 적대검증 반영): 라이브 DB 재적용 안전(드롭 후 재생성).
alter table public.jobs drop constraint if exists jobs_position_url_http_chk;
alter table public.jobs add constraint jobs_position_url_http_chk
  check (
    position_url ~ '^https?://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?(/.*)?$'
    and position_url !~ '\s'
    and position_url !~ '\.\.'
  );

do $$ begin
  alter table public.jobs add constraint jobs_requested_by_nonblank_chk
    check (btrim(requested_by) <> '');
exception when duplicate_object then null; end $$;

-- 상태 전이 화이트리스트를 DB 경계에서 강제(V1 결함 2: service_role 직접 UPDATE 우회 차단).
create or replace function public.jobs_transition_guard()
returns trigger
language plpgsql
as $$
begin
  -- V1 2R: no-op 재설정(running→running 등)도 python 화이트리스트와 동일하게 거부
  if not (
       (old.status = 'queued'           and new.status in ('running','cancelled'))
    or (old.status = 'running'          and new.status in ('paused_for_human','done','failed'))
    or (old.status = 'paused_for_human' and new.status in ('queued','cancelled'))
  ) then
    raise exception '금지된 상태 전이: % -> %', old.status, new.status;
  end if;
  return new;
end;
$$;

drop trigger if exists jobs_transition_guard_trg on public.jobs;
create trigger jobs_transition_guard_trg
  before update of status on public.jobs
  for each row execute function public.jobs_transition_guard();

-- V1 2R 신규 결함: INSERT 로 초기 상태를 running/done 등으로 심는 우회 차단.
create or replace function public.jobs_insert_guard()
returns trigger
language plpgsql
as $$
begin
  if new.status <> 'queued' then
    raise exception '신규 잡은 queued 로만 생성 가능 (시도: %)', new.status;
  end if;
  if new.started_at is not null or new.finished_at is not null then
    raise exception '신규 잡에 started_at/finished_at 선지정 금지';
  end if;
  return new;
end;
$$;

drop trigger if exists jobs_insert_guard_trg on public.jobs;
create trigger jobs_insert_guard_trg
  before insert on public.jobs
  for each row execute function public.jobs_insert_guard();

-- 락 고아화 방지(V1 결함 3): 어떤 경로로든 종결/재큐잉되면 락 자동 해제.
create or replace function public.jobs_lock_cleanup()
returns trigger
language plpgsql
as $$
begin
  -- V1 2R: 직접 UPDATE 로 paused_for_human 이 되어도 락이 남지 않게(release_job 과 동일 의미)
  if new.status in ('done','failed','cancelled','queued','paused_for_human') then
    delete from public.account_locks where job_id = new.id;
  end if;
  return new;
end;
$$;

drop trigger if exists jobs_lock_cleanup_trg on public.jobs;
create trigger jobs_lock_cleanup_trg
  after update of status on public.jobs
  for each row execute function public.jobs_lock_cleanup();

-- 잡 1건 클레임. V1 결함 1(암묵 커서 프리페치가 여분 행 락 보유) 반영:
-- FOR-IN 커서 대신 반복마다 LIMIT 1 FOR UPDATE SKIP LOCKED 로 한 행씩만 잠근다.
create or replace function public.claim_next_job(p_machine text)
returns setof public.jobs
language plpgsql
security definer
set search_path = public
as $$
declare
  j public.jobs%rowtype;
  last_id bigint := 0;
  locked boolean;
begin
  if p_machine not in ('macmini','macbook','winpc') then
    raise exception 'unknown machine: %', p_machine;
  end if;
  loop
    -- V1 2R: 락 충돌이 뻔한 후보는 애초에 잠그지 않는다(사재기 최소화).
    -- unique_violation 폴백은 이 필터와 insert 사이의 레이스 전용으로만 남는다.
    select * into j from public.jobs
      where machine = p_machine and status = 'queued' and id > last_id
        and (account_key = '' or not exists (
              select 1 from public.account_locks al
              where al.account_key = public.jobs.account_key))
      order by id
      limit 1
      for update skip locked;
    if not found then
      return;  -- 집을 잡 없음 → 빈 결과
    end if;
    last_id := j.id;
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
end;
$$;

-- 잡 종결/일시정지 + 락 해제. 재큐잉은 resume_job, 취소는 cancel_job 전용
-- (V1 결함 4: running→cancelled 는 전이 화이트리스트에 없음 — release 에서 제외).
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
  if p_status not in ('done','failed','paused_for_human') then
    raise exception 'release 불가 상태: %', p_status;
  end if;
  update public.jobs
    set status = p_status,
        finished_at = case when p_status in ('done','failed') then now() else finished_at end,
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

-- 취소: queued 또는 paused_for_human 에서만(화이트리스트와 1:1 정합).
create or replace function public.cancel_job(p_job_id bigint, p_reason text default '')
returns setof public.jobs
language plpgsql
security definer
set search_path = public
as $$
begin
  update public.jobs
    set status = 'cancelled', finished_at = now(),
        result_summary = coalesce(p_reason, '')
    where id = p_job_id and status in ('queued','paused_for_human');
  if not found then
    raise exception 'queued/paused_for_human 상태의 잡 % 가 없습니다', p_job_id;
  end if;
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
revoke all on function public.cancel_job(bigint, text) from public, anon, authenticated;
grant execute on function public.claim_next_job(text) to service_role;
grant execute on function public.release_job(bigint, text, text, text) to service_role;
grant execute on function public.resume_job(bigint) to service_role;
grant execute on function public.cancel_job(bigint, text) to service_role;
