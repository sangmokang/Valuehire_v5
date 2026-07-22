"""U1 (AC-N2 前半) — 대상 해소 3분기 정책 nl_shell.resolve().

계약: docs/sot/32-nl-shell-routing.json §resolution_policy
  zero_hits : 실행 금지 + 다른 장소로 임의 확장 금지 (E-NL2)
  one_hit   : 진행 허용
  many_hits : 고르기 전까지 실행 금지, 선택지 최대 4개 (E-NL1)

이 단위는 **정책만** 검증한다. 실제 ClickUp/웹 검색 어댑터는 U2 소관이라
여기서는 검색기를 주입(injection)해 순수 로직으로 시험한다.

왜 정책을 코드로 고정하나: "0건이면 실행 안 함"을 문장으로만 두면 지켜졌는지
기계가 못 본다. 이 결함이 실제로 사고를 냈다(CLAUDE.md §0.2 추측 실행 금지).
"""

from __future__ import annotations

import json
import pathlib
import unittest

from tools.multi_position_sourcing import nl_shell

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = json.loads(
    (ROOT / "docs/sot/32-nl-shell-routing.json").read_text(encoding="utf-8"))
POLICY = CONTRACT["resolution_policy"]

CU = "https://app.clickup.com/t/"


def _cmd(raw="클릭업에서 번개장터 PM 찾아"):
    parsed = nl_shell.parse(raw)
    assert parsed is not None, raw
    return parsed


def _searcher(*hits):
    """(이름, URL) 목록을 돌려주는 가짜 검색기."""
    def search(locus, target):
        return [nl_shell.Candidate(name=n, url=u) for n, u in hits]
    return search


class ZeroHits(unittest.TestCase):
    def test_zero_blocks_execution(self):
        r = nl_shell.resolve(_cmd(), _searcher())
        self.assertEqual(r.status, "zero")
        self.assertFalse(r.may_execute)
        self.assertEqual(r.url, "")

    def test_zero_does_not_widen_locus(self):
        """E-NL2 — 사장님이 장소를 지정하셨으므로 다른 장소로 확장하지 않는다."""
        seen: list[str] = []

        def search(locus, target):
            seen.append(locus)
            return []

        nl_shell.resolve(_cmd(), search)
        self.assertEqual(seen, ["clickup"], f"장소를 임의 확장함: {seen}")


class OneHit(unittest.TestCase):
    def test_one_proceeds_with_url(self):
        r = nl_shell.resolve(_cmd(), _searcher(("PM(Core Product)", CU + "86exwz89j")))
        self.assertEqual(r.status, "one")
        self.assertTrue(r.may_execute)
        self.assertEqual(r.url, CU + "86exwz89j")


class ManyHits(unittest.TestCase):
    """실제로 발생한 사례 — '번개장터 PM' 이 ClickUp 에 2건(Core Product / BD)."""

    def _many(self):
        return nl_shell.resolve(_cmd(), _searcher(
            ("Product Manager(Core Product)", CU + "86exwz89j"),
            ("Product Manager(Business Development)", CU + "86exx1v3q"),
        ))

    def test_many_blocks_execution(self):
        r = self._many()
        self.assertEqual(r.status, "many")
        self.assertFalse(r.may_execute, "여러 건인데 임의로 하나를 골라 실행함")
        self.assertEqual(r.url, "")

    def test_many_offers_choices(self):
        r = self._many()
        self.assertEqual(len(r.candidates), 2)
        self.assertEqual(r.candidates[0].url, CU + "86exwz89j")

    def test_choices_are_capped_by_contract(self):
        cap = POLICY["many_hits"]["max_choices"]
        r = nl_shell.resolve(_cmd(), _searcher(
            *[(f"P{i}", f"{CU}id{i}") for i in range(cap + 3)]))
        self.assertEqual(len(r.candidates), cap)
        self.assertEqual(r.truncated, 3, "잘라낸 건수를 숨기면 안 된다")


class NoTargetRoutes(unittest.TestCase):
    """resolver == 'none' 인 경로(queue 조회)는 검색 없이 바로 진행한다."""

    def test_queue_needs_no_search(self):
        called = []

        def search(locus, target):
            called.append(1)
            return []

        r = nl_shell.resolve(_cmd("작업목록 보여줘"), search)
        self.assertEqual(r.status, "one")
        self.assertTrue(r.may_execute)
        self.assertEqual(called, [], "해소가 필요 없는데 검색을 호출함")


class PolicyDrivenByContract(unittest.TestCase):
    """정책 숫자·플래그를 코드에 하드코딩하지 않고 계약에서 읽는가."""

    def test_flags_match_contract(self):
        for status, key in (("zero", "zero_hits"), ("one", "one_hit"), ("many", "many_hits")):
            self.assertEqual(
                nl_shell.policy_for(status)["may_execute"],
                POLICY[key]["may_execute"],
                f"{status} 정책이 계약과 다름")

    def test_searcher_failure_is_not_silent_success(self):
        """검색기가 터지면 '0건'으로 둔갑시키지 않는다 — 실행 금지 + 사유 보존."""
        def boom(locus, target):
            raise RuntimeError("clickup down")

        r = nl_shell.resolve(_cmd(), boom)
        self.assertEqual(r.status, "error")
        self.assertFalse(r.may_execute)
        self.assertIn("clickup down", r.error)


if __name__ == "__main__":
    unittest.main()
