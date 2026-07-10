"""단계 A — 함대 작업 큐(job_queue) 기계 검증.

계약(docs/prompts/fleet-control-sequential-prompts-2026-07-11.md §프롬프트 A):
- jobs 행 페이로드는 fail-closed: machine/skill/role/position_url 무효 → None.
- 상태 전이는 화이트리스트만 허용(queued→running→paused_for_human→done|failed|cancelled).
- claim/release RPC 페이로드 빌더도 무효 입력 거부.
- 마이그레이션 SQL 이 실제로 존재하고 핵심 DDL(jobs, account_locks, claim_next_job)을 담는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.multi_position_sourcing.job_queue import (
    ALLOWED_TRANSITIONS,
    FLEET_MACHINES,
    FLEET_SKILLS,
    claim_next_job_payload,
    is_valid_transition,
    new_job_payload,
    release_job_payload,
)

REPO = Path(__file__).resolve().parents[1]


# ── 페이로드 fail-closed ──────────────────────────────────────────────

def _ok_kwargs(**over):
    kw = dict(
        machine="macmini",
        skill="humansearch",
        position_url="https://app.clickup.com/t/86ey4umzk",
        requested_by="814353841088757800:사장님",
        role="owner",
    )
    kw.update(over)
    return kw


def test_new_job_payload_happy_path():
    row = new_job_payload(**_ok_kwargs())
    assert row is not None
    assert row["machine"] == "macmini"
    assert row["skill"] == "humansearch"
    assert row["status"] == "queued"
    assert row["position_url"].startswith("https://")
    assert row["requested_by"]
    assert row["role"] == "owner"
    # account_key 기본값: 머신 바인딩(계정↔머신 1:1 정책)
    assert row["account_key"]


@pytest.mark.parametrize("machine", ["", "macstudio", "MACMINI", None, "winpc "])
def test_new_job_payload_rejects_bad_machine(machine):
    assert new_job_payload(**_ok_kwargs(machine=machine)) is None


@pytest.mark.parametrize("skill", ["", "outreach", "send", None, "search"])
def test_new_job_payload_rejects_bad_skill(skill):
    assert new_job_payload(**_ok_kwargs(skill=skill)) is None


@pytest.mark.parametrize("role", ["", "admin", None, "root"])
def test_new_job_payload_rejects_bad_role(role):
    assert new_job_payload(**_ok_kwargs(role=role)) is None


@pytest.mark.parametrize("url", ["", None, "notaurl", "javascript:alert(1)", "ftp://x"])
def test_new_job_payload_rejects_bad_url(url):
    assert new_job_payload(**_ok_kwargs(position_url=url)) is None


def test_new_job_payload_rejects_blank_requester():
    assert new_job_payload(**_ok_kwargs(requested_by="")) is None
    assert new_job_payload(**_ok_kwargs(requested_by="   ")) is None


def test_new_job_payload_params_must_be_dict():
    assert new_job_payload(**_ok_kwargs(), params=["not", "dict"]) is None  # type: ignore[arg-type]
    row = new_job_payload(**_ok_kwargs(), params={"tier": "정밀"})
    assert row is not None and row["params"] == {"tier": "정밀"}


def test_explicit_account_key_wins_over_default():
    row = new_job_payload(**_ok_kwargs(), account_key="linkedin:seat1")
    assert row is not None and row["account_key"] == "linkedin:seat1"


# ── 상태 전이 화이트리스트 ────────────────────────────────────────────

@pytest.mark.parametrize("old,new", [
    ("queued", "running"),
    ("queued", "cancelled"),
    ("running", "paused_for_human"),
    ("running", "done"),
    ("running", "failed"),
    ("paused_for_human", "queued"),   # /resume
    ("paused_for_human", "cancelled"),
])
def test_valid_transitions(old, new):
    assert is_valid_transition(old, new) is True


@pytest.mark.parametrize("old,new", [
    ("queued", "done"),               # 실행 없이 완료 금지
    ("queued", "paused_for_human"),
    ("done", "running"),              # 종결 상태 재가동 금지
    ("failed", "running"),
    ("cancelled", "queued"),
    ("running", "queued"),
    ("running", "running"),
    ("nope", "running"),
    ("queued", "nope"),
])
def test_invalid_transitions(old, new):
    assert is_valid_transition(old, new) is False


def test_transition_table_only_contains_known_statuses():
    known = {"queued", "running", "paused_for_human", "done", "failed", "cancelled"}
    for old, news in ALLOWED_TRANSITIONS.items():
        assert old in known
        assert set(news) <= known


# ── RPC 페이로드 빌더 ────────────────────────────────────────────────

def test_claim_payload_valid_machine_only():
    assert claim_next_job_payload("macbook") == {"p_machine": "macbook"}
    with pytest.raises(ValueError):
        claim_next_job_payload("laptop")
    with pytest.raises(ValueError):
        claim_next_job_payload("")


def test_release_payload_terminal_or_pause_only():
    p = release_job_payload(7, "done", result_summary="후보 12명 등록")
    assert p == {"p_job_id": 7, "p_status": "done",
                 "p_result_summary": "후보 12명 등록", "p_error": ""}
    p2 = release_job_payload(8, "paused_for_human", error="캡차 감지")
    assert p2["p_status"] == "paused_for_human"
    with pytest.raises(ValueError):
        release_job_payload(9, "queued")        # release 로 재큐잉 금지
    with pytest.raises(ValueError):
        release_job_payload(9, "running")
    with pytest.raises(ValueError):
        release_job_payload(0, "done")          # 잡 id 양수 강제
    with pytest.raises(ValueError):
        release_job_payload(-1, "failed")


# ── 발송 게이트: 큐 계층에 발송성 스킬이 존재할 수 없다(SOT28) ───────

def test_fleet_skills_contain_no_send_capability():
    assert set(FLEET_SKILLS) == {"humansearch", "aisearch", "url"}
    for banned in ("send", "outreach", "inmail", "mail"):
        assert all(banned not in s for s in FLEET_SKILLS)


def test_fleet_machines_fixed():
    assert set(FLEET_MACHINES) == {"macmini", "macbook", "winpc"}


# ── 마이그레이션 실체(배선) ──────────────────────────────────────────

def test_migration_file_contains_core_ddl():
    candidates = sorted((REPO / "supabase" / "migrations").glob("*fleet_jobs*.sql"))
    assert candidates, "fleet_jobs 마이그레이션 SQL 이 없습니다"
    sql = candidates[-1].read_text()
    for needle in (
        "create table if not exists public.jobs",
        "create table if not exists public.account_locks",
        "claim_next_job",
        "release_job",
        "for update skip locked",
        "enable row level security",
        "service_role",
    ):
        assert needle in sql.lower(), f"마이그레이션에 '{needle}' 누락"
