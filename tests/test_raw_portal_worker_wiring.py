"""PR #149 B2: profile-only 검색의 exact raw single-target 생산 배선."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools.multi_position_sourcing.portal_worker import (
    PortalWorker,
    PortalWorkerConfig,
    SearchLivenessMonitor,
)
from tools.multi_position_sourcing.raw_page_adapter import RawPage


class ForbiddenPlaywright:
    def __getattr__(self, name: str):
        raise AssertionError(f"raw mode must not touch Playwright: {name}")


class FakeRawTab:
    def __init__(self) -> None:
        self.disconnect_calls = 0
        self.fill_calls = 0
        self.click_calls = 0
        self.navigation_calls = 0
        self.badge_calls = 0
        self._badge_label = None

    def eval(self, expression: str):
        if "document.readyState" in expression:
            return "interactive"
        if "location.href" in expression:
            return "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
        if ".length" in expression and "querySelectorAll" in expression:
            return 1
        if "getAttribute" in expression:
            return "https://www.saramin.co.kr/zf_user/member/resume-view?idx=42"
        if "innerText" in expression:
            return "ROS2 robotics engineer"
        if "e.value=" in expression:
            self.fill_calls += 1
        if ".click()" in expression:
            self.click_calls += 1
        return None

    def navigate(self, _url: str, wait_ms: int = 0) -> None:
        self.navigation_calls += 1
        if wait_ms == 45000:
            raise AssertionError("Playwright timeout was misused as a fixed raw sleep")

    def on(self, _event: str, _handler: object) -> None:
        return None

    def mark_busy(self, label: str) -> bool:
        self._badge_label = label
        self.badge_calls += 1
        return True

    def disconnect(self) -> None:
        self.disconnect_calls += 1

    def __getattr__(self, name: str):
        if name == "close":
            return self.disconnect
        raise AttributeError(name)


class RawPortalWorkerWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_workers_share_one_channel_lock_regardless_of_worker_id(self) -> None:
        with TemporaryDirectory(prefix="raw-lock-a-") as root_a, TemporaryDirectory(
            prefix="raw-lock-b-"
        ) as root_b:
            first = PortalWorkerConfig(
                channel="saramin",
                worker_id="worker-a",
                profile_root=Path(root_a),
                connection_mode="raw_single_tab",
            )
            second = PortalWorkerConfig(
                channel="saramin",
                worker_id="worker-b",
                profile_root=Path(root_b),
                connection_mode="raw_single_tab",
            )
        self.assertEqual(first.lock_path, second.lock_path)

    async def test_raw_mode_attaches_exact_existing_target_without_playwright(self) -> None:
        fake_target = {
            "id": "fake",
            "type": "page",
            "url": "https://notsaramin.co.kr/zf_user/memcom",
            "webSocketDebuggerUrl": "ws://fake",
        }
        exact_target = {
            "id": "exact",
            "type": "page",
            "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "webSocketDebuggerUrl": "ws://exact",
        }
        tab = FakeRawTab()
        attached: list[dict] = []
        listed_endpoints: list[str] = []

        def attach(target: dict, badge: bool = True):
            self.assertFalse(badge)
            attached.append(target)
            return tab

        def list_pages(endpoint: str):
            listed_endpoints.append(endpoint)
            return [fake_target, exact_target]

        with TemporaryDirectory(prefix="raw-worker-") as root, patch(
            "tools.multi_position_sourcing.raw_cdp.list_pages",
            side_effect=list_pages,
        ), patch("tools.multi_position_sourcing.raw_cdp.attach", side_effect=attach):
            with patch(
                "tools.multi_position_sourcing.portal_worker.resolve_managed_channel_cdp_endpoint",
                return_value="http://127.0.0.1:9338",
            ):
                worker = PortalWorker(
                    PortalWorkerConfig(
                        channel="saramin",
                        profile_root=Path(root),
                        chrome_cdp_endpoint="http://127.0.0.1:9223",
                        connection_mode="raw_single_tab",
                    ),
                    playwright=ForbiddenPlaywright(),
                )
                await worker.start()
                result = await worker.run_one_search(
                    "robotics",
                    ready_check=lambda _page: _async_true(),
                )
                page = worker._raw_page
                await worker.stop()

        self.assertIs(page._tab, tab)
        self.assertEqual(attached, [exact_target])
        self.assertEqual(listed_endpoints, ["http://127.0.0.1:9338"])
        self.assertEqual(result.status, "searched")
        self.assertEqual(len(result.candidate_cards), 1)
        self.assertIn("idx=42", result.candidate_cards[0].profile_url)
        self.assertEqual(tab.fill_calls, 1)
        self.assertEqual(tab.click_calls, 1)
        self.assertGreaterEqual(tab.badge_calls, 2)
        self.assertEqual(tab.disconnect_calls, 1)
        self.assertIsNone(worker.browser)

    async def test_login_marker_is_proved_before_any_navigation(self) -> None:
        with TemporaryDirectory(prefix="raw-precheck-") as root:
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root),
                    connection_mode="raw_single_tab",
                )
            )
            tab = FakeRawTab()
            worker._raw_page = RawPage(
                tab,
                initial_url="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            )
            result = await worker._run_one_search_body(
                "robotics",
                ready_check=lambda _page: _async_false(),
            )
        self.assertEqual(result.status, "not_ready")
        self.assertEqual(tab.navigation_calls, 0)

    async def test_raw_start_fails_when_visible_marker_cannot_be_applied(self) -> None:
        target = {
            "id": "exact",
            "type": "page",
            "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "webSocketDebuggerUrl": "ws://exact",
        }

        class MarkerFailTab(FakeRawTab):
            def mark_busy(self, _label: str) -> bool:
                return False

        tab = MarkerFailTab()
        with TemporaryDirectory(prefix="raw-badge-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.resolve_managed_channel_cdp_endpoint",
            return_value="http://127.0.0.1:9223",
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.list_pages",
            return_value=[target],
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.attach",
            return_value=tab,
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root),
                    connection_mode="raw_single_tab",
                )
            )
            try:
                with self.assertRaises(RuntimeError):
                    await worker.start()
            finally:
                await worker.stop()
        self.assertEqual(tab.disconnect_calls, 1)

    async def test_raw_monitor_reads_fresh_login_redirect_url(self) -> None:
        class RedirectTab(FakeRawTab):
            def eval(self, expression: str):
                if "location.href" in expression:
                    return "https://www.saramin.co.kr/zf_user/auth?ut=c"
                return super().eval(expression)

        cause = await SearchLivenessMonitor("saramin").check_page(
            RawPage(RedirectTab(), initial_url="https://www.saramin.co.kr/")
        )
        self.assertEqual(cause, "login_redirect")


async def _async_true() -> bool:
    return True


async def _async_false() -> bool:
    return False


if __name__ == "__main__":
    unittest.main()
