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
        users = [DiscordAuthorizedUser(
            name="사장님", alias="boss", email="sangmokang@valueconnect.kr",
            discord_id="814353841088757800")]
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


# ═══ ultracode QA 확정 결함(2026-07-13) 재발 방지 ═══════════════════

from tools.multi_position_sourcing.fleet_heartbeat import (  # noqa: E402
    RUNNING_STALL_SECONDS,
    stalled_running_jobs,
)
from tools.multi_position_sourcing.fleet_worker import (  # noqa: E402
    PAUSE_COOLDOWN_SECONDS,
    FleetWorker,
    parse_worker_output,
    sleep_seconds_after,
)


# ── QA-1: running 고아 잡 가시화(워커 급사 → 영구 running + 계정락 잔존) ──

def _running_row(job_id=20, machine="macmini", age=RUNNING_STALL_SECONDS + 1):
    return {"id": job_id, "machine": machine, "status": "running",
            "started_at_epoch": NOW - age}


class TestStalledRunningJobs:
    def test_한도_초과_running_은_고아_의심(self):
        out = stalled_running_jobs([_running_row()], now_epoch=NOW)
        assert len(out) == 1 and out[0]["id"] == 20

    def test_경계_정확히_한도는_아직_정상(self):
        assert stalled_running_jobs(
            [_running_row(age=RUNNING_STALL_SECONDS)], now_epoch=NOW) == []

    def test_running_아니면_제외(self):
        row = _running_row()
        row["status"] = "queued"
        assert stalled_running_jobs([row], now_epoch=NOW) == []

    def test_시작시각_결손_fail_closed(self):
        row = {"id": 21, "machine": "macmini", "status": "running"}
        assert len(stalled_running_jobs([row], now_epoch=NOW)) == 1

    def test_한도는_claude_타임아웃보다_길다(self):
        # 40분 잡이 정상 실행 중인데 고아로 오판하면 안 된다.
        from tools.multi_position_sourcing.fleet_worker import CLAUDE_TIMEOUT_SECONDS
        assert RUNNING_STALL_SECONDS > CLAUDE_TIMEOUT_SECONDS

    def test_watchdog_이_running_고아를_경보한다(self):
        notes, state = [], {}
        wd = Watchdog(
            fetch_heartbeats=lambda now: [
                {"machine": m, "beat_at_epoch": NOW} for m in ("macmini", "macbook", "winpc")],
            notify=notes.append,
            load_alert_state=lambda: dict(state),
            save_alert_state=state.update,
            fetch_running_jobs=lambda now: [_running_row(job_id=20)],
        )
        alerted = wd.run_once(now_epoch=NOW)
        assert "job:20" in alerted
        assert any("20" in n and "running" in n for n in notes)


# ── QA-2: 캡차(일시정지) 직후 같은 계정 재진입 금지 — 쿨다운 ────────

class TestPauseCooldown:
    def test_paused_후_쿨다운_시간(self):
        assert sleep_seconds_after("paused_for_human", 30) == PAUSE_COOLDOWN_SECONDS
        assert PAUSE_COOLDOWN_SECONDS >= 300, "사람이 캡차 푸는 최소 여유"

    def test_기존_상태별_대기시간_유지(self):
        assert sleep_seconds_after("idle", 30) == 30
        assert sleep_seconds_after("error", 30) == 15
        assert sleep_seconds_after("error", 5) == 5
        assert sleep_seconds_after("done", 30) == 0
        assert sleep_seconds_after("failed", 30) == 0

    def test_loop_가_paused_후_실제로_쉰다(self, monkeypatch):
        sleeps: list[float] = []

        class StopLoop(BaseException):
            # loop 의 광역 except Exception 방어(의도된 fail-soft)에 잡히지 않고
            # 테스트를 탈출시키기 위한 신호 — BaseException 직계.
            pass

        class Q:
            calls = 0

            def probe_auth(self):
                return ("ok", "")

            def claim_next(self, machine):
                Q.calls += 1
                if Q.calls == 1:
                    return {"id": 1, "skill": "humansearch", "machine": "macmini",
                            "position_url": "https://x.co/p", "requested_by": "u",
                            "role": "owner", "params": {}}
                raise StopLoop()

            def release(self, *a, **k):
                return {}

        def fake_runner(prompt, timeout):
            return ("PAUSED_FOR_HUMAN: 캡차", 0)

        monkeypatch.setattr(
            "tools.multi_position_sourcing.fleet_worker.time.sleep", sleeps.append)
        w = FleetWorker("macmini", queue=Q(), runner=fake_runner,
                        notifier=lambda j, t: None)
        with pytest.raises(StopLoop):
            w.loop(poll_seconds=30)
        assert PAUSE_COOLDOWN_SECONDS in sleeps, "일시정지 직후 쿨다운 없이 재claim 금지"


# ── QA-3: stderr 가 길어도 PAUSED 마커를 잃지 않는다 ────────────────

class TestPausedMarkerNotDrownedByStderr:
    def test_stderr_20줄이_마커를_밀어내지_못한다(self):
        stdout = "작업 요약...\nPAUSED_FOR_HUMAN: 링크드인 캡차"
        stderr = "\n".join(f"Traceback line {i}" for i in range(20))
        result = parse_worker_output(stdout, 1, stderr=stderr)
        assert result["status"] == "paused_for_human"
        assert "캡차" in result["reason"]

    def test_기존_2인자_호출_호환(self):
        assert parse_worker_output("PAUSED_FOR_HUMAN: x", 0)["status"] == "paused_for_human"
        assert parse_worker_output("", 0)["status"] == "failed"

    def test_실패_요약에는_stderr_포함(self):
        result = parse_worker_output("부분 출력", 1, stderr="RuntimeError: boom")
        assert result["status"] == "failed"
        assert "boom" in result.get("summary", "")


# ── QA-4: release 실패가 잡을 조용한 running 고아로 두지 않는다 ─────

class TestReleaseRetry:
    def _worker(self, q, notes):
        return FleetWorker("macmini", queue=q, runner=lambda p, t: ("요약 텍스트", 0),
                           notifier=lambda j, t: notes.append(t))

    def test_일시_장애는_재시도로_흡수(self, monkeypatch):
        monkeypatch.setattr(
            "tools.multi_position_sourcing.fleet_worker.time.sleep", lambda s: None)
        notes: list[str] = []

        class Q:
            n = 0

            def claim_next(self, m):
                return {"id": 5, "skill": "humansearch", "machine": "macmini",
                        "position_url": "https://x.co/p", "requested_by": "u",
                        "role": "owner", "params": {}}

            def release(self, *a, **k):
                Q.n += 1
                if Q.n < 3:
                    raise OSError("network blip")
                return {}

        assert self._worker(Q(), notes).run_once() == "done"
        assert Q.n == 3

    def test_최종_실패시_고아_경보_후_예외(self, monkeypatch):
        monkeypatch.setattr(
            "tools.multi_position_sourcing.fleet_worker.time.sleep", lambda s: None)
        notes: list[str] = []

        class Q:
            def claim_next(self, m):
                return {"id": 6, "skill": "humansearch", "machine": "macmini",
                        "position_url": "https://x.co/p", "requested_by": "u",
                        "role": "owner", "params": {}}

            def release(self, *a, **k):
                raise OSError("supabase down")

        with pytest.raises(Exception):
            self._worker(Q(), notes).run_once()
        assert any("고아" in n and "6" in n for n in notes), "최종 실패는 조용히 넘어가지 않는다"
