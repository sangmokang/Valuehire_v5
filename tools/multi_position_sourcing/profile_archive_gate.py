"""profile_archive_gate — 후보자 저장 강제 게이트(순수 로직 + 영수증 조회).

SOT-26 browser_evidence_capture.failure_policy: 영수증 없이 score/advance/complete 금지.
이 모듈은 그 정책을 harness 훅(2차 방어)이 쓰도록 순수 함수로 노출한다.
전진성 작업(제안 발송·후보 등록·pos-fill)만 좁게 차단하고, 검색·로그인·읽기는 통과한다.

V1 적대검증(2026-07-26) 봉인: 전 발송/등록 스킬 포함 · tool_input 전 문자열 재귀 스캔 ·
percent-decode · 다중 URL 전수 검사 · URL canonical 정규화(쿼리·슬래시 무시).
"""
from __future__ import annotations

import re
import sqlite3
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

# 저장(캡처)을 스스로 수행하는 러너 스킬 — 차단하면 저장 자체가 막히므로 항상 통과.
_CAPTURE_SKILLS = frozenset({"aisearch", "humansearch", "url", "login",
                             "ai-search", "ai_search"})
# 특정 후보자를 "전진"(제안 발송·등록·모달 채움)시키는 스킬 — 저장 영수증이 선행돼야 한다.
# (.claude/skills 실측: 자동발송 clickup-position-talent-matching 포함)
_ADVANCE_SKILLS = frozenset({
    "jdbuilder", "pos-fill", "posfill",
    "saramin-talent-sourcing", "jobkorea-talent-sourcing",
    "linkedin-rps-jd-set-builder", "recruit-post-builder",
    "clickup-position-talent-matching",
    "chatgpt-position-sourcing", "chatgpt-multi-tab-sourcing",
    "codeit-talent-archive-search", "aisearch-codeit",
})

# 후보자 프로필 URL 패턴 — browser_evidence._canonical* 가 인정하는 실 형식을 단일 출처로 반영:
#   saramin: applicant-view / talent-pool resume / 이력서 상세(쿼리 id 포함)
#   jobkorea: /Corp/Person/*, /Person/*, /SearchFirm/*, /Recruit/Co_Read?rNo=
#   linkedin: /talent/profile/<id>, /talent/hire/.../profile/<id>
_PROFILE_URL_RE = re.compile(
    r"https?://[^\s\"'<>()]*?(?:"
    r"saramin\.co\.kr/[^\s\"'<>()]*?(?:applicant-view|resume|talent)[^\s\"'<>()]*"
    r"|jobkorea\.co\.kr/[^\s\"'<>()]*?(?:corp/person|/person/|searchfirm|co_read|resume)[^\s\"'<>()]*"
    r"|linkedin\.com/talent/[^\s\"'<>()]*?profile/[^\s\"'<>()]+"
    r")",
    re.IGNORECASE,
)

DEFAULT_ARCHIVE_DB = Path.home() / ".valuehire" / "profile_archives.sqlite3"

_CANON_HINT = (
    "정식 저장 경로: 검색 러너(humansearch/aisearch)로 후보를 방문하면 "
    "capture_owned_browser_evidence 가 profile-mode 로 자동 저장합니다. "
    "수동으로 연 후보는 저장되지 않으므로 러너로 캡처한 뒤 전진하세요(SOT-26 failure_policy)."
)


def _percent_decode(text: str) -> str:
    """최대 3회 percent-decode(전체 인코딩 우회 봉인). 실패해도 원문 유지."""
    seen = text
    for _ in range(3):
        try:
            nxt = urllib.parse.unquote(seen)
        except Exception:
            break
        if nxt == seen:
            break
        seen = nxt
    return seen


def _iter_strings(value: Any) -> Iterator[str]:
    """tool_input 안의 모든 문자열을 재귀적으로 방출(중첩 dict/list 포함)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _iter_strings(v)


def canonicalize_url(url: str) -> str:
    """쿼리·프래그먼트 제거 + host 소문자 + 경로 끝 슬래시 제거(영수증 대조 정규화)."""
    try:
        p = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip().rstrip("/")
    path = p.path.rstrip("/")
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), path, "", ""))


def extract_profile_url(text: Any) -> str:
    """문자열에서 첫 후보자 프로필 URL(원문형). 없으면 빈 문자열."""
    urls = extract_profile_urls(text)
    return urls[0] if urls else ""


def extract_profile_urls(text: Any) -> list[str]:
    """문자열(퍼센트 디코드 포함)에서 모든 후보자 프로필 URL을 순서·중복제거로 반환."""
    if not isinstance(text, str):
        return []
    out: list[str] = []
    for candidate in (text, _percent_decode(text)):
        for m in _PROFILE_URL_RE.finditer(candidate):
            u = m.group(0).rstrip(".,);]}")
            if u not in out:
                out.append(u)
    return out


def receipt_exists(
    db_path: Path | str,
    *,
    profile_url: str,
    position_id: str = "",
) -> bool:
    """ProfileArchiveStore 영수증 존재 여부(URL은 canonical 대조). DB 없음/오류는 False."""
    path = Path(db_path)
    if not path.is_file() or not profile_url:
        return False
    target = canonicalize_url(profile_url)
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        if position_id:
            rows = con.execute(
                "SELECT profile_url FROM profile_archive_receipts WHERE position_id=?",
                (position_id,)).fetchall()
        else:
            rows = con.execute(
                "SELECT profile_url FROM profile_archive_receipts").fetchall()
        return any(canonicalize_url(str(r[0])) == target for r in rows)
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
    """전진성 작업인데 후보 저장 영수증 없는 URL이 하나라도 있으면 사유, 아니면 None."""
    if str(tool) != "Skill" or not isinstance(tool_input, Mapping):
        return None
    skill = str(tool_input.get("skill") or "").strip().lower()
    if skill in _CAPTURE_SKILLS or skill not in _ADVANCE_SKILLS:
        return None
    position_id = str(tool_input.get("position_id") or "").strip()
    seen: list[str] = []
    for text in _iter_strings(tool_input):
        for url in extract_profile_urls(text):
            if url not in seen:
                seen.append(url)
    if not seen:
        return None  # 후보 식별자 없음 → 이 게이트 대상 아님(좁은 게이트)
    unsaved = [u for u in seen if not has_receipt(u, position_id)]
    if not unsaved:
        return None
    return (
        f"⛔ 차단(profile-archive-first): 미저장 후보 {len(unsaved)}건이 있어 "
        f"제안/등록(전진)을 막았습니다 — {unsaved[0]}"
        + (f" 외 {len(unsaved) - 1}건" if len(unsaved) > 1 else "")
        + ". " + _CANON_HINT
    )
