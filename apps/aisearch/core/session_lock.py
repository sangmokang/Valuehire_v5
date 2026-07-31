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

2026-07-31 전수 리뷰 수정:
- F8: 크래시로 남은 **오래된(stale)** 락은 자동 회수한다. 예전에는 어떤 경우에도
  자동 회수를 하지 않아, 한 번 죽으면 링크드인 채널이 매 실행 실패하고 그
  예외가 파이프라인 전체를 aborted 로 만들었다(사람인·잡코리아 결과까지 폐기).
  사람 손 없이는 복구 불가능한 상태를 코드가 스스로 만들면 안 된다.
- F9: `mkdir` 성공과 메타 기록 사이의 창에서 진 쪽이 "손상된 락 — 수동 해제"로
  오진단됐다. 짧은 유예 동안 메타가 나타나길 기다려 **정상 경합**으로 보고한다.
- F10: `owner.json` 이 dict 가 아니면 `AttributeError` 로 터졌다 — 타입까지 검증한다.

살아 있는 보유자의 락은 어떤 경우에도 탈취하지 않는다(E4 불변).
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

DEFAULT_STALE_SECONDS = 3600.0  # 이 시간 넘게 갱신 없는 락은 죽은 락으로 간주
#: F9 — mkdir 직후 메타 기록 전 창을 정상 경합으로 판정하기 위한 유예(초).
DEFAULT_META_GRACE_SECONDS = 1.0


class LinkedInSessionLockError(RuntimeError):
    """다른 프로세스/기기가 이미 링크드인 세션 락을 보유 중 — fail-closed."""


@dataclass
class LinkedInSessionLock:
    """컨텍스트 매니저 — `with lock:` 진입 시 획득, 이탈 시 해제."""

    lock_dir: Path
    owner: str
    stale_seconds: float = DEFAULT_STALE_SECONDS
    meta_grace_seconds: float = DEFAULT_META_GRACE_SECONDS
    clock: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    _acquired: bool = field(default=False, init=False, repr=False)
    #: V1 2라운드 — 이 인스턴스가 획득한 락을 식별하는 1회용 표식.
    #: owner 이름·pid 만으로는 부족하다(같은 기기·같은 이름이 다시 뜰 수 있다).
    #: heartbeat/release 는 메타의 token 이 이 값과 같을 때만 동작한다 —
    #: 죽었다 되살아난 프로세스가 남의 락을 덮어쓰거나 지우는 것을 막는다.
    _token: str = field(default_factory=lambda: uuid.uuid4().hex, init=False, repr=False)

    def _meta_path(self) -> Path:
        return self.lock_dir / "owner.json"

    def _read_meta(self) -> Optional[dict]:
        """메타를 읽는다. 부재·파싱 실패·**dict 아님**은 전부 판독 실패(F10)."""
        try:
            data = json.loads(self._meta_path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 손상/부재는 판독 실패로 처리
            return None
        return data if isinstance(data, dict) else None

    def _age_of(self, meta: dict) -> Optional[float]:
        """마지막 **생존 신호** 이후 경과 시간.

        자체 적대검증 발견: 획득 시각(acquired_at)만 보면, 한 시간 넘게 정상
        실행 중인 락이 stale 로 오인돼 다른 기기에 탈취된다(E4 위반 — 계정당
        동시 1기기). 그래서 heartbeat 가 갱신하는 last_seen_at 을 우선 본다.
        """
        for key in ("last_seen_at", "acquired_at"):
            value = meta.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return self.clock() - float(value)
        return None

    def _wait_for_meta(self) -> Optional[dict]:
        """F9 — 메타가 아직 안 써진 '경합 순간'을 유예 동안 기다려 본다."""
        meta = self._read_meta()
        if meta is not None or self.meta_grace_seconds <= 0:
            return meta
        deadline = self.clock() + self.meta_grace_seconds
        step = min(0.05, self.meta_grace_seconds)
        while self.clock() < deadline:
            self.sleep(step)
            meta = self._read_meta()
            if meta is not None:
                return meta
        return None

    def _dir_age(self) -> Optional[float]:
        try:
            return self.clock() - self.lock_dir.stat().st_mtime
        except OSError:
            return None

    def _reclaim(self) -> None:
        """죽은 락 회수 — 디렉터리를 통째로 지운다(내용은 메타 하나뿐)."""
        shutil.rmtree(self.lock_dir, ignore_errors=True)

    def _write_meta(self, *, acquired_at: Optional[float] = None) -> None:
        # 원자적 교체 — 반쯤 쓰인 메타가 다른 기기에 읽히지 않게 한다.
        now = self.clock()
        tmp = self._meta_path().with_name("owner.json.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "owner": self.owner,
                    "acquired_at": now if acquired_at is None else acquired_at,
                    "last_seen_at": now,
                    "pid": os.getpid(),
                    "token": self._token,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self._meta_path())

    def heartbeat(self) -> None:
        """살아 있음을 알린다 — 장시간 실행이 stale 로 오인되지 않게 한다.

        보유 중이 아니면 아무 것도 하지 않는다. 기록 실패는 삼킨다(심장박동
        실패가 검색 자체를 멈추면 안 된다 — 실패가 이어지면 stale 회수로 자연
        수렴한다). 호출자는 stale_seconds 보다 촘촘히 불러야 한다.
        """
        if not self._acquired:
            return
        meta = self._read_meta() or {}
        if meta.get("token") != self._token:
            # 내 락이 아니다 — 그 사이 회수되어 다른 기기가 가져갔다.
            self._acquired = False
            return
        acquired_at = meta.get("acquired_at")
        try:
            self._write_meta(
                acquired_at=acquired_at
                if isinstance(acquired_at, (int, float)) and not isinstance(acquired_at, bool)
                else None
            )
        except OSError:
            pass

    def acquire(self) -> None:
        for attempt in (1, 2):  # 회수 후 딱 한 번만 재시도(무한 탈취 경쟁 금지)
            try:
                self.lock_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError as exc:
                if attempt == 2:
                    raise LinkedInSessionLockError(
                        f"링크드인 세션 락 재획득 실패({self.lock_dir}) — 회수 직후 "
                        "다른 기기가 먼저 가져갔다(경합), fail-closed"
                    ) from exc
                meta = self._wait_for_meta()
                if meta is not None and self._age_of(meta) is None:
                    # V1 3차 — 시각이 없는 메타(예: `{}`)를 "살아 있음"으로 보면
                    # 죽은 락이 영원히 남는다. 시각 없는 메타는 손상으로 보고
                    # 디렉터리 나이로 판정한다(아래 경로와 동일).
                    meta = None
                if meta is not None:
                    age = self._age_of(meta)
                    if age is None or age < self.stale_seconds:
                        # 살아 있는 보유자 — 절대 탈취하지 않는다(E4: 계정당 1기기).
                        raise LinkedInSessionLockError(
                            f"링크드인 세션 락 보유 중: owner={meta.get('owner')!r} "
                            f"pid={meta.get('pid')}"
                            + (f" ({age:.0f}초 전 획득)" if age is not None else "")
                            + " — fail-closed"
                        ) from exc
                    # F8 — stale 로 보이지만, 회수는 되돌릴 수 없으므로 한 번 더
                    # 확인한다(V1 3라운드): 유예 시간 뒤 last_seen_at 이 바뀌었다면
                    # 보유자는 살아 있다(느린 기기·시계 차이). 그때는 절대 뺏지 않는다.
                    before = meta.get("last_seen_at")
                    if self.meta_grace_seconds > 0:
                        self.sleep(self.meta_grace_seconds)
                    recheck = self._read_meta()
                    if recheck is not None:
                        if recheck.get("last_seen_at") != before:
                            raise LinkedInSessionLockError(
                                "링크드인 세션 락 보유자가 살아 있다(생존 신호 갱신 확인) "
                                "— 회수하지 않는다, fail-closed"
                            ) from exc
                        age2 = self._age_of(recheck)
                        if age2 is not None and age2 < self.stale_seconds:
                            raise LinkedInSessionLockError(
                                "링크드인 세션 락 보유 중(재확인) — fail-closed"
                            ) from exc
                    self._reclaim()
                    continue
                # 메타를 끝내 못 읽었다. 두 가지 경우가 있다:
                #  (a) 방금 mkdir 한 다른 기기가 아직 메타를 안 썼다(정상 경합)
                #  (b) 크래시로 메타 없이 디렉터리만 남았다(죽은 락)
                # 디렉터리 나이로 가른다 — 오래됐으면 (b) 로 보고 회수한다.
                dir_age = self._dir_age()
                if dir_age is not None and dir_age >= self.stale_seconds:
                    self._reclaim()
                    continue
                raise LinkedInSessionLockError(
                    f"링크드인 세션 락 보유 중({self.lock_dir}) — 다른 기기가 방금 "
                    "획득해 메타 기록 전이다(정상 경합), fail-closed"
                ) from exc
            else:
                self._write_meta()
                self._acquired = True
                return

    def _owns_lock(self) -> bool:
        meta = self._read_meta()
        return bool(meta and meta.get("token") == self._token)

    def release(self) -> None:
        if not self._acquired:
            return
        if not self._owns_lock():
            # V1 2라운드 — 이미 회수되어 다른 기기가 보유 중이다. 남의 락을
            # 지우면 두 기기가 동시에 링크드인에 붙는다(E4 위반).
            self._acquired = False
            return
        try:
            try:
                self._meta_path().unlink()
            except FileNotFoundError:
                pass
            self.lock_dir.rmdir()
        except OSError:
            # 해제 실패가 파이프라인 결과를 덮지 않도록 한다 — 남은 락은 다음
            # 실행에서 stale 회수 대상이 된다(F8).
            pass
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
