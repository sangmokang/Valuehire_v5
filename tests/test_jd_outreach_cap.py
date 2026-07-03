"""PC-G1 — 아웃리치 JD 글자수 캡 가드(assert_outreach_jd_within_cap).

인수기준(백로그 PC-G1): '가'*1900 은 OutreachJdCapError 를 raise 하고
'가'*1899 는 예외 없이 반환한다. 캡 상수·글자수 계산은 inmail_precheck 의
CHANNEL_CHAR_LIMITS·char_count 를 재사용한다(SOT5 — 1899 재정의 금지).
길이 검증만 한다 — Send/insert 자동 없음(SOT3).
"""
import unicodedata

import pytest

from tools.multi_position_sourcing.jd_outreach import (
    OutreachJdCapError,
    assert_outreach_jd_within_cap,
)
from tools.multi_position_sourcing.inmail_precheck import CHANNEL_CHAR_LIMITS


# --- 인수기준(AC): LinkedIn 기본 1,899 경계 ---
def test_ac_1900_raises():
    with pytest.raises(OutreachJdCapError):
        assert_outreach_jd_within_cap("가" * 1900)


def test_ac_1899_returns_without_error():
    # 예외 없이 반환(반환값은 본문 그대로 — insert/send 부작용 없음)
    assert assert_outreach_jd_within_cap("가" * 1899) == "가" * 1899


# --- 경계: == 한도는 통과, +1 은 STOP ---
def test_exact_limit_passes():
    limit = CHANNEL_CHAR_LIMITS["linkedin_rps"]
    assert assert_outreach_jd_within_cap("가" * limit, channel="linkedin_rps") == "가" * limit


def test_one_over_limit_raises():
    limit = CHANNEL_CHAR_LIMITS["linkedin_rps"]
    with pytest.raises(OutreachJdCapError):
        assert_outreach_jd_within_cap("가" * (limit + 1), channel="linkedin_rps")


# --- 채널별 한도: 사람인·잡코리아 2,000 ---
@pytest.mark.parametrize("channel", ["saramin", "jobkorea"])
def test_saramin_jobkorea_2000_boundary(channel):
    limit = CHANNEL_CHAR_LIMITS[channel]
    assert limit == 2000
    assert assert_outreach_jd_within_cap("가" * limit, channel=channel) == "가" * limit
    with pytest.raises(OutreachJdCapError):
        assert_outreach_jd_within_cap("가" * (limit + 1), channel=channel)


# --- 미지원 채널은 fail-closed(조용히 통과 금지) ---
def test_unknown_channel_raises():
    with pytest.raises((OutreachJdCapError, KeyError, ValueError)):
        assert_outreach_jd_within_cap("가", channel="telepathy")


# --- NFC 기준 글자수: 분해형 한글이 결합 후 한도 내면 통과(raw len 아님) ---
def test_counts_by_nfc_not_raw_length():
    # 분해형 '가' = 'ㄱ'+'ㅏ'(코드포인트 2) 를 1899자 만들면 raw len=3798 이나 NFC=1899
    decomposed = unicodedata.normalize("NFD", "가") * 1899
    assert len(decomposed) > 1899  # raw 로는 한도 초과
    assert assert_outreach_jd_within_cap(decomposed) == decomposed  # NFC 기준이므로 통과


# --- OutreachJdCapError 는 Exception 하위 ---
def test_error_is_exception():
    assert issubclass(OutreachJdCapError, Exception)
