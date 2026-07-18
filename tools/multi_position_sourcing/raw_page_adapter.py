"""raw CDP → playwright-page 어댑터 (TODO-2b 조각 B1, SOT-26 INV5).

사장님 크롬 탭 수백개면 playwright connectOverCDP 전체 attach 가 hang 하므로, 목표 탭
1개에만 raw CDP WebSocket 으로 붙는다(raw_cdp.CDPTab). 그런데 검색 실행부는 playwright
page/locator API 에 얽혀 있어, 그 표면만 raw_cdp 위에 재현하는 어댑터를 둔다.

selector·value 는 반드시 json.dumps 로 이스케이프해 JS 에 넣는다(injection·따옴표 안전).
eval 은 tab.eval(Runtime.evaluate, returnByValue) 1회 왕복. tab 주입으로 라이브 분리.

조각 B1 범위: locator/count/fill/click/inner_text/first, goto/wait_for_timeout/url.
page.on(이벤트 모니터=재로그인 감지)은 조각 B2 에서 배선(여기선 no-op).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


def _maybe_await(value: Any) -> Any:
    # tab.eval 이 동기(FakeTab)든 async(실 CDPTab 래핑)든 동일 처리.
    if asyncio.iscoroutine(value):
        return value
    return value


class RawLocator:
    def __init__(self, tab: Any, selector: str, index: int = 0) -> None:
        self._tab = tab
        self._selector = selector
        self._index = index

    @property
    def _sel_js(self) -> str:
        # querySelectorAll(<json selector>)[index] — 이스케이프로 injection 차단.
        return f"document.querySelectorAll({json.dumps(self._selector)})[{self._index}]"

    @property
    def first(self) -> "RawLocator":
        return RawLocator(self._tab, self._selector, index=0)

    async def count(self) -> int:
        expr = f"document.querySelectorAll({json.dumps(self._selector)}).length"
        return int(await _resolve(self._tab.eval(expr)) or 0)

    async def fill(self, value: str) -> None:
        el = self._sel_js
        expr = (
            "(function(){var e=" + el + ";if(!e)return false;"
            f"e.value={json.dumps(value)};"
            "e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));"
            "return true;})()"
        )
        await _resolve(self._tab.eval(expr))

    async def click(self) -> None:
        expr = "(function(){var e=" + self._sel_js + ";if(e)e.click();return !!e;})()"
        await _resolve(self._tab.eval(expr))

    async def inner_text(self) -> str:
        expr = "(function(){var e=" + self._sel_js + ";return e?e.innerText:'';})()"
        return str(await _resolve(self._tab.eval(expr)) or "")


class RawPage:
    def __init__(self, tab: Any) -> None:
        self._tab = tab

    def locator(self, selector: str) -> RawLocator:
        return RawLocator(self._tab, selector)

    async def goto(self, url: str, *, wait_until: str | None = None, timeout: int | None = None) -> None:
        wait_ms = int(timeout) if timeout else 4000
        result = self._tab.navigate(url, wait_ms=wait_ms)
        await _resolve(result)

    async def wait_for_timeout(self, ms: float) -> None:
        await asyncio.sleep(float(ms) / 1000.0)

    async def url(self) -> str:
        return str(await _resolve(self._tab.eval("location.href")) or "")

    def on(self, event: str, handler: Any) -> None:
        # 조각 B1: 이벤트 모니터(재로그인 감지)는 조각 B2 에서 CDP 이벤트로 배선.
        return None


async def _resolve(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value
