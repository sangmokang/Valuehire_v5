"""profile_archive_gate — 후보자 저장 강제 게이트(순수 로직 + 영수증 조회).

SOT-26 browser_evidence_capture.failure_policy: 영수증 없이 score/advance/complete 금지.
이 모듈은 그 정책을 harness 훅(2차 방어)이 쓰도록 순수 함수로 노출한다.
전진성 작업(제안 발송·후보 등록·pos-fill)만 좁게 차단하고, 검색·로그인·읽기는 통과한다.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping

# 저장(캡처)을 스스로 수행하는 러너 스킬 — 차단하면 저장 자체가 막히므로 항상 통과.
_CAPTURE_SKILLS = frozenset({"aisearch", "humansearch", "url", "login",
                             "ai-search", "ai_search"})
# 후보자를 "전진"시키는(제안/등록) 스킬 — 저장 영수증이 선행돼야 한다.
_ADVANCE_SKILLS = frozenset({
    "jdbuilder", "pos-fill", "posfill",
    "saramin-talent-sourcing", "jobkorea-talent-sourcing",
    "linkedin-rps-jd-set-builder", "recruit-post-builder",
})

# 후보자 프로필 URL 패턴(사람인 이력서·잡코리아 이력서·링크드인 recruiter).
_PROFILE_URL_RE = re.compile(
    r"https?://[^\s\"'<>]*?(?:"
    r"hiring\.saramin\.co\.kr/applicant-view[^\s\"'<>]*"
    r"|saramin\.co\.kr/[^\s\"'<>]*?(?:resume|talent)[^\s\"'<>]*"
    r"|jobkorea\.co\.kr/[^\s\"'<>]*?(?:Resume|Person)[^\s\"'<>]*"
    r"|linkedin\.com/talent/profile/[^\s\"'<>]+"
    r")",
    re.IGNORECASE,
)

DEFAULT_ARCHIVE_DB = Path.home() / ".valuehire" / "profile_archives.sqlite3"

_CANON_HINT = (
    "정식 저장 경로: 검색 러너(humansearch/aisearch)로 후보를 방문하면 "
    "capture_owned_browser_evidence 가 profile-mode 로 자동 저장합니다. "
    "수동으로 연 후보는 저장되지 않으므로 러너로 캡처한 뒤 전진하세요(SOT-26 failure_policy)."
)


def extract_profile_url(text: Any) -> str:
    """문자열에서 첫 후보자 프로필 URL 추출. 없으면 빈 문자열."""
    if not isinstance(text, str):
        return ""
    m = _PROFILE_URL_RE.search(text)
    return m.group(0).rstrip(".,);]}") if m else ""


def _tool_input_text(tool_input: Any) -> str:
    if not isinstance(tool_input, Mapping):
        return ""
    parts = []
    for key in ("request_text", "text", "command", "prompt", "url", "profile_url", "args"):
        v = tool_input.get(key)
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, (list, tuple)):
            parts.append(" ".join(str(x) for x in v))
    return " ".join(parts)


def receipt_exists(
    db_path: Path | str,
    *,
    profile_url: str,
    position_id: str = "",
) -> bool:
    """ProfileArchiveStore 영수증 존재 여부. DB 없음/오류는 False(fail-closed는 호출부 몫)."""
    path = Path(db_path)
    if not path.is_file() or not profile_url:
        return False
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        if position_id:
            row = con.execute(
                "SELECT 1 FROM profile_archive_receipts "
                "WHERE profile_url=? AND position_id=? LIMIT 1",
                (profile_url, position_id)).fetchone()
        else:
            row = con.execute(
                "SELECT 1 FROM profile_archive_receipts WHERE profile_url=? LIMIT 1",
                (profile_url,)).fetchone()
        return row is not None
    except sqlite3.Error:
        return False
    finally:
        con.close()


def block_reason(
    tool: str,
    tool_input: Any,
    *,
    has_receipt: Callable[[str, str], bool],
) -> str | None:
    """전진성 작업인데 후보 저장 영수증이 없으면 사유 문자열, 아니면 None.

    has_receipt(profile_url, position_id) -> bool 은 호출부(훅)가 DB 조회로 주입한다.
    """
    if str(tool) != "Skill":
        return None
    if not isinstance(tool_input, Mapping):
        return None
    skill = str(tool_input.get("skill") or "").strip().lower()
    if skill in _CAPTURE_SKILLS or skill not in _ADVANCE_SKILLS:
        return None
    text = _tool_input_text(tool_input)
    profile_url = extract_profile_url(text)
    if not profile_url:
        return None  # 후보 식별자 없음 → 이 게이트 대상 아님(좁은 게이트)
    position_id = str(tool_input.get("position_id") or "").strip()
    if has_receipt(profile_url, position_id):
        return None
    return (
        f"⛔ 차단(profile-archive-first): 이 후보자({profile_url})가 아직 저장되지 않아 "
        f"제안/등록(전진)을 막았습니다. " + _CANON_HINT
    )
