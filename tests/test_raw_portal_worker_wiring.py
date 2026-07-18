"""PR #149 B2: profile-only 검색의 exact raw single-target 생산 배선."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools.multi_position_sourcing.portal_worker import PortalWorker, PortalWorkerConfig


class ForbiddenPlaywright:
    def __getattr__(self, name: str):
        raise AssertionError(f"raw mode must not touch Playwright: {name}")


class FakeRawTab:
    def __init__(self) -> None:
        self.disconnect_calls = 0

    def eval(self, expression: str):
        if "location.href" in expression:
            return "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
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
            page = await worker._acquire_search_page()
            await worker.stop()

        self.assertIs(page._tab, tab)
        self.assertEqual(attached, [exact_target])
        self.assertEqual(tab.disconnect_calls, 1)
        self.assertIsNone(worker.browser)


if __name__ == "__main__":
    unittest.main()
