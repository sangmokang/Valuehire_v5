"""humansearch #8 — 핵심 후보 개인화 InMail 발송 전 기계 체크리스트.

Movensys 사고(2026-06-30, 수신자 Meseret Abayebas Tadese 에게 "Rocha연구원님" 인사 +
"하니다" 오타 + VERIFIED-PULL·P.S. CTA 누락) 재발 봉인. 발송은 언제나 사장님 수동(SOT3) —
이 모듈은 "문구를 저장/채팅창 제공하기 직전"의 fail-closed 검문소다.

체크 5종(STOP) + 1종(보고):
  ① 인사말 이름 == 수확 프로필 이름 (부분 일치, 추출 실패도 STOP — fail-open 금지)
  ② 채널별 글자수 한도 (linkedin_rps 1,899 / saramin·jobkorea 2,000, NFC 문자수)
  ③ 금지 워딩 린트 (통화·전화 요청 / "딱 맞·정확히 맞물·꼭 맞"류 과장 / raw {·} / HTML 주석)
     — 단 R21 표준 CTA "딱 맞지 않으셔도"는 부정문이므로 통과
  ④ 회사 브리핑 요소(position-register §1.5 8요소) 6개 미만 → warning(보고 후 진행)
  ⑤ 한글 자모 분리·알려진 오타("하니다") → STOP
  ⑥ VERIFIED-PULL(무료 이력서 피드백) 문단 부재 → STOP

CLI (SKILL #8 이 발송 전 필수로 호출):
  python3 -m tools.multi_position_sourcing.inmail_precheck \
    --body-file <문구.txt> --profile-name "<수확 name 그대로>" --channel linkedin_rps \
    [--briefing-elements N]
  exit 0 = 통과 / 1 = STOP(사유 JSON 출력) / 2 = 사용법 오류
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# position-register §1.5 — 회사 브리핑 8요소 (3채널 공통 SOT)
BRIEFING_ELEMENT_KEYS: tuple[str, ...] = (
    "one_line",       # ① 한 줄 정의 (무엇을 누구에게)
    "history",        # ② 설립·연혁 핵심
    "funding_stage",  # ③ 상장/투자 단계
    "revenue",        # ④ 매출·이익 (연도 명시)
    "headcount",      # ⑤ 임직원 수
    "parent_group",   # ⑥ 모기업/계열·주요 주주
    "ceo_quote",      # ⑦ 대표 소개 + 공개 발언 quote (출처)
    "recent_news",    # ⑧ 최근 뉴스·신사업
)
BRIEFING_MIN_ELEMENTS = 6
UNVERIFIED_MARKER = "※미확인"

# 채널별 본문 한도 — linkedin R2 hard cap / 사람인 offerComment·잡코리아 EXEC_WORK 2,000자
CHANNEL_CHAR_LIMITS: dict[str, int] = {
    "linkedin_rps": 1899,
    "saramin": 2000,
    "jobkorea": 2000,
}

# 인사말에서 이름 뒤에 붙는 호칭 — 이름 비교 전 제거
_TITLE_SUFFIXES: tuple[str, ...] = (
    "연구원", "책임", "선임", "수석", "매니저", "프로", "팀장", "파트장", "실장",
    "이사", "상무", "대표", "개발자", "엔지니어", "디자이너", "박사", "석사",
    "교수", "과장", "차장", "부장", "대리", "사원", "님", "씨",
)

_KO_GREETING = re.compile(r"안녕하세요[,!.]*\s*([^\n]{1,40}?)\s*(?:님|씨)(?:께)?\s*[,!.\s]")
_EN_GREETING = re.compile(
    r"^(?:Hi|Hello|Dear)\s+([A-Za-z][A-Za-z .'\-]{0,40}?)\s*[,!\n]",
    re.MULTILINE | re.IGNORECASE,
)

# 금지 워딩 — 골든샘플 절대규칙. R21 CTA("딱/꼭 맞지 않으셔도")는 부정문이라 제외.
_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("call_request", re.compile(r"통화|전화|phone\s*call|quick\s*call", re.IGNORECASE)),
    ("exaggeration", re.compile(r"딱\s*맞(?!지\s*않)|정확히\s*맞물|꼭\s*맞(?!지\s*않)|perfect\s*fit", re.IGNORECASE)),
    ("raw_brace", re.compile(r"[{}]")),          # R25 — invalid variable 배너
    ("html_comment", re.compile(r"<!--")),        # R25 — 스크래퍼 메타 잔재
)

_JAMO = re.compile(r"[ㄱ-ㅣ]")                    # 정상 완성형 문장엔 자모 단독 출현 0
_KNOWN_TYPOS: tuple[str, ...] = ("하니다",)       # Movensys 실사고 오타("합니다" 오기)

# VERIFIED-PULL 필수 마커 — 한/영 본문 각각 인정
_VERIFIED_PULL_MARKERS: tuple[str, ...] = ("이력서 피드백", "레주메 피드백", "resume feedback")

_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")


def char_count(body: str) -> int:
    """NFC 정규화 코드포인트 수 — LinkedIn counter([...body].length)와 동일 기준."""
    return len(unicodedata.normalize("NFC", body))


def _fold(text: str) -> str:
    """NFKC + 형식문자(Cf, zero-width 류) 제거 + lower — 린트 우회 차단."""
    t = unicodedata.normalize("NFKC", text)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    return t.lower()


def _strip_titles(name: str) -> str:
    tokens = name.split()
    while tokens and tokens[-1] in _TITLE_SUFFIXES:
        tokens.pop()
    out = " ".join(tokens)
    for suffix in _TITLE_SUFFIXES:  # 붙여 쓴 호칭: "Rocha연구원"
        if out.endswith(suffix) and len(out) > len(suffix):
            out = out[: -len(suffix)]
            break
    return out.strip()


def extract_greeting_name(body: str) -> str | None:
    """본문 앞부분 인사말에서 수신자 이름을 추출. 못 찾으면 None (호출측 fail-closed)."""
    head = "\n".join(body.splitlines()[:5])
    m = _KO_GREETING.search(head + " ")
    if m:
        name = _strip_titles(m.group(1).strip())
        return name or None
    m = _EN_GREETING.search(head)
    if m:
        return m.group(1).strip() or None
    return None


def _name_tokens(s: str) -> list[str]:
    folded = _fold(s)
    return [t for t in re.split(r"[^0-9a-z가-힣]+", folded) if len(t) >= 2]


def greeting_matches_profile(body: str, profile_name: str) -> bool:
    """인사말 이름 ↔ 수확 프로필 이름 부분 일치. 추출 실패·공허 입력은 False(fail-closed)."""
    greeting = extract_greeting_name(body)
    if not greeting or not (profile_name or "").strip():
        return False
    g_tokens = _name_tokens(greeting)
    p_tokens = _name_tokens(profile_name)
    if not g_tokens or not p_tokens:
        return False
    return any(g == p or g in p or p in g for g in g_tokens for p in p_tokens)


def hangul_jamo_broken(text: str) -> bool:
    """자모 단독 출현(ㄱ-ㅣ) = 입력 깨짐 신호. 완성형 정상 문장은 0회."""
    return _JAMO.search(text) is not None


def count_briefing_elements(elements: dict) -> int:
    """§1.5 8요소 중 '출처 있는 값'이 채워진 개수. ※미확인·빈값은 제외."""
    count = 0
    for value in (elements or {}).values():
        text = str(value or "").strip()
        if text and not text.startswith(UNVERIFIED_MARKER):
            count += 1
    return count


def body_language_for_profile(name: str, visible_text: str = "") -> str:
    """프로필 이름·이력이 영문이면 'en'(인사말만 한국어 허용), 아니면 'ko'."""
    name = (name or "").strip()
    if name:
        if _HANGUL.search(name):
            return "ko"
        if _LATIN.search(name):
            return "en"
    text = (visible_text or "").strip()
    if text and not _HANGUL.search(text) and _LATIN.search(text):
        return "en"
    return "ko"


@dataclass(frozen=True)
class InMailPrecheckResult:
    ok: bool
    stops: tuple[str, ...]
    warnings: tuple[str, ...]
    char_count: int
    channel: str


def precheck_inmail(
    body: str,
    *,
    profile_name: str,
    channel: str,
    briefing_element_count: int | None = None,
) -> InMailPrecheckResult:
    """발송 전 기계 체크리스트. stops 가 하나라도 있으면 ok=False → 문구 제공 금지(STOP)."""
    stops: list[str] = []
    warnings: list[str] = []
    body = body or ""

    # ② 채널 한도 (미지의 채널 = fail-closed)
    n = char_count(body)
    limit = CHANNEL_CHAR_LIMITS.get(channel)
    if limit is None:
        stops.append(f"channel_unknown: '{channel}' — 허용 채널 {sorted(CHANNEL_CHAR_LIMITS)}")
    elif n > limit:
        stops.append(f"char_limit: {n}자 > {limit}자 ({channel})")

    # ① 인사말 이름 일치 (추출 실패 포함 STOP)
    if not greeting_matches_profile(body, profile_name):
        greeting = extract_greeting_name(body)
        if greeting is None:
            stops.append("name_greeting_not_found: 인사말에서 수신자 이름을 찾지 못함 — fail-closed STOP")
        else:
            stops.append(f"name_mismatch: 인사말 '{greeting}' ≠ 프로필 '{profile_name}' — STOP")

    # ③ 금지 워딩
    folded = _fold(body)
    for label, pattern in _FORBIDDEN_PATTERNS:
        target = body if label in ("raw_brace", "html_comment") else folded
        hit = pattern.search(target)
        if hit:
            stops.append(f"forbidden_wording[{label}]: '{hit.group(0)}'")

    # ⑤ 자모 분리·알려진 오타
    if hangul_jamo_broken(body):
        stops.append("typo_jamo: 한글 자모 분리(입력 깨짐) 감지 — 스크린샷 대조 필요")
    for typo in _KNOWN_TYPOS:
        if typo in folded:
            stops.append(f"typo_known: '{typo}'")

    # ⑥ VERIFIED-PULL 문단
    if not any(marker in folded for marker in _VERIFIED_PULL_MARKERS):
        stops.append("verified_pull_missing: 무료 이력서 피드백(VERIFIED-PULL) 문단 부재")

    # ④ 회사 브리핑 요소 — 6개 미만은 STOP 이 아니라 보고(§1.5 '보고 후 진행')
    if briefing_element_count is not None and briefing_element_count < BRIEFING_MIN_ELEMENTS:
        warnings.append(
            f"briefing_below_6: 확인된 브리핑 요소 {briefing_element_count}/{len(BRIEFING_ELEMENT_KEYS)}"
            f" (<{BRIEFING_MIN_ELEMENTS}) — 사장님 보고 후 진행"
        )

    return InMailPrecheckResult(
        ok=not stops,
        stops=tuple(stops),
        warnings=tuple(warnings),
        char_count=n,
        channel=channel,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="humansearch #8 InMail 발송 전 기계 체크리스트")
    parser.add_argument("--body-file", required=True, help="검사할 문구 파일(UTF-8)")
    parser.add_argument("--profile-name", required=True, help="수확 JSON 의 name 그대로")
    parser.add_argument("--channel", required=True, help="linkedin_rps | saramin | jobkorea")
    parser.add_argument("--briefing-elements", type=int, default=None, help="확인된 §1.5 요소 개수")
    args = parser.parse_args(argv)

    body = Path(args.body_file).read_text(encoding="utf-8")
    result = precheck_inmail(
        body,
        profile_name=args.profile_name,
        channel=args.channel,
        briefing_element_count=args.briefing_elements,
    )
    print(
        json.dumps(
            {
                "ok": result.ok,
                "stops": list(result.stops),
                "warnings": list(result.warnings),
                "char_count": result.char_count,
                "channel": result.channel,
                "limit": CHANNEL_CHAR_LIMITS.get(result.channel),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
