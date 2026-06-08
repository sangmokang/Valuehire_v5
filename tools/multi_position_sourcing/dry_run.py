from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .access import discord_dm_routing_guard
from .clickup_activity import format_clickup_activity_comment
from .dedup import canonical_profile_url
from .fixtures import SAMPLE_POSITIONS, SAMPLE_PROFILE
from .grouping import group_positions
from .models import QueueItem, utc_now_iso
from .queue_runner import run_queue_cycle
from .scoring import top_matches_for_profile


def build_dry_run_payload() -> dict[str, object]:
    groups = group_positions(SAMPLE_POSITIONS)
    backend_group = next(group for group in groups if group.role_family == "backend")
    po_group = next(group for group in groups if group.role_family == "product_po")
    matches = top_matches_for_profile(SAMPLE_PROFILE, SAMPLE_POSITIONS, top_n=5)
    queue = tuple(
        QueueItem(
            group_id=group.group_id,
            channel="saramin",
            keyword_plan=tuple(session for session in group.keyword_plan if session.channel == "saramin"),
        )
        for group in groups
    )
    cycle = run_queue_cycle(
        queue,
        now_iso=utc_now_iso(),
        chrome_connected=False,
        max_items_per_cycle=2,
    )
    return {
        "mode": "dry_run",
        "side_effects": {
            "clickup_write": False,
            "supabase_write": False,
            "rps_export_write": False,
            "outreach_clicked": False,
        },
        "position_groups": [asdict(group) for group in groups],
        "backend_keyword_plan": [asdict(session) for session in backend_group.keyword_plan],
        "product_po_keyword_plan": [asdict(session) for session in po_group.keyword_plan],
        "sample_profile_canonical_url": canonical_profile_url(SAMPLE_PROFILE.profile_url),
        "sample_profile_top_matches": [asdict(match) for match in matches],
        "sample_clickup_activity_comment": format_clickup_activity_comment(matches[0]),
        "discord_dm_routing": discord_dm_routing_guard(
            "834330913469890570",
            is_dm=True,
            access_doc_path="docs/search-access.md",
        ),
        "queue_cycle_summary": asdict(cycle),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ValueHire multi-position sourcing dry-run.")
    parser.add_argument(
        "--output",
        default="artifacts/multi_position_sourcing/dry-run-latest.json",
        help="Path for dry-run JSON artifact.",
    )
    args = parser.parse_args()
    payload = build_dry_run_payload()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(output))


if __name__ == "__main__":
    main()

