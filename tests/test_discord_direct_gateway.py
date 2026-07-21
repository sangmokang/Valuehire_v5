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
import logging
import os
import shlex
import time
import unittest
from typing import Any
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
    def test_fleet_commands_and_direct_search_aliases_registered(self) -> None:
        names = {p["name"] for p in slash_commands_to_register()}
        self.assertEqual(
            names,
            set(FLEET_COMMANDS) | {"url", "aisearch", "humansearch"}
            | {"jobs", "login", "skill"},  # AC-1 단일 봇 콘솔 표면
        )

    def test_direct_search_alias_payloads_require_position_url(self) -> None:
        payloads = {p["name"]: p for p in slash_commands_to_register()}
        for command in ("url", "aisearch", "humansearch"):
            options = payloads[command]["options"]
            url_option = next(option for option in options if option["name"] == "url")
            self.assertTrue(url_option["required"])
            self.assertFalse(any(option["name"] == "skill" for option in options))

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
        self.assertEqual(
            names,
            {"fleet-status", "url", "aisearch", "humansearch", "jobs", "login", "skill"})


class InteractionEnvelopeTests(unittest.TestCase):
    def test_direct_search_aliases_normalize_to_fleet_run_with_fixed_skill(self) -> None:
        for index, command in enumerate(("url", "aisearch", "humansearch"), start=1):
            interaction = FakeInteraction(
                interaction_id=f"41{index:016d}",
                user_id=OWNER_ID,
                command=command,
                options=[{"name": "url", "value": CLICKUP_URL}],
            )
            envelope = interaction_to_envelope(interaction)
            assert envelope is not None
            self.assertEqual(envelope.command, "fleet-run")
            tokens = shlex.split(envelope.raw_args)
            self.assertIn(f"skill:{command}", tokens)
            self.assertIn(f"url:{CLICKUP_URL}", tokens)
            self.assertIn(f"idempotency:discord:{interaction.id}", tokens)

    def test_direct_alias_cannot_override_fixed_skill(self) -> None:
        interaction = FakeInteraction(
            interaction_id="424242424242424242",
            user_id=OWNER_ID,
            command="url",
            options=[
                {"name": "url", "value": CLICKUP_URL},
                {"name": "skill", "value": "humansearch"},
            ],
        )
        envelope = interaction_to_envelope(interaction)
        assert envelope is not None
        self.assertEqual(envelope.command, "fleet-run")
        self.assertEqual(shlex.split(envelope.raw_args).count("skill:url"), 1)
        self.assertIn("skill:humansearch", shlex.split(envelope.raw_args))

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


class IdempotencyKeyInjectionTests(unittest.TestCase):
    """INV-D2("같은 이벤트 2회 → 잡 1개") 를 게이트웨이 레벨에서 실제로 보증.

    Codex 5차 재검증 CRITICAL 실측 재현: 같은 Discord 이벤트를 2번 처리하면 실제로
    잡이 2개 생겼다(direct_receiver.handle_envelope 가 idempotency_key 를 자동으로
    채우지 않기 때문 — 그건 envelope 을 만드는 쪽의 책임). 이 테스트는 같은
    interaction_id/message_id 로 envelope 을 두 번 만들면 완전히 같은
    idempotency_key 가 들어가는지(=DB 유니크 인덱스가 실제로 중복을 잡을 수 있는
    조건) 확인한다."""

    def test_fleet_run_interaction_gets_deterministic_idempotency_key(self) -> None:
        def _make() -> str:
            interaction = FakeInteraction(
                interaction_id="343434343434343434", user_id=OWNER_ID,
                command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
            )
            return interaction_to_envelope(interaction).raw_args

        first, second = _make(), _make()
        self.assertEqual(first, second)
        self.assertIn("idempotency:discord:343434343434343434", first)

    def test_different_events_get_different_idempotency_keys(self) -> None:
        interaction1 = FakeInteraction(
            interaction_id="353535353535353535", user_id=OWNER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
        )
        interaction2 = FakeInteraction(
            interaction_id="363636363636363636", user_id=OWNER_ID,
            command="fleet-run", options=[{"name": "url", "value": CLICKUP_URL}],
        )
        raw1 = interaction_to_envelope(interaction1).raw_args
        raw2 = interaction_to_envelope(interaction2).raw_args
        self.assertNotEqual(raw1, raw2)

    def test_non_fleet_run_command_not_touched(self) -> None:
        interaction = FakeInteraction(
            interaction_id="373737373737373737", user_id=OWNER_ID, command="fleet-status",
        )
        envelope = interaction_to_envelope(interaction)
        self.assertNotIn("idempotency", envelope.raw_args)

    def test_explicit_idempotency_not_overwritten(self) -> None:
        result = gw._with_discord_idempotency_key(
            "fleet-run", "url:https://x.example.com idempotency:manual-key-123",
            "999999999999999999",
        )
        self.assertIn("idempotency:manual-key-123", result)
        self.assertNotIn("discord:999999999999999999", result)

    def test_text_message_fleet_run_gets_idempotency_key(self) -> None:
        message = FakeMessage(
            message_id="383838383838383838", author_id=OWNER_ID,
            content=f"/fleet-run url:{CLICKUP_URL}",
        )
        envelope = message_to_envelope(message, bot_user_id="999999999999999999")
        self.assertIn("idempotency:discord:383838383838383838", envelope.raw_args)


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
    async def test_each_direct_search_alias_enqueues_its_fixed_skill(self) -> None:
        for index, command in enumerate(("url", "aisearch", "humansearch"), start=1):
            interaction = FakeInteraction(
                interaction_id=f"61{index:016d}",
                user_id=OWNER_ID,
                command=command,
                options=[{"name": "url", "value": CLICKUP_URL}],
            )
            queue = FakeQueue()
            result = await handle_slash_interaction(
                interaction,
                queue=queue,
                authorized_users=AUTHORIZED,
                config=DiscordAccessConfig(allow_dm=True),
            )
            self.assertEqual(result["action"], "enqueued")
            self.assertEqual(len(queue.enqueued), 1)
            self.assertEqual(queue.enqueued[0]["skill"], command)

    async def test_direct_alias_missing_url_does_not_enqueue(self) -> None:
        interaction = FakeInteraction(
            interaction_id="626262626262626262",
            user_id=OWNER_ID,
            command="aisearch",
            options=[],
        )
        queue = FakeQueue()
        result = await handle_slash_interaction(
            interaction,
            queue=queue,
            authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertNotEqual(result.get("action"), "enqueued")
        self.assertEqual(queue.enqueued, [])

    async def test_direct_alias_skill_override_does_not_enqueue(self) -> None:
        interaction = FakeInteraction(
            interaction_id="636363636363636363",
            user_id=OWNER_ID,
            command="url",
            options=[
                {"name": "url", "value": CLICKUP_URL},
                {"name": "skill", "value": "humansearch"},
            ],
        )
        queue = FakeQueue()
        result = await handle_slash_interaction(
            interaction,
            queue=queue,
            authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertNotEqual(result.get("action"), "enqueued")
        self.assertEqual(queue.enqueued, [])

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
    def test_owner_text_alias_normalizes_to_fleet_run(self) -> None:
        for index, command in enumerate(("url", "aisearch", "humansearch"), start=1):
            message = FakeMessage(
                message_id=f"71{index:016d}",
                author_id=OWNER_ID,
                content=f"/{command} url:{CLICKUP_URL}",
            )
            envelope = message_to_envelope(message, bot_user_id="999999999999999999")
            assert envelope is not None
            self.assertEqual(envelope.command, "fleet-run")
            tokens = shlex.split(envelope.raw_args)
            self.assertIn(f"skill:{command}", tokens)
            self.assertIn(f"url:{CLICKUP_URL}", tokens)

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


class BuildClientOwnerConsistencyTests(unittest.TestCase):
    """Codex 2차검증 재재현 CRITICAL — _build_client() 가 FLEET_OWNER_DISCORD_IDS(env)
    로 owner_user_ids 를 바꿔 넘기면, 그 값은 게이트웨이 텍스트 DM 범위 필터에만
    반영되고 direct_receiver.handle_envelope → dispatch_fleet_command 내부의 owner
    전용 명령(resume/cancel) 판정은 fleet_dispatch.OWNER_USER_IDS 고정값만 본다(그
    경로는 조각 C 범위 밖이라 못 고침) — 두 지점이 다른 owner 를 가리키면 "새 owner
    는 DM 통과, resume/cancel 은 거부"라는 불일치가 재현된다. _build_client() 는
    항상 고정 OWNER_USER_IDS 를 써서 최소한 자기 안에서는 일관되게 유지해야 한다."""

    def test_build_client_uses_fixed_owner_ids_not_env_override(self) -> None:
        with patch.object(gw, "load_discord_access_config",
                           return_value=DiscordAccessConfig(allow_dm=True)), \
             patch.object(gw, "load_authorized_discord_users", return_value=AUTHORIZED), \
             patch.object(gw, "_minimal_privilege_queue_factory", return_value=lambda: FakeQueue()), \
             patch.dict(os.environ, {"FLEET_OWNER_DISCORD_IDS": "111111111111111111"}, clear=False):
            client = gw._build_client()
        self.assertEqual(tuple(client._owner_user_ids), gw.OWNER_USER_IDS)
        self.assertNotIn("111111111111111111", client._owner_user_ids)


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
        self.assertIsInstance(client, gw.MinimalPrivilegeQueueClient)
        self.assertEqual(client.key, "scoped-minimal-key")
        self.assertNotEqual(client.key, "admin-key-should-not-be-used")

    def test_rejects_dedicated_key_identical_to_service_role(self) -> None:
        """Codex 2차검증 재재현: 관리자급 키를 이름만 바꾼 전용 env 에 그대로 넣는
        설정 실수를 방어적으로 거부한다(문자열 일치 검사 — DB 쪽 실제 제한 역할이
        없다는 근본 한계까지 없애지는 못함, verdict 에 별도 명시)."""
        env = {
            gw.QUEUE_URL_ENV: "https://scoped.example.supabase.co",
            gw.QUEUE_KEY_ENV: "same-admin-key",
            "SUPABASE_SERVICE_ROLE_KEY": "same-admin-key",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit):
                gw._minimal_privilege_queue_factory()


class MinimalPrivilegeQueueClientRpcOnlyTests(unittest.TestCase):
    """Codex 4차 재검증 CRITICAL — "문자열 비교만으로는 실제 제한을 증명 못 한다".

    MinimalPrivilegeQueueClient 는 어떤 메서드를 호출해도 ``/rest/v1/rpc/<name>`` 경로만
    쳐야 한다 — ``/rest/v1/jobs``(테이블 직접 접근) 경로를 절대 안 쳐야, DB 마이그레이션
    (20260719_discord_gateway_minimal_privilege_rpc.sql)이 그은 경계와 코드가 실제로
    맞물린다. urlopen 을 가로채 실제 요청 URL 을 검사한다(네트워크 0).
    """

    def _client_with_recorder(self) -> tuple[Any, list[str]]:
        requested_urls: list[str] = []

        class FakeHTTPResponse:
            def __init__(self, body: bytes) -> None:
                self._body = body

            def read(self) -> bytes:
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=30):
            requested_urls.append(req.full_url)
            return FakeHTTPResponse(b"[]")

        client = gw.MinimalPrivilegeQueueClient(
            url="https://scoped.example.supabase.co", key="scoped-minimal-key")
        return client, requested_urls, fake_urlopen

    def test_recent_only_calls_rpc_endpoint(self) -> None:
        client, urls, fake_urlopen = self._client_with_recorder()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.recent(5)
        self.assertEqual(len(urls), 1)
        self.assertIn("/rest/v1/rpc/discord_gateway_recent_jobs", urls[0])
        self.assertNotIn("/rest/v1/jobs", urls[0])

    def test_resume_not_supported_no_network(self) -> None:
        """v2 보안 경계(Codex 5차 재검증 CRITICAL) — resume/cancel 을 anon RPC 로 노출하면
        신원 검증 없이 임의 잡 재개/취소가 가능해져(anon 키 보유자가 recent_jobs 로 id 를
        알아낸 뒤 호출) owner 전용 명령의 앱 레벨 인가를 완전히 우회한다. 그래서 이
        최소권한 클라이언트는 resume/cancel 을 아예 지원하지 않는다 — 네트워크조차
        안 나가야 한다."""
        client, urls, fake_urlopen = self._client_with_recorder()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(NotImplementedError):
                client.resume(1)
        self.assertEqual(urls, [])

    def test_cancel_not_supported_no_network(self) -> None:
        client, urls, fake_urlopen = self._client_with_recorder()
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(NotImplementedError):
                client.cancel(1, "test")
        self.assertEqual(urls, [])

    def test_enqueue_only_calls_rpc_endpoint_not_table(self) -> None:
        client, urls, fake_urlopen = self._client_with_recorder()

        class FakeHTTPResponse:
            def __init__(self, body: bytes) -> None:
                self._body = body

            def read(self) -> bytes:
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen_with_row(req, timeout=30):
            urls.append(req.full_url)
            import json as _json
            return FakeHTTPResponse(_json.dumps([{"id": 1, "status": "queued"}]).encode())

        with patch("urllib.request.urlopen", side_effect=fake_urlopen_with_row), \
             patch(
                 "tools.multi_position_sourcing.job_queue.url_host_resolves_public",
                 return_value=True):
            client.enqueue({
                "machine": "macmini", "skill": "aisearch",
                "position_url": "https://app.clickup.com/t/x", "requested_by": "owner:owner",
                "role": "owner", "params": {}, "status": "queued",
            })
        self.assertEqual(len(urls), 1)
        self.assertIn("/rest/v1/rpc/discord_gateway_enqueue", urls[0])
        self.assertNotIn("/rest/v1/jobs", urls[0])

    def test_enqueue_rejects_agent_skill_before_network(self) -> None:
        """v2 보안 경계 — skill='agent' 는 owner 전용(fragment E, 이 조각 범위 밖)이라
        이 최소권한 경로에서 절대 등록되면 안 된다. 파이썬 레벨에서 먼저 거부해
        네트워크조차 안 나가야 한다(RPC 쪽 화이트리스트와 이중 방어)."""
        client, urls, fake_urlopen = self._client_with_recorder()
        # new_job_payload 자체가 skill='agent' 를 받으려면 owner-agent 전용 params
        # 스키마(request_text/agent/execution_mode/approval_id/...) 를 통과해야 해서
        # 이 테스트 목적(내 PermissionError 방어선만 격리 검증)엔 과하다 — 재검증 함수를
        # "이미 통과한 것처럼" 패치해 MinimalPrivilegeQueueClient.enqueue 자체의 방어를
        # 고립시켜 확인한다.
        fake_revalidated = {
            "machine": "macmini", "skill": "agent", "position_url": CLICKUP_URL,
            "requested_by": "owner:owner", "role": "owner", "params": {}, "account_key": "",
            "status": "queued",
        }
        with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             patch(
                 "tools.multi_position_sourcing.job_queue.url_host_resolves_public",
                 return_value=True), \
             patch(
                 "tools.multi_position_sourcing.job_queue.new_job_payload",
                 return_value=fake_revalidated):
            with self.assertRaises(PermissionError):
                client.enqueue({
                    "machine": "macmini", "skill": "agent",
                    "position_url": CLICKUP_URL, "requested_by": "owner:owner",
                    "role": "owner", "params": {}, "status": "queued",
                })
        self.assertEqual(urls, [])

    def test_enqueue_never_sends_p_role_field(self) -> None:
        """RPC 페이로드에 p_role 키 자체가 없어야 한다(SQL 함수 시그니처에도 p_role
        파라미터가 없다 — 완전히 제거됐는지 확인, 부분 수정으로 남아있으면 안 된다)."""
        client, urls, fake_urlopen = self._client_with_recorder()
        captured_bodies: list[bytes] = []

        class FakeHTTPResponse:
            def __init__(self, body: bytes) -> None:
                self._body = body

            def read(self) -> bytes:
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen_capture(req, timeout=30):
            captured_bodies.append(req.data)
            import json as _json
            return FakeHTTPResponse(_json.dumps([{"id": 1}]).encode())

        with patch("urllib.request.urlopen", side_effect=fake_urlopen_capture), \
             patch(
                 "tools.multi_position_sourcing.job_queue.url_host_resolves_public",
                 return_value=True):
            client.enqueue({
                "machine": "macmini", "skill": "aisearch",
                "position_url": "https://app.clickup.com/t/x", "requested_by": "owner:owner",
                "role": "owner", "params": {}, "status": "queued",
            })
        self.assertEqual(len(captured_bodies), 1)
        self.assertNotIn(b'"p_role"', captured_bodies[0])


class MinimalPrivilegeMigrationStaticTests(unittest.TestCase):
    """마이그레이션 SQL 자체를 정적으로 검사 — 라이브 DB 가 없는 이 worktree 에서는
    이게 "실제 제한이 걸릴 것"이라는 유일한 기계 증거다(적용 자체는 별도 배포 단계,
    goal §7 조각 J). v2(Codex 5차 재검증 CRITICAL 반영) — 3개 RPC 만 anon 에 grant
    되고, resume_job/cancel_job 은 **이 파일에서 anon 에 grant 되지 않아야** 한다
    (최초판은 grant 했었고, 그게 신원 검증 없는 임의 잡 취소/재개 우회였다). jobs/
    account_locks 테이블 자체는 anon 에게 여전히 막혀 있는지도 확인한다."""

    def _sql(self) -> str:
        import pathlib

        path = (pathlib.Path(gw.__file__).resolve().parents[1]
                / "supabase" / "migrations"
                / "20260719_discord_gateway_minimal_privilege_rpc.sql")
        self.assertTrue(path.exists(), f"마이그레이션 파일 없음: {path}")
        return path.read_text(encoding="utf-8")

    def test_grants_execute_on_three_rpcs_to_anon_specifically(self) -> None:
        """Codex 5차 재검증 MINOR 지적: 이전 테스트는 "grant execute ... public.{fn}"
        접두어만 확인하고 문장이 실제로 "to anon" 으로 끝나는지(다른 role 로 잘못
        바뀌어도 통과) 검사하지 않았다 — 이번엔 전체 grant 문장을 정확히 매칭한다."""
        sql = self._sql().lower()
        self.assertIn(
            "grant execute on function public.discord_gateway_enqueue"
            "(text, text, text, text, jsonb, text) to anon;", sql)
        self.assertIn(
            "grant execute on function public.discord_gateway_recent_jobs(int) to anon;", sql)
        self.assertIn(
            "grant execute on function public.discord_gateway_job_by_idempotency_key(text) "
            "to anon;", sql)

    def test_does_not_grant_resume_or_cancel_to_anon(self) -> None:
        """v2 핵심 봉인 — resume_job/cancel_job 을 anon 에 grant 하는 문장이 이 파일에
        있으면 안 된다(있었던 v1 결함의 회귀 방지). 함수 자체는 언급될 수 있지만
        (설계 노트 주석 안에서), "grant execute ... resume_job... to anon" 조합이
        코드로는 존재하면 안 된다."""
        sql = self._sql().lower()
        self.assertNotIn("grant execute on function public.resume_job(bigint) to anon", sql)
        self.assertNotIn(
            "grant execute on function public.cancel_job(bigint, text) to anon", sql)

    def test_enqueue_function_signature_has_no_role_parameter(self) -> None:
        """v2 핵심 봉인 — discord_gateway_enqueue 함수 시그니처에 p_role 파라미터가
        없어야 한다(호출자가 role 을 골라 owner 잡을 위조하지 못하게, SQL 안에서
        항상 'member' 로 하드코딩). 설명 주석에는 "p_role" 문자열이 역사적 맥락으로
        등장하므로(v1 결함 설명), 실제 파라미터 선언 패턴("p_role text")만 검사한다."""
        sql = self._sql()
        self.assertNotIn("p_role text", sql)
        self.assertIn("'member'", sql)

    def test_enqueue_function_rejects_agent_skill_in_sql(self) -> None:
        sql = self._sql()
        self.assertIn("humansearch", sql)
        self.assertIn("이 최소권한 경로는 humansearch/aisearch/url 스킬만 허용합니다", sql)

    def test_revokes_direct_table_access_from_anon(self) -> None:
        sql = self._sql().lower()
        self.assertIn("revoke all on public.jobs from anon", sql)
        self.assertIn("revoke all on public.account_locks from anon", sql)


class DefaultAuditTests(unittest.TestCase):
    def test_default_audit_does_not_raise_and_is_wired_into_client(self) -> None:
        gw._default_audit({"action": "denied", "reason": "test"})  # no exception = pass
        client = gw.DirectGatewayClient(
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
            queue_factory=lambda: FakeQueue(),
        )
        self.assertIsNotNone(client._audit)

    def test_default_audit_actually_emits_observable_log_record(self) -> None:
        """Codex 2차검증 재재현: logger.info() 만으로는 루트 로거에 핸들러가 없으면
        (기본 파이썬 상태) 아무 것도 안 보여 '감사 배선'이 이름뿐이었다. 이 모듈은
        자체 핸들러를 붙이므로 외부 logging 설정과 무관하게 실제 로그 레코드가
        나가야 한다 — assertLogs 로 실제 방출을 확인(존재 여부만 확인하고 끝나지
        않는다)."""
        with self.assertLogs("discord_direct_gateway", level="INFO") as captured:
            gw._default_audit({"action": "denied", "reason": "unit-test-marker-xyz"})
        self.assertTrue(
            any("unit-test-marker-xyz" in line for line in captured.output),
            captured.output,
        )

    def test_module_handler_actually_attached_independent_of_assertLogs(self) -> None:
        """Codex 4차 재검증 지적: assertLogs 는 그 자체가 임시 핸들러를 붙이므로,
        모듈이 스스로 핸들러를 붙였는지 여부와 무관하게 항상 통과한다(위 테스트의
        맹점). 이 테스트는 assertLogs 없이 ``gw.logger.handlers`` 를 직접 검사해
        모듈 자신의 핸들러가 실제로 붙어 있는지 확인한다 — 이걸 지우는 뮤턴트라면
        이 테스트가 잡는다."""
        self.assertTrue(
            any(isinstance(h, logging.StreamHandler) for h in gw.logger.handlers),
            "discord_direct_gateway 로거에 자체 StreamHandler 가 없음",
        )
        self.assertFalse(gw.logger.propagate)


class CommandBackupTests(unittest.TestCase):
    """goal §3 '등록 롤백' — 전체 PUT 교체 전에 기존 명령 payload 를 파일로 백업한다."""

    def test_backup_writes_current_commands_to_file(self) -> None:
        import json
        import tempfile
        from unittest.mock import MagicMock

        existing_commands = [{"name": "old-command", "id": "1"}]
        fake_response = MagicMock()
        fake_response.read.return_value = json.dumps(existing_commands).encode("utf-8")
        fake_response.__enter__.return_value = fake_response
        fake_response.__exit__.return_value = False

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("urllib.request.urlopen", return_value=fake_response):
                path = gw.backup_current_discord_commands(
                    application_id="app123", bot_token="fake-token",
                    backup_dir=tmp_dir,
                )
            self.assertIsNotNone(path)
            saved = json.loads(open(path, encoding="utf-8").read())
            self.assertEqual(saved, existing_commands)

    def test_backup_returns_none_on_network_failure_fail_closed(self) -> None:
        import tempfile
        import urllib.error

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
                path = gw.backup_current_discord_commands(
                    application_id="app123", bot_token="fake-token",
                    backup_dir=tmp_dir,
                )
            self.assertIsNone(path)


class SyncCommandsBackupOrderingTests(unittest.IsolatedAsyncioTestCase):
    """_sync_commands() 운영 배선 레벨 — 백업 없이는 PUT(재등록)이 절대 안 나가야 한다."""

    async def test_register_skipped_when_backup_fails(self) -> None:
        client = gw.DirectGatewayClient(
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
            queue_factory=lambda: FakeQueue(),
        )
        register_calls = []
        with patch.object(gw, "backup_current_discord_commands", return_value=None), \
             patch(
                 "tools.multi_position_sourcing.register_discord_commands"
                 ".bulk_register_discord_commands",
                 side_effect=lambda **kw: register_calls.append(kw) or {"ok": True}), \
             patch.dict(os.environ, {"DISCORD_CLIENT_ID": "app123", "DISCORD_BOT_TOKEN": "tok"}):
            await client._sync_commands()
        self.assertEqual(register_calls, [])  # 백업 실패 → 등록(PUT) 자체를 안 부름.

    async def test_register_called_after_successful_backup(self) -> None:
        client = gw.DirectGatewayClient(
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
            queue_factory=lambda: FakeQueue(),
        )
        order: list[str] = []
        with patch.object(
                gw, "backup_current_discord_commands",
                side_effect=lambda **kw: order.append("backup") or "/tmp/fake-backup.json"), \
             patch(
                 "tools.multi_position_sourcing.register_discord_commands"
                 ".bulk_register_discord_commands",
                 side_effect=lambda **kw: order.append("register") or {"ok": True}), \
             patch.dict(os.environ, {"DISCORD_CLIENT_ID": "app123", "DISCORD_BOT_TOKEN": "tok"}):
            await client._sync_commands()
        self.assertEqual(order, ["backup", "register"])


class ExecutionPrimitiveTests(unittest.TestCase):
    """INV-D1 회귀 트립와이어 — subprocess/os.system/eval/exec 등이 새로 들어오면 잡는다.

    Codex 2차검증 재재현 지적: 이전 버전은 ``subprocess.run``(속성이 아니라 모듈 자체를
    안 막음), ``from subprocess import Popen`` 뒤 맨 이름 ``Popen(...)`` 호출, ``os.execv``
    를 놓쳤다. 이번엔 (a) import 자체를 허용목록으로 제한 + (b) 실행류 이름을 맨
    이름(Name)·속성(Attribute) 양쪽 다 넓게 배너해 우회를 줄인다.

    discord.Client.run()/setup_hook 등 discord.py 정상 사용까지 막지 않도록 gateway 전용
    허용목록으로 조정한다(direct_receiver.py 의 것과는 다른 화이트리스트 — 그쪽은 discord.py
    자체를 안 쓰므로 더 엄격했다)."""

    _ALLOWED_ABSOLUTE_IMPORTS = frozenset({
        "__future__", "asyncio", "logging", "os", "re", "shlex", "json", "time",
        "typing", "discord",
    })
    _ALLOWED_IMPORT_PREFIXES = ("urllib", "pathlib", "tools.multi_position_sourcing")

    _BANNED_NAMES = frozenset({
        "eval", "exec", "compile", "__import__", "subprocess", "Popen", "popen2",
        "system", "popen", "execv", "execve", "execl", "execle", "execlp", "execvp",
        "spawnl", "spawnv", "spawnve", "fork", "getoutput", "check_output",
    })
    _BANNED_ATTRS = frozenset({
        "system", "popen", "Popen", "spawn", "spawnl", "spawnv", "spawnve",
        "check_output", "call", "getoutput", "execv", "execve", "execl", "execle",
        "execlp", "execvp", "fork", "run_module", "run_path",
        "__builtins__", "__globals__", "__subclasses__", "__bases__", "__mro__",
    })

    def _violations_in_source(self, source: str) -> list[str]:
        tree = ast.parse(source)
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if (alias.name not in self._ALLOWED_ABSOLUTE_IMPORTS
                            and top not in self._ALLOWED_ABSOLUTE_IMPORTS
                            and not any(alias.name.startswith(p) for p in self._ALLOWED_IMPORT_PREFIXES)):
                        violations.append(f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                top = module_name.split(".")[0]
                if (module_name not in self._ALLOWED_ABSOLUTE_IMPORTS
                        and top not in self._ALLOWED_ABSOLUTE_IMPORTS
                        and not any(module_name.startswith(p) for p in self._ALLOWED_IMPORT_PREFIXES)):
                    violations.append(f"from {module_name} import ...")
                # Codex 4차검증 지적: `from os import execv as harmless` 처럼 별칭을 쓰면
                # 이후 코드에서 "harmless(...)" 로만 나타나 ast.Name 검사(원래 이름
                # "execv")를 피해간다 — import 시점의 원래 이름(alias.name, asname 아님)
                # 자체를 여기서 검사해 별칭 우회를 막는다.
                for alias in node.names:
                    if alias.name in self._BANNED_NAMES:
                        violations.append(f"import-name:{alias.name}")
            elif isinstance(node, ast.Name) and node.id in self._BANNED_NAMES:
                violations.append(f"name:{node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in self._BANNED_ATTRS:
                violations.append(f"attr:{node.attr}")
        return violations

    def test_no_execution_primitives_in_source(self) -> None:
        import scripts.discord_direct_gateway as module

        source = open(module.__file__, encoding="utf-8").read()
        self.assertEqual(self._violations_in_source(source), [])

    def test_trip_wire_catches_subprocess_run(self) -> None:
        """자기검증 — 트립와이어 자체가 codex 가 놓쳤던 4종(별칭 우회 포함)을 실제로
        잡는지, 실제 검사 로직(``_violations_in_source``)을 그대로 재사용해 확인한다
        (로직이 두 곳에서 따로 유지되면 드리프트가 생기므로 하나만 둔다)."""
        for mutant_source in (
            "import subprocess\nsubprocess.run(['ls'])\n",
            "from subprocess import Popen\nPopen(['ls'])\n",
            "import os\nos.execv('/bin/ls', [])\n",
            "from os import execv as harmless\nharmless('/bin/ls', [])\n",
        ):
            found = self._violations_in_source(mutant_source)
            self.assertTrue(found, f"트립와이어가 놓침: {mutant_source!r}")


if __name__ == "__main__":
    unittest.main()
