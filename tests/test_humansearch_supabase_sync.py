"""S1 (2026-07-03 사장님) — humansearch 후보를 Supabase 에 적재하는 매핑 계약 (RED 먼저).

사장님 요구 필드:
 1. profile_archives  = 레쥬메 전문(text_content) + profile url (url 없으면 적재 금지)
 2. sourcing_results  = 포지션별 profile url·학력·경력·점수·왜 잘 맞는지(fit_reason)
"""
from __future__ import annotations

from tools.multi_position_sourcing.humansearch_supabase_sync import (
    to_profile_archive_row,
    to_sourcing_result_row,
)

LOCAL = {
    "url": "https://www.linkedin.com/talent/profile/AEMAAtest1",
    "name": "홍길동",
    "headline": "Robotics Engineer",
    "channel": "linkedin_rps",
    "position_id": "86ey50nwr",
    "screenshot_path": "/tmp/shot.png",
    "raw_text": "레쥬메 전문 텍스트 " * 50,
    "match_score": 83,
    "fit_reason": "must-have 직결: robot, c++",
    "candidate_briefing": '{"education": "한양대 석사", "why_fit": ["로봇 제어 14년"], "why_not": [], "otw": true}',
    "created_at": "2026-07-02 23:00:00",
}


def test_s1_profile_archive_has_full_resume_and_url() -> None:
    row = to_profile_archive_row(LOCAL)
    assert row["url"] == LOCAL["url"]
    assert row["text_content"] == LOCAL["raw_text"]          # 레쥬메 전문 그대로
    assert row["text_length"] == len(LOCAL["raw_text"])
    assert row["site"] == "linkedin_rps"
    assert LOCAL["screenshot_path"] in row["screenshot_paths"]
    assert row["captured_at"] == LOCAL["created_at"]  # NOT NULL 컬럼(400 재발 방지)


def test_s1_profile_archive_rejects_missing_url_or_text() -> None:
    """profile url 반드시 필요(사장님 0순위) — 없으면 적재 자체를 거부(fail-closed)."""
    assert to_profile_archive_row({**LOCAL, "url": ""}) is None
    assert to_profile_archive_row({**LOCAL, "url": "javascript:void(0)"}) is None
    assert to_profile_archive_row({**LOCAL, "raw_text": "  "}) is None


def test_s1_sourcing_result_has_position_contract_fields() -> None:
    row = to_sourcing_result_row(LOCAL, position_title="[모벤시스] Robotics C++")
    assert row["value"] == LOCAL["url"] and row["value_type"] == "profile_url"
    assert row["position_id"] == "86ey50nwr"
    assert row["position_title"] == "[모벤시스] Robotics C++"
    assert row["match_score"] == 83
    assert "한양대" in row["education_summary"]        # 학력
    assert "로봇 제어 14년" in row["career_summary"]    # 경력(핵심 근거)
    assert row["fit_reason"]                            # 왜 잘 맞는지
    assert row["channel"] == "linkedin_rps"


def test_s1_sourcing_result_rejects_invalid() -> None:
    assert to_sourcing_result_row({**LOCAL, "url": "not a url"}, "t") is None
    assert to_sourcing_result_row({**LOCAL, "match_score": None}, "t") is None


def test_s1_config_declares_supabase_persistence() -> None:
    """SOT config 에 Supabase 적재 계약이 선언돼 있어야 함(배선 증명)."""
    from tools.multi_position_sourcing.humansearch import load_humansearch_config
    sb = load_humansearch_config()["persistence"]["supabase"]
    assert sb["enabled"] is True
    assert "레쥬메 전문" in sb["profile_archives"] and "url" in sb["profile_archives"]
    assert "fit_reason" in sb["sourcing_results"]
    assert sb["mapper"] == "tools/multi_position_sourcing/humansearch_supabase_sync.py"
