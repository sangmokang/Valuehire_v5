"""PC-G3(사람인) — 이직제안 2칸 컴포저 build_saramin_offer_body 인수 기준.

사장님 확정 SSOT(2026-07-05): 4채널 공통 순서 ①개인화 인사 → ②[회사소개] 불릿 →
③JD 원문 → ④CTA → ⑤서명. 사람인은 칸이 2개뿐:
  - offer_comment ← ①+②+짧은 포지션 셀링+④+⑤ (2,000자 캡)
  - charge_work   ← ③만 ([헤더]+불릿, 2,000자 캡)

oracle 은 구현이 아니라 **이미 배송된 독립 검사기**(precheck_inmail·PC-G1 캡가드) —
생성기와 테스트가 서로 베끼는 가짜 GREEN 을 구조적으로 차단한다(PC-G2 패턴 그대로).
스펙: docs/engineering/pc-g3-multichannel-outreach-prompt-2026-07-05.md
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tools.multi_position_sourcing.inmail_precheck import (
    BRIEFING_MIN_ELEMENTS,
    CHANNEL_CHAR_LIMITS,
    char_count,
    count_briefing_elements,
    extract_greeting_name,
    greeting_matches_profile,
    precheck_inmail,
)
from tools.multi_position_sourcing.jd_outreach import (
    OutreachJdCapError,
    assert_outreach_jd_within_cap,
    build_saramin_offer_body,
)

# ── 골든 픽스처 (사장님 확정 리서치 예시 — 테크핀레이팅스, 한 줄 불릿 압축) ──


def golden_kwargs() -> dict:
    return {
        "candidate_name": "김민수",
        "personalized_opener": (
            "기업금융 데이터 분석 커리어가 인상 깊어, 한 분만 보고 연락드립니다."
        ),
        "company_name": "테크핀레이팅스",
        "position_title": "기업 CB 데이터 분석가",
        "company_briefing": {
            "one_line": (
                "신한은행·더존비즈온·SGI서울보증 3사 합작 핀테크 — "
                "국내 1호 기업금융 특화 CB 플랫폼 사업자"
            ),
            "history": "2021년 설립, 기업 CB 본허가 국내 1호",
            "funding_stage": "3사 합작 법인(신한은행·더존비즈온·SGI서울보증)",
            "revenue": "2025년 매출 성장 지속(공시 기준)",
            "headcount": "약 50명(원티드 기준)",
            "parent_group": "신한금융그룹·더존비즈온 계열",
            "recent_news": "기업 신용평가 데이터 사업 확장",
        },
        "jd_responsibilities": [
            "기업 CB 평가모형 데이터 분석",
            "대안신용평가 모형 개발·검증",
            "금융 데이터 파이프라인 설계",
        ],
        "jd_qualifications": [
            "데이터 분석 3년 이상",
            "SQL·Python 실무 경험",
        ],
        "jd_preferences": [
            "신용평가·여신 도메인 경험",
            "금융권 프로젝트 경험",
        ],
        "jd_conditions": [
            "서울 중구, 정규직",
        ],
        "hiring_process": [
            "서류 → 1차 실무 면접 → 2차 임원 면접",
        ],
        "language": "ko",
    }


@pytest.fixture()
def golden_result() -> tuple[dict, dict]:
    kwargs = golden_kwargs()
    return build_saramin_offer_body(**kwargs), kwargs


# ── AC-0 반환 계약: dict[str, str] 두 칸 정확히 ──


def test_ac0_return_contract(golden_result):
    result, _ = golden_result
    assert isinstance(result, dict)
    assert set(result) == {"offer_comment", "charge_work"}
    assert all(isinstance(v, str) and v.strip() for v in result.values())


# ── AC-1 offer_comment: 독립 검사기 precheck_inmail 이 ok=True (saramin 채널) ──


def test_ac1_offer_comment_passes_precheck(golden_result):
    result, kwargs = golden_result
    check = precheck_inmail(
        result["offer_comment"],
        profile_name=kwargs["candidate_name"],
        channel="saramin",
        briefing_element_count=count_briefing_elements(kwargs["company_briefing"]),
    )
    assert check.ok is True, f"precheck STOP: {check.stops}"
    assert check.stops == ()


def test_ac1_offer_comment_structure(golden_result):
    """① 인사+오프너, ② 브리핑, 짧은 셀링(회사명·타이틀 포함), ④ CTA, ⑤ 서명."""
    result, kwargs = golden_result
    oc = result["offer_comment"]
    assert f"안녕하세요 {kwargs['candidate_name']}님" in oc
    assert "밸류커넥트" in oc  # _INTRO 재사용
    assert kwargs["personalized_opener"] in oc
    assert kwargs["company_name"] in oc
    assert kwargs["position_title"] in oc  # 포지션 셀링 줄
    assert "이력서 피드백" in oc  # _VERIFIED_PULL
    assert "강상모 드림" in oc  # _CLOSING
    assert "P.S." in oc and "https://valuehire.cc/resume" in oc  # _PS_CTA


def test_ac1_offer_comment_briefing_values_present(golden_result):
    result, kwargs = golden_result
    briefing = kwargs["company_briefing"]
    assert count_briefing_elements(briefing) >= BRIEFING_MIN_ELEMENTS
    for key, value in briefing.items():
        assert value in result["offer_comment"], f"브리핑 요소 '{key}' 값이 offer_comment 에 없음"


def test_ac1_offer_comment_no_jd_sections(golden_result):
    """③(JD 원문)은 charge_work 전용 — offer_comment 에 섞이면 칸 매핑 위반."""
    result, _ = golden_result
    oc = result["offer_comment"]
    for header in ("[주요 업무]", "[자격 요건]", "[우대 사항]", "[근무 조건]", "[전형 절차]"):
        assert header not in oc, f"offer_comment 에 JD 섹션 {header} 혼입"


# ── AC-2 charge_work: ③ JD 원문만, [헤더]+불릿 ──


def test_ac2_charge_work_sections(golden_result):
    result, kwargs = golden_result
    cw = result["charge_work"]
    assert "[주요 업무]" in cw
    assert "[자격 요건]" in cw
    assert "[우대 사항]" in cw
    assert "[근무 조건]" in cw
    assert "[전형 절차]" in cw
    for item in (
        kwargs["jd_responsibilities"]
        + kwargs["jd_qualifications"]
        + kwargs["jd_preferences"]
        + kwargs["jd_conditions"]
        + kwargs["hiring_process"]
    ):
        assert item in cw, f"JD 항목 누락(누락 금지 SSOT): {item}"
    # ③만 — 인사·CTA·서명 혼입 금지
    assert "안녕하세요" not in cw
    assert "P.S." not in cw
    assert "강상모 드림" not in cw
    assert "이력서 피드백" not in cw


def test_ac2_optional_sections_omitted_when_absent():
    """우대/근무조건/전형절차 미제공 → 해당 [헤더] 자체 생략(빈 불릿 헤더 금지)."""
    kwargs = golden_kwargs()
    kwargs["jd_preferences"] = None
    kwargs["jd_conditions"] = None
    kwargs["hiring_process"] = None
    result = build_saramin_offer_body(**kwargs)
    cw = result["charge_work"]
    assert "[우대 사항]" not in cw
    assert "[근무 조건]" not in cw
    assert "[전형 절차]" not in cw
    assert "[주요 업무]" in cw and "[자격 요건]" in cw


def test_ac2_optional_sections_empty_list_rejected():
    """제공됐는데 빈 리스트/공백뿐 → 생략이 아니라 fail-closed 거부(있으면 필수와 동일 검문)."""
    for field in ("jd_preferences", "jd_conditions", "hiring_process"):
        kwargs = golden_kwargs()
        kwargs[field] = []
        with pytest.raises(ValueError, match=field):
            build_saramin_offer_body(**kwargs)
        kwargs[field] = ["  ", ""]
        with pytest.raises(ValueError, match=field):
            build_saramin_offer_body(**kwargs)


def test_ac2_required_jd_lists_rejected_when_empty():
    for field in ("jd_responsibilities", "jd_qualifications"):
        kwargs = golden_kwargs()
        kwargs[field] = []
        with pytest.raises(ValueError, match=field):
            build_saramin_offer_body(**kwargs)


# ── AC-3 채널 캡: 두 칸 다 saramin 2,000자 캡가드(PC-G1) 실배선 ──


def test_ac3_both_fields_within_saramin_cap(golden_result):
    result, _ = golden_result
    for key in ("offer_comment", "charge_work"):
        assert assert_outreach_jd_within_cap(result[key], channel="saramin") == result[key]
        assert char_count(result[key]) <= CHANNEL_CHAR_LIMITS["saramin"]


def test_ac3_composer_routes_through_cap_guard(monkeypatch):
    """컴포저가 PC-G1 캡가드를 두 칸 모두 saramin 채널로 실제 호출하는지(배선)."""
    import tools.multi_position_sourcing.jd_outreach as mod

    calls: list[str] = []
    orig = mod.assert_outreach_jd_within_cap

    def spy(body: str, channel: str = "linkedin_rps") -> str:
        calls.append(channel)
        return orig(body, channel=channel)

    monkeypatch.setattr(mod, "assert_outreach_jd_within_cap", spy)
    mod.build_saramin_offer_body(**golden_kwargs())
    assert calls == ["saramin", "saramin"], f"캡가드 배선 끊김: {calls}"


def test_ac3_over_cap_stops():
    """2,000자 초과 시 조용한 잘라내기가 아니라 STOP(raise)."""
    kwargs = golden_kwargs()
    kwargs["jd_responsibilities"] = [f"업무 항목 {i} — " + "가" * 80 for i in range(30)]
    with pytest.raises(OutreachJdCapError):
        build_saramin_offer_body(**kwargs)


# ── AC-4 방어 상속: PC-G2 와 동일 공격 벡터 회귀 ──


def test_ac4_unverified_marker_briefing_omitted():
    kwargs = golden_kwargs()
    kwargs["company_briefing"] = dict(kwargs["company_briefing"])
    kwargs["company_briefing"]["parent_group"] = "​※미확인"  # zero-width 삽입
    result = build_saramin_offer_body(**kwargs)
    assert "미확인" not in result["offer_comment"].replace(" ", "")


def test_ac4_unverified_marker_other_paths_rejected():
    marker = "※‍미확인"  # ZWJ 변형
    for field in ("personalized_opener", "company_name", "position_title"):
        kwargs = golden_kwargs()
        kwargs[field] = f"정상 텍스트 {marker}"
        with pytest.raises(ValueError, match=field):
            build_saramin_offer_body(**kwargs)
    kwargs = golden_kwargs()
    kwargs["jd_preferences"] = ["정상 항목", f"항목 {marker}"]
    with pytest.raises(ValueError, match="jd_preferences"):
        build_saramin_offer_body(**kwargs)


def test_ac4_control_char_injection_rejected():
    cases = [
        ("company_name", "테크핀\n[가짜섹션]"),
        ("position_title", "분석가\x00Lead"),
        ("candidate_name", "김\n민수"),
    ]
    for field, value in cases:
        kwargs = golden_kwargs()
        kwargs[field] = value
        with pytest.raises(ValueError, match=field):
            build_saramin_offer_body(**kwargs)
    kwargs = golden_kwargs()
    kwargs["jd_conditions"] = ["서울\r\n[가짜] 주입"]
    with pytest.raises(ValueError, match="jd_conditions"):
        build_saramin_offer_body(**kwargs)


def test_ac4_reserved_header_masquerade_rejected():
    """기존 예약헤더 + 사람인 신규 섹션 헤더([우대 사항]·[근무 조건]·[전형 절차]·[회사소개])
    위장 모두 거부 — NBSP 등 유니코드 공백 변형 포함."""
    cases = [
        ("personalized_opener", "[주요 업무] 기존 헤더 위장"),
        ("personalized_opener", "[우대 사항] 신규 헤더 위장"),
        ("personalized_opener", "[전형 절차] 신규 헤더 위장"),
        ("company_name", "[근무 조건] 위장"),
        ("company_name", "[회사소개] 위장"),
        ("personalized_opener", "[우대 사항] NBSP 변형 위장"),
    ]
    for field, value in cases:
        kwargs = golden_kwargs()
        kwargs[field] = value
        with pytest.raises(ValueError, match=field):
            build_saramin_offer_body(**kwargs)


def test_ac4_briefing_unknown_keys_rejected():
    kwargs = golden_kwargs()
    kwargs["company_briefing"] = dict(kwargs["company_briefing"])
    kwargs["company_briefing"]["marketing_hook"] = "8요소 밖 키"
    with pytest.raises(ValueError, match="8요소 밖 키"):
        build_saramin_offer_body(**kwargs)


def test_ac4_non_string_inputs_rejected():
    for field in ("candidate_name", "personalized_opener", "company_name", "position_title"):
        for bad in ({"a": 1}, ["x"], 123, None):
            kwargs = golden_kwargs()
            kwargs[field] = bad
            with pytest.raises(ValueError, match=field):
                build_saramin_offer_body(**kwargs)
    kwargs = golden_kwargs()
    kwargs["company_briefing"] = "문자열 아님 dict"
    with pytest.raises(ValueError, match="company_briefing"):
        build_saramin_offer_body(**kwargs)


def test_ac4_none_list_item_rejected():
    for field in ("jd_responsibilities", "jd_qualifications", "jd_preferences",
                  "jd_conditions", "hiring_process"):
        kwargs = golden_kwargs()
        kwargs[field] = ["정상 항목", None]
        with pytest.raises(ValueError, match=field):
            build_saramin_offer_body(**kwargs)


def test_ac4_language_validated():
    for bad in ("jp", 123, None, ["ko"]):
        kwargs = golden_kwargs()
        kwargs["language"] = bad
        with pytest.raises(ValueError, match="language"):
            build_saramin_offer_body(**kwargs)


# ── AC-5 이름 일치 + 금지워딩 비주입 ──


def test_ac5_greeting_name(golden_result):
    result, kwargs = golden_result
    oc = result["offer_comment"]
    assert greeting_matches_profile(oc, kwargs["candidate_name"])
    assert extract_greeting_name(oc) is not None
    assert not greeting_matches_profile(oc, "Meseret Abayebas Tadese")


def test_ac5_no_forbidden_wording_injected(golden_result):
    result, _ = golden_result
    for text in result.values():
        assert "{" not in text and "}" not in text
        assert "<!--" not in text
        assert "통화" not in text and "전화" not in text
        assert not re.search(r"딱\s*맞(?!지\s*않)", text)


# ── AC-6 부수효과 0: 모듈에 IO/네트워크 import·open 호출 없음 (PC-G2 패턴) ──

_BANNED_IMPORT_ROOTS = {
    "requests", "urllib", "http", "socket", "subprocess", "os", "shutil",
    "pathlib", "playwright", "websocket", "selenium", "asyncio", "aiohttp",
}


def test_ac6_pure_module_no_side_effect_imports(golden_result):
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
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "open", "컴포저에서 파일 IO 금지(SOT3)"
