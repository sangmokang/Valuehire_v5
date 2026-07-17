-- Owner-approved Discord natural-language jobs. Search/member admission remains unchanged.

alter table public.jobs drop constraint if exists jobs_skill_check;
alter table public.jobs add constraint jobs_skill_check
  check (skill in ('humansearch', 'aisearch', 'url', 'agent'));

alter table public.jobs drop constraint if exists jobs_owner_agent_contract_chk;
alter table public.jobs add constraint jobs_owner_agent_contract_chk
  check (
    skill <> 'agent'
    or ((
      role = 'owner'
      and jsonb_typeof(params) = 'object'
      and params ?& array[
        'request_text', 'agent', 'approval_id', 'prompt_sha256', 'approval_sha256',
        'idempotency_key', 'execution_mode'
      ]
      and params - array[
        'request_text', 'agent', 'approval_id', 'prompt_sha256', 'approval_sha256',
        'idempotency_key', 'execution_mode'
      ]::text[] = '{}'::jsonb
      and jsonb_typeof(params->'request_text') = 'string'
      and jsonb_typeof(params->'agent') = 'string'
      and jsonb_typeof(params->'approval_id') = 'string'
      and jsonb_typeof(params->'prompt_sha256') = 'string'
      and jsonb_typeof(params->'approval_sha256') = 'string'
      and jsonb_typeof(params->'idempotency_key') = 'string'
      and jsonb_typeof(params->'execution_mode') = 'string'
      and char_length(params->>'request_text') between 1 and 8000
      and params->>'request_text' ~ '[^[:space:]]'
      and params->>'agent' in ('claude', 'codex')
      and params->>'approval_id' ~ '^discord:[0-9]{15,22}$'
      and params->>'idempotency_key' = params->>'approval_id'
      and params->>'prompt_sha256' ~ '^[0-9a-f]{64}$'
      and params->>'prompt_sha256' = encode(
        sha256(convert_to(params->>'request_text', 'UTF8')), 'hex'
      )
      and params->>'execution_mode' in ('read_only', 'workspace_write')
      and params->>'approval_sha256' = encode(sha256(convert_to(
        octet_length(convert_to(params->>'request_text', 'UTF8'))::text || ':' ||
        (params->>'request_text') ||
        octet_length(convert_to(params->>'agent', 'UTF8'))::text || ':' ||
        (params->>'agent') ||
        octet_length(convert_to(params->>'execution_mode', 'UTF8'))::text || ':' ||
        (params->>'execution_mode') ||
        octet_length(convert_to(params->>'approval_id', 'UTF8'))::text || ':' ||
        (params->>'approval_id'), 'UTF8'
      )), 'hex')
      and position_url ~ '^https://discord[.]com/channels/(@me|[0-9]{15,22})/[0-9]{15,22}/[0-9]{15,22}$'
      and params->>'approval_id' = 'discord:' || substring(
        position_url from '/([0-9]{15,22})$'
      )
      and btrim(account_key) <> ''
      and account_key !~ '[[:space:]]'
    ) is true)
  );

create unique index if not exists jobs_discord_idempotency_key_uidx
  on public.jobs ((params->>'idempotency_key'))
  where coalesce(params->>'idempotency_key', '') <> '';
