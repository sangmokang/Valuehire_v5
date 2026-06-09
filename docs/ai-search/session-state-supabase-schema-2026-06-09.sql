-- Valuehire multisite session persistence v2.
-- Store only app-level encrypted storage snapshots. Cookie, localStorage,
-- credential, token, and webhook values must never be inserted as plaintext.

create extension if not exists pgcrypto;

create table if not exists public.session_state (
  id uuid primary key default gen_random_uuid(),
  site text not null check (site in ('saramin', 'jobkorea', 'linkedin_rps')),
  worker_id text not null,
  storage_state_enc bytea not null,
  is_validated boolean not null default false,
  kind text not null check (kind in ('current', 'last_known_good')),
  captured_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (site, worker_id, kind),
  check (octet_length(storage_state_enc) > 64),
  constraint session_state_validated_only_check
    check (is_validated = true),
  constraint session_state_encrypted_envelope_check
    check (substring(storage_state_enc from 1 for 5) = decode('5648535331', 'hex'))
);

do $$
begin
  alter table public.session_state
    add constraint session_state_encrypted_envelope_check
    check (substring(storage_state_enc from 1 for 5) = decode('5648535331', 'hex'));
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  alter table public.session_state
    add constraint session_state_validated_only_check
    check (is_validated = true) not valid;
exception
  when duplicate_object then null;
end;
$$;

create table if not exists public.reauth_events (
  id uuid primary key default gen_random_uuid(),
  site text not null check (site in ('saramin', 'jobkorea', 'linkedin_rps')),
  worker_id text not null,
  cause text not null check (length(cause) between 1 and 128),
  recovered_by text not null check (recovered_by in ('snapshot_reinject', 'auto_relogin', 'human', 'unrecovered')),
  occurred_at timestamptz not null default now(),
  constraint reauth_events_cause_allowed_check
    check (
      cause in (
        'profile_corrupt',
        'cookie_rotated',
        'forced_logout',
        'login_redirect',
        'login_marker_missing',
        'login_marker_lost',
        'unknown'
      )
      or cause ~ '^http_(401|403)$'
    )
);

do $$
begin
  alter table public.reauth_events
    add constraint reauth_events_cause_allowed_check
    check (
      cause in (
        'profile_corrupt',
        'cookie_rotated',
        'forced_logout',
        'login_redirect',
        'login_marker_missing',
        'login_marker_lost',
        'unknown'
      )
      or cause ~ '^http_(401|403)$'
    ) not valid;
exception
  when duplicate_object then null;
end;
$$;

create index if not exists reauth_events_site_worker_occurred_at_idx
  on public.reauth_events (site, worker_id, occurred_at desc);

alter table public.session_state enable row level security;
alter table public.reauth_events enable row level security;

revoke all on public.session_state from public, anon, authenticated;
revoke all on public.reauth_events from public, anon, authenticated;
grant select, insert on public.reauth_events to service_role;

-- Supabase service_role bypasses RLS by design. Keep that key server-side only.
-- These policies make the intended writer explicit for deployments that grant
-- direct role privileges rather than using only the service_role bypass.
drop policy if exists service_role_session_state_all on public.session_state;
create policy service_role_session_state_all
  on public.session_state
  for all
  to service_role
  using (true)
  with check (true);

drop policy if exists service_role_reauth_events_all on public.reauth_events;
create policy service_role_reauth_events_all
  on public.reauth_events
  for all
  to service_role
  using (true)
  with check (true);

create or replace function public.save_validated_session_snapshot(
  site_arg text,
  worker_id_arg text,
  storage_state_b64_arg text,
  captured_at_arg timestamptz
)
returns table (
  site text,
  worker_id text,
  storage_state_b64 text,
  is_validated boolean,
  kind text,
  captured_at timestamptz,
  updated_at timestamptz
)
language plpgsql
security definer
set search_path = public
as $$
declare
  previous_current public.session_state%rowtype;
  storage_state_decoded bytea;
begin
  if site_arg not in ('saramin', 'jobkorea', 'linkedin_rps') then
    raise exception 'unsupported site';
  end if;

  storage_state_decoded := decode(storage_state_b64_arg, 'base64');
  if octet_length(storage_state_decoded) <= 64
     or substring(storage_state_decoded from 1 for 5) <> decode('5648535331', 'hex') then
    raise exception 'storage_state_enc must use Valuehire encrypted session envelope';
  end if;

  select *
    into previous_current
    from public.session_state ss
    where ss.site = site_arg
      and ss.worker_id = worker_id_arg
      and ss.kind = 'current'
      and ss.is_validated = true;

  if found then
    insert into public.session_state (
      site, worker_id, storage_state_enc, is_validated, kind, captured_at, updated_at
    )
    values (
      previous_current.site,
      previous_current.worker_id,
      previous_current.storage_state_enc,
      true,
      'last_known_good',
      previous_current.captured_at,
      captured_at_arg
    )
    on conflict (site, worker_id, kind) do update
      set storage_state_enc = excluded.storage_state_enc,
          is_validated = true,
          captured_at = excluded.captured_at,
          updated_at = excluded.updated_at;
  end if;

  insert into public.session_state (
    site, worker_id, storage_state_enc, is_validated, kind, captured_at, updated_at
  )
  values (
    site_arg,
    worker_id_arg,
    storage_state_decoded,
    true,
    'current',
    captured_at_arg,
    captured_at_arg
  )
  on conflict (site, worker_id, kind) do update
    set storage_state_enc = excluded.storage_state_enc,
        is_validated = true,
        captured_at = excluded.captured_at,
        updated_at = excluded.updated_at;

  return query
    select ss.site,
           ss.worker_id,
           encode(ss.storage_state_enc, 'base64') as storage_state_b64,
           ss.is_validated,
           ss.kind,
           ss.captured_at,
           ss.updated_at
      from public.session_state ss
      where ss.site = site_arg
        and ss.worker_id = worker_id_arg
        and ss.kind = 'current';
end;
$$;

create or replace function public.latest_validated_session_snapshot(
  site_arg text,
  worker_id_arg text
)
returns table (
  site text,
  worker_id text,
  storage_state_b64 text,
  is_validated boolean,
  kind text,
  captured_at timestamptz,
  updated_at timestamptz
)
language sql
security definer
set search_path = public
as $$
  select ss.site,
         ss.worker_id,
         encode(ss.storage_state_enc, 'base64') as storage_state_b64,
         ss.is_validated,
         ss.kind,
         ss.captured_at,
         ss.updated_at
    from public.session_state ss
    where ss.site = site_arg
      and ss.worker_id = worker_id_arg
      and ss.is_validated = true
      and ss.kind in ('current', 'last_known_good')
    order by case ss.kind when 'current' then 0 else 1 end, ss.captured_at desc
    limit 1;
$$;

create or replace function public.validated_session_snapshots(
  site_arg text,
  worker_id_arg text
)
returns table (
  site text,
  worker_id text,
  storage_state_b64 text,
  is_validated boolean,
  kind text,
  captured_at timestamptz,
  updated_at timestamptz
)
language sql
security definer
set search_path = public
as $$
  select ss.site,
         ss.worker_id,
         encode(ss.storage_state_enc, 'base64') as storage_state_b64,
         ss.is_validated,
         ss.kind,
         ss.captured_at,
         ss.updated_at
    from public.session_state ss
    where ss.site = site_arg
      and ss.worker_id = worker_id_arg
      and ss.is_validated = true
      and ss.kind in ('current', 'last_known_good')
    order by case ss.kind when 'current' then 0 else 1 end, ss.captured_at desc
    limit 2;
$$;

create or replace function public.reauth_weekly_counts(
  week_start_arg timestamptz
)
returns table (
  site text,
  worker_id text,
  cause text,
  recovered_by text,
  count bigint
)
language sql
security definer
set search_path = public
as $$
  select re.site,
         re.worker_id,
         re.cause,
         re.recovered_by,
         count(*)::bigint as count
    from public.reauth_events re
    where re.occurred_at >= week_start_arg
      and re.occurred_at < week_start_arg + interval '7 days'
    group by re.site, re.worker_id, re.cause, re.recovered_by
    order by re.site, re.worker_id, re.cause, re.recovered_by;
$$;

revoke execute on function public.save_validated_session_snapshot(text, text, text, timestamptz)
  from public, anon, authenticated;
grant execute on function public.save_validated_session_snapshot(text, text, text, timestamptz)
  to service_role;

revoke execute on function public.latest_validated_session_snapshot(text, text)
  from public, anon, authenticated;
grant execute on function public.latest_validated_session_snapshot(text, text)
  to service_role;

revoke execute on function public.validated_session_snapshots(text, text)
  from public, anon, authenticated;
grant execute on function public.validated_session_snapshots(text, text)
  to service_role;

revoke execute on function public.reauth_weekly_counts(timestamptz)
  from public, anon, authenticated;
grant execute on function public.reauth_weekly_counts(timestamptz)
  to service_role;
