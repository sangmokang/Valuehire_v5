from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

_FORM_RULES = {
    "saramin": {
        "username": (
            'input[name="id"]', "#id", 'input[name="user_id"]',
            'input[name="member_id"]',
        ),
        "password": (
            'input[name="password"]', "#password", 'input[name="passwd"]',
            'input[name="member_pass"]',
        ),
        "submit": ('button[type="submit"]', 'input[type="submit"]'),
    },
    "jobkorea": {
        "username": ("#M_ID", 'input[name="M_ID"]'),
        "password": ("#M_PWD", 'input[name="M_PWD"]'),
        "submit": ('button.login-button[type="submit"]', 'button[type="submit"]'),
    },
    "linkedin_rps": {
        "username": (
            "#username", "#session_key", 'input[name="session_key"]',
            'input[name="login"]', 'input[type="email"]',
        ),
        "password": (
            "#password", "#session_password", 'input[name="session_password"]',
            'input[name="password"]',
        ),
        "submit": ('button[type="submit"]', ".btn__primary--large"),
    },
}


@dataclass(frozen=True)
class LoginFormObservation:
    valid: bool
    fingerprint: str
    url: str
    badge_present: bool = False
    selectors: tuple[str, str, str] = field(default=("", "", ""), repr=False)
    signature: str = field(default="", repr=False)


def _official_login_surface(site: str, url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold()
    path = parsed.path.rstrip("/").casefold() or "/"
    if parsed.scheme != "https":
        return False
    if site == "saramin":
        return (
            host in {"saramin.co.kr", "www.saramin.co.kr"}
            and path == "/zf_user/auth"
            and parse_qs(parsed.query).get("ut") == ["c"]
        )
    if site == "jobkorea":
        return (
            host in {"jobkorea.co.kr", "www.jobkorea.co.kr"}
            and path == "/login/login_tot.asp"
        )
    if site == "linkedin_rps":
        return (
            host in {"linkedin.com", "www.linkedin.com"}
            and path == "/login"
        )
    return False


def _same_official_origin(site: str, page_url: str, action_url: str) -> bool:
    try:
        page = urlsplit(page_url)
        action = urlsplit(action_url)
    except ValueError:
        return False
    if action.scheme != "https":
        return False
    page_host = (page.hostname or "").casefold()
    action_host = (action.hostname or "").casefold()
    allowed = {
        "saramin": {"saramin.co.kr", "www.saramin.co.kr"},
        "jobkorea": {"jobkorea.co.kr", "www.jobkorea.co.kr"},
        "linkedin_rps": {"linkedin.com", "www.linkedin.com"},
    }.get(site, set())
    return page_host in allowed and action_host in allowed


def _site_context_is_valid(site: str, raw: dict[str, Any]) -> bool:
    if site == "saramin":
        return raw.get("saraminCorporate") is True
    if site == "jobkorea":
        return (
            raw.get("jobkoreaCorporate") is True
            and raw.get("jobkoreaSearchFirm") is True
        )
    if site == "linkedin_rps":
        return raw.get("linkedinPrimaryLogin") is True
    return False


def read_login_form(tab: Any, site: str) -> LoginFormObservation:
    rules = _FORM_RULES.get(site)
    if rules is None:
        return LoginFormObservation(False, "", "")
    raw = tab.eval(
        "(()=>{const groups=" + json.dumps(rules) + ";"
        "const shown=(e)=>{if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();"
        "return s.display!=='none'&&s.visibility!=='hidden'&&s.opacity!=='0'&&r.width>0&&r.height>0};"
        "const pick=(xs)=>xs.find(s=>shown(document.querySelector(s)))||'';"
        "const u=pick(groups.username),p=pick(groups.password),b=pick(groups.submit);"
        "const ue=u&&document.querySelector(u),pe=p&&document.querySelector(p),be=b&&document.querySelector(b);"
        "const form=ue&&ue.form;"
        "const sig=(s)=>{const e=s&&document.querySelector(s);"
        "return e?[e.tagName,e.getAttribute('type')||'',"
        "e.getAttribute('name')||'',e.getAttribute('autocomplete')||'',"
        "e.form&&e.form.action||'',e.form&&e.form.method||''].join('|'):''};"
        "const corporate=document.querySelector('#devMemTab li.on a[data-m-type=\"Co\"]');"
        "const searchFirm=document.querySelector('#btnCorpMemberType');"
        "return {url:location.href,bodyPresent:!!document.body,selectors:[u,p,b],"
        "signature:[sig(u),sig(p),sig(b)].join('::'),"
        "badgePresent:!!document.getElementById('vh-automation-badge'),"
        "sameForm:!!form&&pe&&be&&pe.form===form&&be.form===form,"
        "visible:shown(ue)&&shown(pe)&&shown(be),"
        "enabled:!!ue&&!!pe&&!!be&&!ue.disabled&&!pe.disabled&&!be.disabled,"
        "passwordType:!!pe&&(pe.getAttribute('type')||'').toLowerCase()==='password',"
        "formMethod:form?(form.method||'GET').toUpperCase():'',"
        "formAction:form?form.action:'',"
        "saraminCorporate:new URL(location.href).searchParams.get('ut')==='c',"
        "jobkoreaCorporate:!!corporate,"
        "jobkoreaSearchFirm:!!searchFirm&&searchFirm.checked===true,"
        "linkedinPrimaryLogin:location.pathname.replace(/\\/$/,'')==='/login'};})()"
    )
    if not isinstance(raw, dict):
        return LoginFormObservation(False, "", "")
    selectors = raw.get("selectors")
    selected = tuple(selectors) if (
        isinstance(selectors, list) and len(selectors) == 3
        and all(isinstance(value, str) for value in selectors)) else ("", "", "")
    url = str(raw.get("url") or "")
    signature = str(raw.get("signature") or "")
    action = str(raw.get("formAction") or "")
    valid = bool(
        raw.get("bodyPresent") is True
        and all(selected)
        and signature
        and _official_login_surface(site, url)
        and raw.get("sameForm") is True
        and raw.get("visible") is True
        and raw.get("enabled") is True
        and raw.get("passwordType") is True
        and str(raw.get("formMethod") or "").upper() == "POST"
        and _same_official_origin(site, url, action)
        and _site_context_is_valid(site, raw)
    )
    context = {
        "saraminCorporate": raw.get("saraminCorporate") is True,
        "jobkoreaCorporate": raw.get("jobkoreaCorporate") is True,
        "jobkoreaSearchFirm": raw.get("jobkoreaSearchFirm") is True,
        "linkedinPrimaryLogin": raw.get("linkedinPrimaryLogin") is True,
    }
    fingerprint = hashlib.sha256(json.dumps([
        site, url, selected, signature, action,
        str(raw.get("formMethod") or "").upper(), context,
    ],
        separators=(",", ":")).encode()).hexdigest() if valid else ""
    return LoginFormObservation(
        valid, fingerprint, url, raw.get("badgePresent") is True,
        selected, signature,
    )


def prepare_jobkorea_searchfirm(tab: Any) -> bool:
    """Select both the corporate tab and the separate search-firm switch."""
    raw = tab.eval(
        "(()=>{"
        "if(location.protocol!=='https:'||"
        "!/^(www\\.)?jobkorea\\.co\\.kr$/i.test(location.hostname)||"
        "location.pathname.toLowerCase()!=='/login/login_tot.asp')return false;"
        "const corporate=document.querySelector('#devMemTab a[data-m-type=\"Co\"]');"
        "const checkbox=document.querySelector('#btnCorpMemberType');"
        "if(!corporate||!checkbox)return false;"
        "const active=()=>corporate.parentElement&&corporate.parentElement.classList.contains('on');"
        "if(!active())corporate.click();"
        "if(!checkbox.checked)checkbox.click();"
        "return !!active()&&checkbox.checked===true;})()"
    )
    return raw is True


def submit_login_form_once(tab: Any, *, form: LoginFormObservation,
                           episode_id: str, username: str,
                           password: str) -> dict[str, Any]:
    if not form.valid or not episode_id or not username or not password:
        return {"submitted": False, "reason": "invalid_submission_input"}
    marker = hashlib.sha256(episode_id.encode()).hexdigest()
    script = (
        "(()=>{const expected=" + json.dumps({
            "url": form.url,
            "selectors": form.selectors,
            "signature": form.signature,
            "marker": marker,
        }) + ";"
        "if(location.href!==expected.url||"
        "!document.getElementById('vh-automation-badge'))"
        "return {submitted:false,reason:'target_or_badge_changed'};"
        "const [us,ps,bs]=expected.selectors;"
        "const u=document.querySelector(us),p=document.querySelector(ps),"
        "b=document.querySelector(bs);"
        "const sig=(e)=>e?[e.tagName,e.getAttribute('type')||'',"
        "e.getAttribute('name')||'',e.getAttribute('autocomplete')||'',"
        "e.form&&e.form.getAttribute('action')||''].join('|'):'';"
        "if(!u||!p||!b||[sig(u),sig(p),sig(b)].join('::')!==expected.signature)"
        "return {submitted:false,reason:'selector_drift'};"
        "const root=document.documentElement;"
        "if(root.dataset.vhLoginEpisode===expected.marker)"
        "return {submitted:false,reason:'episode_already_submitted'};"
        "root.dataset.vhLoginEpisode=expected.marker;"
        "const set=(e,v)=>{const d=Object.getOwnPropertyDescriptor("
        "Object.getPrototypeOf(e),'value');(d&&d.set?d.set.bind(e):"
        "(x)=>{e.value=x})(v);e.dispatchEvent(new Event('input',{bubbles:true}));"
        "e.dispatchEvent(new Event('change',{bubbles:true}))};"
        "set(u," + json.dumps(username) + ");set(p," + json.dumps(password)
        + ");b.click();return {submitted:true,reason:'submitted'};})()"
    )
    raw = tab.eval(script)
    if not isinstance(raw, dict):
        return {"submitted": False, "reason": "submission_unverified"}
    return {
        "submitted": raw.get("submitted") is True,
        "reason": str(raw.get("reason") or "submission_unverified"),
    }
