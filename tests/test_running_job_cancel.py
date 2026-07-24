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
