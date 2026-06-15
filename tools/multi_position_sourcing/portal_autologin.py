from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Channel
from .portal_login import _body_text, _close_popups, _has_security_challenge, ready_check_for_channel
from .portal_recovery import PortalCredentials
from .portal_worker import _close_page_if_possible

SARAMIN_CORPORATE_LOGIN_URL = (
    "https://www.saramin.co.kr/zf_user/auth?ut=c&url="
    "https%3A%2F%2Fwww.saramin.co.kr%2Fzf_user%2Fmemcom%2Ftalent-pool%2Fmain%2Fsearch"
)
JOBKOREA_LOGIN_URL = "https://www.jobkorea.co.kr/Login/Login_Tot.asp"


@dataclass(frozen=True)
class AutoLoginSelectors:
    username: tuple[str, ...]
    password: tuple[str, ...]
    submit: tuple[str, ...]


AUTO_LOGIN_SELECTORS: dict[Channel, AutoLoginSelectors] = {
    "saramin": AutoLoginSelectors(
        username=(
            'input[name="id"]',
            "#id",
            'input[name="user_id"]',
            'input[name="member_id"]',
            'input[type="text"]',
        ),
        password=(
            'input[name="password"]',
            "#password",
            'input[name="passwd"]',
            'input[name="member_pass"]',
            'input[type="password"]',
        ),
        submit=(
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("로그인")',
            'a:has-text("로그인")',
        ),
    ),
    "jobkorea": AutoLoginSelectors(
        username=(
            "#M_ID",
            'input[name="M_ID"]',
            "#loginId",
            'input[name="id"]',
            'input[type="text"]',
        ),
        password=(
            "#M_PWD",
            'input[name="M_PWD"]',
            "#loginPwd",
            'input[name="password"]',
            'input[type="password"]',
        ),
        submit=(
            "#lb_login",
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("로그인")',
            'a:has-text("로그인")',
        ),
    ),
}


def login_url_for_channel(site: Channel) -> str:
    if site == "saramin":
        return SARAMIN_CORPORATE_LOGIN_URL
    if site == "jobkorea":
        return JOBKOREA_LOGIN_URL
    raise ValueError(f"automatic login is not configured for {site}")


@dataclass(frozen=True)
class LoginSelectorPreflight:
    """Whether the configured auto-login selectors still match the live login page.

    A drift (any role not found) means the portal changed its login HTML, so auto-login
    would silently fail. Surfacing it lets operators fix the selector map instead of
    mistaking the drift for a transient security challenge.
    """

    channel: Channel
    username: Any = None
    password: Any = None
    submit: Any = None

    @property
    def username_found(self) -> bool:
        return self.username is not None

    @property
    def password_found(self) -> bool:
        return self.password is not None

    @property
    def submit_found(self) -> bool:
        return self.submit is not None

    @property
    def drifted(self) -> bool:
        return not (self.username_found and self.password_found and self.submit_found)

    @property
    def missing_roles(self) -> tuple[str, ...]:
        missing: list[str] = []
        if not self.username_found:
            missing.append("username")
        if not self.password_found:
            missing.append("password")
        if not self.submit_found:
            missing.append("submit")
        return tuple(missing)


async def login_selector_preflight(page: Any, site: Channel) -> LoginSelectorPreflight:
    if site not in AUTO_LOGIN_SELECTORS:
        raise ValueError(f"automatic login is not configured for {site}")
    selectors = AUTO_LOGIN_SELECTORS[site]
    return LoginSelectorPreflight(
        channel=site,
        username=await _first_visible_locator(page, selectors.username),
        password=await _first_visible_locator(page, selectors.password),
        submit=await _first_visible_locator(page, selectors.submit),
    )


async def auto_relogin_portal(context: Any, site: Channel, credentials: PortalCredentials) -> bool:
    if site not in AUTO_LOGIN_SELECTORS:
        raise ValueError(f"automatic login is not configured for {site}")

    page = await context.new_page()
    try:
        ready_check = ready_check_for_channel(site)
        login_url = login_url_for_channel(site)
        await page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
        if hasattr(page, "wait_for_timeout"):
            await page.wait_for_timeout(1000)
        await _close_popups(page)

        if await ready_check(page):
            return True
        await page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
        if hasattr(page, "wait_for_timeout"):
            await page.wait_for_timeout(1000)
        await _close_popups(page)

        # Never attempt to bypass an anti-bot security challenge (captcha / 2FA /
        # checkpoint). Auto-submitting credentials into one is detection-evasion and
        # the fastest way to get the account locked — stop and let recovery pause/alert.
        if _has_security_challenge(await _body_text(page), getattr(page, "url", "")):
            return False

        preflight = await login_selector_preflight(page, site)
        if preflight.drifted:
            # Selector drift: the portal changed its login HTML. Do not guess or fill
            # blindly — a drift is reported (missing_roles) rather than silently retried.
            return False

        await preflight.username.fill(credentials.username)
        await preflight.password.fill(credentials.password)
        await preflight.submit.click()
        if hasattr(page, "wait_for_timeout"):
            await page.wait_for_timeout(2500)
        await _close_popups(page)
        return await ready_check(page)
    finally:
        await _close_page_if_possible(page)


async def _first_visible_locator(page: Any, selectors: tuple[str, ...]) -> Any | None:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
            if hasattr(count, "__await__"):
                count = await count
            if int(count) > 0:
                return locator.first
        except Exception:
            continue
    return None
