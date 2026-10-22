-- App 02: expose the existing fleet registry + heartbeat as one readiness input.
-- Registration metadata stays in fleet_machines; this does not create a second registry.

drop function if exists public.linkedin_ready_machines();
create function public.linkedin_ready_machines()
returns table (
  machine_id text,
  queue_machine text,
  platform text,
  hostname_aliases jsonb,
  agent_version text,
  capabilities jsonb,
  last_heartbeat_at timestamptz,
  delegated_for_request_id text,
  linkedin_rps_logged_in boolean
)
language sql
security definer
set search_path = ''
stable
as $$
  select
    case when fm.machine_id = 'macbook' then 'macbook_pro' else fm.machine_id end,
    fm.machine_id,
    fm.os,
    case
      when jsonb_typeof(fm.labels -> 'hostname_aliases') = 'array'
        then fm.labels -> 'hostname_aliases'
      when fm.machine_id = 'macmini' then '["mac-mini","맥미니"]'::jsonb
      when fm.machine_id in ('macbook','macbook_pro')
        then '["macbook","macbook-pro","맥북","맥북프로"]'::jsonb
      when fm.machine_id = 'winpc' then '["win-pc","윈pc","윈도우pc"]'::jsonb
      else '[]'::jsonb
    end,
    fm.worker_version,
    case
      when jsonb_typeof(fm.labels -> 'capabilities') = 'array'
        then fm.labels -> 'capabilities'
      when coalesce(hb.linkedin_rps_logged_in, false)
        then '["linkedin_rps"]'::jsonb
      else '[]'::jsonb
    end,
    hb.beat_at,
    nullif(fm.labels ->> 'delegated_for_request_id', ''),
    coalesce(hb.linkedin_rps_logged_in, false)
  from public.fleet_machines fm
  left join public.machine_heartbeats hb on hb.machine = fm.machine_id
  where fm.enabled and not fm.draining;
$$;

revoke all on function public.linkedin_ready_machines()
  from public, anon, authenticated;
grant execute on function public.linkedin_ready_machines() to service_role, anon;
