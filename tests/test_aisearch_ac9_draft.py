"""AC-9 — /jdbuilder 연동 후보 전달 메시지 초안 생성기 (발송 절대 아님).

V1 결함 5종 RED 재현 + 기존 계약 유지 (테스트 약화 금지):
  결함1 필수 인입 문구 미적용 — R1/R21 CTA(https://valuehire.cc/resume)와
        VERIFIED-PULL(무료 이력서 피드백) 문단이 본문에 강제되어야 한다.
        출처: .codex/skills/jdbuilder/SKILL.md:15 (R1),
              .codex/skills/linkedin-rps-jd-set-builder/SKILL.md:34 (R21),
              tools/multi_position_sourcing/inmail_precheck.py:79-83,290-294.
  결함2 개인화 미적용 — 이름·현재회사·헤드라인을 인사말에 반영(범용 인사말 금지),
        누락 시 fail-fast. 출처: .codex/skills/jdbuilder/SKILL.md:16 (R2),
        .codex/skills/linkedin-rps-jd-set-builder/SKILL.md:130-141 (§3.3 meta 6종).
  결함3 본문 밀도 — 1,800자 이상 목표(상한 1,899 이내) 검문. 111자 빈약 초안 거부.
        출처: .codex/skills/linkedin-rps-jd-set-builder/SKILL.md:18 (R2
        "풍성한 본문은 1,800~1,899자를 목표"), :69, :266-279 (§6.3 len<1800 가드).
  결함4 빈 직무명·빈 JD 요약 허용 → 거부. 브리핑 값 None → 거부(문자열 "None"
        변환 금지). 미지 브리핑 키 조용히 버림 → 명시적 거부(E8).
  결함5 inmail_precheck 검문 로직 import 재사용(복제 금지) —
        precheck_inmail(tools/multi_position_sourcing/inmail_precheck.py:247-314)을
        초안에 그대로 돌려 stops 0 이어야 한다.
  결함6 브리핑 요소 개수 = 실측 8요소 고정.
        출처: tools/multi_position_sourcing/inmail_precheck.py:34-44 (8 keys),
        .codex/skills/linkedin-rps-jd-set-builder/SKILL.md:33 (R20 — 8요소, §1.5).
"""
from __future__ import annotations

import inspect
import re

import pytest

from tools.multi_position_sourcing import inmail_precheck as precheck_mod
from tools.multi_position_sourcing.inmail_precheck import (
    BRIEFING_ELEMENT_KEYS,
    BRIEFING_MIN_ELEMENTS,
    CHANNEL_CHAR_LIMITS,
    char_count,
    precheck_inmail,
)

from apps.aisearch.core import draft_builder
from apps.aisearch.core.draft_builder import (
    DraftCharLimitError,
    DraftDensityError,
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

JD_SUMMARY = (
    "시제품 개발 프로젝트 총괄, 글로벌 고객 커뮤니케이션, "
    "설계-생산-품질 부서 간 일정 조율과 리스크 관리를 담당합니다."
)

BASE_KWARGS = dict(
    candidate_name="김민수",
    candidate_company="현대로템",
    candidate_headline="기구설계 파트리더",
    company_name="한국프리시전웍스",
    position_title="Tech PM",
    briefing_elements=FULL_BRIEFING,
    jd_summary=JD_SUMMARY,
    channel="linkedin_rps",
)


def _draft(**overrides):
    """유효 입력 헬퍼 — 밀도(1,800자 미달)만 결정적으로 보정해 재시도한다.

    입력 검증 오류(빈 값·미지 키·미지 채널·상한 초과)는 그대로 전파한다 —
    밀도 게이트 자체는 TestBodyDensity 에서 직접(무보정) 검증한다.
    """
    kwargs = dict(BASE_KWARGS)
    kwargs.update(overrides)
    try:
        return build_candidate_draft(**kwargs)
    except DraftDensityError as e:
        deficit = e.minimum - e.char_count
        kwargs["jd_summary"] = kwargs["jd_summary"] + "다" * deficit
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


class TestRequiredCta:
    """결함1 — R1/R21 필수 인입 문구 + VERIFIED-PULL 문단 강제."""

    def test_body_carries_r21_cta_verbatim(self):
        body = _draft()["body"]
        # R21 원문(linkedin-rps-jd-set-builder SKILL.md:34) 그대로
        assert "https://valuehire.cc/resume" in body
        assert "P.S. 지금 이 포지션이 딱 맞지 않으셔도 괜찮습니다." in body
        assert "무료 커리어 검증 신청" in body

    def test_body_carries_verified_pull_marker(self):
        # inmail_precheck.py:79-80 _VERIFIED_PULL_MARKERS 인정 문구
        assert "이력서 피드백" in _draft()["body"]

    def test_draft_passes_reused_precheck_gate(self):
        """결함5 — inmail_precheck.precheck_inmail 재사용으로 stops 0 증명."""
        draft = _draft()
        result = precheck_inmail(
            draft["body"],
            profile_name=BASE_KWARGS["candidate_name"],
            channel=draft["channel"],
            briefing_element_count=draft["briefing_element_count"],
        )
        assert result.stops == ()
        assert result.ok is True

    def test_builder_reuses_precheck_function_not_a_copy(self):
        assert draft_builder.precheck_inmail is precheck_mod.precheck_inmail


class TestPersonalization:
    """결함2 — jdbuilder R2: 이름·현재회사·헤드라인 인사말 반영, 누락 시 fail-fast."""

    def test_current_company_and_headline_in_body(self):
        body = _draft()["body"]
        assert "현대로템" in body
        assert "기구설계 파트리더" in body

    @pytest.mark.parametrize("field", ["candidate_company", "candidate_headline"])
    @pytest.mark.parametrize("bad", ["", "   ", None])
    def test_missing_personalization_fails_fast(self, field, bad):
        with pytest.raises(ValueError):
            build_candidate_draft(**{**BASE_KWARGS, field: bad})


class TestBodyDensity:
    """결함3 — §6.3: 1,800자 미만 빈약 초안 거부, 상한(1,899) 이내."""

    def test_thin_111_char_style_draft_rejected(self):
        # 밀도 보정 없는 직접 호출 — 짧은 JD 요약이면 반드시 거부
        with pytest.raises(DraftDensityError):
            build_candidate_draft(**{**BASE_KWARGS, "jd_summary": "PM 포지션입니다."})

    def test_density_error_reports_counts(self):
        with pytest.raises(DraftDensityError) as ei:
            build_candidate_draft(**{**BASE_KWARGS, "jd_summary": "PM 포지션입니다."})
        assert ei.value.minimum == 1800
        assert 0 < ei.value.char_count < 1800

    def test_valid_draft_lands_in_target_window(self):
        draft = _draft()
        assert 1800 <= draft["char_count"] <= 1899


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


class TestFailClosedInputs:
    """결함4 — 빈 직무명/빈 JD 요약/브리핑 None 값/미지 브리핑 키 전부 거부."""

    @pytest.mark.parametrize(
        "field",
        ["candidate_name", "company_name", "position_title", "jd_summary"],
    )
    @pytest.mark.parametrize("bad", ["", "   ", None])
    def test_empty_required_string_rejected(self, field, bad):
        with pytest.raises(ValueError):
            build_candidate_draft(**{**BASE_KWARGS, field: bad})

    def test_briefing_value_none_rejected_never_stringified(self):
        elems = dict(FULL_BRIEFING, revenue=None)
        with pytest.raises(ValueError) as ei:
            build_candidate_draft(**{**BASE_KWARGS, "briefing_elements": elems})
        assert "revenue" in str(ei.value)
        # 문자열 "None" 변환으로 몰래 통과하지 않았음을 이름으로 확인
        assert "None" not in repr(_draft()["body"])

    def test_unknown_briefing_key_rejected_explicitly_e8(self):
        elems = dict(FULL_BRIEFING, revenue_2027="추정 900억")
        with pytest.raises(ValueError) as ei:
            build_candidate_draft(**{**BASE_KWARGS, "briefing_elements": elems})
        msg = str(ei.value)
        assert "E8" in msg
        assert "revenue_2027" in msg


class TestBriefingDensity:
    def test_sot_fixes_exactly_8_elements(self):
        """결함6 — 참조 SOT 실측 8요소 고정 (inmail_precheck.py:34-44, R20)."""
        assert len(BRIEFING_ELEMENT_KEYS) == 8
        assert draft_builder.BRIEFING_ELEMENT_KEYS is BRIEFING_ELEMENT_KEYS

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
