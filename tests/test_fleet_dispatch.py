"""단계 C — 함대 Discord 디스패치(fleet_dispatch) 기계 검증.

계약(docs/prompts/fleet-control-sequential-prompts-2026-07-11.md §프롬프트 C):
- fleet-run: 인가된 멤버/owner 가 잡을 큐에 넣는다(발송 아님 — enqueue 만).
- fleet-resume / fleet-cancel: owner 전용(멤버 거부).
- fleet-status: 인가된 사용자면 최근 잡 요약(읽기).
- 어떤 명령도 발송/아웃리치 함수를 호출할 수 없다(SOT28 — 큐엔 검색 스킬만).
- 기존 run-search(source/keyword) 의미를 약화시키지 않는다(별도 명령).
"""
from __future__ import annotations

import pytest

from tools.multi_position_sourcing.access import DiscordAuthorizedUser
from tools.multi_position_sourcing.discord_routing import (
    DiscordAccessConfig,
    DiscordInvocation,
    SUPPORTED_DISCORD_COMMANDS,
)
from tools.multi_position_sourcing.fleet_dispatch import (
    FLEET_COMMANDS,
    build_fleet_job_payload,
    dispatch_fleet_command,
    is_owner,
)

OWNER_ID = "814353841088757800"
MEMBER_ID = "999000111222333444"
CHANNEL = "111111111111111111"
GUILD = "222222222222222222"
OWNER_ROLE = "333333333333333333"


def _users():
    return (DiscordAuthorizedUser(name="사장님", alias="owner",
                                  email="dev@valueconnect.kr", discord_id=OWNER_ID),)


def _config():
    return DiscordAccessConfig(
        allowed_channel_ids=(CHANNEL,),
        allowed_role_ids=("444444444444444444",),  # member 역할
        allow_dm=True,
    )


def _inv(command, user_id=OWNER_ID, is_dm=True, options=None, roles=()):
    return DiscordInvocation(
        user_id=user_id, channel_id=CHANNEL if not is_dm else "dm",
        command_name=command, is_dm=is_dm, invocation_kind="slash",
        guild_id="" if is_dm else GUILD, member_role_ids=roles,
        options=options or {},
    )


class FakeQueue:
    def __init__(self):
        self.enqueued = []
        self.resumed = []
        self.cancelled = []

    def enqueue(self, payload):
        self.enqueued.append(payload)
        return {"id": 42, **payload}

    def resume(self, job_id):
        self.resumed.append(job_id)
        return [{"id": job_id, "status": "queued"}]

    def cancel(self, job_id, reason=""):
        self.cancelled.append((job_id, reason))
        return [{"id": job_id, "status": "cancelled"}]

    def recent(self, limit=10):
        return [{"id": 42, "status": "running", "skill": "humansearch",
                 "machine": "macmini", "result_summary": ""}]


# ── 명령 등록 ────────────────────────────────────────────────────────

def test_fleet_commands_registered_but_run_search_untouched():
    assert set(FLEET_COMMANDS) == {"fleet-run", "fleet-resume", "fleet-status", "fleet-cancel"}
    for c in FLEET_COMMANDS:
        assert c in SUPPORTED_DISCORD_COMMANDS
    # 기존 run-search 는 그대로 존재(약화 금지)
    assert "run-search" in SUPPORTED_DISCORD_COMMANDS


# ── 페이로드 빌드 (fleet-run) ────────────────────────────────────────

def test_build_fleet_job_payload_happy():
    p = build_fleet_job_payload(
        {"skill": "humansearch", "url": "https://app.clickup.com/t/abc", "machine": "macmini"},
        requested_by=f"{OWNER_ID}:사장님", role="owner")
    assert p is not None
    assert p["skill"] == "humansearch" and p["machine"] == "macmini"
    assert p["status"] == "queued"


def test_build_fleet_job_payload_preserves_existing_machine_default():
    p = build_fleet_job_payload(
        {"skill": "aisearch", "url": "https://app.clickup.com/t/abc"},
        requested_by="m:member", role="member")
    assert p is not None and p["machine"] == "macmini"


def test_build_fleet_job_payload_accepts_normalized_dynamic_machine():
    p = build_fleet_job_payload(
        {"skill": "humansearch", "url": "https://x.com/a", "machine": "server42"},
        requested_by="m:member", role="member")
    assert p is not None and p["machine"] == "server42"


@pytest.mark.parametrize("opts", [
    {"skill": "send", "url": "https://x.com/a"},        # 발송성 스킬 금지
    {"skill": "humansearch", "url": "notaurl"},
    {"skill": "humansearch"},                            # url 없음
    {"url": "https://x.com/a"},                          # skill 없음
    {"skill": "humansearch", "url": "https://x.com/a", "machine": " server42"},
])
def test_build_fleet_job_payload_fail_closed(opts):
    assert build_fleet_job_payload(opts, requested_by="m:member", role="member") is None


# ── owner 판정 ───────────────────────────────────────────────────────

def test_is_owner_by_explicit_id_and_role():
    assert is_owner(_inv("fleet-resume", user_id=OWNER_ID, is_dm=True),
                    owner_user_ids=(OWNER_ID,), owner_role_ids=(OWNER_ROLE,)) is True
    # 멤버 DM → owner 아님
    assert is_owner(_inv("fleet-resume", user_id=MEMBER_ID, is_dm=True),
                    owner_user_ids=(OWNER_ID,), owner_role_ids=(OWNER_ROLE,)) is False
    # 길드에서 owner 역할 보유 → owner
    assert is_owner(_inv("fleet-resume", user_id=MEMBER_ID, is_dm=False, roles=(OWNER_ROLE,)),
                    owner_user_ids=(OWNER_ID,), owner_role_ids=(OWNER_ROLE,)) is True


def test_owner_decoupled_from_member_contacts():
    # V1 결함: 인가된 멤버 연락처(팀원)가 owner 로 새면 안 됨. owner 는 명시적 id 로만.
    from tools.multi_position_sourcing.fleet_dispatch import OWNER_USER_IDS
    team_member = "555000111222333444"  # authorized_users 에 있어도 owner_user_ids 엔 없음
    q = FakeQueue()
    r = dispatch_fleet_command(
        DiscordInvocation(user_id=team_member, channel_id="dm", command_name="fleet-resume",
                          is_dm=True, invocation_kind="slash", guild_id="",
                          member_role_ids=(), options={"job": "7"}),
        authorized_users=(DiscordAuthorizedUser(name="팀원", alias="m", email="m@x.kr",
                                                discord_id=team_member),),
        config=DiscordAccessConfig(allowed_channel_ids=(), allowed_role_ids=(), allow_dm=True),
        queue=q, owner_user_ids=OWNER_USER_IDS, owner_role_ids=())
    assert r["action"] == "denied_owner_only"
    assert q.resumed == []
    # 반대로 사장님(OWNER_USER_IDS)은 멤버 목록에 없어도 owner
    assert OWNER_ID in OWNER_USER_IDS


# ── 디스패치: fleet-run (멤버 허용) ──────────────────────────────────

def test_dispatch_fleet_run_enqueues():
    q = FakeQueue()
    r = dispatch_fleet_command(
        _inv("fleet-run", user_id=OWNER_ID, is_dm=True,
             options={"skill": "humansearch", "url": "https://app.clickup.com/t/abc"}),
        authorized_users=_users(), config=_config(), queue=q, owner_role_ids=(OWNER_ROLE,))
    assert r["action"] == "enqueued" and r["job"]["id"] == 42
    assert len(q.enqueued) == 1
    assert q.resumed == [] and q.cancelled == []


def test_dispatch_unauthorized_user_blocked():
    q = FakeQueue()
    r = dispatch_fleet_command(
        _inv("fleet-run", user_id=MEMBER_ID, is_dm=True,
             options={"skill": "humansearch", "url": "https://app.clickup.com/t/abc"}),
        authorized_users=_users(), config=_config(), queue=q, owner_role_ids=(OWNER_ROLE,))
    assert r["action"] == "denied"
    assert q.enqueued == []


# ── 디스패치: resume/cancel owner 전용 ───────────────────────────────

def test_dispatch_resume_owner_only():
    q = FakeQueue()
    # owner DM → 허용
    r = dispatch_fleet_command(
        _inv("fleet-resume", user_id=OWNER_ID, is_dm=True, options={"job": "7"}),
        authorized_users=_users(), config=_config(), queue=q, owner_role_ids=(OWNER_ROLE,))
    assert r["action"] == "resumed" and q.resumed == [7]

    # 멤버(길드, member 역할) → 인가는 되지만 owner 아님 → 거부
    q2 = FakeQueue()
    cfg = _config()
    r2 = dispatch_fleet_command(
        DiscordInvocation(user_id=MEMBER_ID, channel_id=CHANNEL, command_name="fleet-resume",
                          is_dm=False, invocation_kind="slash", guild_id=GUILD,
                          member_role_ids=("444444444444444444",), options={"job": "7"}),
        authorized_users=_users(), config=cfg, queue=q2, owner_role_ids=(OWNER_ROLE,))
    assert r2["action"] == "denied_owner_only"
    assert q2.resumed == []


def test_dispatch_cancel_owner_only_and_needs_job():
    q = FakeQueue()
    r = dispatch_fleet_command(
        _inv("fleet-cancel", user_id=OWNER_ID, is_dm=True, options={"job": "9"}),
        authorized_users=_users(), config=_config(), queue=q, owner_role_ids=(OWNER_ROLE,))
    assert r["action"] == "cancelled" and q.cancelled == [(9, "Discord fleet-cancel")]
    # job 없음 → 오류
    r2 = dispatch_fleet_command(
        _inv("fleet-cancel", user_id=OWNER_ID, is_dm=True, options={}),
        authorized_users=_users(), config=_config(), queue=FakeQueue(), owner_role_ids=(OWNER_ROLE,))
    assert r2["action"] == "error"


def test_dispatch_status_readable_by_member():
    q = FakeQueue()
    r = dispatch_fleet_command(
        _inv("fleet-status", user_id=OWNER_ID, is_dm=True),
        authorized_users=_users(), config=_config(), queue=q, owner_role_ids=(OWNER_ROLE,))
    assert r["action"] == "status" and len(r["jobs"]) == 1


# ── 발송 게이트: 디스패처는 발송 함수를 절대 부르지 않는다 ───────────

def test_dispatch_never_calls_send():
    import inspect
    from tools.multi_position_sourcing import fleet_dispatch
    src = inspect.getsource(fleet_dispatch)
    for banned in ("send_message", "send_inmail", "send_mail", "outreach", ".send("):
        assert banned not in src, f"디스패처에 발송 호출 흔적: {banned}"


def test_dispatch_wrong_command_returns_none():
    q = FakeQueue()
    assert dispatch_fleet_command(
        _inv("register-position", user_id=OWNER_ID, is_dm=True),
        authorized_users=_users(), config=_config(), queue=q, owner_role_ids=(OWNER_ROLE,)) is None


# ── 이슈 D(2026-07-15 승인) — skill=url 머신 미지정 → 로그인 머신 라우팅 ──

def _routing_queue(rows=None, raise_rpc=False):
    q = FakeQueue()
    q.linkedin_calls = []
    def linkedin_ready_machines():
        q.linkedin_calls.append(1)
        if raise_rpc:
            raise RuntimeError("rpc down")
        return rows or []
    q.linkedin_ready_machines = linkedin_ready_machines
    return q


def test_url_job_without_machine_routes_to_logged_in_machine():
    import time
    now = int(time.time())
    q = _routing_queue(rows=[{"machine": "winpc", "beat_at_epoch": now - 5,
                              "linkedin_rps_logged_in": True}])
    result = dispatch_fleet_command(
        _inv("fleet-run", options={"skill": "url", "url": "https://career.wrtn.io/ko/o/1"}),
        authorized_users=_users(), config=_config(), queue=q)
    assert result["action"] == "enqueued"
    assert q.enqueued[0]["machine"] == "winpc"
    assert q.linkedin_calls, "라우팅 조회가 실제로 호출돼야 함"


def test_url_job_routing_rpc_failure_falls_back_to_macmini():
    q = _routing_queue(raise_rpc=True)
    result = dispatch_fleet_command(
        _inv("fleet-run", options={"skill": "url", "url": "https://career.wrtn.io/ko/o/1"}),
        authorized_users=_users(), config=_config(), queue=q)
    assert result["action"] == "enqueued"
    assert q.enqueued[0]["machine"] == "macmini"


def test_url_job_explicit_machine_not_overridden():
    import time
    now = int(time.time())
    q = _routing_queue(rows=[{"machine": "winpc", "beat_at_epoch": now - 5,
                              "linkedin_rps_logged_in": True}])
    result = dispatch_fleet_command(
        _inv("fleet-run", options={"skill": "url", "machine": "macbook",
                                   "url": "https://career.wrtn.io/ko/o/1"}),
        authorized_users=_users(), config=_config(), queue=q)
    assert result["action"] == "enqueued"
    assert q.enqueued[0]["machine"] == "macbook"
    assert not q.linkedin_calls, "명시 머신이면 라우팅 조회 안 함"


def test_non_url_skill_keeps_existing_default():
    q = _routing_queue(rows=[{"machine": "winpc", "beat_at_epoch": 9_999_999_999,
                              "linkedin_rps_logged_in": True}])
    result = dispatch_fleet_command(
        _inv("fleet-run", options={"skill": "aisearch", "url": "https://app.clickup.com/t/abc"}),
        authorized_users=_users(), config=_config(), queue=q)
    assert result["action"] == "enqueued"
    assert q.enqueued[0]["machine"] == "macmini"
    assert not q.linkedin_calls


def test_url_jobs_share_single_linkedin_seat_lock():
    """V1(Codex) blocker 수용 — 라우팅으로 머신이 갈라져도 LinkedIn 좌석은 1개다.
    skill=url 잡은 머신 무관 공유 account_key 로 글로벌 락이 걸려야 동시 2머신 실행이 막힌다."""
    import time
    now = int(time.time())
    q1 = _routing_queue(rows=[{"machine": "winpc", "beat_at_epoch": now - 5,
                               "linkedin_rps_logged_in": True}])
    dispatch_fleet_command(
        _inv("fleet-run", options={"skill": "url", "url": "https://career.wrtn.io/ko/o/1"}),
        authorized_users=_users(), config=_config(), queue=q1)
    q2 = _routing_queue(rows=[{"machine": "macmini", "beat_at_epoch": now - 5,
                               "linkedin_rps_logged_in": True}])
    dispatch_fleet_command(
        _inv("fleet-run", options={"skill": "url", "url": "https://career.wrtn.io/ko/o/2"}),
        authorized_users=_users(), config=_config(), queue=q2)
    k1, k2 = q1.enqueued[0]["account_key"], q2.enqueued[0]["account_key"]
    assert q1.enqueued[0]["machine"] == "winpc"
    assert q2.enqueued[0]["machine"] == "macmini"
    assert k1 == k2, f"좌석 락 키가 머신 따라 갈라짐: {k1} vs {k2}"
    assert "linkedin" in k1


def test_non_url_jobs_keep_machine_bound_account_key():
    q = _routing_queue()
    dispatch_fleet_command(
        _inv("fleet-run", options={"skill": "aisearch", "url": "https://app.clickup.com/t/abc"}),
        authorized_users=_users(), config=_config(), queue=q)
    assert q.enqueued[0]["account_key"] == "portal:macmini"
