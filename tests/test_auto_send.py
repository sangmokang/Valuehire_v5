"""3사 자동발송 게이트 — SOT28 (docs/sot/28-auto-send-policy.json).

사장님 명시 지시(2026-07-07)로 SOT 불변식 3을 조건부 개정:
게이트(85점+·하드제외 0·기계 검문 직접 실행·캡 이내·중복 아님·일일 상한 미만·킬스위치 off)를
전부 통과한 발송만 자동으로 누른다. 하나라도 어긋나면 차단(fail-closed).

V1 적대검증(2026-07-07) 반례 봉인 테스트 포함: NaN/float/str 점수, bool 정책값,
pending 2단계 원장, 원장 오염 차단, 도메인 탭 선택, 게이트 없는 라이브 호출 금지.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing.auto_send import (
    AutoSendPolicyError,
    DEFAULT_POLICY_PATH,
    LedgerCorruptError,
    SendDecision,
    SendLedger,
    SendRequest,
    evaluate_send,
    load_policy,
    plan_send_steps,
)
from tools.multi_position_sourcing.auto_send_runner import _execute_live, _pick_page
from tools.multi_position_sourcing.jd_outreach import build_linkedin_inmail_jd
from tools.multi_position_sourcing.selectors import DEFAULT_SELECTOR_MAP

REPO = Path(__file__).resolve().parent.parent
NOW = dt.datetime(2026, 7, 7, 12, 0, 0, tzinfo=dt.timezone.utc)


def _policy() -> dict:
    return load_policy(DEFAULT_POLICY_PATH)


def _golden_body(name: str = "김후보", channel: str = "linkedin_rps") -> str:
    """게이트의 실검문(precheck)을 통과하는 골든샘플 v2 구조 본문 — 컴포저 실사용."""
    return build_linkedin_inmail_jd(
        candidate_name=name,
        personalized_opener="한 회사에서 리드로 성장해 오신 여정을 인상 깊게 봤습니다.",
        company_name="뤼튼테크놀로지스",
        position_title="AX Backend Engineer",
        company_briefing={},
        jd_responsibilities=["Agentic AI 플랫폼 개발"],
        jd_qualifications=["TypeScript·MongoDB API 개발 경험"],
        why_consider=["AX CIC 초기 멤버 권한"],
        channel=channel,
    )


def _request(**over) -> SendRequest:
    base = dict(
        candidate_key="https://www.linkedin.com/talent/profile/OK1",
        candidate_name="김후보",
        channel="linkedin_rps",
        position_id="P-1",
        body=_golden_body(),
        score=90,
        hard_exclude_flags=(),
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


@pytest.mark.parametrize("mutate", [
    lambda p: p["gate"].__setitem__("min_score", True),           # bool→1 강등(V1 반례 2)
    lambda p: p.__setitem__("dedupe_window_days", True),          # 중복창 1일 축소
    lambda p: p["channels"]["saramin"].__setitem__("daily_cap", True),
    lambda p: p["channels"]["saramin"].__setitem__("cdp_http", "http://evil:9999"),
])
def test_policy_bool_and_endpoint_poisoning_rejected(tmp_path: Path, mutate) -> None:
    policy = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
    mutate(policy)
    poisoned = tmp_path / "poisoned.json"
    poisoned.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(AutoSendPolicyError):
        load_policy(poisoned)


# ── 게이트: 통과 조건 전부 충족 시에만 allowed ───────────────
def test_gate_allows_only_when_all_pass(tmp_path: Path) -> None:
    d = evaluate_send(_request(), _policy(), _ledger(tmp_path), env={}, now=NOW)
    assert d.allowed and d.reasons == ()


@pytest.mark.parametrize(
    "over,reason_prefix",
    [
        ({"score": None}, "score_missing"),
        ({"score": 84}, "score_below_min"),
        ({"score": float("nan")}, "score_invalid"),   # V1 critical: NaN<85 는 False
        ({"score": 90.0}, "score_invalid"),
        ({"score": "90"}, "score_invalid"),
        ({"score": True}, "score_invalid"),
        ({"hard_exclude_flags": ("freelancer",)}, "hard_excluded"),
        ({"channel": "gmail"}, "channel_unknown"),
        ({"body": "안녕하세요 김후보님, " + "가" * 1900}, "precheck_stop:char_limit"),
        ({"body": None}, "request_invalid"),           # 크래시 아닌 차단 사유(V1 minor)
        ({"candidate_key": ""}, "request_invalid"),
        ({"hard_exclude_flags": ["freelancer"]}, "request_invalid"),
    ],
)
def test_gate_blocks_fail_closed(tmp_path: Path, over: dict, reason_prefix: str) -> None:
    d = evaluate_send(_request(**over), _policy(), _ledger(tmp_path), env={}, now=NOW)
    assert not d.allowed
    assert any(r.startswith(reason_prefix) for r in d.reasons), d.reasons


def test_gate_runs_precheck_itself_not_self_reported(tmp_path: Path) -> None:
    """V1 반례 6: 자가신고 플래그가 아니라 게이트가 검문을 직접 실행해야 한다."""
    bad_body = "안녕하세요 김후보님, 좋은 기회가 있어 연락드립니다."  # VERIFIED-PULL·P.S. 부재
    d = evaluate_send(_request(body=bad_body), _policy(), _ledger(tmp_path), env={}, now=NOW)
    assert not d.allowed
    assert any(r.startswith("precheck_stop:") for r in d.reasons), d.reasons
    # 인사말 이름 불일치도 게이트가 직접 잡는다
    d2 = evaluate_send(
        _request(candidate_name="박다른"), _policy(), _ledger(tmp_path), env={}, now=NOW
    )
    assert not d2.allowed and any("name_mismatch" in r for r in d2.reasons)


def test_gate_kill_switch_blocks(tmp_path: Path) -> None:
    policy = _policy()
    env = {policy["kill_switch_env"]: "1"}
    d = evaluate_send(_request(), policy, _ledger(tmp_path), env=env, now=NOW)
    assert not d.allowed and any(r.startswith("kill_switch_on") for r in d.reasons)
    # 빈 문자열/"0" 도 off 로 취급하지 않는다 — 존재 자체가 정지 신호(안전 우선)
    d0 = evaluate_send(_request(), policy, _ledger(tmp_path), env={policy["kill_switch_env"]: "0"}, now=NOW)
    assert not d0.allowed


def test_gate_channel_disabled_blocks(tmp_path: Path) -> None:
    policy = _policy()
    policy["channels"]["saramin"]["enabled"] = False
    d = evaluate_send(
        _request(channel="saramin", body=_golden_body(channel="saramin")),
        policy, _ledger(tmp_path), env={}, now=NOW,
    )
    assert not d.allowed and any(r.startswith("channel_disabled") for r in d.reasons)


# ── 원장: 중복·일일 상한·2단계 기록·오염 ─────────────────────
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


def test_ledger_pending_also_blocks_duplicate(tmp_path: Path) -> None:
    """V1 반례 4: 클릭 결과 불명(pending)도 발송으로 간주해 재발송 차단."""
    ledger = _ledger(tmp_path)
    req = _request()
    ledger.append(
        candidate_key=req.candidate_key, channel=req.channel,
        position_id="P-0", body="발송 시도", mode="pending", sent_at=NOW,
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
    ledger.append(
        candidate_key="https://x/dry", channel="linkedin_rps",
        position_id="P-1", body="b", mode="dry_run", sent_at=NOW,
    )
    assert ledger.sent_count_on("linkedin_rps", NOW.date()) == cap
    d = evaluate_send(_request(), policy, ledger, env={}, now=NOW)
    assert not d.allowed and any(r.startswith("daily_cap_reached") for r in d.reasons)
    # 다른 채널은 상한과 무관
    d2 = evaluate_send(
        _request(channel="saramin", body=_golden_body(channel="saramin")),
        policy, ledger, env={}, now=NOW,
    )
    assert d2.allowed, d2.reasons


def test_ledger_corrupt_line_blocks_not_crashes(tmp_path: Path) -> None:
    """V1 minor: 원장 오염은 크래시가 아니라 차단 사유 — 발송 이력 판단 불가 = 정지."""
    ledger = _ledger(tmp_path)
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    ledger.path.write_text("{깨진 json\n", encoding="utf-8")
    with pytest.raises(LedgerCorruptError):
        ledger.records()
    d = evaluate_send(_request(), _policy(), ledger, env={}, now=NOW)
    assert not d.allowed and any(r.startswith("ledger_corrupt") for r in d.reasons)


def test_ledger_naive_timestamp_treated_as_utc(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "candidate_key": "https://x/naive", "channel": "linkedin_rps",
        "position_id": "P", "body_sha256": "0" * 64, "mode": "live",
        "sent_at": "2026-07-07T11:00:00",  # naive
    }
    ledger.path.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    assert ledger.sent_count_on("linkedin_rps", NOW.date()) == 1


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


def test_ledger_lock_is_exclusive(tmp_path: Path) -> None:
    """잠금이 실제 flock 인지 — 다른 fd 로 non-blocking 획득 시도가 실패해야 한다."""
    import fcntl

    ledger = _ledger(tmp_path)
    with ledger.lock():
        lock_path = ledger.path.with_suffix(ledger.path.suffix + ".lock")
        with lock_path.open("a") as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


# ── 발송 단계 계획: 셀렉터 배선(고아 금지) ───────────────────
@pytest.mark.parametrize("channel,site", [
    ("saramin", "saramin"), ("jobkorea", "jobkorea"), ("linkedin_rps", "linkedin_rps"),
])
def test_plan_send_steps_wired_to_selectors(channel: str, site: str) -> None:
    steps = plan_send_steps(channel)
    assert steps, f"{channel} 발송 단계 없음"
    assert steps[-1].action == "click", "마지막 단계는 발송 버튼 클릭"
    assert steps[-1].guard_body is True, "발송 클릭 직전 본문 실재 guard 필수(V1 반례 5)"
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


# ── 라이브 경로 안전장치 ─────────────────────────────────────
def test_execute_live_requires_allowed_decision() -> None:
    """구조적 강제(V1 minor): 게이트 판정 객체 없이 라이브 발송 호출 불가."""
    with pytest.raises(AutoSendPolicyError):
        _execute_live(_request(), _policy(), SendDecision(allowed=False, reasons=("x",)))
    with pytest.raises(AutoSendPolicyError):
        _execute_live(_request(), _policy(), None)  # type: ignore[arg-type]


def test_pick_page_matches_channel_domain_only() -> None:
    """V1 반례 5: pages[0] 임의 선택 금지 — 채널 도메인 탭만 선택."""
    pages = [
        {"type": "page", "url": "https://www.google.com/"},
        {"type": "iframe", "url": "https://www.saramin.co.kr/frame"},
        {"type": "page", "url": "https://www.saramin.co.kr/talent-pool"},
    ]
    assert _pick_page(pages, "saramin")["url"].endswith("/talent-pool")
    with pytest.raises(RuntimeError):
        _pick_page(pages, "jobkorea")
    with pytest.raises(AutoSendPolicyError):
        _pick_page(pages, "gmail")


def test_pick_page_rejects_lookalike_urls() -> None:
    """V2 minor 1: 부분문자열 매칭 금지 — hostname 정확/서브도메인 일치만 인정."""
    lookalikes = [
        {"type": "page", "url": "https://evil.example/?next=https://www.linkedin.com/"},
        {"type": "page", "url": "https://linkedin.com.evil.example/talent"},
        {"type": "page", "url": "https://notlinkedin.com/talent"},
    ]
    with pytest.raises(RuntimeError):
        _pick_page(lookalikes, "linkedin_rps")
    real = lookalikes + [{"type": "page", "url": "https://www.linkedin.com/talent/inbox"}]
    assert _pick_page(real, "linkedin_rps")["url"].endswith("/talent/inbox")


def test_sent_count_folds_pending_live_pair(tmp_path: Path) -> None:
    """V2 minor 2: pending→live 2단계 기록은 같은 후보 1건 — 상한 2배속 소모 방지."""
    ledger = _ledger(tmp_path)
    for mode in ("pending", "live"):
        ledger.append(
            candidate_key="https://x/one", channel="saramin",
            position_id="P-1", body="b", mode=mode, sent_at=NOW,
        )
    assert ledger.sent_count_on("saramin", NOW.date()) == 1


# ── 배선: SOT 개정 + runner 경로 ─────────────────────────────
def test_claude_md_references_sot28() -> None:
    text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert "28-auto-send-policy" in text, "CLAUDE.md 불변식 3이 SOT28 을 참조해야 개정 유효"


def test_runner_uses_gate_single_path() -> None:
    src = (REPO / "tools/multi_position_sourcing/auto_send_runner.py").read_text(encoding="utf-8")
    assert "evaluate_send" in src, "runner 가 게이트를 거치지 않음(우회 금지)"
    assert "plan_send_steps" in src
    assert "SendLedger" in src
    assert "ledger.lock()" in src, "판정+선기록이 잠금 임계구역 밖 — TOCTOU 재발(V1 반례 3)"
    assert '"pending"' in src, "pending 선기록 부재 — 클릭 후 예외 시 이중발송(V1 반례 4)"
