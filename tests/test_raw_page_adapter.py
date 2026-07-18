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
        self.navigation_waits: list[int] = []
        self.events: list[tuple[str, object]] = []
        self._results = results or {}

    def eval(self, expr: str):
        self.evals.append(expr)
        for needle, val in self._results.items():
            if needle in expr:
                return val
        return None

    def navigate(self, url: str, wait_ms: int = 0):
        self.navigations.append(url)
        self.navigation_waits.append(wait_ms)

    def on(self, event: str, handler: object) -> None:
        self.events.append((event, handler))


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
        self.assertEqual(
            _run(page.locator("body").inner_text(timeout=5000)),
            "결과 12건",
        )

    def test_selector_with_quotes_is_escaped(self) -> None:
        # injection 방지: 따옴표·백슬래시 든 selector 가 JS 를 깨지 않게 이스케이프.
        tab = FakeTab()
        page = RawPage(tab)
        evil = "a[href=\"x\"]'; alert(1);//"
        _run(page.locator(evil).count())
        js = tab.evals[-1]
        # 원시 selector 가 JSON 문자열로 안전 삽입 — 날 것의 '; alert 가 코드로 안 들어감.
        self.assertIn(json.dumps(evil), js)

    def test_playwright_has_text_selector_is_translated_before_native_query(self) -> None:
        tab = FakeTab(results={"querySelectorAll": 1})
        page = RawPage(tab)
        self.assertEqual(_run(page.locator('button:has-text("검색")').count()), 1)
        self.assertNotIn(":has-text", tab.evals[-1])

    def test_first_is_index_zero(self) -> None:
        tab = FakeTab(results={"innerText": "첫번째"})
        page = RawPage(tab)
        self.assertEqual(_run(page.locator(".item").first.inner_text()), "첫번째")

    def test_nth_get_attribute_and_press_cover_production_surface(self) -> None:
        tab = FakeTab(results={"getAttribute": "/profile/42"})
        page = RawPage(tab)
        item = page.locator("a.profile").nth(2)
        self.assertEqual(_run(item.get_attribute("href")), "/profile/42")
        _run(item.press("Enter"))
        self.assertTrue(any("[2]" in expr for expr in tab.evals))
        self.assertIn("KeyboardEvent", tab.evals[-1])

    def test_goto_navigates_and_url_reads_location_href(self) -> None:
        tab = FakeTab(results={"location.href": "https://www.saramin.co.kr/x"})
        page = RawPage(tab)
        _run(page.goto("https://www.saramin.co.kr/x", timeout=45000))
        self.assertEqual(tab.navigations[-1], "https://www.saramin.co.kr/x")
        self.assertEqual(page.url, "https://www.saramin.co.kr/x")
        self.assertEqual(_run(page.current_url()), "https://www.saramin.co.kr/x")
        self.assertNotEqual(tab.navigation_waits[-1], 45000)

    def test_goto_waits_for_dom_content_readiness(self) -> None:
        class LoadingTab(FakeTab):
            def __init__(self):
                super().__init__()
                self.states = ["loading", "loading", "interactive"]
                self.ready_reads = 0
                self._badge_label = "Codex login target"
                self.badge_refreshes = 0

            def eval(self, expr: str):
                if "document.readyState" in expr:
                    self.ready_reads += 1
                    return self.states.pop(0)
                return super().eval(expr)

            def mark_busy(self, label: str):
                self.asserted_label = label
                self.badge_refreshes += 1

        tab = LoadingTab()
        _run(RawPage(tab).goto(
            "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            wait_until="domcontentloaded",
            timeout=1000,
        ))
        self.assertEqual(tab.ready_reads, 3)
        self.assertEqual(tab.badge_refreshes, 1)
        self.assertEqual(tab.asserted_label, "Codex login target")

    def test_on_delegates_to_raw_tab_event_bridge(self) -> None:
        tab = FakeTab()
        page = RawPage(tab)
        handler = lambda _response: None
        page.on("response", handler)
        self.assertEqual(tab.events, [("response", handler)])


if __name__ == "__main__":
    unittest.main()
