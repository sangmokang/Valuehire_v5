"""U7 (AC-N4 마무리) — 게이트웨이에 자연어 경로를 **실제로 꽂는다**.

여기까지 U1~U6 가 만든 것은 전부 `message_to_envelope` 가 평문을 None 으로 버리는
한 죽은 코드다. 이 단위가 그 마지막 한 뼘을 잇는다.

이 저장소에서 같은 함정이 이미 두 번 났다 — `bot_intent.classify_free_text()` 도,
`guards/nl-shell-routing.py` 도 만들어만 두고 아무도 부르지 않아 잠들어 있었다.
그래서 이 테스트는 "함수가 있다"가 아니라 **"평문 메시지를 넣으면 큐로 간다"** 를 본다.

배선 방식(새 경로를 만들지 않는다): 자연어 → `plan_from_text` 가 만든
`/fleet-run …` 문자열 → **기존 파서에 다시 태운다**. 기존 명령 처리·인증·멱등이
그대로 적용된다.
"""

from __future__ import annotations

import asyncio
import unittest

from scripts.discord_direct_gateway import (
    handle_text_message, message_to_envelope, nl_plan_for_text,
)
from tools.multi_position_sourcing import nl_shell
from tools.multi_position_sourcing.access import DiscordAuthorizedUser
from tools.multi_position_sourcing.discord_routing import DiscordAccessConfig

from tests.test_discord_direct_gateway import FakeMessage  # 기존 픽스처 재사용

OWNER = "814353841088757800"
CU = "https://app.clickup.com/t/"


def _searcher(*hits):
    def search(locus, target):
        return [nl_shell.Candidate(n, u) for n, u in hits]
    return search


class FakeQueue:
    def __init__(self):
        self.enqueued: list[dict] = []

    def enqueue(self, payload):
        self.enqueued.append(payload)
        return {"id": 99, "status": "queued"}

    def recent(self, *a, **kw):
        return []


def _run(msg, queue, searcher):
    return asyncio.run(handle_text_message(
        msg, bot_user_id="123456789012345678", queue=queue,
        authorized_users=(DiscordAuthorizedUser(name="owner", alias="owner", email="o@v.kr", discord_id=OWNER),),
        config=DiscordAccessConfig(allow_dm=True),
        nl_searcher_factory=lambda: searcher,
    ))


class FreeTextReachesQueue(unittest.TestCase):
    """사장님이 DM 으로 친 한국어 한 줄이 실제로 잡이 된다 — 이 작업 전체의 목적."""

    def test_owner_sentence_becomes_a_job(self):
        queue = FakeQueue()
        msg = FakeMessage(message_id="1529267252160927272", author_id=OWNER,
                          content="클릭업에서 번개장터 PM 서치해")
        _run(msg, queue, _searcher(("PM(Core Product)", CU + "86exwz89j")))
        self.assertEqual(len(queue.enqueued), 1,
                         "평문이 큐에 도달하지 못했다 — 배선이 끊겨 있다")
        self.assertEqual(queue.enqueued[0]["skill"], "aisearch")
        self.assertEqual(queue.enqueued[0]["position_url"], CU + "86exwz89j")

    def test_idempotency_uses_discord_event_id(self):
        queue = FakeQueue()
        msg = FakeMessage(message_id="1529267252160927272", author_id=OWNER,
                          content="클릭업에서 번개장터 PM 서치해")
        _run(msg, queue, _searcher(("PM", CU + "86a")))
        params = queue.enqueued[0]["params"]
        self.assertIn("1529267252160927272", params.get("idempotency_key", ""))


class NotQueuedButAnswered(unittest.TestCase):
    """실행 안 하는 경우에도 **반드시 답한다** — 조용히 삼키면 먹힌 줄 모른다."""

    def test_many_candidates_answers_without_queueing(self):
        queue = FakeQueue()
        msg = FakeMessage(message_id="1529267252160927001", author_id=OWNER,
                          content="클릭업에서 번개장터 PM 서치해")
        _run(msg, queue, _searcher(("PM(Core)", CU + "86a"), ("PM(BD)", CU + "86b")))
        self.assertEqual(queue.enqueued, [], "고르기 전에 실행했다")
        self.assertIn("channel.send", msg.calls, "여러 건인데 아무 말도 안 했다")

    def test_zero_hits_answers_without_queueing(self):
        queue = FakeQueue()
        msg = FakeMessage(message_id="1529267252160927002", author_id=OWNER,
                          content="클릭업에서 없는회사 PM 서치해")
        _run(msg, queue, _searcher())
        self.assertEqual(queue.enqueued, [])
        self.assertIn("channel.send", msg.calls)


class ExistingBehaviourUnchanged(unittest.TestCase):
    """기존 명령·무시 정책이 그대로인지 — 회귀 방지."""

    def test_slash_style_command_still_works(self):
        queue = FakeQueue()
        msg = FakeMessage(message_id="1529267252160927003", author_id=OWNER,
                          content=f"/fleet-run aisearch {CU}86zzz")
        _run(msg, queue, _searcher())
        self.assertEqual(len(queue.enqueued), 1)

    def test_plain_chat_is_still_ignored(self):
        queue = FakeQueue()
        msg = FakeMessage(message_id="1529267252160927004", author_id=OWNER, content="고마워요")
        _run(msg, queue, _searcher())
        self.assertEqual(queue.enqueued, [])
        self.assertNotIn("channel.send", msg.calls, "잡담에 답해 소음을 만들었다")

    def test_unauthorized_dm_still_ignored(self):
        queue = FakeQueue()
        msg = FakeMessage(message_id="1529267252160927005", author_id="999999999999999999",
                          content="클릭업에서 번개장터 PM 서치해")
        asyncio.run(handle_text_message(
            msg, bot_user_id="123456789012345678", queue=queue,
            authorized_users=(), config=DiscordAccessConfig(allow_dm=True),
            nl_searcher_factory=lambda: _searcher(("PM", CU + "86a")),
        ))
        self.assertEqual(queue.enqueued, [], "미인가 사용자의 자연어가 실행됐다")

    def test_unauthorized_dm_gets_no_reply_either(self):
        """뮤턴트 생존으로 발견(2026-07-22) — 큐만 검사해서, 인가 검사를 통째로 지워도
        테스트가 통과했다. 실행이 안 되는 것과 **아무 응답도 안 하는 것**은 다르다.

        미인가 사용자에게 '못 찾았습니다' 같은 답을 돌려주면, 봇이 무엇을 알아듣는지·
        어떤 대상이 있는지 알려주는 정보 노출이 된다. 인가 전에는 침묵해야 한다.
        """
        queue = FakeQueue()
        msg = FakeMessage(message_id="1529267252160927006",
                          author_id="999999999999999999",
                          content="클릭업에서 없는회사 PM 서치해")
        asyncio.run(handle_text_message(
            msg, bot_user_id="123456789012345678", queue=queue,
            authorized_users=(), config=DiscordAccessConfig(allow_dm=True),
            nl_searcher_factory=lambda: _searcher(),
        ))
        self.assertEqual(queue.enqueued, [])
        self.assertNotIn("channel.send", msg.calls,
                         "미인가 사용자에게 응답해 봇 동작을 노출했다")


class PlanHelperIsExposed(unittest.TestCase):
    def test_nl_plan_for_text_returns_plan(self):
        plan = nl_plan_for_text("클릭업에서 번개장터 PM 서치해",
                                searcher=_searcher(("PM", CU + "86a")),
                                message_id="7")
        self.assertEqual(plan.action, "enqueue")

    def test_envelope_still_none_for_free_text(self):
        """message_to_envelope 는 순수 변환으로 남는다 — 자연어 판단을 섞지 않는다."""
        msg = FakeMessage(message_id="1529267252160927008", author_id=OWNER,
                          content="클릭업에서 번개장터 PM 서치해")
        self.assertIsNone(message_to_envelope(msg, bot_user_id="123456789012345678"))


class ClientForwardsSearcher(unittest.TestCase):
    """#200 — 운영 클라이언트가 nl_searcher_factory 를 on_message 로 전달해야 NL 이 산다."""

    def test_direct_gateway_client_stores_and_forwards_factory(self):
        from scripts.discord_direct_gateway import DirectGatewayClient
        sentinel = lambda: _searcher(("PM", CU + "86a"))
        client = DirectGatewayClient(
            authorized_users=(), config=DiscordAccessConfig(allow_dm=True),
            queue_factory=lambda: FakeQueue(),
            nl_searcher_factory=sentinel)
        # 저장돼 on_message 가 handle_text_message 로 넘길 수 있어야 한다.
        self.assertIs(client._nl_searcher_factory, sentinel)


if __name__ == "__main__":
    unittest.main()
