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
    },
    "linkedin_rps": {
        "profile_url": (
            SelectorCandidate("label", 'a[href*="/talent/profile/"]', "RPS candidate profile links only"),
            SelectorCandidate("data-test", '[data-test-profile-link]', "data-test fallback if available"),
        ),
        "inmail_send_button_forbidden": (
            SelectorCandidate("label", 'button:has-text("Send InMail")', "forbidden outreach control; must never click"),
            SelectorCandidate("label", 'button:has-text("보내기")', "forbidden localized outreach control"),
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

