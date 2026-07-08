"""로그인 정책 재확인 (2026-07-08, /st L3).

계약:
- AC1: _wait_for_human_intervention 진입 시 page.bring_to_front() 를 호출한다(2FA 순간
  브라우저를 앞으로 띄워 사장님이 바로 처리). best-effort — bring_to_front 가 실패해도
  사람-게이트 폴링/자동재개 흐름은 정상 동작한다.
- AC2: docs/sot/26-portal-login-spec.json 불변식에 (a) 자동로그인 무조건 수행·차단 금지 강화,
  (b) 사람 개입(2FA 등) 필요 시 브라우저를 앞으로 띄운다 신규 불변식이 존재.
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


def test_human_intervention_brings_browser_to_front():
    """AC1: 사람-게이트 진입 시 브라우저를 앞으로 띄운다."""
    page = _FakePage()
    result = _run_intervention(page, [True])  # 즉시 ready → 빠르게 종료
    assert page.bring_to_front_calls >= 1, "2FA 관문에서 page.bring_to_front() 가 호출돼야 함"
    assert result["ready"] is True


def test_bring_to_front_failure_does_not_break_flow():
    """AC1(best-effort): bring_to_front 가 실패해도 사람-게이트 흐름은 계속된다."""
    page = _FakePage(bring_raises=True)
    result = _run_intervention(page, [False, True])  # 한 번 폴링 후 ready
    assert page.bring_to_front_calls >= 1
    assert result["ready"] is True  # 예외가 흐름을 깨지 않음


def test_sot26_recements_auto_login_and_bring_to_front():
    """AC2: SOT26 불변식 강화 — 자동로그인 무조건 + 2FA 시 브라우저 앞으로."""
    spec = json.loads(SOT26.read_text(encoding="utf-8"))
    invariants = " ".join(spec.get("invariants", []))
    # (a) 자동로그인 무조건 수행 · 차단 금지 강화
    assert "무조건" in invariants, "자동로그인을 자동화가 무조건 수행한다는 강화 문구 필요"
    # (b) 2FA 등 사람 개입 시 브라우저를 앞으로 띄운다
    assert "앞으로" in invariants or "bring_to_front" in json.dumps(spec, ensure_ascii=False), (
        "사람 개입(2FA) 시 브라우저를 앞으로 띄운다는 불변식 필요"
    )


def test_sot26_still_forbids_no_autologin_disable():
    """AC3: 자동로그인 차단 스키마가 다시 들어오지 않았는지 가드."""
    encoded = SOT26.read_text(encoding="utf-8")
    assert "linkedin_auto_login_disabled" not in encoded
    assert "auto_login_disabled" not in encoded
