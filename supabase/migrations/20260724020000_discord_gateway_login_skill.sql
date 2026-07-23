-- #190 — 최소권한 게이트웨이 RPC 화이트리스트에 `login` 추가 (2026-07-24)
--
-- 왜: #188 로 login 이 큐 정식 스킬이 됐지만 이 RPC 가 여전히 검색 3종만 허용해
--     디스코드 /login 이 라이브에서 등록되지 못한다.
--
-- 원칙 유지(E24 — 목록 확장, 제한 해제 아님). 기존 가드 전부 보존:
--   * role 은 항상 'member' 로 강제(호출자 지정 불가 — owner 잡 위조 방지)
--   * idempotency_key 는 discord 이벤트 파생만(^discord:[0-9]{15,22}$)
--   * advisory lock 기반 원자적 enqueue-or-get(같은 이벤트 2회 → 잡 1개)
--   * agent/그 외 스킬은 계속 거부
-- login 의 position_url 은 빈 문자열('') — jobs 테이블 제약은
-- 20260724010000_fleet_login_skill.sql 이 이미 login 한정으로 허용한다.
--
-- 본문은 라이브 함수 정의(2026-07-24 실측 pg_get_functiondef)를 그대로 복제하고
-- 화이트리스트 한 줄만 넓힌다.

create or replace function public.discord_gateway_enqueue(
  p_machine text, p_position_url text, p_requested_by text,
  p_skill text default 'aisearch'::text, p_params jsonb default '{}'::jsonb,
  p_account_key text default ''::text)
 returns table(id bigint, machine text, skill text, status text,
               created_at timestamptz, created boolean)
 language plpgsql
 security definer
 set search_path to ''
as $function$
declare
  event_key text := coalesce(p_params->>'idempotency_key', '');
begin
  if p_skill not in ('humansearch', 'aisearch', 'url', 'login') then
    raise exception 'minimal gateway skill is not allowed: %', p_skill;
  end if;
  if btrim(coalesce(p_requested_by, '')) = '' then
    raise exception 'requested_by is required';
  end if;
  if event_key !~ '^discord:[0-9]{15,22}$' then
    raise exception 'idempotency_key is required and must derive from a Discord event';
  end if;

  perform pg_advisory_xact_lock(pg_catalog.hashtextextended(event_key, 0));
  return query
    select existing.id, existing.machine, existing.skill, existing.status,
           existing.created_at, false
      from public.jobs as existing
     where existing.params->>'idempotency_key' = event_key
     order by existing.id
     limit 1;
  if found then
    return;
  end if;

  return query
    with inserted as (
      insert into public.jobs (
        machine, skill, position_url, params, requested_by, role, account_key
      ) values (
        p_machine, p_skill, coalesce(p_position_url, ''), coalesce(p_params, '{}'::jsonb),
        p_requested_by, 'member', coalesce(p_account_key, '')
      )
      returning public.jobs.id, public.jobs.machine, public.jobs.skill,
                public.jobs.status, public.jobs.created_at
    )
    select inserted.id, inserted.machine, inserted.skill, inserted.status,
           inserted.created_at, true
      from inserted;
end;
$function$;
