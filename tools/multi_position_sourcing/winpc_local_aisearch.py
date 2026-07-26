"""Owner-explicit AI Search execution on the current Windows PC.

This entrypoint starts/reuses the WinPC managed portal browser, repairs the
exact-target login receipt when necessary, and invokes the canonical AI Search
prompt locally.  It never creates or claims a fleet queue job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .fleet_worker import (
    _run_codex,
    build_job_prompt,
    parse_worker_output,
    validate_aisearch_receipt,
)
from .job_queue import _valid_url
from . import login_barrier
from .winpc_portal_browser import ensure_windows_portal_browser, winpc_environment


REPO = Path(__file__).resolve().parents[2]
LOCAL_SEARCH_TIMEOUT_SECONDS = 14_400
DEFAULT_ARTIFACT_ROOT = REPO / "artifacts" / "winpc-local-aisearch"
DEFAULT_LOCK_PATH = Path.home() / ".valuehire" / "winpc-local-aisearch.lock"
LOCAL_EXECUTOR_MARKER = "VALUEHIRE_WINPC_LOCAL_AISEARCH_EXECUTOR=1"
_CHANNELS = ("saramin", "jobkorea")
_CLICKUP_TASK_PATH = re.compile(r"^/t/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)?$")
_ENV_LINE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")
_SECRET_KEY = re.compile(
    r"(?:password|passwd|cookie|token|secret|authorization|api[_-]?key)",
    re.IGNORECASE,
)


def _normalize_clickup_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path.rstrip("/")
    if (
        not _valid_url(url)
        or parsed.scheme != "https"
        or parsed.hostname != "app.clickup.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not _CLICKUP_TASK_PATH.fullmatch(path)
    ):
        raise ValueError("exact ClickUp task URL is required")
    return f"https://app.clickup.com{path}"


@dataclass(frozen=True)
class LocalAisearchRequest:
    position_url: str = field(repr=False)
    channels: tuple[str, ...] = ("saramin",)
    requested_by: str = field(default="owner-local", repr=False)
    job_id: int = field(default_factory=lambda: int(time.time_ns() // 1_000_000))

    def __post_init__(self) -> None:
        clean_url = _normalize_clickup_url(self.position_url)
        channels = tuple(
            dict.fromkeys(str(channel).strip().casefold() for channel in self.channels)
        )
        if not channels or any(channel not in _CHANNELS for channel in channels):
            raise ValueError("WinPC local AI Search channels are saramin/jobkorea")
        if not isinstance(self.job_id, int) or isinstance(self.job_id, bool) or self.job_id <= 0:
            raise ValueError("job_id must be a positive integer")
        object.__setattr__(self, "position_url", clean_url)
        object.__setattr__(self, "channels", channels)

    def as_job(self) -> dict[str, Any]:
        return {
            "id": self.job_id,
            "machine": "winpc",
            "skill": "aisearch",
            "position_url": self.position_url,
            "requested_by": self.requested_by,
            "role": "owner",
            "params": {
                "channels": list(self.channels),
                "execution": "live",
                "queue_mode": "none",
                "agent": "codex",
                "local_archive_required": True,
            },
        }


@dataclass(frozen=True)
class LocalAisearchResult:
    status: str
    job_id: str
    machine: str
    channels: tuple[str, ...]
    artifact_dir: Path
    reason: str = field(default="", repr=False)

    def public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "job_id": self.job_id,
            "machine": self.machine,
            "channels": list(self.channels),
            "artifact_dir": str(self.artifact_dir),
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


class LocalAisearchBusy(RuntimeError):
    pass


class _LocalRunLock:
    """OS byte lock; process death releases it without stale-file deletion."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any | None = None

    def __enter__(self) -> "_LocalRunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise LocalAisearchBusy("another WinPC local AI Search is running") from exc
        self._handle = handle
        return self

    def __exit__(self, *_exc: object) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _env_file_candidates(source: Mapping[str, str]) -> list[Path]:
    roots: list[Path] = []
    explicit = str(source.get("VALUEHIRE_REPO_DIR") or "").strip()
    if explicit:
        roots.append(Path(explicit))
    roots.extend((Path.cwd(), REPO))
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        resolved = str(root.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(root)
    return [
        root / name
        for root in unique
        for name in (".env.local", ".env")
    ]


def _load_local_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = dict(os.environ if environ is None else environ)
    for path in _env_file_candidates(source):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            match = _ENV_LINE.match(line.strip())
            if not match:
                continue
            key = match.group("key")
            if str(source.get(key) or ""):
                continue
            value = match.group("value").strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            source[key] = value
    # Windows Korean consoles default to cp949, which cannot encode several
    # status punctuation characters emitted by the canonical login/search code.
    source["PYTHONUTF8"] = "1"
    source["PYTHONIOENCODING"] = "utf-8"
    native_codex = shutil.which("codex.exe", path=source.get("PATH"))
    if native_codex:
        source["VALUEHIRE_CODEX_BIN"] = native_codex
    local = winpc_environment(source)
    local.update(
        {
            "VALUEHIRE_OWNER_LOCAL_AI_SEARCH": "1",
            "VALUEHIRE_JOB_SKILL": "aisearch",
            "VALUEHIRE_JOB_ROLE": "owner",
        }
    )
    return local


def _safe_text(value: object, environ: Mapping[str, str]) -> str:
    text = str(value or "")
    for key, secret in sorted(environ.items(), key=lambda item: len(item[1]), reverse=True):
        if _SECRET_KEY.search(key) and len(secret) >= 4:
            text = text.replace(secret, "[REDACTED]")
    return text


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _login_subprocess(site: str, *, environ: Mapping[str, str]) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "tools.multi_position_sourcing.session_guard",
        "auto-login",
        "--site",
        site,
        "--agent",
        "Codex",
        "--owner-explicit-local",
    ]
    proc = subprocess.run(
        command,
        cwd=str(REPO),
        env=dict(environ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        shell=False,
    )
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    if not lines:
        return {"status": "failed", "note": "login runner returned no status"}
    try:
        payload = json.loads(lines[-1])
    except ValueError:
        return {"status": "failed", "note": "login runner returned malformed status"}
    return payload if isinstance(payload, dict) else {"status": "failed"}


def prepare_local_portals(
    channels: tuple[str, ...],
    *,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    states = []
    for channel in channels:
        states.append(ensure_windows_portal_browser(channel, environ=environ))
        probe_job = {
            "skill": "aisearch",
            "params": {"channels": [channel]},
        }
        reason = login_barrier.job_block_reason(
            probe_job,
            machine="winpc",
            now_epoch=time.time(),
        )
        if reason is None:
            continue
        login = _login_subprocess(channel, environ=environ)
        state = str(login.get("state") or login.get("status") or "")
        if state == "HUMAN_AUTH":
            return {
                "status": "paused_for_human",
                "channel": channel,
                "reason": str(login.get("note") or "보안 확인 필요"),
                "browsers": states,
            }
        if state != "AUTHENTICATED":
            return {
                "status": "failed",
                "channel": channel,
                "reason": str(login.get("note") or state or "로그인 준비 실패"),
                "browsers": states,
            }
        refreshed = login_barrier.job_block_reason(
            probe_job,
            machine="winpc",
            now_epoch=time.time(),
        )
        if refreshed is not None:
            return {
                "status": "failed",
                "channel": channel,
                "reason": refreshed,
                "browsers": states,
            }
    return {"status": "ready", "channels": list(channels), "browsers": states}


def _default_runner(
    prompt: str,
    timeout: int,
    *,
    env: Mapping[str, str],
) -> tuple[str, str, int]:
    return _run_codex(prompt, timeout, env=env)


Runner = Callable[..., tuple[str, str, int]]
PortalPreparer = Callable[..., Mapping[str, Any]]


def run_local_aisearch(
    request: LocalAisearchRequest,
    *,
    dry_run: bool = False,
    artifact_root: str | Path = DEFAULT_ARTIFACT_ROOT,
    lock_path: str | Path = DEFAULT_LOCK_PATH,
    environ: Mapping[str, str] | None = None,
    portal_preparer: PortalPreparer = prepare_local_portals,
    runner: Runner = _default_runner,
    system_name: str | None = None,
) -> LocalAisearchResult:
    if (system_name or platform.system()) != "Windows":
        raise RuntimeError("WinPC local AI Search requires Windows")
    run_dir = Path(artifact_root) / f"job-{request.job_id}"
    with _LocalRunLock(Path(lock_path)):
        run_dir.mkdir(parents=True, exist_ok=True)
        job = request.as_job()
        prompt = (
            f"{LOCAL_EXECUTOR_MARKER}\n"
            "이 프롬프트는 이미 WinPC 로컬 실행기 안에서 실행 중입니다. "
            "winpc_local_aisearch 모듈을 다시 호출하지 말고 현재 프로세스에서 "
            "AI Search 단계들을 직접 수행하십시오.\n"
            "$ai-search\n"
            + build_job_prompt(job)
        )
        base = {
            "job_id": str(request.job_id),
            "machine": "winpc",
            "channels": list(request.channels),
            "position_url": request.position_url,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "started_at": time.time(),
        }
        if dry_run:
            _write_json(
                run_dir / "receipt.json",
                {**base, "status": "dry_run", "completed_at": time.time()},
            )
            return LocalAisearchResult(
                "dry_run",
                str(request.job_id),
                "winpc",
                request.channels,
                run_dir,
            )

        process_env = _load_local_environment(environ)
        prepared = portal_preparer(request.channels, environ=process_env)
        prepared_status = str(prepared.get("status") or "")
        if prepared_status != "ready":
            status = (
                "paused_for_human"
                if prepared_status == "paused_for_human"
                else "failed"
            )
            reason = _safe_text(prepared.get("reason") or prepared_status, process_env)
            _write_json(
                run_dir / "receipt.json",
                {
                    **base,
                    "status": status,
                    "reason": reason,
                    "completed_at": time.time(),
                },
            )
            return LocalAisearchResult(
                status,
                str(request.job_id),
                "winpc",
                request.channels,
                run_dir,
                reason=reason,
            )

        try:
            stdout, stderr, exit_code = runner(
                prompt,
                LOCAL_SEARCH_TIMEOUT_SECONDS,
                env=process_env,
            )
        except subprocess.TimeoutExpired:
            stdout, stderr, exit_code = "", "local agent timeout", 124
        except Exception as exc:  # noqa: BLE001 - failure is recorded with secrets removed
            stdout, stderr, exit_code = "", str(exc), 1
        safe_stdout = _safe_text(stdout, process_env)
        safe_stderr = _safe_text(stderr, process_env)
        (run_dir / "stdout.log").write_text(safe_stdout, encoding="utf-8")
        (run_dir / "stderr.log").write_text(safe_stderr, encoding="utf-8")
        parsed = parse_worker_output(stdout, exit_code, stderr=stderr)
        status = str(parsed.get("status") or "failed")
        reason = _safe_text(parsed.get("reason") or "", process_env)
        receipt: Mapping[str, Any] | None = None
        if status == "done":
            try:
                receipt = validate_aisearch_receipt(stdout, job["params"])
            except ValueError as exc:
                status = "failed"
                reason = _safe_text(exc, process_env)
        payload: dict[str, Any] = {
            **base,
            "status": status,
            "reason": reason,
            "exit_code": int(exit_code),
            "completed_at": time.time(),
        }
        if receipt is not None:
            payload["receipt"] = receipt
        _write_json(run_dir / "receipt.json", payload)
        return LocalAisearchResult(
            status,
            str(request.job_id),
            "winpc",
            request.channels,
            run_dir,
            reason=reason,
        )


def _parse_channels(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def main(argv: list[str] | None = None) -> int:
    if platform.system() == "Windows":
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Run Valuehire AI Search on this WinPC")
    parser.add_argument("--url", required=True)
    parser.add_argument("--channels", default="saramin")
    parser.add_argument("--job-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = LocalAisearchRequest(
            position_url=args.url,
            channels=_parse_channels(args.channels),
            **({"job_id": args.job_id} if args.job_id is not None else {}),
        )
        result = run_local_aisearch(request, dry_run=args.dry_run)
    except LocalAisearchBusy as exc:
        print(json.dumps({"status": "busy", "reason": str(exc)}, ensure_ascii=False))
        return 3
    except Exception as exc:  # noqa: BLE001 - CLI reports only a short non-secret reason
        print(json.dumps({"status": "failed", "reason": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result.public_dict(), ensure_ascii=False))
    return 0 if result.status in {"done", "dry_run", "paused_for_human"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
