"""함대 작업 큐 — Supabase jobs/account_locks 클라이언트 (2026-07-11 사장님 지시).

설계 근거: docs/prompts/fleet-control-sequential-prompts-2026-07-11.md §프롬프트 A.
- 순수 매핑 함수(new_job_payload, is_valid_transition, claim/release 페이로드)는
  기계 검증 대상(tests/test_job_queue.py) — fail-closed: 무효 입력은 None/ValueError.
- HTTP 적재는 JobQueueClient 가 REST/RPC 로 수행(기존 humansearch_supabase_backfill 패턴).
- 발송성 스킬은 이 계층에 존재할 수 없다(SOT28 발송 게이트 — 큐로는 서치·수집만).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

# Bootstrap/default machines remain useful for aliases and status views, but
# they are no longer an admission whitelist. Registered machine IDs are
# dynamic and share this syntax with fleet_machines.machine_id in PostgreSQL.
FLEET_MACHINES: tuple[str, ...] = ("macmini", "macbook", "winpc")
FLEET_SKILLS: tuple[str, ...] = ("humansearch", "aisearch", "url")
OWNER_AGENT_SKILL = "agent"
QUEUE_SKILLS: tuple[str, ...] = (*FLEET_SKILLS, OWNER_AGENT_SKILL)
OWNER_AGENT_MAX_REQUEST_CHARS = 8_000
FLEET_ROLES: tuple[str, ...] = ("owner", "member")
FLEET_AGENTS: tuple[str, ...] = ("claude", "codex")  # 이슈 B — 실행 엔진 화이트리스트

_SNOWFLAKE_RE = re.compile(r"^[0-9]{15,22}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OWNER_AGENT_PARAM_KEYS = frozenset({
    "request_text", "agent", "approval_id", "prompt_sha256",
    "approval_sha256", "idempotency_key", "execution_mode",
})


def _approval_sha256(request: str, agent: str, mode: str, approval_id: str) -> str:
    encoded = (value.encode("utf-8") for value in (request, agent, mode, approval_id))
    material = b"".join(str(len(value)).encode("ascii") + b":" + value for value in encoded)
    return hashlib.sha256(material).hexdigest()

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


def is_valid_machine_id(machine: Any) -> bool:
    """Match the database machine_id contract without silently normalizing."""
    if not isinstance(machine, str) or not 1 <= len(machine) <= 64:
        return False
    if not ("a" <= machine[0] <= "z" or "0" <= machine[0] <= "9"):
        return False
    return all(
        "a" <= char <= "z" or "0" <= char <= "9" or char in "_-"
        for char in machine
    )


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
    if port is not None and not 0 < port <= 65535:
        return False
    # 조각 G(goal 2026-07-17 §5): SSRF 1단 — IP 리터럴·localhost 계열은 큐에 못 들어간다.
    return not _host_forbidden_literal(parsed.hostname or "")


def _ip_is_global(ip: str) -> bool:
    """공인 주소만 True. loopback/private/link-local(메타데이터 169.254.169.254 포함)/
    reserved/CGNAT/unspecified 는 ipaddress.is_global 이 전부 False — 그걸 그대로 쓴다.
    multicast 는 명시 배제(파이썬 버전별 is_global 판정 흔들림 방지). 파싱 불가는 False."""
    try:
        addr = ipaddress.ip_address(ip.partition("%")[0])  # fe80::1%en0 의 scope 제거
    except ValueError:
        return False
    # V1-F2: fec0::/10 site-local 은 deprecated 라 ipaddress.is_global 이 True 로 오판하지만
    # 여전히 내부 라우팅 대역 — 명시 차단. IPv6Address.is_site_local 로 잡는다.
    if getattr(addr, "is_site_local", False):
        return False
    return addr.is_global and not addr.is_multicast


def _looks_like_ip_literal_host(host: str) -> bool:
    """호스트가 '진짜 도메인'이 아니라 IP 를 흉내낸 숫자 표기인지 — DNS 없이 판정.

    실도메인의 최상위 라벨(TLD)은 항상 알파벳으로 끝난다. 따라서 마지막 라벨이 순수 숫자
    이거나(예: 010.0.0.1, 127.1), 호스트 전체가 십진 정수(예: 2130706433)이거나, 0x·0o
    같은 진법 접두를 쓰면 IP 흉내 표기로 본다 — ipaddress 가 표준 표기만 파싱하는 틈으로
    십진/8진/16진 loopback 이 새는 것을 1단에서 막는다(V1-F5, 방어심층)."""
    if host.isdigit():                    # 순수 십진 정수형 IP (2130706433 = 127.0.0.1)
        return True
    labels = host.split(".")
    last = labels[-1]
    if last and (last.isdigit() or last.startswith(("0x", "0o"))):
        return True
    return False


def _host_forbidden_literal(host: str) -> bool:
    """DNS 없이 판정 가능한 금지 호스트 — localhost 계열 + 비공인/기만 IP 리터럴."""
    host = host.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        # 표준 IP 표기는 아님 — 하지만 IP 흉내 숫자표기(십진/8진/16진)면 1단에서 거부.
        return _looks_like_ip_literal_host(host)
    return not _ip_is_global(host)


def url_host_resolves_public(url: str, *, getaddrinfo: Any = None) -> bool:
    """SSRF 2단 — 호스트가 해석되는 주소 **전부** 공인일 때만 True (fail-closed).

    사설이 하나라도 섞이면(DNS rebinding 류) False. 해석 실패·빈 결과·예외 전부 False.
    순수 테스트를 위해 resolver 주입식 — 기본은 socket.getaddrinfo(실 DNS).
    """
    resolve = getaddrinfo if getaddrinfo is not None else __import__("socket").getaddrinfo
    try:
        # V1-F1: 잘못 닫힌 IPv6 URL(예: 'https://[::1/x')은 .hostname 에서 ValueError 를
        # 던진다 — 예외가 새어나가지 않게 감싸 안전측 False 로 떨군다(fail-closed).
        host = urllib.parse.urlparse(url or "").hostname
    except ValueError:
        return False
    if not host:
        return False
    try:
        infos = resolve(host, None)
    except Exception:  # noqa: BLE001 — 어떤 해석 실패든 통과로 위장하지 않는다
        return False
    ips = {info[4][0] for info in infos if len(info) >= 5 and info[4]}
    return bool(ips) and all(_ip_is_global(str(ip)) for ip in ips)


# 이슈 D(V1 blocker 수용): LinkedIn Recruiter 좌석은 1개 — 로그인 머신 라우팅으로
# 머신이 갈라져도 skill=url 잡은 이 공유 키로 글로벌 락을 걸어 동시 2머신 실행을 막는다.
LINKEDIN_RPS_ACCOUNT_KEY = "portal:linkedin_rps"


def default_account_key(skill: str, machine: str) -> str:
    """계정 락 기본 정책 — LinkedIn 잡(url)은 좌석 공유 키, 그 외는 머신 바인딩 키."""
    if skill == "url":
        return LINKEDIN_RPS_ACCOUNT_KEY
    return f"portal:{machine}"


def _valid_owner_agent_params(params: dict[str, Any], position_url: str, role: str) -> bool:
    """Validate the exact owner-approved Discord message envelope."""
    if role != "owner" or set(params) != _OWNER_AGENT_PARAM_KEYS:
        return False
    request = params.get("request_text")
    if (not isinstance(request, str) or not request.strip()
            or len(request) > OWNER_AGENT_MAX_REQUEST_CHARS or "\x00" in request):
        return False
    agent = params.get("agent")
    mode = params.get("execution_mode")
    approval = params.get("approval_id")
    digest = params.get("prompt_sha256")
    approval_digest = params.get("approval_sha256")
    idempotency = params.get("idempotency_key")
    if agent not in FLEET_AGENTS or mode not in ("read_only", "workspace_write"):
        return False
    if not isinstance(approval, str) or not approval.startswith("discord:"):
        return False
    message_id = approval.removeprefix("discord:")
    if not _SNOWFLAKE_RE.fullmatch(message_id) or idempotency != approval:
        return False
    try:
        expected_digest = hashlib.sha256(request.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        return False
    if (not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest)
            or digest != expected_digest):
        return False
    expected_approval_digest = _approval_sha256(request, agent, mode, approval)
    if (not isinstance(approval_digest, str)
            or not _SHA256_RE.fullmatch(approval_digest)
            or approval_digest != expected_approval_digest):
        return False
    expected = re.fullmatch(
        r"https://discord\.com/channels/(?:@me|[0-9]{15,22})/"
        r"[0-9]{15,22}/([0-9]{15,22})", position_url,
    )
    return bool(expected and expected.group(1) == message_id)


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
    if not is_valid_machine_id(machine):
        return None
    if skill not in QUEUE_SKILLS:
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
    if skill == OWNER_AGENT_SKILL:
        if not _valid_owner_agent_params(params, position_url.strip(), role):
            return None
    # 이슈 A(2026-07-15): followup_skill 도 화이트리스트만 — 큐 입구에서 fail-closed
    if "followup_skill" in params and params["followup_skill"] not in FLEET_SKILLS:
        return None
    # 이슈 B(2026-07-15): 실행 엔진도 화이트리스트만 — claude|codex 외 거부
    if "agent" in params and params["agent"] not in FLEET_AGENTS:
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


def new_owner_agent_job_payload(
    *,
    machine: Any,
    guild_id: Any,
    channel_id: Any,
    message_id: Any,
    request_text: Any,
    agent: Any,
    requested_by: Any,
    verified_role: Any,
    execution_mode: Any = "workspace_write",
) -> dict[str, Any] | None:
    """Build one immutable queue job from one explicitly approved Discord message."""
    if verified_role != "owner":
        return None
    if guild_id != "@me" and (
            not isinstance(guild_id, str) or not _SNOWFLAKE_RE.fullmatch(guild_id)):
        return None
    if (not isinstance(channel_id, str) or not _SNOWFLAKE_RE.fullmatch(channel_id)
            or not isinstance(message_id, str) or not _SNOWFLAKE_RE.fullmatch(message_id)
            or not isinstance(request_text, str) or not isinstance(agent, str)
            or agent not in FLEET_AGENTS or not isinstance(execution_mode, str)
            or execution_mode not in ("read_only", "workspace_write")):
        return None
    try:
        prompt_sha256 = hashlib.sha256(request_text.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        return None
    approval_id = f"discord:{message_id}"
    params = {
        "request_text": request_text,
        "agent": agent,
        "approval_id": approval_id,
        "prompt_sha256": prompt_sha256,
        "approval_sha256": _approval_sha256(
            request_text, agent, execution_mode, approval_id),
        "idempotency_key": approval_id,
        "execution_mode": execution_mode,
    }
    return new_job_payload(
        machine=machine,
        skill=OWNER_AGENT_SKILL,
        position_url=f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}",
        requested_by=requested_by,
        role="owner",
        params=params,
    )


def is_valid_transition(old: Any, new: Any) -> bool:
    return new in ALLOWED_TRANSITIONS.get(old, ())


def claim_next_job_payload(machine: str) -> dict[str, str]:
    if not is_valid_machine_id(machine):
        raise ValueError(f"invalid machine id: {machine!r}")
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
    def __init__(self, url: str = "", key: str = "", *, getaddrinfo: Any = None) -> None:
        url, key = (url or "").strip(), (key or "").strip()  # V1 2R: 공백 자격증명 거부
        if url and key:
            self.url, self.key = url.rstrip("/"), key
        elif url or key:
            raise ValueError("url/key 는 둘 다 주거나 둘 다 생략(같은 출처 강제)")
        else:
            u, k = _env_config()
            self.url, self.key = u.rstrip("/"), k
        # 조각 G: enqueue 직전 SSRF 2단(DNS) 검사용 resolver — 테스트는 주입, 운영은 실 DNS.
        self._getaddrinfo = getaddrinfo

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
        # 조각 G(goal §5): 이름 기반 호스트도 POST 직전 DNS 해석으로 공인 여부를 강제.
        # 사설·loopback·메타데이터로 해석되면 HTTP 호출 없이 즉시 거부(fail-closed).
        if not url_host_resolves_public(
                revalidated["position_url"], getaddrinfo=self._getaddrinfo):
            raise ValueError(
                "position_url 호스트가 공인 주소로 해석되지 않음(사설/loopback/메타데이터 거부)")
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

    def linkedin_ready_machines(self) -> list:
        """이슈 D — heartbeat 의 LinkedIn 로그인 상태 조회(라우팅용, epoch 초)."""
        rows = self._call("POST", "/rpc/linkedin_ready_machines", {})
        return list(rows) if isinstance(rows, list) else []

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
