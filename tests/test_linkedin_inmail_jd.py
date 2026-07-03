"""PC-G2 — LinkedIn InMail 본문 컴포저 build_linkedin_inmail_jd 인수 기준.

oracle 은 구현이 아니라 **이미 배송된 독립 검사기**(precheck_inmail·PC-G1 캡가드)다 —
생성기와 테스트가 서로 베끼는 가짜 GREEN 을 구조적으로 차단한다.
스펙: docs/engineering/pc-g2-inmail-composer-goal-2026-07-04.md (이슈 #59)
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tools.multi_position_sourcing.inmail_precheck import (
    BRIEFING_MIN_ELEMENTS,
    count_briefing_elements,
    extract_greeting_name,
    greeting_matches_profile,
    precheck_inmail,
)
from tools.multi_position_sourcing.jd_outreach import (
    assert_outreach_jd_within_cap,
    build_linkedin_inmail_jd,
)

# ── 골든 픽스처 (ax-sales-lead — 테스트 안에만, 실이름·라이브 하드코딩 금지) ──


def golden_kwargs() -> dict:
    return {
        "candidate_name": "Jihoon Park",
        "personalized_opener": (
            "B2B/B2G 영업 커리어가 인상 깊어, 한 분만 보고 연락드립니다."
        ),
        "company_name": "뤼튼테크놀로지스",
        "position_title": "AX Sales Team Lead",
        "company_briefing": {
            "one_line": "2021년 설립된 국내 대표 생성형 AI 기업",
            "ceo_quote": '대표 이세영 — "AI는 공기처럼 모두가 누리는 존재여야 한다"',
            "funding_stage": "시리즈B 1,080억원, 누적 1,300억원+",
            "revenue": "2025년 연매출 300억원 상회",
            "headcount": "약 90명",
            "history": "2021 설립·생활형 AI 전환",
            "recent_news": "기업용 AI 전환(AX) 사업 확대",
        },
        "jd_responsibilities": [
            "기업·정부 대형 딜 직접 발굴·클로징",
            "세일즈 플레이북 수립·팀 이식",
            "신규 세그먼트·GTM 전략",
            "0→1 세일즈 조직 구축",
        ],
        "jd_qualifications": [
            "B2B/G 대형 딜 직접 성사 실적",
            "협상·계약 체결·팀 성장 경험",
            "AI 도메인 미경험 무방",
        ],
        "why_consider": ["플레잉 리드 권한", "0→1 조직 구축", "대형 딜 최전선"],
        "location": "서울",
        "language": "ko",
        "channel": "linkedin_rps",
    }


@pytest.fixture()
def golden_body() -> tuple[str, dict]:
    kwargs = golden_kwargs()
    return build_linkedin_inmail_jd(**kwargs), kwargs


# ── AC-1 골든 통과: 독립 검사기 precheck_inmail 이 ok=True ──


def test_ac1_golden_passes_precheck(golden_body):
    body, kwargs = golden_body
    result = precheck_inmail(
        body,
        profile_name=kwargs["candidate_name"],
        channel="linkedin_rps",
        briefing_element_count=count_briefing_elements(kwargs["company_briefing"]),
    )
    assert result.ok is True, f"precheck STOP: {result.stops}"
    assert result.stops == ()


# ── AC-2 브리핑 요소: 최소 6 + 채운 값이 body 에 실제 포함 ──


def test_ac2_briefing_elements_in_body(golden_body):
    body, kwargs = golden_body
    briefing = kwargs["company_briefing"]
    assert count_briefing_elements(briefing) >= BRIEFING_MIN_ELEMENTS
    for key, value in briefing.items():
        assert value in body, f"브리핑 요소 '{key}' 값이 body 에 없음"


def test_ac2_unverified_marker_zero_width_bypass_blocked():
    """codex V1 결함 1: zero-width 문자가 붙은 ※미확인 이 본문에 새어들면 안 된다."""
    kwargs = golden_kwargs()
    kwargs["company_briefing"] = dict(kwargs["company_briefing"])
    kwargs["company_briefing"]["parent_group"] = "​※미확인"
    kwargs["company_briefing"]["recent_news"] = "﻿※미확인 (출처 없음)"
    body = build_linkedin_inmail_jd(**kwargs)
    assert "※미확인" not in body
    assert "​" not in body and "﻿" not in body


def test_ac2_unverified_marker_variants_blocked():
    """codex V1 round2 결함 1: 마커 변형(공백·NBSP·이형선택자·전각치환 삽입)도 생략돼야 한다."""
    variants = [
        "※ 미확인",            # 마커 안 공백
        "※ 미확인",       # NBSP
        "※미️확인",       # variation selector 삽입
        "＊미확인",             # 전각 별표 치환
        "시리즈B 규모 ※ 미 확 인",  # 값 중간 + 낱자 분리
    ]
    for variant in variants:
        kwargs = golden_kwargs()
        kwargs["company_briefing"] = dict(kwargs["company_briefing"])
        kwargs["company_briefing"]["parent_group"] = variant
        body = build_linkedin_inmail_jd(**kwargs)
        assert "미확인" not in body.replace(" ", ""), f"변형 마커 유출: {variant!r}"
        assert variant not in body


def test_briefing_non_string_values_rejected():
    """codex V1 round2 결함 2: 리스트/None 혼입 브리핑 값이 repr 로 새어들면 안 된다."""
    for bad in (["​※미확인"], [None], 123, {"nested": "dict"}):
        kwargs = golden_kwargs()
        kwargs["company_briefing"] = dict(kwargs["company_briefing"])
        kwargs["company_briefing"]["parent_group"] = bad
        with pytest.raises(ValueError, match="parent_group"):
            build_linkedin_inmail_jd(**kwargs)


def test_unverified_marker_in_other_paths_rejected():
    """codex V1 round3 결함 1: 브리핑 밖 경로(오프너·회사명·타이틀·JD·근무지)로
    미확인 마커가 유출되면 안 된다 — 생략이 아니라 ValueError(의미 왜곡 방지)."""
    marker = "※‍미확인"  # ZWJ 삽입 변형
    for field, value in (
        ("personalized_opener", f"커리어가 인상 깊습니다. {marker}"),
        ("company_name", f"뤼튼 {marker}"),
        ("position_title", f"Sales Lead {marker}"),
        ("location", f"서울 {marker}"),
    ):
        kwargs = golden_kwargs()
        kwargs[field] = value
        with pytest.raises(ValueError, match=field):
            build_linkedin_inmail_jd(**kwargs)
    kwargs = golden_kwargs()
    kwargs["jd_responsibilities"] = ["딜 발굴", f"플레이북 {marker}"]
    with pytest.raises(ValueError, match="jd_responsibilities"):
        build_linkedin_inmail_jd(**kwargs)


def test_non_string_scalar_inputs_rejected():
    """codex V1 round3 결함 2: 타이틀 등 문자열 인자에 dict/list/int/None 이 들어오면
    repr 유출 없이 ValueError 로 거부."""
    for field in ("candidate_name", "personalized_opener", "company_name",
                  "position_title", "location"):
        for bad in ({"a": 1}, ["x"], 123):
            kwargs = golden_kwargs()
            kwargs[field] = bad
            with pytest.raises(ValueError, match=field):
                build_linkedin_inmail_jd(**kwargs)
    for field in ("candidate_name", "company_name", "position_title"):
        kwargs = golden_kwargs()
        kwargs[field] = None
        with pytest.raises(ValueError, match=field):
            build_linkedin_inmail_jd(**kwargs)


def test_non_string_jd_list_items_rejected():
    kwargs = golden_kwargs()
    kwargs["jd_qualifications"] = ["실적", {"bullet": "dict"}]
    with pytest.raises(ValueError, match="jd_qualifications"):
        build_linkedin_inmail_jd(**kwargs)


def test_none_jd_list_item_rejected():
    """codex V1 round4 결함 1: 리스트 안 None 이 조용히 빠지면 안 된다 — 명시 거부."""
    for field in ("jd_responsibilities", "jd_qualifications", "why_consider"):
        kwargs = golden_kwargs()
        kwargs[field] = ["정상 항목", None]
        with pytest.raises(ValueError, match=field):
            build_linkedin_inmail_jd(**kwargs)


def test_language_channel_bad_type_valueerror():
    """codex V1 round4 결함 2: language/channel 오타입은 TypeError 아닌 ValueError."""
    for field in ("language", "channel"):
        for bad in ({"a": 1}, ["x"], 123, None):
            kwargs = golden_kwargs()
            kwargs[field] = bad
            with pytest.raises(ValueError, match=field):
                build_linkedin_inmail_jd(**kwargs)


def test_company_briefing_container_type_enforced():
    """codex V1 round4 followup: 브리핑 컨테이너가 dict 아니면 ValueError."""
    for bad in (["one_line"], "문자열", 123):
        kwargs = golden_kwargs()
        kwargs["company_briefing"] = bad
        with pytest.raises(ValueError, match="company_briefing"):
            build_linkedin_inmail_jd(**kwargs)


def test_empty_jd_lists_rejected():
    """codex V1 결함 2: 불릿 없는 헤더만 있는 문구가 조용히 만들어지면 안 된다(fail-closed)."""
    for field in ("jd_responsibilities", "jd_qualifications", "why_consider"):
        kwargs = golden_kwargs()
        kwargs[field] = []
        with pytest.raises(ValueError, match=field):
            build_linkedin_inmail_jd(**kwargs)
        kwargs[field] = ["  ", ""]  # 공백뿐인 리스트도 빈 것으로 취급
        with pytest.raises(ValueError, match=field):
            build_linkedin_inmail_jd(**kwargs)


def test_ac2_unverified_briefing_value_omitted():
    kwargs = golden_kwargs()
    kwargs["company_briefing"] = dict(kwargs["company_briefing"])
    kwargs["company_briefing"]["parent_group"] = "※미확인"
    body = build_linkedin_inmail_jd(**kwargs)
    assert "※미확인" not in body, "미확인 요소는 본문에 넣지 않는다(출처 있는 사실만)"


# ── AC-3 VERIFIED-PULL + P.S. CTA: 함수가 고정 삽입(호출자 입력 아님) ──


def test_ac3_verified_pull_and_ps_cta(golden_body):
    body, _ = golden_body
    assert "이력서 피드백" in body, "VERIFIED-PULL 문단 부재"
    assert "P.S." in body
    assert "https://valuehire.cc/resume" in body, "R21 인입 CTA 부재"


def test_ac3_english_verified_pull():
    kwargs = golden_kwargs()
    kwargs["language"] = "en"
    body = build_linkedin_inmail_jd(**kwargs)
    assert "resume feedback" in body.lower(), "영어 본문 VERIFIED-PULL 부재"
    assert "https://valuehire.cc/resume" in body


# ── AC-4 부수효과 0: 문자열만 반환, 모듈에 IO/네트워크/브라우저 import 없음 ──

_BANNED_IMPORT_ROOTS = {
    "requests", "urllib", "http", "socket", "subprocess", "os", "shutil",
    "pathlib", "playwright", "websocket", "selenium", "asyncio", "aiohttp",
}


def test_ac4_pure_string_no_side_effect_imports(golden_body):
    body, _ = golden_body
    assert isinstance(body, str) and body.strip()

    import tools.multi_position_sourcing.jd_outreach as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    banned = roots & _BANNED_IMPORT_ROOTS
    assert not banned, f"컴포저 모듈에 부수효과 import 금지(SOT3): {banned}"


def test_ac4_open_not_called_in_module():
    import tools.multi_position_sourcing.jd_outreach as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open", "컴포저에서 파일 IO 금지(SOT3)"


# ── AC-5 이름 일치: 인사말 이름 == candidate_name (손 재입력 금지) ──


def test_ac5_greeting_name_exact(golden_body):
    body, kwargs = golden_body
    name = kwargs["candidate_name"]
    assert f"안녕하세요 {name}님" in body, "인사말에 candidate_name 그대로 없음"
    assert greeting_matches_profile(body, name)
    assert extract_greeting_name(body) is not None


def test_ac5_other_name_does_not_match(golden_body):
    body, _ = golden_body
    assert not greeting_matches_profile(body, "Meseret Abayebas Tadese")


# ── AC-6 금지워딩 비주입: 깨끗한 입력에 함수가 스스로 추가하지 않음 ──


def test_ac6_no_forbidden_wording_injected(golden_body):
    body, _ = golden_body
    assert "{" not in body and "}" not in body, "raw 중괄호 금지(R25)"
    assert "<!--" not in body
    assert "통화" not in body and "전화" not in body
    # "딱 맞지 않으셔도"(R21 부정문 CTA)만 허용 — 그 외 "딱 맞" 과장 금지
    import re

    assert not re.search(r"딱\s*맞(?!지\s*않)", body)


# ── 길이: PC-G1 캡가드 재사용 (STOP 강제 단언은 PC-G2b 비범위) ──


def test_golden_within_channel_cap(golden_body):
    body, _ = golden_body
    assert assert_outreach_jd_within_cap(body, channel="linkedin_rps") == body


def test_composer_routes_through_cap_guard(monkeypatch):
    """컴포저가 PC-G1 캡가드를 실제로 거치는지(배선). STOP 강제 단언은 PC-G2b."""
    import tools.multi_position_sourcing.jd_outreach as mod

    calls: list[str] = []
    orig = mod.assert_outreach_jd_within_cap

    def spy(body: str, channel: str = "linkedin_rps") -> str:
        calls.append(channel)
        return orig(body, channel=channel)

    monkeypatch.setattr(mod, "assert_outreach_jd_within_cap", spy)
    mod.build_linkedin_inmail_jd(**golden_kwargs())
    assert calls == ["linkedin_rps"], "컴포저가 캡가드를 호출하지 않음(배선 끊김)"


# ── 구조: 제목·근무지·서명 (골든샘플 v2) ──


def test_structure_subject_location_signature(golden_body):
    body, kwargs = golden_body
    first_line = body.splitlines()[0]
    assert kwargs["company_name"] in first_line
    assert kwargs["position_title"] in first_line
    assert "강상모 드림" in body
    assert "밸류커넥트" in body
    assert "서울" in body  # location 제공 시 [근무지] 포함


def test_structure_location_omitted_when_none():
    kwargs = golden_kwargs()
    kwargs["location"] = None
    body = build_linkedin_inmail_jd(**kwargs)
    assert "[근무지]" not in body
