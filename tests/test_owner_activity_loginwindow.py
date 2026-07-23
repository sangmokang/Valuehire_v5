"""이슈 #192 — 잠금화면(loginwindow)에서 감지기 에러 → 워커 영구 양보 버그.

2026-07-24 03:3x 라이브 실측: 화면이 잠기면 osascript `{name, unix id}` 복합 질의가
-1728 로 실패한다(frontmost = loginwindow 는 복합 속성 조회 불가). 감지기는
(None, None) → `detector_unavailable` → fail-closed '사장님 활동 중' 판정이 되어,
사장님이 주무시는 밤 내내 워커가 claim 을 양보한다(큐 잡 방치 — SOT29 INV9 위반).

인수 기준: 이 파일이 GREEN.
- 복합 질의 실패 시 name 단독 질의로 폴백한다.
- frontmost 가 loginwindow(잠금화면)면 크롬 아님으로 판정 — idle 이 충분하면
  양보하지 않는다(owner_activity_detected=False).
- 두 질의 모두 실패하면 기존 fail-closed(양보) 유지.
"""
from __future__ import annotations

import subprocess

from tools.multi_position_sourcing import owner_activity as oa


def _fake_run(combined_rc: int, combined_out: str,
              name_rc: int = 0, name_out: str = "loginwindow",
              idle_out: str = '"HIDIdleTime" = 656000000000'):
    """osascript 복합/단독, ioreg idle 호출을 흉내내는 run_command."""

    def run_command(argv, **kwargs):
        joined = " ".join(argv)
        if "unix id" in joined:
            return subprocess.CompletedProcess(
                argv, combined_rc, stdout=combined_out,
                stderr="" if combined_rc == 0 else "execution error: -1728")
        if "osascript" in joined:
            return subprocess.CompletedProcess(argv, name_rc, stdout=name_out, stderr="")
        # idle 판독(ioreg 등)은 성공으로 흉내.
        return subprocess.CompletedProcess(argv, 0, stdout=idle_out, stderr="")

    return run_command


def test_frontmost_falls_back_to_name_only_query():
    name, pid = oa._macos_frontmost_app_and_pid(
        _fake_run(combined_rc=1, combined_out=""))
    assert name == "loginwindow"
    assert pid is None


def test_locked_screen_is_not_owner_activity():
    snap = oa.detect_owner_activity_snapshot(
        run_command=_fake_run(combined_rc=1, combined_out=""),
        system_name="Darwin",
    )
    assert snap.owner_activity_detected is False
    assert snap.foreground_app == "loginwindow"


def test_both_queries_failing_stays_fail_closed():
    snap = oa.detect_owner_activity_snapshot(
        run_command=_fake_run(combined_rc=1, combined_out="",
                              name_rc=1, name_out=""),
        system_name="Darwin",
    )
    assert snap.owner_activity_detected is True


def test_combined_query_success_path_unchanged():
    snap = oa.detect_owner_activity_snapshot(
        run_command=_fake_run(combined_rc=0, combined_out="Code, 1234"),
        system_name="Darwin",
    )
    # 앞창이 크롬이 아니면 3사 개입 아님 — 양보하지 않는다(기존 계약 유지).
    assert snap.owner_activity_detected is False
    assert snap.foreground_app == "Code"
