"""2026-07-31 전수 리뷰 — H1 SOT25 5필드 + 프로필 저장 증거 게이트 (U3), F12 (이름).

goal: docs/engineering/aisearch-review-fix-goal-2026-07-31.md
SOT: docs/sot/25-ai-search-execution-process.json
  - clickup_registration_contract.candidate_subtask_required_fields = 5필드
    (profile_url, score, why_fit, profile_summary, saved_profile_evidence)
  - clickup_registration_contract.profile_save_evidence_required = true

계약 재사용(중복 구현 금지): tools/multi_position_sourcing/humansearch_register.py
의 has_saved_profile_evidence()/_saved_profile_evidence_text() 와 **동형**이다 —
manifest + screenshot_sha256 결합 영수증만 인정하고, 없으면 "missing" 으로
표기하며, "missing"·빈값은 등록 거부(fail-closed).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.aisearch_evidence import make_evidence

from apps.aisearch.core import recorders
from apps.aisearch.core.recorders import (
    REQUIRED_FIELDS,
    Candidate,
    DualRecorder,
    saved_profile_evidence_text,
)

EVIDENCE = make_evidence(
    "https://www.linkedin.com/talent/profile/minhonggildong",
    position_id="빅밸류 세일즈 총괄",
    site="linkedin_rps",
)


@pytest.fixture(autouse=True)
def _structural_evidence_verifier(monkeypatch):
    """영수증 **실물** 무결성은 전용 테스트가 지킨다 — 여기서는 모양 검사로 대체.

    프로덕션 기본값이 정본 검증기(browser_evidence.complete_evidence_payload)라는
    사실은 tests/test_aisearch_v1_round3.py 가 따로 잠근다.
    """
    from tests.aisearch_evidence import use_structural_verifier

    use_structural_verifier(monkeypatch)


class FakeClickUp:
    def __init__(self):
        self.created_tasks: list = []
        self.created_subtasks: list = []

    def find_parent_task(self, list_id, position_name):
        return None

    def subtask_exists_with_profile_url(self, list_id, profile_url):
        return False

    def create_parent_task(self, list_id, position_name):
        self.created_tasks.append((list_id, position_name))
        return "parent-1"

    def create_candidate_subtask(self, list_id, parent_task_id, fields):
        self.created_subtasks.append(fields)
        return "sub-1"


class FakeDiscord:
    def __init__(self):
        self.messages: list = []

    def post_message(self, channel_id, content):
        self.messages.append({"channel_id": channel_id, "content": content})
        return "msg-1"


class FakeAdmin:
    def __init__(self):
        self.registered: list = []

    def register_candidate(self, payload):
        self.registered.append(payload)
        return {"ok": True, "candidate": {"id": "x"}, "deduped": False}


def _candidate(**over) -> Candidate:
    base = dict(
        profile_url="https://www.linkedin.com/talent/profile/minhonggildong",
        score=87,
        why_fit="B2B SaaS 세일즈 8년",
        profile_summary="현 A사 세일즈 리드",
        evidence=dict(EVIDENCE),
        name="홍길동",
    )
    base.update(over)
    return Candidate(**base)


def _live_recorder():
    cu, dc, am = FakeClickUp(), FakeDiscord(), FakeAdmin()
    return cu, dc, am, DualRecorder(
        clickup=cu, discord=dc, admin=am, live=True, owner_signoff=True
    )


# ── SOT25 원문 대조 ────────────────────────────────────────────────────────


def test_h1_required_fields_match_sot25_five_fields():
    sot = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/sot/25-ai-search-execution-process.json")
        .read_text(encoding="utf-8")
    )
    expected = sot["clickup_registration_contract"]["candidate_subtask_required_fields"]
    assert sorted(REQUIRED_FIELDS) == sorted(expected), (
        f"SOT25 필수 필드와 코드가 다르다: SOT={expected} / 코드={REQUIRED_FIELDS}"
    )
    assert "saved_profile_evidence" in REQUIRED_FIELDS
    assert sot["clickup_registration_contract"]["profile_save_evidence_required"] is True


# ── H1 — 증거 없으면 subtask 생성 금지(fail-closed) ────────────────────────


def test_h1_missing_evidence_rejects_before_any_external_write():
    cu, dc, am, rec = _live_recorder()

    result = rec.record(
        position_name="빅밸류 세일즈 총괄",
        candidate=_candidate(evidence=None),
        channel="linkedin_rps",
    )

    assert result.status == "failed"
    assert "saved_profile_evidence" in (result.error or "")
    assert cu.created_subtasks == [], "증거 없이 subtask 가 생성됐다(SOT25 위반)"
    assert cu.created_tasks == []
    assert am.registered == []


def test_h1_literal_missing_marker_is_rejected():
    cu, dc, am, rec = _live_recorder()

    result = rec.record(
        position_name="빅밸류 세일즈 총괄",
        candidate=_candidate(evidence="missing"),
        channel="linkedin_rps",
    )

    assert result.status == "failed"
    assert cu.created_subtasks == []
    assert am.registered == []


def test_h1_evidence_present_creates_subtask_with_five_fields():
    cu, dc, am, rec = _live_recorder()

    result = rec.record(
        position_name="빅밸류 세일즈 총괄",
        candidate=_candidate(),
        channel="linkedin_rps",
    )

    assert result.status == "recorded"
    assert len(cu.created_subtasks) == 1
    fields = cu.created_subtasks[0]
    for name in REQUIRED_FIELDS:
        assert name in fields, f"subtask 필드 누락: {name}"
    assert fields["saved_profile_evidence"].startswith("manifest: ")
    assert "screenshot_sha256" in fields["saved_profile_evidence"]


def test_h1_evidence_text_helper_matches_humansearch_contract():
    # manifest + digest 둘 다 있어야 영수증 — 하나라도 없으면 "missing".
    assert saved_profile_evidence_text(EVIDENCE) == (
        f"manifest: {EVIDENCE['manifest_path']} | screenshot_sha256: {EVIDENCE['screenshot_sha256']}"
    )
    assert saved_profile_evidence_text({"manifest_path": "/x"}) == "missing"
    assert saved_profile_evidence_text({"screenshot_sha256": "a" * 64}) == "missing"
    assert saved_profile_evidence_text(None) == "missing"
    assert saved_profile_evidence_text({}) == "missing"


def test_h1_dry_run_also_refuses_without_evidence():
    """dry-run 계획에도 증거 없는 후보는 담기지 않는다(계획이 곧 라이브 모양)."""
    cu, dc = FakeClickUp(), FakeDiscord()
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdmin())

    result = rec.record(
        position_name="빅밸류 세일즈 총괄",
        candidate=_candidate(evidence=None),
        channel="linkedin_rps",
    )

    assert result.status == "failed"
    kinds = [a["kind"] for a in result.planned_actions]
    assert "clickup_create_candidate_subtask" not in kinds
    assert "admin_register_candidate" not in kinds


# ── F12 — 이름 미확보 시에도 후보끼리 병합되지 않는다 ──────────────────────


def test_f12_unknown_name_is_unique_per_candidate():
    cu, dc, am, rec = _live_recorder()

    for url in ("https://www.linkedin.com/talent/profile/linkedincomina", "https://www.linkedin.com/talent/profile/linkedincominb"):
        rec.record(
            position_name="P",
            candidate=_candidate(
                name="",
                profile_url=url,
                evidence=make_evidence(url, position_id="P", site="linkedin_rps"),
            ),
            channel="linkedin_rps",
        )

    names = [p["name"] for p in am.registered]
    assert len(names) == 2
    assert names[0] != names[1], (
        "이름 미확보 후보가 전부 같은 이름으로 나가면 v4 dedup 이 한 건으로 병합한다"
    )
    for name in names:
        assert name.startswith("이름 미확인")
        assert "http" not in name  # URL 을 이름인 척 보내지 않는다


def test_f12_unknown_name_is_deterministic_for_same_profile():
    cu, dc, am, rec = _live_recorder()
    url = "https://www.linkedin.com/talent/profile/kedincominsame"

    cand = _candidate(
        name="",
        profile_url=url,
        evidence=make_evidence(url, position_id="P", site="linkedin_rps"),
    )
    rec.record(position_name="P", candidate=cand, channel="linkedin_rps")
    rec2_cu, rec2_dc, am2, rec2 = _live_recorder()
    rec2.record(position_name="P", candidate=cand, channel="linkedin_rps")

    assert am.registered[0]["name"] == am2.registered[0]["name"]


def test_module_exposes_evidence_helpers():
    assert hasattr(recorders, "saved_profile_evidence_text")
    assert hasattr(recorders, "EVIDENCE_MISSING")
