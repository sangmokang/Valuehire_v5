#!/usr/bin/env python3
"""Supabase-free, human-in-the-loop portal live-search runner for interactive AI Search.

Opens a headed persistent browser, lets the operator log in by hand in the visible
window (no captcha/2FA is ever bypassed), then runs keyword searches against that
SAME live session and collects public result cards. With --hold the window stays
open after searches so the operator can keep the logged-in session as a process.

Reuses SOT-compliant helpers (selectors, card collection). It intentionally does NOT
use the SearchLivenessMonitor login-redirect gate, which false-positives on a
freshly human-logged-in corporate session; readiness is judged by the real presence
of the search input instead.

Usage:
  python3 scripts/run_portal_search.py --channel saramin \
      --keywords "스마트홈 영업" "조명제어 영업" \
      --wait-login-seconds 1200 --hold --output artifacts/out.json

Safety: search + collect only. No outreach (InMail/Send) is ever automated.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from pathlib import Path

from tools.multi_position_sourcing.portal_login import (
    ready_check_for_channel,
    _close_popups,
    _auto_login_session,
)
from tools.multi_position_sourcing.portal_worker import (
    PortalWorker,
    PortalWorkerConfig,
    SEARCH_SURFACE_URLS,
    _submit_keyword_search,
    collect_result_cards,
)

# Where to send the operator to log in (corporate ut=c flow for Saramin).
LOGIN_URLS = {
    "saramin": (
        "https://www.saramin.co.kr/zf_user/auth?ut=c&url="
        "https%3A%2F%2Fwww.saramin.co.kr%2Fzf_user%2Fmemcom%2Ftalent-pool%2Fmain%2Fsearch"
    ),
    "jobkorea": "https://www.jobkorea.co.kr/Corp/Person/Find",
    "linkedin_rps": "https://www.linkedin.com/talent/home",
}


async def _wait_for_login(page, channel: str, ready_check, deadline_s: float) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        try:
            if await ready_check(page):
                return True
        except Exception:
            pass
        await asyncio.sleep(3)
    return False


async def run(channel: str, keywords: list[str], wait_login_s: float, hold: bool, output: Path) -> dict:
    from playwright.async_api import async_playwright

    worker_config = PortalWorkerConfig(channel=channel, worker_id="default", mode="headed")
    ready_check = ready_check_for_channel(channel)
    search_url = SEARCH_SURFACE_URLS[channel]
    out: dict = {"channel": channel, "mode": "headed", "login_ready": False, "searches": []}

    async with async_playwright() as pw:
        async with PortalWorker(worker_config, playwright=pw) as worker:
            page = await worker.context.new_page()
            # Send operator to the (corporate) login surface; keep window open while they log in.
            await page.goto(LOGIN_URLS.get(channel, search_url), wait_until="domcontentloaded", timeout=60000)
            await _close_popups(page)  # always X-close any popup to reach the search screen
            print(f"[{channel}] window open. waiting up to {int(wait_login_s)}s for login...", flush=True)

            # Principle: attempt auto-login first. Operator may take over to go faster.
            ready = await ready_check(page)
            if not ready:
                print(f"[{channel}] trying auto-login from secret store...", flush=True)
                try:
                    auto = await _auto_login_session(worker.context, channel)
                    print(f"[{channel}] auto-login: {auto.get('login')}", flush=True)
                except Exception as exc:
                    print(f"[{channel}] auto-login error: {type(exc).__name__}", flush=True)
                await page.goto(LOGIN_URLS.get(channel, search_url), wait_until="domcontentloaded", timeout=60000)
                await _close_popups(page)
                ready = await ready_check(page)
            if not ready and wait_login_s > 0:
                print(f"[{channel}] not ready — log in manually in the window (faster). polling...", flush=True)
                ready = await _wait_for_login(page, channel, ready_check, wait_login_s)
            out["login_ready"] = ready
            if not ready:
                print(f"[{channel}] login not ready within wait window.", flush=True)
            else:
                print(f"[{channel}] login ready — running {len(keywords)} searches.", flush=True)
                for kw in keywords:
                    status, reason, cards = "searched", "", ()
                    try:
                        await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_timeout(1200)
                        await _close_popups(page)  # always X-close popups before searching
                        if not await ready_check(page):
                            status, reason = "not_ready", "search input missing after navigation"
                        else:
                            reason = await _submit_keyword_search(page, channel, kw)
                            await page.wait_for_timeout(1500)
                            cards = await collect_result_cards(page, channel)
                    except Exception as exc:
                        status, reason = "error", f"{type(exc).__name__}"
                    card_list = [{"profile_url": c.profile_url, "snippet": c.snippet} for c in cards]
                    out["searches"].append(
                        {"keyword": kw, "status": status, "reason": reason,
                         "url": getattr(page, "url", ""), "card_count": len(card_list), "cards": card_list}
                    )
                    print(f"  '{kw}': {status} cards={len(card_list)}", flush=True)
                    await asyncio.sleep(random.uniform(2.5, 5.0))

            output.write_text(json.dumps(out, ensure_ascii=False, indent=2))
            total = sum(s["card_count"] for s in out["searches"])
            print(f"[{channel}] TOTAL cards={total} output={output}", flush=True)

            if hold:
                print(f"[{channel}] HOLDING window open (session kept as process). Ctrl-C / kill to stop.", flush=True)
                while True:
                    await asyncio.sleep(30)

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True, choices=["saramin", "jobkorea", "linkedin_rps"])
    ap.add_argument("--keywords", nargs="+", required=True)
    ap.add_argument("--wait-login-seconds", type=float, default=0.0)
    ap.add_argument("--hold", action="store_true")
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    asyncio.run(run(args.channel, args.keywords, args.wait_login_seconds, args.hold, args.output))


if __name__ == "__main__":
    main()
