"""로그인 세션가드 — exact target, 사람 로그인 대기, 안전 keepalive.

직전 세션의 session_guard/vault/cdp_util/launch_chrome 아이디어(쿠키 스냅샷 롤링,
2단계 판정, LinkedIn 단일기기·자동로그인 금지)를 **새 scripts/ 트리 없이** v5 기존
인프라 위에 재작성한 것(2026-07-17 /st 지시 5). 역할 분담:

- 브라우저 접속: ``raw_cdp``(단일 탭 attach, 종료=WebSocket 해제만) 재사용 — 재발명 금지.
- 사람 점유 감지: ``owner_activity.detect_owner_activity_snapshot`` 재사용.
  **keepalive 직전마다 호출이 필수**이며, 감지 실패는 fail-closed(사용 중 간주).
- 자격증명 저장: ``portal_keychain``(키체인) 재사용 — 이 모듈은 비밀번호를 다루지 않는다.

이 모듈은 과거의 쿠키 판정 보조 함수도 호환용으로 남기지만 쿠키 존재를 keepalive
성공으로 보지 않는다. 실제 성공은 exact target에서 allowlist 링크를 한 번 클릭하고,
``Page.navigateToHistoryEntry``로 원래 history entry를 복원한 뒤 URL과 로그인 마커를
모두 재검증했을 때뿐이다.

⚠️ CDP 쿠키 조회(``fetch_cookies_via_cdp``)는 **실크롬 왕복 검증 전 = 미검증** 상태다.
실크롬에서 왕복(쿠키 조회 → 스냅샷 → 재조회 일치) 증거를 남기기 전까지 "검증됨"이라
표기하지 않는다(/st 지시 5). 실패 시 None 을 돌려 2단계 판정이 probe 로 폴백한다.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

Site = Literal["saramin", "jobkorea", "linkedin_rps"]
CookieEvidence = Literal["present", "absent", "unknown"]
KeepaliveAction = Literal[
    "skip_not_due", "skip_owner_active", "probe_readonly", "reauth", "human_wait",
]


@dataclass(frozen=True)
class BrowserTargetRef:
    """One exact existing page target in one managed browser profile."""

    site: Site
    endpoint: str
    target_id: str
    websocket_url: str
    initial_url: str
    profile_path: str = ""


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
    _original_title: str = field(default="", repr=False, compare=False)

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

# 1단계(쿠키) 판정에 쓰는 세션 쿠키 이름.
SESSION_COOKIE_NAMES: dict[Site, tuple[str, ...]] = {
    "saramin": ("JSESSIONID",),
    "jobkorea": ("ASP.NET_SessionId",),
    "linkedin_rps": ("li_at",),
}

_SITE_DOMAINS: dict[Site, str] = {
    "saramin": "saramin.co.kr",
    "jobkorea": "jobkorea.co.kr",
    "linkedin_rps": "linkedin.com",
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

DEFAULT_SNAPSHOT_ROOT = Path.home() / ".valuehire" / "session_snapshots"


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


def _managed_profile_path(site: Site, env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    configured = str(source.get(_SITE_PROFILE_ENV[site]) or "").strip()
    return configured or str(_SITE_DEFAULT_PROFILES[site])


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
    if managed_endpoint_resolver is None:
        from .portal_worker import resolve_managed_channel_cdp_endpoint

        managed_endpoint_resolver = resolve_managed_channel_cdp_endpoint
    if list_pages is None:
        from .raw_cdp import list_pages as raw_list_pages

        list_pages = raw_list_pages

    endpoint = _local_cdp_endpoint(str(managed_endpoint_resolver(site)).strip())
    pages = list_pages(endpoint)
    wanted_id = str(target_id or "").strip()
    matches: list[Mapping[str, Any]] = []
    for target in pages or ():
        if not isinstance(target, Mapping) or target.get("type") != "page":
            continue
        current_id = _target_identifier(target)
        current_url = str(target.get("url") or "")
        websocket_url = str(target.get("webSocketDebuggerUrl") or "").strip()
        if not current_id or not websocket_url or not _official_site_url(site, current_url):
            continue
        if wanted_id and current_id != wanted_id:
            continue
        matches.append(target)
    if len(matches) != 1:
        detail = "exact target id" if wanted_id else "unique site target"
        raise LookupError(f"{site} {detail} match count was {len(matches)}")

    selected = matches[0]
    return BrowserTargetRef(
        site=site,
        endpoint=endpoint,
        target_id=_target_identifier(selected),
        websocket_url=str(selected["webSocketDebuggerUrl"]),
        initial_url=str(selected["url"]),
        profile_path=_managed_profile_path(site, env),
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

        idle = getattr(snapshot, "idle_seconds", None)
        valid_idle = (
            snapshot is not None
            and getattr(snapshot, "detection_status", "") == "ok"
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

    script = """
(() => {
  const visible = (selector) => Array.from(document.querySelectorAll(selector)).some((e) => {
    const s = getComputedStyle(e); const r = e.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0' && r.width > 0 && r.height > 0;
  });
  const text = (document.body && document.body.innerText || '').slice(0, 50000);
  return {
    url: location.href,
    text: text,
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
    text = str(raw.get("text") or "")
    folded = f"{text} {url}".casefold()
    challenge_tokens = (
        "captcha", "checkpoint", "challenge", "authwall", "multiple sign-ins",
        "only one session", "enterprise-authentication", "보안문자", "2단계", "인증번호",
    )
    challenge = any(token.casefold() in folded for token in challenge_tokens)
    proofs: list[str] = []
    authenticated = False
    if site == "saramin":
        account = "로그아웃" in text or "valueconnect" in folded or "value connect" in folded
        search = raw.get("saraminSearch") is True
        if account:
            proofs.append("account_or_logout")
        if search:
            proofs.append("talent_search_controls")
        authenticated = bool(account and search and _official_site_url(site, url))
    elif site == "jobkorea":
        logout = "로그아웃" in text
        account = "밸류커넥트" in text or "valueconnect" in folded or "value connect" in folded
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
        authenticated = bool(surface and account and search)
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
    return bool(
        target.target_id == ref.target_id
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


def _auth_matches(observation: Any, expected_url: str) -> bool:
    return bool(
        isinstance(observation, AuthObservation)
        and observation.authenticated is True
        and observation.challenge is False
        and observation.url == expected_url
        and observation.proof_names
    )


def _history_source_entry(tab: Any, source_url: str) -> int | str | None:
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
    if isinstance(entry_id, bool) or not isinstance(entry_id, (int, str)) or entry_id == "":
        return None
    return entry_id


def _wait_for_authenticated_url(
    tab: Any,
    expected_url: str,
    *,
    auth_probe: Callable[[Any], AuthObservation],
    sleep: Callable[[float], None],
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        try:
            if _auth_matches(auth_probe(tab), expected_url):
                return True
        except Exception:
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        sleep(min(0.1, remaining))


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
    if _tab_target_id(tab) != ref.target_id:
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
    except Exception:
        return {"status": "skipped_owner_active", "restore_pending": False}
    click = getattr(tab, "click_safe_link", None)
    if not callable(click):
        return {"status": "skipped_atomic_click_unavailable", "restore_pending": False}
    try:
        clicked = click(target)
    except Exception:
        clicked = False
    if clicked is not True:
        return {"status": "click_failed", "restore_pending": False}

    if _tab_target_id(tab) != ref.target_id:
        return {"status": "target_changed", "restore_pending": True}

    destination_auth = _wait_for_authenticated_url(
        tab,
        target.destination_url,
        auth_probe=auth_probe,
        sleep=sleep,
        timeout_seconds=navigation_timeout_seconds,
    )

    try:
        mutation_gate()
    except Exception:
        return {
            "status": "restore_pending",
            "restore_pending": True,
            "source_entry_id": source_entry_id,
            "destination_verified": destination_auth,
        }
    if _tab_target_id(tab) != ref.target_id:
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

    if _tab_target_id(tab) != ref.target_id:
        return {
            "status": "target_changed_after_restore",
            "restore_pending": True,
        }

    restored_auth = _wait_for_authenticated_url(
        tab,
        target.source_url,
        auth_probe=auth_probe,
        sleep=sleep,
        timeout_seconds=navigation_timeout_seconds,
    )
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


def _unique_browser_pid(tab: Any) -> int:
    result = tab.send("SystemInfo.getProcessInfo")
    values = result.get("processInfo") if isinstance(result, Mapping) else None
    pids = {
        int(item["id"])
        for item in (values or ())
        if isinstance(item, Mapping)
        and str(item.get("type") or "").casefold() == "browser"
        and not isinstance(item.get("id"), bool)
        and isinstance(item.get("id"), (int, float))
        and float(item["id"]).is_integer()
        and int(item["id"]) > 0
    }
    if len(pids) != 1:
        raise RuntimeError(f"unique browser PID match count was {len(pids)}")
    return next(iter(pids))


def present_exact_login_window_once(
    tab: Any,
    ref: BrowserTargetRef,
    *,
    agent: str,
    mutation_gate: Callable[[], None],
    state: str = "AI_ATTACHED",
    window_resolver: Callable[..., Any] | None = None,
    window_capture: Callable[..., bytes] | None = None,
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
    original_title = str(tab.eval("document.title") or "")
    site_label = "LinkedIn RPS" if ref.site == "linkedin_rps" else ref.site
    # Never echo the previous page title: it can contain a candidate name or a
    # search query.  Site + sanitized URL are reported separately.
    visible_title = f"{marker} {site_label} login"
    browser_pid = _unique_browser_pid(tab)
    window_result = tab.send("Browser.getWindowForTarget", {"targetId": ref.target_id})
    raw_bounds = window_result.get("bounds") if isinstance(window_result, Mapping) else None
    if not isinstance(raw_bounds, Mapping):
        raise RuntimeError("CDP window bounds are unavailable")
    from .macos_window_locator import (
        CdpWindowIdentity,
        WindowBounds,
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
    # First resolve by exact PID+bounds without reading any title.  If this is
    # ambiguous, fail before title/badge/focus mutations.  After focus, resolve
    # again with the unique marker and require the same CGWindowID.
    preflight_window = resolve(CdpWindowIdentity(
        browser_pid=browser_pid,
        target_id=ref.target_id,
        title_marker="",
        bounds=bounds,
    ))

    presentation_key = (ref.site, ref.endpoint, ref.target_id)
    if getattr(tab, "_vh_human_auth_presentation_key", None) == presentation_key:
        raise RuntimeError("exact login window was already presented for this auth episode")
    # Claim before the first mutation: a partial failure must not cause repeated
    # title/focus/capture attempts that steal the owner's foreground again.
    setattr(tab, "_vh_human_auth_presentation_key", presentation_key)

    mutation_gate()
    title_result = tab.eval(
        "(function(){if(location.href!==" + json.dumps(live_url) +
        ")return null;document.title=" + json.dumps(visible_title) +
        ";return document.title;})()"
    )
    if title_result != visible_title:
        raise RuntimeError("exact target title marker could not be installed")

    mutation_gate()
    marker_fn = getattr(tab, "mark_busy", None)
    if not callable(marker_fn) or marker_fn(marker, expected_url=live_url) is not True:
        raise RuntimeError("visible login-window marker could not be installed")

    mutation_gate()
    tab.send("Page.bringToFront")

    window = resolve(CdpWindowIdentity(
        browser_pid=browser_pid,
        target_id=ref.target_id,
        title_marker=marker,
        bounds=bounds,
    ))
    if window.cg_window_id != preflight_window.cg_window_id:
        raise RuntimeError("exact login window identity changed after focus")
    png = capture(window.cg_window_id)
    if not isinstance(png, bytes) or not png:
        raise RuntimeError("exact login-window capture is empty")
    return LoginWindowLocator(
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
        _original_title=original_title,
    )


def keepalive_due(site: Site, *, last_at: float | None, now: float) -> bool:
    """마지막 keepalive 이후 주기가 지났는가. 첫 회차(last_at=None)는 항상 due."""
    if last_at is None:
        return True
    return (now - last_at) >= KEEPALIVE_INTERVAL_SECONDS[site]


def classify_cookie_evidence(site: Site, cookies: list[dict[str, Any]] | None) -> CookieEvidence:
    """Return domain-bound cookie evidence; values are never inspected or logged."""
    if cookies is None:
        return "unknown"
    official = _SITE_DOMAINS[site]
    for cookie in cookies:
        name = str(cookie.get("name") or "")
        domain = str(cookie.get("domain") or "").strip().lstrip(".").rstrip(".").casefold()
        domain_ok = domain == official or domain.endswith("." + official)
        if domain_ok and name in SESSION_COOKIE_NAMES[site]:
            return "present"
    return "absent"


def decide_keepalive(
    site: Site, *, due: bool, owner_active: bool, cookie_evidence: CookieEvidence,
) -> KeepaliveAction:
    """keepalive 1회차의 행동 결정 (순수함수 — 판정 우선순위가 곧 SOT-28 계약).

    1) 사람 점유 최우선: owner_active 면 due 여도 건너뛴다(§4 — 사장님을 앞지르지 않는다).
    2) due 아니면 아무것도 안 한다(분 단위 과잉 클릭 금지).
    3) 쿠키 present/unknown → 진단 증거일 뿐이며 읽기 전용 probe가 필요하다.
    5) absent → 사람인·잡코리아는 자동 재로그인(§3), LinkedIn 은 human_wait
       (자동 폼 로그인 금지 + 계정당 단일 기기, §3a·§5).
    """
    if owner_active:
        return "skip_owner_active"
    if not due:
        return "skip_not_due"
    if cookie_evidence in {"present", "unknown"}:
        return "probe_readonly"
    if site == "linkedin_rps":
        return "human_wait"
    return "reauth"


def save_cookie_snapshot(
    site: Site, cookies: list[dict[str, Any]], *,
    root: Path = DEFAULT_SNAPSHOT_ROOT, keep: int = 5, now: float | None = None,
) -> Path:
    """Persist only non-secret cookie metadata, never values or token material."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    stamp = f"{(time.time() if now is None else now):.3f}".replace(".", "")
    path = root / f"{site}-{stamp}.json"
    safe_keys = ("name", "domain", "path", "secure", "httpOnly", "sameSite", "session")
    metadata = [
        {key: cookie[key] for key in safe_keys if key in cookie}
        for cookie in cookies
        if isinstance(cookie, Mapping)
    ]
    payload = {
        "site": site,
        "saved_at": now if now is not None else time.time(),
        "cookies": metadata,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    # O_CREAT 의 0600 은 "새 파일"에만 적용 — 선존재 파일은 이전 권한이 유지된다
    # (V1 적대검증 반례 2026-07-18). 비밀 쿠키 파일이므로 무조건 0600 강제.
    os.chmod(path, 0o600)
    snapshots = sorted(root.glob(f"{site}-*.json"), key=lambda p: p.name)
    for old in snapshots[:-keep]:
        old.unlink(missing_ok=True)
    return path


def fetch_cookies_via_cdp(tab: Any) -> list[dict[str, Any]] | None:
    """CDP 로 현재 브라우저의 쿠키를 읽는다 — ⚠️ 실크롬 왕복 검증 전(미검증).

    ``raw_cdp.CDPTab.send`` 계약만 사용한다. Storage.getCookies(브라우저 전역) 우선,
    구버전 호환으로 Network.getCookies 폴백. 어떤 실패든 None(=unknown 판정 → probe
    폴백)으로 삼켜 keepalive 를 죽이지 않는다. 반환 쿠키는 비밀값 — 로그 금지.
    """
    for method in ("Storage.getCookies", "Network.getCookies"):
        try:
            result = tab.send(method)
        except Exception:
            continue
        cookies = result.get("cookies") if isinstance(result, dict) else None
        if isinstance(cookies, list):
            return cookies
    return None


def run_keepalive_once(
    site: Site, *,
    owner_snapshot: Any,
    tab_factory: Any,
    last_at: float | None,
    now: float | None = None,
    snapshot_root: Path = DEFAULT_SNAPSHOT_ROOT,
) -> dict[str, Any]:
    """keepalive 1회차 오케스트레이션 — 판정 순서가 곧 계약.

    ① owner_activity 확인(브라우저를 건드리기 **전**) → 사용 중이면 즉시 종료.
    ② due 계산 → 아니면 종료. ③ 그때만 tab_factory() 로 CDP attach(읽기 전용) 후
    쿠키 1단계 판정, present 면 스냅샷 롤링 저장. probe/reauth/human_wait 은 실행하지
    않고 action 으로만 보고한다(실행은 기존 러너 — portal_login §3 자동 재로그인 경로).
    끝나면 tab.close() = WebSocket 해제만(raw_cdp 계약 — 탭/브라우저는 살아있다).
    """
    now = time.time() if now is None else now
    snap = owner_snapshot()
    owner_active = bool(getattr(snap, "owner_activity_detected", True))
    due = keepalive_due(site, last_at=last_at, now=now)
    base = {"site": site, "at": now, "owner_active": owner_active, "due": due}
    if owner_active or not due:
        action = decide_keepalive(site, due=due, owner_active=owner_active,
                                  cookie_evidence="unknown")
        return {**base, "action": action, "cookie_evidence": None}
    tab = tab_factory()
    try:
        cookies = fetch_cookies_via_cdp(tab)
        evidence = classify_cookie_evidence(site, cookies)
        action = decide_keepalive(site, due=True, owner_active=False, cookie_evidence=evidence)
        if evidence == "present" and cookies is not None:
            save_cookie_snapshot(site, cookies, root=snapshot_root, now=now)
        return {**base, "action": action, "cookie_evidence": evidence}
    finally:
        try:
            disconnect = getattr(tab, "disconnect", None)
            if callable(disconnect):
                disconnect()  # WebSocket only; never clear a badge while owner-active.
            else:
                tab.close()  # Legacy test/fake compatibility when no disconnect surface exists.
        except Exception:
            pass


def _default_tab_factory(site: Site, *, target_id: str | None = None) -> Any:
    from . import raw_cdp

    ref = resolve_existing_target(site, target_id=target_id)
    return raw_cdp.attach(
        {
            "id": ref.target_id,
            "type": "page",
            "url": ref.initial_url,
            "webSocketDebuggerUrl": ref.websocket_url,
        },
        badge=False,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m tools.multi_position_sourcing.session_guard --site saramin`.

    결과 JSON 1줄(stdout). 쿠키 값은 절대 출력하지 않는다(evidence 분류만).
    """
    import argparse

    parser = argparse.ArgumentParser(description="session keepalive one round (read-only)")
    parser.add_argument("--site", required=True, choices=sorted(KEEPALIVE_INTERVAL_SECONDS))
    parser.add_argument(
        "--target-id",
        default=None,
        help="exact existing CDP target id (required when the managed browser has multiple site tabs)",
    )
    parser.add_argument("--last-at", type=float, default=None)
    args = parser.parse_args(argv)
    site: Site = args.site

    from .owner_activity import detect_owner_activity_snapshot

    result = run_keepalive_once(
        site,
        owner_snapshot=detect_owner_activity_snapshot,
        tab_factory=lambda: _default_tab_factory(site, target_id=args.target_id),
        last_at=args.last_at,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
