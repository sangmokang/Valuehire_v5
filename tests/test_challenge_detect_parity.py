"""Harness Gate 2 — PC-F3 로그인 게이트 보안챌린지 감지에 RPS 세션락·authwall 신호 추가.

현행 `_has_security_challenge`는 7토큰만 봐서 RPS 멀티세션 락(multiple sign-ins/only one session/
enterprise-authentication)·authwall 을 못 잡는다 → 봇이 STOP 못 하고 계속 두드림(SOT2).
SOT26:163 이 콕 집은 이 신호들을 추가한다. 단 후보 텍스트에 흔한 SOT26 토큰(recaptcha·보안문자 OCR·
unusual activity 등)은 raw abort 오탐 위험이라 제외 — _CHALLENGE_TOKENS ⊆ SOT26(완전일치 아님).
각 단언은 "일부러 깨면 RED, 실제면 GREEN".
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing.portal_login import _CHALLENGE_TOKENS, _has_security_challenge

_REPO = Path(__file__).resolve().parents[1]


# ── 신규: RPS 세션락·authwall 신호 탐지(현행 7토큰이 못 잡던 것) ──
@pytest.mark.parametrize(
    "text",
    [
        "You can have Only one session at a time",   # RPS 세션락
        "multiple sign-ins detected on this account",
        "enterprise-authentication/sessions redirect",
        "LinkedIn authwall blocking access",
    ],
)
def test_detects_session_lock_and_block_signals(text):
    assert _has_security_challenge(text) is True


# ── 기존 7토큰 회귀 유지 ──
@pytest.mark.parametrize(
    "text",
    ["보안문자 입력", "CAPTCHA required", "2단계 인증", "인증번호 6자리", "이상 접근 감지", "checkpoint 감지", "security challenge"],
)
def test_keeps_existing_tokens(text):
    assert _has_security_challenge(text) is True


def test_url_field_also_checked():
    assert _has_security_challenge("", url="https://www.linkedin.com/enterprise-authentication/sessions") is True


@pytest.mark.parametrize(
    ("text", "url"),
    [
        ("환영합니다 대시보드", ""),
        ("검색 결과 128건", ""),
        ("normal profile page content", ""),
        ("LinkedIn login page", "https://www.linkedin.com/uas/login-cap?session_redirect=https%3A%2F%2Fwww.linkedin.com%2Ftalent%2Fhome"),
        ("li.protechts frame loaded", "https://li.protechts.net/"),
    ],
)
def test_no_false_positive_on_benign(text, url):
    assert _has_security_challenge(text, url=url) is False


@pytest.mark.parametrize(
    "candidate_text",
    [
        "enterprise authentication architect at Toss",  # 'enterprise-authentication'(하이픈) 아님
        "single sign-on SSO expert",                     # 'multiple sign-ins' 아님
        "session management and scaling",                # 'only one session' 아님
        "built an authentication wall for the API",      # 'authwall'(붙임) 아님
        "Senior ML Engineer, PyTorch",
    ],
)
def test_new_tokens_do_not_false_match_candidate_text(candidate_text):
    """신규 추가 토큰(authwall·multiple sign-ins·enterprise-authentication 등)이 흔한 후보/JD 문구를
    오탐하지 않아야 한다 — 오탐하면 정상 로그인/검색을 막는 가용성 회귀(adversarial V2/V3)."""
    assert _has_security_challenge(candidate_text) is False


def test_tokens_are_subset_of_sot26():
    """단일 진실 드리프트/오탈자 차단 — 코드 토큰은 SOT26 unified_regex 토큰의 부분집합이어야 한다."""
    sot = json.loads((_REPO / "docs/sot/26-portal-login-spec.json").read_text(encoding="utf-8"))
    sot_tokens = {t.strip().lower() for t in sot["block_detection"]["unified_regex"].split("|")}
    code_tokens = {t.strip().lower() for t in _CHALLENGE_TOKENS}
    missing = code_tokens - sot_tokens
    assert not missing, f"SOT26 에 없는 토큰(오탈자?): {missing}"


def test_critical_session_lock_tokens_present():
    """SOT26:163 이 지시한 RPS 멀티세션 락·authwall 신호가 반드시 포함돼야 한다."""
    code = {t.lower() for t in _CHALLENGE_TOKENS}
    for required in ["multiple sign-ins", "only one session", "enterprise-authentication", "authwall"]:
        assert required in code, f"필수 세션락/블록 토큰 {required!r} 누락"
