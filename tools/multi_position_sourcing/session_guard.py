"""로그인 세션가드 — exact target, 사람 로그인 대기, 안전 keepalive.

기존 브라우저 하나에만 붙는 v5 인프라 위에서 세 가지를 강제한다.

- 브라우저 접속: ``raw_cdp``(단일 탭 attach, 종료=WebSocket 해제만) 재사용 — 재발명 금지.
- 사람 점유 감지: ``owner_activity.detect_owner_activity_snapshot`` 재사용.
  **keepalive 직전마다 호출이 필수**이며, 감지 실패는 fail-closed(사용 중 간주).
- 자격증명·쿠키를 읽거나 복사하거나 저장하지 않는다.

이 모듈은 과거의 쿠키 판정 보조 함수도 호환용으로 남기지만 쿠키 존재를 keepalive
성공으로 보지 않는다. 실제 성공은 exact target에서 allowlist 링크를 한 번 클릭하고,
``Page.navigateToHistoryEntry``로 원래 history entry를 복원한 뒤 URL과 로그인 마커를
모두 재검증했을 때뿐이다.

인증 증거는 exact target의 비밀 없는 DOM boolean과 URL만 매번 새로 읽는다.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlsplit, urlunsplit

Site = Literal["saramin", "jobkorea", "linkedin_rps"]


@dataclass(frozen=True)
class BrowserTargetRef:
    """One exact existing page target in one managed browser profile."""

    site: Site
    endpoint: str
    target_id: str
    websocket_url: str
    initial_url: str
    profile_path: str = ""
    browser_pid: int = 0


@dataclass(frozen=True)
class ManagedBrowserProcess:
    browser_pid: int
    profile_path: str


@dataclass(frozen=True)
class AuthObservation:
    """Non-secret, read-only evidence from the currently attached target."""

    authenticated: bool
    challenge: bool
    url: str
    proof_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class SafeKeepaliveTarget:
    """Previously verified, zero-cost GET link allowed for one keepalive roundtrip."""

    target_id: str
    source_url: str
    selector: str
    destination_url: str
    method: str = "GET"
    target_attr: str = "_self"
    download: bool = False
    dedicated_tab: bool = False
    clean_form: bool = False
    previously_opened_free: bool = False
    risk_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoginWindowLocator:
    """Non-secret locator shown once when AI_ATTACHED hands login to a human."""

    agent: str
    site: Site
    browser_pid: int
    profile_path: str
    cdp_endpoint: str
    target_id_suffix: str
    sanitized_title: str
    sanitized_url: str
    cg_window_id: int
    screenshot_sha256: str
    screenshot_size_bytes: int
    presentation_count: int = 1
    application_activated: bool = True
    _original_title: str = field(default="", repr=False, compare=False)
    _marker: str = field(default="", repr=False, compare=False)
    _document_loader_id: str = field(default="", repr=False, compare=False)
    _badge_bound_url: str = field(default="", repr=False, compare=False)
    _title_marker_applied: bool = field(default=False, repr=False, compare=False)
    _title_marker_pending: bool = field(default=False, repr=False, compare=False)
    _badge_marker_pending: bool = field(default=False, repr=False, compare=False)

# SOT-28 §4: 사람인·잡코리아 서버세션(JSESSIONID·ASP.NET_SessionId)은 20~30분 유휴
# 만료 → 주기는 15분 이하. LinkedIn li_at 는 장수명 → 30분 읽기 전용이면 충분.
KEEPALIVE_INTERVAL_SECONDS: dict[Site, int] = {
    "saramin": 900,
    "jobkorea": 900,
    "linkedin_rps": 1800,
}

# 읽기 전용 probe 표면. 잡코리아는 대문자 /Corp/Person/Find (소문자 경로는 리다이렉트
# 손실 이력 — 2026-07-17 /st 지시 5). 유료 차감·저장·발송 표면 금지(SOT-28 §4).
PROBE_URLS: dict[Site, str] = {
    "saramin": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
    "jobkorea": "https://www.jobkorea.co.kr/Corp/Person/Find",
    "linkedin_rps": "https://www.linkedin.com/talent/home",
}

_SITE_DOMAINS: dict[Site, str] = {
    "saramin": "saramin.co.kr",
    "jobkorea": "jobkorea.co.kr",
    "linkedin_rps": "linkedin.com",
}
_SITE_TARGET_PATH_PREFIXES: dict[Site, tuple[str, ...]] = {
    "saramin": (
        "/zf_user/memcom/talent-pool/",
        "/zf_user/member/resume-view",
        "/zf_user/auth",
        "/zf_user/company-viewer/certification",
    ),
    "jobkorea": (
        "/corp/person/find",
        "/login/",
        "/searchfirm/",
        "/recruit/co_read",
        "/person/",
    ),
    "linkedin_rps": (
        "/talent/",
        "/login",
        "/uas/login-cap",
        "/checkpoint/",
        "/enterprise-authentication/",
        "/authwall",
    ),
}
_SITE_PROFILE_ENV: dict[Site, str] = {
    "saramin": "SARAMIN_PROFILE",
    "jobkorea": "JOBKOREA_PROFILE",
    "linkedin_rps": "LINKEDIN_PROFILE",
}
_SITE_DEFAULT_PROFILES: dict[Site, Path] = {
    "saramin": Path.home() / ".valuehire" / "portal_profiles" / "saramin" / "default",
    "jobkorea": Path.home() / ".valuehire" / "portal_profiles" / "jobkorea" / "default",
    "linkedin_rps": Path.home() / ".valuehire" / "cdp_profiles" / "linkedin",
}
_UNSAFE_KEEPALIVE_LABELS = frozenset(
    {"paid", "save", "send", "modal", "new_candidate"}
)
_UNSAFE_KEEPALIVE_URL_TOKENS = (
    "logout", "log-out", "signout", "sign-out", "inmail", "send", "message",
    "compose", "proposal", "offer", "save", "payment", "purchase", "checkout",
    "charge", "paid", "new-candidate", "new_candidate", "delete", "remove",
    "session/switch", "switch-session",
)

def _official_site_url(site: Site, url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if (
        parsed.scheme.casefold() != "https"
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    host = (parsed.hostname or "").rstrip(".").casefold()
    official = _SITE_DOMAINS[site]
    return host == official or host.endswith("." + official)


def _target_identifier(target: Mapping[str, Any]) -> str:
    return str(target.get("id") or target.get("targetId") or "").strip()


def _allowed_target_surface(site: Site, url: str) -> bool:
    if not _official_site_url(site, url):
        return False
    try:
        path = (urlsplit(url).path or "/").casefold()
    except ValueError:
        return False
    return any(path.startswith(prefix) for prefix in _SITE_TARGET_PATH_PREFIXES[site])


def _exact_target_websocket(endpoint: str, target_id: str, websocket_url: str) -> bool:
    try:
        http = urlsplit(endpoint)
        ws = urlsplit(websocket_url)
        http_port = http.port
        ws_port = ws.port
    except ValueError:
        return False
    return bool(
        ws.scheme == "ws"
        and ws.hostname in {"127.0.0.1", "localhost"}
        and ws_port == http_port
        and ws.username is None
        and ws.password is None
        and ws.query == ""
        and ws.fragment == ""
        and ws.path == f"/devtools/page/{target_id}"
    )


def _managed_profile_path(site: Site, env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    configured = str(source.get(_SITE_PROFILE_ENV[site]) or "").strip()
    return configured or str(_SITE_DEFAULT_PROFILES[site])


_MANAGED_CHROME_EXECUTABLE_NAMES = frozenset({
    "chrome",
    "chromium",
    "chromium browser",
    "google chrome",
    "google chrome for testing",
})
_MANAGED_CHROME_LEGACY_APPLICATION_PATHS = frozenset({
    "/applications/chrome",
    "/applications/chromium",
    "/applications/google chrome",
    "/applications/google chrome for testing",
})
_POSITIONAL_NAVIGATION_TOKEN = re.compile(
    r"(?:^|\s)(?:[A-Za-z][A-Za-z0-9+.-]*://\S+|"
    r"(?:about|data|file|javascript):\S*|www\.\S+)(?=\s|$)",
    re.IGNORECASE,
)


def _is_managed_chrome_executable(command_prefix: str) -> bool:
    """Accept one actual Chrome executable token, never an interpreter tail."""

    value = command_prefix.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    folded = value.casefold()
    if folded in _MANAGED_CHROME_EXECUTABLE_NAMES:
        return True
    if folded in _MANAGED_CHROME_LEGACY_APPLICATION_PATHS:
        return True
    app_match = re.fullmatch(
        r"/.+/(?:google chrome(?: for testing)?|chromium|chrome)\.app/"
        r"contents/macos/(?P<name>google chrome(?: for testing)?|chromium|chrome)",
        folded,
    )
    return bool(app_match and app_match.group("name") in _MANAGED_CHROME_EXECUTABLE_NAMES)


def resolve_managed_browser_process(
    site: Site,
    endpoint: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> ManagedBrowserProcess:
    """Bind the already verified endpoint to one root Chrome PID/profile.

    Page-target CDP sockets reject ``SystemInfo.getProcessInfo``.  The managed
    endpoint resolver has already proved the exact profile/port pair, so this
    read-only OS pass accepts only one root process declaring that exact port and
    extracts its literal ``--user-data-dir`` argument.  Renderer/utility children
    and ambiguous roots fail closed; command lines are never returned or logged.
    """
    if site not in _SITE_DOMAINS:
        raise ValueError(f"unsupported login site: {site!r}")
    local = _local_cdp_endpoint(endpoint)
    port = urlsplit(local).port
    try:
        result = runner(
            ["ps", "ax", "-o", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        raise LookupError("managed browser process inspection failed") from exc
    if int(getattr(result, "returncode", 1)) != 0:
        raise LookupError("managed browser process inspection failed")
    matches: list[ManagedBrowserProcess] = []
    for raw_line in str(getattr(result, "stdout", "") or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pid_text, separator, command = line.partition(" ")
        if not separator or not pid_text.isascii() or not pid_text.isdigit():
            continue
        option_start = re.search(r"(?:^|\s)--[A-Za-z0-9]", command)
        executable = command[:option_start.start()].strip() if option_start else ""
        if not _is_managed_chrome_executable(executable):
            continue
        # ``ps -o command=`` does not preserve argv quoting on macOS.  Parse
        # Chrome's long options by their next `` --flag`` boundary so an
        # unquoted profile such as ``--user-data-dir=/tmp/LinkedIn Profile``
        # remains one literal value.  Ambiguous duplicate flags fail closed.
        option_pattern = re.compile(
            r"(?:^|\s)--(?P<name>[A-Za-z0-9][A-Za-z0-9-]*)"
            r"(?:=(?P<value>.*?))?"
            r"(?=\s+--[A-Za-z0-9][A-Za-z0-9-]*(?:=|\s|$)|$)"
        )
        options: dict[str, list[str | None]] = {}
        for match in option_pattern.finditer(command):
            options.setdefault(match.group("name"), []).append(match.group("value"))
        if "type" in options:
            continue
        ports = options.get("remote-debugging-port", [])
        profiles = options.get("user-data-dir", [])
        if len(ports) != 1 or str(ports[0] or "").strip() != str(port):
            continue
        if len(profiles) != 1 or profiles[0] is None:
            continue
        profile = str(profiles[0]).strip()
        if len(profile) >= 2 and profile[0] == profile[-1] and profile[0] in {"'", '"'}:
            profile = profile[1:-1]
        if (
            not profile
            or not os.path.isabs(profile)
            or _POSITIONAL_NAVIGATION_TOKEN.search(profile) is not None
            or any(ord(character) < 32 or ord(character) == 127 for character in profile)
        ):
            continue
        pid = int(pid_text)
        if pid <= 0:
            continue
        matches.append(ManagedBrowserProcess(pid, profile))
    if len(matches) != 1:
        raise LookupError(f"{site} managed browser root process match count was {len(matches)}")
    return matches[0]


def _local_cdp_endpoint(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise LookupError("managed CDP endpoint is malformed") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise LookupError("managed CDP endpoint is not one local endpoint")
    return f"http://127.0.0.1:{port}"


def resolve_existing_target(
    site: Site,
    *,
    target_id: str | None = None,
    managed_endpoint_resolver: Callable[[str], str] | None = None,
    browser_process_resolver: Callable[[Site, str], ManagedBrowserProcess] | None = None,
    list_pages: Callable[[str], list[dict[str, Any]]] | None = None,
    env: Mapping[str, str] | None = None,
) -> BrowserTargetRef:
    """Resolve exactly one existing site page in the site's managed browser.

    This deliberately has no cross-port scan, URL-substring lookup, first-page
    fallback, or target creation.  Multiple same-site pages require an explicit
    target id; a missing/duplicate id fails closed.
    """

    if site not in _SITE_DOMAINS:
        raise ValueError(f"unsupported login site: {site!r}")
    default_endpoint_resolver = managed_endpoint_resolver is None
    if default_endpoint_resolver:
        from .portal_worker import resolve_managed_channel_cdp_endpoint

        managed_endpoint_resolver = resolve_managed_channel_cdp_endpoint
    if list_pages is None:
        from .raw_cdp import list_pages as raw_list_pages

        list_pages = raw_list_pages

    endpoint = _local_cdp_endpoint(str(managed_endpoint_resolver(site)).strip())
    if browser_process_resolver is None and default_endpoint_resolver:
        browser_process_resolver = resolve_managed_browser_process
    process = (
        browser_process_resolver(site, endpoint)
        if browser_process_resolver is not None
        else ManagedBrowserProcess(0, _managed_profile_path(site, env))
    )
    if browser_process_resolver is not None:
        # Detect a process/port swap between the OS identity read and target list.
        confirmed = _local_cdp_endpoint(str(managed_endpoint_resolver(site)).strip())
        if confirmed != endpoint:
            raise LookupError("managed browser endpoint changed during identity resolution")
    pages = list_pages(endpoint)
    wanted_id = str(target_id or "").strip()
    matches: list[Mapping[str, Any]] = []
    for target in pages or ():
        if not isinstance(target, Mapping) or target.get("type") != "page":
            continue
        current_id = _target_identifier(target)
        current_url = str(target.get("url") or "")
        websocket_url = str(target.get("webSocketDebuggerUrl") or "").strip()
        if (
            not current_id
            or not websocket_url
            or not _allowed_target_surface(site, current_url)
            or not _exact_target_websocket(endpoint, current_id, websocket_url)
        ):
            continue
        if wanted_id and current_id != wanted_id:
            continue
        matches.append(target)
    if len(matches) != 1:
        detail = "exact target id" if wanted_id else "unique site target"
        raise LookupError(f"{site} {detail} match count was {len(matches)}")

    selected = matches[0]
    if browser_process_resolver is not None:
        confirmed_process = browser_process_resolver(site, endpoint)
        if confirmed_process != process:
            raise LookupError("managed browser process changed after exact page selection")
    return BrowserTargetRef(
        site=site,
        endpoint=endpoint,
        target_id=_target_identifier(selected),
        websocket_url=str(selected["webSocketDebuggerUrl"]),
        initial_url=str(selected["url"]),
        profile_path=process.profile_path,
        browser_pid=process.browser_pid,
    )


def wait_for_human_auth(
    *,
    auth_probe: Callable[[], AuthObservation],
    owner_snapshot: Callable[[], Any],
    sleep: Callable[[float], None] = time.sleep,
    stop_requested: Callable[[], bool],
    poll_interval_seconds: float = 5.0,
    quiet_seconds: float = 15.0,
) -> AuthObservation | None:
    """Wait indefinitely using read-only probes until auth and owner quiet agree.

    The function intentionally receives no page/tab object, so it cannot focus,
    navigate, click, type, close a popup, or destroy a target.  There is no timeout;
    only the caller's explicit stop signal may hand off.
    """

    poll = max(5.0, float(poll_interval_seconds))
    quiet = max(15.0, float(quiet_seconds))
    while True:
        if stop_requested():
            return None
        try:
            observation = auth_probe()
        except Exception:
            observation = None
        try:
            snapshot = owner_snapshot()
        except Exception:
            snapshot = None
        if stop_requested():
            return None

        idle = getattr(snapshot, "idle_seconds", None)
        valid_idle = (
            snapshot is not None
            and getattr(snapshot, "detection_status", "") == "ok"
            and getattr(snapshot, "owner_activity_detected", True) is False
            and not isinstance(idle, bool)
            and isinstance(idle, (int, float))
            and math.isfinite(float(idle))
            and float(idle) >= quiet
        )
        if (
            isinstance(observation, AuthObservation)
            and observation.authenticated is True
            and observation.challenge is False
            and bool(observation.proof_names)
            and valid_idle
        ):
            return observation
        sleep(poll)


def read_auth_observation(tab: Any, site: Site) -> AuthObservation:
    """Read fresh site auth/challenge markers without causing navigation or clicks."""

    script = r"""
(() => {
  const visible = (selector) => Array.from(document.querySelectorAll(selector)).some((e) => {
    const s = getComputedStyle(e); const r = e.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0' && r.width > 0 && r.height > 0;
  });
  const bodyText = document.body && document.body.innerText || '';
  const folded = bodyText.toLowerCase();
  const path = location.pathname.toLowerCase();
  const challengePath = /\/(checkpoint|uas\/login-cap|enterprise-authentication|authwall)(\/|$)/.test(path);
  const challengeControl = visible(
    'iframe[src*="captcha"], [class*="captcha"], [id*="captcha"], input[name*="captcha"], input[autocomplete="one-time-code"]'
  );
  const challengePhrase = folded.includes('multiple sign-ins') ||
    folded.includes('only one session') || folded.includes('보안문자') ||
    folded.includes('인증번호') || folded.includes('2단계 인증');
  return {
    url: location.href,
    hasChallenge: challengePath || challengeControl || challengePhrase,
    hasLogout: folded.includes('로그아웃') || folded.includes('log out'),
    hasValueConnect: folded.includes('valueconnect') || folded.includes('value connect') || bodyText.includes('밸류커넥트'),
    saraminSearch: !!document.querySelector('input.search_input') && !!document.querySelector('#career_min') && !!document.querySelector('#career_max'),
    jobkoreaSearch: !!document.querySelector("#txtKeyword, input[placeholder*='키워드'], input[placeholder*='검색']"),
    linkedinSearch: visible('a[href*="/talent/search"]'),
    linkedinAccount: visible('[data-test-recruiter-account-menu], [data-test-recruiter-nav-user-menu]')
  };
})()
"""
    raw = tab.eval(script)
    if not isinstance(raw, Mapping):
        return AuthObservation(False, False, "", ())
    url = str(raw.get("url") or "")
    challenge = raw.get("hasChallenge") is True
    proofs: list[str] = []
    authenticated = False
    if site == "saramin":
        account = raw.get("hasLogout") is True or raw.get("hasValueConnect") is True
        search = raw.get("saraminSearch") is True
        if account:
            proofs.append("account_or_logout")
        if search:
            proofs.append("talent_search_controls")
        authenticated = bool(account and search and _official_site_url(site, url))
    elif site == "jobkorea":
        logout = raw.get("hasLogout") is True
        account = raw.get("hasValueConnect") is True
        search = raw.get("jobkoreaSearch") is True
        if logout and account:
            proofs.append("logout_and_account")
        if search:
            proofs.append("talent_search_controls")
        authenticated = bool(logout and account and search and _official_site_url(site, url))
    elif site == "linkedin_rps":
        surface = _official_site_url(site, url) and urlsplit(url).path.casefold().startswith("/talent/")
        account = raw.get("linkedinAccount") is True
        search = raw.get("linkedinSearch") is True
        if surface:
            proofs.append("talent_surface")
        if account:
            proofs.append("recruiter_account")
        if search:
            proofs.append("recruiter_search")
        # Recruiter pages such as /talent/projects do not always render a
        # /talent/search anchor.  The exact official talent surface plus the
        # recruiter account control is the stable authentication proof; the
        # search link remains optional corroborating evidence.
        authenticated = bool(surface and account)
    return AuthObservation(
        authenticated=authenticated and not challenge,
        challenge=challenge,
        url=url,
        proof_names=tuple(proofs),
    )


def _same_https_origin(left: str, right: str) -> bool:
    try:
        one, two = urlsplit(left), urlsplit(right)
        one_port, two_port = one.port, two.port
    except ValueError:
        return False
    for parsed in (one, two):
        if (
            parsed.scheme.casefold() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return False
    return (
        one.scheme.casefold(),
        (one.hostname or "").rstrip(".").casefold(),
        one_port,
    ) == (
        two.scheme.casefold(),
        (two.hostname or "").rstrip(".").casefold(),
        two_port,
    )


def _decoded_policy_surface(*values: str) -> str | None:
    """Decode URL policy input repeatedly and reject ambiguous/control data."""

    decoded_values: list[str] = []
    try:
        for value in values:
            current = value
            if any(ord(character) < 32 or ord(character) == 127 for character in current):
                return None
            for _decode_pass in range(4):
                decoded = unquote(current, encoding="utf-8", errors="strict")
                if decoded == current:
                    break
                current = decoded
            # More than four encoding layers are not a legitimate audited
            # descriptor surface.  Refuse instead of guessing its meaning.
            if re.search(r"%[0-9A-Fa-f]{2}", current):
                return None
            if any(ord(character) < 32 or ord(character) == 127 for character in current):
                return None
            decoded_values.append(current.casefold())
    except (UnicodeError, ValueError):
        return None
    return " ".join(decoded_values)


def _safe_keepalive_descriptor(ref: BrowserTargetRef, target: SafeKeepaliveTarget) -> bool:
    try:
        if not all(
            isinstance(value, str)
            for value in (
                target.target_id,
                target.source_url,
                target.selector,
                target.destination_url,
                target.method,
                target.target_attr,
            )
        ):
            return False
        labels = {str(label).strip().casefold() for label in target.risk_labels}
        if not isinstance(target.risk_labels, (tuple, list)):
            return False
    except (TypeError, AttributeError):
        return False
    unsafe_url_surface = _decoded_policy_surface(
        target.source_url,
        target.destination_url,
        target.selector,
    )
    return bool(
        unsafe_url_surface is not None
        and target.target_id == ref.target_id
        and target.source_url == ref.initial_url
        and target.selector.strip()
        and "\x00" not in target.selector
        and target.method.strip().upper() == "GET"
        and target.target_attr.strip().casefold() in {"", "_self"}
        and target.download is False
        and target.dedicated_tab is True
        and target.clean_form is True
        and target.previously_opened_free is True
        and labels.isdisjoint(_UNSAFE_KEEPALIVE_LABELS)
        and not any(token in unsafe_url_surface for token in _UNSAFE_KEEPALIVE_URL_TOKENS)
        and _official_site_url(ref.site, target.source_url)
        and _official_site_url(ref.site, target.destination_url)
        and _same_https_origin(target.source_url, target.destination_url)
    )


def _tab_current_url(tab: Any) -> str:
    reader = getattr(tab, "current_url", None)
    if callable(reader):
        return str(reader() or "")
    evaluator = getattr(tab, "eval", None)
    if callable(evaluator):
        return str(evaluator("location.href") or "")
    raise RuntimeError("raw target has no read-only current URL operation")


def _tab_target_id(tab: Any) -> str:
    value = getattr(tab, "target_id", "")
    if callable(value):
        value = value()
    return str(value or "").strip()


def _main_document_loader_id(tab: Any) -> str:
    """Read the current main-frame loader identity without touching the page."""

    try:
        result = tab.send("Page.getFrameTree")
    except Exception:
        return ""
    tree = result.get("frameTree") if isinstance(result, Mapping) else None
    frame = tree.get("frame") if isinstance(tree, Mapping) else None
    if not isinstance(frame, Mapping):
        return ""
    loader_id = str(frame.get("loaderId") or "").strip()
    frame_id = str(frame.get("id") or "").strip()
    return loader_id if loader_id and frame_id else ""


def _fresh_target_matches(tab: Any, ref: BrowserTargetRef, expected_url: str) -> bool:
    """Revalidate the immutable attach binding with fresh CDP target info."""
    if _tab_target_id(tab) != ref.target_id:
        return False
    try:
        result = tab.send("Target.getTargetInfo", {"targetId": ref.target_id})
    except Exception:
        return False
    info = result.get("targetInfo") if isinstance(result, Mapping) else None
    return bool(
        isinstance(info, Mapping)
        and str(info.get("targetId") or "") == ref.target_id
        and str(info.get("type") or "") == "page"
        and str(info.get("url") or "") == expected_url
    )


def _auth_matches(observation: Any, expected_url: str) -> bool:
    return bool(
        isinstance(observation, AuthObservation)
        and observation.authenticated is True
        and observation.challenge is False
        and observation.url == expected_url
        and observation.proof_names
    )


def _history_source_entry(tab: Any, source_url: str) -> int | None:
    result = tab.send("Page.getNavigationHistory")
    if not isinstance(result, Mapping):
        return None
    index = result.get("currentIndex")
    entries = result.get("entries")
    if isinstance(index, bool) or not isinstance(index, int) or not isinstance(entries, list):
        return None
    if index < 0 or index >= len(entries):
        return None
    current = entries[index]
    if not isinstance(current, Mapping) or str(current.get("url") or "") != source_url:
        return None
    entry_id = current.get("id")
    if isinstance(entry_id, bool) or not isinstance(entry_id, int) or entry_id <= 0:
        return None
    return entry_id


def _history_ready_for_restore(
    tab: Any,
    *,
    source_entry_id: int,
    source_url: str,
    destination_url: str,
) -> bool:
    """Prove click added exactly one destination entry after the saved source."""
    try:
        result = tab.send("Page.getNavigationHistory")
    except Exception:
        return False
    if not isinstance(result, Mapping):
        return False
    index = result.get("currentIndex")
    entries = result.get("entries")
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or not isinstance(entries, list)
        or index <= 0
        or index >= len(entries)
    ):
        return False
    current = entries[index]
    previous = entries[index - 1]
    return bool(
        isinstance(current, Mapping)
        and isinstance(previous, Mapping)
        and str(current.get("url") or "") == destination_url
        and previous.get("id") == source_entry_id
        and str(previous.get("url") or "") == source_url
    )


def _wait_for_stable_authenticated_target(
    tab: Any,
    ref: BrowserTargetRef,
    expected_url: str,
    *,
    auth_probe: Callable[[Any], AuthObservation],
    sleep: Callable[[float], None],
    timeout_seconds: float,
    history_probe: Callable[[], bool] | None = None,
    sample_spacing_seconds: float = 0.1,
) -> str:
    """Require two fresh, redirect-safe observations of one exact target.

    CDP click and history restoration are asynchronous.  One URL/auth read can
    observe a document immediately before a redirect, so each accepted sample
    rechecks target identity and URL *after* the DOM auth probe, and success
    requires two consecutive samples with the expected history shape.
    """

    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    consecutive = 0
    while True:
        if _tab_target_id(tab) != ref.target_id:
            return "target_changed"
        try:
            before = _fresh_target_matches(tab, ref, expected_url)
            observation = auth_probe(tab) if before else None
            after = bool(
                before
                and _auth_matches(observation, expected_url)
                and _fresh_target_matches(tab, ref, expected_url)
                and _tab_current_url(tab) == expected_url
            )
            history_ok = history_probe is None or history_probe()
        except Exception:
            after = False
            history_ok = False
        if after and history_ok:
            consecutive += 1
            if consecutive >= 2:
                return "ok"
        else:
            consecutive = 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "unverified"
        sleep(min(max(0.1, float(sample_spacing_seconds)), remaining))


def execute_keepalive_roundtrip(
    tab: Any,
    ref: BrowserTargetRef,
    target: SafeKeepaliveTarget,
    *,
    auth_probe: Callable[[Any], AuthObservation],
    mutation_gate: Callable[[], None],
    sleep: Callable[[float], None] = time.sleep,
    navigation_timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Click one verified link and restore the exact previous history entry.

    Each of the only two mutations has a fresh external lease/owner-idle gate.
    If the second gate fails after the click, no Back command is sent: the exact
    pending state is reported so a later owner-safe handoff can decide what to do.
    """

    if not _safe_keepalive_descriptor(ref, target):
        return {"status": "skipped_unsafe", "restore_pending": False}
    if not _fresh_target_matches(tab, ref, target.source_url):
        return {"status": "skipped_target_mismatch", "restore_pending": False}
    try:
        if _tab_current_url(tab) != target.source_url:
            return {"status": "skipped_source_mismatch", "restore_pending": False}
        source_entry_id = _history_source_entry(tab, target.source_url)
    except Exception:
        return {"status": "skipped_history_unavailable", "restore_pending": False}
    if source_entry_id is None:
        return {"status": "skipped_history_mismatch", "restore_pending": False}

    try:
        mutation_gate()
    except Exception as exc:
        from .portal_worker import ProfileLockError

        if (
            isinstance(exc, ProfileLockError)
            and _profile_lock_is_retryable_mutation_wait(exc)
        ):
            return {"status": "skipped_owner_active", "restore_pending": False}
        raise
    click = getattr(tab, "click_safe_link", None)
    if not callable(click):
        return {"status": "skipped_atomic_click_unavailable", "restore_pending": False}
    click_error = False
    try:
        clicked = click(target)
    except Exception:
        click_error = True
        clicked = False
    if clicked is not True:
        try:
            live_after_attempt = _tab_current_url(tab)
        except Exception:
            live_after_attempt = ""
        if live_after_attempt == target.destination_url:
            clicked = True
        elif live_after_attempt != target.source_url:
            return {"status": "click_uncertain", "restore_pending": True}
    if clicked is not True and not click_error:
        return {"status": "click_failed", "restore_pending": False}

    destination_state = _wait_for_stable_authenticated_target(
        tab,
        ref,
        target.destination_url,
        auth_probe=auth_probe,
        sleep=sleep,
        timeout_seconds=navigation_timeout_seconds,
        history_probe=lambda: _history_ready_for_restore(
            tab,
            source_entry_id=source_entry_id,
            source_url=target.source_url,
            destination_url=target.destination_url,
        ),
    )
    if destination_state == "target_changed":
        return {"status": "target_changed", "restore_pending": True}
    destination_auth = destination_state == "ok"
    if not destination_auth:
        return {
            "status": "destination_unverified",
            "restore_pending": True,
        }

    try:
        mutation_gate()
    except Exception as exc:
        from .portal_worker import ProfileLockError

        if (
            isinstance(exc, ProfileLockError)
            and _profile_lock_is_retryable_mutation_wait(exc)
        ):
            return {
                "status": "restore_pending",
                "restore_pending": True,
                "source_entry_id": source_entry_id,
                "destination_verified": destination_auth,
            }
        raise
    if not _fresh_target_matches(tab, ref, target.destination_url):
        return {
            "status": "target_changed",
            "restore_pending": True,
            "destination_verified": destination_auth,
        }
    try:
        tab.send("Page.navigateToHistoryEntry", {"entryId": source_entry_id})
    except Exception:
        return {
            "status": "restore_failed",
            "restore_pending": True,
            "source_entry_id": source_entry_id,
        }

    restored_state = _wait_for_stable_authenticated_target(
        tab,
        ref,
        target.source_url,
        auth_probe=auth_probe,
        sleep=sleep,
        timeout_seconds=navigation_timeout_seconds,
        history_probe=lambda: _history_source_entry(tab, target.source_url) == source_entry_id,
        # Keep two full observations, but leave enough real dwell between them
        # to catch a delayed challenge redirect after history restoration.
        sample_spacing_seconds=0.2,
    )
    if restored_state == "target_changed":
        return {
            "status": "target_changed_after_restore",
            "restore_pending": True,
            "destination_verified": destination_auth,
        }
    restored_auth = restored_state == "ok"
    success = destination_auth and restored_auth
    return {
        "status": "ok" if success else "verification_failed",
        "restore_pending": not restored_auth,
        "destination_verified": destination_auth,
        "restored_verified": restored_auth,
    }


def _sanitize_locator_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        parsed_port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        return ""
    host = (parsed.hostname or "").rstrip(".").casefold()
    port = f":{parsed_port}" if parsed_port not in {None, 443} else ""
    return urlunsplit(("https", host + port, parsed.path or "/", "", ""))


def _login_title_marker(agent: str, site: Site, target_id: str) -> tuple[str, str]:
    clean_agent = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(agent)).strip("-.")[:24]
    clean_target = re.sub(r"[^A-Za-z0-9_.-]+", "", target_id)
    if not clean_agent or not clean_target:
        raise ValueError("agent and target id must have a safe visible form")
    suffix = clean_target[-12:]
    site_label = "linkedin" if site == "linkedin_rps" else site
    return f"[LOGIN HERE][{clean_agent}][{site_label}][{suffix}]", suffix


def present_exact_login_window_once(
    tab: Any,
    ref: BrowserTargetRef,
    *,
    agent: str,
    mutation_gate: Callable[[], None],
    state: str = "AI_ATTACHED",
    episode_id: str = "default",
    window_resolver: Callable[..., Any] | None = None,
    window_capture: Callable[..., bytes] | None = None,
    application_activator: Callable[[int], bool] | None = None,
    window_sleep: Callable[[float], None] = time.sleep,
) -> LoginWindowLocator:
    """Mark, focus, resolve and capture one exact login window in AI_ATTACHED.

    HUMAN_AUTH never calls this function.  The three mutations (title, badge,
    bring-to-front) each receive a fresh lease/idle gate.  Callers retain the
    returned ``presentation_count=1`` as the episode guard and must not invoke it
    again until a new explicit auth episode begins.
    """

    if state != "AI_ATTACHED":
        raise RuntimeError("exact login-window presentation is allowed only in AI_ATTACHED")
    if _tab_target_id(tab) != ref.target_id:
        raise RuntimeError("exact target identity changed before login-window presentation")
    live_url = _tab_current_url(tab)
    if live_url != ref.initial_url or not _official_site_url(ref.site, live_url):
        raise RuntimeError("exact target URL changed before login-window presentation")
    marker, suffix = _login_title_marker(agent, ref.site, ref.target_id)
    original_title = ""
    document_loader_id = _main_document_loader_id(tab)
    site_label = "LinkedIn RPS" if ref.site == "linkedin_rps" else ref.site
    # Never echo the previous page title: it can contain a candidate name or a
    # search query.  Site + sanitized URL are reported separately.
    visible_title = f"{marker} {site_label} login"
    browser_pid = ref.browser_pid
    if isinstance(browser_pid, bool) or not isinstance(browser_pid, int) or browser_pid <= 0:
        raise RuntimeError("exact managed browser PID is unavailable")
    window_result = tab.send("Browser.getWindowForTarget", {"targetId": ref.target_id})
    raw_bounds = window_result.get("bounds") if isinstance(window_result, Mapping) else None
    if not isinstance(raw_bounds, Mapping):
        raise RuntimeError("CDP window bounds are unavailable")
    from .macos_window_locator import (
        CdpWindowIdentity,
        WindowBounds,
        activate_exact_macos_application,
        capture_exact_window_png,
        resolve_exact_macos_window,
    )

    bounds = WindowBounds(
        left=raw_bounds.get("left"),
        top=raw_bounds.get("top"),
        width=raw_bounds.get("width"),
        height=raw_bounds.get("height"),
    )
    resolve = window_resolver or resolve_exact_macos_window
    capture = window_capture or capture_exact_window_png
    activate = application_activator or activate_exact_macos_application
    # First resolve by exact PID+bounds without reading any title.  If this is
    # ambiguous, fail before title/badge/focus mutations.  After focus, resolve
    # again with the unique marker and require the same CGWindowID.
    preflight_identity = CdpWindowIdentity(
        browser_pid=browser_pid,
        target_id=ref.target_id,
        title_marker="",
        bounds=bounds,
    )
    preflight_window = (
        resolve(preflight_identity, require_on_screen=False)
        if window_resolver is None
        else resolve(preflight_identity)
    )
    if not document_loader_id:
        raise RuntimeError(
            "exact target document identity is unavailable before presentation"
        )

    clean_episode = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(episode_id)).strip("-.")[:64]
    if not clean_episode:
        raise ValueError("auth episode id must have a safe non-empty form")
    presentation_key = (ref.site, ref.endpoint, ref.target_id, clean_episode)
    if getattr(tab, "_vh_human_auth_presentation_key", None) == presentation_key:
        raise RuntimeError("exact login window was already presented for this auth episode")

    def require_same_target(phase: str) -> None:
        if (
            not _fresh_target_matches(tab, ref, live_url)
            or _tab_current_url(tab) != live_url
            or _main_document_loader_id(tab) != document_loader_id
        ):
            raise RuntimeError(f"exact target document changed before {phase}")

    def resolve_marked_window(*, frontmost: bool) -> Any:
        last_error: Exception | None = None
        for attempt in range(20):
            require_same_target("window resolution")
            try:
                if window_resolver is None:
                    return resolve(
                        marked_identity,
                        require_on_screen=frontmost,
                        require_frontmost=frontmost,
                    )
                return resolve(marked_identity)
            except Exception as exc:
                last_error = exc
                if attempt == 19:
                    raise
                window_sleep(0.1)
        assert last_error is not None
        raise last_error

    # A gate rejection happens before the episode is claimed, so a later owner-idle
    # retry can still present once.  Once a mutation may have been dispatched, the
    # episode is claimed and repeated focus/capture is forbidden.
    mutation_gate()
    require_same_target("visible badge")
    setattr(tab, "_vh_human_auth_presentation_key", presentation_key)
    provisional_locator = LoginWindowLocator(
        agent=re.sub(r"[^A-Za-z0-9_.-]+", "-", str(agent)).strip("-."),
        site=ref.site,
        browser_pid=browser_pid,
        profile_path=ref.profile_path or _managed_profile_path(ref.site),
        cdp_endpoint=ref.endpoint,
        target_id_suffix=suffix,
        sanitized_title=visible_title,
        sanitized_url=_sanitize_locator_url(live_url),
        cg_window_id=int(preflight_window.cg_window_id),
        screenshot_sha256="",
        screenshot_size_bytes=0,
        application_activated=False,
        _original_title=original_title,
        _marker=marker,
        _document_loader_id=document_loader_id,
        _badge_bound_url=live_url,
    )
    # The runner can guardedly clean a partially presented episode even when a
    # marker/title/focus/capture operation raises before this function returns.
    setattr(tab, "_vh_human_auth_cleanup_locator", provisional_locator)
    marker_fn = getattr(tab, "mark_busy", None)
    provisional_locator = replace(
        provisional_locator,
        _badge_marker_pending=True,
    )
    setattr(tab, "_vh_human_auth_cleanup_locator", provisional_locator)
    if not callable(marker_fn) or marker_fn(marker, expected_url=live_url) is not True:
        raise RuntimeError("visible login-window marker could not be installed")
    # Bind cleanup to the document that actually received the badge. A reload
    # can land after the pre-dispatch loader proof but before Runtime.evaluate;
    # the next check must abort, while finally still removes our exact badge
    # from the replacement document instead of treating it as unrelated.
    badge_loader_id = _main_document_loader_id(tab)
    provisional_locator = replace(
        provisional_locator,
        _document_loader_id=badge_loader_id,
        _badge_marker_pending=False,
    )
    setattr(tab, "_vh_human_auth_cleanup_locator", provisional_locator)
    if badge_loader_id != document_loader_id:
        raise RuntimeError("exact target document changed while installing visible badge")

    mutation_gate()
    require_same_target("title marker")
    title_marker = getattr(tab, "set_title_if_badge_owned", None)
    if not callable(title_marker):
        raise RuntimeError("badge-bound title marker surface is unavailable")
    provisional_locator = replace(
        provisional_locator,
        _title_marker_pending=True,
    )
    setattr(tab, "_vh_human_auth_cleanup_locator", provisional_locator)
    original_title = title_marker(
        visible_title,
        expected_url=live_url,
        badge_label=marker,
    )
    if not isinstance(original_title, str):
        raise RuntimeError("exact target title marker could not be installed")
    provisional_locator = replace(
        provisional_locator,
        _original_title=original_title,
        _title_marker_applied=True,
        _title_marker_pending=False,
        _badge_marker_pending=False,
    )
    setattr(tab, "_vh_human_auth_cleanup_locator", provisional_locator)
    require_same_target("installed title marker")

    marked_identity = CdpWindowIdentity(
        browser_pid=browser_pid,
        target_id=ref.target_id,
        title_marker=marker,
        bounds=bounds,
    )
    # An inactive tab's document.title is not the OS CGWindowName until Chrome
    # makes that exact page the active tab in its existing window.
    mutation_gate()
    require_same_target("focus")
    tab.send("Page.bringToFront")

    marked_window = resolve_marked_window(frontmost=False)
    if marked_window.cg_window_id != preflight_window.cg_window_id:
        raise RuntimeError("exact login window identity changed after title marker")

    mutation_gate()
    require_same_target("application activation")
    if activate(browser_pid) is not True:
        raise RuntimeError("exact managed browser application could not be activated")

    window = resolve_marked_window(frontmost=True)
    if window.cg_window_id != preflight_window.cg_window_id:
        raise RuntimeError("exact login window identity changed after focus")
    require_same_target("window capture")
    png = capture(window.cg_window_id)
    if not isinstance(png, bytes) or not png:
        raise RuntimeError("exact login-window capture is empty")
    locator = LoginWindowLocator(
        agent=re.sub(r"[^A-Za-z0-9_.-]+", "-", str(agent)).strip("-."),
        site=ref.site,
        browser_pid=browser_pid,
        profile_path=ref.profile_path or _managed_profile_path(ref.site),
        cdp_endpoint=ref.endpoint,
        target_id_suffix=suffix,
        sanitized_title=visible_title,
        sanitized_url=_sanitize_locator_url(live_url),
        cg_window_id=int(window.cg_window_id),
        screenshot_sha256=hashlib.sha256(png).hexdigest(),
        screenshot_size_bytes=len(png),
        application_activated=True,
        _original_title=original_title,
        _marker=marker,
        _document_loader_id=document_loader_id,
        _badge_bound_url=live_url,
        _title_marker_applied=True,
        _title_marker_pending=False,
    )
    setattr(tab, "_vh_human_auth_cleanup_locator", locator)
    return locator


def cleanup_exact_login_presentation(
    tab: Any,
    ref: BrowserTargetRef,
    locator: LoginWindowLocator,
    *,
    mutation_gate: Callable[[], None],
) -> dict[str, Any]:
    """Guardedly remove only this episode's badge/title on the original page.

    A successful human login commonly replaces the document.  In that case the
    marker disappeared with the old document and restoring its private title into
    the new page would be wrong, so cleanup is a read-only no-op.  If the original
    document remains, each cleanup mutation receives a fresh owner-idle gate.
    """

    if _tab_target_id(tab) != ref.target_id:
        return {"status": "cleanup_target_changed", "cleanup_pending": True}
    try:
        live_url = _tab_current_url(tab)
    except Exception:
        return {"status": "cleanup_unreadable", "cleanup_pending": True}
    loader_id = locator._document_loader_id
    if not loader_id and live_url != ref.initial_url:
        return {"status": "cleanup_not_applicable_navigation_changed", "cleanup_pending": False}
    if not _fresh_target_matches(tab, ref, live_url):
        return {"status": "cleanup_target_changed", "cleanup_pending": True}
    if (
        loader_id
        and _main_document_loader_id(tab) != loader_id
        and not locator._badge_marker_pending
    ):
        return {"status": "cleanup_not_applicable_document_changed", "cleanup_pending": False}

    marker = locator._marker
    if not marker or not locator.sanitized_title:
        return {"status": "cleanup_identity_missing", "cleanup_pending": True}
    mutations = 0
    title_original_unknown = False
    if locator._title_marker_pending:
        try:
            current_title = str(tab.eval("document.title") or "")
        except Exception:
            title_original_unknown = True
        else:
            title_original_unknown = (
                current_title == locator.sanitized_title
                or current_title.startswith(marker)
            )

    if locator._title_marker_applied:
        restore_title = getattr(tab, "restore_title_if_badge_owned", None)
        if not callable(restore_title):
            return {"status": "cleanup_title_surface_missing", "cleanup_pending": True}
        try:
            mutation_gate()
        except Exception:
            return {"status": "cleanup_title_pending", "cleanup_pending": True}
        if (
            not _fresh_target_matches(tab, ref, live_url)
            or _tab_current_url(tab) != live_url
            or (loader_id and _main_document_loader_id(tab) != loader_id)
        ):
            return {
                "status": "cleanup_title_document_changed",
                "cleanup_pending": True,
            }
        title_cleanup = restore_title(
            locator._original_title,
            expected_url=live_url,
            badge_label=marker,
            title_prefix=marker,
        )
        if title_cleanup not in {"restored", "title_changed"}:
            return {"status": "cleanup_title_unverified", "cleanup_pending": True}
        if title_cleanup == "restored":
            mutations += 1

    clear_busy = getattr(tab, "clear_busy", None)
    if not callable(clear_busy):
        return {"status": "cleanup_surface_missing", "cleanup_pending": True}
    try:
        mutation_gate()
    except Exception:
        return {"status": "cleanup_owner_active", "cleanup_pending": True}
    if (
        not _fresh_target_matches(tab, ref, live_url)
        or _tab_current_url(tab) != live_url
        or (
            loader_id
            and _main_document_loader_id(tab) != loader_id
            and not locator._badge_marker_pending
        )
    ):
        return {"status": "cleanup_document_changed", "cleanup_pending": True}
    badge_bound_url = locator._badge_bound_url or ref.initial_url
    if clear_busy(
        marker,
        expected_url=live_url,
        badge_bound_url=badge_bound_url,
    ) is not True:
        return {"status": "cleanup_badge_unverified", "cleanup_pending": True}
    mutations += 1
    if title_original_unknown:
        return {
            "status": "cleanup_title_original_unknown",
            "cleanup_pending": True,
            "mutations": mutations,
        }
    return {"status": "cleanup_ok", "cleanup_pending": False, "mutations": mutations}


def _default_login_lease(site: Site) -> Any:
    from .portal_worker import PortalWorkerConfig, ProfileLock

    return ProfileLock(PortalWorkerConfig(
        channel=site,
        worker_id="default",
        mode="headed",
        connection_mode="raw_single_tab",
    ))


def _attach_exact_ref(target: Mapping[str, Any], *, badge: bool = False) -> Any:
    from . import raw_cdp

    return raw_cdp.attach(dict(target), badge=badge)


def _public_locator_payload(locator: LoginWindowLocator) -> dict[str, Any]:
    """Serialize only the intentional non-secret locator surface."""
    return {
        "event": "LOGIN_WINDOW_READY",
        "agent": locator.agent,
        "site": locator.site,
        "browser_pid": locator.browser_pid,
        "profile_path": locator.profile_path,
        "cdp_endpoint": locator.cdp_endpoint,
        "target_id_suffix": locator.target_id_suffix,
        "sanitized_title": locator.sanitized_title,
        "sanitized_url": locator.sanitized_url,
        "cg_window_id": locator.cg_window_id,
        "screenshot_sha256": locator.screenshot_sha256,
        "screenshot_size_bytes": locator.screenshot_size_bytes,
        "presentation_count": locator.presentation_count,
        "application_activated": locator.application_activated,
    }


def _disconnect_websocket_only(tab: Any | None) -> bool:
    if tab is None:
        return True
    disconnect = getattr(tab, "disconnect", None)
    if not callable(disconnect):
        return False
    try:
        return disconnect() is True
    except BaseException:
        return False


def _profile_lock_is_contention(exc: BaseException) -> bool:
    message = str(exc).strip().casefold()
    return message == "busy" or "already locked" in message


def _profile_lock_is_retryable_mutation_wait(exc: BaseException) -> bool:
    message = str(exc).strip().casefold()
    return _profile_lock_is_contention(exc) or message in {
        "owner activity blocks raw browser mutation",
        "owner activity detection failed closed",
        "owner idle proof did not increase during quiet dwell",
    }


def _acquire_login_lease_read_only(
    lease: Any,
    *,
    stop_requested: Callable[[], bool],
    sleep: Callable[[float], None],
) -> bool:
    """Wait for the site lease without inspecting or mutating any browser."""

    from .portal_worker import ProfileLockError

    while True:
        if stop_requested():
            return False
        try:
            lease.acquire()
            return True
        except ProfileLockError as exc:
            if not _profile_lock_is_contention(exc):
                raise
            if stop_requested():
                return False
            sleep(5.0)


def _wait_for_initial_mutation_gate(
    mutation_gate: Callable[[], None],
    *,
    stop_requested: Callable[[], bool],
    sleep: Callable[[float], None],
) -> bool:
    """Yield in HUMAN_ACTIVE until the first attach/presentation may begin."""

    from .portal_worker import ProfileLockError

    while True:
        if stop_requested():
            return False
        try:
            mutation_gate()
            if stop_requested():
                return False
            return True
        except ProfileLockError as exc:
            if not _profile_lock_is_retryable_mutation_wait(exc):
                raise
            if stop_requested():
                return False
            sleep(5.0)


class _HumanAuthStopRequested(RuntimeError):
    """Internal control flow: a read-only presentation wait was stopped."""


def run_human_auth_episode(
    site: Site,
    *,
    agent: str,
    target_id: str | None = None,
    stop_requested: Callable[[], bool] | None = None,
    owner_snapshot: Callable[[], Any] | None = None,
    mutation_sleep: Callable[[float], None] = time.sleep,
    wait_sleep: Callable[[float], None] = time.sleep,
    locator_sink: Callable[[Mapping[str, Any]], None] | None = None,
    _lease_factory: Callable[[Site], Any] | None = None,
    _target_resolver: Callable[..., BrowserTargetRef] | None = None,
    _tab_attacher: Callable[..., Any] | None = None,
    _auth_reader: Callable[[Any, Site], AuthObservation] | None = None,
    _presenter: Callable[..., LoginWindowLocator] | None = None,
    _auth_waiter: Callable[..., AuthObservation | None] | None = None,
    _cleanup: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one exact existing-target auth handoff without creating browser state."""
    if site not in _SITE_DOMAINS:
        raise ValueError(f"unsupported login site: {site!r}")
    clean_agent = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(agent)).strip("-.")[:24]
    if not clean_agent:
        raise ValueError("agent must have a safe visible name")
    if owner_snapshot is None:
        from .owner_activity import detect_owner_activity_snapshot

        mutation_owner_snapshot = detect_owner_activity_snapshot
        auth_owner_snapshot = lambda: detect_owner_activity_snapshot(
            idle_threshold_seconds=15.0,
        )
    else:
        mutation_owner_snapshot = owner_snapshot
        auth_owner_snapshot = owner_snapshot
    from .portal_worker import assert_raw_browser_mutation_allowed

    lease_factory = _lease_factory or _default_login_lease
    resolver = _target_resolver or resolve_existing_target
    attacher = _tab_attacher or _attach_exact_ref
    auth_reader = _auth_reader or read_auth_observation
    presenter = _presenter or present_exact_login_window_once
    waiter = _auth_waiter or wait_for_human_auth
    cleanup = _cleanup or cleanup_exact_login_presentation
    stop = stop_requested or (lambda: False)
    sink = locator_sink or (lambda _payload: None)
    lease = lease_factory(site)
    tab: Any | None = None
    ref: BrowserTargetRef | None = None
    locator: LoginWindowLocator | None = None
    mutation_gate: Callable[[], None] | None = None
    cleanup_attempted = False
    try:
        if not _acquire_login_lease_read_only(
            lease,
            stop_requested=stop,
            sleep=wait_sleep,
        ):
            return {"status": "human_auth_stopped", "site": site}
        ref = resolver(site, target_id=target_id)
        mutation_gate = lambda: assert_raw_browser_mutation_allowed(
            lease,
            owner_snapshot=mutation_owner_snapshot,
            sleep=mutation_sleep,
        )
        # Attach itself is read-only, but the gate here ensures a user who is
        # actively driving this exact managed browser is never even shadowed.
        # HUMAN_ACTIVE is a read-only wait state, not a terminal error.
        if not _wait_for_initial_mutation_gate(
            mutation_gate,
            stop_requested=stop,
            sleep=wait_sleep,
        ):
            return {"status": "human_auth_stopped", "site": site}
        tab = attacher({
            "id": ref.target_id,
            "type": "page",
            "url": ref.initial_url,
            "webSocketDebuggerUrl": ref.websocket_url,
        }, badge=False)
        if _tab_target_id(tab) != ref.target_id:
            raise RuntimeError("attached target identity does not match resolved target")
        initial_auth = auth_reader(tab, site)
        if _auth_matches(initial_auth, ref.initial_url):
            return {
                "status": "authenticated",
                "site": site,
                "already_authenticated": True,
                "auth_url": _sanitize_locator_url(initial_auth.url),
                "proof_names": list(initial_auth.proof_names),
            }

        if stop():
            return {"status": "human_auth_stopped", "site": site}

        def presentation_mutation_gate() -> None:
            if not _wait_for_initial_mutation_gate(
                mutation_gate,
                stop_requested=stop,
                sleep=wait_sleep,
            ):
                raise _HumanAuthStopRequested()

        episode_id = secrets.token_hex(16)
        try:
            locator = presenter(
                tab,
                ref,
                agent=clean_agent,
                mutation_gate=presentation_mutation_gate,
                episode_id=episode_id,
            )
        except _HumanAuthStopRequested:
            return {"status": "human_auth_stopped", "site": site}
        public_locator = _public_locator_payload(locator)
        sink(public_locator)
        observation = waiter(
            auth_probe=lambda: auth_reader(tab, site),
            owner_snapshot=auth_owner_snapshot,
            sleep=wait_sleep,
            stop_requested=stop,
        )
        if observation is None or stop():
            cleanup_attempted = True
            cleanup_result = cleanup(
                tab,
                ref,
                locator,
                mutation_gate=mutation_gate,
            )
            return {
                "status": "human_auth_stopped",
                "site": site,
                "window": public_locator,
                "cleanup": cleanup_result,
            }
        cleanup_attempted = True
        cleanup_result = cleanup(
            tab,
            ref,
            locator,
            mutation_gate=mutation_gate,
        )
        return {
            "status": "authenticated",
            "site": site,
            "already_authenticated": False,
            "auth_url": _sanitize_locator_url(observation.url),
            "proof_names": list(observation.proof_names),
            "window": public_locator,
            "cleanup": cleanup_result,
        }
    finally:
        if (
            tab is not None
            and ref is not None
            and mutation_gate is not None
            and not cleanup_attempted
        ):
            pending_locator = locator or getattr(
                tab,
                "_vh_human_auth_cleanup_locator",
                None,
            )
            if isinstance(pending_locator, LoginWindowLocator):
                cleanup_attempted = True
                try:
                    cleanup(
                        tab,
                        ref,
                        pending_locator,
                        mutation_gate=mutation_gate,
                    )
                except BaseException:
                    # Preserve the original stop/error while still proving that
                    # guarded cleanup was attempted.  Never fall back to an
                    # unguarded UI mutation.
                    pass
        _disconnect_websocket_only(tab)
        lease.release()


def _cleanup_keepalive_badge(
    tab: Any,
    ref: BrowserTargetRef,
    label: str,
    *,
    mutation_gate: Callable[[], None],
    document_loader_id: str = "",
    badge_bound_url: str = "",
) -> dict[str, Any]:
    try:
        live_url = _tab_current_url(tab)
    except Exception:
        return {"status": "cleanup_unreadable", "cleanup_pending": True}
    bound_url = badge_bound_url or ref.initial_url
    if not document_loader_id and live_url != bound_url:
        return {"status": "cleanup_not_applicable_navigation_changed", "cleanup_pending": False}
    if not _fresh_target_matches(tab, ref, live_url):
        return {"status": "cleanup_target_changed", "cleanup_pending": True}
    if document_loader_id and _main_document_loader_id(tab) != document_loader_id:
        return {"status": "cleanup_not_applicable_document_changed", "cleanup_pending": False}
    clear_busy = getattr(tab, "clear_busy", None)
    if not callable(clear_busy):
        return {"status": "cleanup_surface_missing", "cleanup_pending": True}
    try:
        mutation_gate()
    except Exception:
        return {"status": "cleanup_owner_active", "cleanup_pending": True}
    try:
        live_url = _tab_current_url(tab)
    except Exception:
        return {"status": "cleanup_unreadable", "cleanup_pending": True}
    if not _fresh_target_matches(tab, ref, live_url):
        return {"status": "cleanup_target_changed", "cleanup_pending": True}
    if document_loader_id and _main_document_loader_id(tab) != document_loader_id:
        return {"status": "cleanup_not_applicable_document_changed", "cleanup_pending": False}
    if not document_loader_id and live_url != bound_url:
        return {"status": "cleanup_not_applicable_navigation_changed", "cleanup_pending": False}
    if clear_busy(
        label,
        expected_url=live_url,
        badge_bound_url=bound_url,
    ) is not True:
        return {"status": "cleanup_badge_unverified", "cleanup_pending": True}
    return {"status": "cleanup_ok", "cleanup_pending": False}


def run_safe_keepalive_episode(
    site: Site,
    target: SafeKeepaliveTarget,
    *,
    agent: str,
    owner_snapshot: Callable[[], Any] | None = None,
    mutation_sleep: Callable[[float], None] = time.sleep,
    navigation_sleep: Callable[[float], None] = time.sleep,
    _lease_factory: Callable[[Site], Any] | None = None,
    _target_resolver: Callable[..., BrowserTargetRef] | None = None,
    _tab_attacher: Callable[..., Any] | None = None,
    _auth_reader: Callable[[Any, Site], AuthObservation] | None = None,
    _roundtrip: Callable[..., dict[str, Any]] | None = None,
    _cleanup_badge: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one guarded allowlisted link click and exact history Back."""
    if site not in _SITE_DOMAINS:
        raise ValueError(f"unsupported login site: {site!r}")
    clean_agent = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(agent)).strip("-.")[:24]
    if not clean_agent:
        raise ValueError("agent must have a safe visible name")
    if owner_snapshot is None:
        from .owner_activity import detect_owner_activity_snapshot

        owner_snapshot = detect_owner_activity_snapshot
    from .portal_worker import assert_raw_browser_mutation_allowed

    lease_factory = _lease_factory or _default_login_lease
    resolver = _target_resolver or resolve_existing_target
    attacher = _tab_attacher or _attach_exact_ref
    auth_reader = _auth_reader or read_auth_observation
    roundtrip = _roundtrip or execute_keepalive_roundtrip
    cleanup_badge = _cleanup_badge or _cleanup_keepalive_badge
    lease = lease_factory(site)
    tab: Any | None = None
    ref: BrowserTargetRef | None = None
    mutation_gate: Callable[[], None] | None = None
    label = ""
    badge_bound_url = ""
    badge_document_loader_id = ""
    badge_attempted = False
    cleanup_attempted = False
    try:
        _acquire_login_lease_read_only(
            lease,
            stop_requested=lambda: False,
            sleep=navigation_sleep,
        )
        ref = resolver(site, target_id=target.target_id)
        mutation_gate = lambda: assert_raw_browser_mutation_allowed(
            lease,
            owner_snapshot=owner_snapshot,
            sleep=mutation_sleep,
        )
        try:
            mutation_gate()
        except Exception as exc:
            from .portal_worker import ProfileLockError

            if isinstance(exc, ProfileLockError):
                if _profile_lock_is_retryable_mutation_wait(exc):
                    return {
                        "status": "skipped_owner_active",
                        "site": site,
                        "restore_pending": False,
                    }
                raise
            raise
        tab = attacher({
            "id": ref.target_id,
            "type": "page",
            "url": ref.initial_url,
            "webSocketDebuggerUrl": ref.websocket_url,
        }, badge=False)
        if _tab_target_id(tab) != ref.target_id:
            raise RuntimeError("attached target identity does not match resolved target")
        source_auth = auth_reader(tab, site)
        if not _auth_matches(source_auth, target.source_url):
            return {
                "status": "auth_required",
                "site": site,
                "restore_pending": False,
            }
        if not _safe_keepalive_descriptor(ref, target):
            return {
                "status": "skipped_unsafe",
                "site": site,
                "restore_pending": False,
            }
        marker, _suffix = _login_title_marker(clean_agent, site, ref.target_id)
        label = marker.replace("LOGIN HERE", "KEEPALIVE")
        badge_bound_url = ref.initial_url
        try:
            mutation_gate()
        except Exception as exc:
            from .portal_worker import ProfileLockError

            if isinstance(exc, ProfileLockError):
                if _profile_lock_is_retryable_mutation_wait(exc):
                    return {
                        "status": "skipped_owner_active",
                        "site": site,
                        "restore_pending": False,
                    }
                raise
            raise
        mark_busy = getattr(tab, "mark_busy", None)
        badge_attempted = True
        if not callable(mark_busy) or mark_busy(label, expected_url=ref.initial_url) is not True:
            return {
                "status": "badge_failed",
                "site": site,
                "restore_pending": False,
            }
        badge_document_loader_id = _main_document_loader_id(tab)
        result = roundtrip(
            tab,
            ref,
            target,
            auth_probe=lambda current: auth_reader(current, site),
            mutation_gate=mutation_gate,
            sleep=navigation_sleep,
        )
        cleanup_attempted = True
        cleanup_result = cleanup_badge(
            tab,
            ref,
            label,
            mutation_gate=mutation_gate,
            document_loader_id=badge_document_loader_id,
            badge_bound_url=badge_bound_url,
        )
        return {**result, "site": site, "cleanup": cleanup_result}
    finally:
        if (
            badge_attempted
            and not cleanup_attempted
            and tab is not None
            and ref is not None
            and mutation_gate is not None
            and label
        ):
            cleanup_attempted = True
            try:
                cleanup_badge(
                    tab,
                    ref,
                    label,
                    mutation_gate=mutation_gate,
                    document_loader_id=badge_document_loader_id,
                    badge_bound_url=badge_bound_url,
                )
            except BaseException:
                pass
        _disconnect_websocket_only(tab)
        lease.release()


def keepalive_due(site: Site, *, last_at: float | None, now: float) -> bool:
    """마지막 keepalive 이후 주기가 지났는가. 첫 회차(last_at=None)는 항상 due."""
    if last_at is None:
        return True
    return (now - last_at) >= KEEPALIVE_INTERVAL_SECONDS[site]


_SAFE_TARGET_JSON_KEYS = frozenset({
    "target_id",
    "source_url",
    "selector",
    "destination_url",
    "method",
    "target_attr",
    "download",
    "dedicated_tab",
    "clean_form",
    "previously_opened_free",
    "risk_labels",
})


def load_safe_keepalive_target(path_value: str | os.PathLike[str]) -> SafeKeepaliveTarget:
    """Load one owner-audited descriptor without accepting extra secret fields."""
    path = Path(path_value).expanduser()
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError("safe keepalive target record is unavailable") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or info.st_size <= 0
        or info.st_size > 64 * 1024
        or info.st_mode & 0o022
    ):
        raise ValueError("safe keepalive target record is not a protected regular file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ValueError("safe keepalive target record has a different owner")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("safe keepalive target record is invalid JSON") from exc
    if not isinstance(payload, Mapping) or set(payload) != _SAFE_TARGET_JSON_KEYS:
        raise ValueError("safe keepalive target record has an unexpected schema")
    risk_labels = payload.get("risk_labels")
    if not isinstance(risk_labels, list) or not all(
        isinstance(label, str) and 0 < len(label) <= 64 for label in risk_labels
    ):
        raise ValueError("safe keepalive risk labels are invalid")
    for key in ("target_id", "source_url", "selector", "destination_url", "method", "target_attr"):
        if not isinstance(payload.get(key), str) or not str(payload[key]).strip():
            raise ValueError(f"safe keepalive {key} is invalid")
    for key in ("download", "dedicated_tab", "clean_form", "previously_opened_free"):
        if not isinstance(payload.get(key), bool):
            raise ValueError(f"safe keepalive {key} is invalid")
    if (
        str(payload["method"]).strip().upper() != "GET"
        or str(payload["target_attr"]).strip().casefold() not in {"", "_self"}
        or payload["download"] is not False
        or payload["dedicated_tab"] is not True
        or payload["clean_form"] is not True
        or payload["previously_opened_free"] is not True
    ):
        raise ValueError("safe keepalive target record is not a read-only audited link")
    return SafeKeepaliveTarget(
        target_id=str(payload["target_id"]),
        source_url=str(payload["source_url"]),
        selector=str(payload["selector"]),
        destination_url=str(payload["destination_url"]),
        method=str(payload["method"]),
        target_attr=str(payload["target_attr"]),
        download=payload["download"],
        dedicated_tab=payload["dedicated_tab"],
        clean_form=payload["clean_form"],
        previously_opened_free=payload["previously_opened_free"],
        risk_labels=tuple(risk_labels),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI for the actual exact-target human-auth and keepalive runners."""
    import argparse

    parser = argparse.ArgumentParser(description="exact existing-target login session guard")
    commands = parser.add_subparsers(dest="command", required=True)
    auth = commands.add_parser("human-auth", help="present one exact window and wait read-only")
    auth.add_argument("--site", required=True, choices=sorted(KEEPALIVE_INTERVAL_SECONDS))
    auth.add_argument("--agent", required=True)
    auth.add_argument(
        "--target-id",
        default=None,
        help="exact existing CDP target id (required when the managed browser has multiple site tabs)",
    )
    keepalive = commands.add_parser("keepalive", help="one audited click and exact history Back")
    keepalive.add_argument("--site", required=True, choices=sorted(KEEPALIVE_INTERVAL_SECONDS))
    keepalive.add_argument("--agent", required=True)
    keepalive.add_argument("--safe-target-json", required=True)
    args = parser.parse_args(argv)
    site: Site = args.site

    if args.command == "human-auth":
        result = run_human_auth_episode(
            site,
            agent=args.agent,
            target_id=args.target_id,
            locator_sink=lambda payload: print(json.dumps(payload, ensure_ascii=False)),
        )
    else:
        target = load_safe_keepalive_target(args.safe_target_json)
        result = run_safe_keepalive_episode(site, target, agent=args.agent)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
