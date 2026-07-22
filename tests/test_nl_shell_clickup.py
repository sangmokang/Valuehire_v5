"""U2 (AC-N2 後半) — ClickUp 대상 해소 어댑터.

사장님 실제 사례가 이 단위의 존재 이유다:
    입력  "클릭업에서 번개장터 PM 찾아"
    실제  ClickUp 제목은 "Product Manager(Core Product)" / "…(Business Development)"
    함정  **'PM' 이라는 글자가 제목에 없다** — 단순 부분일치로는 0건이 되어
          "못 찾았습니다"라고 답하게 된다(실제로 이 상황이 있었다).

그래서 역할 약어 동의어(PM ↔ Product Manager)를 계약(SOT-32 role_synonyms)에서
읽어 매칭한다. 코드에 사전을 숨기지 않는다.

검색 수단은 기존 계약 `ClickUpSearchTasks`(humansearch_register.py:74) 와
같은 모양의 어댑터를 주입받는다 — 새 러너를 만들지 않는다(CLAUDE.md §0.2).
"""

from __future__ import annotations

import json
import pathlib
import unittest

from tools.multi_position_sourcing import nl_shell

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = json.loads(
    (ROOT / "docs/sot/32-nl-shell-routing.json").read_text(encoding="utf-8"))

CU = "https://app.clickup.com/t/"

# 사장님이 실제로 마주친 ClickUp 응답 모양(2026-07-22 디스코드 로그 기준).
REAL_TASKS = [
    {"id": "86exwz89j", "name": "Product Manager(Core Product)",
     "url": CU + "86exwz89j", "list": {"name": "번개장터"}},
    {"id": "86exx1v3q", "name": "Product Manager(Business Development)",
     "url": CU + "86exx1v3q", "list": {"name": "번개장터"}},
    {"id": "86zzz0001", "name": "Backend Engineer",
     "url": CU + "86zzz0001", "list": {"name": "토스"}},
]


def _adapter(tasks=None, record=None):
    """기존 ClickUpSearchTasks 모양: (list_id=, query=, parent=) -> Sequence[Mapping]."""
    def search(**kwargs):
        if record is not None:
            record.append(kwargs)
        return list(REAL_TASKS if tasks is None else tasks)
    return search


def _searcher(**kw):
    return nl_shell.clickup_position_searcher(_adapter(**kw), list_id="901814621569")


class OwnerRealCase(unittest.TestCase):
    """'번개장터 PM' 이 제목에 'PM' 이 없는 Task 2건을 찾아내야 한다."""

    def test_abbreviation_matches_full_role_name(self):
        found = _searcher()("clickup", "번개장터 PM")
        self.assertEqual(len(found), 2, f"약어 매칭 실패: {[c.name for c in found]}")
        self.assertEqual({c.url for c in found},
                         {CU + "86exwz89j", CU + "86exx1v3q"})

    def test_company_scopes_the_result(self):
        """회사명이 다르면 걸러진다 — '토스 PM' 은 번개장터 PM 을 물어오면 안 된다."""
        self.assertEqual(_searcher()("clickup", "토스 PM"), [])

    def test_full_role_name_also_matches(self):
        found = _searcher()("clickup", "번개장터 Product Manager")
        self.assertEqual(len(found), 2)

    def test_resolve_reports_many_for_this_case(self):
        """U1 정책과 이어붙였을 때 '선택지 2개'가 나와야 한다(실행 금지)."""
        cmd = nl_shell.parse("클릭업에서 번개장터 PM 찾아")
        r = nl_shell.resolve(cmd, _searcher())
        self.assertEqual(r.status, "many")
        self.assertFalse(r.may_execute)
        self.assertEqual(len(r.candidates), 2)

    def test_single_hit_resolves_to_one(self):
        cmd = nl_shell.parse("클릭업에서 토스 백엔드 찾아")
        r = nl_shell.resolve(cmd, _searcher())
        self.assertEqual(r.status, "one")
        self.assertTrue(r.may_execute)
        self.assertEqual(r.url, CU + "86zzz0001")


class AdapterContract(unittest.TestCase):
    def test_uses_configured_list_id(self):
        rec: list[dict] = []
        nl_shell.clickup_position_searcher(
            _adapter(record=rec), list_id="901814621569")("clickup", "번개장터 PM")
        self.assertEqual(rec[0]["list_id"], "901814621569")

    def test_candidate_carries_readable_name(self):
        found = _searcher()("clickup", "번개장터 PM")
        self.assertIn("Core Product", " ".join(c.name for c in found))

    def test_task_without_url_is_reconstructed_from_id(self):
        found = nl_shell.clickup_position_searcher(
            _adapter(tasks=[{"id": "86abc", "name": "PM", "list": {"name": "A"}}]),
            list_id="x")("clickup", "A PM")
        self.assertEqual(found[0].url, CU + "86abc")

    def test_task_without_id_or_url_is_dropped(self):
        """URL 을 만들 수 없는 항목은 후보로 내보내지 않는다 — 빈 링크 금지."""
        found = nl_shell.clickup_position_searcher(
            _adapter(tasks=[{"name": "A PM"}]), list_id="x")("clickup", "A PM")
        self.assertEqual(found, [])

    def test_adapter_error_propagates(self):
        """어댑터 실패를 '0건'으로 삼키지 않는다 — resolve 가 error 로 받게 둔다."""
        def boom(**kw):
            raise RuntimeError("clickup 401")

        with self.assertRaises(RuntimeError):
            nl_shell.clickup_position_searcher(boom, list_id="x")("clickup", "번개장터 PM")


class SynonymsFromContract(unittest.TestCase):
    def test_contract_declares_role_synonyms(self):
        self.assertIn("role_synonyms", CONTRACT)
        self.assertIn("pm", {k.lower() for k in CONTRACT["role_synonyms"]})

    def test_every_declared_synonym_actually_matches(self):
        """계약에 적은 동의어가 실제로 동작해야 한다 — 문서만 늘리는 위장 방지."""
        for abbr, fulls in CONTRACT["role_synonyms"].items():
            for full in fulls:
                tasks = [{"id": "x1", "name": full, "url": CU + "x1",
                          "list": {"name": "테스트사"}}]
                found = nl_shell.clickup_position_searcher(
                    _adapter(tasks=tasks), list_id="x")("clickup", f"테스트사 {abbr}")
                self.assertEqual(len(found), 1, f"동의어 미동작: {abbr} → {full}")


if __name__ == "__main__":
    unittest.main()
