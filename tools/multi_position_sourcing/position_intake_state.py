from __future__ import annotations

import json
from pathlib import Path


STATE_VERSION = 1


def default_intake_state_path() -> Path:
    return Path.home() / ".vh-search-results" / "position_intake" / "state.json"


def _string_ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        message_id = str(item or "").strip()
        if message_id and message_id not in seen:
            out.append(message_id)
            seen.add(message_id)
    return out


def _normalise_state(payload: object) -> dict[str, object]:
    source = payload if isinstance(payload, dict) else {}
    return {
        "version": STATE_VERSION,
        "processed_message_ids": _string_ids(source.get("processed_message_ids")),
        "pending_approval_message_ids": _string_ids(source.get("pending_approval_message_ids")),
    }


def load_intake_state(state_path: str | Path | None = None) -> dict[str, object]:
    path = Path(state_path) if state_path is not None else default_intake_state_path()
    if not path.exists():
        return _normalise_state({})
    try:
        return _normalise_state(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return _normalise_state({})


def write_intake_state(state: dict[str, object], state_path: str | Path | None = None) -> None:
    path = Path(state_path) if state_path is not None else default_intake_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _normalise_state(state)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def message_id_in_state(state: dict[str, object], key: str, message_id: str) -> bool:
    return message_id in set(_string_ids(state.get(key)))


def add_message_id(state: dict[str, object], key: str, message_id: str) -> bool:
    message_id = (message_id or "").strip()
    if not message_id:
        return False
    ids = _string_ids(state.get(key))
    if message_id in ids:
        state[key] = ids
        return False
    ids.append(message_id)
    state[key] = ids
    return True


def remove_message_id(state: dict[str, object], key: str, message_id: str) -> bool:
    message_id = (message_id or "").strip()
    ids = _string_ids(state.get(key))
    kept = [item for item in ids if item != message_id]
    state[key] = kept
    return len(kept) != len(ids)
