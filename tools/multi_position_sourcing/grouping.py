from __future__ import annotations

import hashlib
from collections import defaultdict
from statistics import median

from .keywords import build_keyword_plan, portal_keywords_for_family
from .models import Position, PositionGroup, RoleFamily

ROLE_SIGNALS: dict[RoleFamily, tuple[str, ...]] = {
    "backend": ("backend", "server", "spring", "nestjs", "java", "kotlin", "api", "platform", "infra"),
    "frontend": ("frontend", "react", "web", "typescript", "next.js", "ui engineer"),
    "ai_ml": ("ai engineer", "machine learning", "ml", "llm", "pytorch", "model", "mlops", "recsys"),
    "product_po": ("product owner", "product manager", "po", "pm", "service planning", "ontology", "플랫폼기획", "서비스기획"),
    "growth": ("growth", "performance marketing", "crm", "retention", "funnel", "referral", "cmo"),
    "sales": ("sales", "account executive", "enterprise", "pipeline", "saas", "crm", "renewal"),
    "operations": ("operations", "settlement", "billing", "content admin", "정산", "운영"),
}

CORE_KEYWORDS: dict[RoleFamily, tuple[str, ...]] = {
    "backend": ("backend api", "spring", "node/nest", "platform", "infra", "production"),
    "frontend": ("react", "typescript", "next.js", "design system", "web performance"),
    "ai_ml": ("python", "pytorch", "ml production", "llm", "recsys", "mlops"),
    "product_po": ("product owner", "product manager", "service planning", "platform planning", "stakeholder"),
    "growth": ("growth", "performance marketing", "crm", "retention", "consumer funnel"),
    "sales": ("b2b sales", "saas", "pipeline", "crm", "enterprise"),
    "operations": ("operations", "settlement", "billing", "partner communication", "data hygiene"),
    "unknown": (),
}


def infer_role_family(position: Position) -> RoleFamily:
    haystack = f"{position.role_title} {position.jd_text}".lower()
    best_family: RoleFamily = "unknown"
    best_count = 0
    for family, signals in ROLE_SIGNALS.items():
        count = sum(1 for signal in signals if signal.lower() in haystack)
        if count > best_count:
            best_family = family
            best_count = count
    return best_family


def _seniority_bucket(position: Position) -> tuple[int, int]:
    midpoint = median([position.seniority_min, position.seniority_max])
    if midpoint <= 3:
        return (0, 4)
    if midpoint <= 8:
        return (3, 10)
    return (7, 15)


def _similarity_key(position: Position) -> tuple[str, tuple[int, int], str, str]:
    family = infer_role_family(position)
    seniority = _seniority_bucket(position)
    size = position.company_size or "unknown_size"
    stage = _stage_bucket(position.investment_stage)
    if family in {"backend", "product_po", "ai_ml"}:
        return (family, seniority, size, stage)
    return (family, seniority, position.industry_segment or "unknown_industry", stage)


def _stage_bucket(stage: str) -> str:
    normalized = stage.lower()
    if any(signal in normalized for signal in ("series_b", "series_c", "series d", "profitable_growth", "growth")):
        return "growth_stage"
    if any(signal in normalized for signal in ("seed", "series_a", "pre_a")):
        return "early_stage"
    return normalized or "unknown_stage"


def _group_id(key: tuple[str, tuple[int, int], str, str], positions: list[Position]) -> str:
    seed = "|".join([str(key), ",".join(sorted(p.position_id for p in positions))])
    suffix = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    return f"{key[0]}-{key[1][0]}to{key[1][1]}-{suffix}"


def group_positions(positions: tuple[Position, ...] | list[Position]) -> tuple[PositionGroup, ...]:
    buckets: dict[tuple[str, tuple[int, int], str, str], list[Position]] = defaultdict(list)
    for position in positions:
        buckets[_similarity_key(position)].append(position)

    groups: list[PositionGroup] = []
    for key, grouped_positions in sorted(buckets.items(), key=lambda item: str(item[0])):
        family = key[0]  # type: ignore[assignment]
        seniority = key[1]
        notes = tuple(
            f"{p.company_name}: size={p.company_size or 'unknown'}, "
            f"industry={p.industry_segment or 'unknown'}, stage={p.investment_stage or 'unknown'}, "
            f"talent_density={p.talent_density_notes or 'not_provided'}"
            for p in grouped_positions
        )
        portal_keywords, filters = portal_keywords_for_family(family, seniority)
        shell_group = PositionGroup(
            group_id=_group_id(key, grouped_positions),
            role_family=family,
            seniority_range=seniority,
            core_keywords=CORE_KEYWORDS.get(family, ()),
            portal_keywords_by_channel=portal_keywords,
            filters_by_channel=filters,
            position_ids=tuple(p.position_id for p in grouped_positions),
            company_similarity_notes=notes,
        )
        groups.append(
            PositionGroup(
                **{**shell_group.__dict__, "keyword_plan": build_keyword_plan(shell_group)}
            )
        )
    return tuple(groups)
