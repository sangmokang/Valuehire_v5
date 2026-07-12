create table if not exists public.organization_analysis (
  position_id text primary key,
  company_name text not null,
  role_title text not null,
  company_size text not null default '',
  industry_segment text not null default '',
  investment_stage text not null default '',
  organization_analysis text not null default '',
  talent_density_notes text not null default '',
  org_fit_target text not null default 'neutral_target',
  updated_at timestamptz not null default now()
);

create index if not exists organization_analysis_company_idx
  on public.organization_analysis (company_name);

alter table public.organization_analysis enable row level security;

revoke all on public.organization_analysis from public, anon, authenticated;
grant select, insert, update on public.organization_analysis to service_role;

drop policy if exists service_role_organization_analysis_all on public.organization_analysis;
create policy service_role_organization_analysis_all
  on public.organization_analysis
  for all
  to service_role
  using (true)
  with check (true);
