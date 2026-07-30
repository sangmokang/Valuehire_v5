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


class FakeAdminApiClient:
    """AC-6 주입식 페이크 — 실제 HTTP 없음. register_candidate 호출 payload 만 기록."""

    def __init__(self):
        self.registered = []

    def register_candidate(self, payload):
        self.registered.append(dict(payload))
        return {"ok": True, "candidate": {"id": f"admin-{len(self.registered)}"}, "deduped": False}


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
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)
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
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)

    rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate())

    assert cu.created_tasks == []  # 부모 중복 생성 금지
    assert cu.created_subtasks[0]["parent_task_id"] == "task-existing"


def test_duplicate_profile_url_skips_registration():
    url = "https://www.linkedin.com/in/hong-gildong/"
    cu = FakeClickUpClient(existing_profile_urls=[url])
    dc = FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)

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
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate(score=59))

    assert result.recorded is False
    assert cu.duplicate_checks == []  # 확정 아님 — 아무 것도 안 함
    assert cu.created_subtasks == []
    assert dc.messages == []


# ── V1 결함 수정 계약 (RED 재현) ─────────────────────────────────────────────
# 결함1: dry-run 이 recorded=True 로 실제 기록처럼 표시됨 → status 분리
# 결함2: ClickUp 성공 후 Discord 실패 → 재시도 시 중복 판정으로 Discord 영구 누락
# 결함3: 중복확인→생성 비원자 → 결정론적 외부 멱등키(profile_url 기반) 계약
# 결함4: 점수 정수·0~100 범위 검증(101 거부)
# 결함5: dry-run 에서 부모 Task ID None 인 subtask 계획 → placeholder 참조


class FailFirstDiscordClient:
    """첫 post_message 만 실패하고 이후엔 성공 — 부분 실패 재현용."""

    def __init__(self):
        self.messages = []
        self.calls = 0

    def post_message(self, channel_id, content):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("discord down")
        self.messages.append({"channel_id": channel_id, "content": content})
        return f"msg-{len(self.messages)}"


def test_defect1_dry_run_status_is_dry_run_never_recorded():
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc)

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate())

    # dry-run 은 절대 recorded 로 표시되면 안 된다
    assert result.status == "dry_run"
    assert result.recorded is False


def test_defect1_live_success_status_is_recorded():
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate())

    assert result.status == "recorded"
    assert result.recorded is True
    assert result.pending_steps == []


def test_defect2_partial_failure_reports_partial_and_pending_steps():
    cu, dc = FakeClickUpClient(), FailFirstDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate())

    # ClickUp 은 성공, Discord 결과 게시부터 실패 → partial + 미완 단계 목록
    assert result.status == "partial"
    assert result.recorded is False
    assert result.pending_steps == ["discord_result", "discord_member"]
    assert len(cu.created_subtasks) == 1
    assert dc.messages == []
    assert result.error is not None


def test_defect2_resume_completes_only_pending_steps_despite_duplicate():
    cand = make_candidate()
    cu, dc = FakeClickUpClient(), FailFirstDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)

    r1 = rec.record(position_name="빅밸류 세일즈 총괄", candidate=cand)
    assert r1.status == "partial"

    # 실제 상황 재현: 1차에서 subtask 가 이미 생성됐으므로 중복확인은 True 가 된다
    cu.existing_profile_urls.add(cand.profile_url)
    dup_checks_before = len(cu.duplicate_checks)

    r2 = rec.record(position_name="빅밸류 세일즈 총괄", candidate=cand, resume_from=r1)

    # 재시도는 중복 판정으로 skip 되지 않고 미완 단계만 이어서 최종 완결
    assert r2.status == "recorded"
    assert r2.duplicate_skipped is False
    assert r2.pending_steps == []
    assert len(cu.created_subtasks) == 1  # ClickUp 재생성 없음
    assert len(cu.duplicate_checks) == dup_checks_before  # 중복확인 재수행 없음
    channels = [m["channel_id"] for m in dc.messages]
    assert DISCORD_RESULT_CHANNEL_ID in channels
    assert DISCORD_MEMBER_CHANNEL_ID in channels


def test_defect3_subtask_carries_deterministic_idempotency_key():
    cand = make_candidate()

    def run_once():
        cu, dc = FakeClickUpClient(), FakeDiscordClient()
        rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)
        rec.record(position_name="빅밸류 세일즈 총괄", candidate=cand)
        return cu.created_subtasks[0]["fields"]["idempotency_key"]

    key1, key2 = run_once(), run_once()
    assert key1 == key2  # profile_url 기반 결정론 — 재시도에도 동일 키
    assert cand.profile_url not in key1  # 원문 URL 노출 없이 파생 키

    other = make_candidate(profile_url="https://www.linkedin.com/in/other-person/")
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)
    rec.record(position_name="빅밸류 세일즈 총괄", candidate=other)
    assert cu.created_subtasks[0]["fields"]["idempotency_key"] != key1


@pytest.mark.parametrize("bad_score", [101, -1, 87.5, "87", True])
def test_defect4_score_must_be_int_0_to_100(bad_score):
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)

    result = rec.record(
        position_name="빅밸류 세일즈 총괄", candidate=make_candidate(score=bad_score)
    )

    assert result.status == "failed"
    assert result.recorded is False
    assert result.error is not None and "score" in result.error
    assert cu.created_tasks == []
    assert cu.created_subtasks == []
    # 에러는 멤버 채널에만 보고
    assert [m["channel_id"] for m in dc.messages] == [DISCORD_MEMBER_CHANNEL_ID]


def test_defect5_dry_run_subtask_plan_uses_parent_placeholder():
    cu, dc = FakeClickUpClient(), FakeDiscordClient()  # 부모 Task 없음 → 생성 예정
    rec = DualRecorder(clickup=cu, discord=dc)

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate())

    sub_plan = next(
        a for a in result.planned_actions
        if a["kind"] == "clickup_create_candidate_subtask"
    )
    # None 이 아니라 의미가 명확한 placeholder 참조
    assert sub_plan["parent_task_id"] == "<parent-to-be-created>"


def test_defect5_live_subtask_uses_real_created_parent_id():
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate())

    sub_plan = next(
        a for a in result.planned_actions
        if a["kind"] == "clickup_create_candidate_subtask"
    )
    assert sub_plan["parent_task_id"] == "task-1"  # 생성된 실제 ID
    assert cu.created_subtasks[0]["parent_task_id"] == "task-1"


def test_missing_required_field_fails_closed_and_reports_error_to_member_channel():
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=FakeAdminApiClient(), live=True, owner_signoff=True)

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate(why_fit=""))

    assert result.recorded is False
    assert result.error is not None and "why_fit" in result.error
    assert cu.created_tasks == []
    assert cu.created_subtasks == []
    # 에러는 멤버 채널에만 게시
    channels = [m["channel_id"] for m in dc.messages]
    assert channels == [DISCORD_MEMBER_CHANNEL_ID]
    assert "why_fit" in dc.messages[0]["content"]


# ── AC-6 — admin.valuehire.cc(v4) 등록
# (goal: docs/engineering/aisearch-register-api-goal-2026-07-31.md) ─────────────


def test_ac6_dry_run_plans_admin_register_without_calling_admin_client():
    cu, dc, am = FakeClickUpClient(), FakeDiscordClient(), FakeAdminApiClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=am)  # 기본 dry-run

    result = rec.record(
        position_name="빅밸류 세일즈 총괄",
        candidate=make_candidate(name="홍길동"),
        channel="linkedin",
    )

    assert result.dry_run is True
    assert am.registered == []  # dry-run: 실제 호출 0회
    plan = next(a for a in result.planned_actions if a["kind"] == "admin_register_candidate")
    assert plan["name"] == "홍길동"
    assert plan["channel"] == "linkedin"
    assert plan["match_score"] == 87
    assert plan["jd_title"] == "빅밸류 세일즈 총괄"


def test_ac6_live_calls_admin_register_with_mapped_fields():
    cu, dc, am = FakeClickUpClient(), FakeDiscordClient(), FakeAdminApiClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=am, live=True, owner_signoff=True)
    cand = make_candidate(name="홍길동")

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=cand, channel="saramin")

    assert result.status == "recorded"
    assert len(am.registered) == 1
    sent = am.registered[0]
    assert sent["name"] == "홍길동"
    assert sent["profile_url"] == cand.profile_url
    assert sent["match_score"] == cand.score
    assert sent["why_fit"] == cand.why_fit
    assert sent["profile_summary"] == cand.profile_summary
    assert sent["channel"] == "saramin"


def test_ac6_missing_candidate_name_falls_back_to_profile_url():
    cu, dc, am = FakeClickUpClient(), FakeDiscordClient(), FakeAdminApiClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=am, live=True, owner_signoff=True)
    cand = make_candidate()  # name 미지정 — 기본값 ""

    rec.record(position_name="빅밸류 세일즈 총괄", candidate=cand, channel="linkedin")

    assert am.registered[0]["name"] == cand.profile_url


def test_ac6_missing_channel_falls_back_to_unknown_not_blank():
    cu, dc, am = FakeClickUpClient(), FakeDiscordClient(), FakeAdminApiClient()
    rec = DualRecorder(clickup=cu, discord=dc, admin=am, live=True, owner_signoff=True)

    rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate())  # channel 인자 없음

    assert am.registered[0]["channel"] == "unknown"


def test_ac6_admin_not_configured_fails_partial_in_live_mode_not_silent_success():
    """admin 미주입 + live=True 인데 기록 경로에 도달하면 조용히 성공한 척하지 않는다."""
    cu, dc = FakeClickUpClient(), FakeDiscordClient()
    rec = DualRecorder(clickup=cu, discord=dc, live=True, owner_signoff=True)  # admin 생략

    result = rec.record(position_name="빅밸류 세일즈 총괄", candidate=make_candidate())

    assert result.status in ("partial", "failed")
    assert result.error is not None
