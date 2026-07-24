-- #196 — 실행 중(running) 잡 즉시중지 허용 (2026-07-24, 사장님 1순위)
--
-- 왜: 상태 트리거가 running→cancelled 를 금지하고 cancel_job 이 queued/paused 만
--     취소해, 실행 중 세션을 멈출 경로가 아예 없었다("중지해"가 무시되던 근본 원인).
--
-- 무엇: (1) 전이 가드에 running→cancelled 를 한 칸 추가(다른 전이는 불변),
--       (2) cancel_job 이 running 도 취소 대상에 포함.
--     워커는 실행 중 자기 잡 상태를 폴링하다 cancelled 를 보면 서브프로세스
--     프로세스그룹을 죽이고 재release 하지 않는다(협조적 취소, 코드 측).
--
-- 안전: running→cancelled 는 owner 취소 요청으로만 일어난다(앱 레벨 is_owner +
--       후속 이슈의 게이트웨이 안전 경로). 워커의 finish_job 은 여전히
--       where status='running' 이라, 이미 cancelled 된 잡을 done/failed 로
--       되돌리지 못한다(경합 안전 — 취소가 이긴다).

create or replace function public.jobs_transition_guard()
 returns trigger
 language plpgsql
as $function$
begin
  -- V1 2R: no-op 재설정(running→running 등)도 python 화이트리스트와 동일하게 거부
  if not (
       (old.status = 'queued'           and new.status in ('running','cancelled'))
    or (old.status = 'running'          and new.status in ('paused_for_human','done','failed','cancelled'))
    or (old.status = 'paused_for_human' and new.status in ('queued','cancelled'))
  ) then
    raise exception '금지된 상태 전이: % -> %', old.status, new.status;
  end if;
  return new;
end;
$function$;

create or replace function public.cancel_job(p_job_id bigint, p_reason text default ''::text)
 returns setof public.jobs
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
begin
  update public.jobs
    set status = 'cancelled', finished_at = now(),
        result_summary = coalesce(p_reason, '')
    where id = p_job_id and status in ('queued','running','paused_for_human');
  if not found then
    raise exception 'queued/running/paused_for_human 상태의 잡 % 가 없습니다', p_job_id;
  end if;
  -- #196 Codex V2 2R: running 잡 취소 시 account_lock 을 반드시 해제한다(release_job 과
  -- 동일). 안 하면 그 account_key 가 영구 점유돼 이후 claim 이 막힌다.
  delete from public.account_locks where job_id = p_job_id;
  return query select * from public.jobs where id = p_job_id;
end;
$function$;
