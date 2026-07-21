"""AC-6 — 조회형 명령 라우팅 (goal: discord-single-bot-console §6.2·§11 AC-6).

읽기 명령을 봇 API 층(/api/bot/*) 호출 스펙으로 사상하는 순수 매퍼.
- /kpi        → GET /api/bot/kpi
- /interviews → GET /api/bot/candidates?view=interviews  (E23: unified_candidate_history_view)
- /cases      → GET /api/bot/candidates?view=cases
- /priority   → GET /api/bot/positions
- /job <번호> → GET /api/bot/jobs/<번호>
- /jobs       → GET /api/bot/jobs

안전: 읽기 전용(메서드 GET 고정). 알 수 없는 명령/잘못된 인자는 None(실행 금지).
결과 2000자 초과 처리(E10 결정 ㉮): 상위 N 만 채팅 + 웹 링크(truncate_for_discord).
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.bot_read_commands import (
    READ_COMMANDS,
    ReadRequest,
    map_read_command,
    truncate_for_discord,
)


class MappingTests(unittest.TestCase):
    def test_kpi(self) -> None:
        r = map_read_command("kpi", {})
        self.assertEqual(r, ReadRequest(method="GET", path="/api/bot/kpi", params={}))

    def test_kpi_with_week(self) -> None:
        r = map_read_command("kpi", {"week": "2026-07-20"})
        self.assertEqual(r.params, {"week": "2026-07-20"})

    def test_interviews_and_cases_use_candidates_view(self) -> None:
        self.assertEqual(map_read_command("interviews", {}).path, "/api/bot/candidates")
        self.assertEqual(map_read_command("interviews", {}).params, {"view": "interviews"})
        self.assertEqual(map_read_command("cases", {}).params, {"view": "cases"})

    def test_priority(self) -> None:
        self.assertEqual(map_read_command("priority", {}).path, "/api/bot/positions")

    def test_job_by_id(self) -> None:
        r = map_read_command("job", {"id": "42"})
        self.assertEqual(r.path, "/api/bot/jobs/42")

    def test_jobs_list(self) -> None:
        self.assertEqual(map_read_command("jobs", {}).path, "/api/bot/jobs")

    def test_all_read_requests_are_get(self) -> None:
        for cmd in READ_COMMANDS:
            args = {"id": "1"} if cmd == "job" else {}
            self.assertEqual(map_read_command(cmd, args).method, "GET", cmd)


class RejectionTests(unittest.TestCase):
    def test_unknown_command_none(self) -> None:
        self.assertIsNone(map_read_command("weekly", {}))   # 쓰기 명령은 여기서 매핑 안 함
        self.assertIsNone(map_read_command("bogus", {}))

    def test_job_without_id_none(self) -> None:
        self.assertIsNone(map_read_command("job", {}))

    def test_job_invalid_id_none(self) -> None:
        for bad in ("abc", "-1", "0", "1;DROP", "1 2", ""):
            self.assertIsNone(map_read_command("job", {"id": bad}), bad)

    def test_kpi_invalid_week_none(self) -> None:
        self.assertIsNone(map_read_command("kpi", {"week": "not-a-date"}))
        self.assertIsNone(map_read_command("kpi", {"week": "2026/07/20"}))


class TruncateTests(unittest.TestCase):
    def test_short_text_unchanged(self) -> None:
        text, truncated = truncate_for_discord("짧은 결과", link="https://x")
        self.assertEqual(text, "짧은 결과")
        self.assertFalse(truncated)

    def test_long_text_truncated_with_link(self) -> None:
        long = "가" * 5000
        text, truncated = truncate_for_discord(long, link="https://admin/x")
        self.assertTrue(truncated)
        self.assertLessEqual(len(text), 2000)
        self.assertIn("https://admin/x", text)

    def test_truncation_never_exceeds_2000(self) -> None:
        for n in (1900, 1999, 2000, 2001, 4000):
            text, _ = truncate_for_discord("x" * n, link="https://admin/y")
            self.assertLessEqual(len(text), 2000, n)


if __name__ == "__main__":
    unittest.main()
