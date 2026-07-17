"""디스코드 직결 수신기 조각 A — envelope + 순수 수신 로직 (goal: docs/prompts/discord-direct-connect-goal-2026-07-17.md §5A).

인수 기준(기계 단언):
- /fleet-run envelope 1건 → dispatch_fleet_command 정확히 1회 + 응답문(잡 번호 포함).
- 파싱(parse_hermes_fleet_args)·권한검사(route_discord_invocation)는 경로당 정확히 1회(INV-D3).
- 비인가 사용자·신원미상 → 응답 None(침묵) + 감사 이벤트만(INV-D6). 큐 접촉 0.
- 길드 컨텍스트 보존: guild_id/channel_id/role_ids 가 DiscordInvocation 까지 그대로 전달
  (기존 hermes_fleet_bridge 의 DM 고정 재사용 금지 — goal §3).
- 검색 명령 인자 파싱 실패(따옴표 안 닫힘 등) → fail-closed: 인가자에겐 안전한 안내문,
  비인가자에겐 침묵. 원본 예외 문자열 비노출.
- 수신기는 네트워크를 직접 만지지 않는다(큐·감사·시계 전부 주입, INV-D1).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tools.multi_position_sourcing import direct_receiver as dr
from tools.multi_position_sourcing import fleet_dispatch
from tools.multi_position_sourcing.access import DiscordAuthorizedUser
from tools.multi_position_sourcing.direct_receiver import (
    DiscordEnvelope,
    handle_envelope,
)
from tools.multi_position_sourcing.discord_routing import DiscordAccessConfig

OWNER_ID = "814353841088757800"
MEMBER_ID = "222222222222222222"
STRANGER_ID = "999999999999999999"
CLICKUP_URL = "https://app.clickup.com/t/86eznizpq"

AUTHORIZED = (
    DiscordAuthorizedUser(name="owner", alias="o", email="o@valueconnect.kr", discord_id=OWNER_ID),
    DiscordAuthorizedUser(name="member", alias="m", email="m@valueconnect.kr", discord_id=MEMBER_ID),
)


class FakeQueue:
    """enqueue 만 기록하는 가짜 큐 — 네트워크 0."""

    def __init__(self) -> None:
        self.enqueued: list[dict] = []

    def enqueue(self, payload: dict) -> dict:
        self.enqueued.append(payload)
        return {"id": 77, **payload}

    def recent(self, n: int) -> list[dict]:
        return []


def _dm_envelope(user_id: str = OWNER_ID, *, command: str = "fleet-run",
                 raw_args: str = CLICKUP_URL, event_id: str = "111111111111111111") -> DiscordEnvelope:
    return DiscordEnvelope(
        event_id=event_id, user_id=user_id, channel_id="333333333333333333",
        command=command, raw_args=raw_args, is_dm=True,
    )


class FleetRunDispatchTests(unittest.TestCase):
    def test_fleet_run_dispatches_once_and_replies_with_job_id(self) -> None:
        queue = FakeQueue()
        audit: list[dict] = []
        with patch.object(dr, "parse_hermes_fleet_args",
                          side_effect=dr.parse_hermes_fleet_args) as parse_spy, \
             patch.object(fleet_dispatch, "route_discord_invocation",
                          side_effect=fleet_dispatch.route_discord_invocation) as route_spy, \
             patch.object(dr, "dispatch_fleet_command",
                          side_effect=dr.dispatch_fleet_command) as dispatch_spy:
            result = handle_envelope(
                _dm_envelope(), queue=queue, authorized_users=AUTHORIZED,
                config=DiscordAccessConfig(allow_dm=True), audit=audit.append,
            )
        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "enqueued")
        self.assertEqual(len(queue.enqueued), 1)
        self.assertIn("77", result["response"], "응답문에 잡 번호가 있어야 한다")
        # INV-D3: 파싱·권한검사·디스패치 경로당 정확히 1회
        self.assertEqual(parse_spy.call_count, 1)
        self.assertEqual(route_spy.call_count, 1)
        self.assertEqual(dispatch_spy.call_count, 1)
        self.assertTrue(any(e.get("action") == "enqueued" for e in audit))

    def test_receiver_never_executes_itself_enqueue_only(self) -> None:
        # INV-D1: 수신기는 응답문 생성까지만 — 큐에 넣은 payload 는 기존 계약 그대로.
        queue = FakeQueue()
        handle_envelope(_dm_envelope(), queue=queue, authorized_users=AUTHORIZED,
                        config=DiscordAccessConfig(allow_dm=True))
        self.assertEqual(len(queue.enqueued), 1)
        payload = queue.enqueued[0]
        self.assertEqual(payload["status"], "queued")
        self.assertIn(payload["skill"], ("humansearch", "aisearch", "url"))


class FailClosedTests(unittest.TestCase):
    def test_unauthorized_user_gets_silence_and_audit_only(self) -> None:
        queue = FakeQueue()
        audit: list[dict] = []
        result = handle_envelope(
            _dm_envelope(STRANGER_ID), queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True), audit=audit.append,
        )
        self.assertIsNone(result["response"], "비인가자에겐 무응답(침묵)이어야 한다")
        self.assertEqual(queue.enqueued, [])
        self.assertTrue(any(e.get("action") == "denied" for e in audit),
                        "감사 로그에는 남아야 한다")

    def test_missing_identity_is_ignored_without_queue_touch(self) -> None:
        queue = FakeQueue()
        audit: list[dict] = []
        for bad in ("", "   ", "abc"):  # snowflake 모양 아님 = 신원 불신
            result = handle_envelope(
                _dm_envelope(bad), queue=queue, authorized_users=AUTHORIZED,
                config=DiscordAccessConfig(allow_dm=True), audit=audit.append,
            )
            self.assertIsNone(result["response"], bad)
        self.assertEqual(queue.enqueued, [])
        self.assertTrue(audit, "신원미상도 감사 이벤트는 남긴다")

    def test_parse_error_is_fail_closed_and_does_not_leak(self) -> None:
        queue = FakeQueue()
        # 인가자: 안전한 안내문(원본 셸 파싱 예외 원문 비노출), 큐 접촉 0.
        result = handle_envelope(
            _dm_envelope(raw_args='url:"unclosed'), queue=queue,
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertIsNotNone(result["response"])
        self.assertNotIn("Traceback", result["response"])
        self.assertNotIn("shlex", result["response"])
        self.assertEqual(queue.enqueued, [])
        # 비인가자: 파싱 실패라도 침묵(오류문으로 명령 존재를 알려주지 않는다).
        result2 = handle_envelope(
            _dm_envelope(STRANGER_ID, raw_args='url:"unclosed'), queue=queue,
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertIsNone(result2["response"])
        self.assertEqual(queue.enqueued, [])

    def test_control_characters_in_args_fail_closed(self) -> None:
        queue = FakeQueue()
        result = handle_envelope(
            _dm_envelope(raw_args="https://app.clickup.com/t/a b"), queue=queue,
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertNotEqual(result["action"], "enqueued")
        self.assertEqual(queue.enqueued, [])


class GuildContextTests(unittest.TestCase):
    """goal §3 — 직결 수신기는 길드 컨텍스트를 처음으로 진짜 전달한다(DM 고정 금지)."""

    def _guild_envelope(self, **overrides) -> DiscordEnvelope:
        fields = dict(
            event_id="444444444444444444", user_id=STRANGER_ID,
            channel_id="555555555555555555", guild_id="666666666666666666",
            role_ids=("777777777777777777",), command="fleet-run",
            raw_args=CLICKUP_URL, is_dm=False,
        )
        fields.update(overrides)
        return DiscordEnvelope(**fields)

    def test_guild_fields_reach_invocation_unchanged(self) -> None:
        queue = FakeQueue()
        seen: list = []

        def capture(invocation, **kwargs):
            seen.append(invocation)
            return dr.dispatch_fleet_command(invocation, **kwargs)

        config = DiscordAccessConfig(
            allowed_channel_ids=("555555555555555555",),
            allowed_role_ids=("777777777777777777",),
        )
        with patch.object(dr, "dispatch_fleet_command", side_effect=capture):
            result = handle_envelope(
                self._guild_envelope(), queue=queue,
                authorized_users=AUTHORIZED, config=config,
            )
        self.assertEqual(result["action"], "enqueued", "역할 허용 → 등록돼야 한다")
        inv = seen[0]
        self.assertFalse(inv.is_dm, "DM 고정(hermes 어댑터 재사용) 금지")
        self.assertEqual(inv.guild_id, "666666666666666666")
        self.assertEqual(inv.channel_id, "555555555555555555")
        self.assertEqual(inv.member_role_ids, ("777777777777777777",))

    def test_guild_channel_not_allowlisted_is_silent(self) -> None:
        queue = FakeQueue()
        audit: list[dict] = []
        config = DiscordAccessConfig(allowed_channel_ids=("123456789012345678",))
        result = handle_envelope(
            self._guild_envelope(), queue=queue,
            authorized_users=AUTHORIZED, config=config, audit=audit.append,
        )
        self.assertIsNone(result["response"])
        self.assertEqual(queue.enqueued, [])
        self.assertTrue(any(e.get("action") == "denied" for e in audit))


class MemberOwnerBoundaryTests(unittest.TestCase):
    def test_member_owner_only_command_gets_polite_denial_not_silence(self) -> None:
        # 인가된 멤버가 owner 전용(fleet-cancel)을 부르면 — 신원은 믿으므로 침묵이 아니라 안내.
        queue = FakeQueue()
        result = handle_envelope(
            _dm_envelope(MEMBER_ID, command="fleet-cancel", raw_args="job:3"),
            queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertIsNotNone(result["response"])
        self.assertIn("owner", result["response"])
        self.assertEqual(queue.enqueued, [])


if __name__ == "__main__":
    unittest.main()
