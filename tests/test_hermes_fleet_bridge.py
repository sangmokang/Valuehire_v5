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
