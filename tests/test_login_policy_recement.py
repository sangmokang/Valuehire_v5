"""로그인 정책 재확인 (2026-07-08, /st L3).

계약:
- AC1: legacy portal_login 사람 게이트는 generic focus/poll을 수행하지 않고 exact-window
  session_guard에 fail-closed 위임한다.
- AC2: docs/sot/26은 PID+CGWindowID exact handoff 1회와 HUMAN_AUTH 무조작·무제한 대기를 명시한다.
- AC3: 기존 가드(자동로그인 차단 부재)는 여전히 유지.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing import portal_login

REPO = Path(__file__).resolve().parents[1]
SOT26 = REPO / "docs" / "sot" / "26-portal-login-spec.json"


class _FakePage:
    def __init__(self, ready_after: int = 0, bring_raises: bool = False):
        self.url = "https://www.linkedin.com/checkpoint/challengesV2/abc"
        self._bring_raises = bring_raises
        self.bring_to_front_calls = 0
        self._ready_after = ready_after
        self._polls = 0
        self.navigation_calls = 0
        self.click_calls = 0

    async def bring_to_front(self):
        self.bring_to_front_calls += 1
        if self._bring_raises:
            raise RuntimeError("bring_to_front not supported")

    async def wait_for_timeout(self, ms):
        self._polls += 1


def _run_intervention(page, ready_values):
    """ready_check가 ready_values 를 순서대로 반환하도록 하여 사람-게이트를 짧게 끝낸다."""
    seq = list(ready_values)

    async def ready_check(_page):
        return seq.pop(0) if seq else True

    opts = portal_login.HumanInterventionOptions(enabled=True, timeout_seconds=10, poll_interval_seconds=0)
    return asyncio.run(
        portal_login._wait_for_human_intervention(
            page, "linkedin_rps", ready_check=ready_check, options=opts, note="2FA test"
        )
    )


def test_legacy_human_intervention_delegates_without_generic_focus_or_poll():
    """AC1: exact identity 없는 legacy 함수는 UI를 건드리지 않고 새 runner로 위임한다."""
    page = _FakePage()
    result = _run_intervention(page, [True])
    assert page.bring_to_front_calls == 0
    assert page._polls == 0
    assert result["ready"] is False
    assert result["login"] == "human_auth_runner_required"


def test_legacy_human_intervention_never_runs_mutating_ready_check():
    page = _FakePage(bring_raises=True)
    calls = 0

    async def forbidden_ready_check(_page):
        nonlocal calls
        calls += 1
        raise AssertionError("legacy ready check may navigate/click")

    result = asyncio.run(
        portal_login._wait_for_human_intervention(
            page,
            "linkedin_rps",
            ready_check=forbidden_ready_check,
            options=portal_login.HumanInterventionOptions(enabled=True),
            note="2FA test",
        )
    )
    assert calls == 0
    assert page.bring_to_front_calls == 0
    assert result["login"] == "human_auth_runner_required"


def test_sot26_recements_exact_window_and_read_only_human_auth():
    spec = json.loads(SOT26.read_text(encoding="utf-8"))
    encoded = json.dumps(spec, ensure_ascii=False)
    assert "CGWindowID" in encoded
    assert "CoreGraphics" in encoded
    assert "screencapture -x -l" in encoded
    human = spec["human_auth_control"]
    assert human["max_presentations_per_episode"] == 1
    assert human["timeout_seconds"] is None
    assert human["quiet_after_owner_input_seconds"] == 15
    assert human["allowed_during_wait"] == ["read_auth_marker", "read_owner_idle", "wait"]
    assert "portal_login._wait_for_human_intervention" not in encoded
    assert "page.bring_to_front" not in encoded


def test_sot26_still_forbids_no_autologin_disable():
    """AC3: 자동로그인 차단 스키마가 다시 들어오지 않았는지 가드."""
    encoded = SOT26.read_text(encoding="utf-8")
    assert "linkedin_auto_login_disabled" not in encoded
    assert "auto_login_disabled" not in encoded
