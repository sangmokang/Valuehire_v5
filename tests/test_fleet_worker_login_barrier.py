"""fleet_worker 1층 코드 장벽 — 영수증 BLOCKED 시 검색 executor 호출 0 (RED #639).

프롬프트 RED 목록 1·3·12 + 레거시 portal_login 제거(우선순위 1) 고정.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tools.multi_position_sourcing import fleet_worker as fw
from tools.multi_position_sourcing import login_barrier as lb
from tools.multi_position_sourcing import session_guard
from tools.multi_position_sourcing.fleet_worker import FleetWorker
from tools.multi_position_sourcing.session_guard import BrowserTargetRef

NOW = int(datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc).timestamp())
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _job(skill="aisearch", params=None, machine="macmini"):
    return {
        "id": 7,
        "skill": skill,
        "machine": machine,
        "position_url": "https://app.clickup.com/t/123" if skill != "login" else "",
        "params": params or {},
        "requested_by": "owner",
        "role": "owner",
        "status": "queued",
    }


def _write_valid_receipts(tmp_path: Path, channels) -> Path:
    rdir = tmp_path / "login_receipts"
    rdir.mkdir(exist_ok=True)
    for ch in channels:
        evidence_dir = (tmp_path / f"{ch}-evidence").resolve()
        evidence_dir.mkdir(exist_ok=True)
        shot = evidence_dir / "viewport.png"
        text = evidence_dir / "visible-text.txt"
        manifest = evidence_dir / "manifest.json"
        shot.write_bytes(PNG)
        text.write_text("authenticated account marker", encoding="utf-8")
        evidence = {
            "status": "saved",
            "capture_status": "saved",
            "site": ch,
            "task": "login",
            "mode": "evidence",
            "url": {
                "saramin": "https://www.saramin.co.kr/zf_user/",
                "jobkorea": "https://www.jobkorea.co.kr/",
                "linkedin_rps": "https://www.linkedin.com/talent/",
            }[ch],
            "profile_url": "",
            "screenshot_path": str(shot),
            "text_path": str(text),
            "manifest_path": str(manifest),
            "screenshot_sha256": hashlib.sha256(PNG).hexdigest(),
            "visible_text_sha256": hashlib.sha256(text.read_bytes()).hexdigest(),
            "captured_at": "2026-07-25T11:59:00Z",
            "position_id": "",
            "candidate_index": 0,
            "archive_row_id": None,
            "archive_db_path": "",
            "endpoint": "http://127.0.0.1:9311",
            "profile_path": str(Path.cwd().resolve()),
            "browser_pid": 4242,
            "target_id": "T1",
        }
        manifest.write_text(json.dumps(evidence), encoding="utf-8")
        (rdir / f"{ch}.json").write_text(json.dumps({
            "schema_version": 1,
            "channel": ch,
            "state": "AUTHENTICATED",
            "ready": True,
            "host": "macmini",
            "target_id": "T1",
            "endpoint": "http://127.0.0.1:9311",
            "profile_path": str(Path.cwd().resolve()),
            "browser_pid": 4242,
            "last_verified_at": (
                datetime.fromtimestamp(NOW, tz=timezone.utc) - timedelta(seconds=30)
            ).isoformat(),
            "owner_activity_detected": False,
            "proof_names": ["marker"],
            "mutation_count": 0,
            "capture_status": "saved",
            "screenshot_path": str(shot),
            "text_path": str(text),
            "manifest_path": str(manifest),
            "screenshot_sha256": evidence["screenshot_sha256"],
            "text_sha256": evidence["visible_text_sha256"],
            "evidence": evidence,
        }), encoding="utf-8")
    return rdir


class FakeQueue:
    def __init__(self, job):
        self._job = job
        self.released = []

    def enqueue(self, payload):
        return {"id": 99, **payload}

    def claim_next(self, machine):
        j, self._job = self._job, None
        return j

    def release(self, job_id, status, *, result_summary="", error=""):
        self.released.append((job_id, status, result_summary, error))
        return [{"id": job_id, "status": status}]


@pytest.fixture(autouse=True)
def _quiet_notify(monkeypatch):
    monkeypatch.setattr(
        session_guard,
        "resolve_existing_target",
        lambda site, *, target_id=None, **_kwargs: BrowserTargetRef(
            site=site,
            endpoint="http://127.0.0.1:9311",
            target_id=str(target_id or ""),
            websocket_url=f"ws://127.0.0.1:9311/devtools/page/{target_id}",
            initial_url={
                "saramin": "https://www.saramin.co.kr/zf_user/",
                "jobkorea": "https://www.jobkorea.co.kr/",
                "linkedin_rps": "https://www.linkedin.com/talent/",
            }[site],
            profile_path=str(Path.cwd().resolve()),
            browser_pid=4242,
        ),
    )
    monkeypatch.setattr(
        lb,
        "_live_authenticated_target",
        lambda site, target_id: session_guard.resolve_existing_target(
            site, target_id=target_id
        ),
        raising=False,
    )
    with patch.object(fw, "discord_notify", lambda job, text: None):
        yield


def _run_worker(job, receipt_dir, notes=None, executor_stdout="ok"):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append([str(c) for c in cmd])
        return SimpleNamespace(stdout=executor_stdout, stderr="", returncode=0)

    notes = notes if notes is not None else []
    with patch.object(fw.subprocess, "run", fake_run), \
         patch.object(fw.time, "time", lambda: float(NOW)), \
         patch.object(fw, "job_url_block_reason", lambda job: None), \
         patch.object(lb, "default_receipt_dir", lambda: Path(receipt_dir)):
        q = FakeQueue(job)
        w = FleetWorker(machine="macmini", queue=q,
                        notifier=lambda j, t: notes.append(t))
        status = w.run_once()
    return status, q, calls, notes


def test_no_receipts_means_zero_executor_calls(tmp_path):
    status, q, calls, notes = _run_worker(_job(), tmp_path / "empty")
    assert status == "failed"
    assert calls == [], "장벽 BLOCKED — 어떤 서브프로세스도 실행되면 안 됨"
    assert q.released[-1][1] == "failed"
    joined = "\n".join(notes)
    assert "로그인" in joined
    assert "paused_for_human" not in joined
    assert "session_guard human-auth" not in joined
    assert "fleet-resume" not in joined


def test_partial_receipts_block_humansearch(tmp_path):
    rdir = _write_valid_receipts(tmp_path, ["saramin"])  # jobkorea 누락
    job = _job(skill="humansearch",
               params={"channels": ["saramin", "jobkorea"],
                       "search_urls": ["https://www.saramin.co.kr/x"]})
    status, q, calls, notes = _run_worker(job, rdir)
    assert status == "failed"
    assert calls == []


def test_legacy_portal_login_is_never_invoked(tmp_path):
    status, q, calls, notes = _run_worker(_job(), tmp_path / "empty")
    flat = " ".join(" ".join(c) for c in calls)
    assert "portal_login" not in flat
    assert not hasattr(fw, "_run_login_preflight"), (
        "레거시 portal_login preflight 는 제거돼야 한다 — "
        "정식 경로는 session_guard human-auth")


def test_model_pass_string_does_not_bypass(tmp_path):
    job = _job(params={"note": "LOGIN_BARRIER=PASS"})
    status, q, calls, notes = _run_worker(job, tmp_path / "empty")
    assert status == "failed"
    assert calls == []


def test_valid_receipts_let_executor_run_once(tmp_path):
    rdir = _write_valid_receipts(tmp_path, ["saramin", "jobkorea"])
    status, q, calls, notes = _run_worker(_job(), rdir)
    assert status != "paused_for_human"
    assert len(calls) >= 1, "PASS 면 기존 정식 executor 가 실행돼야 함(counter-AC)"


def test_blocked_notice_names_exact_human_action(tmp_path):
    rdir = tmp_path / "login_receipts"
    rdir.mkdir()
    (rdir / "linkedin_rps.json").write_text(json.dumps({
        "schema_version": 1,
        "channel": "linkedin_rps",
        "state": "HUMAN_AUTH",
        "challenge_verified": True,
        "challenge_type": "captcha",
        "target_id": "T1",
        "proof_names": ["captcha_visible"],
    }), encoding="utf-8")
    job = _job(skill="url",
               params={"search_urls": ["https://www.linkedin.com/talent/search"]})
    status, q, calls, notes = _run_worker(job, rdir)
    assert status == "paused_for_human"
    joined = "\n".join(notes)
    assert "session_guard" in joined and "linkedin_rps" in joined, (
        "필요한 사람 조치(session_guard human-auth)와 채널을 정확히 안내해야 함")


def test_auth_conflict_is_terminal_without_human_pause_or_resume(tmp_path):
    rdir = tmp_path / "login_receipts"
    rdir.mkdir()
    (rdir / "linkedin_rps.json").write_text(json.dumps({
        "schema_version": 1,
        "channel": "linkedin_rps",
        "state": "AUTH_CONFLICT",
        "conflict_verified": True,
        "conflict_type": "multiple_authenticated_machines",
        "authenticated_machine_count": 2,
        "proof_names": ["fleet_snapshot"],
    }), encoding="utf-8")
    status, q, calls, notes = _run_worker(
        _job(skill="url", params={
            "search_urls": ["https://www.linkedin.com/talent/search"],
        }),
        rdir,
    )
    assert status == "failed"
    assert q.released[-1][1] == "failed"
    assert calls == []
    joined = "\n".join(notes)
    assert "AUTH_CONFLICT" in joined
    assert "paused_for_human" not in joined
    assert "session_guard human-auth" not in joined
    assert "fleet-resume" not in joined


def test_human_auth_label_without_positive_challenge_proof_is_handoff(tmp_path):
    rdir = tmp_path / "login_receipts"
    rdir.mkdir()
    (rdir / "linkedin_rps.json").write_text(json.dumps({
        "schema_version": 1,
        "channel": "linkedin_rps",
        "state": "HUMAN_AUTH",
    }), encoding="utf-8")
    status, q, calls, notes = _run_worker(
        _job(skill="url", params={
            "search_urls": ["https://www.linkedin.com/talent/search"],
        }),
        rdir,
    )
    assert status == "failed"
    assert q.released[-1][1] == "failed"
    assert calls == []
    joined = "\n".join(notes)
    assert "paused_for_human" not in joined
    assert "session_guard human-auth" not in joined
    assert "fleet-resume" not in joined


def test_executor_pause_marker_without_challenge_evidence_is_terminal(tmp_path):
    rdir = _write_valid_receipts(tmp_path, ["saramin", "jobkorea"])
    status, q, calls, notes = _run_worker(
        _job(),
        rdir,
        executor_stdout="PAUSED_FOR_HUMAN: unsupported assertion",
    )
    assert calls, "로그인 장벽을 통과한 뒤 실제 executor 출력 경로를 검사해야 함"
    assert status == "failed"
    assert q.released[-1][1] == "failed"
    joined = "\n".join(notes)
    assert "fleet-resume" not in joined
