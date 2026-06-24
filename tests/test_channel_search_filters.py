"""슬라이스 B — 사람인/잡코리아 검색필터를 라이브 keyword_plan 에 주입.

goal: docs/engineering/linkedin-boolean-live-wire-goal-2026-06-24.md §5.5 계약

계약(SDD):
  saramin  → filters["saramin_search"] = {"and": [...], "or": [...], "not": ["신입","인턴","프리랜서"]}
  jobkorea → filters["jobkorea_chips"] = ["엄선 키워드", ...]  (OR 누적)
  linkedin → filters["boolean_query"]  (슬라이스 A, 회귀 없어야)

불변식: 채널 격리(키 안 섞임) / not 기본값 강제 / 연차·지역 안 섞임 / 빈 생성은 에러 / 원본 비변형.
"""

from __future__ import annotations

import json
import unittest

from tools.multi_position_sourcing.dry_run import build_dry_run_payload
from tools.multi_position_sourcing.fixtures import SAMPLE_POSITIONS
from tools.multi_position_sourcing.grouping import group_positions
from tools.multi_position_sourcing.keywords import build_keyword_plan
from tools.multi_position_sourcing.llm_keywords import (
    DEFAULT_SARAMIN_EXCLUDE,
    KeywordGenerationError,
    generate_saramin_search,
    inject_channel_search_filters,
)
from tools.multi_position_sourcing.models import BOOLEAN_CHANNELS

_KW = ["AI 엔지니어", "AI Engineer", "ML Engineer"]
_AND = ["PyTorch"]
_OR = ["AI 엔지니어", "ML 엔지니어", "머신러닝 엔지니어"]
_XRAY = '("AI Engineer" OR "ML Engineer") AND ("PyTorch" OR "TensorFlow")'


def _fake_llm(prompt: str) -> str:
    """결정론 가짜 LLM — keywords/boolean_query/and/or 를 모두 담아 반환(프롬프트 무관)."""
    return json.dumps(
        {"keywords": _KW, "boolean_query": _XRAY, "and": _AND, "or": _OR}
    )


def _fake_llm_no_split(prompt: str) -> str:
    """and/or 분리를 안 주는 LLM — or 는 keywords 로 폴백돼야(슬라이스 A 호환)."""
    return json.dumps({"keywords": _KW, "boolean_query": _XRAY})


def _empty_llm(prompt: str) -> str:
    return ""


def _blank_keywords_llm(prompt: str) -> str:
    """JSON 은 멀쩡하지만 유효 키워드가 0개 — or 폴백도 비어 0건 검색 위험."""
    return json.dumps({"keywords": [], "or": []})


def _rep():
    return SAMPLE_POSITIONS[0]


def _sessions():
    group = group_positions(SAMPLE_POSITIONS)[0]
    return build_keyword_plan(group)


class SaraminSearchTest(unittest.TestCase):
    def test_saramin_session_gets_and_or_not(self) -> None:
        injected = inject_channel_search_filters(_sessions(), _rep(), llm_client=_fake_llm)
        saramin = [s for s in injected if s.channel == "saramin"]
        self.assertTrue(saramin, "픽스처에 saramin 세션이 있어야 한다")
        for s in saramin:
            search = s.filters.get("saramin_search")
            self.assertIsNotNone(search, "saramin 세션에 saramin_search 가 실려야 한다")
            self.assertEqual(list(search["and"]), _AND)
            self.assertEqual(list(search["or"]), _OR)
            self.assertEqual(list(search["not"]), list(DEFAULT_SARAMIN_EXCLUDE))

    def test_not_defaults_even_if_llm_omits(self) -> None:
        search = generate_saramin_search(_rep(), llm_client=_fake_llm_no_split)
        self.assertEqual(list(search["not"]), list(DEFAULT_SARAMIN_EXCLUDE))
        # or 는 keywords 로 폴백(비어서 0건 검색 나지 않게)
        self.assertEqual(list(search["or"]), _KW)

    def test_empty_llm_propagates(self) -> None:
        with self.assertRaises(KeywordGenerationError):
            generate_saramin_search(_rep(), llm_client=_empty_llm)

    def test_blank_keywords_propagate(self) -> None:
        """JSON 정상이어도 유효 키워드 0개면 에러 — or 폴백이 빈 통과 못 하게(MUTANT 방어)."""
        with self.assertRaises(KeywordGenerationError):
            generate_saramin_search(_rep(), llm_client=_blank_keywords_llm)


class JobkoreaChipsTest(unittest.TestCase):
    def test_jobkorea_session_gets_chips(self) -> None:
        injected = inject_channel_search_filters(_sessions(), _rep(), llm_client=_fake_llm)
        jobkorea = [s for s in injected if s.channel == "jobkorea"]
        self.assertTrue(jobkorea, "픽스처에 jobkorea 세션이 있어야 한다")
        for s in jobkorea:
            chips = s.filters.get("jobkorea_chips")
            self.assertEqual(list(chips), _KW, "잡코리아 칩 = 엄선 키워드 리스트(OR)")


class ChannelIsolationTest(unittest.TestCase):
    """채널 격리 — 한 채널 검색식이 다른 채널 filters 로 새면 안 된다."""

    def test_keys_do_not_cross_channels(self) -> None:
        injected = inject_channel_search_filters(_sessions(), _rep(), llm_client=_fake_llm)
        for s in injected:
            if s.channel == "saramin":
                self.assertNotIn("boolean_query", s.filters)
                self.assertNotIn("jobkorea_chips", s.filters)
            elif s.channel == "jobkorea":
                self.assertNotIn("boolean_query", s.filters)
                self.assertNotIn("saramin_search", s.filters)
            elif s.channel in BOOLEAN_CHANNELS:
                self.assertNotIn("saramin_search", s.filters)
                self.assertNotIn("jobkorea_chips", s.filters)
                self.assertEqual(s.filters.get("boolean_query"), _XRAY)

    def test_does_not_mutate_input_sessions(self) -> None:
        sessions = _sessions()
        inject_channel_search_filters(sessions, _rep(), llm_client=_fake_llm)
        for s in sessions:
            self.assertNotIn("saramin_search", s.filters)
            self.assertNotIn("jobkorea_chips", s.filters)
            self.assertNotIn("boolean_query", s.filters)


class DryRunWiringTest(unittest.TestCase):
    """라이브 큐 진입점(build_dry_run_payload)이 채널 검색필터를 큐에 싣는가."""

    def _filters_by_channel(self, payload):
        out: dict[str, list] = {}
        for item in payload["queue_cycle_summary"]["updated_items"]:
            for s in item["keyword_plan"]:
                out.setdefault(item["channel"], []).append(s["filters"])
        return out

    def test_with_llm_client_injects_saramin_and_jobkorea(self) -> None:
        payload = build_dry_run_payload(llm_client=_fake_llm)
        fbc = self._filters_by_channel(payload)
        self.assertTrue(all("saramin_search" in f for f in fbc["saramin"]))
        self.assertTrue(all("jobkorea_chips" in f for f in fbc["jobkorea"]))
        # 격리: 평문 채널에 boolean_query 안 섞임
        for plain in ("saramin", "jobkorea"):
            self.assertTrue(all("boolean_query" not in f for f in fbc[plain]))

    def test_without_llm_client_keeps_plan_unchanged(self) -> None:
        payload = build_dry_run_payload()
        fbc = self._filters_by_channel(payload)
        for ch, filters_list in fbc.items():
            for f in filters_list:
                self.assertNotIn("saramin_search", f)
                self.assertNotIn("jobkorea_chips", f)


if __name__ == "__main__":
    unittest.main()
