"""Harness Gate 2 — PC-K3 BUG-BOOL-FAILOPEN 봉인. RED 먼저.

boolean 채널(linkedin_rps/public_web)에 유효 keywords가 있는데 boolean_query 가 ''/'   ' 이면
현행은 `if boolean_query:` 로 조용히 통과 → 빈 쿼리 0건 검색. 이걸 KeywordGenerationError 로 fail-closed.
각 단언은 "일부러 깨면 RED, 실제면 GREEN".
"""
from __future__ import annotations

import json

import pytest

from tools.multi_position_sourcing.grouping import group_positions
from tools.multi_position_sourcing.fixtures import SAMPLE_POSITIONS
from tools.multi_position_sourcing.keywords import build_keyword_plan
from tools.multi_position_sourcing.llm_keywords import (
    KeywordGenerationError,
    _require_boolean_query,
    build_llm_keyword_sessions,
    build_llm_queue_items,
    inject_boolean_queries,
    inject_channel_search_filters,
)
from tools.multi_position_sourcing.models import BOOLEAN_CHANNELS

_KW = ["AI 엔지니어", "AI Engineer", "ML Engineer"]
_XRAY = '("AI Engineer" OR "ML Engineer") AND ("PyTorch" OR "TensorFlow")'


def _rep():
    return SAMPLE_POSITIONS[0]


def _sessions():
    group = group_positions(SAMPLE_POSITIONS)[0]
    return build_keyword_plan(group)


def _valid_kw_empty_boolean_llm(prompt: str) -> str:
    """유효 keywords 인데 boolean_query 는 빈 문자열 — boolean 채널이면 0건 검색 위험."""
    return json.dumps({"keywords": _KW, "boolean_query": "", "and": ["PyTorch"], "or": _KW})


def _valid_kw_blank_boolean_llm(prompt: str) -> str:
    """boolean_query 가 공백만 — strip 후 빈 것으로 취급되어야."""
    return json.dumps({"keywords": _KW, "boolean_query": "   ", "and": ["PyTorch"], "or": _KW})


def _valid_boolean_llm(prompt: str) -> str:
    """정상 — boolean_query 채워짐(회귀: raise 없이 주입)."""
    return json.dumps({"keywords": _KW, "boolean_query": _XRAY, "and": ["PyTorch"], "or": _KW})


def test_fixture_has_boolean_channel():
    assert any(s.channel in BOOLEAN_CHANNELS for s in _sessions()), (
        "픽스처에 boolean 채널 세션이 있어야 이 조각이 의미 있다"
    )


def test_inject_channel_filters_raises_on_empty_boolean():
    with pytest.raises(KeywordGenerationError):
        inject_channel_search_filters(_sessions(), _rep(), llm_client=_valid_kw_empty_boolean_llm)


def test_inject_channel_filters_raises_on_blank_boolean():
    with pytest.raises(KeywordGenerationError):
        inject_channel_search_filters(_sessions(), _rep(), llm_client=_valid_kw_blank_boolean_llm)


def test_inject_boolean_queries_raises_on_empty_boolean():
    with pytest.raises(KeywordGenerationError):
        inject_boolean_queries(_sessions(), _rep(), llm_client=_valid_kw_empty_boolean_llm)


def test_valid_boolean_still_injects_no_raise():
    """회귀 — 정상 boolean_query면 raise 없이 boolean 채널 세션에 주입."""
    injected = inject_channel_search_filters(_sessions(), _rep(), llm_client=_valid_boolean_llm)
    bch = [s for s in injected if s.channel in BOOLEAN_CHANNELS]
    assert bch, "boolean 채널 세션이 있어야 한다"
    for s in bch:
        assert s.filters.get("boolean_query") == _XRAY


# ── Codex V1 반영: 제3 경로(build_llm_*) 배선 + 평문 격리 + None 방어 ──────
def test_build_llm_sessions_raises_on_empty_boolean_channel():
    """제3 경로 — boolean 채널만 돌려 빈 boolean_query면 raise(조용한 통과 금지)."""
    with pytest.raises(KeywordGenerationError):
        build_llm_keyword_sessions(_rep(), llm_client=_valid_kw_empty_boolean_llm, channels=("linkedin_rps",))


def test_build_llm_queue_items_raises_on_empty_boolean_channel():
    with pytest.raises(KeywordGenerationError):
        build_llm_queue_items(_rep(), llm_client=_valid_kw_empty_boolean_llm, channels=("linkedin_rps",))


def test_build_llm_sessions_plaintext_channel_no_raise():
    """평문 채널(saramin)은 빈 boolean_query가 정상 — 과잉 raise 금지, boolean_query 키도 없음."""
    sessions = build_llm_keyword_sessions(_rep(), llm_client=_valid_kw_empty_boolean_llm, channels=("saramin",))
    assert sessions, "평문 채널도 세션은 생성돼야(raise 없이)"
    for s in sessions:
        assert "boolean_query" not in s.filters


def test_guard_none_boolean_query_fails_closed_not_crash():
    """비문자열(None) boolean_query 직접 주입 시 AttributeError 아닌 KeywordGenerationError."""
    class _Plan:
        keywords = ("AI Engineer",)
        boolean_query = None

    with pytest.raises(KeywordGenerationError):
        _require_boolean_query("linkedin_rps", _Plan())


def test_guard_plaintext_channel_never_raises():
    """비-boolean 채널은 keywords 있고 boolean_query 비어도 raise 안 함(격리)."""
    class _Plan:
        keywords = ("AI 엔지니어",)
        boolean_query = ""

    assert _require_boolean_query("saramin", _Plan()) == ""
