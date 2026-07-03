#!/usr/bin/env python3
"""humansearch 로컬 SQLite → Supabase 적재 (profile_archives + sourcing_results).

- 중복 방지: profile_archives 는 url 로, sourcing_results 는 (value, position_id) 로
  기존 행 조회 후 없는 것만 insert (조용한 덮어쓰기 금지).
- career_periods 는 results.json(employment_history)에서 url 매칭으로 보강.
사용: python3 scripts/humansearch_supabase_backfill.py [--dry-run]
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from tools.multi_position_sourcing.humansearch_supabase_sync import (  # noqa: E402
    to_profile_archive_row,
    to_sourcing_result_row,
)

DB = Path.home() / ".vh-data" / "ai-search-candidates.db"
POSITION_TITLES = {
    "86ey4umzk": "[뤼튼테크놀로지스 AX CIC] AX Product Manager (Ontology)",
    "86exxe704": "[모벤시스] Robotics C++ 매니퓰레이터 제어 라이브러리",
    "86ey3eace": "[토트] Physical AI Engineer",
}
RESULTS_JSON = [
    Path.home() / ".vh-search-results/linkedin_rps/2026-07-02/wrtn-ax-pm-ontology/results.json",
    Path.home() / ".vh-search-results/linkedin_rps/2026-07-02/robotics-dual/results.json",
]


def _env(key: str) -> str:
    for base in (REPO, REPO.parent.parent):
        env = base / ".env.local"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} 없음")


SB_URL = _env("NEXT_PUBLIC_SUPABASE_URL")
SB_KEY = _env("SUPABASE_SERVICE_ROLE_KEY")


def _api(method: str, path: str, payload=None):
    req = urllib.request.Request(
        f"{SB_URL}/rest/v1{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
        return json.loads(body) if body else []


def _get(path: str):
    req = urllib.request.Request(f"{SB_URL}/rest/v1{path}",
                                 headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def load_tenures() -> dict[str, list]:
    out: dict[str, list] = {}
    for p in RESULTS_JSON:
        if p.exists():
            for r in json.loads(p.read_text()):
                hist = r.get("employment_history") or []
                if hist:
                    out[r["url"]] = hist
    return out


def main(dry: bool) -> None:
    # V1(Codex): 동시 실행 2개 = 중복 insert — 단일 실행 락(디스코드 다리와 동일 유틸 재사용)
    from scripts.discord_command_listener import acquire_single_instance_lock
    import os as _os
    lock = Path.home() / ".valuehire" / "supabase_backfill.lock"
    if not dry and not acquire_single_instance_lock(lock, _os.getpid()):
        raise SystemExit("이미 다른 적재기가 실행 중 — 종료(중복 insert 방지)")
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM ai_search_candidates WHERE position_id IN (?,?,?)",
        tuple(POSITION_TITLES)).fetchall()]
    conn.close()
    tenures = load_tenures()
    print(f"로컬 후보 행: {len(rows)}")

    # 1) profile_archives — url 단위(중복 url 은 1회)
    seen_urls: dict[str, dict] = {}
    for r in rows:
        pa = to_profile_archive_row(r)
        if pa and pa["url"] not in seen_urls:
            seen_urls[pa["url"]] = pa
    urls = list(seen_urls)
    existing = set()
    for i in range(0, len(urls), 40):
        chunk = ",".join(f'"{u}"' for u in urls[i:i+40])
        for row in _get(f"/profile_archives?select=url&url=in.({urllib.parse.quote(chunk)})"):
            existing.add(row["url"])
    new_pa = [v for u, v in seen_urls.items() if u not in existing]
    print(f"profile_archives: 대상 {len(seen_urls)} / 기존 {len(existing)} / 신규 {len(new_pa)}")
    from datetime import datetime, timezone
    for pa in new_pa:
        pa.setdefault("captured_at", datetime.now(timezone.utc).isoformat())
    if new_pa and not dry:
        _api("POST", "/profile_archives", new_pa)
        print("  -> inserted")

    # 2) sourcing_results — 먼저 run 등록(FK), 그 다음 (value, position_id) 단위
    RUN_ID = "humansearch-backfill-2026-07-03"
    if not _get(f"/sourcing_runs?select=id&id=eq.{RUN_ID}&limit=1") and not dry:
        from datetime import datetime, timezone
        _api("POST", "/sourcing_runs", [{
            "id": RUN_ID, "triggered_at": datetime.now(timezone.utc).isoformat(),
            "position_count": len(POSITION_TITLES), "status": "completed",
            "notes": "humansearch 2026-07-02 로컬 SQLite 소급 적재 (뤼튼 AX PM·모벤시스·토트)",
        }])
        print("sourcing_runs: run 등록 ->", RUN_ID)
    inserted = skipped = rejected = 0
    payloads = []
    for r in rows:
        sr = to_sourcing_result_row(r, POSITION_TITLES.get(r["position_id"], r["position_id"]))
        if not sr:
            rejected += 1
            continue
        sr["id"] = f"hs-{uuid.uuid4()}"
        sr["run_id"] = RUN_ID
        from datetime import datetime, timezone
        sr["created_at"] = r.get("created_at") or datetime.now(timezone.utc).isoformat()
        if r["url"] in tenures:
            sr["career_periods"] = tenures[r["url"]]
        payloads.append(sr)
    for sr in payloads:
        q = f"/sourcing_results?select=id&value=eq.{urllib.parse.quote(sr['value'], safe='')}&position_id=eq.{sr['position_id']}&limit=1"
        if _get(q):
            skipped += 1
            continue
        if not dry:
            _api("POST", "/sourcing_results", [sr])
        inserted += 1
    print(f"sourcing_results: 신규 {inserted} / 기존스킵 {skipped} / 거부(fail-closed) {rejected}")
    if dry:
        print("(dry-run — 실제 적재 안 함)")


if __name__ == "__main__":
    main(dry="--dry-run" in sys.argv)
