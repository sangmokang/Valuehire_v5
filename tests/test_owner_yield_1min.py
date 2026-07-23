"""사장님 양보 1분 자동 재개(SOT29 INV9, 2026-07-20 60초 개정) + LinkedIn 로그인 머신 탐색 prompting — 이슈 #107.

사장님 지시(2026-07-15, 2026-07-20 60초·3사 한정 개정): "내가 쓸 동안은 멈췄다가 1분 뒤까지 이상이 없으면 계속 시작해."
- 영구 중단(변형 backlog 폐기·10분 쿨다운·>=300 스펙)은 이 원칙을 방해하는 코드 → 삭제.
- LinkedIn(skill=url) 잡은 로그인된 기기(macmini/macbook/winpc 중 하나)를 탐색해 쓰도록 프롬프트에 명시.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.multi_position_sourcing.fleet_worker import (
    OWNER_YIELD_RESUME_SECONDS,
    PAUSE_COOLDOWN_SECONDS,
    FleetWorker,
    build_job_prompt,
    sleep_seconds_after,
)

REPO = Path(__file__).resolve().parents[1]
OWNER_ID = "814353841088757800"


# ── 인수 1: 대기 시간 = 1분(60초), 10분(600) 잔존 0 ────────────────

def test_pause_resume_is_one_minute():
    assert OWNER_YIELD_RESUME_SECONDS == 60, "SOT29 INV9(2026-07-20 개정) — 1분 뒤 자동 재개"
    assert PAUSE_COOLDOWN_SECONDS == OWNER_YIELD_RESUME_SECONDS, "별칭 드리프트 금지(단일 출처)"
    assert sleep_seconds_after("paused_for_human", 30) == 60


def test_no_600_cooldown_left_in_worker_source():
    src = (REPO / "tools" / "multi_position_sourcing" / "fleet_worker.py").read_text("utf-8")
    assert "PAUSE_COOLDOWN_SECONDS = 600" not in src, "사장님 원칙(1분)을 방해하는 10분 쿨다운 잔존"


# ── 인수 2: paused 후 backlog 미폐기 → 1분 양보 → 자동 재개 ─────────

class FakeQueue:
    def __init__(self, jobs):
        self.jobs = list(jobs)
        self.released = []
        self.enqueued = []
        self.claim_calls = 0

    def claim_next(self, machine):
        self.claim_calls += 1
        return self.jobs.pop(0) if self.jobs else None

    def release(self, job_id, status, *, result_summary="", error=""):
        self.released.append((job_id, status))
        return [{"id": job_id, "status": status}]

    def enqueue(self, payload):
        self.enqueued.append(payload)
        return {"id": 100 + len(self.enqueued), **payload}


def _job(job_id=7, params=None):
    return {
        "id": job_id, "machine": "macmini", "skill": "humansearch",
        "position_url": "https://app.clickup.com/t/TASK1",
        "requested_by": f"{OWNER_ID}:owner", "role": "owner",
        "params": params or {},
    }


def _group_job(job_id=7):
    return _job(job_id, params={"group_session": {
        "group_id": "sales-3to10-abc",
        "sibling_position_urls": ["https://app.clickup.com/t/TASK2"],
        "note": "같은 세션 연속 검색",
        "pending_variants": [
            {"channel": "saramin", "keyword": "변형키워드A", "filters": {}},
        ],
    }})


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


def _worker(queue, clock, pause_on_job_id=None, *, wall_clock=None, yield_state_path=None):
    def runner(prompt, timeout):
        if pause_on_job_id is not None and f"잡 #{pause_on_job_id}" in prompt:
            return ("PAUSED_FOR_HUMAN: 캡차", 0)
        return ('후보 3명 저장 완료\nHUMANSEARCH_EVIDENCE_RECEIPT:{"opened_profiles":0,"profile_evidence":[]}', 0)

    return FleetWorker(
        machine="macmini", queue=queue, runner=runner,
        notifier=lambda job, text: None, clock=clock,
        wall_clock=wall_clock, yield_state_path=yield_state_path)


def test_paused_suspends_backlog_then_resumes_after_1min():
    """사장님 스펙(#107): paused 는 '1분 양보'지 '영구 폐기'가 아니다.

    기존 #104 의 영구 폐기 테스트(test_paused_for_human_clears_backlog_no_night_reentry)를
    사장님 지시로 대체한다.
    """
    clock = FakeClock()
    q = FakeQueue([_group_job(7), _job(8)])
    w = _worker(q, clock, pause_on_job_id=8)
    assert w.run_once() == "done"              # 잡7 → 변형 backlog 적재
    assert w.run_once() == "paused_for_human"  # 잡8 캡차 → 1분 양보 시작(폐기 아님)
    # 1분 안: 사장님이 처리 중일 수 있음 — idle 이어도 enqueue 금지(눈치)
    clock.now += 59
    assert w.run_once() == "idle"
    assert q.enqueued == [], "1분 전 자동 enqueue = 양보 위반"
    # 1분 경과 + 이상 없음: 자동 재개(심야 지속) — 영구 중단 금지
    clock.now += 2
    assert w.run_once() == "idle"
    assert len(q.enqueued) == 1, "1분 뒤 자동 재개 미구현 — 영구 중단은 SOT29 INV9 위반"
    assert q.enqueued[0]["params"]["variant"]["keyword"] == "변형키워드A"


def test_repeated_pause_extends_yield_window():
    """pause 가 또 오면 그 시점부터 다시 1분 — '이상이 없으면'의 코드 표현.

    (V1 F1 반영 재작성: 1분 창 안에서는 claim 자체가 안 되므로, 2번째 이상 신호는
    첫 창이 지난 뒤에 온다 — 그 시점부터 창이 다시 1분으로 연장돼야 한다.)
    """
    clock = FakeClock()
    q = FakeQueue([_group_job(7), _job(8), _job(9)])
    w = _worker(q, clock, pause_on_job_id=None)
    w.runner = lambda prompt, timeout: (
        ('후보 3명 저장 완료\nHUMANSEARCH_EVIDENCE_RECEIPT:{"opened_profiles":0,"profile_evidence":[]}', 0)
        if "잡 #7" in prompt else ("PAUSED_FOR_HUMAN: 캡차", 0))
    assert w.run_once() == "done"
    assert w.run_once() == "paused_for_human"   # t=0: 1번째 이상 → 창 [0,60)
    clock.now += 61
    assert w.run_once() == "paused_for_human"   # t=61: 재개 직후 또 이상 → 창 연장 [61,121)
    clock.now += 30                             # t=91 (2번째 이상 후 30초)
    assert w.run_once() == "idle"
    assert q.enqueued == [], "직전 이상 후 1분이 안 지났는데 재개 — 창 연장 미구현"
    clock.now += 31                             # t=122 (2번째 이상 후 61초)
    assert w.run_once() == "idle"
    assert len(q.enqueued) == 1


# ── 인수 3: LinkedIn(url) 잡 프롬프트에 로그인 머신 탐색 지시 ────────

def test_url_job_prompt_instructs_login_machine_discovery():
    prompt = build_job_prompt({
        "id": 5, "skill": "url",
        "position_url": "https://www.linkedin.com/talent/hire/1/discover/recruiterSearch",
        "requested_by": f"{OWNER_ID}:owner", "role": "owner", "params": {},
    })
    assert "로그인된" in prompt, "로그인된 브라우저 탐색 지시 없음"
    for machine in ("macmini", "macbook", "winpc"):
        assert machine in prompt, f"후보 머신 {machine} 안내 없음"
    # 사장님 지시: 탐색 결과 이 머신이 아니면 로그인 머신을 찾아 보고
    assert "탐색" in prompt


def test_humansearch_prompt_unchanged_by_url_rule():
    prompt = build_job_prompt(_job())
    assert "linkedin_rps_logged_in" not in prompt  # url 전용 지시가 다른 스킬에 새지 않음


# ── 인수 4: SOT29 에 INV9 명문화 ─────────────────────────────────────

def test_sot29_has_owner_yield_invariant():
    data = json.loads((REPO / "docs" / "sot" / "29-fleet-control.json").read_text("utf-8"))
    inv = data["invariants"].get("INV9_owner_yield_1min", "")
    assert "60" in inv and "재개" in inv, "SOT29 INV9(1분 자동 재개) 미명문화"
    md = (REPO / "docs" / "sot" / "29-fleet-control.md").read_text("utf-8")
    assert "1분" in md and "자동 재개" in md
    claude_md = (REPO / "CLAUDE.md").read_text("utf-8")
    assert "60초" in claude_md or "1분" in claude_md, "최상위 SOT(CLAUDE.md)에 수치 미반영"


# ── V1(Codex) 적대검증 수용 회귀 (2026-07-15 2R) ────────────────────

def test_yield_window_gates_claim_too():
    """V1 F1: 1분 창은 enqueue 만이 아니라 *다음 잡 claim* 도 막아야 한다."""
    clock = FakeClock()
    q = FakeQueue([_job(8), _job(9)])
    w = _worker(q, clock, pause_on_job_id=8)
    assert w.run_once() == "paused_for_human"   # t=0: 이상 신호
    clock.now += 30
    assert w.run_once() == "idle"
    assert q.jobs and q.jobs[0]["id"] == 9, "1분 내 다음 잡 claim = 양보 위반(V1 F1)"
    clock.now += 31                              # t=61: 창 경과 → 재개
    assert w.run_once() == "done"
    assert not q.jobs


def test_yield_window_survives_worker_restart(tmp_path):
    """V1 F2: 워커 재시작(launchd KeepAlive)이 1분 창을 지우면 안 된다 — 로컬 상태 파일."""
    state = tmp_path / "owner-yield-macmini.json"
    clock = FakeClock()
    q = FakeQueue([_job(8), _job(9)])
    w = _worker(q, clock, pause_on_job_id=8)
    w._yield_state_path = state
    assert w.run_once() == "paused_for_human"
    assert state.exists(), "양보 창 미영속 — 재시작 시 즉시 재개(V1 F2)"
    # 재시작: 새 인스턴스가 상태 파일에서 창을 복원
    q2 = FakeQueue([_job(9)])
    w2 = _worker(q2, FakeClock(5000.0), pause_on_job_id=None)
    w2._yield_state_path = state
    w2._restore_yield_state()
    assert w2.run_once() == "idle", "재시작 후 1분 내 claim = 양보 위반(V1 F2)"
    assert q2.jobs, "잡이 소비되면 안 됨"


def test_restart_preserves_pending_variants_and_does_not_revive_consumed_ones(tmp_path):
    """#114 회귀: deadline뿐 아니라 아직 enqueue하지 않은 변형도 재기동 뒤 살아야 한다."""
    state = tmp_path / "owner-yield-macmini.json"
    clock = FakeClock()
    wall = FakeClock(1_800_000_000.0)
    q = FakeQueue([_group_job(7), _job(8)])
    w = _worker(q, clock, pause_on_job_id=8,
                wall_clock=wall, yield_state_path=state)

    assert w.run_once() == "done"
    assert w.run_once() == "paused_for_human"
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert len(saved["variant_backlog"]) == 1

    restarted_clock = FakeClock(5000.0)
    restarted_queue = FakeQueue([])
    restarted = _worker(
        restarted_queue, restarted_clock, pause_on_job_id=None,
        wall_clock=wall, yield_state_path=state)
    assert len(restarted._variant_backlog) == 1, "재기동으로 변형 backlog 유실"
    assert restarted.run_once() == "idle"
    assert restarted_queue.claim_calls == 0, "남은 양보 시간 중 claim 금지"

    restarted_clock.now += 61
    wall.now += 61
    assert restarted.run_once() == "idle"
    assert len(restarted_queue.enqueued) == 1

    final = _worker(
        FakeQueue([]), FakeClock(9000.0), pause_on_job_id=None,
        wall_clock=wall, yield_state_path=state)
    assert final._variant_backlog == [], "이미 enqueue한 변형이 재기동 뒤 부활"


def test_corrupt_backlog_cannot_cancel_a_valid_restart_yield(tmp_path):
    state = tmp_path / "owner-yield-macmini.json"
    state.write_text(json.dumps({
        "machine": "macmini",
        "yield_until_epoch": 1_800_000_040.0,
        "variant_backlog": [{"skill": "url", "status": "queued"}],
    }), encoding="utf-8")
    clock = FakeClock(5000.0)
    wall = FakeClock(1_800_000_000.0)
    q = FakeQueue([_job(9)])
    worker = _worker(
        q, clock, pause_on_job_id=None,
        wall_clock=wall, yield_state_path=state)

    assert worker._variant_backlog == []
    assert worker._yield_remaining() > 30
    assert worker.run_once() == "idle"
    assert q.claim_calls == 0, "손상된 backlog가 남은 양보 시간까지 취소하면 안 됨"


def _valid_persisted_variant(keyword="보안"):
    from tools.multi_position_sourcing.session_batch import variant_job_payload
    payload = variant_job_payload(
        _job(7),
        {"channel": "saramin", "keyword": keyword, "filters": {}},
        group_id="infra-security",
    )
    assert payload is not None
    return payload


def test_restart_accepts_six_variants_but_rejects_seven_without_dropping_deadline(tmp_path):
    variants = [_valid_persisted_variant(f"보안-{index}") for index in range(7)]
    for count, expected in ((6, 6), (7, 0)):
        state = tmp_path / f"owner-yield-count-{count}.json"
        state.write_text(json.dumps({
            "schema_version": 2,
            "machine": "macmini",
            "yield_until_epoch": 1_800_000_040.0,
            "variant_backlog": variants[:count],
        }), encoding="utf-8")
        worker = _worker(
            FakeQueue([]), FakeClock(5000.0), pause_on_job_id=None,
            wall_clock=FakeClock(1_800_000_000.0), yield_state_path=state)
        assert len(worker._variant_backlog) == expected
        assert worker._yield_remaining() == 40


def test_restart_rejects_nonvariant_and_cross_machine_backlogs(tmp_path):
    from tools.multi_position_sourcing.job_queue import new_job_payload
    normal = new_job_payload(
        machine="macmini", skill="humansearch",
        position_url="https://app.clickup.com/t/TASK1",
        requested_by=f"{OWNER_ID}:owner", role="owner", params={})
    assert normal is not None
    cross_machine = {**_valid_persisted_variant(),
                     "machine": "winpc", "account_key": "portal:winpc"}

    for index, bad_payload in enumerate((normal, cross_machine)):
        state = tmp_path / f"owner-yield-bad-{index}.json"
        state.write_text(json.dumps({
            "schema_version": 2,
            "machine": "macmini",
            "yield_until_epoch": 1_800_000_040.0,
            "variant_backlog": [bad_payload],
        }), encoding="utf-8")
        q = FakeQueue([_job(9)])
        worker = _worker(
            q, FakeClock(5000.0), pause_on_job_id=None,
            wall_clock=FakeClock(1_800_000_000.0), yield_state_path=state)
        assert worker._variant_backlog == []
        assert worker._yield_remaining() == 40
        assert worker.run_once() == "idle" and q.claim_calls == 0


def test_legacy_or_unknown_schema_never_restores_a_backlog(tmp_path):
    valid = _valid_persisted_variant()
    for index, schema in enumerate((None, 99, 2.0, True)):
        state_data = {
            "machine": "macmini",
            "yield_until_epoch": 1_800_000_040.0,
            "variant_backlog": [valid],
        }
        if schema is not None:
            state_data["schema_version"] = schema
        state = tmp_path / f"owner-yield-schema-{index}.json"
        state.write_text(json.dumps(state_data), encoding="utf-8")
        worker = _worker(
            FakeQueue([]), FakeClock(5000.0), pause_on_job_id=None,
            wall_clock=FakeClock(1_800_000_000.0), yield_state_path=state)
        assert worker._yield_remaining() == 40
        assert worker._variant_backlog == []


def test_legacy_deadline_only_state_remains_compatible(tmp_path):
    state = tmp_path / "owner-yield-macmini.json"
    state.write_text(json.dumps({
        "yield_until_epoch": 1_800_000_040.0,
    }), encoding="utf-8")
    worker = _worker(
        FakeQueue([]), FakeClock(5000.0), pause_on_job_id=None,
        wall_clock=FakeClock(1_800_000_000.0), yield_state_path=state)
    assert worker._yield_remaining() > 30
    assert worker._variant_backlog == []


def test_owner_probe_gates_claim():
    """V1 F3: 사장님 활동 감지(주입 프로브) 중에는 claim/enqueue 를 하지 않는다(눈치)."""
    clock = FakeClock()
    q = FakeQueue([_job(8)])
    w = _worker(q, clock, pause_on_job_id=None)
    active = {"on": True}
    w.owner_probe = lambda: active["on"]
    assert w.run_once() == "idle"
    assert q.jobs, "사장님 활동 중 claim = R4 위반"
    active["on"] = False                         # 손 뗌(감지기가 idle≥60 판정)
    assert w.run_once() == "done"


def test_owner_probe_error_yields_failclosed():
    clock = FakeClock()
    q = FakeQueue([_job(8)])
    w = _worker(q, clock, pause_on_job_id=None)
    w.owner_probe = lambda: (_ for _ in ()).throw(RuntimeError("osascript 실패"))
    assert w.run_once() == "idle"
    assert q.jobs, "감지 실패 시 fail-closed 양보(사장님을 앞지르지 않는다)"


def test_chrome_frontmost_but_long_idle_resumes():
    """V1 F4: 크롬을 앞창에 둔 채 자리를 비워도(idle≥60) 재개 — 영구 양보 금지(INV9)."""
    from tools.multi_position_sourcing.owner_activity import compute_yield_decision
    assert compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=9999) is False
    assert compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=10) is True
    assert compute_yield_decision(frontmost_is_chrome=True, os_idle_seconds=None) is True
    assert compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=59) is True
    assert compute_yield_decision(frontmost_is_chrome=False, os_idle_seconds=61) is False


def test_paused_sleep_uses_remaining_window():
    """V1 F5: release 지연 등으로 시간이 흘렀으면 남은 창만큼만 잔다(고정 60 금지)."""
    clock = FakeClock()
    q = FakeQueue([_job(8)])
    w = _worker(q, clock, pause_on_job_id=8)
    assert w.run_once() == "paused_for_human"
    clock.now += 20
    assert w._post_status_delay("paused_for_human", 30) == 40
    assert w._post_status_delay("idle", 30) == 30


def test_fleet_status_exposes_linkedin_ready(monkeypatch):
    """V1 F6: 프롬프트가 안내하는 로그인 머신 정보를 fleet-status 가 실제로 노출해야 한다."""
    from tools.multi_position_sourcing.access import DiscordAuthorizedUser
    from tools.multi_position_sourcing.discord_routing import (
        DiscordAccessConfig, DiscordInvocation)
    from tools.multi_position_sourcing.fleet_dispatch import dispatch_fleet_command

    class Q:
        def recent(self, limit=10):
            return []

        def linkedin_ready_machines(self):
            return [{"machine": "winpc", "linkedin_rps_logged_in": True}]

    users = (DiscordAuthorizedUser(
        name="사장님", alias="owner", email="dev@valueconnect.kr", discord_id=OWNER_ID),)
    config = DiscordAccessConfig(
        allowed_channel_ids=("111",), allowed_role_ids=("444",), allow_dm=True)
    inv = DiscordInvocation(
        user_id=OWNER_ID, channel_id="dm", command_name="fleet-status", is_dm=True,
        invocation_kind="slash", guild_id="", member_role_ids=(), options={})
    out = dispatch_fleet_command(inv, authorized_users=users, config=config, queue=Q())
    assert "linkedin_ready" in out, "로그인 머신 정보 미노출(V1 F6 — 프롬프트와 실기능 불일치)"


def test_url_skill_doc_does_not_stop_on_plain_login_redirect():
    """V1 F7: 일반 로그인 리다이렉트 즉시 STOP 은 SOT 불변식 1(자동 로그인)과 충돌 — 삭제."""
    doc = (REPO / ".claude" / "skills" / "url" / "SKILL.md").read_text("utf-8")
    stop_lines = [l for l in doc.splitlines() if "즉시 STOP" in l]
    assert stop_lines, "STOP 규칙 자체는 유지(캡차·2FA·멀티세션락)"
    assert all("로그인 리다이렉트" not in l for l in stop_lines), \
        "일반 로그인 리다이렉트 STOP = 자동 로그인(SOT 불변식 1) 방해 코드"


def test_sot31_qa2_superseded_by_inv9():
    """V1 F8: 하위 SOT(31, 구30)에 600초 쿨다운이 '처치'로 남아 있으면 SOT 간 드리프트."""
    doc = (REPO / "docs" / "sot" / "31-fleet-run-reliability.md").read_text("utf-8")
    assert "PAUSE_COOLDOWN_SECONDS=600" not in doc, "구 600초 스펙 잔존(INV9 와 충돌)"
    assert "INV9" in doc, "INV9(60초) 로 대체됐음을 명시해야 함"


def test_yield_state_path_is_outside_repo():
    """V2 확정 버그: 상태 파일이 저장소 안(.fleet/)에 쓰이면 pause 마다 git 작업공간이
    더러워진다(Harness 청결 게이트 방해). 런타임 상태는 저장소 밖에 둔다."""
    from tools.multi_position_sourcing.fleet_worker import REPO as WREPO, default_yield_state_path
    p = default_yield_state_path("macmini").resolve()
    assert not str(p).startswith(str(WREPO.resolve()) + "/"), \
        "런타임 yield 상태 파일이 저장소 안에 있음 — 워크트리 오염(V2 지적)"
    assert "macmini" in p.name
