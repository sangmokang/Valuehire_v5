"""이슈 #194 — login 잡의 Codex 실행이 ~/.valuehire 잠금·영수증을 쓸 수 있어야 한다.

라이브 실측(잡 #75, 2026-07-24 2회 재현): 기본 `--sandbox read-only` 가
`~/.valuehire/browser_locks/*.lock` 생성을 거부해 login 잡이 항상
'프로필 잠금 파일 접근 권한 없음' paused_for_human 으로 끝난다.

인수 기준: 이 파일이 GREEN.
- login 잡 env 로 만든 Codex 인자에는 workspace-write 샌드박스 + 네트워크 설정 +
  `--add-dir ~/.valuehire` 가 포함된다(명시 read_only 여도 login 이 이긴다 —
  login 은 쓰기 없이는 성립 불가한 스킬).
- login 이 아닌 잡의 기본 인자는 기존 그대로(read-only, .valuehire add-dir 없음).
- danger 계열 플래그 금지 가드 유지.
"""
from __future__ import annotations

from pathlib import Path

from tools.multi_position_sourcing import fleet_worker


VALUEHIRE_HOME = str(Path.home() / ".valuehire")


def _pairs(args):
    return list(zip(args, args[1:]))


def _owner_login_env(**extra):
    return {"VALUEHIRE_JOB_SKILL": "login", "VALUEHIRE_JOB_ROLE": "owner", **extra}


def test_owner_login_job_codex_args_allow_valuehire_writes():
    args = fleet_worker.build_codex_exec_args(_owner_login_env())
    assert ("--sandbox", "workspace-write") in _pairs(args)
    assert ("--add-dir", VALUEHIRE_HOME) in _pairs(args)
    assert fleet_worker._NETWORK_CONFIG_FLAG in args


def test_owner_login_overrides_explicit_read_only_mode():
    args = fleet_worker.build_codex_exec_args(
        _owner_login_env(VALUEHIRE_AGENT_EXECUTION_MODE="read_only"))
    assert ("--sandbox", "workspace-write") in _pairs(args)


def test_member_forged_login_does_not_escalate():
    """Codex V2 F1 — anon 이 강제하는 role=member 로는 넓은 샌드박스를 못 얻는다."""
    args = fleet_worker.build_codex_exec_args({
        "VALUEHIRE_JOB_SKILL": "login", "VALUEHIRE_JOB_ROLE": "member"})
    assert ("--sandbox", "read-only") in _pairs(args)
    assert ("--add-dir", VALUEHIRE_HOME) not in _pairs(args)
    # role 미지정(구 페이로드)도 확장 금지 — fail-closed.
    args2 = fleet_worker.build_codex_exec_args({"VALUEHIRE_JOB_SKILL": "login"})
    assert ("--sandbox", "read-only") in _pairs(args2)


def test_non_login_default_stays_read_only_without_valuehire_dir():
    for env in ({}, {"VALUEHIRE_JOB_SKILL": "humansearch"}):
        args = fleet_worker.build_codex_exec_args(env)
        assert ("--sandbox", "read-only") in _pairs(args)
        assert ("--add-dir", VALUEHIRE_HOME) not in _pairs(args)


def test_login_args_keep_danger_guard():
    args = fleet_worker.build_codex_exec_args(_owner_login_env())
    assert "danger-full-access" not in args
    assert "--dangerously-bypass-approvals-and-sandbox" not in args


def test_busy_badge_env_carries_job_skill_and_role():
    class _Q:  # noqa: D401 — 최소 큐 스텁
        pass

    worker = fleet_worker.FleetWorker(
        machine="macmini", queue=_Q(), notifier=lambda job, text: None)
    env = worker._busy_badge_env(
        {"id": 7, "skill": "login", "role": "owner"}, "codex")
    assert env.get("VALUEHIRE_JOB_SKILL") == "login"
    assert env.get("VALUEHIRE_JOB_ROLE") == "owner"
