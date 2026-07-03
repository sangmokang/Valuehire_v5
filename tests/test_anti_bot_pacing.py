"""PC-E1 — 봇방지 페이싱 primitive (harvest_policy, SOT22 단일 출처).

무인 라이브 루프가 봇처럼 굴지 않도록(SOT2 — URL 연타·알람 후 무한재시도 구조적 차단) 페이싱을
결정론 순수함수로 제공한다. delay 상수는 docs/sot/22 에서 읽어 이중정의를 막는다(SOT5).

인수기준:
  - SOT22 delay 상수(random_delay_between_keywords_ms 20000~60000 · short_delay_ms 2000~5000)를
    읽어 채널별 간격 경계 안의 결정론 지터를 반환한다(같은 (kind,step,seed) → 같은 값).
  - 최대단계 캡으로 무한재시도를 막는다(step >= cap 이면 계속 금지).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing.harvest_policy import (
    deterministic_delay_ms,
    max_keyword_steps,
    pacing_bounds_ms,
    should_continue_pacing,
)

_SOT22 = json.loads(
    (Path(__file__).resolve().parents[1] / "docs/sot/22-talent-search-filters.json").read_text(
        encoding="utf-8"
    )
)
_BOT = _SOT22["linkedin"]["bot_protection"]


def test_bounds_read_from_sot22_single_source() -> None:
    # 하드코딩이 아니라 SOT22 값을 그대로 읽어야 한다(이중정의 방지, SOT5).
    kw = _BOT["random_delay_between_keywords_ms"]
    short = _BOT["short_delay_ms"]
    assert pacing_bounds_ms("between_keywords") == (kw["min"], kw["max"])
    assert pacing_bounds_ms("short") == (short["min"], short["max"])
    # 스펙 값 확인(회귀 봉인)
    assert pacing_bounds_ms("between_keywords") == (20000, 60000)
    assert pacing_bounds_ms("short") == (2000, 5000)


def test_delay_within_bounds_for_all_steps() -> None:
    lo, hi = pacing_bounds_ms("between_keywords")
    for step in range(200):
        d = deterministic_delay_ms(kind="between_keywords", step=step, seed=7)
        assert lo <= d <= hi
    slo, shi = pacing_bounds_ms("short")
    for step in range(200):
        d = deterministic_delay_ms(kind="short", step=step, seed=7)
        assert slo <= d <= shi


def test_delay_is_deterministic() -> None:
    a = deterministic_delay_ms(kind="between_keywords", step=3, seed=42)
    b = deterministic_delay_ms(kind="between_keywords", step=3, seed=42)
    assert a == b


def test_delay_has_jitter_across_steps() -> None:
    # 상수(고정값)면 봇 탐지 — step 마다 값이 흩어져야 한다.
    vals = {deterministic_delay_ms(kind="between_keywords", step=s, seed=1) for s in range(30)}
    assert len(vals) >= 10  # 30개 중 최소 10개 이상 서로 다름


def test_seed_changes_sequence() -> None:
    seq1 = [deterministic_delay_ms(kind="short", step=s, seed=1) for s in range(20)]
    seq2 = [deterministic_delay_ms(kind="short", step=s, seed=2) for s in range(20)]
    assert seq1 != seq2


def test_max_keyword_steps_from_sot22() -> None:
    assert max_keyword_steps() == _BOT["keyword_limit_per_run"]
    assert max_keyword_steps() == 3


def test_should_continue_stops_at_cap() -> None:
    cap = max_keyword_steps()
    assert should_continue_pacing(step=0) is True
    assert should_continue_pacing(step=cap - 1) is True
    # step 이 cap 에 도달하면 계속 금지(무한재시도 방지, SOT2)
    assert should_continue_pacing(step=cap) is False
    assert should_continue_pacing(step=cap + 5) is False


def test_should_continue_custom_cap() -> None:
    assert should_continue_pacing(step=4, max_steps=5) is True
    assert should_continue_pacing(step=5, max_steps=5) is False


def test_unknown_kind_rejected() -> None:
    with pytest.raises(Exception):
        pacing_bounds_ms("nonexistent")
