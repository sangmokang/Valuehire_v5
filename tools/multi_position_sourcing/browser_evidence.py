"""Exact-target browser evidence capture shared by search and login runners.

The caller must already own the site's browser lease and provide the same fresh
owner-idle guard used for browser mutations.  This module never discovers,
creates, navigates, focuses, or closes a browser target.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import struct
import time
import uuid
import zlib
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import parse_qs, urlsplit, urlunsplit

from .humansearch import is_valid_profile_url

EvidenceMode = Literal["profile", "evidence"]
_TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,47}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_SCREENSHOT_BYTES = 20 * 1024 * 1024
_MAX_VISIBLE_TEXT_CHARS = 500_000
_CAPTURE_ROOT = Path.home() / ".vh-browser-evidence"
_TASK_MODES: dict[str, EvidenceMode] = {
    "ai-search": "profile",
    "humansearch": "profile",
    "url": "evidence",
    "login": "evidence",
}


class BrowserEvidenceError(RuntimeError):
    """Fail-closed evidence error; callers must not treat the profile as saved."""


@dataclass(frozen=True)
class BrowserEvidenceReceipt:
    status: str
    site: str
    task: str
    mode: EvidenceMode
    url: str
    profile_url: str
    screenshot_path: str
    text_path: str
    manifest_path: str
    screenshot_sha256: str
    visible_text_sha256: str
    captured_at: str
    position_id: str = ""
    candidate_index: int = 0
    archive_row_id: int | None = None
    archive_db_path: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "capture_status": self.status,
            "site": self.site,
            "task": self.task,
            "mode": self.mode,
            "url": self.url,
            "profile_url": self.profile_url,
            "screenshot_path": self.screenshot_path,
            "text_path": self.text_path,
            "manifest_path": self.manifest_path,
            "screenshot_sha256": self.screenshot_sha256,
            "visible_text_sha256": self.visible_text_sha256,
            "captured_at": self.captured_at,
            "position_id": self.position_id,
            "candidate_index": self.candidate_index,
            "archive_row_id": self.archive_row_id,
            "archive_db_path": self.archive_db_path,
        }


def complete_evidence_payload(value: Any) -> bool:
    """Validate receipt fields against the actual private files and manifest."""

    if not isinstance(value, dict) or value.get("status") != "saved":
        return False
    for key in ("screenshot_path", "text_path", "manifest_path"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            return False
    if not all(
        isinstance(value.get(key), str) and _SHA256_RE.fullmatch(value[key]) is not None
        for key in ("screenshot_sha256", "visible_text_sha256")
    ):
        return False
    try:
        paths = {key: Path(value[key]) for key in ("screenshot_path", "text_path", "manifest_path")}
        if (
            paths["screenshot_path"].name != "viewport.png"
            or paths["text_path"].name != "visible-text.txt"
            or paths["manifest_path"].name != "manifest.json"
            or len({path.parent for path in paths.values()}) != 1
        ):
            return False
        evidence_dir = paths["manifest_path"].parent
        if not evidence_dir.is_absolute() or evidence_dir.is_symlink():
            return False
        directory_metadata = os.lstat(evidence_dir)
        if not stat.S_ISDIR(directory_metadata.st_mode):
            return False
        if os.name != "nt" and directory_metadata.st_mode & 0o077:
            return False
        screenshot = _read_private_regular(paths["screenshot_path"], _MAX_SCREENSHOT_BYTES)
        text = _read_private_regular(paths["text_path"], _MAX_VISIBLE_TEXT_CHARS * 4)
        if len(screenshot) > _MAX_SCREENSHOT_BYTES or not _valid_png(screenshot):
            return False
        if len(text) > _MAX_VISIBLE_TEXT_CHARS * 4 or not text.strip():
            return False
        if not text.decode("utf-8").strip():
            return False
        if hashlib.sha256(screenshot).hexdigest() != value["screenshot_sha256"]:
            return False
        if hashlib.sha256(text).hexdigest() != value["visible_text_sha256"]:
            return False
        manifest_bytes = _read_private_regular(paths["manifest_path"], 1024 * 1024)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("status") != "saved":
            return False
        for key in (
            "site",
            "task",
            "mode",
            "url",
            "profile_url",
            "position_id",
            "candidate_index",
            "archive_row_id",
            "archive_db_path",
            "screenshot_path",
            "text_path",
            "manifest_path",
            "screenshot_sha256",
            "visible_text_sha256",
        ):
            if manifest.get(key) != value.get(key):
                return False
        site = value.get("site")
        task = value.get("task")
        mode = value.get("mode")
        if site not in {"saramin", "jobkorea", "linkedin_rps"}:
            return False
        if task not in _TASK_MODES or _TASK_MODES[task] != mode:
            return False
        if mode == "profile":
            if (
                not isinstance(value.get("position_id"), str)
                or not value["position_id"].strip()
                or not isinstance(value.get("candidate_index"), int)
                or isinstance(value.get("candidate_index"), bool)
                or value["candidate_index"] < 1
                or not isinstance(value.get("archive_row_id"), int)
                or isinstance(value.get("archive_row_id"), bool)
                or value["archive_row_id"] < 1
                or not isinstance(value.get("archive_db_path"), str)
                or not value["archive_db_path"].strip()
                or not _profile_identity(site, str(value.get("profile_url") or ""))
            ):
                return False
            if not _archive_record_matches(value):
                return False
        elif (
            value.get("profile_url")
            or value.get("position_id")
            or value.get("candidate_index") != 0
            or value.get("archive_row_id") is not None
            or value.get("archive_db_path")
        ):
            return False
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return True


def _archive_record_matches(value: Mapping[str, Any]) -> bool:
    path = Path(str(value["archive_db_path"]))
    try:
        metadata = os.lstat(path)
        if (
            not path.is_absolute()
            or path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or (os.name != "nt" and metadata.st_mode & 0o077)
        ):
            return False
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute(
                "SELECT profile_url,channel,position_id,scenario,candidate_index,"
                "screenshot_path,screenshot_sha256,resume_text,remote_status "
                "FROM profile_archive_receipts WHERE id=?",
                (value["archive_row_id"],),
            ).fetchone()
        if row is None:
            return False
        return (
            row[0] == value["profile_url"]
            and row[1] == value["site"]
            and row[2] == value["position_id"]
            and row[3] == value["task"]
            and row[4] == value["candidate_index"]
            and row[5] == value["screenshot_path"]
            and row[6] == value["screenshot_sha256"]
            and hashlib.sha256(str(row[7]).encode("utf-8")).hexdigest()
            == value["visible_text_sha256"]
            and row[8] != "evidence_pending"
        )
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return False


def _read_private_regular(path: Path, maximum_bytes: int) -> bytes:
    """Read one stable regular file without following a swapped final symlink."""

    if not path.is_absolute():
        raise OSError("browser evidence path must be absolute")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
            raise OSError("browser evidence file must be non-empty and regular")
        if metadata.st_size > maximum_bytes:
            raise OSError("browser evidence file is too large")
        if os.name != "nt" and metadata.st_mode & 0o077:
            raise OSError("browser evidence file is not private")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != metadata.st_size or len(payload) > maximum_bytes:
            raise OSError("browser evidence file changed while reading")
        final_metadata = os.fstat(descriptor)
        if (
            final_metadata.st_dev != metadata.st_dev
            or final_metadata.st_ino != metadata.st_ino
            or final_metadata.st_size != metadata.st_size
        ):
            raise OSError("browser evidence file identity changed while reading")
        return payload
    finally:
        os.close(descriptor)


def _tab_target_id(tab: Any) -> str:
    value = getattr(tab, "target_id", "")
    if callable(value):
        value = value()
    return str(value or "").strip()


def _current_url(tab: Any) -> str:
    reader = getattr(tab, "current_url", None)
    if callable(reader):
        return str(reader() or "")
    evaluator = getattr(tab, "eval", None)
    if callable(evaluator):
        return str(evaluator("location.href") or "")
    raise BrowserEvidenceError("exact target current URL is unavailable")


def _visible_text(tab: Any) -> str:
    evaluator = getattr(tab, "eval", None)
    if not callable(evaluator):
        raise BrowserEvidenceError("exact target visible text operation is unavailable")
    raw = evaluator(
        "(() => document.body ? (document.body.innerText || document.body.textContent || '') : '')()"
    )
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise BrowserEvidenceError("visible browser text is empty")
    if len(text) > _MAX_VISIBLE_TEXT_CHARS:
        text = text[:_MAX_VISIBLE_TEXT_CHARS]
    return text


def _official_url(site: str, value: str) -> bool:
    from .session_guard import _official_site_url

    try:
        return _official_site_url(site, value)  # type: ignore[arg-type]
    except (KeyError, ValueError):
        return False


def _profile_identity(site: str, value: str) -> str:
    if not _official_url(site, value):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.port not in (None, 443):
            return ""
        path = parsed.path.rstrip("/")
        path_lower = path.casefold()
        query = {key.casefold(): values for key, values in parse_qs(parsed.query).items()}
    except ValueError:
        return ""
    if site == "linkedin_rps":
        match = re.search(r"/talent/profile/([^/?#]+)$", path, re.IGNORECASE)
        return f"linkedin_rps:{match.group(1)}" if match else ""
    if site == "saramin":
        if not (
            path_lower == "/zf_user/member/resume-view"
            or path_lower.startswith("/applicant-view/position/resume/")
        ):
            return ""
        query_ids: list[str] = []
        for key in ("resume_idx", "residx", "resumeid", "rno"):
            query_ids.extend(str(item).strip() for item in query.get(key, ()) if str(item).strip())
        path_match = re.fullmatch(
            r"/applicant-view/position/resume/([^/?#]+)", path, re.IGNORECASE
        )
        path_id = path_match.group(1).strip() if path_match else ""
        identities = query_ids + ([path_id] if path_id else [])
        if len(identities) != 1:
            return ""
        return f"saramin:{identities[0]}"
    if site == "jobkorea":
        if not (
            path_lower in {
                "/corp/person/find/resume/view",
                "/corp/person/detail",
                "/corp/person/view",
                "/recruit/co_read",
            }
            or path_lower.startswith("/person/")
            or path_lower.startswith("/searchfirm/")
        ):
            return ""
        query_ids = [str(item).strip() for item in query.get("rno", ()) if str(item).strip()]
        if len(query_ids) != 1:
            return ""
        return f"jobkorea:{query_ids[0]}"
    return ""


def _sanitized_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _authenticated(observation: Any, expected_url: str) -> bool:
    return bool(
        getattr(observation, "authenticated", False) is True
        and getattr(observation, "challenge", True) is False
        and getattr(observation, "auth_conflict", True) is False
        and str(getattr(observation, "url", "") or "") == expected_url
        and tuple(getattr(observation, "proof_names", ()) or ())
    )


def _valid_png(payload: bytes) -> bool:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n") or len(payload) < 45:
        return False
    offset = 8
    seen_ihdr = False
    while offset + 12 <= len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(payload):
            return False
        data = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != expected_crc:
            return False
        if not seen_ihdr:
            if chunk_type != b"IHDR" or length != 13:
                return False
            seen_ihdr = True
        if chunk_type == b"IEND":
            return seen_ihdr and length == 0 and end == len(payload)
        offset = end
    return False


def _capture_png(tab: Any) -> bytes:
    sender = getattr(tab, "send", None)
    if not callable(sender):
        raise BrowserEvidenceError("exact target screenshot operation is unavailable")
    response = sender(
        "Page.captureScreenshot",
        {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
    )
    encoded = response.get("data") if isinstance(response, dict) else None
    if not isinstance(encoded, str) or not encoded:
        raise BrowserEvidenceError("browser screenshot is empty")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BrowserEvidenceError("browser screenshot is invalid base64") from exc
    if len(payload) > _MAX_SCREENSHOT_BYTES or not _valid_png(payload):
        raise BrowserEvidenceError("browser screenshot is not one complete PNG")
    return payload


def _private_dir(path: Path) -> None:
    if path.is_symlink():
        raise BrowserEvidenceError("browser evidence directory symlink is forbidden")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise BrowserEvidenceError("browser evidence directory is unavailable")
    os.chmod(path, 0o700)


def _write_private(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short private evidence write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def _write_manifest_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        _write_private(
            temporary,
            (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _persist(
    *,
    root_dir: Path,
    site: str,
    task: str,
    mode: EvidenceMode,
    url: str,
    profile_url: str,
    screenshot: bytes,
    visible_text: str,
    archive_store: Any | None,
    position_id: str,
    candidate_index: int,
) -> BrowserEvidenceReceipt:
    captured_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    day_root = root_dir / captured_at[:10] / task
    _private_dir(root_dir)
    _private_dir(root_dir / captured_at[:10])
    _private_dir(day_root)
    identity = hashlib.sha256((profile_url or url).encode("utf-8")).hexdigest()[:12]
    leaf = f"{captured_at.replace(':', '-')}-{identity}-{uuid.uuid4().hex[:12]}"
    staging = day_root / f".{leaf}.tmp"
    final = day_root / leaf
    screenshot_path = final / "viewport.png"
    text_path = final / "visible-text.txt"
    manifest_path = final / "manifest.json"
    screenshot_hash = hashlib.sha256(screenshot).hexdigest()
    text_payload = visible_text.encode("utf-8")
    text_hash = hashlib.sha256(text_payload).hexdigest()
    archive_row_id: int | None = None
    archive_db_path = ""
    try:
        _private_dir(staging)
        _write_private(staging / "viewport.png", screenshot)
        _write_private(staging / "visible-text.txt", text_payload)
        _write_private(
            staging / "manifest.json",
            (json.dumps({"status": "pending"}) + "\n").encode("utf-8"),
        )
        os.replace(staging, final)
        manifest = {
            "status": "saved",
            "capture_status": "saved",
            "site": site,
            "task": task,
            "mode": mode,
            "url": _sanitized_url(url),
            "source_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "profile_url": profile_url,
            "screenshot_path": str(screenshot_path),
            "text_path": str(text_path),
            "manifest_path": str(manifest_path),
            "screenshot_sha256": screenshot_hash,
            "visible_text_sha256": text_hash,
            "captured_at": captured_at,
            "position_id": position_id,
            "candidate_index": candidate_index,
            "archive_row_id": archive_row_id,
            "archive_db_path": archive_db_path,
        }
        if mode == "profile":
            if archive_store is None:
                from .profile_archive_store import ProfileArchiveStore

                archive_store = ProfileArchiveStore()
            save_with_finalizer = getattr(archive_store, "save_with_finalizer", None)
            if not callable(save_with_finalizer):
                raise TypeError("profile archive store lacks atomic evidence finalizer")

            def finalize_manifest(row_id: int, database_path: Path) -> None:
                nonlocal archive_row_id, archive_db_path
                archive_row_id = int(row_id)
                archive_db_path = str(database_path)
                manifest["archive_row_id"] = archive_row_id
                manifest["archive_db_path"] = archive_db_path
                _write_manifest_atomic(manifest_path, manifest)

            receipt = save_with_finalizer(
                profile_url=profile_url,
                channel=site,
                position_id=position_id,
                scenario=task,
                page=1,
                candidate_index=candidate_index,
                screenshot_path=screenshot_path,
                resume_text=visible_text,
                finalizer=finalize_manifest,
            )
            archive_row_id = int(receipt.row_id)
        else:
            _write_manifest_atomic(manifest_path, manifest)
    except BaseException as exc:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(final, ignore_errors=True)
        raise BrowserEvidenceError("browser evidence persistence failed") from exc
    return BrowserEvidenceReceipt(
        status="saved",
        site=site,
        task=task,
        mode=mode,
        url=_sanitized_url(url),
        profile_url=profile_url,
        screenshot_path=str(screenshot_path),
        text_path=str(text_path),
        manifest_path=str(manifest_path),
        screenshot_sha256=screenshot_hash,
        visible_text_sha256=text_hash,
        captured_at=captured_at,
        position_id=position_id,
        candidate_index=candidate_index,
        archive_row_id=archive_row_id,
        archive_db_path=archive_db_path,
    )


def capture_owned_browser_evidence(
    tab: Any,
    *,
    site: str,
    task: str,
    mode: EvidenceMode,
    expected_target_id: str,
    mutation_guard: Callable[[], None],
    auth_probe: Callable[[Any, str], Any],
    profile_url: str = "",
    root_dir: str | Path = _CAPTURE_ROOT,
    archive_store: Any | None = None,
    position_id: str = "",
    candidate_index: int = 0,
) -> BrowserEvidenceReceipt:
    """Capture one stable viewport/text pair from the already-owned exact target."""

    if site not in {"saramin", "jobkorea", "linkedin_rps"}:
        raise BrowserEvidenceError("unsupported browser evidence site")
    if mode not in {"profile", "evidence"}:
        raise BrowserEvidenceError("unsupported browser evidence mode")
    if not _TASK_RE.fullmatch(str(task or "")) or _TASK_MODES.get(task) != mode:
        raise BrowserEvidenceError("browser evidence task name is invalid")
    if not expected_target_id or _tab_target_id(tab) != expected_target_id:
        raise BrowserEvidenceError("exact browser target identity changed")
    def prove_safe() -> None:
        try:
            mutation_guard()
        except BrowserEvidenceError:
            raise
        except Exception as exc:
            raise BrowserEvidenceError("fresh browser owner and lease proof failed") from exc

    prove_safe()
    initial_url = _current_url(tab)
    if not _official_url(site, initial_url):
        raise BrowserEvidenceError("browser evidence URL is not an official site")
    if mode == "profile":
        if not is_valid_profile_url(profile_url) or not position_id or candidate_index < 1:
            raise BrowserEvidenceError("profile evidence identity is incomplete")
        initial_identity = _profile_identity(site, initial_url)
        requested_identity = _profile_identity(site, profile_url)
        if not initial_identity or initial_identity != requested_identity:
            raise BrowserEvidenceError("profile identity changed before capture")
    observation = auth_probe(tab, site)
    if not _authenticated(observation, initial_url):
        raise BrowserEvidenceError("authenticated browser evidence required")
    initial_text = _visible_text(tab)

    prove_safe()
    screenshot = _capture_png(tab)

    prove_safe()
    final_url = _current_url(tab)
    final_observation = auth_probe(tab, site)
    final_text = _visible_text(tab)
    if final_url != initial_url or final_text != initial_text:
        raise BrowserEvidenceError("browser page changed during capture")
    if not _authenticated(final_observation, final_url):
        raise BrowserEvidenceError("authenticated browser evidence required after capture")
    if _tab_target_id(tab) != expected_target_id:
        raise BrowserEvidenceError("exact browser target identity changed")

    prove_safe()
    return _persist(
        root_dir=Path(root_dir).expanduser(),
        site=site,
        task=task,
        mode=mode,
        url=final_url,
        profile_url=profile_url,
        screenshot=screenshot,
        visible_text=final_text,
        archive_store=archive_store,
        position_id=position_id,
        candidate_index=candidate_index,
    )
