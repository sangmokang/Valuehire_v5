"""슬라이스 A — LLM boolean_query 를 라이브 keyword_plan 에 주입.

goal: docs/engineering/linkedin-boolean-live-wire-goal-2026-06-24.md

AC(EARS): If 라이브 검색이 boolean 채널(linkedin_rps/public_web) 포지션을 처리하면,
then 그 KeywordSession.filters['boolean_query'] 는 LLM 이 생성한 비어있지 않은 X-ray
쿼리여야 한다. 평문 채널(saramin/jobkorea)에는 절대 주입되면 안 된다.

PR#31 소비측(`_query_for_session`)까지 end-to-end 로, boolean_query 가 실제 검색어로
채택되는지 단언한다(브라우저 발송 아님 — URL 조립 직전 검색어까지).
"""

from __future__ import annotations

import json
import unittest

from tools.multi_position_sourcing.dry_run import build_dry_run_payload
from tools.multi_position_sourcing.fixtures import SAMPLE_POSITIONS
from tools.multi_position_sourcing.llm_keywords import (
    KeywordGenerationError,
    inject_boolean_queries,
)
from tools.multi_position_sourcing.models import BOOLEAN_CHANNELS
from tools.multi_position_sourcing.portal_queue_executor import _query_for_session
from tools.multi_position_sourcing.grouping import group_positions
from tools.multi_position_sourcing.keywords import build_keyword_plan

_XRAY = '("AI Engineer" OR "ML Engineer") AND ("PyTorch" OR "TensorFlow")'


def _fake_llm(prompt: str) -> str:
    """결정론 가짜 LLM — 항상 키워드 + X-ray 를 반환(채널 무관).

    generate_keyword_plan 이 평문 채널에서는 boolean_query 를 버리므로, 평문에 새는지
    여부는 '가짜가 항상 줘도 평문엔 안 들어간다'로 검증된다.
    """
    return json.dumps({"keywords": ["AI 엔지니어", "AI Engineer"], "boolean_query": _XRAY})


def _empty_llm(prompt: str) -> str:
    return ""  # 빈 응답 → KeywordGenerationError 유발해야 함


class InjectBooleanQueriesUnitTest(unittest.TestCase):
    def _rep_position(self):
        return SAMPLE_POSITIONS[0]

    def test_boolean_channel_sessions_get_xray_query(self) -> None:
        group = group_positions(SAMPLE_POSITIONS)[0]
        sessions = build_keyword_plan(group)
        injected = inject_boolean_queries(sessions, self._rep_position(), llm_client=_fake_llm)
        boolean_sessions = [s for s in injected if s.channel in BOOLEAN_CHANNELS]
        self.assertTrue(boolean_sessions, "픽스처에 boolean 채널 세션이 있어야 한다")
        for s in boolean_sessions:
            self.assertEqual(
                s.filters.get("boolean_query"), _XRAY,
                msg=f"{s.channel} 세션에 X-ray boolean_query 가 실려야 한다",
            )

    def test_plain_channels_never_get_boolean_query(self) -> None:
        group = group_positions(SAMPLE_POSITIONS)[0]
        sessions = build_keyword_plan(group)
        injected = inject_boolean_queries(sessions, self._rep_position(), llm_client=_fake_llm)
        for s in injected:
            if s.channel not in BOOLEAN_CHANNELS:
                self.assertNotIn(
                    "boolean_query", s.filters,
                    msg=f"평문 채널 {s.channel} 에 boolean_query 가 새면 안 된다",
                )

    def test_llm_failure_propagates_not_swallowed(self) -> None:
        group = group_positions(SAMPLE_POSITIONS)[0]
        sessions = build_keyword_plan(group)
        with self.assertRaises(KeywordGenerationError):
            inject_boolean_queries(sessions, self._rep_position(), llm_client=_empty_llm)

    def test_does_not_mutate_input_sessions(self) -> None:
        group = group_positions(SAMPLE_POSITIONS)[0]
        sessions = build_keyword_plan(group)
        inject_boolean_queries(sessions, self._rep_position(), llm_client=_fake_llm)
        for s in sessions:
            self.assertNotIn(
                "boolean_query", s.filters,
                msg="원본 세션의 공유 filters 를 변형하면 안 된다(다른 그룹 오염)",
            )


class BooleanQueryReachesExecutorTest(unittest.TestCase):
    """주입된 boolean_query 가 PR#31 소비측 검색어 선택까지 도달하는가(end-to-end)."""

    def test_query_for_session_uses_injected_boolean_query(self) -> None:
        group = group_positions(SAMPLE_POSITIONS)[0]
        sessions = build_keyword_plan(group)
        injected = inject_boolean_queries(sessions, SAMPLE_POSITIONS[0], llm_client=_fake_llm)
        boolean_sessions = [s for s in injected if s.channel in BOOLEAN_CHANNELS]
        for s in boolean_sessions:
            self.assertEqual(
                _query_for_session(s), _XRAY,
                msg=f"{s.channel}: executor 가 boolean_query 를 검색어로 채택해야 한다",
            )


class DryRunLiveWireTest(unittest.TestCase):
    """라이브 큐 진입점(dry_run)이 llm_client 를 받으면 boolean_query 를 큐에 싣는가."""

    def _boolean_query_set(self, payload):
        items = payload["queue_cycle_summary"]["updated_items"]
        out = {}
        for item in items:
            for s in item["keyword_plan"]:
                bq = s["filters"].get("boolean_query")
                if bq:
                    out.setdefault(item["channel"], set()).add(bq)
        return out

    def test_with_llm_client_injects_boolean_query_into_boolean_channels(self) -> None:
        payload = build_dry_run_payload(llm_client=_fake_llm)
        bq = self._boolean_query_set(payload)
        for ch in BOOLEAN_CHANNELS:
            self.assertIn(ch, bq, msg=f"{ch} 큐 항목에 boolean_query 가 실려야 한다")
            self.assertIn(_XRAY, bq[ch])
        for plain in ("saramin", "jobkorea"):
            self.assertNotIn(plain, bq, msg=f"평문 {plain} 에 boolean_query 가 새면 안 된다")

    def test_without_llm_client_keeps_native_plan_unchanged(self) -> None:
        """기존 호출(인자 없음)은 그대로 — boolean_query 주입 없음(512 회귀 방지)."""
        payload = build_dry_run_payload()
        bq = self._boolean_query_set(payload)
        self.assertEqual(bq, {}, msg="llm_client 없으면 boolean_query 가 전혀 없어야 한다")


class BooleanQueryReachesLinkedInUrlTest(unittest.TestCase):
    """라이브 1건 실증(L3) — boolean_query 가 LinkedIn searchKeyword URL 까지 인코딩.

    브라우저 발송 없음: 가짜 page 가 goto(url) 의 url 만 포착한다(R3 발송금지 준수).
    생성→executor 검색어 선택→URL 조립까지 런타임 추적.
    """

    def test_boolean_query_encoded_into_linkedin_searchkeyword(self) -> None:
        import asyncio
        from urllib.parse import quote

        from tools.multi_position_sourcing.portal_worker import _goto_search_surface

        group = group_positions(SAMPLE_POSITIONS)[0]
        sessions = build_keyword_plan(group)
        injected = inject_boolean_queries(sessions, SAMPLE_POSITIONS[0], llm_client=_fake_llm)
        linkedin_session = next(s for s in injected if s.channel == "linkedin_rps")
        keyword = _query_for_session(linkedin_session)
        self.assertEqual(keyword, _XRAY, "executor 가 boolean_query 를 검색어로 골라야 한다")

        captured: dict[str, str] = {}

        class _FakePage:
            async def goto(self, url, **kwargs):  # noqa: ANN001
                captured["url"] = url
            # wait_for_timeout 속성 없음 → 대기 스킵(발송/네트워크 없음)

        asyncio.run(_goto_search_surface(_FakePage(), "linkedin_rps", keyword))
        self.assertIn("searchKeyword=", captured["url"])
        self.assertIn(quote(_XRAY), captured["url"], "X-ray 쿼리가 URL 인코딩돼 들어가야 한다")
        # 평문 표준키워드가 아니라 boolean_query 가 들어갔음을 교차 확인
        self.assertNotEqual(keyword, linkedin_session.standard_keyword)


if __name__ == "__main__":
    unittest.main()
