"""아웃리치 JD 컴포저 — 길이 캡 가드(PC-G1) + LinkedIn InMail 본문 조립(PC-G2).

후보 맞춤 JD(InMail/이직제안 본문)를 "보낼 수 있는 상태"로 조립하는 모듈.
PC-G1 = 채널 글자수 캡 가드, PC-G2 = 골든샘플 v2 구조의 본문 문자열 조립(순수함수).

SOT 가드:
- SOT3: 문자열 조립·검증만. Send/컴포저 insert 같은 자동 부작용 없음 —
  발송·저장은 언제나 사장님 손. 초과 시 STOP(raise).
- SOT5: 채널 한도·글자수·브리핑 8요소를 재정의하지 않고 inmail_precheck 의
  CHANNEL_CHAR_LIMITS·char_count·BRIEFING_ELEMENT_KEYS 를 그대로 재사용한다.
- 문구 구조 SOT: skills/humansearch/references/inmail-golden-sample.md (v2).
"""
from __future__ import annotations

import unicodedata

from .inmail_precheck import (
    BRIEFING_ELEMENT_KEYS,
    CHANNEL_CHAR_LIMITS,
    UNVERIFIED_MARKER,
    char_count,
)

__all__ = [
    "OutreachJdCapError",
    "assert_outreach_jd_within_cap",
    "build_linkedin_inmail_jd",
]


class OutreachJdCapError(ValueError):
    """아웃리치 JD 본문이 채널 글자수 한도를 초과했을 때 raise (발송 전 STOP)."""


def assert_outreach_jd_within_cap(body: str, channel: str = "linkedin_rps") -> str:
    """본문이 채널 한도 이내면 body 를 그대로 반환, 초과면 OutreachJdCapError.

    - 글자수는 char_count(NFC 코드포인트 수) 기준 — LinkedIn 카운터와 동일.
    - 한도는 CHANNEL_CHAR_LIMITS 단일 출처. 미지원 채널은 fail-closed(raise).
    - == 한도는 통과, 한도+1 은 STOP.
    """
    if channel not in CHANNEL_CHAR_LIMITS:
        raise OutreachJdCapError(
            f"unknown_channel: '{channel}' — 지원 채널 {sorted(CHANNEL_CHAR_LIMITS)}"
        )
    limit = CHANNEL_CHAR_LIMITS[channel]
    count = char_count(body)
    if count > limit:
        raise OutreachJdCapError(
            f"outreach_jd_over_cap: {channel} 본문 {count}자 > 한도 {limit}자 — STOP"
        )
    return body


# ── PC-G2: 골든샘플 v2 고정 문단 — 함수가 삽입하므로 누락이 구조적으로 불가능 ──

_INTRO = "저는 테크 서치펌 밸류커넥트(Valueconnect)의 헤드헌터 강상모라고 합니다."

_VERIFIED_PULL: dict[str, str] = {
    "ko": (
        "밸류커넥트는 꼭 이번 기회가 아니더라도, 레주메를 보내주시면 개인정보를 지켜 "
        "개선된 버전의 이력서 피드백을 무료로 드리고 있습니다. 커리어에 도움 되시리라 생각합니다."
    ),
    "en": (
        "Even if this role is not for you, send us your resume and we will "
        "return free resume feedback with your privacy protected."
    ),
}

_CLOSING = "그럼 또 소통 나눌 수 있기를 기대합니다. 감사합니다!\n강상모 드림"

# R21 표준 인입 CTA — "딱 맞지 않으셔도"는 부정문(과장 아님, precheck 허용 패턴)
_PS_CTA = (
    "P.S. 지금 이 포지션이 딱 맞지 않으셔도 괜찮습니다. 밸류커넥트가 이력서를 직접 검증해, "
    "더 잘 맞는 기회까지 연결해 드립니다 — 무료 커리어 검증 신청: https://valuehire.cc/resume"
)


def _strip_invisible(text: str) -> str:
    """형식 문자(Cf — zero-width 류) 제거. ※미확인 마커 우회 차단(codex V1 결함 1)."""
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _bullets(field: str, items: list[str]) -> str:
    """불릿 조립. 빈/공백뿐 리스트는 fail-closed 거부(codex V1 결함 2 — 무불릿 헤더 금지)."""
    cleaned = [item.strip() for item in (items or []) if item and item.strip()]
    if not cleaned:
        raise ValueError(f"{field} 비어 있음 — 불릿 없는 헤더만 있는 문구 금지(fail-closed)")
    return "\n".join(f"· {item}" for item in cleaned)


def build_linkedin_inmail_jd(
    *,
    candidate_name: str,
    personalized_opener: str,
    company_name: str,
    position_title: str,
    company_briefing: dict,
    jd_responsibilities: list[str],
    jd_qualifications: list[str],
    why_consider: list[str],
    location: str | None = None,
    language: str = "ko",
    channel: str = "linkedin_rps",
) -> str:
    """골든샘플 v2 구조로 InMail 본문 문자열을 조립해 반환. 부수효과 0(Send/insert 없음).

    - candidate_name 은 수확 JSON 의 name 그대로 인사말에 박는다(손 재입력 금지, ①).
    - VERIFIED-PULL(⑤)·P.S. CTA(⑥)는 여기서 고정 삽입 — 호출자가 빠뜨릴 수 없다.
    - 최종 판정은 precheck_inmail(단일 검문소)에 위임하되, 채널 캡(PC-G1)은
      조립 직후 즉시 확인한다(초과분을 하류로 흘려보내지 않음).
    """
    name = (candidate_name or "").strip()
    if not name:
        raise ValueError("candidate_name 비어 있음 — 수확 JSON 의 name 을 그대로 넣을 것")
    opener = (personalized_opener or "").strip()
    if not opener:
        raise ValueError("personalized_opener 비어 있음 — 정곡 관찰 1줄 필수")
    if language not in _VERIFIED_PULL:
        raise ValueError(f"language 는 {sorted(_VERIFIED_PULL)} 중 하나: '{language}'")
    unknown = set(company_briefing or {}) - set(BRIEFING_ELEMENT_KEYS)
    if unknown:
        raise ValueError(
            f"company_briefing 에 §1.5 8요소 밖 키 금지(SOT5): {sorted(unknown)}"
        )

    briefing_lines = [company_name]
    for key in BRIEFING_ELEMENT_KEYS:  # 출처 있는 값만, ※미확인·빈값은 생략
        value = _strip_invisible(str((company_briefing or {}).get(key) or "")).strip()
        if value and UNVERIFIED_MARKER not in value:
            briefing_lines.append(f"· {value}")

    sections = [
        f"[제목] {company_name}, {position_title}",
        f"안녕하세요 {name}님,",
        f"{_INTRO}\n{opener}",
        "\n".join(briefing_lines),
        f"[주요 업무]\n{_bullets('jd_responsibilities', jd_responsibilities)}",
        f"[자격 요건]\n{_bullets('jd_qualifications', jd_qualifications)}",
        f"[왜 검토할 만한가]\n{_bullets('why_consider', why_consider)}",
        _VERIFIED_PULL[language],
        _CLOSING,
        _PS_CTA,
    ]
    if location and location.strip():
        sections.append(f"[근무지] {location.strip()}")

    body = "\n\n".join(sections)
    return assert_outreach_jd_within_cap(body, channel=channel)
