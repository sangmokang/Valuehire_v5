"""AC-9 RED — /jdbuilder 연동 후보 전달 메시지 초안 생성기 (발송 절대 아님).

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §AC-9
  - WHEN 후보가 등록되면 THE SYSTEM SHALL 회사 브리핑 요소를 포함한
    전달용 메시지 "초안"을 만든다. 발송 버튼은 절대 누르지 않는다.
  - 검증: 글자수 상한 준수 + 발송 API 호출 경로 부재.

재사용하는 레포 SOT 계약 (추측 금지 — 실측 근거):
  - 회사 브리핑 8요소 + 최소 6개:
    tools/multi_position_sourcing/inmail_precheck.py:34-44
    (BRIEFING_ELEMENT_KEYS 8종, BRIEFING_MIN_ELEMENTS=6;
     원 SOT = .claude/skills/position-register/SKILL.md §1.5,
     .claude/skills/linkedin-rps-jd-set-builder/SKILL.md R20)
  - 채널별 글자수 상한 (linkedin_rps 1,899 / saramin·jobkorea 2,000):
    tools/multi_position_sourcing/inmail_precheck.py:48-52
    (원 SOT = linkedin-rps-jd-set-builder SKILL.md R2 "1,899 hard cap")
  - NFC 글자수 기준: tools/multi_position_sourcing/inmail_precheck.py:89-91
"""
from __future__ import annotations

import inspect
import re

import pytest

from tools.multi_position_sourcing.inmail_precheck import (
    BRIEFING_ELEMENT_KEYS,
    BRIEFING_MIN_ELEMENTS,
    CHANNEL_CHAR_LIMITS,
    char_count,
)

from apps.aisearch.core import draft_builder
from apps.aisearch.core.draft_builder import (
    DraftCharLimitError,
    build_candidate_draft,
)

# position-register §1.5 예시(한국프리시전웍스) 기반 — 8요소 전부 출처 있는 값
FULL_BRIEFING = {
    "one_line": "글로벌 1,000곳+에 시제품·목업·QDM 공급하는 제품개발 파트너",
    "history": "1993년 설립",
    "funding_stage": "2022년 코스닥 상장(종목 417970)",
    "revenue": "2024년 매출 약 680억, 영업이익 전년비 +92%",
    "headcount": "약 330명",
    "parent_group": "한국타이어 그룹 계열(지분 62.92%)",
    "ceo_quote": "대표 공개 발언: \"로봇 액추에이터로 확장\" (2026 기사)",
    "recent_news": "K-휴머노이드 연합 참여, 로봇 액추에이터 신사업",
}


def _draft(**overrides):
    kwargs = dict(
        candidate_name="김민수",
        company_name="한국프리시전웍스",
        position_title="Tech PM",
        briefing_elements=FULL_BRIEFING,
        jd_summary="시제품 개발 프로젝트 총괄, 글로벌 고객 커뮤니케이션",
        channel="linkedin_rps",
    )
    kwargs.update(overrides)
    return build_candidate_draft(**kwargs)


class TestDraftShape:
    def test_returns_plain_dict_with_str_body(self):
        draft = _draft()
        assert type(draft) is dict
        assert isinstance(draft["body"], str) and draft["body"]
        assert draft["channel"] == "linkedin_rps"
        assert draft["is_draft_only"] is True

    def test_body_contains_briefing_elements_and_candidate(self):
        draft = _draft()
        body = draft["body"]
        assert "김민수" in body
        assert "한국프리시전웍스" in body
        assert "Tech PM" in body
        # 8요소 전부 본문에 실림 (SOT §1.5 밀도 기준)
        for value in FULL_BRIEFING.values():
            assert value.split("(")[0].strip()[:10] in body, value
        assert draft["briefing_element_count"] == len(BRIEFING_ELEMENT_KEYS)
        assert draft["warnings"] == []


class TestCharLimit:
    def test_reuses_sot_channel_limits(self):
        # 추측 금지 — inmail_precheck.py:48-52 의 상한 dict 를 그대로 재사용
        assert draft_builder.CHANNEL_CHAR_LIMITS is CHANNEL_CHAR_LIMITS
        assert CHANNEL_CHAR_LIMITS["linkedin_rps"] == 1899

    def test_draft_within_limit_and_counts_reported(self):
        draft = _draft()
        assert draft["char_limit"] == 1899
        assert draft["char_count"] == char_count(draft["body"])
        assert draft["char_count"] <= 1899

    def test_over_limit_fails_fast(self):
        with pytest.raises(DraftCharLimitError):
            _draft(jd_summary="핵심업무 " * 800)  # 1,899자 확실 초과

    def test_unknown_channel_fails_fast(self):
        with pytest.raises(ValueError):
            _draft(channel="fax")


class TestBriefingDensity:
    def test_below_min_elements_warns_not_silently_passes(self):
        # §1.5: 6개 미만 = STOP 이 아니라 "사장님 보고 후 진행" → warnings 로 노출
        sparse = {k: FULL_BRIEFING[k] for k in ("one_line", "history", "revenue")}
        draft = _draft(briefing_elements=sparse)
        assert draft["briefing_element_count"] == 3
        assert any("briefing" in w for w in draft["warnings"])

    def test_unverified_marker_not_counted(self):
        elems = dict(FULL_BRIEFING, ceo_quote="※미확인", recent_news="  ")
        draft = _draft(briefing_elements=elems)
        assert draft["briefing_element_count"] == 6
        assert draft["briefing_element_count"] >= BRIEFING_MIN_ELEMENTS


class TestNoSendPath:
    """발송 API 호출 경로가 아예 없음을 증명 (AC-9 '발송 버튼은 절대 누르지 않는다')."""

    def test_module_has_no_send_like_symbols(self):
        names = [n for n in dir(draft_builder)]
        assert not [n for n in names if re.search(r"(?i)send|dispatch|deliver|submit", n)]

    def test_source_has_no_send_or_network_code(self):
        src = inspect.getsource(draft_builder)
        assert not re.search(r"(?i)\bsend\b", src)
        for banned in (
            "requests", "urllib", "http.client", "httpx", "aiohttp",
            "socket", "smtplib", "websocket", "subprocess", "playwright",
        ):
            assert not re.search(rf"(?m)^\s*(?:import|from)\s+{re.escape(banned)}\b", src), banned

    def test_module_imports_are_stdlib_pure_only(self):
        # 모듈이 실제 로드한 의존성에 네트워크/브라우저 모듈이 없어야 한다
        loaded = {
            getattr(v, "__name__", "")
            for v in vars(draft_builder).values()
            if inspect.ismodule(v)
        }
        assert not loaded & {"requests", "urllib", "socket", "smtplib", "httpx", "aiohttp"}
