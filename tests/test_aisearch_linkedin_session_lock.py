"""V1 독립검증 결함4 — 링크드인 RPS 기기 간 세션 락.

goal: docs/engineering/aisearch-fleet-next-steps-goal-2026-08-01.md (V1 findings #4)
"""
from __future__ import annotations

import time

import pytest

from apps.aisearch.core.session_lock import (
    LinkedInSessionLock,
    LinkedInSessionLockError,
)


def test_second_owner_is_rejected_while_first_holds_lock(tmp_path):
    lock_dir = tmp_path / "linkedin_rps"
    lock_a = LinkedInSessionLock(lock_dir=lock_dir, owner="macmini")
    lock_b = LinkedInSessionLock(lock_dir=lock_dir, owner="macbook")

    lock_a.acquire()
    try:
        with pytest.raises(LinkedInSessionLockError, match="macmini"):
            lock_b.acquire()
    finally:
        lock_a.release()


def test_release_then_reacquire_by_another_owner_succeeds(tmp_path):
    lock_dir = tmp_path / "linkedin_rps"
    lock_a = LinkedInSessionLock(lock_dir=lock_dir, owner="macmini")
    lock_a.acquire()
    lock_a.release()

    lock_b = LinkedInSessionLock(lock_dir=lock_dir, owner="macbook")
    lock_b.acquire()  # 이전 소유자가 풀었으니 성공해야 함
    lock_b.release()


def test_context_manager_releases_on_exception():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        lock_dir = Path(tmp) / "linkedin_rps"
        with pytest.raises(ValueError):
            with LinkedInSessionLock(lock_dir=lock_dir, owner="macmini"):
                raise ValueError("작업 중 실패")
        # 예외가 나도 락 디렉터리는 해제돼 다음 owner 가 즉시 획득 가능해야 한다.
        LinkedInSessionLock(lock_dir=lock_dir, owner="macbook").acquire()


def test_stale_lock_past_threshold_is_reclaimed_but_live_lock_is_not(tmp_path):
    """정책 개정(2026-07-31 전수 리뷰 F8).

    이전 정책은 "stale 이어도 자동 회수 금지 — 사람이 수동 해제"였다. 그런데
    프로세스가 한 번 강제 종료되면 락이 그대로 남아, 이후 **모든 실행**에서
    링크드인 채널이 실패하고 그 예외가 파이프라인 전체를 aborted 로 만들었다
    (사람인·잡코리아 결과까지 폐기). 사람 손 없이는 복구 불가능한 상태를 코드가
    스스로 만드는 것은 SOT 불변식 2("멈추고 방치하지 않는다")에 어긋난다.

    새 정책: **오래된(stale) 락만** 회수한다. 살아 있는 보유자의 락은 여전히
    절대 탈취하지 않는다(E4: 계정당 동시 1기기).
    """
    lock_dir = tmp_path / "linkedin_rps"
    old = LinkedInSessionLock(lock_dir=lock_dir, owner="macmini", stale_seconds=0.01)
    old.acquire()
    time.sleep(0.05)  # stale_seconds 를 넘김 — 보유자가 죽은 것으로 간주된다

    fresh = LinkedInSessionLock(lock_dir=lock_dir, owner="macbook", stale_seconds=0.01)
    fresh.acquire()  # 회수 성공 — 영구 정지 없음
    try:
        # 살아 있는 락은 여전히 탈취 금지.
        other = LinkedInSessionLock(
            lock_dir=lock_dir, owner="windows", stale_seconds=3600.0
        )
        with pytest.raises(LinkedInSessionLockError):
            other.acquire()
    finally:
        fresh.release()


def test_corrupted_meta_fails_closed_not_silent_success(tmp_path):
    lock_dir = tmp_path / "linkedin_rps"
    lock_dir.mkdir(parents=True)
    (lock_dir / "owner.json").write_text("not json", encoding="utf-8")

    with pytest.raises(LinkedInSessionLockError):
        LinkedInSessionLock(lock_dir=lock_dir, owner="macbook").acquire()
