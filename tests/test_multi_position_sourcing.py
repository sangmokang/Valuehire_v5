from __future__ import annotations

import unittest

from tools.multi_position_sourcing.access import (
    authorized_discord_users_from_markdown,
    is_authorized_discord_dm,
    portal_credential_status,
)
from tools.multi_position_sourcing.clickup_activity import format_clickup_activity_comment
from tools.multi_position_sourcing.dedup import SeenProfile, canonical_profile_url, seen_within_ttl
from tools.multi_position_sourcing.dry_run import build_dry_run_payload
from tools.multi_position_sourcing.fixtures import SAMPLE_POSITIONS, SAMPLE_PROFILE
from tools.multi_position_sourcing.grouping import group_positions
from tools.multi_position_sourcing.keywords import keyword_plan_for_channel
from tools.multi_position_sourcing.models import QueueItem
from tools.multi_position_sourcing.queue_runner import run_queue_cycle
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


if __name__ == "__main__":
    unittest.main()
