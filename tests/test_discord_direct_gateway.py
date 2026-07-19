"""디스코드 직결 게이트웨이 조각 C (goal: docs/prompts/discord-direct-connect-goal-2026-07-17.md §5C)

인수 기준(기계 단언), Codex Rescue 2차 적대검증(NEEDS-FIX 5건) 반영 후 재봉인:
- 명령 소유권 일치: 등록 대상 슬래시 명령 = fleet_dispatch.FLEET_COMMANDS 처리 로직이
  실제 있는 명령만이며, 이 교집합은 FLEET_COMMANDS 를 동적으로 참조한다(하드코딩 아님).
- 인터랙션 → DiscordEnvelope 변환은 길드 컨텍스트(guild_id/channel_id/role_ids)를
  실제로 채운다(DM 고정 금지, hermes_fleet_bridge 방식 재사용 아님).
- 슬래시 3초 규칙: interaction.response.defer(ephemeral=True) 가 항상 첫 호출이며,
  큐 생성(queue_factory) 실패와도 무관하게 지켜진다(운영 배선 on_interaction 레벨까지).
- handle_envelope 의 net I/O 는 asyncio.to_thread 로 위임돼 이벤트 루프를 막지 않는다.
- fail-closed 침묵: response=None 인 모든 경로(비인가/신원미상/미지원)는 항상 동일한
  무정보 ack 를 보낸다.
- 예외 메시지·raw 옵션 값이 회신에 노출되지 않는다.
- 게이트웨이 자신은 SUPABASE_SERVICE_ROLE_KEY(관리자급)를 읽지 않는다(INV-D5).
- 텍스트 명령은 owner DM + 봇 멘션만(인가된 일반 멤버의 자유 DM 은 무시).
- 단위테스트는 discord.py 의 실제 게이트웨이/HTTP 를 켜지 않는다 — fleet-run 성공 경로가
  거치는 fleet_worker.discord_notify 도 명시적으로 무력화한다(네트워크 0 실제 보증).
"""

from __future__ import annotations

import ast
import os
import shlex
import time
import unittest
from unittest.mock import patch

from scripts import discord_direct_gateway as gw
from scripts.discord_direct_gateway import (
    handle_slash_interaction,
    handle_text_message,
    interaction_to_envelope,
    message_to_envelope,
    slash_commands_to_register,
)
from tools.multi_position_sourcing.access import DiscordAuthorizedUser
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


class _NotifySilencedCase(unittest.IsolatedAsyncioTestCase):
    """enqueue 에 도달하는 테스트는 워커의 직접 Discord 알림을 반드시 끈다.

    실자격증명이 보이는 로컬 환경에서 dispatch_fleet_command → discord_notify 가
    실발송하는 사고 방지(tests/test_direct_receiver.py 의 동일 패턴 재사용 — Codex
    2차검증 CRITICAL#4: "단위테스트가 네트워크 0 이라고 주장하지만 fleet-run 성공
    경로가 discord_notify 를 거쳐 실제 HTTP 를 낼 수 있다" 지적 반영).
    """

    def setUp(self) -> None:
        from tools.multi_position_sourcing import fleet_worker
        self._notify_calls: list[tuple] = []
        patcher = patch.object(
            fleet_worker, "discord_notify",
            lambda job, text: self._notify_calls.append((job, text)))
        patcher.start()
        self.addCleanup(patcher.stop)


class FakeQueue:
    def __init__(self, *, enqueue_delay: float = 0.0) -> None:
        self.enqueued: list[dict] = []
        self._next_id = 1
        self._enqueue_delay = enqueue_delay

    def enqueue(self, payload: dict) -> dict:
        if self._enqueue_delay:
            time.sleep(self._enqueue_delay)  # 동기 블로킹 — asyncio.to_thread 검증용.
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


class FakeInteractionEditor:
    """discord.Interaction.edit_original_response 흉내 — 첫 회신 경로(§8)."""

    def __init__(self, calls: list[str], sent: list[dict]) -> None:
        self._calls = calls
        self._sent = sent

    async def __call__(self, *, content: str = "") -> None:
        self._calls.append("edit_original_response")
        self._sent.append({"content": content, "ephemeral": True})


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
        self.edit_original_response = FakeInteractionEditor(self.calls, self.sent)


class FakeChannel:
    def __init__(self, calls: list[str], channel_id: str) -> None:
        self._calls = calls
        self.id = int(channel_id)

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
        self.channel = FakeChannel(self.calls, channel_id)


class CommandOwnershipTests(unittest.TestCase):
    def test_only_fleet_dispatch_owned_commands_registered(self) -> None:
        names = {p["name"] for p in slash_commands_to_register()}
        self.assertEqual(names, set(FLEET_COMMANDS))

    def test_dead_ui_commands_excluded(self) -> None:
        names = {p["name"] for p in slash_commands_to_register()}
        for dead in ("search-status", "run-search", "register-position",
                     "session-status", "relogin-needed"):
            self.assertNotIn(dead, names)

    def test_no_duplicate_command_names(self) -> None:
        names = [p["name"] for p in slash_commands_to_register()]
        self.assertEqual(len(names), len(set(names)))

    def test_filter_follows_fleet_commands_dynamically_not_hardcoded(self) -> None:
        """FLEET_COMMANDS 를 바꾸면 등록 목록도 같이 바뀌어야 한다 — 정적 목록 하드코딩
        이면 이 테스트가 실패한다(Codex 2차검증: "동적 추종이 검사로 봉인 안 됨" 반영)."""
        with patch.object(gw, "FLEET_COMMANDS", ("fleet-status",)):
            names = {p["name"] for p in slash_commands_to_register()}
        self.assertEqual(names, {"fleet-status"})


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
        interaction = FakeInteraction(
            interaction_id="333333333333333333", user_id=OWNER_ID,
            command="fleet-resume", options=[{"name": "job", "value": "7"}],
        )
        envelope = interaction_to_envelope(interaction)
        tokens = shlex.split(envelope.raw_args)
        self.assertIn("job:7", tokens)


class ThreeSecondDeferTests(_NotifySilencedCase):
    async def test_defer_called_before_queue_touched(self) -> None:
        interaction = FakeInteraction(
            interaction_id="444444444444444444", user_id=MEMBER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
        )
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
        self.assertIn("defer(ephemeral=True)", interaction.calls)

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

    async def test_defer_survives_queue_factory_failure(self) -> None:
        """운영 배선 결함(V1 CRITICAL#1) 재발 방지 — queue_factory() 가 예외를 던져도
        defer 는 이미 끝난 뒤라 3초 규칙이 깨지지 않고, 게이트웨이도 죽지 않는다."""
        interaction = FakeInteraction(
            interaction_id="565656565656565656", user_id=OWNER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
        )

        def failing_factory():
            raise RuntimeError("supabase 연결 실패")

        result = await handle_slash_interaction(
            interaction, queue_factory=failing_factory, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertTrue(interaction.calls[0].startswith("defer"))
        self.assertEqual(len(interaction.sent), 1)
        self.assertEqual(result["action"], "internal_error")

    async def test_on_interaction_does_not_prebuild_queue_before_defer(self) -> None:
        """DirectGatewayClient.on_interaction() 레벨 — 큐를 인자 평가 시점에 미리 만들지
        않는다(V1 CRITICAL#1 정확한 재현: 예전엔 handle_slash_interaction(..., queue=
        self._queue_factory()) 처럼 호출부에서 즉시 평가돼 defer 도달 전에 죽을 수 있었다)."""
        built = []

        def factory():
            built.append(1)
            raise RuntimeError("queue 생성 실패")

        client = gw.DirectGatewayClient(
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
            queue_factory=factory,
        )
        interaction = FakeInteraction(
            interaction_id="676767676767676767", user_id=OWNER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
        )
        import discord as _discord
        interaction.type = _discord.InteractionType.application_command
        await client.on_interaction(interaction)
        # defer 는 반드시 불렸어야 한다 — factory() 가 실패해도 무관.
        self.assertTrue(interaction.calls[0].startswith("defer"))
        self.assertEqual(len(interaction.sent), 1)


class NonBlockingEventLoopTests(_NotifySilencedCase):
    async def test_two_slow_enqueues_run_concurrently_not_serially(self) -> None:
        """handle_envelope 의 동기 net I/O(최대 30초)가 스레드로 위임돼야, 여러 인터랙션의
        블로킹 큐 호출이 서로를 기다리지 않고 동시에 진행된다(Codex 2차검증 CRITICAL: 동기
        호출이 이벤트 루프를 막아 다음 인터랙션 응답을 지연시킨다는 지적 반영).

        직접적인 방법 — 지연시간 0.2초짜리 enqueue 2건을 asyncio.gather 로 동시에 돌리고
        총 소요시간을 잰다. asyncio.to_thread 로 스레드풀에 위임되면 두 블로킹 호출이
        겹쳐 돌아 총 소요 ≈0.2초(왕복 오버헤드 포함 허용치 이내)여야 한다. 만약 이벤트
        루프에서 그대로(동기) 실행되면 두 번째 인터랙션의 defer→처리가 첫 번째가 끝날
        때까지 못 들어가 총 소요가 ≈0.4초로 거의 두 배가 된다 — 이 차이로 판정한다.
        """
        import asyncio
        import time as _time

        def _make_interaction(iid: str) -> FakeInteraction:
            return FakeInteraction(
                interaction_id=iid, user_id=OWNER_ID,
                command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
            )

        interaction1 = _make_interaction("818181818181818181")
        interaction2 = _make_interaction("828282828282828282")
        queue1 = FakeQueue(enqueue_delay=0.2)
        queue2 = FakeQueue(enqueue_delay=0.2)

        started = _time.monotonic()
        await asyncio.gather(
            handle_slash_interaction(
                interaction1, queue=queue1, authorized_users=AUTHORIZED,
                config=DiscordAccessConfig(allow_dm=True)),
            handle_slash_interaction(
                interaction2, queue=queue2, authorized_users=AUTHORIZED,
                config=DiscordAccessConfig(allow_dm=True)),
        )
        elapsed = _time.monotonic() - started
        # 동시 실행이면 ~0.2초, 순차(블로킹)면 ~0.4초 — 중간값 0.32초를 경계로 판정.
        self.assertLess(elapsed, 0.32, f"두 블로킹 큐 호출이 겹쳐 돌지 않음(순차 실행 의심): {elapsed:.3f}s")


class HandleSlashInteractionTests(_NotifySilencedCase):
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
        self.assertIn("edit_original_response", interaction.calls)
        # 네트워크 0 실제 보증 — discord_notify 는 무력화됐지만 "호출은 됐다"만 확인.
        self.assertEqual(len(self._notify_calls), 1)

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
        self.assertEqual(len(interaction.sent), 1)
        first_ack = interaction.sent[0]["content"]
        self.assertEqual(first_ack, gw._GENERIC_SILENT_ACK)

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
        self.assertEqual(interaction.sent[0]["content"], gw._GENERIC_SILENT_ACK)

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
            self.assertNotIn("sk-fake-token-shaped-AAAABBBBCCCC", entry["content"])

    async def test_followup_send_failure_does_not_raise(self) -> None:
        interaction = FakeInteraction(
            interaction_id="121212121212121212", user_id=OWNER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
        )

        async def broken_edit(*, content: str = "") -> None:
            raise RuntimeError("network blip")

        interaction.edit_original_response = broken_edit
        result = await handle_slash_interaction(
            interaction, queue=FakeQueue(), authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertEqual(result["action"], "enqueued")

    async def test_success_response_never_echoes_raw_args(self) -> None:
        """성공 경로도 envelope.raw_args 를 그대로 되돌려 보내지 않는다(요약 문구만)."""
        secret_looking = "sk-fake-token-shaped-AAAABBBBCCCC"
        interaction = FakeInteraction(
            interaction_id="989898989898989898", user_id=OWNER_ID,
            command="fleet-run",
            options=[{"name": "url", "value": CLICKUP_URL},
                     {"name": "agent", "value": secret_looking}],
        )
        # agent 는 claude|codex 만 허용되므로 이 값 자체는 parse 단계에서 거부되지만,
        # 거부 회신에도 원문이 안 보이는지 확인.
        result = await handle_slash_interaction(
            interaction, queue=FakeQueue(), authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        for entry in interaction.sent:
            self.assertNotIn(secret_looking, entry["content"])


class TextMessageTests(_NotifySilencedCase):
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
        self.assertEqual(envelope.channel_id, "777777777777777777")
        self.assertEqual(envelope.role_ids, ("888888888888888888",))

    def test_message_without_mention_or_slash_ignored(self) -> None:
        message = FakeMessage(
            message_id="141414141414141414", author_id=MEMBER_ID,
            content="그냥 잡담입니다",
        )
        envelope = message_to_envelope(message, bot_user_id="999999999999999999")
        self.assertIsNone(envelope)

    async def test_owner_dm_text_command_enqueues(self) -> None:
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

    async def test_member_dm_text_command_ignored_owner_only_scope(self) -> None:
        """goal §3 — 텍스트 명령 기본 범위는 owner DM + 봇 멘션만. 인가된 일반 멤버라도
        자유 DM 슬래시 텍스트는 큐에 닿으면 안 된다(Codex 2차검증 MINOR 지적 반영)."""
        message = FakeMessage(
            message_id="171717171717171717", author_id=MEMBER_ID,
            content=f"/fleet-run url:{CLICKUP_URL}",
        )
        queue = FakeQueue()
        result = await handle_text_message(
            message, bot_user_id="999999999999999999", queue=queue,
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertIsNone(result)
        self.assertEqual(queue.enqueued, [])
        self.assertEqual(message.calls, [])

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


class MinimalPrivilegeQueueTests(unittest.TestCase):
    """INV-D5 — 게이트웨이는 SUPABASE_SERVICE_ROLE_KEY(관리자급)를 절대 읽지 않는다."""

    def test_missing_dedicated_env_fails_closed(self) -> None:
        env = {
            "SUPABASE_SERVICE_ROLE_KEY": "admin-key-should-not-be-used",
            "NEXT_PUBLIC_SUPABASE_URL": "https://admin.example.supabase.co",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit):
                gw._minimal_privilege_queue_factory()

    def test_dedicated_env_builds_factory_without_reading_service_role(self) -> None:
        env = {
            gw.QUEUE_URL_ENV: "https://scoped.example.supabase.co",
            gw.QUEUE_KEY_ENV: "scoped-minimal-key",
            "SUPABASE_SERVICE_ROLE_KEY": "admin-key-should-not-be-used",
        }
        with patch.dict(os.environ, env, clear=True):
            factory = gw._minimal_privilege_queue_factory()
        client = factory()
        self.assertEqual(client.key, "scoped-minimal-key")
        self.assertNotEqual(client.key, "admin-key-should-not-be-used")


class DefaultAuditTests(unittest.TestCase):
    def test_default_audit_does_not_raise_and_is_wired_into_client(self) -> None:
        gw._default_audit({"action": "denied", "reason": "test"})  # no exception = pass
        client = gw.DirectGatewayClient(
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
            queue_factory=lambda: FakeQueue(),
        )
        self.assertIsNotNone(client._audit)


class ExecutionPrimitiveTests(unittest.TestCase):
    """INV-D1 회귀 트립와이어 — subprocess/os.system/eval/exec 등이 새로 들어오면 잡는다.

    discord.Client.run()/setup_hook 등 discord.py 정상 사용까지 막지 않도록 gateway 전용
    허용목록으로 조정한다(direct_receiver.py 의 것과는 다른 화이트리스트 — 그쪽은 discord.py
    자체를 안 쓰므로 더 엄격했다)."""

    _BANNED_NAMES = frozenset({"eval", "exec", "compile", "__import__"})
    _BANNED_ATTRS = frozenset({
        "system", "popen", "Popen", "spawn", "check_output", "call", "getoutput",
        "__builtins__", "__globals__", "__subclasses__", "__bases__", "__mro__",
    })

    def _violations(self) -> list[str]:
        import scripts.discord_direct_gateway as module

        source = open(module.__file__, encoding="utf-8").read()
        tree = ast.parse(source)
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in self._BANNED_NAMES:
                violations.append(f"name:{node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in self._BANNED_ATTRS:
                violations.append(f"attr:{node.attr}")
        return violations

    def test_no_execution_primitives_in_source(self) -> None:
        self.assertEqual(self._violations(), [])


if __name__ == "__main__":
    unittest.main()
