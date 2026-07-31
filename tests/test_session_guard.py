"""Session guard policy: no cookies, exact DOM proof, guarded keepalive."""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from tools.multi_position_sourcing import session_guard
from tools.multi_position_sourcing.session_guard import (
    AuthObservation,
    KEEPALIVE_INTERVAL_SECONDS,
    PROBE_URLS,
    load_safe_keepalive_target,
    keepalive_due,
    read_auth_observation,
    wait_for_human_auth,
)


def test_intervals_are_conservative() -> None:
    assert KEEPALIVE_INTERVAL_SECONDS["saramin"] <= 900
    assert KEEPALIVE_INTERVAL_SECONDS["jobkorea"] <= 900
    assert KEEPALIVE_INTERVAL_SECONDS["linkedin_rps"] == 1800


def test_due_only_after_interval() -> None:
    assert not keepalive_due("saramin", last_at=1000.0, now=1899.0)
    assert keepalive_due("saramin", last_at=1000.0, now=1900.0)
    assert keepalive_due("saramin", last_at=None, now=42.0)


def test_probe_urls_are_https_and_jobkorea_keeps_canonical_case() -> None:
    assert PROBE_URLS["jobkorea"] == "https://www.jobkorea.co.kr/Corp/Person/Find"
    assert all(url.startswith("https://") for url in PROBE_URLS.values())


def test_production_session_guard_has_no_cookie_read_or_snapshot_path() -> None:
    source = inspect.getsource(session_guard)
    for forbidden in (
        "Storage.getCookies",
        "Network.getCookies",
        "save_cookie_snapshot",
        "fetch_cookies_via_cdp",
        "run_keepalive_once",
    ):
        assert forbidden not in source


def test_auth_probe_returns_only_boolean_evidence_not_body_text() -> None:
    class Tab:
        script = ""

        def eval(self, script: str):
            self.script = script
            return {
                "url": "https://www.linkedin.com/talent/home",
                "hasChallenge": False,
                "hasLogout": False,
                "hasValueConnect": False,
                "saraminSearch": False,
                "jobkoreaSearch": False,
                "linkedinSearch": True,
                "linkedinAccount": True,
            }

    tab = Tab()
    observation = read_auth_observation(tab, "linkedin_rps")

    assert observation.authenticated is True
    assert observation.challenge is False
    assert observation.proof_names == (
        "talent_surface",
        "recruiter_account",
        "recruiter_search",
    )
    assert "text:" not in tab.script
    assert ".slice(0, 50000)" not in tab.script
    assert "bodyText" in tab.script  # evaluated inside the page; never returned
    assert "folded.includes('로그아웃')" not in tab.script
    assert "accountControls" in tab.script


def test_resume_body_words_do_not_authenticate_without_account_controls() -> None:
    class Tab:
        def eval(self, _script: str):
            return {
                "url": "https://www.jobkorea.co.kr/corp/person/find/resume/view?rNo=2",
                "hasChallenge": False,
                "hasSessionConflict": False,
                "hasLogout": False,
                "hasValueConnect": False,
                "saraminSearch": False,
                "jobkoreaSearch": False,
                "linkedinSearch": False,
                "linkedinAccount": False,
            }

    observation = read_auth_observation(Tab(), "jobkorea")

    assert observation.authenticated is False
    assert "profile_detail" in observation.proof_names


def test_linkedin_talent_projects_account_marker_is_authenticated_without_search_link() -> None:
    class Tab:
        def eval(self, _script: str):
            return {
                "url": "https://www.linkedin.com/talent/projects",
                "hasChallenge": False,
                "hasLogout": False,
                "hasValueConnect": False,
                "saraminSearch": False,
                "jobkoreaSearch": False,
                "linkedinSearch": False,
                "linkedinAccount": True,
            }

    observation = read_auth_observation(Tab(), "linkedin_rps")

    assert observation.authenticated is True
    assert observation.proof_names == ("talent_surface", "recruiter_account")


@pytest.mark.parametrize(
    ("url", "multiple_signins"),
    [
        (
            "https://www.linkedin.com/enterprise-authentication/sessions",
            False,
        ),
        ("https://www.linkedin.com/talent/home", True),
    ],
)
def test_linkedin_multiple_signin_is_terminal_auth_conflict_not_human_challenge(
    url: str,
    multiple_signins: bool,
) -> None:
    class Tab:
        def eval(self, _script: str):
            return {
                "url": url,
                "hasChallenge": False,
                "hasSessionConflict": multiple_signins or "enterprise-authentication/sessions" in url,
                "hasLogout": False,
                "hasValueConnect": False,
                "saraminSearch": False,
                "jobkoreaSearch": False,
                "linkedinSearch": False,
                "linkedinAccount": False,
            }

    observation = read_auth_observation(Tab(), "linkedin_rps")

    assert observation.auth_conflict is True
    assert observation.challenge is False
    assert observation.authenticated is False
    assert observation.proof_names == ("session_conflict",)


def test_human_auth_wait_returns_session_conflict_without_owner_poll_or_sleep() -> None:
    observation = AuthObservation(
        authenticated=False,
        challenge=False,
        url="https://www.linkedin.com/enterprise-authentication/sessions",
        proof_names=("session_conflict",),
        auth_conflict=True,
    )

    result = wait_for_human_auth(
        auth_probe=lambda: observation,
        owner_snapshot=lambda: pytest.fail("terminal conflict must not poll owner state"),
        sleep=lambda _seconds: pytest.fail("terminal conflict must not wait or retry"),
        stop_requested=lambda: False,
    )

    assert result is observation


def test_linkedin_authwall_is_an_allowed_existing_challenge_surface() -> None:
    ref = session_guard.resolve_existing_target(
        "linkedin_rps",
        target_id="authwall-target",
        managed_endpoint_resolver=lambda _site: "http://127.0.0.1:9225",
        list_pages=lambda _endpoint: [{
            "id": "authwall-target",
            "type": "page",
            "url": "https://www.linkedin.com/authwall?trk=talent",
            "webSocketDebuggerUrl": (
                "ws://127.0.0.1:9225/devtools/page/authwall-target"
            ),
        }],
    )

    assert ref.target_id == "authwall-target"


def _safe_payload() -> dict[str, object]:
    return {
        "target_id": "target-exact",
        "source_url": "https://www.linkedin.com/talent/home",
        "selector": 'a[href="https://www.linkedin.com/talent/projects"]',
        "destination_url": "https://www.linkedin.com/talent/projects",
        "method": "GET",
        "target_attr": "_self",
        "download": False,
        "dedicated_tab": True,
        "clean_form": True,
        "previously_opened_free": True,
        "risk_labels": [],
    }


def test_safe_target_file_has_exact_protected_schema() -> None:
    with TemporaryDirectory(prefix="vh_safe_target_") as root:
        path = Path(root) / "safe.json"
        path.write_text(json.dumps(_safe_payload()), encoding="utf-8")
        os.chmod(path, 0o600)

        target = load_safe_keepalive_target(path)

    assert target.target_id == "target-exact"
    assert target.previously_opened_free is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update({"cookie": "secret"}),
        lambda data: data.update({"method": "POST"}),
        lambda data: data.update({"previously_opened_free": "true"}),
    ],
)
def test_safe_target_file_rejects_extra_or_wrong_typed_fields(mutate) -> None:
    payload = _safe_payload()
    mutate(payload)
    with TemporaryDirectory(prefix="vh_safe_target_bad_") as root:
        path = Path(root) / "safe.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(path, 0o600)
        with pytest.raises(ValueError):
            load_safe_keepalive_target(path)


def test_safe_target_file_rejects_symlink_and_group_writable_record() -> None:
    with TemporaryDirectory(prefix="vh_safe_target_mode_") as root:
        real = Path(root) / "real.json"
        real.write_text(json.dumps(_safe_payload()), encoding="utf-8")
        os.chmod(real, 0o620)
        with pytest.raises(ValueError, match="protected regular file"):
            load_safe_keepalive_target(real)

        os.chmod(real, 0o600)
        link = Path(root) / "link.json"
        link.symlink_to(real)
        with pytest.raises(ValueError, match="protected regular file"):
            load_safe_keepalive_target(link)


# --- LinkedIn Recruiter 계정 마커 드리프트 회귀 (2026-07-31 라이브 사고) ---
#
# humansearch 가 후보 20명을 수집하고도 첫 프로필 증거 저장에서
# BrowserEvidenceError("authenticated browser evidence required") 로 전부 멈췄다.
# 로그인은 정상인데 read_auth_observation 의 Recruiter 계정 마커 selector 가
# LinkedIn DOM 변경으로 더 이상 존재하지 않아 authenticated=False 가 됐다.
# 기존 테스트는 linkedinAccount 를 mock 으로 주입해서 selector 드리프트를 못 잡았다.

_LIVE_NAV_FIXTURE = (
    Path(__file__).parent / "fixtures" / "linkedin_recruiter_nav_attrs_2026-07-31.json"
)


def _live_recruiter_nav_attributes() -> frozenset[str]:
    data = json.loads(_LIVE_NAV_FIXTURE.read_text(encoding="utf-8"))
    return frozenset(data["visible_data_attributes"])


def _attribute_names_in_selectors(selectors: tuple[str, ...]) -> frozenset[str]:
    names: set[str] = set()
    for selector in selectors:
        for part in selector.split(","):
            part = part.strip()
            if part.startswith("[") and part.endswith("]"):
                names.add(part[1:-1].split("=")[0].strip())
    return frozenset(names)


def test_linkedin_recruiter_account_selectors_match_live_recruiter_nav() -> None:
    """계정 증명 selector 중 최소 하나는 라이브 Recruiter nav 에 실제로 존재해야 한다."""
    matched = _attribute_names_in_selectors(
        session_guard.LINKEDIN_RECRUITER_ACCOUNT_SELECTORS
    ) & _live_recruiter_nav_attributes()
    assert matched, (
        "Recruiter 계정 마커가 라이브 DOM 과 어긋남 — "
        f"selectors={session_guard.LINKEDIN_RECRUITER_ACCOUNT_SELECTORS}"
    )


def test_linkedin_account_probe_script_uses_the_shared_selector_constant() -> None:
    """주입 스크립트가 상수를 그대로 써야 한다(이중 정의 금지)."""
    source = inspect.getsource(read_auth_observation)
    for selector in session_guard.LINKEDIN_RECRUITER_ACCOUNT_SELECTORS:
        assert selector in source, f"probe script 에 {selector!r} 가 없음"
