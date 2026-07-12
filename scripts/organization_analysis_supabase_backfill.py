#!/usr/bin/env python3
"""SQLite ``organization_analysis`` → Supabase batch mirror.

Primary store is local sqlite. This script mirrors the local table into Supabase
in batches using idempotent upsert-by-position-id semantics.

Usage:
  python3 scripts/organization_analysis_supabase_backfill.py [--dry-run]
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.multi_position_sourcing.organization_analysis import DB_PATH, TABLE_NAME  # noqa: E402
from tools.multi_position_sourcing.humansearch_supabase_sync import (  # noqa: E402
    to_organization_analysis_row,
)


def _env(key: str) -> str:
    for base in (REPO, REPO.parent.parent):
        env = base / ".env.local"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} 없음")


def _api(
    method: str,
    path: str,
    payload=None,
    *,
    base_url: str,
    service_key: str,
    upsert: bool = False,
):
    req = urllib.request.Request(
        f"{base_url}/rest/v1{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal" if upsert else "return=minimal",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
        return json.loads(body) if body else []


def _load_local_rows() -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT * FROM {TABLE_NAME} ORDER BY updated_at DESC, position_id ASC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def main(dry: bool) -> None:
    rows = _load_local_rows()
    print(f"로컬 organization_analysis 행: {len(rows)}")
    payloads = []
    for row in rows:
        payload = to_organization_analysis_row(row)
        if payload:
            payloads.append(payload)
    print(f"Supabase 후보 payload: {len(payloads)}")

    print(f"organization_analysis: 대상 {len(payloads)}")
    if payloads and not dry:
        base_url = _env("NEXT_PUBLIC_SUPABASE_URL")
        service_key = _env("SUPABASE_SERVICE_ROLE_KEY")
        _api(
            "POST",
            "/organization_analysis?on_conflict=position_id",
            payloads,
            base_url=base_url,
            service_key=service_key,
            upsert=True,
        )
        print("  -> upserted")
    if dry:
        print("(dry-run — 실제 적재 안 함)")


if __name__ == "__main__":
    main(dry="--dry-run" in sys.argv)
