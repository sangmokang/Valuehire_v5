"""apps/aisearch 프로덕션 엔트리포인트 — V1 3차 결함 ④("실행 호출부 0개") 해소.

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §2/§4. JD 파일 경로를
받아 cdp_driver(raw CDP 어댑터) + run_search_pipeline 을 조립·실행한다.

사용:
    python -m apps.aisearch.run jd.json --ws-url ws://127.0.0.1:9222/devtools/page/<id>

원칙:
- **기본 dry-run** — ClickUp/Discord 외부 기록 0(계획만 산출). ``--live`` 는
  명시 플래그이며, 기록 클라이언트가 구성되지 않은 현재는 fail-closed 로
  거부한다(조용한 발신 금지 — SOT 발송 불변식과 동일 원칙).
- CDP 트랜스포트는 주입 가능(``main(..., transport_factory=...)``) — 테스트는
  페이크 트랜스포트로 조립 경로 전체를 검증한다(실 브라우저/9222 접속 0).
- 열어본 페이지 전량 저장(D4)은 로컬 JSONL(PageStore 계약 upsert)로 남긴다.
  Supabase 어댑터로의 교체는 같은 PageStore 계약을 구현해 주입하면 된다.
- 자동 발송 경로는 존재하지 않는다(AC-9 초안 생성까지가 끝).
- 현재 조립은 단일 탭(단일 트랜스포트)에 3채널 스레드가 붙는 구조다 —
  라이브 다채널 동시 실행은 채널별 탭/트랜스포트 주입(build_deps 재사용)이
  필요하며, 그 배선은 라이브 검증 단계의 후속 작업으로 명시해 둔다.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from apps.aisearch.core.cdp_driver import CdpDriver, connect_websocket_transport
from apps.aisearch.core.intervention import InterventionMonitor
from apps.aisearch.core.orchestrator import (
    STATUS_COMPLETED,
    PipelineDeps,
    PipelineReport,
    run_search_pipeline,
)
from apps.aisearch.core.recorders import DualRecorder

__all__ = ["build_deps", "main"]


class JsonlPageStore:
    """PageStore 계약(D4 전량 저장)의 로컬 JSONL 구현 — 네트워크 0.

    채널 스레드 3개가 동시에 저장하므로 파일 쓰기는 락으로 직렬화한다.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def upsert(self, table: str, row: dict) -> None:
        line = json.dumps({"table": table, **row}, ensure_ascii=False) + "\n"
        with self._lock, self._path.open("a", encoding="utf-8") as f:
            f.write(line)


class StderrNotifier:
    """AC-7 차단 알림의 최소 구현 — 표준에러로 즉시 표면화(삼키지 않는다)."""

    def notify(self, message: str) -> None:
        print(f"[aisearch][차단 알림] {message}", file=sys.stderr)


class _NotConfiguredClient:
    """dry-run 전용 미구성 클라이언트 — 어떤 호출이 와도 fail-closed.

    dry-run 파이프라인은 후보 추출이 배선되기 전까지 기록 경로에 진입하지
    않으므로 이 클라이언트는 호출되지 않는다. 호출됐다면 그 자체가 결함이다.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, item: str) -> Any:
        raise RuntimeError(
            f"{self._name} 클라이언트 미구성 — dry-run 에서 기록 경로가 "
            f"호출됐다(fail-closed): {item}"
        )


def _no_candidates(channel: str) -> list[dict]:
    """후보 추출 기본값 — 저장된 raw 페이지 기반 추출기가 배선되기 전까지 0건.

    조용한 추정 후보 생성 금지(E8): 추출기가 없으면 후보 0건이 정직한 결과다.
    실제 추출기는 build_deps(extract_candidates=...)로 주입한다.
    """
    return []


def build_deps(
    driver: CdpDriver,
    store: Any,
    monitor: InterventionMonitor,
    recorder: DualRecorder,
    machine: str,
    extract_candidates: Callable[[str], list[dict]] = _no_candidates,
) -> PipelineDeps:
    """cdp_driver 를 오케스트레이터 포트에 그대로 배선한다(결함 ①② 해소 지점)."""
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


def _report_payload(report: PipelineReport, live: bool) -> dict:
    def _plain(value: Any) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            return {k: _plain(v) for k, v in asdict(value).items()}
        if isinstance(value, dict):
            return {k: _plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_plain(v) for v in value]
        return value

    payload = _plain(report)
    payload["live"] = live
    return payload


def main(
    argv: Optional[list[str]] = None,
    *,
    transport_factory: Optional[Callable[[str], Any]] = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m apps.aisearch.run",
        description="JD 파일로 3사(RPS/사람인/잡코리아) 검색 파이프라인 실행",
    )
    parser.add_argument("jd_path", help="JD JSON 파일 경로")
    parser.add_argument(
        "--ws-url",
        default=None,
        help="대상 탭의 CDP WebSocket URL (테스트는 transport_factory 주입)",
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
        help="ClickUp/Discord 라이브 기록(명시 플래그). 기본은 dry-run.",
    )
    args = parser.parse_args(argv)

    if args.live:
        # 라이브 기록 클라이언트(ClickUp/Discord)가 아직 배선되지 않았다 —
        # 조용한 dry-run 격하 금지, fail-closed 로 거부한다.
        parser.exit(
            2,
            "--live 거부: ClickUp/Discord 기록 클라이언트 미구성(fail-closed). "
            "기본 dry-run 으로 실행하십시오.\n",
        )

    if transport_factory is None:
        if not args.ws_url:
            parser.exit(2, "--ws-url 이 필요합니다(라이브 CDP 연결 대상 탭).\n")
        transport_factory = connect_websocket_transport

    jd = json.loads(Path(args.jd_path).read_text(encoding="utf-8"))

    driver = CdpDriver(transport_factory(args.ws_url or ""))
    store = JsonlPageStore(Path(args.pages_out))
    monitor = InterventionMonitor(time.monotonic, StderrNotifier())
    recorder = DualRecorder(
        _NotConfiguredClient("ClickUp"), _NotConfiguredClient("Discord")
    )  # 기본 dry-run — 외부 기록 0

    report = run_search_pipeline(jd, build_deps(driver, store, monitor, recorder, args.machine))

    payload = _report_payload(report, live=False)
    if args.report_out:
        Path(args.report_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        f"[aisearch] status={report.status} variants={len(report.variants)} "
        f"registered={len(report.registered)} drafts={len(report.drafts)} "
        f"excluded={len(report.excluded)} error={report.error or '-'}"
    )
    return 0 if report.status == STATUS_COMPLETED else 1


if __name__ == "__main__":  # pragma: no cover — 프로덕션 진입점
    raise SystemExit(main())
