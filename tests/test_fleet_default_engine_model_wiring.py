"""단위3a — 전역 기본 엔진·모델이 실제 job 페이로드에 배선된다.

goal: docs/engineering/discord-deterministic-routing-login-first-goal-2026-07-24.md
/model 로 정한 전역 기본이 "저장만" 되고 끝나면 무의미하다(strict 배선증명).
job enqueue 시 params.agent/model 이 명시되지 않으면 전역 기본을 주입하고,
명시돼 있으면 그 값을 보존한다(그 job 만 예외).
"""

from __future__ import annotations

from tools.multi_position_sourcing import fleet_dispatch as fd
from tools.multi_position_sourcing import engine_model_default as emd
from tools.multi_position_sourcing.fleet_dispatch import build_fleet_job_payload

CU = "https://app.clickup.com/t/86exwz89j"


def test_payload_fills_global_default_when_unset(monkeypatch, tmp_path):
    p = tmp_path / "d.json"
    emd.set_default(p, engine="claude", model="claude-opus-4-8")
    monkeypatch.setattr(fd, "_ENGINE_MODEL_PATH", p, raising=False)
    payload = build_fleet_job_payload(
        {"skill": "humansearch", "url": CU, "machine": "macmini"},
        requested_by="814353841088757800:owner", role="owner")
    assert payload is not None
    assert payload["params"]["agent"] == "claude"
    assert payload["params"]["model"] == "claude-opus-4-8"


def test_payload_no_injection_when_default_unset(monkeypatch, tmp_path):
    # 사장님이 /model 을 설정하지 않았으면(파일 없음) agent/model 을 주입하지 않는다 —
    # 기존 lane별 기본(검색=claude, owner agent=codex)을 보존(회귀 방지).
    monkeypatch.setattr(fd, "_ENGINE_MODEL_PATH", tmp_path / "none.json", raising=False)
    payload = build_fleet_job_payload(
        {"skill": "humansearch", "url": CU, "machine": "macmini"},
        requested_by="814353841088757800:owner", role="owner")
    assert "agent" not in (payload["params"] or {})
    assert "model" not in (payload["params"] or {})


def test_payload_keeps_explicit_agent_and_model(monkeypatch, tmp_path):
    p = tmp_path / "d.json"
    emd.set_default(p, engine="claude", model="claude-opus-4-8")
    monkeypatch.setattr(fd, "_ENGINE_MODEL_PATH", p, raising=False)
    payload = build_fleet_job_payload(
        {"skill": "humansearch", "url": CU, "machine": "macmini",
         "params": {"agent": "codex", "model": "gpt-5.5"}},
        requested_by="814353841088757800:owner", role="owner")
    assert payload["params"]["agent"] == "codex"
    assert payload["params"]["model"] == "gpt-5.5"
