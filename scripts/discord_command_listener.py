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
    # V1(Codex): 공백 2개 치환으론 '봇   정지'(3개)·탭 우회 가능 → 모든 공백을 1개로 정규화
    import re as _re
    low = _re.sub(r"\s+", " ", content.strip().lower())
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


def acquire_single_instance_lock(lock_path: Path, pid: int) -> bool:
    """리스너 단일 실행 보장(V1 Codex: 2개 동시 실행=중복 명령 실행).

    락 파일에 기록된 pid 가 살아 있으면 False(두 번째 실행 거부).
    죽은 pid·빈 락은 회수하고 자기 pid 를 기록한다.
    """
    try:
        if lock_path.exists():
            old = lock_path.read_text().strip()
            if old.isdigit():
                try:
                    os.kill(int(old), 0)  # 살아있음 검사(시그널 미전송)
                    return False
                except (ProcessLookupError, PermissionError, OverflowError):
                    pass  # 죽었거나 무효 — 회수
    except OSError:
        return False
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(pid))
    return True


def save_last_atomic(state_path: Path, last_id: str) -> None:
    """임시파일→os.replace 원자 교체(V1 Codex: 동시 쓰기 반쪽 파일 방지)."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"last_id": last_id}))
    os.replace(tmp, state_path)


def _load_last() -> str:
    if STATE.exists():
        return json.loads(STATE.read_text()).get("last_id", "0")
    return "0"


def _save_last(last_id: str) -> None:
    save_last_atomic(STATE, last_id)


_AGENT_COMMANDS: dict[str, tuple[str, ...]] = {
    "claude": ("claude", "-p"),
    "codex": ("codex", "exec"),
}


def select_agent_and_prompt(content: str) -> tuple[str, str]:
    """DM 원문 → (agent, prompt). 순수 함수(이슈 F, 2026-07-15 사장님 지시).

    'codex:' 접두어(대소문자·앞뒤 공백 무관)일 때만 agent=codex 로 전환하고 접두어를
    벗겨낸 나머지를 프롬프트로 쓴다. 문장 중간의 "codex"/"코덱스" 단어는 오탐 방지를
    위해 무시한다(접두어 위치가 아니면 트리거 안 됨). 접두어가 없으면 agent=claude,
    프롬프트는 원문을 1바이트도 재구성하지 않는다 — 여기가 안전 템플릿(이슈 A/B)과
    반대로 verbatim 이 목적인 지점이다.
    """
    stripped = content.lstrip()
    if stripped[:6].lower() == "codex:":
        return "codex", stripped[6:].strip()
    return "claude", content


def _run_agent(agent: str, prompt: str) -> str:
    cmd = list(_AGENT_COMMANDS[agent]) + [prompt]
    try:
        p = subprocess.run(
            cmd, cwd=str(REPO), capture_output=True,
            text=True, timeout=CLAUDE_TIMEOUT,
        )
        out = (p.stdout or "").strip() or (p.stderr or "").strip() or "(응답 없음)"
        return out
    except subprocess.TimeoutExpired:
        return "⏱️ 시간 초과(20분) — 작업이 길면 터미널에서 이어서 확인 필요"
    except FileNotFoundError:
        return f"❌ {agent} CLI 를 찾을 수 없음"


def _run_claude(prompt: str) -> str:
    return _run_agent("claude", prompt)


LOCK = Path.home() / ".valuehire" / "discord_cmd_bridge.lock"


def main() -> None:
    if not acquire_single_instance_lock(LOCK, os.getpid()):
        print("이미 다른 리스너가 실행 중 — 종료(중복 실행 금지)", flush=True)
        return
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
            cmds, page_last = select_new_commands(list(msgs), last)
            if not cmds:
                # 명령 없는 페이지(타인/봇 메시지)만 포인터 전진
                last = page_last
                _save_last(last)
            for m in cmds:
                content = m["content"].strip()
                if is_kill_command(content):
                    _save_last(m["id"])
                    _send("🛑 명령 다리 정지합니다.")
                    return
                agent, prompt = select_agent_and_prompt(content)
                tag = "" if agent == "claude" else f"({agent})"
                _send(f"⏳ 접수{tag}: {content[:120]} — 실행 중…")
                result = _run_agent(agent, prompt)
                _send(f"✅ 결과:\n{result[:5500]}")
                # V1(Codex): 실행 *완료 후* 저장 — 중간에 죽으면 재실행(유실 금지, at-least-once)
                last = m["id"]
                _save_last(last)
        except Exception as e:  # noqa: BLE001
            print(f"loop error: {e}", flush=True)
            time.sleep(30)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
