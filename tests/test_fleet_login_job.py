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
    """fail-closed 유지 — login 은 빈 값만. 쓰레기 문자열은 여전히 거부."""
    payload = job_queue.new_job_payload(
        machine="macmini", skill="login", position_url="not a url",
        requested_by=OWNER_ID, role="owner",
    )
    assert payload is None


def test_new_job_payload_login_rejects_any_url():
    """Codex V2 2R-1 — login 은 무대상 스킬: 정상 URL 이라도 거부(빈 값만 허용)."""
    payload = job_queue.new_job_payload(
        machine="macmini", skill="login",
        position_url="https://app.clickup.com/t/86eufjabc",
        requested_by=OWNER_ID, role="owner",
    )
    assert payload is None


def test_build_job_prompt_login_rejects_any_url():
    with pytest.raises(ValueError):
        fleet_worker.build_job_prompt(
            _login_job(position_url="https://app.clickup.com/t/86eufjabc"))


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
# Codex V2 반증 수용: (1) 마커는 마지막 비공백 줄만, (2) 채널은 정확히 3개,
# (3) output 경로 고정, (4) 실제 영수증 파일과 교차 대조.

_NOW = 1_784_800_000


def _login_receipt_line(channels=("saramin", "jobkorea", "linkedin_rps"),
                        ready=True,
                        output="artifacts/portal_session_status_latest.json"):
    import json
    return fleet_worker._LOGIN_RECEIPT_MARKER + json.dumps({
        "channels": {ch: {"ready": ready} for ch in channels},
        "output": output,
    })


def _file_receipt(now=_NOW, ready=True,
                  channels=("saramin", "jobkorea", "linkedin_rps")):
    from datetime import datetime, timezone
    return {
        "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "portal_sessions": [{"channel": ch, "ready": ready} for ch in channels],
    }


_STARTED = _NOW - 600  # 잡 시작 시각(기본: 10분 전 시작, 영수증은 그 뒤 갱신)


def _validate(stdout, file_payload=None, now=_NOW, started=_STARTED):
    return fleet_worker.validate_login_receipt(
        stdout,
        started_epoch=started,
        file_payload=_file_receipt() if file_payload is None else file_payload,
        now_epoch=now)


def test_validate_login_receipt_accepts_all_ready():
    receipt = _validate("작업 완료\n" + _login_receipt_line())
    assert set(receipt["channels"]) == {"saramin", "jobkorea", "linkedin_rps"}


def test_validate_login_receipt_missing_marker_fails():
    with pytest.raises(ValueError):
        _validate("로그인 다 했습니다(증거 없음)")


def test_validate_login_receipt_marker_mid_output_fails():
    """Codex V2 — 마커 뒤에 다른 출력이 붙으면(중간 삽입 위조) 거부."""
    with pytest.raises(ValueError):
        _validate(_login_receipt_line() + "\n그리고 추가 로그")


def test_validate_login_receipt_not_ready_channel_fails():
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(ready=False))


def test_validate_login_receipt_missing_channel_fails():
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(channels=("saramin",)))


def test_validate_login_receipt_extra_channel_fails():
    """Codex V2 — 임의 채널 추가로 부풀린 영수증 거부(정확히 3개)."""
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(
            channels=("saramin", "jobkorea", "linkedin_rps", "fakeportal")))


def test_validate_login_receipt_wrong_output_path_fails():
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(output="/tmp/elsewhere.json"))


def test_validate_login_receipt_file_cross_check_not_ready_fails():
    """stdout 이 ready 라고 우겨도 실제 영수증 파일이 not-ready 면 거부."""
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(),
                  file_payload=_file_receipt(ready=False))


def test_validate_login_receipt_file_cross_check_stale_fails():
    stale = _file_receipt(now=_NOW - fleet_worker.LOGIN_RECEIPT_MAX_AGE_SECONDS - 10)
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(), file_payload=stale)


def test_validate_login_receipt_file_missing_fails():
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(), file_payload={})


def test_validate_login_receipt_file_older_than_job_start_fails():
    """Codex V2 2R-2 — 24시간 내라도 잡 시작 *이전* 영수증은 미갱신 = 거부."""
    before_start = _file_receipt(now=_STARTED - 60)
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(), file_payload=before_start)


def test_validate_login_receipt_same_second_but_earlier_fails():
    """Codex V2 4R — 같은 초 안이라도 시작 직전(소수점) 영수증은 거부."""
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(),
                  file_payload=_file_receipt(now=_STARTED + 0.2),
                  started=_STARTED + 0.5)


def test_validate_login_receipt_duplicate_stdout_keys_fails():
    """Codex V2 2R-3 — JSON 중복 키(뒤값 승리 트릭) 거부."""
    line = (fleet_worker._LOGIN_RECEIPT_MARKER
            + '{"channels": {"saramin": {"ready": false}, "saramin": {"ready": true}, '
              '"jobkorea": {"ready": true}, "linkedin_rps": {"ready": true}}, '
              '"output": "artifacts/portal_session_status_latest.json"}')
    with pytest.raises(ValueError):
        _validate("완료\n" + line)


def test_validate_login_receipt_duplicate_file_entries_fails():
    """파일에 같은 채널이 두 번(모순 가능) 있으면 거부."""
    payload = _file_receipt()
    payload["portal_sessions"].append({"channel": "saramin", "ready": False})
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(), file_payload=payload)


def test_validate_login_receipt_extra_file_channel_fails():
    payload = _file_receipt(
        channels=("saramin", "jobkorea", "linkedin_rps", "fakeportal"))
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(), file_payload=payload)


def test_validate_login_receipt_malformed_file_entry_fails():
    """Codex V2 3R-2 — 비정상(비객체) 항목을 조용히 건너뛰지 않는다."""
    payload = _file_receipt()
    payload["portal_sessions"].append("garbage-entry")
    with pytest.raises(ValueError):
        _validate("완료\n" + _login_receipt_line(), file_payload=payload)


def test_read_login_receipt_rejects_duplicate_file_keys(tmp_path, monkeypatch):
    """Codex V2 3R-1 — 영수증 파일의 JSON 중복 키(뒤값 승리)도 None(차단)."""
    target = tmp_path / fleet_worker.LOGIN_RECEIPT_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        '{"generated_at": "2026-07-24T00:00:00+00:00", '
        '"portal_sessions": [], "portal_sessions": []}', encoding="utf-8")
    monkeypatch.setattr(fleet_worker, "REPO", tmp_path)
    assert fleet_worker._read_login_receipt() is None


def test_login_prompt_requires_receipt_marker():
    prompt = fleet_worker.build_job_prompt(_login_job())
    assert fleet_worker._LOGIN_RECEIPT_MARKER in prompt


# ── Codex V2 F3 — followup:login 자동 체이닝 차단 ────────────────────────


def test_followup_skills_exclude_login():
    assert "login" not in job_queue.FOLLOWUP_SKILLS
    assert set(job_queue.FOLLOWUP_SKILLS) == set(job_queue.FLEET_SKILLS) - {"login"}


def test_new_job_payload_rejects_followup_login():
    payload = job_queue.new_job_payload(
        machine="macmini", skill="url",
        position_url="https://app.clickup.com/t/86eufjabc",
        requested_by=OWNER_ID, role="owner",
        params={"followup_skill": "login"},
    )
    assert payload is None


def test_fleet_args_rejects_followup_login():
    from tools.multi_position_sourcing.fleet_args import (
        FleetArgsError, parse_fleet_args)
    with pytest.raises(FleetArgsError):
        parse_fleet_args(
            "fleet-run",
            "url:https://app.clickup.com/t/86eufjabc followup:login")


# ── Codex V2 F1 — 운영(관리자) 경로에서도 login 등록이 가능해야 한다 ─────


def test_public_dns_check_skipped_only_for_login_empty_url():
    assert job_queue.position_url_requires_public_dns(
        {"skill": "login", "position_url": ""}) is False
    assert job_queue.position_url_requires_public_dns(
        {"skill": "humansearch",
         "position_url": "https://app.clickup.com/t/86eufjabc"}) is True
    # login 이라도 URL 이 있으면 DNS 검사 대상(약화 금지).
    assert job_queue.position_url_requires_public_dns(
        {"skill": "login",
         "position_url": "https://app.clickup.com/t/86eufjabc"}) is True


def test_login_migration_extends_jobs_skill_check():
    import pathlib
    files = sorted(pathlib.Path("supabase/migrations").glob("*login_skill*.sql"))
    assert files, "login 스킬 DB 마이그레이션이 없습니다(라이브 큐가 login 을 거부)"
    sql = files[-1].read_text(encoding="utf-8")
    assert "jobs_skill_check" in sql
    assert "'login'" in sql
