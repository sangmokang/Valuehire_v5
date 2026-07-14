"""D1 (2026-07-03 사장님) — 디스코드 DM 으로 Claude 에 명령 내리는 다리 (RED 먼저).

안전 계약: ①사장님(OWNER_ID) 메시지만 명령으로 인정 ②봇 자신·타인 메시지 무시
③이미 처리한 메시지(id<=last) 재실행 금지 ④빈/공백 명령 무시 ⑤"봇 정지"는 킬 스위치
⑥회신은 2000자 제한 안전 분할.
"""
from __future__ import annotations

from scripts.discord_command_listener import (
    OWNER_ID,
    chunk_reply,
    is_kill_command,
    select_agent_and_prompt,
    select_new_commands,
)


def _msg(mid: str, author: str, content: str) -> dict:
    return {"id": mid, "author": {"id": author}, "content": content}


def test_d1_only_owner_messages_selected() -> None:
    msgs = [
        _msg("101", OWNER_ID, "서치 상태 알려줘"),
        _msg("102", "9999", "해킹 시도"),          # 타인 — 무시
        _msg("103", "1512101118543397056", "봇 자신"),  # 봇 — 무시
    ]
    cmds, last = select_new_commands(msgs, last_id="100")
    assert [c["content"] for c in cmds] == ["서치 상태 알려줘"]
    assert last == "103"


def test_d1_already_processed_not_rerun() -> None:
    msgs = [_msg("50", OWNER_ID, "옛 명령"), _msg("120", OWNER_ID, "새 명령")]
    cmds, last = select_new_commands(msgs, last_id="100")
    assert [c["content"] for c in cmds] == ["새 명령"]
    assert last == "120"


def test_d1_empty_and_whitespace_ignored() -> None:
    msgs = [_msg("201", OWNER_ID, "   "), _msg("202", OWNER_ID, "")]
    cmds, last = select_new_commands(msgs, last_id="200")
    assert cmds == [] and last == "202"


def test_d1_kill_switch() -> None:
    assert is_kill_command("봇 정지")
    assert is_kill_command("  stop bot  ")
    assert not is_kill_command("정지하지 말고 계속")


def test_d1_reply_chunked_under_discord_limit() -> None:
    chunks = chunk_reply("가" * 4500)
    assert all(len(c) <= 1900 for c in chunks)
    assert "".join(chunks) == "가" * 4500


# ── V1(Codex 2026-07-03) 적발 결함 회귀봉인 ──
def test_d1_v1_kill_switch_multi_whitespace() -> None:
    """'봇   정지'(공백 3개)·탭도 킬 스위치 — 공백 정규화 우회 금지."""
    assert is_kill_command("봇   정지")
    assert is_kill_command("stop\tbot")


def test_d1_v1_single_instance_lock(tmp_path) -> None:
    """리스너 2개 동시 실행 금지 — 두 번째 acquire 는 실패해야(중복 실행 차단)."""
    from scripts.discord_command_listener import acquire_single_instance_lock
    lock = tmp_path / "bridge.lock"
    assert acquire_single_instance_lock(lock, pid=11111) is True
    # 살아있는 프로세스(pid=자기 자신)로 기록된 락은 두 번째가 못 얻음
    import os
    lock.write_text(str(os.getpid()))
    assert acquire_single_instance_lock(lock, pid=22222) is False
    # 죽은 pid 락은 회수 가능
    lock.write_text("99999999")
    assert acquire_single_instance_lock(lock, pid=33333) is True


def test_d1_v1_state_saved_atomically(tmp_path) -> None:
    """상태 저장은 임시파일→교체(원자적) — 동시 쓰기로 반쪽 파일 금지."""
    from scripts.discord_command_listener import save_last_atomic
    state = tmp_path / "state.json"
    save_last_atomic(state, "12345")
    import json
    assert json.loads(state.read_text())["last_id"] == "12345"


# ── 이슈 F(2026-07-15 사장님 지시) — Discord DM = 쉘 프론트엔드, codex 선택지 ──
def test_f_default_agent_is_claude_verbatim() -> None:
    """접두어 없으면 agent=claude, 프롬프트는 원문 그대로(1바이트도 재구성 안 함)."""
    agent, prompt = select_agent_and_prompt("찾아줘 이 링크")
    assert agent == "claude"
    assert prompt == "찾아줘 이 링크"


def test_f_codex_prefix_switches_agent_and_strips_prefix() -> None:
    agent, prompt = select_agent_and_prompt("codex: 이 버그 고쳐줘 foo.py 43번째 줄")
    assert agent == "codex"
    assert prompt == "이 버그 고쳐줘 foo.py 43번째 줄"


def test_f_codex_prefix_case_and_whitespace_insensitive() -> None:
    agent, prompt = select_agent_and_prompt("Codex:   fix bug")
    assert agent == "codex"
    assert prompt == "fix bug"


def test_f_codex_word_mid_sentence_does_not_trigger() -> None:
    """접두어가 아니라 문장 중간의 'codex'/'코덱스'는 오탐 안 됨 — 기본 claude, verbatim 유지."""
    agent, prompt = select_agent_and_prompt("이거 코덱스 얘기인데 찾아줘")
    assert agent == "claude"
    assert prompt == "이거 코덱스 얘기인데 찾아줘"


def test_f_run_agent_dispatches_correct_subprocess_command(monkeypatch) -> None:
    from scripts import discord_command_listener as dcl

    captured: dict[str, list[str]] = {}

    class _FakeCompleted:
        stdout = "ok"
        stderr = ""

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompleted()

    monkeypatch.setattr(dcl.subprocess, "run", _fake_run)
    dcl._run_agent("claude", "hello")
    assert captured["cmd"] == ["claude", "-p", "hello"]
    dcl._run_agent("codex", "hello")
    assert captured["cmd"] == ["codex", "exec", "hello"]


def test_f_v1_main_loop_verbatim_prompt_and_agent_tag(monkeypatch) -> None:
    """V1(Codex) 반증 수용 — main 루프가 프롬프트를 바깥 공백까지 그대로 전달하고,
    접수 메시지에 선택된 agent(claude 포함)를 표시한다."""
    from types import SimpleNamespace

    from scripts import discord_command_listener as dcl

    raw = "  keep  internal  \nformatting  "
    sent: list[str] = []
    argv: list[list[str]] = []
    msgs = [
        {"id": "101", "author": {"id": dcl.OWNER_ID}, "content": raw},
        {"id": "102", "author": {"id": dcl.OWNER_ID}, "content": "봇 정지"},
    ]
    monkeypatch.setattr(dcl, "acquire_single_instance_lock", lambda *a: True)
    monkeypatch.setattr(dcl, "_load_last", lambda: "100")
    monkeypatch.setattr(dcl, "_api", lambda *a, **k: msgs)
    monkeypatch.setattr(dcl, "_send", sent.append)
    monkeypatch.setattr(dcl, "_save_last", lambda _last: None)
    monkeypatch.setattr(
        dcl.subprocess, "run",
        lambda cmd, **kw: (argv.append(cmd) or SimpleNamespace(stdout="ok", stderr="")),
    )
    dcl.main()
    assert argv == [["claude", "-p", raw]]  # 원문 그대로 — 앞뒤 공백도 재구성 금지
    assert any(s.startswith("⏳ 접수(claude):") for s in sent)
