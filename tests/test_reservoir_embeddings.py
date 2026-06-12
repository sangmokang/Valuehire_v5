"""저수지 모델 단계 4 — pgvector 스키마 + 임베딩 적재.

인수 기준(기계 단언):
  - 결정론적 순수파이썬 임베더(numpy 금지) + L2 정규화 + cosine_similarity.
  - ingest_profile_embedding: 저장→임베딩 적재, canonical URL 기준 dedup(2번째는 skip).
  - 모든 적재 경계에 관측 로그(line="index") 1줄(reservoir_log 계약).
  - embeddings.sql: pgvector extension + profile_embeddings + HNSW(vector_cosine_ops), 멱등.
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from tools.multi_position_sourcing.embed import (
    InMemoryEmbeddingStore,
    cosine_similarity,
    embed_text,
    ingest_profile_embedding,
)
from tools.multi_position_sourcing.models import CapturedProfile
from tools.multi_position_sourcing.reservoir_log import validate_reservoir_log_record

REPO_ROOT = Path(__file__).resolve().parents[1]


def _profile(
    url: str = "https://www.saramin.co.kr/profile/x1",
    text: str = "backend spring kotlin java",
) -> CapturedProfile:
    return CapturedProfile(
        profile_url=url,
        source_channel="saramin",
        visible_text=text,
        summary="backend engineer",
        captured_at="2026-06-12T00:00:00+00:00",
        skills=tuple(text.split()),
    )


class EmbedderTests(unittest.TestCase):
    def test_embed_text_deterministic_and_normalized(self) -> None:
        v1 = embed_text("backend spring kotlin")
        v2 = embed_text("backend spring kotlin")
        self.assertEqual(v1, v2)  # 결정론(sha1 기반, hash 시드 무관)
        self.assertEqual(len(v1), len(v2))
        norm = math.sqrt(sum(x * x for x in v1))
        self.assertAlmostEqual(norm, 1.0, places=6)  # L2 정규화

    def test_embed_text_distinguishes_content(self) -> None:
        a = embed_text("backend spring kotlin java platform")
        b = embed_text("marketing growth crm retention funnel")
        self.assertAlmostEqual(cosine_similarity(a, a), 1.0, places=6)
        self.assertLess(cosine_similarity(a, b), 0.5)  # 다른 내용 → 낮은 유사도

    def test_cosine_pure_python_returns_float(self) -> None:
        sim = cosine_similarity((1.0, 0.0), (1.0, 0.0))
        self.assertIsInstance(sim, float)
        self.assertAlmostEqual(sim, 1.0, places=6)
        self.assertAlmostEqual(cosine_similarity((1.0, 0.0), (0.0, 1.0)), 0.0, places=6)


class IngestTests(unittest.TestCase):
    def test_ingest_stores_embedding_and_logs_index(self) -> None:
        store = InMemoryEmbeddingStore()
        result = ingest_profile_embedding(
            _profile(), embedder=embed_text, store=store, run_id="r1", today="2026-06-12"
        )
        self.assertTrue(result.stored)
        self.assertFalse(result.deduped)
        self.assertEqual(store.size(), 1)
        self.assertTrue(result.log_records)
        for rec in result.log_records:
            validate_reservoir_log_record(rec)
            self.assertEqual(rec["line"], "index")

    def test_ingest_dedups_same_canonical_profile(self) -> None:
        store = InMemoryEmbeddingStore()
        first = _profile(url="https://www.saramin.co.kr/profile/x1?trk=abc")
        dup = _profile(url="https://www.saramin.co.kr/profile/x1#frag")  # canonical 동일
        ingest_profile_embedding(first, embedder=embed_text, store=store, run_id="r1", today="2026-06-12")
        result = ingest_profile_embedding(dup, embedder=embed_text, store=store, run_id="r1", today="2026-06-12")
        self.assertTrue(result.deduped)
        self.assertFalse(result.stored)
        self.assertEqual(store.size(), 1)  # 중복 적재 안 함
        for rec in result.log_records:
            validate_reservoir_log_record(rec)


class SqlSchemaContractTests(unittest.TestCase):
    def test_embeddings_sql_exists_with_pgvector_and_hnsw(self) -> None:
        sql_path = REPO_ROOT / "docs" / "ai-search" / "embeddings.sql"
        self.assertTrue(sql_path.exists(), f"missing {sql_path}")
        sql = sql_path.read_text(encoding="utf-8").lower()
        self.assertIn("create extension if not exists vector", sql)
        self.assertIn("profile_embeddings", sql)
        self.assertIn("hnsw", sql)
        self.assertIn("vector_cosine_ops", sql)
        self.assertIn("if not exists", sql)  # 멱등


if __name__ == "__main__":
    unittest.main()
