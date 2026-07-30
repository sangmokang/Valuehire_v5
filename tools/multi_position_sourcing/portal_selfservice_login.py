"""self-service raw-CDP 자동 로그인 (이슈 B, SOT-26 INV1/INV2 · login 스킬 §4).

세션 보존 계약:
- 기존 target 하나에서만 조작. 새 browser/context/page/tab 0회, close 0회.
- 일반 로그인 화면일 때만 저장 자격증명을 동일 target 폼에 1회 제출.
- 캡차·2FA·checkpoint·세션충돌은 제출 0회로 HUMAN_AUTH 인계.
- 이미 로그인돼 있으면 mutation 0회.
- 비밀번호는 러너 내부(Keychain→creds_provider)에서만 흐르고 반환값·로그·모델 컨텍스트에 넣지 않는다.

호출자(session_guard auto-login)가 lease·owner-idle·정확한 target attach를 책임지고,
이 모듈은 그 target(duck-typed: .eval/.navigate/.current_url) 위에서만 동작한다.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

from .models import Channel
from .portal_autologin import AUTO_LOGIN_SELECTORS, login_url_for_channel
from .portal_login import (
    _CHALLENGE_TOKENS,
    _is_pure_security_challenge,
    _is_session_conflict,
)

# SOT-26 login_state_check: URL 아닌 GNB 마커로 판정.
_AUTH_MARKERS: dict[str, tuple[str, ...]] = {
    "saramin": ("강상모", "valueconnect", "로그아웃"),
    "jobkorea": ("로그아웃", "밸류커넥트"),
    "linkedin_rps": ("/talent",),
}
_LOGGED_OUT_MARKERS: dict[str, tuple[str, ...]] = {
    "saramin": ("로그인", "회원가입"),
    "jobkorea": ("로그인",),
    "linkedin_rps": ("login-cap", "authwall"),
}


@dataclass(frozen=True)
class PortalCreds:
    username: str
    password: str


def _is_authenticated(site: str, body: str) -> bool:
    low = body.lower()
    markers = _AUTH_MARKERS.get(site, ())
    if site == "saramin":
        # 계정명/valueconnect 는 강한 신호. '로그아웃' 만으로는 부족(로그인 링크와 공존 가능).
        if "강상모" in body or "valueconnect" in low:
            return True
        out = _LOGGED_OUT_MARKERS["saramin"]
        return "로그아웃" in body and not all(m in body for m in out)
    return any(m.lower() in low for m in markers)


def _is_authenticated_page(site: str, body: str, url: str) -> bool:
    """Recognize an authenticated page from stable body and URL evidence.

    LinkedIn Recruiter pages do not render the literal ``/talent`` text that the
    legacy body-only check expected.  A real authenticated Talent surface does
    render the account-menu control, so bind that marker to the official HTTPS
    Talent URL instead of navigating an already logged-in tab to the login form.
    """
    if site != "linkedin_rps":
        return _is_authenticated(site, body)
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").rstrip(".").casefold()
    path = (parsed.path or "").casefold()
    official_talent_surface = bool(
        parsed.scheme.casefold() == "https"
        and parsed.username is None
        and parsed.password is None
        and (host == "linkedin.com" or host.endswith(".linkedin.com"))
        and (path == "/talent" or path.startswith("/talent/"))
    )
    return official_talent_surface and (
        _is_authenticated(site, body)
        or "expand the user menu" in body.casefold()
    )


def decide_login_step(site: str, body: str, url: str) -> str:
    """순수 판정 — 'already_authenticated' | 'security_challenge' | 'session_conflict' | 'fill_credentials'.

    2026-07-31(AC-A): 세션충돌(`session_conflict`)은 진짜 보안챌린지(`security_challenge`)와
    분리된 별도 상태다 — 오너가 명시적으로 기기를 지정하면(`owner_takeover`) 세션충돌만
    무시하고 진행할 수 있어야 하기 때문. 진짜 챌린지는 항상 `security_challenge`로 우선
    판정되며 owner_takeover 로도 우회할 수 없다.
    """
    if site not in AUTO_LOGIN_SELECTORS:
        raise ValueError(f"automatic login is not configured for {site}")
    if _is_pure_security_challenge(body, url):
        return "security_challenge"
    if _is_session_conflict(body, url):
        return "session_conflict"
    if _is_authenticated_page(site, body, url):
        return "already_authenticated"
    return "fill_credentials"


def _fill_js(selectors: tuple[str, ...], value: str) -> str:
    """네이티브 setter + input/change 이벤트로 채운다(React 등 대비). 값은 JSON 인코딩."""
    return (
        "(()=>{const sels=" + json.dumps(list(selectors)) + ";"
        "for(const s of sels){const el=document.querySelector(s);"
        "if(el){const p=Object.getOwnPropertyDescriptor(el.__proto__,'value');"
        "(p&&p.set?p.set:(v=>{el.value=v})).call(el," + json.dumps(value) + ");"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));return true;}}"
        "return false;})()"
    )


def _submit_js(selectors: tuple[str, ...]) -> str:
    # 표식 'SUBMIT' 로 테스트/로그가 제출 시도를 식별(값 노출 없음).
    return (
        "/*SUBMIT*/(()=>{const sels=" + json.dumps(list(selectors)) + ";"
        "for(const s of sels){const el=document.querySelector(s);"
        "if(el){el.click();return true;}}"
        "const f=document.querySelector('form');if(f){f.submit();return true;}"
        "return false;})()"
    )


def _read_body(tab: Any) -> str:
    return str(tab.eval("document.body ? document.body.innerText : ''") or "")


def _challenge_markers(body: str, url: str) -> list[str]:
    haystack = f"{body} {url}".casefold()
    return [token for token in _CHALLENGE_TOKENS if token.casefold() in haystack]


def _login_form_shape(tab: Any) -> dict[str, Any]:
    """Return selector-only drift metadata; never read field values or page text."""
    result = tab.eval(
        "(()=>({readyState:document.readyState,"
        "inputs:[...document.querySelectorAll('input')].map(e=>({"
        "type:e.getAttribute('type')||'',name:e.getAttribute('name')||'',"
        "autocomplete:e.getAttribute('autocomplete')||''})),"
        "forms:document.querySelectorAll('form').length,"
        "iframes:document.querySelectorAll('iframe').length,"
        "buttons:[...document.querySelectorAll('button')].slice(0,12).map(e=>"
        "(e.innerText||e.getAttribute('aria-label')||'').trim()"
        ".replace(/[\\w.+-]+@[\\w.-]+\\.[A-Za-z]{2,}/g,'[email]')"
        ".replace(/\\+?\\d[\\d\\s().-]{7,}\\d/g,'[phone]').slice(0,80))"
        ".filter(Boolean)}))()"
    )
    return result if isinstance(result, dict) else {}


def _login_fields_present(tab: Any, selectors: Any) -> bool:
    result = tab.eval(
        "(()=>{const u=" + json.dumps(list(selectors.username))
        + ",p=" + json.dumps(list(selectors.password))
        + ";return u.some(s=>document.querySelector(s))"
        "&&p.some(s=>document.querySelector(s));})()"
    )
    return result is True


def perform_autologin(
    tab: Any,
    site: Channel,
    creds: PortalCreds,
    *,
    sleep: Callable[[float], None] = time.sleep,
    settle_seconds: float = 2.5,
    post_submit_polls: int = 4,
    owner_takeover: bool = False,
) -> dict[str, Any]:
    """기존 target 위에서 세션 보존 자동 로그인 1회. 반환에 비밀값 없음.

    2026-07-31(AC-A): ``owner_takeover=True``면 세션충돌(다른 기기 로그인)을 이유로
    멈추지 않고 자격증명 제출까지 진행한다 — 사장님이 명시적으로 이 기기에서
    로그인하라고 지시한 경우에만 CLI ``--owner-takeover``로 전달된다. 진짜
    보안챌린지(captcha/2FA/checkpoint)는 이 값과 무관하게 항상 멈춘다.
    """
    if site not in AUTO_LOGIN_SELECTORS:
        raise ValueError(f"automatic login is not configured for {site}")
    selectors = AUTO_LOGIN_SELECTORS[site]

    body = _read_body(tab)
    url = tab.current_url()
    step = decide_login_step(site, body, url)
    if step == "already_authenticated":
        return {"state": "AUTHENTICATED", "site": site, "mutations": 0,
                "note": "이미 로그인됨 — 조작 0회"}

    # LinkedIn login-cap에 실제 자격증명 폼이 이미 있으면 그대로 사용한다.
    # 2026-07-26 현재 /uas/login 직접 이동은 일부 관리 브라우저에서 연결 오류
    # 화면으로 끝나므로, 검증된 기존 폼을 버리고 재이동하지 않는다.
    existing_linkedin_form = (
        site == "linkedin_rps"
        and "/uas/login-cap" in url
        and _login_fields_present(tab, selectors)
    )
    if not existing_linkedin_form:
        # 로그아웃/폼: 공식 로그인 URL 로 이동(동일 target) 후 재판정.
        tab.navigate(login_url_for_channel(site))
        sleep(settle_seconds)
        body = _read_body(tab)
        url = tab.current_url()
        step = decide_login_step(site, body, url)

    if step == "already_authenticated":
        return {"state": "AUTHENTICATED", "site": site, "mutations": 1,
                "note": "이동 후 기존 세션 확인"}
    if step == "security_challenge":
        return {"state": "HUMAN_AUTH", "site": site, "mutations": 0,
                "note": "보안 챌린지 감지 — 제출 0회, 사람 인계 필요",
                "challenge_markers": _challenge_markers(body, url)}
    if step == "session_conflict" and not owner_takeover:
        return {"state": "HUMAN_AUTH", "site": site, "mutations": 0,
                "note": "세션 충돌(다른 기기 로그인) 감지 — 제출 0회. "
                        "이 기기에서 로그인하려면 오너가 명시적으로 지정(--owner-takeover) 필요",
                "challenge_markers": _challenge_markers(body, url)}

    # 일반 로그인 화면 또는 owner_takeover 로 세션충돌을 넘긴 경우: 자격증명 1회 제출.
    ok_id = tab.eval(_fill_js(selectors.username, creds.username))
    ok_pw = tab.eval(_fill_js(selectors.password, creds.password))
    if not (ok_id and ok_pw):
        return {"state": "SELECTOR_DRIFT", "site": site, "mutations": 0,
                "note": "로그인 입력 셀렉터 미발견 — 제출 안 함(셀렉터 사전 수리 필요)",
                "form_shape": _login_form_shape(tab)}
    tab.eval(_submit_js(selectors.submit))

    # 제출 후 페이지가 안정될 때까지 폴링한다. 2FA/캡차 페이지는 리다이렉트로 늦게 뜨므로
    # 한 번만 보고 AUTH_FAILED 로 오판하지 않는다(2026-07-26 실측: 사람인 2단계 인증 지연 로드).
    # 챌린지가 먼저 뜨면 HUMAN_AUTH 가 인증 마커보다 우선한다(2FA 페이지에도 계정명이 있으므로).
    for _ in range(max(1, int(post_submit_polls))):
        sleep(settle_seconds)
        body = _read_body(tab)
        url = tab.current_url()
        if _is_pure_security_challenge(body, url):
            return {"state": "HUMAN_AUTH", "site": site, "mutations": 1,
                    "note": "제출 후 보안 챌린지(2FA/캡차 등) — 제출 재시도 없이 사람 인계"}
        if _is_session_conflict(body, url) and not owner_takeover:
            return {"state": "HUMAN_AUTH", "site": site, "mutations": 1,
                    "note": "제출 후 세션 충돌 감지 — 오너 명시 지정(--owner-takeover) 필요"}
        if _is_authenticated_page(site, body, url):
            return {"state": "AUTHENTICATED", "site": site, "mutations": 1,
                    "note": "자동 로그인 성공"}
    return {"state": "AUTH_FAILED", "site": site, "mutations": 1,
            "note": "제출 후 로그인 마커·챌린지 모두 미확인"}
