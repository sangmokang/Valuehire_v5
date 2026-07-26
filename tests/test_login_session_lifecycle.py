"""App 15 — keepalive, resume, and handoff share one lifecycle coordinator."""

from __future__ import annotations

import json

import pytest

from tools.multi_position_sourcing.login_session_lifecycle import coordinate_lifecycle


def _safe_target(tmp_path):
    path = tmp_path / "safe.json"
    path.write_text(json.dumps({
        "target_id": "target-1",
        "source_url": "https://www.saramin.co.kr/zf_user/member/persons/main",
        "selector": "a.keepalive",
        "destination_url": "https://www.saramin.co.kr/zf_user/member/persons/scrap",
        "method": "GET", "target_attr": "_self", "download": False,
        "dedicated_tab": True, "clean_form": True,
        "previously_opened_free": True, "risk_labels": [],
    }), encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.mark.parametrize(
    ("site", "elapsed", "due"),
    [("saramin", 899, False), ("jobkorea", 900, True),
     ("linkedin_rps", 1799, False), ("linkedin_rps", 1800, True)],
)
def test_keepalive_intervals_and_safe_target_default_skip(tmp_path, site, elapsed, due):
    calls = []
    result = coordinate_lifecycle(
        operation="keepalive", site=site, now=2000,
        last_verified_at=2000 - elapsed, last_keepalive_at=None,
        safe_target_path=_safe_target(tmp_path),
        job_id="job-1", target_id="target-1",
        expected_job_id="job-1", expected_target_id="target-1",
        lease_token="mine", current_lease_token="mine",
        keepalive_runner=lambda *_a, **_k: calls.append("run") or {
            "status": "ok", "mutations": 2, "restore_pending": False},
    )
    assert bool(calls) is due
    assert result["state"] == ("AUTHENTICATED" if due else "KEEPALIVE_SKIPPED")
    assert result["browser_close_count"] == 0


def test_missing_or_incomplete_safe_target_skips_without_navigation(tmp_path):
    calls = []
    bad = tmp_path / "bad.json"
    bad.write_text('{"destination_url":"https://evil.example/%252e%252e"}')
    result = coordinate_lifecycle(
        operation="keepalive", site="saramin", now=2000,
        last_verified_at=1000, safe_target_path=bad,
        keepalive_runner=lambda *_a, **_k: calls.append("run"),
    )
    assert result["state"] == "KEEPALIVE_SKIPPED"
    assert calls == []
    assert result["mutation_count"] == 0


def test_owner_activity_skips_keepalive_and_back_zero(tmp_path):
    calls = []
    result = coordinate_lifecycle(
        operation="keepalive", site="saramin", now=2000,
        last_verified_at=1000, safe_target_path=_safe_target(tmp_path),
        owner_active=True,
        keepalive_runner=lambda *_a, **_k: calls.append("click-or-back"),
    )
    assert result["state"] == "KEEPALIVE_SKIPPED"
    assert calls == []


@pytest.mark.parametrize(
    ("job", "target", "state", "resume"),
    [
        ("job-1", "target-1", "AUTHENTICATED", "KEEPALIVE"),
        ("job-2", "target-1", "TARGET_CHANGED", "DISCOVER"),
        ("job-1", "target-2", "TARGET_CHANGED", "DISCOVER"),
    ],
)
def test_resume_revalidates_existing_job_and_target(job, target, state, resume):
    result = coordinate_lifecycle(
        operation="resume", site="saramin", now=2000,
        job_id=job, target_id=target,
        expected_job_id="job-1", expected_target_id="target-1",
    )
    assert result["state"] == state
    assert result["resume_from"] == resume


@pytest.mark.parametrize("failure", (RuntimeError("boom"), KeyboardInterrupt()))
def test_error_and_ctrl_c_release_only_own_token_and_never_close_browser(failure):
    calls = []

    def runner(*_a, **_k):
        raise failure

    with pytest.raises(type(failure)):
        coordinate_lifecycle(
            operation="keepalive", site="saramin", now=2000,
            last_verified_at=1000, safe_target={"target_id": "target-1"},
            lease_token="mine", current_lease_token="mine",
            keepalive_runner=runner,
            disconnect=lambda: calls.append("disconnect"),
            release_lease=lambda: calls.append("release"),
            close_browser=lambda: calls.append("CLOSE"),
        )
    assert calls == ["disconnect", "release"]


def test_lost_lease_token_never_releases_someone_elses_lease():
    calls = []
    result = coordinate_lifecycle(
        operation="handoff", site="saramin", now=2000,
        lease_token="mine", current_lease_token="theirs",
        disconnect=lambda: calls.append("disconnect"),
        release_lease=lambda: calls.append("release"),
    )
    assert result["state"] == "LEASE_TOKEN_LOST"
    assert calls == ["disconnect"]
    assert result["browser_close_count"] == 0
