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

from .raw_cdp import _badge_identity_js, _badge_visibility_js


MutationGuard = Callable[[], Any]
OwnershipUrl = Callable[[], str]
_BADGE_ID = "vh-automation-badge"


def _ownership_js(expected_url: str, badge_label: str, action: str = "return true;") -> str:
    return (
        "(function(){"
        f"if(location.href!=={json.dumps(expected_url)})return false;"
        f"var b=document.getElementById({json.dumps(_BADGE_ID)});"
        "if(!b)return false;"
        + _badge_identity_js("b", badge_label, "return false;")
        + _badge_visibility_js("b", "return false;")
        + action
        + "})()"
    )


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
        ownership_url: OwnershipUrl | None = None,
        require_badge: bool = False,
    ) -> None:
        self._tab = tab
        self._selector = selector
        self._index = index
        self._mutation_guard = mutation_guard
        self._ownership_url = ownership_url
        self._require_badge = require_badge

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
            ownership_url=self._ownership_url,
            require_badge=self._require_badge,
        )

    def nth(self, index: int) -> "RawLocator":
        return RawLocator(
            self._tab,
            self._selector,
            index=index,
            mutation_guard=self._mutation_guard,
            ownership_url=self._ownership_url,
            require_badge=self._require_badge,
        )

    async def count(self) -> int:
        expr = f"{self._elements_js}.length"
        return int(await _tab_call(self._tab, "eval", expr) or 0)

    async def is_visible(self) -> bool:
        element = self._sel_js
        expr = (
            "(function(){var e=" + element + ";if(!e)return false;"
            "var s=window.getComputedStyle(e);"
            "var r=e.getBoundingClientRect();"
            "return s.display!=='none'&&s.visibility!=='hidden'&&"
            "s.opacity!=='0'&&r.width>0&&r.height>0;})()"
        )
        return await _tab_call(self._tab, "eval", expr) is True

    async def fill(self, value: str, **_kwargs: Any) -> None:
        await _run_mutation_guard(self._mutation_guard)
        el = self._sel_js
        action = (
            "var e=" + el + ";if(!e)return false;"
            f"e.value={json.dumps(value)};"
            "e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));"
            "return true;"
        )
        await self._run_mutation(action)

    async def click(self, **_kwargs: Any) -> None:
        await _run_mutation_guard(self._mutation_guard)
        action = "var e=" + self._sel_js + ";if(!e)return false;e.click();return true;"
        await self._run_mutation(action)

    async def press(self, key: str, **_kwargs: Any) -> None:
        await _run_mutation_guard(self._mutation_guard)
        key_js = json.dumps(key)
        action = (
            "var e=" + self._sel_js + ";if(!e)return false;"
            f"var k={key_js};"
            "['keydown','keypress','keyup'].forEach(function(t){"
            "e.dispatchEvent(new KeyboardEvent(t,{key:k,bubbles:true}));});"
            "if(k==='Enter'&&e.form&&e.form.requestSubmit){e.form.requestSubmit();}"
            "return true;"
        )
        await self._run_mutation(action)

    async def _run_mutation(self, action: str) -> None:
        if self._require_badge:
            expected_url = self._ownership_url() if self._ownership_url else ""
            label = str(getattr(self._tab, "_badge_label", "") or "")
            if not expected_url or not label:
                raise RuntimeError("raw DOM ownership proof is missing")
            rendered = getattr(self._tab, "prove_badge_rendered", None)
            if not callable(rendered) or await _tab_call(
                self._tab,
                "prove_badge_rendered",
                expected_url=expected_url,
                badge_label=label,
            ) is not True:
                raise RuntimeError("raw rendered badge ownership proof failed")
            # Rendering proof performs multiple CDP round trips. Recheck the
            # canonical lease/owner-idle barrier at the actual mutation boundary.
            await _run_mutation_guard(self._mutation_guard)
            owned_eval = getattr(self._tab, "eval_if_badge_owned", None)
            if not callable(owned_eval):
                raise RuntimeError("raw proven badge object action is unavailable")
            acknowledged = await _tab_call(
                self._tab,
                "eval_if_badge_owned",
                action,
                expected_url=expected_url,
                badge_label=label,
            )
            if acknowledged is not True:
                raise RuntimeError("raw DOM ownership or selector proof failed")
            return
        expr = "(function(){" + action + "})()"
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
            ownership_url=lambda: self._url,
            require_badge=self._require_badge,
        )

    async def _prove_dom_ownership(self, expected_url: str) -> None:
        label = str(getattr(self._tab, "_badge_label", "") or "")
        if not expected_url or not label:
            raise RuntimeError("raw DOM ownership proof is missing")
        acknowledged = await _tab_call(
            self._tab,
            "eval",
            _ownership_js(expected_url, label),
        )
        if acknowledged is not True:
            raise RuntimeError("raw DOM ownership proof failed")

    async def _refresh_busy_badge(self, *, expected_url: str | None = None) -> None:
        label = getattr(self._tab, "_badge_label", None)
        marker = getattr(self._tab, "mark_busy", None)
        if not label or not callable(marker):
            if self._require_badge:
                raise RuntimeError("visible automation marker is missing")
            return
        await _run_mutation_guard(self._mutation_guard)
        if expected_url is None:
            expected_url = str(
                await _tab_call(self._tab, "eval", "location.href") or ""
            )
        applied = await _tab_call(
            self._tab,
            "mark_busy",
            label,
            expected_url=expected_url,
        )
        if self._require_badge and applied is not True:
            raise RuntimeError("visible automation marker refresh failed")

    async def goto(self, url: str, *, wait_until: str | None = None, timeout: int | None = None) -> None:
        origin_url = self._url
        timeout_seconds = float(timeout) / 1000.0 if timeout and timeout > 0 else 30.0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        await _run_mutation_guard(self._mutation_guard)
        if self._require_badge:
            label = str(getattr(self._tab, "_badge_label", "") or "")
            navigator = getattr(self._tab, "navigate_if_owned", None)
            lifecycle = getattr(self._tab, "wait_for_next_lifecycle", None)
            if not origin_url or not label or not callable(navigator) or not callable(lifecycle):
                raise RuntimeError("raw atomic navigation/loader proof is unavailable")
            rendered = getattr(self._tab, "prove_badge_rendered", None)
            if not callable(rendered) or await _tab_call(
                self._tab,
                "prove_badge_rendered",
                expected_url=origin_url,
                badge_label=label,
            ) is not True:
                raise RuntimeError("raw rendered badge ownership proof failed")
            # The owner can return while the compositor proof is running.
            await _run_mutation_guard(self._mutation_guard)
            navigation = await asyncio.wait_for(
                _tab_call(
                    self._tab,
                    "navigate_if_owned",
                    url,
                    expected_url=origin_url,
                    badge_label=label,
                ),
                timeout=timeout_seconds,
            )
            if not isinstance(navigation, dict) or navigation.get("ownershipAcknowledged") is not True:
                raise RuntimeError("raw DOM ownership proof failed before navigation")
            cursor = navigation.get("lifecycleCursor")
            if isinstance(cursor, bool) or not isinstance(cursor, int):
                raise RuntimeError("raw navigation loader proof is missing")
            if wait_until is None:
                wait_until = "domcontentloaded"
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
                    "wait_for_next_lifecycle",
                    cursor,
                    lifecycle_name,
                    remaining,
                ),
                timeout=remaining,
            )
            self._url = url
            await self._refresh_busy_badge(expected_url=url)
            return
        action = _tab_call(self._tab, "navigate", url, wait_ms=0)
        navigation = await asyncio.wait_for(action, timeout=timeout_seconds)
        if isinstance(navigation, dict):
            if navigation.get("errorText"):
                raise RuntimeError("raw navigation failed")
            if navigation.get("isDownload") is True:
                raise RuntimeError("raw navigation download was rejected")
        self._url = url
        loader_id = ""
        if isinstance(navigation, dict):
            loader_id = str(navigation.get("loaderId") or "")
        if wait_until is None:
            return
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
            await self._refresh_busy_badge(expected_url=url)
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
                await self._refresh_busy_badge(expected_url=url)
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
