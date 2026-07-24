"""단위2b — 디스코드 /model 명령 dispatch 연결.

goal: docs/engineering/discord-deterministic-routing-login-first-goal-2026-07-24.md
- 인자 없음 → 현재 전역 기본 엔진·모델 조회(action=model)
- engine/model 지정 → 전역 기본 설정(action=model_set), **owner 전용**
저장 경로는 fd._ENGINE_MODEL_PATH (테스트가 monkeypatch 로 격리).
"""

from __future__ import annotations

from tools.multi_position_sourcing import fleet_dispatch as fd
from tools.multi_position_sourcing import engine_model_default as emd
from tools.multi_position_sourcing.fleet_dispatch import (
    dispatch_fleet_command,
    FLEET_COMMANDS,
)
from tools.multi_position_sourcing.discord_routing import (
    DiscordInvocation,
    DiscordAccessConfig,
    DiscordAuthorizedUser,
)

OWNER = "814353841088757800"


class _Q:  # /model 은 큐를 쓰지 않는다
    pass


def _inv(name, options=None, user_id=OWNER):
    return DiscordInvocation(
        user_id=user_id, channel_id="c1", command_name=name,
        is_dm=True, invocation_kind="slash", options=options or {},
    )


_USERS = (DiscordAuthorizedUser(
    name="boss", alias="boss", email="x@x", discord_id=OWNER),)
_CFG = DiscordAccessConfig(allow_dm=True)


def test_model_in_fleet_commands():
    assert "model" in FLEET_COMMANDS


def test_model_query_returns_current_default(monkeypatch, tmp_path):
    monkeypatch.setattr(fd, "_ENGINE_MODEL_PATH", tmp_path / "d.json", raising=False)
    out = dispatch_fleet_command(
        _inv("model"), authorized_users=_USERS, config=_CFG, queue=_Q())
    assert out["action"] == "model"
    assert out["default"]["engine"] in ("codex", "claude")
    assert out["default"]["model"]


def test_model_set_by_owner_persists(monkeypatch, tmp_path):
    p = tmp_path / "d.json"
    monkeypatch.setattr(fd, "_ENGINE_MODEL_PATH", p, raising=False)
    out = dispatch_fleet_command(
        _inv("model", {"engine": "claude", "model": "claude-opus-4-8"}),
        authorized_users=_USERS, config=_CFG, queue=_Q())
    assert out["action"] == "model_set"
    assert emd.get_default(p) == {"engine": "claude", "model": "claude-opus-4-8"}


def test_model_set_invalid_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(fd, "_ENGINE_MODEL_PATH", tmp_path / "d.json", raising=False)
    out = dispatch_fleet_command(
        _inv("model", {"engine": "gpt", "model": "x"}),
        authorized_users=_USERS, config=_CFG, queue=_Q())
    assert out["action"] == "error"
