"""V1 독립 적대검증 2라운드(2026-07-31) — FAIL 판정 11건 대응.

goal: docs/engineering/aisearch-review-fix-goal-2026-07-31.md `## 적대 검증 로그`

V1(codex, fresh·read-only)이 실제 공격 입력으로 재현한 결함들:
1. H1  증거 게이트가 아무 문자열("x")이나 통과시킨다.
2. H2  후보 고유 정보인 회사·직함(draft_inputs.candidate_*)이 제외어 스캔에서 빠졌다.
3. F6  자동 재개 기준이 30초라 SOT(60초)와 어긋난다.
4. F7  재개 시 같은 후보가 리포트·초안에 중복 집계된다.
6. F8  heartbeat/release 가 **자기 락인지 확인하지 않아** 남의 락을 덮어쓰거나 지운다.
7. M2  협조적 중단 확인이 목록 요청에만 있어, 실패 후에도 상세 조회·등록이 계속된다.
8. H5  저장소 인스턴스/프로세스가 둘이면 마지막 쓰기가 앞 행을 지운다.
9. admin 클라이언트 생성자가 키의 여백을 먼저 잘라내 "무여백 거부"를 우회시킨다.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import threading
from pathlib import Path

import pytest

from tests.aisearch_evidence import make_evidence

from apps.aisearch.core import recorders as rec_mod
from apps.aisearch.core.admin_api_client import AdminApiConfigError, HttpAdminApiClient
from apps.aisearch.core.orchestrator import _find_exclusion_match
from apps.aisearch.core.pagination_store import TABLE_NAME, make_row_id
from apps.aisearch.core.recorders import Candidate, DualRecorder
from apps.aisearch.core.session_lock import (
    LinkedInSessionLock,
    LinkedInSessionLockError,
)
from apps.aisearch.run import JsonlPageStore

POSITION = "빅밸류 세일즈 총괄"
PROFILE_URL = "https://www.linkedin.com/in/hong-gildong/"
CHANNEL = "linkedin_rps"

GOOD_EVIDENCE = make_evidence(PROFILE_URL, position_id=POSITION, site=CHANNEL)


class FakeClickUp:
    def __init__(self):
        self.created_tasks: list = []
        self.created_subtasks: list = []

    def find_parent_task(self, *a):
        return None

    def subtask_exists_with_profile_url(self, *a):
        return False

    def create_parent_task(self, *a):
        self.created_tasks.append(a)
        return "parent-1"

    def create_candidate_subtask(self, list_id, parent, fields):
        self.created_subtasks.append(fields)
        return "sub-1"


class FakeDiscord:
    def __init__(self):
        self.messages: list = []

    def post_message(self, channel_id, content):
        self.messages.append(content)
        return "m1"


class FakeAdmin:
    def __init__(self):
        self.registered: list = []

    def register_candidate(self, payload):
        self.registered.append(payload)
        return {"ok": True, "candidate": {"id": "x"}, "deduped": False}


def _live():
    cu, dc, am = FakeClickUp(), FakeDiscord(), FakeAdmin()
    return cu, dc, am, DualRecorder(
        clickup=cu, discord=dc, admin=am, live=True, owner_signoff=True
    )


def _cand(**over) -> Candidate:
    base = dict(
        profile_url=PROFILE_URL,
        score=87,
        why_fit="세일즈 8년",
        profile_summary="현 A사 리드",
        evidence=dict(GOOD_EVIDENCE),
        name="홍길동",
    )
    base.update(over)
    return Candidate(**base)


# ── 1. H1 — 증거는 '있는 척'이 아니라 실제 영수증이어야 한다 ────────────────


@pytest.mark.parametrize(
    "bad_evidence",
    [
        "x",  # 아무 문자열
        "manifest: | screenshot_sha256:",  # 모양만 흉내
        {"manifest_path": "/m.json"},  # 해시 없음
        {"screenshot_sha256": "a" * 64},  # manifest 없음
        {**GOOD_EVIDENCE, "screenshot_sha256": "짧은해시"},  # 해시 형식 위반
        {**GOOD_EVIDENCE, "profile_url": "https://other.example/p/9"},  # 다른 후보 증거
        {**GOOD_EVIDENCE, "position_id": "다른 포지션"},  # 다른 포지션 증거
        {**GOOD_EVIDENCE, "task": "humansearch"},  # 다른 작업의 증거
        {**GOOD_EVIDENCE, "mode": "list"},  # 목록 캡처(프로필 저장 아님)
        None,
    ],
)
def test_v1_1_fabricated_or_mismatched_evidence_is_rejected(bad_evidence):
    cu, dc, am, rec = _live()

    result = rec.record(
        position_name=POSITION, candidate=_cand(evidence=bad_evidence), channel=CHANNEL
    )

    assert result.status == "failed", f"가짜 증거가 통과했다: {bad_evidence!r}"
    assert cu.created_subtasks == []
    assert am.registered == []


def test_v1_1_real_evidence_still_registers():
    cu, dc, am, rec = _live()
    result = rec.record(position_name=POSITION, candidate=_cand(), channel=CHANNEL)
    assert result.status == "recorded"
    assert cu.created_subtasks[0]["saved_profile_evidence"].startswith("manifest: ")


def test_v1_1_evidence_from_another_channel_is_rejected():
    cu, dc, am, rec = _live()
    result = rec.record(
        position_name=POSITION,
        candidate=_cand(evidence={**GOOD_EVIDENCE, "site": "saramin"}),
        channel=CHANNEL,
    )
    assert result.status == "failed"


# ── 2. H2 — 후보 고유 정보(회사·직함)도 제외어 스캔 대상 ───────────────────


def _payload(headline="기구설계 파트리더", company="현대로템"):
    return {
        "score_payload": {"score": 88, "dimensions": {}},
        "record": {"profile_url": PROFILE_URL, "why_fit": "적합", "profile_summary": "요약"},
        "draft_inputs": {
            "candidate_name": "김민수",
            "candidate_company": company,
            "candidate_headline": headline,
            "jd_summary": "이 포지션은 인턴 채용이 아닙니다",  # JD 공통 — 스캔 제외
            "briefing_elements": ["매출 300억", "인턴 프로그램 운영"],  # JD 공통
            "company_name": "한국프리시전웍스",
            "position_title": "Tech PM",
            "channel": CHANNEL,
        },
    }


def test_v1_2_candidate_headline_is_scanned():
    matched = _find_exclusion_match(_payload(headline="Freelance Product Manager"), ["freelance"])
    assert matched is not None, "후보 직함의 제외어를 놓쳤다"
    assert "candidate_headline" in matched[1]


def test_v1_2_candidate_company_is_scanned():
    matched = _find_exclusion_match(_payload(company="프리랜서 스튜디오"), ["프리랜서"])
    assert matched is not None, "후보 소속의 제외어를 놓쳤다"
    assert "candidate_company" in matched[1]


def test_v1_2_jd_common_text_still_excluded_from_scan():
    assert _find_exclusion_match(_payload(), ["인턴"]) is None, (
        "JD 공통 문구(jd_summary·briefing_elements)가 다시 스캔에 들어왔다"
    )


# ── 3. F6 — 자동 재개 기준이 SOT(60초)와 같아야 한다 ───────────────────────


def test_v1_3_resume_delay_matches_sot_60_seconds():
    from apps.aisearch.core.intervention import RESUME_DELAY_SECONDS

    assert RESUME_DELAY_SECONDS == 60.0, (
        f"SOT 불변식 2 는 60초인데 구현은 {RESUME_DELAY_SECONDS}초다"
    )


def test_v1_3_monitor_does_not_resume_before_60_seconds():
    from apps.aisearch.core.intervention import InterventionMonitor, MonitorState

    now = [0.0]

    class _N:
        def notify(self, m):
            pass

    monitor = InterventionMonitor(lambda: now[0], _N())
    monitor.on_human_input()
    now[0] = 59.9
    assert monitor.poll() is MonitorState.PAUSED_HUMAN
    now[0] = 60.0
    assert monitor.poll() is MonitorState.RUNNING


# ── 4. F7 — 재개가 같은 후보를 두 번 세지 않는다 ───────────────────────────


def test_v1_4_resume_does_not_double_count_same_candidate():
    from apps.aisearch.core.orchestrator import run_search_pipeline
    from tests.test_aisearch_orchestrator import PAYLOAD_60, Harness, _candidate, _jd

    h = Harness(pages=1)
    jd = _jd()
    same = _candidate(PAYLOAD_60, "https://saramin.example/p/60")
    # 같은 후보가 한 채널 결과에 두 번 들어온 경우(추출기 중복)
    for channel in ("linkedin_rps", "saramin", "jobkorea"):
        h.candidates[channel] = [dict(same), dict(same)]

    first = run_search_pipeline(jd, h.deps())
    resumed = run_search_pipeline(jd, h.deps(), previous=first)

    assert len(resumed.registered) == len(resumed.record_states), (
        f"중복 집계: registered={len(resumed.registered)} "
        f"record_states={len(resumed.record_states)}"
    )
    assert len(resumed.drafts) == len(resumed.record_states), (
        f"초안 중복: drafts={len(resumed.drafts)}"
    )


# ── 6. F8 — 락 소유권 확인(남의 락을 덮어쓰거나 지우지 않는다) ─────────────


def test_v1_6_heartbeat_does_not_overwrite_another_owners_lock(tmp_path):
    lock_dir = tmp_path / "linkedin_rps"
    now = [1000.0]
    a = LinkedInSessionLock(
        lock_dir=lock_dir, owner="A", stale_seconds=10.0, clock=lambda: now[0]
    )
    a.acquire()

    now[0] += 100.0  # A 가 멎어 stale 이 됨
    b = LinkedInSessionLock(
        lock_dir=lock_dir, owner="B", stale_seconds=10.0, clock=lambda: now[0]
    )
    b.acquire()  # 정당한 회수

    a.heartbeat()  # 되살아난 A 가 심장박동을 시도한다

    meta = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
    assert meta["owner"] == "B", "죽었던 A 가 B 의 락 메타를 덮어썼다"


def test_v1_6_release_does_not_delete_another_owners_lock(tmp_path):
    lock_dir = tmp_path / "linkedin_rps"
    now = [1000.0]
    a = LinkedInSessionLock(
        lock_dir=lock_dir, owner="A", stale_seconds=10.0, clock=lambda: now[0]
    )
    a.acquire()
    now[0] += 100.0
    b = LinkedInSessionLock(
        lock_dir=lock_dir, owner="B", stale_seconds=10.0, clock=lambda: now[0]
    )
    b.acquire()

    a.release()  # A 가 뒤늦게 해제를 시도한다

    assert lock_dir.exists(), "A 가 B 의 락을 지워버렸다"
    meta = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
    assert meta["owner"] == "B"
    b.release()


# ── 7. M2 — 중단 신호는 상세 조회·등록에도 걸린다 ──────────────────────────


def test_v1_7_stop_signal_halts_detail_and_registration_too():
    from apps.aisearch.core.orchestrator import run_search_pipeline
    from tests.test_aisearch_orchestrator import PAYLOAD_60, Harness, _candidate, _jd

    h = Harness(pages=1, live_recorder=True)
    jd = _jd()
    for channel in ("linkedin_rps", "saramin", "jobkorea"):
        h.candidates[channel] = [
            _candidate(PAYLOAD_60, f"https://{channel}.example/p/60")
        ]

    failed = threading.Event()

    def side_effect(channel: str, page: int) -> None:
        if channel == "saramin":
            failed.set()
            raise RuntimeError("saramin 폭발")
        failed.wait(timeout=5)  # 다른 채널은 실패 이후에 진행한다

    h.list_side_effect = side_effect

    report = run_search_pipeline(jd, h.deps())

    assert report.status == "aborted"
    assert h.admin.registered == [], (
        f"중단 신호 이후에도 admin 등록이 나갔다: {len(h.admin.registered)}건"
    )


# ── 8. H5 — 저장소가 둘이어도 행이 사라지지 않는다 ─────────────────────────


def _row(page_type: str, url: str) -> dict:
    return {
        "id": make_row_id(
            channel="saramin", page_type=page_type, url=url, position_ref="P1"
        ),
        "channel": "saramin",
        "page_type": page_type,
        "url": url,
        "position_ref": "P1",
        "raw_html_or_text": "<html/>",
        "machine": "m",
        "captured_at": "2026-07-31T00:00:00+00:00",
    }


def test_v1_8_two_store_instances_do_not_lose_rows(tmp_path):
    """두 저장소 객체(=두 실행)가 같은 파일에 써도 앞 행이 사라지면 안 된다."""
    path = tmp_path / "pages.jsonl"
    a = JsonlPageStore(path)
    b = JsonlPageStore(path)  # 같은 파일을 보는 두 번째 저장자

    a.upsert(TABLE_NAME, _row("list", "https://p/1"))
    b.upsert(TABLE_NAME, _row("list", "https://p/2"))
    a.upsert(TABLE_NAME, _row("detail", "https://p/3"))

    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    urls = {r["url"] for r in rows}
    assert urls == {"https://p/1", "https://p/2", "https://p/3"}, (
        f"동시 저장자 때문에 행이 사라졌다: {sorted(urls)}"
    )


def test_v1_8_temp_file_name_is_unique_per_writer(tmp_path):
    path = tmp_path / "pages.jsonl"
    a = JsonlPageStore(path)
    b = JsonlPageStore(path)
    assert a._tmp_path() != b._tmp_path(), "임시파일 이름이 같아 서로를 덮어쓴다"


# ── 9. admin — 여백 붙은 키는 생성자에서도 거부 ────────────────────────────


def test_v1_9_padded_internal_key_is_rejected_not_silently_trimmed():
    with pytest.raises(AdminApiConfigError):
        HttpAdminApiClient(base_url="https://admin.valuehire.cc", internal_key=" " + "k" * 32)


def test_v1_9_padded_env_key_is_also_rejected(monkeypatch):
    monkeypatch.setenv("ADMIN_API_BASE_URL", "https://admin.valuehire.cc")
    monkeypatch.setenv("ADMIN_API_INTERNAL_KEY", "k" * 32 + " ")
    with pytest.raises(AdminApiConfigError):
        HttpAdminApiClient()


def test_v1_9_base_url_whitespace_is_still_forgiven():
    client = HttpAdminApiClient(
        base_url="  https://admin.valuehire.cc/  ", internal_key="k" * 32
    )
    assert client.base_url == "https://admin.valuehire.cc"
