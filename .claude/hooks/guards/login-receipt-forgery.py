"""guards/login-receipt-forgery.py — 로그인 영수증 위조 차단 (#639, V2 실증 우회 봉인).

로그인 영수증(~/.valuehire/login_receipts)은 session_guard human-auth 성공만 기록한다.
shell 리다이렉트·cp/mv/ln·sed -i·python -c, 그리고 Write/Edit 계열 파일 도구로
이 경로에 쓰는 것은 전부 위조로 간주해 차단한다. 읽기(cat/ls/rg/grep)는 통과.
fleet 잡 컨텍스트 여부와 무관하게 항상 적용(위조는 어디서든 위조다).
"""
import re

NAME = "login-receipt-forgery"

_RECEIPT_PATH = re.compile(r"login_receipts", re.I)
_WRITE_TO_RECEIPT = re.compile(
    r">\s*\S*login_receipts"
    r"|\btee\b(?:\s+-\S+)*\s+\S*login_receipts", re.I)
_MUTATORS = re.compile(
    r"(?:^|[\n;&|`]|\$\()\s*(?:sudo\s+)?(cp|mv|ln|rsync|install)\b", re.I)
_SED_I = re.compile(r"\bsed\b(?:\s+\S+)*?\s-i\b|\bsed\s+-i\b", re.I)
_PY_C = re.compile(r"\bpython3?\s+-c\b", re.I)
_FILE_WRITE_SUFFIXES = ("__create_text_file", "__replace_content", "__replace_in_files")
_FILE_WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")

_HINT = ("영수증은 정식 러너(python3 -m tools.multi_position_sourcing.session_guard "
         "human-auth --site <채널>)만 기록합니다(#639).")


def check(tool, tool_input):
    name = str(tool)
    if name in _FILE_WRITE_TOOLS or name.endswith(_FILE_WRITE_SUFFIXES):
        target = ""
        if isinstance(tool_input, dict):
            target = str(tool_input.get("file_path")
                         or tool_input.get("notebook_path")
                         or tool_input.get("relative_path") or "")
        if _RECEIPT_PATH.search(target):
            return ("⛔ 차단(login-receipt-forgery): 파일 쓰기 도구로 로그인 영수증 경로를 "
                    "직접 기록하는 것은 위조입니다. " + _HINT)
    cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if isinstance(cmd, (list, tuple)):
        cmd = " ".join(str(c) for c in cmd)
    if not cmd or not _RECEIPT_PATH.search(cmd):
        return None
    if (_WRITE_TO_RECEIPT.search(cmd) or _MUTATORS.search(cmd)
            or _SED_I.search(cmd) or _PY_C.search(cmd)):
        return ("⛔ 차단(login-receipt-forgery): 로그인 영수증(login_receipts) 경로에 대한 "
                "shell 쓰기/이동/링크/수정은 위조입니다. 'LOGIN_BARRIER=PASS' 문자열을 적어도 "
                "기계 검증은 통과되지 않습니다. " + _HINT)
    return None
