from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Channel = Literal["saramin", "jobkorea", "linkedin_rps", "public_web"]
RoleFamily = Literal[
    "backend",
    "frontend",
    "ai_ml",
    "product_po",
    "growth",
    "sales",
    "operations",
    "unknown",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Position:
    position_id: str
    company_name: str
    role_title: str
    jd_text: str
    seniority_min: int = 0
    seniority_max: int = 99
    company_size: str = ""
    industry_segment: str = ""
    investment_stage: str = ""
    organization_analysis: str = ""
    talent_density_notes: str = ""
    must_haves: tuple[str, ...] = ()
    nice_to_haves: tuple[str, ...] = ()
    source_url: str = ""


@dataclass(frozen=True)
class KeywordSession:
    channel: Channel
    standard_keyword: str
    variants: tuple[str, ...] = ()
    filters: dict[str, Any] = field(default_factory=dict)
    reset_before_run: bool = True
    llm_screening_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class PositionGroup:
    group_id: str
    role_family: RoleFamily
    seniority_range: tuple[int, int]
    core_keywords: tuple[str, ...]
    portal_keywords_by_channel: dict[Channel, tuple[str, ...]]
    filters_by_channel: dict[Channel, dict[str, Any]]
    position_ids: tuple[str, ...]
    company_similarity_notes: tuple[str, ...]
    keyword_plan: tuple[KeywordSession, ...] = ()


@dataclass(frozen=True)
class CapturedProfile:
    profile_url: str
    source_channel: Channel
    visible_text: str
    summary: str
    captured_at: str
    screenshot_path: str = ""
    ocr_text: str = ""
    canonical_url: str = ""
    years_experience: int | None = None
    education: str = ""
    current_or_past_companies: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    industries: tuple[str, ...] = ()
    location_signals: tuple[str, ...] = ()
    language_signals: tuple[str, ...] = ()
    evidence_paths: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()


@dataclass(frozen=True)
class PositionMatch:
    candidate_url: str
    profile_summary: str
    position_id: str
    score: int
    why_fit: tuple[str, ...]
    why_not: tuple[str, ...]
    evidence_paths: tuple[str, ...]
    score_breakdown: dict[str, int]


@dataclass(frozen=True)
class QueueItem:
    group_id: str
    channel: Channel
    keyword_plan: tuple[KeywordSession, ...]
    status: Literal["pending", "claimed", "done", "failed", "stopped"] = "pending"
    attempts: int = 0
    last_error: str = ""
    next_run_at: str = ""


@dataclass(frozen=True)
class QueueCycleSummary:
    searched_groups: tuple[str, ...]
    opened_profiles: int
    saved_profiles: int
    matched_profiles: int
    stopped_reasons: tuple[str, ...]
    updated_items: tuple[QueueItem, ...]

