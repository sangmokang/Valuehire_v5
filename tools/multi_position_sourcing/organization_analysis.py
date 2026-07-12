"""Organization analysis local store.

SQLite is the primary store. Supabase backfill scripts mirror this table in batch.
The table is keyed by ``position_id`` so the same position can be refreshed safely.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import Position
from .scoring import (
    POSITION_BUILDER_CONTEXT_SIGNALS,
    POSITION_ENTERPRISE_CONTEXT_SIGNALS,
    keyword_in_text,
    position_organization_target,
)

DB_PATH = Path.home() / ".vh-data" / "ai-search-candidates.db"
TABLE_NAME = "organization_analysis"

_SALES_SIGNALS = (
    "sales",
    "account executive",
    "ae",
    "b2b",
    "b2g",
    "enterprise",
    "g t m",
    "gtm",
    "deal",
    "closing",
    "pipeline",
    "revenue",
)


def _has_any_signal(text: str, signals: Iterable[str]) -> bool:
    return any(keyword_in_text(signal, text) for signal in signals)


@dataclass(frozen=True)
class OrganizationAnalysisRecord:
    position_id: str
    company_name: str
    role_title: str
    company_size: str
    industry_segment: str
    investment_stage: str
    organization_analysis: str
    talent_density_notes: str
    org_fit_target: str
    updated_at: str


def org_fit_target_for_position(position: Position) -> str:
    """Position 쪽 조직 맥락 라벨(후보 점수의 org_fit 와는 별개)."""
    target = position_organization_target(position)
    if target == "builder":
        return "builder_target"
    if target == "enterprise":
        return "enterprise_target"
    if position.talent_density_notes:
        return "density_target"
    return "neutral_target"


def derive_organization_analysis_text(position: Position) -> str:
    """빈 조직 분석을 포지션 역할/JD로 보완한다.

    명시 필드가 있으면 그대로 쓰고, 비어 있으면 역할 맥락을 최소한으로 문장화한다.
    """
    if position.organization_analysis.strip():
        return position.organization_analysis.strip()
    haystack = " ".join([position.role_title, position.jd_text]).lower()
    if _has_any_signal(haystack, _SALES_SIGNALS):
        if _has_any_signal(haystack, POSITION_ENTERPRISE_CONTEXT_SIGNALS):
            return "Hands-on enterprise/B2B sales lead owning large-deal closing, GTM execution, and team output."
        return "Hands-on sales lead owning pipeline, closing, and team output."
    if _has_any_signal(haystack, POSITION_BUILDER_CONTEXT_SIGNALS):
        return "Founder-adjacent execution role in a startup or scaleup environment."
    if _has_any_signal(haystack, POSITION_ENTERPRISE_CONTEXT_SIGNALS):
        return "Enterprise-facing operating role with reliability, compliance, or large-customer context."
    return f"Position context derived from {position.role_title}."


def derive_talent_density_notes(position: Position) -> str:
    """비어 있는 talent_density_notes 를 커리어 풀 관점으로 보완한다."""
    if position.talent_density_notes.strip():
        return position.talent_density_notes.strip()
    haystack = " ".join([position.role_title, position.jd_text]).lower()
    if _has_any_signal(haystack, _SALES_SIGNALS):
        if _has_any_signal(haystack, POSITION_ENTERPRISE_CONTEXT_SIGNALS):
            return "Relevant pools: enterprise sales, B2B SaaS, B2G, account executive, and GTM operators."
        return "Relevant pools: sales managers, account executives, and revenue operators."
    if _has_any_signal(haystack, POSITION_BUILDER_CONTEXT_SIGNALS):
        return "Relevant pools: startup founders, operators, and scaleup execution teams."
    if _has_any_signal(haystack, POSITION_ENTERPRISE_CONTEXT_SIGNALS):
        return "Relevant pools: enterprise software, compliance, reliability, and large-account operators."
    return "Relevant pools require further JD review."


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            position_id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            role_title TEXT NOT NULL,
            company_size TEXT NOT NULL DEFAULT '',
            industry_segment TEXT NOT NULL DEFAULT '',
            investment_stage TEXT NOT NULL DEFAULT '',
            organization_analysis TEXT NOT NULL DEFAULT '',
            talent_density_notes TEXT NOT NULL DEFAULT '',
            org_fit_target TEXT NOT NULL DEFAULT 'neutral_target',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def record_position(conn: sqlite3.Connection, position: Position, *, updated_at: str) -> OrganizationAnalysisRecord:
    """Position 1건을 sqlite 기본 저장소에 upsert 한다."""
    ensure_schema(conn)
    record = OrganizationAnalysisRecord(
        position_id=position.position_id,
        company_name=position.company_name,
        role_title=position.role_title,
        company_size=position.company_size,
        industry_segment=position.industry_segment,
        investment_stage=position.investment_stage,
        organization_analysis=derive_organization_analysis_text(position),
        talent_density_notes=derive_talent_density_notes(position),
        org_fit_target=org_fit_target_for_position(position),
        updated_at=updated_at,
    )
    conn.execute(
        f"""
        INSERT INTO {TABLE_NAME} (
            position_id, company_name, role_title, company_size, industry_segment,
            investment_stage, organization_analysis, talent_density_notes, org_fit_target, updated_at
        )
        VALUES (:position_id, :company_name, :role_title, :company_size, :industry_segment,
                :investment_stage, :organization_analysis, :talent_density_notes, :org_fit_target, :updated_at)
        ON CONFLICT(position_id) DO UPDATE SET
            company_name=excluded.company_name,
            role_title=excluded.role_title,
            company_size=excluded.company_size,
            industry_segment=excluded.industry_segment,
            investment_stage=excluded.investment_stage,
            organization_analysis=excluded.organization_analysis,
            talent_density_notes=excluded.talent_density_notes,
            org_fit_target=excluded.org_fit_target,
            updated_at=excluded.updated_at
        """,
        asdict(record),
    )
    conn.commit()
    return record


def position_row_to_record(row: dict[str, Any]) -> OrganizationAnalysisRecord | None:
    position_id = str(row.get("position_id", "") or "").strip()
    company_name = str(row.get("company_name", "") or "").strip()
    role_title = str(row.get("role_title", "") or "").strip()
    org = str(row.get("organization_analysis", "") or "").strip()
    density = str(row.get("talent_density_notes", "") or "").strip()
    if not position_id or not company_name or not role_title:
        return None
    if not org and not density:
        return None
    return OrganizationAnalysisRecord(
        position_id=position_id,
        company_name=company_name,
        role_title=role_title,
        company_size=str(row.get("company_size", "") or ""),
        industry_segment=str(row.get("industry_segment", "") or ""),
        investment_stage=str(row.get("investment_stage", "") or ""),
        organization_analysis=org,
        talent_density_notes=density,
        org_fit_target=str(row.get("org_fit_target", "") or "neutral_target"),
        updated_at=str(row.get("updated_at", "") or row.get("created_at", "") or ""),
    )


def fetch_records(conn: sqlite3.Connection) -> list[OrganizationAnalysisRecord]:
    ensure_schema(conn)
    rows = conn.execute(f"SELECT * FROM {TABLE_NAME} ORDER BY updated_at DESC, position_id ASC").fetchall()
    return [OrganizationAnalysisRecord(**dict(row)) for row in rows]


def load_records(db_path: Path = DB_PATH) -> list[OrganizationAnalysisRecord]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return fetch_records(conn)
    finally:
        conn.close()


def store_position(position: Position, *, updated_at: str) -> OrganizationAnalysisRecord:
    db_path = DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        return record_position(conn, position, updated_at=updated_at)
    finally:
        conn.close()
