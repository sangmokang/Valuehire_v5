"""한 그룹의 키워드 생성 실패가 사이클 전체를 죽이면 안 된다.

근거(2026-07-31 코드리뷰 CONFIRMED #4, 2026-08-01 재현):
`valuehire-search-runner.err.log` 에 `KeywordGenerationError: LLM JSON 파싱 실패` 가
반복 기록되고, 그때마다 `valuehire search cycle failed` 로 **사이클 전체**가 죽는다.
`build_dry_run_payload` 의 dict comprehension 에 그룹별 격리가 없어, 그룹 하나의
LLM 응답이 깨지면 정상인 나머지 그룹의 검색까지 통째로 버려진다.

인수 기준: 한 그룹의 LLM 키워드 생성이 계속 실패해도
  ① payload 생성은 성공하고(사이클 생존)
  ② 나머지 그룹은 LLM 주입 계획을 그대로 받고
  ③ 실패한 그룹은 고정표 계획으로 살아남으며 실패 사실이 payload 에 기록된다.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.dry_run import build_dry_run_payload
from tools.multi_position_sourcing.grouping import group_positions
from tools.multi_position_sourcing.fixtures import SAMPLE_POSITIONS

_GOOD_JSON = (
    '{"keywords": ["AI 엔지니어", "Machine Learning Engineer", "LLM", "RAG"], '
    '"boolean_query": "(\\"AI Engineer\\" OR \\"ML Engineer\\") AND (PyTorch OR RAG)"}'
)
# 실제 로그에 찍힌 형태: 따옴표가 깨져 관대한 복구로도 못 살리는 응답.
_BROKEN_JSON = '{"keywords": ["AI 엔지니어" "Machine Learning Engineer"], "boolean_query": }'

# 이 회사의 포지션이 대표인 그룹만 항상 실패시킨다(재시도까지 포함해 결정적으로).
_POISON_COMPANY = "Madup"


def _client_failing_for_poison_company():
    """poison 회사의 프롬프트에는 깨진 JSON, 나머지에는 정상 JSON을 준다."""

    calls: dict[str, int] = {"total": 0, "poisoned": 0}

    def _call(prompt: str) -> str:
        calls["total"] += 1
        if _POISON_COMPANY in prompt:
            calls["poisoned"] += 1
            return _BROKEN_JSON
        return _GOOD_JSON

    _call.calls = calls  # type: ignore[attr-defined]
    return _call


class DryRunGroupIsolationTest(unittest.TestCase):
    def test_one_group_failure_does_not_kill_the_cycle(self) -> None:
        client = _client_failing_for_poison_company()
        # RED: 현재는 KeywordGenerationError 가 그대로 튀어나와 사이클이 죽는다.
        payload = build_dry_run_payload(llm_client=client)
        self.assertIsInstance(payload, dict)
        self.assertTrue(
            client.calls["poisoned"] > 0,  # type: ignore[attr-defined]
            "전제 확인: poison 회사 프롬프트가 실제로 호출되어야 테스트가 의미 있다",
        )

    def test_healthy_groups_still_get_their_plans(self) -> None:
        client = _client_failing_for_poison_company()
        payload = build_dry_run_payload(llm_client=client)
        summary = payload["queue_cycle_summary"]
        self.assertTrue(
            summary["updated_items"],
            "한 그룹이 실패해도 정상 그룹의 큐 항목은 남아야 한다",
        )

    def test_failed_group_is_reported_not_silently_dropped(self) -> None:
        """조용히 사라지면 '0건인데 성공'으로 보인다 — 실패 사유가 payload 에 남아야 한다."""
        client = _client_failing_for_poison_company()
        payload = build_dry_run_payload(llm_client=client)
        failures = payload.get("keyword_plan_failures")
        self.assertIsInstance(
            failures, list, "payload 에 keyword_plan_failures 목록이 있어야 한다"
        )
        self.assertTrue(failures, "실패한 그룹이 있으면 목록이 비면 안 된다")
        joined = " ".join(str(f) for f in failures)
        self.assertIn("group", joined.lower(), "어느 그룹이 실패했는지 식별 가능해야 한다")

    def test_counter_ac_all_healthy_reports_no_failures(self) -> None:
        """과잉 격리 방지: 전부 정상이면 실패 목록은 비어 있어야 한다."""
        payload = build_dry_run_payload(llm_client=lambda prompt: _GOOD_JSON)
        self.assertEqual(payload.get("keyword_plan_failures"), [])

    def test_counter_ac_grouping_unchanged(self) -> None:
        """격리를 넣어도 그룹 구성 자체는 바뀌지 않아야 한다."""
        groups = group_positions(SAMPLE_POSITIONS)
        client = _client_failing_for_poison_company()
        payload = build_dry_run_payload(llm_client=client)
        self.assertEqual(len(payload["groups"]), len(groups))


if __name__ == "__main__":
    unittest.main()
