#!/usr/bin/env python3
"""함대 watchdog (맥미니 상주) — stale 머신을 OPS_HEALTH 로 경보.

단계 G. Supabase heartbeats_epoch RPC 로 머신별 마지막 beat 를 읽어
stale(5분 초과/누락) 머신을 Discord OPS_HEALTH webhook 으로 알린다(30분 중복 억제).
상태(마지막 경보 시각)는 로컬 JSON 에 저장 — 재시작해도 억제 유지.
사용: python3 scripts/fleet_watchdog.py [--once]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.multi_position_sourcing.fleet_heartbeat import Watchdog, health_notify  # noqa: E402
from tools.multi_position_sourcing.job_queue import JobQueueClient  # noqa: E402

STATE_PATH = Path.home() / ".valuehire" / "fleet_watchdog_alerts.json"
POLL_SECONDS = 60


def _fetch(now_epoch: int):
    rows = JobQueueClient()._call("POST", "/rpc/heartbeats_epoch", {})  # noqa: SLF001
    return rows if isinstance(rows, list) else []


def _fetch_queued(now_epoch: int):
    """SOT30 S2 — queued 고착 판정용 잡 목록(조회 실패는 Watchdog 이 fail-soft 처리)."""
    rows = JobQueueClient().queued_jobs()
    return rows if isinstance(rows, list) else []


def _load_state() -> dict[str, int]:
    if STATE_PATH.exists():
        try:
            return {k: int(v) for k, v in json.loads(STATE_PATH.read_text()).items()}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save_state(state: dict[str, int]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Valuehire 함대 watchdog")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args(argv)

    wd = Watchdog(
        fetch_heartbeats=_fetch, notify=health_notify,
        load_alert_state=_load_state, save_alert_state=_save_state,
        fetch_queued_jobs=_fetch_queued,
    )
    if args.once:
        alerted = wd.run_once(now_epoch=int(time.time()))
        print(f"[watchdog] 경보 머신: {alerted or '없음'}")
        return 0
    while True:
        try:
            wd.run_once(now_epoch=int(time.time()))
        except Exception as exc:  # noqa: BLE001 — watchdog 은 죽지 않는다
            print(f"[watchdog] run_once 예외(fail-soft): {exc}", file=sys.stderr)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
