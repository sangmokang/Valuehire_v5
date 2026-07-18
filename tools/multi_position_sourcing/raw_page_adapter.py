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
import inspect
import json
import re
from typing import Any, Callable


MutationGuard = Callable[[], Any]


async def _run_mutation_guard(guard: MutationGuard | None) -> None:
    if guard is None:
        return
    if inspect.iscoroutinefunction(guard):
        await guard()
        return
    result = await asyncio.to_thread(guard)
    if asyncio.iscoroutine(result):
        await result


async def _tab_call(tab: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    """Run blocking raw-CDP calls off the event loop; keep async fakes supported."""
    fn = getattr(tab, method)
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    result = await asyncio.to_thread(fn, *args, **kwargs)
    if asyncio.iscoroutine(result):
        return await result
    return result


class RawLocator:
    def __init__(
        self,
        tab: Any,
        selector: str,
        index: int = 0,
        mutation_guard: MutationGuard | None = None,
    ) -> None:
        self._tab = tab
        self._selector = selector
        self._index = index
        self._mutation_guard = mutation_guard

    @property
    def _elements_js(self) -> str:
        """Translate the small Playwright text pseudo-selector used by our map."""
        match = re.fullmatch(r"(.+):has-text\((['\"])(.*?)\2\)", self._selector)
        if match:
            base, _quote, text = match.groups()
            return (
                f"Array.from(document.querySelectorAll({json.dumps(base)}))"
                ".filter(function(e){return (e.innerText||'').includes("
                f"{json.dumps(text)});}})"
            )
        return f"document.querySelectorAll({json.dumps(self._selector)})"

    @property
    def _sel_js(self) -> str:
        return f"{self._elements_js}[{self._index}]"

    @property
    def first(self) -> "RawLocator":
        return RawLocator(
            self._tab,
            self._selector,
            index=0,
            mutation_guard=self._mutation_guard,
        )

    def nth(self, index: int) -> "RawLocator":
        return RawLocator(
            self._tab,
            self._selector,
            index=index,
            mutation_guard=self._mutation_guard,
        )

    async def count(self) -> int:
        expr = f"{self._elements_js}.length"
        return int(await _tab_call(self._tab, "eval", expr) or 0)

    async def fill(self, value: str, **_kwargs: Any) -> None:
        await _run_mutation_guard(self._mutation_guard)
        el = self._sel_js
        expr = (
            "(function(){var e=" + el + ";if(!e)return false;"
            f"e.value={json.dumps(value)};"
            "e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));"
            "return true;})()"
        )
        await _tab_call(self._tab, "eval", expr)

    async def click(self, **_kwargs: Any) -> None:
        await _run_mutation_guard(self._mutation_guard)
        expr = "(function(){var e=" + self._sel_js + ";if(e)e.click();return !!e;})()"
        await _tab_call(self._tab, "eval", expr)

    async def press(self, key: str, **_kwargs: Any) -> None:
        await _run_mutation_guard(self._mutation_guard)
        key_js = json.dumps(key)
        expr = (
            "(function(){var e=" + self._sel_js + ";if(!e)return false;"
            f"var k={key_js};"
            "['keydown','keypress','keyup'].forEach(function(t){"
            "e.dispatchEvent(new KeyboardEvent(t,{key:k,bubbles:true}));});"
            "if(k==='Enter'&&e.form&&e.form.requestSubmit){e.form.requestSubmit();}"
            "return true;})()"
        )
        await _tab_call(self._tab, "eval", expr)

    async def get_attribute(self, name: str) -> str | None:
        expr = (
            "(function(){var e=" + self._sel_js + ";return e?e.getAttribute("
            + json.dumps(name) + "):null;})()"
        )
        value = await _tab_call(self._tab, "eval", expr)
        return None if value is None else str(value)

    async def inner_text(self, **_kwargs: Any) -> str:
        expr = "(function(){var e=" + self._sel_js + ";return e?e.innerText:'';})()"
        return str(await _tab_call(self._tab, "eval", expr) or "")


class RawPage:
    def __init__(
        self,
        tab: Any,
        *,
        initial_url: str = "",
        require_badge: bool = False,
        mutation_guard: MutationGuard | None = None,
    ) -> None:
        self._tab = tab
        self._url = initial_url
        self._require_badge = require_badge
        self._mutation_guard = mutation_guard

    def locator(self, selector: str) -> RawLocator:
        return RawLocator(
            self._tab,
            selector,
            mutation_guard=self._mutation_guard,
        )

    async def _refresh_busy_badge(self) -> None:
        label = getattr(self._tab, "_badge_label", None)
        marker = getattr(self._tab, "mark_busy", None)
        if not label or not callable(marker):
            if self._require_badge:
                raise RuntimeError("visible automation marker is missing")
            return
        await _run_mutation_guard(self._mutation_guard)
        applied = await _tab_call(self._tab, "mark_busy", label)
        if self._require_badge and applied is not True:
            raise RuntimeError("visible automation marker refresh failed")

    async def goto(self, url: str, *, wait_until: str | None = None, timeout: int | None = None) -> None:
        self._url = url
        timeout_seconds = float(timeout) / 1000.0 if timeout and timeout > 0 else 30.0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        await _run_mutation_guard(self._mutation_guard)
        action = _tab_call(self._tab, "navigate", url, wait_ms=0)
        navigation = await asyncio.wait_for(action, timeout=timeout_seconds)
        if isinstance(navigation, dict):
            if navigation.get("errorText"):
                raise RuntimeError("raw navigation failed")
            if navigation.get("isDownload") is True:
                raise RuntimeError("raw navigation download was rejected")
        if wait_until is None:
            return
        loader_id = ""
        if isinstance(navigation, dict):
            loader_id = str(navigation.get("loaderId") or "")
        if self._require_badge and not loader_id:
            raise RuntimeError("raw navigation loader proof is missing")
        lifecycle = getattr(self._tab, "wait_for_lifecycle", None)
        if loader_id and callable(lifecycle):
            lifecycle_name = {
                "domcontentloaded": "DOMContentLoaded",
                "load": "load",
                "networkidle": "networkIdle",
                "commit": "init",
            }.get(wait_until, "DOMContentLoaded")
            remaining = max(0.001, deadline - loop.time())
            await asyncio.wait_for(
                _tab_call(
                    self._tab,
                    "wait_for_lifecycle",
                    loader_id,
                    lifecycle_name,
                    remaining,
                ),
                timeout=remaining,
            )
            await self._refresh_busy_badge()
            return
        ready_states = {"complete"}
        if wait_until in {"domcontentloaded", "commit"}:
            ready_states.add("interactive")
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"raw navigation did not reach {wait_until}")
            state = str(await asyncio.wait_for(
                _tab_call(self._tab, "eval", "document.readyState"),
                timeout=remaining,
            ) or "")
            if state in ready_states:
                await self._refresh_busy_badge()
                return
            await asyncio.sleep(min(0.1, remaining))

    async def wait_for_timeout(self, ms: float) -> None:
        await asyncio.sleep(float(ms) / 1000.0)

    @property
    def url(self) -> str:
        return self._url

    async def current_url(self) -> str:
        value = await _tab_call(self._tab, "eval", "location.href")
        if value:
            self._url = str(value)
        return self._url

    def on(self, event: str, handler: Any) -> None:
        subscribe = getattr(self._tab, "on", None)
        if callable(subscribe):
            subscribe(event, handler)
