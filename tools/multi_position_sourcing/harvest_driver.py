"""PC-D2b — 상시 Harvest 드라이버(라이브 사이클 경로).

goal: docs/engineering/reservoir-harvest-driver-goal-2026-07-04.md

``run_harvest_cycle``(저수지 심장)과 라이브 실행자 ``HarvestSearchExecutor``(PC-D5)를 잇는
드라이버가 리포에 없었다(고아). 이 모듈이 그 이음매를 채운다:

- ``resolve_repo_dir``: 현재 체크아웃을 모듈 파일 위치에서 파생(env/HOME/Desktop 드리프트 배제,
  자립화 SOT5).
- ``decide_tick``: 이번 tick 을 돌릴지 — ``owner_activity.compute_yield_decision``(PC-F1) 의
  반대를 그대로 쓴다(재구현 금지, 단일출처).
- ``drive_cycle_once``: segments → 큐 → ``arun_harvest_cycle``(async, dry_run 모듈 미호출).
- ``main``: launchd 가 부팅 시 부를 CLI. ``--executor fake|live`` 로 실제 실행자 종류를 출력에
  명시한다(라이브인 척 금지). ``--skip-owner-check`` 없으면 기본은 감지 ON(R4, SOT2).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .harvest_executor import HarvestSearchExecutor
from .harvest_policy import sites_for_machine
from .harvest_runner import HarvestItem, arun_harvest_cycle, build_harvest_queue
from .owner_activity import (
    DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
    compute_yield_decision,
    detect_owner_activity_snapshot,
)


def resolve_repo_dir() -> Path:
    """모듈 파일 위치에서 파생한 현재 체크아웃 루트. env(VALUEHIRE_REPO_DIR)·HOME·Desktop 미참조."""
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TickDecision:
    """이번 tick 에 라이브 사이클을 돌릴지(run) 와 그 사유."""

    run: bool
    reason: str


def decide_tick(
    *,
    frontmost_is_chrome: bool,
    os_idle_seconds: float | None,
    idle_threshold_seconds: float = DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
) -> TickDecision:
    """run == not compute_yield_decision(...) — PC-F1 단일출처, 재구현 금지."""
    should_yield = compute_yield_decision(
        frontmost_is_chrome=frontmost_is_chrome,
        os_idle_seconds=os_idle_seconds,
        idle_threshold_seconds=idle_threshold_seconds,
    )
    if should_yield:
        return TickDecision(run=False, reason="owner activity detected (R4 yield)")
    return TickDecision(run=True, reason="owner idle — resume live cycle")


async def drive_cycle_once(
    *,
    execute_item,
    save_rail,
    segments,
    machine: str,
    run_id: str,
    today: str,
    owner_activity_detected: bool = False,
    log_root: object | None = None,
):
    """한 tick — segments 로 큐를 만들어 ``arun_harvest_cycle`` 을 돈다(dry_run 모듈 미호출)."""
    queue = build_harvest_queue(segments, machines=(machine,), sites=sites_for_machine(machine))
    return await arun_harvest_cycle(
        queue,
        execute_item=execute_item,
        save_rail=save_rail,
        run_id=run_id,
        today=today,
        owner_activity_detected=owner_activity_detected,
        log_root=log_root,
    )


async def _fake_execute_item(item: HarvestItem) -> tuple[object, ...]:
    """CLI ``--executor fake`` 스모크용 — 포털 스택 없이 결정론으로 빈 결과."""
    return ()


def _load_keywords_for_segment(path: str):
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    def keywords_for_segment(segment_id: str) -> tuple[str, ...]:
        return tuple(data.get(segment_id, ()))

    return keywords_for_segment


def _build_live_execute_item(keywords_json: str):
    keywords_for_segment = _load_keywords_for_segment(keywords_json)

    def _runner_for_channel(channel):
        # 라이브 포털 러너 팩토리 배선은 이 조각 범위 밖(PC-F4b/K6). 인자 검증까지만 여기서 완결.
        raise RuntimeError(
            "live portal runner factory 미배선(PC-F4b/K6 몫) — --executor live 는 "
            "인자 검증까지만 이 조각의 범위다."
        )

    return HarvestSearchExecutor(
        runner_for_channel=_runner_for_channel,
        keywords_for_segment=keywords_for_segment,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harvest_driver")
    parser.add_argument("--executor", choices=("fake", "live"), required=True)
    parser.add_argument("--segments", required=True)
    parser.add_argument("--machine", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--today", required=True)
    parser.add_argument("--log-root", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--keywords-json", default=None)
    parser.add_argument("--skip-owner-check", action="store_true")
    args = parser.parse_args(argv)

    segments = tuple(s for s in (seg.strip() for seg in args.segments.split(",")) if s)
    if not segments:
        print(json.dumps({"error": "empty --segments"}), file=sys.stderr)
        return 2

    if args.executor == "live":
        if not args.keywords_json:
            print(
                json.dumps({"error": "--keywords-json required for --executor live"}),
                file=sys.stderr,
            )
            return 2
        execute_item = _build_live_execute_item(args.keywords_json)
    else:
        execute_item = _fake_execute_item

    if args.skip_owner_check:
        owner_activity_detected = False
    else:
        snapshot = detect_owner_activity_snapshot()
        owner_activity_detected = snapshot.owner_activity_detected

    saved: list[Any] = []

    def save_rail(profile: object) -> None:
        saved.append(profile)

    log_root = Path(args.log_root) if args.log_root else None

    summary = asyncio.run(
        drive_cycle_once(
            execute_item=execute_item,
            save_rail=save_rail,
            segments=segments,
            machine=args.machine,
            run_id=args.run_id,
            today=args.today,
            owner_activity_detected=owner_activity_detected,
            log_root=log_root,
        )
    )

    output = {
        "executor": args.executor,
        "run_id": args.run_id,
        "machine": args.machine,
        "segments": list(segments),
        "owner_activity_detected": owner_activity_detected,
        "saved_profiles": summary.saved_profiles,
        "dropped": summary.dropped,
        "searched": [list(pair) for pair in summary.searched],
        "stopped_reasons": list(summary.stopped_reasons),
    }
    text = json.dumps(output, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
