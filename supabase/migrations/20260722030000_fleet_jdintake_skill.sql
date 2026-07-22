-- #AC-N3 — 큐 허용 스킬에 `jdintake` 추가 (2026-07-22)
--
-- 왜: SOT-32 라우팅표의 (web, find) 가 queue_skill = 'jdintake' 를 가리키는데,
--     테이블 check 제약과 enqueue RPC 가 3~4종만 허용해 큐 입구에서 거부된다.
--     사장님 요구 N3("웹에서 공식 채용페이지에서 …찾아 ⇒ JD 파악")이 이 벽에 막힌다.
--
-- 원칙 유지: 화이트리스트를 **없애는 게 아니라 한 칸 넓힌다**. 임의 스킬 실행은 계속 금지
--          (E24 결정 — 제한 해제가 아니라 목록 확장).
--
-- 짝 갱신(부분 갱신 방지 — tests/test_jdintake_skill.py 가 일치를 검사):
--   tools/multi_position_sourcing/job_queue.py   FLEET_SKILLS
--   .claude/hooks/guards/discord-bot-skill-whitelist.py  _ALLOWED_SKILLS
--   skills/jdintake/SKILL.md

alter table public.jobs drop constraint if exists jobs_skill_check;
alter table public.jobs
  add constraint jobs_skill_check
  check (skill in ('humansearch', 'aisearch', 'url', 'agent', 'jdintake'));

-- enqueue RPC 의 하드코딩 목록도 같이 넓힌다(20260719_discord_gateway_minimal_privilege_rpc.sql:60).
create or replace function public.discord_gateway_enqueue(
  p_machine text,
  p_skill text,
  p_position_url text,
  p_requested_by text,
  p_role text,
  p_params jsonb default '{}'::jsonb,
  p_account_key text default ''
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.jobs%rowtype;
  v_key text;
begin
  if p_skill not in ('humansearch', 'aisearch', 'url', 'jdintake') then
    raise exception 'skill not allowed: %', p_skill using errcode = '22023';
  end if;
  if p_machine not in ('macmini', 'macbook', 'winpc') then
    raise exception 'machine not allowed: %', p_machine using errcode = '22023';
  end if;
  if p_role not in ('owner', 'member') then
    raise exception 'role not allowed: %', p_role using errcode = '22023';
  end if;

  v_key := nullif(trim(coalesce(p_params ->> 'idempotency_key', '')), '');
  if v_key is not null then
    select * into v_row from public.jobs
     where params ->> 'idempotency_key' = v_key
     order by id desc limit 1;
    if found then
      return jsonb_build_object('id', v_row.id, 'status', v_row.status,
                                'idempotent', true);
    end if;
  end if;

  insert into public.jobs (machine, skill, position_url, requested_by, role,
                           params, account_key, status)
  values (p_machine, p_skill, p_position_url, p_requested_by, p_role,
          coalesce(p_params, '{}'::jsonb), coalesce(p_account_key, ''), 'queued')
  returning * into v_row;

  return jsonb_build_object('id', v_row.id, 'status', v_row.status,
                            'idempotent', false);
end;
$$;
