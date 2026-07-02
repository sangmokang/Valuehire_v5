"""Harness Gate 2 — PC-I3 직무 키워드 매칭 정밀도 (substring→단어경계). RED 먼저.

현재 결함: humansearch._role_fit_subscore·scoring._role_direct_score가 `kw.lower() in text`
부분문자열 매칭이라 'java'가 'javascript'에, 'account'가 'accounting'에, 'ai'가 'email'에 오탐.
role_fit(가중 0.50 최대축)이 부풀려져 부적격 후보가 70점 합격선을 넘음(라이브 채점 배선).

인수기준: ASCII 단일토큰은 단어경계 매칭(오탐0), 한글은 부분일치, 대소문자 무시.
각 단언은 "일부러 깨면 RED, 실제면 GREEN".
"""
from __future__ import annotations

import pytest

from tools.multi_position_sourcing import humansearch
from tools.multi_position_sourcing.models import CapturedProfile, Position
from tools.multi_position_sourcing.scoring import _role_direct_score, keyword_in_text


def _prof(**kw) -> CapturedProfile:
    base = dict(
        profile_url="https://example.com/in/1",
        source_channel="linkedin_rps",
        visible_text="",
        summary="",
        captured_at="2026-07-03",
    )
    base.update(kw)
    return CapturedProfile(**base)


def _pos(**kw) -> Position:
    base = dict(position_id="p1", company_name="C", role_title="R", jd_text="")
    base.update(kw)
    return Position(**base)


# ── keyword_in_text 순수 계약 ─────────────────────────────────────
@pytest.mark.parametrize(
    "kw,text",
    [
        ("java", "javascript developer"),   # java ∉ javascript
        ("account", "accounting only"),     # account ∉ accounting
        ("ai", "email main"),               # ai ∉ email/main
        ("react", "reactive programming"),  # react ∉ reactive
    ],
)
def test_ascii_token_no_false_positive(kw, text):
    assert keyword_in_text(kw, text) is False


@pytest.mark.parametrize(
    "kw,text",
    [
        ("java", "backend java spring"),
        ("account", "account manager"),
        ("ai", "ai engineer"),
        ("Java", "worked with JAVA daily"),  # 대소문자 무시
    ],
)
def test_ascii_token_boundary_match(kw, text):
    assert keyword_in_text(kw, text) is True


def test_cjk_substring_preserved():
    assert keyword_in_text("자바", "자바개발자") is True


@pytest.mark.parametrize(
    "kw,text,expected",
    [
        ("c++", "c++ and rust", True),
        ("c++", "c plus plus", False),
        ("go", "go and rust", True),
        ("go", "golang rocks", False),   # go ∉ golang (알파벳 경계)
    ],
)
def test_symbol_tokens(kw, text, expected):
    assert keyword_in_text(kw, text) is expected


@pytest.mark.parametrize("kw", ["", "   "])
def test_empty_keyword_is_false(kw):
    assert keyword_in_text(kw, "anything at all") is False


# ── 프로덕션 배선: 채점 함수가 경계 매처를 쓴다 ────────────────────
def test_role_fit_subscore_no_false_positive():
    prof = _prof(skills=("javascript",))
    pos = _pos(must_haves=("java",))
    sub, _reasons = humansearch._role_fit_subscore(prof, pos)
    assert sub == 0.0  # 'java'가 'javascript'에 오탐되어 role_fit 가산되면 RED


def test_role_fit_subscore_true_positive():
    prof = _prof(skills=("java", "spring"))
    pos = _pos(must_haves=("java",))
    sub, _reasons = humansearch._role_fit_subscore(prof, pos)
    assert sub > 0.0


def test_role_direct_score_no_false_positive():
    prof = _prof(skills=("accounting",))
    pos = _pos(must_haves=("account",))
    score, _reasons = _role_direct_score(prof, pos)
    assert score == 0  # 'account'가 'accounting'에 오탐되어 가점되면 RED
