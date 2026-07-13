"""Durable per-Discord-conversation position context for Hermes free-form search."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CONTEXT_TTL_SECONDS = 30 * 60
DEFAULT_CONTEXT_DB = Path.home() / ".hermes" / "valuehire_fleet_context.sqlite3"


@dataclass(frozen=True)
class PositionContext:
    position_url: str
    channels: tuple[str, ...]
    updated_at: float


class PositionContextStore:
    """Small local durable store; keys are isolated by Discord user and channel."""

    def __init__(self, path: str | Path = DEFAULT_CONTEXT_DB, *, now=time.time) -> None:
        self.path = Path(path)
        self.now = now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS position_context ("
                "user_id TEXT NOT NULL, channel_id TEXT NOT NULL, position_url TEXT NOT NULL, "
                "channels_json TEXT NOT NULL, updated_at REAL NOT NULL, "
                "PRIMARY KEY(user_id, channel_id))"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def put(self, user_id: str, channel_id: str, position_url: str,
            channels: Iterable[str]) -> None:
        normalized = tuple(dict.fromkeys(str(c) for c in channels))
        with self._connect() as db:
            db.execute(
                "INSERT INTO position_context VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, channel_id) DO UPDATE SET "
                "position_url=excluded.position_url, channels_json=excluded.channels_json, "
                "updated_at=excluded.updated_at",
                (user_id, channel_id, position_url, json.dumps(normalized), self.now()),
            )

    def get(self, user_id: str, channel_id: str) -> PositionContext | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT position_url, channels_json, updated_at FROM position_context "
                "WHERE user_id=? AND channel_id=?", (user_id, channel_id)
            ).fetchone()
        if row is None or self.now() - float(row[2]) > CONTEXT_TTL_SECONDS:
            return None
        try:
            channels = tuple(json.loads(row[1]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return PositionContext(str(row[0]), channels, float(row[2]))
