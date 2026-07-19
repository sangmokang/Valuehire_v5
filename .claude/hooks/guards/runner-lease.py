"""runner-lease 가드 — 리스 없는 직접 브라우저 타이핑/클릭/JS 도구 호출 차단 (SOT-30 §4.5 R3 ③).

"판단은 모델, 실행은 코드": 손 조작(로그인·검색어 입력·발송·창 조작)은 레포 러너가 한다.
러너가 발급한 리스(.claude/runner-lease.json)가 유효할 때만 브라우저 조작 도구를 허용.
읽기 도구(read_page/snapshot/screenshot 등)와 비브라우저 도구는 항상 통과.

판정 본체 = tools/harness/runner_lease.py (한 곳) — 이 가드는 호출만 한다.
정직 표기: Bash 직접 CDP 등 우회는 존재한다. 목적은 주요 경로 좁히기(SOT-30 R3).
모듈 자체가 없으면 fail-open(strict-gate가 모듈 존재를 별도로 못박음).
"""
import importlib.util
import os
import pathlib

NAME = "runner-lease"

# 차단 대상: 타이핑·클릭·폼·JS·업로드·드래그 등 "손 조작" 계열 전체 도구명
_BLOCK_TOOLS = frozenset({
    "mcp__claude-in-chrome__form_input",
    "mcp__claude-in-chrome__javascript_tool",
    "mcp__claude-in-chrome__file_upload",
    "mcp__claude-in-chrome__shortcuts_execute",
    "mcp__claude-in-chrome__browser_batch",
    "mcp__playwright__browser_type",
    "mcp__playwright__browser_click",
    "mcp__playwright__browser_fill_form",
    "mcp__playwright__browser_press_key",
    "mcp__playwright__browser_select_option",
    "mcp__playwright__browser_drag",
    "mcp__playwright__browser_drop",
    "mcp__playwright__browser_evaluate",
    "mcp__playwright__browser_run_code_unsafe",
    "mcp__playwright__browser_file_upload",
    "mcp__playwright__browser_handle_dialog",
    # 창 파괴(원장 4행 '로그인창 임의 닫기') — V1 반례(2026-07-19) 반영.
    "mcp__playwright__browser_close",
    "mcp__claude-in-chrome__tabs_close_mcp",
})
# browser_tabs 는 action 별 판정 — close(창 파괴)만 손 조작, list/select 등 조회는 통과.
_TABS_TOOL = "mcp__playwright__browser_tabs"
# computer 는 action 별 판정 — 관찰 계열만 허용, 그 외 전부(타이핑·클릭·스크롤·미지 액션) 차단
_COMPUTER_TOOL = "mcp__claude-in-chrome__computer"
_COMPUTER_SAFE_ACTIONS = frozenset({"screenshot", "cursor_position", "zoom"})


def _repo_root():
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if root:
        return pathlib.Path(root)
    # fallback: 이 가드 파일 위치(.claude/hooks/guards/) 기준 레포 루트
    return pathlib.Path(__file__).resolve().parents[3]


def _load_lease_module(root):
    for base in (root, pathlib.Path(__file__).resolve().parents[3]):
        mod_path = pathlib.Path(base) / "tools" / "harness" / "runner_lease.py"
        if mod_path.is_file():
            spec = importlib.util.spec_from_file_location("runner_lease", mod_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def _is_hand_operation(tool, tool_input):
    if tool in _BLOCK_TOOLS:
        return True
    if tool == _COMPUTER_TOOL:
        action = str((tool_input or {}).get("action", "")).lower()
        return action not in _COMPUTER_SAFE_ACTIONS
    if tool == _TABS_TOOL:
        return str((tool_input or {}).get("action", "")).lower() == "close"
    return False


def check(tool, tool_input):
    if not _is_hand_operation(tool, tool_input):
        return None
    root = _repo_root()
    mod = _load_lease_module(root)
    if mod is None:
        return None  # 판정 모듈 부재 — fail-open(존재는 strict-gate가 검사)
    ok, reason = mod.check_lease(root)
    if ok:
        return None
    return (
        f"⛔ 차단(runner-lease, SOT-30 R3): 직접 브라우저 손 조작 도구 '{tool}' — {reason}. "
        "손 조작(로그인·검색어 입력·발송·창 조작)은 레포 정식 러너가 수행합니다. "
        "정식 러너를 실행하세요(러너가 리스를 발급·해제). 러너가 fail-fast했다면 "
        "같은 조작을 손으로 때우지 말고 셀렉터 사전을 수리해 러너로 재시도하세요. "
        "읽기(read_page/snapshot/screenshot)는 리스 없이 허용됩니다."
    )
