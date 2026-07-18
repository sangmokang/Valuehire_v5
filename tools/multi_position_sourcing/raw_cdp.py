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


def _badge_visibility_js(element: str, failure: str) -> str:
    """Return fail-closed rendered visibility proof for one badge element variable."""
    return (
        f"if(typeof {element}.checkVisibility==='function'&&!{element}.checkVisibility("
        "{checkOpacity:true,checkVisibilityCSS:true,contentVisibilityAuto:true}))"
        "{" + failure + "}"
        f"for(var n={element};n&&n.nodeType===1;n=n.parentElement){{"
        "var s=window.getComputedStyle(n);"
        "var cp=s.clipPath||s.webkitClipPath||'none';"
        "var mi=s.maskImage||s.webkitMaskImage||'none';"
        "if(s.display==='none'||s.visibility==='hidden'||s.visibility==='collapse'||"
        "s.opacity==='0'||s.contentVisibility==='hidden'||"
        "(s.filter&&s.filter!=='none')||(cp&&cp!=='none')||(mi&&mi!=='none')||"
        "(s.clip&&s.clip!=='auto')||(s.mixBlendMode&&s.mixBlendMode!=='normal'))"
        "{" + failure + "}}"
        f"var r={element}.getBoundingClientRect();"
        "if(r.width<=0||r.height<=0||r.bottom<=0||r.right<=0||"
        "r.top>=window.innerHeight||r.left>=window.innerWidth)"
        "{" + failure + "}"
        "function vhAlpha(c){if(!c||c==='transparent')return 0;"
        "var m=c.match(/rgba?\\(([^)]+)\\)/);if(!m)return 0;"
        "var p=m[1].split(',');return p.length>3?parseFloat(p[3]):1;}"
        f"var cs=window.getComputedStyle({element});"
        "if(vhAlpha(cs.backgroundColor)<=0||vhAlpha(cs.color)<=0)"
        "{" + failure + "}"
        f"{element}.style.setProperty('pointer-events','auto','important');"
        "var pts=[[r.left+r.width/2,r.top+r.height/2],"
        "[r.left+2,r.top+2],[r.right-2,r.top+2],"
        "[r.left+2,r.bottom-2],[r.right-2,r.bottom-2]];"
        "var hit=true;for(var i=0;i<pts.length;i++){"
        "var x=Math.max(0,Math.min(window.innerWidth-1,pts[i][0]));"
        "var y=Math.max(0,Math.min(window.innerHeight-1,pts[i][1]));"
        "var h=document.elementFromPoint(x,y);"
        f"if(h!=={element}&&!{element}.contains(h)){{hit=false;break;}}}}"
        f"{element}.style.setProperty('pointer-events','none','important');"
        "if(!hit){" + failure + "}"
    )


def _badge_js(label: str, *, expected_url: str | None = None) -> str:
    """상단중앙 고정 배지 주입 JS. pointer-events:none 로 사장님 클릭을 막지 않는다.
    idempotent: 기존 배지를 먼저 제거해 중복이 쌓이지 않는다."""
    text = json.dumps(label, ensure_ascii=False)
    url_guard = ""
    if expected_url is not None:
        url_guard = (
            f"if(location.href!=={json.dumps(expected_url, ensure_ascii=False)})"
            "{return null;}"
        )
    return (
        "(function(){"
        + url_guard
        + f"var id={json.dumps(_BADGE_ID)};"
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
        "[['position','fixed'],['top','0px'],['left','50%'],"
        "['transform','translateX(-50%)'],['z-index','2147483647'],"
        "['display','block'],['visibility','visible'],['opacity','1'],"
        "['pointer-events','none'],['background-color','rgba(220,38,38,0.95)'],"
        "['color','#fff'],['filter','none'],['clip-path','none'],"
        "['mask-image','none'],['mix-blend-mode','normal'],"
        "['backface-visibility','visible'],['contain','none']].forEach(function(p){"
        "e.style.setProperty(p[0],p[1],'important');});"
        "(document.body||document.documentElement).appendChild(e);"
        + _badge_visibility_js("e", "e.remove();return null;")
        + "return id;})()"
    )


def _clear_js(*, expected_url: str | None = None) -> str:
    url_guard = ""
    if expected_url is not None:
        url_guard = (
            f"if(location.href!=={json.dumps(expected_url, ensure_ascii=False)})"
            "{return false;}"
        )
    return (
        "(function(){"
        + url_guard
        + f"var e=document.getElementById({json.dumps(_BADGE_ID)});"
        "if(e){e.remove();}return true;})()"
    )


def _owned_navigation_js(
    url: str,
    *,
    expected_url: str,
    badge_label: str,
) -> str:
    return (
        "(function(){"
        f"if(location.href!=={json.dumps(expected_url)})return false;"
        f"var b=document.getElementById({json.dumps(_BADGE_ID)});"
        f"if(!b||b.textContent!=={json.dumps(badge_label, ensure_ascii=False)})return false;"
        + _badge_visibility_js("b", "return false;")
        + f"var u={json.dumps(url)};"
        "location.assign(u);return true;})()"
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
        self._badge_bound_url: str | None = None
        self._badge_application_uncertain = False
        self._event_handlers: dict[str, list[Any]] = {}
        self._lifecycle_events: list[tuple[str, str]] = []
        try:
            self.send("Page.enable")
            self.send("Runtime.enable")
            self.send("Network.enable")
            self.send("Page.setLifecycleEventsEnabled", {"enabled": True})
        except BaseException:
            try:
                self.ws.close()
            except Exception:
                pass
            raise

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

    def mark_busy(self, label: str, *, expected_url: str | None = None) -> bool:
        """화면에 '사용중' 배지를 띄운다. 라벨을 기억해 navigate 후 재주입한다.
        배지는 부가기능 — 주입 실패해도 예외를 던지지 않는다(실 서치 보호)."""
        self._badge_label = label
        self._badge_bound_url = expected_url
        self._badge_application_uncertain = True
        try:
            acknowledged = self.eval(_badge_js(label, expected_url=expected_url))
        except Exception:
            return False
        self._badge_application_uncertain = False
        if acknowledged == _BADGE_ID:
            return True
        self._badge_bound_url = None
        return False

    @property
    def badge_application_uncertain(self) -> bool:
        return bool(getattr(self, "_badge_application_uncertain", False))

    def clear_badge(self) -> None:
        self._badge_label = None
        try:
            self.eval(_clear_js())
        except Exception:
            pass

    def navigate_if_owned(
        self,
        url: str,
        *,
        expected_url: str,
        badge_label: str,
    ) -> dict[str, Any]:
        cursor = len(self._lifecycle_events)
        acknowledged = self.eval(_owned_navigation_js(
            url,
            expected_url=expected_url,
            badge_label=badge_label,
        ))
        return {
            "ownershipAcknowledged": acknowledged is True,
            "lifecycleCursor": cursor,
        }

    def navigate(self, url: str, wait_ms: int = 4000) -> dict:
        result = self.send("Page.navigate", {"url": url})
        time.sleep(wait_ms / 1000)
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

    def wait_for_next_lifecycle(
        self,
        cursor: int,
        event: str,
        timeout: float = 30.0,
    ) -> str:
        deadline = time.time() + timeout
        start = max(0, int(cursor))
        while time.time() < deadline:
            for loader_id, name in self._lifecycle_events[start:]:
                if name == event:
                    return loader_id
            self.ws.settimeout(max(0.1, deadline - time.time()))
            try:
                message = json.loads(self.ws.recv())
            except Exception:
                continue
            if "method" in message:
                self._dispatch_event(message)
        raise TimeoutError(f"Page next lifecycle event timed out: {event}")

    def eval(self, expr: str) -> Any:
        r = self.send("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if r.get("exceptionDetails"):
            raise RuntimeError("Runtime.evaluate failed")
        result = r.get("result", {})
        if result.get("subtype") == "error":
            raise RuntimeError("Runtime.evaluate returned an error object")
        return result.get("value")

    def screenshot(self, path: str) -> str:
        r = self.send("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(r["data"])
        with open(path, "wb") as f:
            f.write(data)
        return path

    def disconnect(self) -> bool:
        """Close only this raw WebSocket; never mutate or destroy the browser target."""
        try:
            self.ws.close()
        except Exception:
            return False
        return getattr(self.ws, "connected", False) is not True

    def close(self) -> bool:
        # 작업 끝 → 배지 제거(사장님이 이어받을 때 '사용중' 잔상 안 남게).
        if getattr(self, "_badge_label", None):
            try:
                acknowledged = self.eval(_clear_js(
                    expected_url=getattr(self, "_badge_bound_url", None),
                ))
            except Exception:
                return False
            if acknowledged is not True:
                return False
            self._badge_label = None
            self._badge_bound_url = None
            self._badge_application_uncertain = False
        return self.disconnect()


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
