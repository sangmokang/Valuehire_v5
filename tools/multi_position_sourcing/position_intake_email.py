from __future__ import annotations

import re


URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)

POSITION_CONTEXT_RE = re.compile(
    r"채용|채용공고|포지션|직무|JD|모집|합류|opening|position|hiring|recruit",
    re.IGNORECASE,
)
JD_HEADING_RE = re.compile(
    r"회사소개|주요업무|담당업무|자격요건|지원자격|우대사항|복지|혜택",
    re.IGNORECASE,
)
NOISE_URL_MARKERS = (
    "unsubscribe",
    "calendar.google",
    "zoom.us",
    "meet.google",
    "teams.microsoft",
)


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:)>]}\"'")


def _first_position_url(text: str) -> str:
    for match in URL_RE.finditer(text):
        url = _clean_url(match.group(0))
        lowered = url.lower()
        if any(marker in lowered for marker in NOISE_URL_MARKERS):
            continue
        return url
    return ""


def _looks_like_jd(text: str) -> bool:
    headings = {match.group(0).lower() for match in JD_HEADING_RE.finditer(text)}
    return len(text.strip()) >= 80 and len(headings) >= 2


def build_registration_message_from_email(subject: str, body: str) -> str:
    """Convert a customer email into the existing position-registration message shape.

    This is intentionally pure: no Gmail API, no ClickUp write, no search execution.
    It only returns strings accepted by ``parse_discord_position_registration_request``:
    ``"포지션 등록 <url>"`` or ``"포지션 등록\n<JD body>"``. Non-position mail
    returns ``""`` so callers fail closed.
    """
    subject = (subject or "").strip()
    body = (body or "").strip()
    combined = "\n".join(part for part in (subject, body) if part).strip()
    if not combined:
        return ""

    has_position_context = bool(POSITION_CONTEXT_RE.search(combined))
    url = _first_position_url(combined)
    if url and has_position_context:
        return f"포지션 등록 {url}"

    if _looks_like_jd(body):
        return f"포지션 등록\n{body}"

    return ""
