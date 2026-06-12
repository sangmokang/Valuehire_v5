"""저수지 모델 — A/B 측정 하니스 (단계 6).

동일 포지션에 [실시간] vs [저수지] 후보를 나란히 두고, 헤드헌터가 어느 쪽인지 모른 채(블라인드)
적합도를 매긴 뒤 순도(top-N 적합도≥85 비율)를 비교한다. 측정에 집중하는 입력 기반 하니스다 —
후보 산출(실시간 서치 / match())은 호출자가 하고, 여기서는 랭크된 후보 id 리스트 두 개를 받는다.

블라인드 공정성: blind_id 는 arm(realtime/reservoir)을 누설하지 않는다. 순서는 sha1 기반 결정론이라
재현 가능하면서도 arm 과 무관하다. 발송(Send)은 여기서 하지 않는다 — 채점은 사람 게이트.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .models import utc_now_iso
from .reservoir_log import (
    append_reservoir_log,
    make_reservoir_log_record,
    validate_reservoir_log_record,
)

Arm = Literal["realtime", "reservoir"]


@dataclass(frozen=True)
class BlindItem:
    """헤드헌터에게 보이는 블라인드 항목 — blind_id 만 노출한다.

    candidate_id 는 일부러 담지 않는다(arm 흔적이 묻은 id 라면 블라인드가 깨지므로).
    blind_id → (arm, rank, candidate_id) 매핑은 채점 후 언블라인드용으로 ``AbBatch.key`` 에만 둔다.
    """

    blind_id: str


@dataclass(frozen=True)
class AbBatch:
    blind_items: tuple[BlindItem, ...]
    # 언블라인드용(채점 후에만 사용): blind_id -> (arm, rank, candidate_id)
    key: dict[str, tuple[str, int, str]]


@dataclass(frozen=True)
class PurityReport:
    realtime_top20_ge85_ratio: float
    reservoir_top20_ge85_ratio: float
    realtime_n: int
    reservoir_n: int
    threshold: int
    top_n: int
    winner: str
    log_records: tuple[dict, ...]


def _blind_order_key(rank: int, candidate_id: str) -> str:
    # arm 과 무관한 결정론 정렬키(누설 방지).
    return hashlib.sha1(f"{candidate_id}|{rank}".encode("utf-8")).hexdigest()


def build_blind_ab_batch(
    realtime: Sequence[str],
    reservoir: Sequence[str],
) -> AbBatch:
    """[실시간]·[저수지] 랭크 후보(랭크=인덱스)를 합쳐 블라인드 배치로 만든다.

    arm 을 숨긴 blind_id 를 부여하고, sha1 기반 결정론 순서로 정렬한다(arm 누설 없음, 재현 가능).
    """
    entries: list[tuple[str, int, str]] = [
        ("realtime", rank, cid) for rank, cid in enumerate(realtime)
    ] + [("reservoir", rank, cid) for rank, cid in enumerate(reservoir)]
    ordered = sorted(entries, key=lambda e: _blind_order_key(e[1], e[2]))

    blind_items: list[BlindItem] = []
    key: dict[str, tuple[str, int, str]] = {}
    for index, (arm, rank, cid) in enumerate(ordered):
        blind_id = f"blind-{index:04d}"
        blind_items.append(BlindItem(blind_id=blind_id))
        key[blind_id] = (arm, rank, cid)
    return AbBatch(blind_items=tuple(blind_items), key=key)


def score_purity(
    batch: AbBatch,
    blind_scores: Mapping[str, int],
    *,
    threshold: int = 85,
    top_n: int = 20,
    run_id: str = "",
    today: str = "",
    machine: str = "",
    log_root: object | None = None,
) -> PurityReport:
    """블라인드 적합도 채점 → arm별 top-N 적합도≥threshold 비율 + winner. calibrate 라인 로그.

    완료 판정 숫자: 매칭 순도 top-20 중 적합도≥85 비율(기본 threshold=85, top_n=20).
    """
    per_arm: dict[str, list[tuple[int, int]]] = {"realtime": [], "reservoir": []}
    for blind_id, (arm, rank, _cid) in batch.key.items():
        adequacy = blind_scores.get(blind_id)
        if adequacy is None:
            continue
        per_arm[arm].append((rank, int(adequacy)))

    def ratio(arm: str) -> float:
        ranked = [adequacy for _rank, adequacy in sorted(per_arm[arm])[:top_n]]
        if not ranked:
            return 0.0
        return sum(1 for adequacy in ranked if adequacy >= threshold) / len(ranked)

    realtime_ratio = ratio("realtime")
    reservoir_ratio = ratio("reservoir")
    if reservoir_ratio > realtime_ratio:
        winner = "reservoir"
    elif realtime_ratio > reservoir_ratio:
        winner = "realtime"
    else:
        winner = "tie"

    record = make_reservoir_log_record(
        ts=utc_now_iso(),
        run_id=run_id,
        machine=machine,
        segment_id="",
        site="reservoir",
        line="calibrate",
        in_count=len(per_arm["realtime"]) + len(per_arm["reservoir"]),
        out_count=len(per_arm["reservoir"]),
        dropped_count=0,
        status="ok",
    )
    validate_reservoir_log_record(record)
    if log_root is not None:
        append_reservoir_log(record, root=log_root, today=today)

    return PurityReport(
        realtime_top20_ge85_ratio=realtime_ratio,
        reservoir_top20_ge85_ratio=reservoir_ratio,
        realtime_n=len(per_arm["realtime"]),
        reservoir_n=len(per_arm["reservoir"]),
        threshold=threshold,
        top_n=top_n,
        winner=winner,
        log_records=(record,),
    )
