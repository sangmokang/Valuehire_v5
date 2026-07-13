from __future__ import annotations

import json

import pytest

from tools.multi_position_sourcing.hermes_fleet_bridge import (
    FLEET_PLUGIN_COMMANDS,
    HermesFleetBridgeError,
    dispatch_hermes_fleet_command,
    parse_hermes_fleet_args,
)

OWNER = "814353841088757800"
TEAM_MEMBER = "1404643716320329728"


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued = []
        self.resumed = []
        self.cancelled = []

    def enqueue(self, payload):
        self.enqueued.append(payload)
        return {"id": 41, **payload}

    def recent(self, limit):
        return [{"id": 41, "status": "queued"}]

    def resume(self, job_id):
        self.resumed.append(job_id)
        return {"id": job_id, "status": "queued"}

    def cancel(self, job_id, reason):
        self.cancelled.append((job_id, reason))
        return {"id": job_id, "status": "cancelled"}


def test_plugin_exposes_exactly_the_existing_four_fleet_commands() -> None:
    assert FLEET_PLUGIN_COMMANDS == (
        "fleet-run", "fleet-resume", "fleet-status", "fleet-cancel"
    )


def test_fleet_run_parses_only_known_fields_and_reuses_dispatch() -> None:
    queue = FakeQueue()
    result = dispatch_hermes_fleet_command(
        "fleet-run",
        "skill:humansearch url:https://app.clickup.com/t/abc machine:macmini",
        gateway_user_id=OWNER,
        queue=queue,
    )
    assert result["action"] == "enqueued"
    assert queue.enqueued[0]["skill"] == "humansearch"
    assert queue.enqueued[0]["machine"] == "macmini"


@pytest.mark.parametrize(
    ("command", "raw"),
    [
        ("fleet-status", "unexpected:value"),
        ("fleet-run", "skill:humansearch url:https://x.test machine:macmini extra:no"),
        ("fleet-resume", "job:1 extra:no"),
        ("unknown", ""),
    ],
)
def test_unknown_command_or_field_is_explicitly_rejected(command: str, raw: str) -> None:
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args(command, raw)


def test_unclosed_quote_is_rejected_not_leaked_as_raw_valueerror() -> None:
    # self-attack: shlex.split 이 못 닫힌 따옴표에 raw ValueError를 던지는데, 그게 그대로
    # 새면 상위 계약(HermesFleetBridgeError만 던진다는 약속)이 깨진다.
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args("fleet-run", "skill:humansearch url:'unterminated")


def test_duplicate_field_is_rejected_not_silently_overwritten() -> None:
    # self-attack: 같은 필드를 두 번 주면 뒷값이 앞값을 조용히 밀어낼 수 있다(스머글링) — 거부해야 함.
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args(
            "fleet-run", "skill:humansearch skill:aisearch url:https://x.test machine:macmini"
        )


def test_team_member_can_run_and_view_status_but_not_resume_or_cancel() -> None:
    queue = FakeQueue()
    run = dispatch_hermes_fleet_command(
        "fleet-run",
        "skill:humansearch url:https://app.clickup.com/t/abc machine:macmini",
        gateway_user_id=TEAM_MEMBER,
        queue=queue,
    )
    status = dispatch_hermes_fleet_command(
        "fleet-status", "", gateway_user_id=TEAM_MEMBER, queue=queue
    )
    assert run["action"] == "enqueued"
    assert status["action"] == "status"
    for command in ("fleet-resume", "fleet-cancel"):
        denied = dispatch_hermes_fleet_command(
            command, "job:7", gateway_user_id=TEAM_MEMBER, queue=queue
        )
        assert denied["action"] == "denied_owner_only"


def test_missing_gateway_identity_is_rejected_not_assumed_owner() -> None:
    with pytest.raises(HermesFleetBridgeError, match="identity"):
        dispatch_hermes_fleet_command(
            "fleet-status", "", gateway_user_id="", queue=FakeQueue()
        )


def test_unlisted_user_is_denied() -> None:
    result = dispatch_hermes_fleet_command(
        "fleet-status", "", gateway_user_id="999999999999999999", queue=FakeQueue()
    )
    assert result["action"] == "denied"


def test_status_and_owner_actions_return_json_serializable_results() -> None:
    queue = FakeQueue()
    for command, raw in (("fleet-status", ""), ("fleet-resume", "job:7"), ("fleet-cancel", "job:8")):
        result = dispatch_hermes_fleet_command(
            command, raw, gateway_user_id=OWNER, queue=queue
        )
        json.dumps(result, ensure_ascii=False)


def test_default_access_doc_resolves_regardless_of_process_cwd(monkeypatch, tmp_path) -> None:
    # 라이브 적대검증(2026-07-13)에서 실제 발견: 돌아가는 Hermes 게이트웨이의 cwd 는
    # ~/.hermes 라 상대경로 "docs/search-access.md" 는 항상 못 찾는다. 레포 루트 기준
    # 절대경로로 파생해야 cwd 와 무관하게 동작한다.
    monkeypatch.chdir(tmp_path)  # 레포 밖 임의 디렉터리로 이동 — 상대경로였다면 여기서 깨진다
    result = dispatch_hermes_fleet_command(
        "fleet-status", "", gateway_user_id=OWNER, queue=FakeQueue()
    )
    assert result["action"] == "status"


def test_bare_url_alone_defaults_skill_humansearch_and_machine_macmini() -> None:
    # 사장님 요청(2026-07-13): "그냥 /fleet-run 하고 클릭업 링크만 주면 서치하도록" —
    # skill:/machine: 없이 URL 하나만 줘도 humansearch/macmini 기본값으로 등록돼야 한다.
    options = parse_hermes_fleet_args("fleet-run", "https://app.clickup.com/t/abc")
    assert options == {"skill": "humansearch", "url": "https://app.clickup.com/t/abc"}


def test_bare_url_dispatches_end_to_end_with_defaults() -> None:
    queue = FakeQueue()
    result = dispatch_hermes_fleet_command(
        "fleet-run", "https://app.clickup.com/t/abc", gateway_user_id=OWNER, queue=queue
    )
    assert result["action"] == "enqueued"
    assert queue.enqueued[0]["skill"] == "humansearch"
    assert queue.enqueued[0]["machine"] == "macmini"
    assert queue.enqueued[0]["position_url"] == "https://app.clickup.com/t/abc"


def test_bare_url_with_explicit_skill_override_still_works() -> None:
    options = parse_hermes_fleet_args("fleet-run", "skill:aisearch https://app.clickup.com/t/abc")
    assert options == {"skill": "aisearch", "url": "https://app.clickup.com/t/abc"}


def test_bare_machine_token_overrides_default() -> None:
    options = parse_hermes_fleet_args("fleet-run", "https://app.clickup.com/t/abc winpc")
    assert options == {"skill": "humansearch", "url": "https://app.clickup.com/t/abc", "machine": "winpc"}


def test_bare_skill_token_also_accepted() -> None:
    options = parse_hermes_fleet_args("fleet-run", "https://app.clickup.com/t/abc aisearch")
    assert options == {"skill": "aisearch", "url": "https://app.clickup.com/t/abc"}


def test_bare_url_conflicting_with_explicit_url_key_is_rejected() -> None:
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args(
            "fleet-run", "url:https://a.test https://b.test"
        )


def test_two_bare_urls_is_rejected_not_last_one_wins() -> None:
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args("fleet-run", "https://a.test https://b.test")


def test_fleet_run_without_any_url_is_rejected_with_clear_message() -> None:
    with pytest.raises(HermesFleetBridgeError, match="url"):
        parse_hermes_fleet_args("fleet-run", "skill:humansearch machine:macmini")


def test_unrecognized_bare_word_is_still_rejected_not_guessed() -> None:
    # fail-closed: url/skill/machine 어디에도 안 맞는 맨 단어는 추측하지 않고 거부한다.
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args("fleet-run", "https://app.clickup.com/t/abc some_random_word")


def test_uppercase_scheme_bare_url_not_silently_accepted() -> None:
    # self-attack: 대소문자 우회로 URL 판정을 피해가려는 시도 — 소문자 http(s):// 만 인정.
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args("fleet-run", "HTTPS://app.clickup.com/t/abc")


def test_flexible_format_not_offered_to_other_commands() -> None:
    # fleet-status/resume/cancel 은 여전히 엄격 key:value 만 — bare 토큰 완화는 fleet-run 전용.
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args("fleet-resume", "7")


def test_unexpected_internal_error_is_reported_not_leaked_as_raw_exception(monkeypatch) -> None:
    # self-attack: authorized_users 로딩이나 큐 호출에서 예상 못 한 예외(파일 I/O, 네트워크)가
    # 나면 조용한 무응답(Hermes 쪽 광역 except 가 삼킴) 대신 명시적 error dict 로 보고해야 한다.
    class ExplodingQueue:
        def enqueue(self, payload):
            raise RuntimeError("boom")

    result = dispatch_hermes_fleet_command(
        "fleet-run",
        "skill:humansearch url:https://x.test machine:macmini",
        gateway_user_id=OWNER,
        queue=ExplodingQueue(),
    )
    assert result["action"] == "error"
    assert "boom" in result["reason"]
