#!/usr/bin/env python3
"""Collect LinkedIn Recruiter search results via CDP (logged-in session on :9222).

For each keyword: open talent/search, wait + scroll to lazy-load, then extract
structured cards (name, headline, location, open-to-work, profile_url) from each
result row. Search + collect only — no outreach is ever automated.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote

CDP = "http://127.0.0.1:9222"

EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const links = document.querySelectorAll('a[href*="/talent/profile/"]');
  for (const a of links) {
    const href = a.href.split('?')[0];
    const m = href.match(/\/talent\/profile\/([^/?]+)/);
    if (!m) continue;
    const id = m[1];
    if (seen.has(id)) continue;
    seen.add(id);
    // climb to the result row container
    let row = a;
    for (let i = 0; i < 8 && row && row.parentElement; i++) {
      row = row.parentElement;
      if (row.matches && (row.matches('li') || (row.getAttribute && (row.getAttribute('data-test-search-result')!==null)))) break;
    }
    const txt = (row ? row.innerText : a.innerText) || "";
    out.push({ id, profile_url: href, name: (a.innerText||"").trim(), row_text: txt.replace(/\s+\n/g,'\n').trim().slice(0, 600) });
  }
  return out;
}
"""


async def collect_keyword(ctx, keyword: str) -> list[dict]:
    page = await ctx.new_page()
    try:
        url = f"https://www.linkedin.com/talent/search?searchKeyword={quote(keyword)}&start=0&uiOrigin=GLOBAL_SEARCH_HEADER"
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        for _ in range(5):
            await page.mouse.wheel(0, 2500)
            await page.wait_for_timeout(1000)
        rows = await page.evaluate(EXTRACT_JS)
        for r in rows:
            r["keyword"] = keyword
        return rows
    finally:
        await page.close()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", nargs="+", required=True)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    from playwright.async_api import async_playwright
    all_cards: dict[str, dict] = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        for kw in args.keywords:
            try:
                rows = await collect_keyword(ctx, kw)
            except Exception as exc:
                print(f"'{kw}': ERROR {type(exc).__name__}", flush=True)
                continue
            new = 0
            for r in rows:
                if r["id"] not in all_cards:
                    all_cards[r["id"]] = r
                    new += 1
                else:
                    all_cards[r["id"]].setdefault("also_keywords", []).append(kw)
            print(f"'{kw}': {len(rows)} rows ({new} new, total unique {len(all_cards)})", flush=True)
            await asyncio.sleep(2)

    args.output.write_text(json.dumps(list(all_cards.values()), ensure_ascii=False, indent=2))
    print(f"TOTAL unique candidates: {len(all_cards)} -> {args.output}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
