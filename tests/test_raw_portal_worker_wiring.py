"""PR #149 B2: profile-only 검색의 exact raw single-target 생산 배선."""

from __future__ import annotations

import asyncio
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from tools.multi_position_sourcing.portal_worker import (
    ProfileLock,
    ProfileLockError,
    PortalWorker,
    PortalWorkerConfig,
    SearchLivenessMonitor,
)
from tools.multi_position_sourcing.raw_page_adapter import RawPage
from tools.multi_position_sourcing.portal_login import ready_check_for_channel


class ForbiddenPlaywright:
    def __getattr__(self, name: str):
        raise AssertionError(f"raw mode must not touch Playwright: {name}")


class FakeRawTab:
    def __init__(self) -> None:
        self.disconnect_calls = 0
        self.fill_calls = 0
        self.click_calls = 0
        self.navigation_calls = 0
        self.badge_calls = 0
        self._badge_label = None

    def eval(self, expression: str):
        if "document.readyState" in expression:
            return "interactive"
        if "location.href" in expression:
            return "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
        if ".length" in expression and "querySelectorAll" in expression:
            return 1
        if "getAttribute" in expression:
            return "https://www.saramin.co.kr/zf_user/member/resume-view?idx=42"
        if "innerText" in expression:
            return "ROS2 robotics engineer"
        if "e.value=" in expression:
            self.fill_calls += 1
        if ".click()" in expression:
            self.click_calls += 1
        return None

    def navigate(self, _url: str, wait_ms: int = 0) -> dict[str, str]:
        self.navigation_calls += 1
        if wait_ms == 45000:
            raise AssertionError("Playwright timeout was misused as a fixed raw sleep")
        return {"loaderId": "fake-loader"}

    def wait_for_lifecycle(self, loader_id: str, event: str, _timeout: float) -> None:
        if (loader_id, event) != ("fake-loader", "DOMContentLoaded"):
            raise AssertionError("navigation must wait for the exact new loader")

    def on(self, _event: str, _handler: object) -> None:
        return None

    def mark_busy(self, label: str, *, expected_url: str | None = None) -> bool:
        if expected_url is not None:
            current = self.eval("location.href")
            if current != expected_url:
                return False
        self._badge_label = label
        self.badge_calls += 1
        return True

    def disconnect(self) -> None:
        self.disconnect_calls += 1

    def __getattr__(self, name: str):
        if name == "close":
            return self.disconnect
        raise AttributeError(name)


class RawPortalWorkerWiringTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _idle_snapshots():
        idle = 200.0

        def snapshot():
            nonlocal idle
            idle += 1.0
            return SimpleNamespace(
                owner_activity_detected=False,
                idle_seconds=idle,
                detection_status="ok",
            )

        return snapshot

    async def test_raw_workers_share_one_channel_lock_regardless_of_worker_id(self) -> None:
        with TemporaryDirectory(prefix="raw-lock-a-") as root_a, TemporaryDirectory(
            prefix="raw-lock-b-"
        ) as root_b:
            first = PortalWorkerConfig(
                channel="saramin",
                worker_id="worker-a",
                profile_root=Path(root_a),
                connection_mode="raw_single_tab",
            )
            second = PortalWorkerConfig(
                channel="saramin",
                worker_id="worker-b",
                profile_root=Path(root_b),
                connection_mode="raw_single_tab",
            )
        self.assertEqual(first.lock_path, second.lock_path)

    async def test_raw_mode_attaches_exact_existing_target_without_playwright(self) -> None:
        fake_target = {
            "id": "fake",
            "type": "page",
            "url": "https://notsaramin.co.kr/zf_user/memcom",
            "webSocketDebuggerUrl": "ws://fake",
        }
        exact_target = {
            "id": "exact",
            "type": "page",
            "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "webSocketDebuggerUrl": "ws://exact",
        }
        tab = FakeRawTab()
        attached: list[dict] = []
        listed_endpoints: list[str] = []

        def attach(target: dict, badge: bool = True):
            self.assertFalse(badge)
            attached.append(target)
            return tab

        def list_pages(endpoint: str):
            listed_endpoints.append(endpoint)
            return [fake_target, exact_target]

        with TemporaryDirectory(prefix="raw-worker-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.list_pages",
            side_effect=list_pages,
        ), patch("tools.multi_position_sourcing.raw_cdp.attach", side_effect=attach):
            with patch(
                "tools.multi_position_sourcing.portal_worker.resolve_managed_channel_cdp_endpoint",
                return_value="http://127.0.0.1:9338",
            ):
                worker = PortalWorker(
                    PortalWorkerConfig(
                        channel="saramin",
                        profile_root=Path(root),
                        chrome_cdp_endpoint="http://127.0.0.1:9223",
                        connection_mode="raw_single_tab",
                    ),
                    playwright=ForbiddenPlaywright(),
                    owner_snapshot=self._idle_snapshots(),
                    mutation_sleep=lambda _seconds: None,
                )
                await worker.start()
                result = await worker.run_one_search(
                    "robotics",
                    ready_check=lambda _page: _async_true(),
                )
                page = worker._raw_page
                await worker.stop()

        self.assertIs(page._tab, tab)
        self.assertEqual(attached, [exact_target])
        self.assertEqual(listed_endpoints, ["http://127.0.0.1:9338"])
        self.assertEqual(result.status, "searched")
        self.assertEqual(len(result.candidate_cards), 1)
        self.assertIn("idx=42", result.candidate_cards[0].profile_url)
        self.assertEqual(tab.fill_calls, 1)
        self.assertEqual(tab.click_calls, 1)
        self.assertGreaterEqual(tab.badge_calls, 2)
        self.assertEqual(tab.disconnect_calls, 1)
        self.assertIsNone(worker.browser)

    async def test_login_marker_is_proved_before_any_navigation(self) -> None:
        with TemporaryDirectory(prefix="raw-precheck-") as root:
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root),
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=self._idle_snapshots(),
                mutation_sleep=lambda _seconds: None,
            )
            tab = FakeRawTab()
            worker._raw_page = RawPage(
                tab,
                initial_url="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            )
            result = await worker._run_one_search_body(
                "robotics",
                ready_check=lambda _page: _async_false(),
            )
        self.assertEqual(result.status, "not_ready")
        self.assertEqual(tab.navigation_calls, 0)

    async def test_raw_mode_without_login_proof_never_navigates(self) -> None:
        with TemporaryDirectory(prefix="raw-precheck-") as root:
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root),
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=self._idle_snapshots(),
                mutation_sleep=lambda _seconds: None,
            )
            tab = FakeRawTab()
            worker._raw_page = RawPage(
                tab,
                initial_url="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            )
            result = await worker._run_one_search_body("robotics")

        self.assertEqual(result.status, "not_ready")
        self.assertEqual(result.reauth_cause, "login_proof_required")
        self.assertEqual(tab.navigation_calls, 0)

    async def test_raw_start_fails_when_visible_marker_cannot_be_applied(self) -> None:
        target = {
            "id": "exact",
            "type": "page",
            "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "webSocketDebuggerUrl": "ws://exact",
        }

        class MarkerFailTab(FakeRawTab):
            def mark_busy(self, _label: str, *, expected_url: str | None = None) -> bool:
                return False

        tab = MarkerFailTab()
        with TemporaryDirectory(prefix="raw-badge-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ), patch(
            "tools.multi_position_sourcing.portal_worker.resolve_managed_channel_cdp_endpoint",
            return_value="http://127.0.0.1:9223",
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.list_pages",
            return_value=[target],
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.attach",
            return_value=tab,
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root),
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=self._idle_snapshots(),
                mutation_sleep=lambda _seconds: None,
            )
            try:
                with self.assertRaises(RuntimeError):
                    await worker.start()
            finally:
                await worker.stop()
        self.assertEqual(tab.disconnect_calls, 1)

    async def test_owner_activity_barrier_reads_twice_and_dwells_before_mutation(self) -> None:
        snapshots = iter((
            SimpleNamespace(owner_activity_detected=False, idle_seconds=200.0, detection_status="ok"),
            SimpleNamespace(owner_activity_detected=False, idle_seconds=201.0, detection_status="ok"),
        ))
        waits: list[float] = []
        with TemporaryDirectory(prefix="raw-owner-guard-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=lambda: next(snapshots),
                mutation_sleep=waits.append,
            )
            worker._lock.acquire()
            try:
                worker._assert_raw_mutation_allowed()
            finally:
                worker._lock.release()
        self.assertEqual(waits, [1.0])

    async def test_owner_activity_barrier_fails_closed_before_mutation(self) -> None:
        active = SimpleNamespace(
            owner_activity_detected=True,
            idle_seconds=0.0,
            detection_status="ok",
        )
        tab = FakeRawTab()
        with TemporaryDirectory(prefix="raw-owner-active-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=lambda: active,
                mutation_sleep=lambda _seconds: None,
            )
            worker._lock.acquire()
            page = RawPage(tab, mutation_guard=worker._assert_raw_mutation_allowed)
            try:
                with self.assertRaises(ProfileLockError):
                    await page.locator("button").click()
            finally:
                worker._lock.release()
        self.assertEqual(tab.click_calls, 0)

    async def test_owner_active_start_never_attaches_to_the_target(self) -> None:
        active = SimpleNamespace(
            owner_activity_detected=True,
            idle_seconds=0.0,
            detection_status="ok",
        )
        target = {
            "id": "exact",
            "type": "page",
            "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "webSocketDebuggerUrl": "ws://exact",
        }
        attached: list[dict] = []
        with TemporaryDirectory(prefix="raw-owner-attach-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ), patch(
            "tools.multi_position_sourcing.portal_worker.resolve_managed_channel_cdp_endpoint",
            return_value="http://127.0.0.1:9223",
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.list_pages",
            return_value=[target],
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.attach",
            side_effect=lambda selected, **_kwargs: attached.append(selected),
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=lambda: active,
                mutation_sleep=lambda _seconds: None,
            )
            with self.assertRaises(ProfileLockError):
                await worker.start()
            await worker.stop()
        self.assertEqual(attached, [])

    async def test_lost_lease_handoff_disconnects_without_erasing_badge(self) -> None:
        class HandoffTab(FakeRawTab):
            def __init__(self) -> None:
                super().__init__()
                self.close_calls = 0

            def close(self) -> None:
                self.close_calls += 1

        tab = HandoffTab()
        with TemporaryDirectory(prefix="raw-handoff-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                )
            )
            worker._lock.acquire()
            worker._raw_tab = tab
            owner_path = worker.config.lock_path / "owner.json"
            owner_path.write_text('{"token":"replacement","pid":999999}\n', encoding="utf-8")
            await worker.stop()
        self.assertEqual(tab.close_calls, 0)
        self.assertEqual(tab.disconnect_calls, 1)

    async def test_owner_active_handoff_disconnects_without_erasing_badge(self) -> None:
        class HandoffTab(FakeRawTab):
            def __init__(self) -> None:
                super().__init__()
                self.close_calls = 0

            def close(self) -> None:
                self.close_calls += 1

        snapshots = iter((
            SimpleNamespace(owner_activity_detected=True, idle_seconds=0.0, detection_status="ok"),
            SimpleNamespace(owner_activity_detected=False, idle_seconds=200.0, detection_status="ok"),
            SimpleNamespace(owner_activity_detected=False, idle_seconds=201.0, detection_status="ok"),
        ))
        handoff_waits: list[float] = []

        async def handoff_sleep(seconds: float) -> None:
            handoff_waits.append(seconds)
        tab = HandoffTab()
        with TemporaryDirectory(prefix="raw-handoff-active-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=lambda: next(snapshots),
                mutation_sleep=lambda _seconds: None,
                handoff_sleep=handoff_sleep,
            )
            worker._lock.acquire()
            worker._raw_tab = tab
            worker._raw_badge_applied = True
            await worker.stop()
        self.assertEqual(handoff_waits, [5.0])
        self.assertEqual(tab.close_calls, 1)
        self.assertEqual(tab.disconnect_calls, 0)

    async def test_failed_badge_clear_preserves_socket_and_lease_for_retry(self) -> None:
        class ClearFailTab(FakeRawTab):
            def __init__(self) -> None:
                super().__init__()
                self.close_calls = 0

            def close(self) -> bool:
                self.close_calls += 1
                return False

        tab = ClearFailTab()
        with TemporaryDirectory(prefix="raw-handoff-clear-fail-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=self._idle_snapshots(),
                mutation_sleep=lambda _seconds: None,
            )
            worker._lock.acquire()
            lease_path = worker.config.lock_path
            worker._raw_tab = tab
            worker._raw_badge_applied = True
            try:
                with self.assertRaises(RuntimeError):
                    await worker.stop()
                self.assertTrue(lease_path.exists())
                self.assertIs(worker._raw_tab, tab)
                self.assertEqual(tab.disconnect_calls, 0)
            finally:
                worker._lock.release()

        self.assertEqual(tab.close_calls, 1)

    async def test_attach_target_is_revalidated_before_badge_mutation(self) -> None:
        target = {
            "id": "exact",
            "type": "page",
            "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "webSocketDebuggerUrl": "ws://exact",
        }

        class RacedTab(FakeRawTab):
            def eval(self, expression: str):
                if "location.href" in expression:
                    return "https://evil.example/phish"
                return super().eval(expression)

        tab = RacedTab()
        with TemporaryDirectory(prefix="raw-target-race-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ), patch(
            "tools.multi_position_sourcing.portal_worker.resolve_managed_channel_cdp_endpoint",
            return_value="http://127.0.0.1:9223",
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.list_pages",
            return_value=[target],
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.attach",
            return_value=tab,
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=self._idle_snapshots(),
                mutation_sleep=lambda _seconds: None,
            )
            with self.assertRaises(RuntimeError):
                await worker.start()
        self.assertEqual(tab.badge_calls, 0)
        self.assertEqual(tab.disconnect_calls, 1)

    async def test_attach_target_is_revalidated_after_final_owner_dwell(self) -> None:
        target = {
            "id": "exact",
            "type": "page",
            "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "webSocketDebuggerUrl": "ws://exact",
        }

        class MovingTab(FakeRawTab):
            def __init__(self) -> None:
                super().__init__()
                self.live_url = target["url"]

            def eval(self, expression: str):
                if "location.href" in expression:
                    return self.live_url
                return super().eval(expression)

        tab = MovingTab()
        dwell_calls = 0

        def move_during_final_dwell(_seconds: float) -> None:
            nonlocal dwell_calls
            dwell_calls += 1
            if dwell_calls == 2:
                tab.live_url = "https://evil.example/phish"

        with TemporaryDirectory(prefix="raw-final-target-race-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ), patch(
            "tools.multi_position_sourcing.portal_worker.resolve_managed_channel_cdp_endpoint",
            return_value="http://127.0.0.1:9223",
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.list_pages",
            return_value=[target],
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.attach",
            return_value=tab,
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=self._idle_snapshots(),
                mutation_sleep=move_during_final_dwell,
            )
            lease_path = worker.config.lock_path
            with self.assertRaises(RuntimeError):
                await worker.start()

        self.assertEqual(dwell_calls, 2)
        self.assertEqual(tab.badge_calls, 0)
        self.assertEqual(tab.disconnect_calls, 1)
        self.assertFalse(lease_path.exists())

    async def test_badge_injection_is_atomically_bound_to_the_final_url(self) -> None:
        target = {
            "id": "exact",
            "type": "page",
            "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "webSocketDebuggerUrl": "ws://exact",
        }

        class LastMomentMoveTab(FakeRawTab):
            def __init__(self) -> None:
                super().__init__()
                self.live_url = target["url"]
                self.url_reads = 0
                self.expected_urls: list[str | None] = []

            def eval(self, expression: str):
                if "location.href" in expression:
                    self.url_reads += 1
                    result = self.live_url
                    if self.url_reads == 2:
                        self.live_url = "https://evil.example/phish"
                    return result
                return super().eval(expression)

            def mark_busy(self, label: str, expected_url: str | None = None) -> bool:
                self.expected_urls.append(expected_url)
                if expected_url != self.live_url:
                    return False
                return super().mark_busy(label)

        tab = LastMomentMoveTab()
        with TemporaryDirectory(prefix="raw-atomic-badge-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ), patch(
            "tools.multi_position_sourcing.portal_worker.resolve_managed_channel_cdp_endpoint",
            return_value="http://127.0.0.1:9223",
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.list_pages",
            return_value=[target],
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.attach",
            return_value=tab,
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=self._idle_snapshots(),
                mutation_sleep=lambda _seconds: None,
            )
            with self.assertRaises(RuntimeError):
                await worker.start()

        self.assertEqual(tab.url_reads, 2)
        self.assertEqual(tab.expected_urls, [target["url"]])
        self.assertEqual(tab.badge_calls, 0)
        self.assertEqual(tab.disconnect_calls, 1)

    async def test_cancelled_start_releases_lease_before_attach(self) -> None:
        target = {
            "id": "exact",
            "type": "page",
            "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "webSocketDebuggerUrl": "ws://exact",
        }
        entered = threading.Event()
        release = threading.Event()

        def blocking_dwell(_seconds: float) -> None:
            entered.set()
            release.wait(timeout=5)

        with TemporaryDirectory(prefix="raw-cancel-start-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ), patch(
            "tools.multi_position_sourcing.portal_worker.resolve_managed_channel_cdp_endpoint",
            return_value="http://127.0.0.1:9223",
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.list_pages",
            return_value=[target],
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=self._idle_snapshots(),
                mutation_sleep=blocking_dwell,
            )
            task = asyncio.create_task(worker.start())
            await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            try:
                self.assertFalse(worker.config.lock_path.exists())
            finally:
                worker._lock.release()

    async def test_cancelled_start_disconnects_attached_socket_before_releasing_lease(self) -> None:
        target = {
            "id": "exact",
            "type": "page",
            "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "webSocketDebuggerUrl": "ws://exact",
        }
        entered = threading.Event()
        release = threading.Event()
        dwell_calls = 0

        def second_blocking_dwell(_seconds: float) -> None:
            nonlocal dwell_calls
            dwell_calls += 1
            if dwell_calls == 2:
                entered.set()
                release.wait(timeout=5)

        tab = FakeRawTab()
        with TemporaryDirectory(prefix="raw-cancel-attached-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ), patch(
            "tools.multi_position_sourcing.portal_worker.resolve_managed_channel_cdp_endpoint",
            return_value="http://127.0.0.1:9223",
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.list_pages",
            return_value=[target],
        ), patch(
            "tools.multi_position_sourcing.raw_cdp.attach",
            return_value=tab,
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=self._idle_snapshots(),
                mutation_sleep=second_blocking_dwell,
            )
            task = asyncio.create_task(worker.start())
            await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            try:
                self.assertEqual(tab.badge_calls, 0)
                self.assertEqual(tab.disconnect_calls, 1)
                self.assertFalse(worker.config.lock_path.exists())
            finally:
                worker._lock.release()

    async def test_cancelled_stop_finishes_badge_and_socket_handoff_before_unlock(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def blocking_dwell(_seconds: float) -> None:
            entered.set()
            release.wait(timeout=5)

        class HandoffTab(FakeRawTab):
            def __init__(self) -> None:
                super().__init__()
                self.close_calls = 0

            def close(self) -> None:
                self.close_calls += 1

        tab = HandoffTab()
        with TemporaryDirectory(prefix="raw-cancel-stop-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ):
            worker = PortalWorker(
                PortalWorkerConfig(
                    channel="saramin",
                    profile_root=Path(root) / "profile",
                    connection_mode="raw_single_tab",
                ),
                owner_snapshot=self._idle_snapshots(),
                mutation_sleep=blocking_dwell,
            )
            worker._lock.acquire()
            worker._raw_tab = tab
            worker._raw_badge_applied = True
            task = asyncio.create_task(worker.stop())
            await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(tab.close_calls, 1)
            self.assertFalse(worker.config.lock_path.exists())

    async def test_raw_mode_uses_shared_atomic_login_lease(self) -> None:
        with TemporaryDirectory(prefix="raw-shared-lease-") as root, patch(
            "tools.multi_position_sourcing.portal_worker.RAW_SINGLE_TARGET_LOCK_ROOT",
            Path(root) / "browser-locks",
        ):
            config = PortalWorkerConfig(
                channel="saramin",
                profile_root=Path(root) / "profile",
                connection_mode="raw_single_tab",
            )
            self.assertEqual(
                config.lock_path,
                Path(root) / "browser-locks" / "login-saramin.lock",
            )
            first = ProfileLock(config)
            second = ProfileLock(config)
            first.acquire()
            try:
                self.assertTrue(config.lock_path.is_dir())
                first.assert_owned()
                with self.assertRaises(ProfileLockError):
                    second.acquire()
            finally:
                first.release()
            self.assertFalse(config.lock_path.exists())

    async def test_login_proof_requires_account_and_all_search_markers(self) -> None:
        class Locator:
            def __init__(self, page, selector: str) -> None:
                self.page = page
                self.selector = selector

            async def count(self) -> int:
                selectors = {part.strip() for part in self.selector.split(",")}
                return int(bool(selectors & self.page.present))

            async def inner_text(self, **_kwargs) -> str:
                if self.page.body_raises:
                    raise RuntimeError("DOM read failed")
                return self.page.text

            @property
            def first(self):
                return self

            def nth(self, _index: int):
                return self

            async def is_visible(self) -> bool:
                selectors = {part.strip() for part in self.selector.split(",")}
                return bool(selectors & self.page.visible)

        class ProofPage:
            def __init__(
                self,
                url: str,
                text: str,
                present: set[str],
                visible: set[str] | None = None,
                body_raises: bool = False,
            ) -> None:
                self.url = url
                self.text = text
                self.present = present
                self.visible = present if visible is None else visible
                self.body_raises = body_raises

            def locator(self, selector: str):
                return Locator(self, selector)

        saramin = ready_check_for_channel("saramin")
        saramin_fields = {"input.search_input", "#career_min", "#career_max"}
        self.assertFalse(await saramin(ProofPage(
            "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "로그인 | 회원가입",
            saramin_fields,
        )))
        self.assertFalse(await saramin(ProofPage(
            "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "밸류커넥트 | 로그아웃",
            {"input.search_input", "#career_min"},
        )))
        self.assertTrue(await saramin(ProofPage(
            "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "밸류커넥트 | 로그아웃",
            saramin_fields,
        )))
        self.assertFalse(await saramin(ProofPage(
            "https://notsaramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "밸류커넥트 | 로그아웃",
            saramin_fields,
        )))
        self.assertFalse(await saramin(ProofPage(
            "http://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "밸류커넥트 | 로그아웃",
            saramin_fields,
        )))

        jobkorea = ready_check_for_channel("jobkorea")
        keyword = {"#txtKeyword"}
        self.assertFalse(await jobkorea(ProofPage(
            "https://www.jobkorea.co.kr/Corp/Person/Find",
            "밸류커넥트 | 로그인 | 회원가입",
            keyword,
        )))
        self.assertTrue(await jobkorea(ProofPage(
            "https://www.jobkorea.co.kr/Corp/Person/Find",
            "밸류커넥트 | 로그아웃",
            keyword,
        )))
        self.assertFalse(await jobkorea(ProofPage(
            "https://jobkorea.evil.example/Corp/Person/Find",
            "밸류커넥트 | 로그아웃",
            keyword,
        )))

        linkedin = ready_check_for_channel("linkedin_rps")
        recruiter_search = {'a[href*="/talent/search"]'}
        self.assertFalse(await linkedin(ProofPage(
            "https://www.linkedin.com/talent/home",
            "Sign in to LinkedIn Talent Solutions | 로그인",
            recruiter_search,
        )))
        residual = recruiter_search | {'[data-test-recruiter-account-menu]'}
        for login_wall in (
            "Sign in | Email or phone | Password",
            "Log in | Email or phone | Password",
            "",
        ):
            self.assertFalse(await linkedin(ProofPage(
                "https://www.linkedin.com/talent/home",
                login_wall,
                residual,
                visible=set(),
            )))
        self.assertFalse(await linkedin(ProofPage(
            "https://www.linkedin.com/talent/home",
            "",
            residual,
        )))
        self.assertFalse(await linkedin(ProofPage(
            "https://www.linkedin.com/talent/home",
            "unused",
            residual,
            body_raises=True,
        )))
        generic_linkedin = {
            'input[role="combobox"]',
            '[data-test-global-nav-profile]',
        }
        self.assertFalse(await linkedin(ProofPage(
            "https://www.linkedin.com/talent/home",
            "Welcome to LinkedIn. Upgrade to Recruiter to continue.",
            generic_linkedin,
        )))
        self.assertFalse(await linkedin(ProofPage(
            "https://linkedin.evil.example/talent/home",
            "Good evening, Sangmo | Recruiter",
            residual,
        )))
        self.assertFalse(await linkedin(ProofPage(
            "https://notlinkedin.com/talent/home",
            "Good evening, Sangmo | Recruiter",
            residual,
        )))
        self.assertFalse(await linkedin(ProofPage(
            "https://user:pass@www.linkedin.com/talent/home",
            "Good evening, Sangmo | Recruiter",
            residual,
        )))
        self.assertTrue(await linkedin(ProofPage(
            "https://www.linkedin.com/talent/home",
            "Good evening, Sangmo | Recruiter",
            residual,
        )))

    async def test_raw_monitor_reads_fresh_login_redirect_url(self) -> None:
        class RedirectTab(FakeRawTab):
            def eval(self, expression: str):
                if "location.href" in expression:
                    return "https://www.saramin.co.kr/zf_user/auth?ut=c"
                return super().eval(expression)

        cause = await SearchLivenessMonitor("saramin").check_page(
            RawPage(RedirectTab(), initial_url="https://www.saramin.co.kr/")
        )
        self.assertEqual(cause, "login_redirect")


async def _async_true() -> bool:
    return True


async def _async_false() -> bool:
    return False


if __name__ == "__main__":
    unittest.main()
