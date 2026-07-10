"""함대 heartbeat + watchdog (2026-07-11, 단계 G).

설계 근거: docs/prompts/fleet-control-sequential-prompts-2026-07-11.md §프롬프트 G.
- 워커가 1분마다 machine_heartbeats 에 심장박동을 남긴다(record_heartbeat RPC).
- watchdog(맥미니 상주)이 stale 머신(마지막 beat 5분 초과 또는 행 없음)을 OPS_HEALTH 로 경보.
- 중복 경보 30분 억제. webhook/notify 실패는 fail-soft(watchdog 은 죽지 않는다).
PR#66 이 못 잡는 "죽었는데 아무도 모름"을 막는 층.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .job_queue import FLEET_MACHINES

REPO = Path(__file__).resolve().parents[2]

STALE_SECONDS = 300      # 5분 무응답 → stale
ALERT_SUPPRESS_SECONDS = 1800  # 30분 중복 경보 억제


def heartbeat_payload(machine: Any, *, worker_pid: int, now_iso: str) -> dict[str, Any]:
    if machine not in FLEET_MACHINES:
        raise ValueError(f"unknown machine: {machine!r}")
    return {"machine": machine, "beat_at": now_iso, "worker_pid": int(worker_pid)}


def stale_machines(
    rows: Sequence[Mapping[str, Any]],
    *,
    now_epoch: int,
    expected: Sequence[str] = FLEET_MACHINES,
) -> list[str]:
    """마지막 beat 가 STALE_SECONDS 초과인 머신 + 아예 행이 없는 expected 머신.

    입력 rows: [{"machine": str, "beat_at_epoch": int}, ...]
    반환: stale 머신 목록(expected 순서 유지).
    """
    latest: dict[str, int] = {}
    for r in rows:
        m = r.get("machine")
        epoch = r.get("beat_at_epoch")
        if m is None or epoch is None:
            continue
        if m not in latest or epoch > latest[m]:
            latest[m] = int(epoch)
    stale: list[str] = []
    for m in expected:
        beat = latest.get(m)
        if beat is None or (now_epoch - beat) > STALE_SECONDS:
            stale.append(m)
    return stale


def should_alert(machine: str, *, last_alert_epoch: int | None, now_epoch: int) -> bool:
    if last_alert_epoch is None:
        return True
    return (now_epoch - last_alert_epoch) > ALERT_SUPPRESS_SECONDS


def _load_env_line(key: str) -> str:
    import os
    if (os.environ.get(key) or "").strip():
        return os.environ[key].strip()
    bases: list[Path] = []
    if os.environ.get("VALUEHIRE_REPO_DIR"):
        bases.append(Path(os.environ["VALUEHIRE_REPO_DIR"]))
    cur, home = REPO, Path.home()
    while True:
        bases.append(cur)
        if cur == home or cur.parent == cur:
            break
        cur = cur.parent
    for base in bases:
        env = base / ".env.local"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def health_notify(text: str) -> None:
    """OPS_HEALTH webhook 으로 경보(fail-soft)."""
    url = _load_env_line("DISCORD_WEBHOOK_URL_OPS_HEALTH")
    if not url:
        print(f"[watchdog] OPS_HEALTH webhook 없음 — 경보 생략: {text[:80]}", file=sys.stderr)
        return
    req = urllib.request.Request(
        url, data=json.dumps({"content": text[:1900]}).encode(),
        method="POST", headers={"Content-Type": "application/json",
                                "User-Agent": "ValuehireWatchdog/1.0"})
    urllib.request.urlopen(req, timeout=20)


class Watchdog:
    def __init__(
        self,
        *,
        fetch_heartbeats: Callable[[int], Sequence[Mapping[str, Any]]],
        notify: Callable[[str], None] = health_notify,
        load_alert_state: Callable[[], dict[str, int]] = lambda: {},
        save_alert_state: Callable[[dict[str, int]], None] = lambda s: None,
        expected: Sequence[str] = FLEET_MACHINES,
    ) -> None:
        self.fetch_heartbeats = fetch_heartbeats
        self.notify = notify
        self.load_alert_state = load_alert_state
        self.save_alert_state = save_alert_state
        self.expected = tuple(expected)

    def run_once(self, *, now_epoch: int) -> list[str]:
        """stale 머신 경보(억제 반영). 반환: 이번에 실제 경보한 머신 목록."""
        rows = self.fetch_heartbeats(now_epoch)
        stale = stale_machines(rows, now_epoch=now_epoch, expected=self.expected)
        state = self.load_alert_state()
        alerted: list[str] = []
        for m in stale:
            if should_alert(m, last_alert_epoch=state.get(m), now_epoch=now_epoch):
                text = (f"🚨 함대 경보: 머신 '{m}' 이(가) {STALE_SECONDS // 60}분 넘게 "
                        f"응답이 없습니다. 워커/전원/네트워크를 확인해 주세요.")
                try:
                    self.notify(text)
                except Exception as exc:  # noqa: BLE001 — 경보 실패는 watchdog 을 죽이지 않는다
                    print(f"[watchdog] 경보 전송 실패(fail-soft): {exc}", file=sys.stderr)
                state[m] = now_epoch
                alerted.append(m)
        self.save_alert_state(state)
        return alerted
