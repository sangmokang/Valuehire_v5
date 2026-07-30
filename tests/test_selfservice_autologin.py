"""self-service raw-CDP 자동 로그인 (이슈 B) — 세션 보존 계약 준수 RED.

login 스킬 §4 + SOT-26 INV1/INV2:
- 기존 target 하나에서만 조작(새 page/context/browser 0회, close 0회).
- 일반 로그인 화면일 때만 저장 자격증명 1회 제출.
- 캡차·2FA·checkpoint·세션충돌이면 제출 0회로 사람에게 인계.
- 이미 로그인돼 있으면 mutation 0회.
- 비밀번호는 반환값·로그에 절대 넣지 않는다(호출자가 값을 보지 않는다).
"""
from __future__ import annotations

import pytest

from tools.multi_position_sourcing import portal_selfservice_login as ssl


class FakeTab:
    """duck-typed raw_cdp 대체 — close 류 메서드는 아예 없다(있으면 계약 위반)."""

    def __init__(self, script):
        self._script = list(script)  # (kind, payload) 시퀀스: navigate 후 body/url 변화
        self.evals = []
        self.navigations = []
        self._state = self._script.pop(0)

    # 세션 보존: 아래 3개가 호출되면 테스트가 즉시 깨지도록 존재 자체를 금지.
    def close(self):  # pragma: no cover
        raise AssertionError("close() 는 세션 보존 계약 위반")

    def navigate(self, url, wait_ms=4000):
        self.navigations.append(url)
        if self._script:
            self._state = self._script.pop(0)
        return {"ok": True}

    def current_url(self):
        return self._state["url"]

    def eval(self, expr):
        self.evals.append(expr)
        if expr == "location.href":
            return self._state["url"]
        if "innerText" in expr or "document.body" in expr:
            return self._state["body"]
        # fill/submit JS 는 성공 신호 반환
        if self._state.get("on_submit") and ("SUBMIT" in expr or "click" in expr):
            self._state = self._state["on_submit"]
        return True


def creds():
    return ssl.PortalCreds(username="corp-id", password="s3cr3t-pw")


LOGGED_IN = {"url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
             "body": "강상모 로그아웃 인재검색"}
LOGGED_OUT_FORM = {"url": "https://www.saramin.co.kr/zf_user/auth?ut=c",
                   "body": "로그인 회원가입 아이디 비밀번호",
                   "on_submit": LOGGED_IN}
CAPTCHA = {"url": "https://www.saramin.co.kr/zf_user/auth?ut=c",
           "body": "보안문자를 입력하세요 captcha"}


# ── 순수 판정 (표↔테스트) ────────────────────────────────────────────


def test_decide_already_authenticated():
    step = ssl.decide_login_step("saramin", LOGGED_IN["body"], LOGGED_IN["url"])
    assert step == "already_authenticated"


def test_decide_security_challenge():
    step = ssl.decide_login_step("saramin", CAPTCHA["body"], CAPTCHA["url"])
    assert step == "security_challenge"


def test_decide_ready_to_fill():
    step = ssl.decide_login_step("saramin", LOGGED_OUT_FORM["body"], LOGGED_OUT_FORM["url"])
    assert step == "fill_credentials"


# ── 세션 보존 조작 (기존 target·새 page 0·close 0) ─────────────────────


def test_already_authenticated_no_mutation():
    tab = FakeTab([LOGGED_IN])
    r = ssl.perform_autologin(tab, "saramin", creds())
    assert r["state"] == "AUTHENTICATED"
    assert tab.navigations == [], "이미 로그인 → 이동/제출 0회"
    assert not any("value" in e or "SUBMIT" in e for e in tab.evals)


def test_linkedin_talent_home_user_menu_is_authenticated_without_mutation():
    """실제 Recruiter 홈은 body에 '/talent' 문자열이 없어도 로그인된 화면이다."""
    tab = FakeTab([
        {
            "url": "https://www.linkedin.com/talent/home",
            "body": (
                "0 notifications total\n"
                "LinkedIn Talent Solutions\n"
                "Expand the user menu\n"
                "Value Connect - RPS\n"
                "Projects\n"
                "Recruiter search"
            ),
        }
    ])

    result = ssl.perform_autologin(
        tab, "linkedin_rps", creds(), sleep=lambda _seconds: None
    )

    assert result["state"] == "AUTHENTICATED"
    assert result["mutations"] == 0
    assert tab.navigations == []
    assert not any("value" in expr or "SUBMIT" in expr for expr in tab.evals)


@pytest.mark.parametrize(
    ("url", "body"),
    [
        (
            "http://www.linkedin.com/talent/home",
            "Expand the user menu\nValue Connect - RPS",
        ),
        (
            "https://linkedin.com.evil.example/talent/home",
            "Expand the user menu\nValue Connect - RPS",
        ),
        (
            "https://linkedin.com.evil.example/talent/home",
            "LinkedIn Recruiter /talent",
        ),
        (
            "https://www.linkedin.com/uas/login-cap",
            "Expand the user menu\nValue Connect - RPS",
        ),
    ],
)
def test_linkedin_auth_marker_cannot_authenticate_wrong_surface(url, body):
    step = ssl.decide_login_step("linkedin_rps", body, url)

    assert step == "fill_credentials"


def test_linkedin_session_conflict_wins_over_stale_authenticated_markers():
    step = ssl.decide_login_step(
        "linkedin_rps",
        "LinkedIn Recruiter /talent\nExpand the user menu\nmultiple sign-ins detected",
        "https://www.linkedin.com/enterprise-authentication/sessions",
    )

    assert step == "session_conflict"


def test_challenge_hands_off_without_submit():
    tab = FakeTab([{"url": "https://www.saramin.co.kr/zf_user/auth?ut=c", "body": "로그인 아이디"},
                   CAPTCHA])  # navigate 후 캡차 등장
    r = ssl.perform_autologin(tab, "saramin", creds())
    assert r["state"] == "HUMAN_AUTH"
    assert r["challenge_markers"] == ["보안문자", "captcha"]
    assert not any("SUBMIT" in e for e in tab.evals), "캡차면 제출 0회"


def test_normal_login_fills_once_and_verifies():
    tab = FakeTab([{"url": "https://www.saramin.co.kr/zf_user/auth?ut=c", "body": "로그인 아이디"},
                   LOGGED_OUT_FORM])
    r = ssl.perform_autologin(tab, "saramin", creds())
    assert r["state"] == "AUTHENTICATED"
    submits = [e for e in tab.evals if "SUBMIT" in e]
    assert len(submits) == 1, "제출은 정확히 1회"


def test_linkedin_existing_login_cap_form_is_used_without_navigation():
    logged_in = {
        "url": "https://www.linkedin.com/talent/home",
        "body": "LinkedIn Recruiter /talent",
    }
    form = {
        "url": "https://www.linkedin.com/uas/login-cap",
        "body": "LinkedIn 로그인 이메일 비밀번호",
        "on_submit": logged_in,
    }
    tab = FakeTab([form])

    result = ssl.perform_autologin(
        tab, "linkedin_rps", creds(), sleep=lambda _s: None)

    assert result["state"] == "AUTHENTICATED"
    assert tab.navigations == []
    assert len([expr for expr in tab.evals if "SUBMIT" in expr]) == 1


def test_password_never_in_result():
    tab = FakeTab([{"url": "https://www.saramin.co.kr/zf_user/auth?ut=c", "body": "로그인 아이디"},
                   LOGGED_OUT_FORM])
    r = ssl.perform_autologin(tab, "saramin", creds())
    import json
    blob = json.dumps(r, ensure_ascii=False)
    assert "s3cr3t-pw" not in blob and "corp-id" not in blob


def test_selector_drift_reports_only_nonsecret_form_shape():
    class DriftTab(FakeTab):
        def eval(self, expr):
            if "readyState:document.readyState" in expr:
                return {
                    "readyState": "complete",
                    "inputs": [
                        {"type": "email", "name": "", "autocomplete": "username"},
                    ],
                    "forms": 0,
                    "iframes": 1,
                    "buttons": ["이메일로 로그인"],
                }
            if "const sels=" in expr:
                return False
            return super().eval(expr)

    tab = DriftTab([
        {"url": "https://www.linkedin.com/uas/login-cap", "body": "로그인"},
        {"url": "https://www.linkedin.com/uas/login", "body": "로그인"},
    ])

    result = ssl.perform_autologin(tab, "linkedin_rps", creds(), sleep=lambda _s: None)

    assert result["state"] == "SELECTOR_DRIFT"
    assert result["form_shape"]["inputs"] == [
        {"type": "email", "name": "", "autocomplete": "username"},
    ]
    assert "corp-id" not in str(result)
    assert "s3cr3t-pw" not in str(result)


def test_post_submit_2fa_delayed_load_is_human_auth():
    # 2026-07-26 실측: 제출 직후엔 로딩 중, 잠시 뒤 2단계 인증 페이지가 리다이렉트로 뜬다.
    # 계정명(강상모)이 2FA 페이지에도 있으므로 챌린지 판정이 인증 판정보다 우선해야 한다.
    twofa = {"url": "https://www.saramin.co.kr/zf_user/company-viewer/certification",
             "body": "Valueconnect 강상모 2단계 인증 인증번호 입력"}
    form = dict(LOGGED_OUT_FORM)
    form["on_submit"] = twofa
    tab = FakeTab([{"url": "https://www.saramin.co.kr/zf_user/auth?ut=c", "body": "로그인 아이디"},
                   form])
    r = ssl.perform_autologin(tab, "saramin", creds(), sleep=lambda s: None)
    assert r["state"] == "HUMAN_AUTH", r
    submits = [e for e in tab.evals if "SUBMIT" in e]
    assert len(submits) == 1, "2FA 라도 제출은 1회뿐(재시도 없음)"


def test_unsupported_site_raises():
    with pytest.raises(ValueError):
        ssl.decide_login_step("myspace", "x", "y")
