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

    def eval(self, expression: str):
        if "location.href" in expression:
            return "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
        if ".length" in expression and "querySelectorAll" in expression:
            return 1
        if "getAttribute" in expression:
            return "https://www.saramin.co.kr/zf_user/member/resume-view?idx=42"
        if "innerText" in expression:
            return "ROS2 robotics engineer"
        return None

    def navigate(self, _url: str, wait_ms: int = 0) -> None:
        if wait_ms == 45000:
            raise AssertionError("Playwright timeout was misused as a fixed raw sleep")

    def on(self, _event: str, _handler: object) -> None:
        return None

    def disconnect(self) -> None:
        self.disconnect_calls += 1

    def __getattr__(self, name: str):
        if name == "close":
            return self.disconnect
        raise AttributeError(name)


class RawPortalWorkerWiringTests(unittest.IsolatedAsyncioTestCase):
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

        def attach(target: dict):
            attached.append(target)
            return tab

        with TemporaryDirectory(prefix="raw-worker-") as root, patch(
            "tools.multi_position_sourcing.raw_cdp.list_pages",
            return_value=[fake_target, exact_target],
        ), patch("tools.multi_position_sourcing.raw_cdp.attach", side_effect=attach):
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
        self.assertEqual(result.status, "searched")
        self.assertEqual(len(result.candidate_cards), 1)
        self.assertIn("idx=42", result.candidate_cards[0].profile_url)
        self.assertEqual(tab.disconnect_calls, 1)
        self.assertIsNone(worker.browser)

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


if __name__ == "__main__":
    unittest.main()
