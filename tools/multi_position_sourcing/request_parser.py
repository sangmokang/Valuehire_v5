from __future__ import annotations

from dataclasses import dataclass
import re


CLICKUP_TASK_RE = re.compile(r"https?://(?:app\.)?clickup\.com/[^\s)]+", re.IGNORECASE)
WANTED_RE = re.compile(r"https?://(?:www\.)?wanted\.co\.kr/[^\s)]+", re.IGNORECASE)
SEARCH_WORD_RE = re.compile(r"(AI\s*Search|search|서치|써치|검색|후보자\s*찾|롱리스트)", re.IGNORECASE)
REGISTRATION_WORD_RE = re.compile(
    r"(포지션|채용공고|JD|원티드|wanted).{0,20}(등록|추가|올려|넣어|생성|만들)|"
    r"(등록|추가|올려|넣어|생성|만들).{0,20}(포지션|채용공고|JD|원티드|wanted)",
    re.IGNORECASE,
)

JD_SIGNALS = ("담당업무", "자격요건", "우대사항", "주요업무", "채용", "포지션", "JD", "회사소개")


@dataclass(frozen=True)
class SearchRequestParseResult:
    should_route_to_search: bool
    has_position: bool
    input_kind: str
    position_text: str
    reason: str


@dataclass(frozen=True)
class PositionRegistrationRequestParseResult:
    should_route_to_registration: bool
    has_position: bool
    input_kind: str
    position_text: str
    url: str
    text: str
    source: str
    live_external_posting: bool
    reason: str


def _looks_like_registration_request(text: str) -> bool:
    return bool(REGISTRATION_WORD_RE.search(text))


def _looks_like_pasted_jd(text: str) -> bool:
    return len(text) >= 80 and any(signal in text for signal in JD_SIGNALS)


def parse_discord_position_registration_request(message: str) -> PositionRegistrationRequestParseResult:
    """Parse a Discord DM into a fail-closed Valuehire position registration decision.

    This parser is intentionally separate from AI Search routing. Registration is a
    ClickUp/FY26 position intake workflow, not candidate sourcing. It never implies
    external portal posting or outreach; callers must keep those side effects off
    unless a later owner sign-off explicitly opens them.
    """
    text = message.strip()
    if not text:
        return PositionRegistrationRequestParseResult(False, False, "empty", "", "", "", "", False, "empty message")

    registration_intent = _looks_like_registration_request(text)
    clickup = CLICKUP_TASK_RE.search(text)
    wanted = WANTED_RE.search(text)

    if wanted and registration_intent:
        url = wanted.group(0)
        return PositionRegistrationRequestParseResult(
            True,
            True,
            "wanted_url",
            url,
            url,
            "",
            "wanted",
            False,
            "Wanted URL position registration input",
        )
    if clickup and registration_intent:
        url = clickup.group(0)
        return PositionRegistrationRequestParseResult(
            True,
            True,
            "clickup_url",
            url,
            url,
            "",
            "clickup",
            False,
            "ClickUp URL position registration input",
        )
    if registration_intent and _looks_like_pasted_jd(text):
        cleaned = REGISTRATION_WORD_RE.sub("", text, count=1).strip(" :：\n\t-") or text
        return PositionRegistrationRequestParseResult(
            True,
            True,
            "pasted_jd",
            cleaned,
            "",
            cleaned,
            "pasted_jd",
            False,
            "pasted JD position registration input",
        )
    if registration_intent:
        cleaned = REGISTRATION_WORD_RE.sub("", text, count=1).strip(" :：\n\t-")
        if len(cleaned) >= 6:
            return PositionRegistrationRequestParseResult(
                True,
                True,
                "plain_position",
                cleaned,
                "",
                cleaned,
                "plain_position",
                False,
                "plain text position registration input",
            )
        return PositionRegistrationRequestParseResult(
            True,
            False,
            "missing_position",
            "",
            "",
            "",
            "",
            False,
            "registration intent without position",
        )

    return PositionRegistrationRequestParseResult(False, False, "not_registration", "", "", "", "", False, "no registration intent")


def parse_discord_search_request(message: str) -> SearchRequestParseResult:
    """Parse a Discord DM into a fail-closed AI Search routing decision.

    Supported position inputs:
    - ClickUp task/list URL
    - Wanted job URL
    - pasted job description or explicit company/role text

    If the message only says "Search" without a position, do not run sourcing.
    The caller should ask the user to send a ClickUp link, Wanted link, or JD text.
    """
    text = message.strip()
    if not text:
        return SearchRequestParseResult(False, False, "empty", "", "empty message")

    if _looks_like_registration_request(text):
        return SearchRequestParseResult(False, False, "registration_request", "", "position registration request must not route to AI Search")

    search_intent = bool(SEARCH_WORD_RE.search(text))
    clickup = CLICKUP_TASK_RE.search(text)
    wanted = WANTED_RE.search(text)
    pasted_jd = _looks_like_pasted_jd(text)

    if pasted_jd and (clickup or wanted):
        return SearchRequestParseResult(
            True,
            True,
            "url_plus_pasted_jd",
            text,
            "Discord URL plus pasted JD input; use pasted JD immediately and treat URL as reference",
        )
    if clickup:
        return SearchRequestParseResult(True, True, "clickup_url", clickup.group(0), "ClickUp URL position input")
    if wanted:
        return SearchRequestParseResult(True, True, "wanted_url", wanted.group(0), "Wanted URL position input")

    # Treat long pasted text as a JD even if it does not contain the search word.
    if pasted_jd:
        return SearchRequestParseResult(True, True, "pasted_jd", text, "pasted JD position input")

    # Short explicit position text is accepted only when the user clearly asks for search.
    if search_intent:
        cleaned = SEARCH_WORD_RE.sub("", text).strip(" :：\n\t-")
        if len(cleaned) >= 6:
            return SearchRequestParseResult(True, True, "plain_position", cleaned, "plain text position input")
        return SearchRequestParseResult(True, False, "missing_position", "", "search intent without position")

    return SearchRequestParseResult(False, False, "not_search", "", "no search intent or supported position input")
