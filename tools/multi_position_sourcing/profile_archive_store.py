"""Local-first profile archive receipts used before any candidate scoring/advance."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .humansearch import is_valid_profile_url

DEFAULT_ARCHIVE_DB = Path.home() / ".valuehire" / "profile_archives.sqlite3"


@dataclass(frozen=True)
class ProfileSaveReceipt:
    row_id: int
    profile_url: str
    screenshot_sha256: str
    remote_status: str


class ProfileArchiveStore:
    def __init__(self, path: str | Path = DEFAULT_ARCHIVE_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS profile_archive_receipts ("
                "id INTEGER PRIMARY KEY, profile_url TEXT NOT NULL, channel TEXT NOT NULL, "
                "position_id TEXT NOT NULL, scenario TEXT NOT NULL, page INTEGER NOT NULL, "
                "candidate_index INTEGER NOT NULL, screenshot_path TEXT NOT NULL, "
                "screenshot_sha256 TEXT NOT NULL, resume_text TEXT NOT NULL, "
                "hard_exclude_reason TEXT NOT NULL DEFAULT '', captured_at REAL NOT NULL, "
                "remote_status TEXT NOT NULL DEFAULT 'pending', UNIQUE(position_id, profile_url))"
            )

    def save(
        self, *, profile_url: str, channel: str, position_id: str, scenario: str,
        page: int, candidate_index: int, screenshot_path: str | Path, resume_text: str,
        hard_exclude_reason: str = "",
    ) -> ProfileSaveReceipt:
        shot = Path(screenshot_path)
        text = (resume_text or "").strip()
        if not is_valid_profile_url(profile_url):
            raise ValueError("profile URL is missing or invalid")
        if not shot.is_file() or shot.stat().st_size <= 0:
            raise ValueError("profile screenshot is missing or empty")
        if not text:
            raise ValueError("resume text is missing or empty")
        digest = hashlib.sha256(shot.read_bytes()).hexdigest()
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO profile_archive_receipts "
                "(profile_url,channel,position_id,scenario,page,candidate_index,"
                "screenshot_path,screenshot_sha256,resume_text,hard_exclude_reason,captured_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(position_id,profile_url) DO UPDATE SET "
                "screenshot_path=excluded.screenshot_path,screenshot_sha256=excluded.screenshot_sha256,"
                "resume_text=excluded.resume_text,hard_exclude_reason=excluded.hard_exclude_reason,"
                "captured_at=excluded.captured_at",
                (profile_url, channel, position_id, scenario, page, candidate_index,
                 str(shot), digest, text, hard_exclude_reason, time.time()),
            )
            row = db.execute(
                "SELECT id, remote_status FROM profile_archive_receipts "
                "WHERE position_id=? AND profile_url=?", (position_id, profile_url)
            ).fetchone()
            if row is None:
                raise RuntimeError("local profile save receipt not found after commit")
        return ProfileSaveReceipt(int(row[0]), profile_url, digest, str(row[1]))
