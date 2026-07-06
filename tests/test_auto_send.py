"""3사 자동발송 게이트 — SOT28 (docs/sot/28-auto-send-policy.json).

사장님 명시 지시(2026-07-07)로 SOT 불변식 3을 조건부 개정:
게이트(85점+·하드제외 0·precheck 통과·캡 이내·중복 아님·일일 상한 미만·킬스위치 off)를
전부 통과한 발송만 자동으로 누른다. 하나라도 어긋나면 차단(fail-closed).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing.auto_send import (
    AutoSendPolicyError,
    DEFAULT_POLICY_PATH,
    SendLedger,
    SendRequest,
    evaluate_send,
    load_policy,
    plan_send_steps,
)
from tools.multi_position_sourcing.selectors import DEFAULT_SELECTOR_MAP

REPO = Path(__file__).resolve().parent.parent
NOW = dt.datetime(2026, 7, 7, 12, 0, 0, tzinfo=dt.timezone.utc)


def _policy() -> dict:
    return load_policy(DEFAULT_POLICY_PATH)


def _request(**over) -> SendRequest:
    base = dict(
        candidate_key="https://www.linkedin.com/talent/profile/OK1",
        candidate_name="김후보",
        channel="linkedin_rps",
        position_id="P-1",
        body="본문 " * 50,
        score=90,
        hard_exclude_flags=(),
        precheck_passed=True,
    )
    base.update(over)
    return SendRequest(**base)


def _ledger(tmp_path: Path) -> SendLedger:
    return SendLedger(tmp_path / "ledger.jsonl")


# ── SOT28 정책 파일 자체 ─────────────────────────────────────
def test_policy_file_exists_and_valid() -> None:
    policy = _policy()
    assert policy["sot"] == 28
    assert policy["dry_run_default"] is True, "기본은 dry-run — 라이브는 명시 opt-in"
    assert set(policy["channels"]) == {"saramin", "jobkorea", "linkedin_rps"}
    for ch, cfg in policy["channels"].items():
        assert cfg["enabled"] is True, f"{ch} 자동발송이 사장님 지시(3사 모두)와 다름"
        assert cfg["daily_cap"] > 0
    assert policy["gate"]["min_score"] == 85
    assert policy["dedupe_window_days"] >= 1
    assert policy["kill_switch_env"]


def test_policy_schema_fail_closed(tmp_path: Path) -> None:
    broken = tmp_path / "p.json"
    broken.write_text(json.dumps({"sot": 28}), encoding="utf-8")
    with pytest.raises(AutoSendPolicyError):
        load_policy(broken)
    with pytest.raises(AutoSendPolicyError):
        load_policy(tmp_path / "missing.json")


# ── 게이트: 통과 조건 전부 충족 시에만 allowed ───────────────
def test_gate_allows_only_when_all_pass(tmp_path: Path) -> None:
    d = evaluate_send(_request(), _policy(), _ledger(tmp_path), env={}, now=NOW)
    assert d.allowed and d.reasons == ()


@pytest.mark.parametrize(
    "over,reason_prefix",
    [
        ({"score": None}, "score_missing"),
        ({"score": 84}, "score_below_min"),
        ({"hard_exclude_flags": ("freelancer",)}, "hard_excluded"),
        ({"precheck_passed": False}, "precheck_not_passed"),
        ({"channel": "gmail"}, "channel_unknown"),
        ({"body": "가" * 1900}, "body_over_cap"),  # linkedin_rps 캡 1,899
    ],
)
def test_gate_blocks_fail_closed(tmp_path: Path, over: dict, reason_prefix: str) -> None:
    d = evaluate_send(_request(**over), _policy(), _ledger(tmp_path), env={}, now=NOW)
    assert not d.allowed
    assert any(r.startswith(reason_prefix) for r in d.reasons), d.reasons


def test_gate_kill_switch_blocks(tmp_path: Path) -> None:
    policy = _policy()
    env = {policy["kill_switch_env"]: "1"}
    d = evaluate_send(_request(), policy, _ledger(tmp_path), env=env, now=NOW)
    assert not d.allowed and any(r.startswith("kill_switch_on") for r in d.reasons)
    # 빈 문자열/"0" 은 off 로 취급하지 않는다 — 존재 자체가 정지 신호(안전 우선)
    d0 = evaluate_send(_request(), policy, _ledger(tmp_path), env={policy["kill_switch_env"]: "0"}, now=NOW)
    assert not d0.allowed


def test_gate_channel_disabled_blocks(tmp_path: Path) -> None:
    policy = _policy()
    policy["channels"]["saramin"]["enabled"] = False
    d = evaluate_send(_request(channel="saramin"), policy, _ledger(tmp_path), env={}, now=NOW)
    assert not d.allowed and any(r.startswith("channel_disabled") for r in d.reasons)


# ── 원장: 중복·일일 상한 ─────────────────────────────────────
def test_ledger_duplicate_within_window_blocks(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    req = _request()
    ledger.append(
        candidate_key=req.candidate_key, channel=req.channel,
        position_id="P-0", body="이전 발송", mode="live",
        sent_at=NOW - dt.timedelta(days=89),
    )
    d = evaluate_send(req, _policy(), ledger, env={}, now=NOW)
    assert not d.allowed and any(r.startswith("duplicate_send") for r in d.reasons)


def test_ledger_duplicate_outside_window_allows(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    req = _request()
    ledger.append(
        candidate_key=req.candidate_key, channel=req.channel,
        position_id="P-0", body="옛 발송", mode="live",
        sent_at=NOW - dt.timedelta(days=91),
    )
    d = evaluate_send(req, _policy(), ledger, env={}, now=NOW)
    assert d.allowed, d.reasons


def test_ledger_daily_cap_blocks_and_dry_run_not_counted(tmp_path: Path) -> None:
    policy = _policy()
    cap = policy["channels"]["linkedin_rps"]["daily_cap"]
    ledger = _ledger(tmp_path)
    for i in range(cap):
        ledger.append(
            candidate_key=f"https://x/{i}", channel="linkedin_rps",
            position_id="P-1", body="b", mode="live", sent_at=NOW,
        )
    # dry-run 기록은 상한 계산에서 제외돼야 한다
    ledger.append(
        candidate_key="https://x/dry", channel="linkedin_rps",
        position_id="P-1", body="b", mode="dry_run", sent_at=NOW,
    )
    assert ledger.sent_count_on("linkedin_rps", NOW.date()) == cap
    d = evaluate_send(_request(), policy, ledger, env={}, now=NOW)
    assert not d.allowed and any(r.startswith("daily_cap_reached") for r in d.reasons)
    # 다른 채널은 상한과 무관
    d2 = evaluate_send(_request(channel="saramin", body="본문 " * 50), policy, ledger, env={}, now=NOW)
    assert d2.allowed, d2.reasons


def test_ledger_roundtrip_hashes_body(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    rec = ledger.append(
        candidate_key="https://x/1", channel="saramin",
        position_id="P-9", body="비밀 본문", mode="live", sent_at=NOW,
    )
    stored = ledger.records()[0]
    assert stored["candidate_key"] == "https://x/1"
    assert stored["body_sha256"] == rec["body_sha256"]
    assert "비밀 본문" not in json.dumps(stored, ensure_ascii=False), "본문 원문은 원장에 남기지 않는다"


# ── 발송 단계 계획: 셀렉터 배선(고아 금지) ───────────────────
@pytest.mark.parametrize("channel,site", [
    ("saramin", "saramin"), ("jobkorea", "jobkorea"), ("linkedin_rps", "linkedin_rps"),
])
def test_plan_send_steps_wired_to_selectors(channel: str, site: str) -> None:
    steps = plan_send_steps(channel)
    assert steps, f"{channel} 발송 단계 없음"
    assert steps[-1].action == "click", "마지막 단계는 발송 버튼 클릭"
    for step in steps:
        assert step.selector_purpose in DEFAULT_SELECTOR_MAP[site], (
            f"셀렉터 미배선: {site}.{step.selector_purpose}"
        )


def test_plan_send_steps_unknown_channel_raises() -> None:
    with pytest.raises(AutoSendPolicyError):
        plan_send_steps("gmail")


def test_selector_map_has_send_controls() -> None:
    assert "offer_send_button" in DEFAULT_SELECTOR_MAP["saramin"]
    assert "offer_send_button" in DEFAULT_SELECTOR_MAP["jobkorea"]
    assert "inmail_send_button" in DEFAULT_SELECTOR_MAP["linkedin_rps"]


# ── 배선: SOT 개정 + runner 경로 ─────────────────────────────
def test_claude_md_references_sot28() -> None:
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "28-auto-send-policy" in text, "CLAUDE.md 불변식 3이 SOT28 을 참조해야 개정 유효"


def test_runner_uses_gate_single_path() -> None:
    src = (REPO / "tools/multi_position_sourcing/auto_send_runner.py").read_text(encoding="utf-8")
    assert "evaluate_send" in src, "runner 가 게이트를 거치지 않음(우회 금지)"
    assert "plan_send_steps" in src
    assert "SendLedger" in src
