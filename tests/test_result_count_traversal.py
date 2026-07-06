"""PC-C2 — plan_result_count_traversal 파라미터라이즈 단언.

전수조사 결과수 판단 트리(순수함수, 채널별 밴드)를 docs/sot/22 result_count_decision_tree 에서
채널별로 읽어 SOT22 와 일치하는 결정을 반환하는지 경계에서 못 박는다.

핵심 RED(SOT5): RPS 상한(60)을 사람인/잡코리아에 복사하면 61~80 GOLD 가 top_n 으로 잘려 RED —
채널별 밴드를 각자 읽어야 GREEN.
"""

from __future__ import annotations

import json

import pytest

from tools.multi_position_sourcing import humansearch
from tools.multi_position_sourcing.humansearch import (
    TraversalPlan,
    plan_result_count_traversal,
)


# ── 0~4 즉시 포기 (전 채널 공통 하한) ──────────────────────────────────
@pytest.mark.parametrize("channel", ["saramin", "jobkorea", "linkedin"])
@pytest.mark.parametrize("count", [0, 1, 4])
def test_abort_band(channel: str, count: int) -> None:
    plan = plan_result_count_traversal(channel, count)
    assert plan.action == "abort"
    assert plan.limit is None


# ── GOLD 전수: 사람인/잡코리아 5~80, RPS 5~60 (경계 정확) ───────────────
@pytest.mark.parametrize(
    "channel,count",
    [
        ("saramin", 5), ("saramin", 80),
        ("jobkorea", 5), ("jobkorea", 80),
        ("linkedin", 5), ("linkedin", 60),
    ],
)
def test_full_band_boundaries(channel: str, count: int) -> None:
    plan = plan_result_count_traversal(channel, count)
    assert plan.action == "full"
    assert plan.limit is None


# ── ⭐ SOT5 핵심: 사람인/잡코리아 61~80 은 여전히 전수(RPS 60 상한 복사 금지) ──
@pytest.mark.parametrize("channel", ["saramin", "jobkorea"])
@pytest.mark.parametrize("count", [61, 70, 80])
def test_saramin_jobkorea_61_to_80_still_full_not_rps_cut(channel: str, count: int) -> None:
    plan = plan_result_count_traversal(channel, count)
    assert plan.action == "full", (
        f"{channel} {count}명은 SOT22 상 5~80 전수여야 한다 — RPS 60 상한을 복사하면 잘린다(SOT5 위반)"
    )


# ── 부분 처리(top_n): 사람인/잡코리아 81~300→40, RPS 61~200→20 ─────────
@pytest.mark.parametrize(
    "channel,count,limit",
    [
        ("saramin", 81, 40), ("saramin", 300, 40),
        ("jobkorea", 81, 40), ("jobkorea", 300, 40),
        ("linkedin", 61, 20), ("linkedin", 200, 20),
    ],
)
def test_top_n_band(channel: str, count: int, limit: int) -> None:
    plan = plan_result_count_traversal(channel, count)
    assert plan.action == "top_n"
    assert plan.limit == limit


# ── 조건 추가: 사람인/잡코리아 300+, RPS 200+ ──────────────────────────
@pytest.mark.parametrize(
    "channel,count",
    [("saramin", 301), ("saramin", 5000), ("jobkorea", 301), ("linkedin", 201), ("linkedin", 5000)],
)
def test_add_condition_band(channel: str, count: int) -> None:
    plan = plan_result_count_traversal(channel, count)
    assert plan.action == "add_condition"
    assert plan.limit is None


# ── 경계 인접(off-by-one) 정밀 ─────────────────────────────────────────
def test_boundary_off_by_one_saramin() -> None:
    assert plan_result_count_traversal("saramin", 4).action == "abort"
    assert plan_result_count_traversal("saramin", 5).action == "full"
    assert plan_result_count_traversal("saramin", 80).action == "full"
    assert plan_result_count_traversal("saramin", 81).action == "top_n"
    assert plan_result_count_traversal("saramin", 300).action == "top_n"
    assert plan_result_count_traversal("saramin", 301).action == "add_condition"


def test_boundary_off_by_one_linkedin() -> None:
    assert plan_result_count_traversal("linkedin", 4).action == "abort"
    assert plan_result_count_traversal("linkedin", 5).action == "full"
    assert plan_result_count_traversal("linkedin", 60).action == "full"
    assert plan_result_count_traversal("linkedin", 61).action == "top_n"
    assert plan_result_count_traversal("linkedin", 200).action == "top_n"
    assert plan_result_count_traversal("linkedin", 201).action == "add_condition"


# ── 실패-닫힘(fail-closed) ─────────────────────────────────────────────
def test_unknown_channel_raises() -> None:
    with pytest.raises(ValueError):
        plan_result_count_traversal("indeed", 10)


def test_negative_count_raises() -> None:
    with pytest.raises(ValueError):
        plan_result_count_traversal("saramin", -1)


# ── V1(Codex) 적대검증 회귀: 비-int 은 fail-closed ValueError(TypeError·조용한 통과 금지) ──
@pytest.mark.parametrize("bad", [10.5, 3.0, "10", None, True, False, [10], 5.0])
def test_non_int_result_count_raises_valueerror(bad) -> None:
    """float(10.5 가 10 처럼 조용히 통과)·str/None(TypeError)·bool 모두 ValueError 로 fail-closed."""
    with pytest.raises(ValueError):
        plan_result_count_traversal("saramin", bad)


# ── ⭐ SOT5: 실제로 SOT22 를 읽는가(하드코딩 뮤턴트 생존 차단) ───────────
def test_reads_bands_from_sot22_not_hardcoded(monkeypatch, tmp_path) -> None:
    """SOT22 를 변형해 밴드를 바꾸면 결정도 바뀌어야 한다(하드코딩이면 안 바뀜)."""
    original = json.loads(humansearch._SOT22_PATH.read_text(encoding="utf-8"))
    # saramin 전수 상한을 80→40 으로 조작 → 50명은 이제 top_n 이어야
    original["channels"]["saramin"]["result_count_decision_tree"] = {
        "0_to_4": "즉시 포기",
        "5_to_40": "GOLD 전수 처리",
        "41_to_300": "부분 처리 — 상위 40명",
        "300_plus": "AND 키워드 1개 추가",
    }
    fake = tmp_path / "22.json"
    fake.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(humansearch, "_SOT22_PATH", fake)

    # 조작된 트리 기준: 50명은 41~300 → top_n(40). 하드코딩이면 여전히 full → 이 단언이 잡는다.
    plan = plan_result_count_traversal("saramin", 50)
    assert plan.action == "top_n"
    assert plan.limit == 40


def test_returns_frozen_traversal_plan() -> None:
    plan = plan_result_count_traversal("saramin", 10)
    assert isinstance(plan, TraversalPlan)
    with pytest.raises(Exception):
        plan.action = "x"  # frozen dataclass
