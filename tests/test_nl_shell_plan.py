"""U6 (AC-N4) — 자유 문장 한 줄 → 다음 행동 결정 `nl_shell.plan_from_text()`.

게이트웨이가 부를 **최종 함수**다. interpret → resolve → to_fleet_command 를 엮어
"이 문장에 대해 무엇을 할 것인가" 하나를 돌려준다. 순수 함수라 디스코드 없이 시험된다.

행동은 넷뿐이다:
  enqueue  — 큐에 넣을 완성된 /fleet-run 명령이 있다
  choices  — 대상이 여럿이라 사장님이 골라야 한다(실행 금지)
  reply    — 즉답(조회형·못 찾음·거절·문법 안내). 큐에 안 넣는다
  ignore   — 우리 소관이 아니다(다른 처리기로 흘려보낸다)

"실행 안 함"을 조용히 하지 않는 것이 핵심이다 — 사장님이 명령을 던졌는데 아무 반응이
없으면 먹힌 줄 모른다(2026-07-22에 실제로 그 일이 있었다).
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing import nl_shell

CU = "https://app.clickup.com/t/"


def _searcher(*hits):
    def search(locus, target):
        return [nl_shell.Candidate(n, u) for n, u in hits]
    return search


def _boom(locus, target):
    raise RuntimeError("clickup 500")


class Enqueues(unittest.TestCase):
    def test_single_hit_search_produces_command(self):
        plan = nl_shell.plan_from_text(
            "클릭업에서 번개장터 PM 서치해",
            searcher=_searcher(("PM", CU + "86a")), message_id="42")
        self.assertEqual(plan.action, "enqueue")
        self.assertIn("/fleet-run aisearch", plan.command_text)
        self.assertIn(CU + "86a", plan.command_text)
        self.assertIn("discord:42", plan.command_text)

    def test_web_find_enqueues_jdintake(self):
        plan = nl_shell.plan_from_text(
            "웹에서 공식 채용페이지에서 번개장터 PM 찾아",
            searcher=_searcher(("공고", "https://bunjang.career.greetinghr.com/o/1")))
        self.assertEqual(plan.action, "enqueue")
        self.assertIn("jdintake", plan.command_text)


class OffersChoices(unittest.TestCase):
    """사장님 실사례 — '번개장터 PM' 이 2건. 고르기 전엔 절대 실행하지 않는다."""

    def test_many_hits_asks_which_one(self):
        plan = nl_shell.plan_from_text(
            "클릭업에서 번개장터 PM 서치해",
            searcher=_searcher(("PM(Core Product)", CU + "86a"),
                               ("PM(Business Development)", CU + "86b")))
        self.assertEqual(plan.action, "choices")
        self.assertEqual(len(plan.choices), 2)
        self.assertEqual(plan.command_text, "", "고르기 전에 명령을 만들면 안 된다")
        self.assertIn("2", plan.reply)  # 몇 건인지 알려준다


class RepliesWithoutQueueing(unittest.TestCase):
    def test_zero_hits_says_not_found(self):
        plan = nl_shell.plan_from_text("클릭업에서 없는회사 PM 서치해", searcher=_searcher())
        self.assertEqual(plan.action, "reply")
        self.assertEqual(plan.command_text, "")
        self.assertTrue(plan.reply)

    def test_search_failure_is_reported_as_failure_not_zero(self):
        """'못 찾았다'와 '못 물어봤다'를 구분해 보고한다."""
        plan = nl_shell.plan_from_text("클릭업에서 번개장터 PM 서치해", searcher=_boom)
        self.assertEqual(plan.action, "reply")
        self.assertIn("clickup 500", plan.reply)

    def test_clickup_find_replies_with_task_list(self):
        """조회형은 즉답 — 큐에 넣지 않는다."""
        plan = nl_shell.plan_from_text(
            "클릭업에서 번개장터 PM 찾아", searcher=_searcher(("PM", CU + "86a")))
        self.assertEqual(plan.action, "reply")
        self.assertIn(CU + "86a", plan.reply)

    def test_dangerous_request_is_refused_out_loud(self):
        """F-NL5 — 발송 요구는 거절하되 **조용히 무시하지 않는다**."""
        plan = nl_shell.plan_from_text("번개장터 PM 한테 제안 메일 보내줘", searcher=_searcher())
        self.assertNotEqual(plan.action, "enqueue")
        self.assertTrue(plan.reply, "거절 사유를 말하지 않으면 먹힌 줄 모른다")


class Ignores(unittest.TestCase):
    def test_plain_chat_is_ignored(self):
        for raw in ("", "  ", "고마워요"):
            self.assertEqual(nl_shell.plan_from_text(raw, searcher=_searcher()).action,
                             "ignore", raw)


class NeverExecutesWithoutResolution(unittest.TestCase):
    """F-NL3 종단 확인 — 어떤 경로로도 미해소 상태에서 명령이 나오지 않는다."""

    def test_no_command_text_unless_enqueue(self):
        cases = [
            ("클릭업에서 번개장터 PM 서치해", _searcher()),                       # zero
            ("클릭업에서 번개장터 PM 서치해", _boom),                              # error
            ("클릭업에서 번개장터 PM 서치해",
             _searcher(("a", CU + "1"), ("b", CU + "2"))),                        # many
            ("클릭업에서 번개장터 PM 찾아", _searcher(("a", CU + "1"))),          # 조회형
            ("고마워요", _searcher()),                                            # 잡담
        ]
        for raw, searcher in cases:
            plan = nl_shell.plan_from_text(raw, searcher=searcher)
            if plan.action != "enqueue":
                self.assertEqual(plan.command_text, "", f"{raw!r} → {plan.action}")


if __name__ == "__main__":
    unittest.main()
