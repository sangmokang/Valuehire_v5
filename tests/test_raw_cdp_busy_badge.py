"""자동화 점유 표시 배지 — raw CDP 공통 드라이버에 주입.

요구(2026-07-08 사장님): 자동화가 브라우저를 점유해 서치를 돌리는 동안 그 화면에
"사용중"을 표시. 모든 서치(/url·/aisearch·/humansearch)와 Codex에서도 동일.

인수 기준(기계 단언):
- 라벨 해석: agent/task env 반영, 기본 Claude, VH_BADGE_OFF 시 표시 안 함(None).
- 배지 JS: #vh-automation-badge · position:fixed · pointer-events:none(사장님 클릭 방해 금지) ·
  라벨 텍스트 포함 · idempotent(기존 제거 후 생성).
- mark_busy 후 navigate 하면 배지 재주입(페이지 로드로 사라지므로).
- 배지 주입 중 eval 예외가 나도 mark_busy/navigate 는 예외를 던지지 않는다(실 서치 안 깸).
- attach(badge=True)+env → mark_busy 호출, VH_BADGE_OFF 면 미호출.
"""

from __future__ import annotations

import sys
import struct
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.multi_position_sourcing import raw_cdp


def _png_rgba(width: int, height: int, pixel: tuple[int, int, int, int]) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    row = bytes(pixel) * width
    raw = b"".join(b"\x00" + row for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _png_rgba_pixels(
    width: int,
    height: int,
    pixels: list[tuple[int, int, int, int]],
) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    if len(pixels) != width * height:
        raise ValueError("pixel count mismatch")
    rows = []
    for y in range(height):
        row = pixels[y * width:(y + 1) * width]
        rows.append(b"\x00" + b"".join(bytes(pixel) for pixel in row))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


class _RecTab(raw_cdp.CDPTab):
    """ws 없이 eval/send 를 기록하는 CDPTab(생성자 우회)."""

    def __init__(self, *, eval_raises: bool = False, eval_result=None):
        self.evals: list[str] = []
        self.sends: list[tuple] = []
        self._badge_label = None
        self._eval_raises = eval_raises
        self._eval_result = eval_result

    def prove_badge_rendered(self, **_kwargs):
        return True

    def eval(self, expr: str):
        self.evals.append(expr)
        if self._eval_raises:
            raise RuntimeError("boom (렌더러 프리즈 흉내)")
        return self._eval_result

    def send(self, method, params=None, timeout=30.0):
        self.sends.append((method, params))
        return {}


class ResolveLabelTests(unittest.TestCase):
    def test_default_agent_is_claude(self):
        self.assertEqual(raw_cdp._resolve_badge_label({}), "🤖 Claude 자동화 사용중")

    def test_agent_and_task_from_env(self):
        lbl = raw_cdp._resolve_badge_label({"VH_BUSY_AGENT": "Codex", "VH_BUSY_TASK": "/humansearch"})
        self.assertEqual(lbl, "🤖 Codex 자동화 사용중 · /humansearch")

    def test_badge_off_returns_none(self):
        self.assertIsNone(raw_cdp._resolve_badge_label({"VH_BADGE_OFF": "1"}))
        self.assertIsNone(raw_cdp._resolve_badge_label({"VH_BADGE_OFF": "true"}))


class BadgeJsTests(unittest.TestCase):
    def test_badge_js_contract(self):
        js = raw_cdp._badge_js("🤖 Codex 자동화 사용중 · /url")
        self.assertIn("vh-automation-badge", js)
        self.assertIn("position:fixed", js.replace(" ", ""))
        self.assertIn("pointer-events:none", js.replace(" ", ""))
        self.assertIn("Codex", js)
        self.assertIn("사용중", js)
        # idempotent: 기존 요소 제거가 들어있어야 중복 배지 안 쌓임
        self.assertIn("remove", js)
        self.assertIn("parentElement", js)
        self.assertIn("getBoundingClientRect", js)
        self.assertIn("clipPath", js)
        self.assertIn("filter", js)
        self.assertIn("elementFromPoint", js)
        self.assertIn("checkVisibility", js)
        self.assertIn("backgroundColor", js)
        self.assertIn("important", js)
        self.assertNotIn("r.left+2,r.bottom-2", js)
        self.assertIn("r.width*0.25", js)

    def test_png_render_proof_crops_full_viewport_and_requires_overlay_challenge_color(self):
        width, height = 100, 50
        challenge = (17, 203, 91, 255)
        pixels = [(255, 255, 255, 255)] * (width * height)
        for y in range(5, 15):
            for x in range(20, 60):
                pixels[y * width + x] = challenge
        screenshot = _png_rgba_pixels(width, height, pixels)

        self.assertTrue(raw_cdp._png_region_matches_color(
            screenshot,
            css_rect={"x": 20, "y": 5, "width": 40, "height": 10},
            css_viewport={"width": 100, "height": 50},
            expected_rgb=challenge[:3],
        ))
        self.assertFalse(raw_cdp._png_region_matches_color(
            screenshot,
            css_rect={"x": 0, "y": 20, "width": 40, "height": 10},
            css_viewport={"width": 100, "height": 50},
            expected_rgb=challenge[:3],
        ))

    def test_png_render_proof_maps_css_coordinates_to_scaled_screenshot(self):
        width, height = 200, 100
        challenge = (31, 79, 211, 255)
        pixels = [(255, 255, 255, 255)] * (width * height)
        for y in range(10, 30):
            for x in range(40, 120):
                pixels[y * width + x] = challenge
        screenshot = _png_rgba_pixels(width, height, pixels)

        self.assertTrue(raw_cdp._png_region_matches_color(
            screenshot,
            css_rect={"x": 20, "y": 5, "width": 40, "height": 10},
            css_viewport={"width": 100, "height": 50},
            expected_rgb=challenge[:3],
        ))

    def test_clear_js_removes_by_id(self):
        js = raw_cdp._clear_js()
        self.assertIn("vh-automation-badge", js)
        self.assertIn("remove", js)

    def test_badge_js_binds_url_check_and_injection_in_one_evaluation(self):
        expected = "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
        js = raw_cdp._badge_js("Codex", expected_url=expected)
        self.assertIn("location.href", js)
        self.assertIn(expected, js)
        self.assertIn("return null", js)

    def test_owned_navigation_is_one_guarded_runtime_evaluation(self):
        tab = _RecTab(eval_result=True)
        tab._lifecycle_events = []
        result = tab.navigate_if_owned(
            "https://www.jobkorea.co.kr/Corp/Person/Find?keyword=robotics",
            expected_url="https://www.jobkorea.co.kr/Corp/Person/Find",
            badge_label="Codex",
        )
        self.assertTrue(result["ownershipAcknowledged"])
        js = tab.evals[-1]
        self.assertIn("location.href", js)
        self.assertIn("vh-automation-badge", js)
        self.assertIn("getComputedStyle", js)
        self.assertIn("location.assign", js)
        self.assertNotIn("setTimeout", js)


class MarkBusyTests(unittest.TestCase):
    def test_mark_busy_requires_exact_dom_acknowledgement(self):
        missing = _RecTab(eval_result=None)
        confirmed = _RecTab(eval_result=raw_cdp._BADGE_ID)

        self.assertFalse(missing.mark_busy("Codex"))
        self.assertTrue(confirmed.mark_busy("Codex"))

    def test_mark_busy_requires_composited_screenshot_proof(self):
        class OccludedTab(_RecTab):
            def prove_badge_rendered(self, **_kwargs):
                return False

        tab = OccludedTab(eval_result=raw_cdp._BADGE_ID)
        self.assertFalse(tab.mark_busy("Codex", expected_url="https://example.test/search"))
        self.assertTrue(tab.badge_application_uncertain)

    def test_render_proof_uses_browser_owned_overlay_and_full_viewport_screenshot(self):
        challenge = (17, 203, 91)
        screenshot = _png_rgba(100, 50, (*challenge, 255))

        class OverlayTab(_RecTab):
            def eval(self, expr: str):
                self.evals.append(expr)
                return {
                    "x": 0,
                    "y": 0,
                    "width": 100,
                    "height": 50,
                    "viewportWidth": 100,
                    "viewportHeight": 50,
                }

            def send(self, method, params=None, timeout=30.0):
                self.sends.append((method, params))
                if method == "Page.captureScreenshot":
                    import base64
                    return {"data": base64.b64encode(screenshot).decode("ascii")}
                return {}

        tab = OverlayTab()
        with patch.object(raw_cdp, "_overlay_challenge_color", return_value=challenge):
            self.assertTrue(tab.prove_badge_rendered(
                expected_url="https://example.test/search",
                badge_label="Codex",
            ))

        highlight_calls = [params for method, params in tab.sends if method == "Overlay.highlightRect"]
        self.assertGreaterEqual(len(highlight_calls), 2)
        self.assertEqual(highlight_calls[0]["color"], {"r": 17, "g": 203, "b": 91, "a": 1})
        screenshot_calls = [params for method, params in tab.sends if method == "Page.captureScreenshot"]
        self.assertEqual(len(screenshot_calls), 1)
        self.assertNotIn("clip", screenshot_calls[0], "shifted clip drops CDP Overlay pixels")

    def test_clear_badge_hides_browser_owned_overlay(self):
        tab = _RecTab(eval_result=True)
        tab._badge_label = "Codex"
        tab.clear_badge()
        self.assertIn(("Overlay.hideHighlight", None), tab.sends)

    def test_eval_rejects_runtime_exception_details(self):
        tab = _RecTab()
        tab.send = lambda *_args, **_kwargs: {
            "result": {"type": "undefined"},
            "exceptionDetails": {"text": "Uncaught"},
        }

        with self.assertRaises(RuntimeError):
            raw_cdp.CDPTab.eval(tab, "broken()")

    def test_mark_busy_injects_and_remembers(self):
        tab = _RecTab()
        tab.mark_busy("🤖 Claude 자동화 사용중 · /aisearch")
        self.assertEqual(tab._badge_label, "🤖 Claude 자동화 사용중 · /aisearch")
        self.assertTrue(any("vh-automation-badge" in e for e in tab.evals), "배지 JS 주입 안 됨")

    def test_navigate_does_not_reinject_badge_without_a_lease_guard(self):
        tab = _RecTab()
        tab.mark_busy("🤖 Claude 자동화 사용중")
        before = sum("vh-automation-badge" in e for e in tab.evals)
        tab.navigate("https://example.com", wait_ms=0)
        after = sum("vh-automation-badge" in e for e in tab.evals)
        self.assertEqual(after, before, "navigate 내부의 무가드 DOM 쓰기는 금지")
        self.assertIn(("Page.navigate", {"url": "https://example.com"}), tab.sends)

    def test_clear_badge(self):
        tab = _RecTab()
        tab.mark_busy("x")
        tab.clear_badge()
        self.assertIsNone(tab._badge_label)
        self.assertTrue(any("remove" in e for e in tab.evals))

    def test_navigate_without_badge_does_not_inject(self):
        tab = _RecTab()
        tab.navigate("https://example.com", wait_ms=0)
        self.assertFalse(any("vh-automation-badge" in e for e in tab.evals),
                         "배지 안 걸었는데 주입되면 안 됨")

    def test_badge_failure_never_breaks_search(self):
        # 배지 eval 이 터져도 mark_busy/navigate 는 예외를 던지면 안 된다.
        tab = _RecTab(eval_raises=True)
        try:
            tab.mark_busy("x")           # 예외 나면 실패
            tab.navigate("https://example.com", wait_ms=0)
        except Exception as e:  # noqa: BLE001
            self.fail(f"배지 실패가 서치를 깼다: {e!r}")
        # 라벨은 기억해 다음 기회에 재시도 가능해야 함
        self.assertEqual(tab._badge_label, "x")

    def test_close_keeps_socket_open_when_badge_clear_is_not_acknowledged(self):
        class ClearFailTab(_RecTab):
            def __init__(self):
                super().__init__(eval_raises=True)
                self._badge_label = "Codex"
                self.disconnect_calls = 0

            def disconnect(self):
                self.disconnect_calls += 1

        tab = ClearFailTab()
        self.assertFalse(tab.close())
        self.assertEqual(tab.disconnect_calls, 0)
        self.assertEqual(tab._badge_label, "Codex")

    def test_close_keeps_lease_eligible_state_when_socket_close_fails(self):
        class FailingSocket:
            connected = True

            def close(self):
                raise OSError("socket stayed open")

        tab = object.__new__(raw_cdp.CDPTab)
        tab.ws = FailingSocket()
        tab._badge_label = None
        self.assertIs(tab.disconnect(), False)
        self.assertIs(tab.close(), False)

    def test_mark_busy_exposes_unknown_state_when_ack_is_lost(self):
        class SideEffectThenTimeout(_RecTab):
            def eval(self, expr: str):
                self.evals.append(expr)
                raise TimeoutError("ack lost after renderer evaluation")

        tab = SideEffectThenTimeout()
        self.assertFalse(tab.mark_busy("Codex", expected_url="https://example.test/search"))
        self.assertTrue(tab.badge_application_uncertain)

    def test_constructor_closes_socket_when_domain_enable_fails(self):
        class Socket:
            connected = True

            def __init__(self):
                self.close_calls = 0

            def close(self):
                self.close_calls += 1
                self.connected = False

        socket = Socket()
        websocket_module = SimpleNamespace(
            create_connection=lambda *_args, **_kwargs: socket,
        )
        with patch.dict(sys.modules, {"websocket": websocket_module}), patch.object(
            raw_cdp.CDPTab,
            "send",
            side_effect=RuntimeError("Runtime.enable failed"),
        ):
            with self.assertRaises(RuntimeError):
                raw_cdp.CDPTab("ws://fake")
        self.assertEqual(socket.close_calls, 1)

    def test_constructor_enables_dom_and_overlay_domains(self):
        class Socket:
            connected = True

            def close(self):
                self.connected = False

        socket = Socket()
        websocket_module = SimpleNamespace(
            create_connection=lambda *_args, **_kwargs: socket,
        )
        calls = []
        with patch.dict(sys.modules, {"websocket": websocket_module}), patch.object(
            raw_cdp.CDPTab,
            "send",
            side_effect=lambda method, params=None: calls.append((method, params)) or {},
        ):
            raw_cdp.CDPTab("ws://fake")
        self.assertIn(("DOM.enable", None), calls)
        self.assertIn(("Overlay.enable", None), calls)


class RawEventBridgeTests(unittest.TestCase):
    def test_response_and_navigation_events_reach_worker_handlers(self):
        tab = _RecTab()
        tab._event_handlers = {}
        responses = []
        frames = []
        tab.on("response", responses.append)
        tab.on("framenavigated", frames.append)

        tab._dispatch_event({
            "method": "Network.responseReceived",
            "params": {"response": {"status": 401, "url": "https://example.test/login"}},
        })
        tab._dispatch_event({
            "method": "Page.frameNavigated",
            "params": {"frame": {"url": "https://example.test/checkpoint"}},
        })

        self.assertEqual(responses[0].status, 401)
        self.assertEqual(responses[0].url, "https://example.test/login")
        self.assertEqual(frames[0].url, "https://example.test/checkpoint")


class AutoBadgeOnAttachTests(unittest.TestCase):
    def test_maybe_auto_badge_calls_mark_busy(self):
        tab = _RecTab()
        raw_cdp._maybe_auto_badge(tab, {"VH_BUSY_AGENT": "Codex"})
        self.assertEqual(tab._badge_label, "🤖 Codex 자동화 사용중")

    def test_maybe_auto_badge_off(self):
        tab = _RecTab()
        raw_cdp._maybe_auto_badge(tab, {"VH_BADGE_OFF": "1"})
        self.assertIsNone(tab._badge_label)
        self.assertFalse(tab.evals, "배지 꺼짐인데 주입되면 안 됨")


if __name__ == "__main__":
    unittest.main()
