-- ⛔ 오너 확정 전 적용 금지 — 이 파일은 초안(draft)이며 supabase/migrations/ 에
--    두지 않는다(자동 적용 위험). 테이블 오너가 확정되면 그때 migrations 로
--    승격한다. 가칭/오너 확정 필요(D12·§8-2).
-- AC-3 (docs/engineering/aisearch-fleet-goal-2026-07-28.md §5 계약):
--   페이지네이션(최대 20페이지, D3) 순회 중 열어본 리스트 화면 + 상세 프로필
--   페이지 전량(D4)을 담는 원본 스냅샷 테이블. apps/aisearch 는 SOT29 함대
--   인프라와 완전 독립(§1) — 기존 fleet_* 테이블과 무관한 신규 테이블이다.
--
-- 멱등성: id 는 앱이 uuid5(namespace, channel\n page_type\n url\n position_ref) 로
-- 결정론적 생성(apps/aisearch/core/pagination_store.py make_row_id). 재실행/재시도가
-- 같은 페이지를 다시 저장해도 같은 id 로 upsert 되어 중복 행이 생기지 않는다.
-- (channel, page_type, url, position_ref) unique 제약이 DB 단에서 이를 이중으로
-- 보증한다. 2026-07-31 전수 리뷰 AC-3b(= V1 독립검증 결함10, 같은 지적):
-- 예전 제약은 position_ref 가 빠져 있어 코드 멱등키와 어긋났다. 같은 프로필을
-- 서로 다른 포지션 검색에서 만나면 앱은 두 행으로 의도하는데, DB 제약은 두 번째
-- 삽입을 (channel,page_type,url) 중복으로 오판해 거부한다 — 앱의 식별키와
-- 반드시 일치해야 한다.

create table if not exists public.aisearch_pages_raw (
  id uuid primary key,  -- 앱 생성 결정론적 uuid5 멱등키 (default 없음 — 임의 UUID 금지)
  channel text not null check (channel in ('saramin', 'jobkorea', 'linkedin_rps')),
  page_type text not null check (page_type in ('list', 'detail')),
  url text not null,
  captured_at timestamptz not null default now(),
  raw_html_or_text text not null,
  position_ref text not null,
  machine text not null,
  constraint aisearch_pages_raw_idem_key unique (channel, page_type, url, position_ref)
);

comment on table public.aisearch_pages_raw is
  '가칭(오너 확정 필요, D12·§8-2) — AC-3 리스트/상세 페이지 전량 스냅샷(D4), 멱등키 upsert';

create index if not exists aisearch_pages_raw_position_ref_idx
  on public.aisearch_pages_raw (position_ref, captured_at desc);
create index if not exists aisearch_pages_raw_channel_page_type_idx
  on public.aisearch_pages_raw (channel, page_type);

-- upsert 예시(참고): insert ... on conflict (id) do update set
--   captured_at = excluded.captured_at, raw_html_or_text = excluded.raw_html_or_text;
