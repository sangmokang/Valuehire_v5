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
# 저수지 모델 단계 1 — 캐노니컬 세그먼트(직군 묶음). RoleFamily 위에 올린 상위 레이어로,
# 단계 2의 연속 Harvest 단위(포지션 트리거 없이 segment_id만으로 도는)가 된다.
# 매핑 표/헬퍼는 segments.py 참조.
SegmentId = Literal[
    "it_ai_data",
    "marketing_growth",
    "sales_bd",
    "hr_finance_ops",
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
    segment_id: SegmentId = "unknown"
    keyword_plan: tuple[KeywordSession, ...] = ()


@dataclass(frozen=True)
class CandidateResultCard:
    """A single result card collected directly from a portal search results page.

    Holds only public search-listing fields (profile URL + visible snippet). It never
    carries credentials; outreach/sending is a separate, human-gated step.
    """

    profile_url: str
    source_channel: Channel
    snippet: str = ""


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
class ItemSearchResult:
    """Outcome of executing one queue item's keyword plan against a live portal.

    Produced by the worker adapter (``portal_queue_executor.execute_queue_item``) and
    consumed by ``run_live_queue_cycle`` to update item state and aggregate counts.

    ``collected_cards`` is the honest live signal: the number of public result-listing
    cards gathered. ``opened_profiles``/``saved_profiles``/``matched_profiles`` stay 0
    until the profile-open, save-rail, and scoring stages are wired (follow-up work).
    """

    status: Literal["done", "failed", "stopped"]
    collected_cards: int = 0
    opened_profiles: int = 0
    saved_profiles: int = 0
    matched_profiles: int = 0
    stop_reason: str = ""
    last_error: str = ""


@dataclass(frozen=True)
class QueueCycleSummary:
    searched_groups: tuple[str, ...]
    opened_profiles: int
    saved_profiles: int
    matched_profiles: int
    stopped_reasons: tuple[str, ...]
    updated_items: tuple[QueueItem, ...]
    collected_cards: int = 0

