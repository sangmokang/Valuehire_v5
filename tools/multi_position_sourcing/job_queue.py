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

# 취소는 cancel_job 전용(V1: running→cancelled 는 화이트리스트에 없음).
_RELEASE_STATUSES = ("done", "failed", "paused_for_human")
_CANCELABLE_STATUSES = ("queued", "paused_for_human")

_NETLOC_RE = None  # lazy compile


def _valid_url(url: Any) -> bool:
    """http(s) + 공백 없음 + netloc 이 호스트꼴(영숫자/점/하이픈, 선택적 :포트)."""
    global _NETLOC_RE
    if not isinstance(url, str) or not url.strip():
        return False
    u = url.strip()
    if any(ch.isspace() for ch in u):
        return False
    # V1 4R: urlparse 는 스킴을 소문자화해 'HTTPS://' 도 통과시키지만 SQL CHECK 는
    # 소문자만 허용 — DB 와 1:1 정합 위해 소문자 프리픽스만 인정.
    if not u.startswith(("http://", "https://")):
        return False
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme not in ("http", "https"):
        return False
    if _NETLOC_RE is None:
        import re
        _NETLOC_RE = re.compile(
            r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:\d{1,5})?$")
    if not parsed.netloc or not _NETLOC_RE.match(parsed.netloc):
        return False
    if ".." in parsed.netloc:            # V1 2R: 'a..b' 같은 무의미 호스트
        return False
    try:
        port = parsed.port               # V1 2R: 65535 초과 포트
    except ValueError:
        return False
    return port is None or 0 < port <= 65535


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
    # V1(worker)+V2: 개행·제어문자·유니코드 줄구분자(U+2028/2029/0085) 포함 requested_by 는
    # 프롬프트 인젝션 벡터 — 일반 스페이스 외 모든 공백류/제어문자를 큐 입구에서 차단
    if any(ch != " " and (ch.isspace() or ord(ch) < 32) for ch in requested_by):
        return None
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return None
    try:
        # V1: 직렬화 불가 params 차단. allow_nan=False — NaN/Infinity 는 유효 JSON 이 아님(V1 2R)
        json.dumps(params, allow_nan=False)
    except (TypeError, ValueError):
        return None
    if not isinstance(account_key, str) or any(ch.isspace() for ch in account_key):
        return None  # V1 2R: dict 등 비문자열 account_key 가 DB 경계까지 흘러가는 것 차단
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


def cancel_job_payload(job_id: int, reason: str = "") -> dict[str, Any]:
    """queued/paused_for_human 잡 취소용 RPC 페이로드."""
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise ValueError(f"invalid job_id: {job_id!r}")
    return {"p_job_id": job_id, "p_reason": reason or ""}


def classify_auth_probe(status: Any) -> str:
    """SOT30 S3 — 프로브 HTTP 상태코드 분류(순수).

    "ok"(2xx) / "credential_error"(401·403, 재시도 무의미·사람 개입) /
    "server_error"(그 외 전부 — 재시도성). 비정수 입력은 절대 "ok" 로 위장하지
    않는다(fail-closed) — bool 도 int 의 서브클래스라 명시 배제.
    """
    if not isinstance(status, int) or isinstance(status, bool):
        return "server_error"
    if 200 <= status < 300:
        return "ok"
    if status in (401, 403):
        return "credential_error"
    return "server_error"


# ── HTTP 클라이언트 (테스트에서는 urlopen 을 mock) ────────────────────

_URL_KEY = "NEXT_PUBLIC_SUPABASE_URL"
_SRK_KEY = "SUPABASE_SERVICE_ROLE_KEY"


def _env_config() -> tuple[str, str]:
    """(supabase_url, service_role_key) 를 *같은 출처*에서 짝으로 해석.

    V1 결함 7 반영: URL 과 키가 서로 다른 .env.local 에서 섞여 나오면
    엉뚱한 프로젝트에 service_role 키를 쏘게 된다 → 둘 다 가진 첫 출처만 채택.
    우선순위: ① 둘 다 os.environ ② VALUEHIRE_REPO_DIR/.env.local
    ③ REPO 부터 홈까지 상위 폴더의 .env.local (둘 다 가진 첫 파일).
    """
    import os

    # V1 3R: 공백만 든 환경변수가 빈 자격증명으로 통과하지 않게 strip 후 판정
    env_url = (os.environ.get(_URL_KEY) or "").strip()
    env_key = (os.environ.get(_SRK_KEY) or "").strip()
    if env_url and env_key:
        return env_url, env_key
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
        if not env.exists():
            continue
        found: dict[str, str] = {}
        for line in env.read_text().splitlines():
            for key in (_URL_KEY, _SRK_KEY):
                if line.startswith(key + "="):
                    found[key] = line.split("=", 1)[1].strip()
        if found.get(_URL_KEY) and found.get(_SRK_KEY):
            return found[_URL_KEY], found[_SRK_KEY]
    raise RuntimeError(
        f"{_URL_KEY}+{_SRK_KEY} 짝을 같은 출처(환경변수 또는 단일 .env.local)에서 찾지 못했습니다")


class JobQueueClient:
    def __init__(self, url: str = "", key: str = "") -> None:
        url, key = (url or "").strip(), (key or "").strip()  # V1 2R: 공백 자격증명 거부
        if url and key:
            self.url, self.key = url.rstrip("/"), key
        elif url or key:
            raise ValueError("url/key 는 둘 다 주거나 둘 다 생략(같은 출처 강제)")
        else:
            u, k = _env_config()
            self.url, self.key = u.rstrip("/"), k

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
        """new_job_payload 결과만 받는다 — 사후 변조 방지를 위해 필드를 재검증(V1 결함 6)."""
        if not isinstance(payload, dict):
            raise ValueError("new_job_payload 로 만든 페이로드만 enqueue 가능")
        revalidated = new_job_payload(
            machine=payload.get("machine"),
            skill=payload.get("skill"),
            position_url=payload.get("position_url"),
            requested_by=payload.get("requested_by"),
            role=payload.get("role"),
            params=payload.get("params"),
            account_key=payload.get("account_key", ""),
        )
        if revalidated is None or payload.get("status") != "queued":
            raise ValueError("무효 페이로드 — new_job_payload 검증 실패")
        rows = self._call("POST", "/jobs", revalidated)
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

    def cancel(self, job_id: int, reason: str = "") -> Any:
        """queued/paused_for_human 잡 취소 (cancel_job RPC)."""
        return self._call("POST", "/rpc/cancel_job", cancel_job_payload(job_id, reason))

    def resume(self, job_id: int) -> Any:
        """paused_for_human → queued (/resume 전용 RPC)."""
        if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
            raise ValueError(f"invalid job_id: {job_id!r}")
        return self._call("POST", "/rpc/resume_job", {"p_job_id": job_id})

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        return self._call("GET", f"/jobs?order=id.desc&limit={limit}")

    def queued_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """SOT30 S2 — watchdog 고착 판정용 queued 잡 목록(생성 오래된 것부터)."""
        limit = max(1, min(int(limit), 100))
        return self._call(
            "GET",
            "/jobs?status=eq.queued&select=id,machine,status,created_at"
            f"&order=id.asc&limit={limit}")

    def running_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """QA-1 — watchdog running 고아 판정용 잡 목록(워커 급사 가시화)."""
        limit = max(1, min(int(limit), 100))
        return self._call(
            "GET",
            "/jobs?status=eq.running&select=id,machine,status,started_at"
            f"&order=id.asc&limit={limit}")

    def heartbeats_epoch(self) -> list[dict[str, Any]]:
        """머신별 마지막 heartbeat(heartbeats_epoch RPC) — fleet-status 표시용."""
        rows = self._call("POST", "/rpc/heartbeats_epoch", {})
        return rows if isinstance(rows, list) else []

    def probe_auth(self) -> tuple[str, str]:
        """SOT30 S3 — 기동 인증 프로브(가벼운 GET 1회).

        반환 (분류, 상세). 죽은 열쇠(401)가 '조용한 무응답'으로 위장하지 못하게
        분류를 명시 반환한다. 네트워크 예외는 "server_error"(재시도성)로.
        """
        import urllib.error
        try:
            self._call("GET", "/jobs?select=id&limit=1")
            return ("ok", "")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode()[:200]
            except Exception:  # noqa: BLE001 — 본문 못 읽어도 분류는 반환
                pass
            return (classify_auth_probe(exc.code), f"HTTP {exc.code} {detail}".strip())
        except Exception as exc:  # noqa: BLE001 — URLError·타임아웃 등
            return ("server_error", str(exc)[:200])
