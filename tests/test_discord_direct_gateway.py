"""디스코드 직결 게이트웨이 조각 C — RED 먼저
(goal: docs/prompts/discord-direct-connect-goal-2026-07-17.md §5C)

인수 기준(기계 단언):
- 명령 소유권 일치: 등록 대상 슬래시 명령 = fleet_dispatch.FLEET_COMMANDS 처리 로직이
  실제 있는 명령만(search-status/run-search/register-position/session-status/
  relogin-needed 는 정의만 있고 처리가 없어 제외).
- 인터랙션 → DiscordEnvelope 변환은 길드 컨텍스트(guild_id/channel_id/role_ids)를
  실제로 채운다(DM 고정 금지, hermes_fleet_bridge 방식 재사용 아님).
- 슬래시 3초 규칙: handle_envelope(net I/O) 호출 전에 반드시 interaction.response.defer
  가 먼저 불린다(호출 순서 fake 로 검증).
- fail-closed 침묵: response=None 인 모든 경로(비인가/신원미상/미지원)는 항상 동일한
  무정보 ack 를 보낸다 — 침묵 사유별로 회신 내용이 달라지면 그 차이 자체가 "명령이
  존재/적용된다"는 신호가 되므로 금지.
- 예외 메시지에 토큰 모양 문자열이 회신에 노출되지 않는다.
- 단위테스트는 discord.py 의 실제 게이트웨이/HTTP 를 켜지 않는다(fake 인터랙션/메시지만).
"""

from __future__ import annotations

import shlex
import unittest

from scripts.discord_direct_gateway import (
    handle_slash_interaction,
    handle_text_message,
    interaction_to_envelope,
    message_to_envelope,
    slash_commands_to_register,
)
from tools.multi_position_sourcing.access import DiscordAuthorizedUser
from tools.multi_position_sourcing.direct_receiver import DiscordEnvelope
from tools.multi_position_sourcing.discord_routing import DiscordAccessConfig
from tools.multi_position_sourcing.fleet_dispatch import FLEET_COMMANDS

OWNER_ID = "814353841088757800"
MEMBER_ID = "222222222222222222"
STRANGER_ID = "999999999999999999"
CLICKUP_URL = "https://app.clickup.com/t/86eznizpq"

AUTHORIZED = (
    DiscordAuthorizedUser(name="Owner", alias="o", email="o@valueconnect.kr", discord_id=OWNER_ID),
    DiscordAuthorizedUser(name="Member", alias="m", email="m@x.com", discord_id=MEMBER_ID),
)


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []
        self._next_id = 1

    def enqueue(self, payload: dict) -> dict:
        job = dict(payload)
        job["id"] = self._next_id
        self._next_id += 1
        self.enqueued.append(job)
        return job

    def recent(self, limit: int = 10) -> list[dict]:
        return list(reversed(self.enqueued))[:limit]


class FakeResponse:
    """discord.InteractionResponse 흉내 — defer 호출 순서·인자만 기록."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.is_done_flag = False

    async def defer(self, *, ephemeral: bool = False) -> None:
        self._calls.append(f"defer(ephemeral={ephemeral})")
        self.is_done_flag = True

    def is_done(self) -> bool:
        return self.is_done_flag


class FakeFollowup:
    def __init__(self, calls: list[str], sent: list[dict]) -> None:
        self._calls = calls
        self._sent = sent

    async def send(self, content: str = "", *, ephemeral: bool = False) -> None:
        self._calls.append(f"followup.send(ephemeral={ephemeral})")
        self._sent.append({"content": content, "ephemeral": ephemeral})


class FakeRole:
    def __init__(self, role_id: str) -> None:
        self.id = int(role_id)


class FakeMember:
    def __init__(self, user_id: str, roles: tuple[str, ...] = ()) -> None:
        self.id = int(user_id)
        self.roles = [FakeRole(r) for r in roles]


class FakeInteraction:
    def __init__(
        self,
        *,
        interaction_id: str,
        user_id: str,
        command: str,
        options: list[dict] | None = None,
        guild_id: str | None = None,
        channel_id: str = "555555555555555555",
        role_ids: tuple[str, ...] = (),
    ) -> None:
        self.id = int(interaction_id)
        self.data = {"name": command, "options": options or []}
        self.guild_id = int(guild_id) if guild_id else None
        self.channel_id = int(channel_id)
        self.user = FakeMember(user_id, role_ids)
        self.calls: list[str] = []
        self.sent: list[dict] = []
        self.response = FakeResponse(self.calls)
        self.followup = FakeFollowup(self.calls, self.sent)


class FakeChannel:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def send(self, content: str) -> None:
        self._calls.append("channel.send")


class FakeGuild:
    def __init__(self, guild_id: str) -> None:
        self.id = int(guild_id)


class FakeMessage:
    def __init__(
        self,
        *,
        message_id: str,
        author_id: str,
        content: str,
        guild_id: str | None = None,
        channel_id: str = "555555555555555555",
        role_ids: tuple[str, ...] = (),
    ) -> None:
        self.id = int(message_id)
        self.content = content
        self.guild = FakeGuild(guild_id) if guild_id else None
        self.author = FakeMember(author_id, role_ids)
        self.calls: list[str] = []
        self.channel = FakeChannel(self.calls)
        object.__setattr__(self.author, "id", int(author_id))
        # id via channel_id for envelope's channel_id field
        self._channel_id = channel_id
        self.channel.id = int(channel_id)


class CommandOwnershipTests(unittest.TestCase):
    def test_only_fleet_dispatch_owned_commands_registered(self) -> None:
        names = {p["name"] for p in slash_commands_to_register()}
        self.assertEqual(names, set(FLEET_COMMANDS))

    def test_dead_ui_commands_excluded(self) -> None:
        names = {p["name"] for p in slash_commands_to_register()}
        for dead in ("search-status", "run-search", "register-position",
                     "session-status", "relogin-needed"):
            self.assertNotIn(dead, names)


class InteractionEnvelopeTests(unittest.TestCase):
    def test_guild_context_preserved_not_dm_locked(self) -> None:
        interaction = FakeInteraction(
            interaction_id="111111111111111111", user_id=MEMBER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
            guild_id="666666666666666666", channel_id="777777777777777777",
            role_ids=("888888888888888888",),
        )
        envelope = interaction_to_envelope(interaction)
        self.assertIsNotNone(envelope)
        self.assertFalse(envelope.is_dm)
        self.assertEqual(envelope.guild_id, "666666666666666666")
        self.assertEqual(envelope.channel_id, "777777777777777777")
        self.assertEqual(envelope.role_ids, ("888888888888888888",))
        self.assertIn("url:", envelope.raw_args)
        self.assertIn(CLICKUP_URL, envelope.raw_args)

    def test_dm_interaction_has_no_guild(self) -> None:
        interaction = FakeInteraction(
            interaction_id="222222222222222222", user_id=OWNER_ID,
            command="fleet-status",
        )
        envelope = interaction_to_envelope(interaction)
        self.assertIsNotNone(envelope)
        self.assertTrue(envelope.is_dm)
        self.assertEqual(envelope.guild_id, "")
        self.assertEqual(envelope.role_ids, ())

    def test_options_round_trip_via_shlex(self) -> None:
        # 공백을 포함한 값도 원본 그대로 살아남아야 한다(quote→shlex.split 왕복).
        interaction = FakeInteraction(
            interaction_id="333333333333333333", user_id=OWNER_ID,
            command="fleet-resume", options=[{"name": "job", "value": "7"}],
        )
        envelope = interaction_to_envelope(interaction)
        tokens = shlex.split(envelope.raw_args)
        self.assertIn("job:7", tokens)


class ThreeSecondDeferTests(unittest.IsolatedAsyncioTestCase):
    async def test_defer_called_before_queue_touched(self) -> None:
        interaction = FakeInteraction(
            interaction_id="444444444444444444", user_id=MEMBER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
        )
        queue = FakeQueue()
        order: list[str] = []

        class OrderedQueue(FakeQueue):
            def enqueue(self, payload):
                order.append("queue.enqueue")
                return super().enqueue(payload)

        oq = OrderedQueue()

        class OrderedResponse(FakeResponse):
            async def defer(self, *, ephemeral: bool = False) -> None:
                order.append("defer")
                await super().defer(ephemeral=ephemeral)

        interaction.response = OrderedResponse(interaction.calls)

        await handle_slash_interaction(
            interaction, queue=oq, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertEqual(order[0], "defer")
        self.assertIn("queue.enqueue", order)
        self.assertLess(order.index("defer"), order.index("queue.enqueue"))

    async def test_defer_is_first_call_even_when_denied(self) -> None:
        interaction = FakeInteraction(
            interaction_id="555555555555555555", user_id=STRANGER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
            guild_id="666666666666666666", channel_id="777777777777777777",
        )
        queue = FakeQueue()
        await handle_slash_interaction(
            interaction, queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allowed_channel_ids=(), allow_dm=True),
        )
        self.assertTrue(interaction.calls)
        self.assertTrue(interaction.calls[0].startswith("defer"))


class HandleSlashInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorized_fleet_run_enqueues_and_replies_once(self) -> None:
        interaction = FakeInteraction(
            interaction_id="666666666666666666", user_id=OWNER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
        )
        queue = FakeQueue()
        result = await handle_slash_interaction(
            interaction, queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertEqual(result["action"], "enqueued")
        self.assertEqual(len(queue.enqueued), 1)
        self.assertEqual(len(interaction.sent), 1)
        self.assertIn("잡", interaction.sent[0]["content"])
        self.assertTrue(interaction.sent[0]["ephemeral"])

    async def test_unauthorized_guild_channel_silent_generic_ack(self) -> None:
        interaction = FakeInteraction(
            interaction_id="777777777777777777", user_id=STRANGER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
            guild_id="666666666666666666", channel_id="999999999999999999",
        )
        queue = FakeQueue()
        result = await handle_slash_interaction(
            interaction, queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allowed_channel_ids=(), allow_dm=True),
        )
        self.assertIsNone(result["response"])
        self.assertEqual(queue.enqueued, [])
        self.assertEqual(len(interaction.sent), 1)  # discord 요구사항상 뭔가는 응답해야 함
        first_ack = interaction.sent[0]["content"]

        # 다른 침묵 사유(비인가자 목록 자체가 빈 경우)도 완전히 같은 ack 문구여야 한다 —
        # 사유별 회신 차이가 "명령 존재/적용" 신호가 되지 않도록.
        interaction2 = FakeInteraction(
            interaction_id="898989898989898989", user_id=STRANGER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
        )
        result2 = await handle_slash_interaction(
            interaction2, queue=FakeQueue(), authorized_users=(),
            config=DiscordAccessConfig(allowed_channel_ids=(), allow_dm=True),
        )
        self.assertIsNone(result2["response"])
        self.assertEqual(interaction2.sent[0]["content"], first_ack)

    async def test_unsupported_interaction_command_silent(self) -> None:
        interaction = FakeInteraction(
            interaction_id="888888888888888888", user_id=OWNER_ID,
            command="not-a-real-command",
        )
        result = await handle_slash_interaction(
            interaction, queue=FakeQueue(), authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertFalse(result.get("handled", True) is True and result.get("action") == "enqueued")
        self.assertEqual(len(interaction.sent), 1)

    async def test_parse_error_response_has_no_raw_exception_text(self) -> None:
        interaction = FakeInteraction(
            interaction_id="999999999999999999", user_id=OWNER_ID,
            command="fleet-run",
            options=[{"name": "url", "value": 'sk-fake-token-shaped-AAAABBBBCCCC "unclosed'}],
        )
        result = await handle_slash_interaction(
            interaction, queue=FakeQueue(), authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertIsNotNone(interaction.sent)
        for entry in interaction.sent:
            self.assertNotIn("Traceback", entry["content"])
            self.assertNotIn("shlex", entry["content"])

    async def test_followup_send_failure_does_not_raise(self) -> None:
        interaction = FakeInteraction(
            interaction_id="121212121212121212", user_id=OWNER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
        )

        class BrokenFollowup(FakeFollowup):
            async def send(self, content: str = "", *, ephemeral: bool = False) -> None:
                raise RuntimeError("network blip")

        interaction.followup = BrokenFollowup(interaction.calls, interaction.sent)
        # 예외가 새지 않아야 한다 — 회신 실패가 게이트웨이를 죽이면 안 됨.
        result = await handle_slash_interaction(
            interaction, queue=FakeQueue(), authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertEqual(result["action"], "enqueued")


class TextMessageTests(unittest.IsolatedAsyncioTestCase):
    def test_message_to_envelope_preserves_guild_context(self) -> None:
        message = FakeMessage(
            message_id="131313131313131313", author_id=MEMBER_ID,
            content="<@999999999999999999> fleet-status",
            guild_id="666666666666666666", channel_id="777777777777777777",
            role_ids=("888888888888888888",),
        )
        envelope = message_to_envelope(message, bot_user_id="999999999999999999")
        self.assertIsNotNone(envelope)
        self.assertFalse(envelope.is_dm)
        self.assertEqual(envelope.guild_id, "666666666666666666")
        self.assertEqual(envelope.role_ids, ("888888888888888888",))

    def test_message_without_mention_or_slash_ignored(self) -> None:
        message = FakeMessage(
            message_id="141414141414141414", author_id=MEMBER_ID,
            content="그냥 잡담입니다",
        )
        envelope = message_to_envelope(message, bot_user_id="999999999999999999")
        self.assertIsNone(envelope)

    async def test_text_message_authorized_dm_enqueues(self) -> None:
        message = FakeMessage(
            message_id="151515151515151515", author_id=OWNER_ID,
            content=f"/fleet-run url:{CLICKUP_URL}",
        )
        queue = FakeQueue()
        result = await handle_text_message(
            message, bot_user_id="999999999999999999", queue=queue,
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "enqueued")
        self.assertEqual(len(queue.enqueued), 1)
        self.assertIn("channel.send", message.calls)

    async def test_text_message_unsupported_returns_none_no_network(self) -> None:
        message = FakeMessage(
            message_id="161616161616161616", author_id=MEMBER_ID,
            content="hello there",
        )
        queue = FakeQueue()
        result = await handle_text_message(
            message, bot_user_id="999999999999999999", queue=queue,
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertIsNone(result)
        self.assertEqual(queue.enqueued, [])
        self.assertEqual(message.calls, [])


if __name__ == "__main__":
    unittest.main()
