from __future__ import annotations

import base64
from datetime import date
import fcntl
import io
import json
from pathlib import Path
import random
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import urllib.error
from unittest.mock import AsyncMock, patch

from tools.multi_position_sourcing.access import (
    authorized_discord_users_from_markdown,
    is_authorized_discord_dm,
    portal_credential_status,
)
from tools.multi_position_sourcing.clickup_activity import format_clickup_activity_comment
from tools.multi_position_sourcing.discord_briefing import format_discord_candidate_briefing
from tools.multi_position_sourcing.discord_routing import (
    DiscordAccessConfig,
    DiscordInvocation,
    discord_message_content_intent_required,
    discord_slash_command_payloads,
    load_discord_access_config,
    parse_discord_command_text,
    route_discord_invocation,
)
from tools.multi_position_sourcing.register_discord_commands import bulk_register_discord_commands
from tools.multi_position_sourcing.dedup import SeenProfile, canonical_profile_url, seen_within_ttl
from tools.multi_position_sourcing.dry_run import build_dry_run_payload
from tools.multi_position_sourcing.posting_models import ExistingPositionTask, FetchResult
from tools.multi_position_sourcing.position_registration import run_position_registration
from tools.multi_position_sourcing.request_parser import parse_discord_position_registration_request
from tools.multi_position_sourcing.fixtures import SAMPLE_POSITIONS, SAMPLE_PROFILE
from tools.multi_position_sourcing.grouping import group_positions
from tools.multi_position_sourcing.keywords import keyword_plan_for_channel
from tools.multi_position_sourcing.models import CandidateResultCard, QueueItem
from tools.multi_position_sourcing.portal_login import (
    HumanInterventionOptions,
    _has_security_challenge,
    _wait_for_human_intervention,
)
from tools.multi_position_sourcing.portal_autologin import (
    auto_relogin_portal,
    login_selector_preflight,
)
from tools.multi_position_sourcing.portal_live_check import (
    LiveRestartSearchConfig,
    LiveSessionConfig,
    LiveSearchConfig,
    artifact_profile_precheck_payload,
    capture_live_snapshot,
    cleanup_artifact_profiles_payload,
    current_utc_week_start,
    utc_now_live_check,
    delete_profile_dir_if_confirmed,
    discord_webhook_from_env,
    init_discord_webhook_payload,
    init_portal_credentials_payload,
    init_session_key_payload,
    live_readiness_payload,
    missing_discord_alert_webhook_payload,
    main as portal_live_check_main,
    pacing_policy_proof_payload,
    safe_recovery_payload,
    safe_artifact_url,
    safe_attempt_payload,
    safe_live_search_timeout_payload,
    safe_profile_only_result_payload,
    profile_recovery_search_config,
    profile_recovery_snapshot_ready,
    portal_session_preflight_status_payload,
    profile_recovery_proof_status_payload,
    restart_smoke_proof_status_payload,
    refresh_dod_status_artifacts,
    run_profile_only_live_search,
    run_profile_recovery_smoke,
    run_live_search,
    safe_profile_lock_blocked_payload,
    safe_profile_recovery_not_run_payload,
    safe_restart_smoke_payload,
    safe_restart_smoke_timeout_payload,
    safe_result_payload,
    safe_snapshot_metadata_payload,
    safe_snapshot_payload,
    safe_weekly_counts_payload,
    safe_weekly_trend_payload,
    send_discord_alert_test,
    snapshot_metadata_payload,
    supabase_access_check_payload,
    supabase_schema_proof_payload,
    supabase_config_from_env,
    reauth_weekly_trend_payload,
    run_restart_search_smoke,
    weekly_reauth_counts_payload,
)
from tools.multi_position_sourcing.portal_dod_audit import (
    DEFAULT_PRODUCER_SCAN_PATH,
    DEFAULT_SECRET_SCAN_PATH,
    build_dod_audit_payload,
    latest_default_audit_artifacts,
)
from tools.multi_position_sourcing.portal_session import (
    portal_session_flags,
)
from tools.multi_position_sourcing.portal_ops import (
    DEFAULT_PACING_POLICIES,
    DiscordWebhookNotifier,
    InMemoryReauthEventStore,
    ReauthEvent,
    SitePacingPolicy,
    SupabaseReauthEventStore,
)
from tools.multi_position_sourcing.portal_runtime import GuardedPortalSearchRunner, GuardedSearchResult
from tools.multi_position_sourcing.portal_snapshot import (
    EncryptedSessionSnapshot,
    InMemorySessionSnapshotStore,
    MacKeychainSessionKeyProvider,
    OpenSslSessionEncryptor,
    SessionEncryptionError,
    StaticSessionKeyProvider,
    SupabaseRestConfig,
    SupabaseSessionStoreError,
    SupabaseSessionSnapshotStore,
    capture_validated_snapshot,
    decode_storage_state,
    encode_storage_state,
    restore_latest_validated_snapshot,
    reinject_storage_state,
    validate_snapshot_by_reinjection,
)
from tools.multi_position_sourcing.portal_recovery import (
    MacKeychainPortalCredentialProvider,
    PortalCredentials,
    recover_after_reauth,
)
from tools.multi_position_sourcing.portal_worker import (
    DEFAULT_PROFILE_ROOT,
    PortalWorker,
    PortalWorkerConfig,
    PortalWorkerConfigError,
    PortalSearchAttempt,
    ProfileLock,
    ProfileLockError,
    SearchLivenessMonitor,
    clear_stale_singleton_locks,
    collect_result_cards,
    run_search_with_recovery,
)
from tools.multi_position_sourcing.queue_runner import run_queue_cycle
from tools.multi_position_sourcing.request_parser import (
    parse_discord_position_registration_request,
    parse_discord_search_request,
)
from tools.multi_position_sourcing.scoring import top_matches_for_profile
from tools.multi_position_sourcing.selectors import (
    SelectorResolutionError,
    resolve_selector_from_map,
)
from tools.multi_position_sourcing.timeout_recovery import build_timeout_recovery_payload


class FakeLocator:
    def __init__(self, page: "FakePage", selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self) -> "FakeLocator":
        return self

    async def count(self) -> int:
        return 1 if self.selector in self.page.available_selectors else 0

    async def fill(self, value: str) -> None:
        self.page.filled.append((self.selector, value))

    async def click(self) -> None:
        self.page.clicked.append(self.selector)
        self.page.fire_click_responses()

    async def press(self, key: str) -> None:
        self.page.pressed.append((self.selector, key))


class FakePage:
    def __init__(
        self,
        available_selectors: set[str] | None = None,
        response_statuses: tuple[int, ...] = (),
        click_response_statuses: tuple[int, ...] = (),
    ) -> None:
        self.available_selectors = available_selectors or set()
        self.response_statuses = response_statuses
        self.click_response_statuses = click_response_statuses
        self.url = ""
        self.goto_calls: list[str] = []
        self.filled: list[tuple[str, str]] = []
        self.clicked: list[str] = []
        self.pressed: list[tuple[str, str]] = []
        self.event_handlers: dict[str, list[object]] = {}
        self.closed = False

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def on(self, event: str, handler: object) -> None:
        self.event_handlers.setdefault(event, []).append(handler)

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url
        self.goto_calls.append(url)
        for status in self.response_statuses:
            self._fire_response(status)

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None

    async def close(self) -> None:
        self.closed = True

    def fire_click_responses(self) -> None:
        for status in self.click_response_statuses:
            self._fire_response(status)

    def _fire_response(self, status: int) -> None:
        response = type("FakeResponse", (), {"status": status, "url": self.url})()
        for handler in self.event_handlers.get("response", []):
            handler(response)  # type: ignore[operator]


class FakeContext:
    def __init__(
        self,
        available_selectors: set[str] | None = None,
        response_statuses: tuple[int, ...] = (),
        click_response_statuses: tuple[int, ...] = (),
    ) -> None:
        self.available_selectors = available_selectors or set()
        self.response_statuses = response_statuses
        self.click_response_statuses = click_response_statuses
        self.pages: list[FakePage] = []
        self.closed = False

    async def new_page(self) -> FakePage:
        page = FakePage(self.available_selectors, self.response_statuses, self.click_response_statuses)
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.contexts = [context]
        self.closed = False

    async def new_context(self) -> FakeContext:
        context = FakeContext()
        self.contexts.append(context)
        return context

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, context: FakeContext) -> None:
        self.context = context
        self.browser = FakeBrowser(context)
        self.persistent_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.cdp_calls: list[str] = []

    async def launch_persistent_context(self, *args: object, **kwargs: object) -> FakeContext:
        self.persistent_calls.append((args, kwargs))
        return self.context

    async def connect_over_cdp(self, endpoint: str) -> FakeBrowser:
        self.cdp_calls.append(endpoint)
        return self.browser


class FakePlaywright:
    def __init__(self, context: FakeContext) -> None:
        self.chromium = FakeChromium(context)


class FakeSnapshotPage:
    def __init__(self) -> None:
        self.goto_calls: list[str] = []
        self.evaluate_calls: list[tuple[str, object]] = []
        self.closed = False

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.goto_calls.append(url)

    async def evaluate(self, script: str, payload: object) -> None:
        self.evaluate_calls.append((script, payload))

    async def close(self) -> None:
        self.closed = True


class FakeSnapshotContext:
    def __init__(self, state: dict[str, object] | None = None) -> None:
        self.state = state or {}
        self.added_cookies: list[dict[str, object]] = []
        self.pages: list[FakeSnapshotPage] = []
        self.closed = False

    async def storage_state(self) -> dict[str, object]:
        return self.state

    async def add_cookies(self, cookies: list[dict[str, object]]) -> None:
        self.added_cookies.extend(cookies)

    async def new_page(self) -> FakeSnapshotPage:
        page = FakeSnapshotPage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.closed = True


class FakeRuntimeWorker:
    def __init__(
        self,
        *,
        channel: str,
        worker_id: str,
        context: FakeSnapshotContext,
        attempts: list[PortalSearchAttempt],
    ) -> None:
        self.config = type("FakeRuntimeConfig", (), {"channel": channel, "worker_id": worker_id})()
        self.context = context
        self.attempts = attempts
        self.calls: list[str] = []

    async def run_one_search(
        self,
        keyword: str,
        *,
        ready_check: object | None = None,
        monitor: object | None = None,
    ) -> PortalSearchAttempt:
        self.calls.append(keyword)
        if not self.attempts:
            raise AssertionError("no queued portal search attempt")
        return self.attempts.pop(0)


def complete_preflight_session(channel: str) -> dict[str, object]:
    return {
        "channel": channel,
        "ready": True,
        "login": "existing_session_ok",
        "snapshot_capture_required": True,
        "snapshot_captured": True,
        "snapshot_capture_status": "captured",
    }


def complete_preflight_payload(*channels: str) -> dict[str, object]:
    return {
        "kind": "portal_session_preflight",
        "generated_at": "2026-06-09T00:00:00+00:00",
        "ready": True,
        "portal_sessions": [complete_preflight_session(channel) for channel in channels],
    }


def complete_linkedin_discord_event() -> dict[str, object]:
    return {
        "id": "manual-live-check",
        "site": "linkedin_rps",
        "worker_id": "default",
        "cause": "forced_logout",
        "recovered_by": "human",
        "occurred_at": "2026-06-09T00:00:00+00:00",
    }


def write_complete_preflight_artifact(root: Path) -> Path:
    path = root / "portal_session_status_latest.json"
    path.write_text(
        json.dumps(complete_preflight_payload("saramin", "jobkorea", "linkedin_rps")),
        encoding="utf-8",
    )
    return path


class FakeAutoLoginLocator:
    def __init__(self, page: "FakeAutoLoginPage", selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self) -> "FakeAutoLoginLocator":
        return self

    async def count(self) -> int:
        if self.selector == "body":
            return 1
        if self.selector == "input.search_input, #career_min, #career_max":
            return 1 if self.page.logged_in else 0
        if self.selector == "#txtKeyword, input[placeholder*='키워드'], input[placeholder*='검색']":
            return 1 if self.page.logged_in else 0
        if self.selector == 'a[href*="/talent/search"], input[role="combobox"]':
            return 1 if self.page.logged_in else 0
        return 1 if self.selector in self.page.available_selectors else 0

    async def fill(self, value: str) -> None:
        self.page.filled.append((self.selector, value))

    async def click(self, **_kwargs: object) -> None:
        self.page.clicked.append(self.selector)
        if self.selector in self.page.submit_selectors:
            self.page.logged_in = True
            self.page.url = self.page.ready_url

    async def inner_text(self, **_kwargs: object) -> str:
        return "로그아웃" if self.page.logged_in else "로그인"


class FakeAutoLoginPage:
    def __init__(self, *, available_selectors: set[str], submit_selectors: set[str], ready_url: str) -> None:
        self.available_selectors = available_selectors
        self.submit_selectors = submit_selectors
        self.ready_url = ready_url
        self.url = ""
        self.logged_in = False
        self.goto_calls: list[str] = []
        self.filled: list[tuple[str, str]] = []
        self.clicked: list[str] = []
        self.closed = False

    def locator(self, selector: str) -> FakeAutoLoginLocator:
        return FakeAutoLoginLocator(self, selector)

    def get_by_text(self, _text: str, **_kwargs: object) -> FakeAutoLoginLocator:
        return FakeAutoLoginLocator(self, "__missing_text__")

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url
        self.goto_calls.append(url)

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


class FakeAutoLoginContext:
    def __init__(self, page: FakeAutoLoginPage) -> None:
        self.page = page

    async def new_page(self) -> FakeAutoLoginPage:
        return self.page


class FakeCardItem:
    def __init__(self, href: str | None, text: str) -> None:
        self._href = href
        self._text = text

    async def get_attribute(self, name: str) -> str | None:
        return self._href if name == "href" else None

    async def inner_text(self) -> str:
        return self._text


class FakeCardLocator:
    def __init__(self, hrefs: list[str | None], texts: list[str]) -> None:
        self._hrefs = hrefs
        self._texts = texts

    async def count(self) -> int:
        return len(self._hrefs)

    def nth(self, index: int) -> FakeCardItem:
        return FakeCardItem(self._hrefs[index], self._texts[index])


class FakeCardPage:
    """A results page whose selectors map to (hrefs, snippets) for card extraction."""

    def __init__(self, mapping: dict[str, tuple[list[str | None], list[str]]]) -> None:
        self._mapping = mapping
        self.url = ""

    def locator(self, selector: str) -> FakeCardLocator:
        hrefs, texts = self._mapping.get(selector, ([], []))
        return FakeCardLocator(list(hrefs), list(texts))


class DirectSearchResultCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_linkedin_cards_dedupes_profile_links(self) -> None:
        page = FakeCardPage(
            {
                'a[href*="/talent/profile/"]': (
                    [
                        "https://www.linkedin.com/talent/profile/AAA",
                        "https://www.linkedin.com/talent/profile/BBB",
                        "https://www.linkedin.com/talent/profile/AAA",
                    ],
                    ["Backend Engineer · Seoul", "Platform Engineer · Pangyo", "dup"],
                )
            }
        )

        cards = await collect_result_cards(page, "linkedin_rps")

        self.assertEqual(
            [card.profile_url for card in cards],
            [
                "https://www.linkedin.com/talent/profile/AAA",
                "https://www.linkedin.com/talent/profile/BBB",
            ],
        )
        self.assertEqual(cards[0].source_channel, "linkedin_rps")
        self.assertEqual(cards[0].snippet, "Backend Engineer · Seoul")

    async def test_collect_saramin_cards_uses_first_matching_selector(self) -> None:
        page = FakeCardPage(
            {
                'a[href*="/zf_user/talent-pool"][href*="view"]': (
                    ["https://www.saramin.co.kr/zf_user/talent-pool/view?id=1"],
                    ["10y · 백엔드"],
                )
            }
        )

        cards = await collect_result_cards(page, "saramin")

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].source_channel, "saramin")
        self.assertTrue(cards[0].profile_url.endswith("id=1"))

    async def test_collect_result_cards_respects_limit(self) -> None:
        hrefs = [f"https://www.linkedin.com/talent/profile/{i}" for i in range(10)]
        page = FakeCardPage({'a[href*="/talent/profile/"]': (hrefs, [""] * 10)})

        cards = await collect_result_cards(page, "linkedin_rps", limit=3)

        self.assertEqual(len(cards), 3)

    async def test_collect_result_cards_is_failsoft_on_missing_layout(self) -> None:
        # A page with no matching card selectors must yield no cards, never an error,
        # so a changed DOM never turns a real search into a hard failure.
        class EmptyPage:
            def locator(self, _selector: str) -> FakeCardLocator:
                return FakeCardLocator([], [])

        cards = await collect_result_cards(EmptyPage(), "jobkorea")
        self.assertEqual(cards, ())

    def test_result_payload_surfaces_collected_cards(self) -> None:
        result = GuardedSearchResult(
            site="linkedin_rps",
            worker_id="default",
            keyword="backend",
            status="searched",
            reason="searched",
            candidate_cards=(
                CandidateResultCard(
                    profile_url="https://www.linkedin.com/talent/profile/AAA",
                    source_channel="linkedin_rps",
                    snippet="Backend Engineer",
                ),
            ),
        )

        payload = safe_result_payload(result)

        self.assertEqual(payload["result_count"], 1)
        self.assertEqual(payload["results"][0]["profile_url"], "https://www.linkedin.com/talent/profile/AAA")  # type: ignore[index]
        self.assertEqual(payload["results"][0]["source_channel"], "linkedin_rps")  # type: ignore[index]

    def test_result_payload_sanitizes_collected_card_urls(self) -> None:
        result = GuardedSearchResult(
            site="jobkorea",
            worker_id="default",
            keyword="backend",
            status="searched",
            reason="searched",
            candidate_cards=(
                CandidateResultCard(
                    profile_url="https://user:pass@www.jobkorea.co.kr/Person/Profile/1?cookie=session-secret#token-secret",
                    source_channel="jobkorea",
                    snippet="Backend Engineer",
                ),
            ),
        )

        payload = safe_result_payload(result)
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["results"][0]["profile_url"], "https://www.jobkorea.co.kr/Person/Profile/1")  # type: ignore[index]
        self.assertNotIn("session-secret", encoded)
        self.assertNotIn("token-secret", encoded)
        self.assertNotIn("user:pass", encoded)

    def test_profile_only_result_payload_marks_snapshot_capture_skipped(self) -> None:
        attempt = PortalSearchAttempt(
            channel="jobkorea",
            worker_id="default",
            keyword="backend",
            status="searched",
            reason="keyword submitted on persistent portal context",
            url="https://www.jobkorea.co.kr/Corp/Person/Find",
        )

        payload = safe_profile_only_result_payload(attempt)
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["mode"], "profile_only")
        self.assertEqual(payload["status"], "searched")
        self.assertEqual(payload["attempt_status"], "searched")
        self.assertFalse(payload["snapshot_capture_required"])
        self.assertEqual(payload["snapshot_capture_policy"], "skipped_profile_only")
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("cookie", encoded.lower())
        self.assertNotIn("password", encoded.lower())

    async def test_profile_only_live_search_respects_daily_cap_before_browser_start(self) -> None:
        with patch("playwright.async_api.async_playwright") as async_playwright:
            payload = await run_profile_only_live_search(
                LiveSearchConfig(
                    channel="linkedin_rps",
                    keyword="backend",
                    worker_id="default",
                    profile_root=Path("/tmp/valuehire-test-profiles"),
                    chrome_cdp_endpoint="http://127.0.0.1:9222",
                    headless=False,
                    searches_today=DEFAULT_PACING_POLICIES["linkedin_rps"].daily_search_cap,
                    no_sleep=True,
                    disable_auto_relogin=False,
                    delete_profile_before_start=False,
                    confirm_delete_profile="",
                    profile_only=True,
                )
            )

        self.assertEqual(payload["mode"], "profile_only")
        self.assertEqual(payload["status"], "pacing_blocked")
        self.assertTrue(payload["skipped_due_to_cap"])
        self.assertFalse(payload["snapshot_capture_required"])
        async_playwright.assert_not_called()

    def test_profile_lock_blocked_payload_is_safe(self) -> None:
        payload = safe_profile_lock_blocked_payload(
            site="linkedin_rps",
            worker_id="default",
            keyword="backend",
            mode="profile_only",
            snapshot_capture_required=False,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["mode"], "profile_only")
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["reason"], "profile_locked")
        self.assertEqual(payload["attempt_status"], "not_ready")
        self.assertEqual(payload["attempt_reason"], "profile_locked")
        self.assertTrue(payload["profile_lock_blocked"])
        self.assertFalse(payload["snapshot_capture_required"])
        self.assertEqual(payload["snapshot_capture_policy"], "skipped_profile_only")
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("cookie", encoded.lower())
        self.assertNotIn("password", encoded.lower())
        self.assertNotIn("/tmp/", encoded)

    async def test_profile_only_live_search_reports_profile_lock_without_traceback(self) -> None:
        class FakePlaywrightManager:
            async def __aenter__(self) -> object:
                return object()

            async def __aexit__(self, *_exc: object) -> None:
                return None

        class LockingPortalWorker:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            async def __aenter__(self) -> object:
                raise ProfileLockError("profile already locked for saramin/worker-a")

            async def __aexit__(self, *_exc: object) -> None:
                return None

        with patch(
            "playwright.async_api.async_playwright",
            return_value=FakePlaywrightManager(),
        ) as async_playwright, patch(
            "tools.multi_position_sourcing.portal_live_check.PortalWorker",
            LockingPortalWorker,
        ):
            payload = await run_profile_only_live_search(
                LiveSearchConfig(
                    channel="saramin",
                    keyword="backend",
                    worker_id="worker-a",
                    profile_root=Path("/tmp/valuehire-test-profiles"),
                    chrome_cdp_endpoint="http://127.0.0.1:9222",
                    headless=False,
                    searches_today=0,
                    no_sleep=True,
                    disable_auto_relogin=False,
                    delete_profile_before_start=False,
                    confirm_delete_profile="",
                    profile_only=True,
                )
            )

        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["mode"], "profile_only")
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["reason"], "profile_locked")
        self.assertTrue(payload["profile_lock_blocked"])
        self.assertFalse(payload["snapshot_capture_required"])
        self.assertNotIn("saramin/worker-a", encoded)
        self.assertNotIn("/tmp/valuehire-test-profiles", encoded)
        async_playwright.assert_called_once()

    async def test_guarded_live_search_reports_profile_lock_without_traceback(self) -> None:
        class FakePlaywrightManager:
            async def __aenter__(self) -> object:
                return object()

            async def __aexit__(self, *_exc: object) -> None:
                return None

        class LockingPortalWorker:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            async def __aenter__(self) -> object:
                raise ProfileLockError("profile already locked for jobkorea/worker-a")

            async def __aexit__(self, *_exc: object) -> None:
                return None

        with patch(
            "tools.multi_position_sourcing.portal_live_check.supabase_config_from_env",
            return_value=SupabaseRestConfig(
                url="https://project.example.supabase.co",
                service_role_key="service-role-token",
            ),
        ), patch(
            "tools.multi_position_sourcing.portal_live_check.discord_webhook_from_env",
            return_value="",
        ), patch(
            "playwright.async_api.async_playwright",
            return_value=FakePlaywrightManager(),
        ) as async_playwright, patch(
            "tools.multi_position_sourcing.portal_live_check.PortalWorker",
            LockingPortalWorker,
        ):
            payload = await run_live_search(
                LiveSearchConfig(
                    channel="jobkorea",
                    keyword="backend",
                    worker_id="worker-a",
                    profile_root=Path("/tmp/valuehire-test-profiles"),
                    chrome_cdp_endpoint="http://127.0.0.1:9222",
                    headless=False,
                    searches_today=0,
                    no_sleep=True,
                    disable_auto_relogin=True,
                    delete_profile_before_start=False,
                    confirm_delete_profile="",
                    profile_only=False,
                )
            )

        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["mode"], "guarded")
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["reason"], "profile_locked")
        self.assertTrue(payload["profile_lock_blocked"])
        self.assertTrue(payload["snapshot_capture_required"])
        self.assertEqual(payload["snapshot_capture_policy"], "required")
        self.assertNotIn("jobkorea/worker-a", encoded)
        self.assertNotIn("/tmp/valuehire-test-profiles", encoded)
        async_playwright.assert_called_once()

    async def test_capture_live_snapshot_closes_ready_check_page_after_capture(self) -> None:
        class FakePlaywrightManager:
            async def __aenter__(self) -> object:
                return object()

            async def __aexit__(self, *_exc: object) -> None:
                return None

        class SnapshotPortalWorker:
            instances: list["SnapshotPortalWorker"] = []

            def __init__(self, *_args: object, **_kwargs: object) -> None:
                self.context = FakeSnapshotContext()
                self.browser = None
                self.instances.append(self)

            async def __aenter__(self) -> "SnapshotPortalWorker":
                return self

            async def __aexit__(self, *_exc: object) -> None:
                return None

        record = EncryptedSessionSnapshot(
            site="saramin",
            worker_id="default",
            storage_state_enc=b"",
            is_validated=True,
            kind="current",
            captured_at="2026-06-09T00:00:00+00:00",
            updated_at="2026-06-09T00:00:00+00:00",
        )

        async def ready_check(_page: FakeSnapshotPage) -> bool:
            return True

        with patch(
            "tools.multi_position_sourcing.portal_live_check.supabase_config_from_env",
            return_value=SupabaseRestConfig(
                url="https://project.example.supabase.co",
                service_role_key="service-role-token",
            ),
        ), patch(
            "tools.multi_position_sourcing.portal_live_check.ready_check_for_channel",
            return_value=ready_check,
        ), patch(
            "playwright.async_api.async_playwright",
            return_value=FakePlaywrightManager(),
        ), patch(
            "tools.multi_position_sourcing.portal_live_check.PortalWorker",
            SnapshotPortalWorker,
        ), patch(
            "tools.multi_position_sourcing.portal_live_check.capture_validated_snapshot",
            AsyncMock(return_value=record),
        ) as capture_snapshot:
            payload = await capture_live_snapshot(
                LiveSessionConfig(
                    channel="saramin",
                    worker_id="default",
                    profile_root=Path("/tmp/valuehire-test-profiles"),
                    chrome_cdp_endpoint="http://127.0.0.1:9222",
                    headless=False,
                )
            )

        self.assertEqual(payload["status"], "captured")
        self.assertTrue(SnapshotPortalWorker.instances[0].context.pages[0].closed)
        capture_snapshot.assert_awaited_once()

    async def test_capture_live_snapshot_closes_ready_check_page_when_not_ready(self) -> None:
        class FakePlaywrightManager:
            async def __aenter__(self) -> object:
                return object()

            async def __aexit__(self, *_exc: object) -> None:
                return None

        class SnapshotPortalWorker:
            instances: list["SnapshotPortalWorker"] = []

            def __init__(self, *_args: object, **_kwargs: object) -> None:
                self.context = FakeSnapshotContext()
                self.browser = None
                self.instances.append(self)

            async def __aenter__(self) -> "SnapshotPortalWorker":
                return self

            async def __aexit__(self, *_exc: object) -> None:
                return None

        async def not_ready_check(_page: FakeSnapshotPage) -> bool:
            return False

        with patch(
            "tools.multi_position_sourcing.portal_live_check.supabase_config_from_env",
            return_value=SupabaseRestConfig(
                url="https://project.example.supabase.co",
                service_role_key="service-role-token",
            ),
        ), patch(
            "tools.multi_position_sourcing.portal_live_check.ready_check_for_channel",
            return_value=not_ready_check,
        ), patch(
            "playwright.async_api.async_playwright",
            return_value=FakePlaywrightManager(),
        ), patch(
            "tools.multi_position_sourcing.portal_live_check.PortalWorker",
            SnapshotPortalWorker,
        ), patch(
            "tools.multi_position_sourcing.portal_live_check.capture_validated_snapshot",
            AsyncMock(),
        ) as capture_snapshot:
            payload = await capture_live_snapshot(
                LiveSessionConfig(
                    channel="saramin",
                    worker_id="default",
                    profile_root=Path("/tmp/valuehire-test-profiles"),
                    chrome_cdp_endpoint="http://127.0.0.1:9222",
                    headless=False,
                )
            )

        self.assertEqual(payload["status"], "not_captured")
        self.assertFalse(payload["ready"])
        self.assertTrue(SnapshotPortalWorker.instances[0].context.pages[0].closed)
        capture_snapshot.assert_not_awaited()

    def test_profile_only_restart_smoke_payload_is_marked_separately(self) -> None:
        first = safe_profile_only_result_payload(
            PortalSearchAttempt(
                channel="jobkorea",
                worker_id="default",
                keyword="backend",
                status="searched",
                reason="first profile-only search",
            )
        )
        second = safe_profile_only_result_payload(
            PortalSearchAttempt(
                channel="jobkorea",
                worker_id="default",
                keyword="backend",
                status="searched",
                reason="second profile-only search",
            )
        )

        payload = safe_restart_smoke_payload(
            site="jobkorea",
            worker_id="default",
            keyword="backend",
            first=first,
            second=second,
        )

        self.assertTrue(payload["passed"])
        self.assertIsInstance(payload["generated_at"], str)
        self.assertEqual(payload["mode"], "profile_only")
        self.assertEqual(payload["snapshot_capture_policy"], "skipped_profile_only")

    async def test_restart_smoke_skips_second_lifecycle_when_first_times_out(self) -> None:
        calls: list[str] = []

        async def fake_run_live_search(_config: object) -> dict[str, object]:
            calls.append("called")
            return safe_live_search_timeout_payload(
                site="jobkorea",
                worker_id="default",
                keyword="backend",
                lifecycle="first",
                timeout_seconds=3,
            )

        with patch("tools.multi_position_sourcing.portal_live_check.run_live_search", fake_run_live_search):
            payload = await run_restart_search_smoke(
                LiveRestartSearchConfig(
                    channel="jobkorea",
                    keyword="backend",
                    worker_id="default",
                    profile_root=Path("/tmp/valuehire-test-profiles"),
                    chrome_cdp_endpoint="http://127.0.0.1:9222",
                    headless=False,
                    searches_today=0,
                    no_sleep=True,
                    disable_auto_relogin=False,
                    timeout_seconds=3,
                )
            )

        self.assertEqual(calls, ["called"])
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["status"], "timeout")
        self.assertEqual(payload["first"]["status"], "timeout")  # type: ignore[index]
        self.assertEqual(payload["second"]["status"], "not_run")  # type: ignore[index]
        self.assertEqual(payload["second"]["reason"], "first_lifecycle_not_clean")  # type: ignore[index]

    async def test_restart_smoke_counts_second_lifecycle_against_daily_cap(self) -> None:
        searches_today_seen: list[int] = []

        async def fake_run_live_search(config: LiveSearchConfig) -> dict[str, object]:
            searches_today_seen.append(config.searches_today)
            return safe_profile_only_result_payload(
                PortalSearchAttempt(
                    channel=config.channel,
                    worker_id=config.worker_id,
                    keyword=config.keyword,
                    status="searched",
                    reason="keyword submitted on persistent portal context",
                )
            )

        with patch("tools.multi_position_sourcing.portal_live_check.run_live_search", fake_run_live_search):
            payload = await run_restart_search_smoke(
                LiveRestartSearchConfig(
                    channel="linkedin_rps",
                    keyword="backend",
                    worker_id="default",
                    profile_root=Path("/tmp/valuehire-test-profiles"),
                    chrome_cdp_endpoint="http://127.0.0.1:9222",
                    headless=False,
                    searches_today=DEFAULT_PACING_POLICIES["linkedin_rps"].daily_search_cap - 2,
                    no_sleep=True,
                    disable_auto_relogin=False,
                    timeout_seconds=3,
                    profile_only=True,
                )
            )

        self.assertTrue(payload["passed"])
        self.assertEqual(
            searches_today_seen,
            [
                DEFAULT_PACING_POLICIES["linkedin_rps"].daily_search_cap - 2,
                DEFAULT_PACING_POLICIES["linkedin_rps"].daily_search_cap - 1,
            ],
        )


class MultiPositionSourcingTests(unittest.TestCase):
    def symlink_or_skip(self, link: Path, target: Path, *, target_is_directory: bool) -> None:
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"symlink unavailable: {exc}")

    def test_position_grouping_creates_role_groups_and_backend_pair(self) -> None:
        groups = group_positions(SAMPLE_POSITIONS)
        families = {group.role_family for group in groups}
        self.assertIn("backend", families)
        self.assertIn("product_po", families)
        backend_group = next(group for group in groups if group.role_family == "backend")
        self.assertEqual(set(backend_group.position_ids), {"pos-backend-wrtn", "pos-backend-spoon"})
        self.assertTrue(backend_group.company_similarity_notes)

    def test_portal_keyword_generation_uses_one_standard_word_per_session(self) -> None:
        backend_group = next(group for group in group_positions(SAMPLE_POSITIONS) if group.role_family == "backend")
        saramin_sessions = keyword_plan_for_channel(backend_group, "saramin")
        public_web_sessions = keyword_plan_for_channel(backend_group, "public_web")
        self.assertGreaterEqual(len(saramin_sessions), 4)
        self.assertGreaterEqual(len(public_web_sessions), 3)
        self.assertEqual(saramin_sessions[0].standard_keyword, "백엔드 개발자")
        self.assertIn("site:linkedin.com/in", public_web_sessions[0].standard_keyword)
        self.assertTrue(all(session.reset_before_run for session in saramin_sessions))
        self.assertTrue(all(len(session.variants) == 0 for session in saramin_sessions))
        self.assertIn("llm product", saramin_sessions[0].llm_screening_keywords)

    def test_canonical_profile_dedup_normalizes_urls_and_ttl(self) -> None:
        url = "https://www.linkedin.com/talent/profile/ABC123?trk=search#frag"
        canonical = canonical_profile_url(url)
        self.assertEqual(canonical, "https://www.linkedin.com/talent/profile/abc123")
        seen = (SeenProfile(canonical, "2026-06-08T00:00:00+00:00"),)
        self.assertTrue(seen_within_ttl(url, seen, "2026-06-08T12:00:00+00:00", ttl_hours=24))
        self.assertFalse(seen_within_ttl(url, seen, "2026-06-10T12:00:00+00:00", ttl_hours=24))

    def test_profile_to_multi_position_scoring_returns_top_positions(self) -> None:
        matches = top_matches_for_profile(SAMPLE_PROFILE, SAMPLE_POSITIONS, top_n=5)
        self.assertGreaterEqual(len(matches), 5)
        self.assertEqual(matches[0].position_id, "pos-backend-wrtn")
        self.assertGreater(matches[0].score, matches[-1].score)
        self.assertTrue(matches[0].why_fit)
        self.assertTrue(matches[0].evidence_paths)

    def test_selector_fallback_resolution_prefers_stable_selector(self) -> None:
        selected = resolve_selector_from_map(
            "saramin",
            "keyword_input",
            {".search_default input.search_input", "#searchword"},
        )
        self.assertEqual(selected.selector, "#searchword")
        selected = resolve_selector_from_map(
            "jobkorea",
            "keyword_input",
            {"#txtKeyword", 'input[placeholder*="검색어"]'},
        )
        self.assertEqual(selected.selector, "#txtKeyword")

    def test_selector_failure_is_explicit(self) -> None:
        with self.assertRaises(SelectorResolutionError):
            resolve_selector_from_map("saramin", "keyword_input", set())

    def test_dry_run_queue_preserves_pending_without_chrome(self) -> None:
        groups = group_positions(SAMPLE_POSITIONS)
        queue = (
            QueueItem(group_id=groups[0].group_id, channel="saramin", keyword_plan=groups[0].keyword_plan),
        )
        summary = run_queue_cycle(
            queue,
            now_iso="2026-06-08T00:00:00+00:00",
            chrome_connected=False,
        )
        self.assertEqual(summary.searched_groups, ())
        self.assertIn("Chrome CDP not connected", summary.stopped_reasons[0])
        self.assertEqual(summary.updated_items[0].status, "pending")

    def test_queue_requires_portal_session_for_protected_channels(self) -> None:
        queue = (
            QueueItem(group_id="backend-portal", channel="saramin", keyword_plan=()),
        )
        summary = run_queue_cycle(
            queue,
            now_iso="2026-06-08T00:00:00+00:00",
            chrome_connected=True,
        )
        self.assertEqual(summary.searched_groups, ())
        self.assertIn("saramin login session not confirmed", summary.stopped_reasons[0])
        self.assertEqual(summary.updated_items[0].status, "pending")

    def test_queue_processes_protected_channel_after_portal_session_confirmation(self) -> None:
        queue = (
            QueueItem(group_id="backend-portal", channel="saramin", keyword_plan=()),
        )
        summary = run_queue_cycle(
            queue,
            now_iso="2026-06-08T00:00:00+00:00",
            chrome_connected=True,
            portal_sessions={"saramin": True},
        )
        self.assertEqual(summary.searched_groups, ("backend-portal",))
        self.assertEqual(summary.stopped_reasons, ())
        self.assertEqual(summary.updated_items[0].status, "done")

    def test_queue_allows_public_web_without_portal_session(self) -> None:
        queue = (
            QueueItem(group_id="backend-public", channel="public_web", keyword_plan=()),
        )
        summary = run_queue_cycle(
            queue,
            now_iso="2026-06-08T00:00:00+00:00",
            chrome_connected=True,
        )
        self.assertEqual(summary.searched_groups, ("backend-public",))
        self.assertEqual(summary.updated_items[0].status, "done")

    def test_dry_run_does_not_use_plaintext_storage_state_for_session_flags(self) -> None:
        payload = build_dry_run_payload()
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertIn("persistent profile live check required", encoded)
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("storage-state.json", encoded)
        self.assertNotIn("storage state has portal session evidence", encoded)

    def test_portal_runbooks_forbid_scheduled_readiness_heartbeats(self) -> None:
        paths = (
            Path("docs/ai-search/portal-browser-runbook-2026-06-08.md"),
            Path("docs/ai-search/multi-position-sourcing-layer-2026-06-08.md"),
        )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()

        self.assertIn("on demand", combined)
        self.assertIn("not as a timed heartbeat", combined)
        self.assertNotIn("session readiness check: every 15 minutes", combined)
        self.assertNotIn("readiness check: every 15 minutes", combined)
        self.assertNotIn("readiness heartbeat", combined)

    def test_portal_worker_profile_dirs_are_site_and_worker_scoped(self) -> None:
        with TemporaryDirectory() as tmp:
            saramin_a = PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=tmp)
            saramin_b = PortalWorkerConfig(channel="saramin", worker_id="worker-b", profile_root=tmp)
            jobkorea_a = PortalWorkerConfig(channel="jobkorea", worker_id="worker-a", profile_root=tmp)

        self.assertNotEqual(saramin_a.profile_dir, saramin_b.profile_dir)
        self.assertNotEqual(saramin_a.profile_dir, jobkorea_a.profile_dir)
        self.assertEqual(saramin_a.profile_dir.name, "worker-a")
        self.assertEqual(saramin_a.profile_dir.parent.name, "saramin")

    def test_portal_worker_rejects_dot_worker_ids_that_escape_profile_scope(self) -> None:
        with TemporaryDirectory() as tmp:
            for worker_id in (".", ".."):
                with self.subTest(worker_id=worker_id):
                    with self.assertRaises(PortalWorkerConfigError):
                        PortalWorkerConfig(channel="saramin", worker_id=worker_id, profile_root=tmp)

    def test_portal_worker_rejects_artifact_profile_root(self) -> None:
        with self.assertRaises(PortalWorkerConfigError) as caught:
            PortalWorkerConfig(
                channel="saramin",
                worker_id="worker-a",
                profile_root=Path("artifacts") / "portal_profiles",
            )

        self.assertIn("profile_root must not be inside artifacts", str(caught.exception))

    def test_live_configs_reject_artifact_profile_root_before_browser_start(self) -> None:
        profile_root = Path("artifacts") / "portal_profiles"
        with self.assertRaises(PortalWorkerConfigError):
            LiveSearchConfig(
                channel="jobkorea",
                keyword="backend",
                worker_id="default",
                profile_root=profile_root,
                chrome_cdp_endpoint="http://127.0.0.1:9222",
                headless=False,
                searches_today=0,
                no_sleep=True,
                disable_auto_relogin=True,
                delete_profile_before_start=False,
                confirm_delete_profile="",
            )
        with self.assertRaises(PortalWorkerConfigError):
            LiveRestartSearchConfig(
                channel="saramin",
                keyword="backend",
                worker_id="default",
                profile_root=profile_root,
                chrome_cdp_endpoint="http://127.0.0.1:9222",
                headless=False,
                searches_today=0,
                no_sleep=True,
                disable_auto_relogin=True,
                timeout_seconds=1,
            )
        with self.assertRaises(PortalWorkerConfigError):
            LiveSessionConfig(
                channel="linkedin_rps",
                worker_id="default",
                profile_root=profile_root,
                chrome_cdp_endpoint="http://127.0.0.1:9222",
                headless=False,
            )

    def test_default_portal_profile_root_is_not_an_artifact_path(self) -> None:
        self.assertNotIn("artifacts", DEFAULT_PROFILE_ROOT.parts)
        self.assertEqual(DEFAULT_PROFILE_ROOT.name, "portal_profiles")

    def test_default_secret_scan_path_is_safe_artifact_scope(self) -> None:
        self.assertEqual(DEFAULT_SECRET_SCAN_PATH, Path("artifacts/portal_session_dod"))
        self.assertEqual(DEFAULT_PRODUCER_SCAN_PATH, Path("artifacts"))

    def test_discord_command_registration_error_does_not_echo_response_body(self) -> None:
        raw_body = (
            b'{"message":"invalid bot token discord-bot-token-secret",'
            b'"storage_state":{"cookies":[{"value":"cookie-secret"}]}}'
        )

        def fake_urlopen(_request: object, *, timeout: int) -> object:
            raise urllib.error.HTTPError(
                "https://discord.com/api/v10/applications/app/commands",
                401,
                "Unauthorized",
                hdrs={},
                fp=io.BytesIO(raw_body),
            )

        with patch("tools.multi_position_sourcing.register_discord_commands.request.urlopen", fake_urlopen):
            result = bulk_register_discord_commands(
                application_id="app",
                bot_token="discord-bot-token-secret",
                payloads=[{"name": "session-status"}],
            )
        encoded = json.dumps(result, ensure_ascii=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 401)
        self.assertEqual(result["error_hint"], "discord_bot_token_rejected")
        self.assertNotIn("discord-bot-token-secret", encoded)
        self.assertNotIn("cookie-secret", encoded)
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("body", result)

    def test_linkedin_worker_is_single_headed_cdp_worker(self) -> None:
        with self.assertRaises(PortalWorkerConfigError):
            PortalWorkerConfig(channel="linkedin_rps", worker_id="worker-2")
        with self.assertRaises(PortalWorkerConfigError):
            PortalWorkerConfig(channel="linkedin_rps", mode="headless")

        config = PortalWorkerConfig(channel="linkedin_rps")
        self.assertEqual(config.worker_id, "default")
        self.assertFalse(config.headless)

    def test_linkedin_default_worker_profile_lock_is_exclusive(self) -> None:
        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(channel="linkedin_rps", profile_root=tmp)
            first = ProfileLock(config)
            second = ProfileLock(config)
            try:
                first.acquire()
                with self.assertRaises(ProfileLockError):
                    second.acquire()
                lock_text = config.lock_path.read_text(encoding="utf-8")
            finally:
                second.release()
                first.release()

        self.assertIn("channel=linkedin_rps", lock_text)
        self.assertIn("worker_id=default", lock_text)

    def test_linkedin_default_worker_profile_lock_blocks_second_process(self) -> None:
        child_code = """
import sys
from tools.multi_position_sourcing.portal_worker import PortalWorkerConfig, ProfileLock, ProfileLockError

config = PortalWorkerConfig(channel="linkedin_rps", profile_root=sys.argv[1])
try:
    with ProfileLock(config):
        pass
except ProfileLockError:
    sys.exit(7)
sys.exit(0)
"""
        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(channel="linkedin_rps", profile_root=tmp)
            with ProfileLock(config):
                blocked = subprocess.run(
                    [sys.executable, "-c", child_code, tmp],
                    cwd=Path(__file__).resolve().parents[1],
                    check=False,
                )
            released = subprocess.run(
                [sys.executable, "-c", child_code, tmp],
                cwd=Path(__file__).resolve().parents[1],
                check=False,
            )

        self.assertEqual(blocked.returncode, 7)
        self.assertEqual(released.returncode, 0)

    def test_profile_lock_blocks_same_profile_across_processes(self) -> None:
        child_code = """
import sys
from tools.multi_position_sourcing.portal_worker import PortalWorkerConfig, ProfileLock, ProfileLockError

config = PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=sys.argv[1])
try:
    with ProfileLock(config):
        pass
except ProfileLockError:
    sys.exit(7)
sys.exit(0)
"""
        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=tmp)
            with ProfileLock(config):
                blocked = subprocess.run(
                    [sys.executable, "-c", child_code, tmp],
                    cwd=Path(__file__).resolve().parents[1],
                    check=False,
                )
            released = subprocess.run(
                [sys.executable, "-c", child_code, tmp],
                cwd=Path(__file__).resolve().parents[1],
                check=False,
            )

        self.assertEqual(blocked.returncode, 7)
        self.assertEqual(released.returncode, 0)

    def test_profile_lock_rejects_symlink_profile_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_root = root / "target-root"
            target_root.mkdir()
            linked_root = root / "linked-root"
            self.symlink_or_skip(linked_root, target_root, target_is_directory=True)
            config = PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=linked_root)

            with self.assertRaisesRegex(ProfileLockError, "symlinks"):
                ProfileLock(config).acquire()

            self.assertFalse((target_root / "saramin" / "worker-a" / ".profile.lock").exists())

    def test_profile_lock_rejects_symlink_channel_or_profile_dir(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_channel = root / "target-channel"
            target_channel.mkdir()
            linked_channel = root / "saramin"
            self.symlink_or_skip(linked_channel, target_channel, target_is_directory=True)
            channel_config = PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=root)

            with self.assertRaisesRegex(ProfileLockError, "symlinks"):
                ProfileLock(channel_config).acquire()

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            channel_dir = root / "jobkorea"
            channel_dir.mkdir()
            target_profile = root / "target-profile"
            target_profile.mkdir()
            linked_profile = channel_dir / "worker-a"
            self.symlink_or_skip(linked_profile, target_profile, target_is_directory=True)
            profile_config = PortalWorkerConfig(channel="jobkorea", worker_id="worker-a", profile_root=root)

            with self.assertRaisesRegex(ProfileLockError, "symlinks"):
                ProfileLock(profile_config).acquire()

    def test_profile_lock_rejects_symlink_lock_file(self) -> None:
        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=tmp)
            config.profile_dir.mkdir(parents=True)
            target_lock = Path(tmp) / "target.lock"
            target_lock.write_text("outside lock", encoding="utf-8")
            self.symlink_or_skip(config.lock_path, target_lock, target_is_directory=False)

            with self.assertRaisesRegex(ProfileLockError, "lock path"):
                ProfileLock(config).acquire()

            self.assertEqual(target_lock.read_text(encoding="utf-8"), "outside lock")

    def test_profile_lock_acquire_closes_handle_when_metadata_write_fails(self) -> None:
        class WriteFailingLockHandle:
            def __init__(self, lock_path: Path) -> None:
                self._handle = lock_path.open("a+", encoding="utf-8")
                self.closed = False

            def fileno(self) -> int:
                return self._handle.fileno()

            def seek(self, offset: int) -> int:
                return self._handle.seek(offset)

            def truncate(self) -> int:
                return self._handle.truncate()

            def write(self, _value: str) -> int:
                raise RuntimeError("lock metadata write failed with cookie-secret")

            def flush(self) -> None:
                self._handle.flush()

            def close(self) -> None:
                self.closed = True
                self._handle.close()

        opened: list[WriteFailingLockHandle] = []

        def fake_open_real_profile_lock(lock_path: Path) -> WriteFailingLockHandle:
            handle = WriteFailingLockHandle(lock_path)
            opened.append(handle)
            return handle

        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=tmp)
            with patch(
                "tools.multi_position_sourcing.portal_worker._open_real_profile_lock",
                fake_open_real_profile_lock,
            ):
                with self.assertRaisesRegex(RuntimeError, "metadata write failed"):
                    ProfileLock(config).acquire()

            self.assertTrue(opened[0].closed)
            with ProfileLock(config):
                lock_text = config.lock_path.read_text(encoding="utf-8")

        self.assertIn("channel=saramin", lock_text)
        self.assertNotIn("cookie-secret", lock_text)

    def test_profile_lock_acquire_closes_handle_when_flock_fails_unsafely(self) -> None:
        class FlockFailingLockHandle:
            def __init__(self, lock_path: Path) -> None:
                self._handle = lock_path.open("a+", encoding="utf-8")
                self.closed = False

            def fileno(self) -> int:
                return self._handle.fileno()

            def close(self) -> None:
                self.closed = True
                self._handle.close()

        opened: list[FlockFailingLockHandle] = []

        def fake_open_real_profile_lock(lock_path: Path) -> FlockFailingLockHandle:
            handle = FlockFailingLockHandle(lock_path)
            opened.append(handle)
            return handle

        def fake_flock(_fd: int, operation: int) -> None:
            if operation & fcntl.LOCK_EX:
                raise RuntimeError("flock failed with cookie-secret")

        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(channel="jobkorea", worker_id="worker-a", profile_root=tmp)
            with patch(
                "tools.multi_position_sourcing.portal_worker._open_real_profile_lock",
                fake_open_real_profile_lock,
            ), patch("tools.multi_position_sourcing.portal_worker.fcntl.flock", fake_flock):
                with self.assertRaisesRegex(ProfileLockError, "without exposing details") as raised:
                    ProfileLock(config).acquire()

            self.assertTrue(opened[0].closed)
            self.assertNotIn("cookie-secret", str(raised.exception))
            with ProfileLock(config):
                lock_text = config.lock_path.read_text(encoding="utf-8")

        self.assertIn("channel=jobkorea", lock_text)
        self.assertNotIn("cookie-secret", lock_text)

    def test_mac_keychain_provider_reads_existing_base64_key(self) -> None:
        encoded_key = base64.b64encode(b"k" * 32)
        calls: list[list[str]] = []

        def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout=encoded_key, stderr=b"")

        with patch("tools.multi_position_sourcing.portal_snapshot.subprocess.run", fake_run):
            key = MacKeychainSessionKeyProvider(create_if_missing=False).get_key()

        self.assertEqual(key, b"k" * 32)
        self.assertEqual(calls[0][0:4], ["security", "find-generic-password", "-s", "valuehire.session_state"])

    def test_mac_keychain_provider_creates_key_without_key_material_in_argv(self) -> None:
        find_calls: list[list[str]] = []
        add_calls: list[tuple[str, str, str]] = []
        key = b"k" * 32
        encoded_key = base64.b64encode(key).decode("ascii")

        def fake_find(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            find_calls.append(command)
            return subprocess.CompletedProcess(command, 44, stdout=b"", stderr=b"missing")

        def fake_add(*, service: str, account: str, password: str) -> subprocess.CompletedProcess[bytes]:
            add_calls.append((service, account, password))
            return subprocess.CompletedProcess(["security"], 0, stdout=b"", stderr=b"")

        with patch("tools.multi_position_sourcing.portal_snapshot.subprocess.run", fake_find), patch(
            "tools.multi_position_sourcing.portal_snapshot.secrets.token_bytes",
            return_value=key,
        ), patch("tools.multi_position_sourcing.portal_snapshot.add_generic_password", fake_add):
            created = MacKeychainSessionKeyProvider(create_if_missing=True).get_key()

        self.assertEqual(created, key)
        self.assertEqual(len(find_calls), 1)
        self.assertEqual(len(add_calls), 1)
        self.assertEqual(add_calls[0], ("valuehire.session_state", "session_state_v2", encoded_key))
        self.assertNotIn(encoded_key, " ".join(find_calls[0]))

    def test_portal_credentials_load_from_keychain_and_redact_repr(self) -> None:
        def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
            account = command[command.index("-a") + 1]
            secret = "valueconnect" if account.endswith(":username") else "password-secret"
            return subprocess.CompletedProcess(command, 0, stdout=base64.b64encode(secret.encode("utf-8")), stderr=b"")

        with patch("tools.multi_position_sourcing.portal_recovery.subprocess.run", fake_run):
            credentials = MacKeychainPortalCredentialProvider().load("saramin")

        self.assertEqual(credentials.username, "valueconnect")
        self.assertEqual(credentials.password, "password-secret")
        self.assertNotIn("valueconnect", repr(credentials))
        self.assertNotIn("password-secret", repr(credentials))

    def test_portal_credentials_store_writes_keychain_values_via_stdin(self) -> None:
        calls: list[tuple[list[str], bytes]] = []

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            calls.append((command, kwargs.get("input", b"")))  # type: ignore[arg-type]
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        with patch("tools.multi_position_sourcing.portal_keychain.subprocess.run", fake_run):
            MacKeychainPortalCredentialProvider().store(
                "jobkorea",
                PortalCredentials(username="valueconnect", password="password-secret"),
            )

        flattened = " ".join(" ".join(command) for command, _input in calls)
        username_b64 = base64.b64encode(b"valueconnect").decode("ascii")
        password_b64 = base64.b64encode(b"password-secret").decode("ascii")
        self.assertEqual(len(calls), 2)
        self.assertIn("jobkorea:username", calls[0][0])
        self.assertIn("jobkorea:password", calls[1][0])
        self.assertEqual(calls[0][0][-1], "-w")
        self.assertEqual(calls[1][0][-1], "-w")
        self.assertEqual(calls[0][1], (username_b64 + "\n").encode("utf-8"))
        self.assertEqual(calls[1][1], (password_b64 + "\n").encode("utf-8"))
        self.assertNotIn(username_b64, flattened)
        self.assertNotIn(password_b64, flattened)
        self.assertNotIn(" password-secret ", flattened)
        self.assertNotIn(" valueconnect ", flattened)

    def test_supabase_snapshot_store_uses_rpc_base64_without_plaintext(self) -> None:
        requests: list[dict[str, object]] = []
        encrypted = b"VHSS1" + b"x" * 64

        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    [
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(encrypted).decode("ascii"),
                            "is_validated": True,
                            "kind": "current",
                            "captured_at": "2026-06-09T00:00:00+00:00",
                            "updated_at": "2026-06-09T00:00:00+00:00",
                        }
                    ]
                ).encode("utf-8")

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            self.assertEqual(timeout, 3)
            body = request.data.decode("utf-8")  # type: ignore[attr-defined]
            requests.append(
                {
                    "url": request.full_url,  # type: ignore[attr-defined]
                    "headers": dict(request.header_items()),  # type: ignore[attr-defined]
                    "body": body,
                }
            )
            return FakeResponse()

        store = SupabaseSessionSnapshotStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
                timeout_seconds=3,
            ),
            urlopen=fake_urlopen,
        )

        saved = store.save_validated_current(
            site="saramin",
            worker_id="worker-a",
            storage_state_enc=encrypted,
            captured_at="2026-06-09T00:00:00+00:00",
        )

        self.assertEqual(saved.storage_state_enc, encrypted)
        self.assertIn("/rest/v1/rpc/save_validated_session_snapshot", requests[0]["url"])
        self.assertIn("storage_state_b64_arg", requests[0]["body"])
        self.assertNotIn("plain-cookie-secret", requests[0]["body"])
        self.assertNotIn("storage_state_enc", requests[0]["body"])

    def test_supabase_snapshot_store_reads_current_and_lkg_candidates(self) -> None:
        requests: list[dict[str, object]] = []
        current = b"VHSS1" + b"c" * 64
        lkg = b"VHSS1" + b"l" * 64

        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    [
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(current).decode("ascii"),
                            "is_validated": True,
                            "kind": "current",
                            "captured_at": "2026-06-09T00:02:00+00:00",
                            "updated_at": "2026-06-09T00:02:00+00:00",
                        },
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(lkg).decode("ascii"),
                            "is_validated": True,
                            "kind": "last_known_good",
                            "captured_at": "2026-06-09T00:01:00+00:00",
                            "updated_at": "2026-06-09T00:02:00+00:00",
                        },
                    ]
                ).encode("utf-8")

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            requests.append({"url": request.full_url, "body": request.data.decode("utf-8")})  # type: ignore[attr-defined]
            return FakeResponse()

        store = SupabaseSessionSnapshotStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
            ),
            urlopen=fake_urlopen,
        )

        snapshots = store.validated_snapshots(site="saramin", worker_id="worker-a")

        self.assertEqual([snapshot.kind for snapshot in snapshots], ["current", "last_known_good"])
        self.assertEqual(snapshots[0].storage_state_enc, current)
        self.assertIn("/rest/v1/rpc/validated_session_snapshots", requests[0]["url"])
        self.assertIn("worker_id_arg", requests[0]["body"])
        self.assertNotIn("service-role-secret", requests[0]["body"])

    def test_supabase_snapshot_store_skips_unvalidated_or_wrong_kind_candidates(self) -> None:
        valid_lkg = b"VHSS1" + b"l" * 64
        unvalidated = b"VHSS1" + b"u" * 64
        wrong_kind = b"VHSS1" + b"k" * 64

        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    [
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(unvalidated).decode("ascii"),
                            "is_validated": False,
                            "kind": "current",
                            "captured_at": "2026-06-09T00:02:00+00:00",
                            "updated_at": "2026-06-09T00:02:00+00:00",
                        },
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(wrong_kind).decode("ascii"),
                            "is_validated": True,
                            "kind": "poison",
                            "captured_at": "2026-06-09T00:02:00+00:00",
                            "updated_at": "2026-06-09T00:02:00+00:00",
                        },
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(valid_lkg).decode("ascii"),
                            "is_validated": True,
                            "kind": "last_known_good",
                            "captured_at": "2026-06-09T00:01:00+00:00",
                            "updated_at": "2026-06-09T00:02:00+00:00",
                        },
                    ]
                ).encode("utf-8")

        store = SupabaseSessionSnapshotStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
            ),
            urlopen=lambda _request, *, timeout: FakeResponse(),
        )

        snapshots = store.validated_snapshots(site="saramin", worker_id="worker-a")

        self.assertEqual([snapshot.kind for snapshot in snapshots], ["last_known_good"])
        self.assertEqual(snapshots[0].storage_state_enc, valid_lkg)

    def test_supabase_snapshot_store_skips_truthy_validation_and_malformed_metadata_rows(self) -> None:
        truthy_string = b"VHSS1" + b"s" * 64
        truthy_int = b"VHSS1" + b"i" * 64
        missing_worker = b"VHSS1" + b"w" * 64
        missing_timestamp = b"VHSS1" + b"t" * 64
        valid_lkg = b"VHSS1" + b"l" * 64

        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    [
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(truthy_string).decode("ascii"),
                            "is_validated": "true",
                            "kind": "current",
                            "captured_at": "2026-06-09T00:02:00+00:00",
                            "updated_at": "2026-06-09T00:02:00+00:00",
                        },
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(truthy_int).decode("ascii"),
                            "is_validated": 1,
                            "kind": "current",
                            "captured_at": "2026-06-09T00:02:00+00:00",
                            "updated_at": "2026-06-09T00:02:00+00:00",
                        },
                        {
                            "site": "saramin",
                            "worker_id": "",
                            "storage_state_b64": base64.b64encode(missing_worker).decode("ascii"),
                            "is_validated": True,
                            "kind": "current",
                            "captured_at": "2026-06-09T00:02:00+00:00",
                            "updated_at": "2026-06-09T00:02:00+00:00",
                        },
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(missing_timestamp).decode("ascii"),
                            "is_validated": True,
                            "kind": "current",
                            "captured_at": "",
                            "updated_at": "2026-06-09T00:02:00+00:00",
                        },
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(valid_lkg).decode("ascii"),
                            "is_validated": True,
                            "kind": "last_known_good",
                            "captured_at": "2026-06-09T00:01:00+00:00",
                            "updated_at": "2026-06-09T00:02:00+00:00",
                        },
                    ]
                ).encode("utf-8")

        store = SupabaseSessionSnapshotStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
            ),
            urlopen=lambda _request, *, timeout: FakeResponse(),
        )

        snapshots = store.validated_snapshots(site="saramin", worker_id="worker-a")

        self.assertEqual([snapshot.kind for snapshot in snapshots], ["last_known_good"])
        self.assertEqual(snapshots[0].storage_state_enc, valid_lkg)

    def test_supabase_snapshot_store_rejects_unvalidated_save_response(self) -> None:
        encrypted = b"VHSS1" + b"x" * 64

        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    [
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(encrypted).decode("ascii"),
                            "is_validated": False,
                            "kind": "current",
                            "captured_at": "2026-06-09T00:00:00+00:00",
                            "updated_at": "2026-06-09T00:00:00+00:00",
                        }
                    ]
                ).encode("utf-8")

        store = SupabaseSessionSnapshotStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
            ),
            urlopen=lambda _request, *, timeout: FakeResponse(),
        )

        with self.assertRaisesRegex(SupabaseSessionStoreError, "not validated"):
            store.save_validated_current(
                site="saramin",
                worker_id="worker-a",
                storage_state_enc=encrypted,
                captured_at="2026-06-09T00:00:00+00:00",
            )

    def test_supabase_snapshot_store_rejects_truthy_validated_save_response(self) -> None:
        encrypted = b"VHSS1" + b"x" * 64

        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    [
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "storage_state_b64": base64.b64encode(encrypted).decode("ascii"),
                            "is_validated": "true",
                            "kind": "current",
                            "captured_at": "2026-06-09T00:00:00+00:00",
                            "updated_at": "2026-06-09T00:00:00+00:00",
                        }
                    ]
                ).encode("utf-8")

        store = SupabaseSessionSnapshotStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
            ),
            urlopen=lambda _request, *, timeout: FakeResponse(),
        )

        with self.assertRaisesRegex(SupabaseSessionStoreError, "not validated"):
            store.save_validated_current(
                site="saramin",
                worker_id="worker-a",
                storage_state_enc=encrypted,
                captured_at="2026-06-09T00:00:00+00:00",
            )

    def test_snapshot_store_rejects_plaintext_payload_before_storage(self) -> None:
        store = InMemorySessionSnapshotStore()

        with self.assertRaisesRegex(SessionEncryptionError, "malformed"):
            store.save_validated_current(
                site="saramin",
                worker_id="worker-a",
                storage_state_enc=b'{"cookies":[{"value":"plain-cookie-secret"}]}',
                captured_at="2026-06-09T00:00:00+00:00",
            )

        self.assertIsNone(store.latest_validated(site="saramin", worker_id="worker-a"))

    def test_supabase_snapshot_store_rejects_plaintext_payload_before_rpc(self) -> None:
        requests: list[object] = []

        def fake_urlopen(request: object, *, timeout: int) -> object:
            requests.append((request, timeout))
            raise AssertionError("Supabase RPC should not be called for plaintext session payload")

        store = SupabaseSessionSnapshotStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
                timeout_seconds=3,
            ),
            urlopen=fake_urlopen,
        )

        with self.assertRaisesRegex(SessionEncryptionError, "malformed"):
            store.save_validated_current(
                site="jobkorea",
                worker_id="worker-a",
                storage_state_enc=b"plain-cookie-secret",
                captured_at="2026-06-09T00:00:00+00:00",
            )

        self.assertEqual(requests, [])

    def test_supabase_snapshot_store_reports_http_status_without_secret_body(self) -> None:
        def fake_urlopen(request: object, *, timeout: int) -> object:
            raise urllib.error.HTTPError(
                request.full_url,  # type: ignore[attr-defined]
                401,
                "Unauthorized service-role-secret",
                {},
                io.BytesIO(b"service-role-secret"),
            )

        store = SupabaseSessionSnapshotStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
                timeout_seconds=3,
            ),
            urlopen=fake_urlopen,
        )

        with self.assertRaises(SupabaseSessionStoreError) as caught:
            store.latest_validated(site="saramin", worker_id="worker-a")

        message = str(caught.exception)
        self.assertIn("failed with status 401", message)
        self.assertNotIn("service-role-secret", message)
        self.assertNotIn("supabase.example.test", message)

    def test_session_state_schema_enforces_encrypted_snapshot_envelope(self) -> None:
        schema = Path("docs/ai-search/session-state-supabase-schema-2026-06-09.sql").read_text(encoding="utf-8")

        self.assertIn("storage_state_enc bytea not null", schema)
        self.assertNotIn("storage_state json", schema)
        self.assertNotIn("storage_state jsonb", schema)
        self.assertNotIn("storage_state text not null", schema)
        self.assertIn("session_state_encrypted_envelope_check", schema)
        self.assertIn("session_state_validated_only_check", schema)
        self.assertIn("check (is_validated = true)", schema)
        self.assertIn("check (is_validated = true) not valid", schema)
        self.assertIn("substring(storage_state_enc from 1 for 5) = decode('5648535331', 'hex')", schema)
        self.assertIn("substring(storage_state_decoded from 1 for 5) <> decode('5648535331', 'hex')", schema)
        self.assertIn("unique (site, worker_id, kind)", schema)
        self.assertIn("alter table public.session_state enable row level security", schema)
        self.assertIn("alter table public.reauth_events enable row level security", schema)
        self.assertIn("revoke all on public.session_state from public, anon, authenticated", schema)
        self.assertIn("revoke all on public.reauth_events from public, anon, authenticated", schema)
        self.assertIn("grant select, insert on public.reauth_events to service_role", schema)
        self.assertIn("create policy service_role_session_state_all", schema)
        self.assertIn("create policy service_role_reauth_events_all", schema)
        self.assertIn("security definer", schema)
        self.assertIn("set search_path = public", schema)
        self.assertIn(
            "recovered_by in ('snapshot_reinject', 'auto_relogin', 'human', 'unrecovered')",
            schema,
        )
        self.assertIn("reauth_events_cause_allowed_check", schema)
        self.assertIn("'profile_corrupt'", schema)
        self.assertIn("'cookie_rotated'", schema)
        self.assertIn("'forced_logout'", schema)
        self.assertIn("'login_redirect'", schema)
        self.assertIn("'login_marker_missing'", schema)
        self.assertIn("'login_marker_lost'", schema)
        self.assertIn("cause ~ '^http_(401|403)$'", schema)
        # SOT invariant: LinkedIn RPS auto-logs in like the other portals, so the schema
        # must NOT carry a constraint forbidding linkedin_rps auto_relogin reauth rows.
        self.assertNotIn("reauth_events_no_linkedin_auto_relogin_check", schema)
        self.assertNotIn("site <> 'linkedin_rps' or recovered_by <> 'auto_relogin'", schema)
        self.assertIn("check (\n      cause in (", schema)
        self.assertIn(") not valid", schema)
        # SOT invariant: no constraint forbidding linkedin_rps auto_relogin
        self.assertNotIn(
            "check (site <> 'linkedin_rps' or recovered_by <> 'auto_relogin') not valid",
            schema,
        )
        self.assertIn(
            "revoke execute on function public.save_validated_session_snapshot(text, text, text, timestamptz)",
            schema,
        )
        self.assertIn(
            "grant execute on function public.save_validated_session_snapshot(text, text, text, timestamptz)",
            schema,
        )
        self.assertIn(
            "revoke execute on function public.latest_validated_session_snapshot(text, text)",
            schema,
        )
        self.assertIn(
            "grant execute on function public.latest_validated_session_snapshot(text, text)",
            schema,
        )
        self.assertIn("create or replace function public.validated_session_snapshots", schema)
        self.assertIn("limit 2", schema)
        self.assertIn(
            "revoke execute on function public.validated_session_snapshots(text, text)",
            schema,
        )
        self.assertIn(
            "grant execute on function public.validated_session_snapshots(text, text)",
            schema,
        )
        self.assertIn("revoke execute on function public.reauth_weekly_counts(timestamptz)", schema)
        self.assertIn("grant execute on function public.reauth_weekly_counts(timestamptz)", schema)
        self.assertIn("create or replace function public.reauth_weekly_counts", schema)
        self.assertIn("count(*)::bigint as count", schema)

    def test_live_check_supabase_config_requires_service_role_without_exposing_value(self) -> None:
        config = supabase_config_from_env(
            {
                "SUPABASE_URL": "https://supabase.example.test",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
            }
        )

        self.assertEqual(config.rest_url, "https://supabase.example.test/rest/v1")
        self.assertIn("service-role-secret", config.headers()["Authorization"])
        with self.assertRaisesRegex(RuntimeError, "SERVICE_ROLE_KEY"):
            supabase_config_from_env({"SUPABASE_URL": "https://supabase.example.test"})

    def test_supabase_access_check_reports_401_without_secret_values(self) -> None:
        def fake_urlopen(request: object, *, timeout: int) -> object:
            self.assertEqual(timeout, 10)
            self.assertIn("service-role-secret", dict(request.header_items())["Authorization"])  # type: ignore[attr-defined]
            raise urllib.error.HTTPError(
                request.full_url,  # type: ignore[attr-defined]
                401,
                "Unauthorized service-role-secret",
                {},
                io.BytesIO(b"service-role-secret"),
            )

        payload = supabase_access_check_payload(
            {
                "SUPABASE_URL": "https://supabase.example.test",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
            },
            urlopen=fake_urlopen,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["kind"], "supabase_access_check")
        self.assertFalse(payload["ready"])
        self.assertEqual({check["http_status"] for check in payload["checks"]}, {401})  # type: ignore[index]
        self.assertNotIn("service-role-secret", encoded)
        self.assertNotIn("supabase.example.test", encoded)

    def test_supabase_access_check_classifies_invalid_jwt_without_body_output(self) -> None:
        raw_body = b'{"message":"JWSError JWSInvalidSignature project-ref-secret"}'

        def fake_urlopen(request: object, *, timeout: int) -> object:
            raise urllib.error.HTTPError(
                request.full_url,  # type: ignore[attr-defined]
                401,
                "Unauthorized",
                {},
                io.BytesIO(raw_body),
            )

        payload = supabase_access_check_payload(
            {
                "SUPABASE_URL": "https://supabase.example.test",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
            },
            urlopen=fake_urlopen,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(
            {check["http_error_hint"] for check in payload["checks"]},  # type: ignore[index]
            {"invalid_jwt_signature_or_project_mismatch"},
        )
        self.assertNotIn("JWSError", encoded)
        self.assertNotIn("JWSInvalidSignature", encoded)
        self.assertNotIn("project-ref-secret", encoded)
        self.assertNotIn("service-role-secret", encoded)

    def test_supabase_access_check_passes_without_response_body_output(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return b'[{"id":"secret-row-id"}]'

        calls: list[str] = []

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            calls.append(request.full_url)  # type: ignore[attr-defined]
            return FakeResponse()

        payload = supabase_access_check_payload(
            {
                "SUPABASE_URL": "https://supabase.example.test",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
            },
            urlopen=fake_urlopen,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertTrue(payload["ready"])
        self.assertEqual(len(calls), 4)
        self.assertNotIn("secret-row-id", encoded)
        self.assertNotIn("service-role-secret", encoded)

    def test_supabase_access_check_reports_missing_schema_rpc_hint(self) -> None:
        def fake_urlopen(request: object, *, timeout: int) -> object:
            if "/rpc/reauth_weekly_counts" in request.full_url:  # type: ignore[attr-defined]
                raise urllib.error.HTTPError(
                    request.full_url,  # type: ignore[attr-defined]
                    404,
                    "Not Found",
                    {},
                    io.BytesIO(b'{"message":"Could not find function"}'),
                )

            class FakeResponse:
                status = 200

                def __enter__(self) -> "FakeResponse":
                    return self

                def __exit__(self, *_exc: object) -> None:
                    return None

                def read(self) -> bytes:
                    return b"[]"

            return FakeResponse()

        payload = supabase_access_check_payload(
            {
                "SUPABASE_URL": "https://supabase.example.test",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
            },
            urlopen=fake_urlopen,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["action_hint"], "apply_session_state_supabase_schema")
        self.assertEqual(
            {check["http_error_hint"] for check in payload["checks"] if check["status"] == "failed"},  # type: ignore[index]
            {"schema_or_rpc_missing"},
        )
        self.assertNotIn("service-role-secret", encoded)
        self.assertNotIn("Could not find function", encoded)

    def test_supabase_access_check_reports_safe_jwt_diagnostics(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return b"[]"

        def token_segment(payload: dict[str, object]) -> str:
            encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
            return encoded.rstrip("=")

        service_role_key = ".".join(
            [
                token_segment({"alg": "HS256"}),
                token_segment({"role": "service_role", "exp": 4102444800, "ref": "projectref"}),
                "signature-secret",
            ]
        )
        payload = supabase_access_check_payload(
            {
                "SUPABASE_URL": "https://projectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": service_role_key,
            },
            urlopen=lambda *_args, **_kwargs: FakeResponse(),
        )
        encoded = json.dumps(payload, ensure_ascii=False)
        diagnostics = payload["key_diagnostics"]

        self.assertEqual(diagnostics["format"], "jwt")  # type: ignore[index]
        self.assertEqual(diagnostics["role_claim"], "service_role")  # type: ignore[index]
        self.assertFalse(diagnostics["expired"])  # type: ignore[index]
        self.assertEqual(diagnostics["url_key_ref_match"], "passed")  # type: ignore[index]
        self.assertEqual(diagnostics["project_ref_claim_source"], "ref")  # type: ignore[index]
        self.assertEqual(payload["action_hint"], "ready")
        self.assertNotIn(service_role_key, encoded)
        self.assertNotIn("projectref.supabase.co", encoded)
        self.assertNotIn("signature-secret", encoded)

    def test_supabase_access_check_reports_project_ref_mismatch_safely(self) -> None:
        def token_segment(payload: dict[str, object]) -> str:
            encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
            return encoded.rstrip("=")

        service_role_key = ".".join(
            [
                token_segment({"alg": "HS256"}),
                token_segment({"role": "service_role", "exp": 4102444800, "ref": "otherproject"}),
                "signature-secret",
            ]
        )

        def fake_urlopen(request: object, *, timeout: int) -> object:
            raise urllib.error.HTTPError(
                request.full_url,  # type: ignore[attr-defined]
                401,
                "Unauthorized",
                {},
                io.BytesIO(b'{"message":"Invalid API key"}'),
            )

        payload = supabase_access_check_payload(
            {
                "SUPABASE_URL": "https://projectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": service_role_key,
            },
            urlopen=fake_urlopen,
        )
        encoded = json.dumps(payload, ensure_ascii=False)
        diagnostics = payload["key_diagnostics"]

        self.assertFalse(payload["ready"])
        self.assertEqual(diagnostics["url_key_ref_match"], "failed")  # type: ignore[index]
        self.assertEqual(diagnostics["project_ref_claim_source"], "ref")  # type: ignore[index]
        self.assertEqual(payload["action_hint"], "supabase_url_and_service_role_key_project_mismatch")
        self.assertNotIn(service_role_key, encoded)
        self.assertNotIn("projectref.supabase.co", encoded)
        self.assertNotIn("otherproject", encoded)

    def test_supabase_access_check_extracts_project_ref_from_issuer_safely(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return b"[]"

        def token_segment(payload: dict[str, object]) -> str:
            encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
            return encoded.rstrip("=")

        service_role_key = ".".join(
            [
                token_segment({"alg": "HS256"}),
                token_segment(
                    {
                        "role": "service_role",
                        "exp": 4102444800,
                        "iss": "https://projectref.supabase.co/auth/v1",
                    }
                ),
                "signature-secret",
            ]
        )
        payload = supabase_access_check_payload(
            {
                "SUPABASE_URL": "https://projectref.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": service_role_key,
            },
            urlopen=lambda *_args, **_kwargs: FakeResponse(),
        )
        encoded = json.dumps(payload, ensure_ascii=False)
        diagnostics = payload["key_diagnostics"]

        self.assertTrue(payload["ready"])
        self.assertEqual(diagnostics["project_ref_claim_source"], "iss")  # type: ignore[index]
        self.assertEqual(diagnostics["url_key_ref_match"], "passed")  # type: ignore[index]
        self.assertNotIn(service_role_key, encoded)
        self.assertNotIn("projectref.supabase.co", encoded)
        self.assertNotIn("signature-secret", encoded)

    def test_supabase_access_check_cli_exits_nonzero_when_not_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "supabase_access.json"
            with patch(
                "sys.argv",
                [
                    "portal_live_check",
                    "--env-file",
                    str(Path(tmp) / "missing.env"),
                    "supabase-access-check",
                    "--output",
                    str(output),
                ],
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.supabase_access_check_payload",
                return_value={
                    "kind": "supabase_access_check",
                    "ready": False,
                    "key_diagnostics": {"configured": True},
                    "action_hint": "configured_service_role_key_rejected_by_supabase",
                    "checks": [],
                },
            ):
                with self.assertRaises(SystemExit) as raised:
                    portal_live_check_main()

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["action_hint"], "configured_service_role_key_rejected_by_supabase")

    def test_live_readiness_cli_exits_nonzero_when_not_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "readiness.json"
            with patch(
                "sys.argv",
                [
                    "portal_live_check",
                    "--env-file",
                    str(Path(tmp) / "missing.env"),
                    "readiness",
                    "--output",
                    str(output),
                ],
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.live_readiness_payload",
                return_value={
                    "kind": "portal_live_readiness",
                    "ready": False,
                    "checks": [
                        {
                            "name": "supabase_access",
                            "status": "failed",
                            "action_hint": "configured_service_role_key_rejected_by_supabase",
                        }
                    ],
                },
            ):
                with self.assertRaises(SystemExit) as raised:
                    portal_live_check_main()

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["checks"][0]["action_hint"], "configured_service_role_key_rejected_by_supabase")

    def test_live_check_profile_deletion_requires_exact_confirmed_path(self) -> None:
        with TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "artifacts" / "portal_profiles" / "saramin" / "worker-a"
            profile_dir.mkdir(parents=True)
            (profile_dir / "marker").write_text("profile", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                delete_profile_dir_if_confirmed(
                    profile_dir,
                    enabled=True,
                    confirm=str(profile_dir.parent),
                )
            self.assertTrue(profile_dir.exists())

            deleted = delete_profile_dir_if_confirmed(
                profile_dir,
                enabled=True,
                confirm=str(profile_dir),
            )
            self.assertFalse(profile_dir.exists())

        self.assertTrue(deleted)

    def test_live_check_profile_deletion_requires_real_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "not-a-profile-dir"
            file_path.write_text("profile", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "real profile directory"):
                delete_profile_dir_if_confirmed(
                    file_path,
                    enabled=True,
                    confirm=str(file_path),
                )
            self.assertTrue(file_path.exists())

            target_dir = root / "target-profile"
            target_dir.mkdir()
            (target_dir / "marker").write_text("profile", encoding="utf-8")
            symlink_path = root / "symlink-profile"
            symlink_path.symlink_to(target_dir, target_is_directory=True)

            with self.assertRaisesRegex(RuntimeError, "real profile directory"):
                delete_profile_dir_if_confirmed(
                    symlink_path,
                    enabled=True,
                    confirm=str(symlink_path),
                )
            self.assertTrue(symlink_path.is_symlink())
            self.assertTrue(target_dir.exists())

    def test_live_check_profile_deletion_returns_false_when_profile_is_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / "portal_profiles" / "jobkorea" / "worker-a"

            deleted = delete_profile_dir_if_confirmed(
                profile_dir,
                enabled=True,
                confirm=str(profile_dir),
            )

        self.assertFalse(deleted)

    def test_live_check_profile_deletion_refuses_locked_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(channel="jobkorea", worker_id="worker-a", profile_root=tmp)
            config.profile_dir.mkdir(parents=True)
            (config.profile_dir / "marker").write_text("profile", encoding="utf-8")

            lock = ProfileLock(config)
            lock.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "profile is locked"):
                    delete_profile_dir_if_confirmed(
                        config.profile_dir,
                        enabled=True,
                        confirm=str(config.profile_dir),
                    )
                self.assertTrue(config.profile_dir.exists())
            finally:
                lock.release()

            deleted = delete_profile_dir_if_confirmed(
                config.profile_dir,
                enabled=True,
                confirm=str(config.profile_dir),
            )
            self.assertFalse(config.profile_dir.exists())

        self.assertTrue(deleted)

    def test_live_check_result_payload_excludes_recovery_objects_and_secret_state(self) -> None:
        attempt = PortalSearchAttempt(
            channel="saramin",
            worker_id="worker-a",
            keyword="backend",
            status="searched",
            reason="searched on persistent profile",
            url="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
        )
        payload = safe_result_payload(
            GuardedSearchResult(
                site="saramin",
                worker_id="worker-a",
                keyword="backend",
                status="searched",
                reason="searched on persistent profile",
                attempt=attempt,
                snapshot_captured=True,
                snapshot_kind="current",
            )
        )

        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["snapshot_kind"], "current")
        self.assertEqual(payload["attempt_status"], "searched")
        self.assertEqual(payload["attempt_reason"], "searched on persistent profile")
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("cookie", encoded.lower())
        self.assertNotIn("password", encoded.lower())

    def test_live_check_payload_urls_strip_auth_query_and_fragment(self) -> None:
        raw_url = "https://user:pass@www.jobkorea.co.kr:443/Corp/Person/Find?cookie=session-secret#token-secret"
        self.assertEqual(
            safe_artifact_url(raw_url),
            "https://www.jobkorea.co.kr:443/Corp/Person/Find",
        )

        attempt = PortalSearchAttempt(
            channel="jobkorea",
            worker_id="worker-a",
            keyword="backend",
            status="not_ready",
            reason="reauth required before search",
            url=raw_url,
            reauth_cause="login_redirect",
        )
        result_payload = safe_result_payload(
            GuardedSearchResult(
                site="jobkorea",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required before search",
                attempt=attempt,
            )
        )
        attempt_payload = safe_attempt_payload(attempt)
        snapshot_payload = safe_snapshot_payload(
            None,
            site="jobkorea",
            worker_id="worker-a",
            ready=False,
            url=raw_url,
        )
        encoded = json.dumps(
            {
                "result": result_payload,
                "attempt": attempt_payload,
                "snapshot": snapshot_payload,
            },
            ensure_ascii=False,
        )

        self.assertEqual(result_payload["url"], "https://www.jobkorea.co.kr:443/Corp/Person/Find")
        self.assertEqual(attempt_payload["url"], "https://www.jobkorea.co.kr:443/Corp/Person/Find")
        self.assertEqual(snapshot_payload["url"], "https://www.jobkorea.co.kr:443/Corp/Person/Find")
        self.assertNotIn("session-secret", encoded)
        self.assertNotIn("token-secret", encoded)
        self.assertNotIn("user:pass", encoded)
        self.assertNotIn("cookie=", encoded.lower())

    def test_live_check_result_payload_preserves_attempt_when_snapshot_capture_fails(self) -> None:
        attempt = PortalSearchAttempt(
            channel="jobkorea",
            worker_id="default",
            keyword="backend",
            status="searched",
            reason="searched on persistent profile",
            url="https://www.jobkorea.co.kr/Corp/Person/Find",
        )
        payload = safe_result_payload(
            GuardedSearchResult(
                site="jobkorea",
                worker_id="default",
                keyword="backend",
                status="error",
                reason="snapshot capture failed: SupabaseSessionStoreError",
                attempt=attempt,
            )
        )

        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["attempt_status"], "searched")
        self.assertEqual(payload["attempt_reason"], "searched on persistent profile")
        self.assertEqual(payload["reason"], "snapshot capture failed: SupabaseSessionStoreError")
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("cookie", encoded.lower())
        self.assertNotIn("password", encoded.lower())

    def test_live_check_snapshot_payload_excludes_encrypted_session_bytes(self) -> None:
        snapshot = EncryptedSessionSnapshot(
            site="jobkorea",
            worker_id="worker-a",
            storage_state_enc=b"VHSS1encrypted-cookie-secret",
            is_validated=True,
            kind="current",
            captured_at="2026-06-09T00:00:00+00:00",
            updated_at="2026-06-09T00:00:00+00:00",
        )

        payload = safe_snapshot_payload(
            snapshot,
            site="jobkorea",
            worker_id="worker-a",
            ready=True,
            url="https://www.jobkorea.co.kr/Corp/Person/Find",
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["status"], "captured")
        self.assertTrue(payload["snapshot_captured"])
        self.assertEqual(payload["snapshot_kind"], "current")
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("encrypted-cookie-secret", encoded)
        self.assertNotIn("VHSS1", encoded)

    def test_live_check_snapshot_metadata_reports_envelope_without_encrypted_bytes(self) -> None:
        snapshot = EncryptedSessionSnapshot(
            site="saramin",
            worker_id="worker-a",
            storage_state_enc=b"VHSS1encrypted-cookie-secret",
            is_validated=True,
            kind="current",
            captured_at="2026-06-09T00:00:00+00:00",
            updated_at="2026-06-09T00:00:00+00:00",
        )

        payload = safe_snapshot_metadata_payload(snapshot, site="saramin", worker_id="worker-a")
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["kind"], "session_snapshot_metadata")
        self.assertEqual(payload["status"], "present")
        self.assertEqual(payload["encrypted_envelope"], "VHSS1")
        self.assertEqual(payload["encrypted_bytes"], len(snapshot.storage_state_enc))
        self.assertNotIn("encrypted-cookie-secret", encoded)
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("password", encoded.lower())

    def test_live_check_snapshot_metadata_handles_supabase_read_failure_safely(self) -> None:
        class FailingSnapshotStore:
            def latest_validated(self, **_kwargs: object) -> object:
                raise RuntimeError("unauthorized service-role-secret")

        payload = snapshot_metadata_payload(
            channel="saramin",
            worker_id="default",
            store=FailingSnapshotStore(),
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["kind"], "session_snapshot_metadata")
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertFalse(payload["snapshot_present"])
        self.assertNotIn("service-role-secret", encoded)
        self.assertNotIn("storage_state", encoded)

    def test_live_check_weekly_counts_handles_supabase_read_failure_safely(self) -> None:
        class FailingEventStore:
            def weekly_counts(self, **_kwargs: object) -> object:
                raise RuntimeError("unauthorized service-role-secret")

        payload = weekly_reauth_counts_payload(
            week_start="2026-06-09T00:00:00+00:00",
            store=FailingEventStore(),
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["kind"], "reauth_weekly_counts")
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertEqual(payload["rows"], [])
        self.assertNotIn("service-role-secret", encoded)
        self.assertNotIn("storage_state", encoded)

    def test_live_check_restart_smoke_payload_requires_two_clean_worker_lifecycles(self) -> None:
        first = {
            "site": "saramin",
            "worker_id": "worker-a",
            "keyword": "backend",
            "status": "searched",
            "reauth_cause": "",
            "retried_after_recovery": False,
            "profile_deleted_before_start": False,
        }
        second = {
            "site": "saramin",
            "worker_id": "worker-a",
            "keyword": "backend",
            "status": "searched",
            "reauth_cause": "",
            "retried_after_recovery": False,
            "profile_deleted_before_start": False,
        }
        payload = safe_restart_smoke_payload(
            site="saramin",
            worker_id="worker-a",
            keyword="backend",
            first=first,
            second=second,
        )
        failed_payload = safe_restart_smoke_payload(
            site="saramin",
            worker_id="worker-a",
            keyword="backend",
            first=first,
            second={**second, "reauth_cause": "login_redirect"},
        )

        self.assertEqual(payload["kind"], "portal_restart_search_smoke")
        self.assertIsInstance(payload["generated_at"], str)
        self.assertEqual(payload["mode"], "guarded")
        self.assertEqual(payload["snapshot_capture_policy"], "required")
        self.assertEqual(payload["worker_restarts"], 2)
        self.assertTrue(payload["passed"])
        self.assertFalse(failed_payload["passed"])

    def test_restart_smoke_proof_status_payload_accepts_complete_guarded_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                lifecycle = {
                    "site": site,
                    "worker_id": "default",
                    "keyword": "backend",
                    "status": "searched",
                    "mode": "guarded",
                    "snapshot_capture_required": True,
                    "snapshot_capture_policy": "required",
                    "snapshot_captured": True,
                    "reauth_cause": "",
                    "retried_after_recovery": False,
                    "profile_deleted_before_start": False,
                }
                (root / f"portal_restart_smoke_{site}.json").write_text(
                    json.dumps(
                        safe_restart_smoke_payload(
                            site=site,  # type: ignore[arg-type]
                            worker_id="default",
                            keyword="backend",
                            first=lifecycle,
                            second=lifecycle,
                        )
                    ),
                    encoding="utf-8",
                )

            payload = restart_smoke_proof_status_payload(root)

        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["missing_sites"], [])
        self.assertEqual(payload["incomplete_sites"], [])
        self.assertEqual(payload["schema_issues"], {})
        self.assertEqual(payload["proof_issues"], {})
        self.assertEqual(payload["stale_artifacts"], {})

    def test_restart_smoke_proof_separates_schema_from_unmet_proof_conditions(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            full_guarded = {
                "site": "saramin",
                "worker_id": "default",
                "keyword": "backend",
                "status": "searched",
                "mode": "guarded",
                "snapshot_capture_required": True,
                "snapshot_capture_policy": "required",
                "snapshot_captured": True,
                "reauth_cause": "",
                "retried_after_recovery": False,
                "profile_deleted_before_start": False,
            }
            blocked = {
                **full_guarded,
                "site": "jobkorea",
                "status": "not_ready",
                "reason": "reauth required before search",
                "snapshot_captured": False,
            }
            for site in ("saramin", "linkedin_rps"):
                lifecycle = {**full_guarded, "site": site}
                (root / f"portal_restart_smoke_{site}.json").write_text(
                    json.dumps(
                        safe_restart_smoke_payload(
                            site=site,  # type: ignore[arg-type]
                            worker_id="default",
                            keyword="backend",
                            first=lifecycle,
                            second=lifecycle,
                        )
                    ),
                    encoding="utf-8",
                )
            (root / "portal_restart_smoke_jobkorea.json").write_text(
                json.dumps(
                    safe_restart_smoke_payload(
                        site="jobkorea",
                        worker_id="default",
                        keyword="backend",
                        first=blocked,
                        second=blocked,
                    )
                ),
                encoding="utf-8",
            )

            payload = restart_smoke_proof_status_payload(root)

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["schema_issues"], {})
        self.assertIn("jobkorea", payload["proof_issues"])
        self.assertIn("passed", payload["proof_issues"]["jobkorea"])  # type: ignore[index]
        self.assertIn("first_full_guarded", payload["proof_issues"]["jobkorea"])  # type: ignore[index]

    def test_restart_smoke_proof_rejects_stale_complete_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                lifecycle = {
                    "site": site,
                    "worker_id": "default",
                    "keyword": "backend",
                    "status": "searched",
                    "mode": "guarded",
                    "snapshot_capture_required": True,
                    "snapshot_capture_policy": "required",
                    "snapshot_captured": True,
                    "reauth_cause": "",
                    "retried_after_recovery": False,
                    "profile_deleted_before_start": False,
                }
                payload = safe_restart_smoke_payload(
                    site=site,  # type: ignore[arg-type]
                    worker_id="default",
                    keyword="backend",
                    first=lifecycle,
                    second=lifecycle,
                )
                payload["generated_at"] = "2026-06-07T00:00:00+00:00"
                (root / f"portal_restart_smoke_{site}.json").write_text(
                    json.dumps(payload),
                    encoding="utf-8",
                )

            with patch(
                "tools.multi_position_sourcing.portal_live_check.utc_now_live_check",
                return_value="2026-06-09T12:00:00+00:00",
            ):
                proof = restart_smoke_proof_status_payload(root)

        self.assertFalse(proof["ready"])
        self.assertEqual(proof["status"], "failed")
        self.assertEqual(proof["action_hint"], "restart_smoke_stale")
        self.assertEqual(proof["schema_issues"], {})
        self.assertEqual(proof["proof_issues"], {})
        self.assertEqual(set(proof["stale_artifacts"]), {"saramin", "jobkorea", "linkedin_rps"})

    def test_restart_smoke_proof_cli_writes_ready_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                lifecycle = {
                    "site": site,
                    "worker_id": "default",
                    "keyword": "backend",
                    "status": "searched",
                    "mode": "guarded",
                    "snapshot_capture_required": True,
                    "snapshot_capture_policy": "required",
                    "snapshot_captured": True,
                    "reauth_cause": "",
                    "retried_after_recovery": False,
                    "profile_deleted_before_start": False,
                }
                (root / f"portal_restart_smoke_{site}.json").write_text(
                    json.dumps(
                        safe_restart_smoke_payload(
                            site=site,  # type: ignore[arg-type]
                            worker_id="default",
                            keyword="backend",
                            first=lifecycle,
                            second=lifecycle,
                        )
                    ),
                    encoding="utf-8",
                )
            output = root / "restart_proof.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.multi_position_sourcing.portal_live_check",
                    "restart-smoke-proof",
                    "--artifact-root",
                    str(root),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "ready")
        self.assertNotIn("storage_state", json.dumps(payload, ensure_ascii=False))

    def test_restart_smoke_proof_cli_exits_nonzero_when_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "restart_proof.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.multi_position_sourcing.portal_live_check",
                    "restart-smoke-proof",
                    "--artifact-root",
                    str(root),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["status"], "missing")
        self.assertEqual(payload["action_hint"], "restart_smoke_missing")

    def test_live_check_restart_smoke_timeout_payload_is_failed_and_safe(self) -> None:
        payload = safe_restart_smoke_timeout_payload(
            site="jobkorea",
            worker_id="default",
            keyword="backend",
            timeout_seconds=30,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["kind"], "portal_restart_search_smoke")
        self.assertIsInstance(payload["generated_at"], str)
        self.assertEqual(payload["mode"], "guarded")
        self.assertEqual(payload["snapshot_capture_policy"], "required")
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["status"], "timeout")
        self.assertEqual(payload["reason"], "restart_smoke_timeout")
        self.assertEqual(payload["timeout_seconds"], 30)
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("cookie", encoded)
        self.assertNotIn("password", encoded)

    def test_dod_refresh_status_artifacts_writes_non_destructive_status_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_complete_preflight_artifact(root)
            discord_alert = root / "portal_discord_alert_test_latest.json"
            discord_alert.write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "delivered": True,
                        "reauth_event_recorded": True,
                        "event": complete_linkedin_discord_event(),
                    }
                ),
                encoding="utf-8",
            )
            original_discord_alert = discord_alert.read_text(encoding="utf-8")

            def fake_snapshot_metadata(*, channel: str, worker_id: str) -> dict[str, object]:
                return {
                    "kind": "session_snapshot_metadata",
                    "site": channel,
                    "worker_id": worker_id,
                    "snapshot_present": True,
                    "status": "present",
                    "snapshot_kind": "current",
                    "is_validated": True,
                    "encrypted_envelope": "VHSS1",
                    "encrypted_bytes": 96,
                }

            with patch(
                "tools.multi_position_sourcing.portal_live_check.live_readiness_payload",
                return_value={"kind": "portal_live_readiness", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.supabase_access_check_payload",
                return_value={"kind": "supabase_access_check", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.snapshot_metadata_payload",
                side_effect=fake_snapshot_metadata,
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.weekly_reauth_counts_payload",
                return_value={
                    "kind": "reauth_weekly_counts",
                    "status": "present",
                    "week_start": "2026-06-08",
                    "total_events": 0,
                    "rows": [],
                },
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.reauth_weekly_trend_payload",
                return_value={
                    "kind": "reauth_weekly_trend",
                    "status": "present",
                    "latest_week_start": "2026-06-08",
                    "weeks_observed": 4,
                    "latest_total_events": 0,
                    "weeks": [],
                },
            ):
                payload = refresh_dod_status_artifacts(
                    artifact_root=root,
                    worker_id="worker-a",
                    week_start="2026-06-08",
                )

            artifact_names = {item["name"] for item in payload["artifacts"]}  # type: ignore[index]
            action_by_name = {item["action"]: item for item in payload["action_items"]}  # type: ignore[index]
            blockers_by_id = {item["id"]: item["actions"] for item in payload["dod_blockers"]}  # type: ignore[index]
            self.assertFalse(payload["ready"])
            self.assertTrue(any(reason.get("name") == "restart_smoke_proof" for reason in payload["blocking_reasons"]))  # type: ignore[index]
            self.assertEqual(action_by_name["run_guarded_restart_smoke_all_sites"]["area"], "restart_smoke")
            self.assertEqual(
                action_by_name["run_guarded_restart_smoke_all_sites"]["blocks_dod"],
                ["dod_1_restart_search_all_sites"],
            )
            self.assertTrue(
                any(
                    "restart-smoke --channel saramin" in command
                    for command in action_by_name["run_guarded_restart_smoke_all_sites"]["commands"]
                )
            )
            self.assertTrue(
                any(
                    "restart-smoke-proof" in command
                    for command in action_by_name["run_guarded_restart_smoke_all_sites"]["commands"]
                )
            )
            self.assertEqual(action_by_name["run_profile_recovery_smoke_saramin_jobkorea"]["area"], "profile_recovery")
            self.assertEqual(
                action_by_name["run_profile_recovery_smoke_saramin_jobkorea"]["blocks_dod"],
                ["dod_2_profile_corruption_snapshot_recovery"],
            )
            self.assertTrue(
                any(
                    "profile-recovery-smoke --channel saramin" in command
                    for command in action_by_name["run_profile_recovery_smoke_saramin_jobkorea"]["commands"]
                )
            )
            self.assertTrue(
                any(
                    "profile-recovery-proof" in command
                    for command in action_by_name["run_profile_recovery_smoke_saramin_jobkorea"]["commands"]
                )
            )
            self.assertIn("run_guarded_restart_smoke_all_sites", blockers_by_id["dod_1_restart_search_all_sites"])
            self.assertIn(
                "run_profile_recovery_smoke_saramin_jobkorea",
                blockers_by_id["dod_2_profile_corruption_snapshot_recovery"],
            )
            self.assertEqual(
                artifact_names,
                {
                    "readiness",
                    "supabase_access",
                    "supabase_schema_proof",
                    "pacing_policy_proof",
                    "artifact_profile_precheck",
                    "portal_session_preflight_status",
                    "restart_smoke_proof",
                    "discord_alert_precheck",
                    "snapshot_metadata_saramin",
                    "snapshot_metadata_jobkorea",
                    "snapshot_metadata_linkedin_rps",
                    "profile_recovery_proof",
                    "reauth_weekly_counts",
                    "reauth_weekly_trend",
                },
            )
            self.assertTrue((root / "portal_live_readiness_latest.json").exists())
            self.assertTrue((root / "portal_supabase_access_latest.json").exists())
            self.assertTrue((root / "portal_pacing_policy_proof_latest.json").exists())
            self.assertTrue((root / "portal_artifact_profile_precheck_latest.json").exists())
            self.assertTrue((root / "portal_session_preflight_status_latest.json").exists())
            self.assertTrue((root / "portal_restart_smoke_proof_status_latest.json").exists())
            self.assertTrue((root / "portal_snapshot_metadata_saramin.json").exists())
            self.assertTrue((root / "portal_snapshot_metadata_jobkorea.json").exists())
            self.assertTrue((root / "portal_snapshot_metadata_linkedin_rps.json").exists())
            self.assertTrue((root / "portal_profile_recovery_proof_status_latest.json").exists())
            self.assertTrue((root / "portal_reauth_weekly_counts_latest.json").exists())
            self.assertTrue((root / "portal_reauth_weekly_trend_latest.json").exists())
            self.assertFalse((root / "portal_profile_recovery_saramin.json").exists())
            self.assertFalse((root / "portal_profile_recovery_jobkorea.json").exists())
            self.assertFalse((root / "portal_profile_recovery_linkedin_rps.json").exists())
            self.assertEqual(discord_alert.read_text(encoding="utf-8"), original_discord_alert)
            self.assertIn("discord-alert-test", payload["skipped_live_artifacts"])  # type: ignore[index]

    def test_dod_refresh_status_artifacts_reports_profile_artifact_action(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_complete_preflight_artifact(root)
            profile_dir = root / "portal_profiles" / "jobkorea" / "default"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".profile.lock").write_text("", encoding="utf-8")

            def fake_snapshot_metadata(*, channel: str, worker_id: str) -> dict[str, object]:
                return {
                    "kind": "session_snapshot_metadata",
                    "site": channel,
                    "worker_id": worker_id,
                    "snapshot_present": True,
                    "status": "present",
                    "snapshot_kind": "current",
                    "is_validated": True,
                    "encrypted_envelope": "VHSS1",
                    "encrypted_bytes": 96,
                }

            with patch(
                "tools.multi_position_sourcing.portal_live_check.live_readiness_payload",
                return_value={"kind": "portal_live_readiness", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.supabase_access_check_payload",
                return_value={"kind": "supabase_access_check", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.snapshot_metadata_payload",
                side_effect=fake_snapshot_metadata,
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.weekly_reauth_counts_payload",
                return_value={"kind": "reauth_weekly_counts", "status": "present", "rows": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.reauth_weekly_trend_payload",
                return_value={"kind": "reauth_weekly_trend", "status": "present", "weeks": []},
            ):
                payload = refresh_dod_status_artifacts(artifact_root=root)

        encoded = json.dumps(payload, ensure_ascii=False)
        reasons = payload["blocking_reasons"]  # type: ignore[assignment]
        action_by_name = {item["action"]: item for item in payload["action_items"]}  # type: ignore[index]
        blockers_by_id = {item["id"]: item["actions"] for item in payload["dod_blockers"]}  # type: ignore[index]
        profile_reason = next(
            reason for reason in reasons if reason.get("name") == "artifact_profile_precheck"
        )

        self.assertEqual(profile_reason["status"], "unsafe")
        self.assertIn("portal_profiles", str(profile_reason["profile_artifacts"]))
        self.assertIn("remove_persistent_profiles_from_artifacts", action_by_name)
        self.assertEqual(
            action_by_name["remove_persistent_profiles_from_artifacts"]["blocks_dod"],
            ["dod_6_no_plaintext_session_output"],
        )
        profile_cleanup_commands = action_by_name["remove_persistent_profiles_from_artifacts"]["commands"]
        self.assertIn(
            shlex.join(
                [
                    "find",
                    str(root),
                    "-maxdepth",
                    "4",
                    "(",
                    "-type",
                    "d",
                    "-name",
                    "portal_profiles",
                    "-o",
                    "-type",
                    "f",
                    "-name",
                    ".profile.lock",
                    ")",
                    "-print",
                ]
            ),
            profile_cleanup_commands,
        )
        self.assertTrue(
            any(
                "cleanup-artifact-profiles" in command
                for command in profile_cleanup_commands
            )
        )
        self.assertIn(
            shlex.join(
                [
                    "python3",
                    "-m",
                    "tools.multi_position_sourcing.portal_live_check",
                    "cleanup-artifact-profiles",
                    "--artifact-root",
                    str(root),
                    "--confirm-delete-artifact-profiles",
                    str(root / "portal_profiles"),
                    "--output",
                    str(root / "portal_artifact_profile_cleanup_latest.json"),
                ]
            ),
            profile_cleanup_commands,
        )
        self.assertIn(
            shlex.join(
                [
                    "python3",
                    "-m",
                    "tools.multi_position_sourcing.portal_dod_audit",
                    "--latest-defaults",
                    "--artifact-root",
                    str(root),
                ]
            ),
            profile_cleanup_commands,
        )
        self.assertIn(
            "remove_persistent_profiles_from_artifacts",
            blockers_by_id["dod_6_no_plaintext_session_output"],
        )
        self.assertNotIn("storage_state", encoded)

    def test_artifact_profile_precheck_payload_includes_exact_cleanup_argv(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_dir = root / "portal_profiles" / "saramin" / "default"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".profile.lock").write_text("", encoding="utf-8")

            payload = artifact_profile_precheck_payload(root)

        self.assertEqual(payload["status"], "unsafe")
        self.assertEqual(payload["cleanup_confirmation"], str(root / "portal_profiles"))
        self.assertEqual(
            payload["cleanup_command_argv"],
            [
                "python3",
                "-m",
                "tools.multi_position_sourcing.portal_live_check",
                "cleanup-artifact-profiles",
                "--artifact-root",
                str(root),
                "--confirm-delete-artifact-profiles",
                str(root / "portal_profiles"),
                "--output",
                str(root / "portal_artifact_profile_cleanup_latest.json"),
            ],
        )

    def test_artifact_profile_precheck_cli_reports_unsafe_without_deleting(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_dir = root / "portal_profiles" / "saramin" / "default"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".profile.lock").write_text("", encoding="utf-8")
            output = root / "precheck.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.multi_position_sourcing.portal_live_check",
                    "artifact-profile-precheck",
                    "--artifact-root",
                    str(root),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2, msg=result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "unsafe")
            self.assertTrue(profile_dir.exists())
            self.assertIn("portal_profiles", json.dumps(payload, ensure_ascii=False))

    def test_artifact_profile_cleanup_requires_exact_confirm(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_dir = root / "portal_profiles" / "jobkorea" / "default"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".profile.lock").write_text("", encoding="utf-8")

            payload = cleanup_artifact_profiles_payload(
                artifact_root=root,
                confirm_delete_artifact_profiles="",
            )

            self.assertEqual(payload["status"], "not_confirmed")
            self.assertFalse(payload["deleted"])
            self.assertTrue(profile_dir.exists())
            self.assertIn("confirm-delete-artifact-profiles", payload["reason"])  # type: ignore[index]

    def test_artifact_profile_cleanup_deletes_confirmed_artifact_profiles_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_dir = root / "portal_profiles" / "linkedin_rps" / "default"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".profile.lock").write_text("", encoding="utf-8")
            unrelated = root / "portal_live_readiness_latest.json"
            unrelated.write_text("{}", encoding="utf-8")

            payload = cleanup_artifact_profiles_payload(
                artifact_root=root,
                confirm_delete_artifact_profiles=str(root / "portal_profiles"),
            )

            self.assertEqual(payload["status"], "ready")
            self.assertTrue(payload["deleted"])
            self.assertFalse((root / "portal_profiles").exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(payload["profile_artifacts_after"], [])

    def test_artifact_profile_cleanup_refuses_locked_profiles(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_dir = root / "portal_profiles" / "saramin" / "default"
            profile_dir.mkdir(parents=True)
            lock_path = profile_dir / ".profile.lock"
            with lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    payload = cleanup_artifact_profiles_payload(
                        artifact_root=root,
                        confirm_delete_artifact_profiles=str(root / "portal_profiles"),
                    )
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

            self.assertEqual(payload["status"], "failed")
            self.assertFalse(payload["deleted"])
            self.assertTrue(profile_dir.exists())
            self.assertEqual(payload["reason"], "artifact profile cleanup refused because a profile is locked")

    def test_artifact_profile_cleanup_failure_reason_does_not_echo_secret_details(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_dir = root / "portal_profiles" / "jobkorea" / "default"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".profile.lock").write_text("", encoding="utf-8")

            with patch("tools.multi_position_sourcing.portal_live_check.shutil.rmtree", side_effect=RuntimeError(
                "cleanup failed for https://user:pass@www.jobkorea.co.kr?cookie=session-secret#token-secret"
            )):
                payload = cleanup_artifact_profiles_payload(
                    artifact_root=root,
                    confirm_delete_artifact_profiles=str(root / "portal_profiles"),
                )

            encoded = json.dumps(payload, ensure_ascii=False)

            self.assertEqual(payload["status"], "failed")
            self.assertEqual(
                payload["reason"],
                "RuntimeError: artifact profile cleanup failed without exposing details",
            )
            self.assertNotIn("session-secret", encoded)
            self.assertNotIn("token-secret", encoded)
            self.assertNotIn("user:pass", encoded)
            self.assertNotIn("cookie=", encoded.lower())

    def test_artifact_profile_cleanup_generic_failure_is_safe(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_dir = root / "portal_profiles" / "jobkorea" / "default"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".profile.lock").write_text("", encoding="utf-8")

            with patch(
                "tools.multi_position_sourcing.portal_live_check.shutil.rmtree",
                side_effect=OSError(
                    "cleanup failed for https://user:pass@www.jobkorea.co.kr?cookie=session-secret#token-secret"
                ),
            ):
                payload = cleanup_artifact_profiles_payload(
                    artifact_root=root,
                    confirm_delete_artifact_profiles=str(root / "portal_profiles"),
                )

            encoded = json.dumps(payload, ensure_ascii=False)

            self.assertEqual(payload["status"], "failed")
            self.assertEqual(
                payload["reason"],
                "OSError: artifact profile cleanup failed without exposing details",
            )
            self.assertNotIn("session-secret", encoded)
            self.assertNotIn("token-secret", encoded)
            self.assertNotIn("user:pass", encoded)
            self.assertNotIn("cookie=", encoded.lower())

    def test_artifact_profile_cleanup_refuses_symlink_artifact_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_root = root / "real_artifacts"
            profile_dir = target_root / "portal_profiles" / "jobkorea" / "default"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".profile.lock").write_text("", encoding="utf-8")
            symlink_root = root / "artifact_link"
            try:
                symlink_root.symlink_to(target_root, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            payload = cleanup_artifact_profiles_payload(
                artifact_root=symlink_root,
                confirm_delete_artifact_profiles=str(symlink_root / "portal_profiles"),
            )

            self.assertEqual(payload["status"], "failed")
            self.assertFalse(payload["deleted"])
            self.assertEqual(payload["reason"], "artifact profile cleanup refuses a symlink artifact root")
            self.assertTrue(profile_dir.exists())

    def test_artifact_profile_cleanup_refuses_symlink_profile_lock(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_dir = root / "portal_profiles" / "saramin" / "default"
            profile_dir.mkdir(parents=True)
            external_lock = root / "external.lock"
            external_lock.write_text("outside", encoding="utf-8")
            try:
                (profile_dir / ".profile.lock").symlink_to(external_lock)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            payload = cleanup_artifact_profiles_payload(
                artifact_root=root,
                confirm_delete_artifact_profiles=str(root / "portal_profiles"),
            )

            self.assertEqual(payload["status"], "failed")
            self.assertFalse(payload["deleted"])
            self.assertEqual(payload["reason"], "artifact profile cleanup refused because a profile lock is a symlink")
            self.assertTrue(profile_dir.exists())
            self.assertEqual(external_lock.read_text(encoding="utf-8"), "outside")

    def test_dod_refresh_status_artifacts_reports_stale_preflight_action(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_root = Path(tmp) / "profile root"
            (root / "portal_session_status_latest.json").write_text(
                json.dumps(
                    {
                        "kind": "portal_session_preflight",
                        "ready": False,
                        "portal_sessions": [
                            {
                                "channel": "jobkorea",
                                "ready": True,
                                "login": "existing_session_ok",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / "portal_discord_alert_test_latest.json").write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "delivered": True,
                        "reauth_event_recorded": True,
                        "event": complete_linkedin_discord_event(),
                    }
                ),
                encoding="utf-8",
            )

            def fake_snapshot_metadata(*, channel: str, worker_id: str) -> dict[str, object]:
                return {
                    "kind": "session_snapshot_metadata",
                    "site": channel,
                    "worker_id": worker_id,
                    "snapshot_present": True,
                    "status": "present",
                    "snapshot_kind": "current",
                    "is_validated": True,
                    "encrypted_envelope": "VHSS1",
                    "encrypted_bytes": 96,
                }

            with patch(
                "tools.multi_position_sourcing.portal_live_check.live_readiness_payload",
                return_value={"kind": "portal_live_readiness", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.supabase_access_check_payload",
                return_value={"kind": "supabase_access_check", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.snapshot_metadata_payload",
                side_effect=fake_snapshot_metadata,
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.weekly_reauth_counts_payload",
                return_value={
                    "kind": "reauth_weekly_counts",
                    "status": "present",
                    "week_start": "2026-06-08",
                    "total_events": 0,
                    "rows": [],
                },
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.reauth_weekly_trend_payload",
                return_value={
                    "kind": "reauth_weekly_trend",
                    "status": "present",
                    "latest_week_start": "2026-06-08",
                    "weeks_observed": 4,
                    "latest_total_events": 0,
                    "weeks": [],
                },
            ):
                payload = refresh_dod_status_artifacts(
                    artifact_root=root,
                    worker_id="worker-a",
                    profile_root=profile_root,
                )

            encoded = json.dumps(payload, ensure_ascii=False)
            statuses = {item["name"]: item["status"] for item in payload["artifacts"]}  # type: ignore[index]
            action_by_name = {item["action"]: item for item in payload["action_items"]}  # type: ignore[index]
            blockers_by_id = {item["id"]: item["actions"] for item in payload["dod_blockers"]}  # type: ignore[index]

            self.assertFalse(payload["ready"])
            self.assertEqual(statuses["portal_session_preflight_status"], "stale_schema")
            self.assertEqual(action_by_name["refresh_portal_session_preflight"]["area"], "portal_session_preflight")
            self.assertEqual(
                action_by_name["refresh_portal_session_preflight"]["action_hint"],
                "portal_session_preflight_schema_stale",
            )
            self.assertEqual(action_by_name["refresh_portal_session_preflight"]["blocks_dod"], ["dod_1_restart_search_all_sites"])
            self.assertIn(
                shlex.join(
                    [
                        "python3",
                        "-m",
                        "tools.multi_position_sourcing.portal_login",
                        "--channels",
                        "saramin,jobkorea,linkedin_rps",
                        "--profile-root",
                        str(profile_root),
                        "--worker-id",
                        "worker-a",
                        "--no-human-intervention",
                        "--channel-timeout-seconds",
                        "180",
                        "--output",
                        str(root / "portal_session_status_latest.json"),
                    ]
                ),
                action_by_name["refresh_portal_session_preflight"]["commands"],
            )
            self.assertIn("refresh_portal_session_preflight", blockers_by_id["dod_1_restart_search_all_sites"])
            self.assertIn("generated_at", encoded)
            self.assertNotIn("storage_state", encoded)
            self.assertNotIn("cookie-secret", encoded)

    def test_portal_session_preflight_status_payload_requires_snapshot_capture_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "portal_session_status_latest.json"
            path.write_text(
                json.dumps(
                    {
                        "kind": "portal_session_preflight",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "ready": True,
                        "portal_sessions": [
                            {
                                "channel": "saramin",
                                "ready": True,
                                "login": "existing_session_ok",
                            },
                            complete_preflight_session("jobkorea"),
                            complete_preflight_session("linkedin_rps"),
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = portal_session_preflight_status_payload(path)

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["status"], "snapshot_not_captured")
        self.assertEqual(payload["preflight_generated_at"], "2026-06-09T00:00:00+00:00")
        self.assertIn("saramin:snapshot_capture_required_not_true", payload["snapshot_issues"])
        self.assertEqual(payload["action_hint"], "portal_session_preflight_snapshot_missing")

    def test_dod_refresh_status_artifacts_does_not_accept_unrecorded_discord_delivery(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_complete_preflight_artifact(root)
            discord_alert = root / "portal_discord_alert_test_latest.json"
            discord_alert.write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "status": "delivered",
                        "delivered": True,
                        "reauth_event_recorded": False,
                        "event": complete_linkedin_discord_event(),
                    }
                ),
                encoding="utf-8",
            )

            def fake_snapshot_metadata(*, channel: str, worker_id: str) -> dict[str, object]:
                return {
                    "kind": "session_snapshot_metadata",
                    "site": channel,
                    "worker_id": worker_id,
                    "snapshot_present": True,
                    "status": "present",
                    "snapshot_kind": "current",
                    "is_validated": True,
                    "encrypted_envelope": "VHSS1",
                    "encrypted_bytes": 96,
                }

            with patch(
                "tools.multi_position_sourcing.portal_live_check.live_readiness_payload",
                return_value={"kind": "portal_live_readiness", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.supabase_access_check_payload",
                return_value={"kind": "supabase_access_check", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.discord_webhook_from_env",
                return_value="",
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.snapshot_metadata_payload",
                side_effect=fake_snapshot_metadata,
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.weekly_reauth_counts_payload",
                return_value={
                    "kind": "reauth_weekly_counts",
                    "status": "present",
                    "week_start": "2026-06-08",
                    "total_events": 0,
                    "rows": [],
                },
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.reauth_weekly_trend_payload",
                return_value={
                    "kind": "reauth_weekly_trend",
                    "status": "present",
                    "latest_week_start": "2026-06-08",
                    "weeks_observed": 4,
                    "latest_total_events": 0,
                    "weeks": [],
                },
            ):
                payload = refresh_dod_status_artifacts(artifact_root=root)

            statuses = {item["name"]: item["status"] for item in payload["artifacts"]}  # type: ignore[index]
            refreshed_alert = json.loads(discord_alert.read_text(encoding="utf-8"))

            self.assertFalse(payload["ready"])
            self.assertEqual(statuses["discord_alert_precheck"], "missing_webhook")
            action_by_name = {item["action"]: item for item in payload["action_items"]}  # type: ignore[index]
            self.assertEqual(action_by_name["configure_discord_reauth_webhook"]["area"], "discord_alert_precheck")
            self.assertEqual(action_by_name["configure_discord_reauth_webhook"]["status"], "missing_webhook")
            self.assertEqual(action_by_name["configure_discord_reauth_webhook"]["blocks_dod"], ["dod_5_linkedin_discord_alert"])
            self.assertTrue(
                any("init-discord-webhook" in command for command in action_by_name["configure_discord_reauth_webhook"]["commands"])
            )
            self.assertTrue(
                any("discord-alert-test --record-reauth-event" in command for command in action_by_name["configure_discord_reauth_webhook"]["commands"])
            )
            self.assertFalse(refreshed_alert["delivered"])
            self.assertFalse(refreshed_alert["reauth_event_recorded"])

    def test_dod_refresh_status_artifacts_requires_discord_alert_test_when_webhook_configured(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_complete_preflight_artifact(root)

            def fake_snapshot_metadata(*, channel: str, worker_id: str) -> dict[str, object]:
                return {
                    "kind": "session_snapshot_metadata",
                    "site": channel,
                    "worker_id": worker_id,
                    "snapshot_present": True,
                    "status": "present",
                    "snapshot_kind": "current",
                    "is_validated": True,
                    "encrypted_envelope": "VHSS1",
                    "encrypted_bytes": 96,
                }

            with patch(
                "tools.multi_position_sourcing.portal_live_check.live_readiness_payload",
                return_value={"kind": "portal_live_readiness", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.supabase_access_check_payload",
                return_value={"kind": "supabase_access_check", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.discord_webhook_from_env",
                return_value="https://discord.example.test/webhook",
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.snapshot_metadata_payload",
                side_effect=fake_snapshot_metadata,
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.weekly_reauth_counts_payload",
                return_value={
                    "kind": "reauth_weekly_counts",
                    "status": "present",
                    "week_start": "2026-06-08",
                    "total_events": 0,
                    "rows": [],
                },
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.reauth_weekly_trend_payload",
                return_value={
                    "kind": "reauth_weekly_trend",
                    "status": "present",
                    "latest_week_start": "2026-06-08",
                    "weeks_observed": 4,
                    "latest_total_events": 0,
                    "weeks": [],
                },
            ):
                payload = refresh_dod_status_artifacts(artifact_root=root)

            statuses = {item["name"]: item["status"] for item in payload["artifacts"]}  # type: ignore[index]
            action_by_name = {item["action"]: item for item in payload["action_items"]}  # type: ignore[index]
            discord_alert = json.loads((root / "portal_discord_alert_test_latest.json").read_text(encoding="utf-8"))
            encoded = json.dumps(discord_alert, ensure_ascii=False)

        self.assertFalse(payload["ready"])
        self.assertEqual(statuses["discord_alert_precheck"], "not_run")
        self.assertEqual(discord_alert["status"], "not_run")
        self.assertEqual(discord_alert["action_hint"], "discord_alert_test_required")
        self.assertFalse(discord_alert["delivered"])
        self.assertTrue(discord_alert["reauth_event_recording_requested"])
        self.assertFalse(discord_alert["reauth_event_recorded"])
        self.assertIn("run_linkedin_discord_alert_test", action_by_name)
        self.assertNotIn("configure_discord_reauth_webhook", action_by_name)
        self.assertEqual(action_by_name["run_linkedin_discord_alert_test"]["status"], "not_run")
        self.assertEqual(
            action_by_name["run_linkedin_discord_alert_test"]["blocks_dod"],
            ["dod_5_linkedin_discord_alert"],
        )
        self.assertTrue(
            any(
                "discord-alert-test --record-reauth-event" in command
                for command in action_by_name["run_linkedin_discord_alert_test"]["commands"]
            )
        )
        self.assertNotIn("discord.example.test/webhook", encoded)
        self.assertNotIn("storage_state", encoded)

    def test_dod_refresh_status_artifacts_rejects_discord_alert_event_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_complete_preflight_artifact(root)
            (root / "portal_discord_alert_test_latest.json").write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "delivered",
                        "delivered": True,
                        "reauth_event_recording_requested": True,
                        "reauth_event_recorded": True,
                        "event": {
                            "id": "manual-live-check",
                            "site": "saramin",
                            "worker_id": "default",
                            "cause": "profile_corrupt",
                            "recovered_by": "snapshot_reinject",
                            "occurred_at": "2026-06-09T00:00:00+00:00",
                        },
                    }
                ),
                encoding="utf-8",
            )

            def fake_snapshot_metadata(*, channel: str, worker_id: str) -> dict[str, object]:
                return {
                    "kind": "session_snapshot_metadata",
                    "site": channel,
                    "worker_id": worker_id,
                    "snapshot_present": True,
                    "status": "present",
                    "snapshot_kind": "current",
                    "is_validated": True,
                    "encrypted_envelope": "VHSS1",
                    "encrypted_bytes": 96,
                }

            with patch(
                "tools.multi_position_sourcing.portal_live_check.live_readiness_payload",
                return_value={"kind": "portal_live_readiness", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.supabase_access_check_payload",
                return_value={"kind": "supabase_access_check", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.discord_webhook_from_env",
                return_value="https://discord.example.test/webhook",
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.snapshot_metadata_payload",
                side_effect=fake_snapshot_metadata,
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.weekly_reauth_counts_payload",
                return_value={
                    "kind": "reauth_weekly_counts",
                    "status": "present",
                    "week_start": "2026-06-08",
                    "total_events": 0,
                    "rows": [],
                },
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.reauth_weekly_trend_payload",
                return_value={
                    "kind": "reauth_weekly_trend",
                    "status": "present",
                    "latest_week_start": "2026-06-08",
                    "weeks_observed": 4,
                    "latest_total_events": 0,
                    "weeks": [],
                },
            ):
                payload = refresh_dod_status_artifacts(artifact_root=root)

            statuses = {item["name"]: item["status"] for item in payload["artifacts"]}  # type: ignore[index]
            action_by_name = {item["action"]: item for item in payload["action_items"]}  # type: ignore[index]

        self.assertFalse(payload["ready"])
        self.assertEqual(statuses["discord_alert_precheck"], "event_mismatch")
        self.assertEqual(action_by_name["run_linkedin_discord_alert_test"]["status"], "event_mismatch")
        self.assertEqual(
            action_by_name["run_linkedin_discord_alert_test"]["blocks_dod"],
            ["dod_5_linkedin_discord_alert"],
        )

    def test_dod_refresh_status_artifacts_writes_missing_discord_precheck_without_delivery(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_complete_preflight_artifact(root)

            def fake_snapshot_metadata(*, channel: str, worker_id: str) -> dict[str, object]:
                return {
                    "kind": "session_snapshot_metadata",
                    "site": channel,
                    "worker_id": worker_id,
                    "snapshot_present": True,
                    "status": "present",
                    "snapshot_kind": "current",
                    "is_validated": True,
                    "encrypted_envelope": "VHSS1",
                    "encrypted_bytes": 96,
                }

            with patch(
                "tools.multi_position_sourcing.portal_live_check.live_readiness_payload",
                return_value={"kind": "portal_live_readiness", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.supabase_access_check_payload",
                return_value={"kind": "supabase_access_check", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.discord_webhook_from_env",
                return_value="",
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.snapshot_metadata_payload",
                side_effect=fake_snapshot_metadata,
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.weekly_reauth_counts_payload",
                return_value={
                    "kind": "reauth_weekly_counts",
                    "status": "present",
                    "week_start": "2026-06-08",
                    "total_events": 0,
                    "rows": [],
                },
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.reauth_weekly_trend_payload",
                return_value={
                    "kind": "reauth_weekly_trend",
                    "status": "present",
                    "latest_week_start": "2026-06-08",
                    "weeks_observed": 4,
                    "latest_total_events": 0,
                    "weeks": [],
                },
            ):
                payload = refresh_dod_status_artifacts(artifact_root=root)

            statuses = {item["name"]: item["status"] for item in payload["artifacts"]}  # type: ignore[index]
            discord_alert = json.loads((root / "portal_discord_alert_test_latest.json").read_text(encoding="utf-8"))
            encoded = json.dumps(discord_alert, ensure_ascii=False)

            self.assertFalse(payload["ready"])
            self.assertEqual(statuses["discord_alert_precheck"], "missing_webhook")
            discord_reason = next(
                reason
                for reason in payload["blocking_reasons"]  # type: ignore[union-attr]
                if reason.get("name") == "discord_alert_precheck"
            )
            self.assertEqual(discord_reason["status"], "missing_webhook")
            self.assertEqual(discord_reason["action_hint"], "discord_reauth_webhook_missing")
            self.assertEqual(discord_alert["status"], "missing_webhook")
            self.assertFalse(discord_alert["delivered"])
            self.assertFalse(discord_alert["reauth_event_recorded"])
            self.assertNotIn("storage_state", encoded)
            self.assertNotIn("webhook.example", encoded)

    def test_dod_refresh_status_artifacts_marks_unavailable_snapshot_not_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_complete_preflight_artifact(root)
            with patch(
                "tools.multi_position_sourcing.portal_live_check.live_readiness_payload",
                return_value={"kind": "portal_live_readiness", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.supabase_access_check_payload",
                return_value={"kind": "supabase_access_check", "ready": True, "checks": []},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.snapshot_metadata_payload",
                return_value={
                    "kind": "session_snapshot_metadata",
                    "site": "saramin",
                    "worker_id": "default",
                    "snapshot_present": False,
                    "status": "unavailable",
                    "error_type": "SupabaseSessionStoreError",
                },
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.weekly_reauth_counts_payload",
                return_value={
                    "kind": "reauth_weekly_counts",
                    "status": "present",
                    "week_start": "2026-06-08",
                    "total_events": 0,
                    "rows": [],
                },
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.reauth_weekly_trend_payload",
                return_value={
                    "kind": "reauth_weekly_trend",
                    "status": "present",
                    "latest_week_start": "2026-06-08",
                    "weeks_observed": 4,
                    "latest_total_events": 0,
                    "weeks": [],
                },
            ):
                payload = refresh_dod_status_artifacts(artifact_root=root)

            self.assertFalse(payload["ready"])
            statuses = {item["name"]: item["status"] for item in payload["artifacts"]}  # type: ignore[index]
            self.assertEqual(statuses["snapshot_metadata_saramin"], "unavailable")
            self.assertEqual(statuses["snapshot_metadata_jobkorea"], "unavailable")
            self.assertEqual(statuses["snapshot_metadata_linkedin_rps"], "unavailable")
            self.assertEqual(statuses["profile_recovery_precheck_saramin"], "not_run")
            self.assertEqual(statuses["profile_recovery_precheck_jobkorea"], "not_run")
            recovery = json.loads((root / "portal_profile_recovery_saramin.json").read_text(encoding="utf-8"))
            self.assertEqual(recovery["status"], "not_run")
            self.assertIsInstance(recovery["generated_at"], str)
            self.assertFalse(recovery["profile_deleted_before_start"])
            self.assertEqual(recovery["snapshot_metadata_status"], "unavailable")
            action_by_name = {item["action"]: item for item in payload["action_items"]}  # type: ignore[index]
            self.assertEqual(action_by_name["restore_supabase_snapshot_read_access"]["status"], "unavailable")
            self.assertTrue(
                any(
                    "snapshot-metadata --channel saramin" in command
                    for command in action_by_name["restore_supabase_snapshot_read_access"]["commands"]
                )
            )
            self.assertEqual(
                action_by_name["capture_validated_snapshots_before_profile_recovery_smoke"]["status"],
                "not_run",
            )
            self.assertTrue(
                any(
                    "capture-snapshot --channel saramin" in command
                    for command in action_by_name["capture_validated_snapshots_before_profile_recovery_smoke"]["commands"]
                )
            )
            blockers_by_id = {item["id"]: item["actions"] for item in payload["dod_blockers"]}  # type: ignore[index]
            self.assertIn("restore_supabase_snapshot_read_access", blockers_by_id["dod_2_profile_corruption_snapshot_recovery"])

    def test_dod_refresh_status_artifacts_summarizes_blockers_without_secret_values(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "artifact root"
            profile_root = Path(tmp) / "profile root"
            root.mkdir()
            write_complete_preflight_artifact(root)
            with patch(
                "tools.multi_position_sourcing.portal_live_check.live_readiness_payload",
                return_value={
                    "kind": "portal_live_readiness",
                    "ready": False,
                    "checks": [
                        {
                            "name": "supabase_access",
                            "status": "failed",
                            "action_hint": "configured_service_role_key_rejected_by_supabase",
                        },
                        {
                            "name": "supabase_schema_proof",
                            "status": "failed",
                            "action_hint": "apply_supabase_session_schema",
                            "failed_checks": ["encrypted_snapshot_envelope_constraint"],
                        },
                        {"name": "discord_reauth_webhook_env", "status": "missing"},
                    ],
                },
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.supabase_access_check_payload",
                return_value={
                    "kind": "supabase_access_check",
                    "ready": False,
                    "action_hint": "configured_service_role_key_rejected_by_supabase",
                    "checks": [],
                },
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.discord_webhook_from_env",
                return_value="",
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.snapshot_metadata_payload",
                return_value={
                    "kind": "session_snapshot_metadata",
                    "site": "saramin",
                    "worker_id": "default",
                    "snapshot_present": False,
                    "status": "unavailable",
                    "error_type": "SupabaseSessionStoreError",
                },
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.weekly_reauth_counts_payload",
                return_value={"kind": "reauth_weekly_counts", "status": "unavailable", "error_type": "SupabaseSessionStoreError"},
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.reauth_weekly_trend_payload",
                return_value={"kind": "reauth_weekly_trend", "status": "unavailable", "error_types": ["SupabaseSessionStoreError"]},
            ):
                payload = refresh_dod_status_artifacts(
                    artifact_root=root,
                    worker_id="worker-a",
                    week_start="2026-06-08",
                    keyword="senior qa",
                    profile_root=profile_root,
                )

        encoded = json.dumps(payload, ensure_ascii=False)
        action_items = payload["action_items"]  # type: ignore[assignment]
        reasons = payload["blocking_reasons"]  # type: ignore[assignment]
        actions = [item["action"] for item in action_items]
        action_by_name = {item["action"]: item for item in action_items}
        blockers_by_id = {item["id"]: item["actions"] for item in payload["dod_blockers"]}  # type: ignore[index]

        self.assertFalse(payload["ready"])
        self.assertEqual(actions.count("configure_discord_reauth_webhook"), 1)
        self.assertEqual(action_by_name["fix_supabase_service_role_schema_or_key"]["area"], "supabase_access")
        self.assertEqual(
            action_by_name["fix_supabase_service_role_schema_or_key"]["action_hint"],
            "configured_service_role_key_rejected_by_supabase",
        )
        self.assertTrue(
            any(
                "supabase-access-check" in command
                for command in action_by_name["fix_supabase_service_role_schema_or_key"]["commands"]
            )
        )
        self.assertIn(
            shlex.join(
                [
                    "python3",
                    "-m",
                    "tools.multi_position_sourcing.portal_live_check",
                    "supabase-access-check",
                    "--output",
                    str(root / "portal_supabase_access_latest.json"),
                ]
            ),
            action_by_name["fix_supabase_service_role_schema_or_key"]["commands"],
        )
        self.assertEqual(action_by_name["apply_supabase_session_schema"]["area"], "supabase_schema")
        self.assertEqual(action_by_name["apply_supabase_session_schema"]["action_hint"], "apply_supabase_session_schema")
        self.assertTrue(
            any(
                "supabase-schema-proof" in command
                for command in action_by_name["apply_supabase_session_schema"]["commands"]
            )
        )
        self.assertEqual(action_by_name["configure_discord_reauth_webhook"]["status"], "missing_webhook")
        self.assertIn(
            shlex.join(
                [
                    "python3",
                    "-m",
                    "tools.multi_position_sourcing.portal_live_check",
                    "dod-refresh-status",
                    "--artifact-root",
                    str(root),
                    "--worker-id",
                    "worker-a",
                    "--week-start",
                    "2026-06-08",
                    "--keyword",
                    "senior qa",
                    "--profile-root",
                    str(profile_root),
                    "--output",
                    str(root / "portal_dod_status_refresh_latest.json"),
                ]
            ),
            action_by_name["configure_discord_reauth_webhook"]["commands"],
        )
        self.assertTrue(
            any(
                "init-discord-webhook" in command
                for command in action_by_name["configure_discord_reauth_webhook"]["commands"]
            )
        )
        self.assertEqual(action_by_name["restore_supabase_reauth_event_read_access"]["status"], "unavailable")
        self.assertIn(
            shlex.join(
                [
                    "python3",
                    "-m",
                    "tools.multi_position_sourcing.portal_live_check",
                    "reauth-weekly-counts",
                    "--week-start",
                    "2026-06-08",
                    "--output",
                    str(root / "portal_reauth_weekly_counts_latest.json"),
                ]
            ),
            action_by_name["restore_supabase_reauth_event_read_access"]["commands"],
        )
        self.assertTrue(
            any(
                "reauth-weekly-counts" in command
                for command in action_by_name["restore_supabase_reauth_event_read_access"]["commands"]
            )
        )
        self.assertEqual(action_by_name["run_guarded_restart_smoke_all_sites"]["status"], "missing")
        self.assertIn(
            shlex.join(
                [
                    "python3",
                    "-m",
                    "tools.multi_position_sourcing.portal_live_check",
                    "restart-smoke",
                    "--channel",
                    "linkedin_rps",
                    "--keyword",
                    "senior qa",
                    "--worker-id",
                    "worker-a",
                    "--profile-root",
                    str(profile_root),
                    "--timeout-seconds",
                    "180",
                    "--output",
                    str(root / "portal_restart_smoke_linkedin_rps.json"),
                ]
            ),
            action_by_name["run_guarded_restart_smoke_all_sites"]["commands"],
        )
        self.assertTrue(
            any(
                "restart-smoke --channel linkedin_rps" in command
                for command in action_by_name["run_guarded_restart_smoke_all_sites"]["commands"]
            )
        )
        self.assertTrue(
            any(
                "restart-smoke-proof" in command
                for command in action_by_name["run_guarded_restart_smoke_all_sites"]["commands"]
            )
        )
        self.assertEqual(action_by_name["run_profile_recovery_smoke_saramin_jobkorea"]["status"], "failed")
        self.assertIn(
            shlex.join(
                [
                    "python3",
                    "-m",
                    "tools.multi_position_sourcing.portal_live_check",
                    "profile-recovery-smoke",
                    "--channel",
                    "jobkorea",
                    "--keyword",
                    "senior qa",
                    "--worker-id",
                    "worker-a",
                    "--profile-root",
                    str(profile_root),
                    "--confirm-delete-profile",
                    str(profile_root / "jobkorea" / "worker-a"),
                    "--output",
                    str(root / "portal_profile_recovery_jobkorea.json"),
                ]
            ),
            action_by_name["run_profile_recovery_smoke_saramin_jobkorea"]["commands"],
        )
        self.assertTrue(
            any(
                "profile-recovery-smoke --channel jobkorea" in command
                for command in action_by_name["run_profile_recovery_smoke_saramin_jobkorea"]["commands"]
            )
        )
        self.assertTrue(
            any(
                "profile-recovery-proof" in command
                for command in action_by_name["run_profile_recovery_smoke_saramin_jobkorea"]["commands"]
            )
        )
        self.assertIn("fix_supabase_service_role_schema_or_key", blockers_by_id["dod_1_restart_search_all_sites"])
        self.assertIn("run_guarded_restart_smoke_all_sites", blockers_by_id["dod_1_restart_search_all_sites"])
        self.assertIn(
            "run_profile_recovery_smoke_saramin_jobkorea",
            blockers_by_id["dod_2_profile_corruption_snapshot_recovery"],
        )
        self.assertIn("configure_discord_reauth_webhook", blockers_by_id["dod_5_linkedin_discord_alert"])
        self.assertIn("restore_supabase_reauth_event_read_access", blockers_by_id["dod_7_reauth_events_weekly_observable"])
        self.assertIn("apply_supabase_session_schema", blockers_by_id["dod_6_no_plaintext_session_output"])
        self.assertTrue(any(reason.get("name") == "readiness" for reason in reasons))
        self.assertNotIn("service-role-secret", encoded)
        self.assertNotIn("webhook.example", encoded)
        self.assertNotIn("storage_state", encoded)

    def test_live_readiness_payload_reports_prereqs_without_secret_values(self) -> None:
        payload = live_readiness_payload(
            {
                "SUPABASE_URL": "https://supabase.example.test",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
                "DISCORD_REAUTH_WEBHOOK_URL": "https://discord.example.test/webhook",
            },
            session_key_available=lambda: True,
            portal_credentials_available=lambda _site: True,
            playwright_available=lambda: True,
            supabase_access_payload=lambda _env: {
                "kind": "supabase_access_check",
                "ready": True,
                "action_hint": "ready",
                "checks": [],
            },
            supabase_schema_payload=lambda: {
                "kind": "supabase_session_schema_proof",
                "ready": True,
                "status": "ready",
                "action_hint": "ready",
                "failed_checks": [],
                "checks": [],
            },
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["kind"], "portal_live_readiness")
        self.assertTrue(payload["ready"])
        statuses = {item["name"]: item["status"] for item in payload["checks"]}  # type: ignore[index]
        self.assertEqual(statuses["supabase_access"], "passed")
        self.assertEqual(statuses["supabase_schema_proof"], "passed")
        self.assertNotIn("service-role-secret", encoded)
        self.assertNotIn("discord.example.test/webhook", encoded)
        self.assertNotIn("password", encoded.lower())
        # SOT invariant: LinkedIn RPS is a credentialed auto-login portal like the others
        self.assertIn("linkedin_rps_keychain_credentials", encoded)
        self.assertNotIn("linkedin_auto_login_disabled", encoded)

    def test_live_readiness_payload_marks_missing_required_prereqs(self) -> None:
        payload = live_readiness_payload(
            {},
            session_key_available=lambda: False,
            portal_credentials_available=lambda site: site == "saramin",
            playwright_available=lambda: False,
            supabase_access_payload=lambda _env: {
                "kind": "supabase_access_check",
                "ready": False,
                "action_hint": "supabase_config_missing_or_incomplete",
                "checks": [],
            },
            supabase_schema_payload=lambda: {
                "kind": "supabase_session_schema_proof",
                "ready": True,
                "status": "ready",
                "action_hint": "ready",
                "failed_checks": [],
                "checks": [],
            },
        )

        self.assertFalse(payload["ready"])
        statuses = {item["name"]: item["status"] for item in payload["checks"]}  # type: ignore[index]
        self.assertEqual(statuses["supabase_url_env"], "missing")
        self.assertEqual(statuses["supabase_service_role_env"], "missing")
        self.assertEqual(statuses["supabase_access"], "failed")
        self.assertEqual(statuses["supabase_schema_proof"], "passed")
        self.assertEqual(statuses["discord_reauth_webhook_env"], "missing")
        self.assertEqual(statuses["playwright_available"], "missing")
        self.assertEqual(statuses["mac_keychain_session_key"], "missing")
        self.assertEqual(statuses["saramin_keychain_credentials"], "passed")
        self.assertEqual(statuses["jobkorea_keychain_credentials"], "missing")
        self.assertEqual(statuses["linkedin_rps_keychain_credentials"], "missing")

    def test_live_readiness_payload_surfaces_supabase_access_failure_safely(self) -> None:
        payload = live_readiness_payload(
            {
                "SUPABASE_URL": "https://supabase.example.test",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
                "DISCORD_REAUTH_WEBHOOK_URL": "https://discord.example.test/webhook",
            },
            session_key_available=lambda: True,
            portal_credentials_available=lambda _site: True,
            playwright_available=lambda: True,
            supabase_access_payload=lambda _env: {
                "kind": "supabase_access_check",
                "ready": False,
                "action_hint": "configured_service_role_key_rejected_by_supabase",
                "checks": [
                    {
                        "name": "reauth_events_read",
                        "status": "failed",
                        "http_status": 401,
                        "http_error_hint": "invalid_api_key",
                    }
                ],
            },
            supabase_schema_payload=lambda: {
                "kind": "supabase_session_schema_proof",
                "ready": True,
                "status": "ready",
                "action_hint": "ready",
                "failed_checks": [],
                "checks": [],
            },
        )

        encoded = json.dumps(payload, ensure_ascii=False)
        checks = {item["name"]: item for item in payload["checks"]}  # type: ignore[index]
        self.assertFalse(payload["ready"])
        self.assertEqual(checks["supabase_access"]["status"], "failed")
        self.assertEqual(checks["supabase_access"]["action_hint"], "configured_service_role_key_rejected_by_supabase")
        self.assertNotIn("service-role-secret", encoded)
        self.assertNotIn("invalid_api_key", encoded)

    def test_live_readiness_payload_surfaces_supabase_schema_failure_safely(self) -> None:
        payload = live_readiness_payload(
            {
                "SUPABASE_URL": "https://supabase.example.test",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
                "DISCORD_REAUTH_WEBHOOK_URL": "https://discord.example.test/webhook",
            },
            session_key_available=lambda: True,
            portal_credentials_available=lambda _site: True,
            playwright_available=lambda: True,
            supabase_access_payload=lambda _env: {
                "kind": "supabase_access_check",
                "ready": True,
                "action_hint": "ready",
                "checks": [],
            },
            supabase_schema_payload=lambda: {
                "kind": "supabase_session_schema_proof",
                "ready": False,
                "status": "failed",
                "action_hint": "apply_supabase_session_schema",
                "failed_checks": ["encrypted_snapshot_envelope_constraint"],
                "checks": [
                    {
                        "name": "encrypted_snapshot_envelope_constraint",
                        "status": "failed",
                    }
                ],
            },
        )

        encoded = json.dumps(payload, ensure_ascii=False)
        checks = {item["name"]: item for item in payload["checks"]}  # type: ignore[index]
        self.assertFalse(payload["ready"])
        self.assertEqual(checks["supabase_schema_proof"]["status"], "failed")
        self.assertEqual(checks["supabase_schema_proof"]["action_hint"], "apply_supabase_session_schema")
        self.assertEqual(
            checks["supabase_schema_proof"]["failed_checks"],
            ["encrypted_snapshot_envelope_constraint"],
        )
        self.assertNotIn("service-role-secret", encoded)
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("create table", encoded.lower())

    def test_supabase_schema_proof_payload_validates_local_schema_without_sql_output(self) -> None:
        payload = supabase_schema_proof_payload()
        encoded = json.dumps(payload, ensure_ascii=False)
        check_statuses = {item["name"]: item["status"] for item in payload["checks"]}  # type: ignore[index]

        self.assertEqual(payload["kind"], "supabase_session_schema_proof")
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(check_statuses["encrypted_snapshot_envelope_constraint"], "passed")
        self.assertEqual(check_statuses["reauth_event_policy_constraints"], "passed")
        self.assertEqual(check_statuses["service_role_reauth_events_access"], "passed")
        self.assertEqual(check_statuses["weekly_reauth_counts_rpc"], "passed")
        self.assertEqual(payload["failed_checks"], [])
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("storage_state_enc", encoded)
        self.assertNotIn("create table", encoded.lower())

    def test_supabase_schema_proof_payload_reports_missing_contract_safely(self) -> None:
        with TemporaryDirectory() as tmp:
            schema = Path(tmp) / "schema.sql"
            schema.write_text("create table public.session_state (id uuid primary key);", encoding="utf-8")
            payload = supabase_schema_proof_payload(schema)

        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["action_hint"], "apply_supabase_session_schema")
        self.assertIn("encrypted_snapshot_envelope_constraint", payload["failed_checks"])
        self.assertIn("reauth_event_policy_constraints", payload["failed_checks"])
        self.assertIn("service_role_reauth_events_access", payload["failed_checks"])
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("create table", encoded.lower())

    def test_supabase_schema_proof_requires_weekly_rpc_security_definer(self) -> None:
        weekly_rpc_header = """create or replace function public.reauth_weekly_counts(
  week_start_arg timestamptz
)
returns table (
  site text,
  worker_id text,
  cause text,
  recovered_by text,
  count bigint
)
language sql
security definer
set search_path = public"""
        with TemporaryDirectory() as tmp:
            schema = Path(tmp) / "schema.sql"
            source = Path("docs/ai-search/session-state-supabase-schema-2026-06-09.sql").read_text(encoding="utf-8")
            self.assertIn(weekly_rpc_header, source)
            schema.write_text(
                source.replace(weekly_rpc_header, weekly_rpc_header.replace("security definer\n", "")),
                encoding="utf-8",
            )
            payload = supabase_schema_proof_payload(schema)

        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertFalse(payload["ready"])
        self.assertIn("weekly_reauth_counts_rpc", payload["failed_checks"])
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("create table", encoded.lower())

    def test_init_session_key_payload_reports_keychain_status_without_key_material(self) -> None:
        class FakeKeyProvider:
            def __init__(self) -> None:
                self.calls = 0

            def get_key(self) -> bytes:
                self.calls += 1
                return b"k" * 32

        provider = FakeKeyProvider()
        payload = init_session_key_payload(
            session_key_available=lambda: False,
            key_provider=provider,
        )
        existing_payload = init_session_key_payload(
            session_key_available=lambda: True,
            key_provider=provider,
        )
        encoded = json.dumps(payload, ensure_ascii=False) + json.dumps(existing_payload, ensure_ascii=False)

        self.assertEqual(provider.calls, 2)
        self.assertEqual(payload["kind"], "portal_session_key_init")
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["session_key_available"])
        self.assertTrue(payload["created"])
        self.assertFalse(existing_payload["created"])
        self.assertNotIn(base64.b64encode(b"k" * 32).decode("ascii"), encoded)
        self.assertNotIn("kkkk", encoded)

    def test_init_portal_credentials_payload_imports_env_without_secret_output(self) -> None:
        class FakeCredentialProvider:
            service = "valuehire.portal_credentials"

            def __init__(self) -> None:
                self.stored: list[tuple[str, PortalCredentials]] = []

            def store(self, site: str, credentials: PortalCredentials) -> None:
                self.stored.append((site, credentials))

        provider = FakeCredentialProvider()
        payload = init_portal_credentials_payload(
            {
                "SARAMIN_USERNAME": "valueconnect",
                "SARAMIN_PASSWORD": "saramin-secret",
                "JOBKOREA_USERNAME": "jobkorea-user",
                "JOBKOREA_PASSWORD": "jobkorea-secret",
                "LINKEDIN_USERNAME": "linkedin-user",
                "LINKEDIN_PASSWORD": "linkedin-secret",
            },
            channels=("saramin", "jobkorea", "linkedin_rps"),
            credential_provider=provider,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertTrue(payload["ready"])
        # SOT invariant: all three portals are imported — LinkedIn is no longer skipped
        self.assertEqual([site for site, _credentials in provider.stored], ["saramin", "jobkorea", "linkedin_rps"])
        self.assertEqual(provider.stored[0][1].username, "valueconnect")
        self.assertNotIn('"status": "skipped"', encoded)
        self.assertIn("saramin:username", encoded)
        self.assertIn("linkedin_rps:username", encoded)
        self.assertNotIn("valueconnect", encoded)
        self.assertNotIn("saramin-secret", encoded)
        self.assertNotIn("jobkorea-user", encoded)
        self.assertNotIn("jobkorea-secret", encoded)
        self.assertNotIn("linkedin-user", encoded)
        self.assertNotIn("linkedin-secret", encoded)

    def test_init_portal_credentials_payload_reports_missing_env_safely(self) -> None:
        payload = init_portal_credentials_payload(
            {"SARAMIN_USERNAME": "valueconnect"},
            channels=("saramin", "jobkorea"),
            credential_provider=object(),
        )
        encoded = json.dumps(payload, ensure_ascii=False)
        rows = {row["site"]: row for row in payload["rows"]}  # type: ignore[index]

        self.assertFalse(payload["ready"])
        self.assertEqual(rows["saramin"]["status"], "missing_env")
        self.assertEqual(rows["jobkorea"]["status"], "missing_env")
        self.assertIn("SARAMIN_PASSWORD", encoded)
        self.assertNotIn("valueconnect", encoded)

    def test_init_discord_webhook_payload_imports_env_without_secret_output(self) -> None:
        written: list[str] = []
        webhook_url = "https://discord.example.test/secret-webhook-token"

        payload = init_discord_webhook_payload(
            {"DISCORD_REAUTH_WEBHOOK_URL": webhook_url},
            webhook_writer=written.append,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(written, [webhook_url])
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["env_key"], "DISCORD_REAUTH_WEBHOOK_URL")
        self.assertNotIn(webhook_url, encoded)
        self.assertNotIn("secret-webhook-token", encoded)

    def test_discord_webhook_keychain_writer_uses_stdin_without_webhook_in_argv(self) -> None:
        calls: list[tuple[list[str], bytes]] = []
        webhook_url = "https://discord.example.test/secret-webhook-token"
        encoded_webhook = base64.b64encode(webhook_url.encode("utf-8")).decode("ascii")

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            calls.append((command, kwargs.get("input", b"")))  # type: ignore[arg-type]
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        with patch("tools.multi_position_sourcing.portal_keychain.subprocess.run", fake_run):
            payload = init_discord_webhook_payload({"DISCORD_REAUTH_WEBHOOK_URL": webhook_url})

        encoded_payload = json.dumps(payload, ensure_ascii=False)
        flattened = " ".join(" ".join(command) for command, _input in calls)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][-1], "-w")
        self.assertEqual(calls[0][1], (encoded_webhook + "\n").encode("utf-8"))
        self.assertTrue(payload["ready"])
        self.assertNotIn(webhook_url, encoded_payload)
        self.assertNotIn("secret-webhook-token", encoded_payload)
        self.assertNotIn(webhook_url, flattened)
        self.assertNotIn(encoded_webhook, flattened)

    def test_init_discord_webhook_payload_accepts_existing_keychain_without_secret_output(self) -> None:
        webhook_url = "https://discord.example.test/keychain-secret-webhook"
        payload = init_discord_webhook_payload(
            {},
            keychain_reader=lambda: webhook_url,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["source"], "keychain")
        self.assertNotIn(webhook_url, encoded)
        self.assertNotIn("keychain-secret-webhook", encoded)

    def test_discord_webhook_from_env_falls_back_to_keychain_reader(self) -> None:
        self.assertEqual(
            discord_webhook_from_env(
                {},
                keychain_reader=lambda: "https://discord.example.test/keychain-webhook",
            ),
            "https://discord.example.test/keychain-webhook",
        )
        self.assertEqual(
            discord_webhook_from_env(
                {"DISCORD_REAUTH_WEBHOOK_URL": "https://discord.example.test/env-webhook"},
                keychain_reader=lambda: "https://discord.example.test/keychain-webhook",
            ),
            "https://discord.example.test/env-webhook",
        )

    def test_live_check_weekly_counts_payload_is_aggregate_only(self) -> None:
        payload = safe_weekly_counts_payload(
            {
                ("saramin", "worker-a", "cookie_rotated", "snapshot_reinject"): 2,
                ("linkedin_rps", "default", "forced_logout", "human"): 1,
            },
            week_start="2026-06-09T00:00:00+00:00",
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["kind"], "reauth_weekly_counts")
        self.assertEqual(payload["total_events"], 3)
        self.assertEqual(len(payload["rows"]), 2)  # type: ignore[arg-type]
        self.assertIn('"worker_id"', encoded)
        self.assertNotIn("service-role", encoded)
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("password", encoded.lower())

    def test_live_check_weekly_trend_payload_shows_zero_convergence_metadata(self) -> None:
        store = InMemoryReauthEventStore()
        store.record(
            site="saramin",
            worker_id="worker-a",
            cause="cookie_rotated",
            recovered_by="snapshot_reinject",
            occurred_at="2026-05-26T00:00:00+00:00",
        )
        store.record(
            site="saramin",
            worker_id="worker-a",
            cause="cookie_rotated",
            recovered_by="snapshot_reinject",
            occurred_at="2026-06-02T00:00:00+00:00",
        )
        store.record(
            site="jobkorea",
            worker_id="default",
            cause="login_redirect",
            recovered_by="auto_relogin",
            occurred_at="2026-06-03T00:00:00+00:00",
        )

        payload = reauth_weekly_trend_payload(
            latest_week_start="2026-06-08",
            weeks=3,
            store=store,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["kind"], "reauth_weekly_trend")
        self.assertEqual(payload["status"], "present")
        self.assertEqual(payload["weeks_observed"], 3)
        self.assertEqual(payload["latest_week_start"], "2026-06-08")
        self.assertEqual(payload["latest_total_events"], 0)
        self.assertEqual(payload["previous_total_events"], 2)
        self.assertEqual(payload["delta_from_previous_week"], -2)
        self.assertTrue(payload["latest_week_zero"])
        self.assertEqual(payload["zero_event_weeks"], 1)
        self.assertEqual(
            [week["week_start"] for week in payload["weeks"]],  # type: ignore[index]
            ["2026-05-25", "2026-06-01", "2026-06-08"],
        )
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("cookie-secret", encoded)

    def test_live_check_weekly_trend_payload_marks_partial_unavailable(self) -> None:
        payload = safe_weekly_trend_payload(
            [
                {
                    "kind": "reauth_weekly_counts",
                    "status": "present",
                    "week_start": "2026-06-01",
                    "total_events": 2,
                    "rows": [],
                },
                {
                    "kind": "reauth_weekly_counts",
                    "status": "unavailable",
                    "week_start": "2026-06-08",
                    "total_events": 0,
                    "rows": [],
                    "error_type": "RuntimeError",
                },
            ]
        )

        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["latest_total_events"], 0)
        self.assertEqual(payload["previous_total_events"], 2)
        self.assertIsNone(payload["delta_from_previous_week"])
        self.assertFalse(payload["latest_week_zero"])

    def test_live_check_weekly_trend_payload_sanitizes_rows_to_aggregate_fields(self) -> None:
        payload = safe_weekly_trend_payload(
            [
                {
                    "kind": "reauth_weekly_counts",
                    "status": "present",
                    "week_start": "2026-06-08",
                    "total_events": 1,
                    "rows": [
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "cause": "cookie_rotated",
                            "recovered_by": "snapshot_reinject",
                            "count": 1,
                            "storage_state": "cookie-secret",
                            "raw_webhook": "https://discord.example.test/webhook",
                        }
                    ],
                }
            ]
        )
        encoded = json.dumps(payload, ensure_ascii=False)
        row = payload["weeks"][0]["rows"][0]  # type: ignore[index]

        self.assertEqual(set(row), {"site", "worker_id", "cause", "recovered_by", "count"})
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("cookie-secret", encoded)
        self.assertNotIn("discord.example.test/webhook", encoded)

    def test_live_check_weekly_trend_payload_rejects_bool_totals_and_counts(self) -> None:
        payload = safe_weekly_trend_payload(
            [
                {
                    "kind": "reauth_weekly_counts",
                    "status": "present",
                    "week_start": "2026-06-01",
                    "total_events": 2,
                    "rows": [
                        {
                            "site": "saramin",
                            "worker_id": "worker-a",
                            "cause": "cookie_rotated",
                            "recovered_by": "snapshot_reinject",
                            "count": 2,
                        }
                    ],
                },
                {
                    "kind": "reauth_weekly_counts",
                    "status": "present",
                    "week_start": "2026-06-08",
                    "total_events": True,
                    "rows": [
                        {
                            "site": "jobkorea",
                            "worker_id": "default",
                            "cause": "login_redirect",
                            "recovered_by": "auto_relogin",
                            "count": True,
                        }
                    ],
                },
            ]
        )

        latest_week = payload["weeks"][1]  # type: ignore[index]
        latest_row = latest_week["rows"][0]  # type: ignore[index]

        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["latest_total_events"], 0)
        self.assertIsNone(payload["delta_from_previous_week"])
        self.assertFalse(payload["latest_week_zero"])
        self.assertEqual(latest_week["total_events"], 0)
        self.assertEqual(latest_row["count"], 0)

    def test_live_check_weekly_trend_payload_handles_store_failure_safely(self) -> None:
        class BrokenStore:
            def weekly_counts(self, **_kwargs: object) -> object:
                raise RuntimeError("service-role-secret")

        payload = reauth_weekly_trend_payload(
            latest_week_start="2026-06-08",
            weeks=2,
            store=BrokenStore(),
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["kind"], "reauth_weekly_trend")
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["weeks_observed"], 2)
        self.assertEqual(payload["error_types"], ["RuntimeError"])
        self.assertTrue(all(week["status"] == "unavailable" for week in payload["weeks"]))  # type: ignore[index]
        self.assertNotIn("service-role-secret", encoded)

    def test_current_utc_week_start_uses_monday_boundary(self) -> None:
        self.assertEqual(current_utc_week_start(date(2026, 6, 9)), "2026-06-08")
        self.assertEqual(current_utc_week_start(date(2026, 6, 14)), "2026-06-08")
        self.assertEqual(current_utc_week_start(date(2026, 6, 15)), "2026-06-15")

    def test_profile_recovery_search_config_forces_snapshot_only_recovery(self) -> None:
        config = LiveSearchConfig(
            channel="saramin",
            keyword="backend",
            worker_id="default",
            profile_root=Path("/tmp/valuehire-test-profiles"),
            chrome_cdp_endpoint="http://127.0.0.1:9222",
            headless=False,
            searches_today=0,
            no_sleep=True,
            disable_auto_relogin=False,
            delete_profile_before_start=False,
            confirm_delete_profile="/tmp/valuehire-test-profiles/saramin/default",
            profile_only=True,
        )

        recovery_config = profile_recovery_search_config(config)

        self.assertTrue(recovery_config.disable_auto_relogin)
        self.assertTrue(recovery_config.delete_profile_before_start)
        self.assertFalse(recovery_config.profile_only)

    def test_profile_recovery_search_config_rejects_linkedin(self) -> None:
        config = LiveSearchConfig(
            channel="linkedin_rps",
            keyword="backend",
            worker_id="default",
            profile_root=Path("/tmp/valuehire-test-profiles"),
            chrome_cdp_endpoint="http://127.0.0.1:9222",
            headless=False,
            searches_today=0,
            no_sleep=True,
            disable_auto_relogin=False,
            delete_profile_before_start=False,
            confirm_delete_profile="",
        )

        with self.assertRaises(ValueError):
            profile_recovery_search_config(config)

    def test_profile_recovery_snapshot_ready_requires_validated_encrypted_metadata(self) -> None:
        self.assertTrue(
            profile_recovery_snapshot_ready(
                {
                    "kind": "session_snapshot_metadata",
                    "status": "present",
                    "snapshot_present": True,
                    "is_validated": True,
                    "encrypted_envelope": "VHSS1",
                }
            )
        )
        self.assertFalse(
            profile_recovery_snapshot_ready(
                {
                    "kind": "session_snapshot_metadata",
                    "status": "unavailable",
                    "snapshot_present": False,
                    "is_validated": False,
                    "encrypted_envelope": "VHSS1",
                }
            )
        )

    def test_profile_recovery_proof_status_payload_accepts_snapshot_only_recovery_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fresh_generated_at = utc_now_live_check()
            for site in ("saramin", "jobkorea"):
                (root / f"portal_profile_recovery_{site}.json").write_text(
                    json.dumps(
                        {
                            "kind": "portal_profile_recovery_smoke",
                            "site": site,
                            "worker_id": "default",
                            "keyword": "backend",
                            "generated_at": fresh_generated_at,
                            "recovery_policy": "snapshot_only_no_auto_relogin",
                            "auto_relogin_disabled": True,
                            "mode": "guarded",
                            "status": "searched",
                            "profile_deleted_before_start": True,
                            "reauth_cause": "profile_corrupt",
                            "snapshot_capture_required": True,
                            "snapshot_capture_policy": "required",
                            "snapshot_captured": True,
                            "retried_after_recovery": True,
                            "recovery": {
                                "recovered": True,
                                "recovered_by": "snapshot_reinject",
                                "reauth_event_recorded": True,
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            payload = profile_recovery_proof_status_payload(root)

        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["missing_sites"], [])
        self.assertEqual(payload["incomplete_sites"], [])
        self.assertEqual(payload["schema_issues"], {})
        self.assertEqual(payload["proof_issues"], {})
        self.assertEqual(payload["stale_artifacts"], {})

    def test_profile_recovery_proof_cli_writes_ready_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fresh_generated_at = utc_now_live_check()
            for site in ("saramin", "jobkorea"):
                (root / f"portal_profile_recovery_{site}.json").write_text(
                    json.dumps(
                        {
                            "kind": "portal_profile_recovery_smoke",
                            "site": site,
                            "worker_id": "default",
                            "keyword": "backend",
                            "generated_at": fresh_generated_at,
                            "recovery_policy": "snapshot_only_no_auto_relogin",
                            "auto_relogin_disabled": True,
                            "mode": "guarded",
                            "status": "searched",
                            "profile_deleted_before_start": True,
                            "reauth_cause": "profile_corrupt",
                            "snapshot_capture_required": True,
                            "snapshot_capture_policy": "required",
                            "snapshot_captured": True,
                            "retried_after_recovery": True,
                            "recovery": {
                                "recovered": True,
                                "recovered_by": "snapshot_reinject",
                                "reauth_event_recorded": True,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
            output = root / "profile_recovery_proof.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.multi_position_sourcing.portal_live_check",
                    "profile-recovery-proof",
                    "--artifact-root",
                    str(root),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "ready")
        self.assertNotIn("storage_state", json.dumps(payload, ensure_ascii=False))

    def test_profile_recovery_proof_cli_exits_nonzero_when_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "profile_recovery_proof.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.multi_position_sourcing.portal_live_check",
                    "profile-recovery-proof",
                    "--artifact-root",
                    str(root),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 2, msg=result.stderr)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["status"], "missing")
        self.assertEqual(payload["action_hint"], "profile_recovery_smoke_missing")

    def test_safe_profile_recovery_not_run_payload_does_not_delete_or_leak_snapshot(self) -> None:
        config = LiveSearchConfig(
            channel="jobkorea",
            keyword="backend",
            worker_id="default",
            profile_root=Path("/tmp/valuehire-test-profiles"),
            chrome_cdp_endpoint="http://127.0.0.1:9222",
            headless=False,
            searches_today=0,
            no_sleep=True,
            disable_auto_relogin=True,
            delete_profile_before_start=True,
            confirm_delete_profile="/tmp/valuehire-test-profiles/jobkorea/default",
        )
        payload = safe_profile_recovery_not_run_payload(
            config,
            metadata={
                "kind": "session_snapshot_metadata",
                "status": "unavailable",
                "snapshot_present": False,
                "error_type": "SupabaseSessionStoreError",
            },
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["status"], "not_run")
        self.assertIsInstance(payload["generated_at"], str)
        self.assertFalse(payload["profile_deleted_before_start"])
        self.assertEqual(
            payload["recovery"],
            {
                "recovered": False,
                "recovered_by": "",
                "reauth_event_recorded": False,
                "pause_site": False,
                "discord_alert_sent": False,
            },
        )
        self.assertEqual(payload["snapshot_metadata_status"], "unavailable")
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("cookie", encoded.lower())

    def test_profile_recovery_proof_separates_schema_from_unmet_proof_conditions(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for site in ("saramin", "jobkorea"):
                config = LiveSearchConfig(
                    channel=site,  # type: ignore[arg-type]
                    keyword="backend",
                    worker_id="default",
                    profile_root=Path("/tmp/valuehire-test-profiles"),
                    chrome_cdp_endpoint="http://127.0.0.1:9222",
                    headless=False,
                    searches_today=0,
                    no_sleep=True,
                    disable_auto_relogin=True,
                    delete_profile_before_start=True,
                    confirm_delete_profile=f"/tmp/valuehire-test-profiles/{site}/default",
                )
                payload = safe_profile_recovery_not_run_payload(
                    config,
                    metadata={
                        "kind": "session_snapshot_metadata",
                        "status": "unavailable",
                        "snapshot_present": False,
                    },
                )
                (root / f"portal_profile_recovery_{site}.json").write_text(
                    json.dumps(payload),
                    encoding="utf-8",
                )

            proof = profile_recovery_proof_status_payload(root)

        self.assertFalse(proof["ready"])
        self.assertEqual(proof["schema_issues"], {})
        self.assertIn("saramin", proof["proof_issues"])
        self.assertIn("status_searched", proof["proof_issues"]["saramin"])  # type: ignore[index]
        self.assertIn("snapshot_captured", proof["proof_issues"]["jobkorea"])  # type: ignore[index]

    def test_profile_recovery_proof_rejects_stale_complete_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for site in ("saramin", "jobkorea"):
                (root / f"portal_profile_recovery_{site}.json").write_text(
                    json.dumps(
                        {
                            "kind": "portal_profile_recovery_smoke",
                            "site": site,
                            "worker_id": "default",
                            "keyword": "backend",
                            "generated_at": "2026-06-07T00:00:00+00:00",
                            "recovery_policy": "snapshot_only_no_auto_relogin",
                            "auto_relogin_disabled": True,
                            "mode": "guarded",
                            "status": "searched",
                            "profile_deleted_before_start": True,
                            "reauth_cause": "profile_corrupt",
                            "snapshot_capture_required": True,
                            "snapshot_capture_policy": "required",
                            "snapshot_captured": True,
                            "retried_after_recovery": True,
                            "recovery": {
                                "recovered": True,
                                "recovered_by": "snapshot_reinject",
                                "reauth_event_recorded": True,
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            with patch(
                "tools.multi_position_sourcing.portal_live_check.utc_now_live_check",
                return_value="2026-06-09T12:00:00+00:00",
            ):
                proof = profile_recovery_proof_status_payload(root)

        self.assertFalse(proof["ready"])
        self.assertEqual(proof["status"], "failed")
        self.assertEqual(proof["action_hint"], "profile_recovery_smoke_stale")
        self.assertEqual(proof["schema_issues"], {})
        self.assertEqual(proof["proof_issues"], {})
        self.assertEqual(set(proof["stale_artifacts"]), {"saramin", "jobkorea"})

    def test_portal_dod_audit_passes_with_complete_safe_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_status = root / "portal_session_status.json"
            session_status.write_text(
                json.dumps(
                    complete_preflight_payload("saramin", "jobkorea", "linkedin_rps")
                ),
                encoding="utf-8",
            )
            search_paths: list[Path] = []
            restart_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                search_payload = {
                    "site": site,
                    "worker_id": "default",
                    "keyword": "backend",
                    "mode": "guarded",
                    "status": "searched",
                    "reason": "searched on persistent profile",
                    "reauth_cause": "",
                    "snapshot_capture_required": True,
                    "snapshot_capture_policy": "required",
                    "snapshot_captured": True,
                    "retried_after_recovery": False,
                    "profile_deleted_before_start": False,
                }
                search_path = root / f"search_{site}.json"
                search_path.write_text(json.dumps(search_payload), encoding="utf-8")
                search_paths.append(search_path)
                restart_path = root / f"restart_smoke_{site}.json"
                restart_path.write_text(
                    json.dumps(
                        safe_restart_smoke_payload(
                            site=site,  # type: ignore[arg-type]
                            worker_id="default",
                            keyword="backend",
                            first=search_payload,
                            second=search_payload,
                        )
                    ),
                    encoding="utf-8",
                )
                restart_paths.append(restart_path)
            recovery_paths: list[Path] = []
            for site in ("saramin", "jobkorea"):
                path = root / f"profile_recovery_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "portal_profile_recovery_smoke",
                            "site": site,
                            "worker_id": "default",
                            "keyword": "backend",
                            "generated_at": "2026-06-09T00:00:00+00:00",
                            "recovery_policy": "snapshot_only_no_auto_relogin",
                            "auto_relogin_disabled": True,
                            "mode": "guarded",
                            "status": "searched",
                            "reason": "retried after snapshot restore",
                            "reauth_cause": "profile_corrupt",
                            "snapshot_capture_required": True,
                            "snapshot_capture_policy": "required",
                            "snapshot_captured": True,
                            "retried_after_recovery": True,
                            "profile_deleted_before_start": True,
                            "recovery": {
                                "recovered": True,
                                "recovered_by": "snapshot_reinject",
                                "reauth_event_recorded": True,
                                "pause_site": False,
                                "discord_alert_sent": False,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                recovery_paths.append(path)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            discord_alert = root / "discord_alert.json"
            discord_alert.write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "delivered": True,
                        "reauth_event_recorded": True,
                        "event": complete_linkedin_discord_event(),
                    }
                ),
                encoding="utf-8",
            )
            weekly_counts = root / "weekly_counts.json"
            weekly_rows = [
                {
                    "site": "saramin",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "jobkorea",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "linkedin_rps",
                    "worker_id": "default",
                    "cause": "forced_logout",
                    "recovered_by": "human",
                    "count": 1,
                },
            ]
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08T00:00:00+00:00",
                        "total_events": 3,
                        "rows": weekly_rows,
                    }
                ),
                encoding="utf-8",
            )
            weekly_trend = root / "weekly_trend.json"
            weekly_trend.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_trend",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "latest_week_start": "2026-06-08",
                        "weeks_observed": 2,
                        "latest_total_events": 3,
                        "previous_total_events": 0,
                        "delta_from_previous_week": 3,
                        "latest_week_zero": False,
                        "zero_event_weeks": 1,
                        "error_types": [],
                        "weeks": [
                            {
                                "week_start": "2026-06-01",
                                "status": "present",
                                "total_events": 0,
                                "rows": [],
                            },
                            {
                                "week_start": "2026-06-08",
                                "status": "present",
                                "total_events": 3,
                                "rows": weekly_rows,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=session_status,
                search_artifact_paths=tuple(search_paths),
                profile_recovery_artifact_paths=tuple(recovery_paths),
                restart_smoke_artifact_paths=tuple(restart_paths),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
                discord_alert_path=discord_alert,
                weekly_counts_path=weekly_counts,
                weekly_trend_path=weekly_trend,
                secret_scan_paths=(root,),
            )

        self.assertTrue(payload["passed"])
        self.assertIsInstance(payload["generated_at"], str)
        statuses = {item["id"]: item["status"] for item in payload["requirements"]}  # type: ignore[index]
        self.assertEqual(set(statuses.values()), {"passed"})
        restart_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_1_restart_search_all_sites"
        )
        self.assertIn("modes=", restart_requirement["evidence"])
        self.assertIn("preflight_generated_at=2026-06-09T00:00:00+00:00", restart_requirement["evidence"])
        self.assertIn("preflight_snapshot_capture=all_ready_sessions_captured", restart_requirement["evidence"])

    def test_portal_dod_audit_requires_preflight_generated_at_for_restart_pass(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_status = root / "portal_session_status.json"
            session_status.write_text(
                json.dumps(
                    {
                        "portal_sessions": [
                            complete_preflight_session("saramin"),
                            complete_preflight_session("jobkorea"),
                            complete_preflight_session("linkedin_rps"),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            preflight_status = root / "portal_session_preflight_status_latest.json"
            preflight_status.write_text(
                json.dumps(
                    {
                        "kind": "portal_session_preflight_status",
                        "generated_at": "2026-06-09T00:01:00+00:00",
                        "status": "stale_schema",
                        "ready": False,
                        "preflight_generated_at": "unknown",
                        "schema_issues": ["generated_at"],
                        "snapshot_issues": [],
                        "not_ready_channels": [],
                        "action_hint": "portal_session_preflight_schema_stale",
                    }
                ),
                encoding="utf-8",
            )
            restart_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                search_payload = {
                    "site": site,
                    "worker_id": "default",
                    "keyword": "backend",
                    "mode": "guarded",
                    "status": "searched",
                    "reason": "searched on persistent profile",
                    "reauth_cause": "",
                    "snapshot_capture_required": True,
                    "snapshot_capture_policy": "required",
                    "snapshot_captured": True,
                    "retried_after_recovery": False,
                    "profile_deleted_before_start": False,
                }
                restart_path = root / f"restart_smoke_{site}.json"
                restart_path.write_text(
                    json.dumps(
                        safe_restart_smoke_payload(
                            site=site,  # type: ignore[arg-type]
                            worker_id="default",
                            keyword="backend",
                            first=search_payload,
                            second=search_payload,
                        )
                    ),
                    encoding="utf-8",
                )
                restart_paths.append(restart_path)

            payload = build_dod_audit_payload(
                session_status_path=session_status,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                preflight_status_path=preflight_status,
                restart_smoke_artifact_paths=tuple(restart_paths),
            )

        restart_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_1_restart_search_all_sites"
        )
        self.assertEqual(restart_requirement["status"], "failed")
        self.assertIn("missing_generated_at", restart_requirement["evidence"])
        self.assertIn("preflight_generated_at=unknown", restart_requirement["evidence"])
        self.assertIn("preflight_status=stale_schema", restart_requirement["evidence"])
        self.assertIn("preflight_action_hint=portal_session_preflight_schema_stale", restart_requirement["evidence"])

    def test_portal_dod_audit_requires_preflight_snapshot_capture_for_ready_sessions(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_status = root / "portal_session_status.json"
            session_status.write_text(
                json.dumps(
                    {
                        "kind": "portal_session_preflight",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "ready": True,
                        "portal_sessions": [
                            {
                                "channel": "saramin",
                                "ready": True,
                                "snapshot_capture_required": True,
                                "snapshot_captured": False,
                                "snapshot_capture_status": "unavailable",
                            },
                            complete_preflight_session("jobkorea"),
                            complete_preflight_session("linkedin_rps"),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            restart_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                search_payload = {
                    "site": site,
                    "worker_id": "default",
                    "keyword": "backend",
                    "mode": "guarded",
                    "status": "searched",
                    "reason": "searched on persistent profile",
                    "reauth_cause": "",
                    "snapshot_capture_required": True,
                    "snapshot_capture_policy": "required",
                    "snapshot_captured": True,
                    "retried_after_recovery": False,
                    "profile_deleted_before_start": False,
                }
                restart_path = root / f"restart_smoke_{site}.json"
                restart_path.write_text(
                    json.dumps(
                        safe_restart_smoke_payload(
                            site=site,  # type: ignore[arg-type]
                            worker_id="default",
                            keyword="backend",
                            first=search_payload,
                            second=search_payload,
                        )
                    ),
                    encoding="utf-8",
                )
                restart_paths.append(restart_path)

            payload = build_dod_audit_payload(
                session_status_path=session_status,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                restart_smoke_artifact_paths=tuple(restart_paths),
            )

        restart_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_1_restart_search_all_sites"
        )
        self.assertEqual(restart_requirement["status"], "failed")
        self.assertIn("ready preflight sessions did not prove", restart_requirement["evidence"])
        self.assertIn("saramin:snapshot_not_captured", restart_requirement["evidence"])

    def test_portal_dod_audit_rejects_profile_only_restart_smoke_as_full_dod(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_status = root / "portal_session_status.json"
            session_status.write_text(
                json.dumps(
                    complete_preflight_payload("saramin", "jobkorea", "linkedin_rps")
                ),
                encoding="utf-8",
            )
            restart_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                search_payload = safe_profile_only_result_payload(
                    PortalSearchAttempt(
                        channel=site,  # type: ignore[arg-type]
                        worker_id="default",
                        keyword="backend",
                        status="searched",
                        reason="M1 profile-only search",
                        url="https://example.test/search",
                    )
                )
                path = root / f"restart_smoke_{site}.json"
                path.write_text(
                    json.dumps(
                        safe_restart_smoke_payload(
                            site=site,  # type: ignore[arg-type]
                            worker_id="default",
                            keyword="backend",
                            first=search_payload,
                            second=search_payload,
                        )
                    ),
                    encoding="utf-8",
                )
                restart_paths.append(path)
            restart_proof = root / "portal_restart_smoke_proof_status_latest.json"
            restart_proof.write_text(
                json.dumps(
                    {
                        "kind": "portal_restart_smoke_proof_status",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "failed",
                        "ready": False,
                        "missing_sites": [],
                        "incomplete_sites": [],
                        "non_guarded_sites": ["saramin", "jobkorea", "linkedin_rps"],
                        "schema_issues": {},
                        "action_hint": "restart_smoke_incomplete",
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=session_status,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                restart_smoke_artifact_paths=tuple(restart_paths),
                restart_smoke_proof_path=restart_proof,
            )

        statuses = {item["id"]: item["status"] for item in payload["requirements"]}  # type: ignore[index]
        restart_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_1_restart_search_all_sites"
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(statuses["dod_1_restart_search_all_sites"], "failed")
        self.assertIn("non_guarded_restart", restart_requirement["evidence"])
        self.assertIn("profile_only", restart_requirement["evidence"])
        self.assertIn("restart_smoke_proof_status=failed", restart_requirement["evidence"])
        self.assertIn("restart_smoke_action_hint=restart_smoke_incomplete", restart_requirement["evidence"])
        self.assertIn("restart_smoke_non_guarded_sites", restart_requirement["evidence"])

    def test_portal_dod_audit_reports_stale_restart_smoke_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_status = root / "portal_session_status.json"
            session_status.write_text(
                json.dumps(
                    complete_preflight_payload("saramin", "jobkorea", "linkedin_rps")
                ),
                encoding="utf-8",
            )
            full_guarded = {
                "site": "saramin",
                "worker_id": "default",
                "keyword": "backend",
                "mode": "guarded",
                "status": "searched",
                "reauth_cause": "",
                "snapshot_capture_required": True,
                "snapshot_capture_policy": "required",
                "snapshot_captured": True,
                "retried_after_recovery": False,
                "profile_deleted_before_start": False,
            }
            restart_paths: list[Path] = []
            for site in ("saramin", "linkedin_rps"):
                path = root / f"restart_smoke_{site}.json"
                path.write_text(
                    json.dumps(
                        safe_restart_smoke_payload(
                            site=site,  # type: ignore[arg-type]
                            worker_id="default",
                            keyword="backend",
                            first={**full_guarded, "site": site},
                            second={**full_guarded, "site": site},
                        )
                    ),
                    encoding="utf-8",
                )
                restart_paths.append(path)
            stale_lifecycle = {
                "site": "jobkorea",
                "worker_id": "default",
                "keyword": "backend",
                "status": "searched",
                "reauth_cause": "",
                "snapshot_captured": True,
                "retried_after_recovery": False,
                "profile_deleted_before_start": False,
            }
            stale_path = root / "restart_smoke_jobkorea.json"
            stale_path.write_text(
                json.dumps(
                    {
                        "kind": "portal_restart_search_smoke",
                        "site": "jobkorea",
                        "worker_id": "default",
                        "keyword": "backend",
                        "worker_restarts": 2,
                        "passed": True,
                        "first": stale_lifecycle,
                        "second": stale_lifecycle,
                    }
                ),
                encoding="utf-8",
            )
            restart_paths.append(stale_path)

            payload = build_dod_audit_payload(
                session_status_path=session_status,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                restart_smoke_artifact_paths=tuple(restart_paths),
            )

        restart_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_1_restart_search_all_sites"
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(restart_requirement["status"], "failed")
        self.assertIn("schema_issues", restart_requirement["evidence"])
        self.assertIn("generated_at", restart_requirement["evidence"])
        self.assertIn("jobkorea", restart_requirement["evidence"])
        self.assertIn("missing_top_level", restart_requirement["evidence"])
        self.assertIn("first_missing", restart_requirement["evidence"])

    def test_portal_dod_audit_requires_restart_smoke_generated_at_for_pass(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_status = root / "portal_session_status.json"
            session_status.write_text(
                json.dumps(complete_preflight_payload("saramin", "jobkorea", "linkedin_rps")),
                encoding="utf-8",
            )
            restart_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                search_payload = {
                    "site": site,
                    "worker_id": "default",
                    "keyword": "backend",
                    "mode": "guarded",
                    "status": "searched",
                    "reauth_cause": "",
                    "snapshot_capture_required": True,
                    "snapshot_capture_policy": "required",
                    "snapshot_captured": True,
                    "retried_after_recovery": False,
                    "profile_deleted_before_start": False,
                }
                restart_payload = safe_restart_smoke_payload(
                    site=site,  # type: ignore[arg-type]
                    worker_id="default",
                    keyword="backend",
                    first=search_payload,
                    second=search_payload,
                )
                if site == "jobkorea":
                    restart_payload.pop("generated_at", None)
                path = root / f"restart_smoke_{site}.json"
                path.write_text(json.dumps(restart_payload), encoding="utf-8")
                restart_paths.append(path)

            payload = build_dod_audit_payload(
                session_status_path=session_status,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                restart_smoke_artifact_paths=tuple(restart_paths),
            )

        restart_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_1_restart_search_all_sites"
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(restart_requirement["status"], "failed")
        self.assertIn("generated_at", restart_requirement["evidence"])
        self.assertIn("jobkorea", restart_requirement["evidence"])

    def test_latest_default_audit_artifacts_prefers_full_restart_over_profile_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = latest_default_audit_artifacts(root)
            self.assertEqual(defaults.supabase_access_path, root / "portal_supabase_access_latest.json")
            self.assertEqual(defaults.preflight_status_path, root / "portal_session_preflight_status_latest.json")
            self.assertEqual(
                defaults.restart_smoke_proof_path,
                root / "portal_restart_smoke_proof_status_latest.json",
            )
            self.assertEqual(
                defaults.profile_recovery_proof_path,
                root / "portal_profile_recovery_proof_status_latest.json",
            )
            defaults.session_status_path.write_text(
                json.dumps(
                    complete_preflight_payload("saramin", "jobkorea", "linkedin_rps")
                ),
                encoding="utf-8",
            )
            profile_only = safe_profile_only_result_payload(
                PortalSearchAttempt(
                    channel="jobkorea",
                    worker_id="default",
                    keyword="backend",
                    status="searched",
                    reason="M1 profile-only search",
                    url="https://example.test/profile-only",
                )
            )
            (root / "portal_restart_smoke_jobkorea_profile_only.json").write_text(
                json.dumps(
                    safe_restart_smoke_payload(
                        site="jobkorea",
                        worker_id="default",
                        keyword="backend",
                        first=profile_only,
                        second=profile_only,
                    )
                ),
                encoding="utf-8",
            )
            full_guarded = {
                "site": "jobkorea",
                "worker_id": "default",
                "keyword": "backend",
                "mode": "guarded",
                "status": "searched",
                "reauth_cause": "",
                "snapshot_capture_required": True,
                "snapshot_capture_policy": "required",
                "snapshot_captured": True,
                "retried_after_recovery": False,
                "profile_deleted_before_start": False,
            }
            (root / "portal_restart_smoke_jobkorea.json").write_text(
                json.dumps(
                    safe_restart_smoke_payload(
                        site="jobkorea",
                        worker_id="default",
                        keyword="backend",
                        first=full_guarded,
                        second=full_guarded,
                    )
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=defaults.session_status_path,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                restart_smoke_artifact_paths=defaults.restart_smoke_artifact_paths,
            )

        restart_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_1_restart_search_all_sites"
        )
        self.assertIn("'jobkorea': 'guarded'", restart_requirement["evidence"])

    def test_restart_smoke_proof_status_falls_back_to_profile_only_when_full_is_invalid(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_only = safe_restart_smoke_payload(
                site="jobkorea",
                worker_id="default",
                keyword="backend",
                first=safe_profile_only_result_payload(
                    PortalSearchAttempt(
                        channel="jobkorea",
                        worker_id="default",
                        keyword="backend",
                        status="searched",
                        reason="profile-only search",
                    )
                ),
                second=safe_profile_only_result_payload(
                    PortalSearchAttempt(
                        channel="jobkorea",
                        worker_id="default",
                        keyword="backend",
                        status="searched",
                        reason="profile-only search",
                    )
                ),
            )
            (root / "portal_restart_smoke_jobkorea_profile_only.json").write_text(
                json.dumps(profile_only),
                encoding="utf-8",
            )
            (root / "portal_restart_smoke_jobkorea.json").write_text(
                json.dumps(
                    {
                        "kind": "portal_restart_search_smoke",
                        "site": "jobkorea",
                        "worker_id": "default",
                        "keyword": "backend",
                        "worker_restarts": 2,
                        "passed": True,
                        "first": {
                            "site": "jobkorea",
                            "worker_id": "default",
                            "keyword": "backend",
                            "status": "searched",
                            "reauth_cause": "",
                            "snapshot_capture_required": True,
                            "snapshot_capture_policy": "required",
                            "snapshot_captured": True,
                            "retried_after_recovery": False,
                            "profile_deleted_before_start": False,
                        },
                        "second": {
                            "site": "jobkorea",
                            "worker_id": "default",
                            "keyword": "backend",
                            "status": "searched",
                            "reauth_cause": "",
                            "snapshot_capture_required": True,
                            "snapshot_capture_policy": "required",
                            "snapshot_captured": True,
                            "retried_after_recovery": False,
                            "profile_deleted_before_start": False,
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = restart_smoke_proof_status_payload(root)

        self.assertFalse(payload["ready"])
        self.assertNotIn("jobkorea", payload["schema_issues"])
        self.assertIn("jobkorea", payload["incomplete_sites"])
        self.assertIn("jobkorea", payload["non_guarded_sites"])

    def test_restart_smoke_proof_status_uses_legacy_linkedin_profile_only_filename(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_only = safe_restart_smoke_payload(
                site="linkedin_rps",
                worker_id="default",
                keyword="backend",
                first=safe_profile_only_result_payload(
                    PortalSearchAttempt(
                        channel="linkedin_rps",
                        worker_id="default",
                        keyword="backend",
                        status="searched",
                        reason="profile-only search",
                    )
                ),
                second=safe_profile_only_result_payload(
                    PortalSearchAttempt(
                        channel="linkedin_rps",
                        worker_id="default",
                        keyword="backend",
                        status="searched",
                        reason="profile-only search",
                    )
                ),
            )
            (root / "portal_restart_smoke_linkedin_profile_only.json").write_text(
                json.dumps(profile_only),
                encoding="utf-8",
            )

            payload = restart_smoke_proof_status_payload(root)

        self.assertIn("linkedin_rps", payload["paths"])
        self.assertEqual(
            payload["paths"]["linkedin_rps"],
            str(root / "portal_restart_smoke_linkedin_profile_only.json"),
        )
        self.assertNotIn("linkedin_rps", payload["missing_sites"])
        self.assertFalse(payload["ready"])

    def test_latest_default_audit_skips_missing_optional_paths_in_secret_scan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            defaults = latest_default_audit_artifacts(root)
            defaults.session_status_path.write_text(
                json.dumps(
                    complete_preflight_payload("saramin", "jobkorea", "linkedin_rps")
                ),
                encoding="utf-8",
            )
            for site, path in (
                ("saramin", root / "portal_snapshot_metadata_saramin.json"),
                ("jobkorea", root / "portal_snapshot_metadata_jobkorea.json"),
                ("linkedin_rps", root / "portal_snapshot_metadata_linkedin_rps.json"),
            ):
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
            defaults.discord_alert_path.write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "delivered": True,
                        "reauth_event_recorded": True,
                        "event": complete_linkedin_discord_event(),
                    }
                ),
                encoding="utf-8",
            )
            defaults.weekly_counts_path.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "rows": [
                            {
                                "site": "saramin",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": 1,
                            },
                            {
                                "site": "jobkorea",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": 1,
                            },
                            {
                                "site": "linkedin_rps",
                                "cause": "forced_logout",
                                "recovered_by": "human",
                                "count": 1,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            scan_dir = root / "empty_scan"
            scan_dir.mkdir()
            output = root / "audit.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.multi_position_sourcing.portal_dod_audit",
                    "--latest-defaults",
                    "--artifact-root",
                    str(root),
                    "--secret-scan-path",
                    str(scan_dir),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2, msg=result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
        secret_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_6_no_plaintext_session_output"
        )
        self.assertEqual(secret_requirement["status"], "passed")
        self.assertNotIn(":missing", secret_requirement["evidence"])

    def test_latest_default_audit_scans_artifact_root_for_plain_state_producers(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            producer = root / "legacy_probe.py"
            producer.write_text(
                "SECRET = 'must-not-leak'\n"
                "await context.storage_state(path=str(ROOT / 'artifacts' / 'saramin_storage_state.json'))\n",
                encoding="utf-8",
            )
            scan_dir = root / "empty_scan"
            scan_dir.mkdir()
            output = root / "audit.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.multi_position_sourcing.portal_dod_audit",
                    "--latest-defaults",
                    "--artifact-root",
                    str(root),
                    "--secret-scan-path",
                    str(scan_dir),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2, msg=result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))

        secret_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_6_no_plaintext_session_output"
        )
        self.assertEqual(secret_requirement["status"], "failed")
        self.assertIn("producer scripts", secret_requirement["evidence"])
        self.assertIn("legacy_probe.py", secret_requirement["evidence"])
        self.assertNotIn("must-not-leak", secret_requirement["evidence"])

    def test_latest_default_audit_scans_artifact_root_for_camel_case_plain_state_producers(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            producer = root / "legacy_probe.ts"
            producer.write_text(
                "const secret = 'must-not-leak';\n"
                "await context.storageState({ path: 'artifacts/jobkorea_storage_state.json' });\n",
                encoding="utf-8",
            )
            scan_dir = root / "empty_scan"
            scan_dir.mkdir()
            output = root / "audit.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.multi_position_sourcing.portal_dod_audit",
                    "--latest-defaults",
                    "--artifact-root",
                    str(root),
                    "--secret-scan-path",
                    str(scan_dir),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2, msg=result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))

        secret_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_6_no_plaintext_session_output"
        )
        self.assertEqual(secret_requirement["status"], "failed")
        self.assertIn("producer scripts", secret_requirement["evidence"])
        self.assertIn("legacy_probe.ts", secret_requirement["evidence"])
        self.assertNotIn("must-not-leak", secret_requirement["evidence"])

    def test_portal_dod_audit_fails_when_supabase_schema_proof_is_not_ready(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_proof = root / "schema_proof.json"
            schema_proof.write_text(
                json.dumps(
                    {
                        "kind": "supabase_session_schema_proof",
                        "ready": False,
                        "status": "failed",
                        "action_hint": "apply_supabase_session_schema",
                        "failed_checks": ["encrypted_snapshot_envelope_constraint"],
                        "checks": [
                            {
                                "name": "encrypted_snapshot_envelope_constraint",
                                "status": "failed",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                supabase_schema_proof_path=schema_proof,
            )

        requirements = {item["id"]: item for item in payload["requirements"]}  # type: ignore[index]
        self.assertEqual(requirements["dod_6_no_plaintext_session_output"]["status"], "failed")
        self.assertIn("schema_proof_action_hint=apply_supabase_session_schema", requirements["dod_6_no_plaintext_session_output"]["evidence"])
        self.assertIn("encrypted_snapshot_envelope_constraint", requirements["dod_6_no_plaintext_session_output"]["evidence"])
        self.assertEqual(requirements["dod_7_reauth_events_weekly_observable"]["status"], "failed")
        self.assertIn("Supabase reauth schema proof is not ready", requirements["dod_7_reauth_events_weekly_observable"]["evidence"])
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("storage_state", encoded)
        self.assertNotIn("create table", encoded.lower())

    def test_latest_default_audit_scans_artifact_root_for_plain_state_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plaintext_state = root / "legacy_session.json"
            plaintext_state.write_text(
                json.dumps(
                    {
                        "cookies": [{"domain": ".jobkorea.co.kr", "name": "sid", "value": "must-not-leak"}],
                        "origins": [],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "audit.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.multi_position_sourcing.portal_dod_audit",
                    "--latest-defaults",
                    "--artifact-root",
                    str(root),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2, msg=result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))

        secret_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_6_no_plaintext_session_output"
        )
        self.assertEqual(secret_requirement["status"], "failed")
        self.assertIn("plaintext Playwright storage state artifacts", secret_requirement["evidence"])
        self.assertIn("legacy_session.json", secret_requirement["evidence"])
        self.assertNotIn("must-not-leak", secret_requirement["evidence"])

    def test_latest_default_audit_scans_artifact_root_for_camel_case_plain_state_file_names(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plaintext_state = root / "legacyStorageState.json"
            plaintext_state.write_text(
                json.dumps({"note": "legacy plaintext session export placeholder"}),
                encoding="utf-8",
            )
            output = root / "audit.json"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.multi_position_sourcing.portal_dod_audit",
                    "--latest-defaults",
                    "--artifact-root",
                    str(root),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2, msg=result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))

        secret_requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_6_no_plaintext_session_output"
        )
        self.assertEqual(secret_requirement["status"], "failed")
        self.assertIn("plaintext Playwright storage state artifacts", secret_requirement["evidence"])
        self.assertIn("legacyStorageState.json", secret_requirement["evidence"])
        self.assertNotIn("legacy plaintext session export placeholder", secret_requirement["evidence"])

    def test_portal_dod_audit_fails_when_scan_path_has_plain_storage_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            plaintext_state = root / "plain_session.json"
            plaintext_state.write_text(
                json.dumps(
                    {
                        "cookies": [{"domain": ".saramin.co.kr", "name": "sid", "value": "must-not-leak"}],
                        "origins": [],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
                secret_scan_paths=(root,),
            )

        requirement = next(
            item for item in payload["requirements"] if item["id"] == "dod_6_no_plaintext_session_output"  # type: ignore[index]
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(requirement["status"], "failed")  # type: ignore[index]
        self.assertIn("plain_session.json", requirement["evidence"])  # type: ignore[index]
        self.assertNotIn("must-not-leak", requirement["evidence"])  # type: ignore[index]

    def test_portal_dod_audit_fails_when_log_embeds_plain_storage_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            log_file = root / "portal_error.log"
            log_file.write_text(
                "error while capturing portal session: "
                + json.dumps(
                    {
                        "cookies": [{"domain": ".jobkorea.co.kr", "name": "sid", "value": "must-not-leak"}],
                        "origins": [{"origin": "https://www.jobkorea.co.kr", "localStorage": []}],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
                secret_scan_paths=(root,),
            )

        requirement = next(
            item for item in payload["requirements"] if item["id"] == "dod_6_no_plaintext_session_output"  # type: ignore[index]
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(requirement["status"], "failed")  # type: ignore[index]
        self.assertIn("portal_error.log", requirement["evidence"])  # type: ignore[index]
        self.assertNotIn("must-not-leak", requirement["evidence"])  # type: ignore[index]

    def test_portal_dod_audit_fails_when_safe_artifact_contains_secret_url_terms(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            leaky_artifact = root / "portal_result.json"
            leaky_artifact.write_text(
                json.dumps(
                    {
                        "url": "https://user:pass@www.saramin.co.kr/search?cookie=session-secret#token-secret",
                        "note": "signature-secret",
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(leaky_artifact,),
                profile_recovery_artifact_paths=(),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
            )

        requirement = next(
            item for item in payload["requirements"] if item["id"] == "dod_6_no_plaintext_session_output"  # type: ignore[index]
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(requirement["status"], "failed")  # type: ignore[index]
        self.assertIn("portal_result.json", requirement["evidence"])  # type: ignore[index]
        self.assertIn("user:pass", requirement["evidence"])  # type: ignore[index]
        self.assertIn("session-secret", requirement["evidence"])  # type: ignore[index]
        self.assertIn("token-secret", requirement["evidence"])  # type: ignore[index]

    def test_portal_dod_audit_fails_when_safe_artifact_contains_camel_case_storage_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            leaky_artifact = root / "portal_result.json"
            leaky_artifact.write_text(
                json.dumps(
                    {
                        "storageState": {"cookies": [{"value": "must-not-leak"}]},
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(leaky_artifact,),
                profile_recovery_artifact_paths=(),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
            )

        requirement = next(
            item for item in payload["requirements"] if item["id"] == "dod_6_no_plaintext_session_output"  # type: ignore[index]
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(requirement["status"], "failed")  # type: ignore[index]
        self.assertIn("portal_result.json", requirement["evidence"])  # type: ignore[index]
        self.assertIn("storagestate", requirement["evidence"])  # type: ignore[index]
        self.assertNotIn("must-not-leak", requirement["evidence"])  # type: ignore[index]

    def test_portal_dod_audit_fails_when_scan_path_has_plain_storage_state_producer(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            producer = root / "legacy_probe.py"
            producer.write_text(
                "SECRET = 'must-not-leak'\n"
                "await context.storage_state(path=str(ROOT / 'artifacts' / 'portal_search_storage_state.json'))\n",
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
                secret_scan_paths=(root,),
            )

        requirement = next(
            item for item in payload["requirements"] if item["id"] == "dod_6_no_plaintext_session_output"  # type: ignore[index]
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(requirement["status"], "failed")  # type: ignore[index]
        self.assertIn("producer scripts", requirement["evidence"])  # type: ignore[index]
        self.assertIn("legacy_probe.py", requirement["evidence"])  # type: ignore[index]
        self.assertNotIn("must-not-leak", requirement["evidence"])  # type: ignore[index]

    def test_portal_dod_audit_fails_when_js_context_uses_plain_storage_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            producer = root / "legacy_loader.js"
            producer.write_text(
                "const secret = 'must-not-leak';\n"
                "await browser.newContext({ storageState: 'artifacts/linkedin_storage_state.json' });\n",
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
                secret_scan_paths=(root,),
            )

        requirement = next(
            item for item in payload["requirements"] if item["id"] == "dod_6_no_plaintext_session_output"  # type: ignore[index]
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(requirement["status"], "failed")  # type: ignore[index]
        self.assertIn("producer scripts", requirement["evidence"])  # type: ignore[index]
        self.assertIn("legacy_loader.js", requirement["evidence"])  # type: ignore[index]
        self.assertNotIn("must-not-leak", requirement["evidence"])  # type: ignore[index]

    def test_portal_dod_audit_fails_when_persistent_context_receives_storage_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            python_producer = root / "persistent_loader.py"
            python_producer.write_text(
                "SECRET = 'must-not-leak'\n"
                "await chromium.launch_persistent_context(str(profile_dir), storage_state=state)\n",
                encoding="utf-8",
            )
            js_producer = root / "persistent_loader.js"
            js_producer.write_text(
                "const secret = 'must-not-leak';\n"
                "await chromium.launchPersistentContext(profileDir, { storageState });\n",
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
                secret_scan_paths=(root,),
            )

        requirement = next(
            item for item in payload["requirements"] if item["id"] == "dod_6_no_plaintext_session_output"  # type: ignore[index]
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(requirement["status"], "failed")  # type: ignore[index]
        self.assertIn("producer scripts", requirement["evidence"])  # type: ignore[index]
        self.assertIn("persistent_loader.py", requirement["evidence"])  # type: ignore[index]
        self.assertIn("persistent_loader.js", requirement["evidence"])  # type: ignore[index]
        self.assertNotIn("must-not-leak", requirement["evidence"])  # type: ignore[index]

    def test_portal_dod_audit_allows_safe_persistent_context_without_storage_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            safe_worker = root / "safe_worker.py"
            safe_worker.write_text(
                "STORAGE_STATE_ENC = 'metadata label only; no plaintext state export'\n"
                "await chromium.launch_persistent_context(str(profile_dir), headless=True)\n",
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
                secret_scan_paths=(root,),
            )

        requirement = next(
            item for item in payload["requirements"] if item["id"] == "dod_6_no_plaintext_session_output"  # type: ignore[index]
        )
        self.assertEqual(requirement["status"], "passed")  # type: ignore[index]
        self.assertNotIn("safe_worker.py", requirement["evidence"])  # type: ignore[index]

    def test_portal_dod_audit_fails_when_storage_state_is_dumped_indirectly(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            producer = root / "indirect_dump.py"
            producer.write_text(
                "SECRET = 'must-not-leak'\n"
                "state = await context.storage_state()\n"
                "Path('session-debug.json').write_text(json.dumps(state))\n",
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
                secret_scan_paths=(root,),
            )

        requirement = next(
            item for item in payload["requirements"] if item["id"] == "dod_6_no_plaintext_session_output"  # type: ignore[index]
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(requirement["status"], "failed")  # type: ignore[index]
        self.assertIn("producer scripts", requirement["evidence"])  # type: ignore[index]
        self.assertIn("indirect_dump.py", requirement["evidence"])  # type: ignore[index]
        self.assertNotIn("must-not-leak", requirement["evidence"])  # type: ignore[index]

    def test_portal_dod_audit_fails_when_artifacts_contain_browser_profile(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": True,
                            "status": "present",
                            "snapshot_kind": "current",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            profile_dir = root / "portal_profiles" / "jobkorea" / "default"
            profile_dir.mkdir(parents=True)
            (profile_dir / ".profile.lock").write_text("", encoding="utf-8")

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
                secret_scan_paths=(root,),
            )

        requirement = next(
            item for item in payload["requirements"] if item["id"] == "dod_6_no_plaintext_session_output"  # type: ignore[index]
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(requirement["status"], "failed")  # type: ignore[index]
        self.assertIn("persistent browser profile artifacts", requirement["evidence"])  # type: ignore[index]
        self.assertIn("portal_profiles", requirement["evidence"])  # type: ignore[index]

    def test_portal_dod_audit_marks_supabase_read_unavailable_artifacts_failed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"snapshot_metadata_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "worker_id": "default",
                            "snapshot_present": False,
                            "status": "unavailable",
                            "error_type": "SupabaseSessionStoreError",
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(path)
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "unavailable",
                        "week_start": "2026-06-09T00:00:00+00:00",
                        "total_events": 0,
                        "rows": [],
                        "error_type": "RuntimeError",
                    }
                ),
                encoding="utf-8",
            )
            weekly_trend = root / "weekly_trend.json"
            weekly_trend.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_trend",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "unavailable",
                        "latest_week_start": "2026-06-08",
                        "weeks_observed": 4,
                        "latest_total_events": 0,
                        "previous_total_events": 0,
                        "delta_from_previous_week": None,
                        "latest_week_zero": False,
                        "zero_event_weeks": 0,
                        "error_types": ["RuntimeError"],
                        "weeks": [],
                    }
                ),
                encoding="utf-8",
            )
            supabase_access = root / "supabase_access.json"
            supabase_access.write_text(
                json.dumps(
                    {
                        "kind": "supabase_access_check",
                        "ready": False,
                        "action_hint": "configured_service_role_key_rejected_by_supabase",
                        "checks": [
                            {
                                "name": "reauth_weekly_counts_rpc",
                                "status": "failed",
                                "error_type": "HTTPError",
                                "error_hint": "invalid_api_key",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
                weekly_counts_path=weekly_counts,
                weekly_trend_path=weekly_trend,
                supabase_access_path=supabase_access,
                secret_scan_paths=(root,),
            )

        requirements = {item["id"]: item for item in payload["requirements"]}  # type: ignore[index]
        self.assertFalse(payload["passed"])
        self.assertEqual(requirements["dod_6_no_plaintext_session_output"]["status"], "failed")
        self.assertIn(
            "could not be read",
            requirements["dod_6_no_plaintext_session_output"]["evidence"],
        )
        self.assertIn(
            "action_hint=configured_service_role_key_rejected_by_supabase",
            requirements["dod_6_no_plaintext_session_output"]["evidence"],
        )
        self.assertEqual(requirements["dod_7_reauth_events_weekly_observable"]["status"], "failed")
        self.assertIn(
            "could not be read",
            requirements["dod_7_reauth_events_weekly_observable"]["evidence"],
        )
        self.assertIn(
            "action_hint=configured_service_role_key_rejected_by_supabase",
            requirements["dod_7_reauth_events_weekly_observable"]["evidence"],
        )
        self.assertIn(
            "weekly_counts_generated_at=2026-06-09T00:00:00+00:00",
            requirements["dod_7_reauth_events_weekly_observable"]["evidence"],
        )
        self.assertIn(
            "weekly_trend_weeks_observed=4",
            requirements["dod_7_reauth_events_weekly_observable"]["evidence"],
        )
        self.assertIn(
            "weekly_trend_error_types=['RuntimeError']",
            requirements["dod_7_reauth_events_weekly_observable"]["evidence"],
        )
        self.assertNotIn("invalid_api_key", requirements["dod_6_no_plaintext_session_output"]["evidence"])
        self.assertNotIn("invalid_api_key", requirements["dod_7_reauth_events_weekly_observable"]["evidence"])

    def test_portal_dod_audit_marks_missing_profile_recovery_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_status = root / "portal_session_status.json"
            session_status.write_text(
                json.dumps(
                    complete_preflight_payload("saramin", "jobkorea", "linkedin_rps")
                ),
                encoding="utf-8",
            )
            search_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                path = root / f"search_{site}.json"
                path.write_text(
                    json.dumps(
                        {
                            "site": site,
                            "status": "searched",
                            "reauth_cause": "",
                            "retried_after_recovery": False,
                            "profile_deleted_before_start": False,
                        }
                    ),
                    encoding="utf-8",
                )
                search_paths.append(path)
            discord_alert = root / "discord_alert.json"
            discord_alert.write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "delivered": True,
                        "reauth_event_recorded": True,
                        "event": complete_linkedin_discord_event(),
                    }
                ),
                encoding="utf-8",
            )
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(json.dumps({"kind": "reauth_weekly_counts", "rows": []}), encoding="utf-8")

            payload = build_dod_audit_payload(
                session_status_path=session_status,
                search_artifact_paths=tuple(search_paths),
                profile_recovery_artifact_paths=(),
                restart_smoke_artifact_paths=(),
                discord_alert_path=discord_alert,
                weekly_counts_path=weekly_counts,
            )

        self.assertFalse(payload["passed"])
        statuses = {item["id"]: item["status"] for item in payload["requirements"]}  # type: ignore[index]
        self.assertEqual(statuses["dod_1_restart_search_all_sites"], "missing")
        self.assertEqual(statuses["dod_2_profile_corruption_snapshot_recovery"], "missing")

    def test_portal_dod_audit_reports_profile_recovery_not_run_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recovery_paths: list[Path] = []
            for site in ("saramin", "jobkorea"):
                recovery = root / f"profile_recovery_{site}.json"
                recovery.write_text(
                    json.dumps(
                        {
                            "kind": "portal_profile_recovery_smoke",
                            "site": site,
                            "worker_id": "default",
                            "keyword": "backend",
                            "generated_at": "2026-06-09T00:00:00+00:00",
                            "recovery_policy": "snapshot_only_no_auto_relogin",
                            "auto_relogin_disabled": True,
                            "mode": "guarded",
                            "status": "not_run",
                            "reason": "validated_snapshot_required_before_profile_deletion",
                            "reauth_cause": "profile_corrupt",
                            "snapshot_capture_required": True,
                            "snapshot_capture_policy": "required",
                            "snapshot_captured": False,
                            "retried_after_recovery": False,
                            "profile_deleted_before_start": False,
                            "recovery": {
                                "recovered": False,
                                "recovered_by": "",
                                "reauth_event_recorded": False,
                                "pause_site": False,
                                "discord_alert_sent": False,
                            },
                            "snapshot_metadata_status": "unavailable",
                            "snapshot_present": False,
                        }
                    ),
                    encoding="utf-8",
                )
                recovery_paths.append(recovery)
            recovery_proof = root / "portal_profile_recovery_proof_status_latest.json"
            recovery_proof.write_text(
                json.dumps(
                    {
                        "kind": "portal_profile_recovery_proof_status",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "failed",
                        "ready": False,
                        "missing_sites": [],
                        "incomplete_sites": ["saramin", "jobkorea"],
                        "schema_issues": {
                            "saramin": ["snapshot_captured"],
                            "jobkorea": ["snapshot_captured"],
                        },
                        "action_hint": "profile_recovery_smoke_incomplete",
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=tuple(recovery_paths),
                profile_recovery_proof_path=recovery_proof,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_2_profile_corruption_snapshot_recovery"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("validated_snapshot_required_before_profile_deletion", requirement["evidence"])
        self.assertIn("snapshot_metadata_status", requirement["evidence"])
        self.assertIn("generated_at", requirement["evidence"])
        self.assertIn("profile_recovery_proof_status=failed", requirement["evidence"])
        self.assertIn("profile_recovery_action_hint=profile_recovery_smoke_incomplete", requirement["evidence"])
        self.assertIn("profile_recovery_incomplete_sites", requirement["evidence"])
        self.assertNotIn("missing_top_level", requirement["evidence"])

    def test_portal_dod_audit_requires_profile_recovery_kind_for_pass(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recovery_paths: list[Path] = []
            for site in ("saramin", "jobkorea"):
                recovery = root / f"profile_recovery_{site}.json"
                recovery.write_text(
                    json.dumps(
                        {
                            "site": site,
                            "worker_id": "default",
                            "keyword": "backend",
                            "generated_at": "2026-06-09T00:00:00+00:00",
                            "recovery_policy": "snapshot_only_no_auto_relogin",
                            "auto_relogin_disabled": True,
                            "mode": "guarded",
                            "status": "searched",
                            "reason": "retried after snapshot restore",
                            "reauth_cause": "profile_corrupt",
                            "snapshot_capture_required": True,
                            "snapshot_capture_policy": "required",
                            "snapshot_captured": True,
                            "retried_after_recovery": True,
                            "profile_deleted_before_start": True,
                            "recovery": {
                                "recovered": True,
                                "recovered_by": "snapshot_reinject",
                                "reauth_event_recorded": True,
                                "pause_site": False,
                                "discord_alert_sent": False,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                recovery_paths.append(recovery)

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=tuple(recovery_paths),
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_2_profile_corruption_snapshot_recovery"
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("kind", requirement["evidence"])
        self.assertIn("missing_top_level", requirement["evidence"])

    def test_portal_dod_audit_rejects_auto_relogin_profile_recovery_for_dod2(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recovery_paths: list[Path] = []
            for site in ("saramin", "jobkorea"):
                recovery = root / f"profile_recovery_{site}.json"
                recovery.write_text(
                    json.dumps(
                        {
                            "kind": "portal_profile_recovery_smoke",
                            "site": site,
                            "worker_id": "default",
                            "keyword": "backend",
                            "generated_at": "2026-06-09T00:00:00+00:00",
                            "recovery_policy": "snapshot_only_no_auto_relogin",
                            "auto_relogin_disabled": True,
                            "mode": "guarded",
                            "status": "searched",
                            "reason": "retried after auto relogin",
                            "reauth_cause": "profile_corrupt",
                            "snapshot_capture_required": True,
                            "snapshot_capture_policy": "required",
                            "snapshot_captured": True,
                            "retried_after_recovery": True,
                            "profile_deleted_before_start": True,
                            "recovery": {
                                "recovered": True,
                                "recovered_by": "auto_relogin",
                                "reauth_event_recorded": True,
                                "pause_site": False,
                                "discord_alert_sent": False,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                recovery_paths.append(recovery)

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=tuple(recovery_paths),
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_2_profile_corruption_snapshot_recovery"
        )
        self.assertFalse(payload["passed"])
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("snapshot-only recovery", requirement["evidence"])
        self.assertIn("auto_relogin", requirement["evidence"])

    def test_portal_dod_audit_requires_linkedin_human_reauth_weekly_row(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_status = root / "portal_session_status.json"
            session_status.write_text(
                json.dumps(
                    complete_preflight_payload("saramin", "jobkorea", "linkedin_rps")
                ),
                encoding="utf-8",
            )
            restart_paths: list[Path] = []
            for site in ("saramin", "jobkorea", "linkedin_rps"):
                search_payload = {
                    "site": site,
                    "worker_id": "default",
                    "keyword": "backend",
                    "mode": "guarded",
                    "status": "searched",
                    "reauth_cause": "",
                    "snapshot_capture_required": True,
                    "snapshot_capture_policy": "required",
                    "snapshot_captured": True,
                    "retried_after_recovery": False,
                    "profile_deleted_before_start": False,
                }
                path = root / f"restart_smoke_{site}.json"
                path.write_text(
                    json.dumps(
                        safe_restart_smoke_payload(
                            site=site,  # type: ignore[arg-type]
                            worker_id="default",
                            keyword="backend",
                            first=search_payload,
                            second=search_payload,
                        )
                    ),
                    encoding="utf-8",
                )
                restart_paths.append(path)
            recovery_paths: list[Path] = []
            metadata_paths: list[Path] = []
            for site in ("saramin", "jobkorea"):
                recovery = root / f"profile_recovery_{site}.json"
                recovery.write_text(
                    json.dumps(
                        {
                            "site": site,
                            "generated_at": "2026-06-09T00:00:00+00:00",
                            "mode": "guarded",
                            "status": "searched",
                            "reauth_cause": "profile_corrupt",
                            "snapshot_capture_required": True,
                            "snapshot_capture_policy": "required",
                            "snapshot_captured": True,
                            "retried_after_recovery": True,
                            "profile_deleted_before_start": True,
                            "recovery": {
                                "recovered": True,
                                "recovered_by": "snapshot_reinject",
                                "reauth_event_recorded": True,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                recovery_paths.append(recovery)
                metadata = root / f"snapshot_metadata_{site}.json"
                metadata.write_text(
                    json.dumps(
                        {
                            "kind": "session_snapshot_metadata",
                            "site": site,
                            "snapshot_present": True,
                            "status": "present",
                            "is_validated": True,
                            "encrypted_envelope": "VHSS1",
                            "encrypted_bytes": 96,
                        }
                    ),
                    encoding="utf-8",
                )
                metadata_paths.append(metadata)
            linkedin_metadata = root / "snapshot_metadata_linkedin_rps.json"
            linkedin_metadata.write_text(
                json.dumps(
                    {
                        "kind": "session_snapshot_metadata",
                        "site": "linkedin_rps",
                        "snapshot_present": True,
                        "status": "present",
                        "is_validated": True,
                        "encrypted_envelope": "VHSS1",
                        "encrypted_bytes": 96,
                    }
                ),
                encoding="utf-8",
            )
            metadata_paths.append(linkedin_metadata)
            discord_alert = root / "discord_alert.json"
            discord_alert.write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "delivered": True,
                        "reauth_event_recorded": True,
                    }
                ),
                encoding="utf-8",
            )
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08",
                        "total_events": 2,
                        "rows": [
                            {
                                "site": "saramin",
                                "worker_id": "default",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": 1,
                            },
                            {
                                "site": "jobkorea",
                                "worker_id": "default",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": 1,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=session_status,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=tuple(recovery_paths),
                restart_smoke_artifact_paths=tuple(restart_paths),
                snapshot_metadata_artifact_paths=tuple(metadata_paths),
                discord_alert_path=discord_alert,
                weekly_counts_path=weekly_counts,
            )

        statuses = {item["id"]: item["status"] for item in payload["requirements"]}  # type: ignore[index]
        self.assertFalse(payload["passed"])
        self.assertEqual(statuses["dod_7_reauth_events_weekly_observable"], "failed")
        requirement = next(
            item for item in payload["requirements"] if item["id"] == "dod_7_reauth_events_weekly_observable"  # type: ignore[index]
        )
        self.assertIn("missing linkedin_rps forced_logout human row", requirement["evidence"])  # type: ignore[index]

    def test_portal_dod_audit_requires_weekly_trend_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08",
                        "total_events": 3,
                        "rows": [
                            {
                                "site": "saramin",
                                "worker_id": "default",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": 1,
                            },
                            {
                                "site": "jobkorea",
                                "worker_id": "default",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": 1,
                            },
                            {
                                "site": "linkedin_rps",
                                "worker_id": "default",
                                "cause": "forced_logout",
                                "recovered_by": "human",
                                "count": 1,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                weekly_counts_path=weekly_counts,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_7_reauth_events_weekly_observable"
        )
        self.assertEqual(requirement["status"], "missing")
        self.assertIn("weekly reauth trend artifact was not supplied", requirement["evidence"])

    def test_portal_dod_audit_requires_weekly_trend_latest_week_observations(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_rows = [
                {
                    "site": "saramin",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "jobkorea",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "linkedin_rps",
                    "worker_id": "default",
                    "cause": "forced_logout",
                    "recovered_by": "human",
                    "count": 1,
                },
            ]
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08",
                        "total_events": 3,
                        "rows": weekly_rows,
                    }
                ),
                encoding="utf-8",
            )
            trend_rows = weekly_rows[:-1]
            weekly_trend = root / "weekly_trend.json"
            weekly_trend.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_trend",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "latest_week_start": "2026-06-08",
                        "weeks_observed": 2,
                        "latest_total_events": 2,
                        "previous_total_events": 0,
                        "delta_from_previous_week": 2,
                        "latest_week_zero": False,
                        "zero_event_weeks": 1,
                        "weeks": [
                            {
                                "week_start": "2026-06-01",
                                "status": "present",
                                "total_events": 0,
                                "rows": [],
                            },
                            {
                                "week_start": "2026-06-08",
                                "status": "present",
                                "total_events": 2,
                                "rows": trend_rows,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                weekly_counts_path=weekly_counts,
                weekly_trend_path=weekly_trend,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_7_reauth_events_weekly_observable"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("weekly reauth trend latest week missing required observations", requirement["evidence"])
        self.assertIn("latest_week_missing_linkedin_rps_forced_logout_human", requirement["evidence"])

    def test_portal_dod_audit_requires_multi_week_trend_for_zero_convergence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_rows = [
                {
                    "site": "saramin",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "jobkorea",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "linkedin_rps",
                    "worker_id": "default",
                    "cause": "forced_logout",
                    "recovered_by": "human",
                    "count": 1,
                },
            ]
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08",
                        "total_events": 3,
                        "rows": weekly_rows,
                    }
                ),
                encoding="utf-8",
            )
            weekly_trend = root / "weekly_trend.json"
            weekly_trend.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_trend",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "latest_week_start": "2026-06-08",
                        "weeks_observed": 1,
                        "latest_total_events": 3,
                        "previous_total_events": 0,
                        "delta_from_previous_week": None,
                        "latest_week_zero": False,
                        "zero_event_weeks": 0,
                        "weeks": [
                            {
                                "week_start": "2026-06-08",
                                "status": "present",
                                "total_events": 3,
                                "rows": weekly_rows,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                weekly_counts_path=weekly_counts,
                weekly_trend_path=weekly_trend,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_7_reauth_events_weekly_observable"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("weeks_observed_min", requirement["evidence"])
        self.assertIn("weeks_min", requirement["evidence"])

    def test_portal_dod_audit_rejects_broken_weekly_trend_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_rows = [
                {
                    "site": "saramin",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "jobkorea",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "linkedin_rps",
                    "worker_id": "default",
                    "cause": "forced_logout",
                    "recovered_by": "human",
                    "count": 1,
                },
            ]
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08",
                        "total_events": 3,
                        "rows": weekly_rows,
                    }
                ),
                encoding="utf-8",
            )
            weekly_trend = root / "weekly_trend.json"
            weekly_trend.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_trend",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "latest_week_start": "2026-06-08",
                        "weeks_observed": 2,
                        "latest_total_events": 0,
                        "previous_total_events": 0,
                        "delta_from_previous_week": 0,
                        "latest_week_zero": True,
                        "zero_event_weeks": 2,
                        "weeks": [
                            {
                                "week_start": "2026-06-01",
                                "status": "present",
                                "total_events": 0,
                                "rows": [],
                            },
                            {
                                "week_start": "2026-06-08",
                                "status": "present",
                                "total_events": 4,
                                "rows": weekly_rows,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                weekly_counts_path=weekly_counts,
                weekly_trend_path=weekly_trend,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_7_reauth_events_weekly_observable"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("weekly reauth trend artifact", requirement["evidence"])
        self.assertIn("latest_total_events", requirement["evidence"])
        self.assertIn("total_events_sum", requirement["evidence"])

    def test_portal_dod_audit_rejects_bool_weekly_trend_numbers(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_rows = [
                {
                    "site": "saramin",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "jobkorea",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "linkedin_rps",
                    "worker_id": "default",
                    "cause": "forced_logout",
                    "recovered_by": "human",
                    "count": 1,
                },
            ]
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08",
                        "total_events": 3,
                        "rows": weekly_rows,
                    }
                ),
                encoding="utf-8",
            )
            weekly_trend = root / "weekly_trend.json"
            weekly_trend.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_trend",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "latest_week_start": "2026-06-08",
                        "weeks_observed": True,
                        "latest_total_events": True,
                        "previous_total_events": False,
                        "delta_from_previous_week": 3,
                        "latest_week_zero": False,
                        "zero_event_weeks": False,
                        "weeks": [
                            {
                                "week_start": "2026-06-01",
                                "status": "present",
                                "total_events": 0,
                                "rows": [],
                            },
                            {
                                "week_start": "2026-06-08",
                                "status": "present",
                                "total_events": True,
                                "rows": [
                                    {
                                        "site": "saramin",
                                        "worker_id": "default",
                                        "cause": "profile_corrupt",
                                        "recovered_by": "snapshot_reinject",
                                        "count": True,
                                    }
                                ],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                weekly_counts_path=weekly_counts,
                weekly_trend_path=weekly_trend,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_7_reauth_events_weekly_observable"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("weekly reauth trend artifact", requirement["evidence"])
        self.assertIn("weeks_observed", requirement["evidence"])
        self.assertIn("latest_total_events", requirement["evidence"])
        self.assertIn("weeks[1].total_events", requirement["evidence"])
        self.assertIn("weeks[1].rows[0].count", requirement["evidence"])

    def test_portal_dod_audit_rejects_policy_invalid_weekly_trend_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_rows = [
                {
                    "site": "saramin",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "jobkorea",
                    "worker_id": "default",
                    "cause": "profile_corrupt",
                    "recovered_by": "snapshot_reinject",
                    "count": 1,
                },
                {
                    "site": "linkedin_rps",
                    "worker_id": "default",
                    "cause": "forced_logout",
                    "recovered_by": "human",
                    "count": 1,
                },
            ]
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08",
                        "total_events": 3,
                        "rows": weekly_rows,
                    }
                ),
                encoding="utf-8",
            )
            trend_rows = weekly_rows + [
                {
                    "site": "linkedin_rps",
                    "worker_id": "default",
                    "cause": "forced_logout",
                    "recovered_by": "auto_relogin",
                    "count": 1,
                    "storage_state": "cookie-secret",
                }
            ]
            weekly_trend = root / "weekly_trend.json"
            weekly_trend.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_trend",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "latest_week_start": "2026-06-08",
                        "weeks_observed": 2,
                        "latest_total_events": 4,
                        "previous_total_events": 0,
                        "delta_from_previous_week": 4,
                        "latest_week_zero": False,
                        "zero_event_weeks": 1,
                        "weeks": [
                            {
                                "week_start": "2026-06-01",
                                "status": "present",
                                "total_events": 0,
                                "rows": [],
                            },
                            {
                                "week_start": "2026-06-08",
                                "status": "present",
                                "total_events": 4,
                                "rows": trend_rows,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                weekly_counts_path=weekly_counts,
                weekly_trend_path=weekly_trend,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_7_reauth_events_weekly_observable"
        )
        self.assertEqual(requirement["status"], "failed")
        # The disallowed extra field (a leaked storage_state) is still rejected; LinkedIn
        # auto_relogin is no longer treated as a policy violation (SOT invariant).
        self.assertIn("fields_allowed", requirement["evidence"])
        self.assertNotIn("linkedin_auto_relogin_forbidden", requirement["evidence"])
        self.assertNotIn("cookie-secret", requirement["evidence"])

    def test_portal_dod_audit_rejects_broken_weekly_count_aggregate(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08",
                        "total_events": 1,
                        "rows": [
                            {
                                "site": "saramin",
                                "worker_id": "default",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": 2,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                weekly_counts_path=weekly_counts,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_7_reauth_events_weekly_observable"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("schema_issues", requirement["evidence"])
        self.assertIn("total_events_sum", requirement["evidence"])

    def test_portal_dod_audit_rejects_bool_weekly_count_numbers(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08",
                        "total_events": True,
                        "rows": [
                            {
                                "site": "saramin",
                                "worker_id": "default",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                weekly_counts_path=weekly_counts,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_7_reauth_events_weekly_observable"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("schema_issues", requirement["evidence"])
        self.assertIn("total_events", requirement["evidence"])
        self.assertIn("rows[0].count", requirement["evidence"])

    def test_portal_dod_audit_accepts_linkedin_auto_relogin_weekly_row(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08",
                        "total_events": 4,
                        "rows": [
                            {
                                "site": "saramin",
                                "worker_id": "default",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": 1,
                            },
                            {
                                "site": "jobkorea",
                                "worker_id": "default",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": 1,
                            },
                            {
                                "site": "linkedin_rps",
                                "worker_id": "default",
                                "cause": "forced_logout",
                                "recovered_by": "human",
                                "count": 1,
                            },
                            {
                                "site": "linkedin_rps",
                                "worker_id": "default",
                                "cause": "forced_logout",
                                "recovered_by": "auto_relogin",
                                "count": 1,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                weekly_counts_path=weekly_counts,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_7_reauth_events_weekly_observable"
        )
        # SOT invariant: linkedin_rps/auto_relogin is an allowed recovery outcome, so the
        # audit must NOT reject it. (Status is "missing" only because no weekly_trend
        # artifact was supplied here, not because of any policy violation.)
        self.assertNotEqual(requirement["status"], "failed")
        self.assertNotIn("policy-invalid", requirement["evidence"])
        self.assertNotIn("linkedin_auto_relogin_forbidden", requirement["evidence"])

    def test_portal_dod_audit_rejects_unknown_weekly_count_cause(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            weekly_counts = root / "weekly_counts.json"
            weekly_counts.write_text(
                json.dumps(
                    {
                        "kind": "reauth_weekly_counts",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "present",
                        "week_start": "2026-06-08",
                        "total_events": 4,
                        "rows": [
                            {
                                "site": "saramin",
                                "worker_id": "default",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": 1,
                            },
                            {
                                "site": "jobkorea",
                                "worker_id": "default",
                                "cause": "profile_corrupt",
                                "recovered_by": "snapshot_reinject",
                                "count": 1,
                            },
                            {
                                "site": "linkedin_rps",
                                "worker_id": "default",
                                "cause": "forced_logout",
                                "recovered_by": "human",
                                "count": 1,
                            },
                            {
                                "site": "saramin",
                                "worker_id": "default",
                                "cause": "freeform_secret_reason",
                                "recovered_by": "snapshot_reinject",
                                "count": 1,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                weekly_counts_path=weekly_counts,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_7_reauth_events_weekly_observable"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("schema_issues", requirement["evidence"])
        self.assertIn("cause_allowed", requirement["evidence"])

    def test_reauth_event_store_records_weekly_counts(self) -> None:
        store = InMemoryReauthEventStore()
        store.record(
            site="saramin",
            worker_id="worker-a",
            cause="cookie_rotated",
            recovered_by="snapshot_reinject",
            occurred_at="2026-06-09T01:00:00+00:00",
        )
        store.record(
            site="saramin",
            worker_id="worker-a",
            cause="cookie_rotated",
            recovered_by="snapshot_reinject",
            occurred_at="2026-06-10T01:00:00+00:00",
        )
        store.record(
            site="saramin",
            worker_id="worker-b",
            cause="cookie_rotated",
            recovered_by="snapshot_reinject",
            occurred_at="2026-06-10T02:00:00+00:00",
        )
        store.record(
            site="saramin",
            worker_id="worker-a",
            cause="cookie_rotated",
            recovered_by="snapshot_reinject",
            occurred_at="2026-06-17T01:00:00+00:00",
        )

        counts = store.weekly_counts(week_start="2026-06-09T00:00:00+00:00")

        self.assertEqual(counts[("saramin", "worker-a", "cookie_rotated", "snapshot_reinject")], 2)
        self.assertEqual(counts[("saramin", "worker-b", "cookie_rotated", "snapshot_reinject")], 1)

    def test_discord_alert_test_can_record_linkedin_reauth_event(self) -> None:
        class FakeResponse:
            status = 204

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        def fake_urlopen(_request: object, *, timeout: int) -> FakeResponse:
            self.assertEqual(timeout, 10)
            return FakeResponse()

        event_store = InMemoryReauthEventStore()
        payload = send_discord_alert_test(
            "https://discord.example.test/webhook",
            event_store=event_store,
            urlopen=fake_urlopen,
            occurred_at="2026-06-09T12:00:00+00:00",
        )
        counts = event_store.weekly_counts(week_start="2026-06-08T00:00:00+00:00")

        self.assertTrue(payload["delivered"])
        self.assertTrue(payload["reauth_event_recorded"])
        self.assertEqual(payload["event"]["cause"], "forced_logout")  # type: ignore[index]
        self.assertEqual(payload["event"]["occurred_at"], "2026-06-09T12:00:00+00:00")  # type: ignore[index]
        self.assertEqual(event_store.events[0].site, "linkedin_rps")
        self.assertEqual(event_store.events[0].cause, "forced_logout")
        self.assertEqual(event_store.events[0].recovered_by, "human")
        self.assertEqual(counts[("linkedin_rps", "default", "forced_logout", "human")], 1)

    def test_discord_alert_test_keeps_delivery_evidence_when_recording_fails(self) -> None:
        class FakeResponse:
            status = 204

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        class FailingEventStore:
            def record(self, **_kwargs: object) -> object:
                raise RuntimeError("service-role-secret")

        payload = send_discord_alert_test(
            "https://discord.example.test/webhook",
            event_store=FailingEventStore(),  # type: ignore[arg-type]
            urlopen=lambda _request, *, timeout: FakeResponse(),
            occurred_at="2026-06-09T12:00:00+00:00",
            record_reauth_event_requested=True,
        )
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertTrue(payload["delivered"])
        self.assertFalse(payload["reauth_event_recorded"])
        self.assertEqual(payload["status"], "recording_failed")
        self.assertEqual(payload["reauth_event_error_type"], "RuntimeError")
        self.assertNotIn("service-role-secret", encoded)

    def test_discord_alert_cli_still_sends_when_reauth_store_config_fails(self) -> None:
        sent: list[str] = []

        class FakeNotifier:
            def __init__(self, webhook_url: str, **_kwargs: object) -> None:
                self.webhook_url = webhook_url

            def send_reauth_alert(self, _event: object) -> bool:
                sent.append(self.webhook_url)
                return True

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "discord_alert.json"
            with patch.object(
                sys,
                "argv",
                [
                    "portal_live_check.py",
                    "discord-alert-test",
                    "--webhook-url",
                    "https://discord.example.test/webhook",
                    "--record-reauth-event",
                    "--output",
                    str(output),
                ],
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.supabase_config_from_env",
                side_effect=RuntimeError("service-role-secret"),
            ), patch(
                "tools.multi_position_sourcing.portal_live_check.DiscordWebhookNotifier",
                FakeNotifier,
            ):
                with self.assertRaises(SystemExit) as raised:
                    portal_live_check_main()

            payload = json.loads(output.read_text(encoding="utf-8"))
            encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(sent, ["https://discord.example.test/webhook"])
        self.assertTrue(payload["delivered"])
        self.assertTrue(payload["reauth_event_recording_requested"])
        self.assertFalse(payload["reauth_event_recorded"])
        self.assertEqual(payload["status"], "recording_failed")
        self.assertEqual(payload["reauth_event_error_type"], "RuntimeError")
        self.assertNotIn("service-role-secret", encoded)
        self.assertNotIn("discord.example.test/webhook", encoded)

    def test_missing_discord_alert_webhook_payload_is_safe(self) -> None:
        payload = missing_discord_alert_webhook_payload()
        encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["kind"], "discord_alert_test")
        self.assertIsInstance(payload["generated_at"], str)
        self.assertEqual(payload["status"], "missing_webhook")
        self.assertFalse(payload["delivered"])
        self.assertFalse(payload["reauth_event_recorded"])
        self.assertNotIn("https://", encoded)
        self.assertNotIn("discord.example.test/webhook", encoded)

    def test_portal_dod_audit_reports_discord_alert_failure_details(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            discord_alert = root / "discord_alert.json"
            discord_alert.write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "status": "missing_webhook",
                        "delivered": False,
                        "reauth_event_recorded": False,
                        "reason": "webhook env or keychain value is required",
                        "action_hint": "discord_reauth_webhook_missing",
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                discord_alert_path=discord_alert,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_5_linkedin_discord_alert"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("missing_webhook", requirement["evidence"])
        self.assertIn("discord_reauth_webhook_missing", requirement["evidence"])
        self.assertIn("generated_at", requirement["evidence"])
        self.assertNotIn("https://", requirement["evidence"])

    def test_portal_dod_audit_requires_discord_alert_reauth_recording(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            discord_alert = root / "discord_alert.json"
            discord_alert.write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "delivered": True,
                        "reauth_event_recorded": False,
                        "event": complete_linkedin_discord_event(),
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                discord_alert_path=discord_alert,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_5_linkedin_discord_alert"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("delivered=true", requirement["evidence"])
        self.assertIn("reauth_event_recorded=true", requirement["evidence"])

    def test_portal_dod_audit_requires_linkedin_discord_alert_event_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            discord_alert = root / "discord_alert.json"
            discord_alert.write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "generated_at": "2026-06-09T00:00:00+00:00",
                        "delivered": True,
                        "reauth_event_recorded": True,
                        "event": {
                            "id": "manual-live-check",
                            "site": "saramin",
                            "worker_id": "default",
                            "cause": "profile_corrupt",
                            "recovered_by": "snapshot_reinject",
                            "occurred_at": "2026-06-09T00:00:00+00:00",
                        },
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                discord_alert_path=discord_alert,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_5_linkedin_discord_alert"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("event.site", requirement["evidence"])
        self.assertIn("event.cause", requirement["evidence"])
        self.assertIn("event.recovered_by", requirement["evidence"])

    def test_portal_dod_audit_requires_discord_alert_generated_at(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            discord_alert = root / "discord_alert.json"
            discord_alert.write_text(
                json.dumps(
                    {
                        "kind": "discord_alert_test",
                        "delivered": True,
                        "reauth_event_recorded": True,
                        "event": complete_linkedin_discord_event(),
                    }
                ),
                encoding="utf-8",
            )

            payload = build_dod_audit_payload(
                session_status_path=None,
                search_artifact_paths=(),
                profile_recovery_artifact_paths=(),
                discord_alert_path=discord_alert,
            )

        requirement = next(
            item
            for item in payload["requirements"]  # type: ignore[union-attr]
            if item["id"] == "dod_5_linkedin_discord_alert"
        )
        self.assertEqual(requirement["status"], "failed")
        self.assertIn("generated_at", requirement["evidence"])
        self.assertIn("delivered=true", requirement["evidence"])
        self.assertIn("reauth_event_recorded=true", requirement["evidence"])

    def test_supabase_reauth_event_store_records_and_counts_without_secret_payload(self) -> None:
        requests: list[dict[str, object]] = []

        class FakeResponse:
            def __init__(self, payload: object, status: int = 200) -> None:
                self._payload = payload
                self.status = status

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(self._payload).encode("utf-8")

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            requests.append(
                {
                    "url": request.full_url,  # type: ignore[attr-defined]
                    "method": request.get_method(),  # type: ignore[attr-defined]
                    "body": None if request.data is None else request.data.decode("utf-8"),  # type: ignore[attr-defined]
                }
            )
            if "/rest/v1/reauth_events" in request.full_url and request.get_method() == "POST":  # type: ignore[attr-defined]
                return FakeResponse(
                    [
                        {
                            "id": "event-1",
                            "site": "linkedin_rps",
                            "worker_id": "default",
                            "cause": "forced_logout",
                            "recovered_by": "human",
                            "occurred_at": "2026-06-09T00:00:00+00:00",
                        }
                    ],
                    status=201,
                )
            if "/rest/v1/rpc/reauth_weekly_counts" in request.full_url:  # type: ignore[attr-defined]
                return FakeResponse(
                    [
                        {
                            "site": "linkedin_rps",
                            "worker_id": "default",
                            "cause": "forced_logout",
                            "recovered_by": "human",
                            "count": 2,
                        },
                        {
                            "site": "linkedin_rps",
                            "worker_id": "manual-review",
                            "cause": "forced_logout",
                            "recovered_by": "human",
                            "count": 1,
                        },
                    ]
                )
            return FakeResponse(
                [
                    {
                        "site": "linkedin_rps",
                        "worker_id": "default",
                        "cause": "forced_logout",
                        "recovered_by": "human",
                    },
                    {
                        "site": "linkedin_rps",
                        "worker_id": "default",
                        "cause": "forced_logout",
                        "recovered_by": "human",
                    },
                    {
                        "site": "linkedin_rps",
                        "worker_id": "manual-review",
                        "cause": "forced_logout",
                        "recovered_by": "human",
                    },
                ]
            )

        store = SupabaseReauthEventStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
                timeout_seconds=3,
            ),
            urlopen=fake_urlopen,
        )

        event = store.record(
            site="linkedin_rps",
            worker_id="default",
            cause="forced_logout",
            recovered_by="human",
            occurred_at="2026-06-09T00:00:00+00:00",
        )
        counts = store.weekly_counts(week_start="2026-06-09T00:00:00+00:00")

        self.assertEqual(event.id, "event-1")
        self.assertEqual(counts[("linkedin_rps", "default", "forced_logout", "human")], 2)
        self.assertEqual(counts[("linkedin_rps", "manual-review", "forced_logout", "human")], 1)
        self.assertIn("/rest/v1/reauth_events", requests[0]["url"])
        self.assertNotIn("service-role-secret", requests[0]["body"])
        self.assertIn("/rest/v1/rpc/reauth_weekly_counts", requests[1]["url"])
        self.assertIn("week_start_arg", requests[1]["body"])
        self.assertNotIn("service-role-secret", requests[1]["body"])

    def test_supabase_reauth_event_store_rejects_invalid_returned_record(self) -> None:
        requests: list[dict[str, object]] = []

        class FakeResponse:
            status = 201

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    [
                        {
                            "id": "poison-event",
                            "site": "linkedin_rps",
                            "worker_id": "default",
                            "cause": "forced_logout",
                            "recovered_by": "totally_unsupported",
                            "occurred_at": "2026-06-09T00:00:00+00:00",
                        }
                    ]
                ).encode("utf-8")

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            requests.append(
                {
                    "url": request.full_url,  # type: ignore[attr-defined]
                    "method": request.get_method(),  # type: ignore[attr-defined]
                    "body": None if request.data is None else request.data.decode("utf-8"),  # type: ignore[attr-defined]
                }
            )
            return FakeResponse()

        store = SupabaseReauthEventStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
                timeout_seconds=3,
            ),
            urlopen=fake_urlopen,
        )

        event = store.record(
            site="linkedin_rps",
            worker_id="default",
            cause="forced_logout",
            recovered_by="human",
            occurred_at="2026-06-09T00:00:00+00:00",
        )

        self.assertNotEqual(event.id, "poison-event")
        self.assertEqual(event.site, "linkedin_rps")
        self.assertEqual(event.recovered_by, "human")
        self.assertEqual(event.occurred_at, "2026-06-09T00:00:00+00:00")
        self.assertIn("/rest/v1/reauth_events", requests[0]["url"])
        self.assertNotIn("service-role-secret", requests[0]["body"])

    def test_supabase_reauth_event_store_weekly_rpc_skips_malformed_rows(self) -> None:
        requests: list[dict[str, object]] = []

        class FakeResponse:
            status = 200

            def __init__(self, payload: object) -> None:
                self._payload = payload

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(self._payload).encode("utf-8")

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            requests.append(
                {
                    "url": request.full_url,  # type: ignore[attr-defined]
                    "method": request.get_method(),  # type: ignore[attr-defined]
                    "body": None if request.data is None else request.data.decode("utf-8"),  # type: ignore[attr-defined]
                }
            )
            return FakeResponse(
                [
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "recovered_by": "snapshot_reinject",
                        "count": 2,
                    },
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "recovered_by": "snapshot_reinject",
                        "count": "3",
                    },
                    {
                        "site": "jobkorea",
                        "worker_id": "default",
                        "cause": "http_401",
                        "recovered_by": "human",
                        "count": "1",
                    },
                    "not-a-row",
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "count": 3,
                    },
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "recovered_by": "snapshot_reinject",
                        "count": "not-an-int",
                    },
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "recovered_by": "snapshot_reinject",
                        "count": 0,
                    },
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "recovered_by": "snapshot_reinject",
                        "count": -1,
                    },
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "recovered_by": "snapshot_reinject",
                        "count": True,
                    },
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "recovered_by": "snapshot_reinject",
                        "count": 1.5,
                    },
                    {
                        "site": "unknown",
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "recovered_by": "snapshot_reinject",
                        "count": 4,
                    },
                    {
                        "site": "saramin",
                        "worker_id": "",
                        "cause": "cookie_rotated",
                        "recovered_by": "snapshot_reinject",
                        "count": 4,
                    },
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "freeform_secret_reason",
                        "recovered_by": "snapshot_reinject",
                        "count": 4,
                    },
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "recovered_by": "email",
                        "count": 4,
                    },
                    {
                        "site": "linkedin_rps",
                        "worker_id": "default",
                        "cause": "forced_logout",
                        "recovered_by": "auto_relogin",
                        "count": 4,
                    },
                    {
                        "site": 7,
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "recovered_by": "snapshot_reinject",
                        "count": 4,
                    },
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "cookie_rotated",
                        "recovered_by": "snapshot_reinject",
                        "count": [],
                    },
                ]
            )

        store = SupabaseReauthEventStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
                timeout_seconds=3,
            ),
            urlopen=fake_urlopen,
        )

        counts = store.weekly_counts(week_start="2026-06-09T00:00:00+00:00")

        self.assertEqual(
            counts,
            {
                ("saramin", "worker-a", "cookie_rotated", "snapshot_reinject"): 5,
                ("jobkorea", "default", "http_401", "human"): 1,
                # SOT invariant: linkedin_rps/auto_relogin is valid and is now counted.
                ("linkedin_rps", "default", "forced_logout", "auto_relogin"): 4,
            },
        )
        self.assertIn("/rest/v1/rpc/reauth_weekly_counts", requests[0]["url"])
        self.assertIn("week_start_arg", requests[0]["body"])
        self.assertNotIn("service-role-secret", requests[0]["body"])

    def test_reauth_event_stores_accept_linkedin_auto_relogin(self) -> None:
        # SOT invariant: LinkedIn RPS auto-logs in like the other portals, so a
        # linkedin_rps/auto_relogin reauth event is valid and recordable.
        memory_store = InMemoryReauthEventStore()
        event = memory_store.record(
            site="linkedin_rps",
            worker_id="default",
            cause="forced_logout",
            recovered_by="auto_relogin",
            occurred_at="2026-06-09T00:00:00+00:00",
        )
        self.assertEqual(event.recovered_by, "auto_relogin")
        self.assertEqual(len(memory_store.events), 1)
        self.assertEqual(memory_store.events[0].site, "linkedin_rps")

        requests: list[object] = []

        class FakeResponse:
            status = 201

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return b""

        def fake_urlopen(request: object, *, timeout: int) -> object:
            requests.append(request)
            return FakeResponse()

        supabase_store = SupabaseReauthEventStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
                timeout_seconds=3,
            ),
            urlopen=fake_urlopen,
        )

        written = supabase_store.record(
            site="linkedin_rps",
            worker_id="default",
            cause="forced_logout",
            recovered_by="auto_relogin",
            occurred_at="2026-06-09T00:00:00+00:00",
        )
        self.assertEqual(written.recovered_by, "auto_relogin")
        self.assertEqual(len(requests), 1)

    def test_reauth_event_stores_reject_unsupported_cause_before_write(self) -> None:
        memory_store = InMemoryReauthEventStore()
        with self.assertRaisesRegex(ValueError, "unsupported reauth event cause"):
            memory_store.record(
                site="saramin",
                worker_id="worker-a",
                cause="freeform_secret_reason",
                recovered_by="snapshot_reinject",
                occurred_at="2026-06-09T00:00:00+00:00",
            )

        requests: list[object] = []

        def fake_urlopen(request: object, *, timeout: int) -> object:
            requests.append(request)
            raise AssertionError("Unsupported reauth cause should not be written")

        supabase_store = SupabaseReauthEventStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
                timeout_seconds=3,
            ),
            urlopen=fake_urlopen,
        )

        with self.assertRaisesRegex(ValueError, "unsupported reauth event cause"):
            supabase_store.record(
                site="jobkorea",
                worker_id="default",
                cause="freeform_secret_reason",
                recovered_by="snapshot_reinject",
                occurred_at="2026-06-09T00:00:00+00:00",
            )
        self.assertEqual(requests, [])
        self.assertEqual(memory_store.events, [])

    def test_supabase_reauth_event_store_falls_back_when_weekly_rpc_missing(self) -> None:
        requests: list[dict[str, object]] = []

        class FakeResponse:
            status = 200

            def __init__(self, payload: object) -> None:
                self._payload = payload

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(self._payload).encode("utf-8")

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            requests.append(
                {
                    "url": request.full_url,  # type: ignore[attr-defined]
                    "method": request.get_method(),  # type: ignore[attr-defined]
                    "body": None if request.data is None else request.data.decode("utf-8"),  # type: ignore[attr-defined]
                }
            )
            if "/rest/v1/rpc/reauth_weekly_counts" in request.full_url:  # type: ignore[attr-defined]
                raise urllib.error.HTTPError(
                    request.full_url,  # type: ignore[attr-defined]
                    404,
                    "Not Found",
                    {},
                    io.BytesIO(b'{"message":"Could not find function"}'),
                )
            return FakeResponse(
                [
                    {
                        "site": "jobkorea",
                        "worker_id": "default",
                        "cause": "profile_corrupt",
                        "recovered_by": "snapshot_reinject",
                    },
                    {
                        "site": "jobkorea",
                        "worker_id": "default",
                        "cause": "profile_corrupt",
                        "recovered_by": "snapshot_reinject",
                    },
                ]
            )

        store = SupabaseReauthEventStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
                timeout_seconds=3,
            ),
            urlopen=fake_urlopen,
        )

        counts = store.weekly_counts(week_start="2026-06-09T00:00:00+00:00")

        self.assertEqual(counts[("jobkorea", "default", "profile_corrupt", "snapshot_reinject")], 2)
        self.assertIn("/rest/v1/rpc/reauth_weekly_counts", requests[0]["url"])
        self.assertIn("select=site,worker_id,cause,recovered_by", requests[1]["url"])

    def test_supabase_reauth_event_store_weekly_table_fallback_skips_malformed_rows(self) -> None:
        requests: list[dict[str, object]] = []

        class FakeResponse:
            status = 200

            def __init__(self, payload: object) -> None:
                self._payload = payload

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(self._payload).encode("utf-8")

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            requests.append(
                {
                    "url": request.full_url,  # type: ignore[attr-defined]
                    "method": request.get_method(),  # type: ignore[attr-defined]
                    "body": None if request.data is None else request.data.decode("utf-8"),  # type: ignore[attr-defined]
                }
            )
            if "/rest/v1/rpc/reauth_weekly_counts" in request.full_url:  # type: ignore[attr-defined]
                raise urllib.error.HTTPError(
                    request.full_url,  # type: ignore[attr-defined]
                    404,
                    "Not Found",
                    {},
                    io.BytesIO(b'{"message":"Could not find function"}'),
                )
            return FakeResponse(
                [
                    {
                        "site": "jobkorea",
                        "worker_id": "default",
                        "cause": "profile_corrupt",
                        "recovered_by": "snapshot_reinject",
                    },
                    {
                        "site": "jobkorea",
                        "worker_id": "default",
                        "cause": "profile_corrupt",
                        "recovered_by": "snapshot_reinject",
                    },
                    {
                        "site": "saramin",
                        "worker_id": "worker-a",
                        "cause": "http_403",
                        "recovered_by": "human",
                    },
                    "not-a-row",
                    {
                        "site": "jobkorea",
                        "worker_id": "default",
                        "cause": "profile_corrupt",
                    },
                    {
                        "site": None,
                        "worker_id": "default",
                        "cause": "profile_corrupt",
                        "recovered_by": "snapshot_reinject",
                    },
                    {
                        "site": "jobkorea",
                        "worker_id": "",
                        "cause": "profile_corrupt",
                        "recovered_by": "snapshot_reinject",
                    },
                    {
                        "site": "jobkorea",
                        "worker_id": "default",
                        "cause": "freeform_secret_reason",
                        "recovered_by": "snapshot_reinject",
                    },
                    {
                        "site": "jobkorea",
                        "worker_id": "default",
                        "cause": "profile_corrupt",
                        "recovered_by": "email",
                    },
                    {
                        "site": "linkedin_rps",
                        "worker_id": "default",
                        "cause": "forced_logout",
                        "recovered_by": "auto_relogin",
                    },
                ]
            )

        store = SupabaseReauthEventStore(
            SupabaseRestConfig(
                url="https://supabase.example.test",
                service_role_key="service-role-secret",
                timeout_seconds=3,
            ),
            urlopen=fake_urlopen,
        )

        counts = store.weekly_counts(week_start="2026-06-09T00:00:00+00:00")

        self.assertEqual(
            counts,
            {
                ("jobkorea", "default", "profile_corrupt", "snapshot_reinject"): 2,
                ("saramin", "worker-a", "http_403", "human"): 1,
                # SOT invariant: linkedin_rps/auto_relogin is valid and is now counted.
                ("linkedin_rps", "default", "forced_logout", "auto_relogin"): 1,
            },
        )
        self.assertIn("/rest/v1/rpc/reauth_weekly_counts", requests[0]["url"])
        self.assertIn("select=site,worker_id,cause,recovered_by", requests[1]["url"])

    def test_discord_notifier_sends_linkedin_reauth_alert_payload(self) -> None:
        sent: list[dict[str, object]] = []

        class FakeResponse:
            status = 204

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            self.assertEqual(timeout, 3)
            sent.append(
                {
                    "url": request.full_url,  # type: ignore[attr-defined]
                    "payload": json.loads(request.data.decode("utf-8")),  # type: ignore[attr-defined]
                }
            )
            return FakeResponse()

        notifier = DiscordWebhookNotifier(
            webhook_url="https://discord.example.test/webhook",
            timeout_seconds=3,
            urlopen=fake_urlopen,
        )
        event = ReauthEvent(
            id="event-1",
            site="linkedin_rps",
            worker_id="default",
            cause="forced_logout",
            recovered_by="human",
            occurred_at="2026-06-09T00:00:00+00:00",
        )

        delivered = notifier.send_reauth_alert(event)

        self.assertTrue(delivered)
        self.assertEqual(sent[0]["url"], "https://discord.example.test/webhook")
        self.assertIn("linkedin_rps session reauth required", sent[0]["payload"]["content"])  # type: ignore[index]
        self.assertIn("forced_logout", sent[0]["payload"]["content"])  # type: ignore[index]

    def test_site_pacing_enforces_daily_cap_and_jittered_delay_ranges(self) -> None:
        policy = DEFAULT_PACING_POLICIES["linkedin_rps"]
        rng = random.Random(1234)

        search_delay = policy.next_search_delay_seconds(rng)
        page_delay = policy.next_page_delay_seconds(rng)

        self.assertTrue(policy.min_search_delay_seconds <= search_delay <= policy.max_search_delay_seconds)
        self.assertTrue(policy.min_page_delay_seconds <= page_delay <= policy.max_page_delay_seconds)
        self.assertTrue(policy.can_start_search(searches_today=policy.daily_search_cap - 1))
        self.assertFalse(policy.can_start_search(searches_today=policy.daily_search_cap))

    def test_pacing_policy_proof_payload_validates_default_guardrails(self) -> None:
        payload = pacing_policy_proof_payload()
        encoded = json.dumps(payload, ensure_ascii=False)
        check_statuses = {item["name"]: item["status"] for item in payload["checks"]}  # type: ignore[index]

        self.assertEqual(payload["kind"], "portal_pacing_policy_proof")
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["failed_checks"], [])
        self.assertEqual(check_statuses["protected_portal_policies_present"], "passed")
        self.assertEqual(check_statuses["linkedin_daily_cap_conservative"], "passed")
        self.assertEqual(check_statuses["linkedin_search_delay_conservative"], "passed")
        self.assertEqual(check_statuses["linkedin_page_delay_conservative"], "passed")
        self.assertIn("linkedin_rps", {item["site"] for item in payload["sites"]})  # type: ignore[index]
        self.assertNotIn("cookie", encoded.lower())
        self.assertNotIn("password", encoded.lower())
        self.assertNotIn("webhook", encoded.lower())

    def test_pacing_policy_proof_payload_reports_fixed_or_missing_guardrails(self) -> None:
        payload = pacing_policy_proof_payload(
            {
                "saramin": SitePacingPolicy("saramin", 45, 45, 8, 30, 120),
                "linkedin_rps": SitePacingPolicy("linkedin_rps", 30, 30, 0, 0, 200),
            }
        )

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["action_hint"], "fix_portal_pacing_policy")
        self.assertIn("protected_portal_policies_present", payload["failed_checks"])
        self.assertIn("saramin:search_delay_jittered_not_fixed", payload["failed_checks"])
        self.assertIn("linkedin_rps:page_delay_positive_range", payload["failed_checks"])
        self.assertIn("linkedin_rps:page_delay_jittered_not_fixed", payload["failed_checks"])

    def test_pacing_policy_proof_cli_writes_ready_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "pacing_policy.json"
            with patch.object(
                sys,
                "argv",
                [
                    "portal_live_check.py",
                    "pacing-policy-proof",
                    "--output",
                    str(output),
                ],
            ):
                portal_live_check_main()

            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(payload["ready"])
        self.assertEqual(payload["kind"], "portal_pacing_policy_proof")

    def test_dry_run_payload_contains_required_artifacts(self) -> None:
        payload = build_dry_run_payload()
        self.assertEqual(payload["mode"], "dry_run")
        self.assertFalse(payload["side_effects"]["outreach_clicked"])  # type: ignore[index]
        self.assertGreaterEqual(len(payload["position_groups"]), 5)  # type: ignore[arg-type]
        self.assertGreaterEqual(len(payload["backend_keyword_plan"]), 4)  # type: ignore[arg-type]
        self.assertIn("public_web", {item["channel"] for item in payload["backend_keyword_plan"]})  # type: ignore[index]
        self.assertGreaterEqual(len(payload["product_po_keyword_plan"]), 4)  # type: ignore[arg-type]
        self.assertGreaterEqual(len(payload["sample_profile_top_matches"]), 3)  # type: ignore[arg-type]
        self.assertIn("Profile URL:", payload["sample_clickup_activity_comment"])
        self.assertIn("후보자 요약:", payload["sample_discord_candidate_briefing"])
        self.assertIn("잘 맞는 이유:", payload["sample_discord_candidate_briefing"])
        self.assertIn("안 맞는 이유:", payload["sample_discord_candidate_briefing"])
        self.assertIn("834330913469890570", payload["discord_dm_routing"]["authorized_user_ids"])  # type: ignore[index]

    def test_discord_dm_allowlist_is_loaded_from_search_access_doc(self) -> None:
        markdown = """
| Name | Alias | Email | Discord ID |
| --- | --- | --- | --- |
| 이상혁 | Rogan | rogan@valueconnect.kr | 1404643716320329728 |
| 김충수 |  | kcs@valueconnect.kr | 834330913469890570 |
| 김형준 | Julian | julian@valueconnect.kr | 1153183633297911848 |
"""
        users = authorized_discord_users_from_markdown(markdown)
        self.assertEqual({user.discord_id for user in users}, {"1404643716320329728", "834330913469890570", "1153183633297911848"})
        self.assertTrue(is_authorized_discord_dm("834330913469890570", users))
        self.assertFalse(is_authorized_discord_dm("999", users))

    def test_portal_credential_status_supports_per_portal_and_shared_env_names(self) -> None:
        status = portal_credential_status(
            {
                "SARAMIN_USERNAME": "valueconnect",
                "SARAMIN_PASSWORD": "secret",
                "JOBKOREA_USERNAME": "valueconnect",
                "JOBKOREA_PASSWORD": "secret",
            }
        )
        self.assertTrue(status["saramin"]["ready"])
        self.assertEqual(status["saramin"]["username_key"], "SARAMIN_USERNAME")
        self.assertTrue(status["jobkorea"]["ready"])
        self.assertEqual(status["jobkorea"]["password_key"], "JOBKOREA_PASSWORD")
        self.assertNotIn("secret", str(status))

        shared_status = portal_credential_status(
            {
                "JOB_PORTAL_USERNAME": "valueconnect",
                "JOB_PORTAL_PASSWORD": "secret",
            }
        )
        self.assertTrue(shared_status["saramin"]["ready"])
        self.assertTrue(shared_status["jobkorea"]["ready"])

    def test_clickup_activity_comment_contains_required_search_fields(self) -> None:
        match = top_matches_for_profile(SAMPLE_PROFILE, SAMPLE_POSITIONS, top_n=1)[0]
        comment = format_clickup_activity_comment(match)
        self.assertIn("Profile URL:", comment)
        self.assertIn(SAMPLE_PROFILE.profile_url, comment)
        self.assertIn("점수:", comment)
        self.assertIn("왜 잘 맞는지:", comment)
        self.assertIn("후보자 프로필 요약:", comment)
        self.assertIn(str(match.score), comment)

    def test_discord_search_request_accepts_member_position_inputs(self) -> None:
        clickup = parse_discord_search_request("AI Search https://app.clickup.com/t/86abc123")
        self.assertTrue(clickup.should_route_to_search)
        self.assertTrue(clickup.has_position)
        self.assertEqual(clickup.input_kind, "clickup_url")

        clickup_with_jd = parse_discord_search_request(
            "이 포지션 후보자 찾아줘 https://app.clickup.com/t/86ew25gkz\n"
            "기술/도메인 요구\nPhysical AI / Robotics\nWMX Engine, ROS2 패키지 설계 및 노드 개발\n"
            "NVIDIA Isaac Sim/Lab\nC/C++ 임베디드 제어\nFleet management system, HW 관련 분야 관심자 적합\n"
            "전문연구요원 채용 TO 별도 운영 중"
        )
        self.assertTrue(clickup_with_jd.should_route_to_search)
        self.assertTrue(clickup_with_jd.has_position)
        self.assertEqual(clickup_with_jd.input_kind, "url_plus_pasted_jd")
        self.assertIn("Discord", clickup_with_jd.reason)

        wanted = parse_discord_search_request("서치 https://www.wanted.co.kr/wd/123456")
        self.assertTrue(wanted.should_route_to_search)
        self.assertTrue(wanted.has_position)
        self.assertEqual(wanted.input_kind, "wanted_url")

        pasted = parse_discord_search_request(
            "회사소개: Valuehire\n주요업무: 백엔드 플랫폼 개발과 채용 데이터 파이프라인 운영\n"
            "자격요건: Python, TypeScript, 데이터 모델링 경험\n우대사항: HR SaaS 경험"
        )
        self.assertTrue(pasted.should_route_to_search)
        self.assertTrue(pasted.has_position)
        self.assertEqual(pasted.input_kind, "pasted_jd")

        missing = parse_discord_search_request("Search")
        self.assertTrue(missing.should_route_to_search)
        self.assertFalse(missing.has_position)
        self.assertEqual(missing.input_kind, "missing_position")

    def test_discord_position_registration_request_takes_precedence_over_search(self) -> None:
        wanted = parse_discord_position_registration_request(
            "이 원티드 포지션 등록해줘 https://www.wanted.co.kr/wd/363433"
        )
        self.assertTrue(wanted.should_route_to_registration)
        self.assertTrue(wanted.has_position)
        self.assertEqual(wanted.input_kind, "wanted_url")
        self.assertEqual(wanted.url, "https://www.wanted.co.kr/wd/363433")
        self.assertEqual(wanted.source, "wanted")
        self.assertFalse(wanted.live_external_posting)

        pasted = parse_discord_position_registration_request(
            "채용공고 등록\n회사소개: Valuehire\n주요업무: 백엔드 플랫폼 개발과 채용 데이터 파이프라인 운영\n"
            "자격요건: Python, TypeScript, 데이터 모델링 경험\n우대사항: HR SaaS 경험"
        )
        self.assertTrue(pasted.should_route_to_registration)
        self.assertTrue(pasted.has_position)
        self.assertEqual(pasted.input_kind, "pasted_jd")
        self.assertIn("주요업무", pasted.text)

        ambiguous = parse_discord_position_registration_request(
            "Search 말고 등록해줘 https://www.wanted.co.kr/wd/123456"
        )
        self.assertTrue(ambiguous.should_route_to_registration)
        self.assertFalse(parse_discord_search_request("Search 말고 등록해줘 https://www.wanted.co.kr/wd/123456").should_route_to_search)

        missing = parse_discord_position_registration_request("포지션 등록")
        self.assertTrue(missing.should_route_to_registration)
        self.assertFalse(missing.has_position)
        self.assertEqual(missing.input_kind, "missing_position")

    def test_discord_candidate_briefing_contains_required_search_fields(self) -> None:
        match = top_matches_for_profile(SAMPLE_PROFILE, SAMPLE_POSITIONS, top_n=1)[0]
        briefing = format_discord_candidate_briefing(match)
        self.assertIn("Profile URL:", briefing)
        self.assertIn(SAMPLE_PROFILE.profile_url, briefing)
        self.assertIn("점수:", briefing)
        self.assertIn("후보자 요약:", briefing)
        self.assertIn("잘 맞는 이유:", briefing)
        self.assertIn("안 맞는 이유:", briefing)
        self.assertIn(str(match.score), briefing)
        self.assertIn(match.profile_summary, briefing)
        for reason in match.why_fit:
            self.assertIn(reason, briefing)
        for reason in match.why_not:
            self.assertIn(reason, briefing)

    def test_discord_slash_run_search_parses_source_and_keyword(self) -> None:
        parsed = parse_discord_command_text('/run-search source:saramin keyword:"backend developer"')

        self.assertTrue(parsed.should_route)
        self.assertEqual(parsed.invocation_kind, "slash")
        self.assertEqual(parsed.command_name, "run-search")
        self.assertEqual(parsed.options["source"], "saramin")
        self.assertEqual(parsed.options["keyword"], "backend developer")

    def test_discord_register_position_slash_command_parses_url(self) -> None:
        parsed = parse_discord_command_text('/register-position url:https://www.wanted.co.kr/wd/363433')

        self.assertTrue(parsed.should_route)
        self.assertEqual(parsed.invocation_kind, "slash")
        self.assertEqual(parsed.command_name, "register-position")
        self.assertEqual(parsed.options["url"], "https://www.wanted.co.kr/wd/363433")

    def test_discord_bot_mention_register_position_parses_text(self) -> None:
        parsed = parse_discord_command_text(
            '<@1512101118543397056> register-position text:"여기어때 Cloud Security & Tech Leader"',
            bot_user_id="1512101118543397056",
        )

        self.assertTrue(parsed.should_route)
        self.assertEqual(parsed.invocation_kind, "mention")
        self.assertEqual(parsed.command_name, "register-position")
        self.assertEqual(parsed.options["text"], "여기어때 Cloud Security & Tech Leader")

    def test_discord_bot_mention_command_parses_without_free_text_prefix(self) -> None:
        parsed = parse_discord_command_text(
            '<@1512101118543397056> session-status',
            bot_user_id="1512101118543397056",
        )

        self.assertTrue(parsed.should_route)
        self.assertEqual(parsed.invocation_kind, "mention")
        self.assertEqual(parsed.command_name, "session-status")

    def test_discord_server_channel_requires_allowlisted_channel_and_identity(self) -> None:
        users = authorized_discord_users_from_markdown(
            """
| Name | Alias | Email | Discord ID |
| --- | --- | --- | --- |
| 김충수 |  | kcs@valueconnect.kr | 834330913469890570 |
"""
        )
        invocation = DiscordInvocation(
            user_id="834330913469890570",
            channel_id="123456789012345678",
            guild_id="123456789012345679",
            command_name="search-status",
            is_dm=False,
            invocation_kind="slash",
        )

        allowed = route_discord_invocation(
            invocation,
            authorized_users=users,
            config=DiscordAccessConfig(allowed_channel_ids=("123456789012345678",)),
        )
        rejected = route_discord_invocation(
            invocation,
            authorized_users=users,
            config=DiscordAccessConfig(allowed_channel_ids=("999999999999999999",)),
        )

        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.response_visibility, "ephemeral")
        self.assertFalse(rejected.allowed)
        self.assertIn("not allowlisted", rejected.reason)

    def test_discord_server_channel_accepts_allowed_role_without_dm_contact(self) -> None:
        invocation = DiscordInvocation(
            user_id="999999999999999999",
            channel_id="123456789012345678",
            guild_id="123456789012345679",
            command_name="search-status",
            is_dm=False,
            invocation_kind="mention",
            member_role_ids=("222222222222222222",),
        )

        decision = route_discord_invocation(
            invocation,
            authorized_users=(),
            config=DiscordAccessConfig(
                allowed_channel_ids=("123456789012345678",),
                allowed_role_ids=("222222222222222222",),
            ),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.response_visibility, "public_ack_then_dm")

    def test_discord_access_config_loads_channel_and_role_allowlists_from_env(self) -> None:
        config = load_discord_access_config(
            {
                "DISCORD_ALLOWED_CHANNEL_IDS": "123456789012345678, 999999999999999999",
                "DISCORD_ALLOWED_ROLE_IDS": "222222222222222222",
                "DISCORD_ALLOW_DM_COMMANDS": "false",
            }
        )

        self.assertEqual(config.allowed_channel_ids, ("123456789012345678", "999999999999999999"))
        self.assertEqual(config.allowed_role_ids, ("222222222222222222",))
        self.assertFalse(config.allow_dm)

    def test_discord_safe_default_does_not_require_message_content_intent(self) -> None:
        self.assertFalse(discord_message_content_intent_required(free_text_channel_commands=False))
        self.assertTrue(discord_message_content_intent_required(free_text_channel_commands=True))
        command_names = {payload["name"] for payload in discord_slash_command_payloads()}
        self.assertEqual(
            {"search-status", "run-search", "register-position", "session-status", "relogin-needed"},
            command_names,
        )

    def test_timeout_recovery_uses_discord_jd_before_clickup_retry(self) -> None:
        payload = build_timeout_recovery_payload(
            discord_report=(
                "대상:\nhttps://app.clickup.com/t/86ew25gkz\n"
                "처리 결과: 중단\n결과: 600초 제한 시간 초과\n"
                "Claude 세션 한도 도달\n"
                "후보자 저장: 0건\nClickUp 기록: 0건\nSupabase 저장: 0건\n제안 발송: 0건"
            ),
            latest_message=(
                "이 포지션 후보자 찾아줘 https://app.clickup.com/t/86ew25gkz\n"
                "기술/도메인 요구\nPhysical AI / Robotics\nWMX Engine, ROS2 패키지 설계 및 노드 개발\n"
                "NVIDIA Isaac Sim/Lab\nC/C++ 임베디드 제어\nFleet management system, HW 관련 분야 관심자 적합\n"
                "전문연구요원 채용 TO 별도 운영 중"
            ),
        )

        self.assertTrue(payload["issue"]["codex_timed_out"])  # type: ignore[index]
        self.assertEqual(payload["issue"]["codex_timeout_seconds"], 600)  # type: ignore[index]
        self.assertTrue(payload["issue"]["claude_session_limited"])  # type: ignore[index]
        self.assertTrue(payload["issue"]["side_effects_zero"])  # type: ignore[index]
        self.assertTrue(payload["routing_decision"]["use_discord_text_before_clickup_fetch"])  # type: ignore[index]
        self.assertIn("ROS2", payload["search_plan"]["must_have_terms"])  # type: ignore[index]
        self.assertEqual(payload["side_effects"]["candidate_saved"], 0)  # type: ignore[index]


class PortalLoginHumanInterventionTests(unittest.IsolatedAsyncioTestCase):
    def test_storage_state_encryption_round_trips_without_plaintext_cookie(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"x" * 32))
        plaintext = json.dumps(
            {
                "cookies": [{"name": "session", "value": "plain-cookie-secret"}],
                "origins": [],
            }
        ).encode("utf-8")

        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)

        self.assertEqual(decrypted, plaintext)
        self.assertNotIn(b"plain-cookie-secret", encrypted)

    async def test_capture_validated_snapshot_saves_only_validated_current_and_lkg(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"y" * 32))
        store = InMemorySessionSnapshotStore()
        first_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "first-secret"}],
                "origins": [],
            }
        )
        rejected_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "poison-secret"}],
                "origins": [],
            }
        )
        second_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "second-secret"}],
                "origins": [],
            }
        )

        first = await capture_validated_snapshot(
            context=first_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        rejected = await capture_validated_snapshot(
            context=rejected_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: False,
            captured_at="2026-06-09T00:01:00+00:00",
        )
        second = await capture_validated_snapshot(
            context=second_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:02:00+00:00",
        )

        current = store.get(site="saramin", worker_id="worker-a", kind="current")
        last_known_good = store.get(site="saramin", worker_id="worker-a", kind="last_known_good")
        self.assertIsNotNone(first)
        self.assertIsNone(rejected)
        self.assertIsNotNone(second)
        self.assertEqual(current, second)
        self.assertEqual(last_known_good.storage_state_enc, first.storage_state_enc)  # type: ignore[union-attr]
        self.assertNotIn(b"poison-secret", current.storage_state_enc)  # type: ignore[union-attr]

    async def test_capture_validated_snapshot_rejects_empty_site_state_before_validation(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"e" * 32))
        store = InMemorySessionSnapshotStore()
        context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".evil.test", "name": "evil", "value": "drop-cookie"}],
                "origins": [
                    {
                        "origin": "https://evil.test",
                        "localStorage": [{"name": "token", "value": "drop-local"}],
                    }
                ],
            }
        )
        validator_called = False

        def validator(_state: Mapping[str, object]) -> bool:
            nonlocal validator_called
            validator_called = True
            return True

        record = await capture_validated_snapshot(
            context=context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=validator,
            captured_at="2026-06-09T00:00:00+00:00",
        )

        self.assertIsNone(record)
        self.assertFalse(validator_called)
        self.assertIsNone(store.latest_validated(site="saramin", worker_id="worker-a"))

    async def test_reinject_storage_state_uses_manual_cookies_and_local_storage(self) -> None:
        context = FakeSnapshotContext()
        state = {
            "cookies": [{"domain": ".jobkorea.co.kr", "name": "jk", "value": "secret"}],
            "origins": [
                {
                    "origin": "https://www.jobkorea.co.kr",
                    "localStorage": [{"name": "token", "value": "local-secret"}],
                }
            ],
        }

        await reinject_storage_state(context, state)

        self.assertEqual(
            context.added_cookies,
            [{"domain": ".jobkorea.co.kr", "path": "/", "name": "jk", "value": "secret"}],
        )
        self.assertEqual(context.pages[0].goto_calls, ["https://www.jobkorea.co.kr"])
        self.assertIn({"name": "token", "value": "local-secret"}, context.pages[0].evaluate_calls[0][1])  # type: ignore[operator]
        self.assertTrue(context.pages[0].closed)

    async def test_reinject_storage_state_filters_to_site_scope_when_site_is_provided(self) -> None:
        context = FakeSnapshotContext()
        state = {
            "cookies": [
                {"domain": ".saramin.co.kr", "name": "saramin", "value": "keep-cookie"},
                {"domain": ".evil.test", "name": "evil", "value": "drop-cookie"},
                {"url": "https://jobs.saramin.co.kr", "name": "saramin-url", "value": "keep-url-cookie"},
                {"url": "https://evil.test", "name": "evil-url", "value": "drop-url-cookie"},
            ],
            "origins": [
                {
                    "origin": "https://www.saramin.co.kr",
                    "localStorage": [{"name": "token", "value": "keep-local"}],
                },
                {
                    "origin": "https://evil.test",
                    "localStorage": [{"name": "token", "value": "drop-local"}],
                },
            ],
        }

        await reinject_storage_state(context, state, site="saramin")

        self.assertEqual(
            context.added_cookies,
            [
                {"domain": ".saramin.co.kr", "path": "/", "name": "saramin", "value": "keep-cookie"},
                {"url": "https://jobs.saramin.co.kr", "name": "saramin-url", "value": "keep-url-cookie"},
            ],
        )
        self.assertEqual(len(context.pages), 1)
        self.assertEqual(context.pages[0].goto_calls, ["https://www.saramin.co.kr"])
        self.assertIn({"name": "token", "value": "keep-local"}, context.pages[0].evaluate_calls[0][1])  # type: ignore[operator]

    async def test_reinject_storage_state_normalizes_cookie_shape_and_skips_malformed_items(self) -> None:
        context = FakeSnapshotContext()
        state = {
            "cookies": [
                {"domain": ".jobkorea.co.kr", "name": "needs-path", "value": "keep"},
                {"domain": ".jobkorea.co.kr", "path": "/Corp", "name": "has-path", "value": "keep"},
                {"domain": ".jobkorea.co.kr", "name": "missing-value"},
                {"domain": ".jobkorea.co.kr", "name": "non-string-value", "value": 123},
                {"domain": ".evil-jobkorea.co.kr.example.com", "name": "spoof", "value": "drop"},
                {"url": "https://www.jobkorea.co.kr", "name": "url-cookie", "value": "keep"},
            ],
            "origins": [
                {
                    "origin": "https://www.jobkorea.co.kr",
                    "localStorage": [
                        {"name": "token", "value": "keep-local"},
                        {"name": "missing-value"},
                        {"name": "non-string-value", "value": 123},
                        {"name": "", "value": "empty-name"},
                    ],
                },
                {
                    "origin": "https://evil-jobkorea.co.kr.example.com",
                    "localStorage": [{"name": "token", "value": "drop-local"}],
                },
            ],
        }

        await reinject_storage_state(context, state, site="jobkorea")

        self.assertEqual(
            context.added_cookies,
            [
                {"domain": ".jobkorea.co.kr", "path": "/", "name": "needs-path", "value": "keep"},
                {"domain": ".jobkorea.co.kr", "path": "/Corp", "name": "has-path", "value": "keep"},
                {"url": "https://www.jobkorea.co.kr", "name": "url-cookie", "value": "keep"},
            ],
        )
        self.assertEqual(len(context.pages), 1)
        self.assertEqual(context.pages[0].goto_calls, ["https://www.jobkorea.co.kr"])
        self.assertEqual(context.pages[0].evaluate_calls[0][1], [{"name": "token", "value": "keep-local"}])

    async def test_capture_validated_snapshot_saves_only_site_scoped_state(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"s" * 32))
        store = InMemorySessionSnapshotStore()
        seen_states: list[Mapping[str, object]] = []
        context = FakeSnapshotContext(
            {
                "cookies": [
                    {"domain": ".saramin.co.kr", "name": "saramin", "value": "keep-cookie"},
                    {"domain": ".evil.test", "name": "evil", "value": "drop-cookie"},
                ],
                "origins": [
                    {
                        "origin": "https://www.saramin.co.kr",
                        "localStorage": [{"name": "token", "value": "keep-local"}],
                    },
                    {
                        "origin": "https://evil.test",
                        "localStorage": [{"name": "token", "value": "drop-local"}],
                    },
                ],
            }
        )

        def validator(state: Mapping[str, object]) -> bool:
            seen_states.append(state)
            return True

        record = await capture_validated_snapshot(
            context=context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=validator,
            captured_at="2026-06-09T00:00:00+00:00",
        )

        saved_state = decode_storage_state(encryptor.decrypt(record.storage_state_enc))  # type: ignore[union-attr]
        serialized = json.dumps(saved_state, ensure_ascii=False)
        self.assertEqual(saved_state, seen_states[0])
        self.assertIn("keep-cookie", serialized)
        self.assertIn("keep-local", serialized)
        self.assertNotIn("drop-cookie", serialized)
        self.assertNotIn("drop-local", serialized)

    async def test_linkedin_snapshot_validation_uses_supplied_cdp_browser(self) -> None:
        class LaunchForbiddenChromium:
            async def launch(self, **_kwargs: object) -> object:
                raise AssertionError("LinkedIn snapshot validation must not launch headless Chromium")

        class FakeValidationBrowser:
            def __init__(self) -> None:
                self.context = FakeSnapshotContext()
                self.closed = False

            async def new_context(self) -> FakeSnapshotContext:
                return self.context

            async def close(self) -> None:
                self.closed = True

        playwright = type("FakeValidationPlaywright", (), {"chromium": LaunchForbiddenChromium()})()
        browser = FakeValidationBrowser()

        async def ready_check(page: FakeSnapshotPage) -> bool:
            return page.goto_calls[-1] == "https://www.linkedin.com/talent/home"

        validated = await validate_snapshot_by_reinjection(
            playwright=playwright,
            browser=browser,
            site="linkedin_rps",
            state={"cookies": [{"domain": ".linkedin.com", "name": "li_at", "value": "secret"}], "origins": []},
            ready_check=ready_check,
        )

        self.assertTrue(validated)
        self.assertFalse(browser.closed)
        self.assertTrue(browser.context.closed)
        self.assertEqual(browser.context.added_cookies[0]["domain"], ".linkedin.com")

    async def test_snapshot_validation_closes_owned_browser_when_context_creation_fails(self) -> None:
        class FailingValidationBrowser:
            def __init__(self) -> None:
                self.closed = False

            async def new_context(self) -> object:
                raise RuntimeError("new context failed with cookie-secret")

            async def close(self) -> None:
                self.closed = True

        class FakeValidationChromium:
            def __init__(self, browser: FailingValidationBrowser) -> None:
                self.browser = browser

            async def launch(self, **_kwargs: object) -> FailingValidationBrowser:
                return self.browser

        browser = FailingValidationBrowser()
        playwright = type("FakeValidationPlaywright", (), {"chromium": FakeValidationChromium(browser)})()

        async def ready_check(_page: object) -> bool:
            return True

        with self.assertRaises(RuntimeError):
            await validate_snapshot_by_reinjection(
                playwright=playwright,
                site="saramin",
                state={"cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "secret"}]},
                ready_check=ready_check,
            )

        self.assertTrue(browser.closed)

    async def test_snapshot_validation_closes_owned_browser_when_context_close_fails(self) -> None:
        class CloseFailingSnapshotContext(FakeSnapshotContext):
            async def close(self) -> None:
                self.closed = True
                raise RuntimeError("context close failed with cookie-secret")

        class CloseFailingValidationBrowser:
            def __init__(self) -> None:
                self.context = CloseFailingSnapshotContext()
                self.closed = False

            async def new_context(self) -> CloseFailingSnapshotContext:
                return self.context

            async def close(self) -> None:
                self.closed = True

        class FakeValidationChromium:
            def __init__(self, browser: CloseFailingValidationBrowser) -> None:
                self.browser = browser

            async def launch(self, **_kwargs: object) -> CloseFailingValidationBrowser:
                return self.browser

        browser = CloseFailingValidationBrowser()
        playwright = type("FakeValidationPlaywright", (), {"chromium": FakeValidationChromium(browser)})()

        async def ready_check(_page: object) -> bool:
            return True

        with self.assertRaises(RuntimeError):
            await validate_snapshot_by_reinjection(
                playwright=playwright,
                site="saramin",
                state={"cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "secret"}]},
                ready_check=ready_check,
            )

        self.assertTrue(browser.context.closed)
        self.assertTrue(browser.closed)

    async def test_restore_latest_validated_snapshot_reinjects_decrypted_state(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"z" * 32))
        store = InMemorySessionSnapshotStore()
        source_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "saramin", "value": "secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=source_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        target_context = FakeSnapshotContext()

        restored = await restore_latest_validated_snapshot(
            context=target_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
        )

        self.assertTrue(restored)
        self.assertEqual(
            target_context.added_cookies,
            [{"domain": ".saramin.co.kr", "path": "/", "name": "saramin", "value": "secret"}],
        )

    async def test_restore_snapshot_ignores_local_storage_page_close_failure(self) -> None:
        class CloseFailingSnapshotPage(FakeSnapshotPage):
            async def close(self) -> None:
                self.closed = True
                raise RuntimeError("local storage close failed with cookie-secret")

        class CloseFailingReinjectContext(FakeSnapshotContext):
            async def new_page(self) -> CloseFailingSnapshotPage:
                page = CloseFailingSnapshotPage()
                self.pages.append(page)
                return page

        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"c" * 32))
        store = InMemorySessionSnapshotStore()
        source_context = FakeSnapshotContext(
            {
                "cookies": [],
                "origins": [
                    {
                        "origin": "https://www.saramin.co.kr",
                        "localStorage": [{"name": "token", "value": "restore-secret"}],
                    }
                ],
            }
        )
        await capture_validated_snapshot(
            context=source_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        target_context = CloseFailingReinjectContext()

        restored = await restore_latest_validated_snapshot(
            context=target_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
        )

        self.assertTrue(restored)
        self.assertEqual(target_context.pages[0].goto_calls, ["https://www.saramin.co.kr"])
        self.assertIn({"name": "token", "value": "restore-secret"}, target_context.pages[0].evaluate_calls[0][1])  # type: ignore[operator]
        self.assertTrue(target_context.pages[0].closed)

    async def test_restore_latest_validated_snapshot_filters_legacy_cross_site_state(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"l" * 32))
        store = InMemorySessionSnapshotStore()
        legacy_state = {
            "cookies": [
                {"domain": ".saramin.co.kr", "name": "saramin", "value": "keep-cookie"},
                {"domain": ".evil.test", "name": "evil", "value": "drop-cookie"},
            ],
            "origins": [
                {
                    "origin": "https://www.saramin.co.kr",
                    "localStorage": [{"name": "token", "value": "keep-local"}],
                },
                {
                    "origin": "https://evil.test",
                    "localStorage": [{"name": "token", "value": "drop-local"}],
                },
            ],
        }
        store.save_validated_current(
            site="saramin",
            worker_id="worker-a",
            storage_state_enc=encryptor.encrypt(encode_storage_state(legacy_state)),
            captured_at="2026-06-09T00:00:00+00:00",
        )
        target_context = FakeSnapshotContext()

        restored = await restore_latest_validated_snapshot(
            context=target_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
        )

        self.assertTrue(restored)
        self.assertEqual(
            target_context.added_cookies,
            [{"domain": ".saramin.co.kr", "path": "/", "name": "saramin", "value": "keep-cookie"}],
        )
        self.assertEqual(len(target_context.pages), 1)
        self.assertEqual(target_context.pages[0].goto_calls, ["https://www.saramin.co.kr"])
        self.assertIn({"name": "token", "value": "keep-local"}, target_context.pages[0].evaluate_calls[0][1])  # type: ignore[operator]

    async def test_restore_validated_snapshot_falls_back_to_lkg_when_current_has_no_site_state(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"b" * 32))
        store = InMemorySessionSnapshotStore()
        good_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "saramin", "value": "lkg-secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=good_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        store.save_validated_current(
            site="saramin",
            worker_id="worker-a",
            storage_state_enc=encryptor.encrypt(
                encode_storage_state(
                    {
                        "cookies": [{"domain": ".evil.test", "name": "evil", "value": "drop"}],
                        "origins": [
                            {
                                "origin": "https://evil.test",
                                "localStorage": [{"name": "token", "value": "drop"}],
                            }
                        ],
                    }
                )
            ),
            captured_at="2026-06-09T00:01:00+00:00",
        )
        target_context = FakeSnapshotContext()

        restored = await restore_latest_validated_snapshot(
            context=target_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
        )

        self.assertTrue(restored)
        self.assertEqual(
            target_context.added_cookies,
            [{"domain": ".saramin.co.kr", "path": "/", "name": "saramin", "value": "lkg-secret"}],
        )

    async def test_restore_validated_snapshot_falls_back_to_lkg_when_current_is_corrupt(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"z" * 32))
        store = InMemorySessionSnapshotStore()
        good_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "saramin", "value": "lkg-secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=good_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        store.save_validated_current(
            site="saramin",
            worker_id="worker-a",
            storage_state_enc=encryptor.encrypt(b"not-json"),
            captured_at="2026-06-09T00:01:00+00:00",
        )
        target_context = FakeSnapshotContext()

        restored = await restore_latest_validated_snapshot(
            context=target_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
        )

        self.assertTrue(restored)
        self.assertEqual(
            target_context.added_cookies,
            [{"domain": ".saramin.co.kr", "path": "/", "name": "saramin", "value": "lkg-secret"}],
        )

    async def test_recovery_uses_snapshot_before_auto_relogin(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"r" * 32))
        store = InMemorySessionSnapshotStore()
        source_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".jobkorea.co.kr", "name": "jk", "value": "secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=source_context,
            site="jobkorea",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        event_store = InMemoryReauthEventStore()
        target_context = FakeSnapshotContext()
        auto_login_called = False

        async def auto_relogin(_context: object, _site: str, _credentials: PortalCredentials) -> bool:
            nonlocal auto_login_called
            auto_login_called = True
            return True

        async def ready_after_restore(_page: FakeSnapshotPage) -> bool:
            return True

        decision = await recover_after_reauth(
            context=target_context,
            attempt=PortalSearchAttempt(
                channel="jobkorea",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="cookie_rotated",
            ),
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            auto_relogin=auto_relogin,
            post_recovery_ready_check=ready_after_restore,
        )

        self.assertTrue(decision.recovered)
        self.assertEqual(decision.recovered_by, "snapshot_reinject")
        self.assertFalse(auto_login_called)
        self.assertEqual(target_context.added_cookies[0]["value"], "secret")
        self.assertEqual(event_store.events[0].recovered_by, "snapshot_reinject")

    async def test_snapshot_recovery_success_ignores_ready_page_close_failure(self) -> None:
        class CloseFailingSnapshotPage(FakeSnapshotPage):
            async def close(self) -> None:
                self.closed = True
                raise RuntimeError("ready page close failed with cookie-secret")

        class CloseFailingReadyContext(FakeSnapshotContext):
            async def new_page(self) -> CloseFailingSnapshotPage:
                page = CloseFailingSnapshotPage()
                self.pages.append(page)
                return page

        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"q" * 32))
        store = InMemorySessionSnapshotStore()
        source_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".jobkorea.co.kr", "name": "jk", "value": "secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=source_context,
            site="jobkorea",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        event_store = InMemoryReauthEventStore()
        target_context = CloseFailingReadyContext()

        async def ready_after_restore(_page: FakeSnapshotPage) -> bool:
            return True

        decision = await recover_after_reauth(
            context=target_context,
            attempt=PortalSearchAttempt(
                channel="jobkorea",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="cookie_rotated",
            ),
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            post_recovery_ready_check=ready_after_restore,
        )

        self.assertTrue(decision.recovered)
        self.assertEqual(decision.recovered_by, "snapshot_reinject")
        self.assertTrue(target_context.pages[0].closed)
        self.assertEqual(event_store.events[0].recovered_by, "snapshot_reinject")

    async def test_recovery_does_not_count_snapshot_restore_without_ready_check(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"o" * 32))
        store = InMemorySessionSnapshotStore()
        source_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".jobkorea.co.kr", "name": "jk", "value": "restore-secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=source_context,
            site="jobkorea",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        event_store = InMemoryReauthEventStore()
        target_context = FakeSnapshotContext()

        decision = await recover_after_reauth(
            context=target_context,
            attempt=PortalSearchAttempt(
                channel="jobkorea",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="cookie_rotated",
            ),
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
        )

        self.assertFalse(decision.recovered)
        self.assertEqual(decision.recovered_by, "unrecovered")
        self.assertEqual(target_context.added_cookies[0]["value"], "restore-secret")
        self.assertEqual(event_store.events[0].recovered_by, "unrecovered")

    async def test_recovery_does_not_record_snapshot_reinject_until_ready_after_restore(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"n" * 32))
        store = InMemorySessionSnapshotStore()
        source_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".jobkorea.co.kr", "name": "jk", "value": "restore-secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=source_context,
            site="jobkorea",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        event_store = InMemoryReauthEventStore()
        target_context = FakeSnapshotContext()
        ready_pages: list[FakeSnapshotPage] = []

        async def not_ready_after_restore(page: FakeSnapshotPage) -> bool:
            ready_pages.append(page)
            return False

        decision = await recover_after_reauth(
            context=target_context,
            attempt=PortalSearchAttempt(
                channel="jobkorea",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="cookie_rotated",
            ),
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            post_recovery_ready_check=not_ready_after_restore,
        )

        self.assertFalse(decision.recovered)
        self.assertEqual(decision.recovered_by, "unrecovered")
        self.assertEqual(target_context.added_cookies[0]["value"], "restore-secret")
        self.assertEqual(ready_pages[0].goto_calls, ["https://www.jobkorea.co.kr/Corp/Person/Find"])
        self.assertTrue(ready_pages[0].closed)
        self.assertEqual(event_store.events[0].recovered_by, "unrecovered")

    async def test_linkedin_recovery_uses_snapshot_before_human_alert(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"y" * 32))
        store = InMemorySessionSnapshotStore()
        source_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".linkedin.com", "name": "li_at", "value": "secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=source_context,
            site="linkedin_rps",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        event_store = InMemoryReauthEventStore()
        target_context = FakeSnapshotContext()

        class FakeCredentialProvider:
            def load(self, _site: str) -> PortalCredentials:
                raise AssertionError("LinkedIn credential provider must not be called")

        async def auto_relogin(_context: object, site: str, _credentials: PortalCredentials) -> bool:
            raise AssertionError(f"LinkedIn auto relogin must never run for {site}")

        async def ready_after_restore(_page: FakeSnapshotPage) -> bool:
            return True

        decision = await recover_after_reauth(
            context=target_context,
            attempt=PortalSearchAttempt(
                channel="linkedin_rps",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="forced_logout",
            ),
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            credential_provider=FakeCredentialProvider(),
            auto_relogin=auto_relogin,
            post_recovery_ready_check=ready_after_restore,
        )

        self.assertTrue(decision.recovered)
        self.assertEqual(decision.recovered_by, "snapshot_reinject")
        self.assertFalse(decision.pause_site)
        self.assertFalse(decision.discord_alert_sent)
        self.assertEqual(target_context.added_cookies[0]["value"], "secret")
        self.assertEqual(event_store.events[0].site, "linkedin_rps")
        self.assertEqual(event_store.events[0].recovered_by, "snapshot_reinject")

    async def test_saramin_recovery_auto_relogin_runs_only_after_snapshot_failure(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"s" * 32))
        store = InMemorySessionSnapshotStore()
        event_store = InMemoryReauthEventStore()
        credentials_seen: list[PortalCredentials] = []
        case = self

        class FakeCredentialProvider:
            def load(self, site: str) -> PortalCredentials:
                case.assertEqual(site, "saramin")
                return PortalCredentials(username="user-secret", password="password-secret")

        async def auto_relogin(_context: object, site: str, credentials: PortalCredentials) -> bool:
            self.assertEqual(site, "saramin")
            credentials_seen.append(credentials)
            return True

        async def ready_after_relogin(_page: FakeSnapshotPage) -> bool:
            return True

        decision = await recover_after_reauth(
            context=FakeSnapshotContext(),
            attempt=PortalSearchAttempt(
                channel="saramin",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="forced_logout",
            ),
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            credential_provider=FakeCredentialProvider(),
            auto_relogin=auto_relogin,
            post_recovery_ready_check=ready_after_relogin,
        )

        self.assertTrue(decision.recovered)
        self.assertEqual(decision.recovered_by, "auto_relogin")
        self.assertEqual(len(credentials_seen), 1)
        self.assertNotIn("password-secret", repr(credentials_seen[0]))
        self.assertEqual(event_store.events[0].recovered_by, "auto_relogin")

    async def test_recovery_tries_auto_relogin_after_snapshot_restore_is_not_ready(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"c" * 32))
        store = InMemorySessionSnapshotStore()
        source_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "stale-secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=source_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        event_store = InMemoryReauthEventStore()
        target_context = FakeSnapshotContext()
        ready_results = [False, True]
        auto_login_called: list[str] = []
        case = self

        class FakeCredentialProvider:
            def load(self, site: str) -> PortalCredentials:
                case.assertEqual(site, "saramin")
                return PortalCredentials(username="user-secret", password="password-secret")

        async def auto_relogin(_context: object, site: str, _credentials: PortalCredentials) -> bool:
            auto_login_called.append(site)
            return True

        async def ready_after_recovery(page: FakeSnapshotPage) -> bool:
            self.assertTrue(page.goto_calls)
            return ready_results.pop(0)

        decision = await recover_after_reauth(
            context=target_context,
            attempt=PortalSearchAttempt(
                channel="saramin",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="cookie_rotated",
            ),
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            credential_provider=FakeCredentialProvider(),
            auto_relogin=auto_relogin,
            post_recovery_ready_check=ready_after_recovery,
        )

        self.assertTrue(decision.recovered)
        self.assertEqual(decision.recovered_by, "auto_relogin")
        self.assertEqual(auto_login_called, ["saramin"])
        self.assertEqual(target_context.added_cookies[0]["value"], "stale-secret")
        self.assertEqual(len(target_context.pages), 2)
        self.assertTrue(all(page.closed for page in target_context.pages))
        self.assertEqual(event_store.events[0].recovered_by, "auto_relogin")

    async def test_auto_relogin_retries_transient_errors_with_exponential_backoff(self) -> None:
        # A transient failure (network / timeout) during auto-relogin must be retried
        # with exponential backoff (1s, 2s, ...) rather than abandoned after one attempt.
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"r" * 32))
        store = InMemorySessionSnapshotStore()  # empty -> snapshot restore fails first
        event_store = InMemoryReauthEventStore()
        context = FakeSnapshotContext()
        attempts: list[str] = []
        slept: list[float] = []
        case = self

        class FakeCredentialProvider:
            def load(self, site: str) -> PortalCredentials:
                case.assertEqual(site, "saramin")
                return PortalCredentials(username="user-secret", password="password-secret")

        async def auto_relogin(_context: object, site: str, _credentials: PortalCredentials) -> bool:
            attempts.append(site)
            if len(attempts) < 3:
                raise ConnectionError("transient network failure during relogin")
            return True

        async def ready_after_recovery(_page: FakeSnapshotPage) -> bool:
            return True

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        decision = await recover_after_reauth(
            context=context,
            attempt=PortalSearchAttempt(
                channel="saramin",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="forced_logout",
            ),
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            credential_provider=FakeCredentialProvider(),
            auto_relogin=auto_relogin,
            post_recovery_ready_check=ready_after_recovery,
            sleep=fake_sleep,
        )

        self.assertTrue(decision.recovered)
        self.assertEqual(decision.recovered_by, "auto_relogin")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(slept, [1.0, 2.0])
        self.assertEqual(event_store.events[0].recovered_by, "auto_relogin")

    async def test_auto_relogin_does_not_retry_on_security_challenge_false(self) -> None:
        # A clean False from auto_relogin means a captcha / 2FA / checkpoint was detected.
        # SOT invariant: NEVER hammer a security challenge — try exactly once, no backoff.
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"s" * 32))
        store = InMemorySessionSnapshotStore()  # empty -> snapshot restore fails first
        event_store = InMemoryReauthEventStore()
        context = FakeSnapshotContext()
        attempts: list[str] = []
        slept: list[float] = []

        class FakeCredentialProvider:
            def load(self, _site: str) -> PortalCredentials:
                return PortalCredentials(username="user-secret", password="password-secret")

        async def auto_relogin(_context: object, site: str, _credentials: PortalCredentials) -> bool:
            attempts.append(site)
            return False  # security challenge detected

        async def ready_after_recovery(_page: FakeSnapshotPage) -> bool:
            return True

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        decision = await recover_after_reauth(
            context=context,
            attempt=PortalSearchAttempt(
                channel="saramin",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="forced_logout",
            ),
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            credential_provider=FakeCredentialProvider(),
            auto_relogin=auto_relogin,
            post_recovery_ready_check=ready_after_recovery,
            sleep=fake_sleep,
        )

        self.assertFalse(decision.recovered)
        self.assertEqual(decision.recovered_by, "unrecovered")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(slept, [])

    async def test_recovery_does_not_count_auto_relogin_without_ready_check(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"a" * 32))
        event_store = InMemoryReauthEventStore()
        context = FakeSnapshotContext()
        auto_login_called: list[str] = []
        case = self

        class FakeCredentialProvider:
            def load(self, site: str) -> PortalCredentials:
                case.assertEqual(site, "saramin")
                return PortalCredentials(username="user-secret", password="password-secret")

        async def auto_relogin(_context: object, site: str, _credentials: PortalCredentials) -> bool:
            auto_login_called.append(site)
            return True

        decision = await recover_after_reauth(
            context=context,
            attempt=PortalSearchAttempt(
                channel="saramin",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="forced_logout",
            ),
            encryptor=encryptor,
            snapshot_store=InMemorySessionSnapshotStore(),
            event_store=event_store,
            credential_provider=FakeCredentialProvider(),
            auto_relogin=auto_relogin,
        )

        self.assertEqual(auto_login_called, ["saramin"])
        self.assertFalse(decision.recovered)
        self.assertEqual(decision.recovered_by, "unrecovered")
        self.assertEqual(context.pages, [])
        self.assertEqual(event_store.events[0].recovered_by, "unrecovered")

    async def test_recovery_does_not_count_auto_relogin_until_ready_check_passes(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"b" * 32))
        event_store = InMemoryReauthEventStore()
        context = FakeSnapshotContext()
        ready_pages: list[FakeSnapshotPage] = []
        case = self

        class FakeCredentialProvider:
            def load(self, site: str) -> PortalCredentials:
                case.assertEqual(site, "jobkorea")
                return PortalCredentials(username="user-secret", password="password-secret")

        async def auto_relogin(_context: object, _site: str, _credentials: PortalCredentials) -> bool:
            return True

        async def not_ready_after_relogin(page: FakeSnapshotPage) -> bool:
            ready_pages.append(page)
            return False

        decision = await recover_after_reauth(
            context=context,
            attempt=PortalSearchAttempt(
                channel="jobkorea",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="login_redirect",
            ),
            encryptor=encryptor,
            snapshot_store=InMemorySessionSnapshotStore(),
            event_store=event_store,
            credential_provider=FakeCredentialProvider(),
            auto_relogin=auto_relogin,
            post_recovery_ready_check=not_ready_after_relogin,
        )

        self.assertFalse(decision.recovered)
        self.assertEqual(decision.recovered_by, "unrecovered")
        self.assertEqual(ready_pages[0].goto_calls, ["https://www.jobkorea.co.kr/Corp/Person/Find"])
        self.assertTrue(ready_pages[0].closed)
        self.assertEqual(event_store.events[0].recovered_by, "unrecovered")

    async def test_saramin_recovery_records_unrecovered_when_credentials_fail(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"u" * 32))
        event_store = InMemoryReauthEventStore()

        class FailingCredentialProvider:
            def load(self, _site: str) -> PortalCredentials:
                raise RuntimeError("keychain unavailable")

        async def auto_relogin(_context: object, _site: str, _credentials: PortalCredentials) -> bool:
            raise AssertionError("auto relogin should not run without credentials")

        decision = await recover_after_reauth(
            context=FakeSnapshotContext(),
            attempt=PortalSearchAttempt(
                channel="saramin",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="forced_logout",
            ),
            encryptor=encryptor,
            snapshot_store=InMemorySessionSnapshotStore(),
            event_store=event_store,
            credential_provider=FailingCredentialProvider(),
            auto_relogin=auto_relogin,
        )

        self.assertFalse(decision.recovered)
        self.assertEqual(decision.recovered_by, "unrecovered")
        self.assertEqual(event_store.events[0].site, "saramin")
        self.assertEqual(event_store.events[0].cause, "forced_logout")
        self.assertEqual(event_store.events[0].recovered_by, "unrecovered")

    async def test_jobkorea_recovery_records_unrecovered_when_auto_relogin_raises(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"v" * 32))
        event_store = InMemoryReauthEventStore()

        class FakeCredentialProvider:
            def load(self, _site: str) -> PortalCredentials:
                return PortalCredentials(username="user-secret", password="password-secret")

        async def auto_relogin(_context: object, _site: str, _credentials: PortalCredentials) -> bool:
            raise RuntimeError("login form changed")

        decision = await recover_after_reauth(
            context=FakeSnapshotContext(),
            attempt=PortalSearchAttempt(
                channel="jobkorea",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="login_redirect",
            ),
            encryptor=encryptor,
            snapshot_store=InMemorySessionSnapshotStore(),
            event_store=event_store,
            credential_provider=FakeCredentialProvider(),
            auto_relogin=auto_relogin,
        )

        self.assertFalse(decision.recovered)
        self.assertEqual(decision.recovered_by, "unrecovered")
        self.assertEqual(event_store.events[0].site, "jobkorea")
        self.assertEqual(event_store.events[0].cause, "login_redirect")
        self.assertEqual(event_store.events[0].recovered_by, "unrecovered")

    async def test_saramin_recovery_surfaces_reauth_event_record_failure(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"w" * 32))

        class FailingEventStore:
            def record(self, **_kwargs: object) -> ReauthEvent:
                raise RuntimeError("supabase unavailable")

        decision = await recover_after_reauth(
            context=FakeSnapshotContext(),
            attempt=PortalSearchAttempt(
                channel="saramin",
                worker_id="worker-a",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="forced_logout",
            ),
            encryptor=encryptor,
            snapshot_store=InMemorySessionSnapshotStore(),
            event_store=FailingEventStore(),
        )

        payload = safe_recovery_payload(decision)

        self.assertFalse(decision.recovered)
        self.assertEqual(decision.recovered_by, "unrecovered")
        self.assertFalse(decision.reauth_event_recorded)
        self.assertFalse(payload["reauth_event_recorded"])

    async def test_linkedin_recovery_alerts_even_when_reauth_event_record_fails(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"x" * 32))
        sent: list[str] = []

        class FailingEventStore:
            def record(self, **_kwargs: object) -> ReauthEvent:
                raise RuntimeError("supabase unavailable")

        class FakeResponse:
            status = 204

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            sent.append(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            return FakeResponse()

        decision = await recover_after_reauth(
            context=FakeSnapshotContext(),
            attempt=PortalSearchAttempt(
                channel="linkedin_rps",
                worker_id="default",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="forced_logout",
            ),
            encryptor=encryptor,
            snapshot_store=InMemorySessionSnapshotStore(),
            event_store=FailingEventStore(),
            discord_notifier=DiscordWebhookNotifier(
                webhook_url="https://discord.example.test/webhook",
                urlopen=fake_urlopen,
            ),
        )

        self.assertFalse(decision.recovered)
        self.assertEqual(decision.recovered_by, "human")
        self.assertTrue(decision.pause_site)
        self.assertTrue(decision.discord_alert_sent)
        self.assertFalse(decision.reauth_event_recorded)
        self.assertIn("linkedin_rps", sent[0])

    async def test_linkedin_recovery_auto_relogs_from_secret_store(self) -> None:
        # SOT invariant: LinkedIn RPS recovers via automatic credential relogin from the
        # secret store, like saramin/jobkorea. auto_relogin_portal never bypasses a
        # captcha/2FA/checkpoint; on detection it returns False and the human fallback runs.
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"l" * 32))
        store = InMemorySessionSnapshotStore()
        event_store = InMemoryReauthEventStore()
        credential_loads: list[str] = []
        credentials_seen: list[PortalCredentials] = []

        class FakeCredentialProvider:
            def load(self, site: str) -> PortalCredentials:
                credential_loads.append(site)
                return PortalCredentials(username="linkedin-user", password="linkedin-secret")

        async def auto_relogin(_context: object, site: str, credentials: PortalCredentials) -> bool:
            self.assertEqual(site, "linkedin_rps")
            credentials_seen.append(credentials)
            return True

        async def ready_after_relogin(_page: FakeSnapshotPage) -> bool:
            return True

        decision = await recover_after_reauth(
            context=FakeSnapshotContext(),
            attempt=PortalSearchAttempt(
                channel="linkedin_rps",
                worker_id="default",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="forced_logout",
            ),
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            credential_provider=FakeCredentialProvider(),
            auto_relogin=auto_relogin,
            post_recovery_ready_check=ready_after_relogin,
        )

        self.assertTrue(decision.recovered)
        self.assertEqual(decision.recovered_by, "auto_relogin")
        self.assertEqual(credential_loads, ["linkedin_rps"])
        self.assertNotIn("linkedin-secret", repr(credentials_seen[0]))
        self.assertEqual(event_store.events[0].recovered_by, "auto_relogin")

    async def test_linkedin_recovery_ignores_supplied_auto_relogin_and_alerts_human(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"l" * 32))
        store = InMemorySessionSnapshotStore()
        event_store = InMemoryReauthEventStore()
        sent: list[str] = []
        auto_relogin_called: list[str] = []

        class FakeResponse:
            status = 204

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            sent.append(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            return FakeResponse()

        class FakeCredentialProvider:
            def load(self, _site: str) -> PortalCredentials:
                raise AssertionError("LinkedIn credential provider must not be called")

        async def auto_relogin(_context: object, site: str, _credentials: PortalCredentials) -> bool:
            auto_relogin_called.append(site)
            return True

        decision = await recover_after_reauth(
            context=FakeSnapshotContext(),
            attempt=PortalSearchAttempt(
                channel="linkedin_rps",
                worker_id="default",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="forced_logout",
            ),
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            credential_provider=FakeCredentialProvider(),
            auto_relogin=auto_relogin,
            discord_notifier=DiscordWebhookNotifier(
                webhook_url="https://discord.example.test/webhook",
                urlopen=fake_urlopen,
            ),
        )

        self.assertEqual(auto_relogin_called, [])
        self.assertFalse(decision.recovered)
        self.assertTrue(decision.pause_site)
        self.assertTrue(decision.discord_alert_sent)
        self.assertEqual(decision.recovered_by, "human")
        self.assertIn("linkedin_rps", sent[0])
        self.assertEqual(event_store.events[0].recovered_by, "human")

    async def test_linkedin_recovery_pauses_site_when_discord_alert_fails(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"m" * 32))
        event_store = InMemoryReauthEventStore()

        def failing_urlopen(_request: object, *, timeout: int) -> object:
            raise RuntimeError("discord unavailable")

        decision = await recover_after_reauth(
            context=FakeSnapshotContext(),
            attempt=PortalSearchAttempt(
                channel="linkedin_rps",
                worker_id="default",
                keyword="backend",
                status="not_ready",
                reason="reauth required",
                reauth_cause="forced_logout",
            ),
            encryptor=encryptor,
            snapshot_store=InMemorySessionSnapshotStore(),
            event_store=event_store,
            discord_notifier=DiscordWebhookNotifier(
                webhook_url="https://discord.example.test/webhook",
                urlopen=failing_urlopen,
            ),
        )

        self.assertFalse(decision.recovered)
        self.assertEqual(decision.recovered_by, "human")
        self.assertTrue(decision.pause_site)
        self.assertFalse(decision.discord_alert_sent)
        self.assertEqual(event_store.events[0].site, "linkedin_rps")
        self.assertEqual(event_store.events[0].cause, "forced_logout")
        self.assertEqual(event_store.events[0].recovered_by, "human")

    async def test_login_selector_preflight_reports_no_drift_when_all_present(self) -> None:
        page = FakeAutoLoginPage(
            available_selectors={'input[name="id"]', 'input[name="password"]', 'button[type="submit"]'},
            submit_selectors={'button[type="submit"]'},
            ready_url="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
        )
        preflight = await login_selector_preflight(page, "saramin")
        self.assertFalse(preflight.drifted)
        self.assertEqual(preflight.missing_roles, ())
        self.assertTrue(preflight.username_found)
        self.assertTrue(preflight.password_found)
        self.assertTrue(preflight.submit_found)

    async def test_login_selector_preflight_flags_missing_password_as_drift(self) -> None:
        page = FakeAutoLoginPage(
            available_selectors={'input[name="id"]', 'button[type="submit"]'},  # no password field
            submit_selectors={'button[type="submit"]'},
            ready_url="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
        )
        preflight = await login_selector_preflight(page, "saramin")
        self.assertTrue(preflight.drifted)
        self.assertEqual(preflight.missing_roles, ("password",))
        self.assertTrue(preflight.username_found)
        self.assertFalse(preflight.password_found)
        self.assertTrue(preflight.submit_found)

    async def test_login_selector_preflight_supports_linkedin_rps(self) -> None:
        page = FakeAutoLoginPage(
            available_selectors={"#username", "#password", 'button[type="submit"]'},
            submit_selectors={'button[type="submit"]'},
            ready_url="https://www.linkedin.com/talent/home",
        )
        preflight = await login_selector_preflight(page, "linkedin_rps")
        self.assertFalse(preflight.drifted)
        self.assertEqual(preflight.missing_roles, ())
        self.assertTrue(preflight.username_found)
        self.assertTrue(preflight.password_found)
        self.assertTrue(preflight.submit_found)

    async def test_saramin_auto_relogin_fills_keychain_credentials_and_revalidates(self) -> None:
        page = FakeAutoLoginPage(
            available_selectors={'input[name="id"]', 'input[name="password"]', 'button[type="submit"]'},
            submit_selectors={'button[type="submit"]'},
            ready_url="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
        )
        context = FakeAutoLoginContext(page)
        credentials = PortalCredentials(username="valueconnect", password="password-secret")

        recovered = await auto_relogin_portal(context, "saramin", credentials)

        self.assertTrue(recovered)
        self.assertIn(('input[name="id"]', "valueconnect"), page.filled)
        self.assertIn(('input[name="password"]', "password-secret"), page.filled)
        self.assertEqual(page.clicked, ['button[type="submit"]'])
        self.assertGreaterEqual(len(page.goto_calls), 2)
        self.assertTrue(page.closed)

    async def test_jobkorea_auto_relogin_uses_site_specific_login_selectors(self) -> None:
        page = FakeAutoLoginPage(
            available_selectors={"#M_ID", "#M_PWD", "#lb_login"},
            submit_selectors={"#lb_login"},
            ready_url="https://www.jobkorea.co.kr/Corp/Person/Find",
        )
        context = FakeAutoLoginContext(page)
        credentials = PortalCredentials(username="valueconnect", password="password-secret")

        recovered = await auto_relogin_portal(context, "jobkorea", credentials)

        self.assertTrue(recovered)
        self.assertIn(("#M_ID", "valueconnect"), page.filled)
        self.assertIn(("#M_PWD", "password-secret"), page.filled)
        self.assertEqual(page.clicked, ["#lb_login"])
        self.assertTrue(page.closed)

    async def test_auto_relogin_success_ignores_login_page_close_failure(self) -> None:
        class CloseFailingAutoLoginPage(FakeAutoLoginPage):
            async def close(self) -> None:
                self.closed = True
                raise RuntimeError("auto login close failed with cookie-secret")

        page = CloseFailingAutoLoginPage(
            available_selectors={'input[name="id"]', 'input[name="password"]', 'button[type="submit"]'},
            submit_selectors={'button[type="submit"]'},
            ready_url="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
        )

        recovered = await auto_relogin_portal(
            FakeAutoLoginContext(page),
            "saramin",
            PortalCredentials(username="valueconnect", password="password-secret"),
        )

        self.assertTrue(recovered)
        self.assertTrue(page.closed)

    async def test_auto_relogin_closes_login_page_when_form_is_missing(self) -> None:
        page = FakeAutoLoginPage(
            available_selectors=set(),
            submit_selectors=set(),
            ready_url="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
        )
        context = FakeAutoLoginContext(page)

        recovered = await auto_relogin_portal(
            context,
            "saramin",
            PortalCredentials(username="valueconnect", password="password-secret"),
        )

        self.assertFalse(recovered)
        self.assertEqual(page.filled, [])
        self.assertTrue(page.closed)

    async def test_linkedin_auto_relogin_fills_keychain_credentials_and_revalidates(self) -> None:
        page = FakeAutoLoginPage(
            available_selectors={"#username", "#password", 'button[type="submit"]'},
            submit_selectors={'button[type="submit"]'},
            ready_url="https://www.linkedin.com/talent/home",
        )
        context = FakeAutoLoginContext(page)
        credentials = PortalCredentials(username="linkedin-user", password="linkedin-secret")

        recovered = await auto_relogin_portal(context, "linkedin_rps", credentials)

        self.assertTrue(recovered)
        self.assertIn(("#username", "linkedin-user"), page.filled)
        self.assertIn(("#password", "linkedin-secret"), page.filled)
        self.assertEqual(page.clicked, ['button[type="submit"]'])
        self.assertGreaterEqual(len(page.goto_calls), 2)
        self.assertTrue(page.closed)

    async def test_auto_relogin_refuses_unconfigured_channel(self) -> None:
        # public_web has no login form/credentials and must still raise.
        with self.assertRaises(ValueError):
            await auto_relogin_portal(
                FakeAutoLoginContext(
                    FakeAutoLoginPage(
                        available_selectors=set(),
                        submit_selectors=set(),
                        ready_url="",
                    )
                ),
                "public_web",
                PortalCredentials(username="blocked", password="blocked"),
            )

    async def test_guarded_runtime_success_captures_validated_snapshot_after_search(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"g" * 32))
        store = InMemorySessionSnapshotStore()
        event_store = InMemoryReauthEventStore()
        context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "safe-secret"}],
                "origins": [],
            }
        )
        worker = FakeRuntimeWorker(
            channel="saramin",
            worker_id="worker-a",
            context=context,
            attempts=[
                PortalSearchAttempt(
                    channel="saramin",
                    worker_id="worker-a",
                    keyword="backend",
                    status="searched",
                    reason="searched on persistent profile",
                )
            ],
        )
        sleeps: list[float] = []

        async def sleep(seconds: float) -> None:
            sleeps.append(seconds)

        runner = GuardedPortalSearchRunner(
            worker=worker,
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            snapshot_validator=lambda _state: True,
            pacing_policies={"saramin": SitePacingPolicy("saramin", 1, 1, 1, 1, 10)},
            sleep=sleep,
        )

        result = await runner.run_keyword_search("backend", searches_today=0)
        current = store.get(site="saramin", worker_id="worker-a", kind="current")

        self.assertEqual(result.status, "searched")
        self.assertTrue(result.snapshot_captured)
        self.assertEqual(result.snapshot_kind, "current")
        self.assertEqual(worker.calls, ["backend"])
        self.assertEqual(sleeps, [1])
        self.assertIsNotNone(current)
        self.assertNotIn(b"safe-secret", current.storage_state_enc)  # type: ignore[union-attr]

    async def test_guarded_runtime_rejects_unvalidated_snapshot_after_search(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"p" * 32))
        store = InMemorySessionSnapshotStore()
        worker = FakeRuntimeWorker(
            channel="jobkorea",
            worker_id="worker-a",
            context=FakeSnapshotContext(
                {
                    "cookies": [{"domain": ".jobkorea.co.kr", "name": "jk", "value": "poison-secret"}],
                    "origins": [],
                }
            ),
            attempts=[
                PortalSearchAttempt(
                    channel="jobkorea",
                    worker_id="worker-a",
                    keyword="backend",
                    status="searched",
                    reason="searched on persistent profile",
                )
            ],
        )
        runner = GuardedPortalSearchRunner(
            worker=worker,
            encryptor=encryptor,
            snapshot_store=store,
            event_store=InMemoryReauthEventStore(),
            snapshot_validator=lambda _state: False,
            pacing_policies={"jobkorea": SitePacingPolicy("jobkorea", 1, 1, 1, 1, 10)},
            sleep=None,
        )

        result = await runner.run_keyword_search("backend", searches_today=0)

        self.assertEqual(result.status, "searched")
        self.assertFalse(result.snapshot_captured)
        self.assertIsNone(store.latest_validated(site="jobkorea", worker_id="worker-a"))
        self.assertNotIn("poison-secret", repr(result))

    async def test_guarded_runtime_snapshot_store_error_preserves_search_evidence(self) -> None:
        class FailingSnapshotStore(InMemorySessionSnapshotStore):
            def save_validated_current(self, **_kwargs: object) -> EncryptedSessionSnapshot:
                raise RuntimeError("snapshot store unavailable")

        worker = FakeRuntimeWorker(
            channel="jobkorea",
            worker_id="default",
            context=FakeSnapshotContext(
                {
                    "cookies": [{"domain": ".jobkorea.co.kr", "name": "jk", "value": "safe-secret"}],
                    "origins": [],
                }
            ),
            attempts=[
                PortalSearchAttempt(
                    channel="jobkorea",
                    worker_id="default",
                    keyword="backend",
                    status="searched",
                    reason="searched on persistent profile",
                    candidate_cards=(
                        CandidateResultCard(
                            profile_url="https://www.jobkorea.co.kr/Person/Profile/1",
                            source_channel="jobkorea",
                            snippet="Backend Engineer",
                        ),
                    ),
                )
            ],
        )
        runner = GuardedPortalSearchRunner(
            worker=worker,
            encryptor=OpenSslSessionEncryptor(StaticSessionKeyProvider(b"s" * 32)),
            snapshot_store=FailingSnapshotStore(),
            event_store=InMemoryReauthEventStore(),
            snapshot_validator=lambda _state: True,
            pacing_policies={"jobkorea": SitePacingPolicy("jobkorea", 1, 1, 1, 1, 10)},
            sleep=None,
        )

        result = await runner.run_keyword_search("backend", searches_today=0)
        payload = safe_result_payload(result)

        self.assertEqual(result.status, "error")
        self.assertEqual(result.reason, "snapshot capture failed: RuntimeError")
        self.assertEqual(result.attempt.status, "searched")  # type: ignore[union-attr]
        self.assertEqual(len(result.candidate_cards), 1)
        self.assertEqual(payload["attempt_status"], "searched")
        self.assertEqual(payload["result_count"], 1)
        self.assertNotIn("safe-secret", json.dumps(payload, ensure_ascii=False))

    async def test_guarded_runtime_pacing_cap_blocks_without_worker_call(self) -> None:
        worker = FakeRuntimeWorker(
            channel="linkedin_rps",
            worker_id="default",
            context=FakeSnapshotContext(),
            attempts=[],
        )
        runner = GuardedPortalSearchRunner(
            worker=worker,
            encryptor=OpenSslSessionEncryptor(StaticSessionKeyProvider(b"c" * 32)),
            snapshot_store=InMemorySessionSnapshotStore(),
            event_store=InMemoryReauthEventStore(),
            snapshot_validator=lambda _state: True,
            pacing_policies={"linkedin_rps": SitePacingPolicy("linkedin_rps", 1, 1, 1, 1, 2)},
            sleep=None,
        )

        result = await runner.run_keyword_search("backend", searches_today=2)

        self.assertEqual(result.status, "pacing_blocked")
        self.assertTrue(result.skipped_due_to_cap)
        self.assertEqual(worker.calls, [])
        self.assertEqual(result.reason, "daily protected-portal search cap reached")

    async def test_guarded_runtime_records_unrecovered_when_recovery_orchestrator_fails(self) -> None:
        worker = FakeRuntimeWorker(
            channel="saramin",
            worker_id="worker-a",
            context=FakeSnapshotContext(),
            attempts=[
                PortalSearchAttempt(
                    channel="saramin",
                    worker_id="worker-a",
                    keyword="backend",
                    status="not_ready",
                    reason="reauth required during search",
                    reauth_cause="forced_logout",
                )
            ],
        )
        event_store = InMemoryReauthEventStore()
        runner = GuardedPortalSearchRunner(
            worker=worker,
            encryptor=OpenSslSessionEncryptor(StaticSessionKeyProvider(b"e" * 32)),
            snapshot_store=InMemorySessionSnapshotStore(),
            event_store=event_store,
            snapshot_validator=lambda _state: True,
            pacing_policies={"saramin": SitePacingPolicy("saramin", 1, 1, 1, 1, 10)},
            sleep=None,
        )

        with patch(
            "tools.multi_position_sourcing.portal_runtime.recover_after_reauth",
            side_effect=RuntimeError("unexpected recovery failure"),
        ):
            result = await runner.run_keyword_search("backend", searches_today=0)

        self.assertEqual(result.status, "error")
        self.assertEqual(result.reason, "reauth recovery failed: RuntimeError")
        self.assertEqual(result.recovery_decision.recovered_by, "unrecovered")  # type: ignore[union-attr]
        self.assertTrue(result.recovery_decision.reauth_event_recorded)  # type: ignore[union-attr]
        self.assertEqual(event_store.events[0].site, "saramin")
        self.assertEqual(event_store.events[0].cause, "forced_logout")
        self.assertEqual(event_store.events[0].recovered_by, "unrecovered")

    async def test_guarded_runtime_records_human_and_alerts_when_linkedin_recovery_orchestrator_fails(self) -> None:
        sent: list[str] = []

        class FakeResponse:
            status = 204

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            sent.append(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            return FakeResponse()

        worker = FakeRuntimeWorker(
            channel="linkedin_rps",
            worker_id="default",
            context=FakeSnapshotContext(),
            attempts=[
                PortalSearchAttempt(
                    channel="linkedin_rps",
                    worker_id="default",
                    keyword="backend",
                    status="not_ready",
                    reason="reauth required during search",
                    reauth_cause="forced_logout",
                )
            ],
        )
        event_store = InMemoryReauthEventStore()
        runner = GuardedPortalSearchRunner(
            worker=worker,
            encryptor=OpenSslSessionEncryptor(StaticSessionKeyProvider(b"f" * 32)),
            snapshot_store=InMemorySessionSnapshotStore(),
            event_store=event_store,
            snapshot_validator=lambda _state: True,
            discord_notifier=DiscordWebhookNotifier(
                webhook_url="https://discord.example.test/webhook",
                urlopen=fake_urlopen,
            ),
            pacing_policies={"linkedin_rps": SitePacingPolicy("linkedin_rps", 1, 1, 1, 1, 10)},
            sleep=None,
        )

        with patch(
            "tools.multi_position_sourcing.portal_runtime.recover_after_reauth",
            side_effect=RuntimeError("unexpected recovery failure"),
        ):
            result = await runner.run_keyword_search("backend", searches_today=0)

        self.assertEqual(result.status, "error")
        self.assertTrue(result.pause_site)
        self.assertEqual(result.recovery_decision.recovered_by, "human")  # type: ignore[union-attr]
        self.assertTrue(result.recovery_decision.discord_alert_sent)  # type: ignore[union-attr]
        self.assertEqual(event_store.events[0].site, "linkedin_rps")
        self.assertEqual(event_store.events[0].recovered_by, "human")
        self.assertIn("linkedin_rps", sent[0])

    async def test_guarded_runtime_snapshot_recovery_retries_and_captures_fresh_snapshot(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"v" * 32))
        store = InMemorySessionSnapshotStore()
        source_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "restore-secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=source_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        target_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "fresh-secret"}],
                "origins": [],
            }
        )
        worker = FakeRuntimeWorker(
            channel="saramin",
            worker_id="worker-a",
            context=target_context,
            attempts=[
                PortalSearchAttempt(
                    channel="saramin",
                    worker_id="worker-a",
                    keyword="backend",
                    status="not_ready",
                    reason="reauth required during search",
                    reauth_cause="http_401",
                ),
                PortalSearchAttempt(
                    channel="saramin",
                    worker_id="worker-a",
                    keyword="backend",
                    status="searched",
                    reason="retried after snapshot restore",
                ),
            ],
        )
        event_store = InMemoryReauthEventStore()

        async def ready_after_restore(_page: FakeSnapshotPage) -> bool:
            return True

        runner = GuardedPortalSearchRunner(
            worker=worker,
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            snapshot_validator=lambda _state: True,
            ready_check=ready_after_restore,
            pacing_policies={"saramin": SitePacingPolicy("saramin", 1, 1, 1, 1, 10)},
            sleep=None,
        )

        result = await runner.run_keyword_search("backend", searches_today=0)
        current = store.get(site="saramin", worker_id="worker-a", kind="current")
        last_known_good = store.get(site="saramin", worker_id="worker-a", kind="last_known_good")
        current_state = decode_storage_state(encryptor.decrypt(current.storage_state_enc))  # type: ignore[union-attr]
        last_known_good_state = decode_storage_state(encryptor.decrypt(last_known_good.storage_state_enc))  # type: ignore[union-attr]

        self.assertEqual(result.status, "searched")
        self.assertTrue(result.retried_after_recovery)
        self.assertTrue(result.snapshot_captured)
        self.assertEqual(result.recovery_decision.recovered_by, "snapshot_reinject")  # type: ignore[union-attr]
        self.assertEqual(worker.calls, ["backend", "backend"])
        self.assertEqual(target_context.added_cookies[0]["value"], "restore-secret")
        self.assertEqual(event_store.events[0].recovered_by, "snapshot_reinject")
        self.assertEqual(current_state["cookies"][0]["value"], "fresh-secret")  # type: ignore[index]
        self.assertEqual(last_known_good_state["cookies"][0]["value"], "restore-secret")  # type: ignore[index]

    async def test_guarded_runtime_does_not_count_snapshot_restore_until_ready_check_passes(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"m" * 32))
        store = InMemorySessionSnapshotStore()
        source_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "restore-secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=source_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        target_context = FakeSnapshotContext()
        worker = FakeRuntimeWorker(
            channel="saramin",
            worker_id="worker-a",
            context=target_context,
            attempts=[
                PortalSearchAttempt(
                    channel="saramin",
                    worker_id="worker-a",
                    keyword="backend",
                    status="not_ready",
                    reason="reauth required during search",
                    reauth_cause="http_401",
                )
            ],
        )
        event_store = InMemoryReauthEventStore()
        ready_pages: list[FakeSnapshotPage] = []

        async def not_ready_after_restore(page: FakeSnapshotPage) -> bool:
            ready_pages.append(page)
            return False

        runner = GuardedPortalSearchRunner(
            worker=worker,
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            snapshot_validator=lambda _state: True,
            ready_check=not_ready_after_restore,
            pacing_policies={"saramin": SitePacingPolicy("saramin", 1, 1, 1, 1, 10)},
            sleep=None,
        )

        result = await runner.run_keyword_search("backend", searches_today=0)

        self.assertEqual(result.status, "not_ready")
        self.assertFalse(result.recovery_decision.recovered)  # type: ignore[union-attr]
        self.assertEqual(result.recovery_decision.recovered_by, "unrecovered")  # type: ignore[union-attr]
        self.assertFalse(result.retried_after_recovery)
        self.assertEqual(worker.calls, ["backend"])
        self.assertEqual(target_context.added_cookies[0]["value"], "restore-secret")
        self.assertEqual(ready_pages[0].goto_calls, ["https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"])
        self.assertTrue(ready_pages[0].closed)
        self.assertEqual(event_store.events[0].recovered_by, "unrecovered")

    async def test_guarded_runtime_profile_corrupt_override_survives_snapshot_recovery(self) -> None:
        encryptor = OpenSslSessionEncryptor(StaticSessionKeyProvider(b"q" * 32))
        store = InMemorySessionSnapshotStore()
        source_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "restore-secret"}],
                "origins": [],
            }
        )
        await capture_validated_snapshot(
            context=source_context,
            site="saramin",
            worker_id="worker-a",
            encryptor=encryptor,
            store=store,
            validator=lambda _state: True,
            captured_at="2026-06-09T00:00:00+00:00",
        )
        target_context = FakeSnapshotContext(
            {
                "cookies": [{"domain": ".saramin.co.kr", "name": "session", "value": "fresh-secret"}],
                "origins": [],
            }
        )
        worker = FakeRuntimeWorker(
            channel="saramin",
            worker_id="worker-a",
            context=target_context,
            attempts=[
                PortalSearchAttempt(
                    channel="saramin",
                    worker_id="worker-a",
                    keyword="backend",
                    status="not_ready",
                    reason="login marker missing after profile deletion",
                    reauth_cause="login_marker_missing",
                ),
                PortalSearchAttempt(
                    channel="saramin",
                    worker_id="worker-a",
                    keyword="backend",
                    status="searched",
                    reason="retried after snapshot restore",
                ),
            ],
        )
        event_store = InMemoryReauthEventStore()

        async def ready_after_restore(_page: FakeSnapshotPage) -> bool:
            return True

        runner = GuardedPortalSearchRunner(
            worker=worker,
            encryptor=encryptor,
            snapshot_store=store,
            event_store=event_store,
            snapshot_validator=lambda _state: True,
            ready_check=ready_after_restore,
            pacing_policies={"saramin": SitePacingPolicy("saramin", 1, 1, 1, 1, 10)},
            sleep=None,
        )

        result = await runner.run_keyword_search(
            "backend",
            searches_today=0,
            reauth_cause_override="profile_corrupt",
        )
        payload = safe_result_payload(result, profile_deleted_before_start=True)

        self.assertEqual(result.status, "searched")
        self.assertEqual(result.reauth_cause, "profile_corrupt")
        self.assertEqual(result.recovery_decision.recovered_by, "snapshot_reinject")  # type: ignore[union-attr]
        self.assertEqual(event_store.events[0].cause, "profile_corrupt")
        self.assertEqual(payload["reauth_cause"], "profile_corrupt")
        self.assertTrue(payload["profile_deleted_before_start"])
        self.assertEqual(target_context.added_cookies[0]["value"], "restore-secret")

    async def test_profile_recovery_smoke_skips_live_search_without_validated_snapshot(self) -> None:
        config = LiveSearchConfig(
            channel="jobkorea",
            keyword="backend",
            worker_id="default",
            profile_root=Path("/tmp/valuehire-test-profiles"),
            chrome_cdp_endpoint="http://127.0.0.1:9222",
            headless=False,
            searches_today=0,
            no_sleep=True,
            disable_auto_relogin=False,
            delete_profile_before_start=False,
            confirm_delete_profile="/tmp/valuehire-test-profiles/jobkorea/default",
        )
        live_search = AsyncMock()

        with patch(
            "tools.multi_position_sourcing.portal_live_check.snapshot_metadata_payload",
            return_value={
                "kind": "session_snapshot_metadata",
                "site": "jobkorea",
                "worker_id": "default",
                "status": "unavailable",
                "snapshot_present": False,
            },
        ), patch("tools.multi_position_sourcing.portal_live_check.run_live_search", live_search):
            payload = await run_profile_recovery_smoke(config)

        self.assertEqual(payload["status"], "not_run")
        self.assertEqual(payload["kind"], "portal_profile_recovery_smoke")
        self.assertEqual(payload["recovery_policy"], "snapshot_only_no_auto_relogin")
        self.assertTrue(payload["auto_relogin_disabled"])
        self.assertFalse(payload["profile_deleted_before_start"])
        live_search.assert_not_called()

    async def test_profile_recovery_smoke_marks_success_payload_snapshot_only(self) -> None:
        config = LiveSearchConfig(
            channel="saramin",
            keyword="backend",
            worker_id="default",
            profile_root=Path("/tmp/valuehire-test-profiles"),
            chrome_cdp_endpoint="http://127.0.0.1:9222",
            headless=False,
            searches_today=0,
            no_sleep=True,
            disable_auto_relogin=False,
            delete_profile_before_start=False,
            confirm_delete_profile="/tmp/valuehire-test-profiles/saramin/default",
        )
        live_search = AsyncMock(
            return_value={
                "site": "saramin",
                "worker_id": "default",
                "keyword": "backend",
                "generated_at": "2026-06-09T00:00:00+00:00",
                "mode": "guarded",
                "status": "searched",
                "reason": "retried after snapshot restore",
                "reauth_cause": "profile_corrupt",
                "snapshot_capture_required": True,
                "snapshot_capture_policy": "required",
                "snapshot_captured": True,
                "retried_after_recovery": True,
                "profile_deleted_before_start": True,
                "recovery": {
                    "recovered": True,
                    "recovered_by": "snapshot_reinject",
                    "reauth_event_recorded": True,
                },
            }
        )

        with patch(
            "tools.multi_position_sourcing.portal_live_check.snapshot_metadata_payload",
            return_value={
                "kind": "session_snapshot_metadata",
                "site": "saramin",
                "worker_id": "default",
                "status": "present",
                "snapshot_present": True,
                "is_validated": True,
                "encrypted_envelope": "VHSS1",
            },
        ), patch("tools.multi_position_sourcing.portal_live_check.run_live_search", live_search):
            payload = await run_profile_recovery_smoke(config)

        self.assertEqual(payload["kind"], "portal_profile_recovery_smoke")
        self.assertEqual(payload["recovery_policy"], "snapshot_only_no_auto_relogin")
        self.assertTrue(payload["auto_relogin_disabled"])
        self.assertEqual(payload["recovery"]["recovered_by"], "snapshot_reinject")  # type: ignore[index]
        recovery_config = live_search.call_args.args[0]
        self.assertTrue(recovery_config.disable_auto_relogin)
        self.assertTrue(recovery_config.delete_profile_before_start)
        self.assertFalse(recovery_config.profile_only)

    async def test_guarded_runtime_linkedin_reauth_pauses_site_and_alerts(self) -> None:
        sent: list[str] = []

        class FakeResponse:
            status = 204

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        def fake_urlopen(request: object, *, timeout: int) -> FakeResponse:
            sent.append(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            return FakeResponse()

        worker = FakeRuntimeWorker(
            channel="linkedin_rps",
            worker_id="default",
            context=FakeSnapshotContext(),
            attempts=[
                PortalSearchAttempt(
                    channel="linkedin_rps",
                    worker_id="default",
                    keyword="backend",
                    status="not_ready",
                    reason="reauth required during search",
                    reauth_cause="forced_logout",
                )
            ],
        )
        event_store = InMemoryReauthEventStore()
        runner = GuardedPortalSearchRunner(
            worker=worker,
            encryptor=OpenSslSessionEncryptor(StaticSessionKeyProvider(b"h" * 32)),
            snapshot_store=InMemorySessionSnapshotStore(),
            event_store=event_store,
            snapshot_validator=lambda _state: True,
            discord_notifier=DiscordWebhookNotifier(
                webhook_url="https://discord.example.test/webhook",
                urlopen=fake_urlopen,
            ),
            pacing_policies={"linkedin_rps": SitePacingPolicy("linkedin_rps", 1, 1, 1, 1, 10)},
            sleep=None,
        )

        result = await runner.run_keyword_search("backend", searches_today=0)

        self.assertEqual(result.status, "not_ready")
        self.assertTrue(result.pause_site)
        self.assertFalse(result.retried_after_recovery)
        self.assertEqual(worker.calls, ["backend"])
        self.assertEqual(result.recovery_decision.recovered_by, "human")  # type: ignore[union-attr]
        self.assertEqual(event_store.events[0].recovered_by, "human")
        self.assertIn("linkedin_rps", sent[0])

    def test_clear_stale_singleton_locks_removes_only_chromium_lock_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            profile = Path(tmp)
            # Real saved-login data — MUST be preserved (the whole point of the profile).
            (profile / "Cookies").write_text("login-secret")
            (profile / "Default").mkdir()
            (profile / "Default" / "Cookies").write_text("login-secret-2")
            (profile / "Local State").write_text("{}")
            # Stale Chromium singleton artifacts left by a crashed run.
            (profile / "SingletonLock").symlink_to("somehost-12345")
            (profile / "SingletonCookie").write_text("x")
            (profile / "SingletonSocket").write_text("x")

            removed = clear_stale_singleton_locks(profile)

            self.assertEqual(set(removed), {"SingletonLock", "SingletonCookie", "SingletonSocket"})
            self.assertFalse((profile / "SingletonLock").is_symlink())
            self.assertFalse((profile / "SingletonCookie").exists())
            self.assertFalse((profile / "SingletonSocket").exists())
            # Saved login data untouched.
            self.assertTrue((profile / "Cookies").exists())
            self.assertEqual((profile / "Cookies").read_text(), "login-secret")
            self.assertTrue((profile / "Default" / "Cookies").exists())
            self.assertTrue((profile / "Local State").exists())

    async def test_worker_start_clears_stale_singleton_locks_before_launch(self) -> None:
        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(
                channel="saramin",
                worker_id="worker-a",
                profile_root=tmp,
                mode="headless",
            )
            profile = config.profile_dir
            profile.mkdir(parents=True, exist_ok=True)
            (profile / "Cookies").write_text("login-secret")
            (profile / "SingletonLock").symlink_to("somehost-999")

            context = FakeContext(available_selectors={'input[name="searchword"]', 'button[name="search"]'})
            worker = PortalWorker(config, playwright=FakePlaywright(context))
            await worker.start()
            await worker.stop()

            self.assertFalse((profile / "SingletonLock").is_symlink())
            self.assertTrue((profile / "Cookies").exists())

    async def test_run_one_search_times_out_when_page_hangs(self) -> None:
        # A page operation that never returns must not pin the worker forever: the
        # per-search timeout turns it into a clean error attempt so the queue moves on.
        import asyncio as _asyncio

        class HangingPage(FakePage):
            async def goto(self, url: str, **_kwargs: object) -> None:
                self.url = url
                self.goto_calls.append(url)
                await _asyncio.Event().wait()  # never resolves

        class HangingContext(FakeContext):
            async def new_page(self) -> FakePage:
                page = HangingPage(self.available_selectors)
                self.pages.append(page)
                return page

        context = HangingContext(available_selectors={'input[name="searchword"]', 'button[name="search"]'})
        playwright = FakePlaywright(context)
        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(
                channel="saramin",
                worker_id="worker-a",
                profile_root=tmp,
                mode="headless",
                search_timeout_seconds=0.05,
            )
            worker = PortalWorker(config, playwright=playwright)
            await worker.start()
            result = await worker.run_one_search("backend")
            await worker.stop()

        self.assertEqual(result.status, "error")
        self.assertIn("timed out", result.reason.lower())
        self.assertEqual(result.channel, "saramin")
        self.assertEqual(result.keyword, "backend")

    async def test_saramin_worker_launches_persistent_context_without_storage_state(self) -> None:
        context = FakeContext(available_selectors={'input[name="searchword"]', 'button[name="search"]'})
        playwright = FakePlaywright(context)
        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(
                channel="saramin",
                worker_id="worker-a",
                profile_root=tmp,
                mode="headless",
                launch_args=("--disable-blink-features=AutomationControlled",),
            )
            worker = PortalWorker(config, playwright=playwright)
            await worker.start()
            await worker.start()
            result = await worker.run_one_search("backend")
            await worker.stop()

        self.assertEqual(result.status, "searched")
        self.assertEqual(len(playwright.chromium.persistent_calls), 1)
        args, kwargs = playwright.chromium.persistent_calls[0]
        self.assertEqual(args[0], str(config.profile_dir))
        self.assertTrue(kwargs["headless"])
        self.assertEqual(kwargs["args"], ["--disable-blink-features=AutomationControlled"])
        self.assertNotIn("storage_state", kwargs)
        self.assertTrue(context.closed)
        self.assertEqual(context.pages[-1].filled, [('input[name="searchword"]', "backend")])
        self.assertEqual(context.pages[-1].clicked, ['button[name="search"]'])

    async def test_jobkorea_worker_keeps_mode_immutable_until_reboot(self) -> None:
        context = FakeContext(available_selectors={"#txtKeyword"})
        playwright = FakePlaywright(context)
        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(channel="jobkorea", worker_id="worker-a", profile_root=tmp, mode="headed")
            worker = PortalWorker(config, playwright=playwright)
            await worker.start()
            await worker.start()
            worker.mark_blocked_for_reboot(next_mode="headless")
            await worker.run_one_search("backend")
            await worker.stop()

        self.assertEqual(worker.blocked_next_mode, "headless")
        self.assertEqual(len(playwright.chromium.persistent_calls), 1)
        args, kwargs = playwright.chromium.persistent_calls[0]
        self.assertEqual(args[0], str(config.profile_dir))
        self.assertFalse(kwargs["headless"])
        self.assertNotIn("storage_state", kwargs)
        self.assertNotIn("storageState", kwargs)
        self.assertEqual(context.pages[-1].pressed, [("#txtKeyword", "Enter")])

    async def test_linkedin_worker_attaches_over_cdp_and_does_not_close_chrome(self) -> None:
        context = FakeContext()
        playwright = FakePlaywright(context)
        # SOT(browser_policy.json) 포트로 attach 해야 검문소를 통과한다. 포트를 바꾸려면
        # 코드에 임의로 박지 말고 규칙 파일 한 곳을 고친다(= 이 SOT 잠금의 핵심).
        config = PortalWorkerConfig(
            channel="linkedin_rps",
            chrome_cdp_endpoint="http://127.0.0.1:9222",
        )
        worker = PortalWorker(config, playwright=playwright)

        await worker.start()
        result = await worker.run_one_search("backend engineer")
        await worker.stop()

        self.assertEqual(result.status, "searched")
        self.assertEqual(playwright.chromium.cdp_calls, ["http://127.0.0.1:9222"])
        self.assertEqual(playwright.chromium.persistent_calls, [])
        self.assertIn("linkedin.com/talent/search", context.pages[-1].goto_calls[-1])
        self.assertFalse(context.closed)
        self.assertFalse(playwright.chromium.browser.closed)

    async def test_portal_worker_error_does_not_echo_exception_secret_url(self) -> None:
        class SecretErrorPage:
            url = "https://user:pass@www.saramin.co.kr/search?cookie=session-secret#token-secret"
            closed = False

            def on(self, _event: str, _handler: object) -> None:
                return None

            async def goto(self, _url: str, **_kwargs: object) -> None:
                raise ValueError(
                    "browser failed at https://user:pass@www.saramin.co.kr/search?cookie=session-secret#token-secret"
                )

            async def close(self) -> None:
                self.closed = True

        class SecretErrorContext(FakeContext):
            async def new_page(self) -> SecretErrorPage:  # type: ignore[override]
                page = SecretErrorPage()
                self.pages.append(page)  # type: ignore[arg-type]
                return page

        context = SecretErrorContext()
        playwright = FakePlaywright(context)
        with TemporaryDirectory() as tmp:
            worker = PortalWorker(
                PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=tmp),
                playwright=playwright,
            )
            result = await worker.run_one_search("backend")
            await worker.stop()

        encoded = json.dumps(safe_attempt_payload(result), ensure_ascii=False)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.reason, "ValueError: portal search failed without exposing details")
        self.assertEqual(result.url, "https://www.saramin.co.kr/search")
        self.assertNotIn("session-secret", encoded)
        self.assertNotIn("token-secret", encoded)
        self.assertNotIn("user:pass", encoded)
        self.assertNotIn("cookie=", encoded.lower())
        self.assertTrue(context.pages[-1].closed)

    async def test_portal_worker_new_page_error_returns_safe_attempt(self) -> None:
        class NewPageErrorContext(FakeContext):
            async def new_page(self) -> FakePage:  # type: ignore[override]
                raise RuntimeError(
                    "new page failed for https://user:pass@www.jobkorea.co.kr?cookie=session-secret#token-secret"
                )

        context = NewPageErrorContext()
        playwright = FakePlaywright(context)
        with TemporaryDirectory() as tmp:
            worker = PortalWorker(
                PortalWorkerConfig(channel="jobkorea", worker_id="worker-a", profile_root=tmp),
                playwright=playwright,
            )
            result = await worker.run_one_search("backend")
            await worker.stop()

        encoded = json.dumps(safe_attempt_payload(result), ensure_ascii=False)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.reason, "RuntimeError: portal search failed without exposing details")
        self.assertEqual(result.url, "")
        self.assertNotIn("session-secret", encoded)
        self.assertNotIn("token-secret", encoded)
        self.assertNotIn("user:pass", encoded)
        self.assertNotIn("cookie=", encoded.lower())

    async def test_portal_worker_selector_missing_returns_safe_attempt(self) -> None:
        class SecretUrlPage(FakePage):
            async def goto(self, _url: str, **_kwargs: object) -> None:
                self.url = "https://user:pass@www.jobkorea.co.kr/search?cookie=session-secret#token-secret"
                self.goto_calls.append(_url)

        class SelectorMissingContext(FakeContext):
            async def new_page(self) -> SecretUrlPage:  # type: ignore[override]
                page = SecretUrlPage()
                self.pages.append(page)  # type: ignore[arg-type]
                return page

        context = SelectorMissingContext()
        playwright = FakePlaywright(context)
        with TemporaryDirectory() as tmp:
            worker = PortalWorker(
                PortalWorkerConfig(channel="jobkorea", worker_id="worker-a", profile_root=tmp),
                playwright=playwright,
            )
            result = await worker.run_one_search("backend")
            await worker.stop()

        encoded = json.dumps(safe_attempt_payload(result), ensure_ascii=False)
        self.assertEqual(result.status, "selector_missing")
        self.assertEqual(result.reason, "RuntimeError: portal selector missing without exposing details")
        self.assertEqual(result.url, "https://www.jobkorea.co.kr/search")
        self.assertNotIn("session-secret", encoded)
        self.assertNotIn("token-secret", encoded)
        self.assertNotIn("user:pass", encoded)
        self.assertNotIn("cookie=", encoded.lower())

    async def test_portal_worker_closes_search_page_without_closing_persistent_context(self) -> None:
        context = FakeContext(available_selectors={'input[name="searchword"]', 'button[name="search"]'})
        playwright = FakePlaywright(context)
        with TemporaryDirectory() as tmp:
            worker = PortalWorker(
                PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=tmp),
                playwright=playwright,
            )
            try:
                result = await worker.run_one_search("backend")

                self.assertEqual(result.status, "searched")
                self.assertTrue(context.pages[-1].closed)
                self.assertFalse(context.closed)
            finally:
                await worker.stop()

    async def test_portal_worker_stop_ignores_context_close_failure_and_releases_lock(self) -> None:
        class CloseFailingContext(FakeContext):
            async def close(self) -> None:
                self.closed = True
                raise RuntimeError("context close failed with cookie-secret")

        class CloseFailingPlaywrightManager:
            def __init__(self) -> None:
                self.closed = False

            async def __aexit__(self, *_exc: object) -> None:
                self.closed = True
                raise RuntimeError("playwright manager close failed with cookie-secret")

        context = CloseFailingContext(available_selectors={'input[name="searchword"]', 'button[name="search"]'})
        playwright = FakePlaywright(context)
        with TemporaryDirectory() as tmp:
            config = PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=tmp)
            worker = PortalWorker(config, playwright=playwright)
            result = await worker.run_one_search("backend")
            manager = CloseFailingPlaywrightManager()
            worker._playwright_manager = manager

            await worker.stop()

            reacquired = ProfileLock(config)
            reacquired.acquire()
            reacquired.release()

        self.assertEqual(result.status, "searched")
        self.assertTrue(context.closed)
        self.assertTrue(manager.closed)
        self.assertIsNone(worker._playwright_manager)

    async def test_search_monitor_marks_reauth_on_401_during_submit(self) -> None:
        context = FakeContext(
            available_selectors={'input[name="searchword"]', 'button[name="search"]'},
            click_response_statuses=(401,),
        )
        playwright = FakePlaywright(context)
        with TemporaryDirectory() as tmp:
            worker = PortalWorker(
                PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=tmp),
                playwright=playwright,
            )
            result = await worker.run_one_search("backend", monitor=SearchLivenessMonitor("saramin"))
            await worker.stop()

        self.assertEqual(result.status, "not_ready")
        self.assertEqual(result.reauth_cause, "http_401")
        self.assertEqual(result.reason, "reauth required during search")

    async def test_search_aborts_when_login_marker_is_lost_during_search(self) -> None:
        context = FakeContext(available_selectors={'input[name="searchword"]', 'button[name="search"]'})
        playwright = FakePlaywright(context)
        ready_results = [True, False]

        async def ready_check(_page: FakePage) -> bool:
            return ready_results.pop(0)

        with TemporaryDirectory() as tmp:
            worker = PortalWorker(
                PortalWorkerConfig(channel="saramin", worker_id="worker-a", profile_root=tmp),
                playwright=playwright,
            )
            result = await worker.run_one_search("backend", ready_check=ready_check)
            await worker.stop()

        self.assertEqual(result.status, "not_ready")
        self.assertEqual(result.reauth_cause, "login_marker_lost")

    async def test_run_search_with_recovery_retries_after_reauth_cause(self) -> None:
        class StubWorker:
            config = type("Config", (), {"channel": "saramin"})()

            def __init__(self) -> None:
                self.calls = 0

            async def run_one_search(
                self,
                keyword: str,
                *,
                ready_check: object | None = None,
                monitor: object | None = None,
            ) -> PortalSearchAttempt:
                self.calls += 1
                if self.calls == 1:
                    return PortalSearchAttempt(
                        channel="saramin",
                        worker_id="worker-a",
                        keyword=keyword,
                        status="not_ready",
                        reason="reauth required during search",
                        reauth_cause="http_401",
                    )
                return PortalSearchAttempt(
                    channel="saramin",
                    worker_id="worker-a",
                    keyword=keyword,
                    status="searched",
                    reason="retried after restore",
                )

        worker = StubWorker()
        recovered: list[str] = []

        async def recover(attempt: PortalSearchAttempt) -> bool:
            recovered.append(attempt.reauth_cause)
            return True

        result = await run_search_with_recovery(worker, "backend", recover=recover)

        self.assertEqual(result.status, "searched")
        self.assertEqual(worker.calls, 2)
        self.assertEqual(recovered, ["http_401"])

    async def test_human_intervention_waits_until_manual_resolution_is_ready(self) -> None:
        class FakePage:
            url = "https://example.com/checkpoint"

            def __init__(self) -> None:
                self.ready_checks = 0
                self.waits = 0

            async def wait_for_timeout(self, _milliseconds: int) -> None:
                self.waits += 1

        page = FakePage()

        async def ready_check(fake_page: FakePage) -> bool:
            fake_page.ready_checks += 1
            if fake_page.ready_checks >= 2:
                fake_page.url = "https://example.com/talent/home"
                return True
            return False

        result = await _wait_for_human_intervention(
            page,
            "linkedin_rps",
            ready_check=ready_check,
            options=HumanInterventionOptions(enabled=True, timeout_seconds=10, poll_interval_seconds=1),
            note="checkpoint detected",
        )

        self.assertTrue(result["ready"])
        self.assertEqual(result["login"], "human_intervention_ok")
        self.assertEqual(page.waits, 1)

    async def test_human_intervention_can_be_disabled_for_headless_runs(self) -> None:
        class FakePage:
            url = "https://example.com/checkpoint"

        async def never_ready(_page: FakePage) -> bool:
            return False

        result = await _wait_for_human_intervention(
            FakePage(),
            "saramin",
            ready_check=never_ready,
            options=HumanInterventionOptions(enabled=False),
            note="security challenge detected",
        )

        self.assertFalse(result["ready"])
        self.assertEqual(result["login"], "human_intervention_disabled")

    def test_security_challenge_detection_includes_2fa_and_checkpoint_terms(self) -> None:
        self.assertTrue(_has_security_challenge("2단계 인증번호를 입력하세요"))
        self.assertTrue(_has_security_challenge("", "https://www.linkedin.com/checkpoint/challenge"))
        self.assertTrue(_has_security_challenge("CAPTCHA required"))


# Rich Wanted-style HTML that yields a confident "text" recognition:
# og:site_name -> company, og:title -> role, body carries >=3 distinct JD signals.
_WANTED_REG_HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta property="og:site_name" content="밸류커넥트">
  <meta property="og:title" content="시니어 백엔드 엔지니어">
</head>
<body>
  <h1>시니어 백엔드 엔지니어</h1>
  <h2>주요업무</h2>
  <p>백엔드 API 설계 및 개발을 담당합니다. 분산 시스템 운영 경험을 쌓습니다.</p>
  <h2>자격요건</h2>
  <p>서버 개발 5년 이상 경력, Python/Go 등 백엔드 언어 숙련.</p>
  <h2>우대사항</h2>
  <p>대규모 트래픽 처리 경험, 채용 포지션 관련 도메인 이해.</p>
</body>
</html>"""


class _RegFakeFetcher:
    """Stdlib fake http_fetch: records calls, returns a fixed FetchResult."""

    def __init__(self, result: FetchResult) -> None:
        self._result = result
        self.calls: list[str] = []

    def __call__(self, url: str) -> FetchResult:
        self.calls.append(url)
        return self._result


class _RegRecordingClickUp:
    """Stdlib fakes for clickup_search / create_task / create_comment with call recording."""

    def __init__(self, existing: tuple[ExistingPositionTask, ...] = ()) -> None:
        self.existing = existing
        self.search_calls = 0
        self.created_tasks: list[tuple[str, str]] = []
        self.created_comments: list[tuple[str, str]] = []

    def search(self, recognition):  # noqa: ANN001 - test fake
        self.search_calls += 1
        return self.existing

    def create_task(self, title: str, body: str) -> tuple[str, str]:
        self.created_tasks.append((title, body))
        return ("task-NEW", "https://app.clickup.com/t/task-NEW")

    def create_comment(self, task_id: str, body: str) -> str:
        self.created_comments.append((task_id, body))
        return "comment-NEW"


class PositionRegistrationExecutionTests(unittest.TestCase):
    """End-to-end execution layer over a real parsed Discord registration request."""

    def _parse_wanted(self):
        return parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )

    def test_new_task_planned_in_dry_run(self) -> None:
        parse_result = self._parse_wanted()
        self.assertTrue(parse_result.should_route_to_registration)
        self.assertEqual(parse_result.input_kind, "wanted_url")

        http_fetch = _RegFakeFetcher(
            FetchResult(
                url=parse_result.url,
                ok=True,
                status_code=200,
                html=_WANTED_REG_HTML,
                fetch_method="httpx",
            )
        )
        clickup = _RegRecordingClickUp(existing=())

        outcome = run_position_registration(
            parse_result,
            http_fetch=http_fetch,
            clickup_search=clickup.search,
            clickup_create_task=clickup.create_task,
            clickup_create_comment=clickup.create_comment,
            dry_run=True,
        )

        self.assertEqual(outcome.status, "created")
        self.assertTrue(outcome.is_new_task)
        self.assertTrue(outcome.dry_run)
        self.assertEqual(outcome.recognition_mode, "text")
        self.assertGreaterEqual(outcome.confidence, 0.55)
        # Dry-run plans only: no real ClickUp create call happened.
        self.assertEqual(clickup.created_tasks, [])
        self.assertEqual(clickup.created_comments, [])
        self.assertEqual(http_fetch.calls, [parse_result.url])
        # Fail-safe invariants always hold.
        self.assertFalse(outcome.external_posting_sent)
        self.assertFalse(outcome.secret_emitted)

    def test_resubmitting_same_url_links_comment_instead_of_creating(self) -> None:
        parse_result = self._parse_wanted()
        http_fetch = _RegFakeFetcher(
            FetchResult(
                url=parse_result.url,
                ok=True,
                status_code=200,
                html=_WANTED_REG_HTML,
                fetch_method="httpx",
            )
        )
        existing = (
            ExistingPositionTask(
                task_id="task-EXISTING",
                task_url="https://app.clickup.com/t/task-EXISTING",
                company="밸류커넥트",
                role="시니어 백엔드 엔지니어",
                source_url="https://www.wanted.co.kr/wd/363433",
            ),
        )
        clickup = _RegRecordingClickUp(existing=existing)

        # not dry-run so the comment is actually linked.
        outcome = run_position_registration(
            parse_result,
            http_fetch=http_fetch,
            clickup_search=clickup.search,
            clickup_create_task=clickup.create_task,
            clickup_create_comment=clickup.create_comment,
            dry_run=False,
        )

        self.assertEqual(outcome.status, "linked")
        self.assertFalse(outcome.is_new_task)
        self.assertEqual(outcome.task_id, "task-EXISTING")
        self.assertEqual(outcome.comment_id, "comment-NEW")
        # Linked a comment, never created a new task.
        self.assertEqual(clickup.created_tasks, [])
        self.assertEqual(len(clickup.created_comments), 1)
        self.assertEqual(clickup.created_comments[0][0], "task-EXISTING")
        self.assertFalse(outcome.external_posting_sent)
        self.assertFalse(outcome.secret_emitted)

    def test_extract_failure_is_fail_closed_skipped(self) -> None:
        parse_result = self._parse_wanted()
        # Blocked fetch with no render fallback -> extraction fails -> skipped.
        http_fetch = _RegFakeFetcher(
            FetchResult(
                url=parse_result.url,
                ok=False,
                status_code=403,
                html="",
                fetch_method="httpx",
                reason="blocked",
            )
        )
        clickup = _RegRecordingClickUp(existing=())

        outcome = run_position_registration(
            parse_result,
            http_fetch=http_fetch,
            clickup_search=clickup.search,
            clickup_create_task=clickup.create_task,
            clickup_create_comment=clickup.create_comment,
            dry_run=True,
        )

        self.assertEqual(outcome.status, "skipped")
        self.assertFalse(outcome.is_new_task)
        # Fail-closed: never searched/created/commented on a failed extraction.
        self.assertEqual(clickup.search_calls, 0)
        self.assertEqual(clickup.created_tasks, [])
        self.assertEqual(clickup.created_comments, [])
        self.assertFalse(outcome.external_posting_sent)
        self.assertFalse(outcome.secret_emitted)

    def test_dry_run_payload_includes_position_registration_execution_sample(self) -> None:
        payload = build_dry_run_payload()
        self.assertIn("sample_position_registration_execution", payload)
        sample = payload["sample_position_registration_execution"]
        self.assertIsInstance(sample, dict)
        # The sample is a dry-run RegistrationOutcome with no real side effects.
        self.assertTrue(sample["dry_run"])
        self.assertIn(sample["status"], {"created", "linked", "skipped"})
        self.assertFalse(sample["external_posting_sent"])
        self.assertFalse(sample["secret_emitted"])
        # Existing side_effects flags meaning intact (no real writes in dry-run).
        self.assertFalse(payload["side_effects"]["clickup_write"])


if __name__ == "__main__":
    unittest.main()
