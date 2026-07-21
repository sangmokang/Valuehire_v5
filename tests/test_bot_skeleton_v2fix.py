"""AC-1 후속 — Codex V2 적대검증(NEEDS-FIX) 결함 봉인 (2026-07-22).

V2 findings → 수정 계약:
- C1(CRITICAL) 멱등키 스머글링: 호출자가 idempotency: 를 명시해도 디스코드 event_id
  키가 항상 이긴다 — 같은 event_id 는 어떤 입력으로도 잡 2개가 될 수 없다.
- M1 권한 확인 전 큐 접촉: 큐는 지연 생성(_LazyQueue) — 비인가/화이트리스트 거부
  경로에서는 queue_factory 가 아예 호출되지 않는다(운영 상태 비노출).
- M2 큐 장애 문구: 인가자에게는 생성 실패든 enqueue 실패든 "지금 접수 불가" 계열 회신.
- M3 빈/무효 engine: 명시된 agent 값이 빈 문자열이면 거부(조용한 미지정 취급 금지).
- m1 빈 /skill name → "아직 지원" 안내. m2 옵션 컨테이너 타입 오염 → 크래시 없이 침묵.
- m3 입력 길이 상한(8,000자) — 초과는 파싱 거부.
(URL 가장자리 공백 strip 은 표준화로 수용 — verdict 문서에 사유 기록.)
"""

from __future__ import annotations

import shlex
import unittest
from unittest.mock import patch

from scripts.discord_direct_gateway import (
    _GENERIC_SILENT_ACK,
    _with_discord_idempotency_key,
    handle_slash_interaction,
)
from tests.test_discord_bot_console_ac1 import (
    AUTHORIZED,
    CLICKUP_URL,
    CONFIG,
    FakeInteraction,
    FakeQueue,
    STRANGER_ID,
    _dm,
)
from tools.multi_position_sourcing.fleet_args import FleetArgsError, parse_fleet_args


class _NotifySilenced(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from tools.multi_position_sourcing import fleet_worker
        patcher = patch.object(fleet_worker, "discord_notify", lambda job, text: None)
        patcher.start()
        self.addCleanup(patcher.stop)


class IdempotencySmugglingTests(_NotifySilenced):
    def test_explicit_idempotency_cannot_override_event_key(self) -> None:
        raw = _with_discord_idempotency_key(
            "fleet-run", f"url:{CLICKUP_URL} idempotency:attacker-A", "710000000000000009")
        tokens = shlex.split(raw)
        self.assertIn("idempotency:discord:710000000000000009", tokens)
        self.assertNotIn("idempotency:attacker-A", tokens)

    async def test_same_event_with_different_explicit_keys_single_job(self) -> None:
        queue = FakeQueue()
        for smuggled in ("attacker-A", "attacker-B"):
            interaction = _dm(
                "fleet-run",
                [{"name": "url", "value": CLICKUP_URL},
                 {"name": "idempotency", "value": smuggled}],
                interaction_id="710000000000000010")
            await handle_slash_interaction(
                interaction, queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(len(queue.enqueued), 1)


class LazyQueueTests(_NotifySilenced):
    async def test_unauthorized_never_touches_queue_factory(self) -> None:
        calls = []

        def factory():
            calls.append(1)
            raise RuntimeError("죽은 큐")

        interaction = _dm("aisearch", [{"name": "url", "value": CLICKUP_URL}],
                          user_id=STRANGER_ID)
        result = await handle_slash_interaction(
            interaction, queue_factory=factory,
            authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(calls, [], "비인가 경로에서 큐 생성기가 호출되면 안 됨")
        self.assertIsNone(result["response"])
        self.assertEqual(interaction.sent[0]["content"], _GENERIC_SILENT_ACK)

    async def test_whitelist_rejection_never_touches_queue_factory(self) -> None:
        calls = []

        def factory():
            calls.append(1)
            raise RuntimeError("죽은 큐")

        interaction = _dm("skill", [{"name": "name", "value": "taxbill"},
                                    {"name": "url", "value": CLICKUP_URL}])
        await handle_slash_interaction(
            interaction, queue_factory=factory,
            authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(calls, [], "화이트리스트 거부 경로에서 큐 생성 금지")
        self.assertIn("아직 지원", interaction.sent[0]["content"])

    async def test_enqueue_failure_replies_unavailable(self) -> None:
        class DeadQueue:
            def enqueue(self, payload):
                raise RuntimeError("supabase down")

        interaction = _dm("aisearch", [{"name": "url", "value": CLICKUP_URL}])
        result = await handle_slash_interaction(
            interaction, queue=DeadQueue(),
            authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(result["action"], "internal_error")
        self.assertIn("접수 불가", interaction.sent[0]["content"])

    async def test_factory_failure_replies_unavailable_to_authorized(self) -> None:
        def factory():
            raise RuntimeError("supabase down")

        interaction = _dm("aisearch", [{"name": "url", "value": CLICKUP_URL}])
        result = await handle_slash_interaction(
            interaction, queue_factory=factory,
            authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(result["action"], "internal_error")
        self.assertIn("접수 불가", interaction.sent[0]["content"])


class EngineValueTests(_NotifySilenced):
    def test_parse_rejects_explicit_empty_agent(self) -> None:
        with self.assertRaises(FleetArgsError):
            parse_fleet_args("fleet-run", f"url:{CLICKUP_URL} agent:")

    async def test_empty_engine_option_rejected_not_silently_unspecified(self) -> None:
        queue = FakeQueue()
        interaction = _dm("aisearch", [{"name": "url", "value": CLICKUP_URL},
                                       {"name": "engine", "value": ""}])
        result = await handle_slash_interaction(
            interaction, queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(queue.enqueued, [])
        self.assertNotEqual(result["action"], "enqueued")
        self.assertIsNotNone(result["response"])


class MalformedInputTests(_NotifySilenced):
    async def test_empty_skill_name_gets_friendly_rejection(self) -> None:
        queue = FakeQueue()
        interaction = _dm("skill", [{"name": "name", "value": ""},
                                    {"name": "url", "value": CLICKUP_URL}])
        await handle_slash_interaction(
            interaction, queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(queue.enqueued, [])
        self.assertIn("아직 지원", interaction.sent[0]["content"])

    async def test_options_container_type_pollution_no_crash(self) -> None:
        queue = FakeQueue()
        interaction = FakeInteraction(
            interaction_id="710000000000000011", user_id=STRANGER_ID,
            command="aisearch")
        interaction.data = {"name": "aisearch", "options": "garbage-not-a-list"}
        result = await handle_slash_interaction(
            interaction, queue=queue, authorized_users=AUTHORIZED, config=CONFIG)
        self.assertEqual(queue.enqueued, [])
        self.assertIsNone(result["response"])
        self.assertEqual(len(interaction.sent), 1)

    def test_parse_rejects_oversized_raw_args(self) -> None:
        with self.assertRaises(FleetArgsError):
            parse_fleet_args("fleet-run", f"url:{CLICKUP_URL} " + "x" * 8001)


if __name__ == "__main__":
    unittest.main()
