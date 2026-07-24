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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from collections.abc import Iterable

from .models import CapturedProfile, Channel, Position, PositionMatch
from .matching_score_contract import CONTRACT_VERSION, calculate_final_score
from .scoring import (
    HIGH_TIER_SCHOOL_SIGNALS,
    count_short_tenure_hops,
    keyword_in_text,
)

# ── 사장님 확정 상수 (config JSON 과 단일 출처로 일치해야 함; H2/H3 가 교차검증) ──
LEGACY_PREFILTER_WEIGHTS: dict[str, float] = {
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
    "독립계약자",
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


# ── PC-C2: 전수조사 결과수 판단 트리(순수함수, 채널별 밴드) ──────────────────
# 밴드 경계·상한은 docs/sot/22 result_count_decision_tree 에서 채널별로 읽는다(SOT5 단일출처).
# PC-C3b(라이브 전수 순회)가 이 결정을 소비한다 — 채널마다 재구현·하드코딩 금지.
_SOT22_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "sot" / "22-talent-search-filters.json"
)

_BAND_RANGE_RE = re.compile(r"^(\d+)_to_(\d+)$")
_BAND_PLUS_RE = re.compile(r"^(\d+)_plus$")


@dataclass(frozen=True)
class TraversalPlan:
    """result_count 밴드 결정 — 라이브 전수 순회(PC-C3b)가 소비한다.

    action: "abort"(포기) | "full"(GOLD 전수, limit=None) | "top_n"(상위 N만) | "add_condition"(조건추가).
    limit:  top_n 이면 N, 그 외엔 None. band: 매칭된 SOT22 밴드 키(관측용). channel: 판단 채널.
    """

    action: str
    limit: int | None
    band: str
    channel: str


def _classify_band_action(prose: str) -> tuple[str, int | None]:
    """SOT22 밴드 서술 → (action, limit). 해석 불가 서술은 fail-closed(ValueError).

    ⚠️ 순서 중요: 300_plus/200_plus 서술은 "AND 추가 후에도 초과면 포기"라 '추가'와 '포기'를 둘 다
    담는다 — '추가'(add_condition)를 '포기'보다 먼저 판정해야 조건추가 밴드가 abort 로 오분류되지 않는다.
    """
    top = re.search(r"상위\s*(\d+)", prose)
    if top:
        return "top_n", int(top.group(1))
    if "추가" in prose:
        return "add_condition", None
    if "전수" in prose:
        return "full", None
    if "포기" in prose:
        return "abort", None
    raise ValueError(f"SOT22 밴드 서술을 해석할 수 없음(fail-closed): {prose!r}")


def _decision_tree_for(channel: str) -> dict:
    """SOT22 의 channels[channel].result_count_decision_tree(단일출처). 없으면 fail-closed."""
    data = json.loads(_SOT22_PATH.read_text(encoding="utf-8"))
    try:
        tree = data["channels"][channel]["result_count_decision_tree"]
    except (KeyError, TypeError):
        raise ValueError(f"SOT22 에 채널 result_count_decision_tree 없음: {channel!r}")
    if not isinstance(tree, dict):
        raise ValueError(f"SOT22 {channel} result_count_decision_tree 형식 오류")
    return tree


def plan_result_count_traversal(channel: str, result_count: int) -> TraversalPlan:
    """검색 결과수를 SOT22 채널별 밴드에 대입해 전수/부분/포기/조건추가를 결정한다(순수함수).

    밴드 경계·상한은 docs/sot/22 에서 채널별로 읽는다 — 하드코딩 이중정의 금지(SOT5). RPS 상한(60)을
    사람인/잡코리아(80)에 복사하면 61~80 GOLD 가 잘린다. 미지원 채널·음수·해석불가 밴드는 조용히
    넘기지 않고 ValueError(fail-closed).
    """
    # 타입 fail-closed: int 만 허용. float(10.5)·str("10")·None·bool 은 거부(ValueError, TypeError 아님).
    # bool 은 int 서브클래스라 type() 로 명시 거부한다(True 를 1명으로 오취급 방지). V1(Codex) 적대검증 회귀.
    if type(result_count) is not int:
        raise ValueError(
            f"result_count 는 int 여야 함(fail-closed): {type(result_count).__name__}={result_count!r}"
        )
    if result_count < 0:
        raise ValueError(f"result_count 는 음수일 수 없음: {result_count}")

    tree = _decision_tree_for(channel)

    # (lo, hi, key): "A_to_B"=[A,B], "N_plus"=[N,inf). 메타 키(_source·read_via·note 등)는 무시.
    bands: list[tuple[int, float, str]] = []
    for key in tree:
        m = _BAND_RANGE_RE.match(key)
        if m:
            bands.append((int(m.group(1)), float(m.group(2)), key))
            continue
        p = _BAND_PLUS_RE.match(key)
        if p:
            bands.append((int(p.group(1)), float("inf"), key))

    if not bands:
        raise ValueError(f"SOT22 {channel} 밴드가 비었음(fail-closed)")

    # lo 오름차순 첫 매칭 → 경계 중첩(예: [81,300] 과 [300,inf))에서 좁은(낮은 lo) 밴드 우선(결정론).
    for lo, hi, key in sorted(bands, key=lambda b: b[0]):
        if lo <= result_count <= hi:
            action, limit = _classify_band_action(tree[key])
            return TraversalPlan(action=action, limit=limit, band=key, channel=channel)

    raise ValueError(f"result_count={result_count} 가 {channel} 밴드에 없음(fail-closed)")


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


def hard_exclude_reason(
    profile: CapturedProfile, channel: Channel, *, seniority_max: int | None = None
) -> str | None:
    """채점 전 제외 사유. 없으면 None(=채점 대상). 사장님 확정 규칙.

    ``seniority_max`` 가 주어지면 JD 경력상한 초과(오버스펙)를 컷한다(PC-I1). 경력은
    ``profile.years_experience``(러너가 졸업연도/근속으로 산출, PC-I2). 미상(None)이면 컷하지 않는다
    — 잘못 제외하지 않는다(fail-open on unknown; 컷은 확실히 초과일 때만).
    """
    text = _profile_text(profile)  # 이미 _normalize(공백 제거·제로폭 strip·NFKC·소문자) 적용됨

    if any(_normalize(marker) in text for marker in FREELANCER_MARKERS):
        return "freelancer"

    if count_short_tenure_hops(profile.employment_history) >= FREQUENT_JOB_CHANGE_MIN_HOPS:
        return "frequent_job_change"

    if channel in PORTAL_SCHOOL_CUT_CHANNELS and _is_low_tier_school(profile.education):
        return "low_tier_school"

    if (
        seniority_max is not None
        and profile.years_experience is not None
        and profile.years_experience > seniority_max
    ):
        return "seniority_over_cap"

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
    """Legacy collection heuristic; never eligible for final send/registration.

    This remains only so existing CDP collection can rank an unreviewed local
    queue. Final candidate decisions must pass ``score_humansearch_contract``.
    """
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
    raw = sum(
        LEGACY_PREFILTER_WEIGHTS[key] * subs[key]
        for key in LEGACY_PREFILTER_WEIGHTS
    )
    score = max(0, min(100, round(100 * raw)))
    breakdown = {
        key: round(100 * LEGACY_PREFILTER_WEIGHTS[key] * subs[key])
        for key in LEGACY_PREFILTER_WEIGHTS
    }

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


def score_humansearch_contract(
    profile: CapturedProfile,
    position: Position,
    evaluation: dict[str, object],
) -> PositionMatch:
    """Turn validated Stage 3 gates/D1-D8 into the only sendable match."""

    result = calculate_final_score(evaluation)
    dimensions = evaluation["dimensions"]
    gates = evaluation["gates"]
    if not isinstance(dimensions, dict) or not isinstance(gates, list):
        # calculate_final_score normally catches this; keep the type boundary
        # explicit for static callers and future refactors.
        raise TypeError("evaluation must contain dimensions and gates")

    why_fit = tuple(
        f"{dimension_id}: {item['evidence']}"
        for dimension_id, item in dimensions.items()
        if isinstance(item, dict)
        and item.get("score") != "not_applicable"
        and isinstance(item.get("score"), int)
        and item["score"] >= 3
    )[:4]
    why_not = tuple(
        f"{gate['verdict']}: {gate['requirement']} — {gate['evidence']}"
        for gate in gates
        if isinstance(gate, dict) and gate.get("verdict") != "pass"
    )[:4]
    breakdown = {
        dimension_id: 0 if item["score"] == "not_applicable" else item["score"]
        for dimension_id, item in dimensions.items()
        if isinstance(item, dict)
    }
    return PositionMatch(
        candidate_url=profile.profile_url,
        profile_summary=profile.summary,
        position_id=position.position_id,
        score=int(result["score"]),
        why_fit=why_fit,
        why_not=why_not,
        evidence_paths=profile.evidence_paths,
        score_breakdown=breakdown,
        contract_version=CONTRACT_VERSION,
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
        if m.contract_version == CONTRACT_VERSION
        and set(m.score_breakdown) == {f"D{index}" for index in range(1, 9)}
        and m.score >= PASS_THRESHOLD
        and is_valid_profile_url(m.candidate_url)
    )
