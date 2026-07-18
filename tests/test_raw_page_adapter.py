"""raw CDP → playwright-page 어댑터 (TODO-2b 조각 B1).

검색 실행부(run_one_search 등)가 쓰는 playwright page/locator 표면을 raw_cdp.CDPTab
위에 제공한다(SOT-26 INV5: 전체 connectOverCDP 금지, 목표 탭 1개 raw CDP). eval 을
주입한 FakeTab 으로 라이브 분리 검증. selector/value 는 injection 방지 이스케이프.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from tools.multi_position_sourcing.raw_page_adapter import RawPage, _ownership_js


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
    def test_ownership_proof_requires_a_rendered_visible_badge(self) -> None:
        js = _ownership_js("https://example.test/search", "Codex")
        self.assertIn("getComputedStyle", js)
        self.assertIn("getBoundingClientRect", js)
        self.assertIn("visibility", js)
        self.assertIn("opacity", js)
        self.assertIn("parentElement", js)
        self.assertIn("innerHeight", js)

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

    def test_is_visible_requires_rendered_geometry(self) -> None:
        tab = FakeTab(results={"getBoundingClientRect": True})
        page = RawPage(tab)

        self.assertTrue(_run(page.locator("button.account").is_visible()))
        self.assertIn("getBoundingClientRect", tab.evals[-1])

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

            def mark_busy(self, label: str, *, expected_url: str | None = None):
                self.asserted_label = label
                self.asserted_url = expected_url
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

    def test_goto_binds_readiness_to_new_navigation_loader(self) -> None:
        class LifecycleTab(FakeTab):
            def __init__(self):
                super().__init__()
                self.lifecycle_calls: list[tuple[str, str, float]] = []

            def navigate(self, url: str, wait_ms: int = 0):
                super().navigate(url, wait_ms=wait_ms)
                return {"loaderId": "new-loader"}

            def wait_for_lifecycle(self, loader_id: str, event: str, timeout: float):
                self.lifecycle_calls.append((loader_id, event, timeout))

            def eval(self, expr: str):
                if "document.readyState" in expr:
                    return "complete"  # old document; must not be accepted directly
                return super().eval(expr)

        tab = LifecycleTab()
        _run(RawPage(tab).goto(
            "https://www.jobkorea.co.kr/Corp/Person/Find",
            wait_until="domcontentloaded",
            timeout=1000,
        ))
        self.assertEqual(len(tab.lifecycle_calls), 1)
        self.assertEqual(tab.lifecycle_calls[0][:2], ("new-loader", "DOMContentLoaded"))

    def test_required_mode_rejects_indeterminate_badge_refresh(self) -> None:
        class MissingBadgeTab(FakeTab):
            _badge_label = "Codex"

            def mark_busy(self, _label: str, *, expected_url: str | None = None):
                return None

        with self.assertRaisesRegex(RuntimeError, "marker refresh"):
            _run(RawPage(MissingBadgeTab(), require_badge=True)._refresh_busy_badge())

    def test_badge_refresh_atomically_binds_the_observed_url(self) -> None:
        class MovingTab(FakeTab):
            _badge_label = "Codex"

            def __init__(self):
                super().__init__()
                self.live_url = "https://www.jobkorea.co.kr/Corp/Person/Find"
                self.expected_urls: list[str | None] = []

            def eval(self, expr: str):
                if "location.href" in expr:
                    result = self.live_url
                    self.live_url = "https://evil.example/phish"
                    return result
                return super().eval(expr)

            def mark_busy(self, _label: str, expected_url: str | None = None):
                self.expected_urls.append(expected_url)
                return expected_url == self.live_url

        tab = MovingTab()
        with self.assertRaisesRegex(RuntimeError, "marker refresh"):
            _run(RawPage(tab, require_badge=True)._refresh_busy_badge())
        self.assertEqual(
            tab.expected_urls,
            ["https://www.jobkorea.co.kr/Corp/Person/Find"],
        )

    def test_goto_rejects_navigation_protocol_error(self) -> None:
        class FailedNavigationTab(FakeTab):
            def navigate(self, url: str, wait_ms: int = 0):
                super().navigate(url, wait_ms=wait_ms)
                return {"errorText": "net::ERR_NAME_NOT_RESOLVED"}

        with self.assertRaisesRegex(RuntimeError, "navigation failed"):
            _run(RawPage(FailedNavigationTab()).goto("https://invalid.example"))

    def test_goto_rejects_download_navigation(self) -> None:
        class DownloadNavigationTab(FakeTab):
            def navigate(self, url: str, wait_ms: int = 0):
                super().navigate(url, wait_ms=wait_ms)
                return {"isDownload": True}

        with self.assertRaisesRegex(RuntimeError, "download"):
            _run(RawPage(DownloadNavigationTab()).goto("https://example.test/file"))

    def test_required_mode_rejects_navigation_without_new_loader(self) -> None:
        class NoLoaderTab(FakeTab):
            _badge_label = "Codex"

            def mark_busy(self, _label: str):
                return True

            def wait_for_lifecycle(self, *_args):
                raise AssertionError("no loader must not be treated as the old document")

            def eval(self, expr: str):
                if "vh-automation-badge" in expr:
                    return True
                if "document.readyState" in expr:
                    return "complete"
                return super().eval(expr)

        with self.assertRaisesRegex(RuntimeError, "loader"):
            _run(RawPage(
                NoLoaderTab(),
                initial_url="https://www.jobkorea.co.kr/Corp/Person/Find",
                require_badge=True,
            ).goto(
                "https://www.jobkorea.co.kr/Corp/Person/Find",
                wait_until="domcontentloaded",
                timeout=1000,
            ))

    def test_required_mode_cannot_skip_loader_and_marker_by_omitting_wait(self) -> None:
        class NoLoaderTab(FakeTab):
            _badge_label = "Codex"

            def mark_busy(self, _label: str):
                return True

            def eval(self, expr: str):
                if "vh-automation-badge" in expr:
                    return True
                return super().eval(expr)

        with self.assertRaisesRegex(RuntimeError, "loader"):
            _run(RawPage(
                NoLoaderTab(),
                initial_url="https://www.jobkorea.co.kr/Corp/Person/Find",
                require_badge=True,
            ).goto(
                "https://www.jobkorea.co.kr/Corp/Person/Find",
            ))

    def test_every_raw_mutation_rechecks_the_shared_lease(self) -> None:
        tab = FakeTab()
        checks: list[str] = []

        def guard() -> None:
            checks.append("owned")

        page = RawPage(tab, mutation_guard=guard)
        _run(page.locator("input").fill("robotics"))
        _run(page.locator("button").click())
        _run(page.locator("input").press("Enter"))
        _run(page.goto("https://example.test/search"))

        self.assertEqual(checks, ["owned"] * 4)

    def test_lost_lease_blocks_mutation_before_raw_command(self) -> None:
        tab = FakeTab()

        def lost() -> None:
            raise RuntimeError("lease lost")

        page = RawPage(tab, mutation_guard=lost)
        with self.assertRaisesRegex(RuntimeError, "lease lost"):
            _run(page.locator("button").click())
        self.assertEqual(tab.evals, [])

    def test_required_mode_blocks_fill_click_and_press_after_badge_or_url_loss(self) -> None:
        class LostOwnershipTab(FakeTab):
            _badge_label = "Codex"

            def __init__(self):
                super().__init__()
                self.live_url = "https://evil.example/phish"
                self.badge_present = False
                self.mutations = 0

            def eval(self, expr: str):
                if "vh-automation-badge" in expr:
                    if not self.badge_present or "jobkorea.co.kr" not in self.live_url:
                        return False
                if "e.value=" in expr or ".click()" in expr or "KeyboardEvent" in expr:
                    self.mutations += 1
                    return True
                return super().eval(expr)

        tab = LostOwnershipTab()
        page = RawPage(
            tab,
            initial_url="https://www.jobkorea.co.kr/Corp/Person/Find",
            require_badge=True,
        )
        for operation in (
            lambda: page.locator("input").fill("robotics"),
            lambda: page.locator("button").click(),
            lambda: page.locator("input").press("Enter"),
        ):
            with self.assertRaisesRegex(RuntimeError, "ownership"):
                _run(operation())
        self.assertEqual(tab.mutations, 0)

    def test_required_mode_rejects_missing_selector_instead_of_silent_success(self) -> None:
        class MissingSelectorTab(FakeTab):
            _badge_label = "Codex"

            def eval(self, expr: str):
                if "vh-automation-badge" in expr:
                    return False
                return super().eval(expr)

        page = RawPage(
            MissingSelectorTab(),
            initial_url="https://www.jobkorea.co.kr/Corp/Person/Find",
            require_badge=True,
        )
        with self.assertRaisesRegex(RuntimeError, "ownership"):
            _run(page.locator("button.missing").click())

    def test_required_mode_proves_badge_before_navigation(self) -> None:
        class BadgeLostTab(FakeTab):
            _badge_label = "Codex"

            def __init__(self):
                super().__init__()
                self.navigation_calls = 0

            def eval(self, expr: str):
                if "vh-automation-badge" in expr:
                    return False
                return super().eval(expr)

            def navigate(self, url: str, wait_ms: int = 0):
                self.navigation_calls += 1
                return {"loaderId": "must-not-run"}

            def wait_for_lifecycle(self, *_args):
                return None

            def mark_busy(self, _label: str, *, expected_url: str | None = None):
                return False

        tab = BadgeLostTab()
        with self.assertRaises(RuntimeError):
            _run(RawPage(
                tab,
                initial_url="https://www.jobkorea.co.kr/Corp/Person/Find",
                require_badge=True,
            ).goto(
                "https://www.jobkorea.co.kr/Corp/Person/Find?keyword=robotics",
                wait_until="domcontentloaded",
            ))
        self.assertEqual(tab.navigation_calls, 0)

    def test_required_navigation_uses_atomic_owned_navigation_command(self) -> None:
        class AtomicNavigationTab(FakeTab):
            _badge_label = "Codex"

            def __init__(self):
                super().__init__()
                self.atomic_calls = []
                self.refresh_calls = []

            def navigate(self, *_args, **_kwargs):
                raise AssertionError("separate Page.navigate is forbidden in required mode")

            def navigate_if_owned(self, url: str, *, expected_url: str, badge_label: str):
                self.atomic_calls.append((url, expected_url, badge_label))
                return {"ownershipAcknowledged": True, "lifecycleCursor": 0}

            def wait_for_next_lifecycle(self, cursor: int, event: str, timeout: float):
                self.asserted_lifecycle = (cursor, event, timeout)
                return "new-loader"

            def mark_busy(self, label: str, *, expected_url: str | None = None):
                self.refresh_calls.append((label, expected_url))
                return True

        origin = "https://www.jobkorea.co.kr/Corp/Person/Find"
        destination = origin + "?keyword=robotics"
        tab = AtomicNavigationTab()
        _run(RawPage(tab, initial_url=origin, require_badge=True).goto(
            destination,
            wait_until="domcontentloaded",
            timeout=1000,
        ))
        self.assertEqual(tab.atomic_calls, [(destination, origin, "Codex")])
        self.assertEqual(tab.asserted_lifecycle[:2], (0, "DOMContentLoaded"))
        self.assertEqual(tab.refresh_calls, [("Codex", destination)])

    def test_on_delegates_to_raw_tab_event_bridge(self) -> None:
        tab = FakeTab()
        page = RawPage(tab)
        handler = lambda _response: None
        page.on("response", handler)
        self.assertEqual(tab.events, [("response", handler)])


if __name__ == "__main__":
    unittest.main()
