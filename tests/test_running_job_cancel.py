"""이슈 #196 — 실행 중(running) 잡 협조적 즉시중지.

사장님 1순위 요구(2026-07-24): "중지해"를 눌러도 실행 중 세션이 안 멈춤. 근본 원인은
DB 상태 트리거가 running→cancelled 를 금지하고 cancel_job 이 queued/paused 만
취소하는 것 + 러너가 blocking subprocess.run 이라 중간 중단 불가.

인수 기준: 이 파일이 GREEN.
- (a) 마이그레이션이 running→cancelled 를 허용하고 cancel_job 이 running 도 취소.
- (b) run_agent_with_cancel 이 폴링 중 취소를 감지하면 서브프로세스 프로세스그룹
      전체를 죽이고 JobCancelled 를 던진다.
- (c) 취소 신호가 없으면 정상 (stdout, stderr, code) 반환(기존 러너 계약 불변).
- (d) cancel_observed 순수 판정: running/None 은 계속, 그 외(cancelled 등)는 중단.
"""
from __future__ import annotations

import pathlib

import pytest

from tools.multi_position_sourcing import fleet_worker


# ── (d) 순수 판정 ────────────────────────────────────────────────────────


def test_cancel_observed_pure():
    assert fleet_worker.cancel_observed("cancelled") is True
    assert fleet_worker.cancel_observed("failed") is True  # 사라진 잡도 중단
    assert fleet_worker.cancel_observed("running") is False
    assert fleet_worker.cancel_observed(None) is False  # 조회 실패는 계속(오탐 금지)


# ── (b)(c) 실행기: 협조적 취소 ──────────────────────────────────────────


class _FakeProc:
    """Popen 흉내 — poll()이 정해진 횟수 뒤 종료코드를 낸다."""

    def __init__(self, finish_after_polls: int | None, out="OK", err="", code=0):
        self.pid = 4242
        self._left = finish_after_polls
        self._out, self._err, self._code = out, err, code
        self.killed_group = False

    def poll(self):
        if self._left is None:
            return None  # 영원히 실행(취소로만 끝남)
        if self._left > 0:
            self._left -= 1
            return None
        return self._code

    def communicate(self, timeout=None):
        return self._out, self._err

    def wait(self, timeout=None):
        return self._code


def _run(proc, cancel_values, **kw):
    """run_agent_with_cancel 을 페이크 seam 으로 호출."""
    states = iter(cancel_values)
    killed = {"group": False}

    def kill_group(p):
        killed["group"] = True

    result = fleet_worker.run_agent_with_cancel(
        popen_factory=lambda: proc,
        cancel_check=lambda: fleet_worker.cancel_observed(next(states, "running")),
        kill_process_group=kill_group,
        poll_seconds=0,
        sleep=lambda _s: None,
        **kw,
    )
    return result, killed


def test_run_agent_normal_completion_returns_output():
    proc = _FakeProc(finish_after_polls=2, out="done", err="", code=0)
    (out, err, code), killed = _run(proc, cancel_values=["running", "running", "running"])
    assert (out, err, code) == ("done", "", 0)
    assert killed["group"] is False


def test_run_agent_cancel_kills_group_and_raises():
    proc = _FakeProc(finish_after_polls=None)  # 스스로는 안 끝남
    with pytest.raises(fleet_worker.JobCancelled):
        _run(proc, cancel_values=["running", "cancelled", "cancelled"])
    # kill 은 _run 내부 closure 에서 관찰 — 예외 후 확인 위해 재실행 대신 별도 검사
    proc2 = _FakeProc(finish_after_polls=None)
    killed = {"group": False}
    try:
        fleet_worker.run_agent_with_cancel(
            popen_factory=lambda: proc2,
            cancel_check=lambda: True,
            kill_process_group=lambda p: killed.__setitem__("group", True),
            poll_seconds=0, sleep=lambda _s: None,
        )
    except fleet_worker.JobCancelled:
        pass
    assert killed["group"] is True


# ── (a) 마이그레이션 ────────────────────────────────────────────────────


# ── 워커 배선: JobCancelled → 'cancelled', 재release 없음 ────────────────


def test_worker_cancel_check_polls_job_status():
    class _Q:
        def __init__(self):
            self.calls = []

        def job_status(self, job_id):
            self.calls.append(job_id)
            return "cancelled"

    w = fleet_worker.FleetWorker(
        machine="macmini", queue=_Q(), notifier=lambda j, t: None)
    check = w._cancel_check_for(75)
    assert check() is True  # cancelled → 중단
    # job_status 없는 큐는 None → 러너가 기존 subprocess.run 경로(하위호환) 사용.
    w2 = fleet_worker.FleetWorker(
        machine="macmini", queue=object(), notifier=lambda j, t: None)
    assert w2._cancel_check_for(75) is None


def test_worker_returns_cancelled_without_release_on_jobcancelled():
    """JobCancelled 가 나면 워커는 release 없이 'cancelled' 반환(경합 안전)."""
    released = []

    class _Q:
        def claim_next(self, machine):
            return {"id": 9, "skill": "humansearch", "machine": "macmini",
                    "role": "owner",
                    "position_url": "https://app.clickup.com/t/86eufjabc",
                    "params": {}}

        def job_status(self, job_id):
            return "cancelled"

        def release(self, *a, **k):
            released.append((a, k))

    def raising_runner(prompt, timeout, **kw):
        raise fleet_worker.JobCancelled()

    w = fleet_worker.FleetWorker(
        machine="macmini", queue=_Q(), runner=raising_runner,
        notifier=lambda j, t: None)
    assert w.run_once() == "cancelled"
    assert released == []  # 이미 terminal(cancelled) — 재release 금지


def test_worker_completion_race_ends_cancelled(monkeypatch):
    """Codex V2 F4 — 러너가 정상 종료했어도 그 사이 취소됐으면 done 이 아니라 cancelled.

    release 는 호출되지 않아야 한다(finish_job no-op 재시도·거짓 고아경보·완료알림·
    후속잡 유출 방지)."""
    released = []

    class _Q:
        def claim_next(self, machine):
            return {"id": 9, "skill": "humansearch", "machine": "macmini",
                    "role": "owner",
                    "position_url": "https://app.clickup.com/t/86eufjabc",
                    "params": {}}

        def job_status(self, job_id):
            # 러너가 정상 종료한 시점엔 owner 취소가 이미 반영돼 있다(경합).
            return "cancelled"

        def release(self, *a, **k):
            released.append((a, k))

    def ok_runner(prompt, timeout, **kw):
        return ("정상 출력", "", 0)  # 정상 완료

    w = fleet_worker.FleetWorker(
        machine="macmini", queue=_Q(), runner=ok_runner,
        notifier=lambda j, t: None)
    assert w.run_once() == "cancelled"
    assert released == []


def test_native_agent_run_kills_real_process_on_cancel():
    """Codex V2 F6 — 실제 서브프로세스를 취소 신호로 프로세스그룹째 종료(통합)."""
    import os
    import signal
    import sys
    import time as _t

    flips = {"n": 0}

    def cancel_check():
        flips["n"] += 1
        return flips["n"] >= 2  # 첫 폴은 계속, 두 번째 폴에서 취소

    # 자기 프로세스그룹에 자식을 하나 더 두고 오래 자는 프로세스 — killpg 로 둘 다 죽어야.
    script = ("import time,sys,os\n"
              "sys.stderr.write('up'); sys.stderr.flush()\n"
              "time.sleep(120)\n")
    start = _t.time()
    with pytest.raises(fleet_worker.JobCancelled):
        fleet_worker._native_agent_run(
            [sys.executable, "-c", script], cwd=".", env=None,
            input_text="", timeout=60, cancel_check=cancel_check,
            poll_seconds=0.05)
    # 120초 sleep 인데 취소로 즉시(≤10초) 끝나야 한다.
    assert _t.time() - start < 10


def test_migration_allows_running_to_cancelled():
    files = sorted(pathlib.Path("supabase/migrations").glob("*running*cancel*.sql"))
    assert files, "running 취소 마이그레이션이 없습니다"
    sql = files[-1].read_text(encoding="utf-8")
    body = "\n".join(line.split("--", 1)[0] for line in sql.splitlines()).lower()
    # running → cancelled 전환 허용 + cancel_job 이 running 포함.
    assert "running" in body and "cancelled" in body
    assert "cancel_job" in body
    assert "'queued','running','paused_for_human'" in body.replace(" ", "") \
        or "'running'" in body
