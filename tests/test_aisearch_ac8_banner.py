"""AC-8 — 자동화 조작 중 빨간 띠 오버레이 크롬 익스텐션 (신규) 계약 테스트.

goal 문서: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-8 / D9.

계약(기계 단언):
- apps/aisearch/extension/manifest.json — Manifest V3, content_scripts 매치 패턴에
  saramin/jobkorea/linkedin 포함, content.js 등록.
- apps/aisearch/extension/content.js — CustomEvent("valuehire:automation") 수신,
  detail.active true 면 빨간 띠 배너 생성, false 면 제거.
- apps/aisearch/core/banner.py — dispatch 용 JS 스니펫 문자열 생성(브라우저 호출 없음).
  스니펫은 올바른 이벤트명과 JSON payload(active/task)를 담는다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

EXT_DIR = REPO / "apps" / "aisearch" / "extension"
EVENT_NAME = "valuehire:automation"


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------

def _load_manifest() -> dict:
    manifest_path = EXT_DIR / "manifest.json"
    assert manifest_path.is_file(), f"manifest.json 없음: {manifest_path}"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def test_manifest_is_v3_with_name_and_version() -> None:
    manifest = _load_manifest()
    assert manifest["manifest_version"] == 3
    assert isinstance(manifest.get("name"), str) and manifest["name"].strip()
    assert isinstance(manifest.get("version"), str) and manifest["version"].strip()


def test_manifest_content_scripts_cover_three_portals() -> None:
    manifest = _load_manifest()
    scripts = manifest.get("content_scripts")
    assert isinstance(scripts, list) and scripts, "content_scripts 비어 있음"

    all_matches = "\n".join(
        pattern for entry in scripts for pattern in entry.get("matches", [])
    )
    for portal in ("saramin", "jobkorea", "linkedin"):
        assert portal in all_matches, f"{portal} 매치 패턴 누락: {all_matches!r}"

    all_js = [js for entry in scripts for js in entry.get("js", [])]
    assert "content.js" in all_js, f"content.js 미등록: {all_js!r}"


def test_manifest_content_script_files_exist() -> None:
    manifest = _load_manifest()
    for entry in manifest["content_scripts"]:
        for js in entry.get("js", []):
            assert (EXT_DIR / js).is_file(), f"content_scripts 파일 없음: {js}"


# ---------------------------------------------------------------------------
# content.js (계약 수준 문자열/구조 검사)
# ---------------------------------------------------------------------------

def _content_js() -> str:
    path = EXT_DIR / "content.js"
    assert path.is_file(), f"content.js 없음: {path}"
    return path.read_text(encoding="utf-8")


def test_content_js_listens_for_automation_event() -> None:
    src = _content_js()
    assert EVENT_NAME in src, f"이벤트명 {EVENT_NAME!r} 없음"
    assert re.search(
        r"addEventListener\(\s*['\"]" + re.escape(EVENT_NAME) + r"['\"]", src
    ), "valuehire:automation addEventListener 등록 없음"


def test_content_js_creates_and_removes_banner() -> None:
    src = _content_js()
    # 생성: 요소 생성 + 고정 상단 빨간 띠 스타일.
    assert "createElement" in src, "배너 요소 생성(createElement) 없음"
    assert re.search(r"position\s*:?\s*['\"]?fixed", src), "position:fixed 없음"
    # 제거: detail.active false 경로에서 remove.
    assert re.search(r"\.remove\s*\(\s*\)", src), "배너 제거(.remove()) 없음"
    # active 분기 존재.
    assert "active" in src, "detail.active 분기 없음"
    # 사장님 표시 문구(자동화 안내).
    assert "자동화" in src, "배너 안내 문구(자동화) 없음"


def test_content_js_cancels_pending_attach_on_remove() -> None:
    """V1 결함 #1 — DOMContentLoaded 전에 표시→제거 신호가 오면,
    제거 시 예약된 부착(DOMContentLoaded 리스너)을 반드시 취소해야 한다.
    (취소가 없으면 문서 준비 후 배너가 다시 나타나는 경쟁 조건.)
    """
    src = _content_js()
    # 예약 취소: DOMContentLoaded 리스너 해제 코드가 존재해야 한다.
    assert re.search(
        r"removeEventListener\(\s*['\"]DOMContentLoaded['\"]", src
    ), "제거 경로에서 예약된 DOMContentLoaded 부착을 취소(removeEventListener)하지 않음"


def test_content_js_tracks_pending_attach_for_latest_state_wins() -> None:
    """V1 결함 #1 — 최신 신호가 우선하도록 예약된 부착을 상태로 추적해야 한다.

    구조 계약: 예약된 부착 핸들러를 공유 변수(pendingAttach)에 저장하고,
    removeBanner 경로에서 그 변수를 참조해 취소·초기화해야 한다.
    """
    src = _content_js()
    assert "pendingAttach" in src, "예약 부착 추적 상태(pendingAttach) 없음"

    # removeBanner 함수 본문 안에서 pendingAttach 취소가 일어나야 한다.
    match = re.search(
        r"function\s+removeBanner\s*\(\s*\)\s*\{(.*?)\n  \}", src, re.DOTALL
    )
    assert match, "removeBanner 함수 본문 추출 실패"
    body = match.group(1)
    assert "pendingAttach" in body, "removeBanner 가 예약된 부착을 취소하지 않음"
    assert "removeEventListener" in body, (
        "removeBanner 가 DOMContentLoaded 리스너를 해제하지 않음"
    )


# ---------------------------------------------------------------------------
# banner.py (dispatch 스니펫 생성 — 브라우저 호출 금지)
# ---------------------------------------------------------------------------

def test_banner_module_exports_event_name() -> None:
    from apps.aisearch.core import banner

    assert banner.EVENT_NAME == EVENT_NAME


def _extract_detail(snippet: str) -> dict:
    match = re.search(r"detail\s*:\s*(\{.*\})\s*\}\s*\)\s*\)", snippet, re.DOTALL)
    assert match, f"스니펫에서 detail JSON 추출 실패: {snippet!r}"
    return json.loads(match.group(1))


def test_dispatch_snippet_active_true_carries_task() -> None:
    from apps.aisearch.core.banner import build_dispatch_snippet

    snippet = build_dispatch_snippet(active=True, task="사람인 서치 3페이지")
    assert isinstance(snippet, str)
    assert "CustomEvent" in snippet
    assert EVENT_NAME in snippet
    detail = _extract_detail(snippet)
    assert detail == {"active": True, "task": "사람인 서치 3페이지"}


def test_dispatch_snippet_active_false_clears() -> None:
    from apps.aisearch.core.banner import build_dispatch_snippet

    snippet = build_dispatch_snippet(active=False, task="")
    detail = _extract_detail(snippet)
    assert detail["active"] is False


def test_dispatch_snippet_escapes_quotes_in_task() -> None:
    from apps.aisearch.core.banner import build_dispatch_snippet

    tricky = 'linkedin "RPS" 서치 </script>'
    snippet = build_dispatch_snippet(active=True, task=tricky)
    detail = _extract_detail(snippet)
    assert detail["task"] == tricky
    # </script> 원문이 그대로 남으면 인라인 주입 시 위험 — 이스케이프 강제.
    assert "</script>" not in snippet


def test_dispatch_snippet_rejects_non_bool_active() -> None:
    """V1 결함 #2 — active="false"(문자열)를 True 로 조용히 변환하면 안 된다.

    active 는 bool 만 허용, 그 외 타입은 fail-fast 예외.
    """
    import pytest

    from apps.aisearch.core.banner import build_dispatch_snippet

    for bad_active in ("false", "true", 1, 0, None, [], object()):
        with pytest.raises(TypeError):
            build_dispatch_snippet(active=bad_active, task="사람인 서치")


def test_dispatch_snippet_rejects_non_str_task() -> None:
    """V1 결함 #2 — task=None 을 "None" 문자열로 조용히 변환하면 안 된다.

    task 는 str 만 허용, 그 외 타입은 fail-fast 예외.
    """
    import pytest

    from apps.aisearch.core.banner import build_dispatch_snippet

    for bad_task in (None, 123, ["작업"], {"task": "x"}, object()):
        with pytest.raises(TypeError):
            build_dispatch_snippet(active=True, task=bad_task)


def test_dispatch_snippet_active_true_requires_nonempty_task() -> None:
    """V1 결함 #2 — 표시(active=True) 신호의 task 는 비어있지 않은 str 만 허용.

    (제거 신호 active=False 는 payload 문구가 필요 없으므로 빈 문자열 허용 —
    기존 계약 test_dispatch_snippet_active_false_clears 유지.)
    """
    import pytest

    from apps.aisearch.core.banner import build_dispatch_snippet

    for empty_task in ("", "   ", "\n\t"):
        with pytest.raises(ValueError):
            build_dispatch_snippet(active=True, task=empty_task)


def test_banner_module_does_not_touch_browser() -> None:
    src = (REPO / "apps" / "aisearch" / "core" / "banner.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("subprocess", "websocket", "requests", "urllib", "socket"):
        assert forbidden not in src, f"banner.py 는 브라우저/네트워크 호출 금지: {forbidden}"
