"""raw CDP → playwright-page 어댑터 (TODO-2b 조각 B1).

검색 실행부(run_one_search 등)가 쓰는 playwright page/locator 표면을 raw_cdp.CDPTab
위에 제공한다(SOT-26 INV5: 전체 connectOverCDP 금지, 목표 탭 1개 raw CDP). eval 을
주입한 FakeTab 으로 라이브 분리 검증. selector/value 는 injection 방지 이스케이프.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from tools.multi_position_sourcing.raw_page_adapter import RawPage


class FakeTab:
    """raw_cdp.CDPTab 대역 — eval 로 받은 JS 를 기록하고 미리 정한 값을 돌려준다."""

    def __init__(self, results=None):
        self.evals: list[str] = []
        self.navigations: list[str] = []
        self._results = results or {}

    def eval(self, expr: str):
        self.evals.append(expr)
        for needle, val in self._results.items():
            if needle in expr:
                return val
        return None

    def navigate(self, url: str, wait_ms: int = 0):
        self.navigations.append(url)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class RawPageAdapterTests(unittest.TestCase):
    def test_count_evaluates_query_selector_all_length(self) -> None:
        tab = FakeTab(results={"querySelectorAll": 3})
        page = RawPage(tab)
        self.assertEqual(_run(page.locator("#txtKeyword").count()), 3)
        self.assertTrue(any("querySelectorAll" in e and "#txtKeyword" in e for e in tab.evals))

    def test_fill_sets_value_and_dispatches_input_change(self) -> None:
        tab = FakeTab()
        page = RawPage(tab)
        _run(page.locator("input[name='k']").fill("hi"))
        js = tab.evals[-1]
        self.assertIn("hi", js)
        self.assertIn("input", js)   # input 이벤트 dispatch
        self.assertIn("change", js)  # change 이벤트 dispatch

    def test_click_calls_element_click(self) -> None:
        tab = FakeTab()
        page = RawPage(tab)
        _run(page.locator("button.search").click())
        self.assertIn(".click()", tab.evals[-1])

    def test_inner_text_returns_element_text(self) -> None:
        tab = FakeTab(results={"innerText": "결과 12건"})
        page = RawPage(tab)
        self.assertEqual(_run(page.locator("body").inner_text()), "결과 12건")

    def test_selector_with_quotes_is_escaped(self) -> None:
        # injection 방지: 따옴표·백슬래시 든 selector 가 JS 를 깨지 않게 이스케이프.
        tab = FakeTab()
        page = RawPage(tab)
        evil = "a[href=\"x\"]'; alert(1);//"
        _run(page.locator(evil).count())
        js = tab.evals[-1]
        # 원시 selector 가 JSON 문자열로 안전 삽입 — 날 것의 '; alert 가 코드로 안 들어감.
        self.assertIn(json.dumps(evil), js)

    def test_first_is_index_zero(self) -> None:
        tab = FakeTab(results={"innerText": "첫번째"})
        page = RawPage(tab)
        self.assertEqual(_run(page.locator(".item").first.inner_text()), "첫번째")

    def test_goto_navigates_and_url_reads_location_href(self) -> None:
        tab = FakeTab(results={"location.href": "https://www.saramin.co.kr/x"})
        page = RawPage(tab)
        _run(page.goto("https://www.saramin.co.kr/x"))
        self.assertEqual(tab.navigations[-1], "https://www.saramin.co.kr/x")
        self.assertEqual(_run(page.url()), "https://www.saramin.co.kr/x")

    def test_on_is_noop_in_b1(self) -> None:
        # 조각 B1: 이벤트 모니터는 아직 no-op(조각 B2). 예외만 안 나면 됨.
        tab = FakeTab()
        page = RawPage(tab)
        page.on("response", lambda r: None)  # 예외 없이 통과


if __name__ == "__main__":
    unittest.main()
