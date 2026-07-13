"""SOT30(docs/sot/30-fleet-run-reliability.md) S2·S3 계약 테스트 — RED 먼저.

S2: queued 고착 감지(stalled_queued_jobs) + Watchdog 경보 + fleet-status heartbeat 나이.
S3: 자격증명 프로브(classify_auth_probe/probe_auth) + 워커 기동 인증 게이트(fail-loud).
2026-07-13 라이브 사고(잡 16 이 1시간 queued 고착·맥북 401 조용한 실패) 재발 방지.
"""
from __future__ import annotations

import pytest

from tools.multi_position_sourcing.fleet_heartbeat import (
    QUEUED_STALL_SECONDS,
    Watchdog,
    heartbeat_ages,
    stalled_queued_jobs,
)
from tools.multi_position_sourcing.fleet_worker import wait_until_authenticated
from tools.multi_position_sourcing.job_queue import classify_auth_probe

NOW = 1_800_000_000  # 고정 기준 시각(epoch) — 실시간 비의존(결정론)


# ── S2-1: stalled_queued_jobs 순수함수 ──────────────────────────────

def _row(job_id=16, machine="macmini", status="queued", age=QUEUED_STALL_SECONDS + 1):
    return {"id": job_id, "machine": machine, "status": status,
            "created_at_epoch": NOW - age}


class TestStalledQueuedJobs:
    def test_고착_잡은_잡힌다(self):
        out = stalled_queued_jobs([_row()], now_epoch=NOW)
        assert len(out) == 1
        assert out[0]["id"] == 16 and out[0]["machine"] == "macmini"

    def test_경계_정확히_10분은_고착_아님(self):
        assert stalled_queued_jobs(
            [_row(age=QUEUED_STALL_SECONDS)], now_epoch=NOW) == []

    def test_경계_10분_1초는_고착(self):
        assert len(stalled_queued_jobs(
            [_row(age=QUEUED_STALL_SECONDS + 1)], now_epoch=NOW)) == 1

    @pytest.mark.parametrize("status", ["running", "paused_for_human", "done",
                                        "failed", "cancelled"])
    def test_queued_아니면_아무리_오래돼도_제외(self, status):
        assert stalled_queued_jobs(
            [_row(status=status, age=99_999)], now_epoch=NOW) == []

    def test_생성시각_결손은_fail_closed_고착_취급(self):
        # 언제 만들어졌는지 증명 못 하면 신선하다고 가정하지 않는다.
        row = {"id": 7, "machine": "macmini", "status": "queued"}
        out = stalled_queued_jobs([row], now_epoch=NOW)
        assert len(out) == 1 and out[0]["id"] == 7

    def test_생성시각_비정수도_fail_closed(self):
        row = {"id": 8, "machine": "macmini", "status": "queued",
               "created_at_epoch": "어제쯤"}
        assert len(stalled_queued_jobs([row], now_epoch=NOW)) == 1

    def test_빈_입력은_빈_결과(self):
        assert stalled_queued_jobs([], now_epoch=NOW) == []

    def test_iso_created_at_문자열도_해석(self):
        # Supabase 는 created_at 을 ISO8601 로 준다 — epoch 없이도 판정돼야 한다.
        from datetime import datetime, timedelta, timezone
        created = datetime(2026, 7, 13, 0, 16, 14, tzinfo=timezone.utc)
        row = {"id": 9, "machine": "macmini", "status": "queued",
               "created_at": "2026-07-13T00:16:14.002859+00:00"}
        one_hour_later = int((created + timedelta(hours=1)).timestamp())
        assert len(stalled_queued_jobs([row], now_epoch=one_hour_later)) == 1
        five_min_later = int((created + timedelta(minutes=5)).timestamp())
        assert stalled_queued_jobs([row], now_epoch=five_min_later) == []


# ── S2-2: Watchdog 이 고착 잡을 경보한다(30분 억제) ─────────────────

def _watchdog(notify_log, state, queued_rows):
    return Watchdog(
        fetch_heartbeats=lambda now: [
            {"machine": m, "beat_at_epoch": NOW} for m in ("macmini", "macbook", "winpc")
        ],  # 머신 heartbeat 는 전부 신선 — 잡 고착 경보만 분리 검증
        notify=notify_log.append,
        load_alert_state=lambda: dict(state),
        save_alert_state=state.update,
        fetch_queued_jobs=lambda now: queued_rows,
    )


class TestWatchdogQueuedStall:
    def test_고착_잡_경보_발생(self):
        notes, state = [], {}
        wd = _watchdog(notes, state, [_row(job_id=16)])
        alerted = wd.run_once(now_epoch=NOW)
        assert any("16" in n and "macmini" in n for n in notes)
        assert "job:16" in alerted

    def test_같은_잡은_30분_안에_두번_경보하지_않는다(self):
        notes, state = [], {}
        wd = _watchdog(notes, state, [_row(job_id=16)])
        wd.run_once(now_epoch=NOW)
        wd.run_once(now_epoch=NOW + 60)
        assert sum("16" in n for n in notes) == 1

    def test_전송_실패시_억제하지_않고_다음_주기_재시도(self):
        state = {}
        calls = {"n": 0}

        def flaky(text):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("webhook down")

        wd = Watchdog(
            fetch_heartbeats=lambda now: [
                {"machine": m, "beat_at_epoch": NOW} for m in ("macmini", "macbook", "winpc")],
            notify=flaky,
            load_alert_state=lambda: dict(state),
            save_alert_state=state.update,
            fetch_queued_jobs=lambda now: [_row(job_id=16)],
        )
        assert wd.run_once(now_epoch=NOW) == []          # 실패 → 경보 처리 안 됨
        assert "job:16" in wd.run_once(now_epoch=NOW + 60)  # 재시도 성공

    def test_fetch_없으면_기존_동작_그대로(self):
        # 하위호환 — fetch_queued_jobs 미지정 구성(기존 스크립트)이 그대로 돌아야 한다.
        notes, state = [], {}
        wd = Watchdog(
            fetch_heartbeats=lambda now: [],
            notify=notes.append,
            load_alert_state=lambda: dict(state),
            save_alert_state=state.update,
        )
        alerted = wd.run_once(now_epoch=NOW)
        assert set(alerted) == {"macmini", "macbook", "winpc"}  # 기존 stale 경보만


# ── S2-3: heartbeat 나이 계산(fleet-status 표시용) ──────────────────

class TestHeartbeatAges:
    def test_나이_계산과_없는_머신_None(self):
        rows = [{"machine": "macmini", "beat_at_epoch": NOW - 42}]
        ages = heartbeat_ages(rows, now_epoch=NOW)
        assert ages["macmini"] == 42
        assert ages["macbook"] is None and ages["winpc"] is None

    def test_여러_beat_중_최신만(self):
        rows = [{"machine": "macmini", "beat_at_epoch": NOW - 500},
                {"machine": "macmini", "beat_at_epoch": NOW - 10}]
        assert heartbeat_ages(rows, now_epoch=NOW)["macmini"] == 10


class TestFleetStatusHeartbeats:
    def test_status_응답에_heartbeat_나이_포함(self):
        from tools.multi_position_sourcing.discord_routing import (
            DiscordAccessConfig, DiscordInvocation)
        from tools.multi_position_sourcing.fleet_dispatch import dispatch_fleet_command
        from tools.multi_position_sourcing.access import DiscordAuthorizedUser

        class FakeQueue:
            def recent(self, n):
                return []

            def heartbeats_epoch(self):
                return [{"machine": "macmini", "beat_at_epoch": NOW - 30}]

        inv = DiscordInvocation(
            user_id="814353841088757800", channel_id="c", command_name="fleet-status",
            is_dm=True, invocation_kind="slash", options={})
        users = [DiscordAuthorizedUser(name="사장님", discord_user_id="814353841088757800")]
        out = dispatch_fleet_command(
            inv, authorized_users=users, config=DiscordAccessConfig(allow_dm=True),
            queue=FakeQueue())
        assert out["action"] == "status"
        assert "heartbeats" in out, "SOT30 인수기준 3 — heartbeat 나이 표시"
        assert out["heartbeats"]["macmini"] is not None
        assert out["heartbeats"]["macbook"] is None


# ── S3-1: 자격증명 프로브 분류(순수) ────────────────────────────────

class TestClassifyAuthProbe:
    @pytest.mark.parametrize("code", [200, 201, 206])
    def test_2xx_ok(self, code):
        assert classify_auth_probe(code) == "ok"

    @pytest.mark.parametrize("code", [401, 403])
    def test_인증오류(self, code):
        assert classify_auth_probe(code) == "credential_error"

    @pytest.mark.parametrize("code", [500, 503, 429, 404])
    def test_그외는_재시도성_오류(self, code):
        assert classify_auth_probe(code) == "server_error"

    @pytest.mark.parametrize("bad", [None, "401", 4.01, True])
    def test_비정수는_ok_로_위장_못함(self, bad):
        assert classify_auth_probe(bad) != "ok"


# ── S3-2: 워커 기동 인증 게이트 — 조용히 죽지 않는다(fail-loud) ─────

class TestWaitUntilAuthenticated:
    def test_첫_probe_ok_면_즉시_통과_알림없음(self):
        notes, sleeps = [], []
        ok = wait_until_authenticated(
            lambda: ("ok", ""), notify=notes.append, sleep=sleeps.append)
        assert ok is True and notes == [] and sleeps == []

    def test_401_이면_명시_경보_후_백오프_재시도(self):
        notes, sleeps = [], []
        seq = iter([("credential_error", "Invalid API key"),
                    ("credential_error", "Invalid API key"),
                    ("ok", "")])
        ok = wait_until_authenticated(
            lambda: next(seq), notify=notes.append, sleep=sleeps.append)
        assert ok is True
        assert len(notes) == 1, "같은 원인 경보는 1회만(스팸 금지)"
        assert "Invalid API key" in notes[0] or "자격증명" in notes[0]
        assert len(sleeps) == 2 and sleeps[0] <= sleeps[1], "백오프 증가"

    def test_max_attempts_소진시_False_반환(self):
        notes, sleeps = [], []
        ok = wait_until_authenticated(
            lambda: ("credential_error", "dead key"),
            notify=notes.append, sleep=sleeps.append, max_attempts=3)
        assert ok is False
        assert len(notes) == 1

    def test_probe_예외도_삼키지_않고_재시도(self):
        notes, sleeps = [], []
        state = {"n": 0}

        def probe():
            state["n"] += 1
            if state["n"] == 1:
                raise OSError("network unreachable")
            return ("ok", "")

        ok = wait_until_authenticated(
            probe, notify=notes.append, sleep=sleeps.append)
        assert ok is True and len(sleeps) == 1
