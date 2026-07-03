from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.multi_position_sourcing.inmail_precheck import (
    body_language_for_profile,
    char_count,
    extract_greeting_name,
    greeting_matches_profile,
    hangul_jamo_broken,
    precheck_inmail,
)


PROFILE_EN = "Meseret Abayebas Tadese"
PROFILE_KO = "조현용"
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
    "더 잘 맞는 기회까지 연결해 드립니다 - 무료 커리어 검증 신청: https://valuehire.cc/resume"
)


def ok_body_ko(name: str = "조현용", *, ps: bool = True) -> str:
    parts = [
        f"안녕하세요 {name}님,",
        "",
        "저는 테크 서치펌 밸류커넥트(Valueconnect)의 헤드헌터 강상모라고 합니다.",
        "이력을 살펴보고 먼저 제안드립니다. 최근 이직이 기존 전문영역과 결이 조금 다르다 싶었습니다.",
        "",
        "[회사 브리핑]",
        "* 1993년 설립, 2022년 코스닥 상장",
        "",
        "[주요 업무]",
        "* 모션제어 소프트웨어 개발",
        "",
        "[자격 요건]",
        "* C++ 및 로보틱스 경력",
        "",
        "[왜 검토할 만한가]",
        "* 도메인 난이도와 성장 여지",
        "",
        VERIFIED_PULL_KO,
        "",
        "감사합니다.",
        "강상모 드림",
    ]
    if ps:
        parts.extend(["", PS_CTA])
    return "\n".join(parts)


def ok_body_en(name: str = "Meseret") -> str:
    return "\n".join(
        [
            f"Hi {name},",
            "",
            "I am Sangmo Kang from Valueconnect.",
            "I reviewed your background and wanted to share one carefully selected role.",
            "",
            "[Company Briefing]",
            "* Founded in 1993 and listed on KOSDAQ in 2022.",
            "",
            "[Responsibilities]",
            "* Build motion-control software.",
            "",
            "[Requirements]",
            "* C++ and robotics experience.",
            "",
            "[Why it may be worth reviewing]",
            "* The role has a technical domain with room to grow.",
            "",
            VERIFIED_PULL_EN,
            "",
            "Best regards,",
            "Sangmo Kang",
        ]
    )


def result(body: str | None, profile: str | None = PROFILE_EN, channel: str = "linkedin_rps") -> dict:
    r = precheck_inmail(body, profile_name=profile, channel=channel)
    return {
        "ok": r.ok,
        "stops": list(r.stops),
        "warnings": list(r.warnings),
        "char_count": r.char_count,
    }


base = ok_body_ko("Meseret")
boundary_base = ok_body_ko("Meseret")
boundary_pad = 1899 - char_count(boundary_base)

cases = {
    "AC1_honorific_variant_survives": {
        "extract": extract_greeting_name("안녕하세요 Meseret 연구원님,\n본문"),
        "matches": greeting_matches_profile("안녕하세요 Meseret 연구원님,\n본문", PROFILE_EN),
    },
    "AC1_surname_given_order_survives": {
        "matches": greeting_matches_profile("Hi Tadese Meseret,", PROFILE_EN),
    },
    "AC1_two_char_token_false_pass": result(ok_body_ko("et")),
    "AC1_empty_body_fail_closed": result(""),
    "AC1_none_body_fail_closed": result(None),
    "AC1_empty_profile_fail_closed": result(base, ""),
    "AC2_nfc_nfd": {
        "nfc_len": char_count("한글"),
        "nfd_len": char_count(unicodedata.normalize("NFD", "한글")),
    },
    "AC2_non_bmp_emoji": {"char_count": char_count("😀")},
    "AC2_crlf_boundary": {
        "lf": char_count("a\nb"),
        "crlf": char_count("a\r\nb"),
    },
    "AC2_1899_ok": result(boundary_base + ("가" * boundary_pad)),
    "AC2_1900_stop": result(boundary_base + ("가" * boundary_pad) + "가"),
    "AC3_whitespace_call_bypass": result(base + "\n5분만 전 화 가능하실까요?"),
    "AC3_zero_width_fullwidth_case_blocked": result(base + "\n딱\u200b맞는 포지션, ＰＨＯＮＥ　ＣＡＬＬ"),
    "AC3_r21_cta_not_blocked": result(base),
    "AC3_normal_sentence_not_blocked": result(base + "\n역할 범위와 조직 맥락을 보고 차분히 검토해 보셔도 좋겠습니다."),
    "AC4_briefing_warning_only": {
        "one_element": precheck_inmail(base, profile_name=PROFILE_EN, channel="linkedin_rps", briefing_element_count=1).__dict__,
    },
    "AC5_normal_korean_not_flagged": {
        "hangul_jamo_broken": hangul_jamo_broken(ok_body_ko(PROFILE_KO)),
        "result": result(ok_body_ko(PROFILE_KO), PROFILE_KO),
    },
    "AC5_single_jamo_overblock": result(ok_body_ko(PROFILE_KO) + "\nㄱ 항목은 회사 브리핑입니다.", PROFILE_KO),
    "AC5_hanida_substring": result(ok_body_ko(PROFILE_KO) + "\n사하니다라는 내부 코드명은 없습니다.", PROFILE_KO),
    "AC6_missing_verified_stops": result(base.replace(VERIFIED_PULL_KO, "")),
    "AC6_english_marker_survives": result(ok_body_en("Meseret")),
    "AC6_missing_ps_cta_false_pass": result(ok_body_ko("Meseret", ps=False)),
    "AC7_language_helper": {
        "english_profile": body_language_for_profile(PROFILE_EN),
        "korean_profile": body_language_for_profile(PROFILE_KO),
        "empty_english_text": body_language_for_profile("", "Robotics engineer, ETH Zurich"),
        "empty_korean_text": body_language_for_profile("", "로보틱스 엔지니어 5년"),
    },
    "AC7_english_profile_korean_body_false_pass": result(ok_body_ko("Meseret")),
    "AC8_unknown_channel_fail_closed": result(base, PROFILE_EN, "unknown"),
}


print(json.dumps(cases, ensure_ascii=False, indent=2, default=str))
