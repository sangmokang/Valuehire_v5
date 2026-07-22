"""U4 — 자유 문장의 **단일 진입점** nl_shell.interpret().

왜 필요한가(2026-07-22 회수에서 발견):
    자유 문장을 해석하는 코드가 이미 두 벌 있다.
      - `bot_intent.classify_free_text()` — 상위 goal AC-5 산출물. URL 이 딸린
        문장을 허용 명령(aisearch/humansearch/url/login/jobs/kpi)으로 사상.
      - `nl_shell.parse()` — 이번 작업. URL 없이 이름만 준 문장을 (장소·대상·동사)로.
    그런데 **bot_intent 는 아무 데서도 안 쓰인다**(죽은 코드). 이 상태로 게이트웨이를
    배선하면 파서가 둘로 갈라져 서로 다른 답을 내는 드리프트가 생긴다 —
    내가 만든 SOT-32 F-NL4 가 금지하는 바로 그 상황이다.

    그래서 게이트웨이가 부를 창구를 **하나로** 정한다. 새로 만드는 게 아니라
    둘을 합류시킨다(CLAUDE.md §0.2 — 기존 구현 재사용).

합류 규칙(이 테스트가 계약이다):
    1. nl_shell.parse() 를 **먼저** 시도한다 — URL 없이 이름만 준 경우가 이번 작업의
       존재 이유이고, bot_intent 는 그 경우를 못 다룬다.
    2. 실패하면 bot_intent.classify_free_text() 로 넘긴다 — URL 이 딸린 기존 문장은
       그쪽이 이미 잘 다룬다.
    3. 둘 다 실패하면 실행 금지. 추측하지 않는다.
    4. 어느 쪽이 답했는지 항상 밝힌다(source) — 디버깅 가능해야 한다.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing import nl_shell
from tools.multi_position_sourcing.bot_intent import ClassifyOutcome

CU = "https://app.clickup.com/t/86ey90v4k"
SARAMIN = "https://www.saramin.co.kr/zf_user/talent-search?searchword=pm"


class NlShellWins(unittest.TestCase):
    """URL 없는 이름 문장은 nl_shell 이 잡는다 — 이게 이번 작업의 존재 이유."""

    def test_owner_clickup_sentence(self):
        r = nl_shell.interpret("클릭업에서 번개장터 PM 찾아")
        self.assertEqual(r.source, "nl_shell")
        self.assertIsNotNone(r.command)
        self.assertEqual(r.command.locus, "clickup")
        self.assertIsNone(r.intent)

    def test_owner_web_sentence(self):
        r = nl_shell.interpret("웹에서 공식 채용페이지에서 번개장터 PM 찾아")
        self.assertEqual(r.source, "nl_shell")
        self.assertEqual(r.command.locus, "web")


class BotIntentFallback(unittest.TestCase):
    """URL 이 딸린 기존 문장은 이미 있던 분류기가 처리한다 — 중복 구현 금지."""

    def test_search_url_falls_back_to_bot_intent(self):
        r = nl_shell.interpret(f"이 검색결과 순회해줘 {SARAMIN}")
        self.assertEqual(r.source, "bot_intent")
        self.assertIsNone(r.command)
        self.assertIsNotNone(r.intent)

    def test_clickup_url_falls_back_to_bot_intent(self):
        r = nl_shell.interpret(f"이 포지션 서치해줘 {CU}")
        self.assertEqual(r.source, "bot_intent")
        self.assertIsNotNone(r.intent)


class NeitherExecutes(unittest.TestCase):
    def test_gibberish_is_not_executed(self):
        for raw in ("", "   ", "ㅇㅇ", "고마워요", "오늘 날씨 어때"):
            r = nl_shell.interpret(raw)
            self.assertFalse(r.may_execute, f"실행 허용됨: {raw!r}")
            self.assertIsNone(r.command)

    def test_send_request_is_refused_not_guessed(self):
        """F-NL5/SOT28 — 발송 요구는 어느 창구에서도 실행으로 이어지지 않는다."""
        r = nl_shell.interpret("번개장터 PM 후보한테 제안 메일 보내줘")
        self.assertFalse(r.may_execute)
        self.assertIsNone(r.command)

    def test_refused_path_still_names_its_real_source(self):
        """뮤턴트 생존으로 발견(2026-07-22) — 실행 금지 분기의 source 를 아무도
        검사하지 않아, 'bot_intent 가 거절했는데 nl_shell 이 답했다'고 거짓 보고해도
        전부 통과했다. 거짓 출처는 디버깅을 불가능하게 만든다.
        """
        r = nl_shell.interpret("번개장터 PM 후보한테 제안 메일 보내줘")
        self.assertEqual(r.source, "bot_intent")
        self.assertIsNotNone(r.intent, "거절한 분류기 결과를 버리면 사유를 못 알린다")

    def test_unknown_path_names_bot_intent_too(self):
        r = nl_shell.interpret("오늘 날씨 어때")
        self.assertEqual(r.source, "bot_intent")


class OrderIsContractual(unittest.TestCase):
    """합류 순서가 규칙이다 — nl_shell 우선. 뒤집히면 이름 문장이 죽는다."""

    def test_nl_shell_is_tried_first(self):
        calls: list[str] = []
        r = nl_shell.interpret(
            "클릭업에서 번개장터 PM 찾아",
            _classifier=lambda t: calls.append("bot_intent") or None)
        self.assertEqual(r.source, "nl_shell")
        self.assertEqual(calls, [], "nl_shell 이 잡았는데 bot_intent 도 불렀다")

    def test_classifier_is_injectable_and_used_on_fallback(self):
        calls: list[str] = []

        def spy(text):
            calls.append(text)
            from tools.multi_position_sourcing.bot_intent import ClassifyResult
            return ClassifyResult(outcome=ClassifyOutcome.UNKNOWN)

        nl_shell.interpret("이건 아무 말", _classifier=spy)
        self.assertEqual(calls, ["이건 아무 말"])


class SingleEntryPoint(unittest.TestCase):
    """게이트웨이가 부를 창구가 하나임을 봉인(F-NL4 드리프트 방지)."""

    def test_interpret_is_exported(self):
        self.assertTrue(callable(getattr(nl_shell, "interpret", None)))

    def test_result_always_states_its_source(self):
        for raw in ("클릭업에서 번개장터 PM 찾아", f"서치해줘 {CU}", "아무말"):
            self.assertIn(nl_shell.interpret(raw).source,
                          {"nl_shell", "bot_intent", "none"})


if __name__ == "__main__":
    unittest.main()
