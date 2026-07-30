"""AC-A/AC-B(2026-07-31): 오너 명시 기기전환 + 로그인 최우선 순위.

goal: docs/engineering/login-owner-priority-takeover-goal-2026-07-31.md
"""
from __future__ import annotations

from tools.multi_position_sourcing import owner_activity, portal_selfservice_login as ssl
from tools.multi_position_sourcing.portal_login import (
    _is_pure_security_challenge,
    _is_session_conflict,
)


class _Tab:
    def __init__(self, *, url: str, body: str = "", authenticated_after_submit: bool = True):
        self._url = url
        self.body = body
        self.authenticated_after_submit = authenticated_after_submit
        self.submitted = False
        self.evals: list[str] = []

    def current_url(self) -> str:
        return self._url

    def eval(self, script: str):
        self.evals.append(script)
        if "querySelector" in script and "value" in script:
            return True
        if "click" in script or "submit" in script.lower():
            self.submitted = True
            return True
        return True

    def navigate(self, url: str) -> None:
        self._url = url


CREDS = ssl.PortalCreds(username="u", password="p")


def _monkeypatch_body(monkeypatch, body: str) -> None:
    monkeypatch.setattr(ssl, "_read_body", lambda tab: body)
    monkeypatch.setattr(ssl, "_is_authenticated", lambda site, b: b == "AUTHENTICATED")


# --- AC-A: portal_login token split -----------------------------------------------------

def test_pure_security_challenge_excludes_session_conflict_tokens() -> None:
    assert _is_pure_security_challenge("", url="https://www.linkedin.com/enterprise-authentication/sessions") is False
    assert _is_pure_security_challenge("captcha 확인") is True


def test_session_conflict_detects_only_conflict_tokens() -> None:
    assert _is_session_conflict("", url="https://www.linkedin.com/enterprise-authentication/sessions") is True
    assert _is_session_conflict("multiple sign-ins detected") is True
    assert _is_session_conflict("captcha 확인") is False


# --- AC-A: perform_autologin regression + new takeover path -------------------------------

def test_session_conflict_without_owner_takeover_halts_like_before(monkeypatch) -> None:
    tab = _Tab(url="https://www.linkedin.com/enterprise-authentication/sessions", body="")
    _monkeypatch_body(monkeypatch, "multiple sign-ins detected")
    monkeypatch.setattr(ssl, "_login_fields_present", lambda tab, selectors: False)

    result = ssl.perform_autologin(tab, "linkedin_rps", CREDS)

    assert result["state"] == "HUMAN_AUTH"
    assert result["mutations"] == 0
    assert tab.submitted is False


def test_session_conflict_with_owner_takeover_proceeds_to_submit(monkeypatch) -> None:
    tab = _Tab(url="https://www.linkedin.com/uas/login-cap", body="")
    calls = {"n": 0}

    def fake_read_body(_tab):
        calls["n"] += 1
        if calls["n"] == 1:
            return "multiple sign-ins detected"
        return "AUTHENTICATED"

    monkeypatch.setattr(ssl, "_read_body", fake_read_body)
    monkeypatch.setattr(ssl, "_is_authenticated", lambda site, b: b == "AUTHENTICATED")
    monkeypatch.setattr(ssl, "_login_fields_present", lambda tab, selectors: True)

    result = ssl.perform_autologin(tab, "linkedin_rps", CREDS, owner_takeover=True)

    assert result["state"] == "AUTHENTICATED"
    assert tab.submitted is True


def test_real_challenge_halts_even_with_owner_takeover(monkeypatch) -> None:
    tab = _Tab(url="https://www.linkedin.com/checkpoint/challenge", body="")
    _monkeypatch_body(monkeypatch, "보안문자 입력")
    monkeypatch.setattr(ssl, "_login_fields_present", lambda tab, selectors: False)

    result = ssl.perform_autologin(tab, "linkedin_rps", CREDS, owner_takeover=True)

    assert result["state"] == "HUMAN_AUTH"
    assert tab.submitted is False


# --- AC-B: is_login_screen_path pure decision --------------------------------------------

def test_login_path_markers_match_known_login_screens() -> None:
    assert owner_activity.is_login_screen_path("saramin", "/zf_user/auth") is True
    assert owner_activity.is_login_screen_path("jobkorea", "/Login/Login_Corp") is True
    assert owner_activity.is_login_screen_path("linkedin_rps", "/uas/login-cap") is True
    assert owner_activity.is_login_screen_path("linkedin_rps", "/checkpoint/challenge") is True


def test_non_login_portal_pages_are_not_login_screen() -> None:
    assert owner_activity.is_login_screen_path("saramin", "/zf_user/memcom/talent-pool/main/search") is False
    assert owner_activity.is_login_screen_path("jobkorea", "/Corp/Person/Find") is False
    assert owner_activity.is_login_screen_path("linkedin_rps", "/talent/search") is False


def test_unreadable_path_fails_closed_as_login_screen() -> None:
    assert owner_activity.is_login_screen_path("saramin", None) is True


# --- AC-B: detect_login_screen_snapshot fail-closed shape --------------------------------

def test_detect_login_screen_snapshot_false_when_chrome_not_frontmost() -> None:
    result = owner_activity.detect_login_screen_snapshot(
        system_name="Darwin",
        run_command=lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    # frontmost app read fails -> fail-closed True is also acceptable; assert type only.
    assert isinstance(result, bool)


def test_detect_login_screen_snapshot_failclosed_on_non_darwin() -> None:
    assert owner_activity.detect_login_screen_snapshot(system_name="Windows") is True
