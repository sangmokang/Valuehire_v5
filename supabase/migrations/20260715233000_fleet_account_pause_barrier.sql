-- 이슈 #105: paused_for_human 을 워커 메모리가 아닌 계정 단위 서버 장벽으로 강제한다.
-- enqueue 는 허용하고 claim 만 막아 요청을 잃지 않으며, 시간 만료 없이 수동 해소를 기다린다.

-- 실행 중인 레거시 공백 키는 계정 락 없이 이미 실행 중인 상태라 자동 보정하면 안 된다.
-- 배포를 명시적으로 멈춰 운영자가 먼저 확인하게 한다. 대기·일시정지 행은 현재 기본키
-- 정책과 같은 값으로 안전하게 보정해 영구 대기나 pause 전환 실패를 막는다.
do $$
begin
  if exists (
    select 1 from public.jobs
    where status = 'running' and btrim(account_key) = ''
  ) then
    raise exception 'running 상태의 공백 account_key 잡을 먼저 수동 확인해야 합니다';
  end if;
end;
$$;

update public.jobs
set account_key = case
  when skill = 'url' then 'portal:linkedin_rps'
  else 'portal:' || machine
end
where status in ('queued','paused_for_human')
  and btrim(account_key) = '';

alter table public.jobs drop constraint if exists jobs_active_account_key_nonblank_chk;
alter table public.jobs add constraint jobs_active_account_key_nonblank_chk
  check (
    status not in ('queued','running','paused_for_human')
    or (
      btrim(account_key) <> ''
      and account_key = btrim(account_key)
      and account_key !~ '[[:space:]]'
    )
  );

create index if not exists jobs_paused_account_key_idx
  on public.jobs (account_key)
  where status = 'paused_for_human' and btrim(account_key) <> '';

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
    select q.* into j
      from public.jobs q
      where q.machine = p_machine
        and q.status = 'queued'
        and btrim(q.account_key) <> ''
        and q.id > last_id
        and not exists (
          select 1
          from public.account_locks al
          where al.account_key = q.account_key
        )
        and not exists (
          select 1
          from public.jobs paused
          where paused.status = 'paused_for_human'
            and btrim(paused.account_key) <> ''
            and paused.account_key = q.account_key
        )
      order by q.id
      limit 1
      for update of q skip locked;
    if not found then
      return;
    end if;
    last_id := j.id;
    begin
      insert into public.account_locks (account_key, holder_machine, job_id)
      values (j.account_key, p_machine, j.id);
      locked := true;
    exception when unique_violation then
      locked := false;
    end;
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

revoke all on function public.claim_next_job(text) from public, anon, authenticated;
grant execute on function public.claim_next_job(text) to service_role;
