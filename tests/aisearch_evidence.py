"""테스트 공용 — **정본 검증기가 실제로 인정하는** 프로필 저장 영수증 생성기.

V1 3차 지적: aisearch 가 자체적으로 만든 얕은 증거 검사(경로 문자열·해시 형식)는
아무 파일이나 지정해도 통과했고, 실제 캡처 도구가 쓰는 작업명(`ai-search`)과도
어긋나 **진짜 영수증이 거부**됐다. 그래서 aisearch 는 이제
`tools/multi_position_sourcing/browser_evidence.complete_evidence_payload`
(humansearch 와 같은 정본 검증기)에 위임한다 — 중복 구현 금지.

이 헬퍼는 그 정본 검증기를 실제로 통과하는 영수증을 만든다:
0700 디렉터리 + 진짜 PNG(viewport.png) + visible-text.txt + manifest.json +
profile_archive_receipts 행이 든 SQLite 아카이브(0600).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import tempfile
import zlib
from pathlib import Path

#: 실제 캡처 도구(session_guard --task)가 쓰는 작업명. "aisearch" 가 아니다.
EVIDENCE_TASK = "ai-search"

_ROOT = Path(tempfile.mkdtemp(prefix="aisearch-evidence-")).resolve()

#: 채널별 "정식 프로필 URL" 모양 — browser_evidence._profile_identity 계약.
_PROFILE_URLS = {
    "linkedin_rps": "https://www.linkedin.com/talent/profile/{key}",
    "saramin": "https://www.saramin.co.kr/zf_user/member/resume-view?rsNo={key}&rsAppNo=1",
    "jobkorea": "https://www.jobkorea.co.kr/Corp/Person/ResumeView?Gno={key}",
}


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _tiny_png() -> bytes:
    """1x1 회색 PNG — browser_evidence._valid_png 를 통과하는 진짜 PNG."""
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00\x80")
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def canonical_profile_url(site: str, key: str) -> str:
    """해당 채널의 정식 프로필 URL(증거 계약이 요구하는 모양)."""
    template = _PROFILE_URLS.get(site)
    if template is None:
        raise ValueError(f"미지 채널: {site}")
    return template.format(key=key)


def _archive_db(folder: Path, row: dict) -> tuple[Path, int]:
    db_path = folder / "profile_archive.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS profile_archive_receipts ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, profile_url TEXT, channel TEXT, "
            "position_id TEXT, scenario TEXT, candidate_index INTEGER, "
            "screenshot_path TEXT, screenshot_sha256 TEXT, resume_text TEXT, "
            "remote_status TEXT)"
        )
        cursor = db.execute(
            "INSERT INTO profile_archive_receipts (profile_url, channel, position_id, "
            "scenario, candidate_index, screenshot_path, screenshot_sha256, resume_text, "
            "remote_status) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                row["profile_url"],
                row["site"],
                row["position_id"],
                row["task"],
                row["candidate_index"],
                row["screenshot_path"],
                row["screenshot_sha256"],
                row["resume_text"],
                "synced",
            ),
        )
        row_id = int(cursor.lastrowid)
    os.chmod(db_path, 0o600)
    return db_path, row_id


def make_evidence(
    profile_url: str,
    *,
    position_id: str,
    site: str = "linkedin_rps",
    task: str = EVIDENCE_TASK,
    mode: str = "profile",
    candidate_index: int = 1,
) -> dict:
    """정본 검증기가 인정하는 실제 영수증(파일·아카이브 행까지 진짜로 만든다)."""
    key = hashlib.sha256(f"{profile_url}|{position_id}|{site}".encode()).hexdigest()[:16]
    folder = (_ROOT / key).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)

    shot = folder / "viewport.png"
    text = folder / "visible-text.txt"
    manifest_path = folder / "manifest.json"
    resume_text = f"프로필 본문 — {profile_url}"

    if not shot.exists():
        shot.write_bytes(_tiny_png())
        os.chmod(shot, 0o600)
    if not text.exists():
        text.write_text(resume_text, encoding="utf-8")
        os.chmod(text, 0o600)

    payload = {
        "status": "saved",
        "site": site,
        "task": task,
        "mode": mode,
        "url": profile_url,
        "profile_url": profile_url,
        "position_id": position_id,
        "candidate_index": candidate_index,
        "screenshot_path": str(shot),
        "text_path": str(text),
        "manifest_path": str(manifest_path),
        "screenshot_sha256": hashlib.sha256(shot.read_bytes()).hexdigest(),
        "visible_text_sha256": hashlib.sha256(
            text.read_bytes()
        ).hexdigest(),
    }
    db_path, row_id = _archive_db(
        folder, {**payload, "resume_text": text.read_text(encoding="utf-8")}
    )
    payload["archive_db_path"] = str(db_path)
    payload["archive_row_id"] = row_id

    manifest_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.chmod(manifest_path, 0o600)
    return payload


def structural_receipt_check(value) -> bool:
    """단위 테스트용 — 영수증의 **모양**만 본다(파일 무결성은 전용 테스트 담당).

    프로덕션은 browser_evidence.complete_evidence_payload 를 쓴다. 여기서 대신
    쓰는 것은 "이 후보·이 포지션·이 채널의 프로필 캡처인가"를 판정하는 데
    필요한 필드가 갖춰졌는지까지다 — 그 판정 로직 자체는 그대로 검사된다.
    """
    if not isinstance(value, dict) or value.get("status") != "saved":
        return False
    for key in ("screenshot_path", "text_path", "manifest_path", "profile_url",
                "position_id", "site", "task", "mode"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            return False
    for key in ("screenshot_sha256", "visible_text_sha256"):
        digest = value.get(key)
        if not isinstance(digest, str) or len(digest) != 64:
            return False
    return value.get("site") in {"saramin", "jobkorea", "linkedin_rps"}


def use_structural_verifier(monkeypatch) -> None:
    """이 모듈의 테스트에서 실물 검증기를 모양 검사로 대체한다."""
    from apps.aisearch.core import recorders

    monkeypatch.setattr(recorders, "EVIDENCE_VERIFIER", structural_receipt_check)
