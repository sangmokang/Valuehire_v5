"""AC-5 — ClickUp + Discord 이중 기록 (goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §4 AC-5, §5).

계약(SOT25 clickup_registration_contract 재사용):
- 60점 이상 후보 확정 시 ClickUp 리스트 901818680208 에 포지션 부모 Task + 후보 Subtask 등록.
  등록 전 같은 profile_url 중복확인 — 존재하면 등록 안 함(fail-closed skip).
  후보 Subtask 필수 4필드: profile_url, score, why_fit, profile_summary.
- Discord 결과 채널 1470955309089554554 에 {매칭점수, 프로필URL, 적합/부적합 사유,
  매칭 근거, 학력, 경력 브리핑} 게시.
- 진행상황/에러는 Discord 멤버 채널 1512503041448743092 에 별도 게시.
- L3 외부 쓰기: 라이브 발신은 코드 기본값 OFF — 주입식 클라이언트 + dry-run 기본.
  라이브는 live=True + owner_signoff=True 둘 다 있어야 하며 하나라도 없으면 fail-closed.
"""

from __future__ import annotations

import pytest

from apps.aisearch.core.recorders import (
    CLICKUP_LIST_ID,
    DISCORD_MEMBER_CHANNEL_ID,
    DISCORD_RESULT_CHANNEL_ID,
    Candidate,
    DualRecorder,
    LiveGateError,
)


class FakeClickUpClient:
    """주입식 페이크 — 실제 HTTP 호출 없음. 호출 payload 만 기록."""

    def __init__(self, existing_profile_urls=(), existing_parent_task_id=None):
        self.existing_profile_urls = set(existing_profile_urls)
        self.existing_parent_task_id = existing_parent_task_id
        self.created_tasks = []
        self.created_subtasks = []
        self.duplicate_checks = []

    def find_parent_task(self, list_id, position_name):
        return self.existing_parent_task_id

    def subtask_exists_with_profile_url(self, list_id, profile_url):
        self.duplicate_checks.append((list_id, profile_url))
        return profile_url in self.existing_profile_urls

    def create_parent_task(self, list_id, position_name):
        self.created_tasks.append({"list_id": list_id, "name": position_name})
        return f"task-{len(self.created_tasks)}"

    def create_candidate_subtask(self, list_id, parent_task_id, fields):
        self.created_subtasks.append(
            {"list_id": list_id, "parent_task_id": parent_task_id, "fields": dict(fields)}
        )
        return f"subtask-{len(self.created_subtasks)}"


class FakeDiscordClient:
    def __init__(self):
        self.messages = []

    def post_message(self, channel_id, content):
        self.messages.append({"channel_id": channel_id, "content": content})
        return f"msg-{len(self.messages)}"


def make_candidate(**over):
    base = dict(
        profile_url="https://www.linkedin.com/in/hong-gildong/",
        score=87,
        why_fit="B2B SaaS 세일즈 8년, 좋은학교, 직무 직결",
        profile_summary="현 A사 세일즈 리드, SaaS 신규영업 총괄",
        match_basis="D1 학력 상위권 + D3 직무 직결 + D5 이직 안정성",
        education="한국대 경영학 학사",
        career_brief="A사 5년(세일즈 리드), B사 3년(AE)",
    )
    base.update(over)
    return Candidate(**base)


def test_constants_match_sot():
    assert CLICKUP_LIST_ID == "901818680208"
    assert DISCORD_RESULT_CHANNEL_ID == "1470955309089554554"
    assert DISCORD_MEMBER_CHANNEL_ID == "1512503041448743092"


def test_dry_run_is_default_and_never_writes():
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc)
    assert rec.live is False  # 코드 기본값 OFF

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate())

    # 외부 쓰기 0건 — dry-run 은 계획만 만든다
    assert cu.created_tasks == []
    assert cu.created_subtasks == []
    assert dc.messages == []
    assert result.dry_run is True
    # 중복확인(read)은 dry-run 에서도 수행된다 (SOT25: 등록 전 필수 회수 단계)
    assert cu.duplicate_checks == [(CLICKUP_LIST_ID, make_candidate().profile_url)]
    # 계획된 payload 는 라이브와 동일 모양이어야 검증 가능
    kinds = [a["kind"] for a in result.planned_actions]
    assert "clickup_create_parent_task" in kinds
    assert "clickup_create_candidate_subtask" in kinds
    assert "discord_result_post" in kinds
    assert "discord_member_post" in kinds


def test_live_without_owner_signoff_fails_closed():
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    with pytest.raises(LiveGateError):
        DualRecorder(clickup=cu, discord=dc, live=True)  # signoff 없이 라이브 금지
    with pytest.raises(LiveGateError):
        DualRecorder(clickup=cu, discord=dc, live=True, owner_signoff=False)


def test_live_records_to_clickup_and_both_discord_channels():
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, live=True, owner_signoff=True)
    cand = make_candidate()

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=cand)

    assert result.dry_run is False
    # 부모 Task + 후보 Subtask 가 SOT 리스트에 생성
    assert cu.created_tasks == [{"list_id": CLICKUP_LIST_ID, "name": "빅밸류 세일즈 총괄"}]
    assert len(cu.created_subtasks) == 1
    sub = cu.created_subtasks[0]
    assert sub["list_id"] == CLICKUP_LIST_ID
    assert sub["parent_task_id"] == "task-1"
    # 필수 4필드 (SOT25 candidate_subtask_required_fields 핵심)
    for field in ("profile_url", "score", "why_fit", "profile_summary"):
        assert field in sub["fields"], field
    assert sub["fields"]["profile_url"] == cand.profile_url
    assert sub["fields"]["score"] == 87

    # Discord 결과 채널 + 멤버 채널 각 1건
    by_channel = {m["channel_id"]: m["content"] for m in dc.messages}
    assert set(by_channel) == {DISCORD_RESULT_CHANNEL_ID, DISCORD_MEMBER_CHANNEL_ID}
    body = by_channel[DISCORD_RESULT_CHANNEL_ID]
    # {매칭점수, 프로필URL, 적합/부적합 사유, 매칭 근거, 학력, 경력 브리핑} 전부 포함
    assert "87" in body
    assert cand.profile_url in body
    assert cand.why_fit in body
    assert cand.match_basis in body
    assert cand.education in body
    assert cand.career_brief in body


def test_existing_parent_task_is_reused_not_duplicated():
    cu = FakeClickUpClient(existing_parent_task_id="task-existing")
    dc = FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, live=True, owner_signoff=True)

    rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate())

    assert cu.created_tasks == []  # 부모 중복 생성 금지
    assert cu.created_subtasks[0]["parent_task_id"] == "task-existing"


def test_duplicate_profile_url_skips_registration():
    url = "https://www.linkedin.com/in/hong-gildong/"
    cu = FakeClickUpClient(existing_profile_urls=[url])
    dc = FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, live=True, owner_signoff=True)

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate(profile_url=url))

    assert result.duplicate_skipped is True
    assert cu.created_tasks == []
    assert cu.created_subtasks == []
    # 결과 채널 게시 없음, 멤버 채널에 중복 skip 요약만
    channels = [m["channel_id"] for m in dc.messages]
    assert DISCORD_RESULT_CHANNEL_ID not in channels
    assert channels == [DISCORD_MEMBER_CHANNEL_ID]
    assert "중복" in dc.messages[0]["content"]


def test_below_threshold_records_nothing():
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, live=True, owner_signoff=True)

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate(score=59))

    assert result.recorded is False
    assert cu.duplicate_checks == []  # 확정 아님 — 아무 것도 안 함
    assert cu.created_subtasks == []
    assert dc.messages == []


def test_missing_required_field_fails_closed_and_reports_error_to_member_channel():
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, live=True, owner_signoff=True)

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate(why_fit=""))

    assert result.recorded is False
    assert result.error is not None and "why_fit" in result.error
    assert cu.created_tasks == []
    assert cu.created_subtasks == []
    # 에러는 멤버 채널에만 게시
    channels = [m["channel_id"] for m in dc.messages]
    assert channels == [DISCORD_MEMBER_CHANNEL_ID]
    assert "why_fit" in dc.messages[0]["content"]
