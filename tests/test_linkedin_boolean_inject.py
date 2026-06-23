"""RED→GREEN — LinkedIn 검색창에 Boolean 검색식이 실제로 도달하는가.

구멍: ``llm_keywords`` 가 ``filters['boolean_query']`` 에 X-ray 쿼리를 실어 나르지만,
``portal_queue_executor.keywords_for_item`` 이 ``standard_keyword`` 만 꺼내며 그것을 버린다.
그래서 boolean_query 가 LinkedIn ``searchKeyword=`` 까지 도달하지 못한다(부분 고아).

AC1: boolean 채널(linkedin_rps/public_web) + 비어있지 않은 boolean_query → 검색어로 boolean_query.
AC2: boolean 채널용 LLM 프롬프트는 연차·지역·OTW 제외 + Title+Skill+Domain만 지시.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.llm_keywords import _build_prompt
from tools.multi_position_sourcing.models import KeywordSession, QueueItem
from tools.multi_position_sourcing.portal_queue_executor import keywords_for_item

BOOL_Q = '("Backend Engineer") AND ("Kafka" OR "Spark") AND ("fintech" OR "핀테크")'


def _item(channel, sessions) -> QueueItem:
    return QueueItem(group_id="g1", channel=channel, keyword_plan=tuple(sessions), status="pending")


class _FakePosition:
    company_name = "밸류커넥트"
    role_title = "Backend Engineer"
    must_haves = ("Java", "Kafka")
    nice_to_haves = ("fintech",)
    jd_text = "백엔드 개발자 채용. 경력 5년 이상, 서울 근무."


class BooleanInjectionTest(unittest.TestCase):
    def test_ac1_linkedin_session_yields_boolean_query(self) -> None:
        """boolean 채널 + boolean_query 있으면 검색어로 그 boolean_query 가 나와야 한다."""
        item = _item(
            "linkedin_rps",
            [
                KeywordSession(
                    channel="linkedin_rps",
                    standard_keyword="Backend Engineer",
                    filters={"boolean_query": BOOL_Q},
                )
            ],
        )
        self.assertEqual(keywords_for_item(item), (BOOL_Q,))

    def test_ac1_public_web_also_uses_boolean_query(self) -> None:
        item = _item(
            "public_web",
            [
                KeywordSession(
                    channel="public_web",
                    standard_keyword="site:linkedin.com/in Backend Korea",
                    filters={"boolean_query": BOOL_Q},
                )
            ],
        )
        self.assertEqual(keywords_for_item(item), (BOOL_Q,))

    def test_ac1_counter_plain_channel_keeps_standard_keyword(self) -> None:
        """평문 채널(saramin)은 boolean_query 가 있어도 standard_keyword 를 지켜야 한다(AND/OR 미지원)."""
        item = _item(
            "saramin",
            [
                KeywordSession(
                    channel="saramin",
                    standard_keyword="백엔드 개발자",
                    filters={"boolean_query": BOOL_Q},
                )
            ],
        )
        self.assertEqual(keywords_for_item(item), ("백엔드 개발자",))

    def test_ac1_counter_empty_boolean_query_falls_back(self) -> None:
        """boolean_query 가 비면 standard_keyword 로 폴백(0건 검색 방지)."""
        item = _item(
            "linkedin_rps",
            [
                KeywordSession(
                    channel="linkedin_rps",
                    standard_keyword="Backend Engineer",
                    filters={"boolean_query": ""},
                )
            ],
        )
        self.assertEqual(keywords_for_item(item), ("Backend Engineer",))

    def test_ac2_prompt_excludes_years_region_for_boolean_channel(self) -> None:
        """boolean 채널 프롬프트는 연차·지역 제외 + Title+Skill+Domain 만 지시해야 한다."""
        prompt = _build_prompt(_FakePosition(), "linkedin_rps")
        self.assertIn("연차", prompt)
        self.assertIn("지역", prompt)
        # Title+Skill+Domain 만으로 구성하라는 지시가 있어야 한다.
        self.assertTrue(
            ("Title" in prompt and "Skill" in prompt and "Domain" in prompt)
            or ("직무" in prompt and "기술" in prompt and "도메인" in prompt),
            "프롬프트가 boolean_query 구성요소(Title+Skill+Domain)를 명시해야 함",
        )


if __name__ == "__main__":
    unittest.main()
