#!/usr/bin/env python3
"""Probe LinkedIn Recruiter search-results DOM via CDP to find correct card selectors."""
from __future__ import annotations
import asyncio
from urllib.parse import quote


async def main() -> None:
    from playwright.async_api import async_playwright
    kw = "Crestron"
    url = f"https://www.linkedin.com/talent/search?searchKeyword={quote(kw)}&start=0&uiOrigin=GLOBAL_SEARCH_HEADER"
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        # scroll to trigger lazy load
        for _ in range(4):
            await page.mouse.wheel(0, 2500)
            await page.wait_for_timeout(1200)
        print("URL:", page.url)
        selectors = [
            'a[href*="/talent/profile/"]',
            '[data-test-profile-link]',
            'li[data-test-search-result]',
            'ol.search-results__list li',
            'div[data-test-search-result]',
            'a[href*="/in/"]',
            '[data-live-test-row]',
            '.artdeco-entity-lockup__title',
            'div.profile-list__border-bottom',
        ]
        for s in selectors:
            try:
                c = await page.locator(s).count()
            except Exception as e:
                c = f"ERR {type(e).__name__}"
            print(f"{c}\t{s}")
        # sample first 8 profile hrefs + text
        loc = page.locator('a[href*="/talent/profile/"]')
        n = min(await loc.count(), 8)
        print("--- sample profile links ---")
        for i in range(n):
            it = loc.nth(i)
            href = await it.get_attribute("href")
            txt = (await it.inner_text() or "").strip().replace("\n", " ")[:80]
            print(f"[{i}] {href}  | {txt}")
        await page.close()


if __name__ == "__main__":
    asyncio.run(main())
