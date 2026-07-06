"""3사 제안 자동발송 게이트 + 원장 — SOT28 (docs/sot/28-auto-send-policy.json).

사장님 명시 지시(2026-07-07)로 SOT 불변식 3을 조건부 개정한 유일한 발송 관문.

불변식:
- fail-closed: 점수 없음·정책 오염·채널 미정의 등 판단 불가는 전부 차단.
- 발송 경로 단일화: 라이브 클릭은 evaluate_send(allowed=True) 없이는 금지.
- dry-run 기본: 라이브 발송은 명시 opt-in(--live)만.
- 원장: 라이브 발송은 전부 기록, 본문은 sha256 해시만(원문 비저장).
- 킬스위치: env 존재 자체가 정지 신호(값 "0"/빈 문자열도 정지 — 안전 우선).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .inmail_precheck import CHANNEL_CHAR_LIMITS, char_count

__all__ = [
    "AutoSendPolicyError",
    "DEFAULT_POLICY_PATH",
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


class AutoSendPolicyError(ValueError):
    """SOT28 정책 위반/오염 — 판단 불가는 허용이 아니라 차단(fail-closed)."""


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
    window = policy.get("dedupe_window_days")
    if not isinstance(window, int) or window < 1:
        raise AutoSendPolicyError("policy_invalid: dedupe_window_days 는 1 이상 정수")
    gate = policy.get("gate")
    if not isinstance(gate, dict) or not isinstance(gate.get("min_score"), int):
        raise AutoSendPolicyError("policy_invalid: gate.min_score 부재")
    channels = policy.get("channels")
    if not isinstance(channels, dict) or set(channels) != set(_CHANNELS):
        raise AutoSendPolicyError(f"policy_invalid: channels 는 정확히 {_CHANNELS}")
    for name, cfg in channels.items():
        if not isinstance(cfg, dict) or not isinstance(cfg.get("enabled"), bool):
            raise AutoSendPolicyError(f"policy_invalid: channels.{name}.enabled 부재")
        cap = cfg.get("daily_cap")
        if not isinstance(cap, int) or cap < 1:
            raise AutoSendPolicyError(f"policy_invalid: channels.{name}.daily_cap 는 1 이상 정수")
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
    precheck_passed: bool = False


@dataclass(frozen=True)
class SendDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()


class SendLedger:
    """발송 원장(JSONL append-only). 라이브 발송 기록·중복 차단·일일 상한 계산의 단일 출처."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

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
        if mode not in ("live", "dry_run"):
            raise AutoSendPolicyError(f"ledger_mode_invalid: {mode!r}")
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
        if not self.path.exists():
            return []
        rows: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows

    @staticmethod
    def _sent_at(record: dict) -> dt.datetime:
        return dt.datetime.fromisoformat(record["sent_at"])

    def sent_count_on(self, channel: str, date: dt.date) -> int:
        """해당 날짜(UTC)·채널의 라이브 발송 수 — dry-run 은 세지 않는다."""
        return sum(
            1
            for r in self.records()
            if r.get("mode") == "live"
            and r.get("channel") == channel
            and self._sent_at(r).date() == date
        )

    def already_sent(
        self,
        candidate_key: str,
        channel: str,
        *,
        window_days: int,
        now: dt.datetime | None = None,
    ) -> bool:
        """같은 후보·같은 채널로 window 안에 라이브 발송한 적이 있으면 참."""
        reference = now if now is not None else dt.datetime.now(dt.timezone.utc)
        cutoff = reference - dt.timedelta(days=window_days)
        return any(
            r.get("mode") == "live"
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

    if policy.get("kill_switch_env") in environ:
        reasons.append(f"kill_switch_on: env {policy['kill_switch_env']} 존재 — 전 채널 정지")

    channel_cfg = policy.get("channels", {}).get(request.channel)
    if request.channel not in CHANNEL_CHAR_LIMITS or channel_cfg is None:
        reasons.append(f"channel_unknown: {request.channel!r}")
    elif not channel_cfg.get("enabled"):
        reasons.append(f"channel_disabled: {request.channel}")

    min_score = policy["gate"]["min_score"]
    if request.score is None:
        reasons.append("score_missing: 점수 없는 후보는 발송 금지(fail-closed)")
    elif request.score < min_score:
        reasons.append(f"score_below_min: {request.score} < {min_score}")

    if policy["gate"].get("hard_exclusions_block", True):
        for flag in request.hard_exclude_flags:
            reasons.append(f"hard_excluded:{flag}")

    if policy["gate"].get("require_precheck_pass", True) and request.precheck_passed is not True:
        reasons.append("precheck_not_passed: inmail_precheck exit 0 증거 필요")

    limit = CHANNEL_CHAR_LIMITS.get(request.channel)
    if limit is not None and char_count(request.body) > limit:
        reasons.append(f"body_over_cap: {char_count(request.body)}자 > {limit}자")

    if channel_cfg is not None:
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

    return SendDecision(allowed=not reasons, reasons=tuple(reasons))


@dataclass(frozen=True)
class SendStep:
    action: str  # "fill" | "click"
    site: str
    selector_purpose: str
    value_field: str | None = None  # fill 일 때 SendRequest 의 어느 값을 넣는지


_SEND_PLANS: dict[str, tuple[SendStep, ...]] = {
    "saramin": (
        SendStep("fill", "saramin", "offer_comment_input", "body"),
        SendStep("fill", "saramin", "offer_charge_work_input", "body"),
        SendStep("click", "saramin", "offer_send_button"),
    ),
    "jobkorea": (
        SendStep("click", "jobkorea", "offer_preview_button"),
        SendStep("click", "jobkorea", "offer_send_button"),
    ),
    "linkedin_rps": (
        SendStep("fill", "linkedin_rps", "inmail_body_input", "body"),
        SendStep("click", "linkedin_rps", "inmail_send_button"),
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
