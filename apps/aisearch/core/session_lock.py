"""V1 독립검증 결함4 — 링크드인 RPS 단일세션 락(기기 간, SOT29 비의존 독립 구현).

`orchestrator.py`의 기존 `threading.RLock`(PipelineDeps.lock)은 같은 프로세스
안의 스레드만 막는다 — 맥미니와 맥북에서 각자 프로세스를 띄우면 서로를 전혀
모른다(E4 위반: 링크드인 계정 = 동시 1기기). 이 모듈은 SOT29 함대 인프라를
재사용하지 않고(오너 결정: 완전 독립 구조) 원자적 `mkdir` 파일락만으로 기기
간 배타를 구현한다.

**중요한 전제**: 이 락이 실제로 기기 간 배타를 보장하려면 `lock_dir`이
**여러 기기에서 공유되는 저장소**(예: 네트워크 드라이브, iCloud/Dropbox 동기화
폴더) 위에 있어야 한다. 로컬 전용 경로(`~/.valuehire/...`)를 쓰면 그 기기
안에서만 유효하고, 다른 기기의 동시 실행은 여전히 못 막는다 — 호출자가
실제 공유 경로를 넘겨야 한다(이 모듈은 경로의 공유 여부를 검증하지 않는다).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_STALE_SECONDS = 3600.0  # 이 시간 넘게 갱신 없는 락은 죽은 락으로 간주


class LinkedInSessionLockError(RuntimeError):
    """다른 프로세스/기기가 이미 링크드인 세션 락을 보유 중 — fail-closed."""


@dataclass
class LinkedInSessionLock:
    """컨텍스트 매니저 — `with lock:` 진입 시 획득, 이탈 시 해제."""

    lock_dir: Path
    owner: str
    stale_seconds: float = DEFAULT_STALE_SECONDS
    _acquired: bool = field(default=False, init=False, repr=False)

    def _meta_path(self) -> Path:
        return self.lock_dir / "owner.json"

    def _read_meta(self) -> Optional[dict]:
        try:
            return json.loads(self._meta_path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 손상/부재는 판독 실패로 처리
            return None

    def acquire(self) -> None:
        try:
            self.lock_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            meta = self._read_meta()
            age = time.time() - meta.get("acquired_at", 0.0) if meta else None
            if meta is not None and age is not None and age < self.stale_seconds:
                raise LinkedInSessionLockError(
                    f"링크드인 세션 락 보유 중: owner={meta.get('owner')!r} "
                    f"pid={meta.get('pid')} ({age:.0f}초 전 획득) — fail-closed"
                ) from exc
            # 오래됐거나(stale) 메타를 못 읽은 락 — 자동 탈취하지 않는다(경합
            # 위험). 사람이 상태를 확인한 뒤 수동으로 지워야 한다.
            raise LinkedInSessionLockError(
                f"오래됐거나 손상된 락 발견({self.lock_dir}) — 자동 탈취 금지, "
                "사람 확인 후 수동 해제 필요"
            ) from exc
        self._meta_path().write_text(
            json.dumps(
                {"owner": self.owner, "acquired_at": time.time(), "pid": os.getpid()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self._acquired = True

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            try:
                self._meta_path().unlink()
            except FileNotFoundError:
                pass
            self.lock_dir.rmdir()
        finally:
            self._acquired = False

    def __enter__(self) -> "LinkedInSessionLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()


def default_linkedin_session_lock(*, owner: str, machine: str) -> LinkedInSessionLock:
    """기본 락 경로 — 로컬 전용(`~/.valuehire`). 진짜 기기 간 배제가 필요하면
    호출자가 공유 스토리지 경로로 오버라이드해야 한다(위 모듈 docstring 참고)."""
    lock_dir = Path.home() / ".valuehire" / "aisearch_locks" / "linkedin_rps"
    return LinkedInSessionLock(lock_dir=lock_dir, owner=f"{owner}@{machine}")
