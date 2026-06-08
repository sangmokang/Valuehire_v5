from __future__ import annotations

from .models import CapturedProfile, Position, PositionMatch

HIGH_TIER_COMPANY_SIGNALS = {
    "naver",
    "kakao",
    "coupang",
    "line",
    "baemin",
    "toss",
    "kurly",
    "zigzag",
    "todayhouse",
    "scaleup",
    "platform",
}


def _contains_any(text: str, signals: tuple[str, ...] | list[str]) -> list[str]:
    lower = text.lower()
    return [signal for signal in signals if signal.lower() in lower]


def _company_tier_score(profile: CapturedProfile) -> tuple[int, tuple[str, ...]]:
    companies = " ".join(profile.current_or_past_companies).lower()
    matched = tuple(signal for signal in HIGH_TIER_COMPANY_SIGNALS if signal in companies)
    if matched:
        return 10, tuple(f"company tier signal: {signal}" for signal in matched[:2])
    if profile.current_or_past_companies:
        return 6, ("company history present but tier requires human review",)
    return 0, ()


def score_profile_for_position(profile: CapturedProfile, position: Position) -> PositionMatch:
    text = " ".join(
        [
            profile.visible_text,
            profile.ocr_text,
            " ".join(profile.skills),
            " ".join(profile.industries),
            " ".join(profile.current_or_past_companies),
        ]
    )
    why_fit: list[str] = []
    why_not: list[str] = []

    must_have_hits = _contains_any(text, position.must_haves)
    must_score = round(40 * (len(must_have_hits) / max(1, len(position.must_haves))))
    if must_have_hits:
        why_fit.append(f"must-have direct hits: {', '.join(must_have_hits)}")
    else:
        why_not.append("no direct must-have evidence in visible/OCR text")

    seniority_score = 0
    if profile.years_experience is None:
        why_not.append("years of experience not visible")
    elif position.seniority_min <= profile.years_experience <= position.seniority_max:
        seniority_score = 15
        why_fit.append(f"{profile.years_experience} years fits requested seniority")
    elif abs(profile.years_experience - position.seniority_min) <= 1 or abs(profile.years_experience - position.seniority_max) <= 1:
        seniority_score = 9
        why_fit.append(f"{profile.years_experience} years is near requested seniority buffer")
    else:
        why_not.append(f"{profile.years_experience} years outside requested seniority range")

    education_score = 0
    if any(token in profile.education.lower() for token in ("bs", "ba", "bachelor", "master", "ms", "phd", "computer")):
        education_score = 10
        why_fit.append("education signal satisfies default degree filter")
    elif profile.education:
        education_score = 5
        why_not.append("education present but degree/major fit needs review")
    else:
        why_not.append("education not captured")

    company_score, company_reasons = _company_tier_score(profile)
    why_fit.extend(company_reasons)

    industry_stage_hits = _contains_any(
        text,
        [position.industry_segment, position.company_size, position.investment_stage],
    )
    industry_score = min(15, len(industry_stage_hits) * 5)
    if industry_stage_hits:
        why_fit.append(f"company stage/industry signals: {', '.join(industry_stage_hits)}")
    else:
        why_not.append("stage/industry/culture fit not directly visible")

    korea_score = 0
    if _contains_any(" ".join(profile.location_signals), ["korea", "seoul", "대한민국", "서울"]):
        korea_score += 3
    if _contains_any(" ".join(profile.language_signals), ["korean", "한국어"]):
        korea_score += 2
    if korea_score:
        why_fit.append("Korea/language signal present")
    else:
        why_not.append("Korea/language signal missing")

    evidence_score = 5 if profile.evidence_paths and (profile.visible_text or profile.ocr_text) else 0
    if not evidence_score:
        why_not.append("profile archive evidence path or text missing")

    risk_penalty = min(10, len(profile.risks) * 5)
    if profile.risks:
        why_not.extend(profile.risks)

    breakdown = {
        "must_have": must_score,
        "seniority": seniority_score,
        "education": education_score,
        "company_tier": company_score,
        "stage_industry_culture": industry_score,
        "korea_language_region": korea_score,
        "evidence_quality": evidence_score,
        "risk_penalty": -risk_penalty,
    }
    score = max(0, min(100, sum(breakdown.values())))
    return PositionMatch(
        candidate_url=profile.profile_url,
        profile_summary=profile.summary,
        position_id=position.position_id,
        score=score,
        why_fit=tuple(why_fit),
        why_not=tuple(why_not),
        evidence_paths=profile.evidence_paths,
        score_breakdown=breakdown,
    )


def top_matches_for_profile(
    profile: CapturedProfile,
    positions: tuple[Position, ...] | list[Position],
    top_n: int = 5,
) -> tuple[PositionMatch, ...]:
    matches = [score_profile_for_position(profile, position) for position in positions]
    matches.sort(key=lambda item: item.score, reverse=True)
    return tuple(matches[:top_n])

