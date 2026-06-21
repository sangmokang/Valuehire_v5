from __future__ import annotations

import unittest

from tools.multi_position_sourcing.llm_keywords import (
    KeywordGenerationError,
    LLMKeywordPlan,
    build_llm_keyword_sessions,
    build_llm_queue_items,
    generate_keyword_plan,
)
from tools.multi_position_sourcing.models import KeywordSession, Position, QueueItem

_JD = (
    "우리는 LLM 기반 추천 시스템을 상용화할 AI 엔지니어를 찾습니다. "
    "PyTorch, RAG, 모델 서빙(MLOps) 경험 필수. 네이버/카카오 등 대규모 트래픽 경험 우대."
)
_POSITION = Position(
    position_id="p-1",
    company_name="매드업",
    role_title="AI Engineer",
    jd_text=_JD,
    must_haves=("PyTorch", "LLM", "모델 서빙"),
)


def _client_returning(payload: str):
    """Fake LLM client that records the prompt and returns a fixed payload."""

    captured: dict[str, str] = {}

    def _call(prompt: str) -> str:
        captured["prompt"] = prompt
        return payload

    _call.captured = captured  # type: ignore[attr-defined]
    return _call


_GOOD_JSON = (
    '{"keywords": ["AI 엔지니어", "Machine Learning Engineer", "LLM", "RAG"], '
    '"boolean_query": "(\\"AI Engineer\\" OR \\"ML Engineer\\") AND (PyTorch OR RAG)"}'
)


class TestLLMKeywordGeneration(unittest.TestCase):
    def test_prompt_includes_jd_text_and_role(self) -> None:
        client = _client_returning(_GOOD_JSON)
        generate_keyword_plan(_POSITION, "linkedin_rps", llm_client=client)
        prompt = client.captured["prompt"]  # type: ignore[attr-defined]
        # 키워드는 하드코딩 표가 아니라 JD 원문을 LLM에 넘겨 뽑아야 한다.
        self.assertIn("LLM 기반 추천 시스템", prompt)
        self.assertIn("AI Engineer", prompt)

    def test_prompt_asks_for_bilingual_keywords(self) -> None:
        client = _client_returning(_GOOD_JSON)
        generate_keyword_plan(_POSITION, "saramin", llm_client=client)
        prompt = client.captured["prompt"]  # type: ignore[attr-defined]
        self.assertIn("국문", prompt)
        self.assertIn("영문", prompt)

    def test_parses_keywords_from_llm_response(self) -> None:
        plan = generate_keyword_plan(_POSITION, "linkedin_rps", llm_client=_client_returning(_GOOD_JSON))
        self.assertIsInstance(plan, LLMKeywordPlan)
        self.assertEqual(
            plan.keywords,
            ("AI 엔지니어", "Machine Learning Engineer", "LLM", "RAG"),
        )

    def test_linkedin_channel_keeps_boolean_query(self) -> None:
        plan = generate_keyword_plan(_POSITION, "linkedin_rps", llm_client=_client_returning(_GOOD_JSON))
        self.assertIn("OR", plan.boolean_query)
        self.assertIn("AND", plan.boolean_query)

    def test_saramin_channel_has_no_boolean_query(self) -> None:
        # 사람인/잡코리아 인재검색 필드의 AND/OR 지원은 미검증 → 평문 키워드만.
        plan = generate_keyword_plan(_POSITION, "saramin", llm_client=_client_returning(_GOOD_JSON))
        self.assertEqual(plan.boolean_query, "")
        self.assertTrue(plan.keywords)

    def test_keywords_deduped_preserving_order(self) -> None:
        payload = '{"keywords": ["LLM", "LLM", "RAG", "  LLM  ", "RAG"], "boolean_query": ""}'
        plan = generate_keyword_plan(_POSITION, "jobkorea", llm_client=_client_returning(payload))
        self.assertEqual(plan.keywords, ("LLM", "RAG"))

    def test_empty_response_raises(self) -> None:
        with self.assertRaises(KeywordGenerationError):
            generate_keyword_plan(_POSITION, "saramin", llm_client=_client_returning("   "))

    def test_garbage_response_raises(self) -> None:
        with self.assertRaises(KeywordGenerationError):
            generate_keyword_plan(_POSITION, "saramin", llm_client=_client_returning("죄송합니다 모르겠어요"))

    def test_no_keywords_in_json_raises(self) -> None:
        # JSON은 맞지만 키워드가 비면 0건 검색의 원인 → 조용히 통과시키지 않는다.
        with self.assertRaises(KeywordGenerationError):
            generate_keyword_plan(_POSITION, "saramin", llm_client=_client_returning('{"keywords": [], "boolean_query": ""}'))


class TestBuildLLMKeywordSessions(unittest.TestCase):
    def test_one_session_per_keyword_for_single_channel(self) -> None:
        sessions = build_llm_keyword_sessions(
            _POSITION, channels=("saramin",), llm_client=_client_returning(_GOOD_JSON)
        )
        self.assertTrue(all(isinstance(s, KeywordSession) for s in sessions))
        self.assertEqual(
            tuple(s.standard_keyword for s in sessions),
            ("AI 엔지니어", "Machine Learning Engineer", "LLM", "RAG"),
        )
        self.assertTrue(all(s.channel == "saramin" for s in sessions))

    def test_covers_all_requested_channels(self) -> None:
        sessions = build_llm_keyword_sessions(
            _POSITION,
            channels=("saramin", "linkedin_rps"),
            llm_client=_client_returning(_GOOD_JSON),
        )
        self.assertEqual({s.channel for s in sessions}, {"saramin", "linkedin_rps"})

    def test_boolean_query_carried_in_filters_for_linkedin(self) -> None:
        sessions = build_llm_keyword_sessions(
            _POSITION, channels=("linkedin_rps",), llm_client=_client_returning(_GOOD_JSON)
        )
        self.assertTrue(sessions)
        for s in sessions:
            self.assertIn("AND", s.filters.get("boolean_query", ""))

    def test_saramin_sessions_have_no_boolean_query_filter(self) -> None:
        sessions = build_llm_keyword_sessions(
            _POSITION, channels=("saramin",), llm_client=_client_returning(_GOOD_JSON)
        )
        self.assertTrue(sessions)
        for s in sessions:
            self.assertEqual(s.filters.get("boolean_query", ""), "")

    def test_generation_error_propagates(self) -> None:
        # 한 채널이라도 키워드를 못 뽑으면 조용히 건너뛰지 않고 에러(0건 검색 방지).
        with self.assertRaises(KeywordGenerationError):
            build_llm_keyword_sessions(
                _POSITION, channels=("saramin",), llm_client=_client_returning("   ")
            )


class TestBuildLLMQueueItems(unittest.TestCase):
    def test_one_queue_item_per_channel(self) -> None:
        items = build_llm_queue_items(
            _POSITION, channels=("saramin", "jobkorea"), llm_client=_client_returning(_GOOD_JSON)
        )
        self.assertTrue(all(isinstance(it, QueueItem) for it in items))
        self.assertEqual(tuple(it.channel for it in items), ("saramin", "jobkorea"))

    def test_queue_item_keyword_plan_is_channel_scoped(self) -> None:
        items = build_llm_queue_items(
            _POSITION, channels=("saramin", "linkedin_rps"), llm_client=_client_returning(_GOOD_JSON)
        )
        for it in items:
            self.assertTrue(it.keyword_plan)  # 비어있지 않음(0건 방지)
            self.assertTrue(all(s.channel == it.channel for s in it.keyword_plan))

    def test_queue_item_group_id_traces_position(self) -> None:
        items = build_llm_queue_items(
            _POSITION, channels=("saramin",), llm_client=_client_returning(_GOOD_JSON)
        )
        self.assertIn(_POSITION.position_id, items[0].group_id)

    def test_queue_item_starts_pending(self) -> None:
        items = build_llm_queue_items(
            _POSITION, channels=("saramin",), llm_client=_client_returning(_GOOD_JSON)
        )
        self.assertEqual(items[0].status, "pending")

    def test_generation_error_propagates(self) -> None:
        with self.assertRaises(KeywordGenerationError):
            build_llm_queue_items(
                _POSITION, channels=("saramin",), llm_client=_client_returning("   ")
            )


if __name__ == "__main__":
    unittest.main()
