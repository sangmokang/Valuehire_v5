"""AC-9 — /jdbuilder 연동 후보 전달 메시지 "초안" 생성기. 발송 절대 아님.

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §AC-9
  "후보가 등록되면 회사 브리핑 요소를 포함한 전달용 메시지 초안을 만든다.
   발송 버튼은 절대 누르지 않는다."

이 모듈은 순수 문자열 조립만 한다 — 네트워크/브라우저/발송 코드 0.
발송은 언제나 사장님 수동 게이트(SOT3) 또는 SOT28 게이트 밖 영역이며,
여기서는 dict(초안)만 반환한다.

재사용한 레포 SOT 계약 (추측 금지):
  - 회사 브리핑 8요소 + 최소 6개(미만이면 보고):
    tools/multi_position_sourcing/inmail_precheck.py:34-44
    (원 SOT = .claude/skills/position-register/SKILL.md §1.5,
     .claude/skills/linkedin-rps-jd-set-builder/SKILL.md R20)
  - 채널별 글자수 상한 linkedin_rps 1,899 / saramin·jobkorea 2,000:
    tools/multi_position_sourcing/inmail_precheck.py:48-52
    (원 SOT = linkedin-rps-jd-set-builder SKILL.md R2 — LinkedIn InMail
     direct composer hard cap 1,899자)
  - NFC 코드포인트 글자수 기준: tools/multi_position_sourcing/inmail_precheck.py:89-91
"""
from __future__ import annotations

from tools.multi_position_sourcing.inmail_precheck import (
    BRIEFING_ELEMENT_KEYS,
    BRIEFING_MIN_ELEMENTS,
    CHANNEL_CHAR_LIMITS,  # SOT 상한 dict 를 그대로 재사용 (사본 금지)
    char_count,
    count_briefing_elements,
)

__all__ = [
    "BRIEFING_ELEMENT_KEYS",
    "BRIEFING_MIN_ELEMENTS",
    "CHANNEL_CHAR_LIMITS",
    "DraftCharLimitError",
    "build_candidate_draft",
]

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


def _verified_briefing(briefing_elements: dict | None) -> dict[str, str]:
    """§1.5 8요소 중 알려진 키만 취해 순서 보존. 미지 키는 무시(추측 금지)."""
    src = briefing_elements or {}
    return {k: str(src[k]) for k in BRIEFING_ELEMENT_KEYS if k in src}


def build_candidate_draft(
    *,
    candidate_name: str,
    company_name: str,
    position_title: str,
    briefing_elements: dict | None,
    jd_summary: str,
    channel: str = "linkedin_rps",
) -> dict:
    """후보 전달용 메시지 "초안" dict 를 만든다. 반환만 하고 아무 데도 내보내지 않는다.

    fail-fast:
      - 미지 채널 → ValueError (fail-closed, inmail_precheck 과 동일 원칙)
      - 상한 초과 → DraftCharLimitError (linkedin_rps 1,899 등 —
        출처: tools/multi_position_sourcing/inmail_precheck.py:48-52)
    """
    limit = CHANNEL_CHAR_LIMITS.get(channel)
    if limit is None:
        raise ValueError(
            f"channel_unknown: '{channel}' — 허용 채널 {sorted(CHANNEL_CHAR_LIMITS)}"
        )
    if not (candidate_name or "").strip():
        raise ValueError("candidate_name 비어 있음 — 초안 생성 불가(fail-closed)")
    if not (company_name or "").strip():
        raise ValueError("company_name 비어 있음 — 초안 생성 불가(fail-closed)")

    briefing = _verified_briefing(briefing_elements)
    element_count = count_briefing_elements(briefing)

    warnings: list[str] = []
    if element_count < BRIEFING_MIN_ELEMENTS:
        # §1.5: 6개 미만 = STOP 이 아니라 "사장님 보고 후 진행"
        warnings.append(
            f"briefing_below_{BRIEFING_MIN_ELEMENTS}: 확인된 브리핑 요소 "
            f"{element_count}/{len(BRIEFING_ELEMENT_KEYS)} — 사장님 보고 후 진행"
        )

    briefing_lines = [
        f"- {_BRIEFING_LABELS[key]}: {value}" for key, value in briefing.items()
    ]
    body = "\n".join(
        [
            f"안녕하세요 {candidate_name}님, 밸류커넥트입니다.",
            "",
            f"{company_name}의 {position_title} 포지션을 제안드리고자 연락드립니다.",
            "",
            f"[{company_name} 브리핑]",
            *briefing_lines,
            "",
            "[포지션 핵심]",
            jd_summary.strip(),
            "",
            "검토 의향이 있으시면 편하신 방법으로 회신 부탁드립니다. 감사합니다.",
        ]
    )

    n = char_count(body)
    if n > limit:
        raise DraftCharLimitError(
            f"char_limit: 초안 {n}자 > {limit}자 ({channel}) — "
            "fail-fast, 상한 출처 tools/multi_position_sourcing/inmail_precheck.py:48-52"
        )

    return {
        "channel": channel,
        "body": body,
        "char_count": n,
        "char_limit": limit,
        "briefing_element_count": element_count,
        "warnings": warnings,
        "is_draft_only": True,  # AC-9: 초안만 — 발송 경로 없음
    }
