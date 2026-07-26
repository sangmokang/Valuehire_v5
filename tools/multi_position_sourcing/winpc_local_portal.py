"""Bounded browser operations for an owner-explicit WinPC AI Search.

The Codex planner calls this module instead of issuing ad-hoc localhost HTTP or
PowerShell browser commands.  It attaches to the one registered managed target,
shows the standard automation badge, applies the existing owner/lease guards,
and disconnects without closing the browser or its tab.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urljoin

from .portal_login import ready_check_for_channel
from .portal_ops import DEFAULT_PACING_POLICIES
from .portal_worker import (
    PortalWorker,
    PortalWorkerConfig,
    SearchLivenessMonitor,
    collect_result_cards,
    resolve_channel_cdp_endpoint,
    url_matches_channel_surface,
)
from .session_guard import (
    _attach_exact_ref,
    _owner_explicit_snapshot_reader,
    _sanitize_locator_url,
    read_auth_observation,
    resolve_existing_target,
)
from .winpc_portal_browser import winpc_environment


CHANNELS = ("saramin", "jobkorea")
MAX_KEYWORDS = 8
MAX_PAGES_PER_KEYWORD = 10
_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_NEXT_PAGE_SELECTORS: dict[str, tuple[str, ...]] = {
    "saramin": (
        ".PageBox button.BtnNext",
        ".pagination a.btn_next",
        ".pagination a[title*='다음']",
        ".pagination button[aria-label*='다음']",
        "a[rel='next']",
    ),
    "jobkorea": (
        ".tplPagination a.next",
        ".pagination a.next",
        ".pagination a[title*='다음']",
        ".pagination button[aria-label*='다음']",
        "a[rel='next']",
    ),
}
_RESULT_COUNT_SELECTORS: dict[str, tuple[str, ...]] = {
    "saramin": ("span.list_count", ".talent_list_count", ".result_count"),
    "jobkorea": (".devTplSchPhCnt", ".resultCount", ".tplListCnt"),
}
_RESULT_COUNT_PATTERN = re.compile(r"(?:\ucd1d\s*)?([\d,]+)\s*(?:\uba85|\uac74)")


class _DomVerifiedLivenessMonitor(SearchLivenessMonitor):
    """Local exact-target searches trust repeated DOM auth proof over asset 401/403."""

    def _handle_response(self, response: Any) -> None:
        return


def _safe_keyword_character(character: str) -> bool:
    return character.isalnum() or character.isspace() or character in {"+", "#", ".", "/", "-"}


def _normalize_keywords(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    clean: list[str] = []
    for raw in values:
        value = " ".join(str(raw or "").split())
        if (
            not value
            or len(value) > 180
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or not all(_safe_keyword_character(character) for character in value)
        ):
            raise ValueError("search keyword is empty, too long, or contains unsafe characters")
        if value not in clean:
            clean.append(value)
    if not clean or len(clean) > MAX_KEYWORDS:
        raise ValueError(f"one to {MAX_KEYWORDS} unique keywords are required")
    return tuple(clean)


def _activate_winpc_environment(
    channel: str,
    *,
    job_id: str,
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
) -> dict[str, str]:
    if (system_name or platform.system()) != "Windows":
        raise RuntimeError("local portal helper requires Windows")
    if channel not in CHANNELS or not _SAFE_JOB_ID.fullmatch(job_id):
        raise ValueError("invalid WinPC local portal request")
    env = winpc_environment(os.environ if environ is None else environ)
    env["VALUEHIRE_OWNER_LOCAL_AI_SEARCH"] = "1"
    env["VALUEHIRE_JOB_SKILL"] = "aisearch"
    env["VALUEHIRE_JOB_ROLE"] = "owner"
    env["VH_BUSY_AGENT"] = "Codex"
    env["VH_BUSY_TASK"] = f"local AI Search #{job_id} ({channel})"
    os.environ.pop("VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT", None)
    os.environ.update(env)
    return env


def probe_local_channel(
    channel: str,
    *,
    job_id: str,
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
) -> dict[str, Any]:
    """Read fresh exact-target auth markers without browser mutation."""

    _activate_winpc_environment(
        channel,
        job_id=job_id,
        environ=environ,
        system_name=system_name,
    )
    ref = resolve_existing_target(channel)
    tab = _attach_exact_ref(
        {
            "id": ref.target_id,
            "type": "page",
            "url": ref.initial_url,
            "webSocketDebuggerUrl": ref.websocket_url,
        },
        badge=False,
    )
    try:
        observation = read_auth_observation(tab, channel)
    finally:
        try:
            tab.close()
        except Exception:
            pass
    state = (
        "AUTH_CONFLICT"
        if observation.auth_conflict
        else "HUMAN_AUTH"
        if observation.challenge
        else "AUTHENTICATED"
        if observation.authenticated
        else "LOGGED_OUT"
    )
    return {
        "status": "ready" if state == "AUTHENTICATED" else "blocked",
        "channel": channel,
        "state": state,
        "target_id": ref.target_id,
        "url": _sanitize_locator_url(observation.url),
        "proof_names": list(observation.proof_names),
        "browser_preserved": True,
    }


async def _next_page_locator(
    page: Any,
    channel: str,
    *,
    next_page_number: int | None = None,
) -> Any | None:
    if channel == "saramin" and next_page_number is not None:
        numbered = page.locator(
            f'.PageBox button:has-text("{next_page_number}")'
        ).first
        try:
            if (
                int(await numbered.count()) > 0
                and await numbered.is_visible()
                and str(await numbered.inner_text() or "").strip()
                == str(next_page_number)
            ):
                return numbered
        except Exception:
            pass
    for selector in _NEXT_PAGE_SELECTORS[channel]:
        locator = page.locator(selector).first
        try:
            if int(await locator.count()) <= 0 or not await locator.is_visible():
                continue
            aria_disabled = str(await locator.get_attribute("aria-disabled") or "").casefold()
            css_class = str(await locator.get_attribute("class") or "").casefold()
            if aria_disabled == "true" or any(
                marker in css_class for marker in ("disabled", "is-disabled", "off")
            ):
                continue
            return locator
        except Exception:
            continue
    return None


async def _advance_page(page: Any, locator: Any, channel: str) -> None:
    href = str(await locator.get_attribute("href") or "").strip()
    if href:
        current_url = str(await page.current_url() or "")
        destination = urljoin(current_url, href)
        if not url_matches_channel_surface(channel, destination):
            raise RuntimeError("pagination target left the protected search surface")
        await page.goto(
            destination,
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        return
    await locator.click()
    await page.wait_for_timeout(1500)
    current_url = str(await page.current_url() or "")
    if not url_matches_channel_surface(channel, current_url):
        raise RuntimeError("pagination left the protected search surface")
    refresher = getattr(page, "_refresh_busy_badge", None)
    if callable(refresher):
        await refresher(expected_url=current_url)


async def _read_search_evidence(
    page: Any,
    channel: str,
    keyword: str,
) -> tuple[bool, bool, int | None]:
    body_text = ""
    try:
        body_text = str(await page.locator("body").first.inner_text() or "")
    except Exception:
        pass
    normalized_keyword = " ".join(keyword.casefold().split())
    normalized_body = " ".join(body_text.casefold().split())
    query_verified = bool(normalized_keyword and normalized_keyword in normalized_body)
    result_count: int | None = None
    for selector in _RESULT_COUNT_SELECTORS[channel]:
        try:
            locator = page.locator(selector).first
            if int(await locator.count()) <= 0:
                continue
            text = str(await locator.inner_text() or "")
            match = _RESULT_COUNT_PATTERN.search(text)
            if match:
                result_count = int(match.group(1).replace(",", ""))
                break
        except Exception:
            continue
    if result_count is None:
        match = _RESULT_COUNT_PATTERN.search(body_text)
        if match:
            result_count = int(match.group(1).replace(",", ""))
    return query_verified, result_count is not None, result_count


async def _run_portal_search(
    channel: str,
    keywords: tuple[str, ...],
    *,
    job_id: str,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> dict[str, Any]:
    probe = probe_local_channel(channel, job_id=job_id)
    if probe["status"] != "ready":
        return {**probe, "queries": [], "cards": []}

    endpoint = resolve_channel_cdp_endpoint(channel, env=os.environ)
    config = PortalWorkerConfig(
        channel=channel,
        worker_id="default",
        profile_root=Path.home() / ".valuehire" / "winpc-local-worker-profiles",
        mode="headed",
        chrome_cdp_endpoint=endpoint,
        connection_mode="raw_single_tab",
        search_timeout_seconds=120.0,
    )
    worker = PortalWorker(
        config,
        owner_snapshot=_owner_explicit_snapshot_reader(),
    )
    ready_check = ready_check_for_channel(channel)
    policy = DEFAULT_PACING_POLICIES[channel]
    all_cards: dict[str, dict[str, str]] = {}
    queries: list[dict[str, Any]] = []
    try:
        for keyword_index, keyword in enumerate(keywords):
            attempt = await worker.run_one_search(
                keyword,
                ready_check=ready_check,
                monitor=_DomVerifiedLivenessMonitor(channel),
            )
            query_cards: dict[str, dict[str, str]] = {}
            for card in attempt.candidate_cards:
                query_cards[card.profile_url] = {
                    "profile_url": card.profile_url,
                    "snippet": card.snippet,
                }
            pages_visited = 1 if attempt.status == "searched" else 0
            last_page_reached = False
            query_verified = False
            result_count_verified = False
            result_count: int | None = None
            if attempt.status == "searched":
                page = worker._raw_page
                if page is None:
                    raise RuntimeError("raw search page disappeared")
                (
                    query_verified,
                    result_count_verified,
                    result_count,
                ) = await _read_search_evidence(page, channel, keyword)
                while pages_visited < MAX_PAGES_PER_KEYWORD:
                    next_page = await _next_page_locator(
                        page,
                        channel,
                        next_page_number=pages_visited + 1,
                    )
                    if next_page is None:
                        last_page_reached = True
                        break
                    await sleep(policy.next_page_delay_seconds())
                    await _advance_page(page, next_page, channel)
                    pages_visited += 1
                    for card in await collect_result_cards(page, channel):
                        query_cards[card.profile_url] = {
                            "profile_url": card.profile_url,
                            "snippet": card.snippet,
                        }
                all_cards.update(query_cards)
            queries.append(
                {
                    "keyword": keyword,
                    "status": attempt.status,
                    "reason": attempt.reason,
                    "pages_visited": pages_visited,
                    "last_page_reached": last_page_reached,
                    "card_count": len(query_cards),
                    "query_verified": query_verified,
                    "result_count_verified": result_count_verified,
                    "result_count": result_count,
                }
            )
            if attempt.status != "searched":
                break
            if keyword_index + 1 < len(keywords):
                await sleep(policy.next_search_delay_seconds())
    finally:
        await worker.stop()

    searched = bool(queries) and all(
        item["status"] == "searched"
        and item["query_verified"] is True
        and item["result_count_verified"] is True
        for item in queries
    )
    return {
        "status": "done" if searched else "blocked",
        "channel": channel,
        "state": "AUTHENTICATED",
        "login_verified": True,
        "query_verified": searched,
        "result_count_verified": searched,
        "queries": queries,
        "pages_visited": sum(int(item["pages_visited"]) for item in queries),
        "last_page_reached": bool(queries)
        and all(item["last_page_reached"] for item in queries),
        "opened_profiles": 0,
        "saved_receipts": 0,
        "profile_evidence": [],
        "cards": list(all_cards.values()),
        "browser_preserved": True,
    }


def run_local_portal_search(
    channel: str,
    keywords: tuple[str, ...] | list[str],
    *,
    job_id: str,
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
) -> dict[str, Any]:
    _activate_winpc_environment(
        channel,
        job_id=job_id,
        environ=environ,
        system_name=system_name,
    )
    return asyncio.run(_run_portal_search(channel, _normalize_keywords(keywords), job_id=job_id))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded WinPC managed portal operations")
    parser.add_argument("--channel", required=True, choices=CHANNELS)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.probe:
            if args.keyword or args.output is not None:
                raise ValueError("probe does not accept keywords or output")
            result = probe_local_channel(args.channel, job_id=args.job_id)
        else:
            if args.output is None:
                raise ValueError("search output path is required")
            result = run_local_portal_search(
                args.channel,
                tuple(args.keyword),
                job_id=args.job_id,
            )
            _write_json(args.output, result)
    except Exception as exc:
        result = {"status": "failed", "reason": type(exc).__name__}
        print(json.dumps(result, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") in {"ready", "done"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
