"""humansearch 브라우징·로그인 라이브 프리플라이트 게이트 (docs/sot/27).

이 게이트가 없어서 2026-06-30 뤼튼 AX Sales 순회가 죽은 검색에서 0건을 조용히 뱉고
같은 네비게이션을 반복했다. 여기서는 *순수 판정*(evaluate_search_preflight)과
*fail-closed 배선*(assert_live_or_abort)을 강제한다.
"""
from __future__ import annotations

import pytest

from tools.multi_position_sourcing.humansearch_preflight import (
    PreflightError,
    assert_not_blocked_or_abort,
    assert_live_or_abort,
    build_probe_js,
    evaluate_blocking_preflight,
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


def test_zero_results_with_stray_card_fails():
    # 적대검증 발견 버그: '0 results'(검색 0건)인데 카드가 1개라도 잡히면 통과해선 안 된다.
    d = evaluate_search_preflight(_live_probe(card_count=1, results_text="0 results"))
    assert d["ok"] is False
    assert d["checks"]["results_rendered"] is False


def test_zero_count_korean_fails():
    d = evaluate_search_preflight(_live_probe(card_count=1, results_text="결과 0개"))
    assert d["ok"] is False
    assert d["checks"]["results_rendered"] is False


def test_real_count_formats_pass():
    # 링크드인 실제 결과수 포맷들은 통과해야 한다(false-negative 방지).
    for rt in ("1 result", "3.9K+ results", "1 – 25 of 3,912 results", "결과 3,912개", "3,912 명"):
        d = evaluate_search_preflight(_live_probe(results_text=rt))
        assert d["ok"] is True, rt


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


def test_linkedin_login_cap_is_login_expiry_not_captcha():
    d = evaluate_blocking_preflight(
        {
            "url": "https://www.linkedin.com/uas/login-cap?session_redirect=https%3A%2F%2Fwww.linkedin.com%2Ftalent%2Fprofile%2Fabc",
            "card_count": 0,
            "results_text": "",
            "logged_in_account": "",
            "multiple_signins": False,
            "captcha": False,
        }
    )
    assert d["ok"] is False
    assert d["checks"]["no_login_redirect"] is False
    assert d["checks"]["no_captcha"] is True
    assert any("로그인" in reason for reason in d["reasons"])
    assert not any("캡차" in reason for reason in d["reasons"])


def test_live_search_without_account_label_reuses_existing_session():
    # 우상단 계정명 셀렉터가 화면 언어/A-B UI 때문에 빗나가도 카드와 결과수가 정상으로
    # 렌더됐다면 이미 로그인된 세션이다. 계정명 공백만으로 재로그인시키면 안 된다.
    d = evaluate_search_preflight(_live_probe(logged_in_account="  "))
    assert d["ok"] is True
    assert d["checks"]["logged_in"] is True


def test_empty_account_without_live_results_fails():
    d = evaluate_search_preflight(
        _live_probe(logged_in_account="  ", card_count=0, results_text="")
    )
    assert d["ok"] is False
    assert d["checks"]["logged_in"] is True
    assert d["checks"]["results_rendered"] is False


def test_non_talent_url_with_stale_result_dom_fails():
    d = evaluate_search_preflight(
        _live_probe(
            url="https://www.linkedin.com/feed/",
            logged_in_account="",
            card_count=1,
            results_text="1 result",
        )
    )
    assert d["ok"] is False
    assert d["checks"]["on_search_surface"] is False


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


def test_blocking_preflight_allows_normal_profile_page_without_results():
    d = evaluate_blocking_preflight(
        {
            "url": "https://www.linkedin.com/talent/profile/abc",
            "card_count": 0,
            "results_text": "",
            "logged_in_account": "",
            "multiple_signins": False,
            "captcha": False,
        }
    )
    assert d["ok"] is True


def test_blocking_preflight_stops_captcha_on_profile_page():
    d = evaluate_blocking_preflight(
        {
            "url": "https://www.linkedin.com/talent/profile/abc",
            "card_count": 0,
            "results_text": "",
            "multiple_signins": False,
            "captcha": True,
        }
    )
    assert d["ok"] is False
    assert d["checks"]["no_captcha"] is False


def test_assert_not_blocked_or_abort_raises_on_session_lock():
    tab = _FakeTab(
        {
            "url": "https://www.linkedin.com/enterprise-authentication/sessions",
            "card_count": 0,
            "results_text": "",
            "multiple_signins": True,
            "captcha": False,
        }
    )
    with pytest.raises(PreflightError):
        assert_not_blocked_or_abort(tab)


def test_runner_wires_the_gate_no_orphan():
    # R4 배선 증명: 러너가 assert_live_or_abort 를 import 하고 호출한다(고아 아님).
    from pathlib import Path

    src = Path("tools/multi_position_sourcing/humansearch_cdp_run.py").read_text(encoding="utf-8")
    assert "from tools.multi_position_sourcing.humansearch_preflight import assert_live_or_abort" in src
    assert "assert_live_or_abort(tab)" in src


def test_build_probe_js_regex_matches_evaluate_formats_incl_korean():
    # V2 발견 회귀 방지: build_probe_js 의 결과수 정규식이 evaluate 가 받는 포맷(특히 한국어
    # '결과 N개')을 모두 잡아야 한다. 안 그러면 살아있는 검색을 거부(false-negative).
    import re as _re

    js = build_probe_js()
    pattern = r"\d[\d,.]*\s*(?:K\+?|results?|명|개)"
    assert pattern in js, "build_probe_js 가 evaluate 와 동일한 결과수 정규식을 써야 한다"
    pat = _re.compile(pattern, _re.I)
    for rt in ("1 result", "3.9K+ results", "1 – 25 of 3,912 results", "결과 3,912개", "3,912 명"):
        m = pat.search(rt)
        assert m, f"JS 정규식이 못 잡음: {rt}"
        # 추출된 토큰이 evaluate 의 positive-count 도 통과해야 한다(end-to-end 일관성)
        assert evaluate_search_preflight(_live_probe(results_text=m.group(0)))["ok"] is True, rt


def test_build_probe_js_is_nonempty_str_with_markers():
    js = build_probe_js()
    assert isinstance(js, str) and len(js) > 50
    # 핵심 신호를 수집하는 JS 여야 한다
    assert "/talent/profile/" in js
    assert "multiple sign" in js.lower()
    assert "one-time-code" in js
    assert "captcha: challenge" in js
    assert "getComputedStyle" in js
    assert "getBoundingClientRect" in js


def test_build_probe_js_only_flags_visible_challenge_ui() -> None:
    """숨은/화면 밖 OTP DOM과 후보 서술은 차단으로 오인하지 않고 실제 보이는 UI만 잡는다."""
    from playwright.sync_api import sync_playwright

    cases = (
        ('<input autocomplete="one-time-code" style="width:120px;height:24px">', True),
        ('<div style="display:none"><input autocomplete="one-time-code" style="width:120px;height:24px"></div>', False),
        ('<div style="visibility:hidden"><input autocomplete="one-time-code" style="width:120px;height:24px"></div>', False),
        ('<div style="opacity:0"><input autocomplete="one-time-code" style="width:120px;height:24px"></div>', False),
        ('<div aria-hidden="true"><input autocomplete="one-time-code" style="width:120px;height:24px"></div>', False),
        ('<input autocomplete="one-time-code" style="position:fixed;left:-10000px;width:120px;height:24px">', False),
        ('<p>2단계 인증 제품을 만든 후보 경력</p>', False),
        ('<h1>Security verification</h1>', True),
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 800, "height": 600})
            for html, expected in cases:
                page.set_content(html)
                probe = page.evaluate(build_probe_js())
                assert probe["captcha"] is expected, (html, probe)
        finally:
            browser.close()
