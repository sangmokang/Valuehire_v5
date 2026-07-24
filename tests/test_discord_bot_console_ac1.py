"""AC-1 — 단일 디스코드 봇 뼈대 (goal: docs/prompts/discord-single-bot-console-goal-2026-07-22.md §11 AC-1).

인수 기준(기계 단언):
- 파싱 함수 이사: direct_receiver 는 더 이상 hermes_fleet_bridge 를 import 하지 않고
  새 모듈 fleet_args 를 쓴다. hermes_fleet_bridge 는 AC-8 전까지 살아 있고(호환
  re-export), 두 이름은 같은 객체다(드리프트 0).
- 명령 표면: /aisearch /humansearch /url /login /skill /jobs 가 슬래시 등록 목록에
  있고, 검색 별칭에는 engine(claude|codex) 옵션이 있다.
- engine 미지정 → params.agent == "claude" (명시 라벨), engine:codex → "codex",
  이상값(대문자·공백·모르는 이름) → 거부(조용한 claude 폴백 금지).
- /skill 은 DB 화이트리스트(humansearch/aisearch/url) 밖 스킬을 "아직 지원하지
  않습니다"로 거부한다(마이그레이션은 AC 밖). /login 도 같은 게이트에 걸린다
  (login 스킬이 아직 큐 화이트리스트 밖 — E24 후속).
- 비인가 사용자/채널 → 침묵 + 큐 무접촉. 같은 event_id 2회 → 잡 1개.
- 큐 죽음(queue_factory 예외) → 명령을 삼키지 않고 "지금 접수 불가" 회신.
- 잘못된 URL(스킴 없음/공백/제어문자) → 큐 무접촉 거부.
- /jobs → 상태 요약 + Fleet-job 웹 링크.
"""

from __future__ import annotations

import pathlib
import shlex
import unittest
from typing import Any
from unittest.mock import patch

from scripts import discord_direct_gateway as gw
from scripts.discord_direct_gateway import (
    handle_slash_interaction,
    interaction_to_envelope,
    slash_commands_to_register,
)
from tools.multi_position_sourcing.access import DiscordAuthorizedUser
from tools.multi_position_sourcing.discord_routing import DiscordAccessConfig

ROOT = pathlib.Path(__file__).resolve().parent.parent
OWNER_ID = "814353841088757800"
STRANGER_ID = "999999999999999999"
CLICKUP_URL = "https://app.clickup.com/t/86eznizpq"
FLEET_TAB_URL = "https://admin.valuehire.cc/ai-search-list?view=fleet"

AUTHORIZED = (
    DiscordAuthorizedUser(name="Owner", alias="o", email="o@valueconnect.kr", discord_id=OWNER_ID),
)


class _NotifySilencedCase(unittest.IsolatedAsyncioTestCase):
    """enqueue 도달 테스트는 워커의 Discord 실알림을 끈다(기존 패턴 재사용)."""

    def setUp(self) -> None:
        from tools.multi_position_sourcing import fleet_worker
        patcher = patch.object(fleet_worker, "discord_notify", lambda job, text: None)
        patcher.start()
        self.addCleanup(patcher.stop)


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []
        self._next_id = 1

    def enqueue(self, payload: dict) -> dict:
        # 멱등키 계약(INV-D2): 같은 idempotency_key 는 기존 잡을 그대로 돌려준다.
        key = (payload.get("params") or {}).get("idempotency_key")
        if key:
            for job in self.enqueued:
                if (job.get("params") or {}).get("idempotency_key") == key:
                    return job
        job = dict(payload)
        job["id"] = self._next_id
        self._next_id += 1
        self.enqueued.append(job)
        return job

    def recent(self, limit: int = 10) -> list[dict]:
        return list(reversed(self.enqueued))[:limit]


class FakeResponse:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def defer(self, *, ephemeral: bool = False) -> None:
        self._calls.append(f"defer(ephemeral={ephemeral})")


class FakeFollowup:
    def __init__(self, calls: list[str], sent: list[dict]) -> None:
        self._calls, self._sent = calls, sent

    async def send(self, content: str = "", *, ephemeral: bool = False, **kwargs) -> None:
        self._calls.append("followup.send")
        self._sent.append({"content": content})


class FakeEditor:
    def __init__(self, calls: list[str], sent: list[dict]) -> None:
        self._calls, self._sent = calls, sent

    async def __call__(self, *, content: str = "", **kwargs) -> None:
        self._calls.append("edit_original_response")
        replacement = {"content": content}
        if self._sent:
            self._sent[-1] = replacement
        else:
            self._sent.append(replacement)


class FakeMember:
    def __init__(self, user_id: str) -> None:
        self.id = int(user_id)
        self.roles: list[Any] = []


class FakeInteraction:
    def __init__(self, *, interaction_id: str, user_id: str, command: str,
                 options: list[dict] | None = None, guild_id: str | None = None,
                 channel_id: str = "555555555555555555") -> None:
        self.id = int(interaction_id)
        self.data = {"name": command, "options": options or []}
        self.guild_id = int(guild_id) if guild_id else None
        self.channel_id = int(channel_id)
        self.user = FakeMember(user_id)
        self.calls: list[str] = []
        self.sent: list[dict] = []
        self.response = FakeResponse(self.calls)
        self.followup = FakeFollowup(self.calls, self.sent)
        self.edit_original_response = FakeEditor(self.calls, self.sent)


def _dm(command: str, options: list[dict] | None = None, *, user_id: str = OWNER_ID,
        interaction_id: str = "710000000000000001") -> FakeInteraction:
    return FakeInteraction(interaction_id=interaction_id, user_id=user_id,
                           command=command, options=options)


CONFIG = DiscordAccessConfig(allow_dm=True)


class ParsingModuleMoveTests(unittest.TestCase):
    """이사(AC-1 전제): 헤르메스 이름이 안 붙은 새 모듈 + 원본 호환 유지."""

    def test_new_module_exists_and_bridge_reexports_same_objects(self) -> None:
        from tools.multi_position_sourcing import fleet_args, hermes_fleet_bridge
        self.assertIs(hermes_fleet_bridge.parse_hermes_fleet_args, fleet_args.parse_fleet_args)
        self.assertIs(hermes_fleet_bridge.HermesFleetBridgeError, fleet_args.FleetArgsError)

    def test_direct_receiver_no_longer_imports_hermes_bridge(self) -> None:
        source = (ROOT / "tools/multi_position_sourcing/direct_receiver.py").read_text(
            encoding="utf-8")
        self.assertNotIn("hermes_fleet_bridge", source)

    def test_moved_parser_behavior_unchanged(self) -> None:
        from tools.multi_position_sourcing.fleet_args import FleetArgsError, parse_fleet_args
        options = parse_fleet_args("fleet-run", f"url:{CLICKUP_URL} skill:aisearch")
        self.assertEqual(options["skill"], "aisearch")
        with self.assertRaises(FleetArgsError):
            parse_fleet_args("fleet-run", "")


class CommandSurfaceTests(unittest.TestCase):
    def test_bot_console_commands_registered(self) -> None:
        names = {p["name"] for p in slash_commands_to_register()}
        for command in ("aisearch", "humansearch", "url", "login", "skill", "jobs"):
            self.assertIn(command, names)

    def test_direct_search_aliases_expose_engine_option(self) -> None:
        payloads = {p["name"]: p for p in slash_commands_to_register()}
        for command in ("aisearch", "humansearch", "url", "skill"):
            option_names = {o["name"] for o in payloads[command].get("options", [])}
            self.assertIn("engine", option_names, command)
            engine = next(o for o in payloads[command]["options"] if o["name"] == "engine")
            choices = {c["value"] for c in engine.get("choices", [])}
            self.assertEqual(choices, {"claude", "codex"})


class EngineSelectionEnvelopeTests(unittest.TestCase):
    def test_engine_unspecified_defaults_to_claude_label(self) -> None:
        envelope = interaction_to_envelope(
            _dm("aisearch", [{"name": "url", "value": CLICKUP_URL}]))
        assert envelope is not None
        self.assertIn("agent:claude", shlex.split(envelope.raw_args))

    def test_engine_codex_maps_to_agent_codex(self) -> None:
        envelope = interaction_to_envelope(
            _dm("aisearch", [{"name": "url", "value": CLICKUP_URL},
                             {"name": "engine", "value": "codex"}]))
        assert envelope is not None
        tokens = shlex.split(envelope.raw_args)
        self.assertIn("agent:codex", tokens)
        self.assertNotIn("agent:claude", tokens)

    def test_jobs_normalizes_to_fleet_status(self) -> None:
        envelope = interaction_to_envelope(_dm("jobs"))
        assert envelope is not None
        self.assertEqual(envelope.command, "fleet-status")

    def test_skill_command_maps_name_to_fixed_skill_token(self) -> None:
        envelope = interaction_to_envelope(
            _dm("skill", [{"name": "name", "value": "humansearch"},
                          {"name": "url", "value": CLICKUP_URL}]))
        assert envelope is not None
        self.assertEqual(envelope.command, "fleet-run")
        self.assertIn("skill:humansearch", shlex.split(envelope.raw_args))


class SlashBehaviorTests(_NotifySilencedCase):
    async def test_unauthorized_user_rejected_queue_untouched(self) -> None:
        queue = FakeQueue()
        result = await handle_slash_interaction(
            _dm("aisearch", [{"name": "url", "value": CLICKUP_URL}], user_id=STRANGER_ID),
            queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(queue.enqueued, [])
        self.assertIsNone(result["response"])

    async def test_unauthorized_channel_rejected(self) -> None:
        queue = FakeQueue()
        interaction = FakeInteraction(
            interaction_id="710000000000000002", user_id=OWNER_ID, command="aisearch",
            options=[{"name": "url", "value": CLICKUP_URL}],
            guild_id="888888888888888888", channel_id="777777777777777777")
        result = await handle_slash_interaction(
            interaction, queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True, allowed_channel_ids=("123456789012345678",)))
        self.assertEqual(queue.enqueued, [])
        self.assertIsNone(result["response"])

    async def test_same_event_id_twice_single_job(self) -> None:
        queue = FakeQueue()
        for _ in range(2):
            interaction = _dm("aisearch", [{"name": "url", "value": CLICKUP_URL}],
                              interaction_id="710000000000000003")
            result = await handle_slash_interaction(
                interaction, queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
            self.assertEqual(result["action"], "enqueued")
            self.assertIn("#1", interaction.sent[0]["content"])
        self.assertEqual(len(queue.enqueued), 1)

    async def test_engine_codex_reaches_queue_params(self) -> None:
        queue = FakeQueue()
        await handle_slash_interaction(
            _dm("aisearch", [{"name": "url", "value": CLICKUP_URL},
                             {"name": "engine", "value": "codex"}]),
            queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(queue.enqueued[0]["params"]["agent"], "codex")

    async def test_engine_unspecified_reaches_queue_as_claude(self) -> None:
        queue = FakeQueue()
        await handle_slash_interaction(
            _dm("aisearch", [{"name": "url", "value": CLICKUP_URL}]),
            queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(queue.enqueued[0]["params"]["agent"], "claude")

    async def test_engine_garbage_rejected_not_silent_claude(self) -> None:
        queue = FakeQueue()
        # "codex "(가장자리 공백)는 기존 파서의 strip 정규화로 codex 가 된다(허용 값으로의
        # 표준화지 다른 엔진으로의 조용한 폴백이 아님) — 내부 공백·대문자·미지 이름만 거부 대상.
        for bad in ("CODEX", "co dex", "gpt5"):
            interaction = _dm("aisearch", [{"name": "url", "value": CLICKUP_URL},
                                           {"name": "engine", "value": bad}])
            result = await handle_slash_interaction(
                interaction, queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
            self.assertEqual(queue.enqueued, [], bad)
            self.assertNotEqual(result["action"], "enqueued", bad)
            self.assertIsNotNone(result["response"], bad)

    async def test_invalid_urls_rejected(self) -> None:
        queue = FakeQueue()
        for bad in ("notaurl", "https://a b.com/x", "https://evil.com/\x07bell",
                    "ftp://files.example.com/x"):
            result = await handle_slash_interaction(
                _dm("aisearch", [{"name": "url", "value": bad}]),
                queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
            self.assertEqual(queue.enqueued, [], bad)
            self.assertNotEqual(result["action"], "enqueued", bad)

    async def test_queue_dead_replies_unavailable_not_swallowed(self) -> None:
        def failing_factory():
            raise RuntimeError("supabase down")

        interaction = _dm("aisearch", [{"name": "url", "value": CLICKUP_URL}])
        result = await handle_slash_interaction(
            interaction, queue_factory=failing_factory,
            authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(result["action"], "internal_error")
        self.assertEqual(len(interaction.sent), 1)
        self.assertIn("접수 불가", interaction.sent[0]["content"])

    async def test_skill_outside_whitelist_gets_friendly_rejection(self) -> None:
        queue = FakeQueue()
        interaction = _dm("skill", [{"name": "name", "value": "taxbill"},
                                    {"name": "url", "value": CLICKUP_URL}])
        result = await handle_slash_interaction(
            interaction, queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(queue.enqueued, [])
        self.assertNotEqual(result["action"], "enqueued")
        self.assertIn("아직 지원", interaction.sent[0]["content"])

    async def test_login_enqueues_queue_job(self) -> None:
        """스펙 전환(#188) — /login 은 '아직 지원 안 함' 안내가 아니라 큐 정식 잡이다.

        워커가 이 잡을 Codex 엔진으로 강제 실행하는 계약은
        tests/test_fleet_login_job.py 가 검사한다.
        """
        queue = FakeQueue()
        interaction = _dm("login", [{"name": "portal", "value": "saramin"}])
        result = await handle_slash_interaction(
            interaction, queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(result["action"], "enqueued")
        self.assertEqual(len(queue.enqueued), 1)
        self.assertEqual(queue.enqueued[0]["skill"], "login")
        self.assertEqual(queue.enqueued[0]["position_url"], "")

    async def test_login_from_stranger_stays_silent(self) -> None:
        queue = FakeQueue()
        interaction = _dm("login", [{"name": "portal", "value": "saramin"}],
                          user_id=STRANGER_ID)
        result = await handle_slash_interaction(
            interaction, queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
        self.assertIsNone(result["response"])
        self.assertEqual(interaction.sent[0]["content"], gw._GENERIC_SILENT_ACK)

    async def test_jobs_reply_includes_fleet_tab_link(self) -> None:
        queue = FakeQueue()
        interaction = _dm("jobs")
        result = await handle_slash_interaction(
            interaction, queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(result["action"], "status")
        self.assertIn(FLEET_TAB_URL, interaction.sent[0]["content"])


if __name__ == "__main__":
    unittest.main()
