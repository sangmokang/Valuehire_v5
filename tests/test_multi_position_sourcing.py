from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

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
from tools.multi_position_sourcing.dedup import SeenProfile, canonical_profile_url, seen_within_ttl
from tools.multi_position_sourcing.dry_run import build_dry_run_payload
from tools.multi_position_sourcing.fixtures import SAMPLE_POSITIONS, SAMPLE_PROFILE
from tools.multi_position_sourcing.grouping import group_positions
from tools.multi_position_sourcing.keywords import keyword_plan_for_channel
from tools.multi_position_sourcing.models import QueueItem
from tools.multi_position_sourcing.portal_login import (
    HumanInterventionOptions,
    _has_security_challenge,
    _wait_for_human_intervention,
)
from tools.multi_position_sourcing.portal_session import (
    portal_session_flags,
    portal_session_statuses_from_storage_state,
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


class MultiPositionSourcingTests(unittest.TestCase):
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

    def test_portal_storage_state_builds_session_flags(self) -> None:
        with TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "storage-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "cookies": [
                            {"domain": ".saramin.co.kr"},
                            {"domain": ".linkedin.com"},
                        ],
                        "origins": [
                            {"origin": "https://www.jobkorea.co.kr"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            statuses = portal_session_statuses_from_storage_state(state_path)
            flags = portal_session_flags(statuses)

        self.assertTrue(flags["saramin"])
        self.assertTrue(flags["jobkorea"])
        self.assertTrue(flags["linkedin_rps"])

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


class PortalLoginHumanInterventionTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
