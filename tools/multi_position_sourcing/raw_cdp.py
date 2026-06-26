"""raw CDP 단일타깃 드라이버 — 사장님 9222 탭 과다 환경에서 connectOverCDP 전체 attach hang 회피.

websocket-client(동기)로 *한 개* page 타깃에만 붙어 Page.navigate / Runtime.evaluate /
Page.captureScreenshot 를 친다. humansearch 순회에서 재사용.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.request
from typing import Any

import websocket  # websocket-client


CDP_HTTP = "http://localhost:9222"


def _http_get(path: str) -> Any:
    with urllib.request.urlopen(CDP_HTTP + path, timeout=10) as r:
        return json.loads(r.read().decode())


def list_pages() -> list[dict]:
    return [t for t in _http_get("/json") if t.get("type") == "page"]


def new_tab(url: str = "about:blank") -> dict:
    # PUT /json/new?{url}
    req = urllib.request.Request(CDP_HTTP + "/json/new?" + url, method="PUT")
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
