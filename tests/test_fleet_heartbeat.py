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
    assert p == {"machine": "macmini", "beat_at": "2026-07-11T00:00:00Z", "worker_pid": 4242,
                 "linkedin_rps_logged_in": False}


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


def test_stale_exact_boundary_off_by_one():
    # V1 결함2: 정확히 STALE_SECONDS = stale 아님(> 만 stale). 뮤턴트 >→>= 고정.
    now = 1_000_000
    assert stale_machines(_rows(("macmini", STALE_SECONDS)), now_epoch=now,
                          expected=("macmini",)) == []
    assert stale_machines(_rows(("macmini", STALE_SECONDS + 1)), now_epoch=now,
                          expected=("macmini",)) == ["macmini"]


def test_stale_clock_skew_future_beat_not_stale():
    # V1: now < beat(시계 역행/스큐) 시 음수 경과 → stale 아님
    now = 1_000_000
    assert stale_machines(_rows(("macmini", -120)), now_epoch=now,
                          expected=("macmini",)) == []


# ── 중복 경보 억제 (30분) ────────────────────────────────────────────

def test_should_alert_suppression():
    # 마지막 경보가 없으면 경보
    assert should_alert("macbook", last_alert_epoch=None, now_epoch=1_000_000) is True
    # 30분 이내 재경보 억제
    assert should_alert("macbook", last_alert_epoch=1_000_000 - 60, now_epoch=1_000_000) is False
    # 30분 초과면 재경보
    assert should_alert("macbook", last_alert_epoch=1_000_000 - 1801, now_epoch=1_000_000) is True
    # V1 결함3: 정확히 1800초 = 아직 억제(> 만 재경보). 뮤턴트 >→>= 고정.
    assert should_alert("macbook", last_alert_epoch=1_000_000 - 1800, now_epoch=1_000_000) is False
    assert should_alert("macbook", last_alert_epoch=1_000_000 - 1800, now_epoch=1_000_001) is True


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


def test_watchdog_notify_failure_does_not_suppress(monkeypatch):
    # V1 결함4: 전송 실패 시 억제(state)·alerted 표기 안 함 → 다음 주기 재시도(장애 은폐 금지)
    from tools.multi_position_sourcing import fleet_heartbeat as fh
    state = {}
    calls = {"n": 0}

    def flaky(text):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("webhook down")

    w = fh.Watchdog(
        fetch_heartbeats=lambda now_epoch: _rows(("macbook", STALE_SECONDS + 5)),
        notify=flaky, load_alert_state=lambda: dict(state),
        save_alert_state=lambda s: (state.clear(), state.update(s)),
        expected=("macbook",))
    a1 = w.run_once(now_epoch=1_000_000)
    assert a1 == []           # 전송 실패 → 경보 표기 없음
    assert "macbook" not in state  # 억제 안 함
    a2 = w.run_once(now_epoch=1_000_010)  # 30분 안 지났어도 재시도(억제 안 됐으므로)
    assert a2 == ["macbook"]  # 이번엔 성공


def test_beat_loop_independent_of_jobs():
    # V1 결함1: 심장박동이 잡 실행과 무관하게 interval 마다 계속 뛰는지(별도 스레드 로직)
    from tools.multi_position_sourcing.fleet_heartbeat import beat_loop

    beats = {"n": 0}

    class FakeStop:
        def __init__(self, stop_after):
            self.stop_after = stop_after
            self.waits = 0
        def is_set(self):
            return self.waits >= self.stop_after
        def wait(self, t):
            self.waits += 1

    beat_loop(lambda: beats.__setitem__("n", beats["n"] + 1),
              FakeStop(stop_after=3), interval=60)
    assert beats["n"] == 3  # 3회 뛰고 정지


def test_beat_loop_survives_beat_exception():
    from tools.multi_position_sourcing.fleet_heartbeat import beat_loop

    class FakeStop:
        def __init__(self):
            self.waits = 0
        def is_set(self):
            return self.waits >= 2
        def wait(self, t):
            self.waits += 1

    # beat_fn 이 예외를 던져도 스레드 루프는 계속(다음 주기)
    beat_loop(lambda: (_ for _ in ()).throw(RuntimeError("db down")),
              FakeStop(), interval=1)  # 예외 전파되면 실패


def test_worker_loop_beats_via_thread():
    # 배선(R4): worker.loop 이 beat_loop 스레드를 띄워 record_heartbeat 를 반복 호출
    from tools.multi_position_sourcing.fleet_worker import FleetWorker

    beats = {"n": 0}

    class Q:
        def _call(self, method, path, payload):
            beats["n"] += 1
            return [{"machine": "macmini"}]
        def claim_next(self, machine):
            # loop 을 한 바퀴 뒤 멈추기 위해 예외로 빠져나온다
            raise KeyboardInterrupt

    w = FleetWorker(machine="macmini", queue=Q(),
                    runner=lambda p, t: ("", 0), notifier=lambda j, t: None)
    import pytest as _pytest
    with _pytest.raises(KeyboardInterrupt):
        w.loop(poll_seconds=0, heartbeat_seconds=0)
    # 스레드가 최소 1회 심장박동(record_heartbeat→_call)을 냈다
    import time as _t
    _t.sleep(0.05)
    assert beats["n"] >= 1


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


def test_worker_loop_records_heartbeat():
    # 배선(R4): fleet_worker.record_heartbeat 가 record_heartbeat RPC 를 자기 머신으로 호출
    from tools.multi_position_sourcing.fleet_worker import FleetWorker

    calls = []

    class Q:
        def _call(self, method, path, payload):
            calls.append((method, path, payload))
            return [{"machine": "macmini"}]

    w = FleetWorker(machine="macmini", queue=Q(),
                    runner=lambda p, t: ("", 0), notifier=lambda j, t: None)
    w.record_heartbeat()
    assert calls and calls[0][1] == "/rpc/record_heartbeat"
    assert calls[0][2]["p_machine"] == "macmini"
    assert isinstance(calls[0][2]["p_worker_pid"], int)


def test_watchdog_script_and_plist_exist():
    sh = REPO / "scripts" / "fleet_watchdog.py"
    plist = REPO / "ops" / "launchd" / "com.valuehire.fleet-watchdog.plist"
    assert sh.exists() and "Watchdog" in sh.read_text()
    assert plist.exists() and "fleet_watchdog.py" in plist.read_text()


def test_sot29_fleet_control_doc_integrity():
    import json
    doc = REPO / "docs" / "sot" / "29-fleet-control.json"
    md = REPO / "docs" / "sot" / "29-fleet-control.md"
    assert doc.exists() and md.exists()
    d = json.loads(doc.read_text())
    assert d["sot_id"] == 29
    inv = d["invariants"]
    # 핵심 불변식이 문서에 실재하는지(계정 바인딩·발송 게이트·owner 전용·stale 경보)
    assert "INV1_account_machine_binding" in inv
    assert "INV4_send_gate" in inv
    assert "INV5_owner_only" in inv
    assert "INV7_stale_alert" in inv
    assert set(d["machines"]) == {"macmini", "winpc", "macbook"}
    # CLAUDE.md 에서 링크(배선)
    claude_md = REPO / "CLAUDE.md"
    assert "29-fleet-control" in claude_md.read_text()


def test_migration_has_heartbeat_table():
    cands = sorted((REPO / "supabase" / "migrations").glob("*heartbeat*.sql"))
    assert cands, "heartbeat 마이그레이션 없음"
    sql = "\n".join(l.split("--", 1)[0] for l in cands[-1].read_text().splitlines()).lower()
    for needle in ("create table if not exists public.machine_heartbeats",
                   "record_heartbeat", "service_role", "enable row level security"):
        assert needle in sql, f"'{needle}' 누락"


# ── 이슈 D(2026-07-15, 사장님 SOT29 §2 개정 승인) — LinkedIn 로그인 머신 라우팅 ──

def test_heartbeat_payload_carries_linkedin_flag():
    p = heartbeat_payload("winpc", worker_pid=1, now_iso="2026-07-15T00:00:00Z",
                          linkedin_rps_logged_in=True)
    assert p["linkedin_rps_logged_in"] is True


def test_linkedin_flag_from_portal_status():
    from tools.multi_position_sourcing.fleet_heartbeat import (
        linkedin_rps_logged_in_from_status,
    )
    now = 1_800_000_000
    fresh = {"kind": "portal_session_preflight",
             "generated_at": "2027-01-15T08:00:00Z",
             "portal_sessions": [{"channel": "linkedin_rps", "ready": True}]}
    import datetime
    gen_epoch = int(datetime.datetime(2027, 1, 15, 8, 0, tzinfo=datetime.timezone.utc).timestamp())
    assert linkedin_rps_logged_in_from_status(fresh, now_epoch=gen_epoch + 60) is True
    # 오래된 파일(기본 24h 초과)은 신뢰하지 않는다
    assert linkedin_rps_logged_in_from_status(fresh, now_epoch=gen_epoch + 86401) is False
    not_ready = {"generated_at": "2027-01-15T08:00:00Z",
                 "portal_sessions": [{"channel": "linkedin_rps", "ready": False}]}
    assert linkedin_rps_logged_in_from_status(not_ready, now_epoch=gen_epoch + 60) is False
    # 채널 누락·깨진 payload·깨진 날짜 = False (fail-closed)
    assert linkedin_rps_logged_in_from_status({"portal_sessions": []}, now_epoch=now) is False
    assert linkedin_rps_logged_in_from_status(None, now_epoch=now) is False
    assert linkedin_rps_logged_in_from_status(
        {"generated_at": "not-a-date",
         "portal_sessions": [{"channel": "linkedin_rps", "ready": True}]},
        now_epoch=now) is False


def test_pick_linkedin_machine_priority_and_fallback():
    from tools.multi_position_sourcing.fleet_heartbeat import pick_linkedin_machine
    now = 1_800_000_000
    rows = [
        {"machine": "macbook", "beat_at_epoch": now - 10, "linkedin_rps_logged_in": True},
        {"machine": "winpc", "beat_at_epoch": now - 10, "linkedin_rps_logged_in": True},
    ]
    # SOT29 INV8 신뢰도 우선순위: macmini > winpc > macbook
    assert pick_linkedin_machine(rows, now_epoch=now) == "winpc"
    rows.append({"machine": "macmini", "beat_at_epoch": now - 10, "linkedin_rps_logged_in": True})
    assert pick_linkedin_machine(rows, now_epoch=now) == "macmini"
    # 아무도 로그인 안 됨 → macmini 폴백(무동작보다 낫다, 사장님 승인 설계)
    assert pick_linkedin_machine([], now_epoch=now) == "macmini"
    # stale heartbeat(5분 초과)는 제외
    stale = [{"machine": "winpc", "beat_at_epoch": now - 301, "linkedin_rps_logged_in": True}]
    assert pick_linkedin_machine(stale, now_epoch=now) == "macmini"
    # 깨진 행은 무시(fail-closed)
    junk = [{"machine": "winpc", "linkedin_rps_logged_in": True},
            {"beat_at_epoch": now, "linkedin_rps_logged_in": True}]
    assert pick_linkedin_machine(junk, now_epoch=now) == "macmini"


def test_linkedin_migration_and_sot29_amended():
    mig = REPO / "supabase" / "migrations" / "20260715_fleet_linkedin_routing.sql"
    assert mig.exists(), "heartbeat linkedin 컬럼 마이그레이션 없음"
    sql = mig.read_text(encoding="utf-8")
    assert "linkedin_rps_logged_in" in sql
    assert "p_linkedin_rps_logged_in" in sql
    assert "linkedin_ready_machines" in sql
    md = (REPO / "docs" / "sot" / "29-fleet-control.md").read_text(encoding="utf-8")
    assert "macmini` 전용" not in md, "SOT29 §2 macmini 전용 조항이 아직 개정 안 됨"
    assert "linkedin_rps_logged_in" in md
    js = (REPO / "docs" / "sot" / "29-fleet-control.json").read_text(encoding="utf-8")
    assert "macmini 전용" not in js
    assert "linkedin_rps_logged_in" in js


def test_future_dated_status_rejected():
    """V1(Codex) blocker 수용 — 미래 시각 generated_at(시계 튐/조작)은 신뢰하지 않는다."""
    from tools.multi_position_sourcing.fleet_heartbeat import (
        linkedin_rps_logged_in_from_status,
    )
    future = {"generated_at": "2099-01-01T00:00:00Z",
              "portal_sessions": [{"channel": "linkedin_rps", "ready": True}]}
    assert linkedin_rps_logged_in_from_status(future, now_epoch=1_800_000_000) is False


def test_legacy_two_arg_heartbeat_resets_linkedin_flag_in_migration():
    """V1(Codex) blocker 수용 — 구버전 워커(2인자 RPC)가 beat 만 갱신하면
    낡은 linkedin=true 가 '신선한 로그인'으로 영구 위장된다. 새 마이그레이션이
    2인자 함수를 재정의해 flag 를 false 로 리셋해야 한다(fail-closed)."""
    sql = (REPO / "supabase" / "migrations" / "20260715_fleet_linkedin_routing.sql"
           ).read_text(encoding="utf-8").lower()
    assert "record_heartbeat(p_machine text, p_worker_pid integer)" in sql, \
        "2인자 record_heartbeat 재정의 누락"
    two_arg = sql.split("record_heartbeat(p_machine text, p_worker_pid integer)", 1)[1]
    assert "linkedin_rps_logged_in = false" in two_arg.split("$$;")[0].replace("\n", " "), \
        "2인자 경로가 linkedin 플래그를 false 로 리셋하지 않음"
