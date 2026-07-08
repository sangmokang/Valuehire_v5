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
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.multi_position_sourcing import raw_cdp


class _RecTab(raw_cdp.CDPTab):
    """ws 없이 eval/send 를 기록하는 CDPTab(생성자 우회)."""

    def __init__(self, *, eval_raises: bool = False):
        self.evals: list[str] = []
        self.sends: list[tuple] = []
        self._badge_label = None
        self._eval_raises = eval_raises

    def eval(self, expr: str):
        self.evals.append(expr)
        if self._eval_raises:
            raise RuntimeError("boom (렌더러 프리즈 흉내)")
        return None

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

    def test_clear_js_removes_by_id(self):
        js = raw_cdp._clear_js()
        self.assertIn("vh-automation-badge", js)
        self.assertIn("remove", js)


class MarkBusyTests(unittest.TestCase):
    def test_mark_busy_injects_and_remembers(self):
        tab = _RecTab()
        tab.mark_busy("🤖 Claude 자동화 사용중 · /aisearch")
        self.assertEqual(tab._badge_label, "🤖 Claude 자동화 사용중 · /aisearch")
        self.assertTrue(any("vh-automation-badge" in e for e in tab.evals), "배지 JS 주입 안 됨")

    def test_navigate_reinjects_badge(self):
        tab = _RecTab()
        tab.mark_busy("🤖 Claude 자동화 사용중")
        before = sum("vh-automation-badge" in e for e in tab.evals)
        tab.navigate("https://example.com", wait_ms=0)
        after = sum("vh-automation-badge" in e for e in tab.evals)
        self.assertGreater(after, before, "navigate 후 배지 재주입 안 됨(페이지 로드로 사라짐)")
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
