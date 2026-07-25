"""후보자 프로필 저장 강제 게이트 (RED) — SOT-26 failure_policy 훅 강제.

전진성 작업(제안 발송·후보 등록·pos-fill)은 그 후보자의 ProfileArchiveStore 영수증이
있을 때만 허용한다. 없으면 차단(정식 캡처 러너 안내). 검색·로그인·읽기는 통과.
"""
from __future__ import annotations

import sqlite3

import pytest

from tools.multi_position_sourcing import profile_archive_gate as pag

SARAMIN_URL = "https://hiring.saramin.co.kr/applicant-view/position/resume/19452507"


def _make_db(tmp_path, rows=()):
    db = tmp_path / "profile_archives.sqlite3"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE profile_archive_receipts (id INTEGER PRIMARY KEY, "
        "profile_url TEXT NOT NULL, channel TEXT NOT NULL, position_id TEXT NOT NULL, "
        "scenario TEXT, page INTEGER, candidate_index INTEGER, screenshot_path TEXT, "
        "screenshot_sha256 TEXT, resume_text TEXT, captured_at REAL NOT NULL, "
        "UNIQUE(position_id, profile_url))"
    )
    for url, pos in rows:
        con.execute(
            "INSERT INTO profile_archive_receipts(profile_url,channel,position_id,captured_at) "
            "VALUES(?,?,?,?)", (url, "saramin", pos, 1.0))
    con.commit()
    con.close()
    return db


# ── U2: 영수증 조회 ──────────────────────────────────────────────────


def test_receipt_exists_true(tmp_path):
    db = _make_db(tmp_path, [(SARAMIN_URL, "61")])
    assert pag.receipt_exists(db, profile_url=SARAMIN_URL, position_id="61") is True


def test_receipt_exists_false_when_absent(tmp_path):
    db = _make_db(tmp_path, [])
    assert pag.receipt_exists(db, profile_url=SARAMIN_URL, position_id="61") is False


def test_receipt_exists_url_only_match(tmp_path):
    db = _make_db(tmp_path, [(SARAMIN_URL, "61")])
    assert pag.receipt_exists(db, profile_url=SARAMIN_URL, position_id="") is True


def test_receipt_missing_db_is_false(tmp_path):
    assert pag.receipt_exists(tmp_path / "nope.sqlite3",
                              profile_url=SARAMIN_URL, position_id="61") is False


# ── U1: 순수 게이트 ──────────────────────────────────────────────────


def _has(url, pos=""):
    saved = {(SARAMIN_URL, "61")}
    return lambda u, p: (u, p) in saved or (u == SARAMIN_URL and (u, "61") in saved and not p)


ADVANCE_SKILLS = ["jdbuilder", "pos-fill", "saramin-talent-sourcing", "jobkorea-talent-sourcing"]


@pytest.mark.parametrize("skill", ADVANCE_SKILLS)
def test_advance_without_receipt_blocks(skill):
    reason = pag.block_reason(
        "Skill", {"skill": skill, "request_text": f"이 후보 {SARAMIN_URL} 제안"},
        has_receipt=lambda u, p: False)
    assert reason is not None and "저장" in reason


@pytest.mark.parametrize("skill", ADVANCE_SKILLS)
def test_advance_with_receipt_passes(skill):
    reason = pag.block_reason(
        "Skill", {"skill": skill, "request_text": f"이 후보 {SARAMIN_URL} 제안"},
        has_receipt=lambda u, p: True)
    assert reason is None


@pytest.mark.parametrize("skill", ["aisearch", "humansearch", "url", "login"])
def test_search_and_login_skills_pass(skill):
    reason = pag.block_reason(
        "Skill", {"skill": skill, "request_text": SARAMIN_URL},
        has_receipt=lambda u, p: False)
    assert reason is None, "검색·로그인 러너가 저장을 수행 — 차단 안 함"


def test_read_only_bash_passes():
    assert pag.block_reason(
        "Bash", {"command": f"cat resume.txt # {SARAMIN_URL}"},
        has_receipt=lambda u, p: False) is None


def test_advance_without_profile_url_passes():
    # 후보 식별자가 없으면 이 게이트 대상 아님(다른 게이트 소관).
    assert pag.block_reason(
        "Skill", {"skill": "jdbuilder", "request_text": "회사 소개 JD 작성"},
        has_receipt=lambda u, p: False) is None


def test_extract_profile_url_variants():
    for u in (SARAMIN_URL,
              "https://www.jobkorea.co.kr/Corp/Person/Resume?rIdx=123",
              "https://www.linkedin.com/talent/profile/AAA"):
        got = pag.extract_profile_url(f"이 후보 {u} 등록해줘")
        assert got == u, u
    assert pag.extract_profile_url("프로필 URL 없음") == ""
