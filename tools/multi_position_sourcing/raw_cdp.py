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


def _http_get(path: str) -> Any:
    with urllib.request.urlopen(_cdp_base() + path, timeout=10) as r:
        return json.loads(r.read().decode())


def list_pages() -> list[dict]:
    return [t for t in _http_get("/json") if t.get("type") == "page"]


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
        self.send("Page.enable")
        self.send("Runtime.enable")

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
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method} error: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(f"{method} timed out")

    def navigate(self, url: str, wait_ms: int = 4000) -> None:
        self.send("Page.navigate", {"url": url})
        time.sleep(wait_ms / 1000)

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
        try:
            self.ws.close()
        except Exception:
            pass


def attach(target: dict) -> CDPTab:
    return CDPTab(target["webSocketDebuggerUrl"])
