"""Harness Gate 2 — PC-K4 BUG-HARVEST-ASYNC 봉인. RED 먼저.

`_resolve` 가 실행중 이벤트루프에서 `asyncio.run(코루틴)` 을 호출해 RuntimeError 로 크래시한다.
live Harvest 드라이버(async)가 run_harvest_cycle 을 돌리면 사이클 통째 죽음. 스레드-새루프로 봉인.
각 단언은 "일부러 깨면 RED, 실제면 GREEN".
"""
from __future__ import annotations

import asyncio

from tools.multi_position_sourcing.harvest_runner import (
    _resolve,
    build_harvest_queue,
    run_harvest_cycle,
)


async def _coro(value):
    return value


def test_resolve_passthrough_non_coroutine():
    assert _resolve(("x", "y")) == ("x", "y")


def test_resolve_sync_context_runs_coroutine():
    assert _resolve(_coro(("a", "b"))) == ("a", "b")


def test_resolve_within_running_loop_no_crash():
    """실행중 이벤트루프 안에서 코루틴 resolve — RuntimeError 없이 결과 반환."""

    async def driver():
        return _resolve(_coro(("p1", "p2")))

    assert asyncio.run(driver()) == ("p1", "p2")


def test_run_harvest_cycle_from_running_loop():
    """live 드라이버가 async 컨텍스트라도 run_harvest_cycle(async execute_item) 크래시 없이 저장."""
    queue = build_harvest_queue(("it_ai_data",), machines=("macbook",))

    async def execute_item(item):
        return ("prof-a", "prof-b")

    saved: list[str] = []

    def save_rail(profile: str) -> None:
        saved.append(profile)

    async def driver():
        return run_harvest_cycle(
            queue,
            execute_item=execute_item,
            save_rail=save_rail,
            run_id="run-loop",
            today="2026-07-03",
        )

    summary = asyncio.run(driver())
    assert summary.saved_profiles >= 1
    assert summary.dropped == 0
    assert saved


def test_run_harvest_cycle_from_loop_fail_closed_on_coro_exception():
    """실행중 루프에서 execute_item 코루틴이 예외를 raise 하면 크래시 아닌 fail-closed(저장 0)."""
    queue = build_harvest_queue(("it_ai_data",), machines=("macbook",))

    async def execute_item(item):
        raise RuntimeError("search failed")

    def save_rail(profile: str) -> None:  # pragma: no cover - 실패 시 호출되면 안 됨
        raise AssertionError("실패 아이템은 저장하면 안 된다")

    async def driver():
        return run_harvest_cycle(
            queue,
            execute_item=execute_item,
            save_rail=save_rail,
            run_id="run-loop-fail",
            today="2026-07-03",
        )

    summary = asyncio.run(driver())
    assert summary.saved_profiles == 0
    fails = [rec for rec in summary.log_records if rec.get("status") == "fail"]
    assert fails and all(rec.get("fail_reason") for rec in fails)
