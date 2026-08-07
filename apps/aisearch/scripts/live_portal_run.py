"""수동 라이브 실행기 — 기존 CDP 탭 하나에만 붙어 채널 검색을 1회 실행한다.

로그인 스킬 규칙 준수: 새 탭/새 창 0개(기존 target 만 raw_cdp.list_pages 로
찾아 그 target 의 webSocketDebuggerUrl 에 붙는다). 입력은 apps/aisearch/core
/cdp_driver.CdpDriver(신뢰 입력 Input.insertText, 캡차/2FA 자동 감지 포함)만
쓰고, 이 스크립트 자체는 셀렉터·타이핑 로직을 갖지 않는다(재사용 전용 배선).

사용:
  PYTHONPATH=. python3 -m apps.aisearch.scripts.live_portal_run \
    --channel jobkorea --port 9224 --or 회계 결산 재무회계 --and 더존 \
    --career-min 3 --max-pages 1 --out /path/to/out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from apps.aisearch.core.cdp_driver import CdpDriver, CdpDriverError, connect_websocket_transport
from apps.aisearch.core.live_collect import collect_channel_pages
from apps.aisearch.core.portal_search import build_portal_search_descriptors
from tools.multi_position_sourcing import raw_cdp as legacy_cdp


def resolve_existing_ws_url(port: int, *, target_id: str | None = None) -> str:
    """기존 target 의 webSocketDebuggerUrl 만 돌려준다 — 새 탭/새 창 0개."""
    pages = legacy_cdp.list_pages(endpoint=f"http://127.0.0.1:{port}")
    page_targets = [p for p in pages if not (p.get("url") or "").startswith("devtools://")]
    if target_id:
        matches = [p for p in page_targets if p.get("id") == target_id]
    else:
        matches = page_targets
    if len(matches) != 1:
        ids = [(p.get("id"), p.get("url")) for p in page_targets]
        raise CdpDriverError(
            f"정확한 기존 target 1개를 못 골랐다(fail-closed): 후보={ids!r} "
            f"target_id={target_id!r}"
        )
    ws_url = matches[0].get("webSocketDebuggerUrl")
    if not ws_url:
        raise CdpDriverError(f"webSocketDebuggerUrl 없음: {matches[0]!r}")
    return str(ws_url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", required=True, choices=["saramin", "jobkorea"])
    parser.add_argument("--port", required=True, type=int, help="기존 CDP 포트(예: 9223, 9224)")
    parser.add_argument("--target-id", default=None, help="탭이 여러 개면 정확한 target id")
    parser.add_argument("--or", dest="or_keywords", nargs="*", default=[])
    parser.add_argument("--and", dest="and_keywords", nargs="*", default=[])
    parser.add_argument("--exclude", dest="exclude_keywords", nargs="*", default=[])
    parser.add_argument("--career-min", type=int, default=None)
    parser.add_argument("--career-max", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    descriptors = build_portal_search_descriptors(
        or_keywords=args.or_keywords or None,
        and_keywords=args.and_keywords or None,
        exclude_keywords=args.exclude_keywords or None,
        career_min=args.career_min,
        career_max=args.career_max,
    )
    descriptor = next(d for d in descriptors if d["channel"] == args.channel)

    ws_url = resolve_existing_ws_url(args.port, target_id=args.target_id)
    driver = CdpDriver(connect_websocket_transport(ws_url))

    pages = collect_channel_pages(
        driver, args.channel, descriptor, max_pages=args.max_pages
    )
    payload = {
        "channel": args.channel,
        "descriptor": descriptor,
        "pages": pages,
    }
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total_details = sum(len(p.get("details") or []) for p in pages)
    print(
        f"[live_portal_run] channel={args.channel} pages={len(pages)} "
        f"details={total_details} out={args.out}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — 수동 라이브 실행 전용
    raise SystemExit(main())
