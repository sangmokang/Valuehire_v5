"""U3 (AC-N2 마무리) — 해소 결과를 기존 /fleet-run 계약으로 환원.

이 단위가 자연어 경로와 **기존 인프라를 잇는 마지막 이음매**다. SOT-32 §3 원칙 3:
새 러너를 만들지 않고, 해소가 끝난 뒤에는 기존 `/fleet-run <skill> <url> …` 문자열로
되돌려 기존 큐·워커·스킬을 그대로 태운다.

가장 강한 증거는 "문자열이 예쁘다"가 아니라 **기존 파서가 실제로 받아준다**는 것이다.
그래서 산출물을 진짜 `fleet_args.parse_fleet_args()` 에 먹여서 검증한다.

불변식: 해소가 안 끝났으면(may_execute=False) 명령을 만들지 않는다 — F-NL3.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing import nl_shell
from tools.multi_position_sourcing.fleet_args import parse_fleet_args, FleetArgsError

CU = "https://app.clickup.com/t/86exwz89j"


def _cmd(raw):
    c = nl_shell.parse(raw)
    assert c is not None, raw
    return c


def _one(url=CU):
    return nl_shell.Resolution(status="one", may_execute=True, url=url,
                               candidates=(nl_shell.Candidate("PM", url),))


class RoundTripsThroughRealParser(unittest.TestCase):
    """산출한 명령을 기존 파서가 실제로 받아들이는가 — 이게 핵심 증거."""

    def test_clickup_search_becomes_valid_fleet_run(self):
        text = nl_shell.to_fleet_command(_cmd("클릭업에서 번개장터 PM 서치해"), _one())
        self.assertTrue(text.startswith("/fleet-run "), text)
        command, _, raw_args = text.lstrip("/").partition(" ")
        parsed = parse_fleet_args(command, raw_args)
        self.assertEqual(parsed["skill"], "aisearch")
        self.assertEqual(parsed["url"], CU)

    def test_web_find_becomes_jdintake_fleet_run(self):
        text = nl_shell.to_fleet_command(
            _cmd("웹에서 공식 채용페이지에서 번개장터 PM 찾아"),
            _one("https://bunjang.career.greetinghr.com/o/123"))
        self.assertIn("jdintake", text)

    def test_saramin_search_uses_humansearch(self):
        text = nl_shell.to_fleet_command(
            _cmd("사람인에서 번개장터 PM 서치해"),
            _one("https://www.saramin.co.kr/zf_user/talent-search?x=1"))
        command, _, raw_args = text.lstrip("/").partition(" ")
        self.assertEqual(parse_fleet_args(command, raw_args)["skill"], "humansearch")

    def test_url_with_spaces_or_quotes_does_not_break_parser(self):
        """따옴표·공백이 섞인 URL 이 와도 파서가 깨지지 않게 인용한다."""
        weird = "https://app.clickup.com/t/86e?q=a b&r='c'"
        text = nl_shell.to_fleet_command(_cmd("클릭업에서 번개장터 PM 서치해"), _one(weird))
        command, _, raw_args = text.lstrip("/").partition(" ")
        self.assertEqual(parse_fleet_args(command, raw_args)["url"], weird)


class RefusesUnresolved(unittest.TestCase):
    """F-NL3 — 대상이 확정되지 않았으면 명령을 만들지 않는다."""

    def test_zero_hits_makes_no_command(self):
        r = nl_shell.Resolution(status="zero", may_execute=False)
        self.assertIsNone(nl_shell.to_fleet_command(_cmd("클릭업에서 번개장터 PM 서치해"), r))

    def test_many_hits_makes_no_command(self):
        r = nl_shell.Resolution(status="many", may_execute=False,
                                candidates=(nl_shell.Candidate("a", CU),))
        self.assertIsNone(nl_shell.to_fleet_command(_cmd("클릭업에서 번개장터 PM 서치해"), r))

    def test_error_makes_no_command(self):
        r = nl_shell.Resolution(status="error", may_execute=False, error="clickup down")
        self.assertIsNone(nl_shell.to_fleet_command(_cmd("클릭업에서 번개장터 PM 서치해"), r))

    def test_url_present_but_not_permitted_still_makes_no_command(self):
        """뮤턴트 생존으로 발견(2026-07-22) — 위 세 케이스는 URL 이 비어 있어서
        `not url` 검사에 걸렸을 뿐, **may_execute 게이트는 한 번도 안 탔다**(허수).

        진짜 위험한 상태는 이것이다: 후보가 여럿이라 정책상 실행 금지인데, 편의상
        첫 후보 URL 이 채워져 있는 경우. 여기서 명령이 만들어지면 사장님이 고르기도
        전에 몇 시간짜리 검색이 돈다 — F-NL3 의 본체.
        """
        r = nl_shell.Resolution(
            status="many", may_execute=False, url=CU,
            candidates=(nl_shell.Candidate("PM(Core)", CU),
                        nl_shell.Candidate("PM(BD)", CU + "x")))
        self.assertIsNone(nl_shell.to_fleet_command(_cmd("클릭업에서 번개장터 PM 서치해"), r))

    def test_error_with_stale_url_makes_no_command(self):
        r = nl_shell.Resolution(status="error", may_execute=False, url=CU,
                                error="clickup 500")
        self.assertIsNone(nl_shell.to_fleet_command(_cmd("클릭업에서 번개장터 PM 서치해"), r))

    def test_may_execute_but_empty_url_makes_no_command(self):
        """플래그만 켜져 있고 URL 이 비면 만들지 않는다(모순 상태 방어)."""
        r = nl_shell.Resolution(status="one", may_execute=True, url="")
        self.assertIsNone(nl_shell.to_fleet_command(_cmd("클릭업에서 번개장터 PM 서치해"), r))


class NonQueueingRoutes(unittest.TestCase):
    """큐에 넣지 않는 경로는 명령을 만들지 않는다 — 조회는 즉답이다."""

    def test_clickup_find_is_not_queued(self):
        # (clickup, find) 의 action 은 reply_with_task_list — queue_skill 이 없다
        self.assertIsNone(nl_shell.to_fleet_command(_cmd("클릭업에서 번개장터 PM 찾아"), _one()))

    def test_queue_view_is_not_queued(self):
        r = nl_shell.Resolution(status="one", may_execute=True)
        self.assertIsNone(nl_shell.to_fleet_command(_cmd("작업목록 보여줘"), r))


class Idempotency(unittest.TestCase):
    def test_message_id_becomes_idempotency_key(self):
        """같은 디스코드 이벤트가 두 번 와도 잡이 하나가 되게 멱등키를 실는다(G6)."""
        text = nl_shell.to_fleet_command(
            _cmd("클릭업에서 번개장터 PM 서치해"), _one(), message_id="1529267252")
        command, _, raw_args = text.lstrip("/").partition(" ")
        parsed = parse_fleet_args(command, raw_args)
        # 기존 파서는 idempotency 를 params.idempotency_key 로 옮긴다
        # (fleet_args.py:167-171). 우리 쪽 추측이 아니라 실제 계약에 맞춘다.
        self.assertEqual(parsed["params"]["idempotency_key"], "discord:1529267252")

    def test_same_input_yields_same_command(self):
        a = nl_shell.to_fleet_command(_cmd("클릭업에서 번개장터 PM 서치해"), _one(), message_id="7")
        b = nl_shell.to_fleet_command(_cmd("클릭업에서 번개장터 PM 서치해"), _one(), message_id="7")
        self.assertEqual(a, b)


class ExistingParserUntouched(unittest.TestCase):
    """SOT-32 §6 — fail-closed 파서를 풀지 않았는지 재확인(회귀 방지)."""

    def test_parser_still_rejects_bare_korean(self):
        with self.assertRaises(FleetArgsError):
            parse_fleet_args("fleet-run", "클릭업에서 번개장터 pm")


if __name__ == "__main__":
    unittest.main()
