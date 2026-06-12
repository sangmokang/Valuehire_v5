-- Valuehire 저수지 — 프로필 임베딩(pgvector) 스키마. 단계 4.
-- 멱등(반복 실행 안전): create ... if not exists. 실제 적용은 운영(사람)이 Supabase에 수행한다.
-- 임베딩 차원/모델은 tools/multi_position_sourcing/embed.py 의 EMBEDDING_DIM / EMBEDDING_MODEL 과 일치시킨다.

create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists public.profile_embeddings (
  id uuid primary key default gen_random_uuid(),
  canonical_url text not null unique,            -- dedup 키(canonical_profile_url)
  segment_id text not null default 'unknown',    -- 저수지 세그먼트(단계 1)
  source_channel text not null
    check (source_channel in ('saramin', 'jobkorea', 'linkedin_rps', 'public_web')),
  embedding vector(256) not null,                -- EMBEDDING_DIM 과 일치
  model text not null default 'sha1-hash-256-v1',-- EMBEDDING_MODEL
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 세그먼트 내 top-K 코사인 검색용 HNSW 인덱스(단계 5 match()).
create index if not exists profile_embeddings_hnsw
  on public.profile_embeddings using hnsw (embedding vector_cosine_ops);

-- 세그먼트별 필터링 가속.
create index if not exists profile_embeddings_segment_idx
  on public.profile_embeddings (segment_id);

-- updated_at 자동 갱신(멱등 트리거).
create or replace function public.touch_profile_embeddings_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $$
begin
  create trigger profile_embeddings_set_updated_at
    before update on public.profile_embeddings
    for each row execute function public.touch_profile_embeddings_updated_at();
exception
  when duplicate_object then null;
end;
$$;
