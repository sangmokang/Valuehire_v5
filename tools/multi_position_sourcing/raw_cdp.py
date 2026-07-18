"""raw CDP 단일타깃 드라이버 — 사장님 9222 탭 과다 환경에서 connectOverCDP 전체 attach hang 회피.

websocket-client(동기)로 *한 개* page 타깃에만 붙어 Page.navigate / Runtime.evaluate /
Page.captureScreenshot 를 친다. humansearch 순회에서 재사용.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from types import SimpleNamespace
from typing import Any

# websocket(websocket-client)는 실제 CDP 연결(CDPTab)에서만 필요하다. 모듈 최상단에서 import 하면
# 이 모듈을 재사용하는 순수 로직(예: humansearch_cdp_run 의 하드제외 함수)을 라이브 브라우저·websocket
# 없는 환경(CI)에서 테스트할 수 없다 → 연결 시점으로 지연 import 한다.


_CDP_DEFAULT = "http://localhost:9222"
# 하위호환: 예전처럼 raw_cdp.CDP_HTTP 상수를 참조/대입하던 코드를 위해 이름은 남긴다.
# 실제 붙는 엔드포인트는 _cdp_base() 가 호출 시점에 결정한다(아래).
CDP_HTTP = _CDP_DEFAULT


def _cdp_base() -> str:
    """붙을 CDP HTTP 엔드포인트를 호출 시점에 결정한다.

    포트를 못박지 않는다 — 크롬이 표준 포트가 아닌 곳(예: 링크드인 9338)에 떠도
    CDP_HTTP env(예: `portal_browsers.sh cdp linkedin` 결과)로 그 엔드포인트에 붙는다.
    env 미설정 시 예전 기본값(9222)로 폴백. import 시점이 아닌 호출 시점에 읽으므로
    auto_send_runner 처럼 import 뒤 늦게 env 를 set 하는 패턴도 살아난다.
    """
    return os.environ.get("CDP_HTTP") or CDP_HTTP or _CDP_DEFAULT


def _http_get(path: str, *, endpoint: str | None = None) -> Any:
    base = (endpoint or _cdp_base()).rstrip("/")
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return json.loads(r.read().decode())


# ── 점유 표시 배지 ──────────────────────────────────────────────────────
# 자동화(Claude/Codex)가 브라우저를 점유해 서치를 도는 동안, 그 화면에 "사용중"을 띄운다.
# 사장님이 바로 보고, 봇처럼 몰래 굴지 않는다(SOT 투명성). 배지는 부가기능 —
# 주입 실패가 실제 서치를 절대 깨지 않게 모든 호출을 best-effort 로 감싼다.
_BADGE_ID = "vh-automation-badge"
_BADGE_OFF_VALUES = {"1", "true", "yes", "on"}


def _resolve_badge_label(env: Any) -> str | None:
    """env 로 배지 라벨을 만든다. VH_BADGE_OFF 면 None(표시 안 함)."""
    off = str(env.get("VH_BADGE_OFF", "")).strip().lower()
    if off in _BADGE_OFF_VALUES:
        return None
    agent = (env.get("VH_BUSY_AGENT") or "").strip() or "Claude"
    task = (env.get("VH_BUSY_TASK") or "").strip()
    base = f"🤖 {agent} 자동화 사용중"
    return f"{base} · {task}" if task else base


def _badge_js(label: str) -> str:
    """상단중앙 고정 배지 주입 JS. pointer-events:none 로 사장님 클릭을 막지 않는다.
    idempotent: 기존 배지를 먼저 제거해 중복이 쌓이지 않는다."""
    text = json.dumps(label, ensure_ascii=False)
    return (
        "(function(){"
        f"var id={json.dumps(_BADGE_ID)};"
        "var e=document.getElementById(id);"
        "if(e){e.remove();}"
        "e=document.createElement('div');"
        "e.id=id;"
        f"e.textContent={text};"
        "e.style.cssText='position:fixed;top:0;left:50%;transform:translateX(-50%);"
        "z-index:2147483647;pointer-events:none;"
        "background:rgba(220,38,38,0.95);color:#fff;"
        "font:600 13px/1.6 -apple-system,BlinkMacSystemFont,sans-serif;"
        "padding:4px 14px;border-radius:0 0 8px 8px;box-shadow:0 2px 8px rgba(0,0,0,.3);"
        "letter-spacing:.2px;white-space:nowrap;';"
        "(document.body||document.documentElement).appendChild(e);"
        "return id;})()"
    )


def _clear_js() -> str:
    return (
        "(function(){"
        f"var e=document.getElementById({json.dumps(_BADGE_ID)});"
        "if(e){e.remove();}return true;})()"
    )


def list_pages(endpoint: str | None = None) -> list[dict]:
    """Return page targets from one explicit endpoint without mutating global env."""
    return [t for t in _http_get("/json", endpoint=endpoint) if t.get("type") == "page"]


def new_tab(url: str = "about:blank") -> dict:
    # PUT /json/new?{url}
    req = urllib.request.Request(_cdp_base() + "/json/new?" + url, method="PUT")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def find_page_by_url(substr: str) -> dict | None:
    for t in list_pages():
        if substr in (t.get("url") or ""):
            return t
    return None


class CDPTab:
    def __init__(self, ws_url: str):
        # Chrome rejects ws handshakes carrying an Origin header unless launched with
        # --remote-allow-origins. Suppressing the Origin header sidesteps the 403.
        import websocket  # websocket-client (지연 import — 라이브 연결 시점에만 필요)

        self.ws = websocket.create_connection(
            ws_url, max_size=None, timeout=60, suppress_origin=True
        )
        self._id = 0
        self._badge_label: str | None = None
        self._event_handlers: dict[str, list[Any]] = {}
        self._lifecycle_events: list[tuple[str, str]] = []
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("Network.enable")
        self.send("Page.setLifecycleEventsEnabled", {"enabled": True})

    def on(self, event: str, handler: Any) -> None:
        """Register the small Playwright-style event surface used by the worker."""
        self._event_handlers.setdefault(event, []).append(handler)

    def _dispatch_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params") or {}
        event = ""
        payload: Any = None
        if method == "Network.responseReceived":
            response = params.get("response") or {}
            event = "response"
            payload = SimpleNamespace(
                status=response.get("status", 0),
                url=response.get("url", ""),
            )
        elif method == "Page.frameNavigated":
            frame = params.get("frame") or {}
            event = "framenavigated"
            payload = SimpleNamespace(url=frame.get("url", ""))
        elif method == "Page.lifecycleEvent":
            loader_id = str(params.get("loaderId") or "")
            name = str(params.get("name") or "")
            if loader_id and name:
                self._lifecycle_events.append((loader_id, name))
        if not event:
            return
        for handler in tuple(self._event_handlers.get(event, ())):
            try:
                handler(payload)
            except Exception:
                continue

    def send(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.ws.settimeout(max(0.1, deadline - time.time()))
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                continue
            if "method" in msg:
                self._dispatch_event(msg)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method} error: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(f"{method} timed out")

    def mark_busy(self, label: str) -> bool:
        """화면에 '사용중' 배지를 띄운다. 라벨을 기억해 navigate 후 재주입한다.
        배지는 부가기능 — 주입 실패해도 예외를 던지지 않는다(실 서치 보호)."""
        self._badge_label = label
        try:
            self.eval(_badge_js(label))
        except Exception:
            return False
        return True

    def clear_badge(self) -> None:
        self._badge_label = None
        try:
            self.eval(_clear_js())
        except Exception:
            pass

    def navigate(self, url: str, wait_ms: int = 4000) -> dict:
        result = self.send("Page.navigate", {"url": url})
        time.sleep(wait_ms / 1000)
        # 페이지 로드로 배지가 사라지므로, 점유 중이면 다시 붙인다(best-effort).
        if getattr(self, "_badge_label", None):
            try:
                self.eval(_badge_js(self._badge_label))
            except Exception:
                pass
        return result

    def wait_for_lifecycle(
        self,
        loader_id: str,
        event: str,
        timeout: float = 30.0,
    ) -> None:
        """Wait for a lifecycle event belonging to the new navigation loader."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            wanted = (loader_id, event)
            if wanted in self._lifecycle_events:
                self._lifecycle_events.remove(wanted)
                return
            self.ws.settimeout(max(0.1, deadline - time.time()))
            try:
                message = json.loads(self.ws.recv())
            except Exception:
                continue
            if "method" in message:
                self._dispatch_event(message)
        raise TimeoutError(f"Page lifecycle event timed out: {event}")

    def eval(self, expr: str) -> Any:
        r = self.send("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
        })
        return r.get("result", {}).get("value")

    def screenshot(self, path: str) -> str:
        r = self.send("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(r["data"])
        with open(path, "wb") as f:
            f.write(data)
        return path

    def close(self):
        # 작업 끝 → 배지 제거(사장님이 이어받을 때 '사용중' 잔상 안 남게).
        try:
            if getattr(self, "_badge_label", None):
                self.eval(_clear_js())
        except Exception:
            pass
        try:
            self.ws.close()
        except Exception:
            pass


def _maybe_auto_badge(tab: "CDPTab", env: Any) -> None:
    """attach 직후 env 로 배지를 자동 표시(모든 서치 공통 경로). 실패해도 무해."""
    label = _resolve_badge_label(env)
    if label:
        tab.mark_busy(label)


def attach(target: dict, badge: bool = True) -> CDPTab:
    tab = CDPTab(target["webSocketDebuggerUrl"])
    if badge:
        try:
            _maybe_auto_badge(tab, os.environ)
        except Exception:
            pass
    return tab
