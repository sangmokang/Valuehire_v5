"""함대 작업 큐 — Supabase jobs/account_locks 클라이언트 (2026-07-11 사장님 지시).

설계 근거: docs/prompts/fleet-control-sequential-prompts-2026-07-11.md §프롬프트 A.
- 순수 매핑 함수(new_job_payload, is_valid_transition, claim/release 페이로드)는
  기계 검증 대상(tests/test_job_queue.py) — fail-closed: 무효 입력은 None/ValueError.
- HTTP 적재는 JobQueueClient 가 REST/RPC 로 수행(기존 humansearch_supabase_backfill 패턴).
- 발송성 스킬은 이 계층에 존재할 수 없다(SOT28 발송 게이트 — 큐로는 서치·수집만).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

FLEET_MACHINES: tuple[str, ...] = ("macmini", "macbook", "winpc")
FLEET_SKILLS: tuple[str, ...] = ("humansearch", "aisearch", "url")
FLEET_ROLES: tuple[str, ...] = ("owner", "member")

# 상태 전이 화이트리스트 — 여기 없는 전이는 전부 거부.
ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "queued": ("running", "cancelled"),
    "running": ("paused_for_human", "done", "failed"),
    "paused_for_human": ("queued", "cancelled"),  # queued 복귀 = /resume
    "done": (),
    "failed": (),
    "cancelled": (),
}

_RELEASE_STATUSES = ("done", "failed", "cancelled", "paused_for_human")


def _valid_url(url: Any) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    parsed = urllib.parse.urlparse(url.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def default_account_key(skill: str, machine: str) -> str:
    """계정↔머신 1:1 기본 정책 — 명시 account_key 없으면 머신 바인딩 키."""
    return f"portal:{machine}"


def new_job_payload(
    *,
    machine: Any,
    skill: Any,
    position_url: Any,
    requested_by: Any,
    role: Any,
    params: Any = None,
    account_key: str = "",
) -> dict[str, Any] | None:
    """jobs insert 페이로드. 무효 입력은 None(fail-closed) — 조용한 보정 금지."""
    if machine not in FLEET_MACHINES:
        return None
    if skill not in FLEET_SKILLS:
        return None
    if role not in FLEET_ROLES:
        return None
    if not _valid_url(position_url):
        return None
    if not isinstance(requested_by, str) or not requested_by.strip():
        return None
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return None
    return {
        "machine": machine,
        "skill": skill,
        "position_url": position_url.strip(),
        "params": params,
        "requested_by": requested_by.strip(),
        "role": role,
        "status": "queued",
        "account_key": account_key or default_account_key(skill, machine),
    }


def is_valid_transition(old: Any, new: Any) -> bool:
    return new in ALLOWED_TRANSITIONS.get(old, ())


def claim_next_job_payload(machine: str) -> dict[str, str]:
    if machine not in FLEET_MACHINES:
        raise ValueError(f"unknown machine: {machine!r}")
    return {"p_machine": machine}


def release_job_payload(
    job_id: int,
    status: str,
    *,
    result_summary: str = "",
    error: str = "",
) -> dict[str, Any]:
    """running → 종결/일시정지 전환용 RPC 페이로드. 재큐잉은 release 가 아니라 resume."""
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise ValueError(f"invalid job_id: {job_id!r}")
    if status not in _RELEASE_STATUSES:
        raise ValueError(f"release 불가 상태: {status!r}")
    return {
        "p_job_id": job_id,
        "p_status": status,
        "p_result_summary": result_summary or "",
        "p_error": error or "",
    }


# ── HTTP 클라이언트 (테스트에서는 urlopen 을 mock) ────────────────────

def _env(key: str) -> str:
    """os.environ 우선, 없으면 REPO 부터 홈까지 상위로 올라가며 .env.local 탐색.

    워크트리(.claude/worktrees/*)나 타 머신(VALUEHIRE_REPO_DIR 지정)에서도 동작해야 한다.
    """
    import os

    if os.environ.get(key):
        return os.environ[key].strip()
    bases: list[Path] = []
    if os.environ.get("VALUEHIRE_REPO_DIR"):
        bases.append(Path(os.environ["VALUEHIRE_REPO_DIR"]))
    cur = REPO
    home = Path.home()
    while True:
        bases.append(cur)
        if cur == home or cur.parent == cur:
            break
        cur = cur.parent
    for base in bases:
        env = base / ".env.local"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip()
    raise RuntimeError(f"{key} 를 환경변수/.env.local 에서 찾지 못했습니다")


class JobQueueClient:
    def __init__(self, url: str = "", key: str = "") -> None:
        self.url = (url or _env("NEXT_PUBLIC_SUPABASE_URL")).rstrip("/")
        self.key = key or _env("SUPABASE_SERVICE_ROLE_KEY")

    def _call(self, method: str, path: str, payload: Any = None,
              prefer: str = "return=representation") -> Any:
        req = urllib.request.Request(
            f"{self.url}/rest/v1{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Prefer": prefer,
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode() or "null"
        return json.loads(body)

    def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        """new_job_payload 결과만 받는다. None/비정형 dict 는 거부."""
        if not payload or payload.get("status") != "queued":
            raise ValueError("new_job_payload 로 만든 페이로드만 enqueue 가능")
        rows = self._call("POST", "/jobs", payload)
        return rows[0] if isinstance(rows, list) and rows else rows

    def claim_next(self, machine: str) -> dict[str, Any] | None:
        rows = self._call("POST", "/rpc/claim_next_job", claim_next_job_payload(machine))
        if isinstance(rows, list):
            return rows[0] if rows else None
        return rows or None

    def release(self, job_id: int, status: str, *, result_summary: str = "",
                error: str = "") -> Any:
        return self._call(
            "POST", "/rpc/release_job",
            release_job_payload(job_id, status, result_summary=result_summary, error=error),
        )

    def resume(self, job_id: int) -> Any:
        """paused_for_human → queued (/resume 전용 RPC)."""
        if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
            raise ValueError(f"invalid job_id: {job_id!r}")
        return self._call("POST", "/rpc/resume_job", {"p_job_id": job_id})

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        return self._call("GET", f"/jobs?order=id.desc&limit={limit}")
