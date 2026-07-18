"""Coverage for the protected-portal preflight auto-login path.

These tests assert the new behavior:
- the session preflight submits macOS Keychain credentials automatically (no human
  password entry) for saramin / jobkorea / LinkedIn RPS,
- a captcha / 2FA / checkpoint is never bypassed (auto-login stops and hands off to a human),
- credential resolution never leaks secret values into the result payload.

Kept in a separate module from tests/test_multi_position_sourcing.py to avoid churn on that
large, actively-edited file.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from tools.multi_position_sourcing.access import resolve_portal_credentials
from tools.multi_position_sourcing import portal_login
from tools.multi_position_sourcing.portal_recovery import PortalCredentialError, PortalCredentials


class ResolvePortalCredentialsTests(unittest.TestCase):
    def test_reads_per_portal_and_shared_env_excluding_linkedin(self) -> None:
        env = {
            "SARAMIN_USERNAME": "valueconnect",
            "SARAMIN_PASSWORD": "s-secret",
            "JOB_PORTAL_USERNAME": "valueconnect",
            "JOB_PORTAL_PASSWORD": "shared-secret",
            "LINKEDIN_USERNAME": "x",
            "LINKEDIN_PASSWORD": "y",
        }
        self.assertEqual(resolve_portal_credentials("saramin", env), ("valueconnect", "s-secret"))
        # jobkorea has no per-portal key here -> falls back to the shared JOB_PORTAL_* pair
        self.assertEqual(resolve_portal_credentials("jobkorea", env), ("valueconnect", "shared-secret"))
        # LinkedIn RPS env keys are resolved for credential import/preflight.
        self.assertEqual(resolve_portal_credentials("linkedin_rps", env), ("x", "y"))
        # public_web has no credential keys at all
        self.assertIsNone(resolve_portal_credentials("public_web", env))

    def test_linkedin_rps_specific_env_keys_are_resolved(self) -> None:
        env = {"LINKEDIN_RPS_USERNAME": "rps-user", "LINKEDIN_RPS_PASSWORD": "rps-secret"}
        self.assertEqual(resolve_portal_credentials("linkedin_rps", env), ("rps-user", "rps-secret"))

    def test_missing_password_yields_none(self) -> None:
        self.assertIsNone(resolve_portal_credentials("saramin", {"SARAMIN_USERNAME": "valueconnect"}))
        self.assertIsNone(resolve_portal_credentials("saramin", {"SARAMIN_PASSWORD": "only-pw"}))
        self.assertIsNone(resolve_portal_credentials("saramin", {}))


class PortalSessionPreflightPayloadTests(unittest.TestCase):
    def test_payload_includes_generation_timestamp_for_dod_freshness(self) -> None:
        results = [
            {
                "channel": "saramin",
                "ready": True,
                "login": "existing_session_ok",
                "snapshot_capture_required": True,
                "snapshot_captured": True,
            }
        ]

        payload = portal_login.build_portal_session_preflight_payload(results)

        self.assertEqual(payload["kind"], "portal_session_preflight")
        self.assertTrue(payload["ready"])
        self.assertIsInstance(payload["generated_at"], str)
        self.assertEqual(payload["portal_sessions"], results)


class PreflightAutoLoginSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_ready_preflight_session_pages_are_closed(self) -> None:
        ready_selectors = {
            "saramin": {"input.search_input", "#career_min", "#career_max"},
            "jobkorea": {"#txtKeyword, input[placeholder*='키워드'], input[placeholder*='검색']"},
            "linkedin_rps": {'a[href*="/talent/search"], input[role="combobox"]'},
        }
        ready_selectors["linkedin_rps"].add(portal_login.LINKEDIN_RECRUITER_ACCOUNT_SELECTOR)

        class FakeLocator:
            def __init__(self, page: "FakePage", selector: str) -> None:
                self.page = page
                self.selector = selector
                self.first = self

            async def count(self) -> int:
                if self.selector == "body":
                    return 1
                return 1 if self.selector in ready_selectors[self.page.channel] else 0

            async def inner_text(self, timeout: int = 0) -> str:
                if self.page.channel in {"saramin", "jobkorea"}:
                    return "밸류커넥트 로그아웃"
                return ""

            def nth(self, _index: int) -> "FakeLocator":
                return self

            async def is_visible(self) -> bool:
                return bool(await self.count())

            async def click(self, timeout: int = 0) -> None:
                return None

        class FakePage:
            def __init__(self, channel: str) -> None:
                self.channel = channel
                self.url = ""
                self.closed = False
                self.goto_calls: list[str] = []

            async def goto(self, url: str, **_kwargs: object) -> None:
                self.url = url
                self.goto_calls.append(url)

            async def wait_for_timeout(self, _ms: int) -> None:
                return None

            def locator(self, selector: str) -> FakeLocator:
                return FakeLocator(self, selector)

            def get_by_text(self, _text: str, exact: bool = False) -> FakeLocator:
                return FakeLocator(self, "__popup__")

            async def close(self) -> None:
                self.closed = True

        class FakeContext:
            def __init__(self, page: FakePage) -> None:
                self.page = page

            async def new_page(self) -> FakePage:
                return self.page

        cases = {
            "saramin": portal_login._saramin_session,
            "jobkorea": portal_login._jobkorea_session,
            "linkedin_rps": portal_login._linkedin_rps_session,
        }
        for channel, action in cases.items():
            with self.subTest(channel=channel):
                page = FakePage(channel)

                result = await action(FakeContext(page), portal_login.HumanInterventionOptions(enabled=False))

                self.assertTrue(result["ready"])
                self.assertEqual(result["login"], "existing_session_ok")
                self.assertTrue(page.closed)

    async def test_channel_timeout_returns_safe_not_ready_result(self) -> None:
        async def slow_preflight() -> dict[str, object]:
            await asyncio.sleep(1)
            return {"channel": "saramin", "ready": True, "login": "existing_session_ok"}

        result = await portal_login._run_preflight_channel_with_timeout(
            channel="saramin",
            timeout_seconds=0.01,
            action=slow_preflight,
        )
        encoded = str(result)

        self.assertFalse(result["ready"])
        self.assertEqual(result["login"], "timeout")
        self.assertTrue(result["snapshot_capture_required"])
        self.assertFalse(result["snapshot_captured"])
        self.assertEqual(result["snapshot_capture_status"], "skipped_timeout")
        self.assertNotIn("cookie-secret", encoded)
        self.assertNotIn("storage_state", encoded)

    async def test_preflight_result_url_strips_auth_query_and_fragment(self) -> None:
        result = portal_login._result(
            "linkedin_rps",
            ready=False,
            login="human_intervention_disabled",
            url="https://user:pass@www.linkedin.com/talent/home?cookie=session-secret#token-secret",
        )
        encoded = str(result)

        self.assertEqual(result["url"], "https://www.linkedin.com/talent/home")
        self.assertNotIn("session-secret", encoded)
        self.assertNotIn("token-secret", encoded)
        self.assertNotIn("user:pass", encoded)
        self.assertNotIn("cookie=", encoded.lower())

    async def test_preflight_error_note_does_not_echo_exception_secret_url(self) -> None:
        class FakePage:
            url = "https://user:pass@www.saramin.co.kr/search?cookie=session-secret#token-secret"

            async def goto(self, _url: str, **_kwargs: object) -> None:
                raise RuntimeError(
                    "browser failed at https://user:pass@www.saramin.co.kr/search?cookie=session-secret#token-secret"
                )

        class FakeContext:
            async def new_page(self) -> FakePage:
                return FakePage()

        result = await portal_login._saramin_session(
            FakeContext(),
            portal_login.HumanInterventionOptions(enabled=False),
        )
        encoded = str(result)

        self.assertFalse(result["ready"])
        self.assertEqual(result["login"], "error")
        self.assertEqual(result["note"], "RuntimeError: portal session check failed without exposing details")
        self.assertEqual(result["url"], "https://www.saramin.co.kr/search")
        self.assertNotIn("session-secret", encoded)
        self.assertNotIn("token-secret", encoded)
        self.assertNotIn("user:pass", encoded)
        self.assertNotIn("cookie=", encoded.lower())

    async def test_saramin_rechecks_search_surface_after_auto_login_failure(self) -> None:
        class FakeLocator:
            def __init__(self, page: object, selector: str) -> None:
                self.page = page
                self.selector = selector
                self.first = self

            async def count(self) -> int:
                if self.selector in {"input.search_input", "#career_min", "#career_max"}:
                    return 1 if len(self.page.goto_calls) >= 2 else 0  # type: ignore[attr-defined]
                return 0

            async def inner_text(self, timeout: int = 0) -> str:
                if len(self.page.goto_calls) >= 2:  # type: ignore[attr-defined]
                    return "밸류커넥트 로그아웃"
                return "로그인"

            async def click(self, timeout: int = 0) -> None:
                return None

        class FakePage:
            url = ""

            def __init__(self) -> None:
                self.goto_calls: list[str] = []

            async def goto(self, url: str, **_kwargs: object) -> None:
                self.url = url
                self.goto_calls.append(url)

            async def wait_for_timeout(self, _ms: int) -> None:
                return None

            def locator(self, selector: str) -> FakeLocator:
                return FakeLocator(self, selector)

            def get_by_text(self, _text: str, exact: bool = False) -> FakeLocator:
                return FakeLocator(self, "popup")

        class FakeContext:
            def __init__(self, page: FakePage) -> None:
                self.page = page

            async def new_page(self) -> FakePage:
                return self.page

        page = FakePage()

        async def fake_auto_login(_context: object, _channel: str) -> dict[str, object]:
            return {"channel": "saramin", "ready": False, "login": "auto_login_failed", "note": "", "url": ""}

        with patch("tools.multi_position_sourcing.portal_login._auto_login_session", fake_auto_login):
            result = await portal_login._saramin_session(FakeContext(page), portal_login.HumanInterventionOptions(enabled=False))

        self.assertTrue(result["ready"])
        self.assertEqual(result["login"], "auto_login_ok")
        self.assertGreaterEqual(len(page.goto_calls), 2)

    async def test_reports_missing_credentials_instead_of_waiting_for_human(self) -> None:
        class MissingKeychainProvider:
            def load(self, _channel: str) -> PortalCredentials:
                raise PortalCredentialError("missing password-secret")

        with patch(
            "tools.multi_position_sourcing.portal_recovery.MacKeychainPortalCredentialProvider",
            return_value=MissingKeychainProvider(),
        ):
            result = await portal_login._auto_login_session(object(), "saramin")
        self.assertFalse(result["ready"])
        self.assertEqual(result["login"], "credentials_not_configured")
        self.assertNotIn("password-secret", str(result))

    async def test_auto_login_ignores_env_credentials_without_keychain(self) -> None:
        class MissingKeychainProvider:
            def load(self, _channel: str) -> PortalCredentials:
                raise PortalCredentialError("missing keychain credential")

        with patch(
            "tools.multi_position_sourcing.access.resolve_portal_credentials",
            return_value=("valueconnect", "env-secret"),
        ), patch(
            "tools.multi_position_sourcing.portal_recovery.MacKeychainPortalCredentialProvider",
            return_value=MissingKeychainProvider(),
        ):
            result = await portal_login._auto_login_session(object(), "saramin")

        self.assertFalse(result["ready"])
        self.assertEqual(result["login"], "credentials_not_configured")
        self.assertNotIn("env-secret", str(result))

    async def test_submits_credentials_and_revalidates_without_leaking_secret(self) -> None:
        captured: dict[str, str] = {}

        class KeychainProvider:
            def load(self, channel: str) -> PortalCredentials:
                captured["load_channel"] = channel
                return PortalCredentials(username="valueconnect", password="pw-secret")

        async def fake_auto_relogin(_context: object, channel: str, credentials: object) -> bool:
            captured["channel"] = channel
            captured["password"] = credentials.password  # type: ignore[attr-defined]
            return True

        with patch(
            "tools.multi_position_sourcing.portal_recovery.MacKeychainPortalCredentialProvider",
            return_value=KeychainProvider(),
        ), patch(
            "tools.multi_position_sourcing.portal_autologin.auto_relogin_portal",
            fake_auto_relogin,
        ):
            result = await portal_login._auto_login_session(object(), "saramin")

        self.assertTrue(result["ready"])
        self.assertEqual(result["login"], "auto_login_ok")
        self.assertEqual(captured["load_channel"], "saramin")
        self.assertEqual(captured["channel"], "saramin")
        self.assertEqual(captured["password"], "pw-secret")
        self.assertNotIn("pw-secret", str(result))

    async def test_linkedin_auto_login_attempts_credentials_like_other_portals(self) -> None:
        # SOT invariant: LinkedIn RPS auto-logs in from the secret store, exactly like
        # saramin/jobkorea. The credential value is never leaked into the result payload.
        captured: dict[str, str] = {}

        class KeychainProvider:
            def load(self, channel: str) -> PortalCredentials:
                captured["load_channel"] = channel
                return PortalCredentials(username="linkedin-user", password="linkedin-secret")

        async def fake_auto_relogin(_context: object, channel: str, credentials: object) -> bool:
            captured["channel"] = channel
            captured["password"] = credentials.password  # type: ignore[attr-defined]
            return True

        with patch(
            "tools.multi_position_sourcing.portal_recovery.MacKeychainPortalCredentialProvider",
            return_value=KeychainProvider(),
        ), patch(
            "tools.multi_position_sourcing.portal_autologin.auto_relogin_portal",
            fake_auto_relogin,
        ):
            result = await portal_login._auto_login_session(object(), "linkedin_rps")

        self.assertTrue(result["ready"])
        self.assertEqual(result["login"], "auto_login_ok")
        self.assertEqual(captured["load_channel"], "linkedin_rps")
        self.assertEqual(captured["channel"], "linkedin_rps")
        self.assertEqual(captured["password"], "linkedin-secret")
        self.assertNotIn("linkedin-secret", str(result))

    async def test_auto_login_failure_does_not_bypass_challenge(self) -> None:
        class KeychainProvider:
            def load(self, _channel: str) -> PortalCredentials:
                return PortalCredentials(username="valueconnect", password="pw-secret")

        async def fake_auto_relogin(_context: object, _channel: str, _credentials: object) -> bool:
            return False

        with patch(
            "tools.multi_position_sourcing.portal_recovery.MacKeychainPortalCredentialProvider",
            return_value=KeychainProvider(),
        ), patch(
            "tools.multi_position_sourcing.portal_autologin.auto_relogin_portal",
            fake_auto_relogin,
        ):
            result = await portal_login._auto_login_session(object(), "jobkorea")

        self.assertFalse(result["ready"])
        self.assertEqual(result["login"], "auto_login_failed")

    async def test_ready_preflight_result_captures_validated_snapshot(self) -> None:
        calls: list[dict[str, object]] = []

        async def ready_check(_page: object) -> bool:
            return True

        async def fake_snapshot_capture(**kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return {"snapshot_captured": True, "snapshot_capture_status": "captured"}

        result = await portal_login._with_preflight_snapshot_status(
            {"channel": "saramin", "ready": True, "login": "auto_login_ok"},
            context=object(),
            channel="saramin",
            worker_id="worker-a",
            playwright=object(),
            ready_check=ready_check,
            snapshot_capture=fake_snapshot_capture,
        )

        self.assertTrue(result["snapshot_capture_required"])
        self.assertTrue(result["snapshot_captured"])
        self.assertEqual(result["snapshot_capture_status"], "captured")
        self.assertEqual(calls[0]["channel"], "saramin")
        self.assertEqual(calls[0]["worker_id"], "worker-a")

    async def test_not_ready_preflight_result_skips_snapshot_capture(self) -> None:
        async def ready_check(_page: object) -> bool:
            return True

        async def fake_snapshot_capture(**_kwargs: object) -> dict[str, object]:
            raise AssertionError("snapshot capture should not run unless the session is ready")

        result = await portal_login._with_preflight_snapshot_status(
            {"channel": "jobkorea", "ready": False, "login": "auto_login_failed"},
            context=object(),
            channel="jobkorea",
            worker_id="worker-a",
            playwright=object(),
            ready_check=ready_check,
            snapshot_capture=fake_snapshot_capture,
        )

        self.assertTrue(result["snapshot_capture_required"])
        self.assertFalse(result["snapshot_captured"])
        self.assertEqual(result["snapshot_capture_status"], "skipped_not_ready")

    async def test_preflight_snapshot_capture_failure_does_not_leak_secret(self) -> None:
        async def ready_check(_page: object) -> bool:
            return True

        async def fake_snapshot_capture(**_kwargs: object) -> dict[str, object]:
            raise RuntimeError("failed with service-role-secret and cookie-secret")

        result = await portal_login._with_preflight_snapshot_status(
            {"channel": "saramin", "ready": True, "login": "existing_session_ok"},
            context=object(),
            channel="saramin",
            worker_id="worker-a",
            playwright=object(),
            ready_check=ready_check,
            snapshot_capture=fake_snapshot_capture,
        )
        encoded = str(result)

        self.assertTrue(result["snapshot_capture_required"])
        self.assertFalse(result["snapshot_captured"])
        self.assertEqual(result["snapshot_capture_status"], "unavailable")
        self.assertEqual(
            result["snapshot_capture_note"],
            "RuntimeError: preflight snapshot capture failed without exposing details",
        )
        self.assertNotIn("service-role-secret", encoded)
        self.assertNotIn("cookie-secret", encoded)

    async def test_public_web_preflight_marks_snapshot_not_required(self) -> None:
        result = await portal_login._with_preflight_snapshot_status(
            {"channel": "public_web", "ready": True, "login": "not_required"},
            context=None,
            channel="public_web",
            worker_id="worker-a",
            playwright=object(),
            ready_check=None,
        )

        self.assertFalse(result["snapshot_capture_required"])
        self.assertFalse(result["snapshot_captured"])
        self.assertEqual(result["snapshot_capture_status"], "not_required")


class SaraminSearchUrlContractTests(unittest.TestCase):
    """saramin 검색 진입은 talent-pool 검색 페이지로 직접 이동한다.

    로그인 프로필을 재사용하므로 과거의 auth 래퍼(/zf_user/auth?...url=...)를
    거치지 않는다. 래퍼로 회귀하면 이미 로그인된 세션에서도 불필요한 인증
    리다이렉트를 타게 되므로 이 계약을 잠근다.
    """

    def test_saramin_search_url_is_direct_talent_pool_not_auth_wrapper(self) -> None:
        url = portal_login.SARAMIN_SEARCH_URL
        self.assertEqual(
            url,
            "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
        )
        # 구조 기반 계약: talent-pool 검색 경로로 직접 가고, 쿼리 파라미터(=래퍼)는 없다.
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "www.saramin.co.kr")
        self.assertIn("/memcom/talent-pool/", parsed.path)
        # 쿼리 파라미터 형태의 어떤 auth 래퍼(?...url=...)도 잡는다.
        self.assertEqual(parsed.query, "")
        self.assertNotIn("/zf_user/auth", parsed.path)


if __name__ == "__main__":
    unittest.main()
