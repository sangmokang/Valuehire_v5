"""Harness Gate 2 — PC-K4 BUG-HARVEST-ASYNC 봉인.

현행 `_resolve` 는 실행중 이벤트루프에서 `asyncio.run(코루틴)` 을 호출해
`RuntimeError: asyncio.run() cannot be called from a running event loop` 로 크래시 + 코루틴 미await 경고.
→ 실행중 루프에서는 임의 코루틴을 sync 로 안전하게 해결할 수 없으므로(스레드+새루프는 outer-loop
의존 코루틴에서 deadlock/cross-loop 에러, adversarial V1), 코루틴을 닫고 명시적 예외로 fail-closed 한다
(run_harvest_cycle 이 잡아 status=fail 로그, 저장0). sync 경로(루프 없음)는 asyncio.run 으로 정상 완주.
각 단언은 "일부러 깨면 RED, 실제면 GREEN".
"""
from __future__ import annotations

import asyncio
import warnings

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
    """루프 없는 sync 컨텍스트 — asyncio.run 으로 코루틴 완주(회귀)."""
    assert _resolve(_coro(("a", "b"))) == ("a", "b")


def test_resolve_within_running_loop_fails_closed_cleanly():
    """실행중 이벤트루프에서 코루틴 resolve — asyncio 내부 크래시가 아니라 명확한 도메인 예외로
    fail-closed 하고, 코루틴 미await RuntimeWarning 을 남기지 않는다."""

    async def driver():
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)  # 미await 경고 나면 테스트 실패
            try:
                _resolve(_coro(("p",)))
            except RuntimeError as exc:
                return str(exc)
            return "NO_RAISE"

    msg = asyncio.run(driver())
    assert "async 드라이버" in msg  # 도메인 메시지(asyncio 'cannot be called' 아님)
    assert "cannot be called" not in msg


def test_run_harvest_cycle_from_running_loop_fails_closed():
    """live async 드라이버가 async execute_item 으로 sync run_harvest_cycle 호출 시 크래시/행 없이
    fail-closed — 저장0, status=fail(fail_reason). (async 지원은 별도 async 드라이버의 몫.)"""
    queue = build_harvest_queue(("it_ai_data",), machines=("macbook",))

    async def execute_item(item):
        return ("prof-a", "prof-b")

    def save_rail(profile: str) -> None:  # pragma: no cover - fail-closed 시 호출되면 안 됨
        raise AssertionError("fail-closed 시 저장하면 안 된다")

    async def driver():
        return run_harvest_cycle(
            queue,
            execute_item=execute_item,
            save_rail=save_rail,
            run_id="run-loop",
            today="2026-07-03",
        )

    summary = asyncio.run(driver())
    assert summary.saved_profiles == 0
    fails = [rec for rec in summary.log_records if rec.get("status") == "fail"]
    assert fails and all(rec.get("fail_reason") for rec in fails)
