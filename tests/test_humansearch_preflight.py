"""humansearch 브라우징·로그인 라이브 프리플라이트 게이트 (docs/sot/27).

이 게이트가 없어서 2026-06-30 뤼튼 AX Sales 순회가 죽은 검색에서 0건을 조용히 뱉고
같은 네비게이션을 반복했다. 여기서는 *순수 판정*(evaluate_search_preflight)과
*fail-closed 배선*(assert_live_or_abort)을 강제한다.
"""
from __future__ import annotations

import pytest

from tools.multi_position_sourcing.humansearch_preflight import (
    PreflightError,
    assert_live_or_abort,
    build_probe_js,
    evaluate_search_preflight,
)


def _live_probe(**over):
    base = {
        "url": "https://www.linkedin.com/talent/hire/1750764916/discover/recruiterSearch?searchContextId=e41c02da&start=0",
        "card_count": 21,
        "results_text": "3.9K+ results",
        "logged_in_account": "Value Connect - RPS",
        "multiple_signins": False,
        "captcha": False,
    }
    base.update(over)
    return base


# ── happy path ──
def test_live_search_passes():
    d = evaluate_search_preflight(_live_probe())
    assert d["ok"] is True
    assert d["reasons"] == []
    assert all(d["checks"].values())


# ── 만료/Loading/껍데기: 카드 0 + 결과수 없음 → results_rendered 실패 ──
def test_stale_shell_no_cards_no_results_fails():
    d = evaluate_search_preflight(_live_probe(card_count=0, results_text=""))
    assert d["ok"] is False
    assert d["checks"]["results_rendered"] is False
    assert any("결과" in r or "result" in r.lower() for r in d["reasons"])


def test_loading_state_results_text_empty_but_account_ok_fails():
    # 'Loading search results' — 계정 로그인은 돼 있어도 결과 미렌더면 거부
    d = evaluate_search_preflight(_live_probe(card_count=0, results_text=""))
    assert d["ok"] is False
    assert d["checks"]["logged_in"] is True
    assert d["checks"]["results_rendered"] is False


def test_results_text_present_but_zero_cards_still_fails():
    # 결과수 텍스트는 떠도 카드가 0이면(스켈레톤) 거부
    d = evaluate_search_preflight(_live_probe(card_count=0, results_text="3.9K+ results"))
    assert d["ok"] is False
    assert d["checks"]["results_rendered"] is False


# ── 세션 충돌(다른 기기 동시 로그인) ──
def test_multiple_signins_fails():
    d = evaluate_search_preflight(_live_probe(multiple_signins=True))
    assert d["ok"] is False
    assert d["checks"]["no_session_conflict"] is False


def test_enterprise_auth_session_url_fails():
    d = evaluate_search_preflight(
        _live_probe(url="https://www.linkedin.com/enterprise-authentication/sessions?accountId=1", card_count=0, results_text="")
    )
    assert d["ok"] is False
    assert d["checks"]["no_session_conflict"] is False


# ── 캡차/체크포인트 ──
def test_captcha_fails():
    d = evaluate_search_preflight(_live_probe(captcha=True))
    assert d["ok"] is False
    assert d["checks"]["no_captcha"] is False


# ── 로그인 리다이렉트 / 계정명 없음 ──
def test_login_redirect_url_fails():
    d = evaluate_search_preflight(
        _live_probe(url="https://www.linkedin.com/authwall?trk=x", logged_in_account="")
    )
    assert d["ok"] is False
    assert d["checks"]["logged_in"] is False


def test_empty_account_fails():
    d = evaluate_search_preflight(_live_probe(logged_in_account="  "))
    assert d["ok"] is False
    assert d["checks"]["logged_in"] is False


# ── fail-closed 배선 ──
class _FakeTab:
    def __init__(self, probe):
        self._probe = probe

    def eval(self, expr):
        # build_probe_js() 가 만든 표현식을 평가하는 대신, 주입된 probe 를 그대로 돌려준다.
        return self._probe


def test_assert_live_or_abort_raises_on_dead_search():
    tab = _FakeTab(_live_probe(card_count=0, results_text=""))
    with pytest.raises(PreflightError) as ei:
        assert_live_or_abort(tab)
    assert "결과" in str(ei.value) or "result" in str(ei.value).lower()


def test_assert_live_or_abort_returns_decision_on_live():
    tab = _FakeTab(_live_probe())
    d = assert_live_or_abort(tab)
    assert d["ok"] is True


def test_runner_wires_the_gate_no_orphan():
    # R4 배선 증명: 러너가 assert_live_or_abort 를 import 하고 호출한다(고아 아님).
    from pathlib import Path

    src = Path("tools/multi_position_sourcing/humansearch_cdp_run.py").read_text(encoding="utf-8")
    assert "from tools.multi_position_sourcing.humansearch_preflight import assert_live_or_abort" in src
    assert "assert_live_or_abort(tab)" in src


def test_build_probe_js_is_nonempty_str_with_markers():
    js = build_probe_js()
    assert isinstance(js, str) and len(js) > 50
    # 핵심 신호를 수집하는 JS 여야 한다
    assert "/talent/profile/" in js
    assert "multiple sign" in js.lower()
