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
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from .job_queue import (
    FLEET_MACHINES,
    FLEET_SKILLS,
    JobQueueClient,
    _valid_url,
    new_job_payload,
)

REPO = Path(__file__).resolve().parents[2]

CLAUDE_TIMEOUT_SECONDS = 2400  # 40분
POLL_SECONDS = 30
_SUMMARY_LIMIT = 800
_PAUSE_MARKER = "PAUSED_FOR_HUMAN:"
_SEARCH_RECEIPT_MARKER = "FLEET_SEARCH_RECEIPT:"

# 기본 보고 채널 = 사장님 DM 채널(scripts/discord_command_listener.py 와 동일)
DEFAULT_REPORT_CHANNEL = "1512503041448743092"
_NOTIFICATION_DEDUPE: dict[str, float] = {}

# QA-2(2026-07-13): 캡차/2FA 로 paused_for_human 이 되면 계정락이 풀리는데, 곧바로
# 다음 잡을 claim 하면 사장님이 캡차를 푸는 크롬/계정에 자동화가 재진입한다(SOT29 §2·§4).
# 서버측 락 유지(DB 마이그레이션)는 후속 — 워커측 쿨다운으로 먼저 막는다.
PAUSE_COOLDOWN_SECONDS = 600
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
    """VALUEHIRE_MACHINE 필수 + 화이트리스트 — 무효면 기동 거부."""
    raw = (environ.get("VALUEHIRE_MACHINE") or "").strip()
    if raw not in FLEET_MACHINES:
        raise RuntimeError(
            f"VALUEHIRE_MACHINE 이 유효하지 않습니다: {raw!r} (허용: {FLEET_MACHINES})")
    return raw


def build_job_prompt(job: Mapping[str, Any]) -> str:
    """잡 1건 → claude -p 실행 문구. 계약 위반 잡은 ValueError(fail-closed)."""
    skill = job.get("skill")
    if skill not in FLEET_SKILLS:
        raise ValueError(f"허용되지 않은 스킬: {skill!r}")
    job_id = job.get("id")
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise ValueError(f"invalid job id: {job_id!r}")
    url = job.get("position_url")
    if not _valid_url(url):
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


def _run_claude(prompt: str, timeout: int) -> tuple[str, str, int]:
    """claude -p 실행(레포 루트). 반환: (stdout, stderr, exit_code) — QA-3 로 분리."""
    proc = subprocess.run(
        ["claude", "-p", prompt],
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
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


AUTH_BACKOFF_SECONDS: tuple[int, ...] = (60, 300, 900)  # SOT30 S3 재시도 백오프


def wait_until_authenticated(
    probe: Callable[[], tuple[str, str]],
    *,
    notify: Callable[[str], None],
    sleep: Callable[[float], None],
    max_attempts: int | None = None,
) -> bool:
    """SOT30 S3 — 기동 인증 게이트. 죽은 열쇠(401)로 조용히 폴링루프에 들어가지 않는다.

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
    ) -> None:
        if machine not in FLEET_MACHINES:
            raise RuntimeError(f"unknown machine: {machine!r}")
        self.machine = machine
        self.queue = queue if queue is not None else JobQueueClient()
        self.runner = runner or _run_claude
        self.notifier = notifier or discord_notify
        self.timeout = timeout

    def _notify(self, job: Mapping[str, Any], text: str) -> None:
        try:
            self.notifier(job, text)
        except Exception as exc:  # noqa: BLE001
            print(f"[fleet] notify 실패(fail-soft): {exc}", file=sys.stderr)

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
        job = self.queue.claim_next(self.machine)
        if not job:
            return "idle"
        job_id = job["id"]
        try:
            prompt = build_job_prompt(job)
        except ValueError as exc:
            self._release(job, job_id, "failed", error=f"계약 위반 잡: {exc}")
            self._notify(job, f"❌ 잡 #{job_id} 실패 — 계약 위반: {exc}")
            return "failed"
        if dry_run:
            self._release(job, job_id, "done", result_summary="dry-run — claude 미실행")
            self._notify(job, f"🧪 잡 #{job_id} dry-run 완료 (claude 미실행)")
            return "done"
        # 이슈 C(2026-07-15 goal §3): claim~완료 사이 공백 메움 — 실행 직전 1회, fail-soft(_notify)
        self._notify(job, (
            f"▶️ 잡 #{job_id} 실행 시작 ({self.machine}, skill={job.get('skill')}) — "
            f"position: {job.get('position_url')}"))
        try:
            raw = self.runner(prompt, self.timeout)
        except subprocess.TimeoutExpired:
            self._release(job, job_id, "failed", error=f"claude 타임아웃({self.timeout}s)")
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
        result = parse_worker_output(stdout, code, stderr=stderr)
        if result["status"] == "paused_for_human":
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
        self._release(job, job_id, "done", result_summary=result["summary"])
        self._notify(job, f"✅ 잡 #{job_id} 완료 ({self.machine}):\n{result['summary'][:1500]}")
        self._enqueue_followup(job)
        return "done"

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
        payload = new_job_payload(
            machine=job.get("machine") or self.machine, skill=followup,
            position_url=job.get("position_url"),
            requested_by=job.get("requested_by"), role=job.get("role"),
            params=params, account_key=str(job.get("account_key") or ""),
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

    def record_heartbeat(self) -> None:
        """단계 G: 자기 머신 심장박동을 남긴다(fail-soft — watchdog 이 stale 감지)."""
        import os
        try:
            self.queue._call(  # noqa: SLF001 — 내부 RPC 재사용(재발명 금지)
                "POST", "/rpc/record_heartbeat",
                {"p_machine": self.machine, "p_worker_pid": os.getpid()})
        except Exception as exc:  # noqa: BLE001 — heartbeat 실패가 워커를 죽이면 안 됨
            print(f"[fleet] heartbeat 실패(fail-soft): {exc}", file=sys.stderr)

    def loop(self, poll_seconds: int = POLL_SECONDS, heartbeat_seconds: int = 60) -> None:
        print(f"[fleet] worker 시작 — machine={self.machine}")
        # SOT30 S3: 폴링 전에 인증 프로브 — 죽은 열쇠가 15초 조용한 재시도로 위장 못 하게.
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
                delay = sleep_seconds_after(status, poll_seconds)
                if delay:
                    time.sleep(delay)
        finally:
            stop.set()


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Valuehire 함대 워커")
    ap.add_argument("--once", action="store_true", help="1턴만 처리하고 종료")
    ap.add_argument("--dry-run", action="store_true", help="claude 미실행(큐 왕복만)")
    ap.add_argument("--poll", type=int, default=POLL_SECONDS)
    args = ap.parse_args(argv)

    machine = machine_from_env(os.environ)
    worker = FleetWorker(machine)
    if args.once:
        status = worker.run_once(dry_run=args.dry_run)
        print(f"[fleet] run_once → {status}")
        return 0
    worker.loop(poll_seconds=args.poll)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
