-- 조각 C — 디스코드 직결 게이트웨이 최소권한 RPC (INV-D5, goal §5C).
-- 근거: docs/prompts/discord-direct-connect-goal-2026-07-17.md §2 INV-D5
-- ("수신기는 Supabase service-role 키를 보유하지 않는다 — enqueue/조회 전용
-- 최소권한 자격(RPC 또는 제한 키)만"). Codex Rescue 4차 재검증 지적 — 스크립트
-- 레벨 방어(전용 env 값이 SUPABASE_SERVICE_ROLE_KEY 와 문자열 동일하면 거부)만으로는
-- "제한 키가 실제로 제한돼 있음"을 증명 못 한다 — 이 마이그레이션이 DB 레벨 강제다.
--
-- 설계: 게이트웨이는 anon 키(Supabase 표준 공개키, 커스텀 JWT 발급 불필요)를 쓴다.
-- anon 은 20260711_fleet_jobs_queue.sql 이 이미 public.jobs 에 대한 모든 직접 권한을
-- revoke 해뒀다(테이블 SELECT/INSERT/UPDATE/DELETE 전부 불가) — 이 마이그레이션은
-- 딱 4개의 SECURITY DEFINER RPC 함수(enqueue/최근조회/resume/cancel)에만 EXECUTE 를
-- 얹는다. anon 키가 유출돼도 공격자는 이 4개 함수 호출 이상을 할 수 없다(다른
-- 테이블·임의 SQL·전체 컬럼 조회 전부 불가) — 이것이 "관리자급 키 전체 이양"에서
-- "이 4개 함수만" 으로 반경을 줄이는 실질적 최소권한이다.
--
-- 경계 명시(정직한 한계): resume_job/cancel_job 은 호출자 신원을 SQL 레벨에서
-- 검사하지 않는다(job_id 만 보고 상태 전이 규칙만 지킨다) — 실제 owner 인가는
-- fleet_dispatch.is_owner() 가 Discord 신원으로 이미 앱 레벨에서 걸렀고, 이 RPC 는
-- 그 뒤에만 도달한다. DB grant 는 "무엇을 방어하는가"가 다르다: 이 층은 anon 키
-- 자체가 유출됐을 때의 블라스트 반경(전체 DB 접근 → 이 4개 함수)을 줄이는 것이지,
-- 애플리케이션 레벨 인가를 대체하지 않는다.
--
-- 적용 방법: 이 파일은 코드로만 존재하며 로컬 git worktree 에서 라이브 Supabase 에
-- 적용되지 않는다(`supabase db push` 또는 대시보드 SQL 편집기 실행은 별도 배포 단계 —
-- goal §7 "조각 J 라이브 검증, 사장님 승인 후"). 적용 전에는
-- DISCORD_GATEWAY_SUPABASE_KEY 에 anon 키를 넣어도 이 4개 함수가 아직 없어 게이트웨이
-- enqueue/조회/resume/cancel 이 전부 실패한다(fail-closed 방향 — 관리자 키로 자동
-- 폴백하지 않으므로 안전측 실패).

create or replace function public.discord_gateway_enqueue(
  p_machine text, p_skill text, p_position_url text,
  p_requested_by text, p_role text, p_params jsonb default '{}'::jsonb,
  p_account_key text default ''
) returns setof public.jobs
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_machine not in ('macmini', 'macbook', 'winpc') then
    raise exception 'unknown machine: %', p_machine;
  end if;
  if p_skill not in ('humansearch', 'aisearch', 'url', 'agent') then
    raise exception 'unknown skill: %', p_skill;
  end if;
  if btrim(coalesce(p_requested_by, '')) = '' then
    raise exception 'requested_by 는 필수입니다';
  end if;
  if p_role not in ('owner', 'member') then
    raise exception 'unknown role: %', p_role;
  end if;
  return query
    insert into public.jobs (
      machine, skill, position_url, params, requested_by, role, account_key
    ) values (
      p_machine, p_skill, coalesce(p_position_url, ''), coalesce(p_params, '{}'::jsonb),
      p_requested_by, p_role, coalesce(p_account_key, '')
    )
    returning *;
end;
$$;

-- 최근 잡 조회 — id/machine/skill/status/created_at 만 노출(요청자 신원·params 원문 등
-- 민감 필드 제외 — direct_receiver._render_response·fleet-status 멤버뷰가 어차피 이
-- 필드만 씀, 조각 F "멤버 fleet-status 에 owner 지시 원문 부재" 요구와도 정합).
create or replace function public.discord_gateway_recent_jobs(p_limit int default 10)
returns table (id bigint, machine text, skill text, status text, created_at timestamptz)
language sql
security definer
set search_path = public
as $$
  select id, machine, skill, status, created_at
  from public.jobs
  order by id desc
  limit greatest(1, least(coalesce(p_limit, 10), 50));
$$;

-- 조각 B(idempotent enqueue) 회수 경로용 — 같은 이벤트 2회 → 잡 1개(INV-D2)를 이
-- 최소권한 경로에서도 유지하려면 idempotency_key 로 기존 잡을 다시 찾을 수 있어야
-- 한다(JobQueueClient.job_by_idempotency_key 와 동등, anon 안전 버전).
create or replace function public.discord_gateway_job_by_idempotency_key(p_key text)
returns setof public.jobs
language sql
security definer
set search_path = public
as $$
  select * from public.jobs
  where params ->> 'idempotency_key' = p_key
  limit 1;
$$;

revoke all on function public.discord_gateway_enqueue(text, text, text, text, text, jsonb, text)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_recent_jobs(int)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_job_by_idempotency_key(text)
  from public, anon, authenticated;
grant execute on function public.discord_gateway_enqueue(text, text, text, text, text, jsonb, text) to anon;
grant execute on function public.discord_gateway_recent_jobs(int) to anon;
grant execute on function public.discord_gateway_job_by_idempotency_key(text) to anon;

-- 기존 resume_job/cancel_job(20260711_fleet_jobs_queue.sql) 은 service_role 전용이었다.
-- 게이트웨이(anon)도 owner 전용 명령(fleet-resume/fleet-cancel)을 쓸 수 있도록 EXECUTE
-- 를 추가로 부여한다 — 함수 재정의 없이 grant 만 추가(단일 출처 유지).
grant execute on function public.resume_job(bigint) to anon;
grant execute on function public.cancel_job(bigint, text) to anon;

-- anon 은 여전히 public.jobs/public.account_locks 테이블 자체에는 어떤 직접 권한도
-- 없다(20260711 마이그레이션의 revoke 를 이 파일에서 다시 명시적으로 재확인 — 라이브
-- 재적용 안전을 위해 조건 없이 반복 실행 가능하게 REVOKE 는 멱등).
revoke all on public.jobs from anon;
revoke all on public.account_locks from anon;
