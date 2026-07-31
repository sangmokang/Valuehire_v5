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


def test_stale_lock_past_threshold_is_not_silently_stolen(tmp_path):
    """오래된 락도 자동 탈취하지 않는다 — 사람 확인 후 수동 해제가 정책."""
    lock_dir = tmp_path / "linkedin_rps"
    old = LinkedInSessionLock(lock_dir=lock_dir, owner="macmini", stale_seconds=0.01)
    old.acquire()
    time.sleep(0.05)  # stale_seconds 를 넘김

    fresh = LinkedInSessionLock(lock_dir=lock_dir, owner="macbook", stale_seconds=0.01)
    with pytest.raises(LinkedInSessionLockError):
        fresh.acquire()  # stale 이어도 자동 탈취 금지 — 여전히 실패


def test_corrupted_meta_fails_closed_not_silent_success(tmp_path):
    lock_dir = tmp_path / "linkedin_rps"
    lock_dir.mkdir(parents=True)
    (lock_dir / "owner.json").write_text("not json", encoding="utf-8")

    with pytest.raises(LinkedInSessionLockError):
        LinkedInSessionLock(lock_dir=lock_dir, owner="macbook").acquire()
