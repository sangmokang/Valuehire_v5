"""검색 페이지 획득 추상화 (TODO-2b 조각 B2a).

_run_one_search_body 가 self.context.new_page() 로 직접 페이지를 얻던 것을
self._acquire_search_page() 로 추상화한다. 기본(launch/linkedin) 동작은 100% 보존
— context.new_page() 위임. 조각 B2b 에서 raw attach 채널은 RawPage 를 반환하도록 override.
이 조각은 순수 리팩터라 기존 검색 테스트가 전부 그대로 통과해야 한다(회귀 0).
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.multi_position_sourcing.portal_worker import PortalWorker, PortalWorkerConfig


class FakePage:
    pass


class FakeContext:
    def __init__(self) -> None:
        self.new_page_calls = 0
        self._page = FakePage()

    async def new_page(self) -> FakePage:
        self.new_page_calls += 1
        return self._page


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class AcquireSearchPageTests(unittest.TestCase):
    def _worker(self, root: str) -> PortalWorker:
        cfg = PortalWorkerConfig(
            channel="saramin", profile_root=Path(root),
            chrome_cdp_endpoint="http://127.0.0.1:9223")
        return PortalWorker(cfg, playwright=object())

    def test_acquire_search_page_delegates_to_context_new_page(self) -> None:
        # 기본 동작 보존: _acquire_search_page 는 context.new_page() 를 호출하고 그 page 반환.
        with TemporaryDirectory(prefix="asp_") as root:
            w = self._worker(root)
            ctx = FakeContext()
            w._context = ctx  # start() 우회, context 직접 주입
            page = _run(w._acquire_search_page())
            self.assertIs(page, ctx._page)
            self.assertEqual(ctx.new_page_calls, 1)


if __name__ == "__main__":
    unittest.main()
