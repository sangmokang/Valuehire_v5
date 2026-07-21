"""guards/discord-bot-login-gate.py — H2: 로그인 영수증 없이 검색 스킬 발동 차단 (AC-3, G4 2층).

fleet 잡 컨텍스트(env VH_BUSY_TASK)에서 검색 스킬(humansearch/aisearch/url)을 발동하려면
로그인 영수증(artifacts/portal_session_status_latest.json)이 존재·신선(24h)해야 한다.
1층은 fleet_worker.login_gate_block_reason(잡 시작 자체를 paused_for_human) — 이 훅은
같은 계약의 2층이다. 채널별 세부 판정은 1층이 담당하고, 이 훅은 "영수증 존재+신선+
전체 ready"만 본다(순수·보수적).
"""
import datetime
import json
import os
import pathlib

NAME = "discord-bot-login-gate"

_SEARCH_SKILLS = frozenset({"humansearch", "aisearch", "url"})
_RECEIPT_RELPATH = "artifacts/portal_session_status_latest.json"
_MAX_AGE_SECONDS = 86400  # fleet_heartbeat.PORTAL_STATUS_MAX_AGE_SECONDS 와 동일 기준


def _in_fleet_job() -> bool:
    return bool((os.environ.get("VH_BUSY_TASK") or "").strip())


def _repo_root() -> pathlib.Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if root:
        return pathlib.Path(root)
    return pathlib.Path(__file__).resolve().parents[3]


def _receipt_ok() -> bool:
    try:
        payload = json.loads((_repo_root() / _RECEIPT_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict) or payload.get("ready") is not True:
        return False
    raw = payload.get("generated_at")
    if not isinstance(raw, str) or not raw.strip():
        return False
    try:
        dt = datetime.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        return False
    age = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds()
    return 0 <= age <= _MAX_AGE_SECONDS


def check(tool, tool_input):
    if tool != "Skill" or not _in_fleet_job():
        return None
    skill = str((tool_input or {}).get("skill") or "").strip()
    if skill not in _SEARCH_SKILLS:
        return None
    if _receipt_ok():
        return None
    return (
        "⛔ 차단(discord-bot-login-gate): 로그인 영수증"
        f"({_RECEIPT_RELPATH})이 없거나 만료/미완료 상태입니다 — 검색 스킬 전에 "
        "/login 스킬로 포털 로그인을 먼저 완료해 영수증을 갱신하세요(G4, goal §7)."
    )
