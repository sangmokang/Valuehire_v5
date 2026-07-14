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
    JobQueueClient,
    _env_config,
    cancel_job_payload,
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


@pytest.mark.parametrize("url", [
    "", None, "notaurl", "javascript:alert(1)", "ftp://x",
    "https://exa mple.com/x",   # V1: 공백 포함
    "https://./x",              # V1: 무의미 netloc
    "https://exa\tmple.com",
    "https://example.com:99999/x",  # V1 2R: 포트 범위 초과
    "https://a..b/x",               # V1 2R: 무의미 호스트
    "HTTPS://example.com/x",        # V1 4R: 대문자 스킴 — SQL CHECK 와 1:1 정합
    "Http://example.com/x",
])
def test_new_job_payload_rejects_bad_url(url):
    assert new_job_payload(**_ok_kwargs(position_url=url)) is None


def test_new_job_payload_rejects_unserializable_params():
    # V1: JSON 직렬화 불가 params 가 enqueue 단계 TypeError 로 새면 안 됨 — 입구에서 None
    assert new_job_payload(**_ok_kwargs(), params={"x": object()}) is None
    assert new_job_payload(**_ok_kwargs(), params={"x": {1, 2}}) is None
    assert new_job_payload(**_ok_kwargs(), params={"x": float("nan")}) is None  # V1 2R
    assert new_job_payload(**_ok_kwargs(), params={"x": float("inf")}) is None


def test_new_job_payload_url_parity_with_sql():
    # V1 3R: python↔SQL 규칙 일치 — 쿼리스트링/경로 내 '..' 는 양쪽 다 허용
    assert new_job_payload(**_ok_kwargs(position_url="https://example.com?x=1")) is not None
    assert new_job_payload(**_ok_kwargs(position_url="https://example.com/a..b")) is not None
    assert new_job_payload(**_ok_kwargs(position_url="https://example.com:65535/x")) is not None
    assert new_job_payload(**_ok_kwargs(position_url="https://example.com:0/x")) is None


def test_new_job_payload_rejects_bad_account_key():
    # V1 2R: 비문자열/공백 포함 account_key 가 DB text 경계까지 흘러가면 안 됨
    assert new_job_payload(**_ok_kwargs(), account_key={"seat": 1}) is None  # type: ignore[arg-type]
    assert new_job_payload(**_ok_kwargs(), account_key="seat 1") is None


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
        release_job_payload(9, "cancelled")     # 취소는 cancel_job 전용(V1 결함 4)
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


def test_cancel_payload():
    assert cancel_job_payload(3, "사장님 취소") == {"p_job_id": 3, "p_reason": "사장님 취소"}
    for bad in (0, -1, True, "3"):
        with pytest.raises(ValueError):
            cancel_job_payload(bad)  # type: ignore[arg-type]


# ── 클라이언트: 변조 방지 + env 짝 강제 (V1 결함 6·7) ────────────────

def _fake_client() -> JobQueueClient:
    return JobQueueClient(url="https://example.supabase.co", key="k")


def test_enqueue_rejects_tampered_payload(monkeypatch):
    c = _fake_client()
    calls = []
    monkeypatch.setattr(c, "_call", lambda *a, **k: calls.append(a) or [{"id": 1}])
    good = new_job_payload(**_ok_kwargs())
    tampered = dict(good, skill="send")          # 사후 변조
    with pytest.raises(ValueError):
        c.enqueue(tampered)
    tampered2 = dict(good, status="running")     # 상태 변조
    with pytest.raises(ValueError):
        c.enqueue(tampered2)
    assert calls == []                            # 무효 페이로드는 HTTP 자체가 안 나감
    assert c.enqueue(good) == {"id": 1}
    assert len(calls) == 1


def test_client_requires_url_key_pair():
    with pytest.raises(ValueError):
        JobQueueClient(url="https://example.supabase.co")   # 키만 빠짐
    with pytest.raises(ValueError):
        JobQueueClient(key="k")
    with pytest.raises(ValueError):
        JobQueueClient(url="https://example.supabase.co", key="  ")  # V1 2R: 공백 자격증명
    c = JobQueueClient(url=" https://example.supabase.co/ ", key=" k ")
    assert (c.url, c.key) == ("https://example.supabase.co", "k")


def test_env_config_rejects_whitespace_only_env(tmp_path, monkeypatch):
    # V1 3R: 공백만 든 환경변수가 빈 자격증명으로 채택되면 안 됨
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "   ")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "   ")
    empty = tmp_path / "empty"; empty.mkdir()
    (empty / ".env.local").write_text("")
    monkeypatch.setenv("VALUEHIRE_REPO_DIR", str(empty))
    try:
        url, key = _env_config()
        assert url.strip() and key.strip(), "공백 자격증명이 채택됨"
    except RuntimeError:
        pass  # 상위 폴더에도 짝이 없으면 명시적 실패 — 정상


def test_env_config_pairs_from_same_file(tmp_path, monkeypatch):
    # V1 결함 7: URL 과 키가 서로 다른 파일에서 섞이면 안 됨
    for k in ("NEXT_PUBLIC_SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(k, raising=False)
    half = tmp_path / "half"; half.mkdir()
    (half / ".env.local").write_text("NEXT_PUBLIC_SUPABASE_URL=https://half.supabase.co\n")
    monkeypatch.setenv("VALUEHIRE_REPO_DIR", str(half))
    # half 에는 짝이 없으므로 half 를 채택하지 않고 상위(실레포)로 넘어가거나,
    # 상위에도 없으면 RuntimeError — 어느 쪽이든 "half URL + 다른 파일 키" 조합은 금지.
    try:
        url, key = _env_config()
        assert not (url.startswith("https://half.") and key), "짝 없는 출처의 URL 이 채택됨"
    except RuntimeError:
        pass
    full = tmp_path / "full"; full.mkdir()
    (full / ".env.local").write_text(
        "NEXT_PUBLIC_SUPABASE_URL=https://full.supabase.co\nSUPABASE_SERVICE_ROLE_KEY=sk-full\n")
    monkeypatch.setenv("VALUEHIRE_REPO_DIR", str(full))
    url, key = _env_config()
    assert (url, key) == ("https://full.supabase.co", "sk-full")


# ── 마이그레이션 실체(배선) ──────────────────────────────────────────

def test_migration_file_contains_core_ddl():
    candidates = sorted((REPO / "supabase" / "migrations").glob("*fleet_jobs*.sql"))
    assert candidates, "fleet_jobs 마이그레이션 SQL 이 없습니다"
    raw = candidates[-1].read_text()
    # V2 지적: 주석의 문구만으로 니들이 충족되면 실제 SQL 회귀를 못 잡는다 — '--' 주석 제거 후 매칭
    sql = "\n".join(line.split("--", 1)[0] for line in raw.splitlines())
    for needle in (
        "create table if not exists public.jobs",
        "create table if not exists public.account_locks",
        "claim_next_job",
        "release_job",
        "for update skip locked",
        "enable row level security",
        "service_role",
        "jobs_transition_guard",     # V1 결함 2: DB 경계 전이 강제
        "jobs_lock_cleanup",         # V1 결함 3: 락 고아화 방지
        "cancel_job",                # V1 결함 4: 취소 전용 RPC
        "jobs_position_url_http_chk",
        "limit 1",                   # V1 결함 1: 커서 프리페치 회피(한 행씩 잠금)
        "jobs_insert_guard",         # V1 2R: INSERT 초기 상태 우회 차단
        "not exists",                # V1 2R: 락 충돌 후보 사전 필터(사재기 최소화)
        "between 1 and 65535",       # V1 3R: SQL 포트 범위(0·99999 거부)
        "'paused_for_human') then\n    delete from public.account_locks",
    ):
        assert needle in sql.lower(), f"마이그레이션에 '{needle}' 누락"


# ── 이슈 A(2026-07-15 goal §1) — params.followup_skill 검증 ──

def test_new_job_payload_validates_followup_skill():
    base = dict(machine="macmini", skill="url",
                position_url="https://career.wrtn.io/ko/o/172878",
                requested_by="814353841088757800:owner", role="owner")
    ok = new_job_payload(**base, params={"followup_skill": "aisearch"})
    assert ok is not None
    assert ok["params"]["followup_skill"] == "aisearch"
    assert new_job_payload(**base, params={"followup_skill": "not-a-skill"}) is None


# ── 이슈 B(2026-07-15 goal §2) — params.agent 검증 ──

def test_new_job_payload_validates_agent():
    base = dict(machine="macmini", skill="aisearch",
                position_url="https://app.clickup.com/t/abc",
                requested_by="814353841088757800:owner", role="owner")
    ok = new_job_payload(**base, params={"agent": "codex"})
    assert ok is not None and ok["params"]["agent"] == "codex"
    ok2 = new_job_payload(**base, params={"agent": "claude"})
    assert ok2 is not None
    assert new_job_payload(**base, params={"agent": "gpt4"}) is None
