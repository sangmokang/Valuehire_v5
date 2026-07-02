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


# ── Codex V1 적대검증 반영: 버전숫자·심볼접두·전각·배선누락 ──────────
@pytest.mark.parametrize(
    "kw,text",
    [
        (".net", "asp.net core developer"),  # 심볼 접두 — 매칭 유지
        ("c++", "c++17 and rust"),           # 버전 숫자 — 매칭 유지
        ("python", "python3 django"),         # 버전 숫자 — 매칭 유지
        ("react", "react18 hooks"),
    ],
)
def test_version_and_symbol_edges_still_match(kw, text):
    assert keyword_in_text(kw, text) is True


def test_fullwidth_normalized():
    assert keyword_in_text("java", "ＪＡＶＡ 개발자") is True  # NFKC 전각 정규화


def test_score_profile_for_position_must_have_uses_boundary():
    """Codex V1이 잡은 배선누락 회귀 — score_profile_for_position must_have도 경계매칭."""
    from tools.multi_position_sourcing.scoring import score_profile_for_position

    prof = _prof(visible_text="javascript developer", skills=("javascript",))
    pos = _pos(must_haves=("java",))
    match = score_profile_for_position(prof, pos)
    # 'java'가 'javascript'에 오탐되어 must-have 히트로 잡히면 RED
    assert "must-have direct hits: java" not in " ".join(match.why_fit)
