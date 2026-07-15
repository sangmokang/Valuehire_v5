from __future__ import annotations

import re
import unicodedata

from .models import CapturedProfile, EmploymentTenure, Position, PositionMatch

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

# 저수지 단계 3 — 우수 대학 티어 신호(소문자 비교). 새 신호 추가 시 같은 커밋에 테스트도 보강.
HIGH_TIER_SCHOOL_SIGNALS = {
    "서울대",
    "연세대",
    "고려대",
    "서강대",
    "성균관대",
    "한양대",
    "kaist",
    "카이스트",
    "postech",
    "포스텍",
    "포항공대",
    "stanford",
    "mit",
    "berkeley",
    "cmu",
    "harvard",
    "oxford",
    "cambridge",
    # ── 세계 명문대 확장 (2026-06-26 사장님 지시 — UCLA·미국 Ivy·세계 top 포함) ──
    # substring 매칭이라 오탐을 줄이려 모호한 곳은 풀네임을 쓴다(예: 'columbia university').
    "ucla",
    "university of california, los angeles",
    "uc berkeley",
    "yale",
    "princeton",
    "columbia university",
    "cornell",
    "university of pennsylvania",
    "upenn",
    "wharton",
    "dartmouth",
    "brown university",
    "caltech",
    "california institute of technology",
    "university of chicago",
    "uchicago",
    "northwestern university",
    "duke university",
    "johns hopkins",
    "new york university",
    "nyu",
    "university of michigan",
    "georgia institute of technology",
    "georgia tech",
    "carnegie mellon",
    # 세계(미국 외) 명문
    "imperial college",
    "university college london",
    "london school of economics",
    "eth zurich",
    "eth zürich",
    "epfl",
    "national university of singapore",
    "nanyang technological",
    "tsinghua",
    "peking university",
    "university of tokyo",
    "kyoto university",
    "university of toronto",
    "mcgill university",
    "university of hong kong",
    "hong kong university of science",
}

# 학위/전공은 서로 대체 가능한 표기(alias)다. 별칭 개수는 점수 분모가 아니며,
# 하나 이상 확인되면 education 축의 "긍정 신호" 요건 1개만 충족한다.
EDUCATION_DEGREE_SIGNALS = (
    "bs", "b.s.", "ba", "b.a.", "bachelor", "bsc",
    "master", "msc", "ms", "m.s.", "mba", "phd", "ph.d.", "computer",
    "학사", "석사", "박사", "대학교 졸업", "대학 졸업",
    "4년제 졸업", "대졸", "공학사", "이학사",
)

EDUCATION_MAX_SCORE = 10
COMPANY_TIER_MAX_SCORE = 10
UNIVERSITY_TIER_MAX_SCORE = 8
_SIGNAL_CRITERIA_TOTAL = 2  # 근거 존재 + 긍정 신호 확인

# 1년 미만 재직을 "짧은 재직(이직)"으로 본다.
SHORT_TENURE_MONTHS = 12


def _month_index(year_month: str) -> int | None:
    """"YYYY-MM" → 절대 월 인덱스(year*12+month). 형식이 아니면 None."""
    try:
        year, month = str(year_month).split("-")[:2]
        return int(year) * 12 + int(month)
    except (ValueError, AttributeError):
        return None


def tenure_months(start_month: str, end_month: str) -> int | None:
    """완료된 재직의 개월 수. ``end_month`` 가 비면 현재 재직 → None(감점 대상 아님)."""
    start = _month_index(start_month)
    if start is None or not end_month:
        return None
    end = _month_index(end_month)
    if end is None:
        return None
    return end - start


def count_short_tenure_hops(
    history: tuple[EmploymentTenure, ...] | list[EmploymentTenure],
    *,
    threshold_months: int = SHORT_TENURE_MONTHS,
) -> int:
    """1년 미만 재직 후 이직(완료된 짧은 재직)의 횟수. 현재 재직(end 빈값)은 제외."""
    hops = 0
    for tenure in history:
        months = tenure_months(tenure.start_month, tenure.end_month)
        if months is not None and 0 <= months < threshold_months:
            hops += 1
    return hops


def job_stability_penalty(hops: int) -> int:
    """이직 안정성 감점. 2회부터 감점, 3회 이상은 더 크게(단조 증가, -30 캡)."""
    if hops < 2:
        return 0
    return -min(30, 10 * (hops - 1))


def _weighted_portion_score(matched: int, total: int, weight: int) -> int:
    """v4 scorer의 ``matched / total * weight``를 정수 half-up으로 계산한다.

    v4의 ``total == 0 -> 1``은 JD 요구사항 부재용 규칙이다. 후보 근거 축에서는 정보 없음이
    만점이 되면 안 되므로 0을 반환한다. 잘못된 matched 값도 0..total로 제한한다.
    """
    if total <= 0 or weight <= 0:
        return 0
    bounded = max(0, min(matched, total))
    return (2 * bounded * weight + total) // (2 * total)


def _evidence_signal_score(*, has_evidence: bool, has_signal: bool, weight: int) -> int:
    matched = int(has_evidence) + int(has_evidence and has_signal)
    return _weighted_portion_score(matched, _SIGNAL_CRITERIA_TOTAL, weight)


_ASCII_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")


def _fold(s: str) -> str:
    """NFKC 정규화 후 소문자 — 전각(ＪＡＶＡ)·호환문자를 반각으로 접는다(하드제외 매처와 동일 철학)."""
    return unicodedata.normalize("NFKC", s).lower()


def _visible_fold(s: str) -> str:
    """NFKC/lower 후 제로폭 포맷 문자와 variation selector를 제거한다."""
    return "".join(
        character
        for character in _fold(s)
        if unicodedata.category(character) != "Cf"
        and not 0xFE00 <= ord(character) <= 0xFE0F
        and not 0xE0100 <= ord(character) <= 0xE01EF
    )


def keyword_in_text(keyword: str, text: str) -> bool:
    """직무 키워드가 text에 포함되는지 — ASCII 단일토큰은 영숫자 단어경계, 그 외는 부분일치.

    오탐 차단: 'java'∉'javascript', 'account'∉'accounting', 'ai'∉'email', 'go'∉'golang'.
    정탐 유지: 버전 숫자('python'∈'python3', 'c++'∈'c++17')·심볼 접두('.net'∈'asp.net').
    한글 등 비ASCII·다단어 구는 형태소 경계가 모호해 부분일치. NFKC 로 전각(ＪＡＶＡ) 정규화.
    """
    kw = _fold(keyword).strip()
    if not kw:
        return False
    text_folded = _fold(text)
    if not _ASCII_TOKEN_RE.fullmatch(kw):
        return kw in text_folded
    # ASCII 단일토큰: 키워드의 영숫자 가장자리에만 경계를 건다.
    #  왼쪽: 앞이 영숫자면 단어 일부(오탐) → 차단. 키워드가 심볼로 시작하면(.net) 경계 불필요.
    #  오른쪽: 뒤가 '문자'면 오탐(java|javascript) → 차단. '숫자'는 버전표기라 허용(python3).
    left = r"(?<![a-z0-9])" if kw[0].isalnum() else ""
    right = r"(?![a-z])" if kw[-1].isalnum() else ""
    return re.search(left + re.escape(kw) + right, text_folded) is not None


def _role_direct_score(profile: CapturedProfile, position: Position) -> tuple[int, tuple[str, ...]]:
    """직무 직결성 — 후보 기술스택(skills)이 JD must/nice 키워드와 직결되면 가점."""
    skills = " ".join(profile.skills).lower()
    direct = [kw for kw in (position.must_haves + position.nice_to_haves) if keyword_in_text(kw, skills)]
    score = min(12, len(direct) * 4)
    reasons = (f"role-direct skill match: {', '.join(direct[:3])}",) if direct else ()
    return score, reasons


def _contains_any(text: str, signals: tuple[str, ...] | list[str]) -> list[str]:
    lower = text.lower()
    return [signal for signal in signals if signal.lower() in lower]


def _matching_signals(
    text: str,
    signals: tuple[str, ...] | set[str],
    *,
    strict_entities: bool = False,
) -> tuple[str, ...]:
    """결정론적 alias OR 매칭. 여러 alias가 잡혀도 호출자는 한 논리 요건으로 센다."""
    text_folded = _visible_fold(text)

    def alias_in_text(signal: str) -> bool:
        alias = _visible_fold(signal).strip()
        if not alias:
            return False
        if re.search(r"[가-힣]", alias):
            if not strict_entities:
                return alias in text_folded
            left = r"(?<![^\W_])"
            right = r"(?=학교|(?![^\W_]))" if alias.endswith("대") else r"(?![^\W_])"
            return re.search(left + re.escape(alias) + right, text_folded) is not None
        left = r"(?<![^\W_])" if alias[0].isalnum() else ""
        right = r"(?![^\W_])" if any(character.isalnum() for character in alias) else ""
        return re.search(left + re.escape(alias) + right, text_folded) is not None

    return tuple(signal for signal in sorted(signals) if alias_in_text(signal))


def _degree_match_text(education: str) -> str:
    """학위 신호용 정규화. 전문학사/전문대학교 졸업은 4년제 학위 신호에서 제외한다."""
    text = _visible_fold(education)
    associate_patterns = (
        r"전\s*문\s*대\s*학(?:\s*교)?\s*(?:전\s*문\s*)?학\s*사",
        r"전\s*문\s*학\s*사",
        r"전\s*문\s*대\s*학(?:\s*교)?\s*졸\s*업",
        r"[23]\s*년\s*제\s*(?:전\s*문\s*)?대\s*학(?:\s*교)?\s*졸\s*업",
        r"(?:전\s*문\s*|[23]\s*년\s*제\s*(?:전\s*문\s*)?)대\s*졸",
        r"초\s*대\s*졸",
        r"(?:준|무|장|비(?:\s*[-–—]|\s*\(非\))?)\s*학\s*사|학\s*사(?:\s*학\s*위)?\s*(?:미\s*(?:취\s*득|소\s*지)|아\s*님)",
    )
    for pattern in associate_patterns:
        text = re.sub(pattern, " ", text)
    return text


def _education_score(profile: CapturedProfile) -> tuple[int, tuple[str, ...]]:
    education = _visible_fold(profile.education).strip()
    matched = (
        _matching_signals(_degree_match_text(education), EDUCATION_DEGREE_SIGNALS)
        if education
        else ()
    )
    score = _evidence_signal_score(
        has_evidence=bool(education),
        has_signal=bool(matched),
        weight=EDUCATION_MAX_SCORE,
    )
    if matched:
        return score, (f"education signal satisfies default degree filter: {matched[0]}",)
    if education:
        return score, ("education present but degree/major fit needs review",)
    return score, ()


def _university_tier_score(profile: CapturedProfile) -> tuple[int, tuple[str, ...]]:
    education = _visible_fold(profile.education).strip()
    matched = (
        _matching_signals(
            education,
            HIGH_TIER_SCHOOL_SIGNALS,
            strict_entities=True,
        )
        if education
        else ()
    )
    score = _evidence_signal_score(
        has_evidence=bool(education),
        has_signal=bool(matched),
        weight=UNIVERSITY_TIER_MAX_SCORE,
    )
    if matched:
        return score, (f"university tier signal: {matched[0]}",)
    if education:
        return score, ("university education present but tier requires human review",)
    return score, ()


def _company_tier_score(profile: CapturedProfile) -> tuple[int, tuple[str, ...]]:
    company_items = tuple(
        filter(
            None,
            (_visible_fold(company).strip() for company in profile.current_or_past_companies),
        )
    )
    companies = " ".join(company_items)
    # sorted: set 반복 순서(PYTHONHASHSEED 의존)가 사장님 브리핑 문구를 흔들지 않게 결정론 고정.
    matched = (
        _matching_signals(
            companies,
            HIGH_TIER_COMPANY_SIGNALS,
            strict_entities=True,
        )
        if companies
        else ()
    )
    score = _evidence_signal_score(
        has_evidence=bool(company_items),
        has_signal=bool(matched),
        weight=COMPANY_TIER_MAX_SCORE,
    )
    if matched:
        return score, tuple(f"company tier signal: {signal}" for signal in matched[:2])
    if company_items:
        return score, ("company history present but tier requires human review",)
    return score, ()


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

    must_have_hits = [kw for kw in position.must_haves if kw and keyword_in_text(kw, text)]
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

    education_score, education_reasons = _education_score(profile)
    if education_score == EDUCATION_MAX_SCORE:
        why_fit.extend(education_reasons)
    elif education_score:
        why_not.extend(education_reasons)
    else:
        why_not.append("education not captured")

    company_score, company_reasons = _company_tier_score(profile)
    if company_score == COMPANY_TIER_MAX_SCORE:
        why_fit.extend(company_reasons)
    elif company_score:
        why_not.extend(company_reasons)

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

    # 저수지 단계 3 — 품질 4기준.
    university_score, university_reasons = _university_tier_score(profile)
    if university_score == UNIVERSITY_TIER_MAX_SCORE:
        why_fit.extend(university_reasons)
    elif university_score:
        why_not.extend(university_reasons)

    role_direct_score, role_direct_reasons = _role_direct_score(profile, position)
    why_fit.extend(role_direct_reasons)

    hops = count_short_tenure_hops(profile.employment_history)
    job_stability = job_stability_penalty(hops)
    if job_stability < 0:
        why_not.append(
            f"job-hopping risk: {hops} short tenures (<1yr) ending in a move → stability penalty"
        )

    breakdown = {
        "must_have": must_score,
        "seniority": seniority_score,
        "education": education_score,
        "company_tier": company_score,
        "university_tier": university_score,
        "role_direct": role_direct_score,
        "stage_industry_culture": industry_score,
        "korea_language_region": korea_score,
        "evidence_quality": evidence_score,
        "risk_penalty": -risk_penalty,
        "job_stability": job_stability,
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
