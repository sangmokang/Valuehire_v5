-- Discord message -> fleet job exactly-once enqueue guard.
create unique index if not exists jobs_discord_idempotency_key_uidx
on public.jobs ((params->>'idempotency_key'))
where coalesce(params->>'idempotency_key', '') <> '';
