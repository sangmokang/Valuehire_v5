"""저수지 모델 — 프로필 임베딩 적재 (단계 4).

아카이버 저장 직후 프로필을 임베딩(숫자 벡터)으로 바꿔 pgvector(profile_embeddings)에 적재한다.
canonical URL 기준으로 중복을 dedup하고, 모든 적재 경계에 관측 로그(line="index")를 남긴다.

CI에는 numpy가 없으므로 임베더/cosine은 순수 파이썬이다. sha1 기반 해시 임베더라 PYTHONHASHSEED와
무관하게 결정론적이다(재현성). 실제 운영 임베더(예: OpenAI/Supabase)는 동일 시그니처로 주입 교체한다.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from .dedup import canonical_profile_url
from .models import CapturedProfile, utc_now_iso
from .reservoir_log import (
    append_reservoir_log,
    make_reservoir_log_record,
    validate_reservoir_log_record,
)

EMBEDDING_DIM = 256
EMBEDDING_MODEL = "sha1-hash-256-v1"

Embedder = Callable[[str], "tuple[float, ...]"]

_TOKEN_RE = re.compile(r"[a-z0-9가-힣]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def embed_text(text: str, *, dim: int = EMBEDDING_DIM) -> tuple[float, ...]:
    """결정론적 순수파이썬 해시 임베더 + L2 정규화. sha1 기반이라 hash 시드와 무관."""
    vec = [0.0] * dim
    for token in _tokenize(text):
        digest = int(hashlib.sha1(token.encode("utf-8")).hexdigest(), 16)
        idx = digest % dim
        sign = 1.0 if (digest >> 8) & 1 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(value * value for value in vec))
    if norm == 0.0:
        return tuple(vec)
    return tuple(value / norm for value in vec)


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    """순수파이썬 코사인 유사도(numpy 없이). 영벡터는 0.0."""
    av = list(a)
    bv = list(b)
    dot = sum(x * y for x, y in zip(av, bv))
    na = math.sqrt(sum(x * x for x in av))
    nb = math.sqrt(sum(y * y for y in bv))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def profile_embedding_text(profile: CapturedProfile) -> str:
    """임베딩에 넣을 텍스트(가시 텍스트 + OCR + 요약 + 스킬 + 산업)."""
    return " ".join(
        [
            profile.visible_text,
            profile.ocr_text,
            profile.summary,
            " ".join(profile.skills),
            " ".join(profile.industries),
        ]
    )


@dataclass
class InMemoryEmbeddingStore:
    """테스트/드라이런용 임베딩 store. 운영은 Supabase pgvector(profile_embeddings)로 교체."""

    _by_url: dict[str, tuple[float, ...]] = field(default_factory=dict)

    def has(self, canonical_url: str) -> bool:
        return canonical_url in self._by_url

    def add(self, canonical_url: str, vector: tuple[float, ...]) -> None:
        self._by_url[canonical_url] = vector

    def get(self, canonical_url: str) -> tuple[float, ...] | None:
        return self._by_url.get(canonical_url)

    def items(self) -> tuple[tuple[str, tuple[float, ...]], ...]:
        return tuple(self._by_url.items())

    def size(self) -> int:
        return len(self._by_url)


@dataclass(frozen=True)
class IngestResult:
    stored: bool
    deduped: bool
    canonical_url: str
    log_records: tuple[dict, ...]


def _flush(records: list[dict], log_root: object | None, today: str) -> None:
    for record in records:
        validate_reservoir_log_record(record)
        if log_root is not None:
            append_reservoir_log(record, root=log_root, today=today)


def ingest_profile_embedding(
    profile: CapturedProfile,
    *,
    embedder: Embedder = embed_text,
    store: InMemoryEmbeddingStore,
    run_id: str,
    today: str,
    machine: str = "",
    segment_id: str = "",
    log_root: object | None = None,
) -> IngestResult:
    """프로필 1건을 임베딩해 store에 적재(저장 직후 훅). canonical URL dedup. index 라인 로그.

    - 이미 적재된 canonical → skip(중복), in=1,out=0,dropped=0,status=skip.
    - 신규 → 임베딩 적재, in=out=1, status=ok.
    - embedder 예외 → fail-closed, dropped=1, fail_reason, status=fail(조용한 실패 금지).
    """
    canonical = canonical_profile_url(profile.profile_url)
    base = dict(
        ts=utc_now_iso(),
        run_id=run_id,
        machine=machine,
        segment_id=segment_id,
        site=profile.source_channel,
        line="index",
    )
    records: list[dict] = []

    if store.has(canonical):
        records.append(
            make_reservoir_log_record(
                **base, in_count=1, out_count=0, dropped_count=0,
                status="skip", fail_reason="duplicate canonical url (dedup)",
            )
        )
        result = IngestResult(stored=False, deduped=True, canonical_url=canonical, log_records=tuple(records))
        _flush(records, log_root, today)
        return result

    try:
        vector = embedder(profile_embedding_text(profile))
    except Exception as exc:  # fail-closed.
        records.append(
            make_reservoir_log_record(
                **base, in_count=1, out_count=0, dropped_count=1,
                status="fail", fail_reason=f"{type(exc).__name__}: embedding failed",
            )
        )
        result = IngestResult(stored=False, deduped=False, canonical_url=canonical, log_records=tuple(records))
        _flush(records, log_root, today)
        return result

    store.add(canonical, vector)
    records.append(
        make_reservoir_log_record(
            **base, in_count=1, out_count=1, dropped_count=0, status="ok",
        )
    )
    result = IngestResult(stored=True, deduped=False, canonical_url=canonical, log_records=tuple(records))
    _flush(records, log_root, today)
    return result
