-- 가칭/오너 확정 필요(D12·§8-2) — 이 스키마는 초안이며 오너 확정 전 적용 금지.
-- AC-3 (docs/engineering/aisearch-fleet-goal-2026-07-28.md §5 계약):
--   페이지네이션(최대 20페이지, D3) 순회 중 열어본 리스트 화면 + 상세 프로필
--   페이지 전량(D4)을 담는 원본 스냅샷 테이블. apps/aisearch 는 SOT29 함대
--   인프라와 완전 독립(§1) — 기존 fleet_* 테이블과 무관한 신규 테이블이다.

create table if not exists public.aisearch_pages_raw (
  id uuid primary key default gen_random_uuid(),
  channel text not null check (channel in ('saramin', 'jobkorea', 'linkedin_rps')),
  page_type text not null check (page_type in ('list', 'detail')),
  url text not null,
  captured_at timestamptz not null default now(),
  raw_html_or_text text not null,
  position_ref text not null,
  machine text not null
);

comment on table public.aisearch_pages_raw is
  '가칭(오너 확정 필요, D12·§8-2) — AC-3 리스트/상세 페이지 전량 스냅샷(D4)';

create index if not exists aisearch_pages_raw_position_ref_idx
  on public.aisearch_pages_raw (position_ref, captured_at desc);
create index if not exists aisearch_pages_raw_channel_page_type_idx
  on public.aisearch_pages_raw (channel, page_type);
