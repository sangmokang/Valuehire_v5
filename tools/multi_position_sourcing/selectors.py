from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SelectorKind = Literal["name", "id", "data-test", "label", "class"]


class SelectorResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SelectorCandidate:
    kind: SelectorKind
    selector: str
    purpose: str


SELECTOR_PRIORITY: tuple[SelectorKind, ...] = ("name", "id", "data-test", "label", "class")


DEFAULT_SELECTOR_MAP: dict[str, dict[str, tuple[SelectorCandidate, ...]]] = {
    "saramin": {
        "keyword_input": (
            SelectorCandidate("name", 'input[name="searchword"]', "keyword input if exposed by form name"),
            SelectorCandidate("id", "#searchword", "stable keyword input id fallback"),
            SelectorCandidate("label", 'input[placeholder*="검색"]', "placeholder fallback"),
            SelectorCandidate("class", ".search_default input.search_input", "observed class fallback; use clipboard paste for Korean"),
        ),
        "search_button": (
            SelectorCandidate("name", 'button[name="search"]', "form search button"),
            SelectorCandidate("label", 'button:has-text("검색")', "visible text fallback"),
            SelectorCandidate("class", ".search_panel .btn_search", "class fallback"),
        ),
        # SOT28 자동발송 — 이직 제안 모달(사람인 SKILL §10.1~10.5 라이브 절차의 코드화)
        "offer_comment_input": (
            SelectorCandidate("name", 'textarea[name="jobOffer.offerComment"]', "제안 본문① — execCommand insertText 로만 주입(R10)"),
        ),
        "offer_charge_work_input": (
            SelectorCandidate("name", 'textarea[name="jobOffer.chargeWork"]', "제안 본문②(입사 후 업무) — insertText 주입"),
        ),
        "offer_send_button": (
            SelectorCandidate("label", 'button:has-text("제안 발송")', "SOT28 게이트(evaluate_send allowed) 통과 시에만 클릭"),
            SelectorCandidate("label", 'button:has-text("발송")', "라벨 축약 fallback — 게이트 통과 시에만 클릭"),
        ),
    },
    "jobkorea": {
        "keyword_input": (
            SelectorCandidate("id", "#txtKeyword", "observed stable keyword input"),
            SelectorCandidate("name", 'input[name="stext"]', "keyword input name fallback"),
            SelectorCandidate("label", 'input[placeholder*="검색어"]', "placeholder fallback"),
        ),
        "career_start": (
            SelectorCandidate("id", "#txtCareerStart", "observed career start field"),
            SelectorCandidate("name", 'input[name="CareerStart"]', "career start name fallback"),
        ),
        "career_end": (
            SelectorCandidate("id", "#txtCareerEnd", "observed career end field"),
            SelectorCandidate("name", 'input[name="CareerEnd"]', "career end name fallback"),
        ),
        "filter_search_button": (
            SelectorCandidate("class", ".btnSearchFilter", "observed detailed search button"),
            SelectorCandidate("label", 'button:has-text("검색")', "visible text fallback"),
        ),
        # SOT28 자동발송 — 포지션 제안 흐름(잡코리아 SKILL §16 프로즈 절차의 코드화)
        "offer_preview_button": (
            SelectorCandidate("label", 'button:has-text("미리보기")', "제안 미리보기(miribogi) 열기"),
            SelectorCandidate("class", ".btn-preview", "미리보기 class fallback"),
        ),
        "offer_send_button": (
            SelectorCandidate("label", 'button:has-text("제안보내기")', "SOT28 게이트(evaluate_send allowed) 통과 시에만 클릭"),
            SelectorCandidate("label", 'button:has-text("제안 보내기")', "띄어쓰기 변형 fallback — 게이트 통과 시에만 클릭"),
        ),
    },
    "linkedin_rps": {
        "profile_url": (
            SelectorCandidate("label", 'a[href*="/talent/profile/"]', "RPS candidate profile links only"),
            SelectorCandidate("data-test", '[data-test-profile-link]', "data-test fallback if available"),
        ),
        # SOT28 (2026-07-07 사장님 지시): 종전 forbidden 셀렉터를 게이트 조건부 실행 셀렉터로 전환.
        # evaluate_send(allowed=True) 없이 이 버튼을 클릭하는 코드는 여전히 게이트 위반이다.
        "inmail_body_input": (
            SelectorCandidate("label", 'div[contenteditable="true"][aria-label*="message"]', "InMail 본문 컴포저 — insertText 주입"),
            SelectorCandidate("class", ".msg-form__contenteditable", "컴포저 class fallback"),
        ),
        "inmail_send_button": (
            SelectorCandidate("label", 'button:has-text("Send InMail")', "SOT28 게이트(evaluate_send allowed) 통과 시에만 클릭"),
            SelectorCandidate("label", 'button:has-text("Send")', "라벨 축약 fallback — 게이트 통과 시에만 클릭"),
            SelectorCandidate("label", 'button:has-text("보내기")', "한국어 UI fallback — 게이트 통과 시에만 클릭"),
        ),
    },
}


def resolve_selector(
    candidates: tuple[SelectorCandidate, ...],
    available_selectors: set[str],
) -> SelectorCandidate:
    for kind in SELECTOR_PRIORITY:
        for candidate in candidates:
            if candidate.kind == kind and candidate.selector in available_selectors:
                return candidate
    attempted = ", ".join(candidate.selector for candidate in candidates)
    raise SelectorResolutionError(f"site structure may have changed; no selector matched: {attempted}")


def resolve_selector_from_map(
    site: str,
    purpose: str,
    available_selectors: set[str],
) -> SelectorCandidate:
    try:
        candidates = DEFAULT_SELECTOR_MAP[site][purpose]
    except KeyError as exc:
        raise SelectorResolutionError(f"unknown selector map entry: {site}.{purpose}") from exc
    return resolve_selector(candidates, available_selectors)

