from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
_FORM_RULES = {
    "saramin": {
        "username": ('input[name="id"]', "#id", 'input[name="user_id"]', 'input[name="member_id"]', 'input[type="text"]'),
        "password": ('input[name="password"]', "#password", 'input[name="passwd"]', 'input[type="password"]'),
        "submit": ('button[type="submit"]', 'input[type="submit"]'),
    },
    "jobkorea": {
        "username": ("#M_ID", 'input[name="M_ID"]', "#loginId", 'input[name="id"]', 'input[type="text"]'),
        "password": ("#M_PWD", 'input[name="M_PWD"]', "#loginPwd", 'input[name="password"]', 'input[type="password"]'),
        "submit": ("#lb_login", 'button[type="submit"]', 'input[type="submit"]'),
    },
    "linkedin_rps": {
        "username": ("#username", "#session_key", 'input[name="session_key"]', 'input[name="login"]',
                     'input[type="email"]', 'input[type="text"]'),
        "password": ("#password", "#session_password", 'input[name="session_password"]',
                     'input[name="password"]', 'input[type="password"]'),
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
def read_login_form(tab: Any, site: str) -> LoginFormObservation:
    rules = _FORM_RULES.get(site)
    if rules is None:
        return LoginFormObservation(False, "", "")
    raw = tab.eval(
        "(()=>{const groups=" + json.dumps(rules) + ";const pick=(xs)=>xs.find(s=>document.querySelector(s))||'';"
        "const u=pick(groups.username),p=pick(groups.password),b=pick(groups.submit);"
        "const sig=(s)=>{const e=s&&document.querySelector(s);"
        "return e?[e.tagName,e.getAttribute('type')||'',"
        "e.getAttribute('name')||'',e.getAttribute('autocomplete')||'',"
        "e.form&&e.form.getAttribute('action')||''].join('|'):''};"
        "return {url:location.href,bodyPresent:!!document.body,selectors:[u,p,b],"
        "signature:[sig(u),sig(p),sig(b)].join('::'),"
        "badgePresent:!!document.getElementById('vh-automation-badge')};})()"
    )
    if not isinstance(raw, dict):
        return LoginFormObservation(False, "", "")
    selectors = raw.get("selectors")
    selected = tuple(selectors) if (
        isinstance(selectors, list) and len(selectors) == 3
        and all(isinstance(value, str) for value in selectors)) else ("", "", "")
    url = str(raw.get("url") or "")
    signature = str(raw.get("signature") or "")
    valid = bool(raw.get("bodyPresent") is True and all(selected)
                 and signature and url.startswith("https://"))
    fingerprint = hashlib.sha256(json.dumps([site, url, selected, signature],
        separators=(",", ":")).encode()).hexdigest() if valid else ""
    return LoginFormObservation(valid, fingerprint, url, raw.get("badgePresent") is True, selected, signature)
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
