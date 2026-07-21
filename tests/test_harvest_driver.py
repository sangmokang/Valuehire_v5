"""PC-D2b — 상시 Harvest 드라이버(라이브 사이클 경로) 인수 기준.

goal: docs/engineering/reservoir-harvest-driver-goal-2026-07-04.md

인수 기준(기계 단언):
  1. 주입 페이크 실행자 호출횟수/인자로 라이브 사이클 경로 단언(로그 문구 아님).
  2. R4: owner_activity_detected=True → 실행자 호출 0회.
  3. async 실행자를 실행중 이벤트루프 안에서 직접 await 성공(sync 경로가 못 하는 케이스).
  4. resolve_repo_dir() == 현재 체크아웃(env/Desktop 드리프트 무시).
  5. decide_tick 이 compute_yield_decision 과 전 그리드 일치.
  6. CLI: fake 스모크 exit 0 + JSON(executor 종류 명시) / 빈 segments·live 무키워드 exit 2.
"""

from __future__ import annotations

import asyncio
import json
from itertools import product
from pathlib import Path

import pytest

from tools.multi_position_sourcing import harvest_driver
from tools.multi_position_sourcing.harvest_driver import (
    TickDecision,
    decide_tick,
    drive_cycle_once,
    main,
    resolve_repo_dir,
)
from tools.multi_position_sourcing.harvest_runner import HarvestItem
from tools.multi_position_sourcing.owner_activity import compute_yield_decision


# ----------------------------------------------------------------------------
# 4. resolve_repo_dir — 현재 체크아웃, env/Desktop 드리프트 무시
# ----------------------------------------------------------------------------
def test_resolve_repo_dir_is_current_checkout(monkeypatch, tmp_path) -> None:
    drifted = tmp_path / "some-drifted-desktop-path"
    monkeypatch.setenv("VALUEHIRE_REPO_DIR", str(drifted))
    root = resolve_repo_dir()
    expected = Path(harvest_driver.__file__).resolve().parents[2]
    assert root == expected
    assert (root / "tools" / "multi_position_sourcing").is_dir()
    # env 드리프트 무시: 체크아웃이 어디 있든(로컬 Desktop 포함) env 경로를 따라가면 안 된다
    assert root != drifted.resolve()


# ----------------------------------------------------------------------------
# 5. decide_tick == not compute_yield_decision (단일출처)
# ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "frontmost_is_chrome,os_idle_seconds",
    list(product([True, False], [None, 0.0, 30.0, 59.9, 60.0, 500.0])),
)
def test_decide_tick_matches_compute_yield_decision_grid(
    frontmost_is_chrome, os_idle_seconds
) -> None:
    decision = decide_tick(
        frontmost_is_chrome=frontmost_is_chrome, os_idle_seconds=os_idle_seconds
    )
    assert isinstance(decision, TickDecision)
    should_yield = compute_yield_decision(
        frontmost_is_chrome=frontmost_is_chrome, os_idle_seconds=os_idle_seconds
    )
    assert decision.run == (not should_yield)
    assert decision.reason


# ----------------------------------------------------------------------------
# 1/2/3. drive_cycle_once — 라이브 사이클 경로(페이크 실행자 호출횟수/인자로 단언)
# ----------------------------------------------------------------------------
SEGMENTS = ("it_ai_data", "marketing_growth")


def test_drive_cycle_once_calls_fake_executor_exactly_per_segment_x_site() -> None:
    calls: list[HarvestItem] = []

    async def execute_item(item: HarvestItem):
        calls.append(item)
        return ()

    summary = asyncio.run(
        drive_cycle_once(
            execute_item=execute_item,
            save_rail=lambda p: None,
            segments=SEGMENTS,
            machine="macmini",
            run_id="drv-1",
            today="2026-07-04",
        )
    )
    # 2 세그먼트 × 2 사이트(사람인·잡코리아) = 정확히 4회.
    assert len(calls) == 4
    seen = {(c.segment_id, c.channel) for c in calls}
    assert seen == {
        ("it_ai_data", "saramin"),
        ("it_ai_data", "jobkorea"),
        ("marketing_growth", "saramin"),
        ("marketing_growth", "jobkorea"),
    }
    assert all(isinstance(c, HarvestItem) for c in calls)
    assert summary.dropped == 0


def test_drive_cycle_once_r4_yield_calls_executor_zero_times() -> None:
    calls: list[HarvestItem] = []

    async def execute_item(item: HarvestItem):
        calls.append(item)
        return ("should-not-be-collected",)

    summary = asyncio.run(
        drive_cycle_once(
            execute_item=execute_item,
            save_rail=lambda p: None,
            segments=SEGMENTS,
            machine="macmini",
            run_id="drv-2",
            today="2026-07-04",
            owner_activity_detected=True,
        )
    )
    assert len(calls) == 0
    assert summary.saved_profiles == 0
    assert all(r["status"] == "skip" for r in summary.log_records)


def test_drive_cycle_once_awaits_async_executor_within_running_event_loop() -> None:
    """sync run_harvest_cycle 은 실행중 루프에서 async execute_item 을 fail-closed 거부한다
    (BUG-HARVEST-ASYNC, test_harvest_resolve_loop.py). drive_cycle_once 는 그 케이스에서 성공해야."""

    calls = {"n": 0}

    async def execute_item(item: HarvestItem):
        calls["n"] += 1
        return ("p1",)

    saved: list[object] = []

    async def outer():
        # 이미 실행중인 이벤트루프 안에서 드라이버를 돈다.
        return await drive_cycle_once(
            execute_item=execute_item,
            save_rail=saved.append,
            segments=("it_ai_data",),
            machine="macmini",
            run_id="drv-3",
            today="2026-07-04",
        )

    summary = asyncio.run(outer())
    assert calls["n"] == 2  # it_ai_data × (saramin, jobkorea)
    assert summary.saved_profiles == 2
    assert saved == ["p1", "p1"]


# ----------------------------------------------------------------------------
# 6. CLI main() — fake 스모크 exit 0 / 빈 segments·live 무키워드 exit 2
# ----------------------------------------------------------------------------
def test_main_fake_smoke_exit_zero_and_json_names_executor(tmp_path, capsys) -> None:
    output_path = tmp_path / "out.json"
    log_root = tmp_path / "logs"
    rc = main(
        [
            "--executor", "fake",
            "--segments", "it_ai_data,marketing_growth",
            "--machine", "macmini",
            "--run-id", "cli-1",
            "--today", "2026-07-04",
            "--log-root", str(log_root),
            "--output", str(output_path),
            "--skip-owner-check",
        ]
    )
    assert rc == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    # 라이브인 척 금지 — 실제 실행자 종류를 명시.
    assert payload["executor"] == "fake"
    assert payload["run_id"] == "cli-1"
    jsonl_files = list(log_root.glob("logs/reservoir/*.jsonl")) or list(
        (log_root / "logs" / "reservoir").glob("*.jsonl")
    )
    assert jsonl_files, "fake 스모크도 reservoir 로그를 남겨야 한다"


def test_main_empty_segments_exit_two(capsys) -> None:
    rc = main(
        [
            "--executor", "fake",
            "--segments", "",
            "--machine", "macmini",
            "--run-id", "cli-2",
            "--today", "2026-07-04",
            "--skip-owner-check",
        ]
    )
    assert rc == 2


def test_main_live_without_keywords_json_exit_two() -> None:
    rc = main(
        [
            "--executor", "live",
            "--segments", "it_ai_data",
            "--machine", "macmini",
            "--run-id", "cli-3",
            "--today", "2026-07-04",
            "--skip-owner-check",
        ]
    )
    assert rc == 2


def test_main_default_owner_check_on_yields_when_detected(monkeypatch) -> None:
    """--skip-owner-check 없으면 기본은 감지 ON(R4) — SOT2 위반(기본 OFF) 사고 방지."""

    class _Snapshot:
        owner_activity_detected = True

    monkeypatch.setattr(
        harvest_driver, "detect_owner_activity_snapshot", lambda: _Snapshot()
    )

    calls: list[HarvestItem] = []

    async def execute_item(item: HarvestItem):
        calls.append(item)
        return ()

    monkeypatch.setattr(harvest_driver, "_fake_execute_item", execute_item)

    rc = main(
        [
            "--executor", "fake",
            "--segments", "it_ai_data",
            "--machine", "macmini",
            "--run-id", "cli-4",
            "--today", "2026-07-04",
        ]
    )
    assert rc == 0
    assert len(calls) == 0  # 사장님 크롬 점유 감지 → 실행자 호출 0회(R4)
