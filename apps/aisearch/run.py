"""apps/aisearch 프로덕션 엔트리포인트 — V1 4차 진입점 결함 3건 해소.

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §2/§4. JD 파일 경로를
받아 cdp_driver(raw CDP 어댑터) + run_search_pipeline 을 조립·실행한다.

3단계 실행 모드(4차 진입점 결함 — --live 없이도 브라우저에 붙던 것 재설계):
- **기본 = plan-only**: 브라우저 무접촉(CDP 연결 시도 0). AC1 검색 플랜과
  AC2 포털 디스크립터를 만들어 검증·출력만 한다.
- **--browser**: 브라우저 부착 dry-run — 페이크/실 트랜스포트로 파이프라인을
  돌리되 외부 기록(ClickUp/Discord) 0. 채널당 독립 드라이버(각자 탭/연결)를
  만들어 오케스트레이터에 채널별 드라이버 맵으로 전달한다(4차 결함 ⑩).
- **--live**: 오너 승인 게이트 — 기록 클라이언트 미구성 상태에서는 fail-closed
  로 거부한다(조용한 발신 금지 — SOT 발송 불변식과 동일 원칙).

후보 추출기(4차 진입점 결함 — 항상 0명 silent 금지):
- 채널별 추출기 포트(``extractors``: channel → callable(pages)->[후보 dict])는
  --browser/--live 실행의 **필수 인자**다. 미배선이면 명시적 실패.
- 추출기는 전량 저장된 페이지 행(raw_html_or_text 포함)을 받아 후보 dict
  ({score_payload, record, draft_inputs})를 만들고, 오케스트레이터가 채점·
  제외·등록 흐름으로 넘긴다.

- CDP 트랜스포트는 주입 가능(``main(..., transport_factory=...)``) — 테스트는
  페이크 트랜스포트로 조립 경로 전체를 검증한다(실 브라우저/9222 접속 0).
- 열어본 페이지 전량 저장(D4)은 로컬 JSONL(PageStore 계약 upsert)로 남긴다.
  Supabase 어댑터로의 교체는 같은 PageStore 계약을 구현해 주입하면 된다.
- 자동 발송 경로는 존재하지 않는다(AC-9 초안 생성까지가 끝).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from apps.aisearch.core.admin_api_client import AdminApiConfigError, HttpAdminApiClient
from apps.aisearch.core.boolean_builder import DEFAULT_LOCATION, build_search_plan
from apps.aisearch.core.cdp_driver import CdpDriver, connect_websocket_transport
from apps.aisearch.core.discord_notify import DiscordNotifier
from apps.aisearch.core.intervention import InterventionMonitor
from apps.aisearch.core.intervention import RESUME_DELAY_SECONDS
from apps.aisearch.core.orchestrator import (
    LINKEDIN_CHANNEL,
    STATUS_COMPLETED,
    STATUS_WAITING_RESUME,
    PipelineDeps,
    PipelineReport,
    run_search_pipeline,
)
from apps.aisearch.core.portal_search import build_portal_search_descriptors
from apps.aisearch.core.recorders import DualRecorder
from apps.aisearch.core.session_lock import LinkedInSessionLock

__all__ = ["CHANNELS", "build_deps", "main"]

#: 3사 채널 — 채널당 독립 드라이버(탭/연결) 1개가 계약이다(4차 결함 ⑩).
CHANNELS: tuple[str, ...] = (LINKEDIN_CHANNEL, "saramin", "jobkorea")

#: F6 — 개입이 끝났는지 다시 확인하는 주기(초). RESUME_DELAY_SECONDS(30초)
#: 무입력이면 모니터가 스스로 RUNNING 으로 돌아오므로, 그보다 촘촘히 확인해
#: 개입 종료 후 곧바로 이어서 한다. 한 번에 오래 자면 재개가 늦어진다.
RESUME_POLL_SECONDS: float = RESUME_DELAY_SECONDS / 6

#: 추출기 포트 계약 — extractor(저장된 페이지 행 목록) -> 후보 dict 목록.
Extractor = Callable[[list[dict]], list[dict]]


def _lock_fd(fd: int) -> None:
    """파일 디스크립터 배타 잠금 — 맥/리눅스는 flock, 윈도우는 msvcrt.

    V1 3차 지적: `fcntl` 을 무조건 import 해서 윈도우(Winpc — 함대 3대 중 1대)에서는
    저장 자체가 ModuleNotFoundError 로 죽었다. 운영 대상에 윈도우가 있으므로
    플랫폼별 구현을 갖되, 어느 쪽도 "남의 잠금을 시간으로 뺏는" 방식은 쓰지 않는다.
    """
    try:
        import fcntl
    except ModuleNotFoundError:  # 윈도우
        import msvcrt

        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.05)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock_fd(fd: int) -> None:
    try:
        import fcntl
    except ModuleNotFoundError:  # 윈도우
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


class JsonlPageStore:
    """PageStore 계약(D4 전량 저장)의 로컬 JSONL 구현 — 네트워크 0.

    5차 결함 ② — append 전용이면 재실행마다 같은 페이지가 중복 적재된다.
    저장 키 (table, channel, position_ref, url) 로 **upsert**(기존 행 갱신)
    한다: 초기화 때 기존 파일을 키 인덱스로 적재하고, 갱신 시 파일 전체를
    다시 쓴다(재실행 = 새 인스턴스여도 중복 0). 키 필드가 없는 행은 id 로
    구분해 보존한다(다른 테이블 행 오염 방지).

    채널 스레드 3개가 동시에 저장하므로 쓰기는 락으로 직렬화한다.
    ``rows_for(channel, position_ref)`` 로 **현재 포지션의** 저장 페이지만
    추출기에 되돌려 준다(예전 실행의 다른 포지션 자료 혼입 금지).
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        #: V1 2라운드 — 저장자마다 다른 임시파일 이름. 같은 이름을 쓰면 두
        #: 저장자가 서로의 임시본을 덮어써 파일이 섞인다.
        self._writer_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        #: 저장 키 → 행(테이블 포함). 삽입 순서 보존(dict 순서).
        self._rows: dict[tuple, dict] = {}
        self._reload_from_disk()

    def _tmp_path(self) -> Path:
        return self._path.with_name(f"{self._path.name}.{self._writer_id}.tmp")

    def _lock_path(self) -> Path:
        return self._path.with_name(f"{self._path.name}.lock")

    def _reload_from_disk(self) -> None:
        """파일을 진실의 출처로 삼아 메모리 인덱스를 다시 만든다.

        V1 2라운드 — 예전에는 생성 시점에 한 번만 읽고 이후에는 자기 메모리만
        내보냈다. 같은 파일을 보는 저장자가 둘이면(두 실행·두 인스턴스) 나중
        저장이 상대가 쓴 행을 통째로 지웠다(D4 전량 저장 위반).
        """
        rows: dict[tuple, dict] = {}
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    stored = json.loads(line)
                except ValueError:
                    continue  # 손상된 줄은 건너뛰되 나머지는 보존한다
                if isinstance(stored, dict):
                    rows[self._key(stored.get("table", ""), stored)] = stored
        self._rows = rows

    @staticmethod
    def _key(table: str, row: dict) -> tuple:
        channel = row.get("channel")
        position_ref = row.get("position_ref")
        url = row.get("url")
        page_type = row.get("page_type")
        # 2026-07-31 리뷰 H5 — page_type 을 키에 포함한다. pagination_store 의
        # make_row_id 는 (channel, page_type, url, position_ref) 로 id 를 만드는데
        # 저장 키에는 page_type 이 빠져 있어서, 같은 URL 의 목록 페이지와 상세
        # 페이지가 서로를 덮어썼다(전량 저장 D4 위반). 두 계약을 일치시킨다.
        if channel and page_type and position_ref and url:
            return (table, channel, page_type, position_ref, url)
        # 키 필드 없는 행 — id(또는 전체 내용)로 구분해 덮어쓰기 방지.
        return (table, "__no_page_key__", row.get("id") or json.dumps(row, sort_keys=True))

    @contextmanager
    def _file_lock(self):
        """프로세스 간 직렬화 — 커널 파일락(flock)으로 잡는다.

        V1 3라운드 — 예전에는 "10초 넘은 잠금은 죽은 것으로 보고 지운다"는
        시간 기반 회수를 썼는데, 저장이 10초를 넘기면 **살아 있는** 저장자의
        잠금까지 빼앗아 두 저장자가 동시에 파일 전체를 교체했다(행 유실).
        flock 은 프로세스가 죽으면 커널이 알아서 풀어 주므로 죽은 잠금이라는
        개념 자체가 없다 — 시간 추정이 필요 없다.
        """
        lock_path = self._lock_path()
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            _lock_fd(fd)  # 남이 쥐고 있으면 기다린다(뺏지 않는다)
            try:
                yield
            finally:
                _unlock_fd(fd)
        finally:
            os.close(fd)

    def upsert(self, table: str, row: dict) -> None:
        with self._lock:  # 같은 인스턴스를 쓰는 채널 스레드 직렬화
            with self._file_lock():  # 다른 인스턴스·다른 프로세스와의 직렬화
                self._upsert_locked(table, row)

    def _upsert_locked(self, table: str, row: dict) -> None:
            # 다른 저장자가 그 사이에 쓴 내용을 먼저 흡수한다(행 유실 방지).
            self._reload_from_disk()
            self._rows[self._key(table, row)] = {"table": table, **row}
            lines = [
                json.dumps(stored, ensure_ascii=False)
                for stored in self._rows.values()
            ]
            payload = "\n".join(lines) + ("\n" if lines else "")
            # 2026-07-31 리뷰 H5 — 원자적 쓰기. 예전에는 파일 전체를 제자리에서
            # 다시 썼기 때문에, 쓰는 도중 죽으면 이미 저장해 둔 페이지가 통째로
            # 깨졌다. 임시 파일에 다 쓰고 fsync 한 뒤 os.replace 로 한 번에
            # 바꾼다 — 교체 전에 죽으면 기존 파일이 그대로 남는다.
            tmp_path = self._tmp_path()
            try:
                with open(tmp_path, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, self._path)
            except BaseException:
                tmp_path.unlink(missing_ok=True)  # 실패한 임시본은 남기지 않는다
                raise

    def rows_for(self, channel: str, position_ref: str) -> list[dict]:
        """현재 채널+포지션의 저장 행(원문 포함)만 — 추출기 입력(혼입 0)."""
        with self._lock:
            rows = list(self._rows.values())
        return [
            row
            for row in rows
            if row.get("channel") == channel
            and row.get("position_ref") == position_ref
        ]


class StderrNotifier:
    """(구) stderr 전용 알림 — 5차 결함 ③ 이후 조립 기본은 DiscordNotifier.

    DiscordNotifier 가 stderr 표면화를 포함하므로 조립에서는 더 쓰지 않는다.
    """

    def notify(self, message: str) -> None:
        print(f"[aisearch][차단 알림] {message}", file=sys.stderr)


class _NotConfiguredClient:
    """dry-run 전용 미구성 클라이언트 — 어떤 호출이 와도 fail-closed.

    후보가 나와 기록 경로에 진입하면 즉시 예외 — 미구성 상태에서 조용히
    기록된 척하지 않는다(DualRecorder 가 실패로 집계해 partial 로 보고).
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, item: str) -> Any:
        raise RuntimeError(
            f"{self._name} 클라이언트 미구성 — 기록 경로가 호출됐다"
            f"(fail-closed): {item}"
        )


def build_admin_client(*, live: bool) -> Any:
    """2026-07-31 리뷰 F4 — admin 정본 클라이언트의 **프로덕션 조립 지점**.

    이전에는 HttpAdminApiClient 가 어디에서도 만들어지지 않는 고아 코드였다
    (테스트만 인스턴스화). 여기서 실제 조립 경로에 붙인다.

    ADMIN_API_BASE_URL/ADMIN_API_INTERNAL_KEY 가 없거나 형식(https·키 16자)이
    어긋나면 조용히 넘어가지 않고 _NotConfiguredClient 로 바꿔, 기록 경로가
    실제로 호출될 때 fail-closed 로 표면화한다(미구성인데 성공한 척 금지).
    """
    try:
        return HttpAdminApiClient(live=live)
    except AdminApiConfigError as exc:
        return _NotConfiguredClient(f"Admin({exc})")


def build_deps(
    driver: CdpDriver,
    store: Any,
    monitor: InterventionMonitor,
    recorder: DualRecorder,
    machine: str,
    extract_candidates: Callable[[str], list[dict]],
    *,
    drivers: Optional[Mapping[str, CdpDriver]] = None,
    linkedin_session_lock: Optional[Any] = None,
) -> PipelineDeps:
    """드라이버를 오케스트레이터 포트에 배선한다.

    4차 진입점 결함 수정 — ``extract_candidates`` 는 **필수 인자**다(silent
    0명 기본값 금지). ``drivers`` 맵이 오면 채널별 독립 드라이버로 배선한다
    (결함 ⑩ — fetch/폴링/배너 전부 자기 채널 드라이버로만).
    """
    if drivers is not None:
        channel_drivers = dict(drivers)

        def _driver_for(channel: str) -> CdpDriver:
            d = channel_drivers.get(channel)
            if d is None:
                raise RuntimeError(
                    f"채널 {channel!r} 드라이버 미배선(fail-closed)"
                )
            return d

        def fetch_list_page(channel: str, page: int, payload: dict) -> dict:
            return _driver_for(channel).fetch_list_page(channel, page, payload)

        def fetch_detail_page(channel: str, ref: str) -> dict:
            return _driver_for(channel).fetch_detail_page(channel, ref)

        def poll_driver_events() -> list[dict]:
            events: list[dict] = []
            for d in channel_drivers.values():
                events.extend(d.poll_events())
            return events

        return PipelineDeps(
            driver=driver,
            store=store,
            monitor=monitor,
            recorder=recorder,
            fetch_list_page=fetch_list_page,
            fetch_detail_page=fetch_detail_page,
            extract_candidates=extract_candidates,
            machine=machine,
            poll_driver_events=poll_driver_events,
            drivers=channel_drivers,
            linkedin_session_lock=linkedin_session_lock,
        )
    return PipelineDeps(
        driver=driver,
        store=store,
        monitor=monitor,
        recorder=recorder,
        fetch_list_page=driver.fetch_list_page,
        fetch_detail_page=driver.fetch_detail_page,
        extract_candidates=extract_candidates,
        machine=machine,
        poll_driver_events=driver.poll_events,
        linkedin_session_lock=linkedin_session_lock,
    )


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        # 집합은 JSON 에 그대로 못 담는다 — 순서를 고정해 결정론적으로 만든다.
        return sorted(_plain(v) for v in value)
    return value


def _report_payload(report: PipelineReport, *, mode: str, live: bool) -> dict:
    payload = _plain(report)
    # 내부 집계용 표식은 원장에 남기지 않는다(리포트 계약 밖 — 구현 세부).
    payload.pop("counted_profile_urls", None)
    payload["mode"] = mode
    payload["live"] = live
    return payload


def _write_report(path: Optional[str], payload: dict) -> None:
    if path:
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _run_plan_only(jd: dict, args: argparse.Namespace) -> int:
    """기본 모드 — 브라우저 무접촉: 계획 산출·검증만 한다(CDP 연결 0)."""
    plan = build_search_plan(jd, location=jd.get("location", DEFAULT_LOCATION))
    descriptors = build_portal_search_descriptors(
        or_keywords=jd.get("or_keywords"),
        and_keywords=jd.get("and_keywords"),
        exclude_keywords=jd.get("not_keywords"),
        career_min=jd.get("career_min"),
        career_max=jd.get("career_max"),
    )
    payload = {
        "mode": "plan_only",
        "live": False,
        "cdp_connections": 0,  # 브라우저 무접촉 증거 — 연결 시도 자체가 없다
        "position_name": jd["position_name"],
        "linkedin_stages": [stage.name for stage in plan.stages],
        "descriptors": descriptors,
    }
    _write_report(args.report_out, payload)
    print(
        f"[aisearch] mode=plan_only stages={len(plan.stages)} "
        f"descriptors={len(descriptors)} (브라우저 무접촉 — 실행은 --browser)"
    )
    return 0


def main(
    argv: Optional[list[str]] = None,
    *,
    transport_factory: Optional[Callable[[str], Any]] = None,
    extractors: Optional[Mapping[str, Extractor]] = None,
    recorder: Optional[DualRecorder] = None,
    notifier: Optional[Any] = None,
    sleep: Callable[[float], None] = time.sleep,
    max_resume_attempts: Optional[int] = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m apps.aisearch.run",
        description="JD 파일로 3사(RPS/사람인/잡코리아) 검색 파이프라인 실행",
    )
    parser.add_argument("jd_path", help="JD JSON 파일 경로")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="브라우저 부착 dry-run(외부 기록 0). 기본은 plan-only(브라우저 무접촉).",
    )
    parser.add_argument(
        "--ws-url",
        default=None,
        help=(
            "대상 탭의 CDP WebSocket URL — 테스트(transport_factory 주입) 또는 "
            "단일 탭 실험용. 실제 3채널 동시 실행(--browser, transport_factory "
            "미주입)에서는 이 값 하나를 세 채널이 공유하면 같은 탭을 놓고 채널이 "
            "경합한다(V1 독립검증 결함3) — 그 경로에서는 --ws-url-<channel> 3개를 "
            "각각 주십시오."
        ),
    )
    for _channel in CHANNELS:
        parser.add_argument(
            f"--ws-url-{_channel}",
            dest=f"ws_url_{_channel}",
            default=None,
            help=f"{_channel} 채널 전용 CDP WebSocket URL(채널당 독립 탭 — 다른 채널과 달라야 함)",
        )
    parser.add_argument("--machine", default="macmini", help="실행 머신 식별자")
    parser.add_argument(
        "--pages-out",
        default="aisearch_pages.jsonl",
        help="열어본 페이지 전량 저장(JSONL) 경로 (D4)",
    )
    parser.add_argument("--report-out", default=None, help="실행 리포트 JSON 경로")
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "ClickUp/Discord/admin 라이브 기록(오너 승인 게이트). CLI 단독 실행은 "
            "실제 클라이언트를 만들 방법이 없어 여전히 fail-closed 거부한다 — "
            "recorder= 인자로 live=True·owner_signoff=True 인 실제 DualRecorder를 "
            "주입했을 때만 통과한다(V1 독립검증 결함2: 이전에는 주입 여부와 "
            "무관하게 항상 거부해 admin 등록이 라이브에서 도달 불가능했다)."
        ),
    )
    args = parser.parse_args(argv)

    if args.live and (recorder is None or not recorder.live):
        # 오너 승인 게이트 — CLI 인자만으로는 실제 라이브 클라이언트를 만들
        # 방법이 없다(ClickUp/Discord/admin 자격증명을 CLI 플래그로 받지
        # 않음). 실제 배선은 recorder= 프로그램적 주입으로만 가능하다.
        parser.exit(
            2,
            "--live 거부: live=True 로 구성된 실제 recorder 가 주입되지 않았다"
            "(fail-closed). CLI 인자만으로는 ClickUp/Discord/admin 라이브 "
            "클라이언트를 만들 수 없다 — recorder= 로 실제 DualRecorder(..., "
            "live=True, owner_signoff=True) 를 주입하거나, plan-only(기본)/"
            "--browser dry-run 으로 실행하십시오.\n",
        )

    jd = json.loads(Path(args.jd_path).read_text(encoding="utf-8"))

    if not args.browser:
        # 기본 = plan-only: 브라우저 무접촉(transport_factory 를 아예 안 부른다).
        return _run_plan_only(jd, args)

    # ── --browser: 브라우저 부착 dry-run(외부 기록 0) ──────────────────────
    if extractors is None:
        # 4차 진입점 결함 — 추출기 미배선 상태로 돌면 후보가 조용히 0명이 된다.
        parser.exit(
            2,
            "--browser 거부: 채널별 후보 추출기(extractors) 미배선(fail-closed). "
            "silent 0명 실행은 금지 — 추출기 포트를 주입하십시오.\n",
        )

    channel_urls: dict[str, str] = {
        channel: (getattr(args, f"ws_url_{channel}") or args.ws_url or "")
        for channel in CHANNELS
    }

    if transport_factory is None:
        # V1 독립검증 결함3 — 실제 CDP 연결 경로에서는 채널당 서로 다른 탭이
        # 필수다. 같은 URL(탭)을 여러 채널이 공유하면 페이지 이동이 경합해
        # 후보가 엉뚱한 채널로 저장될 수 있다 — 단일 --ws-url 공용은 여기서 금지.
        missing = [c for c in CHANNELS if not channel_urls[c]]
        if missing:
            parser.exit(
                2,
                "--ws-url-<channel> 이 필요합니다(채널당 독립 탭): "
                f"{', '.join(f'--ws-url-{c}' for c in missing)}\n",
            )
        duplicates = {
            url
            for url in channel_urls.values()
            if list(channel_urls.values()).count(url) > 1
        }
        if duplicates:
            parser.exit(
                2,
                "채널별 --ws-url-<channel> 값이 서로 달라야 합니다(같은 탭 공유 금지, "
                f"fail-closed): 중복 URL {sorted(duplicates)!r}\n",
            )
        # V1 2차 독립검증 결함4 — 실 CDP 경로에서 AISEARCH_LINKEDIN_LOCK_DIR
        # 미설정은 "보호 없이도 조용히 진행"이 아니라 fail-closed 거부다.
        # 링크드인 단일세션(E4)은 실제 브라우저 자동화가 도는 이 경로에서만
        # 의미가 있고, 여기서 안 막으면 운영자가 깜빡한 채 그대로 라이브
        # 실행돼 두 기기 동시 접속 사고로 이어진다.
        if not os.environ.get("AISEARCH_LINKEDIN_LOCK_DIR", "").strip():
            parser.exit(
                2,
                "AISEARCH_LINKEDIN_LOCK_DIR 이 필요합니다(링크드인 기기 간 세션 락, "
                "fail-closed) — 여러 기기가 공유하는 저장소 경로를 설정하십시오.\n",
            )
        transport_factory = connect_websocket_transport

    # 4차 결함 ⑩ — 채널당 독립 드라이버(각자 탭/연결). 트랜스포트 팩토리를
    # 채널마다 따로 불러 연결을 공유하지 않는다(같은 연결 공유 = 응답 혼선).
    # V1 독립검증 결함3 — 각 채널이 자기 전용 URL(탭)로 접속한다(공유 --ws-url 아님).
    drivers: dict[str, CdpDriver] = {
        channel: CdpDriver(transport_factory(channel_urls[channel]))
        for channel in CHANNELS
    }

    store = JsonlPageStore(Path(args.pages_out))
    if notifier is None:
        # 5차 결함 ③ — 차단 알림은 Discord notifier 어댑터(채널
        # 1512503041448743092)로 배선한다. 실제 발신(send 클라이언트)은
        # --live 게이트 뒤 — 기본은 payload 계획만 기록(+stderr 표면화).
        notifier = DiscordNotifier()
    monitor = InterventionMonitor(time.monotonic, notifier)
    if recorder is None:
        recorder = DualRecorder(
            _NotConfiguredClient("ClickUp"),
            _NotConfiguredClient("Discord"),
            build_admin_client(live=False),
        )  # dry-run — 외부 기록 0(기록 경로 진입 시 fail-closed 로 표면화)

    channel_extractors = dict(extractors)

    def extract_candidates(channel: str) -> list[dict]:
        extractor = channel_extractors.get(channel)
        if extractor is None:
            # silent 0명 금지 — 추출기 없는 채널은 명시적 실패(E8).
            raise RuntimeError(
                f"채널 {channel!r} 후보 추출기 미배선(fail-closed) — "
                "extractors 인자를 확인하십시오"
            )
        # 5차 결함 ② — 예전 실행의 다른 포지션 자료 혼입 금지: 현재
        # position_ref(JD position_name)의 저장 행만 추출기에 넘긴다.
        return extractor(store.rows_for(channel, jd["position_name"]))

    # V1 독립검증 결함4 — 링크드인 채널은 기기 간 세션 락으로 감싼다.
    # AISEARCH_LINKEDIN_LOCK_DIR(공유 스토리지 경로) 가 설정된 경우에만 실제
    # 락을 건다 — 테스트/미설정 환경에서 로컬 홈 디렉터리에 조용히 실제 락
    # 파일을 만들지 않기 위해 env 로 명시 오입력을 요구한다(silent 필로소피
    # 유지: 미설정 = "이 실행은 기기 간 배제 없음"을 그대로 드러낸다).
    lock_dir_env = os.environ.get("AISEARCH_LINKEDIN_LOCK_DIR", "").strip()
    linkedin_session_lock = (
        LinkedInSessionLock(lock_dir=Path(lock_dir_env) / "linkedin_rps", owner=f"aisearch@{args.machine}")
        if lock_dir_env
        else None
    )
    deps = build_deps(
        drivers[LINKEDIN_CHANNEL],
        store,
        monitor,
        recorder,
        args.machine,
        extract_candidates,
        drivers=drivers,
        linkedin_session_lock=linkedin_session_lock,
    )
    report = run_search_pipeline(jd, deps)

    # V1 독립검증 결함5 — PAUSED_HUMAN 은 InterventionMonitor.poll() 이 마지막
    # 사람 입력으로부터 30초(RESUME_DELAY_SECONDS) 무입력이면 스스로 RUNNING
    # 으로 되돌리는 상태다. 여기서 실제로 대기·재시도하지 않으면 그 자기복구가
    # 아무 효력이 없다 — waiting_resume 로 그냥 끝나버려 사람이 잡 전체를
    # 수동으로 다시 시작해야 했다(결함5). previous=report 로 미완 단계만
    # 이어서 완결한다(2차 결함 7 재개 경로 재사용).
    # 2026-07-31 리뷰 F6 — 예전에는 6회(=30초)를 소진하면 waiting_resume 그대로
    # 끝냈다. 사장님이 30초 넘게 크롬을 쓰시면 작업이 그냥 멈춘 채 방치되는데,
    # 이는 SOT 불변식 2("멈추고 방치하지 않는다 — 반드시 자동 재개") 위반이다.
    # 기본값을 **상한 없음**으로 바꾸고, 매 사이클 RESUME_POLL_SECONDS 만큼만
    # 자면서(바쁜 대기 아님 — 봇처럼 굴지 않는다) 개입이 끝날 때까지 기다린다.
    # max_resume_attempts 는 운영/테스트가 명시적으로 줄 때만 상한이 된다.
    resume_attempts = 0
    while report.status == STATUS_WAITING_RESUME and (
        max_resume_attempts is None or resume_attempts < max_resume_attempts
    ):
        sleep(RESUME_POLL_SECONDS)
        resume_attempts += 1
        report = run_search_pipeline(jd, deps, previous=report)
    if report.status == STATUS_WAITING_RESUME:
        # 명시적 상한을 준 실행에서만 여기 도달한다 — 조용히 끝내지 않고 알린다.
        print(
            f"[aisearch] 자동 재개 상한({max_resume_attempts}회) 소진 — 여전히 "
            "사람 개입 중. 상한 없이 실행하면 개입이 끝날 때까지 기다립니다.",
            file=sys.stderr,
        )

    # F11(2026-07-31 리뷰) — 원장의 live 표기는 **실제 기록기**를 따른다.
    # 예전에는 --live 플래그만 봤다: recorder= 로 live 레코더를 주입해 실제
    # ClickUp/Discord/admin 쓰기가 일어나도 원장에는 dry-run 으로 남아, 증거가
    # 사실과 정반대가 됐다. 둘 중 하나라도 라이브면 라이브로 기록한다.
    effective_live = bool(args.live or getattr(recorder, "live", False))
    payload = _report_payload(
        report,
        mode="browser_live" if effective_live else "browser_dry_run",
        live=effective_live,
    )
    _write_report(args.report_out, payload)
    print(
        f"[aisearch] mode={payload['mode']} status={report.status} "
        f"variants={len(report.variants)} registered={len(report.registered)} "
        f"drafts={len(report.drafts)} excluded={len(report.excluded)} "
        f"error={report.error or '-'}"
    )
    return 0 if report.status == STATUS_COMPLETED else 1


if __name__ == "__main__":  # pragma: no cover — 프로덕션 진입점
    raise SystemExit(main())
