"""함대 heartbeat + watchdog (2026-07-11, 단계 G).

설계 근거: docs/prompts/fleet-control-sequential-prompts-2026-07-11.md §프롬프트 G.
- 워커가 1분마다 machine_heartbeats 에 심장박동을 남긴다(record_heartbeat RPC).
- watchdog(맥미니 상주)이 stale 머신(마지막 beat 5분 초과 또는 행 없음)을 OPS_HEALTH 로 경보.
- 중복 경보 30분 억제. webhook/notify 실패는 fail-soft(watchdog 은 죽지 않는다).
PR#66 이 못 잡는 "죽었는데 아무도 모름"을 막는 층.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .job_queue import FLEET_MACHINES, is_valid_machine_id

REPO = Path(__file__).resolve().parents[2]

STALE_SECONDS = 300      # 5분 무응답 → stale
ALERT_SUPPRESS_SECONDS = 1800  # 30분 중복 경보 억제
QUEUED_STALL_SECONDS = 600  # SOT31(구 SOT30) S2 — queued 가 10분 초과 미claim 이면 고착 경보
# QA-1(2026-07-13): claude 잡 상한 2400s(fleet_worker.CLAUDE_TIMEOUT_SECONDS)보다 넉넉히
# 길게 — 정상 40분 잡을 고아로 오판하지 않으면서, 워커 급사로 release 를 못 한
# running 고아(+account_locks 잔존 → 머신 큐 데드락)를 가시화한다.
RUNNING_STALL_SECONDS = 3000


def heartbeat_payload(machine: Any, *, worker_pid: int, now_iso: str,
                      linkedin_rps_logged_in: bool = False) -> dict[str, Any]:
    if not is_valid_machine_id(machine):
        raise ValueError(f"invalid machine id: {machine!r}")
    return {"machine": machine, "beat_at": now_iso, "worker_pid": int(worker_pid),
            "linkedin_rps_logged_in": bool(linkedin_rps_logged_in)}


# ── 이슈 D(2026-07-15, 사장님 SOT29 §2 개정 승인) — LinkedIn 로그인 머신 라우팅 ──

PORTAL_STATUS_RELPATH = "artifacts/portal_session_status_latest.json"
# 프리플라이트(portal_login.py)는 상시 도는 게 아니라 세션 준비 시 도므로,
# heartbeat(60s)와 달리 하루 안의 상태 파일은 신뢰한다(포털 세션 수명 기준).
PORTAL_STATUS_MAX_AGE_SECONDS = 86400

# SOT29 INV8 신뢰도: macmini > winpc > macbook
_LINKEDIN_MACHINE_PRIORITY: tuple[str, ...] = ("macmini", "winpc", "macbook")
_LINKEDIN_FALLBACK_MACHINE = "macmini"


def _iso_to_epoch(value: Any) -> int | None:
    from datetime import datetime, timezone
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def linkedin_rps_logged_in_from_status(
    payload: Any, *, now_epoch: int,
    max_age_seconds: int = PORTAL_STATUS_MAX_AGE_SECONDS,
) -> bool:
    """portal_session_status_latest.json → LinkedIn RPS 로그인 여부(순수, fail-closed).

    generated_at 이 없거나 깨졌거나 max_age 초과면 신뢰하지 않는다(False).
    """
    if not isinstance(payload, Mapping):
        return False
    gen_epoch = _iso_to_epoch(payload.get("generated_at"))
    if gen_epoch is None:
        return False
    age = now_epoch - gen_epoch
    # V1 blocker 수용: 미래 시각(음수 나이)도 거부 — 시계 튐/조작 파일이 무한 신뢰되는 것 차단.
    # 정상 시계 오차만 허용(300s).
    if age < -300 or age > max_age_seconds:
        return False
    sessions = payload.get("portal_sessions")
    if not isinstance(sessions, Sequence):
        return False
    for entry in sessions:
        if isinstance(entry, Mapping) and entry.get("channel") == "linkedin_rps":
            return entry.get("ready") is True
    return False


def read_linkedin_login_flag(
    repo_root: Path, *, now_epoch: int,
    max_age_seconds: int = PORTAL_STATUS_MAX_AGE_SECONDS,
) -> bool:
    """머신 로컬 상태 파일을 읽어 LinkedIn 로그인 여부 반환 — 파일 없음/깨짐 = False."""
    try:
        payload = json.loads((repo_root / PORTAL_STATUS_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return linkedin_rps_logged_in_from_status(
        payload, now_epoch=now_epoch, max_age_seconds=max_age_seconds)


def pick_linkedin_machine(
    rows: Sequence[Mapping[str, Any]], *, now_epoch: int,
) -> str:
    """heartbeat 행들 중 LinkedIn 로그인 + fresh(STALE_SECONDS 이내)인 머신 선택(순수).

    우선순위는 SOT29 INV8 신뢰도(macmini > winpc > macbook).
    후보 없으면 macmini 폴백(무동작보다 낫다 — 사장님 승인 설계, fail-safe).
    """
    ready: set[str] = set()
    for r in rows or ():
        if not isinstance(r, Mapping):
            continue
        machine, epoch = r.get("machine"), r.get("beat_at_epoch")
        if (
            not isinstance(machine, str)
            or not is_valid_machine_id(machine)
            or not isinstance(epoch, int)
        ):
            continue
        if (now_epoch - epoch) > STALE_SECONDS:
            continue
        if r.get("linkedin_rps_logged_in") is True:
            ready.add(machine)
    for machine in _LINKEDIN_MACHINE_PRIORITY:
        if machine in ready:
            return machine
    dynamic_ready = sorted(ready.difference(_LINKEDIN_MACHINE_PRIORITY))
    if dynamic_ready:
        return dynamic_ready[0]
    return _LINKEDIN_FALLBACK_MACHINE


def stale_machines(
    rows: Sequence[Mapping[str, Any]],
    *,
    now_epoch: int,
    expected: Sequence[str] = FLEET_MACHINES,
) -> list[str]:
    """마지막 beat 가 STALE_SECONDS 초과인 머신 + 아예 행이 없는 expected 머신.

    입력 rows: [{"machine": str, "beat_at_epoch": int}, ...]
    반환: stale 머신 목록(expected 순서 유지).
    """
    latest: dict[str, int] = {}
    for r in rows:
        m = r.get("machine")
        epoch = r.get("beat_at_epoch")
        if m is None or epoch is None:
            continue
        if m not in latest or epoch > latest[m]:
            latest[m] = int(epoch)
    stale: list[str] = []
    for m in expected:
        beat = latest.get(m)
        if beat is None or (now_epoch - beat) > STALE_SECONDS:
            stale.append(m)
    return stale


def _created_epoch(row: Mapping[str, Any]) -> int | None:
    """행에서 생성 시각 epoch 을 뽑는다. created_at_epoch(int) 우선, 없으면 created_at(ISO).

    해석 불가면 None — 호출부(stalled_queued_jobs)가 fail-closed 로 '고착' 취급한다.
    """
    raw = row.get("created_at_epoch")
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    iso = row.get("created_at")
    if isinstance(iso, str) and iso.strip():
        from datetime import datetime
        try:
            return int(datetime.fromisoformat(iso.strip()).timestamp())
        except ValueError:
            return None
    return None


def stalled_queued_jobs(
    rows: Sequence[Mapping[str, Any]],
    *,
    now_epoch: int,
    stall_seconds: int = QUEUED_STALL_SECONDS,
) -> list[dict[str, Any]]:
    """SOT31(구 SOT30) S2 — queued 상태로 stall_seconds *초과* 방치된 잡 목록.

    - status != "queued" 는 제외(고착 개념이 없음).
    - 생성 시각을 증명 못 하는 queued 행(결손·비정수·ISO 해석불가)은 신선하다고
      가정하지 않고 포함한다(fail-closed) — age_seconds=None 으로 표시.
    반환 행: {"id", "machine", "age_seconds"}
    """
    stalled: list[dict[str, Any]] = []
    for r in rows:
        if r.get("status") != "queued":
            continue
        created = _created_epoch(r)
        if created is None:
            stalled.append({"id": r.get("id"), "machine": r.get("machine"),
                            "age_seconds": None})
            continue
        age = now_epoch - created
        if age > stall_seconds:
            stalled.append({"id": r.get("id"), "machine": r.get("machine"),
                            "age_seconds": age})
    return stalled


def stalled_running_jobs(
    rows: Sequence[Mapping[str, Any]],
    *,
    now_epoch: int,
    stall_seconds: int = RUNNING_STALL_SECONDS,
) -> list[dict[str, Any]]:
    """QA-1 — running 상태로 stall_seconds *초과* 방치된 잡(워커 급사 고아 의심).

    running 잡은 정상이라도 최대 2400s(claude 타임아웃) 걸리므로 한도가 더 길다.
    시작 시각을 증명 못 하는 running 행은 fail-closed 로 포함(age_seconds=None).
    """
    stalled: list[dict[str, Any]] = []
    for r in rows:
        if r.get("status") != "running":
            continue
        started = r.get("started_at_epoch")
        if not isinstance(started, int) or isinstance(started, bool):
            iso = r.get("started_at")
            started = None
            if isinstance(iso, str) and iso.strip():
                from datetime import datetime
                try:
                    started = int(datetime.fromisoformat(iso.strip()).timestamp())
                except ValueError:
                    started = None
        if started is None:
            stalled.append({"id": r.get("id"), "machine": r.get("machine"),
                            "age_seconds": None})
            continue
        age = now_epoch - started
        if age > stall_seconds:
            stalled.append({"id": r.get("id"), "machine": r.get("machine"),
                            "age_seconds": age})
    return stalled


def heartbeat_ages(
    rows: Sequence[Mapping[str, Any]],
    *,
    now_epoch: int,
    expected: Sequence[str] = FLEET_MACHINES,
) -> dict[str, int | None]:
    """SOT31(구 SOT30) 인수기준 3 — 머신별 마지막 heartbeat 나이(초). beat 없으면 None.

    입력 rows: heartbeats_epoch RPC 형상 [{"machine", "beat_at_epoch"}, ...]
    """
    latest: dict[str, int] = {}
    for r in rows:
        m = r.get("machine")
        epoch = r.get("beat_at_epoch")
        if m is None or not isinstance(epoch, int) or isinstance(epoch, bool):
            continue
        if m not in latest or epoch > latest[m]:
            latest[m] = epoch
    return {m: (now_epoch - latest[m]) if m in latest else None for m in expected}


def should_alert(machine: str, *, last_alert_epoch: int | None, now_epoch: int) -> bool:
    if last_alert_epoch is None:
        return True
    return (now_epoch - last_alert_epoch) > ALERT_SUPPRESS_SECONDS


def _load_env_line(key: str) -> str:
    import os
    if (os.environ.get(key) or "").strip():
        return os.environ[key].strip()
    bases: list[Path] = []
    if os.environ.get("VALUEHIRE_REPO_DIR"):
        bases.append(Path(os.environ["VALUEHIRE_REPO_DIR"]))
    cur, home = REPO, Path.home()
    while True:
        bases.append(cur)
        if cur == home or cur.parent == cur:
            break
        cur = cur.parent
    for base in bases:
        env = base / ".env.local"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def health_notify(text: str) -> None:
    """OPS_HEALTH webhook 으로 경보(fail-soft)."""
    url = _load_env_line("DISCORD_WEBHOOK_URL_OPS_HEALTH")
    if not url:
        print(f"[watchdog] OPS_HEALTH webhook 없음 — 경보 생략: {text[:80]}", file=sys.stderr)
        return
    req = urllib.request.Request(
        url, data=json.dumps({"content": text[:1900]}).encode(),
        method="POST", headers={"Content-Type": "application/json",
                                "User-Agent": "ValuehireWatchdog/1.0"})
    urllib.request.urlopen(req, timeout=20)


class Watchdog:
    def __init__(
        self,
        *,
        fetch_heartbeats: Callable[[int], Sequence[Mapping[str, Any]]],
        notify: Callable[[str], None] = health_notify,
        load_alert_state: Callable[[], dict[str, int]] = lambda: {},
        save_alert_state: Callable[[dict[str, int]], None] = lambda s: None,
        expected: Sequence[str] = FLEET_MACHINES,
        fetch_queued_jobs: Callable[[int], Sequence[Mapping[str, Any]]] | None = None,
        fetch_running_jobs: Callable[[int], Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self.fetch_heartbeats = fetch_heartbeats
        self.notify = notify
        self.load_alert_state = load_alert_state
        self.save_alert_state = save_alert_state
        self.expected = tuple(expected)
        self.fetch_queued_jobs = fetch_queued_jobs  # SOT31(구 SOT30) S2 — None 이면 기존 동작 그대로
        self.fetch_running_jobs = fetch_running_jobs  # QA-1 — running 고아 가시화

    def _alert(self, key: str, text: str, state: dict[str, int],
               alerted: list[str], now_epoch: int) -> None:
        """경보 1건(억제·전송실패 규율 공통). 실패 시 억제 안 함 → 다음 주기 재시도."""
        if not should_alert(key, last_alert_epoch=state.get(key), now_epoch=now_epoch):
            return
        try:
            self.notify(text)
        except Exception as exc:  # noqa: BLE001 — watchdog 은 죽지 않는다
            # V1 결함4: 전송 실패 시 억제(state)·alerted 표기 안 함 → 다음 주기 재시도.
            #           실장애를 "경보함"으로 은폐하지 않는다.
            print(f"[watchdog] 경보 전송 실패(다음 주기 재시도): {exc}", file=sys.stderr)
            return
        state[key] = now_epoch
        alerted.append(key)

    def run_once(self, *, now_epoch: int) -> list[str]:
        """stale 머신 + queued 고착 잡 경보(억제 반영). 반환: 경보한 키 목록.

        키: 머신 이름("macmini") 또는 고착 잡("job:16").
        """
        rows = self.fetch_heartbeats(now_epoch)
        stale = stale_machines(rows, now_epoch=now_epoch, expected=self.expected)
        state = self.load_alert_state()
        alerted: list[str] = []
        for m in stale:
            self._alert(
                m,
                (f"🚨 함대 경보: 머신 '{m}' 이(가) {STALE_SECONDS // 60}분 넘게 "
                 f"응답이 없습니다. 워커/전원/네트워크를 확인해 주세요."),
                state, alerted, now_epoch)
        if self.fetch_queued_jobs is not None:
            try:
                job_rows = self.fetch_queued_jobs(now_epoch)
            except Exception as exc:  # noqa: BLE001 — 잡 조회 실패가 머신 경보를 막으면 안 됨
                print(f"[watchdog] queued 잡 조회 실패(다음 주기 재시도): {exc}",
                      file=sys.stderr)
                job_rows = []
            for j in stalled_queued_jobs(job_rows, now_epoch=now_epoch):
                age = j.get("age_seconds")
                age_txt = f"{age // 60}분" if isinstance(age, int) else "확인불가(시각결손)"
                self._alert(
                    f"job:{j.get('id')}",
                    (f"🚨 함대 경보: 잡 #{j.get('id')} (machine={j.get('machine')}) 이(가) "
                     f"{age_txt} 동안 queued 고착 — '{j.get('machine')}' 일꾼이 잡을 "
                     f"집어가지 않습니다. worker 가동/열쇠(401)를 확인해 주세요."),
                    state, alerted, now_epoch)
        if self.fetch_running_jobs is not None:
            try:
                run_rows = self.fetch_running_jobs(now_epoch)
            except Exception as exc:  # noqa: BLE001 — 조회 실패가 다른 경보를 막으면 안 됨
                print(f"[watchdog] running 잡 조회 실패(다음 주기 재시도): {exc}",
                      file=sys.stderr)
                run_rows = []
            for j in stalled_running_jobs(run_rows, now_epoch=now_epoch):
                age = j.get("age_seconds")
                age_txt = f"{age // 60}분" if isinstance(age, int) else "확인불가(시각결손)"
                self._alert(
                    f"job:{j.get('id')}",
                    (f"🚨 함대 경보: 잡 #{j.get('id')} (machine={j.get('machine')}) 이(가) "
                     f"{age_txt} 동안 running 고착 — 워커 급사 고아 의심. 이 잡의 계정락이 "
                     f"남아 '{j.get('machine')}' 큐가 막힐 수 있습니다(수동 정리 필요)."),
                    state, alerted, now_epoch)
        self.save_alert_state(state)
        return alerted


def beat_loop(
    beat_fn: Callable[[], None],
    stop_event: Any,
    *,
    interval: int = 60,
) -> None:
    """잡 실행과 무관하게 interval 마다 심장박동(별도 스레드).

    V1 결함1: 워커 loop 은 최대 40분 잡에 블로킹되므로 loop 상단 heartbeat 만으로는
    정상 머신이 stale 오경보된다. 심장박동을 잡 처리와 분리한다.
    stop_event 는 threading.Event 호환(.is_set(), .wait(t)).
    """
    while not stop_event.is_set():
        try:
            beat_fn()
        except Exception as exc:  # noqa: BLE001 — 심장박동 실패는 스레드를 죽이지 않는다
            print(f"[fleet] heartbeat 스레드 예외(fail-soft): {exc}", file=sys.stderr)
        stop_event.wait(interval)
