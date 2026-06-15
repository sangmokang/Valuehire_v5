from __future__ import annotations

import asyncio
import fcntl
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from .models import CandidateResultCard, Channel
from .portal_safety import safe_artifact_url, safe_exception_label
from .selectors import DEFAULT_SELECTOR_MAP

PortalLaunchMode = Literal["headed", "headless"]
SearchStatus = Literal["searched", "not_ready", "selector_missing", "error"]

PROFILE_WORKER_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
DEFAULT_PROFILE_ROOT = Path(
    os.environ.get("VALUEHIRE_PORTAL_PROFILE_ROOT")
    or Path.home() / ".valuehire" / "portal_profiles"
)
FORBIDDEN_PROFILE_ARTIFACT_ROOT = Path("artifacts")
LINKEDIN_SINGLE_WORKER_ID = "default"

CHROME_CDP_ENDPOINT_ENV = "VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT"
DEFAULT_CHROME_CDP_ENDPOINT = "http://127.0.0.1:9222"


def resolve_chrome_cdp_endpoint(value: str | None = None) -> str:
    """Resolve the Chrome CDP endpoint.

    Precedence: explicit ``value`` > ``VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT`` env
    var > hardcoded default. An empty string is treated as "not provided" so that
    callers can pass through unresolved CLI args.
    """
    if value:
        return value
    return os.environ.get(CHROME_CDP_ENDPOINT_ENV, DEFAULT_CHROME_CDP_ENDPOINT)

SEARCH_SURFACE_URLS: dict[Channel, str] = {
    "saramin": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
    "jobkorea": "https://www.jobkorea.co.kr/Corp/Person/Find",
    "linkedin_rps": "https://www.linkedin.com/talent/home",
    "public_web": "",
}

# Result-card link selectors, in priority order, used to collect candidate cards from a
# search results page. Only profile-listing links are read — outreach controls (InMail /
# "보내기" / "Send") are never selected or clicked.
RESULT_CARD_SELECTORS: dict[Channel, tuple[str, ...]] = {
    "saramin": (
        'a[href*="/zf_user/talent-pool"][href*="view"]',
        'a[href*="/zf_user/member"]',
        ".talent_list .item a[href]",
    ),
    "jobkorea": (
        'a[href*="/Recruit/Co_Read"][href*="rdsKey"]',
        'a[href*="/Person/"][href*="Read"]',
        ".tplList .tplPerson a[href]",
    ),
    "linkedin_rps": (
        'a[href*="/talent/profile/"]',
        '[data-test-profile-link]',
    ),
}
MAX_RESULT_CARDS = 50
SAFE_SELECTOR_ERROR_MESSAGES = {"keyword input selector missing"}


class PortalWorkerConfigError(RuntimeError):
    pass


class ProfileLockError(RuntimeError):
    pass


def validate_portal_profile_root(profile_root: str | Path) -> Path:
    path = Path(profile_root)
    if _is_path_within(path, Path.cwd() / FORBIDDEN_PROFILE_ARTIFACT_ROOT):
        raise PortalWorkerConfigError(
            "profile_root must not be inside artifacts; use ~/.valuehire/portal_profiles "
            "or VALUEHIRE_PORTAL_PROFILE_ROOT outside artifact outputs"
        )
    return path


def _is_path_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError:
        return False
    return True


def _value_from_attr_or_method(value: Any, attr: str, default: Any = None) -> Any:
    resolved = getattr(value, attr, default)
    if callable(resolved):
        try:
            return resolved()
        except TypeError:
            return default
    return resolved


def login_redirect_cause(channel: Channel, url: str) -> str:
    lowered = url.lower()
    if channel == "saramin" and ("/zf_user/auth" in lowered or "login" in lowered):
        return "login_redirect"
    if channel == "jobkorea" and ("/login/" in lowered or "login_tot" in lowered):
        return "login_redirect"
    if channel == "linkedin_rps" and ("/login" in lowered or "/checkpoint" in lowered):
        return "login_redirect"
    return ""


class SearchLivenessMonitor:
    def __init__(self, channel: Channel) -> None:
        self.channel = channel
        self.reauth_cause = ""

    def attach(self, page: Any) -> None:
        if not hasattr(page, "on"):
            return
        page.on("response", self._handle_response)
        page.on("framenavigated", self._handle_navigation)

    def _handle_response(self, response: Any) -> None:
        status = int(_value_from_attr_or_method(response, "status", 0) or 0)
        url = str(_value_from_attr_or_method(response, "url", "") or "")
        if status in {401, 403}:
            self.reauth_cause = f"http_{status}"
            return
        redirect_cause = login_redirect_cause(self.channel, url)
        if redirect_cause:
            self.reauth_cause = redirect_cause

    def _handle_navigation(self, frame: Any) -> None:
        url = str(_value_from_attr_or_method(frame, "url", "") or "")
        redirect_cause = login_redirect_cause(self.channel, url)
        if redirect_cause:
            self.reauth_cause = redirect_cause

    async def check_page(self, page: Any) -> str:
        redirect_cause = login_redirect_cause(self.channel, str(getattr(page, "url", "") or ""))
        if redirect_cause:
            self.reauth_cause = redirect_cause
        return self.reauth_cause


@dataclass(frozen=True)
class PortalWorkerConfig:
    channel: Channel
    worker_id: str = "default"
    profile_root: str | Path = DEFAULT_PROFILE_ROOT
    mode: PortalLaunchMode = "headed"
    launch_args: tuple[str, ...] = ()
    chrome_cdp_endpoint: str = field(default_factory=resolve_chrome_cdp_endpoint)
    viewport_width: int = 1440
    viewport_height: int = 1000
    search_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_root", validate_portal_profile_root(self.profile_root))
        if self.channel == "public_web":
            raise PortalWorkerConfigError("public_web does not require a protected portal worker")
        if not PROFILE_WORKER_ID_RE.match(self.worker_id) or self.worker_id in {".", ".."}:
            raise PortalWorkerConfigError("worker_id must be a safe file-name token")
        if self.channel == "linkedin_rps":
            if self.worker_id != LINKEDIN_SINGLE_WORKER_ID:
                raise PortalWorkerConfigError("LinkedIn RPS is constrained to one headed worker: default")
            if self.mode != "headed":
                raise PortalWorkerConfigError("LinkedIn RPS must attach to headed Chrome")

    @property
    def profile_dir(self) -> Path:
        return Path(self.profile_root) / self.channel / self.worker_id

    @property
    def lock_path(self) -> Path:
        return self.profile_dir / ".profile.lock"

    @property
    def headless(self) -> bool:
        return self.mode == "headless"


@dataclass(frozen=True)
class PortalSearchAttempt:
    channel: Channel
    worker_id: str
    keyword: str
    status: SearchStatus
    reason: str
    url: str = ""
    reauth_cause: str = ""
    candidate_cards: tuple[CandidateResultCard, ...] = ()


class ProfileLock:
    """Cross-process exclusive profile lock backed by flock."""

    def __init__(self, config: PortalWorkerConfig) -> None:
        self.config = config
        self._handle: Any | None = None

    def acquire(self) -> None:
        _ensure_real_profile_dir(self.config)
        handle = _open_real_profile_lock(self.config.lock_path)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            _close_failed_lock_acquire_handle(handle)
            raise ProfileLockError(
                f"profile already locked for {self.config.channel}/{self.config.worker_id}"
            ) from exc
        except Exception as exc:
            _close_failed_lock_acquire_handle(handle)
            raise ProfileLockError("profile lock acquisition failed without exposing details") from exc

        try:
            handle.seek(0)
            handle.truncate()
            handle.write(f"channel={self.config.channel}\nworker_id={self.config.worker_id}\n")
            handle.flush()
        except Exception:
            _close_failed_lock_acquire_handle(handle)
            raise
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        handle = self._handle
        self._handle = None
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            handle.close()
        except Exception:
            pass

    def __enter__(self) -> ProfileLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def _ensure_real_profile_dir(config: PortalWorkerConfig) -> None:
    profile_root = Path(config.profile_root)
    channel_dir = profile_root / config.channel
    profile_dir = config.profile_dir
    _reject_unsafe_profile_path(profile_root)
    if not profile_root.exists():
        profile_root.mkdir(parents=True, exist_ok=True)
    _reject_unsafe_profile_path(profile_root)
    for path in (channel_dir, profile_dir):
        _reject_unsafe_profile_path(path)
        if not path.exists():
            path.mkdir(exist_ok=True)
        _reject_unsafe_profile_path(path)


def _reject_unsafe_profile_path(path: Path) -> None:
    if path.is_symlink():
        raise ProfileLockError("profile path must not include symlinks")
    if path.exists() and not path.is_dir():
        raise ProfileLockError("profile path must be a real directory")


def _open_real_profile_lock(lock_path: Path) -> Any:
    if lock_path.is_symlink():
        raise ProfileLockError("profile lock path must not be a symlink")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ProfileLockError("profile lock path must be a real file") from exc
    return os.fdopen(fd, "r+", encoding="utf-8")


def _close_failed_lock_acquire_handle(handle: Any) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        handle.close()
    except Exception:
        pass


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


async def _close_page_if_possible(page: Any) -> None:
    close = getattr(page, "close", None)
    if not callable(close):
        return
    try:
        await _maybe_await(close())
    except Exception:
        return


async def _safe_count(page: Any, selector: str) -> int:
    try:
        return int(await _maybe_await(page.locator(selector).count()))
    except Exception:
        return 0


async def _first_existing_locator(page: Any, channel: Channel, purpose: str) -> Any | None:
    for candidate in DEFAULT_SELECTOR_MAP.get(channel, {}).get(purpose, ()):
        locator = page.locator(candidate.selector)
        try:
            if int(await _maybe_await(locator.count())) > 0:
                return locator.first
        except Exception:
            continue
    return None


async def _goto_search_surface(page: Any, channel: Channel, keyword: str) -> None:
    if channel == "linkedin_rps" and keyword:
        url = (
            "https://www.linkedin.com/talent/search?"
            f"searchKeyword={quote(keyword)}&start=0&uiOrigin=GLOBAL_SEARCH_HEADER"
        )
    else:
        url = SEARCH_SURFACE_URLS[channel]
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    if hasattr(page, "wait_for_timeout"):
        await page.wait_for_timeout(1000)


async def collect_result_cards(page: Any, channel: Channel, *, limit: int = MAX_RESULT_CARDS) -> tuple[CandidateResultCard, ...]:
    """Collect candidate result cards from the current search results page.

    Reads only public profile-listing links (and their visible snippet). It never selects
    or clicks outreach controls (InMail / Send). Fully fail-soft: any DOM/selector error
    yields an empty tuple so a missing card layout never turns a real search into a hard
    failure. Each profile link is de-duplicated across the selector fallbacks.
    """
    cards: list[CandidateResultCard] = []
    seen: set[str] = set()
    for selector in RESULT_CARD_SELECTORS.get(channel, ()):
        try:
            locator = page.locator(selector)
            count = int(await _maybe_await(locator.count()) or 0)
        except Exception:
            continue
        if count <= 0:
            continue
        for index in range(min(count, limit)):
            try:
                item = locator.nth(index)
                href = await _maybe_await(item.get_attribute("href"))
            except Exception:
                continue
            if not href or href in seen:
                continue
            seen.add(href)
            snippet = ""
            try:
                snippet = (await _maybe_await(item.inner_text()) or "").strip()[:200]
            except Exception:
                snippet = ""
            cards.append(CandidateResultCard(profile_url=str(href), source_channel=channel, snippet=snippet))
            if len(cards) >= limit:
                break
        if cards:
            break
    return tuple(cards)


async def _submit_keyword_search(page: Any, channel: Channel, keyword: str) -> str:
    if channel == "linkedin_rps":
        # The keyword is carried in the talent/search URL opened by _goto_search_surface,
        # so the search has already executed; result cards are collected afterwards. No
        # login or outreach (InMail/Send) automation is performed here.
        return "LinkedIn RPS talent search executed via search URL; collecting result cards (no outreach automation)"
    if not keyword:
        return "search surface opened without keyword"

    input_locator = await _first_existing_locator(page, channel, "keyword_input")
    if input_locator is None:
        raise RuntimeError("keyword input selector missing")
    await input_locator.fill(keyword)

    button_purpose = "search_button" if channel == "saramin" else "filter_search_button"
    button_locator = await _first_existing_locator(page, channel, button_purpose)
    if button_locator is not None:
        await button_locator.click()
    else:
        await input_locator.press("Enter")

    if hasattr(page, "wait_for_timeout"):
        await page.wait_for_timeout(1000)
    return "keyword submitted on persistent portal context"


ReadyCheck = Callable[[Any], Awaitable[bool]]


class PortalWorker:
    def __init__(self, config: PortalWorkerConfig, *, playwright: Any | None = None) -> None:
        self.config = config
        self._provided_playwright = playwright
        self._playwright_manager: Any | None = None
        self._playwright: Any | None = None
        self._lock = ProfileLock(config)
        self._context: Any | None = None
        self._browser: Any | None = None
        self._started = False
        self._blocked_next_mode: PortalLaunchMode | None = None

    @property
    def context(self) -> Any:
        if self._context is None:
            raise RuntimeError("portal worker has not been started")
        return self._context

    @property
    def browser(self) -> Any | None:
        return self._browser

    @property
    def blocked_next_mode(self) -> PortalLaunchMode | None:
        return self._blocked_next_mode

    def mark_blocked_for_reboot(self, *, next_mode: PortalLaunchMode) -> None:
        """Record a next-boot policy without mutating this worker's browser mode."""
        self._blocked_next_mode = next_mode

    async def start(self) -> None:
        if self._started:
            return
        self._lock.acquire()
        try:
            self._playwright = self._provided_playwright
            if self._playwright is None:
                from playwright.async_api import async_playwright

                self._playwright_manager = async_playwright()
                self._playwright = await self._playwright_manager.__aenter__()

            if self.config.channel == "linkedin_rps":
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self.config.chrome_cdp_endpoint
                )
                contexts = getattr(self._browser, "contexts", ())
                self._context = contexts[0] if contexts else await self._browser.new_context()
            else:
                self._context = await self._playwright.chromium.launch_persistent_context(
                    str(self.config.profile_dir),
                    headless=self.config.headless,
                    args=list(self.config.launch_args),
                    viewport={
                        "width": self.config.viewport_width,
                        "height": self.config.viewport_height,
                    },
                )
            self._started = True
        except Exception:
            self._lock.release()
            await self._close_playwright_manager_if_possible()
            raise

    async def stop(self) -> None:
        try:
            if self.config.channel != "linkedin_rps" and self._context is not None:
                try:
                    await self._context.close()
                except Exception:
                    pass
        finally:
            self._context = None
            self._browser = None
            try:
                await self._close_playwright_manager_if_possible()
            finally:
                self._lock.release()
                self._started = False

    async def _close_playwright_manager_if_possible(self) -> None:
        if self._playwright_manager is None:
            return
        manager = self._playwright_manager
        self._playwright_manager = None
        try:
            await manager.__aexit__(None, None, None)
        except Exception:
            return

    async def __aenter__(self) -> PortalWorker:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()

    async def run_one_search(
        self,
        keyword: str,
        *,
        ready_check: ReadyCheck | None = None,
        monitor: SearchLivenessMonitor | None = None,
    ) -> PortalSearchAttempt:
        await self.start()
        timeout = self.config.search_timeout_seconds
        body = self._run_one_search_body(keyword, ready_check=ready_check, monitor=monitor)
        if not timeout or timeout <= 0:
            return await body
        # Bound the whole search so a hung page (goto / submit / card collection that never
        # returns) cannot pin the worker forever and stall the queue. wait_for cancels the
        # body on timeout; the body's finally still closes its page during cancellation.
        try:
            return await asyncio.wait_for(body, timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return PortalSearchAttempt(
                channel=self.config.channel,
                worker_id=self.config.worker_id,
                keyword=keyword,
                status="error",
                reason=f"portal search timed out after {timeout:g}s",
            )

    async def _run_one_search_body(
        self,
        keyword: str,
        *,
        ready_check: ReadyCheck | None = None,
        monitor: SearchLivenessMonitor | None = None,
    ) -> PortalSearchAttempt:
        page: Any | None = None
        try:
            page = await self.context.new_page()
            monitor = monitor or SearchLivenessMonitor(self.config.channel)
            monitor.attach(page)
            await _goto_search_surface(page, self.config.channel, keyword)
            reauth_cause = await monitor.check_page(page)
            if reauth_cause:
                return PortalSearchAttempt(
                    channel=self.config.channel,
                    worker_id=self.config.worker_id,
                    keyword=keyword,
                    status="not_ready",
                    reason="reauth required before search",
                    url=safe_artifact_url(getattr(page, "url", "")),
                    reauth_cause=reauth_cause,
                )
            if ready_check is not None and not await ready_check(page):
                return PortalSearchAttempt(
                    channel=self.config.channel,
                    worker_id=self.config.worker_id,
                    keyword=keyword,
                    status="not_ready",
                    reason="login marker missing on persistent context",
                    url=safe_artifact_url(getattr(page, "url", "")),
                    reauth_cause="login_marker_missing",
                )
            reason = await _submit_keyword_search(page, self.config.channel, keyword)
            reauth_cause = await monitor.check_page(page)
            if reauth_cause:
                return PortalSearchAttempt(
                    channel=self.config.channel,
                    worker_id=self.config.worker_id,
                    keyword=keyword,
                    status="not_ready",
                    reason="reauth required during search",
                    url=safe_artifact_url(getattr(page, "url", "")),
                    reauth_cause=reauth_cause,
                )
            if ready_check is not None and not await ready_check(page):
                return PortalSearchAttempt(
                    channel=self.config.channel,
                    worker_id=self.config.worker_id,
                    keyword=keyword,
                    status="not_ready",
                    reason="login marker lost during search",
                    url=safe_artifact_url(getattr(page, "url", "")),
                    reauth_cause="login_marker_lost",
                )
            cards = await collect_result_cards(page, self.config.channel)
            return PortalSearchAttempt(
                channel=self.config.channel,
                worker_id=self.config.worker_id,
                keyword=keyword,
                status="searched",
                reason=reason,
                url=safe_artifact_url(getattr(page, "url", "")),
                candidate_cards=cards,
            )
        except RuntimeError as exc:
            error_message = str(exc)
            if error_message not in SAFE_SELECTOR_ERROR_MESSAGES:
                return PortalSearchAttempt(
                    channel=self.config.channel,
                    worker_id=self.config.worker_id,
                    keyword=keyword,
                    status="error",
                    reason=safe_exception_label(exc, action="portal search failed"),
                    url=safe_artifact_url(getattr(page, "url", "")),
                )
            return PortalSearchAttempt(
                channel=self.config.channel,
                worker_id=self.config.worker_id,
                keyword=keyword,
                status="selector_missing",
                reason=safe_exception_label(exc, action="portal selector missing"),
                url=safe_artifact_url(getattr(page, "url", "")),
            )
        except Exception as exc:
            return PortalSearchAttempt(
                channel=self.config.channel,
                worker_id=self.config.worker_id,
                keyword=keyword,
                status="error",
                reason=safe_exception_label(exc, action="portal search failed"),
                url=safe_artifact_url(getattr(page, "url", "")),
            )
        finally:
            if page is not None:
                await _close_page_if_possible(page)


RecoveryHandler = Callable[[PortalSearchAttempt], Awaitable[bool]]


async def run_search_with_recovery(
    worker: Any,
    keyword: str,
    *,
    ready_check: ReadyCheck | None = None,
    recover: RecoveryHandler,
    max_retries: int = 1,
) -> PortalSearchAttempt:
    attempts = 0
    while True:
        attempts += 1
        monitor = SearchLivenessMonitor(worker.config.channel)
        result = await worker.run_one_search(keyword, ready_check=ready_check, monitor=monitor)
        if result.status != "not_ready" or not result.reauth_cause or attempts > max_retries:
            return result
        if not await recover(result):
            return result
