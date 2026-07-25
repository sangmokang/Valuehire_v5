"""guards/profile-archive-first.py — 후보자 저장 강제(SOT-26 failure_policy 2층 훅).

전진성 작업(제안 발송·후보 등록·pos-fill)을 발동하는데 그 후보자의 ProfileArchiveStore
영수증(~/.valuehire/profile_archives.sqlite3)이 없으면 차단한다. 1층은 러너 코드
(browser_evidence capture-first)이고, 이 훅은 우회·수동 경로를 막는 2층이다.
검색·로그인·읽기는 통과(그 러너가 저장을 수행).
"""
import os
import sys

# repo tools 를 import 경로에 넣어 순수 게이트를 재사용(디스패처 cwd = repo root).
_REPO = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

NAME = "profile-archive-first"


def _archive_db():
    override = (os.environ.get("VH_PROFILE_ARCHIVE_DB") or "").strip()
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".valuehire", "profile_archives.sqlite3")


def check(tool, tool_input):
    try:
        from tools.multi_position_sourcing import profile_archive_gate as pag
    except Exception:
        return None  # 게이트 모듈 로드 실패 = fail-open(디스패처 계약)
    db = _archive_db()
    return pag.block_reason(
        tool, tool_input,
        has_receipt=lambda url, pos: pag.receipt_exists(db, profile_url=url, position_id=pos),
    )
