"""D1 (2026-07-03 사장님) — 디스코드 DM 으로 Claude 에 명령 내리는 다리 (RED 먼저).

안전 계약: ①사장님(OWNER_ID) 메시지만 명령으로 인정 ②봇 자신·타인 메시지 무시
③이미 처리한 메시지(id<=last) 재실행 금지 ④빈/공백 명령 무시 ⑤"봇 정지"는 킬 스위치
⑥회신은 2000자 제한 안전 분할.
"""
from __future__ import annotations

from pathlib import Path
from io import BytesIO
from urllib.error import HTTPError

from scripts.discord_command_listener import (
    DM_CHANNEL,
    OWNER_ID,
    chunk_reply,
    enqueue_owner_message,
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
def test_f_default_agent_is_codex_verbatim() -> None:
    """접두어 없으면 agent=codex, 프롬프트는 원문 그대로다."""
    agent, prompt = select_agent_and_prompt("찾아줘 이 링크")
    assert agent == "codex"
    assert prompt == "찾아줘 이 링크"


def test_f_codex_prefix_switches_agent_and_preserves_raw_approval() -> None:
    raw = "codex: 이 버그 고쳐줘 foo.py 43번째 줄"
    agent, prompt = select_agent_and_prompt(raw)
    assert agent == "codex"
    assert prompt == raw


def test_f_codex_prefix_case_and_whitespace_insensitive() -> None:
    raw = "Codex:   fix bug"
    agent, prompt = select_agent_and_prompt(raw)
    assert agent == "codex"
    assert prompt == raw


def test_f_claude_prefix_switches_agent_and_preserves_raw_approval() -> None:
    raw = "  Claude:  jdbuilder로 초안 만들어줘  "
    agent, prompt = select_agent_and_prompt(raw)
    assert agent == "claude"
    assert prompt == raw


def test_f_codex_word_mid_sentence_does_not_trigger() -> None:
    """문장 중간의 'codex'/'코덱스'는 오탐 안 됨 — 기본 codex, verbatim 유지."""
    agent, prompt = select_agent_and_prompt("이거 코덱스 얘기인데 찾아줘")
    assert agent == "codex"
    assert prompt == "이거 코덱스 얘기인데 찾아줘"


class _FakeQueue:
    def __init__(self, error: Exception | None = None) -> None:
        self.payloads: list[dict] = []
        self.error = error

    def enqueue(self, payload: dict) -> dict:
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return {"id": 501, **payload}


def _owner_message(content: str = "jdbuilder로 초안 만들어줘") -> dict:
    return {
        "id": "765432109876543210",
        "channel_id": DM_CHANNEL,
        "author": {"id": OWNER_ID, "username": "사장님"},
        "content": content,
    }


def test_owner_message_enqueues_one_durable_codex_job() -> None:
    queue = _FakeQueue()
    result = enqueue_owner_message(_owner_message(), queue=queue, machine="macmini")
    assert result == {"status": "queued", "job_id": 501, "agent": "codex"}
    assert len(queue.payloads) == 1
    row = queue.payloads[0]
    assert row["skill"] == "agent" and row["role"] == "owner"
    assert row["params"]["request_text"] == "jdbuilder로 초안 만들어줘"
    assert row["params"]["agent"] == "codex"
    assert row["params"]["approval_id"] == "discord:765432109876543210"


def test_owner_message_claude_override_is_bound_before_enqueue() -> None:
    queue = _FakeQueue()
    result = enqueue_owner_message(
        _owner_message("claude:  url 스킬로 준비해줘"), queue=queue, machine="macmini")
    assert result["agent"] == "claude"
    assert queue.payloads[0]["params"]["request_text"] == "claude:  url 스킬로 준비해줘"
    assert queue.payloads[0]["params"]["agent"] == "claude"


def test_enqueue_owner_message_reauthenticates_author_and_rejects_blank_prefix() -> None:
    queue = _FakeQueue()
    other = _owner_message()
    other["author"] = {"id": "111111111111111111", "username": "member"}
    import pytest
    with pytest.raises(PermissionError):
        enqueue_owner_message(other, queue=queue, machine="macmini")
    with pytest.raises(ValueError):
        enqueue_owner_message(_owner_message("claude:   "), queue=queue, machine="macmini")
    assert queue.payloads == []


def test_duplicate_message_conflict_is_acknowledged_without_second_execution() -> None:
    conflict = HTTPError(
        "https://db/jobs", 409, "Conflict", None,
        BytesIO(b'{"code":"23505","message":"duplicate key value violates unique constraint '
                b'\\"jobs_discord_idempotency_key_uidx\\""}'),
    )
    queue = _FakeQueue(conflict)
    result = enqueue_owner_message(_owner_message(), queue=queue, machine="macmini")
    assert result == {"status": "duplicate", "job_id": None, "agent": "codex"}
    assert len(queue.payloads) == 1


def test_unrelated_http_409_is_not_misreported_as_duplicate() -> None:
    import pytest
    conflict = HTTPError(
        "https://db/jobs", 409, "Conflict", None,
        BytesIO(b'{"code":"23503","message":"foreign key conflict"}'),
    )
    with pytest.raises(HTTPError):
        enqueue_owner_message(_owner_message(), queue=_FakeQueue(conflict), machine="macmini")


def test_listener_has_no_direct_model_subprocess_path() -> None:
    source = (Path(__file__).resolve().parents[1]
              / "scripts/discord_command_listener.py").read_text(encoding="utf-8")
    assert "subprocess.run" not in source
    assert "def _run_agent" not in source


def test_main_loop_enqueues_then_advances_message_state(monkeypatch) -> None:
    """수신기는 모델을 부르지 않고 큐 접수 성공 뒤에만 메시지 상태를 전진한다."""
    from scripts import discord_command_listener as dcl

    raw = "  keep  internal  \nformatting  "
    sent: list[str] = []
    saved: list[str] = []
    queue = _FakeQueue()
    msgs = [
        {"id": "765432109876543210", "channel_id": dcl.DM_CHANNEL,
         "author": {"id": dcl.OWNER_ID}, "content": raw},
        {"id": "765432109876543211", "channel_id": dcl.DM_CHANNEL,
         "author": {"id": dcl.OWNER_ID}, "content": "봇 정지"},
    ]
    monkeypatch.setattr(dcl, "acquire_single_instance_lock", lambda *a: True)
    monkeypatch.setattr(dcl, "_load_last", lambda: "765432109876543209")
    monkeypatch.setattr(dcl, "_api", lambda *a, **k: msgs)
    monkeypatch.setattr(dcl, "_send", sent.append)
    monkeypatch.setattr(dcl, "_save_last", saved.append)
    dcl.main(queue=queue, machine="macmini")
    assert len(queue.payloads) == 1
    assert queue.payloads[0]["params"]["request_text"] == raw
    assert queue.payloads[0]["params"]["agent"] == "codex"
    assert saved == ["765432109876543210", "765432109876543211"]
    assert any("접수(codex)" in s and "#501" in s for s in sent)
