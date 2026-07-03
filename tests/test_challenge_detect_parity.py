"""Harness Gate 2 — PC-F3 보안챌린지 감지 SOT26 전체 토큰 통일. RED 먼저.

현행 `_has_security_challenge`는 7토큰만 봐서 RPS 멀티세션 락(multiple sign-ins/Only one session/
enterprise-authentication)·authwall·recaptcha·/uas/login·unusual activity 등을 못 잡는다 → 봇이
STOP 못 하고 계속 두드림(SOT2 위반). SOT26 block_detection.unified_regex(18토큰)와 파리티로 통일.
각 단언은 "일부러 깨면 RED, 실제면 GREEN".
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing.portal_login import _has_security_challenge

_REPO = Path(__file__).resolve().parents[1]


# ── 현행 7토큰에 없던 SOT26 신규 토큰 — 현재 False(RED), 통일 후 True ──
@pytest.mark.parametrize(
    "text",
    [
        "google reCAPTCHA widget loaded",         # recaptcha
        "자동입력 방지 문자를 입력하세요",                  # 자동입력 방지
        "redirected to /uas/login-cap page",       # /uas/login + login-cap
        "we noticed unusual activity on your account",  # unusual activity
        "please verify you are not a robot",       # verify you
        "multiple sign-ins detected on this account",   # multiple sign-ins
        "You can have Only one session at a time",  # Only one session (RPS 락)
        "enterprise-authentication/sessions redirect",  # enterprise-authentication
        "LinkedIn authwall blocking access",       # authwall
        "protechts anti-bot page",                 # protechts
    ],
)
def test_detects_new_sot26_tokens(text):
    assert _has_security_challenge(text) is True


# ── 기존 7토큰 회귀 유지 ──
@pytest.mark.parametrize(
    "text",
    ["보안문자 입력", "CAPTCHA required", "2단계 인증", "인증번호 6자리", "이상 접근 감지", "checkpoint challenge", "security challenge"],
)
def test_keeps_existing_tokens(text):
    assert _has_security_challenge(text) is True


def test_url_field_also_checked():
    assert _has_security_challenge("", url="https://www.linkedin.com/uas/login-cap") is True


@pytest.mark.parametrize("text", ["환영합니다 대시보드", "검색 결과 128건", "normal profile page content"])
def test_no_false_positive_on_benign(text):
    assert _has_security_challenge(text) is False


def test_token_set_parity_with_sot26():
    """단일 진실 강제 — 코드 토큰 집합이 SOT26 unified_regex 와 정확히 일치(드리프트=RED)."""
    from tools.multi_position_sourcing.portal_login import _CHALLENGE_TOKENS

    sot = json.loads((_REPO / "docs/sot/26-portal-login-spec.json").read_text(encoding="utf-8"))
    sot_tokens = {t.strip().lower() for t in sot["block_detection"]["unified_regex"].split("|")}
    code_tokens = {t.strip().lower() for t in _CHALLENGE_TOKENS}
    assert code_tokens == sot_tokens


def _preflight_captcha_regex():
    """preflight in-browser JS 의 captcha 정규식을 추출·컴파일(JS≈Python re 프록시로 행동검증)."""
    import re as _re

    from tools.multi_position_sourcing.humansearch_preflight import build_probe_js

    m = _re.search(r"captcha: /(.+?)/i\.test", build_probe_js())
    assert m, "captcha 정규식 추출 실패"
    return _re.compile(m.group(1), _re.IGNORECASE)


@pytest.mark.parametrize(
    "block_text",
    [
        "LinkedIn authwall blocking access",
        "we noticed unusual activity on your account",
        "google reCAPTCHA widget",
        "보안문자 를 입력하세요",
        "자동입력 방지 문자",
        "protechts anti-bot",
        "redirected to /uas/login-cap",
        "enterprise-authentication/sessions",
    ],
)
def test_preflight_detects_real_block_signals(block_text):
    """Codex V1 반영 — 사람검색 preflight 도 실제 블록 신호(authwall·unusual activity·recaptcha 등)를 탐지(STOP)."""
    assert _preflight_captcha_regex().search(block_text)


@pytest.mark.parametrize(
    "benign_text",
    [
        "loves a good technical challenge",  # 'challenge' 흔한 후보/JD 단어
        "2단계 전형 면접 안내",                    # '2단계' 흔한 전형 문구
        "we will verify your references",     # 'verify you' 흔한 문구
        "128 results 검색 결과",
        "Senior Backend Engineer at Toss",
    ],
)
def test_preflight_no_false_abort_on_benign_results_text(benign_text):
    """V2 F1 회귀 봉인 — 결과페이지의 흔한 후보/JD 문구를 캡차로 오탐해 순회를 중단하면 안 됨."""
    assert not _preflight_captcha_regex().search(benign_text)


def test_preflight_keeps_multiple_signin_field():
    """멀티세션 락은 preflight 의 별도 필드(multiple_signins)에서 계속 잡는다."""
    from tools.multi_position_sourcing.humansearch_preflight import build_probe_js

    js = build_probe_js()
    assert "multiple sign-ins" in js and "only one session" in js
