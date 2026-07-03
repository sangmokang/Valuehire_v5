"""Harness Gate 2 RED — humansearch #8 InMail 발송 전 기계 체크리스트.

Movensys 사고(2026-06-30, 수신자 Meseret Abayebas Tadese) 재발 봉인:
  ① 인사말 "Rocha연구원님" ≠ 수확 프로필 이름 → STOP
  ② "하니다" 오타 / 자모 분리 → STOP
  ③ VERIFIED-PULL(무료 이력서 피드백) 문단 누락 → STOP
+ 채널별 글자수 한도(linkedin 1,899 / 사람인·잡코리아 2,000), 금지 워딩 린트,
  회사 브리핑 요소 6개 미만 보고(warning), 언어 자동 선택, SKILL 문서 배선 가드.

goal: docs/engineering/humansearch-inmail-machine-check-goal-2026-07-03.md
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.multi_position_sourcing.inmail_precheck import (
    BRIEFING_ELEMENT_KEYS,
    CHANNEL_CHAR_LIMITS,
    body_language_for_profile,
    char_count,
    count_briefing_elements,
    extract_greeting_name,
    greeting_matches_profile,
    hangul_jamo_broken,
    precheck_inmail,
)

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "humansearch" / "SKILL.md"
GOLDEN = REPO / "skills" / "humansearch" / "references" / "inmail-golden-sample.md"

MESERET = "Meseret Abayebas Tadese"

VERIFIED_PULL_KO = (
    "밸류커넥트는 꼭 이번 기회가 아니더라도, 레주메를 보내주시면 개인정보를 지켜 "
    "개선된 버전의 이력서 피드백을 무료로 드리고 있습니다."
)
VERIFIED_PULL_EN = (
    "Even if this role is not for you, send us your resume and we will return "
    "free resume feedback with your privacy protected."
)
PS_CTA = (
    "P.S. 지금 이 포지션이 딱 맞지 않으셔도 괜찮습니다. 밸류커넥트가 이력서를 직접 검증해, "
    "더 잘 맞는 기회까지 연결해 드립니다 — 무료 커리어 검증 신청: https://valuehire.cc/resume"
)


def _ok_body_ko(name: str = "조현용") -> str:
    return "\n".join(
        [
            f"안녕하세요 {name}님,",
            "",
            "저는 테크 서치펌 밸류커넥트(Valueconnect)의 헤드헌터 강상모라고 합니다.",
            "이력을 살펴보고 먼저 제안드립니다. 최근 이직이 기존 전문영역과 결이 조금 다르다 싶었습니다.",
            "",
            "[회사 브리핑]",
            "· 1993년 설립, 2022년 코스닥 상장",
            "",
            "[주요 업무]",
            "· 모션제어 소프트웨어 개발",
            "",
            "[자격 요건]",
            "· C++ 및 로보틱스 경력",
            "",
            "[왜 검토할 만한가]",
            "· 도메인 난이도와 성장 여지",
            "",
            VERIFIED_PULL_KO,
            "",
            "감사합니다.",
            "강상모 드림",
            "",
            PS_CTA,
        ]
    )


# ── docguard: SKILL/골든샘플 문서 배선 ─────────────────────────────
def test_docguard_skill_wires_precheck() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "inmail_precheck" in text, "SKILL #8 이 기계 체크 CLI(inmail_precheck)를 배선해야 함"
    assert "1,899" in text or "1899" in text, "채널별 글자수 한도(linkedin 1,899) 명시 필요"


def test_docguard_golden_sample_upgraded() -> None:
    text = GOLDEN.read_text(encoding="utf-8")
    for marker in (
        "발송 전 기계 체크리스트",
        "inmail_precheck",
        "언어",            # 언어 자동 선택 규칙
        "1,899",           # 채널 한도
        "2,000",           # 사람인·잡코리아 한도
        "VERIFIED-PULL",
        "P.S.",            # 인입 CTA
        "왜 검토할 만한가",
        "linkedin-rps-jd-set-builder",  # 채널 경계
        "position-register",
    ):
        assert marker in text, f"골든샘플에 '{marker}' 누락"


def test_docguard_golden_sample_keeps_absolute_rules() -> None:
    """기존 절대규칙 약화 금지 — 통화 금지·과장 금지·이력 나열 금지·가독성·Send 금지."""
    text = GOLDEN.read_text(encoding="utf-8")
    for marker in ("전화통화 요청 금지", "과장 금지", "요약·나열하지 않는다", "가독성", "발송(Send) 금지"):
        assert marker in text, f"골든샘플 절대규칙 약화: '{marker}' 사라짐"


# ── name: 인사말 이름 == 프로필 이름 (Movensys 봉인) ────────────────
def test_name_movensys_regression_rocha_vs_meseret_stops() -> None:
    body = _ok_body_ko("Rocha 연구원")
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert not result.ok
    assert any("name" in s for s in result.stops)


def test_name_greeting_matches_english_profile() -> None:
    body = _ok_body_ko("Meseret")
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert not any("name" in s for s in result.stops)


def test_name_korean_with_title_suffix_matches() -> None:
    assert greeting_matches_profile("안녕하세요 조현용 책임님,", "조현용")
    assert greeting_matches_profile("안녕하세요 Meseret님,", MESERET)
    assert not greeting_matches_profile("안녕하세요 Rocha연구원님,", MESERET)


def test_name_nimkke_variant_matches() -> None:
    """자기적대 발견: '님께' 변형 인사말이 추출 실패(fail-closed 오탐)하면 안 된다."""
    assert extract_greeting_name("안녕하세요 조현용님께,") == "조현용"
    assert greeting_matches_profile("안녕하세요 조현용님께,", "조현용")


def test_name_zero_width_evasion_blocked() -> None:
    """자기적대: zero-width·전각 삽입으로 금지 워딩 린트를 우회할 수 없다."""
    body = _ok_body_ko("Meseret") + "\n딱​맞는 포지션, ５분만 통화"
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    labels = [s for s in result.stops if "forbidden" in s]
    assert any("exaggeration" in s for s in labels)
    assert any("call_request" in s for s in labels)


def test_name_english_greeting_forms() -> None:
    assert extract_greeting_name("Hi Meseret,\n\nbody") is not None
    assert greeting_matches_profile("Hi Meseret,", MESERET)
    assert not greeting_matches_profile("Hi Rocha,", MESERET)


def test_name_missing_greeting_fails_closed() -> None:
    """인사말에서 이름을 못 찾으면 통과가 아니라 STOP (fail-open 금지)."""
    body = "본문에 인사말이 없습니다.\n" + VERIFIED_PULL_KO
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert not result.ok
    assert any("name" in s for s in result.stops)


# ── charlimit: 채널별 글자수 ───────────────────────────────────────
def test_charlimit_constants() -> None:
    assert CHANNEL_CHAR_LIMITS["linkedin_rps"] == 1899
    assert CHANNEL_CHAR_LIMITS["saramin"] == 2000
    assert CHANNEL_CHAR_LIMITS["jobkorea"] == 2000


def test_charlimit_1899_passes_1900_stops() -> None:
    base = _ok_body_ko("Meseret")
    pad = 1899 - char_count(base)
    ok_body = base + "가" * pad
    assert char_count(ok_body) == 1899
    r_ok = precheck_inmail(ok_body, profile_name=MESERET, channel="linkedin_rps")
    assert not any("char" in s for s in r_ok.stops)
    r_over = precheck_inmail(ok_body + "가", profile_name=MESERET, channel="linkedin_rps")
    assert not r_over.ok
    assert any("char" in s for s in r_over.stops)


def test_charlimit_counts_nfc_not_bytes() -> None:
    # NFD 풀어쓴 한글이 바이트/자모 단위로 부풀려 세지면 안 된다.
    import unicodedata

    nfd = unicodedata.normalize("NFD", "한글")
    assert char_count(nfd) == 2


# ── forbidden: 금지 워딩 린트 ─────────────────────────────────────
@pytest.mark.parametrize(
    "phrase",
    [
        "짧게 전화 통화 가능하실까요?",
        "5분만 통화하시죠.",
        "이 포지션이 딱 맞아 보입니다.",
        "경력과 정확히 맞물린다고 생각합니다.",
        "후보님께 꼭 맞는 자리입니다.",
        "안녕하세요 {{firstName}}님",
        "본문 <!-- integrity: meta --> 끝",
        "중괄호 { 단독",
    ],
)
def test_forbidden_wording_stops(phrase: str) -> None:
    body = _ok_body_ko("Meseret") + "\n" + phrase
    result = precheck_inmail(body, profile_name=MESERET, channel="saramin")
    assert not result.ok, phrase
    assert any("forbidden" in s for s in result.stops)


def test_forbidden_does_not_flag_r21_cta() -> None:
    """R21 표준 P.S.('딱 맞지 않으셔도')는 과장이 아니다 — 오탐 금지."""
    body = _ok_body_ko("Meseret")
    assert PS_CTA in body
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert not any("forbidden" in s for s in result.stops)
    assert result.ok


# ── briefing: 회사 브리핑 요소 카운트(6 미만 = 보고, STOP 아님) ────
def test_briefing_keys_are_the_eight_elements() -> None:
    assert len(BRIEFING_ELEMENT_KEYS) == 8


def test_briefing_below_6_warns_but_does_not_stop() -> None:
    body = _ok_body_ko("Meseret")
    elements = {k: "" for k in BRIEFING_ELEMENT_KEYS}
    elements[BRIEFING_ELEMENT_KEYS[0]] = "글로벌 1,000곳+ 제품개발 파트너"
    assert count_briefing_elements(elements) == 1
    result = precheck_inmail(
        body, profile_name=MESERET, channel="linkedin_rps",
        briefing_element_count=count_briefing_elements(elements),
    )
    assert result.ok, "6개 미만은 '보고 후 진행'(warning)이지 STOP 이 아니다"
    assert any("briefing" in w for w in result.warnings)


def test_briefing_unverified_marker_not_counted() -> None:
    elements = {k: "※미확인" for k in BRIEFING_ELEMENT_KEYS}
    assert count_briefing_elements(elements) == 0


# ── typo: 자모 분리 + 알려진 오타 ─────────────────────────────────
def test_typo_jamo_separation_stops() -> None:
    body = _ok_body_ko("Meseret") + "\n뒤튼ㅇㅣ 아니라 뤼튼입니다."
    assert hangul_jamo_broken("ㅇㅣ런 자모")
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert not result.ok
    assert any("typo" in s or "jamo" in s for s in result.stops)


def test_typo_known_hanida_stops() -> None:
    body = _ok_body_ko("Meseret") + "\n감사하니다."
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert not result.ok
    assert any("typo" in s for s in result.stops)


def test_typo_normal_korean_not_flagged() -> None:
    assert not hangul_jamo_broken(_ok_body_ko("조현용"))
    result = precheck_inmail(_ok_body_ko("조현용"), profile_name="조현용", channel="linkedin_rps")
    assert result.ok


# ── verified: VERIFIED-PULL 필수 문단 ─────────────────────────────
def test_verified_pull_missing_stops() -> None:
    body = _ok_body_ko("Meseret").replace(VERIFIED_PULL_KO, "")
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert not result.ok
    assert any("verified" in s for s in result.stops)


def test_verified_pull_english_marker_accepted() -> None:
    body = _ok_body_ko("Meseret").replace(VERIFIED_PULL_KO, VERIFIED_PULL_EN)
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert not any("verified" in s for s in result.stops)


# ── language: 프로필 언어 자동 선택 ───────────────────────────────
def test_language_english_profile() -> None:
    assert body_language_for_profile(MESERET) == "en"


def test_language_korean_profile() -> None:
    assert body_language_for_profile("조현용") == "ko"


def test_language_empty_name_falls_back_to_text() -> None:
    assert body_language_for_profile("", visible_text="Robotics engineer, ETH Zurich") == "en"
    assert body_language_for_profile("", visible_text="로보틱스 엔지니어 5년") == "ko"


# ── lang_ko: 한국어 기본·로마자 한국 이름 오판 제거 (사장님 2026-07-03) ──
@pytest.mark.parametrize(
    "name",
    ["HyunJun Jo", "Hyunjun Cho", "Minsu Kim", "Sumin LEE", "Sangbeom Park",
     "Jongchan Baek", "Kangwon Lee", "Jo HyunJun",
     "Brian Paik", "Andrew Yim", "Eunice Chey", "Joyce Yeom", "Alice Maeng"],  # codex V1 적발
)
def test_lang_ko_romanized_korean_name(name: str) -> None:
    """로마자 표기 한국 이름(성씨 신호)은 한국인 → 본문 한국어."""
    assert body_language_for_profile(name) == "ko"


def test_lang_ko_latin_name_with_hangul_text() -> None:
    """이름이 라틴이어도 프로필에 한글(한국 대학 등)이 보이면 한국인."""
    assert body_language_for_profile("HyunJun Jo", visible_text="고려대학교 PhD") == "ko"


def test_lang_ko_foreign_names_stay_english() -> None:
    """명백한 외국 이름은 영어 유지(사장님 명시 잘한 점 — Meseret 건)."""
    assert body_language_for_profile(MESERET) == "en"
    assert body_language_for_profile("John Smith") == "en"


def test_lang_ko_precheck_no_warning_for_romanized_korean() -> None:
    """재발 봉인: 'HyunJun Jo' + 한국어 본문에 language_mismatch 경고 금지."""
    body = _ok_body_ko("HyunJun Jo")
    result = precheck_inmail(body, profile_name="HyunJun Jo", channel="linkedin_rps")
    assert result.ok, result.stops
    assert not any("language" in w for w in result.warnings)


# ── codexv1: codex 1차 적대검증(FAIL 5건) 회귀 봉인 ────────────────
def test_codexv1_two_char_latin_token_no_false_pass() -> None:
    """[HIGH] 'et'⊂'Meseret' 우연 포함 일치 fail-open 차단."""
    assert not greeting_matches_profile("Hi Et,", MESERET)
    body = _ok_body_ko("Et")
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert any("name" in s for s in result.stops)


def test_codexv1_two_char_hangul_containment_still_matches() -> None:
    """한글 2자 이름 포함 일치('민수'⊂'김민수')는 유지 — 과잉 차단 금지."""
    assert greeting_matches_profile("안녕하세요 민수님,", "김민수")


def test_codexv1_whitespace_split_call_request_stops() -> None:
    """[HIGH] '전 화'·'통 화' 공백 삽입 우회 차단."""
    body = _ok_body_ko("Meseret") + "\n5분만 전 화 가능하실까요?"
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert any("call_request" in s for s in result.stops)


def test_codexv1_ps_cta_missing_stops() -> None:
    """[MED] P.S. 인입 CTA(R21) 부재 → STOP (Movensys 결함 ③ 나머지 절반)."""
    body = _ok_body_ko("Meseret").replace(PS_CTA, "")
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert not result.ok
    assert any("ps_cta" in s for s in result.stops)


def test_codexv1_korean_body_for_english_profile_warns() -> None:
    """[MED] 영문 프로필 + 한국어 본문 → language_mismatch 경고(보고 후 진행)."""
    result = precheck_inmail(_ok_body_ko("Meseret"), profile_name=MESERET, channel="linkedin_rps")
    assert result.ok, "언어 규칙은 STOP 이 아니라 보고(warning)"
    assert any("language" in w for w in result.warnings)


def test_codexv1_english_body_with_korean_greeting_and_ps_no_warning() -> None:
    """영문 본문 + 한국어 인사말/P.S.(허용 예외)는 경고 없음."""
    body = "\n".join(
        [
            "안녕하세요 Meseret님,",
            "",
            "I am Sangmo Kang, a headhunter at Valueconnect, a tech search firm.",
            "I reviewed your robotics background and one thing stood out to me.",
            "",
            "[Role]",
            "· Develop robotics motion-control software",
            "",
            VERIFIED_PULL_EN,
            "",
            "Thank you — Sangmo Kang",
            "",
            PS_CTA,
        ]
    )
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert result.ok, result.stops
    assert not any("language" in w for w in result.warnings)


def test_codexv1_single_jamo_stops_spec_locked() -> None:
    """[LOW] 단독 자모('ㄱ 항목')도 STOP — 문서·코드 합의를 코드 기준(보수)으로 고정."""
    body = _ok_body_ko("Meseret") + "\nㄱ 항목"
    result = precheck_inmail(body, profile_name=MESERET, channel="linkedin_rps")
    assert any("jamo" in s for s in result.stops)


# ── cli: SKILL 이 호출하는 실제 진입점 ────────────────────────────
def test_cli_exit_codes(tmp_path: Path) -> None:
    good = tmp_path / "good.txt"
    good.write_text(_ok_body_ko("Meseret"), encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text(_ok_body_ko("Rocha 연구원"), encoding="utf-8")
    cmd = [sys.executable, "-m", "tools.multi_position_sourcing.inmail_precheck"]
    ok = subprocess.run(
        cmd + ["--body-file", str(good), "--profile-name", MESERET, "--channel", "linkedin_rps"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr
    ng = subprocess.run(
        cmd + ["--body-file", str(bad), "--profile-name", MESERET, "--channel", "linkedin_rps"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert ng.returncode == 1, ng.stdout + ng.stderr
    assert "name" in (ng.stdout + ng.stderr)
