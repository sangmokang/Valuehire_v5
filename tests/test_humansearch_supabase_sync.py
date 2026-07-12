"""S1 (2026-07-03 사장님) — humansearch 후보를 Supabase 에 적재하는 매핑 계약 (RED 먼저).

사장님 요구 필드:
 1. profile_archives  = 레쥬메 전문(text_content) + profile url (url 없으면 적재 금지)
 2. sourcing_results  = 포지션별 profile url·학력·경력·점수·왜 잘 맞는지(fit_reason)
"""
from __future__ import annotations

import json

from scripts import organization_analysis_supabase_backfill as org_backfill
from tools.multi_position_sourcing import organization_analysis as org_store
from tools.multi_position_sourcing.humansearch_supabase_sync import (
    to_organization_analysis_row,
    to_profile_archive_row,
    to_sourcing_result_row,
)
from tools.multi_position_sourcing.models import Position
from tools.multi_position_sourcing.scoring import position_organization_target

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


# ── V1(Codex 2026-07-03) 적발 결함 회귀봉인 ──
def test_s1_v1_broken_briefing_rejected() -> None:
    """깨진/누락 briefing 은 학력·경력 칸이 비게 됨 → 매칭 행 적재 거부(fail-closed)."""
    assert to_sourcing_result_row({**LOCAL, "candidate_briefing": "not-json{"}, "t") is None
    assert to_sourcing_result_row({**LOCAL, "candidate_briefing": "[1,2]"}, "t") is None
    assert to_sourcing_result_row({**LOCAL, "candidate_briefing": None}, "t") is None


def test_s1_v1_bool_score_rejected() -> None:
    """match_score=True 는 점수 1이 아니라 무효 — bool 거부, 0~100 범위 강제."""
    assert to_sourcing_result_row({**LOCAL, "match_score": True}, "t") is None
    assert to_sourcing_result_row({**LOCAL, "match_score": 101}, "t") is None
    assert to_sourcing_result_row({**LOCAL, "match_score": -1}, "t") is None


def test_s1_v1_career_summary_excludes_education_sentences() -> None:
    """경력 칸(career_summary)에 '학력 신호 양호(...)' 류 학력 문장 금지 — 진짜 경력 근거만."""
    local = {**LOCAL, "candidate_briefing": json.dumps({
        "education": "KAIST Master",
        "why_fit": ["학력 신호 양호(KAIST Master)", "must-have 직결: robot, c++", "nice-to-have: ros"],
        "why_not": [],
    }, ensure_ascii=False)}
    row = to_sourcing_result_row(local, "t")
    assert "학력" not in row["career_summary"], row["career_summary"]
    assert "robot" in row["career_summary"]
    assert "학력" not in row["fit_reason"].split(";")[0]  # 이유 첫 문장도 경력/직무 우선


def test_s1_organization_analysis_row_maps_position_context() -> None:
    row = to_organization_analysis_row(
        {
            "position_id": "pos-growth-uglylab",
            "company_name": "UglyLab",
            "role_title": "Growth Lead",
            "company_size": "startup",
            "industry_segment": "consumer_commerce",
            "investment_stage": "series_a",
            "organization_analysis": "Founder-adjacent growth owner for consumer commerce scaling.",
            "talent_density_notes": "Good pool from Kurly, Zigzag, TodayHouse, commerce and subscription apps.",
            "org_fit_target": "builder_target",
            "updated_at": "2026-07-08T00:00:00+00:00",
        }
    )
    assert row["position_id"] == "pos-growth-uglylab"
    assert row["organization_analysis"]
    assert row["talent_density_notes"]
    assert row["org_fit_target"] == "builder_target"
    assert row["updated_at"].startswith("2026-07-08")


def test_s1_organization_analysis_row_rejects_empty_payload() -> None:
    assert to_organization_analysis_row({}) is None
    assert to_organization_analysis_row({"position_id": "x", "company_name": "c", "role_title": "r"}) is None


def test_s1_organization_analysis_sqlite_roundtrip(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "ai-search-candidates.db"
    monkeypatch.setattr(org_store, "DB_PATH", db_path)
    position = Position(
        position_id="pos-growth-uglylab",
        company_name="UglyLab",
        role_title="Growth Lead",
        jd_text="consumer growth",
        company_size="startup",
        industry_segment="consumer_commerce",
        investment_stage="series_a",
        organization_analysis="Founder-adjacent growth owner for consumer commerce scaling.",
        talent_density_notes="Good pool from Kurly, Zigzag, TodayHouse, commerce and subscription apps.",
    )
    record = org_store.store_position(position, updated_at="2026-07-08T00:00:00+00:00")
    assert record.position_id == "pos-growth-uglylab"
    assert record.org_fit_target == "builder_target"
    rows = org_store.load_records(db_path)
    assert len(rows) == 1
    assert rows[0].company_name == "UglyLab"
    assert rows[0].organization_analysis


def test_s1_builder_stage_precedes_b2b_customer_context() -> None:
    """scaleup가 B2B 고객을 상대해도 운영 환경 target은 builder로 한 번만 분류한다."""
    position = Position(
        position_id="scaleup-b2b-owner",
        company_name="Example",
        role_title="B2B Sales Owner",
        jd_text="Scaleup owner who closes B2B enterprise deals hands-on.",
        company_size="scaleup",
    )
    assert org_store.org_fit_target_for_position(position) == "builder_target"


def test_s1_enterprise_sales_without_stage_signal_stays_enterprise_target() -> None:
    position = Position(
        position_id="enterprise-sales",
        company_name="LargeCo",
        role_title="Enterprise Sales Lead",
        jd_text="Close enterprise B2B deals for large customers.",
        company_size="large enterprise",
    )
    assert org_store.org_fit_target_for_position(position) == "enterprise_target"


def test_s1_store_and_runtime_share_all_builder_context_signals() -> None:
    for jd in (
        "Join an early-stage small team and build growth.",
        "Series B scrappy fast execution team.",
    ):
        position = Position(
            position_id="builder-signal",
            company_name="Example",
            role_title="Growth Lead",
            jd_text=jd,
        )
        assert org_store.org_fit_target_for_position(position) == "builder_target", jd


def test_s1_generic_sales_is_neutral_in_store_and_runtime_classifier() -> None:
    position = Position(
        position_id="generic-sales",
        company_name="Example",
        role_title="Sales Manager",
        jd_text="Lead the sales team and improve revenue.",
    )
    assert position_organization_target(position) == "neutral"
    assert org_store.org_fit_target_for_position(position) == "neutral_target"


def test_s1_store_runtime_target_parity_for_structured_stage_fields() -> None:
    for field, value in (
        ("investment_stage", "series_a"),
        ("investment_stage", "series_c"),
        ("company_size", "early-stage"),
    ):
        position = Position(
            position_id=f"stage-{field}",
            company_name="Example",
            role_title="Growth Lead",
            jd_text="Build growth systems.",
            **{field: value},
        )
        runtime_target = position_organization_target(position)
        assert runtime_target == "builder", (field, value)
        assert org_store.org_fit_target_for_position(position) == f"{runtime_target}_target"


def test_s1_backfill_dry_run_needs_no_supabase_credentials(tmp_path, monkeypatch, capsys) -> None:
    """--dry-run은 로컬 payload 검사이며 서비스 키를 읽거나 외부 요청을 해서는 안 된다."""
    monkeypatch.setattr(org_backfill, "DB_PATH", tmp_path / "missing.db")
    monkeypatch.setattr(
        org_backfill,
        "_env",
        lambda _key: (_ for _ in ()).throw(AssertionError("dry-run read credentials")),
    )
    monkeypatch.setattr(
        org_backfill,
        "_api",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dry-run called API")),
    )

    org_backfill.main(dry=True)

    output = capsys.readouterr().out
    assert "organization_analysis: 대상 0" in output
    assert "dry-run" in output
