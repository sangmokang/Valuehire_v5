-- APP 02: all new fleet persistence writes use one canonical machine identity.
--
-- NOT VALID deliberately avoids scanning or rewriting historical rows.  It
-- still rejects noncanonical values on new inserts and future row updates.
-- Known legacy aliases remain a read-compatibility concern in application code.

alter table public.fleet_machines
  drop constraint if exists fleet_machines_machine_id_canonical_chk;
alter table public.fleet_machines
  add constraint fleet_machines_machine_id_canonical_chk
  check (machine_id in ('macmini', 'macbook', 'winpc')) not valid;

alter table public.jobs
  drop constraint if exists jobs_machine_canonical_chk;
alter table public.jobs
  add constraint jobs_machine_canonical_chk
  check (machine in ('macmini', 'macbook', 'winpc')) not valid;

alter table public.jobs
  drop constraint if exists jobs_requested_machine_canonical_chk;
alter table public.jobs
  add constraint jobs_requested_machine_canonical_chk
  check (
    requested_machine is null
    or requested_machine in ('macmini', 'macbook', 'winpc')
  ) not valid;

alter table public.jobs
  drop constraint if exists jobs_assigned_machine_canonical_chk;
alter table public.jobs
  add constraint jobs_assigned_machine_canonical_chk
  check (
    assigned_machine is null
    or assigned_machine in ('macmini', 'macbook', 'winpc')
  ) not valid;

alter table public.machine_heartbeats
  drop constraint if exists machine_heartbeats_machine_canonical_chk;
alter table public.machine_heartbeats
  add constraint machine_heartbeats_machine_canonical_chk
  check (machine in ('macmini', 'macbook', 'winpc')) not valid;

alter table public.account_locks
  drop constraint if exists account_locks_holder_machine_canonical_chk;
alter table public.account_locks
  add constraint account_locks_holder_machine_canonical_chk
  check (holder_machine in ('macmini', 'macbook', 'winpc')) not valid;

alter table public.browser_slots
  drop constraint if exists browser_slots_machine_id_canonical_chk;
alter table public.browser_slots
  add constraint browser_slots_machine_id_canonical_chk
  check (machine_id in ('macmini', 'macbook', 'winpc')) not valid;

alter table public.discord_gateway_leases
  drop constraint if exists discord_gateway_leases_target_machine_canonical_chk;
alter table public.discord_gateway_leases
  add constraint discord_gateway_leases_target_machine_canonical_chk
  check (target_machine in ('macmini', 'macbook', 'winpc')) not valid;
