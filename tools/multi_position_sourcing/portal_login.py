from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Channel
from .portal_safety import safe_artifact_url, safe_exception_label
from .portal_worker import (
    DEFAULT_PROFILE_ROOT,
    PortalWorker,
    PortalWorkerConfig,
    _close_page_if_possible,
    resolve_chrome_cdp_endpoint,
)

DEFAULT_PROFILE_ROOT_PATH = str(DEFAULT_PROFILE_ROOT)
DEFAULT_STATUS_OUTPUT = "artifacts/portal_session_status_latest.json"
DEFAULT_ENV_FILE = ".env.local"
DEFAULT_CHANNEL_TIMEOUT_SECONDS = 180
SARAMIN_SEARCH_URL = "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
JOBKOREA_SEARCH_URL = "https://www.jobkorea.co.kr/Corp/Person/Find"
LINKEDIN_RPS_HOME_URL = "https://www.linkedin.com/talent/home"
ReadyCheck = Callable[[Any], Awaitable[bool]]
PreflightSnapshotCapture = Callable[..., Awaitable[dict[str, object]]]


def utc_now_portal_login() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class HumanInterventionOptions:
    enabled: bool = True
    timeout_seconds: int = 900
    poll_interval_seconds: int = 5


def load_env_file(path: str | Path) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def _close_popups(page: Any) -> None:
    for text in ("닫기", "오늘 하루 보지 않기", "확인"):
        try:
            locator = page.get_by_text(text, exact=True)
            if await locator.count():
                await locator.first.click(timeout=1000)
        except Exception:
            pass
    for selector in ('button[aria-label="닫기"]', ".btn_close", ".close", 'button:has-text("X")'):
        try:
            locator = page.locator(selector)
            if await locator.count():
                await locator.first.click(timeout=1000)
        except Exception:
            pass


async def _body_text(page: Any, limit: int = 3000) -> str:
    try:
        return (await page.locator("body").inner_text(timeout=5000))[:limit]
    except Exception:
        return ""


def _has_security_challenge(text: str, url: str = "") -> bool:
    challenge_terms = ("보안문자", "CAPTCHA", "2단계", "인증번호", "이상 접근", "checkpoint", "challenge")
    haystack = f"{text} {url}".lower()
    return any(term.lower() in haystack for term in challenge_terms)


def _result(channel: Channel, *, ready: bool, login: str, note: str = "", url: str = "") -> dict[str, object]:
    return {
        "channel": channel,
        "ready": ready,
        "login": login,
        "note": note,
        "url": safe_artifact_url(url),
    }


def _first_env(source: dict[str, str] | os._Environ[str], names: tuple[str, ...]) -> str:
    for name in names:
        value = source.get(name, "").strip()
        if value:
            return value
    return ""


def _preflight_supabase_config_from_env(source: dict[str, str] | os._Environ[str] | None = None) -> Any:
    from .portal_snapshot import SupabaseRestConfig

    env = os.environ if source is None else source
    url = _first_env(env, ("SUPABASE_URL", "VALUEHIRE_SUPABASE_URL"))
    service_role_key = _first_env(env, ("SUPABASE_SERVICE_ROLE_KEY", "VALUEHIRE_SUPABASE_SERVICE_ROLE_KEY"))
    if not url:
        raise RuntimeError("SUPABASE_URL or VALUEHIRE_SUPABASE_URL is required")
    if not service_role_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY or VALUEHIRE_SUPABASE_SERVICE_ROLE_KEY is required")
    return SupabaseRestConfig(url=url, service_role_key=service_role_key)


async def _capture_preflight_snapshot(
    *,
    context: Any,
    channel: Channel,
    worker_id: str,
    playwright: Any,
    ready_check: ReadyCheck,
    browser: Any | None = None,
) -> dict[str, object]:
    from .portal_snapshot import (
        MacKeychainSessionKeyProvider,
        OpenSslSessionEncryptor,
        SupabaseSessionSnapshotStore,
        capture_validated_snapshot,
        validate_snapshot_by_reinjection,
    )

    supabase_config = _preflight_supabase_config_from_env()
    encryptor = OpenSslSessionEncryptor(MacKeychainSessionKeyProvider())
    snapshot_store = SupabaseSessionSnapshotStore(supabase_config)
    record = await capture_validated_snapshot(
        context=context,
        site=channel,
        worker_id=worker_id,
        encryptor=encryptor,
        store=snapshot_store,
        validator=lambda state: validate_snapshot_by_reinjection(
            playwright=playwright,
            site=channel,
            state=state,
            ready_check=ready_check,
            browser=browser,
        ),
    )
    return {
        "snapshot_captured": record is not None,
        "snapshot_capture_status": "captured" if record is not None else "rejected_by_validation",
    }


async def _with_preflight_snapshot_status(
    result: dict[str, object],
    *,
    context: Any,
    channel: Channel,
    worker_id: str,
    playwright: Any,
    ready_check: ReadyCheck | None,
    browser: Any | None = None,
    snapshot_capture: PreflightSnapshotCapture | None = None,
) -> dict[str, object]:
    if channel == "public_web":
        return {
            **result,
            "snapshot_capture_required": False,
            "snapshot_captured": False,
            "snapshot_capture_status": "not_required",
        }
    if result.get("ready") is not True or ready_check is None:
        return {
            **result,
            "snapshot_capture_required": True,
            "snapshot_captured": False,
            "snapshot_capture_status": "skipped_not_ready",
        }

    capture = snapshot_capture or _capture_preflight_snapshot
    try:
        snapshot = await capture(
            context=context,
            channel=channel,
            worker_id=worker_id,
            playwright=playwright,
            ready_check=ready_check,
            browser=browser,
        )
    except Exception as exc:
        return {
            **result,
            "snapshot_capture_required": True,
            "snapshot_captured": False,
            "snapshot_capture_status": "unavailable",
            "snapshot_capture_note": safe_exception_label(exc, action="preflight snapshot capture failed"),
        }
    return {
        **result,
        "snapshot_capture_required": True,
        "snapshot_captured": bool(snapshot.get("snapshot_captured")),
        "snapshot_capture_status": str(snapshot.get("snapshot_capture_status") or "unknown"),
    }


async def _wait_for_human_intervention(
    page: Any,
    channel: Channel,
    *,
    ready_check: ReadyCheck,
    options: HumanInterventionOptions,
    note: str,
) -> dict[str, object]:
    if not options.enabled:
        return _result(channel, ready=False, login="human_intervention_disabled", note=note, url=getattr(page, "url", ""))

    print(
        f"[{channel}] human intervention required: {note}. "
        f"Resolve the visible browser challenge/login, then wait for automatic resume "
        f"for up to {options.timeout_seconds}s.",
        flush=True,
    )

    elapsed = 0
    while elapsed <= options.timeout_seconds:
        if await ready_check(page):
            return _result(
                channel,
                ready=True,
                login="human_intervention_ok",
                note="human completed portal challenge/login and session was revalidated",
                url=getattr(page, "url", ""),
            )
        await page.wait_for_timeout(max(1, options.poll_interval_seconds) * 1000)
        elapsed += max(1, options.poll_interval_seconds)

    return _result(
        channel,
        ready=False,
        login="human_intervention_timeout",
        note=f"{note}; human intervention did not complete within {options.timeout_seconds}s",
        url=getattr(page, "url", ""),
    )


async def _saramin_search_ready(page: Any) -> bool:
    text = await _body_text(page)
    if _has_security_challenge(text, getattr(page, "url", "")):
        return False
    if "talent-pool" not in getattr(page, "url", ""):
        try:
            await page.goto("https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1500)
            await _close_popups(page)
        except Exception:
            return False
    text = await _body_text(page)
    has_search = await page.locator("input.search_input, #career_min, #career_max").count()
    return bool(has_search or "로그아웃" in text)


async def _jobkorea_search_ready(page: Any) -> bool:
    text = await _body_text(page)
    if _has_security_challenge(text, getattr(page, "url", "")):
        return False
    if "/Corp/Person/Find" not in getattr(page, "url", ""):
        try:
            await page.goto("https://www.jobkorea.co.kr/Corp/Person/Find", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1500)
            await _close_popups(page)
        except Exception:
            return False
    return bool(await page.locator("#txtKeyword, input[placeholder*='키워드'], input[placeholder*='검색']").count())


async def _linkedin_rps_ready(page: Any) -> bool:
    text = await _body_text(page)
    if _has_security_challenge(text, getattr(page, "url", "")):
        return False
    if "/talent/" not in getattr(page, "url", "") or "login" in getattr(page, "url", "").lower():
        try:
            await page.goto("https://www.linkedin.com/talent/home", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2000)
            await _close_popups(page)
        except Exception:
            return False
    url = getattr(page, "url", "")
    if "/talent/" not in url or "login" in url.lower():
        return False
    # A logged-out LinkedIn redirects /talent/* back to a login wall, so also require a
    # Recruiter search affordance — a URL check alone is not a reliable login marker.
    has_recruiter_search = await page.locator('a[href*="/talent/search"], input[role="combobox"]').count()
    return bool(has_recruiter_search)


def ready_check_for_channel(channel: Channel) -> ReadyCheck:
    if channel == "saramin":
        return _saramin_search_ready
    if channel == "jobkorea":
        return _jobkorea_search_ready
    if channel == "linkedin_rps":
        return _linkedin_rps_ready
    raise ValueError(f"{channel} does not require protected portal readiness")


async def _auto_login_session(context: Any, channel: Channel) -> dict[str, object]:
    """Submit stored credentials to log in automatically for Saramin/Jobkorea/LinkedIn RPS.

    SOT invariant (docs/search-access.md): all three protected portals auto-login from the
    secret store — never re-disable LinkedIn here. A captcha / 2FA / checkpoint is never
    bypassed (see portal_autologin.auto_relogin_portal); on detection the automation stops
    and the caller falls back to human intervention rather than submitting into the challenge.
    """
    from .portal_autologin import auto_relogin_portal
    from .portal_recovery import MacKeychainPortalCredentialProvider, PortalCredentialError

    try:
        credentials = MacKeychainPortalCredentialProvider().load(channel)
    except PortalCredentialError:
        return _result(
            channel,
            ready=False,
            login="credentials_not_configured",
            note=(
                "macOS Keychain valuehire.portal_credentials entries are required "
                f"for {channel} automatic login; run init-portal-credentials first"
            ),
        )
    except Exception as exc:
        return _result(
            channel,
            ready=False,
            login="credentials_not_configured",
            note=(
                "macOS Keychain valuehire.portal_credentials entries could not be read "
                f"for {channel} automatic login ({type(exc).__name__})"
            ),
        )
    try:
        ready = await auto_relogin_portal(context, channel, credentials)
    except Exception as exc:
        return _result(
            channel,
            ready=False,
            login="auto_login_error",
            note=f"{type(exc).__name__}: automatic login failed without exposing details",
        )
    if ready:
        return _result(channel, ready=True, login="auto_login_ok", note="automation submitted stored credentials and revalidated the session")
    return _result(
        channel,
        ready=False,
        login="auto_login_failed",
        note="automatic login did not reach a ready session (possible captcha/2FA/checkpoint, which is not bypassed)",
    )


async def _saramin_session(context: Any, options: HumanInterventionOptions) -> dict[str, object]:
    channel: Channel = "saramin"
    page = await context.new_page()
    try:
        await page.goto(SARAMIN_SEARCH_URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(1500)
        await _close_popups(page)

        if await _saramin_search_ready(page):
            return _result(channel, ready=True, login="existing_session_ok", url=page.url)

        if _has_security_challenge(await _body_text(page), getattr(page, "url", "")):
            return await _wait_for_human_intervention(
                page,
                channel,
                ready_check=_saramin_search_ready,
                options=options,
                note="security challenge (captcha/2FA/IP) detected; resolve it in the visible browser — automation never bypasses challenges",
            )

        auto = await _auto_login_session(context, channel)
        if auto.get("ready") is True:
            return auto
        if auto.get("login") == "auto_login_failed":
            await page.goto(SARAMIN_SEARCH_URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1500)
            await _close_popups(page)
            if await _saramin_search_ready(page):
                return _result(
                    channel,
                    ready=True,
                    login="auto_login_ok",
                    note="automation submitted stored credentials and the search surface revalidated the session",
                    url=page.url,
                )
            if options.enabled:
                return await _wait_for_human_intervention(
                    page,
                    channel,
                    ready_check=_saramin_search_ready,
                    options=options,
                    note="automatic login did not reach a ready Saramin session; resolve login/challenge in the visible browser",
                )
        return auto
    except Exception as exc:
        return _result(
            channel,
            ready=False,
            login="error",
            note=safe_exception_label(exc, action="portal session check failed"),
            url=getattr(page, "url", ""),
        )
    finally:
        await _close_page_if_possible(page)


async def _jobkorea_session(context: Any, options: HumanInterventionOptions) -> dict[str, object]:
    channel: Channel = "jobkorea"
    page = await context.new_page()
    try:
        await page.goto(JOBKOREA_SEARCH_URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2000)
        await _close_popups(page)
        if await _jobkorea_search_ready(page):
            return _result(channel, ready=True, login="existing_session_ok", url=page.url)

        if _has_security_challenge(await _body_text(page), getattr(page, "url", "")):
            return await _wait_for_human_intervention(
                page,
                channel,
                ready_check=_jobkorea_search_ready,
                options=options,
                note="security challenge (captcha/2FA/IP) detected; resolve it in the visible browser — automation never bypasses challenges",
            )

        auto = await _auto_login_session(context, channel)
        if auto.get("ready") is True:
            return auto
        if auto.get("login") == "auto_login_failed":
            await page.goto(JOBKOREA_SEARCH_URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2000)
            await _close_popups(page)
            if await _jobkorea_search_ready(page):
                return _result(
                    channel,
                    ready=True,
                    login="auto_login_ok",
                    note="automation submitted stored credentials and the search surface revalidated the session",
                    url=page.url,
                )
            if options.enabled:
                return await _wait_for_human_intervention(
                    page,
                    channel,
                    ready_check=_jobkorea_search_ready,
                    options=options,
                    note="automatic login did not reach a ready Jobkorea session; resolve login/challenge in the visible browser",
                )
        return auto
    except Exception as exc:
        return _result(
            channel,
            ready=False,
            login="error",
            note=safe_exception_label(exc, action="portal session check failed"),
            url=getattr(page, "url", ""),
        )
    finally:
        await _close_page_if_possible(page)


async def _linkedin_rps_session(context: Any, options: HumanInterventionOptions) -> dict[str, object]:
    channel: Channel = "linkedin_rps"
    page = await context.new_page()
    try:
        await page.goto(LINKEDIN_RPS_HOME_URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2500)
        await _close_popups(page)
        text = await _body_text(page)
        if _has_security_challenge(text, page.url):
            return await _wait_for_human_intervention(
                page,
                channel,
                ready_check=_linkedin_rps_ready,
                options=options,
                note="security challenge (captcha/2FA/checkpoint) detected; resolve it in the visible browser — automation never bypasses challenges",
            )
        if await _linkedin_rps_ready(page):
            return _result(channel, ready=True, login="existing_session_ok", url=page.url)

        # SOT invariant: LinkedIn RPS auto-logs in from the secret store, like the other
        # portals. auto_relogin_portal stops on any captcha/2FA/checkpoint (never bypassed).
        auto = await _auto_login_session(context, channel)
        if auto.get("ready") is True:
            return auto
        if auto.get("login") == "auto_login_failed":
            await page.goto(LINKEDIN_RPS_HOME_URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)
            await _close_popups(page)
            if await _linkedin_rps_ready(page):
                return _result(
                    channel,
                    ready=True,
                    login="auto_login_ok",
                    note="automation submitted stored credentials and the Recruiter surface revalidated the session",
                    url=page.url,
                )
            if options.enabled:
                return await _wait_for_human_intervention(
                    page,
                    channel,
                    ready_check=_linkedin_rps_ready,
                    options=options,
                    note="automatic LinkedIn login did not reach a ready session (possible captcha/2FA/checkpoint, which is never bypassed); resolve it in the visible browser",
                )
        return auto
    except Exception as exc:
        return _result(
            channel,
            ready=False,
            login="error",
            note=safe_exception_label(exc, action="portal session check failed"),
            url=getattr(page, "url", ""),
        )
    finally:
        await _close_page_if_possible(page)


def _preflight_timeout_result(channel: Channel, timeout_seconds: float) -> dict[str, object]:
    return {
        **_result(
            channel,
            ready=False,
            login="timeout",
            note=f"portal session preflight exceeded {timeout_seconds}s",
        ),
        "snapshot_capture_required": channel != "public_web",
        "snapshot_captured": False,
        "snapshot_capture_status": "skipped_timeout" if channel != "public_web" else "not_required",
    }


async def _run_preflight_channel_with_timeout(
    *,
    channel: Channel,
    timeout_seconds: float,
    action: Callable[[], Awaitable[dict[str, object]]],
) -> dict[str, object]:
    if timeout_seconds <= 0:
        return await action()
    try:
        return await asyncio.wait_for(action(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return _preflight_timeout_result(channel, timeout_seconds)


async def _run_preflight_channel(
    *,
    channel: Channel,
    profile_root: str | Path,
    worker_id: str,
    chrome_cdp_endpoint: str | None,
    headless: bool,
    playwright: Any,
    options: HumanInterventionOptions,
    snapshot_capture: PreflightSnapshotCapture | None = None,
) -> dict[str, object]:
    if channel == "public_web":
        return await _with_preflight_snapshot_status(
            _result(channel, ready=True, login="not_required"),
            context=None,
            channel=channel,
            worker_id=worker_id,
            playwright=playwright,
            ready_check=None,
            snapshot_capture=snapshot_capture,
        )

    config = PortalWorkerConfig(
        channel=channel,
        worker_id=worker_id,
        profile_root=profile_root,
        mode="headed" if channel == "linkedin_rps" else ("headless" if headless else "headed"),
        chrome_cdp_endpoint=chrome_cdp_endpoint,
    )
    async with PortalWorker(config, playwright=playwright) as worker:
        if channel == "saramin":
            result = await _saramin_session(worker.context, options)
        elif channel == "jobkorea":
            result = await _jobkorea_session(worker.context, options)
        elif channel == "linkedin_rps":
            result = await _linkedin_rps_session(worker.context, options)
        else:
            result = _result(channel, ready=True, login="not_required")
        return await _with_preflight_snapshot_status(
            result,
            context=worker.context,
            channel=channel,
            worker_id=worker_id,
            playwright=playwright,
            ready_check=ready_check_for_channel(channel),
            browser=getattr(worker, "browser", None) if channel == "linkedin_rps" else None,
            snapshot_capture=snapshot_capture,
        )


async def run_portal_login_preflight(
    *,
    channels: tuple[Channel, ...],
    profile_root: str | Path = DEFAULT_PROFILE_ROOT,
    worker_id: str = "default",
    chrome_cdp_endpoint: str | None = None,
    env_file: str | Path = DEFAULT_ENV_FILE,
    headless: bool = False,
    human_intervention: bool = True,
    human_timeout_seconds: int = 900,
    human_poll_seconds: int = 5,
    channel_timeout_seconds: float = DEFAULT_CHANNEL_TIMEOUT_SECONDS,
    snapshot_capture: PreflightSnapshotCapture | None = None,
) -> list[dict[str, object]]:
    load_env_file(env_file)
    chrome_cdp_endpoint = resolve_chrome_cdp_endpoint(chrome_cdp_endpoint)
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("playwright is required for portal login preflight") from exc

    async with async_playwright() as playwright:
        options = HumanInterventionOptions(
            enabled=bool(human_intervention and not headless),
            timeout_seconds=human_timeout_seconds,
            poll_interval_seconds=human_poll_seconds,
        )
        results: list[dict[str, object]] = []
        for channel in channels:
            results.append(
                await _run_preflight_channel_with_timeout(
                    channel=channel,
                    timeout_seconds=channel_timeout_seconds,
                    action=lambda channel=channel: _run_preflight_channel(
                        channel=channel,
                        profile_root=profile_root,
                        worker_id=worker_id,
                        chrome_cdp_endpoint=chrome_cdp_endpoint,
                        headless=headless,
                        playwright=playwright,
                        options=options,
                        snapshot_capture=snapshot_capture,
                    ),
                )
            )
    return results


def _parse_channels(value: str) -> tuple[Channel, ...]:
    channels: list[Channel] = []
    for raw in value.split(","):
        channel = raw.strip()
        if channel in {"saramin", "jobkorea", "linkedin_rps", "public_web"}:
            channels.append(channel)  # type: ignore[arg-type]
    return tuple(channels) or ("saramin", "jobkorea", "linkedin_rps")


def build_portal_session_preflight_payload(results: list[dict[str, object]]) -> dict[str, object]:
    return {
        "kind": "portal_session_preflight",
        "generated_at": utc_now_portal_login(),
        "ready": all(result.get("ready") is True for result in results),
        "portal_sessions": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare protected portal login sessions for multisearch.")
    parser.add_argument("--channels", default="saramin,jobkorea,linkedin_rps")
    parser.add_argument("--profile-root", default=DEFAULT_PROFILE_ROOT_PATH)
    parser.add_argument("--worker-id", default="default")
    parser.add_argument(
        "--chrome-cdp-endpoint",
        default=None,
        help="CDP endpoint of an already-running Chrome (default: $VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT or http://127.0.0.1:9222)",
    )
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--output", default=DEFAULT_STATUS_OUTPUT)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-human-intervention", action="store_true")
    parser.add_argument("--human-timeout-seconds", type=int, default=900)
    parser.add_argument("--human-poll-seconds", type=int, default=5)
    parser.add_argument(
        "--channel-timeout-seconds",
        type=int,
        default=DEFAULT_CHANNEL_TIMEOUT_SECONDS,
        help="Maximum seconds for each portal channel preflight; use 0 to disable the channel-level guard.",
    )
    args = parser.parse_args()

    results = asyncio.run(
        run_portal_login_preflight(
            channels=_parse_channels(args.channels),
            profile_root=args.profile_root,
            worker_id=args.worker_id,
            chrome_cdp_endpoint=args.chrome_cdp_endpoint,
            env_file=args.env_file,
            headless=args.headless,
            human_intervention=not args.no_human_intervention,
            human_timeout_seconds=args.human_timeout_seconds,
            human_poll_seconds=args.human_poll_seconds,
            channel_timeout_seconds=args.channel_timeout_seconds,
        )
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_portal_session_preflight_payload(results)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(output))


if __name__ == "__main__":
    main()
