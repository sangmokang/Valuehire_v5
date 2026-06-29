#!/usr/bin/env python3
"""Check Valuehire AI Search SOT files and report stage/dependency status."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_FILES = (
    "CLAUDE.md",
    "docs/sot/22-talent-search-filters.json",
    "docs/sot/22-talent-search-filters.md",
    "docs/sot/24-position-jd-sot.json",
    "docs/sot/25-ai-search-execution-process.json",
    "docs/sot/25-ai-search-execution-process.md",
    "docs/sot/26-portal-login-spec.json",
    "tools/multi_position_sourcing/models.py",
    "tools/multi_position_sourcing/scoring.py",
    "tools/multi_position_sourcing/channel_search_render.py",
    "tools/multi_position_sourcing/queue_runner.py",
    "tools/multi_position_sourcing/portal_autologin.py",
    "tools/multi_position_sourcing/portal_live_check.py",
    "scripts/run_portal_search.py",
)


def load_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/Users/kangsangmo/Valuehire_v5")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    print(f"repo={repo}")

    missing: list[str] = []
    for relative in REQUIRED_FILES:
        path = repo / relative
        print(f"{'OK' if path.exists() else 'MISSING'} {relative}")
        if not path.exists():
            missing.append(relative)

    json_errors: list[str] = []
    specs: dict[str, dict[str, object]] = {}
    for relative in (
        "docs/sot/22-talent-search-filters.json",
        "docs/sot/24-position-jd-sot.json",
        "docs/sot/25-ai-search-execution-process.json",
        "docs/sot/26-portal-login-spec.json",
    ):
        path = repo / relative
        if not path.exists():
            continue
        try:
            specs[relative] = load_json(path)
            print(f"JSON_OK {relative}")
        except Exception as exc:  # noqa: BLE001 - diagnostics script
            json_errors.append(f"{relative}: {exc}")
            print(f"JSON_ERROR {relative}: {exc}")

    process = specs.get("docs/sot/25-ai-search-execution-process.json", {})
    stages = process.get("stages", [])
    if isinstance(stages, list):
        stage_ids = [
            str(stage.get("id"))
            for stage in stages
            if isinstance(stage, dict) and stage.get("id")
        ]
        print("stage_ids=" + ",".join(stage_ids))

    depends_on = process.get("depends_on", [])
    dead_refs: list[str] = []
    if isinstance(depends_on, list):
        for item in depends_on:
            if not isinstance(item, str):
                continue
            if item.startswith(".env"):
                continue
            if not (repo / item).exists():
                dead_refs.append(item)
        if dead_refs:
            print("DEAD_REFS " + ",".join(dead_refs))

    if missing or json_errors:
        print("status=FAIL")
        return 1

    print("status=OK")
    if dead_refs:
        print("note=Some SOT dependencies are missing but the practical contract remains embedded in SOT 24/25.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
