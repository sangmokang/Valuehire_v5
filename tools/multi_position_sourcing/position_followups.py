from __future__ import annotations

import json
from pathlib import Path

from .position_registration import FY26_CLIENTS_POSITION_LIST_ID, RegistrationOutcome


FOLLOWUP_TASKS: tuple[str, str] = ("url_presetting", "jd_set_build")
QUEUE_VERSION = 1


def default_followup_queue_path() -> Path:
    """Default local queue path, following the existing humansearch home persistence convention."""
    return Path.home() / ".vh-search-results" / "position_intake" / "followups.json"


def load_followup_queue(queue_path: str | Path | None = None) -> list[dict[str, object]]:
    path = Path(queue_path) if queue_path is not None else default_followup_queue_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def write_followup_queue(
    items: list[dict[str, object]], queue_path: str | Path | None = None
) -> None:
    path = Path(queue_path) if queue_path is not None else default_followup_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": QUEUE_VERSION, "items": items}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _position_key(outcome: RegistrationOutcome) -> str:
    task_id = (outcome.task_id or "").strip()
    if task_id:
        return f"clickup_task:{task_id}"
    task_url = (outcome.task_url or "").strip()
    if task_url:
        return f"clickup_url:{task_url}"
    return ""


def _should_enqueue(outcome: RegistrationOutcome) -> bool:
    return (
        not outcome.dry_run
        and outcome.status in {"created", "linked"}
        and bool(_position_key(outcome))
    )


def enqueue_position_followups(
    outcome: RegistrationOutcome,
    *,
    queue_path: str | Path | None = None,
    now_iso: str = "",
) -> tuple[dict[str, object], ...]:
    """Upsert /url and JD-builder followups for a successful registration outcome.

    Skipped/failed outcomes and dry-run previews do not create queue records.
    This keeps approval previews from triggering later live work.
    """
    if not _should_enqueue(outcome):
        return ()

    items = load_followup_queue(queue_path)
    by_key: dict[tuple[str, str], dict[str, object]] = {}
    for item in items:
        position_key = str(item.get("position_key") or "")
        task = str(item.get("task") or "")
        if position_key and task:
            by_key[(position_key, task)] = dict(item)

    position_key = _position_key(outcome)
    enqueued: list[dict[str, object]] = []
    for task in FOLLOWUP_TASKS:
        key = (position_key, task)
        existing = by_key.get(key, {})
        created_at = str(existing.get("created_at") or now_iso)
        item = {
            **existing,
            "position_key": position_key,
            "task": task,
            "status": str(existing.get("status") or "pending"),
            "task_id": outcome.task_id,
            "task_url": outcome.task_url,
            "clickup_list_id": FY26_CLIENTS_POSITION_LIST_ID,
            "registration_status": outcome.status,
            "dry_run": outcome.dry_run,
            "created_at": created_at,
            "updated_at": now_iso,
        }
        by_key[key] = item
        enqueued.append(item)

    task_order = {task: index for index, task in enumerate(FOLLOWUP_TASKS)}
    ordered = sorted(
        by_key.values(),
        key=lambda item: (
            str(item.get("position_key")),
            task_order.get(str(item.get("task") or ""), len(task_order)),
            str(item.get("task") or ""),
        ),
    )
    write_followup_queue(ordered, queue_path)
    return tuple(enqueued)


def build_followup_execution_request(item: dict[str, object]) -> dict[str, object]:
    """Translate a queued followup into the exact skill prompt to execute.

    The request is still inert data. The caller supplies the executor that invokes
    /url or JD-builder, so tests and dry-runs never perform portal work.
    """
    task = str(item.get("task") or "").strip()
    if task not in FOLLOWUP_TASKS:
        raise ValueError(f"unknown position followup task: {task or '(empty)'}")

    task_url = str(item.get("task_url") or "").strip()
    task_id = str(item.get("task_id") or "").strip()
    target = task_url or task_id
    if not target:
        raise ValueError("position followup requires task_url or task_id")

    prompt = f"/url {target}" if task == "url_presetting" else f"jd builder {target}"
    return {
        **item,
        "prompt": prompt,
        "skill": "/url" if task == "url_presetting" else "jd builder",
        "send_allowed": False,
        "clickup_task_id": task_id,
        "clickup_task_url": task_url,
    }
