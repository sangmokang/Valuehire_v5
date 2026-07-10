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

from .job_queue import FLEET_MACHINES, FLEET_SKILLS, JobQueueClient, _valid_url

REPO = Path(__file__).resolve().parents[2]

CLAUDE_TIMEOUT_SECONDS = 2400  # 40분
POLL_SECONDS = 30
_SUMMARY_LIMIT = 800
_PAUSE_MARKER = "PAUSED_FOR_HUMAN:"

# 기본 보고 채널 = 사장님 DM 채널(scripts/discord_command_listener.py 와 동일)
DEFAULT_REPORT_CHANNEL = "1512503041448743092"


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
    # V1: requested_by 개행/제어문자 = 프롬프트 인젝션("규칙 5: ..." 삽입) → fail-closed
    requested_by = str(job.get("requested_by") or "").strip() or "(미상)"
    if any(ord(ch) < 32 for ch in requested_by):
        raise ValueError("requested_by 에 제어문자/개행 — 프롬프트 인젝션 차단")
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
    )


def parse_worker_output(stdout: str, exit_code: int) -> dict[str, str]:
    """claude 출력 → 상태 판정. PAUSED 마커 > exit code > 빈 출력 불신."""
    text = (stdout or "").strip()
    # V1 2R: 실패 방향 설계 — 진짜 PAUSED 를 놓치는 것(캡차인데 자동 진행)이
    # 인용 오탐(불필요한 사람 호출)보다 훨씬 위험하다. 그래서:
    #  - 마지막 15개 비공백 줄 안에서 '줄 시작' 마커면 paused (후행 stderr/로그 허용)
    #  - 줄 중간 인용은 절대 매칭 안 됨, 출력 앞부분의 인용은 15줄 창 밖이라 무시
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in reversed(lines[-15:]):
        if line.startswith(_PAUSE_MARKER):
            reason = line[len(_PAUSE_MARKER):].strip() or "(사유 미기재)"
            return {"status": "paused_for_human", "reason": reason}
    if exit_code != 0:
        return {"status": "failed", "reason": f"exit={exit_code}",
                "summary": text[-_SUMMARY_LIMIT:]}
    if not text:
        return {"status": "failed", "reason": "빈 출력 — 성공으로 치지 않음"}
    return {"status": "done", "summary": text[-_SUMMARY_LIMIT:]}


def _run_claude(prompt: str, timeout: int) -> tuple[str, int]:
    """claude -p 실행(레포 루트). 반환: (stdout, exit_code)."""
    proc = subprocess.run(
        ["claude", "-p", prompt],
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
    )
    return (proc.stdout or "") + (("\n" + proc.stderr) if proc.returncode != 0 else ""), proc.returncode


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


def discord_notify(job: Mapping[str, Any], text: str) -> None:
    """잡 보고를 Discord 채널로 전송(fail-soft — 보고 실패가 잡을 죽이면 안 됨)."""
    import os
    token = _load_env_line("DISCORD_BOT_TOKEN")
    channel = os.environ.get("FLEET_REPORT_CHANNEL", DEFAULT_REPORT_CHANNEL)
    if not token:
        print(f"[fleet] discord 토큰 없음 — 보고 생략: {text[:80]}", file=sys.stderr)
        return
    try:
        req = urllib.request.Request(
            f"https://discord.com/api/v10/channels/{channel}/messages",
            data=json.dumps({"content": text[:1900]}).encode(),
            method="POST",
            headers={"Authorization": f"Bot {token}",
                     "Content-Type": "application/json",
                     "User-Agent": "ValuehireFleetWorker/1.0"},
        )
        urllib.request.urlopen(req, timeout=20)
    except Exception as exc:  # noqa: BLE001 — 보고는 fail-soft
        print(f"[fleet] discord 보고 실패(fail-soft): {exc}", file=sys.stderr)


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

    def run_once(self, dry_run: bool = False) -> str:
        """큐에서 잡 1건 처리. 반환: idle|done|paused_for_human|failed."""
        job = self.queue.claim_next(self.machine)
        if not job:
            return "idle"
        job_id = job["id"]
        try:
            prompt = build_job_prompt(job)
        except ValueError as exc:
            self.queue.release(job_id, "failed", error=f"계약 위반 잡: {exc}")
            self._notify(job, f"❌ 잡 #{job_id} 실패 — 계약 위반: {exc}")
            return "failed"
        if dry_run:
            self.queue.release(job_id, "done", result_summary="dry-run — claude 미실행")
            self._notify(job, f"🧪 잡 #{job_id} dry-run 완료 (claude 미실행)")
            return "done"
        try:
            stdout, code = self.runner(prompt, self.timeout)
        except subprocess.TimeoutExpired:
            self.queue.release(job_id, "failed", error=f"claude 타임아웃({self.timeout}s)")
            self._notify(job, f"⏱️ 잡 #{job_id} 실패 — {self.timeout}초 타임아웃")
            return "failed"
        except Exception as exc:  # noqa: BLE001 — V1: 어떤 예외든 잡을 running 고아로 두지 않는다
            self.queue.release(job_id, "failed", error=f"runner 예외: {exc}")
            self._notify(job, f"❌ 잡 #{job_id} 실패 — 실행 예외: {exc}")
            return "failed"
        result = parse_worker_output(stdout, code)
        if result["status"] == "paused_for_human":
            self.queue.release(job_id, "paused_for_human", error=result["reason"])
            self._notify(job, (
                f"⏸️ 잡 #{job_id} 사람 개입 필요 ({self.machine}): {result['reason']}\n"
                f"처리 후 /resume 으로 재개해 주세요."))
            return "paused_for_human"
        if result["status"] == "failed":
            self.queue.release(job_id, "failed",
                               error=result.get("reason", ""),
                               result_summary=result.get("summary", ""))
            self._notify(job, f"❌ 잡 #{job_id} 실패 ({self.machine}): {result.get('reason','')}")
            return "failed"
        self.queue.release(job_id, "done", result_summary=result["summary"])
        self._notify(job, f"✅ 잡 #{job_id} 완료 ({self.machine}):\n{result['summary'][:1500]}")
        return "done"

    def loop(self, poll_seconds: int = POLL_SECONDS) -> None:
        print(f"[fleet] worker 시작 — machine={self.machine}")
        while True:
            try:
                status = self.run_once()
            except Exception as exc:  # noqa: BLE001 — 루프는 죽지 않는다(fail-soft)
                print(f"[fleet] run_once 예외(fail-soft): {exc}", file=sys.stderr)
                status = "error"
            if status == "idle":
                time.sleep(poll_seconds)
            elif status == "error":
                # V1: 예외 연발 시 hot-loop 방지 — 백오프 후 재시도
                time.sleep(min(poll_seconds, 15))


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
