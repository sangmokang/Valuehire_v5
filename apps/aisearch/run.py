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
import sys
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from apps.aisearch.core.boolean_builder import DEFAULT_LOCATION, build_search_plan
from apps.aisearch.core.cdp_driver import CdpDriver, connect_websocket_transport
from apps.aisearch.core.discord_notify import DiscordNotifier
from apps.aisearch.core.intervention import InterventionMonitor
from apps.aisearch.core.orchestrator import (
    LINKEDIN_CHANNEL,
    STATUS_COMPLETED,
    PipelineDeps,
    PipelineReport,
    run_search_pipeline,
)
from apps.aisearch.core.portal_search import build_portal_search_descriptors
from apps.aisearch.core.recorders import DualRecorder

__all__ = ["CHANNELS", "build_deps", "main"]

#: 3사 채널 — 채널당 독립 드라이버(탭/연결) 1개가 계약이다(4차 결함 ⑩).
CHANNELS: tuple[str, ...] = (LINKEDIN_CHANNEL, "saramin", "jobkorea")

#: 추출기 포트 계약 — extractor(저장된 페이지 행 목록) -> 후보 dict 목록.
Extractor = Callable[[list[dict]], list[dict]]


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
        #: 저장 키 → 행(테이블 포함). 삽입 순서 보존(dict 순서).
        self._rows: dict[tuple, dict] = {}
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                stored = json.loads(line)
                self._rows[self._key(stored.get("table", ""), stored)] = stored

    @staticmethod
    def _key(table: str, row: dict) -> tuple:
        channel = row.get("channel")
        position_ref = row.get("position_ref")
        url = row.get("url")
        if channel and position_ref and url:
            return (table, channel, position_ref, url)
        # 키 필드 없는 행 — id(또는 전체 내용)로 구분해 덮어쓰기 방지.
        return (table, "__no_page_key__", row.get("id") or json.dumps(row, sort_keys=True))

    def upsert(self, table: str, row: dict) -> None:
        with self._lock:
            self._rows[self._key(table, row)] = {"table": table, **row}
            lines = [
                json.dumps(stored, ensure_ascii=False)
                for stored in self._rows.values()
            ]
            self._path.write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
            )

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


def build_deps(
    driver: CdpDriver,
    store: Any,
    monitor: InterventionMonitor,
    recorder: DualRecorder,
    machine: str,
    extract_candidates: Callable[[str], list[dict]],
    *,
    drivers: Optional[Mapping[str, CdpDriver]] = None,
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
    )


def _plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _report_payload(report: PipelineReport, *, mode: str, live: bool) -> dict:
    payload = _plain(report)
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
        help="ClickUp/Discord 라이브 기록(오너 승인 게이트). 현재 fail-closed 거부.",
    )
    args = parser.parse_args(argv)

    if args.live:
        # 오너 승인 게이트 — 라이브 기록 클라이언트(ClickUp/Discord)가 아직
        # 배선되지 않았다. 조용한 dry-run 격하 금지, fail-closed 로 거부한다.
        parser.exit(
            2,
            "--live 거부: ClickUp/Discord 기록 클라이언트 미구성(fail-closed). "
            "plan-only(기본) 또는 --browser dry-run 으로 실행하십시오.\n",
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
            _NotConfiguredClient("Admin"),
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

    deps = build_deps(
        drivers[LINKEDIN_CHANNEL],
        store,
        monitor,
        recorder,
        args.machine,
        extract_candidates,
        drivers=drivers,
    )
    report = run_search_pipeline(jd, deps)

    payload = _report_payload(report, mode="browser_dry_run", live=False)
    _write_report(args.report_out, payload)
    print(
        f"[aisearch] mode=browser_dry_run status={report.status} "
        f"variants={len(report.variants)} registered={len(report.registered)} "
        f"drafts={len(report.drafts)} excluded={len(report.excluded)} "
        f"error={report.error or '-'}"
    )
    return 0 if report.status == STATUS_COMPLETED else 1


if __name__ == "__main__":  # pragma: no cover — 프로덕션 진입점
    raise SystemExit(main())
