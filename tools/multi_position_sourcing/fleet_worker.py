"""함대 워커 — 자기 머신 큐를 폴링해 `claude -p` 로 스킬 잡을 실행 (2026-07-11).

설계 근거: docs/prompts/fleet-control-sequential-prompts-2026-07-11.md §프롬프트 B.
- VALUEHIRE_MACHINE 필수(fail-closed) — 머신 오배정은 계정↔머신 1:1 정책 위반.
- 실행 문구는 스킬 *발동 문구* 방식(.claude/skills) — /mnt 경로 하드코딩 금지.
- SOT28 발송 게이트: 프롬프트에 발송 금지를 명문화하고, 발송성 스킬은 아예 거부.
- PAUSED_FOR_HUMAN 은 exit code 보다 우선(캡차/2FA → 사람 개입 → /resume 재개, SOT 규칙 ②).
- 빈 stdout 은 성공으로 치지 않는다(빈 결과 불신).
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from .browser_evidence import complete_evidence_payload

from tools.codex_skill_sync.sync import (
    default_dest as default_skill_dest,
    default_sources as default_skill_sources,
    sync_skills,
)

from .fleet_heartbeat import read_linkedin_login_flag
from .job_queue import (
    FLEET_MACHINES,
    FLEET_SKILLS,
    FOLLOWUP_SKILLS,
    OWNER_AGENT_SKILL,
    JobQueueClient,
    _valid_url,
    default_account_key,
    is_valid_machine_id,
    new_job_payload,
    url_host_resolves_public,
)

REPO = Path(__file__).resolve().parents[2]

# ── AC-3 G4: 로그인 선행 게이트 (goal: discord-single-bot-console §7) ─────────
# 검색 스킬 잡은 로그인 영수증(portal_login.py 산출)이 유효할 때만 시작한다.
# 훅(H2 guards/discord-bot-login-gate.py)은 2층 — 1층 강제는 이 코드다(훅 fail-open 전제).
LOGIN_RECEIPT_RELPATH = "artifacts/portal_session_status_latest.json"
LOGIN_RECEIPT_MAX_AGE_SECONDS = 86400  # fleet_heartbeat.PORTAL_STATUS_MAX_AGE_SECONDS 와 동일 기준


def _read_login_receipt() -> Any:
    """영수증 JSON 읽기 — 없거나 깨지면 None(판정은 login_gate_block_reason 이 fail-closed).

    Codex V2 3R-1: 파일 쪽도 중복 키(뒤값 승리 모순) 거부 — 훅이 ValueError 를 던지면
    기존 계약대로 None(=차단)으로 떨어진다.
    """
    try:
        return json.loads((REPO / LOGIN_RECEIPT_RELPATH).read_text(encoding="utf-8"),
                          object_pairs_hook=_reject_duplicate_keys)
    except (OSError, ValueError):
        return None


def login_gate_required_channels(job: Mapping[str, Any]) -> tuple[str, ...]:
    """잡이 요구하는 포털 채널. 검색 스킬이 아니면 () — 게이트 미적용."""
    skill = job.get("skill")
    if skill == "url":
        return ("linkedin_rps",)
    if skill in ("humansearch", "aisearch"):
        raw = (job.get("params") or {}).get("channels") or ["saramin", "jobkorea"]
        mapped = []
        for ch in raw:
            name = str(ch).strip()
            normalized = "linkedin_rps" if name in ("linkedin", "linkedin_rps") else name
            if normalized in ("saramin", "jobkorea", "linkedin_rps"):
                mapped.append(normalized)
        return tuple(dict.fromkeys(m for m in mapped if m))
    return ()


def login_gate_block_reason(payload: Any, job: Mapping[str, Any],
                            now_epoch: int) -> str | None:
    """G4 순수 판정 — 차단이면 사유 문자열, 통과면 None. 모호하면 전부 차단(fail-closed).

    영수증 계약: portal_login.build_portal_session_preflight_payload —
    {generated_at(tz 필수), portal_sessions: [{channel, ready}, ...]}.
    """
    required = login_gate_required_channels(job)
    if not required:
        return None
    return _receipt_block_reason(payload, required, now_epoch)


def _receipt_block_reason(payload: Any, required: tuple[str, ...],
                          now_epoch: int,
                          min_generated_epoch: float | None = None) -> str | None:
    """영수증 payload 순수 판정(#188 에서 login 완료 교차검증과 공용으로 추출).

    min_generated_epoch(Codex V2 2R-2): 지정 시 그 시각 이전 영수증은 '이번 실행에서
    갱신 안 됨'으로 차단 — 24시간 내 옛 영수증으로 완료를 위장하는 각도 봉인.
    """
    if not isinstance(payload, Mapping):
        return "로그인 영수증 없음(artifacts/portal_session_status_latest.json)"
    from datetime import datetime
    raw_gen = payload.get("generated_at")
    if not isinstance(raw_gen, str) or not raw_gen.strip():
        return "로그인 영수증에 generated_at 없음"
    try:
        dt = datetime.fromisoformat(raw_gen.strip().replace("Z", "+00:00"))
    except ValueError:
        return "로그인 영수증 generated_at 형식 오류"
    if dt.tzinfo is None:
        return "로그인 영수증 generated_at 에 시간대 없음(신뢰 불가)"
    age = now_epoch - int(dt.timestamp())
    if age < 0 or age > LOGIN_RECEIPT_MAX_AGE_SECONDS:
        return f"로그인 영수증 만료/미래 시각(age={age}s)"
    # Codex V2 4R: 정수 절삭 비교는 같은 초 안의 '시작 직전' 영수증을 통과시킨다
    # — 소수점 시각 그대로 비교(fail-closed 방향).
    if min_generated_epoch is not None and dt.timestamp() < float(min_generated_epoch):
        return "로그인 영수증이 잡 시작 이전 것(이번 실행에서 미갱신)"
    sessions = payload.get("portal_sessions")
    if not isinstance(sessions, list):
        return "로그인 영수증에 portal_sessions 없음"
    by_channel = {}
    for entry in sessions:
        # Codex V2 3R-2: 비정상 항목을 조용히 건너뛰지 않는다 — 형식 오류 = 차단.
        if not isinstance(entry, Mapping):
            return "로그인 영수증 portal_sessions 항목 형식 오류"
        name = str(entry.get("channel") or "")
        # Codex V2 2R-3: 같은 채널 항목이 두 번이면 모순 가능(뒤값 승리) — 차단.
        if name in by_channel:
            return f"{name} 로그인 영수증 항목 중복(모순 가능)"
        by_channel[name] = entry
    for channel in required:
        entry = by_channel.get(channel)
        if not isinstance(entry, Mapping):
            return f"{channel} 로그인 영수증 항목 없음"
        if entry.get("ready") is not True:
            return f"{channel} 로그인 not-ready"
    return None


def _run_login_preflight(job: Mapping[str, Any]) -> bool:
    """검색 전에 정식 포털 로그인 준비 러너를 한 번 실행한다.

    저장 자격증명으로 복구 가능한 세션만 자동 복구한다. 캡차·2FA·checkpoint는
    ``--no-human-intervention`` 계약에 따라 즉시 not-ready 영수증으로 남고, 호출부가
    검색을 시작하지 않은 채 사람에게 넘긴다.
    """
    channels = login_gate_required_channels(job)
    if not channels:
        return True
    command = [
        sys.executable,
        "-m",
        "tools.multi_position_sourcing.portal_login",
        "--channels",
        ",".join(channels),
        "--worker-id",
        str(job.get("machine") or "default"),
        "--no-human-intervention",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=max(60, 240 * len(channels)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


CLAUDE_TIMEOUT_SECONDS = 2400  # 40분
POLL_SECONDS = 30
_SUMMARY_LIMIT = 800
_PAUSE_MARKER = "PAUSED_FOR_HUMAN:"
_SEARCH_RECEIPT_MARKER = "FLEET_SEARCH_RECEIPT:"
_HUMANSEARCH_RECEIPT_MARKER = "HUMANSEARCH_EVIDENCE_RECEIPT:"
_URL_RECEIPT_MARKER = "URL_EVIDENCE_RECEIPT:"
_LOGIN_RECEIPT_MARKER = "LOGIN_EVIDENCE_RECEIPT:"
_LOGIN_RECEIPT_CHANNELS = ("saramin", "jobkorea", "linkedin_rps")
_NETWORK_CONFIG_FLAG = "sandbox_workspace_write.network_access=true"

# 기본 보고 채널 = 사장님 DM 채널(scripts/discord_command_listener.py 와 동일)
DEFAULT_REPORT_CHANNEL = "1512503041448743092"
_NOTIFICATION_DEDUPE: dict[str, float] = {}

# SOT29 INV9(2026-07-20 사장님 지시로 개정; 원본 2026-07-15 #107): 사람 개입(캡차/2FA/
# 3사 포털 사용) 신호 후 60초(1분) 동안 조용하면 자동 재개한다. 영구 중단·10분 쿨다운은
# 이 원칙을 방해하는 코드라 삭제됨. owner_activity.DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS(60)와
# 같은 원칙(단일 출처).
OWNER_YIELD_RESUME_SECONDS = 60
PAUSE_COOLDOWN_SECONDS = OWNER_YIELD_RESUME_SECONDS  # 하위호환 별칭(단일 출처)
_RELEASE_RETRY_ATTEMPTS = 3
_RELEASE_RETRY_BACKOFF = (2, 10)


def sleep_seconds_after(status: str, poll_seconds: int) -> int:
    """loop 이 run_once 결과별로 쉬는 시간(순수) — 뮤테이션 방지용 단일 출처."""
    if status == "idle":
        return poll_seconds
    if status == "error":
        return min(poll_seconds, 15)
    if status == "paused_for_human":
        return PAUSE_COOLDOWN_SECONDS
    return 0


def machine_from_env(environ: Mapping[str, str]) -> str:
    """Require a strict dynamic machine ID; DB registration is checked by RPCs."""
    raw = environ.get("VALUEHIRE_MACHINE") or ""
    if not is_valid_machine_id(raw):
        raise RuntimeError(f"VALUEHIRE_MACHINE 이 유효하지 않습니다: {raw!r}")
    return raw


def _v4_repo(environ: Mapping[str, str] | None = None, repo_root: Path = REPO) -> Path:
    source = os.environ if environ is None else environ
    configured = str(source.get("VALUEHIRE_V4_REPO") or "").strip()
    return Path(configured) if configured else repo_root.parent / "valuehire_v4"


def sync_owner_agent_skills(
    *,
    repo_root: Path = REPO,
    v4_root: Path | None = None,
    dest: Path | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Mirror both repo generations immediately before an owner-agent execution."""
    repo_root = Path(repo_root)
    v4_root = Path(v4_root) if v4_root is not None else _v4_repo(repo_root=repo_root)
    if not repo_root.is_dir():
        raise RuntimeError(f"v5 repo missing: {repo_root}")
    if not v4_root.is_dir():
        raise RuntimeError(f"v4 repo missing: {v4_root}")
    def candidates(sources: list[Path]) -> set[str]:
        found: set[str] = set()
        for source in sources:
            if not source.is_dir():
                continue
            for child in source.iterdir():
                if (not child.name.startswith(".") and not child.is_symlink()
                        and (child / "SKILL.md").is_file()):
                    found.add(child.name)
        return found

    v5_sources = [repo_root / "skills", repo_root / ".claude/skills"]
    v4_sources = [v4_root / ".codex/skills", v4_root / ".claude/skills", v4_root / "tools"]
    v5_names, v4_names = candidates(v5_sources), candidates(v4_sources)
    if not v5_names:
        raise RuntimeError(f"v5 skill sources empty: {repo_root}")
    if not v4_names:
        raise RuntimeError(f"v4 skill sources empty: {v4_root}")
    target = Path(dest) if dest is not None else default_skill_dest()
    result = sync_skills(
        default_skill_sources(repo_root, v4_root=v4_root, home=home),
        target,
    )
    if not result.get("copied"):
        raise RuntimeError("v4/v5 skill sync produced no skills")
    represented = set(result["copied"])
    represented.update(item[0] for item in result["skipped"])
    represented.update(item[0] for item in result["collisions"])
    missing = (v5_names | v4_names) - represented
    if missing:
        raise RuntimeError(f"skill sync omitted names: {sorted(missing)}")
    broken = [name for name in result["copied"] if not (target / name / "SKILL.md").is_file()]
    if broken:
        raise RuntimeError(f"skill sync produced broken copies: {sorted(broken)}")
    return result


def build_owner_agent_prompt(job: Mapping[str, Any]) -> str:
    """Revalidate an immutable owner envelope and build the skill-selection prompt."""
    if job.get("skill") != OWNER_AGENT_SKILL:
        raise ValueError("owner agent 계약이 아닌 작업")
    job_id = job.get("id")
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise ValueError("owner agent 작업 번호 계약 위반")
    revalidated = new_job_payload(
        machine=job.get("machine"), skill=job.get("skill"),
        position_url=job.get("position_url"), requested_by=job.get("requested_by"),
        role=job.get("role"), params=job.get("params"),
        account_key=job.get("account_key", ""),
    )
    if revalidated is None:
        raise ValueError("owner agent 승인 계약 위반")
    if job.get("status") != "running":
        raise ValueError("owner agent 실행 상태 계약 위반")
    for field in ("machine", "skill", "position_url", "params", "requested_by", "role", "account_key"):
        if job.get(field) != revalidated[field]:
            raise ValueError(f"owner agent 승인 필드 정규화 금지: {field}")
    expected_lock = default_account_key(OWNER_AGENT_SKILL, revalidated["machine"])
    if revalidated["account_key"] != expected_lock:
        raise ValueError("owner agent 머신 잠금 키 계약 위반")
    params = revalidated["params"]
    approved_json = json.dumps(params["request_text"], ensure_ascii=False)
    v4_root = _v4_repo()
    skill_root = default_skill_dest()
    return (
        f"[Valuehire owner agent #{job_id}] 인증된 Discord 현재 메시지 1건을 실행합니다.\n"
        f"approval_id: {params['approval_id']}\n"
        f"prompt_sha256: {params['prompt_sha256']}\n"
        f"approval_sha256: {params['approval_sha256']}\n"
        f"approved_request_json: {approved_json}\n"
        "규칙:\n"
        "1. approved_request_json을 JSON 문자열로 해석한 정확한 원문만 요청 범위로 삼을 것.\n"
        "2. v5와 v4에서 동기화된 스킬 설명을 자연어로 매칭하고, 명시된 스킬은 해당 "
        "SKILL.md 전체를 읽고 따를 것.\n"
        f"3. 동기화 스킬 루트는 {skill_root}, 기본 작업 루트는 v5 {REPO}, "
        f"추가 스킬/도구 루트는 v4 {v4_root}다.\n"
        "4. 외부 등록·발송은 원문에 명시된 대상·채널·횟수를 절대 넓히지 말 것.\n"
        "5. 필요한 도구가 없어 부분동작이면 성공을 꾸미지 말고 막힌 이유를 보고할 것.\n"
        "6. danger-full-access나 권한 우회 옵션을 사용하지 말 것.\n"
        f"7. 캡차/2FA/본인확인을 만나면 '{_PAUSE_MARKER} <상황>'을 마지막 줄에 출력할 것.\n"
        "8. 최종 결과는 한국어로 stdout에 요약할 것.\n"
    )


def job_url_block_reason(job: Mapping[str, Any]) -> str | None:
    """실행 직전 URL 공인 DNS 재검증(#190 Codex V2 F3).

    파이썬 게이트웨이 클라이언트의 SSRF 검사는 anon 키로 RPC 를 *직접* 호출하면
    우회된다(DB 는 URL 형식만 검사). 소비 지점(워커)에서 한 번 더 공인 주소를
    강제해, 큐를 어떻게 넣었든 사설/loopback 대상 실행을 차단한다(fail-closed).
    URL 을 쓰는 스킬만 대상 — login('')·agent(디스코드 승인 링크)는 각자 계약이 있다.

    알려진 한계(정직 표기, Codex V2 2R): 검사-사용 사이 DNS 재바인딩(TTL 트릭)이나
    공개 호스트의 사설 주소 리다이렉트까지는 이 층에서 고정할 수 없다 — 실행기는
    브라우저를 사람처럼 조작하므로 소켓 수준 주소 고정이 성립하지 않는다. 이 검사는
    enqueue 시점 검사와 같은 기준을 소비 시점에 한 번 더 적용하는 방벽이다.
    """
    if job.get("skill") not in ("humansearch", "aisearch", "url", "jdintake"):
        return None
    url = job.get("position_url")
    if not url_host_resolves_public(url):
        return "position_url 호스트가 공인 주소로 해석되지 않음(사설/loopback/메타데이터 거부)"
    return None


def select_job_engine(job: Mapping[str, Any]) -> tuple[str, Callable[..., Any]]:
    """엔진 선택 SOT(#188) — login 은 항상 Codex(사장님 지시 2026-07-24),
    그 외 스킬은 params.agent 로 선택(codex 명시 시만 Codex, 기본 claude)."""
    if job.get("skill") == "login":
        return "codex", _run_codex
    if (job.get("params") or {}).get("agent") == "codex":
        return "codex", _run_codex
    return "claude", _run_claude


def build_job_prompt(job: Mapping[str, Any]) -> str:
    """잡 1건 → claude -p 실행 문구. 계약 위반 잡은 ValueError(fail-closed)."""
    skill = job.get("skill")
    if skill == OWNER_AGENT_SKILL:
        return build_owner_agent_prompt(job)
    if skill not in FLEET_SKILLS:
        raise ValueError(f"허용되지 않은 스킬: {skill!r}")
    job_id = job.get("id")
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise ValueError(f"invalid job id: {job_id!r}")
    url = job.get("position_url")
    if skill == "login":
        # login 은 무대상 스킬(#188, Codex V2 2R-1) — 빈 값만 허용(URL 있으면 거부).
        if not isinstance(url, str) or url.strip():
            raise ValueError(f"invalid position_url: {url!r}")
    elif not _valid_url(url):
        raise ValueError(f"invalid position_url: {url!r}")
    # V1+V2: 개행/제어문자/유니코드 줄구분자(U+2028/2029/0085) = 프롬프트 인젝션 → fail-closed
    # (splitlines 가 줄로 취급하는 모든 문자 — 일반 스페이스 외 공백류 전부 거부)
    requested_by = str(job.get("requested_by") or "").strip() or "(미상)"
    if any(ch != " " and (ch.isspace() or ord(ch) < 32) for ch in requested_by):
        raise ValueError("requested_by 에 제어문자/줄구분자 — 프롬프트 인젝션 차단")
    role = job.get("role")
    if role not in ("owner", "member"):
        raise ValueError(f"invalid role: {role!r}")
    params = job.get("params") or {}
    params_line = (
        f"- 추가 파라미터: {json.dumps(params, ensure_ascii=False)}\n" if params else "")
    if skill == "login":
        # SOT26 로그인 계약(#188) — 자동 로그인 항상, 사람 몫은 2FA·캡차·checkpoint 뿐.
        machine = str(job.get("machine") or "(미상)")
        return (
            f"[Valuehire 잡 #{job_id}] login 스킬을 발동해 3사(사람인·잡코리아·LinkedIn RPS) "
            f"포털 로그인 세션을 점검·복구해줘.\n"
            f"- 요청자: {requested_by} (Discord, 역할: {role})\n"
            f"{params_line}"
            f"- 결과: 한국어로 요약해 stdout 에 출력할 것 (워커가 Discord 로 전달함)\n"
            f"규칙:\n"
            f"1. 저장 자격증명으로 자동 로그인·재로그인을 항상 수행할 것(SOT26 INV1 — "
            f"로그인을 막는 대기·회피 금지).\n"
            f"2. 정식 준비 러너를 사용할 것: PYTHONPATH=. python3 -m "
            f"tools.multi_position_sourcing.portal_login --channels "
            f"saramin,jobkorea,linkedin_rps --worker-id {machine} — "
            f"즉석 raw 자동화로 우회하지 말 것.\n"
            f"3. 캡차/2FA/checkpoint 만 사람 몫 — 뜨면 그 브라우저 창을 앞으로 띄워 두고 "
            f"'{_PAUSE_MARKER} <상황>' 을 *마지막 줄*로 출력한 뒤 즉시 종료할 것"
            f"(자동 우회 금지).\n"
            f"4. 브라우저 보존: 창·탭·프로필 종료 0건 — 로그인된 크롬 프로필을 "
            f"로그아웃·삭제·초기화하지 말 것.\n"
            f"5. 비밀번호·쿠키·토큰을 출력하지 말 것.\n"
            f"6. 검색·수집·발송은 이 잡 범위 밖 — 시작하지 말 것.\n"
            f"7. 완료 후 영수증(artifacts/portal_session_status_latest.json) 갱신을 "
            f"확인하고, 마지막 줄에 {_LOGIN_RECEIPT_MARKER} 뒤로 "
            f'{{"channels": {{"saramin": {{"ready": true}}, "jobkorea": {{"ready": true}}, '
            f'"linkedin_rps": {{"ready": true}}}}, "output": "<영수증 경로>"}} 형식 JSON 을 '
            f"출력할 것. ready 가 아닌 채널이 있으면 이 마커 대신 규칙 3의 PAUSE 마커로 "
            f"종료할 것(거짓 ready 금지).\n"
        )
    url_login_rule = ""
    capture_rule = ""
    if skill == "url":
        assigned_machine = str(job.get("machine") or "(미상)")
        url_login_rule = (
            "20. LinkedIn RPS 실행 순서: 함대가 macmini/macbook/winpc 중 heartbeat의 "
            "linkedin_rps_logged_in=true인 머신을 먼저 찾아 이 잡에 배정한다. 현재 배정 머신은 "
            f"{assigned_machine}이다. 이 머신의 영속 크롬 프로필에서 브라우저를 직접 탐색하고, "
            "로그인된 브라우저와 RPS 세션을 실제 URL·DOM으로 검증할 것. 검증 전에는 검색을 "
            "시작하지 말 것. 단순 로그아웃이면 규칙 6을 포함해 이 잡 전체에서 최대 1회만 "
            "local secret store 자동 로그인을 시도할 것. 캡차·2FA·checkpoint가 뜨거나 로그인 "
            "세션을 찾지 못하면 다른 머신을 원격 조작하지 말 것. 운영자가 fleet-status의 "
            "linkedin_ready로 재배정할 수 있도록 다음 형식의 문장을 마지막 줄에 남기고 즉시 "
            f"종료할 것: '{_PAUSE_MARKER} portal=linkedin_rps machine={assigned_machine} "
            f"job={job_id} current_url=<현재 URL> action=linkedin_ready 확인 후 로그인 머신 재배정'.\n")
    if skill == "aisearch":
        capture_rule = (
            "19. 상세 화면을 연 뒤 다음 화면으로 이동하기 전에 exact target id로 정식 "
            "PYTHONPATH=. python3 -m tools.multi_position_sourcing.session_guard capture-evidence를 "
            "--task ai-search --mode profile로 실행할 것. 채널별 모든 "
            "저장 영수증을 profile_evidence에 넣고 후보 evidence와 동일 영수증으로 결합할 것.\n"
        )
    elif skill == "humansearch":
        capture_rule = (
            f"19. 정식 PYTHONPATH=. python3 -m tools.multi_position_sourcing.session_guard "
            f"capture-evidence --task humansearch --mode profile 저장을 "
            f"사용하고, 완료 마지막 줄에 {_HUMANSEARCH_RECEIPT_MARKER} 뒤 JSON으로 "
            "opened_profiles와 profile_evidence를 출력할 것.\n"
        )
    elif skill == "url":
        capture_rule = (
            f"19. 검색 결과 화면을 남긴 뒤 exact target id로 PYTHONPATH=. python3 -m "
            f"tools.multi_position_sourcing.session_guard capture-evidence --task url "
            f"--mode evidence를 실행하고, 완료 마지막 줄에 {_URL_RECEIPT_MARKER} 뒤로 그 "
            "saved JSON 영수증을 그대로 출력할 것.\n"
        )
    return (
        f"[Valuehire 잡 #{job_id}] {skill} 스킬을 발동해 아래 작업을 수행해줘.\n"
        f"- 포지션 URL: {url}\n"
        f"- 요청자: {requested_by} (Discord, 역할: {role})\n"
        f"{params_line}"
        f"- 결과: 한국어로 요약해 stdout 에 출력할 것 (워커가 Discord 로 전달함)\n"
        f"규칙:\n"
        f"1. {skill} 외의 서치·수집 스킬을 발동하지 말 것.\n"
        f"2. 아웃리치·메시지·메일 발송은 어떤 경우에도 하지 말 것 (발송 게이트 SOT28).\n"
        f"3. 로그인된 크롬 프로필을 로그아웃·삭제·초기화하지 말 것.\n"
        f"4. 캡차/2FA/본인확인을 만나면 조작을 멈추고 "
        f"'{_PAUSE_MARKER} <상황>' 을 *마지막 줄*로 출력하고 즉시 종료할 것.\n"
        f"5. params.search_urls가 있으면 그 URL들을 사람이 준비한 검색 결과로 사용하고 "
        f"포지션 URL과 혼동하지 말 것.\n"
        f"6. 보호 포털이 로그아웃 상태면 이 머신의 전용 프로필과 local secret store로 "
        f"정상 로그인을 시도하되, 비밀번호·쿠키·토큰을 출력하지 말 것.\n"
        f"7. aisearch는 ClickUp JD에서 국문·영문·띄어쓰기·약어 변형 검색어를 만들고, "
        f"사람인 OR/AND/NOT 및 잡코리아 키워드 칩·경력 필터를 UI에 직접 입력할 것.\n"
        f"8. 후보 목록은 1페이지에서 끝내지 말고 최소 10페이지 또는 마지막 페이지까지 "
        f"순회하며, 상세 프로필은 한 번에 하나씩 열고 다음 상세 클릭 전 매번 새로 뽑은 "
        f"180~420초(3~7분) 랜덤 지연을 둘 것.\n"
        f"9. 프리랜서/freelancer/freelance/개인사업자/독립계약자/contract worker/외주 또는 종료된 12개월 미만 "
        f"재직이 2회 이상인 후보는 점수 계산 전에 원천 제외할 것.\n"
        f"10. Windows에서는 Chrome Profile 2를 영속 세션으로 재사용하고 Chrome 종료, "
        f"로그아웃, 쿠키 삭제, 프로필 복사·초기화를 하지 말 것.\n"
        f"11. 열어본 모든 레쥬메는 점수·하드제외 여부와 무관하게 URL, 스크린샷, 본문을 "
        f"로컬 DB에 먼저 저장하고 저장 영수증을 확인한 뒤에만 다음 프로필로 이동할 것.\n"
        f"12. aisearch 완료 시 마지막 줄에 {_SEARCH_RECEIPT_MARKER} 뒤로 JSON을 출력할 것. "
        f"채널별 login_verified/query_verified/result_count_verified/pages_visited/"
        f"last_page_reached/opened_profiles/saved_receipts/candidates를 포함할 것.\n"
        f"13. 검색 URL을 사용자에게 요구하지 말고 사람인은 "
        f"https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search, 잡코리아는 "
        f"https://www.jobkorea.co.kr/Corp/Person/Find 로 직접 이동할 것.\n"
        f"14. 검색 직후 로그인 marker, 결과 count, 검색어/칩 반영을 DOM으로 재확인할 것. "
        f"0건이면 selector·입력·로그인을 재검증하고 AND를 완화한 검색 시나리오를 실행할 것.\n"
        f"15. 상세 저장은 URL 원본 검증→스크린샷→본문→로컬 DB commit→Supabase/archive "
        f"동기화 시도→영수증 확인→hard exclude→정식 humansearch.py/scoring.py 점수화 순서일 것.\n"
        f"16. 인증 화면은 visible browser에 그대로 두고 해당 채널만 멈출 것. 출력 marker에는 "
        f"portal, machine, job id, 현재 URL, 필요한 사람 조치만 쓰고 다른 채널은 계속할 것.\n"
        f"17. 후보 결과는 사람인/잡코리아를 구분하고 후보자명, 전체 profile_url, 채널, 점수, "
        f"why_fit, profile_summary, 주요 근거, hard exclude=false, 저장 완료=true를 포함할 것.\n"
        f"18. 후보 제안·InMail·이메일 Send/보내기는 절대 클릭하지 말 것.\n"
        + capture_rule
        + url_login_rule
    )


def validate_aisearch_receipt(stdout: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed when an aisearch claims completion without traversal/save evidence."""
    line = next((x for x in reversed((stdout or "").splitlines())
                 if x.startswith(_SEARCH_RECEIPT_MARKER)), "")
    if not line:
        raise ValueError("aisearch completion receipt missing")
    try:
        receipt = json.loads(line[len(_SEARCH_RECEIPT_MARKER):].strip())
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("aisearch completion receipt invalid JSON") from exc
    if not isinstance(receipt, dict) or not isinstance(receipt.get("channels"), dict):
        raise ValueError("aisearch completion receipt channels missing")
    requested = params.get("channels") or ["saramin", "jobkorea"]
    for channel in requested:
        evidence = receipt["channels"].get(channel)
        if not isinstance(evidence, dict):
            raise ValueError(f"{channel} completion evidence missing")
        for flag in ("login_verified", "query_verified", "result_count_verified"):
            if evidence.get(flag) is not True:
                raise ValueError(f"{channel} {flag} not verified")
        pages = evidence.get("pages_visited")
        if not isinstance(pages, int) or isinstance(pages, bool) or pages < 1:
            raise ValueError(f"{channel} pages_visited invalid")
        if pages < 10 and evidence.get("last_page_reached") is not True:
            raise ValueError(f"{channel} stopped before page 10 without last-page evidence")
        opened, saved = evidence.get("opened_profiles"), evidence.get("saved_receipts")
        if not isinstance(opened, int) or isinstance(opened, bool) or opened < 0 or saved != opened:
            raise ValueError(f"{channel} opened/saved count mismatch")
        profile_evidence = evidence.get("profile_evidence") or []
        if not isinstance(profile_evidence, list) or len(profile_evidence) != opened:
            raise ValueError(f"{channel} per-profile evidence count mismatch")
        expected_site = "linkedin_rps" if channel in {"linkedin", "linkedin_rps"} else channel
        position_id = receipt.get("position_id")
        seen_profiles: set[str] = set()
        for item in profile_evidence:
            if not complete_evidence_payload(item):
                raise ValueError(f"{channel} profile evidence incomplete")
            if (
                item.get("site") != expected_site
                or item.get("task") != "ai-search"
                or item.get("mode") != "profile"
                or not isinstance(position_id, str)
                or not position_id
                or item.get("position_id") != position_id
                or item.get("profile_url") in seen_profiles
            ):
                raise ValueError(f"{channel} profile evidence identity mismatch")
            seen_profiles.add(item["profile_url"])
        candidates = evidence.get("candidates") or []
        if not isinstance(candidates, list):
            raise ValueError(f"{channel} candidates invalid")
        required = {"candidate_name", "profile_url", "channel", "score", "why_fit",
                    "profile_summary", "evidence", "hard_excluded", "saved"}
        for candidate in candidates:
            if not isinstance(candidate, dict) or not required.issubset(candidate):
                raise ValueError(f"{channel} candidate output contract incomplete")
            if not _valid_url(candidate.get("profile_url")) or candidate.get("hard_excluded") is not False:
                raise ValueError(f"{channel} candidate URL/hard-exclude gate failed")
            if candidate.get("saved") is not True:
                raise ValueError(f"{channel} candidate save gate failed")
            candidate_evidence = candidate.get("evidence")
            if (
                candidate.get("channel") != channel
                or not complete_evidence_payload(candidate_evidence)
                or candidate_evidence.get("profile_url") != candidate.get("profile_url")
                or candidate_evidence.get("site") != expected_site
                or candidate_evidence.get("task") != "ai-search"
                or candidate_evidence.get("mode") != "profile"
                or candidate_evidence.get("manifest_path")
                not in {item.get("manifest_path") for item in profile_evidence}
            ):
                raise ValueError(f"{channel} candidate browser evidence incomplete")
    return receipt


def _marked_json(stdout: str, marker: str) -> dict[str, Any]:
    line = next(
        (line for line in reversed((stdout or "").splitlines()) if line.startswith(marker)),
        "",
    )
    if not line:
        raise ValueError(f"{marker.rstrip(':')} completion receipt missing")
    try:
        value = json.loads(line[len(marker):].strip())
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{marker.rstrip(':')} completion receipt invalid") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{marker.rstrip(':')} completion receipt invalid")
    return value


def validate_humansearch_receipt(stdout: str) -> dict[str, Any]:
    receipt = _marked_json(stdout, _HUMANSEARCH_RECEIPT_MARKER)
    opened = receipt.get("opened_profiles")
    items = receipt.get("profile_evidence")
    if (
        not isinstance(opened, int)
        or isinstance(opened, bool)
        or opened < 0
        or not isinstance(items, list)
        or len(items) != opened
    ):
        raise ValueError("humansearch per-profile evidence count mismatch")
    if any(
        not complete_evidence_payload(item)
        or item.get("task") != "humansearch"
        or item.get("mode") != "profile"
        for item in items
    ):
        raise ValueError("humansearch profile evidence incomplete")
    return receipt


def validate_url_receipt(stdout: str) -> dict[str, Any]:
    receipt = _marked_json(stdout, _URL_RECEIPT_MARKER)
    if (
        not complete_evidence_payload(receipt)
        or receipt.get("site") != "linkedin_rps"
        or receipt.get("task") != "url"
        or receipt.get("mode") != "evidence"
    ):
        raise ValueError("url browser evidence incomplete")
    return receipt


_UNSET = object()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """json object_pairs_hook — 중복 키(뒤값 승리 위조 각도) 거부(Codex V2 2R-3)."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def validate_login_receipt(stdout: str, *, started_epoch: float,
                           file_payload: Any = _UNSET,
                           now_epoch: int | None = None) -> dict[str, Any]:
    """login 잡 완료 증거(#188, R2) — 3사 채널별 ready=True 명시 없이는 done 금지.

    ready 아닌 채널이 있으면 엔진은 done 이 아니라 PAUSE 마커로 종료했어야 한다
    (캡차·2FA 는 사람 몫). 그러므로 '완료' 주장 + not-ready 조합은 계약 위반이다.

    Codex V2 반증 수용(위조 각도 봉인):
    - 마커는 *마지막 비공백 줄* 이어야 한다(중간 삽입 후 딴소리 금지).
    - 채널은 정확히 3사(초과·누락 모두 거부), ready 는 bool True 만.
    - output 은 고정 영수증 경로여야 한다.
    - stdout 주장만 믿지 않는다 — 실제 영수증 파일(LOGIN_RECEIPT_RELPATH)을
      교차 대조한다(신선도 + 3사 ready). 파일 주입 인자는 단위테스트용.
    """
    lines = [l.strip() for l in (stdout or "").splitlines() if l.strip()]
    if not lines or not lines[-1].startswith(_LOGIN_RECEIPT_MARKER):
        raise ValueError("login receipt must be the last non-empty line")
    try:
        receipt = json.loads(lines[-1][len(_LOGIN_RECEIPT_MARKER):].strip(),
                             object_pairs_hook=_reject_duplicate_keys)
    except (TypeError, ValueError) as exc:
        raise ValueError("login completion receipt invalid") from exc
    if not isinstance(receipt, dict):
        raise ValueError("login completion receipt invalid")
    channels = receipt.get("channels")
    if not isinstance(channels, dict) or set(channels) != set(_LOGIN_RECEIPT_CHANNELS):
        raise ValueError("login receipt channels must be exactly the three portals")
    for name in _LOGIN_RECEIPT_CHANNELS:
        entry = channels.get(name)
        if not isinstance(entry, dict) or entry.get("ready") is not True:
            raise ValueError(f"login receipt: {name} not ready")
    if receipt.get("output") != LOGIN_RECEIPT_RELPATH:
        raise ValueError("login receipt output path mismatch")
    if file_payload is _UNSET:
        file_payload = _read_login_receipt()
    if now_epoch is None:
        now_epoch = int(time.time())
    reason = _receipt_block_reason(file_payload, _LOGIN_RECEIPT_CHANNELS, now_epoch,
                                   min_generated_epoch=started_epoch)
    if reason is not None:
        raise ValueError(f"login receipt file cross-check failed: {reason}")
    # Codex V2 2R-3/3R-2: 파일 채널은 정확히 3사 각 1건 — 초과·중복·비정상 항목 전부
    # 위조/모순 신호(비정상 항목은 _receipt_block_reason 이 이미 차단, 여기선 개수 일치).
    names = sorted(str(e.get("channel") or "")
                   for e in file_payload.get("portal_sessions", []))
    if names != sorted(_LOGIN_RECEIPT_CHANNELS):
        raise ValueError("login receipt file channels must be exactly the three portals")
    return receipt


def parse_worker_output(stdout: str, exit_code: int, stderr: str = "") -> dict[str, str]:
    """claude 출력 → 상태 판정. PAUSED 마커 > exit code > 빈 출력 불신.

    QA-3(2026-07-13): 마커 탐지는 *stdout 에서만* 한다 — 비정상 종료 시 stderr
    (긴 트레이스백)가 뒤에 붙어 15줄 창에서 정당한 PAUSED 를 밀어내고 캡차를
    failed(종결·재개불가)로 오판하던 결함 봉인. stderr 는 실패 요약에만 쓴다.
    """
    text = (stdout or "").strip()
    # V1 2R: 실패 방향 설계 — 진짜 PAUSED 를 놓치는 것(캡차인데 자동 진행)이
    # 인용 오탐(불필요한 사람 호출)보다 훨씬 위험하다. 그래서:
    #  - 마지막 15개 비공백 줄 안에서 '줄 시작' 마커면 paused (후행 로그 허용)
    #  - 줄 중간 인용은 절대 매칭 안 됨, 출력 앞부분의 인용은 15줄 창 밖이라 무시
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in reversed(lines[-15:]):
        if line.startswith(_PAUSE_MARKER):
            reason = line[len(_PAUSE_MARKER):].strip() or "(사유 미기재)"
            return {"status": "paused_for_human", "reason": reason}
    err = (stderr or "").strip()
    combined = (text + ("\n" + err if err else "")).strip()
    if exit_code != 0:
        return {"status": "failed", "reason": f"exit={exit_code}",
                "summary": combined[-_SUMMARY_LIMIT:]}
    if not text:
        return {"status": "failed", "reason": "빈 출력 — 성공으로 치지 않음"}
    return {"status": "done", "summary": text[-_SUMMARY_LIMIT:]}


def _quote_for_cmd_exe(path: str) -> str:
    """Codex Rescue V2 발견 — 윈도우 실행 경로 자체에 '&' 같은 cmd.exe 메타문자가
    있으면(예: C:\\Tools&RnD\\claude.cmd — IT 배포 경로에 흔히 있을 수 있음) 큰따옴표
    없이 cmd.exe 로 넘어갈 때 명령이 끊긴다. 큰따옴표로 감싸 메타문자를 리터럴로
    고정한다(내부 큰따옴표는 이스케이프)."""
    return '"' + path.replace('"', '\\"') + '"'


def _agent_argv(name: str, base_args: list[str]) -> tuple[list[str], bool]:
    """이슈 F(2026-07-15) — 윈도우에서 npm shim(.cmd/.bat) 실행 시 [WinError 2] 방지.

    맥/리눅스는 execvp 가 PATH 를 뒤져 실행하므로 bare 이름이면 충분하지만, 윈도우의
    CreateProcess(shell=False 경로)는 배치파일을 직접 실행 못 한다 — cmd.exe 를 거쳐야
    한다. shutil.which 로 실제 경로를 찾아, 그 확장자가 .cmd/.bat 이면 shell=True 를
    요구한다고 표시한다. which 가 못 찾으면(예: PATH 미갱신) 기존처럼 bare 이름으로
    폴백 — 조용히 죽거나 무리하게 shell=True 를 강제하지 않는다(fail-soft).

    base_args 에는 프롬프트를 넣지 않는다 — cmd.exe 가 관여하는 경로(shell=True)에서
    프롬프트(포지션 URL·요청자 등 외부 유래 텍스트 포함)를 명령줄에 그대로 실으면
    '&'·'%VAR%' 같은 cmd.exe 메타문자/환경변수 확장에 노출된다(자기적대검증 발견 —
    URL 쿼리스트링의 흔한 '&' 만으로도 명령이 깨지거나, %로 환경변수가 새어나갈 수
    있음). 그래서 shell=True 경로는 프롬프트를 stdin 으로만 전달한다.
    """
    if sys.platform != "win32":
        return [name, *base_args], False
    resolved = shutil.which(name)
    exe = resolved or name
    needs_shell = bool(resolved) and exe.lower().endswith((".cmd", ".bat"))
    if needs_shell:
        exe = _quote_for_cmd_exe(exe)
    return [exe, *base_args], needs_shell


def _terminate_process_tree_windows(pid: int) -> None:
    """Codex Rescue V2 발견 — shell=True(cmd.exe) 경로에서 타임아웃 시 cmd.exe 프로세스만
    죽이면, cmd.exe 가 띄운 실제 에이전트 자식 프로세스는 고아로 남아 계속 돈다.
    taskkill /T 로 프로세스 트리 전체를 종료한다. 실패해도 무시(fail-soft — 타임아웃
    처리 자체가 이것 때문에 막히면 안 됨)."""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=10,
        )
    except Exception:  # noqa: BLE001 — 정리 실패가 타임아웃 처리를 막으면 안 됨
        pass


class JobCancelled(Exception):
    """실행 중 owner 가 잡을 취소해 서브프로세스를 종료했음을 알리는 신호(#196)."""


def cancel_observed(status: Any) -> bool:
    """폴링한 잡 상태가 '이 실행을 중단해야 하는가' 순수 판정(#196).

    - 'running': 계속(정상).
    - None(조회 실패/일시장애): 계속 — 오탐으로 정상 잡을 죽이지 않는다(fail-open은
      여기서 '중단 안 함'이 안전. 진짜 취소는 다음 폴에서 다시 잡힌다).
    - 그 외('cancelled'·'failed'·잡 소멸 등): 중단.
    """
    return status is not None and status != "running"


def _terminate_tree(proc: Any) -> None:
    """플랫폼 무관 프로세스트리 종료(#196 Codex V2 5R).

    Windows 는 taskkill /T(트리), POSIX 는 killpg(프로세스그룹) — 어느 쪽이든 자식
    (손자 브라우저 등)까지 고아 없이 정리한다. POSIX 경로는 호출자가 start_new_session
    으로 프로세스그룹을 만들어 둔 것을 전제한다."""
    if sys.platform == "win32":
        _terminate_process_tree_windows(proc.pid)
    else:
        _kill_process_group_posix(proc)


def _write_stdin_async(proc: Any, text: str) -> None:
    """서브프로세스 stdin 을 데몬 스레드로 쓴다(#196 Codex V2 4R).

    동기 write 는, 자식이 stdin 을 전혀 안 읽고 큰 prompt 가 파이프 버퍼(≈64KB)를
    넘기면 그 자리에서 막힌다 — poll 루프(취소·타임아웃)에 진입조차 못 한다. 별도
    스레드에 넘겨 poll 루프가 항상 돌게 하고, 취소로 프로세스를 죽이면 write 는
    BrokenPipe 로 풀려 스레드가 조용히 끝난다(데몬이라 잔존 안 함)."""
    import threading

    def _writer():
        try:
            if proc.stdin is not None:
                proc.stdin.write(text)
                proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass

    threading.Thread(target=_writer, daemon=True).start()


def _kill_process_group_posix(
    proc: "subprocess.Popen[Any]", *,
    grace_seconds: float = 3.0,
    poll_step: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """POSIX: 세션 리더로 띄운 서브프로세스의 프로세스그룹 전체를 종료.

    Codex/claude 가 띄운 손자 프로세스(브라우저 등)까지 고아 없이 정리한다.
    start_new_session 으로 띄웠으므로 pgid == 리더 pid — getpgid 가 아니라 proc.pid 를
    직접 pgid 로 쓴다(Codex V2 6R: 리더가 먼저 죽어 reap 되면 getpgid 가 실패해 살아있는
    자식을 못 잡던 결함 봉인).

    Codex V2 7R: SIGTERM 후 그룹이 빌 때까지 유예 안에서 폴링(killpg(pgid,0) 이
    ProcessLookupError 면 그룹 소멸)하고, 유예가 다 차도 남아있으면 SIGKILL 로 강제
    종료한다 — 얌전한 그룹은 즉시(폴 간격 내) 끝나 응답성 유지, SIGTERM 을 무시하는
    자식은 유예 뒤 반드시 죽는다. fail-soft(취소 처리를 막지 않는다)."""
    import signal

    pgid = proc.pid  # start_new_session → 리더 자신이 그룹 리더(pgid == pid)

    def group_alive() -> bool:
        try:
            os.killpg(pgid, 0)  # 시그널 0 = 존재 확인(그룹에 멤버가 하나라도 있으면 통과)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return True  # 권한 등 불확실 → 살아있다고 보고 SIGKILL 로 이어감(fail-closed)

    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass
    deadline = monotonic() + max(0.0, grace_seconds)
    while group_alive() and monotonic() < deadline:
        sleep(poll_step)
    if group_alive():
        try:
            os.killpg(pgid, signal.SIGKILL)  # SIGTERM 무시한 자식까지 강제 종료(idempotent)
        except (ProcessLookupError, OSError):
            pass
    try:
        proc.wait(timeout=2)  # 리더 reap(좀비 방지)
    except Exception:  # noqa: BLE001 — reap 실패해도 취소 자체는 성립.
        pass


def run_agent_with_cancel(
    *,
    popen_factory: Callable[[], Any],
    cancel_check: Callable[[], bool],
    kill_process_group: Callable[[Any], None] = _kill_process_group_posix,
    collect_output: Callable[[Any], tuple[str, str]] | None = None,
    timeout: int | None = None,
    poll_seconds: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[str, str, int]:
    """서브프로세스를 폴링하며 실행하다 취소 감지 시 프로세스그룹째 종료(#196).

    - 정상 종료: (stdout, stderr, returncode) 반환(기존 러너 계약과 동형).
    - cancel_check() True: 프로세스그룹 종료 후 JobCancelled 발생(재release 금지 신호).
    - timeout 초과: 프로세스그룹 종료 후 subprocess.TimeoutExpired 재전파(기존 계약).

    출력 수집은 collect_output seam 으로 분리한다 — 실 경로는 임시파일 리다이렉트로
    파이프 버퍼 교착 없이 poll() 만으로 감시하고, 종료 후 파일을 읽는다. 미지정 시
    proc.communicate() 기본값(페이크/단순 프로세스용).
    """
    proc = popen_factory()
    collect = collect_output or (lambda p: p.communicate())
    started = monotonic() if timeout is not None else None
    while True:
        code = proc.poll()
        if code is not None:
            stdout, stderr = collect(proc)
            return (stdout or ""), (stderr or ""), code
        if cancel_check():
            kill_process_group(proc)
            raise JobCancelled()
        if timeout is not None and started is not None \
                and (monotonic() - started) > timeout:
            kill_process_group(proc)
            raise subprocess.TimeoutExpired(cmd="agent", timeout=timeout)
        sleep(poll_seconds)


def _native_agent_run(
    cmd: list[str], *, cwd: str, env: Mapping[str, str] | None,
    input_text: str, timeout: int,
    cancel_check: Callable[[], bool],
    poll_seconds: float = 3.0,
) -> tuple[str, str, int]:
    """POSIX 네이티브(exec) 경로 실행 — 취소 감지 시 프로세스그룹째 종료(#196).

    파이프 교착 방지를 위해 stdout/stderr 를 임시파일로 리다이렉트한다(poll() 감시).
    프롬프트는 stdin 으로 넘긴다(codex `-`/claude `-p` 동일). start_new_session 으로
    프로세스그룹을 만들어 손자(브라우저 등)까지 killpg 로 정리한다."""
    import tempfile

    out_f = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    err_f = tempfile.TemporaryFile(mode="w+", encoding="utf-8")

    def factory():
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=dict(env) if env is not None else None,
            stdin=subprocess.PIPE, stdout=out_f, stderr=err_f,
            text=True, encoding="utf-8", start_new_session=True,
        )
        # 프롬프트를 stdin 으로 밀어넣는다 — stdout 은 파일이라 교착 없고, stdin write
        # 는 데몬 스레드라 자식이 stdin 을 안 읽어도 poll 루프가 막히지 않는다(4R).
        _write_stdin_async(proc, input_text)
        return proc

    def collect(_proc):
        out_f.seek(0); err_f.seek(0)
        return out_f.read(), err_f.read()

    try:
        return run_agent_with_cancel(
            popen_factory=factory, cancel_check=cancel_check,
            collect_output=collect, timeout=timeout, poll_seconds=poll_seconds,
        )
    finally:
        out_f.close(); err_f.close()


def _run_via_shell(cmd: list[str], prompt: str, timeout: int, cwd: str,
                    env: Mapping[str, str] | None,
                    cancel_check: Callable[[], bool] | None = None,
                    poll_seconds: float = 3.0) -> tuple[str, str, int]:
    """윈도우 .cmd/.bat shim(shell=True) 경로 전용 실행기.

    subprocess.run 이 아니라 Popen+communicate 를 직접 써서, 타임아웃 시 cmd.exe
    프로세스 트리 전체(taskkill /T)를 종료할 수 있게 한다(Codex Rescue V2 발견 —
    subprocess.run 의 기본 timeout 처리는 직계 자식인 cmd.exe 만 죽이고 그 자식은
    고아로 남긴다). encoding='utf-8' 을 명시해 비-UTF-8 Windows 로케일에서도 한글
    프롬프트/출력이 깨지지 않게 한다(Codex Rescue V2 발견).
    """
    if cancel_check is not None:
        # #196 Codex V2 3R: 취소 감시 경로는 stdout/stderr 를 임시파일로 리다이렉트한다.
        # PIPE 로 두면 큰 prompt 를 stdin 에 쓰는 동안 자식이 stdout 을 먼저 채워 양쪽
        # 파이프가 막히는 교착이 난다(polling 진입 전 멈춤) — 파일 리다이렉트로 원천 차단.
        # 취소·타임아웃 시 taskkill /T 로 cmd.exe 트리 전체를 종료한다.
        import tempfile

        # 5R: 트리 종료가 자식까지 잡도록 프로세스그룹을 만든다 — Windows 는
        # CREATE_NEW_PROCESS_GROUP, POSIX 는 start_new_session(setsid → killpg 대상).
        popen_kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True
        out_f = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        err_f = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                cmd, shell=True, cwd=cwd,
                env=dict(env) if env is not None else None,
                stdin=subprocess.PIPE, stdout=out_f, stderr=err_f,
                text=True, encoding="utf-8", **popen_kwargs,
            )
            _write_stdin_async(proc, prompt)  # 4R: 데몬 스레드(자식이 stdin 무시해도 무교착)
            started = time.monotonic()
            while True:
                if proc.poll() is not None:
                    out_f.seek(0); err_f.seek(0)
                    return out_f.read(), err_f.read(), proc.returncode
                if cancel_check():
                    _terminate_tree(proc)  # 5R: 플랫폼별(POSIX killpg / Win taskkill)
                    raise JobCancelled()
                if (time.monotonic() - started) > timeout:
                    _terminate_tree(proc)
                    raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)
                time.sleep(poll_seconds)
        finally:
            out_f.close(); err_f.close()
    proc = subprocess.Popen(
        cmd, shell=True, cwd=cwd, env=dict(env) if env is not None else None,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    try:
        stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_tree_windows(proc.pid)
        try:
            proc.communicate(timeout=5)
        except Exception:  # noqa: BLE001 — 정리 단계, 원 타임아웃 전파가 우선
            pass
        raise
    return (stdout or ""), (stderr or ""), proc.returncode


def _run_claude(prompt: str, timeout: int,
                env: Mapping[str, str] | None = None,
                cancel_check: Callable[[], bool] | None = None) -> tuple[str, str, int]:
    """claude -p 실행(레포 루트). 반환: (stdout, stderr, exit_code) — QA-3 로 분리.

    env=None 이면 부모 환경 상속(기존과 동일). 이슈 E: 워커가 배지 env 를 넘긴다.
    이슈 F: 윈도우 .cmd shim(shell=True) 경로에서는 프롬프트를 argv 가 아닌 stdin 으로
    넘겨 cmd.exe 메타문자/변수확장 노출을 원천 차단한다(맥/리눅스·네이티브 exe 경로는
    기존과 동일하게 argv 로 넘겨 행동 불변).
    """
    owner_agent = str((env or {}).get("VALUEHIRE_OWNER_AGENT_JOB") or "") == "1"
    base_args: list[str] = []
    if owner_agent:
        v4_root = _v4_repo(env)
        if not v4_root.is_dir():
            raise RuntimeError(f"v4 repo missing: {v4_root}")
        if sys.platform == "win32" and any(ch in str(v4_root) for ch in "&|<>^%!()"):
            raise ValueError("unsafe Windows v4 path")
        base_args.extend(["--add-dir", str(v4_root)])
        raw_mode = (env or {}).get("VALUEHIRE_AGENT_EXECUTION_MODE")
        permission_mode = {
            "read_only": "plan",
            "workspace_write": "acceptEdits",
        }.get(raw_mode)
        if permission_mode is None:
            raise ValueError(f"unsupported Claude execution mode: {raw_mode!r}")
        base_args.extend(["--permission-mode", permission_mode])
    base_args.append("-p")
    cmd, use_shell = _agent_argv("claude", base_args)
    if use_shell:
        return _run_via_shell(cmd, prompt, timeout, str(REPO), env,
                              cancel_check=cancel_check)
    if cancel_check is not None:
        # #196: owner_agent 는 stdin(-p), 일반은 argv 말미 prompt — 둘 다 stdin 으로
        # 통일해 취소 감지 경로를 태운다(claude 는 -p 와 stdin 모두 프롬프트를 받는다).
        run_cmd = cmd if owner_agent else [*cmd]
        return _native_agent_run(
            run_cmd, cwd=str(REPO), env=env, input_text=prompt, timeout=timeout,
            cancel_check=cancel_check)
    if owner_agent:
        proc = subprocess.run(
            cmd, cwd=str(REPO), input=prompt, capture_output=True, text=True,
            encoding="utf-8", timeout=timeout,
            env=dict(env) if env is not None else None,
        )
        return (proc.stdout or ""), (proc.stderr or ""), proc.returncode
    proc = subprocess.run(
        [*cmd, prompt], cwd=str(REPO), capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
        env=dict(env) if env is not None else None,
    )
    return (proc.stdout or ""), (proc.stderr or ""), proc.returncode


def build_codex_exec_args(environ: Mapping[str, str] | None = None) -> list[str]:
    """Build the only allowed noninteractive Codex command for fleet jobs."""
    source = os.environ if environ is None else environ
    mode = (
        str(source.get("VALUEHIRE_AGENT_EXECUTION_MODE"))
        if "VALUEHIRE_AGENT_EXECUTION_MODE" in source else "read_only"
    )
    # #194: login 잡은 쓰기 없이는 성립 불가(잠금 파일·영수증) — 모드와 무관하게
    # workspace-write + ~/.valuehire add-dir 를 강제한다(라이브 잡 #75 2회 재현 봉인).
    # Codex V2 F1(권한상승 위조 방어): 이 확장은 role=='owner' 일 때만 준다. 최소권한
    # 게이트웨이 RPC 는 anon 호출을 항상 role='member' 로 강제하므로(위조 불가), 공개
    # 키로 위조한 login 잡은 이 넓은 샌드박스를 얻지 못한다(member 는 read-only 유지 →
    # 쓰기 거부로 paused, fail-closed). 진짜 owner 인증 enqueue 경로는 후속 과제(B1).
    login_job = str(source.get("VALUEHIRE_JOB_SKILL") or "") == "login"
    owner_role = str(source.get("VALUEHIRE_JOB_ROLE") or "") == "owner"
    login_escalated = login_job and owner_role
    if login_escalated:
        mode = "workspace_write"
    sandbox = {"read_only": "read-only", "workspace_write": "workspace-write"}.get(mode)
    if sandbox is None:
        raise ValueError(f"unsupported Codex execution mode: {mode!r}")
    args = ["exec", "-C", str(REPO), "--sandbox", sandbox]
    if sandbox == "workspace-write":
        args.extend(["-c", _NETWORK_CONFIG_FLAG])
    if login_escalated:
        valuehire_home = Path.home() / ".valuehire"
        # Codex V2 F2: 윈도우 홈 경로의 cmd.exe 메타문자는 명령 분리·변수확장 위험 —
        # owner 저장소 경로(위)와 동일 차단 기준을 적용한다.
        if sys.platform == "win32" and any(ch in str(valuehire_home) for ch in "&|<>^%!()"):
            raise ValueError("unsafe Windows valuehire path")
        valuehire_home.mkdir(parents=True, exist_ok=True)
        args.extend(["--add-dir", str(valuehire_home)])
    if str(source.get("VALUEHIRE_OWNER_AGENT_JOB") or "") == "1":
        v4_root = _v4_repo(source)
        if not v4_root.is_dir():
            raise RuntimeError(f"v4 repo missing: {v4_root}")
        if sys.platform == "win32" and any(ch in str(v4_root) for ch in "&|<>^%!()"):
            raise ValueError("unsafe Windows v4 path")
        args.extend(["--add-dir", str(v4_root)])
    args.extend(["--ephemeral", "--ignore-user-config", "-"])
    if "danger-full-access" in args or "--dangerously-bypass-approvals-and-sandbox" in args:
        raise ValueError("unsafe Codex sandbox")
    return args


def _run_codex(prompt: str, timeout: int,
               env: Mapping[str, str] | None = None,
               cancel_check: Callable[[], bool] | None = None) -> tuple[str, str, int]:
    """codex exec 실행(레포 루트) — 이슈 B(2026-07-15). claude -p 와 동형 계약.

    이슈 F: 윈도우 .cmd shim 경로는 `codex exec -`(stdin 소스 명시) + input=prompt.
    """
    import ntpath
    codex_name = str((env or {}).get("VALUEHIRE_CODEX_BIN") or "codex").strip()
    basename = ntpath.basename(codex_name).lower()
    if basename not in ("codex", "codex.exe", "codex.cmd", "codex.bat"):
        raise ValueError(f"Codex 실행파일이 아닙니다: {codex_name!r}")
    cmd, use_shell = _agent_argv(codex_name, build_codex_exec_args(env))
    if use_shell:
        return _run_via_shell(cmd, prompt, timeout, str(REPO), env,
                              cancel_check=cancel_check)
    if cancel_check is not None:
        # #196: 실행 중 owner 취소를 감지·종료 가능한 경로.
        return _native_agent_run(
            cmd, cwd=str(REPO), env=env, input_text=prompt, timeout=timeout,
            cancel_check=cancel_check)
    proc = subprocess.run(
        cmd, cwd=str(REPO), input=prompt, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
        env=dict(env) if env is not None else None,
    )
    return (proc.stdout or ""), (proc.stderr or ""), proc.returncode


def _load_env_line(key: str) -> str:
    """os.environ 우선, 없으면 REPO 부터 홈까지 상위 순회(.env.local) — 워크트리 대응."""
    import os
    if (os.environ.get(key) or "").strip():
        return os.environ[key].strip()
    bases: list[Path] = []
    if os.environ.get("VALUEHIRE_REPO_DIR"):
        bases.append(Path(os.environ["VALUEHIRE_REPO_DIR"]))
    cur, home = REPO, Path.home()
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
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


AUTH_BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 900)  # SOT31(구 SOT30) S3 재시도 백오프


def wait_until_authenticated(
    probe: Callable[[], tuple[str, str]],
    *,
    notify: Callable[[str], None],
    sleep: Callable[[float], None],
    max_attempts: int | None = None,
) -> bool:
    """SOT31(구 SOT30) S3 — 기동 인증 게이트. 죽은 열쇠(401)로 조용히 폴링루프에 들어가지 않는다.

    probe() → (분류, 상세). "ok" 면 True. "credential_error" 는 첫 발견 시 1회만
    명시 경보(notify — 같은 원인 스팸 금지)하고 백오프 재시도(크래시루프 금지).
    probe 예외도 삼키지 않고 로그 후 재시도. max_attempts 소진 시 False.
    """
    attempts = 0
    credential_alerted = False
    while True:
        attempts += 1
        try:
            status, detail = probe()
        except Exception as exc:  # noqa: BLE001 — 프로브 예외 = 재시도성(네트워크 등)
            status, detail = "server_error", str(exc)[:200]
        if status == "ok":
            return True
        if status == "credential_error" and not credential_alerted:
            credential_alerted = True
            try:
                notify(
                    f"🚨 함대 워커 기동 실패 — Supabase 자격증명 오류: {detail}\n"
                    f".env.local 열쇠 교체 전까지 잡을 집어갈 수 없습니다"
                    f"(백오프 재시도 중).")
            except Exception as exc:  # noqa: BLE001 — 경보 실패가 게이트를 죽이면 안 됨
                print(f"[fleet] 인증경보 전송 실패(fail-soft): {exc}", file=sys.stderr)
        print(f"[fleet] 인증 프로브 {status}: {detail}", file=sys.stderr)
        if max_attempts is not None and attempts >= max_attempts:
            return False
        backoff = AUTH_BACKOFF_SECONDS[min(attempts - 1, len(AUTH_BACKOFF_SECONDS) - 1)]
        sleep(backoff)


def discord_notify(job: Mapping[str, Any], text: str) -> None:
    """Send each event once to the requester DM and OPS channel in parallel destinations."""
    import os
    import hashlib
    token = _load_env_line("DISCORD_BOT_TOKEN")
    channel = os.environ.get("FLEET_REPORT_CHANNEL", DEFAULT_REPORT_CHANNEL)
    ops_webhook = _load_env_line("DISCORD_WEBHOOK_URL_OPS_HEALTH")
    key = hashlib.sha256(f"{job.get('id','')}\0{text}".encode()).hexdigest()
    now = time.time()
    if now - _NOTIFICATION_DEDUPE.get(key, 0) < 3600:
        return
    _NOTIFICATION_DEDUPE[key] = now
    destinations: list[tuple[str, dict[str, str]]] = []
    if token:
        destinations.append((
            f"https://discord.com/api/v10/channels/{channel}/messages",
            {"Authorization": f"Bot {token}"},
        ))
    if ops_webhook:
        destinations.append((ops_webhook, {}))
    if not destinations:
        print(f"[fleet] Discord 보고 자격증명 없음 — 보고 생략: {text[:80]}", file=sys.stderr)
        return
    for url, extra_headers in destinations:
        try:
            req = urllib.request.Request(
                url, data=json.dumps({"content": text[:1900]}).encode(), method="POST",
                headers={**extra_headers, "Content-Type": "application/json",
                         "User-Agent": "ValuehireFleetWorker/1.0"},
            )
            urllib.request.urlopen(req, timeout=20)
        except Exception as exc:  # noqa: BLE001 — 보고는 fail-soft
            print(f"[fleet] Discord 병렬 보고 실패(fail-soft): {exc}", file=sys.stderr)


class FleetWorker:
    def __init__(
        self,
        machine: str,
        queue: Any | None = None,
        runner: Callable[[str, int], tuple[str, int]] | None = None,
        notifier: Callable[[Mapping[str, Any], str], None] | None = None,
        timeout: int = CLAUDE_TIMEOUT_SECONDS,
        clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], float] | None = None,
        owner_probe: Callable[[], bool] | None = None,
        yield_state_path: str | Path | None = None,
        skill_sync: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        if not is_valid_machine_id(machine):
            raise RuntimeError(f"invalid machine id: {machine!r}")
        self.machine = machine
        self.queue = queue if queue is not None else JobQueueClient()
        # 이슈 B: runner 주입 시 그 러너가 항상 우선(기존 테스트 하위호환).
        # V1 반증 수용: falsy 콜러블도 '주입'이다 — truthiness 아닌 None 판정.
        # 미주입일 때만 job.params.agent 로 claude|codex 선택.
        self.runner = _run_claude if runner is None else runner
        self._runner_injected = runner is not None
        self.notifier = notifier or discord_notify
        self.timeout = timeout
        # 이슈 #104: "방금" done 종결된 humansearch 그룹의 미소진 필터 변형 backlog.
        # 큐 idle 일 때 1건씩 자동 enqueue(심야 지속).
        # 이슈 #107(SOT29 INV9): paused_for_human 은 '1분 양보'다 — 폐기가 아니라
        # _backlog_resume_at 까지 정지 후 자동 재개(영구 중단 금지, 사장님 지시).
        self._variant_backlog: list[dict[str, Any]] = []
        self._clock: Callable[[], float] = clock if clock is not None else time.monotonic
        self._wall_clock: Callable[[], float] = (
            wall_clock if wall_clock is not None else time.time)
        # V1 2R F1: 1분 양보 창은 enqueue 만이 아니라 claim 도 막는 단일 게이트다.
        self._yield_until: float = 0.0
        # V1 2R F3: 사장님 활동 프로브(눈치) — 주입식. None 은 테스트 주입용뿐(프로덕션은 전 OS 게이트).
        # 프로덕션 배선은 main() 의 default_owner_probe() (macOS 포털 한정 + Windows idle, 전 OS 게이트).
        self.owner_probe: Callable[[], bool] | None = owner_probe
        self.skill_sync = sync_owner_agent_skills if skill_sync is None else skill_sync
        # V1 2R F2: launchd 재기동이 양보 창을 지우지 못하게 벽시계 기반 로컬 영속(fail-soft).
        self._yield_state_path = Path(yield_state_path) if yield_state_path is not None else None
        self._restore_yield_state()

    def _yield_remaining(self) -> float:
        return max(0.0, self._yield_until - self._clock())

    def _persist_yield_state(self) -> None:
        """남은 양보 시간과 미등록 변형을 같은 파일에 원자적으로 보존한다."""
        path = self._yield_state_path
        if path is None:
            return
        try:
            remaining = self._yield_remaining()
            if remaining <= 0 and not self._variant_backlog:
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps({
                "schema_version": 2,
                "machine": self.machine,
                "yield_until_epoch": self._wall_clock() + remaining,
                "variant_backlog": self._variant_backlog,
            }, allow_nan=False), encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:  # noqa: BLE001 — 영속 실패가 워커를 죽이면 안 됨
            print(f"[fleet] yield 상태 저장 실패(fail-soft): {exc}", file=sys.stderr)

    def _restore_yield_state(self) -> None:
        """재기동 시 deadline을 먼저, 검증된 변형 backlog를 다음으로 복원한다."""
        path = self._yield_state_path
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("상태 파일이 JSON object가 아님")
            epoch = data.get("yield_until_epoch")
            if isinstance(epoch, bool) or not isinstance(epoch, (int, float)) \
                    or not math.isfinite(epoch):
                raise ValueError("yield_until_epoch 값이 올바르지 않음")
            remaining = min(
                OWNER_YIELD_RESUME_SECONDS,
                max(0.0, float(epoch) - self._wall_clock()),
            )
            if remaining > 0:
                self._yield_until = max(
                    self._yield_until, self._clock() + remaining)

            # #114의 v1은 deadline 하나만 썼다. schema가 없는 파일에서 backlog를
            # 복원하면 임의 형식을 작업 큐로 승격하므로 deadline만 호환한다.
            schema_version = data.get("schema_version")
            if schema_version is None:
                if "variant_backlog" in data:
                    raise ValueError("legacy 상태에 variant_backlog가 포함됨")
                return
            if isinstance(schema_version, bool) or not isinstance(schema_version, int) \
                    or schema_version != 2 or data.get("machine") != self.machine:
                raise ValueError("상태 schema 또는 machine 불일치")

            raw_backlog = data.get("variant_backlog", [])
            from .session_batch import MAX_PENDING_VARIANTS, variant_job_payload
            if not isinstance(raw_backlog, list) or len(raw_backlog) > MAX_PENDING_VARIANTS:
                raise ValueError("variant_backlog 형식 또는 개수 제한 위반")
            restored: list[dict[str, Any]] = []
            for item in raw_backlog:
                if not isinstance(item, dict) or item.get("skill") != "humansearch" \
                        or item.get("status") != "queued" \
                        or item.get("machine") != self.machine:
                    raise ValueError("variant_backlog 작업 계약 위반")
                params = item.get("params")
                variant = params.get("variant") if isinstance(params, dict) else None
                group_id = params.get("group_id") if isinstance(params, dict) else None
                channel = variant.get("channel") if isinstance(variant, dict) else None
                if channel not in ("saramin", "jobkorea") \
                        or not isinstance(group_id, str) or not group_id:
                    raise ValueError("variant_backlog 변형 파라미터 위반")
                regenerated = variant_job_payload(
                    item, variant, group_id=group_id)
                if regenerated is None or regenerated != item:
                    raise ValueError("variant_backlog 작업 검증 실패")
                restored.append(regenerated)
            self._variant_backlog = restored
        except Exception as exc:  # noqa: BLE001
            print(f"[fleet] yield 상태 복원 실패(fail-soft): {exc}", file=sys.stderr)

    def _start_yield(self) -> None:
        self._yield_until = self._clock() + OWNER_YIELD_RESUME_SECONDS
        self._persist_yield_state()

    def _notify(self, job: Mapping[str, Any], text: str) -> None:
        try:
            self.notifier(job, text)
        except Exception as exc:  # noqa: BLE001
            print(f"[fleet] notify 실패(fail-soft): {exc}", file=sys.stderr)

    def _cancel_check_for(self, job_id: int) -> Callable[[], bool] | None:
        """#196: 실행 중 러너가 부를 취소 판정 — 자기 잡 상태를 폴링해 cancelled 감지.

        큐가 job_status 를 지원하지 않으면 None 을 돌려준다 — 러너는 그때 기존
        subprocess.run 경로(취소 감시 없음)를 그대로 쓴다. 이렇게 해야 subprocess.run
        을 목킹하는 기존 워커 테스트가 Popen 경로로 새지 않는다(하위호환).
        조회가 실패하면 cancel_observed(None)=False → '계속'(오탐으로 정상 잡 안 죽임)."""
        status_of = getattr(self.queue, "job_status", None)
        if not callable(status_of):
            return None

        def check() -> bool:
            try:
                return cancel_observed(status_of(job_id))
            except Exception:  # noqa: BLE001 — 조회 실패는 '계속'(오탐 금지)
                return False

        return check

    def _busy_badge_env(self, job: Mapping[str, Any], agent_label: str) -> dict[str, str]:
        """이슈 E: 브라우저 '자동화 사용중' 배지용 env — os.environ 상속 + 배지 2키."""
        import os
        env = dict(os.environ)
        env["VH_BUSY_TASK"] = f"fleet #{job.get('id')} ({job.get('skill')})"
        env["VH_BUSY_AGENT"] = agent_label
        # #194: Codex 인자 빌더가 잡 스킬·역할을 알 수 있게 전달 — login 샌드박스 확장은
        # skill=login && role=owner 일 때만(Codex V2 F1 위조 방어).
        env["VALUEHIRE_JOB_SKILL"] = str(job.get("skill") or "")
        env["VALUEHIRE_JOB_ROLE"] = str(job.get("role") or "")
        if job.get("skill") == OWNER_AGENT_SKILL:
            params = job.get("params") or {}
            env["VALUEHIRE_OWNER_AGENT_JOB"] = "1"
            env["VALUEHIRE_AGENT_EXECUTION_MODE"] = str(params.get("execution_mode") or "")
            env["VALUEHIRE_V4_REPO"] = str(_v4_repo(env))
        return env

    def _release(self, job: Mapping[str, Any], job_id: int, status: str, *,
                 result_summary: str = "", error: str = "") -> Any:
        """QA-4 — release 를 재시도로 감싼다. 일시 장애가 잡을 running 고아로 못 만들게.

        최종 실패는 조용히 넘어가지 않는다: 고아 위험 경보 후 예외 재전파(loop 이
        error 백오프로 흡수). ValueError(계약 위반)는 재시도 무의미 — 즉시 전파.
        """
        last_exc: Exception | None = None
        for attempt in range(_RELEASE_RETRY_ATTEMPTS):
            try:
                return self.queue.release(
                    job_id, status, result_summary=result_summary, error=error)
            except ValueError:
                raise
            except Exception as exc:  # noqa: BLE001 — 네트워크/HTTP 일시 장애
                # #196 Codex V2 2R F3: release 는 where status='running' 이라, 그 사이
                # owner 가 취소해 잡이 이미 'cancelled'(또는 다른 terminal)면 RPC 가
                # 'running 없음'으로 실패한다. 이건 고아가 아니라 '취소가 이겼다' —
                # 상태를 재확인해 running 이 아니면 재시도·고아경보 없이 조용히 종료한다.
                status_of = getattr(self.queue, "job_status", None)
                if callable(status_of):
                    try:
                        current = status_of(job_id)
                    except Exception:  # noqa: BLE001 — 확인 실패 시 기존 재시도 경로로
                        current = "running"
                    if current is not None and current != "running":
                        return None
                last_exc = exc
                if attempt < _RELEASE_RETRY_ATTEMPTS - 1:
                    backoff = _RELEASE_RETRY_BACKOFF[
                        min(attempt, len(_RELEASE_RETRY_BACKOFF) - 1)]
                    print(f"[fleet] release 재시도 {attempt + 1}: {exc}", file=sys.stderr)
                    time.sleep(backoff)
        self._notify(job, (
            f"🚨 잡 #{job_id} 상태보고(release {status}) 최종 실패 — running 고아 위험. "
            f"수동 확인 필요: {last_exc}"))
        assert last_exc is not None
        raise last_exc

    def run_once(self, dry_run: bool = False) -> str:
        """큐에서 잡 1건 처리. 반환: idle|done|paused_for_human|failed."""
        # V1 2R F1(INV9): 마지막 사람 개입 신호 후 1분 창 안에서는 claim 도 하지 않는다
        # — release 예외(15초 백오프)·--once 경로로 창이 우회되는 구멍 봉인.
        if self._yield_remaining() > 0:
            return "idle"
        # V1 2R F3(INV9 '눈치'): 사장님 활동이 감지되는 동안은 claim/enqueue 모두 양보.
        # 프로브 실패 = fail-closed 양보(사장님을 앞지르지 않는다, owner_activity 와 동일 정책).
        if self.owner_probe is not None:
            try:
                owner_active = bool(self.owner_probe())
            except Exception:  # noqa: BLE001
                owner_active = True
            if owner_active:
                return "idle"
        job = self.queue.claim_next(self.machine)
        if not job:
            # 이슈 #104: 큐가 비었으면 방금 그룹의 미소진 변형을 1건만 enqueue —
            # 회당 1건 자연 스로틀. 실행 자체는 다음 턴의 claim 경로(쿨다운·양보 포함)를 탄다.
            self._enqueue_idle_variant()
            return "idle"
        job_id = job["id"]
        if job.get("skill") == OWNER_AGENT_SKILL and job.get("machine") != self.machine:
            error = f"owner agent 배정 머신 불일치: {job.get('machine')} != {self.machine}"
            self._release(job, job_id, "failed", error=error)
            self._notify(job, f"❌ 잡 #{job_id} 실패 — {error}")
            return "failed"
        try:
            prompt = build_job_prompt(job)
        except ValueError as exc:
            self._release(job, job_id, "failed", error=f"계약 위반 잡: {exc}")
            self._notify(job, f"❌ 잡 #{job_id} 실패 — 계약 위반: {exc}")
            return "failed"
        if dry_run:
            self._release(job, job_id, "done", result_summary="dry-run — 실행기 미실행")
            self._notify(job, f"🧪 잡 #{job_id} dry-run 완료 (실행기 미실행)")
            return "done"
        # #190 Codex V2 F3: DB 직접 enqueue 우회 방어 — 실행 직전 URL 공인 재검증.
        # 주입 러너(테스트/시뮬레이션)는 네트워크 DNS 를 만지지 않도록 기존 계약 유지.
        if not self._runner_injected:
            url_reason = job_url_block_reason(job)
            if url_reason is not None:
                self._release(job, job_id, "failed", error=url_reason)
                self._notify(job, f"❌ 잡 #{job_id} 실패 — {url_reason}")
                return "failed"
        # AC-3 G4(1층): 검색 스킬은 로그인 영수증이 유효할 때만 실행. 기본 러너 경로 한정
        # — 주입 러너(테스트/시뮬레이션)는 브라우저를 안 여니 기존 계약 유지.
        if not self._runner_injected and job.get("skill") in FLEET_SKILLS:
            reason = login_gate_block_reason(_read_login_receipt(), job, int(time.time()))
            if reason is not None:
                self._notify(job, (
                    f"🔐 잡 #{job_id} 로그인 준비를 먼저 확인합니다 — "
                    f"skill={job.get('skill')}"))
                _run_login_preflight(job)
                reason = login_gate_block_reason(
                    _read_login_receipt(), job, int(time.time()))
            if reason is not None:
                self._release(job, job_id, "paused_for_human",
                              error=f"로그인 선행 게이트: {reason}")
                self._notify(job, (
                    f"⏸️ 잡 #{job_id} 대기(paused_for_human) — {reason}\n"
                    f"사장님, /login 으로 포털 로그인을 먼저 완료해 주세요. "
                    f"영수증 갱신 후 fleet-resume 로 재개됩니다."))
                return "paused_for_human"
        if job.get("skill") == OWNER_AGENT_SKILL:
            try:
                self.skill_sync()
            except Exception as exc:  # noqa: BLE001 — 동기화 실패 시 모델 실행 금지
                error = f"스킬 동기화 실패: {exc}"
                self._release(job, job_id, "failed", error=error)
                self._notify(job, f"❌ 잡 #{job_id} 실패 — {error}")
                return "failed"
        # 이슈 C(2026-07-15 goal §3): claim~완료 사이 공백 메움 — 실행 직전 1회, fail-soft(_notify)
        self._notify(job, (
            f"▶️ 잡 #{job_id} 실행 시작 ({self.machine}, skill={job.get('skill')}) — "
            f"position: {job.get('position_url')}"))
        runner = self.runner
        agent_label = "claude"
        if not self._runner_injected:
            # 이슈 B + #188 — 주입 러너(테스트/시뮬레이션)는 그대로, 실 경로만 SOT 선택.
            agent_label, runner = select_job_engine(job)
        # #188 Codex V2 2R-2/4R: login 완료 영수증은 이 시각 이후 갱신본만 인정
        # (정수 절삭 없이 소수점 시각 그대로 — 같은 초 경계 우회 봉인).
        started_epoch = time.time()
        try:
            if self._runner_injected:
                raw = runner(prompt, self.timeout)
            else:
                # 이슈 E(사장님 라벨 승인): raw_cdp 배지가 실제 작업명을 보여주도록
                # 서브프로세스 env 에 VH_BUSY_TASK/VH_BUSY_AGENT 주입(프로세스 스코프 —
                # 잡 종료와 함께 소멸, 다음 잡 잔존 없음). 주입 러너 계약(2인자)은 불변.
                # #196: 실행 중 owner 취소를 감지하는 cancel_check 를 넘긴다 — 러너가
                # 서브프로세스를 프로세스그룹째 죽이고 JobCancelled 를 던진다.
                raw = runner(prompt, self.timeout,
                             env=self._busy_badge_env(job, agent_label),
                             cancel_check=self._cancel_check_for(job_id))
        except JobCancelled:
            # DB 는 이미 cancelled(owner 취소) — finish_job(where status='running')은
            # no-op 이 되므로 재release 하지 않는다(경합 안전, 취소가 이긴다).
            self._notify(job, f"🛑 잡 #{job_id} 실행 중지됨 (owner 취소, {self.machine}).")
            return "cancelled"
        except subprocess.TimeoutExpired:
            # V1 반증 수용: 선택된 엔진 이름으로 표기(codex 잡을 claude 로 오표기 금지)
            self._release(job, job_id, "failed", error=f"{agent_label} 타임아웃({self.timeout}s)")
            self._notify(job, f"⏱️ 잡 #{job_id} 실패 — {self.timeout}초 타임아웃")
            return "failed"
        except Exception as exc:  # noqa: BLE001 — V1: 어떤 예외든 잡을 running 고아로 두지 않는다
            self._release(job, job_id, "failed", error=f"runner 예외: {exc}")
            self._notify(job, f"❌ 잡 #{job_id} 실패 — 실행 예외: {exc}")
            return "failed"
        # QA-3: 신형 러너는 (stdout, stderr, code), 기존 러너/테스트는 (stdout, code)
        # QA-7(자기 적대검증): 계약 밖 반환형이 예외로 새면 잡이 running 고아가 된다
        # — 어떤 형태든 release(failed) 로 종결(fail-closed).
        try:
            if len(raw) == 3:
                stdout, stderr, code = raw
            else:
                stdout, code = raw
                stderr = ""
        except (TypeError, ValueError) as exc:
            self._release(job, job_id, "failed", error=f"러너 반환형 계약 위반: {exc}")
            self._notify(job, f"❌ 잡 #{job_id} 실패 — 러너 반환형 계약 위반: {exc}")
            return "failed"
        # #196 Codex V2 F4: 완료-취소 경합 — 서브프로세스가 취소 폴 직전에 정상 종료했는데
        # 그 사이 owner 가 취소해 DB 가 이미 'cancelled' 라면, done/failed 로 보고하지
        # 않는다. release(done)은 where status='running' 이라 no-op → 3회 재시도 후
        # 거짓 '고아' 경보가 뜨고 완료 알림·후속잡까지 새는 걸 막는다. cancelled 로 종결.
        cancel_check = self._cancel_check_for(job_id)
        if cancel_check is not None and cancel_check():
            self._notify(job, f"🛑 잡 #{job_id} 실행 중지됨 (owner 취소, {self.machine}).")
            return "cancelled"
        result = parse_worker_output(stdout, code, stderr=stderr)
        if result["status"] == "paused_for_human":
            # 이슈 #107(SOT29 INV9, 사장님 지시): 사람 개입 신호 = '1분 양보' —
            # backlog 를 폐기하지 않고, 마지막 이상 신호로부터 60초 동안만 자동
            # enqueue 를 정지한다. 1분 뒤 이상이 없으면 자동 재개(영구 중단 금지).
            # pause 가 반복되면 그 시점부터 창이 다시 1분으로 연장된다.
            self._start_yield()
            self._release(job, job_id, "paused_for_human", error=result["reason"])
            self._notify(job, (
                f"⏸️ 잡 #{job_id} 사람 개입 필요 ({self.machine}): {result['reason']}\n"
                f"처리 후 /resume 으로 재개해 주세요."))
            return "paused_for_human"
        if result["status"] == "failed":
            self._release(job, job_id, "failed",
                          error=result.get("reason", ""),
                          result_summary=result.get("summary", ""))
            self._notify(job, f"❌ 잡 #{job_id} 실패 ({self.machine}): {result.get('reason','')}")
            return "failed"
        if job.get("skill") == "aisearch":
            try:
                validate_aisearch_receipt(stdout, job.get("params") or {})
            except ValueError as exc:
                self._release(job, job_id, "failed", error=f"완료 영수증 계약 위반: {exc}")
                self._notify(job, f"❌ 잡 #{job_id} 실패 — 완료 영수증 계약 위반: {exc}")
                return "failed"
        elif job.get("skill") == "humansearch":
            try:
                validate_humansearch_receipt(stdout)
            except ValueError as exc:
                self._release(job, job_id, "failed", error=f"완료 영수증 계약 위반: {exc}")
                self._notify(job, f"❌ 잡 #{job_id} 실패 — 완료 영수증 계약 위반: {exc}")
                return "failed"
        elif job.get("skill") == "url":
            try:
                validate_url_receipt(stdout)
            except ValueError as exc:
                self._release(job, job_id, "failed", error=f"완료 영수증 계약 위반: {exc}")
                self._notify(job, f"❌ 잡 #{job_id} 실패 — 완료 영수증 계약 위반: {exc}")
                return "failed"
        elif job.get("skill") == "login":
            try:
                validate_login_receipt(stdout, started_epoch=started_epoch)
            except ValueError as exc:
                self._release(job, job_id, "failed", error=f"완료 영수증 계약 위반: {exc}")
                self._notify(job, f"❌ 잡 #{job_id} 실패 — 완료 영수증 계약 위반: {exc}")
                return "failed"
        self._release(job, job_id, "done", result_summary=result["summary"])
        self._notify(job, f"✅ 잡 #{job_id} 완료 ({self.machine}):\n{result['summary'][:1500]}")
        self._enqueue_followup(job)
        self._remember_group_variants(job)
        return "done"

    def _remember_group_variants(self, job: Mapping[str, Any]) -> None:
        """이슈 #104: done 종결된 humansearch 잡의 group_session 변형을 backlog 로 기억.

        "방금 그룹"만 유지 — 새 그룹 잡이 done 되면 이전 backlog 를 통째로 교체한다.
        변형 잡 자체(params.variant, group_session 없음)는 backlog 를 만들지 않는다
        (1단계 체인 — _enqueue_followup 과 동일한 무한 체인 방지 원칙).
        """
        if job.get("skill") != "humansearch":
            return
        gs = (job.get("params") or {}).get("group_session")
        if not isinstance(gs, Mapping):
            return
        group_id = str(gs.get("group_id") or "")
        variants = gs.get("pending_variants")
        if not group_id or not isinstance(variants, list):
            return
        from .session_batch import MAX_PENDING_VARIANTS, variant_job_payload
        payloads = []
        for variant in variants:
            # V1(Codex) 수용: 캡은 생성측만 믿지 않는다 — 큐를 우회해 변형이 6건 초과로
            # 들어와도 소비측(워커)에서 다시 캡(심야 폭주 enqueue 차단, 이중 방벽).
            if len(payloads) >= MAX_PENDING_VARIANTS:
                break
            if isinstance(variant, Mapping):
                payload = variant_job_payload(job, variant, group_id=group_id)
                if payload is not None:
                    payloads.append(payload)
        self._variant_backlog = payloads
        self._persist_yield_state()

    def _enqueue_idle_variant(self) -> None:
        """이슈 #104: idle 1회당 변형 1건 enqueue(심야 지속). 실패한 변형은 폐기(fail-soft).

        pop 을 enqueue 보다 먼저 해 같은 변형의 무한 재시도(봇질)를 차단한다. 잡의
        idempotency_key 파생 덕에 중복 재발사도 큐 계층에서 dedup 된다.
        """
        if not self._variant_backlog:
            return
        # 이슈 #107(SOT29 INV9, 2026-07-20 60초 개정): 마지막 사람 개입 신호 후 1분 전엔 양보(no-op).
        # 창이 지나면 아래 enqueue 로 자동 재개 — 별도 사람 조치 불필요.
        if self._yield_remaining() > 0:
            return
        payload = self._variant_backlog.pop(0)
        # pop-before-enqueue 규칙을 상태 파일에도 즉시 반영한다. enqueue 뒤 급사로 생기는
        # 중복 가능성은 payload의 idempotency_key가 큐 계층에서 차단한다.
        self._persist_yield_state()
        variant = (payload.get("params") or {}).get("variant") or {}
        try:
            nxt = self.queue.enqueue(payload)
            nxt_id = (nxt or {}).get("id", "?") if isinstance(nxt, Mapping) else "?"
            self._notify(payload, (
                f"🌙 큐 idle — 그룹 변형 자동 enqueue (잡 #{nxt_id}) "
                f"channel={variant.get('channel')} keyword={variant.get('keyword')} "
                f"(남은 변형 {len(self._variant_backlog)}건)"))
        except Exception as exc:  # noqa: BLE001 — 변형 enqueue 실패가 워커를 죽이면 안 됨
            self._notify(payload, f"⚠️ 그룹 변형 자동 enqueue 실패(해당 변형 폐기): {exc}")

    def _enqueue_followup(self, job: Mapping[str, Any]) -> None:
        """이슈 A(2026-07-15 goal §1): done 종결 잡의 params.followup_skill 을 1건 자동 enqueue.

        체이닝은 1단계 고정 — 후속 잡 params 에는 followup_skill 을 심지 않는다(무한 체인
        방지). failed/paused_for_human 경로에서는 호출되지 않는다. fail-soft: 후속 enqueue
        실패가 이미 done 인 원 잡을 되돌리지 못하므로 경보만 남긴다.
        """
        params = dict(job.get("params") or {})
        followup = params.pop("followup_skill", None)
        if not followup:
            return
        # V1 2R(minor) 수용: 화이트리스트 밖 followup 은 키 파생 전에 차단 —
        # 비정상 긴 스킬명이 음수 슬라이스(160-len(suffix)<0)를 만들 여지 원천 제거.
        # Codex V2(#188): login 은 followup 자동 체이닝 금지(FOLLOWUP_SKILLS).
        if followup not in FOLLOWUP_SKILLS:
            self._notify(job, (
                f"⚠️ 잡 #{job.get('id')} 후속 스킬 무효({str(followup)[:40]!r}) — 체이닝 생략"))
            return
        # V1(Codex) 반증 수용: 부모의 idempotency_key 를 그대로 복사하면
        # fleet_job_idempotency 유니크 인덱스와 충돌해 후속 잡이 조용히 유실된다.
        # 파생 키(부모키:followup:스킬, 160자 캡)로 교체 — 재발사 시 dedup 은 유지.
        parent_key = params.get("idempotency_key")
        if parent_key:
            suffix = f":followup:{followup}"
            params["idempotency_key"] = parent_key[:160 - len(suffix)] + suffix
        payload = new_job_payload(
            machine=job.get("machine") or self.machine, skill=followup,
            position_url=job.get("position_url"),
            requested_by=job.get("requested_by"), role=job.get("role"),
            # 이슈 D 파급 수정: 부모(url) 좌석 공유 락을 상속하지 않는다 — 후속 잡은
            # 자기 스킬의 기본 계정 키(default_account_key)로 락을 건다.
            params=params, account_key="",
        )
        if payload is None:
            self._notify(job, (
                f"⚠️ 잡 #{job.get('id')} 후속({followup}) 페이로드 무효 — 체이닝 생략"))
            return
        try:
            nxt = self.queue.enqueue(payload)
            nxt_id = (nxt or {}).get("id", "?") if isinstance(nxt, Mapping) else "?"
            self._notify(job, (
                f"🔗 잡 #{job.get('id')} 후속 잡 enqueue — skill={followup} (잡 #{nxt_id})"))
        except Exception as exc:  # noqa: BLE001 — 후속 실패가 워커를 죽이면 안 됨
            self._notify(job, f"⚠️ 잡 #{job.get('id')} 후속 잡 enqueue 실패: {exc}")

    def _post_status_delay(self, status: str, poll_seconds: int) -> int:
        """V1 2R F5: paused 대기는 고정 60초가 아니라 *남은 창*만큼만(ceil, 0 하한)."""
        import math
        delay = sleep_seconds_after(status, poll_seconds)
        if status == "paused_for_human":
            delay = max(0, min(delay, math.ceil(self._yield_until - self._clock())))
        return delay

    def record_heartbeat(self) -> None:
        """단계 G: 자기 머신 심장박동을 남긴다(fail-soft — watchdog 이 stale 감지).

        이슈 D: 로컬 포털 상태 파일에서 LinkedIn 로그인 여부를 읽어 동봉한다.
        마이그레이션 전 DB(3인자 RPC 없음)면 기존 2인자 RPC 로 폴백 — 라우팅 정보는
        못 실어도 심장박동 자체는 절대 끊기지 않는다.
        """
        import os
        try:
            flag = read_linkedin_login_flag(REPO, now_epoch=int(time.time()))
        except Exception:  # noqa: BLE001 — 상태 파일 문제로 heartbeat 를 막지 않는다
            flag = False
        try:
            self.queue._call(  # noqa: SLF001 — 내부 RPC 재사용(재발명 금지)
                "POST", "/rpc/record_heartbeat",
                {"p_machine": self.machine, "p_worker_pid": os.getpid(),
                 "p_linkedin_rps_logged_in": bool(flag)})
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[fleet] heartbeat(3인자) 실패 — 레거시 폴백: {exc}", file=sys.stderr)
        try:
            self.queue._call(  # noqa: SLF001
                "POST", "/rpc/record_heartbeat",
                {"p_machine": self.machine, "p_worker_pid": os.getpid()})
        except Exception as exc:  # noqa: BLE001 — heartbeat 실패가 워커를 죽이면 안 됨
            print(f"[fleet] heartbeat 실패(fail-soft): {exc}", file=sys.stderr)

    def loop(self, poll_seconds: int = POLL_SECONDS, heartbeat_seconds: int = 60) -> None:
        print(f"[fleet] worker 시작 — machine={self.machine}")
        # SOT31(구 SOT30) S3: 폴링 전에 인증 프로브 — 죽은 열쇠가 15초 조용한 재시도로 위장 못 하게.
        probe = getattr(self.queue, "probe_auth", None)
        if callable(probe):
            wait_until_authenticated(
                probe,
                notify=lambda text: self._notify({}, text),
                sleep=time.sleep,
            )
        # V1 결함1: 심장박동을 잡 처리와 분리 — 40분 잡 실행 중에도 계속 뛰게 별도 스레드.
        import threading

        from .fleet_heartbeat import beat_loop

        stop = threading.Event()
        beater = threading.Thread(
            target=beat_loop, args=(self.record_heartbeat, stop),
            kwargs={"interval": heartbeat_seconds}, daemon=True)
        beater.start()
        try:
            while True:
                try:
                    status = self.run_once()
                except Exception as exc:  # noqa: BLE001 — 루프는 죽지 않는다(fail-soft)
                    print(f"[fleet] run_once 예외(fail-soft): {exc}", file=sys.stderr)
                    status = "error"
                # QA-2: paused_for_human 직후 쿨다운 포함 — 캡차 처리 중 같은
                # 계정으로 즉시 재claim(자동화 재진입, SOT29 §2·§4 위반) 금지.
                delay = self._post_status_delay(status, poll_seconds)
                if delay:
                    time.sleep(delay)
        finally:
            stop.set()


def default_owner_probe() -> Callable[[], bool] | None:
    """V1 2R F3 배선: 모든 OS 에서 owner_activity 감지기를 게이트로 쓴다(fail-open 금지).

    macOS = 3사 포털 한정 + idle 60초, Windows = GetLastInputInfo idle 단독(60초 유계),
    그 외 OS = 감지기 fail-closed(unsupported → 양보) 그대로 소비 — V1 3차 LOW 봉쇄.
    """
    from .owner_activity import detect_owner_activity_snapshot
    return lambda: detect_owner_activity_snapshot().owner_activity_detected


def default_yield_state_path(machine: str) -> Path:
    return Path.home() / ".valuehire" / "fleet" / f"owner-yield-{machine}.json"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Valuehire 함대 워커")
    ap.add_argument("--once", action="store_true", help="1턴만 처리하고 종료")
    ap.add_argument("--dry-run", action="store_true", help="claude 미실행(큐 왕복만)")
    ap.add_argument("--poll", type=int, default=POLL_SECONDS)
    args = ap.parse_args(argv)

    machine = machine_from_env(os.environ)
    worker = FleetWorker(
        machine, owner_probe=default_owner_probe(),
        yield_state_path=default_yield_state_path(machine))
    if args.once:
        status = worker.run_once(dry_run=args.dry_run)
        print(f"[fleet] run_once → {status}")
        return 0
    worker.loop(poll_seconds=args.poll)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
