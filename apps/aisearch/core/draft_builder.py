"""AC-9 — /jdbuilder 연동 후보 전달 메시지 "초안" 생성기. 발송 절대 아님.

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §AC-9
  "후보가 등록되면 회사 브리핑 요소를 포함한 전달용 메시지 초안을 만든다.
   발송 버튼은 절대 누르지 않는다."

이 모듈은 순수 문자열 조립 + 기계 검문만 한다 — 네트워크/브라우저 코드 0.
후보에게 나가는 최종 클릭은 언제나 사장님 수동 게이트(SOT3)이며,
여기서는 dict(초안)만 반환한다.

재사용한 레포 SOT 계약 (추측 금지 — 전부 실측 인용):
  - 필수 인입 문구(R1/R21): .codex/skills/jdbuilder/SKILL.md:15 (R1 CTA 필수),
    .codex/skills/linkedin-rps-jd-set-builder/SKILL.md:34 (R21 P.S. 원문 —
    https://valuehire.cc/resume), VERIFIED-PULL·P.S. 마커 검문 =
    tools/multi_position_sourcing/inmail_precheck.py:79-83,290-294
  - 개인화(R2): .codex/skills/jdbuilder/SKILL.md:16 — "이름·현재회사·헤드라인을
    인사말에 반영(범용 인사말 금지)"; 재료 스펙 =
    .codex/skills/linkedin-rps-jd-set-builder/SKILL.md:130-141 (§3.3 meta 6종)
  - 본문 밀도: .codex/skills/linkedin-rps-jd-set-builder/SKILL.md:18 (R2 —
    "풍성한 본문은 1,800~1,899자를 목표"), :69, :266-279 (§6.3 len<1800 가드)
  - 회사 브리핑 8요소 + 최소 6개(미만이면 보고):
    tools/multi_position_sourcing/inmail_precheck.py:34-44
    (원 SOT = .claude/skills/position-register/SKILL.md §1.5,
     .codex/skills/linkedin-rps-jd-set-builder/SKILL.md:33 R20 — 8요소)
  - 채널별 글자수 상한 linkedin_rps 1,899 / saramin·jobkorea 2,000:
    tools/multi_position_sourcing/inmail_precheck.py:48-52
  - NFC 코드포인트 글자수 기준: tools/multi_position_sourcing/inmail_precheck.py:89-91
  - 발송 전 기계 체크리스트 재사용(복제 금지):
    tools/multi_position_sourcing/inmail_precheck.py:247-314 precheck_inmail
"""
from __future__ import annotations

from tools.multi_position_sourcing.inmail_precheck import (
    BRIEFING_ELEMENT_KEYS,
    BRIEFING_MIN_ELEMENTS,
    CHANNEL_CHAR_LIMITS,  # SOT 상한 dict 를 그대로 재사용 (사본 금지)
    char_count,
    count_briefing_elements,
    precheck_inmail,  # 검문 로직 재사용 — 여기서 복제하지 않는다
)

__all__ = [
    "BRIEFING_ELEMENT_KEYS",
    "BRIEFING_MIN_ELEMENTS",
    "CHANNEL_CHAR_LIMITS",
    "DRAFT_MIN_CHARS",
    "REQUIRED_PS_CTA",
    "DraftCharLimitError",
    "DraftDensityError",
    "DraftPrecheckError",
    "build_candidate_draft",
]

# §6.3 밀도 하한 — linkedin-rps-jd-set-builder SKILL.md:18 "1,800~1,899자 목표",
# :275 `if (len < 1800)` 가드. 111자류 빈약 초안은 여기서 거부한다.
DRAFT_MIN_CHARS = 1800

# R21 원문 그대로 — .codex/skills/linkedin-rps-jd-set-builder/SKILL.md:34.
# "딱 맞지 않으셔도"는 부정문이라 inmail_precheck 과장 린트(:71)를 통과한다.
REQUIRED_PS_CTA = (
    "P.S. 지금 이 포지션이 딱 맞지 않으셔도 괜찮습니다. "
    "밸류커넥트가 이력서를 직접 검증해, 더 잘 맞는 기회까지 연결해 드립니다 — "
    "무료 커리어 검증 신청: https://valuehire.cc/resume"
)

# VERIFIED-PULL 문단 — inmail_precheck.py:79-80 마커("이력서 피드백") 충족 필수.
_VERIFIED_PULL_PARAGRAPH = (
    "밸류커넥트는 이 제안과 별개로 무료 이력서 피드백(VERIFIED-PULL)도 제공하고 "
    "있습니다. 검토 의향이 있으시면 편하신 방법으로 회신 부탁드립니다."
)

# §1.5 표의 한국어 라벨 — 본문 브리핑 bullet 에 사용
_BRIEFING_LABELS: dict[str, str] = {
    "one_line": "한 줄 소개",
    "history": "설립·연혁",
    "funding_stage": "상장/투자",
    "revenue": "매출·이익",
    "headcount": "임직원",
    "parent_group": "모기업/계열",
    "ceo_quote": "대표",
    "recent_news": "최근 뉴스",
}


class DraftCharLimitError(ValueError):
    """초안이 채널 글자수 상한(inmail_precheck.py:48-52)을 초과 — fail-fast."""


class DraftDensityError(ValueError):
    """초안이 밀도 하한(1,800자 — linkedin-rps SKILL.md:18,275) 미달 — 빈약 초안 거부."""

    def __init__(self, char_count: int, minimum: int = DRAFT_MIN_CHARS) -> None:
        self.char_count = char_count
        self.minimum = minimum
        super().__init__(
            f"draft_too_thin: 초안 {char_count}자 < 하한 {minimum}자 — "
            "빈약 초안 거부 (출처 .codex/skills/linkedin-rps-jd-set-builder/"
            "SKILL.md:18,266-279 §6.3)"
        )


class DraftPrecheckError(ValueError):
    """재사용한 precheck_inmail(inmail_precheck.py:247-314) STOP — 초안 제공 금지."""


def _required_text(value: object, field: str) -> str:
    """빈 값·None 을 fail-closed 로 거부하고 strip 된 문자열만 통과시킨다."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 비어 있음/None — 초안 생성 불가(fail-closed)")
    return value.strip()


def _verified_briefing(briefing_elements: dict | None) -> dict[str, str]:
    """§1.5 8요소 검증 — 미지 키는 명시적 거부(E8), None 값은 거부(문자열
    "None" 변환 금지). 알려진 키만 SOT 순서로 보존한다."""
    src = briefing_elements or {}
    unknown = sorted(set(src) - set(BRIEFING_ELEMENT_KEYS))
    if unknown:
        raise ValueError(
            f"E8 briefing_unknown_keys: {unknown} — §1.5 8요소"
            f"{list(BRIEFING_ELEMENT_KEYS)} 밖의 키는 조용히 버리지 않고 거부"
            "(fail-closed, inmail_precheck.py:34-44)"
        )
    out: dict[str, str] = {}
    for key in BRIEFING_ELEMENT_KEYS:
        if key not in src:
            continue
        value = src[key]
        if value is None:
            raise ValueError(
                f"briefing_value_none: '{key}' 값이 None — 문자열 'None' 변환 금지"
                "(fail-closed)"
            )
        out[key] = str(value)
    return out


def build_candidate_draft(
    *,
    candidate_name: str,
    candidate_company: str,
    candidate_headline: str,
    company_name: str,
    position_title: str,
    briefing_elements: dict | None,
    jd_summary: str,
    channel: str = "linkedin_rps",
) -> dict:
    """후보 전달용 메시지 "초안" dict 를 만든다. 반환만 하고 아무 데도 내보내지 않는다.

    fail-fast (전부 fail-closed):
      - 미지 채널 → ValueError (inmail_precheck 과 동일 원칙)
      - 필수 문자열(이름·현재회사·헤드라인·회사명·직무명·JD 요약) 빈 값/None → ValueError
      - 브리핑 미지 키 → ValueError(E8) / 브리핑 값 None → ValueError
      - 상한 초과 → DraftCharLimitError (linkedin_rps 1,899 —
        출처 tools/multi_position_sourcing/inmail_precheck.py:48-52)
      - 1,800자 미달 → DraftDensityError (§6.3)
      - 재사용 precheck_inmail STOP → DraftPrecheckError (CTA·이름일치·금지워딩 등)
    """
    limit = CHANNEL_CHAR_LIMITS.get(channel)
    if limit is None:
        raise ValueError(
            f"channel_unknown: '{channel}' — 허용 채널 {sorted(CHANNEL_CHAR_LIMITS)}"
        )
    candidate_name = _required_text(candidate_name, "candidate_name")
    candidate_company = _required_text(candidate_company, "candidate_company")
    candidate_headline = _required_text(candidate_headline, "candidate_headline")
    company_name = _required_text(company_name, "company_name")
    position_title = _required_text(position_title, "position_title")
    jd_summary = _required_text(jd_summary, "jd_summary")

    briefing = _verified_briefing(briefing_elements)
    element_count = count_briefing_elements(briefing)

    briefing_lines = [
        f"- {_BRIEFING_LABELS[key]}: {value}"
        for key, value in briefing.items()
        if value.strip()  # 빈 값 bullet 은 싣지 않는다(개수 집계에서도 이미 제외)
    ]
    body = "\n".join(
        [
            # R2 개인화(jdbuilder SKILL.md:16) — 이름+현재회사+헤드라인을 인사말에 반영
            f"안녕하세요 {candidate_name}님, 밸류커넥트 강상모입니다.",
            "",
            f"{candidate_company}에서 '{candidate_headline}'(으)로 쌓아오신 이력을 "
            f"인상 깊게 보았고, {company_name}의 {position_title} 포지션을 "
            "제안드리고자 연락드립니다.",
            "",
            f"[{company_name} 브리핑]",
            *briefing_lines,
            "",
            f"[{position_title} 핵심]",
            jd_summary,
            "",
            _VERIFIED_PULL_PARAGRAPH,
            "",
            "감사합니다.",
            "강상모 드림",
            "",
            "---",
            REQUIRED_PS_CTA,  # R21 필수 인입 문구 — 빠지면 아래 precheck STOP
        ]
    )

    n = char_count(body)
    if n > limit:
        raise DraftCharLimitError(
            f"char_limit: 초안 {n}자 > {limit}자 ({channel}) — "
            "fail-fast, 상한 출처 tools/multi_position_sourcing/inmail_precheck.py:48-52"
        )
    if n < DRAFT_MIN_CHARS:
        raise DraftDensityError(n)

    # 결함5 — 검문 로직 복제 금지: inmail_precheck.py:247-314 를 그대로 돌린다.
    # (CTA/VERIFIED-PULL 마커·인사말 이름 일치·금지 워딩·자모/오타까지 한 번에)
    result = precheck_inmail(
        body,
        profile_name=candidate_name,
        channel=channel,
        briefing_element_count=element_count,
    )
    if result.stops:
        raise DraftPrecheckError(
            "precheck_stop: " + " | ".join(result.stops)
            + " — 출처 tools/multi_position_sourcing/inmail_precheck.py:247-314"
        )

    return {
        "channel": channel,
        "body": body,
        "char_count": n,
        "char_limit": limit,
        "briefing_element_count": element_count,
        "warnings": list(result.warnings),  # briefing<6 보고 등 — precheck 재사용
        "is_draft_only": True,  # AC-9: 초안만 — 발송 경로 없음
    }
