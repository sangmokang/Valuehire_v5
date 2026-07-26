-- App 04: sanitized App 03 reports only. Raw CDP responses and secrets are rejected.
create table public.fleet_browser_inventory (
  request_id text not null,
  source_machine_id text not null
    check (source_machine_id in ('macmini', 'macbook_pro', 'winpc')),
  captured_at timestamptz not null,
  schema_version integer not null check (schema_version = 1),
  integrity_hash text not null check (integrity_hash ~ '^[0-9a-f]{64}$'),
  report jsonb not null check (jsonb_typeof(report) = 'object'),
  received_at timestamptz not null default now(),
  unique (request_id, source_machine_id)
);
alter table public.fleet_browser_inventory enable row level security;
create or replace function public.record_browser_inventory(
  p_source_machine_id text,
  p_report jsonb
)
returns table (accepted boolean, integrity_hash text)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_machine text := p_report ->> 'machine_id';
  v_request text := p_report ->> 'request_id';
  v_hash text := p_report ->> 'integrity_hash';
  v_captured timestamptz;
begin
  if jsonb_typeof(p_report) <> 'object'
     or coalesce(v_machine, '') = ''
     or v_machine is distinct from p_source_machine_id
     or coalesce(v_request, '') = ''
     or coalesce(v_hash, '') !~ '^[0-9a-f]{64}$'
     or (p_report ->> 'schema_version') <> '1'
     or coalesce(p_report ->> 'captured_at', '') !~ '(Z|[+]00:00)$'
     or not exists (
       select 1 from public.fleet_machines fm
       where fm.enabled
         and (case when fm.machine_id = 'macbook'
                   then 'macbook_pro' else fm.machine_id end) = v_machine
     )
     or lower(p_report::text) ~
       '"(cookie|password|secret|token|websocketdebuggerurl)"[[:space:]]*:'
  then
    raise exception 'invalid sanitized browser inventory report';
  end if;
  begin
    v_captured := (p_report ->> 'captured_at')::timestamptz;
  exception when others then
    raise exception 'invalid browser inventory captured_at';
  end;
  insert into public.fleet_browser_inventory (
    request_id, source_machine_id, captured_at, schema_version,
    integrity_hash, report
  ) values (
    v_request, v_machine, v_captured, 1, v_hash, p_report
  )
  on conflict (request_id, source_machine_id) do update
    set received_at = public.fleet_browser_inventory.received_at
    where public.fleet_browser_inventory.integrity_hash = excluded.integrity_hash;

  if not found then
    raise exception 'SNAPSHOT_CONFLICT';
  end if;
  return query select true, v_hash;
end;
$$;

revoke all on table public.fleet_browser_inventory
  from public, anon, authenticated;
grant select on table public.fleet_browser_inventory to service_role;
revoke all on function public.record_browser_inventory(text, jsonb)
  from public, anon, authenticated;
grant execute on function public.record_browser_inventory(text, jsonb)
  to service_role;
