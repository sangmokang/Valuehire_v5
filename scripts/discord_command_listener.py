#!/usr/bin/env python3
"""사장님 Discord DM → Claude 명령 다리 (2026-07-03 사장님 지시).

hermes_v5 봇의 사장님 DM 채널(1512503041448743092)을 폴링해, **사장님이 쓴 새 메시지만**
`claude -p`(헤드리스, 이 레포 루트)로 실행하고 결과를 DM 으로 회신한다.

안전 계약(테스트 D1 강제):
- OWNER_ID(사장님) 메시지만 명령으로 인정 — 봇 자신·타인 무시
- 처리한 메시지 id 는 상태파일에 저장 — 재실행 금지
- "봇 정지"/"stop bot" = 킬 스위치(리스너 종료)
- 명령은 셸이 아니라 Claude 프롬프트로만 전달(임의 셸 실행 아님, Claude 권한 체계 통과)
- 회신은 1900자 분할(Discord 2000 제한)
사용: nohup python3 scripts/discord_command_listener.py >/tmp/discord_bridge.log 2>&1 &
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OWNER_ID = "814353841088757800"
BOT_ID = "1512101118543397056"  # hermes_v5 — 자기 메시지 무시
DM_CHANNEL = "1512503041448743092"
STATE = Path.home() / ".valuehire" / "discord_cmd_state.json"
POLL_SECONDS = 20
CLAUDE_TIMEOUT = 1200  # 20분

_KILL_PHRASES = ("봇 정지", "봇정지", "stop bot", "stopbot")


def is_kill_command(content: str) -> bool:
    low = content.strip().lower().replace("  ", " ")
    return any(k in low for k in _KILL_PHRASES) and not low.startswith("정지하지")


def select_new_commands(messages: list[dict], last_id: str) -> tuple[list[dict], str]:
    """API 메시지 목록 → (사장님 새 명령들 오름차순, 새 last_id). 순수 함수."""
    new_last = last_id
    cmds: list[dict] = []
    for m in sorted(messages, key=lambda x: int(x["id"])):
        mid = m.get("id", "0")
        if int(mid) <= int(last_id):
            continue
        new_last = mid
        author = (m.get("author") or {}).get("id", "")
        if author != OWNER_ID:
            continue
        if not (m.get("content") or "").strip():
            continue
        cmds.append(m)
    return cmds, new_last


def chunk_reply(text: str, limit: int = 1900) -> list[str]:
    return [text[i:i + limit] for i in range(0, len(text), limit)] or [""]


# ── I/O (테스트 비대상 — 라이브 검증) ──
def _token() -> str:
    # .env.local 은 비추적 — worktree 에는 없음. 본 저장소(worktrees/<n>/../..)까지 폴백.
    for base in (REPO, REPO.parent.parent):
        env = base / ".env.local"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("DISCORD_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip()
    return os.environ["DISCORD_BOT_TOKEN"]


def _api(method: str, path: str, payload: dict | None = None) -> list | dict:
    req = urllib.request.Request(
        f"https://discord.com/api/v10{path}",
        data=json.dumps(payload).encode() if payload else None,
        method=method,
        headers={"Authorization": f"Bot {_token()}", "Content-Type": "application/json",
                 "User-Agent": "ValuehireBridge/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read().decode()
        return json.loads(body) if body else {}


def _send(text: str) -> None:
    for c in chunk_reply(text):
        _api("POST", f"/channels/{DM_CHANNEL}/messages", {"content": c})
        time.sleep(0.6)


def _load_last() -> str:
    if STATE.exists():
        return json.loads(STATE.read_text()).get("last_id", "0")
    return "0"


def _save_last(last_id: str) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"last_id": last_id}))


def _run_claude(prompt: str) -> str:
    try:
        p = subprocess.run(
            ["claude", "-p", prompt], cwd=str(REPO), capture_output=True,
            text=True, timeout=CLAUDE_TIMEOUT,
        )
        out = (p.stdout or "").strip() or (p.stderr or "").strip() or "(응답 없음)"
        return out
    except subprocess.TimeoutExpired:
        return "⏱️ 시간 초과(20분) — 작업이 길면 터미널에서 이어서 확인 필요"
    except FileNotFoundError:
        return "❌ claude CLI 를 찾을 수 없음"


def main() -> None:
    last = _load_last()
    # 시작 시 과거 대화 재실행 방지: last=0 이면 현재 최신 id 로 초기화
    if last == "0":
        msgs = _api("GET", f"/channels/{DM_CHANNEL}/messages?limit=1")
        if msgs:
            last = msgs[0]["id"]
        _save_last(last)
    _send("🤖 디스코드 명령 다리 시작 — 이 DM에 지시를 쓰시면 Claude가 실행하고 회신합니다. (\"봇 정지\"로 중단)")
    while True:
        try:
            msgs = _api("GET", f"/channels/{DM_CHANNEL}/messages?after={last}&limit=50")
            cmds, last = select_new_commands(list(msgs), last)
            _save_last(last)
            for m in cmds:
                content = m["content"].strip()
                if is_kill_command(content):
                    _send("🛑 명령 다리 정지합니다.")
                    return
                _send(f"⏳ 접수: {content[:120]} — 실행 중…")
                result = _run_claude(content)
                _send(f"✅ 결과:\n{result[:5500]}")
        except Exception as e:  # noqa: BLE001
            print(f"loop error: {e}", flush=True)
            time.sleep(30)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
