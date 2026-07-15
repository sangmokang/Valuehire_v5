"""사장님 양보 3분 자동 재개(SOT29 INV9) + LinkedIn 로그인 머신 탐색 prompting — 이슈 #107.

사장님 지시(2026-07-15): "내가 쓸 동안은 멈췄다가 3분 뒤까지 이상이 없으면 계속 시작해."
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


# ── 인수 1: 대기 시간 = 3분(180초), 10분(600) 잔존 0 ────────────────

def test_pause_resume_is_three_minutes():
    assert OWNER_YIELD_RESUME_SECONDS == 180, "SOT29 INV9 — 3분 뒤 자동 재개"
    assert PAUSE_COOLDOWN_SECONDS == OWNER_YIELD_RESUME_SECONDS, "별칭 드리프트 금지(단일 출처)"
    assert sleep_seconds_after("paused_for_human", 30) == 180


def test_no_600_cooldown_left_in_worker_source():
    src = (REPO / "tools" / "multi_position_sourcing" / "fleet_worker.py").read_text("utf-8")
    assert "PAUSE_COOLDOWN_SECONDS = 600" not in src, "사장님 원칙(3분)을 방해하는 10분 쿨다운 잔존"


# ── 인수 2: paused 후 backlog 미폐기 → 3분 양보 → 자동 재개 ─────────

class FakeQueue:
    def __init__(self, jobs):
        self.jobs = list(jobs)
        self.released = []
        self.enqueued = []

    def claim_next(self, machine):
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


def _worker(queue, clock, pause_on_job_id=None):
    def runner(prompt, timeout):
        if pause_on_job_id is not None and f"잡 #{pause_on_job_id}" in prompt:
            return ("PAUSED_FOR_HUMAN: 캡차", 0)
        return ("후보 3명 저장 완료", 0)

    return FleetWorker(
        machine="macmini", queue=queue, runner=runner,
        notifier=lambda job, text: None, clock=clock)


def test_paused_suspends_backlog_then_resumes_after_3min():
    """사장님 스펙(#107): paused 는 '3분 양보'지 '영구 폐기'가 아니다.

    기존 #104 의 영구 폐기 테스트(test_paused_for_human_clears_backlog_no_night_reentry)를
    사장님 지시로 대체한다.
    """
    clock = FakeClock()
    q = FakeQueue([_group_job(7), _job(8)])
    w = _worker(q, clock, pause_on_job_id=8)
    assert w.run_once() == "done"              # 잡7 → 변형 backlog 적재
    assert w.run_once() == "paused_for_human"  # 잡8 캡차 → 3분 양보 시작(폐기 아님)
    # 3분 안: 사장님이 처리 중일 수 있음 — idle 이어도 enqueue 금지(눈치)
    clock.now += 179
    assert w.run_once() == "idle"
    assert q.enqueued == [], "3분 전 자동 enqueue = 양보 위반"
    # 3분 경과 + 이상 없음: 자동 재개(심야 지속) — 영구 중단 금지
    clock.now += 2
    assert w.run_once() == "idle"
    assert len(q.enqueued) == 1, "3분 뒤 자동 재개 미구현 — 영구 중단은 SOT29 INV9 위반"
    assert q.enqueued[0]["params"]["variant"]["keyword"] == "변형키워드A"


def test_repeated_pause_extends_yield_window():
    """pause 가 또 오면 그 시점부터 다시 3분 — '이상이 없으면'의 코드 표현."""
    clock = FakeClock()
    q = FakeQueue([_group_job(7), _job(8), _job(9)])
    w = _worker(q, clock, pause_on_job_id=None)
    w.runner = lambda prompt, timeout: (
        ("후보 3명 저장 완료", 0) if "잡 #7" in prompt else ("PAUSED_FOR_HUMAN: 캡차", 0))
    assert w.run_once() == "done"
    assert w.run_once() == "paused_for_human"   # t=0: 양보 시작
    clock.now += 100
    assert w.run_once() == "paused_for_human"   # t=100: 또 이상 → 창 연장
    clock.now += 100                            # t=200 (2번째 pause 후 100초)
    assert w.run_once() == "idle"
    assert q.enqueued == [], "직전 이상 후 3분이 안 지났는데 재개 — 창 연장 미구현"
    clock.now += 81                             # 2번째 pause 후 181초
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
    inv = data["invariants"].get("INV9_owner_yield_3min", "")
    assert "180" in inv and "재개" in inv, "SOT29 INV9(3분 자동 재개) 미명문화"
    md = (REPO / "docs" / "sot" / "29-fleet-control.md").read_text("utf-8")
    assert "3분" in md and "자동 재개" in md
    claude_md = (REPO / "CLAUDE.md").read_text("utf-8")
    assert "180초" in claude_md or "3분" in claude_md, "최상위 SOT(CLAUDE.md)에 수치 미반영"
