"""raw CDP 단일타깃 드라이버 — 사장님 9222 탭 과다 환경에서 connectOverCDP 전체 attach hang 회피.

websocket-client(동기)로 *한 개* page 타깃에만 붙어 Page.navigate / Runtime.evaluate /
Page.captureScreenshot 를 친다. humansearch 순회에서 재사용.
"""
from __future__ import annotations

import base64
import json
import math
import os
import secrets
import struct
import time
import urllib.request
import zlib
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
_BADGE_TAG = "vh-automation-status"
_BADGE_OFF_VALUES = {"1", "true", "yes", "on"}


def _paeth_predictor(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


def _decode_png_rgb(data: bytes) -> tuple[int, int, bytes, bytes] | None:
    """Decode Chrome's non-interlaced 8-bit RGB/RGBA PNG without extra deps."""
    if not isinstance(data, bytes) or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    offset = 8
    header: tuple[int, int, int, int, int, int, int] | None = None
    compressed = bytearray()
    saw_iend = False
    try:
        while offset + 12 <= len(data):
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            payload_start = offset + 8
            payload_end = payload_start + length
            if payload_end + 4 > len(data):
                return None
            payload = data[payload_start:payload_end]
            expected_crc = struct.unpack(">I", data[payload_end:payload_end + 4])[0]
            if zlib.crc32(kind + payload) & 0xFFFFFFFF != expected_crc:
                return None
            if kind == b"IHDR":
                if length != 13 or header is not None:
                    return None
                header = struct.unpack(">IIBBBBB", payload)
            elif kind == b"IDAT":
                if header is None:
                    return None
                compressed.extend(payload)
            elif kind == b"IEND":
                if length != 0:
                    return None
                saw_iend = True
                break
            offset = payload_end + 4
        if header is None or not compressed or not saw_iend:
            return None
        width, height, depth, color_type, compression, filter_method, interlace = header
        if (
            width <= 0 or height <= 0 or width > 4096 or height > 4096
            or depth != 8 or color_type not in {2, 6}
            or compression != 0 or filter_method != 0 or interlace != 0
        ):
            return None
        channels = 3 if color_type == 2 else 4
        stride = width * channels
        raw = zlib.decompress(bytes(compressed))
        if len(raw) != height * (stride + 1):
            return None
        prior = bytearray(stride)
        rgb = bytearray(width * height * 3)
        alpha = bytearray(width * height)
        output_position = 0
        position = 0
        for _row in range(height):
            filter_type = raw[position]
            position += 1
            scan = bytearray(raw[position:position + stride])
            position += stride
            if filter_type not in {0, 1, 2, 3, 4}:
                return None
            for index in range(stride):
                left = scan[index - channels] if index >= channels else 0
                up = prior[index]
                upper_left = prior[index - channels] if index >= channels else 0
                if filter_type == 1:
                    scan[index] = (scan[index] + left) & 0xFF
                elif filter_type == 2:
                    scan[index] = (scan[index] + up) & 0xFF
                elif filter_type == 3:
                    scan[index] = (scan[index] + ((left + up) // 2)) & 0xFF
                elif filter_type == 4:
                    scan[index] = (
                        scan[index] + _paeth_predictor(left, up, upper_left)
                    ) & 0xFF
            for pixel in range(0, stride, channels):
                rgb[output_position * 3:output_position * 3 + 3] = scan[pixel:pixel + 3]
                alpha[output_position] = scan[pixel + 3] if channels == 4 else 255
                output_position += 1
            prior = scan
        return width, height, bytes(rgb), bytes(alpha)
    except (OverflowError, ValueError, TypeError, struct.error, zlib.error):
        return None


def _png_region_matches_color(
    data: bytes,
    *,
    css_rect: dict[str, float],
    css_viewport: dict[str, float],
    expected_rgb: tuple[int, int, int],
) -> bool:
    """Prove an opaque browser-owned Overlay in a full-viewport screenshot."""
    decoded = _decode_png_rgb(data)
    if decoded is None:
        return False
    width, height, rgb, alpha = decoded
    try:
        viewport_width = float(css_viewport["width"])
        viewport_height = float(css_viewport["height"])
        x = float(css_rect["x"])
        y = float(css_rect["y"])
        rect_width = float(css_rect["width"])
        rect_height = float(css_rect["height"])
        expected = tuple(int(value) for value in expected_rgb)
    except (KeyError, TypeError, ValueError):
        return False
    if (
        not all(math.isfinite(value) for value in (
            viewport_width, viewport_height, x, y, rect_width, rect_height
        ))
        or viewport_width <= 0 or viewport_height <= 0
        or x < 0 or y < 0 or rect_width < 8 or rect_height < 8
        or x + rect_width > viewport_width + 0.5
        or y + rect_height > viewport_height + 0.5
        or len(expected) != 3 or any(value < 0 or value > 255 for value in expected)
    ):
        return False
    scale_x = width / viewport_width
    scale_y = height / viewport_height
    # Ignore one device pixel at each edge: Overlay outlines are antialiased there.
    try:
        left = max(0, int(math.floor(x * scale_x)) + 1)
        top = max(0, int(math.floor(y * scale_y)) + 1)
        right = min(width, int(math.ceil((x + rect_width) * scale_x)) - 1)
        bottom = min(height, int(math.ceil((y + rect_height) * scale_y)) - 1)
    except (OverflowError, ValueError):
        return False
    if right <= left or bottom <= top:
        return False
    matches = 0
    total = 0
    for row in range(top, bottom):
        for column in range(left, right):
            pixel = row * width + column
            offset = pixel * 3
            actual = rgb[offset:offset + 3]
            total += 1
            if alpha[pixel] >= 250 and all(
                abs(actual[index] - expected[index]) <= 2 for index in range(3)
            ):
                matches += 1
    return total >= 16 and matches / total >= 0.95


def _overlay_challenge_color() -> tuple[int, int, int]:
    """Return a per-proof opaque color that page content cannot predict or query."""
    return tuple(24 + value % 208 for value in secrets.token_bytes(3))


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
        "function vhPseudoVisible(s){return !!(s&&s.content&&"
        "s.content!=='none'&&s.content!=='normal');}"
        f"if(vhPseudoVisible(window.getComputedStyle({element},'::before'))||"
        f"vhPseudoVisible(window.getComputedStyle({element},'::after')))"
        "{" + failure + "}"
        f"{element}.style.setProperty('pointer-events','auto','important');"
        "var pts=[[r.left+r.width/2,r.top+r.height/2],"
        "[r.left+r.width*0.25,r.top+r.height*0.25],"
        "[r.left+r.width*0.75,r.top+r.height*0.25],"
        "[r.left+r.width*0.25,r.top+r.height*0.75],"
        "[r.left+r.width*0.75,r.top+r.height*0.75]];"
        "var hit=true;for(var i=0;i<pts.length;i++){"
        "var x=Math.max(0,Math.min(window.innerWidth-1,pts[i][0]));"
        "var y=Math.max(0,Math.min(window.innerHeight-1,pts[i][1]));"
        "var h=document.elementFromPoint(x,y);"
        f"if(h!=={element}&&!{element}.contains(h)){{hit=false;break;}}}}"
        f"{element}.style.setProperty('pointer-events','none','important');"
        "if(!hit){" + failure + "}"
    )


def _badge_identity_js(element: str, label: str, failure: str) -> str:
    """Bind the browser-owned tooltip's tag and accessible name to one label."""
    encoded_label = json.dumps(label, ensure_ascii=False)
    return (
        f"if({element}.localName!=={json.dumps(_BADGE_TAG)}||"
        f"{element}.id!=={json.dumps(_BADGE_ID)}||"
        f"{element}.textContent!=={encoded_label}||"
        f"{element}.getAttribute('aria-label')!=={encoded_label}||"
        f"{element}.getAttribute('title')!=={encoded_label}||"
        f"{element}.getAttribute('role')!=='status')"
        "{" + failure + "}"
    )


def _badge_object_identity_function(label: str) -> str:
    """Runtime.callFunctionOn predicate for the exact resolved badge node."""
    encoded_label = json.dumps(label, ensure_ascii=False)
    return (
        "function(){return !!(this&&this.isConnected&&"
        f"this.localName==={json.dumps(_BADGE_TAG)}&&"
        f"this.id==={json.dumps(_BADGE_ID)}&&"
        f"this.textContent==={encoded_label}&&"
        f"this.getAttribute('aria-label')==={encoded_label}&&"
        f"this.getAttribute('title')==={encoded_label}&&"
        "this.getAttribute('role')==='status');}"
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
        f"e=document.createElement({json.dumps(_BADGE_TAG)});"
        "e.id=id;"
        f"e.textContent={text};"
        f"e.setAttribute('aria-label',{text});"
        f"e.setAttribute('title',{text});"
        "e.setAttribute('role','status');"
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
        + _badge_identity_js("e", label, "e.remove();return null;")
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


def _owned_badge_action_function(
    action: str,
    *,
    expected_url: str,
    badge_label: str,
) -> str:
    return (
        "function(){var b=this;"
        f"if(location.href!=={json.dumps(expected_url)})return false;"
        "if(!b||!b.isConnected)return false;"
        + _badge_identity_js("b", badge_label, "return false;")
        + _badge_visibility_js("b", "return false;")
        + action
        + "}"
    )


def _badge_rect_js(expected_url: str | None, badge_label: str) -> str:
    url_guard = ""
    if expected_url is not None:
        url_guard = f"if(location.href!=={json.dumps(expected_url)})return false;"
    return (
        "(function(){"
        + url_guard
        + f"var b=document.getElementById({json.dumps(_BADGE_ID)});"
        "if(!b)return false;"
        + _badge_identity_js("b", badge_label, "return false;")
        + _badge_visibility_js("b", "return false;")
        + "var x=Math.max(0,r.left),y=Math.max(0,r.top);"
        "var right=Math.min(window.innerWidth,r.right);"
        "var bottom=Math.min(window.innerHeight,r.bottom);"
        "return {x:x,y:y,width:right-x,height:bottom-y,"
        "viewportWidth:window.innerWidth,viewportHeight:window.innerHeight};})()"
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
        self._badge_object_id: str | None = None
        self._badge_application_uncertain = False
        self._event_handlers: dict[str, list[Any]] = {}
        self._lifecycle_events: list[tuple[str, str]] = []
        try:
            self.send("Page.enable")
            self.send("Runtime.enable")
            self.send("Network.enable")
            self.send("DOM.enable")
            self.send("Overlay.enable")
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
        if acknowledged == _BADGE_ID:
            try:
                if self.prove_badge_rendered(
                    expected_url=expected_url,
                    badge_label=label,
                ):
                    self._badge_application_uncertain = False
                    return True
            except Exception:
                return False
            return False
        self._badge_application_uncertain = False
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
        try:
            self.send("Overlay.hideHighlight")
        except Exception:
            pass
        self._release_badge_object()

    def _release_badge_object(self) -> None:
        object_id = getattr(self, "_badge_object_id", None)
        self._badge_object_id = None
        if not isinstance(object_id, str) or not object_id:
            return
        try:
            self.send("Runtime.releaseObject", {"objectId": object_id})
        except Exception:
            pass

    def _invalidate_badge_proof(self) -> None:
        self._badge_application_uncertain = True
        try:
            self.send("Overlay.hideHighlight")
        except Exception:
            pass
        self._release_badge_object()

    def _resolved_badge_identity(self, object_id: str, label: str) -> bool:
        result = self.send("Runtime.callFunctionOn", {
            "objectId": object_id,
            "functionDeclaration": _badge_object_identity_function(label),
            "returnByValue": True,
            "awaitPromise": False,
        })
        if not isinstance(result, dict) or result.get("exceptionDetails"):
            return False
        remote = result.get("result")
        return isinstance(remote, dict) and remote.get("value") is True

    def eval_if_badge_owned(
        self,
        action: str,
        *,
        expected_url: str,
        badge_label: str,
    ) -> bool:
        """Run one portal mutation on the exact object proven by the Overlay."""
        object_id = getattr(self, "_badge_object_id", None)
        if not isinstance(object_id, str) or not object_id:
            self._invalidate_badge_proof()
            return False
        try:
            result = self.send("Runtime.callFunctionOn", {
                "objectId": object_id,
                "functionDeclaration": _owned_badge_action_function(
                    action,
                    expected_url=expected_url,
                    badge_label=badge_label,
                ),
                "returnByValue": True,
                "awaitPromise": False,
            })
        except BaseException:
            self._invalidate_badge_proof()
            raise
        remote = result.get("result") if isinstance(result, dict) else None
        acknowledged = (
            not result.get("exceptionDetails")
            and isinstance(remote, dict)
            and remote.get("value") is True
        ) if isinstance(result, dict) else False
        if not acknowledged:
            self._invalidate_badge_proof()
        return acknowledged

    def prove_badge_rendered(
        self,
        *,
        expected_url: str | None,
        badge_label: str,
    ) -> bool:
        # A prior tooltip can live-update from page-mutated aria attributes. Remove
        # it before any early-return path, then retain a new object only on success.
        self._badge_application_uncertain = True
        try:
            self.send("Overlay.hideHighlight")
        except Exception:
            return False
        self._release_badge_object()
        rect = self.eval(_badge_rect_js(expected_url, badge_label))
        if not isinstance(rect, dict):
            return False
        values = [
            rect.get(name)
            for name in ("x", "y", "width", "height", "viewportWidth", "viewportHeight")
        ]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
            return False
        x, y, width, height, viewport_width, viewport_height = (
            float(value) for value in values
        )
        if (
            not all(math.isfinite(value) for value in (
                x, y, width, height, viewport_width, viewport_height
            ))
            or x < 0 or y < 0 or width < 8 or height < 8
            or viewport_width <= 0 or viewport_height <= 0
        ):
            return False
        challenge = _overlay_challenge_color()
        left = max(0, int(math.floor(x)))
        top = max(0, int(math.floor(y)))
        right = min(int(math.ceil(viewport_width)), int(math.ceil(x + width)))
        bottom = min(int(math.ceil(viewport_height)), int(math.ceil(y + height)))
        overlay_rect = {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
        }
        if overlay_rect["width"] < 8 or overlay_rect["height"] < 8:
            return False
        challenge_applied = False
        proof_complete = False
        object_id: str | None = None
        try:
            self.send("Overlay.highlightRect", {
                **overlay_rect,
                "color": {
                    "r": challenge[0],
                    "g": challenge[1],
                    "b": challenge[2],
                    "a": 1,
                },
            })
            challenge_applied = True
            # Chromium omits compositor overlays from a shifted clip. Capture the
            # viewport and crop after decoding instead.
            result = self.send("Page.captureScreenshot", {
                "format": "png",
                "fromSurface": True,
                "captureBeyondViewport": False,
            })
            encoded = result.get("data") if isinstance(result, dict) else None
            if not isinstance(encoded, str) or not encoded:
                return False
            png = base64.b64decode(encoded, validate=True)
            if not _png_region_matches_color(
                png,
                css_rect=overlay_rect,
                css_viewport={"width": viewport_width, "height": viewport_height},
                expected_rgb=challenge,
            ):
                return False
            document = self.send("DOM.getDocument", {"depth": 0})
            root = document.get("root") if isinstance(document, dict) else None
            root_node_id = root.get("nodeId") if isinstance(root, dict) else None
            if isinstance(root_node_id, bool) or not isinstance(root_node_id, int):
                return False
            match = self.send("DOM.querySelector", {
                "nodeId": root_node_id,
                "selector": f"#{_BADGE_ID}",
            })
            node_id = match.get("nodeId") if isinstance(match, dict) else None
            if isinstance(node_id, bool) or not isinstance(node_id, int) or node_id <= 0:
                return False
            resolved = self.send("DOM.resolveNode", {"nodeId": node_id})
            remote_object = resolved.get("object") if isinstance(resolved, dict) else None
            object_id = remote_object.get("objectId") if isinstance(remote_object, dict) else None
            if not isinstance(object_id, str) or not object_id:
                return False
            if not self._resolved_badge_identity(object_id, badge_label):
                return False
            # Keep a browser-owned DevTools tooltip above every page layer.  The
            # custom tag/id and aria-label make the exact agent/task readable even
            # when page CSS tries to cover the DOM badge.
            self.send("Overlay.highlightNode", {
                "nodeId": node_id,
                "highlightConfig": {
                    "showInfo": True,
                    "showAccessibilityInfo": True,
                    "contentColor": {"r": 220, "g": 38, "b": 38, "a": 0.12},
                    "paddingColor": {"r": 255, "g": 255, "b": 255, "a": 0.08},
                    "borderColor": {"r": 255, "g": 255, "b": 255, "a": 1},
                    "marginColor": {"r": 220, "g": 38, "b": 38, "a": 0.08},
                },
            })
            if not self._resolved_badge_identity(object_id, badge_label):
                return False
            self._badge_object_id = object_id
            object_id = None
            proof_complete = True
            self._badge_application_uncertain = False
            return True
        except (ValueError, TypeError):
            return False
        finally:
            if object_id:
                try:
                    self.send("Runtime.releaseObject", {"objectId": object_id})
                except Exception:
                    pass
            if challenge_applied and not proof_complete:
                try:
                    self.send("Overlay.hideHighlight")
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
        acknowledged = self.eval_if_badge_owned(
            f"var u={json.dumps(url)};location.assign(u);return true;",
            expected_url=expected_url,
            badge_label=badge_label,
        )
        if acknowledged:
            # The navigation destroys this execution context. Keep uncertainty/lease
            # until the destination lifecycle re-injects and re-proves the marker.
            self._release_badge_object()
            self._badge_application_uncertain = True
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
            try:
                self.send("Overlay.hideHighlight")
            except Exception:
                return False
            self._release_badge_object()
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
