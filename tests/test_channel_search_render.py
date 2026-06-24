"""슬라이스 B 소비측 — 큐에 실린 채널 검색필터를 '실제 입력 계획'으로 변환(고아 해소).

V2 적대검증이 잡은 결함: inject 가 심은 saramin_search/jobkorea_chips 를 읽는 소비측이 없었다
(boolean_query 만 _query_for_session 이 소비). 이 테스트는 그 소비측(render_search_for_session)을
요구한다 — 라이브 브라우저 렌더러가 호출할, 채널별 구체 입력 계획을 내는 순수함수.

end-to-end: 생성(LLM) → inject(큐 주입) → render(입력 계획) 까지 객체로 단언(브라우저 없음).
"""

from __future__ import annotations

import json
import unittest

from tools.multi_position_sourcing.fixtures import SAMPLE_POSITIONS
from tools.multi_position_sourcing.grouping import group_positions
from tools.multi_position_sourcing.keywords import build_keyword_plan
from tools.multi_position_sourcing.llm_keywords import (
    DEFAULT_SARAMIN_EXCLUDE,
    inject_channel_search_filters,
)
from tools.multi_position_sourcing.channel_search_render import render_search_for_session

_KW = ["AI 엔지니어", "AI Engineer", "ML Engineer"]
_AND = ["PyTorch"]
_OR = ["AI 엔지니어", "ML 엔지니어", "머신러닝 엔지니어"]
_XRAY = '("AI Engineer" OR "ML Engineer") AND ("PyTorch" OR "TensorFlow")'


def _fake_llm(prompt: str) -> str:
    return json.dumps({"keywords": _KW, "boolean_query": _XRAY, "and": _AND, "or": _OR})


def _injected():
    sessions = build_keyword_plan(group_positions(SAMPLE_POSITIONS)[0])
    return inject_channel_search_filters(sessions, SAMPLE_POSITIONS[0], llm_client=_fake_llm)


class RenderTest(unittest.TestCase):
    def test_saramin_renders_field_inputs(self) -> None:
        s = next(x for x in _injected() if x.channel == "saramin")
        plan = render_search_for_session(s)
        self.assertEqual(plan["kind"], "fields")
        self.assertEqual(plan["include"], _AND)               # AND 칸
        self.assertEqual(plan["default"], _OR)                # OR 칸
        self.assertEqual(plan["exclude"], list(DEFAULT_SARAMIN_EXCLUDE))  # NOT 칸

    def test_jobkorea_renders_chip_sequence(self) -> None:
        s = next(x for x in _injected() if x.channel == "jobkorea")
        plan = render_search_for_session(s)
        self.assertEqual(plan["kind"], "chips")
        self.assertEqual(plan["chips"], _KW)                  # 칩 입력 순서(OR)

    def test_linkedin_renders_boolean_keyword(self) -> None:
        s = next(x for x in _injected() if x.channel == "linkedin_rps")
        plan = render_search_for_session(s)
        self.assertEqual(plan["kind"], "keyword")
        self.assertEqual(plan["value"], _XRAY)                # boolean_query 가 검색어로

    def test_saramin_without_filter_falls_back_to_keyword(self) -> None:
        """saramin_search 가 없으면(주입 안 된 세션) standard_keyword 로 폴백 — 깨지지 않게."""
        sessions = build_keyword_plan(group_positions(SAMPLE_POSITIONS)[0])
        s = next(x for x in sessions if x.channel == "saramin")
        plan = render_search_for_session(s)
        self.assertEqual(plan["kind"], "keyword")
        self.assertEqual(plan["value"], s.standard_keyword)


if __name__ == "__main__":
    unittest.main()
