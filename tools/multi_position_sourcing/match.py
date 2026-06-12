"""저수지 모델 — match() + 재랭킹 (단계 5).

JD를 임베딩해 세그먼트 내에서 top-K 코사인으로 후보를 추리고(벡터 검색), scoring.py(품질 4기준)로
2차 정렬해 "알바용 정렬 줄"(우수 인재 상위)을 만든다. 모든 경계에 관측 로그(line="match")를 남긴다.

결정론(재현성): 같은 JD·같은 저수지면 입력 순서와 무관하게 항상 같은 순서. 동점은 코사인 내림차순,
그다음 canonical_url 오름차순으로 안정 정렬한다. 매칭/점수 로직은 코드로 고정한다(스킬 텍스트 금지).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .embed import Embedder, cosine_similarity, embed_text
from .models import CapturedProfile, Position, PositionMatch, SegmentId, utc_now_iso
from .reservoir_log import append_reservoir_log, make_reservoir_log_record, validate_reservoir_log_record
from .scoring import score_profile_for_position

# 한 후보의 저수지 적재 단위: 세그먼트·임베딩 벡터·캡처 프로필.
Scorer = Callable[[CapturedProfile, Position], PositionMatch]


@dataclass(frozen=True)
class ReservoirEntry:
    canonical_url: str
    segment_id: SegmentId
    vector: tuple[float, ...]
    profile: CapturedProfile


@dataclass(frozen=True)
class MatchCandidate:
    canonical_url: str
    segment_id: str
    cosine: float
    quality_score: int


@dataclass(frozen=True)
class MatchResult:
    candidates: tuple[MatchCandidate, ...]
    log_records: tuple[dict, ...]


def match_jd_to_reservoir(
    jd_text: str,
    position: Position,
    entries: Iterable[ReservoirEntry],
    *,
    segment_id: SegmentId,
    embedder: Embedder = embed_text,
    scorer: Scorer = score_profile_for_position,
    top_k: int = 20,
    run_id: str,
    today: str,
    machine: str = "",
    log_root: object | None = None,
) -> MatchResult:
    """세그먼트 내 top-K 코사인 → scoring 2차 정렬. 결정론 + match 라인 로그.

    1) segment_id 로 필터(다른 세그먼트 제외).
    2) JD 임베딩 vs 각 엔트리 벡터 코사인 → 내림차순(동점은 url) top-K 추출(벡터 검색).
    3) 추린 top-K 를 scoring.py(4기준) quality 로 2차 정렬(우수 인재 상위, 동점은 코사인→url).
    4) 경계 로그 1줄: in=세그먼트 후보수, out=정렬 줄 길이, dropped=top-K 밖.
    """
    in_segment = [entry for entry in entries if entry.segment_id == segment_id]
    jd_vector = embedder(jd_text)

    # 2) 벡터 검색: 코사인 내림차순(동점 url 오름차순) → 결정론 top-K.
    retrieved = sorted(
        ((entry, cosine_similarity(jd_vector, entry.vector)) for entry in in_segment),
        key=lambda pair: (-pair[1], pair[0].canonical_url),
    )[:top_k]

    # 3) scoring 2차 정렬: quality 내림차순 → cosine 내림차순 → url 오름차순(안정·결정론).
    candidates = [
        MatchCandidate(
            canonical_url=entry.canonical_url,
            segment_id=entry.segment_id,
            cosine=cosine,
            quality_score=scorer(entry.profile, position).score,
        )
        for entry, cosine in retrieved
    ]
    candidates.sort(key=lambda c: (-c.quality_score, -c.cosine, c.canonical_url))

    record = make_reservoir_log_record(
        ts=utc_now_iso(),
        run_id=run_id,
        machine=machine,
        segment_id=segment_id,
        site="reservoir",
        line="match",
        in_count=len(in_segment),
        out_count=len(candidates),
        dropped_count=max(0, len(in_segment) - len(candidates)),
        status="ok",
    )
    validate_reservoir_log_record(record)
    if log_root is not None:
        append_reservoir_log(record, root=log_root, today=today)

    return MatchResult(candidates=tuple(candidates), log_records=(record,))
