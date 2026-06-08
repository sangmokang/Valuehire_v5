from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .access import discord_dm_routing_guard, load_authorized_discord_users
from .clickup_activity import format_clickup_activity_comment
from .dedup import canonical_profile_url
from .discord_briefing import format_discord_candidate_briefing
from .discord_routing import (
    DiscordAccessConfig,
    DiscordInvocation,
    discord_message_content_intent_required,
    discord_slash_command_payloads,
    load_discord_access_config,
    parse_discord_command_text,
    route_discord_invocation,
)
from .fixtures import SAMPLE_POSITIONS, SAMPLE_PROFILE
from .grouping import group_positions
from .models import QueueItem, utc_now_iso
from .portal_session import portal_session_flags, portal_session_statuses_from_storage_state
from .queue_runner import run_queue_cycle
from .request_parser import (
    parse_discord_position_registration_request,
    parse_discord_search_request,
)
from .scoring import top_matches_for_profile


def build_dry_run_payload() -> dict[str, object]:
    groups = group_positions(SAMPLE_POSITIONS)
    backend_group = next(group for group in groups if group.role_family == "backend")
    po_group = next(group for group in groups if group.role_family == "product_po")
    matches = top_matches_for_profile(SAMPLE_PROFILE, SAMPLE_POSITIONS, top_n=5)
    portal_session_statuses = portal_session_statuses_from_storage_state(
        "artifacts/portal_search_storage_state.json"
    )
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
        portal_sessions=portal_session_flags(portal_session_statuses),
        max_items_per_cycle=2,
    )
    slash_parse = parse_discord_command_text('/run-search source:saramin keyword:"backend"')
    channel_decision = route_discord_invocation(
        DiscordInvocation(
            user_id="834330913469890570",
            channel_id="123456789012345678",
            guild_id="123456789012345679",
            command_name=slash_parse.command_name,
            is_dm=False,
            invocation_kind=slash_parse.invocation_kind,
            member_role_ids=("222222222222222222",),
            options=slash_parse.options,
        ),
        authorized_users=load_authorized_discord_users("docs/search-access.md"),
        config=DiscordAccessConfig(
            allowed_channel_ids=("123456789012345678",),
            allowed_role_ids=("222222222222222222",),
        ),
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
        "sample_discord_candidate_briefing": format_discord_candidate_briefing(matches[0]),
        "portal_session_statuses": [asdict(status) for status in portal_session_statuses],
        "discord_dm_routing": discord_dm_routing_guard(
            "834330913469890570",
            is_dm=True,
            access_doc_path="docs/search-access.md",
        ),
        "sample_discord_position_registration_routing": {
            "registration": asdict(
                parse_discord_position_registration_request(
                    "포지션 등록 https://www.wanted.co.kr/wd/363433"
                )
            ),
            "search_suppressed": asdict(
                parse_discord_search_request(
                    "포지션 등록 https://www.wanted.co.kr/wd/363433"
                )
            ),
        },
        "discord_server_routing": {
            "slash_parse": {
                "should_route": slash_parse.should_route,
                "invocation_kind": slash_parse.invocation_kind,
                "command_name": slash_parse.command_name,
                "options": dict(slash_parse.options),
                "reason": slash_parse.reason,
            },
            "channel_decision": asdict(channel_decision),
            "configured_channels_from_env": load_discord_access_config().allowed_channel_ids,
            "message_content_intent_required_for_safe_default": discord_message_content_intent_required(
                free_text_channel_commands=False
            ),
            "slash_command_names": [payload["name"] for payload in discord_slash_command_payloads()],
        },
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
