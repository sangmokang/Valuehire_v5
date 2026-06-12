"""저수지 모델 — 연속 Harvest 사이클 (단계 2).

포지션 트리거 없이 ``segment_id``만으로 도는 연속 Harvest 큐를 신설한다(Match 큐와 분리). 발견
프로필은 무조건 저장한다(사람인/잡코리아 상세진입=차감0이므로 발견 즉시 전부 저장 → 저수지 적재).
모든 경계에 구조화 관측 로그 1줄을 남기고, 실패는 조용히 넘기지 않는다(fail-closed).

이 모듈은 브라우저/네트워크 수명주기를 소유하지 않는다 — ``execute_item``(검색)과 ``save_rail``
(아카이버 저장)을 주입받아 순수하게 큐/저장/로그만 다룬다(테스트 가능, 재현성).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from itertools import cycle

from .harvest_policy import HARVEST_SITES, worker_should_yield
from .models import Channel, SegmentId, utc_now_iso
from .reservoir_log import (
    append_reservoir_log,
    make_reservoir_log_record,
    validate_reservoir_log_record,
)


@dataclass(frozen=True)
class HarvestItem:
    """연속 Harvest 큐의 한 일감 = (세그먼트 × 사이트)를 한 머신에 배정. 포지션 없음."""

    segment_id: SegmentId
    channel: Channel
    machine: str
    status: str = "pending"
    attempts: int = 0
    last_error: str = ""


@dataclass(frozen=True)
class HarvestCycleSummary:
    searched: tuple[tuple[str, str], ...]
    saved_profiles: int
    dropped: int
    stopped_reasons: tuple[str, ...]
    log_records: tuple[dict, ...]


# 한 Harvest 아이템을 사이트에서 검색해 발견 프로필(임의 객체)들의 시퀀스를 돌려준다(sync/async 둘 다).
ExecuteHarvestItem = Callable[["HarvestItem"], "Awaitable[Iterable[object]] | Iterable[object]"]
# 발견 프로필 1건을 무조건 저장(아카이버 훅). 점수와 무관.
SaveRail = Callable[[object], None]


def build_harvest_queue(
    segments: Iterable[SegmentId],
    *,
    machines: tuple[str, ...],
    sites: tuple[Channel, ...] = HARVEST_SITES,
) -> tuple[HarvestItem, ...]:
    """세그먼트만으로 (segment × site) 일감을 만들어 활성 머신에 라운드로빈 배정한다(결정론).

    포지션이 전혀 관여하지 않는다 — Harvest 큐는 segment_id 구동이다(Match 큐와 분리). 활성 머신에
    라운드로빈으로 돌려 부하를 분산한다(같은 입력 → 항상 같은 배정).
    """
    segment_tuple = tuple(segments)
    if not machines:
        return ()
    rotor = cycle(machines)
    items: list[HarvestItem] = []
    for segment_id in segment_tuple:
        for site in sites:
            items.append(HarvestItem(segment_id=segment_id, channel=site, machine=next(rotor)))
    return tuple(items)


def _resolve(value: object) -> object:
    """execute_item 이 코루틴을 돌려주면 완료까지 돌려 결과를 반환(sync 호출 경로 지원)."""
    if asyncio.iscoroutine(value):
        return asyncio.run(value)
    return value


def run_harvest_cycle(
    queue: Iterable[HarvestItem],
    *,
    execute_item: ExecuteHarvestItem,
    save_rail: SaveRail,
    run_id: str,
    today: str,
    owner_activity_detected: bool = False,
    log_root: object | None = None,
) -> HarvestCycleSummary:
    """한 Harvest 사이클. 발견 프로필을 무조건 저장하고 경계마다 관측 로그를 남긴다.

    - R4: ``owner_activity_detected`` 면 검색하지 않고 ``skip`` 로그(무인 워커 양보).
    - 정상: 발견 N건 → ``save_rail`` N회(무조건 저장) → harvest 라인 ``ok`` 로그(in=out=N, dropped=0).
    - 실패: ``execute_item`` 예외 → fail-closed. ``fail`` 로그(fail_reason 필수), 저장하지 않는다.

    ``log_root`` 가 주어지면 ``append_reservoir_log`` 로 디스크에도 남긴다(테스트는 메모리 레코드 검증).
    """
    ts = utc_now_iso()
    searched: list[tuple[str, str]] = []
    saved_profiles = 0
    dropped = 0
    stopped: list[str] = []
    records: list[dict] = []

    for item in queue:
        base = dict(
            ts=ts,
            run_id=run_id,
            machine=item.machine,
            segment_id=item.segment_id,
            site=item.channel,
            line="harvest",
        )

        if worker_should_yield(owner_activity_detected=owner_activity_detected):
            reason = "owner activity detected (R4 yield)"
            records.append(
                make_reservoir_log_record(
                    **base, in_count=0, out_count=0, dropped_count=0,
                    status="skip", fail_reason=reason,
                )
            )
            if reason not in stopped:
                stopped.append(reason)
            continue

        try:
            found = tuple(_resolve(execute_item(item)))
        except Exception as exc:  # fail-closed: 조용히 넘기지 않는다.
            reason = f"{type(exc).__name__}: harvest search failed"
            records.append(
                make_reservoir_log_record(
                    **base, in_count=0, out_count=0, dropped_count=0,
                    status="fail", fail_reason=reason,
                )
            )
            continue

        # 발견 프로필을 무조건 저장(차감0). save_rail(아카이버 쓰기)이 터져도 fail-closed —
        # 예외를 새지 않고 빠진 건수+이유를 로그로 남긴다(조용한 실패 금지).
        saved_here = 0
        save_error = ""
        for profile in found:
            try:
                save_rail(profile)
            except Exception as exc:
                save_error = f"{type(exc).__name__}: archiver save failed"
                break
            saved_here += 1

        saved_profiles += saved_here
        if save_error:
            dropped_here = len(found) - saved_here
            dropped += dropped_here
            records.append(
                make_reservoir_log_record(
                    **base, in_count=len(found), out_count=saved_here,
                    dropped_count=dropped_here, status="fail", fail_reason=save_error,
                )
            )
            continue

        searched.append((item.segment_id, item.channel))
        records.append(
            make_reservoir_log_record(
                **base, in_count=len(found), out_count=len(found),
                dropped_count=0, status="ok",
            )
        )

    for record in records:
        validate_reservoir_log_record(record)
        if log_root is not None:
            append_reservoir_log(record, root=log_root, today=today)

    return HarvestCycleSummary(
        searched=tuple(searched),
        saved_profiles=saved_profiles,
        dropped=dropped,
        stopped_reasons=tuple(stopped),
        log_records=tuple(records),
    )
