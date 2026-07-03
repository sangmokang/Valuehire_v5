"""아웃리치 JD 컴포저 — 채널별 본문 길이 캡 가드 (PC-G1).

후보 맞춤 JD(InMail/이직제안 본문)를 "보낼 수 있는 상태"로 조립하는 모듈의
첫 조각. 여기서는 **길이 검증만** 한다 — 컴포저 산출물(PC-G2)이 채널 한도를
넘지 않음을 발송 전에 기계로 못박는다.

SOT 가드:
- SOT3: 길이 검증만. Send/컴포저 insert 같은 자동 부작용 없음. 초과 시 STOP(raise).
- SOT5: 채널 한도(linkedin_rps 1899 등)·글자수 계산을 재정의하지 않고
  inmail_precheck 의 CHANNEL_CHAR_LIMITS·char_count 를 그대로 재사용한다.
"""
from __future__ import annotations

from .inmail_precheck import CHANNEL_CHAR_LIMITS, char_count

__all__ = ["OutreachJdCapError", "assert_outreach_jd_within_cap"]


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
