"""수동 라이브 실행기 — LinkedIn RPS. 기존 CDP 탭 하나에만 붙어 1회 검색.

live_portal_run.py 와 동일한 원칙(새 탭/새 창 0개, CdpDriver 재사용,
셀렉터·입력 로직 신규 작성 0)을 LinkedIn RPS 채널에 적용한다.

사용:
  PYTHONPATH=. python3 -m apps.aisearch.scripts.live_rps_run \
    --port 9225 --target-id <exact-target-id> \
    --keyword-groups "회계,결산,재무회계" "더존,iCUBE,아마란스" \
    --university 서울대학교 연세대학교 ... \
    --min-years 3 --max-pages 1 --out /tmp/out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from apps.aisearch.core.boolean_builder import DEFAULT_LOCATION, build_search_plan
from apps.aisearch.core.cdp_driver import CdpDriver, CdpDriverError, connect_websocket_transport
from apps.aisearch.core.live_collect import collect_channel_pages
from apps.aisearch.core.orchestrator import LINKEDIN_CHANNEL
from apps.aisearch.core.data.seoul_universities import SEOUL_UNIVERSITIES
from apps.aisearch.scripts.live_portal_run import resolve_existing_ws_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--target-id", default=None)
    parser.add_argument("--keyword-groups", nargs="+", required=True, help="쉼표로 묶은 그룹 여러 개")
    parser.add_argument("--min-years", type=int, required=True)
    parser.add_argument("--max-years", type=int, default=None)
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    keyword_groups = [g.split(",") for g in args.keyword_groups]
    requirements: dict = {"min_years": args.min_years}
    if args.max_years is not None:
        requirements["max_years"] = args.max_years

    jd = {
        "keyword_groups": keyword_groups,
        "requirements": requirements,
    }
    plan = build_search_plan(jd, location=args.location)
    stage = plan.current_stage()

    search_payload = {
        "channel": LINKEDIN_CHANNEL,
        "keywords": stage.keywords,
        "location": stage.location,
        "universities": list(stage.universities or ()),
        "required_filters": dict(stage.required_filters),
    }

    ws_url = resolve_existing_ws_url(args.port, target_id=args.target_id)
    driver = CdpDriver(connect_websocket_transport(ws_url))
    # execute_search()(RPS)는 현재 화면이 이미 검색 패널이라고 가정하고
    # navigate 를 하지 않는다(기존 프로젝트 내 재검색 재사용 목적) — 백지
    # 상태에서 새로 시작할 때는 이 스크립트가 먼저 검색 화면으로 이동한다.
    driver.navigate("https://www.linkedin.com/talent/search")

    pages = collect_channel_pages(
        driver, LINKEDIN_CHANNEL, search_payload, max_pages=args.max_pages
    )
    payload = {
        "channel": LINKEDIN_CHANNEL,
        "stage": stage.name,
        "search_payload": search_payload,
        "pages": pages,
    }
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total_details = sum(len(p.get("details") or []) for p in pages)
    print(
        f"[live_rps_run] stage={stage.name} pages={len(pages)} "
        f"details={total_details} out={args.out}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — 수동 라이브 실행 전용
    raise SystemExit(main())
