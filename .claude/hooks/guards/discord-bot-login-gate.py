"""guards/discord-bot-login-gate.py — H2: 로그인 영수증 없이 검색 스킬 발동 차단 (AC-3, G4 2층).

#639 login-first: 영수증 정본이 채널별 파일(~/.valuehire/login_receipts/<channel>.json,
login_barrier 계약)로 승격됐다. fleet 잡 컨텍스트(env VH_BUSY_TASK)에서 검색 스킬
(humansearch/aisearch/url)을 발동하려면 필요한 채널 영수증이 존재·신선(1800s)·
AUTHENTICATED 여야 한다. 1층은 fleet_worker + login_barrier.job_block_reason —
이 훅은 같은 계약의 2층(보수적 요약 검사)이다. "LOGIN_BARRIER=PASS" 같은 호출자
문자열은 판정에 쓰지 않는다(파일만 본다).
"""
import datetime
import json
import os
import pathlib

NAME = "discord-bot-login-gate"

_SEARCH_SKILLS = frozenset({"humansearch", "aisearch", "url"})
_MAX_AGE_SECONDS = 1800  # login_barrier.RECEIPT_MAX_AGE_SECONDS 와 동일 기준
_REQUIRED = {
    "url": ("linkedin_rps",),
    "humansearch": ("saramin", "jobkorea"),
    "aisearch": ("saramin", "jobkorea"),
}


def _in_fleet_job() -> bool:
    return bool((os.environ.get("VH_BUSY_TASK") or "").strip())


def _receipt_dir() -> pathlib.Path:
    override = (os.environ.get("VH_LOGIN_RECEIPT_DIR") or "").strip()
    if override:
        return pathlib.Path(override)
    return pathlib.Path.home() / ".valuehire" / "login_receipts"


def _channel_receipt_ok(channel: str) -> bool:
    path = _receipt_dir() / f"{channel}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("state") != "AUTHENTICATED" or payload.get("ready") is not True:
        return False
    if str(payload.get("channel") or "") != channel:
        return False
    machine = (os.environ.get("VALUEHIRE_MACHINE") or "").strip()
    if machine and str(payload.get("host") or "") != machine:
        return False
    raw = payload.get("last_verified_at")
    if not isinstance(raw, str) or not raw.strip():
        return False
    try:
        dt = datetime.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        return False
    age = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds()
    return -60 <= age <= _MAX_AGE_SECONDS


def check(tool, tool_input):
    if tool != "Skill" or not _in_fleet_job():
        return None
    skill = str((tool_input or {}).get("skill") or "").strip()
    if skill not in _SEARCH_SKILLS:
        return None
    missing = [ch for ch in _REQUIRED[skill] if not _channel_receipt_ok(ch)]
    if not missing:
        return None
    return (
        "⛔ 차단(discord-bot-login-gate): 로그인 영수증(~/.valuehire/login_receipts/"
        f"<channel>.json)이 없거나 만료/미인증입니다 — 부족 채널: {', '.join(missing)}. "
        "검색 스킬 전에 정식 경로(python3 -m tools.multi_position_sourcing.session_guard "
        "human-auth --site <채널>)로 로그인 영수증을 먼저 갱신하세요(G4 2층, #639)."
    )
