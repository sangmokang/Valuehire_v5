"""humansearch — 사람이 걸어둔 검색 결과를 순회·채점·디스코드 발송하는 스킬의 결정론 코어.

사장님 확정(2026-06-25):
  - 채점 가중치: 학력 0.30 / 직무적합 0.50 / 프로필 논리력 0.10 / 이직 안정성 0.10 (합 1.0)
  - 합격선 70점 이상만 Discord #ai_search 발송
  - 사람인·잡코리아는 채점 *전에* 하드 제외(프리랜서·잦은이직·하위학교). 지방 국공립대는 허용.
  - 링크드인은 open-to-work 가중 점수제 → 학교 하드 제외 미적용(학력은 가중치로 반영).

브라우저 순회·스크린샷은 raw CDP 단일탭(raw_cdp.py)이 주력 — 사장님 9222 디버그 크롬에 한 타깃만
붙는다(탭 과다 시 connectOverCDP hang 회피, 2026-06-26). MCP claude-in-chrome 은 폴백.
발송은 multi_position_sourcing 인프라 재사용. 이 모듈은 *판정 로직*만 담아 기계 검증(verify) 대상으로 고정한다.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any

from collections.abc import Iterable

from .models import CapturedProfile, Channel, Position, PositionMatch
from .scoring import (
    HIGH_TIER_SCHOOL_SIGNALS,
    count_short_tenure_hops,
    keyword_in_text,
)

# ── 사장님 확정 상수 (config JSON 과 단일 출처로 일치해야 함; H2/H3 가 교차검증) ──
SCORING_WEIGHTS: dict[str, float] = {
    "education": 0.30,
    "role_fit": 0.50,
    "profile_logic": 0.10,
    "job_stability": 0.10,
}
PASS_THRESHOLD = 70

# 채점 전 하드 제외 — 사람인·잡코리아에만 학교 컷 적용(링크드인 제외).
PORTAL_SCHOOL_CUT_CHANNELS: frozenset[Channel] = frozenset({"saramin", "jobkorea"})

FREELANCER_MARKERS = (
    "freelance",
    "freelancer",
    "프리랜서",
    "개인사업자",
    "independent contractor",
    "외주",
    "contract worker",
)

# 전문대·하위권·비정규 학위 신호(소문자 비교). 4년제 정규대(지방 국공립 포함)는 여기 없음 → 통과.
LOW_TIER_SCHOOL_MARKERS = (
    "전문대",
    "전문학교",
    "직업전문학교",
    "사이버대",
    "방송통신대",
    "학점은행",
    "polytechnic",
    "vocational",
)

# 지방 국공립대 — 사장님 확정상 허용(명시 allowlist; 하위 사립과 구분해 안전하게 통과).
REGIONAL_NATIONAL_UNIVERSITIES = (
    "부산대",
    "경북대",
    "전남대",
    "전북대",
    "충남대",
    "충북대",
    "경상국립대",
    "경상대",
    "강원대",
    "제주대",
    "단국대",  # memory: 단국대 이상 허용
    "pusan national",
    "kyungpook national",
)

FREQUENT_JOB_CHANGE_MIN_HOPS = 2

_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "skills" / "humansearch" / "humansearch.config.json"
)

_URL_SAFE_SCHEMES = {"http", "https"}


def load_humansearch_config() -> dict[str, Any]:
    """스킬 설정 JSON 로드(단일 출처). 코드 상수와의 일치는 테스트가 강제한다."""
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def is_valid_profile_url(url: Any) -> bool:
    """발송 가능한 프로필 URL인지 — 사장님 0순위 '프로필 url 절대 오류 없어야'.

    http/https + 호스트가 있어야 통과. 빈값·공백(선행·후행·내부)·상대경로·스킴 없음·
    javascript:void·ftp 거부. 공백이 끼면 무조건 거부 — 복붙 깨진 URL 발송 차단(사장님 0순위).
    """
    if not isinstance(url, str):
        return False
    if not url.strip():
        return False
    if any(ch.isspace() for ch in url):  # 선행/후행/내부 공백 모두 거부
        return False
    # 제로폭/제어/포맷 문자(U+200B 류, BOM, C0/C1) 거부 — isspace 가 못 잡는 보이지 않는 깨짐.
    if any(unicodedata.category(ch) in {"Cc", "Cf", "Cn", "Co", "Cs"} for ch in url):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parsed.scheme in _URL_SAFE_SCHEMES and bool(parsed.hostname)


def _is_invisible(ch: str) -> bool:
    """마커 매칭 전에 지워야 할 '보이지 않는 삽입 문자'인지.

    category Cf(포맷) 전부 — U+200B..U+200D(제로폭)·U+FEFF(BOM)뿐 아니라 U+2060(word joiner)·
    U+00AD(soft hyphen)·U+180E 등 같은 우회 벡터를 한 번에 닫는다(자기 적대검증서 재현).
    variation selector(U+FE00..U+FE0F, U+E0100..U+E01EF)도 보이지 않는 삽입 통로라 함께 제거.
    is_valid_profile_url 이 이미 Cf 를 거부하는 것과 동일 정책(단일 출처).
    """
    if unicodedata.category(ch) == "Cf":
        return True
    cp = ord(ch)
    return 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF


def _normalize(text: str) -> str:
    """하드제외 마커 매칭용 *단일* 정규화 — 프리랜서·전문대·전각 매칭 '전에' 적용(SOT5).

    순서: NFKC(전각 ＦＲＥＥＬＡＮＣＥ·호환문자 표준형 접기) →
          보이지 않는 삽입 문자(_is_invisible: category Cf·variation selector) 제거 →
          공백 전부 제거(collapse) → 소문자.
    제로폭·띄어쓰기('전 문 대학')·전각 어느 우회로도 매처가 새지 않게 한 곳으로 통일(2차검증 재현 차단).
    """
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text)
    stripped = "".join(ch for ch in folded if not _is_invisible(ch))
    collapsed = re.sub(r"\s+", "", stripped)
    return collapsed.lower()


def _profile_text(profile: CapturedProfile) -> str:
    raw = " ".join([profile.summary, profile.visible_text, profile.ocr_text])
    return _normalize(raw)


def hard_exclude_reason(profile: CapturedProfile, channel: Channel) -> str | None:
    """채점 전 제외 사유. 없으면 None(=채점 대상). 사장님 확정 규칙."""
    text = _profile_text(profile)  # 이미 _normalize(공백 제거·제로폭 strip·NFKC·소문자) 적용됨

    if any(_normalize(marker) in text for marker in FREELANCER_MARKERS):
        return "freelancer"

    if count_short_tenure_hops(profile.employment_history) >= FREQUENT_JOB_CHANGE_MIN_HOPS:
        return "frequent_job_change"

    if channel in PORTAL_SCHOOL_CUT_CHANNELS and _is_low_tier_school(profile.education):
        return "low_tier_school"

    return None


def _is_low_tier_school(education: str) -> bool:
    edu = _normalize(education)  # 프리랜서 경로와 동일 정규화 — '전 문 대학'·제로폭 우회 차단
    if not edu:
        return False
    # 전문대학원(법학·의학·경영 등)은 하위 아님 — '전문대' 부분일치로 인한 과잉제외 방지.
    # normalize 의 공백 제거가 '경영 전문 대학원'까지 '전문대학원'으로 접으므로 low_tier 마커보다 먼저 건다.
    if "전문대학원" in edu:
        return False
    # 지방 국공립·명문대 신호가 있으면 절대 하위로 보지 않는다(allowlist 우선).
    if any(_normalize(name) in edu for name in REGIONAL_NATIONAL_UNIVERSITIES):
        return False
    if any(_normalize(sig) in edu for sig in HIGH_TIER_SCHOOL_SIGNALS):
        return False
    return any(_normalize(marker) in edu for marker in LOW_TIER_SCHOOL_MARKERS)


# ── 하위 점수 (각 0.0~1.0) ─────────────────────────────────────────
def _education_subscore(profile: CapturedProfile) -> float:
    edu = (profile.education or "").lower()
    if not edu:
        return 0.0
    if any(sig.lower() in edu for sig in HIGH_TIER_SCHOOL_SIGNALS):
        return 1.0
    if any(name.lower() in edu for name in REGIONAL_NATIONAL_UNIVERSITIES):
        return 0.8
    if any(token in edu for token in ("phd", "doctor", "박사")):
        return 0.8
    if any(token in edu for token in ("master", "ms ", "석사")):
        return 0.7
    if any(token in edu for token in ("bachelor", "bs", "ba", "학사", "대학교", "university")):
        return 0.55
    return 0.3


def _role_fit_subscore(profile: CapturedProfile, position: Position) -> tuple[float, list[str]]:
    text = " ".join([profile.visible_text, profile.ocr_text, " ".join(profile.skills)]).lower()
    must = [kw for kw in position.must_haves if kw and keyword_in_text(kw, text)]
    nice = [kw for kw in position.nice_to_haves if kw and keyword_in_text(kw, text)]
    must_ratio = len(must) / max(1, len(position.must_haves))
    nice_ratio = (len(nice) / len(position.nice_to_haves)) if position.nice_to_haves else 0.0
    sub = min(1.0, 0.8 * must_ratio + 0.2 * nice_ratio)
    reasons = []
    if must:
        reasons.append(f"must-have 직결: {', '.join(must[:3])}")
    if nice:
        reasons.append(f"nice-to-have: {', '.join(nice[:3])}")
    return sub, reasons


def _profile_logic_subscore(profile: CapturedProfile) -> float:
    """프로필 텍스트 정리·논리력 프록시 — 요약과 본문이 충분히 정돈됐는지."""
    summary = profile.summary.strip()
    body = (profile.visible_text or profile.ocr_text).strip()
    if summary and len(summary) >= 20 and body:
        return 1.0
    if summary and body:
        return 0.6
    if summary or body:
        return 0.3
    return 0.0


def _job_stability_subscore(profile: CapturedProfile) -> tuple[float, list[str]]:
    hops = count_short_tenure_hops(profile.employment_history)
    sub = max(0.0, 1.0 - 0.34 * hops)
    reasons = []
    if hops >= FREQUENT_JOB_CHANGE_MIN_HOPS:
        reasons.append(f"단기 이직 {hops}회 — 안정성 하위")
    return sub, reasons


def score_humansearch(profile: CapturedProfile, position: Position) -> PositionMatch:
    """가중 점수(0~100)로 PositionMatch 환원. 가중치는 SCORING_WEIGHTS 단일 출처."""
    edu_sub = _education_subscore(profile)
    role_sub, role_reasons = _role_fit_subscore(profile, position)
    logic_sub = _profile_logic_subscore(profile)
    stability_sub, stability_reasons = _job_stability_subscore(profile)

    subs = {
        "education": edu_sub,
        "role_fit": role_sub,
        "profile_logic": logic_sub,
        "job_stability": stability_sub,
    }
    # 합격선 경계 정확도: 항목별 round() 누적은 raw 69.2 를 70 으로 부풀린다(합격 오판).
    # → raw 가중합을 *한 번만* 반올림해 총점을 낸다. breakdown 은 표시용(합 != score 일 수 있음).
    raw = sum(SCORING_WEIGHTS[key] * subs[key] for key in SCORING_WEIGHTS)
    score = max(0, min(100, round(100 * raw)))
    breakdown = {key: round(100 * SCORING_WEIGHTS[key] * subs[key]) for key in SCORING_WEIGHTS}

    why_fit: list[str] = []
    why_not: list[str] = []
    if edu_sub >= 0.55:
        why_fit.append(f"학력 신호 양호({profile.education})")
    elif profile.education:
        why_not.append(f"학력 적합성 재검토 필요({profile.education})")
    else:
        why_not.append("학력 미수집")
    why_fit.extend(role_reasons)
    if not role_reasons:
        why_not.append("JD 핵심 키워드 직결 근거 부족")
    if logic_sub < 0.6:
        why_not.append("프로필 텍스트 정리·논리 근거 부족")
    why_not.extend(stability_reasons)

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


def eligible_matches_for_send(matches: Iterable[PositionMatch]) -> tuple[PositionMatch, ...]:
    """Discord #ai_search 로 보낼 후보만 남긴다 — 발송 직전 강제 게이트(코드 배선).

    조건: 점수 >= PASS_THRESHOLD **그리고** candidate_url 무결(is_valid_profile_url).
    score_humansearch 는 URL 을 검사하지 않으므로, 깨진/공백/javascript URL 후보가
    브리핑까지 새어나가지 않도록 *발송 경로의 단일 관문*으로 여기서 거른다(사장님 0순위).
    """
    return tuple(
        m
        for m in matches
        if m.score >= PASS_THRESHOLD and is_valid_profile_url(m.candidate_url)
    )
