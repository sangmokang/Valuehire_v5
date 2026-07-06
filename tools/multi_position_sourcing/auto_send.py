"""3사 제안 자동발송 게이트 + 원장 — SOT28 (docs/sot/28-auto-send-policy.json).

사장님 명시 지시(2026-07-07)로 SOT 불변식 3을 조건부 개정한 유일한 발송 관문.

불변식:
- fail-closed: 점수 없음/타입 오염·정책 오염·채널 미정의·원장 오염 등 판단 불가는 전부 차단.
- 발송 경로 단일화: 라이브 클릭은 evaluate_send(allowed=True) 판정 객체 없이는 금지.
- dry-run 기본: 라이브 발송은 명시 opt-in(--live)만.
- 원장: 클릭 직전 pending 선기록 → 성공 확정 시 live 기록(2단계). 본문은 sha256 만.
  pending 도 중복·상한 계산에 발송으로 센다(클릭 결과 불명 = 발송으로 간주, 안전 우선).
- 킬스위치: env 존재 자체가 정지 신호(값 "0"/빈 문자열도 정지 — 안전 우선).
- 검문(precheck)은 자가신고 플래그가 아니라 게이트가 직접 실행한다(V1 반례 6 봉인).

V1 적대검증(2026-07-07)에서 봉인한 구멍: NaN/float/str 점수 통과(critical),
bool 이 int 검사 통과(min_score=true→1), 원장 TOCTOU 경쟁, 클릭 후 예외 시
원장 미기록 이중발송, 원장 오염 크래시 — 각 지점에 주석으로 표시.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping

from .inmail_precheck import CHANNEL_CHAR_LIMITS, char_count, precheck_inmail

__all__ = [
    "AutoSendPolicyError",
    "DEFAULT_POLICY_PATH",
    "LedgerCorruptError",
    "SendDecision",
    "SendLedger",
    "SendRequest",
    "SendStep",
    "evaluate_send",
    "load_policy",
    "plan_send_steps",
]

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = _REPO_ROOT / "docs" / "sot" / "28-auto-send-policy.json"

_CHANNELS: tuple[str, ...] = ("saramin", "jobkorea", "linkedin_rps")

# 발송으로 세는 원장 모드 — pending(클릭 결과 불명)도 발송으로 간주(fail-closed)
_COUNTED_MODES = ("pending", "live")
_LEDGER_MODES = ("pending", "live", "dry_run")


class AutoSendPolicyError(ValueError):
    """SOT28 정책 위반/오염 — 판단 불가는 허용이 아니라 차단(fail-closed)."""


class LedgerCorruptError(AutoSendPolicyError):
    """원장 파일 오염 — 크래시 대신 차단 사유로 승격시키기 위한 전용 예외."""


def _strict_int(value) -> bool:
    """int 이되 bool 이 아님 — isinstance(True, int) 구멍 봉인(V1 반례 2)."""
    return isinstance(value, int) and not isinstance(value, bool)


def load_policy(path: Path | str | None = None) -> dict:
    """SOT28 정책 파일을 읽고 스키마를 fail-closed 로 검증해 반환."""
    policy_path = Path(path) if path is not None else DEFAULT_POLICY_PATH
    if not policy_path.exists():
        raise AutoSendPolicyError(f"policy_missing: {policy_path}")
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutoSendPolicyError(f"policy_unreadable: {policy_path} — {exc}") from exc

    if not isinstance(policy, dict) or policy.get("sot") != 28:
        raise AutoSendPolicyError("policy_invalid: sot != 28")
    if policy.get("dry_run_default") is not True:
        raise AutoSendPolicyError("policy_invalid: dry_run_default 는 true 여야 함(SOT28 불변식)")
    kill_env = policy.get("kill_switch_env")
    if not isinstance(kill_env, str) or not kill_env:
        raise AutoSendPolicyError("policy_invalid: kill_switch_env 부재")
    if not _strict_int(policy.get("dedupe_window_days")) or policy["dedupe_window_days"] < 1:
        raise AutoSendPolicyError("policy_invalid: dedupe_window_days 는 1 이상 정수(bool 금지)")
    gate = policy.get("gate")
    if not isinstance(gate, dict) or not _strict_int(gate.get("min_score")):
        raise AutoSendPolicyError("policy_invalid: gate.min_score 는 정수(bool 금지)")
    channels = policy.get("channels")
    if not isinstance(channels, dict) or set(channels) != set(_CHANNELS):
        raise AutoSendPolicyError(f"policy_invalid: channels 는 정확히 {_CHANNELS}")
    for name, cfg in channels.items():
        if not isinstance(cfg, dict) or not isinstance(cfg.get("enabled"), bool):
            raise AutoSendPolicyError(f"policy_invalid: channels.{name}.enabled 부재")
        if not _strict_int(cfg.get("daily_cap")) or cfg["daily_cap"] < 1:
            raise AutoSendPolicyError(f"policy_invalid: channels.{name}.daily_cap 는 1 이상 정수(bool 금지)")
        cdp = cfg.get("cdp_http")
        if cdp is not None and (
            not isinstance(cdp, str) or not cdp.startswith("http://127.0.0.1:")
        ):
            # 정책 오염으로 임의 CDP 엔드포인트에 붙는 것 차단(V1 minor 4)
            raise AutoSendPolicyError(
                f"policy_invalid: channels.{name}.cdp_http 는 http://127.0.0.1:* 만 허용"
            )
    return policy


@dataclass(frozen=True)
class SendRequest:
    candidate_key: str
    candidate_name: str
    channel: str
    position_id: str
    body: str
    score: int | None
    score_breakdown: Mapping[str, int] | None = None
    hard_exclude_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SendDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()


class SendLedger:
    """발송 원장(JSONL append-only). 발송 기록·중복 차단·일일 상한 계산의 단일 출처.

    2단계 기록(V1 반례 4 봉인): 클릭 직전 mode="pending" 선기록 → 성공 확정 시
    mode="live" 추가 기록. 실패해도 pending 이 남아 재발송이 차단된다(수동 확인 후 해소).
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)

    @contextlib.contextmanager
    def lock(self) -> Iterator[None]:
        """프로세스 간 배타 잠금 — 판정(evaluate)과 기록(append)을 한 임계구역으로 묶어
        동시 실행 이중발송(TOCTOU, V1 반례 3)을 차단한다."""
        import fcntl

        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def append(
        self,
        *,
        candidate_key: str,
        channel: str,
        position_id: str,
        body: str,
        mode: str,
        sent_at: dt.datetime | None = None,
    ) -> dict:
        if mode not in _LEDGER_MODES:
            raise AutoSendPolicyError(f"ledger_mode_invalid: {mode!r} — 허용 {_LEDGER_MODES}")
        when = sent_at if sent_at is not None else dt.datetime.now(dt.timezone.utc)
        record = {
            "candidate_key": candidate_key,
            "channel": channel,
            "position_id": position_id,
            "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "mode": mode,
            "sent_at": when.isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def records(self) -> list[dict]:
        """원장 전체. 오염 줄은 크래시 대신 LedgerCorruptError — 호출측이 차단 사유로 승격."""
        if not self.path.exists():
            return []
        rows: list[dict] = []
        for lineno, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("record 는 객체여야 함")
                self._sent_at(row)  # 시각 파싱 가능성까지 여기서 검증
            except (ValueError, KeyError, TypeError) as exc:
                raise LedgerCorruptError(
                    f"ledger_corrupt: {self.path}:{lineno} — {exc} (수동 확인 필요)"
                ) from exc
            rows.append(row)
        return rows

    @staticmethod
    def _sent_at(record: dict) -> dt.datetime:
        parsed = dt.datetime.fromisoformat(record["sent_at"])
        if parsed.tzinfo is None:  # naive 레코드는 UTC 로 간주(비교 크래시 방지, V1 minor 2)
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed

    def sent_count_on(self, channel: str, date: dt.date) -> int:
        """해당 날짜(UTC)·채널의 발송 수 — pending+live 를 세되 같은 후보의
        pending→live 2단계 기록은 1건으로 접는다(상한 2배속 소모 방지, V2 minor 2).
        dry-run 은 제외."""
        keys = {
            r.get("candidate_key")
            for r in self.records()
            if r.get("mode") in _COUNTED_MODES
            and r.get("channel") == channel
            and self._sent_at(r).date() == date
        }
        return len(keys)

    def already_sent(
        self,
        candidate_key: str,
        channel: str,
        *,
        window_days: int,
        now: dt.datetime | None = None,
    ) -> bool:
        """같은 후보·같은 채널로 window 안에 발송(pending 포함)한 적이 있으면 참."""
        reference = now if now is not None else dt.datetime.now(dt.timezone.utc)
        cutoff = reference - dt.timedelta(days=window_days)
        return any(
            r.get("mode") in _COUNTED_MODES
            and r.get("candidate_key") == candidate_key
            and r.get("channel") == channel
            and self._sent_at(r) >= cutoff
            for r in self.records()
        )


def evaluate_send(
    request: SendRequest,
    policy: dict,
    ledger: SendLedger,
    *,
    env: Mapping[str, str] | None = None,
    now: dt.datetime | None = None,
) -> SendDecision:
    """SOT28 단일 발송 관문 — 사유 0개일 때만 allowed. 판단 불가는 전부 차단."""
    environ = env if env is not None else os.environ
    reference = now if now is not None else dt.datetime.now(dt.timezone.utc)
    reasons: list[str] = []

    # 요청 타입 검문 — 오염 입력은 크래시가 아니라 차단 사유(V1 minor 1)
    for field_name in ("candidate_key", "candidate_name", "channel", "position_id"):
        value = getattr(request, field_name)
        if not isinstance(value, str) or not value.strip():
            reasons.append(f"request_invalid: {field_name} 는 비어있지 않은 문자열이어야 함")
    if not isinstance(request.body, str) or not request.body.strip():
        reasons.append("request_invalid: body 는 비어있지 않은 문자열이어야 함")
    if not isinstance(request.hard_exclude_flags, tuple):
        reasons.append("request_invalid: hard_exclude_flags 는 tuple 이어야 함")
    if reasons:
        return SendDecision(allowed=False, reasons=tuple(reasons))

    if policy.get("kill_switch_env") in environ:
        reasons.append(f"kill_switch_on: env {policy['kill_switch_env']} 존재 — 전 채널 정지")

    channel_cfg = policy.get("channels", {}).get(request.channel)
    if request.channel not in CHANNEL_CHAR_LIMITS or channel_cfg is None:
        reasons.append(f"channel_unknown: {request.channel!r}")
    elif not channel_cfg.get("enabled"):
        reasons.append(f"channel_disabled: {request.channel}")

    # 점수: int 만 인정(bool 금지). None=미채점, 그 외 타입(float/NaN/str)=오염 — 전부 차단.
    # V1 critical 봉인: json 의 NaN 은 float — nan<85 가 False 라 종전 코드는 통과시켰다.
    min_score = policy["gate"]["min_score"]
    if request.score is None:
        reasons.append("score_missing: 점수 없는 후보는 발송 금지(fail-closed)")
    elif not _strict_int(request.score):
        reasons.append(
            f"score_invalid: 점수는 정수만 인정(현재 {type(request.score).__name__}) — fail-closed"
        )
    elif request.score < min_score:
        reasons.append(f"score_below_min: {request.score} < {min_score}")

    if policy["gate"].get("hard_exclusions_block", True):
        for flag in request.hard_exclude_flags:
            reasons.append(f"hard_excluded:{flag}")

    # 검문은 게이트가 직접 실행한다 — 자가신고 플래그 금지(V1 반례 6: 종이 게이트).
    if policy["gate"].get("require_precheck_pass", True):
        check = precheck_inmail(
            request.body, profile_name=request.candidate_name, channel=request.channel
        )
        reasons.extend(f"precheck_stop:{stop}" for stop in check.stops)
    else:
        limit = CHANNEL_CHAR_LIMITS.get(request.channel)
        if limit is not None and char_count(request.body) > limit:
            reasons.append(f"body_over_cap: {char_count(request.body)}자 > {limit}자")

    if channel_cfg is not None:
        try:
            if ledger.already_sent(
                request.candidate_key,
                request.channel,
                window_days=policy["dedupe_window_days"],
                now=reference,
            ):
                reasons.append(
                    f"duplicate_send: {policy['dedupe_window_days']}일 내 동일 후보·채널 발송 이력"
                )
            cap = channel_cfg["daily_cap"]
            if ledger.sent_count_on(request.channel, reference.date()) >= cap:
                reasons.append(f"daily_cap_reached: {request.channel} 일일 상한 {cap}건")
        except LedgerCorruptError as exc:
            # 원장 오염 = 발송 이력 판단 불가 → 차단(크래시 아님). 채널 정지 상태는
            # 수동으로 원장을 복구해야 풀린다(의도된 안전 정지).
            reasons.append(str(exc))

    return SendDecision(allowed=not reasons, reasons=tuple(reasons))


@dataclass(frozen=True)
class SendStep:
    action: str  # "fill" | "click"
    site: str
    selector_purpose: str
    value_field: str | None = None  # fill 일 때 SendRequest 의 어느 값을 넣는지
    guard_body: bool = False  # click 직전 본문(≥100자)이 화면에 실재하는지 검사(V1 반례 5)


_SEND_PLANS: dict[str, tuple[SendStep, ...]] = {
    "saramin": (
        SendStep("fill", "saramin", "offer_comment_input", "body"),
        SendStep("fill", "saramin", "offer_charge_work_input", "body"),
        SendStep("click", "saramin", "offer_send_button", guard_body=True),
    ),
    "jobkorea": (
        # 본문 필드는 상류(pos-fill/등록 흐름)가 채운다 — guard 가 빈 모달 발송을 차단.
        SendStep("click", "jobkorea", "offer_preview_button"),
        SendStep("click", "jobkorea", "offer_send_button", guard_body=True),
    ),
    "linkedin_rps": (
        SendStep("fill", "linkedin_rps", "inmail_body_input", "body"),
        SendStep("click", "linkedin_rps", "inmail_send_button", guard_body=True),
    ),
}


def plan_send_steps(channel: str) -> tuple[SendStep, ...]:
    """채널별 발송 단계(셀렉터 purpose 배선 포함). 미지원 채널은 fail-closed."""
    from .selectors import DEFAULT_SELECTOR_MAP  # 순환 import 방지 지연 로드

    plan = _SEND_PLANS.get(channel)
    if plan is None:
        raise AutoSendPolicyError(f"channel_unknown: {channel!r} — 지원 {sorted(_SEND_PLANS)}")
    for step in plan:
        if step.selector_purpose not in DEFAULT_SELECTOR_MAP.get(step.site, {}):
            raise AutoSendPolicyError(
                f"selector_unwired: {step.site}.{step.selector_purpose} — selectors.py 배선 필요"
            )
    return plan
