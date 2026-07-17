#!/usr/bin/env python3
"""사장님 Discord DM → 영속 작업 큐 접수기.

hermes_v5 봇의 사장님 DM 채널(1512503041448743092)을 폴링해, **사장님이 쓴 새 메시지만**
owner agent 작업으로 등록한다. 모델 실행은 fleet worker만 담당한다.

안전 계약(테스트 D1 강제):
- OWNER_ID(사장님) 메시지만 명령으로 인정 — 봇 자신·타인 무시
- 처리한 메시지 id 는 상태파일에 저장 — 재실행 금지
- "봇 정지"/"stop bot" = 킬 스위치(리스너 종료)
- 수신기는 Claude/Codex subprocess를 직접 실행하지 않고 영속 큐에만 등록
- Discord message id 중복 방지 키로 재시작 후에도 한 번만 등록
- 회신은 1900자 분할(Discord 2000 제한)
사용: nohup python3 scripts/discord_command_listener.py >/tmp/discord_bridge.log 2>&1 &
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.multi_position_sourcing.job_queue import (  # noqa: E402
    JobQueueClient,
    is_valid_machine_id,
    new_owner_agent_job_payload,
)

OWNER_ID = "814353841088757800"
BOT_ID = "1512101118543397056"  # hermes_v5 — 자기 메시지 무시
DM_CHANNEL = "1512503041448743092"
STATE = Path.home() / ".valuehire" / "discord_cmd_state.json"
POLL_SECONDS = 20

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


def select_agent_and_prompt(content: str) -> tuple[str, str]:
    """접두어로 실행기만 선택하고 승인 원문은 1바이트도 재구성하지 않는다."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("빈 Discord 요청")
    stripped = content.lstrip()
    for agent in ("claude", "codex"):
        prefix = agent + ":"
        if stripped[:len(prefix)].lower() == prefix:
            if not stripped[len(prefix):].strip():
                raise ValueError(f"{agent}: 뒤 요청이 비었습니다")
            return agent, content
    return "codex", content


def _is_idempotency_conflict(exc: urllib.error.HTTPError) -> bool:
    if exc.code != 409:
        return False
    try:
        body = json.loads((exc.read() or b"{}").decode("utf-8", errors="replace"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(body, dict):
        return False
    evidence = " ".join(str(body.get(key) or "") for key in ("message", "details", "hint"))
    return body.get("code") == "23505" and "jobs_discord_idempotency_key_uidx" in evidence


def enqueue_owner_message(
    message: dict,
    *,
    queue: JobQueueClient,
    machine: str,
) -> dict[str, object]:
    """Re-authenticate one DM and enqueue it exactly once; never execute a model."""
    author_id = str((message.get("author") or {}).get("id") or "")
    if author_id != OWNER_ID:
        raise PermissionError("owner Discord ID가 아닙니다")
    channel_id = message.get("channel_id")
    if not isinstance(channel_id, str) or channel_id != DM_CHANNEL:
        raise PermissionError("owner DM 채널이 아닙니다")
    raw = message.get("content")
    agent, approved_request = select_agent_and_prompt(raw)
    payload = new_owner_agent_job_payload(
        machine=machine,
        guild_id="@me",
        channel_id=channel_id,
        message_id=str(message.get("id") or ""),
        request_text=approved_request,
        agent=agent,
        requested_by=f"{OWNER_ID}:owner",
        verified_role="owner",
        execution_mode="workspace_write",
    )
    if payload is None:
        raise ValueError("Discord owner agent 작업 계약 위반")
    try:
        row = queue.enqueue(payload)
    except urllib.error.HTTPError as exc:
        if _is_idempotency_conflict(exc):
            return {"status": "duplicate", "job_id": None, "agent": agent}
        raise
    job_id = row.get("id") if isinstance(row, dict) else None
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise ValueError("큐가 유효한 작업 번호를 반환하지 않았습니다")
    return {"status": "queued", "job_id": job_id, "agent": agent}


LOCK = Path.home() / ".valuehire" / "discord_cmd_bridge.lock"


def main(*, queue: JobQueueClient | None = None, machine: str = "") -> None:
    if not acquire_single_instance_lock(LOCK, os.getpid()):
        print("이미 다른 리스너가 실행 중 — 종료(중복 실행 금지)", flush=True)
        return
    selected_machine = machine or (os.environ.get("VALUEHIRE_MACHINE") or "")
    if not is_valid_machine_id(selected_machine):
        raise RuntimeError("VALUEHIRE_MACHINE이 필요합니다")
    job_queue = queue if queue is not None else JobQueueClient()
    last = _load_last()
    # 시작 시 과거 대화 재실행 방지: last=0 이면 현재 최신 id 로 초기화
    if last == "0":
        msgs = _api("GET", f"/channels/{DM_CHANNEL}/messages?limit=1")
        if msgs:
            last = msgs[0]["id"]
        _save_last(last)
    _send("디스코드 작업 접수기 시작 — 이 DM의 새 지시를 영속 대기열에 등록합니다. (\"봇 정지\"로 중단)")
    while True:
        try:
            msgs = _api("GET", f"/channels/{DM_CHANNEL}/messages?after={last}&limit=50")
            cmds, page_last = select_new_commands(list(msgs), last)
            if not cmds:
                # 명령 없는 페이지(타인/봇 메시지)만 포인터 전진
                last = page_last
                _save_last(last)
            for m in cmds:
                raw = m["content"]
                content = raw.strip()  # 표시·킬스위치 판정용 — 프롬프트는 raw 그대로(verbatim, V1 반증 수용)
                if is_kill_command(content):
                    _save_last(m["id"])
                    _send("🛑 명령 다리 정지합니다.")
                    return
                result = enqueue_owner_message(
                    m, queue=job_queue, machine=selected_machine)
                last = m["id"]
                _save_last(last)
                if result["status"] == "duplicate":
                    _send(f"이미 접수({result['agent']})된 Discord 작업입니다.")
                else:
                    _send(f"접수({result['agent']}) 완료 — 작업 #{result['job_id']}")
        except Exception as e:  # noqa: BLE001
            print(f"loop error: {e}", flush=True)
            time.sleep(30)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
