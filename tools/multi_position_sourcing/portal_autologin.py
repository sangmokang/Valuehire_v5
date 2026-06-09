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

        selectors = AUTO_LOGIN_SELECTORS[site]
        username_locator = await _first_visible_locator(page, selectors.username)
        password_locator = await _first_visible_locator(page, selectors.password)
        submit_locator = await _first_visible_locator(page, selectors.submit)
        if username_locator is None or password_locator is None or submit_locator is None:
            return False

        await username_locator.fill(credentials.username)
        await password_locator.fill(credentials.password)
        await submit_locator.click()
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
