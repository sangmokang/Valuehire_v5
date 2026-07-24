"""단위2a — 전역 기본 엔진·모델 저장/조회 (디스코드 /model 의 상태 계층).

goal: docs/engineering/discord-deterministic-routing-login-first-goal-2026-07-24.md
사장님 /st: "/model 로 Codex·Claude 및 모델 선택". 적용 범위 = 전역 기본값 1세트
(§0.16 합리적 기본). 이 단위는 그 기본값의 파일 영속 계층만 — 결정적·fail-closed.
"""

from __future__ import annotations

import pytest

from tools.multi_position_sourcing import engine_model_default as emd


def test_missing_file_returns_builtin_default(tmp_path):
    got = emd.get_default(tmp_path / "none.json")
    assert got["engine"] in ("codex", "claude")
    assert isinstance(got["model"], str) and got["model"]


def test_set_then_get_roundtrip(tmp_path):
    p = tmp_path / "d.json"
    emd.set_default(p, engine="claude", model="claude-opus-4-8")
    assert emd.get_default(p) == {"engine": "claude", "model": "claude-opus-4-8"}


def test_invalid_engine_rejected(tmp_path):
    with pytest.raises(emd.EngineModelError):
        emd.set_default(tmp_path / "d.json", engine="gpt", model="x")


def test_invalid_model_rejected(tmp_path):
    with pytest.raises(emd.EngineModelError):
        emd.set_default(tmp_path / "d.json", engine="claude", model="")
