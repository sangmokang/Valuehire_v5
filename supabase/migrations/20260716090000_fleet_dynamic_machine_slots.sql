-- Issue #126: dynamic fleet machine/slot storage, additive over the legacy queue.
-- Legacy rows and RPC signatures are preserved; claim/lease execution stays in later issues.

create table if not exists public.fleet_machines (
  machine_id text primary key,
  enabled boolean not null,
  os text not null,
  reliability_rank integer not null,
  draining boolean not null default false,
  worker_version text not null,
  heartbeat_generation bigint not null,
  last_seen_at timestamptz not null,
  labels jsonb not null default '{}',
  constraint fleet_machines_id_chk
    check (machine_id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
  constraint fleet_machines_os_chk
    check (os = btrim(os) and os <> '' and os !~ '[[:space:]]'),
  constraint fleet_machines_rank_chk check (reliability_rank >= 0),
  constraint fleet_machines_worker_chk
    check (worker_version = btrim(worker_version) and worker_version <> ''
           and worker_version !~ '[[:space:]]'),
  constraint fleet_machines_generation_chk check (heartbeat_generation >= 0),
  constraint fleet_machines_labels_chk check (jsonb_typeof(labels) = 'object')
);

-- Register the three historical machines plus every machine already referenced by
-- jobs, heartbeats, or a live legacy account lock before adding foreign keys.
insert into public.fleet_machines (
  machine_id, enabled, os, reliability_rank, draining, worker_version,
  heartbeat_generation, last_seen_at, labels
)
select machine_id, true,
       case machine_id
         when 'macmini' then 'macos'
         when 'macbook' then 'macos'
         when 'winpc' then 'windows'
         else 'unknown'
       end,
       case machine_id when 'macmini' then 10 when 'macbook' then 20
                       when 'winpc' then 30 else 100 end,
       false, 'legacy', 0, max(seen_at), '{}'::jsonb
from (
  select known.machine_id, '1970-01-01 00:00:00+00'::timestamptz as seen_at
    from (values ('macmini'), ('macbook'), ('winpc')) known(machine_id)
  union all
  select machine, beat_at from public.machine_heartbeats
  union all
  select machine, created_at from public.jobs
  union all
  select holder_machine, acquired_at from public.account_locks
) observed
where machine_id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'
group by machine_id
on conflict (machine_id) do nothing;

alter table public.jobs add column if not exists requester_platform text;
alter table public.jobs add column if not exists requester_user_id text;
alter table public.jobs add column if not exists request_channel_id text;
alter table public.jobs add column if not exists request_message_id text;
alter table public.jobs add column if not exists resource_class text;
alter table public.jobs add column if not exists requested_machine text;
alter table public.jobs add column if not exists assigned_machine text;
alter table public.jobs add column if not exists assigned_slot_id text;
alter table public.jobs add column if not exists lease_id uuid;
alter table public.jobs add column if not exists dispatch_seq bigint;
alter table public.jobs add column if not exists not_before timestamptz;
alter table public.jobs add column if not exists attempt integer not null default 0;
alter table public.jobs add column if not exists max_attempts integer not null default 3;
alter table public.jobs add column if not exists requirements jsonb not null default '{}';
alter table public.jobs add column if not exists scheduler_version text;

alter table public.jobs drop constraint if exists jobs_attempt_chk;
alter table public.jobs add constraint jobs_attempt_chk
  check (attempt >= 0 and max_attempts > 0 and attempt <= max_attempts);
alter table public.jobs drop constraint if exists jobs_requirements_object_chk;
alter table public.jobs add constraint jobs_requirements_object_chk
  check (jsonb_typeof(requirements) = 'object');

-- Remove only the legacy three-machine lists; old migrations remain immutable.
alter table public.jobs drop constraint if exists jobs_machine_check;
alter table public.machine_heartbeats
  drop constraint if exists machine_heartbeats_machine_check;
alter table public.jobs drop constraint if exists jobs_machine_fkey;
alter table public.jobs drop constraint if exists jobs_requested_machine_fkey;
alter table public.jobs drop constraint if exists jobs_assigned_machine_fkey;

alter table public.machine_heartbeats
  drop constraint if exists machine_heartbeats_machine_fkey;
alter table public.account_locks
  drop constraint if exists account_locks_holder_machine_fkey;

alter table public.jobs add constraint jobs_machine_fkey
  foreign key (machine) references public.fleet_machines(machine_id);
alter table public.jobs add constraint jobs_requested_machine_fkey
  foreign key (requested_machine) references public.fleet_machines(machine_id);
alter table public.jobs add constraint jobs_assigned_machine_fkey
  foreign key (assigned_machine) references public.fleet_machines(machine_id);

alter table public.machine_heartbeats add constraint machine_heartbeats_machine_fkey
  foreign key (machine) references public.fleet_machines(machine_id);
alter table public.account_locks add constraint account_locks_holder_machine_fkey
  foreign key (holder_machine) references public.fleet_machines(machine_id);

create table if not exists public.browser_slots (
  slot_id text primary key,
  machine_id text not null references public.fleet_machines(machine_id),
  resource_class text not null,
  portal text not null,
  profile_key text not null,
  logical_target_key text not null,
  current_cdp_target_id text,
  account_key text not null,
  state text not null,
  generation bigint not null,
  observed_at timestamptz not null,
  login_verified_at timestamptz,
  login_proof_kind text,
  capabilities jsonb not null default '{}',
  constraint browser_slots_id_chk
    check (slot_id ~ '^[a-z0-9][a-z0-9:_.-]{0,127}$'),
  constraint browser_slots_resource_chk
    check (resource_class = btrim(resource_class) and resource_class <> ''
           and resource_class !~ '[[:space:]]'),
  constraint browser_slots_portal_chk
    check (portal = btrim(portal) and portal <> '' and portal !~ '[[:space:]]'),
  constraint browser_slots_profile_chk
    check (profile_key = btrim(profile_key) and profile_key <> ''
           and profile_key !~ '[[:space:]]'),
  constraint browser_slots_logical_chk
    check (logical_target_key = btrim(logical_target_key) and logical_target_key <> ''
           and logical_target_key !~ '[[:space:]]'),
  constraint browser_slots_account_chk
    check (account_key = btrim(account_key) and account_key <> ''
           and account_key !~ '[[:space:]]'),
  constraint browser_slots_state_chk check (
    state in ('ready','busy','parked','human_active','challenge','degraded','offline','draining')
  ),
  constraint browser_slots_generation_chk check (generation >= 0),
  constraint browser_slots_capabilities_chk check (jsonb_typeof(capabilities) = 'object'),
  unique (machine_id, logical_target_key)
);

create table if not exists public.slot_leases (
  lease_id uuid primary key,
  slot_id text not null references public.browser_slots(slot_id),
  job_id bigint not null references public.jobs(id),
  worker_id text not null,
  fencing_token bigint not null,
  acquired_at timestamptz not null,
  renewed_at timestamptz not null,
  expires_at timestamptz not null,
  released_at timestamptz,
  release_reason text,
  constraint slot_leases_worker_chk
    check (worker_id = btrim(worker_id) and worker_id <> ''
           and worker_id !~ '[[:space:]]'),
  constraint slot_leases_fencing_chk check (fencing_token > 0),
  constraint slot_leases_expiry_chk check (expires_at > acquired_at),
  constraint slot_leases_renewed_chk check (renewed_at >= acquired_at),
  constraint slot_leases_release_chk
    check (released_at is null or released_at >= acquired_at)
);

create unique index if not exists slot_leases_one_active_slot_idx
  on public.slot_leases(slot_id) where released_at is null;
create unique index if not exists slot_leases_one_active_job_idx
  on public.slot_leases(job_id) where released_at is null;

create table if not exists public.account_permits (
  account_key text not null,
  permit_no integer not null,
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  primary key (account_key, permit_no),
  constraint account_permits_key_chk
    check (account_key = btrim(account_key) and account_key <> ''
           and account_key !~ '[[:space:]]'),
  constraint account_permits_number_chk check (permit_no > 0),
  constraint account_permits_linkedin_one_chk
    check (account_key <> 'portal:linkedin_rps' or permit_no = 1)
);

insert into public.account_permits(account_key, permit_no)
values ('portal:linkedin_rps', 1)
on conflict (account_key, permit_no) do nothing;

alter table public.jobs drop constraint if exists jobs_assigned_slot_id_fkey;
alter table public.jobs drop constraint if exists jobs_lease_id_fkey;
alter table public.jobs add constraint jobs_assigned_slot_id_fkey
  foreign key (assigned_slot_id) references public.browser_slots(slot_id);
alter table public.jobs add constraint jobs_lease_id_fkey
  foreign key (lease_id) references public.slot_leases(lease_id);


alter table public.fleet_machines enable row level security;
alter table public.browser_slots enable row level security;
alter table public.slot_leases enable row level security;
alter table public.account_permits enable row level security;

revoke all on public.fleet_machines from public, anon, authenticated;
revoke all on public.browser_slots from public, anon, authenticated;
revoke all on public.slot_leases from public, anon, authenticated;
revoke all on public.account_permits from public, anon, authenticated;
grant select, insert, update on public.fleet_machines to service_role;
grant select, insert, update, delete on public.browser_slots to service_role;
grant select, insert, update, delete on public.slot_leases to service_role;
grant select, insert, update, delete on public.account_permits to service_role;

drop policy if exists service_role_fleet_machines_all on public.fleet_machines;
create policy service_role_fleet_machines_all on public.fleet_machines
  for all to service_role using (true) with check (true);
drop policy if exists service_role_browser_slots_all on public.browser_slots;
create policy service_role_browser_slots_all on public.browser_slots
  for all to service_role using (true) with check (true);
drop policy if exists service_role_slot_leases_all on public.slot_leases;
create policy service_role_slot_leases_all on public.slot_leases
  for all to service_role using (true) with check (true);
drop policy if exists service_role_account_permits_all on public.account_permits;
create policy service_role_account_permits_all on public.account_permits
  for all to service_role using (true) with check (true);

-- Keep both heartbeat signatures and replace only their fixed tuple validation.
create or replace function public.record_heartbeat(p_machine text, p_worker_pid integer)
returns setof public.machine_heartbeats
language plpgsql security definer set search_path = public
as $$
begin
  if not exists (
    select 1 from public.fleet_machines where machine_id = p_machine
  ) then
    raise exception 'unknown machine: %', p_machine;
  end if;
  insert into public.machine_heartbeats(machine, beat_at, worker_pid, linkedin_rps_logged_in)
  values (p_machine, now(), coalesce(p_worker_pid, 0), false)
  on conflict (machine) do update
    set beat_at = now(), worker_pid = coalesce(p_worker_pid, 0),
        linkedin_rps_logged_in = false;
  update public.fleet_machines
    set last_seen_at = now(), heartbeat_generation = heartbeat_generation + 1
    where machine_id = p_machine;
  return query select * from public.machine_heartbeats where machine = p_machine;
end;
$$;

create or replace function public.record_heartbeat(
  p_machine text, p_worker_pid integer, p_linkedin_rps_logged_in boolean
)
returns setof public.machine_heartbeats
language plpgsql security definer set search_path = public
as $$
begin
  if not exists (
    select 1 from public.fleet_machines where machine_id = p_machine
  ) then
    raise exception 'unknown machine: %', p_machine;
  end if;
  insert into public.machine_heartbeats(machine, beat_at, worker_pid, linkedin_rps_logged_in)
  values (p_machine, now(), coalesce(p_worker_pid, 0),
          coalesce(p_linkedin_rps_logged_in, false))
  on conflict (machine) do update
    set beat_at = now(), worker_pid = coalesce(p_worker_pid, 0),
        linkedin_rps_logged_in = coalesce(p_linkedin_rps_logged_in, false);
  update public.fleet_machines
    set last_seen_at = now(), heartbeat_generation = heartbeat_generation + 1
    where machine_id = p_machine;
  return query select * from public.machine_heartbeats where machine = p_machine;
end;
$$;

-- Preserve the latest account-pause barrier and existing claim order/locking.
create or replace function public.claim_next_job(p_machine text)
returns setof public.jobs
language plpgsql security definer set search_path = public
as $$
declare
  j public.jobs%rowtype;
  last_id bigint := 0;
  locked boolean;
begin
  if not exists (
    select 1 from public.fleet_machines where machine_id = p_machine
  ) then
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
          select 1 from public.account_locks al where al.account_key = q.account_key
        )
        and not exists (
          select 1 from public.jobs paused
          where paused.status = 'paused_for_human'
            and btrim(paused.account_key) <> ''
            and paused.account_key = q.account_key
        )
      order by q.id
      limit 1
      for update of q skip locked;
    if not found then return; end if;
    last_id := j.id;
    begin
      insert into public.account_locks(account_key, holder_machine, job_id)
      values (j.account_key, p_machine, j.id);
      locked := true;
    exception when unique_violation then
      locked := false;
    end;
    if locked then
      update public.jobs set status = 'running', started_at = now() where id = j.id;
      return query select * from public.jobs where id = j.id;
      return;
    end if;
  end loop;
end;
$$;

revoke all on function public.record_heartbeat(text, integer) from public, anon, authenticated;
revoke all on function public.record_heartbeat(text, integer, boolean) from public, anon, authenticated;
revoke all on function public.claim_next_job(text) from public, anon, authenticated;
grant execute on function public.record_heartbeat(text, integer) to service_role;
grant execute on function public.record_heartbeat(text, integer, boolean) to service_role;
grant execute on function public.claim_next_job(text) to service_role;
