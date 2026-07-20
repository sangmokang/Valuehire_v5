-- 조각 C — 디스코드 직결 게이트웨이 최소권한 RPC (INV-D5, goal §5C).
-- 근거: docs/prompts/discord-direct-connect-goal-2026-07-17.md §2 INV-D5
-- ("수신기는 Supabase service-role 키를 보유하지 않는다 — enqueue/조회 전용
-- 최소권한 자격(RPC 또는 제한 키)만"). Codex Rescue 4차 재검증 지적 — 스크립트
-- 레벨 방어(전용 env 값이 SUPABASE_SERVICE_ROLE_KEY 와 문자열 동일하면 거부)만으로는
-- "제한 키가 실제로 제한돼 있음"을 증명 못 한다 — 이 마이그레이션이 DB 레벨 강제다.
--
-- v2(Codex Rescue 5차 재검증 CRITICAL 반영, 최초판 재설계):
-- anon 키는 Supabase 공식 문서 기준 "공개 가능한 키"다(로그인 안 한 모든 요청이
-- 같은 anon 역할을 공유). 최초판은 discord_gateway_enqueue 가 호출자가 p_role='owner'
-- /p_skill='agent' 를 자유롭게 지정하게 허용했는데, 이러면 anon 키를 아는 누구나
-- Discord 를 거치지 않고 owner/agent 잡을 위조해 큐에 꽂을 수 있었다(신원 검증 없음
-- — fleet_dispatch.is_owner() 는 이 RPC 호출 이전 단계에 있으므로 RPC 자체는 그
-- 결과를 신뢰할 수 없다). 또한 resume_job/cancel_job 을 anon 에 grant 하면 anon 키
-- 보유자가 최근 잡 조회 → 임의 잡 취소/재개까지 앱 레벨 인가를 완전히 우회할 수
-- 있었다. v2 는 이 두 결함을 구조적으로 막는다:
--   1) discord_gateway_enqueue 는 role 을 항상 'member' 로 강제(호출자가 뭘 보내든
--      무시)하고 skill 은 humansearch/aisearch/url 만 허용한다('agent'·owner 잡은
--      이 최소권한 경로로 아예 등록 불가 — 진짜 owner/agent 잡은 더 신뢰된 경로가
--      필요하며 이 스크립트 범위 밖의 별도 과제로 이월한다).
--   2) resume_job/cancel_job 에 대한 anon grant 를 아예 하지 않는다(이 파일은 그
--      두 함수를 건드리지 않는다 — 여전히 20260711 마이그레이션대로 service_role
--      전용). 최소권한 게이트웨이 클라이언트(MinimalPrivilegeQueueClient)는 owner
--      전용 명령(fleet-resume/fleet-cancel)을 지원하지 않고 명시적으로 거부한다
--      (기능 축소를 감수하고 보안 경계를 지킨다 — "일부 기능 없음" 이 "누구나
--      임의 잡 취소 가능"보다 훨씬 안전하다).
--
-- 설계: 게이트웨이는 anon 키(Supabase 표준 공개키, 커스텀 JWT 발급 불필요)를 쓴다.
-- anon 은 20260711_fleet_jobs_queue.sql 이 이미 public.jobs 에 대한 모든 직접 권한을
-- revoke 해뒀다(테이블 SELECT/INSERT/UPDATE/DELETE 전부 불가) — 이 마이그레이션은
-- 3개의 SECURITY DEFINER RPC 함수(enqueue-저권한전용/최근조회/idempotency 조회)에만
-- EXECUTE 를 얹는다. anon 키가 유출돼도 공격자는 humansearch/aisearch/url 스킬의
-- member 역할 잡 등록 + 제한된 컬럼의 최근 잡 조회 이상을 할 수 없다(owner 잡 위조·
-- agent 잡 위조·잡 취소·재개·다른 테이블·임의 SQL 전부 불가).
--
-- 적용 방법: 이 파일은 코드로만 존재하며 로컬 git worktree 에서 라이브 Supabase 에
-- 적용되지 않는다(`supabase db push` 또는 대시보드 SQL 편집기 실행은 별도 배포 단계 —
-- goal §7 "조각 J 라이브 검증, 사장님 승인 후"). 적용 전에는
-- DISCORD_GATEWAY_SUPABASE_KEY 에 anon 키를 넣어도 이 함수들이 아직 없어 게이트웨이
-- enqueue/조회가 전부 실패한다(fail-closed 방향 — 관리자 키로 자동 폴백하지 않으므로
-- 안전측 실패).

-- machine 화이트리스트는 public.jobs 테이블 CHECK 제약(20260711_fleet_jobs_queue.sql)
-- 이 이미 최종 강제한다 — 이 함수 안에서 같은 목록을 따로 하드코딩하면 두 곳이
-- 어긋날 여지가 생기므로(Codex 5차 지적) 여기서는 중복 검사하지 않고 INSERT 가
-- 테이블 CHECK 위반 시 그대로 예외를 내게 둔다.
create or replace function public.discord_gateway_enqueue(
  p_machine text, p_position_url text, p_requested_by text,
  p_skill text default 'aisearch', p_params jsonb default '{}'::jsonb,
  p_account_key text default ''
) returns setof public.jobs
language plpgsql
security definer
set search_path = ''
as $$
begin
  -- v2 CRITICAL 봉인: 호출자가 role/skill 을 자유롭게 골라 owner·agent 잡을 위조하지
  -- 못하게, 이 RPC 는 role 을 항상 'member' 로 강제하고 skill 을 검색 3종으로만
  -- 제한한다(호출자가 p_skill 로 무엇을 보내든 이 화이트리스트 밖이면 거부).
  if p_skill not in ('humansearch', 'aisearch', 'url') then
    raise exception '이 최소권한 경로는 humansearch/aisearch/url 스킬만 허용합니다: %', p_skill;
  end if;
  if btrim(coalesce(p_requested_by, '')) = '' then
    raise exception 'requested_by 는 필수입니다';
  end if;
  return query
    insert into public.jobs (
      machine, skill, position_url, params, requested_by, role, account_key
    ) values (
      p_machine, p_skill, coalesce(p_position_url, ''), coalesce(p_params, '{}'::jsonb),
      p_requested_by, 'member', coalesce(p_account_key, '')
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
set search_path = ''
as $$
  select id, machine, skill, status, created_at
  from public.jobs
  order by id desc
  limit greatest(1, least(coalesce(p_limit, 10), 50));
$$;

-- 조각 B(idempotent enqueue) 회수 경로용 — 같은 이벤트 2회 → 잡 1개(INV-D2)를 이
-- 최소권한 경로에서도 유지하려면 idempotency_key 로 기존 잡을 다시 찾을 수 있어야
-- 한다(JobQueueClient.job_by_idempotency_key 와 동등, anon 안전 버전). 반환 컬럼은
-- discord_gateway_recent_jobs 와 동일하게 제한(요청자 신원·params 원문 비노출).
create or replace function public.discord_gateway_job_by_idempotency_key(p_key text)
returns table (id bigint, machine text, skill text, status text, created_at timestamptz)
language sql
security definer
set search_path = ''
as $$
  select id, machine, skill, status, created_at
  from public.jobs
  where params ->> 'idempotency_key' = p_key
  limit 1;
$$;

revoke all on function public.discord_gateway_enqueue(text, text, text, text, jsonb, text)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_recent_jobs(int)
  from public, anon, authenticated;
revoke all on function public.discord_gateway_job_by_idempotency_key(text)
  from public, anon, authenticated;
grant execute on function public.discord_gateway_enqueue(text, text, text, text, jsonb, text) to anon;
grant execute on function public.discord_gateway_recent_jobs(int) to anon;
grant execute on function public.discord_gateway_job_by_idempotency_key(text) to anon;

-- v2: resume_job/cancel_job 은 이 파일에서 anon 에 grant 하지 않는다(위 설계 노트
-- 참고) — 20260711_fleet_jobs_queue.sql 이 정한 service_role 전용 상태를 그대로
-- 유지한다. 게이트웨이의 owner 전용 명령(fleet-resume/fleet-cancel)은 이 최소권한
-- 경로에서 지원하지 않는다(scripts/discord_direct_gateway.py 의
-- MinimalPrivilegeQueueClient.resume/cancel 이 명시적으로 거부).

-- anon 은 여전히 public.jobs/public.account_locks 테이블 자체에는 어떤 직접 권한도
-- 없다(20260711 마이그레이션의 revoke 를 이 파일에서 다시 명시적으로 재확인 — 라이브
-- 재적용 안전을 위해 조건 없이 반복 실행 가능하게 REVOKE 는 멱등).
revoke all on public.jobs from anon;
revoke all on public.account_locks from anon;
