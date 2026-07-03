"""humansearch #8 — InMail 발송 전 기계 체크리스트 (RED 스텁).

Gate 2: 기대 동작이 아직 없어서 RED. 구현은 Gate 3에서.
"""
from __future__ import annotations

BRIEFING_ELEMENT_KEYS: tuple[str, ...] = ()
CHANNEL_CHAR_LIMITS: dict[str, int] = {}


def char_count(body: str) -> int:
    raise NotImplementedError("Gate 3")


def extract_greeting_name(body: str):
    raise NotImplementedError("Gate 3")


def greeting_matches_profile(body: str, profile_name: str) -> bool:
    raise NotImplementedError("Gate 3")


def hangul_jamo_broken(text: str) -> bool:
    raise NotImplementedError("Gate 3")


def count_briefing_elements(elements) -> int:
    raise NotImplementedError("Gate 3")


def body_language_for_profile(name: str, visible_text: str = "") -> str:
    raise NotImplementedError("Gate 3")


def precheck_inmail(body: str, *, profile_name: str, channel: str, briefing_element_count=None):
    raise NotImplementedError("Gate 3")


if __name__ == "__main__":
    raise SystemExit(2)
