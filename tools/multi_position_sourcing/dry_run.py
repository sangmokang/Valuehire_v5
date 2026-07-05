from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from .access import (
    DiscordAuthorizedUser,
    discord_dm_routing_guard,
    load_authorized_discord_users,
)
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
from .llm_keywords import LLMClient, claude_keyword_client, inject_channel_search_filters
from .models import QueueItem, utc_now_iso
from .portal_session import PORTAL_SESSION_REQUIRED_CHANNELS, PortalSessionStatus, portal_session_flags
from .portal_worker import DEFAULT_PROFILE_ROOT
from .position_followups import load_followup_queue
from .position_intake_runner import IntakeEmail, run_position_intake_routine_once
from .posting_models import ExistingPositionTask, FetchResult, RegistrationOutcome
from .position_registration import (
    FY26_CLIENTS_POSITION_LIST_ID,
    run_position_registration,
)
from .register_position_dispatch import dispatch_register_position
from .queue_runner import run_queue_cycle
from .rps_switch import rps_in_use
from .request_parser import (
    parse_discord_position_registration_request,
    parse_discord_search_request,
)
from .scoring import top_matches_for_profile


# Rich Wanted-style HTML fixture for the dry-run position-registration sample.
# og:site_name -> company, og:title -> role, body carries >=3 distinct JD signals,
# which yields a confident "text" recognition with no network access.
_SAMPLE_REGISTRATION_HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta property="og:site_name" content="밸류커넥트">
  <meta property="og:title" content="시니어 백엔드 엔지니어">
</head>
<body>
  <h1>시니어 백엔드 엔지니어</h1>
  <h2>주요업무</h2>
  <p>백엔드 API 설계 및 개발을 담당합니다. 분산 시스템 운영 경험을 쌓습니다.</p>
  <h2>자격요건</h2>
  <p>서버 개발 5년 이상 경력, Python/Go 등 백엔드 언어 숙련.</p>
  <h2>우대사항</h2>
  <p>대규모 트래픽 처리 경험, 채용 포지션 관련 도메인 이해.</p>
</body>
</html>"""

_SAMPLE_POSITION_INTAKE_EMAIL_BODY = """시니어 백엔드 엔지니어
회사소개
밸류커넥트는 B2B 채용 자동화를 만드는 회사입니다.
주요업무
- 백엔드 API 설계 및 운영
- 검색 파이프라인 데이터 모델링
자격요건
- Python 5년 이상
- 분산 시스템 운영 경험
우대사항
- Kubernetes 경험
채용 포지션 JD입니다.
"""


def _sample_position_registration_outcome() -> object:
    """Run the position-registration execution layer over a sample Wanted URL.

    Uses small inline fixture fakes (rich-HTML http_fetch, empty clickup_search)
    in dry_run=True so there is NO real network or ClickUp side effect. Returns a
    dry-run RegistrationOutcome demonstrating "dry-run 검증 포함".
    """
    parse_result = parse_discord_position_registration_request(
        "포지션 등록 https://www.wanted.co.kr/wd/363433"
    )

    def _fixture_http_fetch(url: str) -> FetchResult:
        return FetchResult(
            url=url,
            ok=True,
            status_code=200,
            html=_SAMPLE_REGISTRATION_HTML,
            fetch_method="httpx",
        )

    def _fixture_clickup_search(_recognition) -> tuple[ExistingPositionTask, ...]:
        return ()

    return run_position_registration(
        parse_result,
        http_fetch=_fixture_http_fetch,
        clickup_search=_fixture_clickup_search,
        dry_run=True,
    )


def _ordered_unique_channels(keyword_plan) -> tuple[str, ...]:
    """keyword_plan 에 등장하는 채널을 처음 등장 순서대로 중복 제거해 반환한다."""
    seen: list[str] = []
    for session in keyword_plan:
        if session.channel not in seen:
            seen.append(session.channel)
    return tuple(seen)


def _sample_register_position_dispatch_demo() -> dict[str, object]:
    """PC-A3 end-to-end 데모 — 인가 DM register-position 인보케이션을 등록 흐름으로 디스패치.

    dry_run=True 라 부작용/발송 없음(SOT3). A-레인(A0 목적지 seam→A1 FY26 배선→A2a 필드→A3 디스패치)이
    데모 엔트리에서 실제로 도달함을 증명한다(고아 아님·R4). 자립형(외부 파일 비의존)."""
    demo_user = DiscordAuthorizedUser(
        name="Owner", alias="owner", email="", discord_id="834330913469890570"
    )
    invocation = DiscordInvocation(
        user_id=demo_user.discord_id,
        channel_id="",
        command_name="register-position",
        is_dm=True,
        invocation_kind="slash",
        guild_id="",
        member_role_ids=(),
        options={"url": "https://www.wanted.co.kr/wd/363433"},
    )
    outcome = dispatch_register_position(
        invocation,
        authorized_users=[demo_user],
        config=DiscordAccessConfig(allow_dm=True),
        dry_run=True,
    )
    return {
        "dispatched": outcome is not None,
        "status": outcome.status if outcome is not None else "not_dispatched",
        "external_posting_sent": bool(outcome is not None and outcome.external_posting_sent),
        "secret_emitted": bool(outcome is not None and outcome.secret_emitted),
        "destination_list_id": FY26_CLIENTS_POSITION_LIST_ID,
    }


def _sample_position_intake_pipeline_demo() -> dict[str, object]:
    """PI-1~PI-3 로컬 계약 데모 — 메일 인입→승인 등록→후속 큐 2건.

    임시 큐와 페이크 등록 함수만 사용한다. Gmail/ClickUp/포털/발송 side effect 없음.
    """
    register_calls: list[dict[str, object]] = []

    def _fixture_register_position(parse_result, **kwargs) -> RegistrationOutcome:
        register_calls.append(
            {
                "input_kind": parse_result.input_kind,
                "dry_run": kwargs.get("dry_run"),
                "clickup_list_id": kwargs.get("clickup_list_id"),
            }
        )
        return RegistrationOutcome(
            status="created",
            is_new_task=True,
            reason="sample position task created",
            task_id="86sampleintake",
            task_url="https://app.clickup.com/t/86sampleintake",
            dry_run=bool(kwargs.get("dry_run")),
        )

    with tempfile.TemporaryDirectory() as tmp:
        queue_path = Path(tmp) / "followups.json"
        email = IntakeEmail(
            message_id="sample-position-email",
            subject="신규 포지션 JD 공유",
            body=_SAMPLE_POSITION_INTAKE_EMAIL_BODY,
            from_email="client@example.com",
        )
        result = run_position_intake_routine_once(
            search_threads=lambda _query: (email,),
            register_position=_fixture_register_position,
            execute_followup=lambda request: {"ok": True, "prompt": request["prompt"]},
            queue_path=queue_path,
            approved_message_ids=("sample-position-email",),
            now_iso="2026-07-05T00:00:00Z",
        )
        queue = load_followup_queue(queue_path)

    return {
        "routine_status": result["status"],
        "result": result["intake"],
        "drain": result["drain"],
        "register_calls": register_calls,
        "queued_tasks": [item["task"] for item in queue],
        "followup_prompts": result["followup_prompts"],
        "send_tasks": [item["task"] for item in queue if "send" in str(item.get("task", "")).lower()],
        "destination_list_id": FY26_CLIENTS_POSITION_LIST_ID,
    }


def build_dry_run_payload(*, llm_client: LLMClient | None = None) -> dict[str, object]:
    groups = group_positions(SAMPLE_POSITIONS)
    # 슬라이스 A+B — llm_client 가 주어지면 각 채널 세션에 그 채널 칸 구조에 맞는 검색필터를
    # 주입한다(링크드인/공개웹=boolean_query, 사람인=saramin_search, 잡코리아=jobkorea_chips).
    # 없으면 기존 고정표 그대로(회귀 없음).
    positions_by_id = {position.position_id: position for position in SAMPLE_POSITIONS}

    def _plan_for(group) -> tuple:
        plan = group.keyword_plan
        if llm_client is not None and group.position_ids:
            representative = positions_by_id.get(group.position_ids[0])
            if representative is not None:
                plan = inject_channel_search_filters(plan, representative, llm_client=llm_client)
        return plan

    plans_by_group = {group.group_id: _plan_for(group) for group in groups}
    backend_group = next(group for group in groups if group.role_family == "backend")
    po_group = next(group for group in groups if group.role_family == "product_po")
    matches = top_matches_for_profile(SAMPLE_PROFILE, SAMPLE_POSITIONS, top_n=5)
    portal_session_statuses = tuple(
        PortalSessionStatus(
            channel=channel,
            ready=False,
            reason="persistent profile live check required; dry-run does not read plaintext storage state",
            source=str(DEFAULT_PROFILE_ROOT),
        )
        for channel in PORTAL_SESSION_REQUIRED_CHANNELS
    )
    # 한 번의 검색이 4채널(사람인·잡코리아·링크드인·공개웹) 모두로 펼쳐지도록,
    # 각 그룹의 keyword_plan 에 존재하는 모든 채널마다 QueueItem 을 만든다.
    # (실행 계층은 item.channel 대로 채널-바운드 러너로 검색한다.)
    queue = tuple(
        QueueItem(
            group_id=group.group_id,
            channel=channel,
            keyword_plan=tuple(
                session for session in plans_by_group[group.group_id] if session.channel == channel
            ),
        )
        for group in groups
        for channel in _ordered_unique_channels(plans_by_group[group.group_id])
    )
    cycle = run_queue_cycle(
        queue,
        now_iso=utc_now_iso(),
        chrome_connected=False,
        portal_sessions=portal_session_flags(portal_session_statuses),
        rps_in_use=rps_in_use(),
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
        "sample_position_registration_execution": asdict(
            _sample_position_registration_outcome()
        ),
        "sample_register_position_dispatch": _sample_register_position_dispatch_demo(),
        "sample_position_intake_pipeline": _sample_position_intake_pipeline_demo(),
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
    parser.add_argument(
        "--no-llm-boolean",
        action="store_true",
        help="boolean 채널 X-ray 쿼리 LLM 주입을 끈다(기본은 켬: claude -p 라이브 경로).",
    )
    args = parser.parse_args()
    # 라이브 배선: 기본적으로 boolean 채널에 LLM X-ray 쿼리를 주입한다(claude -p, 비용 0원).
    llm_client = None if args.no_llm_boolean else claude_keyword_client()
    payload = build_dry_run_payload(llm_client=llm_client)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(output))


if __name__ == "__main__":
    main()
