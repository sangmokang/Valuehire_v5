"""PC-F4a — 자동재개 데몬 순수 결정함수 ``decide_resume`` (goal: docs/engineering/pc-f4a-autoresume-daemon-decision-goal-2026-07-07.md).

여러 tick 에 걸친 yield→(대기)→resume 전이를, 재개 순간 anti-bot 간격(PC-E1)까지 합성해
순수함수로 못박는다. 재개여부 판단은 PC-F1(decide_tick) 단일출처 — 재구현이면 결함.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from tools.multi_position_sourcing.harvest_driver import (
    ResumeDecision,
    decide_resume,
    decide_tick,
    drive_cycle_once,
)
from tools.multi_position_sourcing.harvest_policy import (
    deterministic_delay_ms,
    pacing_bounds_ms,
)
from tools.multi_position_sourcing.harvest_runner import HarvestItem

SEGMENTS = ("it_ai_data", "marketing_growth")


# ----------------------------------------------------------------------------
# 1. idle→재개: 손 뗀 뒤에는 재개하되, 0ms 즉시 두드리지 않는다(SOT2 봇 금지)
# ----------------------------------------------------------------------------
def test_idle_resumes_with_antibot_delay() -> None:
    decision = decide_resume(
        frontmost_is_chrome=False,
        os_idle_seconds=300.0,
        ticks_yielded=3,
        seed=42,
    )
    assert isinstance(decision, ResumeDecision)
    assert decision.resume is True
    lo, hi = pacing_bounds_ms("short")
    assert lo <= decision.delay_ms <= hi
    assert decision.delay_ms > 0
    assert "resume" in decision.reason


# ----------------------------------------------------------------------------
# 2. 크롬 점유/판단불가 → 양보 (PC-F1 fail-closed 상속)
# ----------------------------------------------------------------------------
def test_chrome_foreground_yields_only_while_recent_or_unknown() -> None:
    # INV9(2026-07-20 60초 개정): 크롬 앞창이어도 idle>=60 이면 재개 —
    # "앞창=영구 양보"는 1분 자동 재개를 방해하는 스펙이라 폐기(포털 축 + idle 신호).
    for idle in (None, 0.0, 10.0):
        decision = decide_resume(
            frontmost_is_chrome=True,
            os_idle_seconds=idle,
            ticks_yielded=1,
            seed=1,
        )
        assert decision.resume is False
        assert decision.delay_ms == 0
    resumed = decide_resume(
        frontmost_is_chrome=True, os_idle_seconds=10_000.0, ticks_yielded=1, seed=1)
    assert resumed.resume is True


def test_unknown_idle_fails_closed_to_yield() -> None:
    decision = decide_resume(
        frontmost_is_chrome=False,
        os_idle_seconds=None,
        ticks_yielded=5,
        seed=7,
    )
    assert decision.resume is False
    assert decision.delay_ms == 0


# ----------------------------------------------------------------------------
# 3. 간격은 PC-E1 단일출처 — 하드코딩 뮤턴트 사살(SOT22 바꿔치기 연동)
# ----------------------------------------------------------------------------
def test_delay_equals_pc_e1_deterministic_delay_exactly() -> None:
    for ticks, seed in ((0, 11), (1, 11), (7, 99), (30, 5)):
        decision = decide_resume(
            frontmost_is_chrome=False,
            os_idle_seconds=999.0,
            ticks_yielded=ticks,
            seed=seed,
        )
        assert decision.delay_ms == deterministic_delay_ms(kind="short", step=ticks, seed=seed)


def test_delay_follows_sot22_file_not_hardcoded(tmp_path, monkeypatch) -> None:
    from tools.multi_position_sourcing import harvest_policy as hp

    fake = tmp_path / "22.json"
    fake.write_text(
        json.dumps(
            {
                "channels": {
                    "linkedin": {
                        "bot_protection": {
                            "random_delay_between_keywords_ms": {"min": 111, "max": 222},
                            "short_delay_ms": {"min": 33, "max": 44},
                            "keyword_limit_per_run": 9,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(hp, "_SOT22_PATH", fake)
    hp._bot_protection.cache_clear()
    try:
        for ticks in range(10):
            decision = decide_resume(
                frontmost_is_chrome=False,
                os_idle_seconds=999.0,
                ticks_yielded=ticks,
                seed=3,
            )
            assert 33 <= decision.delay_ms <= 44
    finally:
        hp._bot_protection.cache_clear()


def test_delay_jitter_actually_uses_ticks_yielded_as_step() -> None:
    """고정 간격 = 봇 신호. step(ticks_yielded)이 지터에 실제 반영되는지 — 전부 같은 값이면 결함."""
    delays = {
        decide_resume(
            frontmost_is_chrome=False,
            os_idle_seconds=999.0,
            ticks_yielded=t,
            seed=1234,
        ).delay_ms
        for t in range(20)
    }
    assert len(delays) > 1


# ----------------------------------------------------------------------------
# 4. 재개여부는 decide_tick(PC-F1) 단일출처 — 전 그리드 드리프트 0
# ----------------------------------------------------------------------------
def test_resume_matches_decide_tick_over_full_grid() -> None:
    for chrome in (True, False):
        for idle in (None, 0.0, 30.0, 59.9, 60.0, 200.0):
            decision = decide_resume(
                frontmost_is_chrome=chrome,
                os_idle_seconds=idle,
                ticks_yielded=2,
                seed=8,
            )
            tick = decide_tick(frontmost_is_chrome=chrome, os_idle_seconds=idle)
            assert decision.resume == tick.run, (chrome, idle)
            # 방향 자체도 고정(두 래퍼가 같은 오답을 내는 대칭 오배선 봉인, V1 6차 LOW):
            expected_run = idle is not None and idle >= 60.0
            assert decision.resume == expected_run, (chrome, idle)
            if not decision.resume:
                assert decision.delay_ms == 0


def test_custom_idle_threshold_is_forwarded_to_decide_tick() -> None:
    """V1 생존 뮤턴트(M1: idle_threshold_seconds 미전달) 사살 — 소비자(F4b)가 임계를
    조정하면 그 값으로 판단해야 한다. idle 50 은 임계 30 기준 재개, 임계 60 기준 양보."""
    d_lo = decide_resume(
        frontmost_is_chrome=False, os_idle_seconds=50.0, ticks_yielded=1, seed=1,
        idle_threshold_seconds=30.0,
    )
    assert d_lo.resume is True
    assert d_lo.delay_ms > 0
    d_hi = decide_resume(
        frontmost_is_chrome=False, os_idle_seconds=50.0, ticks_yielded=1, seed=1,
        idle_threshold_seconds=60.0,
    )
    assert d_hi.resume is False
    assert d_hi.delay_ms == 0
    # 단일출처 대조 — decide_tick 에 같은 임계를 줬을 때와 일치
    assert d_lo.resume == decide_tick(
        frontmost_is_chrome=False, os_idle_seconds=50.0, idle_threshold_seconds=30.0
    ).run


def test_custom_pacing_kind_is_forwarded_to_pc_e1() -> None:
    """V2 생존 뮤턴트(SURV-2: pacing_kind 하드코딩) 사살 — between_keywords 대역
    (SOT22 20~60초)은 short(2~5초)와 겹치지 않아 하드코딩이면 경계 단언이 깨진다."""
    decision = decide_resume(
        frontmost_is_chrome=False, os_idle_seconds=999.0, ticks_yielded=2, seed=9,
        pacing_kind="between_keywords",
    )
    assert decision.delay_ms == deterministic_delay_ms(kind="between_keywords", step=2, seed=9)
    lo, hi = pacing_bounds_ms("between_keywords")
    assert lo <= decision.delay_ms <= hi
    short_lo, short_hi = pacing_bounds_ms("short")
    assert not (short_lo <= decision.delay_ms <= short_hi)


# ----------------------------------------------------------------------------
# 5. 페이크 실행자 호출횟수 경계 — 양보 K tick 0회 → 재개 1 tick 정확히 seg×site 회
# ----------------------------------------------------------------------------
def test_multitick_yield_then_resume_executor_call_boundary() -> None:
    calls: list[HarvestItem] = []

    async def execute_item(item: HarvestItem):
        calls.append(item)
        return ()

    # 신호 시퀀스: 크롬 점유 3 tick(양보) → 손 떼고 idle 3 tick 째(재개) → 이후는 데몬 다음 주기.
    signals = [
        {"frontmost_is_chrome": True, "os_idle_seconds": 5.0},
        {"frontmost_is_chrome": True, "os_idle_seconds": 1.0},
        {"frontmost_is_chrome": True, "os_idle_seconds": 0.0},
        {"frontmost_is_chrome": False, "os_idle_seconds": 600.0},
    ]

    async def run_ticks() -> int:
        ticks_yielded = 0
        cycles_run = 0
        for signal in signals:
            decision = decide_resume(ticks_yielded=ticks_yielded, seed=77, **signal)
            if not decision.resume:
                ticks_yielded += 1
                assert len(calls) == 0  # 양보 구간 동안 실행자 호출 정확히 0회
                continue
            await drive_cycle_once(
                execute_item=execute_item,
                save_rail=lambda p: None,
                segments=SEGMENTS,
                machine="macmini",
                run_id="f4a-boundary",
                today="2026-07-07",
            )
            cycles_run += 1
            ticks_yielded = 0
        return cycles_run

    cycles = asyncio.run(run_ticks())
    assert cycles == 1
    # 재개 경계에서 중복실행 0 — 양보했던 사이클을 처음부터 다시 돌리지 않는다(2seg×2site=정확히 4회).
    assert len(calls) == 4
    assert {(c.segment_id, c.channel) for c in calls} == {
        ("it_ai_data", "saramin"),
        ("it_ai_data", "jobkorea"),
        ("marketing_growth", "saramin"),
        ("marketing_growth", "jobkorea"),
    }


# ----------------------------------------------------------------------------
# 6. 결정론 — 같은 입력 → 같은 결정, PYTHONHASHSEED 무관(3프로세스)
# ----------------------------------------------------------------------------
def test_same_inputs_same_decision() -> None:
    kwargs = dict(frontmost_is_chrome=False, os_idle_seconds=500.0, ticks_yielded=4, seed=2026)
    assert decide_resume(**kwargs) == decide_resume(**kwargs)


def test_delay_reproducible_across_hashseed_processes() -> None:
    code = (
        "from tools.multi_position_sourcing.harvest_driver import decide_resume;"
        "print(decide_resume(frontmost_is_chrome=False, os_idle_seconds=500.0,"
        " ticks_yielded=4, seed=2026).delay_ms)"
    )
    repo_root = str(Path(__file__).resolve().parents[1])
    outs = set()
    for hashseed in ("0", "1", "2"):
        env = dict(os.environ, PYTHONHASHSEED=hashseed, PYTHONPATH=repo_root)
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
        )
        outs.add(result.stdout.strip())
    assert len(outs) == 1
