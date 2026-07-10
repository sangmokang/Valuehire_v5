"""단계 G — 함대 heartbeat + watchdog 기계 검증.

계약(docs/prompts/fleet-control-sequential-prompts-2026-07-11.md §프롬프트 G):
- 워커가 1분마다 machine_heartbeats 에 심장박동 기록(machine, beat_at, worker_pid).
- watchdog: 마지막 beat 로부터 5분(±) 초과 머신 → OPS_HEALTH 경보.
- 중복 경보 30분 억제. webhook 미설정 시 fail-soft(경보 생략, 예외 없음).
- 마이그레이션에 machine_heartbeats + upsert RPC 존재.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.multi_position_sourcing.fleet_heartbeat import (
    STALE_SECONDS,
    heartbeat_payload,
    stale_machines,
    should_alert,
)

REPO = Path(__file__).resolve().parents[1]


# ── heartbeat 페이로드 ───────────────────────────────────────────────

def test_heartbeat_payload():
    p = heartbeat_payload("macmini", worker_pid=4242, now_iso="2026-07-11T00:00:00Z")
    assert p == {"machine": "macmini", "beat_at": "2026-07-11T00:00:00Z", "worker_pid": 4242}


@pytest.mark.parametrize("machine", ["", "laptop", "MACMINI", None])
def test_heartbeat_payload_rejects_bad_machine(machine):
    with pytest.raises(ValueError):
        heartbeat_payload(machine, worker_pid=1, now_iso="2026-07-11T00:00:00Z")


# ── stale 판정 (5분 경계) ────────────────────────────────────────────

def _rows(*pairs):
    # pairs: (machine, seconds_ago)
    return [{"machine": m, "beat_at_epoch": 1_000_000 - ago} for m, ago in pairs]


def test_stale_machines_boundary():
    now = 1_000_000
    rows = _rows(("macmini", 60), ("macbook", STALE_SECONDS + 1), ("winpc", STALE_SECONDS - 1))
    stale = stale_machines(rows, now_epoch=now)
    assert stale == ["macbook"]  # 5분 초과만


def test_stale_machines_missing_machine_is_stale():
    # 등록된 함대 머신 중 heartbeat 행이 아예 없는 머신도 stale 로 본다
    now = 1_000_000
    rows = _rows(("macmini", 10))
    stale = stale_machines(rows, now_epoch=now,
                           expected=("macmini", "macbook", "winpc"))
    assert set(stale) == {"macbook", "winpc"}


def test_stale_machines_all_fresh():
    now = 1_000_000
    rows = _rows(("macmini", 5), ("macbook", 5), ("winpc", 5))
    assert stale_machines(rows, now_epoch=now,
                          expected=("macmini", "macbook", "winpc")) == []


# ── 중복 경보 억제 (30분) ────────────────────────────────────────────

def test_should_alert_suppression():
    # 마지막 경보가 없으면 경보
    assert should_alert("macbook", last_alert_epoch=None, now_epoch=1_000_000) is True
    # 30분 이내 재경보 억제
    assert should_alert("macbook", last_alert_epoch=1_000_000 - 60, now_epoch=1_000_000) is False
    # 30분 초과면 재경보
    assert should_alert("macbook", last_alert_epoch=1_000_000 - 1801, now_epoch=1_000_000) is True


# ── 배선 실체 ────────────────────────────────────────────────────────

def test_watchdog_run_alerts_stale_and_suppresses(monkeypatch):
    from tools.multi_position_sourcing import fleet_heartbeat as fh

    alerts = []
    state = {}  # machine -> last_alert_epoch

    def fake_fetch(now_epoch):
        return _rows(("macmini", 10), ("macbook", STALE_SECONDS + 5))

    w = fh.Watchdog(
        fetch_heartbeats=fake_fetch,
        notify=lambda text: alerts.append(text),
        load_alert_state=lambda: dict(state),
        save_alert_state=lambda s: state.update(s),
        expected=("macmini", "macbook", "winpc"),
    )
    # 1회차: macbook + winpc(누락) stale → 경보 2건
    w.run_once(now_epoch=1_000_000)
    assert len(alerts) == 2
    # 즉시 2회차: 30분 억제 → 경보 0
    w.run_once(now_epoch=1_000_030)
    assert len(alerts) == 2


def test_watchdog_no_webhook_fail_soft():
    from tools.multi_position_sourcing import fleet_heartbeat as fh
    # notify 가 예외를 던져도 watchdog 은 죽지 않는다
    def boom(text):
        raise RuntimeError("webhook down")
    w = fh.Watchdog(
        fetch_heartbeats=lambda now_epoch: _rows(("macbook", STALE_SECONDS + 5)),
        notify=boom,
        load_alert_state=lambda: {},
        save_alert_state=lambda s: None,
        expected=("macbook",),
    )
    w.run_once(now_epoch=1_000_000)  # 예외 전파되면 실패


def test_migration_has_heartbeat_table():
    cands = sorted((REPO / "supabase" / "migrations").glob("*heartbeat*.sql"))
    assert cands, "heartbeat 마이그레이션 없음"
    sql = "\n".join(l.split("--", 1)[0] for l in cands[-1].read_text().splitlines()).lower()
    for needle in ("create table if not exists public.machine_heartbeats",
                   "record_heartbeat", "service_role", "enable row level security"):
        assert needle in sql, f"'{needle}' 누락"
