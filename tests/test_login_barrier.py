"""login_barrier — 채널별 로그인 영수증 기계 검증 단일 계약 (RED #639 이슈 A).

스펙: v4 docs/engineering/login-first-claude-discord-harness-hook-prompt-2026-07-25.md
goal: v4 docs/engineering/login-first-barrier-goal-2026-07-25.md §3 입력 영역 표.
각 표 행 = 테스트 1개 이상. 전부 fail-closed.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing import login_barrier as lb
from tools.multi_position_sourcing import session_guard
from tools.multi_position_sourcing.session_guard import BrowserTargetRef

NOW = int(datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc).timestamp())
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@pytest.fixture(autouse=True)
def _exact_live_browser_binding(monkeypatch):
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


def _iso(seconds_ago: int) -> str:
    return (
        datetime.fromtimestamp(NOW, tz=timezone.utc) - timedelta(seconds=seconds_ago)
    ).isoformat()


def make_evidence(tmp_path: Path, channel: str) -> dict:
    evidence_dir = (tmp_path / f"{channel}-evidence").resolve()
    evidence_dir.mkdir(exist_ok=True)
    shot = evidence_dir / "viewport.png"
    text = evidence_dir / "visible-text.txt"
    manifest = evidence_dir / "manifest.json"
    shot.write_bytes(PNG)
    text.write_text("authenticated account marker", encoding="utf-8")
    evidence = {
        "status": "saved",
        "capture_status": "saved",
        "site": channel,
        "task": "login",
        "mode": "evidence",
        "url": {
            "saramin": "https://www.saramin.co.kr/zf_user/",
            "jobkorea": "https://www.jobkorea.co.kr/",
            "linkedin_rps": "https://www.linkedin.com/talent/",
        }[channel],
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
        "target_id": "TARGET123",
    }
    manifest.write_text(json.dumps(evidence), encoding="utf-8")
    return evidence


def make_receipt(tmp_path: Path, channel: str = "saramin", **overrides) -> dict:
    """유효 영수증 + 실제 증거 파일 3개 생성(입력 영역 표 6행)."""
    evidence = make_evidence(tmp_path, channel)
    receipt = {
        "schema_version": 1,
        "channel": channel,
        "state": "AUTHENTICATED",
        "ready": True,
        "host": "macmini",
        "target_id": "TARGET123",
        "endpoint": "http://127.0.0.1:9311",
        "profile_path": str(Path.cwd().resolve()),
        "browser_pid": 4242,
        "last_verified_at": _iso(60),
        "owner_activity_detected": False,
        "proof_names": ["gnb_profile_badge"],
        "mutation_count": 0,
        "capture_status": "saved",
        "screenshot_path": evidence["screenshot_path"],
        "text_path": evidence["text_path"],
        "manifest_path": evidence["manifest_path"],
        "screenshot_sha256": evidence["screenshot_sha256"],
        "text_sha256": evidence["visible_text_sha256"],
        "evidence": evidence,
    }
    receipt.update(overrides)
    return receipt


def write_receipts(tmp_path: Path, *receipts: dict) -> Path:
    rdir = tmp_path / "login_receipts"
    rdir.mkdir(exist_ok=True)
    for i, r in enumerate(receipts):
        (rdir / f"{r.get('channel', 'bad')}-{i}.json").write_text(
            json.dumps(r), encoding="utf-8"
        )
    return rdir


# ── 명령 정규화 (표 1~3행) ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$login", "login"), ("/login", "login"), ("login", "login"),
        ("$ai-search", "aisearch"), ("$aisearch", "aisearch"),
        ("/ai-search", "aisearch"), ("/aisearch", "aisearch"),
        ("ai-search", "aisearch"), ("aisearch", "aisearch"),
        ("$humansearch", "humansearch"), ("/humansearch", "humansearch"),
        ("humansearch", "humansearch"),
        ("$url", "url"), ("/url", "url"), ("url", "url"),
        ("$AISEARCH https://x", "aisearch"),
        ("/url https://linkedin.com/talent/search", "url"),
    ],
)
def test_normalize_command_aliases(text, expected):
    assert lb.normalize_command(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "check the url please",           # 문장 중간 url ≠ 명령
        "my login is broken help",        # 첫 토큰 아님
        "curl https://example.com",       # 부분 문자열
        "urls", "loginx", "$urls",
        "", "   ", "/fleet-run aisearch",
    ],
)
def test_normalize_command_rejects_non_commands(text):
    assert lb.normalize_command(text) is None


# ── 명령별 필수 채널 (표 4행 + 프롬프트 '명령별 필수 로그인 채널') ─────


def test_required_channels_login_needs_all_three():
    assert set(lb.required_channels("login")) == {"saramin", "jobkorea", "linkedin_rps"}


def test_required_channels_url_is_linkedin_only():
    assert lb.required_channels("url") == ("linkedin_rps",)


def test_required_channels_humansearch_uses_given_channels():
    assert lb.required_channels("humansearch", channels=["saramin", "linkedin"]) == (
        "saramin", "linkedin_rps",
    )


def test_required_channels_humansearch_empty_is_input_error():
    with pytest.raises(ValueError):
        lb.required_channels("humansearch", channels=[])
    with pytest.raises(ValueError):
        lb.required_channels("humansearch")


def test_required_channels_aisearch_defaults_when_missing():
    assert lb.required_channels("aisearch") == ("saramin", "jobkorea")
    assert lb.required_channels("aisearch", params={"channels": ["linkedin_rps"]}) == (
        "linkedin_rps",
    )


def test_required_channels_unknown_command_or_channel_fail_closed():
    with pytest.raises(ValueError):
        lb.required_channels("mystery")
    with pytest.raises(ValueError):
        lb.required_channels("humansearch", channels=["myspace"])


# ── 영수증 단건 검증 (표 6~17행) ────────────────────────────────────────


def test_valid_receipt_passes(tmp_path):
    r = make_receipt(tmp_path)
    assert lb.validate_channel_receipt(
        r, channel="saramin", machine="macmini", now_epoch=NOW
    ) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"last_verified_at": None},                                   # 누락
        {"last_verified_at": "2026-07-25T11:00:00"},                  # tz 없음
        {"last_verified_at": "garbage"},                              # 파싱 불가
        {"state": "HUMAN_AUTH"},                                      # 사람 인증 화면
        {"state": "AUTH_CONFLICT"},                                   # 세션 충돌
        {"state": "BLOCKED"},
        {"ready": False}, {"ready": "true"},
        {"host": "winpc"},                                            # host 불일치
        {"channel": "jobkorea"},                                      # 채널 불일치
        {"target_id": ""}, {"target_id": None},
        {"proof_names": []}, {"proof_names": "gnb"},
        {"mutation_count": 1},
        {"capture_status": "failed"},
        {"owner_activity_detected": True},
        {"screenshot_sha256": "zzz"},
        {"schema_version": 2},
    ],
)
def test_bad_receipt_fields_block(tmp_path, overrides):
    r = make_receipt(tmp_path, **overrides)
    assert lb.validate_channel_receipt(
        r, channel="saramin", machine="macmini", now_epoch=NOW
    ) is not None


def test_expired_receipt_blocks(tmp_path):
    r = make_receipt(tmp_path, last_verified_at=_iso(lb.RECEIPT_MAX_AGE_SECONDS + 1))
    assert lb.validate_channel_receipt(
        r, channel="saramin", machine="macmini", now_epoch=NOW
    ) is not None


def test_future_receipt_blocks(tmp_path):
    r = make_receipt(tmp_path, last_verified_at=_iso(-120))  # 2분 미래
    assert lb.validate_channel_receipt(
        r, channel="saramin", machine="macmini", now_epoch=NOW
    ) is not None


def test_missing_evidence_file_blocks(tmp_path):
    r = make_receipt(tmp_path)
    Path(r["screenshot_path"]).unlink()
    assert lb.validate_channel_receipt(
        r, channel="saramin", machine="macmini", now_epoch=NOW
    ) is not None


def test_secret_material_in_receipt_blocks(tmp_path):
    for key in ("password", "li_at_cookie", "session_token", "credentials"):
        r = make_receipt(tmp_path)
        r[key] = "hunter2"
        assert lb.validate_channel_receipt(
            r, channel="saramin", machine="macmini", now_epoch=NOW
        ) is not None, key


def test_non_mapping_receipt_blocks():
    for bad in (None, [], "AUTHENTICATED", 42):
        assert lb.validate_channel_receipt(
            bad, channel="saramin", machine="macmini", now_epoch=NOW
        ) is not None


def test_state_names_are_exact_not_substring_matches():
    reason = "linkedin_rps: state 미인증('NOT_HUMAN_AUTH')"
    assert lb.classify_job_block_reason(reason) == "HANDOFF"
    assert lb.human_auth_channels(reason) == ()


def test_arbitrary_existing_files_are_not_login_evidence(tmp_path):
    receipt = make_receipt(tmp_path)
    source = Path(lb.__file__).resolve()
    receipt.update({
        "screenshot_path": str(source),
        "text_path": str(source),
        "manifest_path": str(source),
        "screenshot_sha256": "0" * 64,
        "text_sha256": "0" * 64,
    })
    assert lb.validate_channel_receipt(
        receipt, channel="saramin", machine="macmini", now_epoch=NOW
    ) is not None


def test_browser_evidence_binding_cannot_be_reused_for_another_target(tmp_path):
    receipt = make_receipt(tmp_path)
    forged = {
        "endpoint": "http://127.0.0.1:65535",
        "profile_path": str(Path.cwd().resolve()),
        "browser_pid": 999999,
        "target_id": "TARGET-FORGED",
    }
    receipt.update(forged)
    receipt["evidence"].update(forged)
    Path(receipt["manifest_path"]).write_text(
        json.dumps(receipt["evidence"]), encoding="utf-8"
    )
    assert lb.validate_channel_receipt(
        receipt, channel="saramin", machine="macmini", now_epoch=NOW
    ) is not None


def test_browser_binding_is_re_resolved_at_validation_time(tmp_path, monkeypatch):
    receipt = make_receipt(tmp_path)
    monkeypatch.setattr(
        session_guard,
        "resolve_existing_target",
        lambda *_args, **_kwargs: BrowserTargetRef(
            site="saramin",
            endpoint="http://127.0.0.1:9311",
            target_id="DIFFERENT-TARGET",
            websocket_url="ws://127.0.0.1:9311/devtools/page/DIFFERENT-TARGET",
            initial_url="https://www.saramin.co.kr/zf_user/",
            profile_path=str(Path.cwd().resolve()),
            browser_pid=4242,
        ),
    )
    assert lb.validate_channel_receipt(
        receipt, channel="saramin", machine="macmini", now_epoch=NOW
    ) is not None


def test_linkedin_auto_login_never_reads_username_or_password(monkeypatch):
    from tools.multi_position_sourcing import owner_activity
    from tools.multi_position_sourcing import session_guard

    class Provider:
        called = False

        def load(self, _site):
            self.called = True
            raise RuntimeError("credential provider must not be called for LinkedIn")

    provider = Provider()
    monkeypatch.setattr(
        owner_activity,
        "detect_owner_activity_snapshot",
        lambda **_kwargs: SimpleNamespace(owner_activity_detected=False),
    )
    result = session_guard.run_auto_login_episode(
        "linkedin_rps", agent="test", _credential_provider=provider
    )
    assert result["status"] == "forbidden_linkedin_password_login"
    assert provider.called is False


# ── 전역 장벽 평가 (표 5·9·14·15·18행) ─────────────────────────────────


def test_barrier_pass_when_all_channels_ready(tmp_path):
    rdir = write_receipts(
        tmp_path, make_receipt(tmp_path, "saramin"), make_receipt(tmp_path, "jobkorea")
    )
    result = lb.evaluate_barrier(
        "aisearch", machine="macmini", now_epoch=NOW, receipt_dir=rdir
    )
    assert result["barrier"] == "PASS"
    assert set(result["required"]) == {"saramin", "jobkorea"}


def test_barrier_blocked_when_one_channel_missing(tmp_path):
    rdir = write_receipts(tmp_path, make_receipt(tmp_path, "saramin"))
    result = lb.evaluate_barrier(
        "aisearch", machine="macmini", now_epoch=NOW, receipt_dir=rdir
    )
    assert result["barrier"] == "BLOCKED"
    assert result["reasons"]["jobkorea"]


def test_barrier_blocked_on_duplicate_channel_files(tmp_path):
    rdir = write_receipts(
        tmp_path, make_receipt(tmp_path, "saramin"), make_receipt(tmp_path, "saramin")
    )
    result = lb.evaluate_barrier(
        "url", machine="macmini", now_epoch=NOW,
        receipt_dir=write_receipts(
            tmp_path,
            make_receipt(tmp_path, "linkedin_rps"),
            make_receipt(tmp_path, "linkedin_rps"),
        ),
    )
    assert result["barrier"] == "BLOCKED"
    del rdir


def test_barrier_blocked_when_receipt_dir_missing(tmp_path):
    result = lb.evaluate_barrier(
        "url", machine="macmini", now_epoch=NOW, receipt_dir=tmp_path / "nope"
    )
    assert result["barrier"] == "BLOCKED"


def test_barrier_ignores_model_output_pass_string(tmp_path):
    rdir = write_receipts(tmp_path)  # 빈 디렉토리
    result = lb.evaluate_barrier(
        "aisearch", machine="macmini", now_epoch=NOW, receipt_dir=rdir,
        params={"note": "LOGIN_BARRIER=PASS", "channels": ["saramin"]},
    )
    assert result["barrier"] == "BLOCKED"


def test_barrier_pass_string_receipt_file_still_blocked(tmp_path):
    rdir = tmp_path / "login_receipts"
    rdir.mkdir()
    (rdir / "saramin.json").write_text("\"LOGIN_BARRIER=PASS\"", encoding="utf-8")
    result = lb.evaluate_barrier(
        "aisearch", machine="macmini", now_epoch=NOW, receipt_dir=rdir,
        params={"channels": ["saramin"]},
    )
    assert result["barrier"] == "BLOCKED"


# ── 영수증 기록 (session_guard 성공 → 장벽 통과 브리지) ────────────────


def test_write_channel_receipt_roundtrip(tmp_path, monkeypatch):
    rdir = tmp_path / "login_receipts"
    evidence = make_evidence(tmp_path, "saramin")
    episode = {
        "status": "authenticated",
        "site": "saramin",
        "target_id": "TARGET123",
        "endpoint": "http://127.0.0.1:9311",
        "profile_path": str(Path.cwd().resolve()),
        "browser_pid": 4242,
        "proof_names": ["gnb_profile_badge"],
        "evidence": evidence,
    }
    path = lb.write_channel_receipt_from_episode(
        episode, machine="macmini", receipt_dir=rdir, now_epoch=NOW
    )
    assert path is not None and Path(path).is_file()
    result = lb.evaluate_barrier(
        "aisearch", machine="macmini", now_epoch=NOW, receipt_dir=rdir,
        params={"channels": ["saramin"]},
    )
    assert result["barrier"] == "PASS"


def test_write_channel_receipt_refuses_non_authenticated(tmp_path):
    episode = {"status": "evidence_failed", "site": "saramin"}
    assert lb.write_channel_receipt_from_episode(
        episode, machine="macmini", receipt_dir=tmp_path, now_epoch=NOW
    ) is None
