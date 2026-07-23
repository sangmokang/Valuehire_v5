"""이슈 #188 — login 을 큐 정식 스킬로 편입하고 워커에서 Codex 엔진 강제.

인수 기준: 이 파일이 GREEN.
- (a) skill='login' 잡이 new_job_payload 로 생성된다(position_url 없이 — 로그인은 대상 URL 이 없다).
- (b) 워커 엔진 선택이 login 잡에서는 params.agent 값과 무관하게 Codex 로 강제된다.
      (사장님 지시 2026-07-24: "로그인은 코덱스, 나머지는 claude|codex 선택")
- (c) build_job_prompt 가 SOT26 로그인 계약(자동 로그인 항상, 2FA·캡차만 사람,
      브라우저 보존)을 담고, URL 없는 login 잡을 계약 위반으로 거부하지 않는다.

기존 계약 보호(회귀 방지):
- 검색 스킬(humansearch 등)의 engine 선택(claude 기본 / codex 명시)은 그대로다.
- login 잡은 로그인 영수증 게이트(G4)의 대상이 아니다 — 게이트 대상이면 만료 영수증이
  로그인 잡 자신을 막는 순환이 생긴다.
"""
from __future__ import annotations

import pytest

from tools.multi_position_sourcing import fleet_worker, job_queue


OWNER_ID = "814353841088757800"


def _login_job(agent: str | None = None, **overrides):
    params = {}
    if agent is not None:
        params["agent"] = agent
    job = {
        "id": 7,
        "machine": "macmini",
        "skill": "login",
        "position_url": "",
        "requested_by": OWNER_ID,
        "role": "owner",
        "params": params,
        "status": "running",
    }
    job.update(overrides)
    return job


# ── (a) 큐 편입 ──────────────────────────────────────────────────────────


def test_login_is_fleet_skill():
    assert "login" in job_queue.FLEET_SKILLS


def test_new_job_payload_login_without_url():
    payload = job_queue.new_job_payload(
        machine="macmini", skill="login", position_url="",
        requested_by=OWNER_ID, role="owner",
    )
    assert payload is not None
    assert payload["skill"] == "login"
    assert payload["position_url"] == ""


def test_new_job_payload_login_rejects_garbage_url():
    """fail-closed 유지 — 빈 값 또는 정상 URL 만. 쓰레기 문자열은 여전히 거부."""
    payload = job_queue.new_job_payload(
        machine="macmini", skill="login", position_url="not a url",
        requested_by=OWNER_ID, role="owner",
    )
    assert payload is None


def test_new_job_payload_search_still_requires_url():
    """회귀 방지 — 검색 스킬의 URL 필수 계약은 약화되지 않는다."""
    payload = job_queue.new_job_payload(
        machine="macmini", skill="humansearch", position_url="",
        requested_by=OWNER_ID, role="member",
    )
    assert payload is None


# ── (b) 엔진 선택 — login 은 Codex 강제, 검색은 선택 유지 ────────────────


@pytest.mark.parametrize("agent", [None, "claude", "codex"])
def test_select_engine_login_forces_codex(agent):
    label, runner = fleet_worker.select_job_engine(_login_job(agent=agent))
    assert label == "codex"
    assert runner is fleet_worker._run_codex


def test_select_engine_search_defaults_to_claude():
    job = _login_job(skill="humansearch",
                     position_url="https://app.clickup.com/t/86eufjabc")
    label, runner = fleet_worker.select_job_engine(job)
    assert label == "claude"
    assert runner is fleet_worker._run_claude


def test_select_engine_search_codex_optin_kept():
    job = _login_job(agent="codex", skill="humansearch",
                     position_url="https://app.clickup.com/t/86eufjabc")
    label, runner = fleet_worker.select_job_engine(job)
    assert label == "codex"
    assert runner is fleet_worker._run_codex


# ── (c) 프롬프트 계약 ────────────────────────────────────────────────────


def test_build_job_prompt_login_contract():
    prompt = fleet_worker.build_job_prompt(_login_job(agent="codex"))
    # SOT26 핵심: 자동 로그인은 항상 수행, 사람 개입은 2FA·캡차·checkpoint 뿐.
    assert "login" in prompt
    assert "2FA" in prompt or "캡차" in prompt
    assert "자동" in prompt
    # 브라우저 보존(창·탭·프로필 종료 금지) 문구 필수 — 봇 같은 창 증식 금지.
    assert "브라우저" in prompt
    # 정식 준비 러너(portal_login)를 프롬프트가 안내한다 — 즉석 raw 자동화 금지.
    assert "portal_login" in prompt


def test_build_job_prompt_login_does_not_require_url():
    prompt = fleet_worker.build_job_prompt(_login_job())
    assert isinstance(prompt, str) and prompt.strip()


# ── 회귀 방지 — 게이트·검증 상호작용 ────────────────────────────────────


def test_login_gate_not_applied_to_login_job():
    assert fleet_worker.login_gate_required_channels({"skill": "login"}) == ()


def test_build_job_prompt_search_still_requires_url():
    with pytest.raises(ValueError):
        fleet_worker.build_job_prompt(
            _login_job(skill="humansearch", position_url=""))


# ── 완료 영수증 — login 도 증거 없이 done 이 될 수 없다(R2) ──────────────


def _login_receipt_line(channels=("saramin", "jobkorea", "linkedin_rps"),
                        ready=True):
    import json
    return fleet_worker._LOGIN_RECEIPT_MARKER + json.dumps({
        "channels": {ch: {"ready": ready} for ch in channels},
        "output": "artifacts/portal_session_status_latest.json",
    })


def test_validate_login_receipt_accepts_all_ready():
    receipt = fleet_worker.validate_login_receipt(
        "작업 완료\n" + _login_receipt_line())
    assert set(receipt["channels"]) == {"saramin", "jobkorea", "linkedin_rps"}


def test_validate_login_receipt_missing_marker_fails():
    with pytest.raises(ValueError):
        fleet_worker.validate_login_receipt("로그인 다 했습니다(증거 없음)")


def test_validate_login_receipt_not_ready_channel_fails():
    with pytest.raises(ValueError):
        fleet_worker.validate_login_receipt(
            "완료\n" + _login_receipt_line(ready=False))


def test_validate_login_receipt_missing_channel_fails():
    with pytest.raises(ValueError):
        fleet_worker.validate_login_receipt(
            "완료\n" + _login_receipt_line(channels=("saramin",)))


def test_login_prompt_requires_receipt_marker():
    prompt = fleet_worker.build_job_prompt(_login_job())
    assert fleet_worker._LOGIN_RECEIPT_MARKER in prompt
