from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .position_followups import (
    build_followup_execution_request,
    enqueue_position_followups,
    load_followup_queue,
    write_followup_queue,
)
from .position_intake_email import build_registration_message_from_email
from .position_intake_state import (
    add_message_id,
    load_intake_state,
    message_id_in_state,
    remove_message_id,
    write_intake_state,
)
from .position_registration import (
    FY26_CLIENTS_POSITION_LIST_ID,
    RegistrationOutcome,
    run_position_registration,
)
from .request_parser import (
    PositionRegistrationRequestParseResult,
    parse_discord_position_registration_request,
)


GMAIL_POSITION_INTAKE_QUERY = (
    'to:dev@valueconnect.kr newer_than:24h '
    '(채용 OR 포지션 OR JD OR hiring OR opening) -in:sent -in:trash -in:spam'
)

RegisterPosition = Callable[..., RegistrationOutcome]
SearchThreads = Callable[[str], Iterable["IntakeEmail"]]
ExecuteFollowup = Callable[[dict[str, object]], object]


@dataclass(frozen=True)
class IntakeEmail:
    message_id: str
    subject: str
    body: str
    from_email: str = ""
    received_at: str = ""


def _call_register(
    register_position: RegisterPosition,
    parse_result: PositionRegistrationRequestParseResult,
    *,
    dry_run: bool,
    registration_deps: dict[str, object],
) -> RegistrationOutcome:
    return register_position(
        parse_result,
        clickup_list_id=FY26_CLIENTS_POSITION_LIST_ID,
        dry_run=dry_run,
        **registration_deps,
    )


def run_position_intake_tick(
    *,
    emails: Iterable[IntakeEmail],
    register_position: RegisterPosition = run_position_registration,
    queue_path: str | Path | None = None,
    state_path: str | Path | None = None,
    approved_message_ids: Sequence[str] = (),
    auto_registration_allowed: bool = False,
    owner_activity_detected: bool = False,
    blocked: bool = False,
    now_iso: str = "",
    registration_deps: dict[str, object] | None = None,
) -> dict[str, object]:
    """Run one local intake tick over already-fetched Gmail message text.

    External adapters are injected. Without explicit approval or the auto-allow
    flag, this produces only a dry-run registration preview and never queues
    followup work.
    """
    if owner_activity_detected:
        return {"status": "yielded", "events": [], "enqueued_count": 0, "reason": "owner_activity_detected"}
    if blocked:
        return {"status": "blocked", "events": [], "enqueued_count": 0, "reason": "blocked_signal"}

    approved = set(approved_message_ids)
    deps = dict(registration_deps or {})
    events: list[dict[str, object]] = []
    enqueued_count = 0
    state = load_intake_state(state_path) if state_path is not None else None
    state_dirty = False

    for email in emails:
        if state is not None and message_id_in_state(
            state, "processed_message_ids", email.message_id
        ):
            events.append({"message_id": email.message_id, "status": "already_processed"})
            continue

        registration_message = build_registration_message_from_email(email.subject, email.body)
        if not registration_message:
            events.append({"message_id": email.message_id, "status": "ignored", "reason": "not_position_email"})
            if state is not None:
                state_dirty = add_message_id(
                    state, "processed_message_ids", email.message_id
                ) or state_dirty
            continue

        parse_result = parse_discord_position_registration_request(registration_message)
        if not parse_result.should_route_to_registration:
            events.append({"message_id": email.message_id, "status": "ignored", "reason": parse_result.reason})
            if state is not None:
                state_dirty = add_message_id(
                    state, "processed_message_ids", email.message_id
                ) or state_dirty
            continue

        can_register = auto_registration_allowed or email.message_id in approved
        if (
            state is not None
            and not can_register
            and message_id_in_state(state, "pending_approval_message_ids", email.message_id)
        ):
            events.append(
                {
                    "message_id": email.message_id,
                    "status": "approval_pending",
                    "dry_run": True,
                }
            )
            continue

        if not can_register:
            preview = _call_register(
                register_position,
                parse_result,
                dry_run=True,
                registration_deps=deps,
            )
            events.append(
                {
                    "message_id": email.message_id,
                    "status": "approval_required",
                    "preview_status": preview.status,
                    "dry_run": True,
                }
            )
            if state is not None:
                state_dirty = add_message_id(
                    state, "pending_approval_message_ids", email.message_id
                ) or state_dirty
            continue

        outcome = _call_register(
            register_position,
            parse_result,
            dry_run=False,
            registration_deps=deps,
        )
        followups = enqueue_position_followups(outcome, queue_path=queue_path, now_iso=now_iso)
        enqueued_count += len(followups)
        events.append(
            {
                "message_id": email.message_id,
                "status": "registered",
                "registration_status": outcome.status,
                "task_id": outcome.task_id,
                "task_url": outcome.task_url,
                "enqueued_count": len(followups),
                "dry_run": False,
            }
        )
        if state is not None and outcome.status in {"created", "linked"} and not outcome.dry_run:
            state_dirty = add_message_id(
                state, "processed_message_ids", email.message_id
            ) or state_dirty
            state_dirty = remove_message_id(
                state, "pending_approval_message_ids", email.message_id
            ) or state_dirty

    if state is not None and state_dirty:
        write_intake_state(state, state_path)
    return {"status": "ok", "events": events, "enqueued_count": enqueued_count}


def run_scheduled_position_intake(
    *,
    search_threads: SearchThreads,
    register_position: RegisterPosition = run_position_registration,
    queue_path: str | Path | None = None,
    state_path: str | Path | None = None,
    approved_message_ids: Sequence[str] = (),
    auto_registration_allowed: bool = False,
    owner_activity_detected: bool = False,
    blocked: bool = False,
    now_iso: str = "",
    registration_deps: dict[str, object] | None = None,
) -> dict[str, object]:
    """Run one scheduled intake turn using a Gmail MCP search adapter.

    ``search_threads`` is the adapter boundary for Claude/Codex Gmail MCP. This
    module does not implement OAuth or Gmail network calls.
    """
    emails = tuple(search_threads(GMAIL_POSITION_INTAKE_QUERY))
    result = run_position_intake_tick(
        emails=emails,
        register_position=register_position,
        queue_path=queue_path,
        state_path=state_path,
        approved_message_ids=approved_message_ids,
        auto_registration_allowed=auto_registration_allowed,
        owner_activity_detected=owner_activity_detected,
        blocked=blocked,
        now_iso=now_iso,
        registration_deps=registration_deps,
    )
    return {**result, "gmail_query": GMAIL_POSITION_INTAKE_QUERY, "email_count": len(emails)}


def drain_position_followups(
    *,
    queue_path: str | Path | None = None,
    execute_followup: ExecuteFollowup,
    owner_activity_detected: bool = False,
    blocked: bool = False,
    now_iso: str = "",
    max_items: int | None = None,
) -> dict[str, object]:
    """Consume pending followups through an injected executor.

    The executor is where /url and JD-builder skill calls live. This function
    only gates and records queue state; it never sends outreach.
    """
    queue = load_followup_queue(queue_path)
    if owner_activity_detected:
        return {"yielded": True, "blocked": False, "executed_count": 0}
    if blocked:
        return {"yielded": False, "blocked": True, "executed_count": 0}

    executed_count = 0
    limit = max_items if max_items is not None else len(queue)
    for item in queue:
        if executed_count >= limit:
            break
        if item.get("status") != "pending":
            continue
        try:
            result = execute_followup(build_followup_execution_request(dict(item)))
        except Exception as exc:
            item["status"] = "blocked"
            item["blocked_reason"] = str(exc)
            item["updated_at"] = now_iso
            break
        item["status"] = "done"
        item["result"] = result if isinstance(result, dict) else {"ok": bool(result)}
        item["completed_at"] = now_iso
        item["updated_at"] = now_iso
        executed_count += 1

    write_followup_queue(queue, queue_path)
    return {"yielded": False, "blocked": False, "executed_count": executed_count}
