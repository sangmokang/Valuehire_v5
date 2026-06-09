from __future__ import annotations

import unittest

from tools.multi_position_sourcing.posting_models import (
    DuplicateMatch,
    ExistingPositionTask,
    PostingRecognition,
)
from tools.multi_position_sourcing.position_dedup import (
    canonical_posting_url,
    find_duplicate_position,
    normalize_company,
    normalize_role,
)


def _recognition(
    *,
    source_url: str = "",
    company: str = "",
    role: str = "",
) -> PostingRecognition:
    return PostingRecognition(
        is_job_posting=True,
        source_url=source_url,
        recognition_mode="text",
        company=company,
        role=role,
        confidence=0.9,
    )


class CanonicalPostingUrlTests(unittest.TestCase):
    def test_strips_query_fragment_trailing_slash_and_lowercases_host(self) -> None:
        url = "https://www.Wanted.co.kr/wd/363433?ref=x#a"
        self.assertEqual(
            canonical_posting_url(url),
            "https://www.wanted.co.kr/wd/363433",
        )

    def test_keeps_wanted_wd_id_path(self) -> None:
        url = "https://www.wanted.co.kr/wd/363433/"
        self.assertEqual(
            canonical_posting_url(url),
            "https://www.wanted.co.kr/wd/363433",
        )

    def test_upgrades_scheme_to_https(self) -> None:
        url = "http://example.com/jobs/42/?utm=foo"
        self.assertEqual(
            canonical_posting_url(url),
            "https://example.com/jobs/42",
        )

    def test_collapses_whitespace_and_trailing_slash_only_path(self) -> None:
        url = "  https://Example.COM/  "
        self.assertEqual(
            canonical_posting_url(url),
            "https://example.com",
        )

    def test_two_wanted_urls_with_different_query_canonicalize_equal(self) -> None:
        a = canonical_posting_url("https://www.wanted.co.kr/wd/363433?ref=a")
        b = canonical_posting_url("https://WWW.WANTED.co.kr/wd/363433#section")
        self.assertEqual(a, b)


class NormalizeCompanyTests(unittest.TestCase):
    def test_drops_korean_corp_marker_and_matches_plain(self) -> None:
        self.assertEqual(
            normalize_company("(주)에이콘"),
            normalize_company("에이콘"),
        )

    def test_drops_circled_corp_marker(self) -> None:
        self.assertEqual(
            normalize_company("㈜에이콘"),
            normalize_company("에이콘"),
        )

    def test_drops_english_suffixes_and_lowercases(self) -> None:
        self.assertEqual(
            normalize_company("Acme Inc."),
            normalize_company("acme"),
        )
        self.assertEqual(
            normalize_company("Acme Co., Ltd."),
            normalize_company("ACME"),
        )
        self.assertEqual(
            normalize_company("Acme LLC"),
            normalize_company("acme"),
        )
        self.assertEqual(
            normalize_company("Acme Corp"),
            normalize_company("acme"),
        )

    def test_collapses_internal_whitespace(self) -> None:
        self.assertEqual(
            normalize_company("  Acme   Robotics  "),
            normalize_company("acme robotics"),
        )

    def test_empty_stays_empty(self) -> None:
        self.assertEqual(normalize_company(""), "")
        self.assertEqual(normalize_company("   "), "")


class NormalizeRoleTests(unittest.TestCase):
    def test_lowercases_and_collapses_spaces(self) -> None:
        self.assertEqual(
            normalize_role("Backend  Engineer"),
            normalize_role("backend engineer"),
        )

    def test_collapses_punctuation_and_strips(self) -> None:
        self.assertEqual(
            normalize_role("  Backend / Engineer  "),
            normalize_role("backend engineer"),
        )

    def test_empty_stays_empty(self) -> None:
        self.assertEqual(normalize_role(""), "")


class FindDuplicatePositionTests(unittest.TestCase):
    def test_same_canonical_source_url_matches_on_source_url(self) -> None:
        recognition = _recognition(
            source_url="https://www.wanted.co.kr/wd/363433?ref=x#a",
            company="에이콘",
            role="Backend Engineer",
        )
        existing = [
            ExistingPositionTask(
                task_id="t1",
                task_url="https://app.clickup.com/t/t1",
                company="Totally Different",
                role="Totally Different",
                source_url="https://www.wanted.co.kr/wd/363433/",
            ),
        ]
        match = find_duplicate_position(recognition, existing)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.task_id, "t1")
        self.assertEqual(match.task_url, "https://app.clickup.com/t/t1")
        self.assertEqual(match.match_basis, "source_url")

    def test_same_company_and_role_different_url_matches_on_company_role(self) -> None:
        recognition = _recognition(
            source_url="https://www.wanted.co.kr/wd/999999",
            company="(주)에이콘",
            role="Backend  Engineer",
        )
        existing = [
            ExistingPositionTask(
                task_id="t2",
                task_url="https://app.clickup.com/t/t2",
                company="에이콘",
                role="backend engineer",
                source_url="https://jobkorea.co.kr/something/else",
            ),
        ]
        match = find_duplicate_position(recognition, existing)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.task_id, "t2")
        self.assertEqual(match.match_basis, "company_role")

    def test_no_match_returns_none(self) -> None:
        recognition = _recognition(
            source_url="https://www.wanted.co.kr/wd/111111",
            company="Acme",
            role="Backend Engineer",
        )
        existing = [
            ExistingPositionTask(
                task_id="t3",
                task_url="https://app.clickup.com/t/t3",
                company="Globex",
                role="Frontend Engineer",
                source_url="https://www.wanted.co.kr/wd/222222",
            ),
        ]
        self.assertIsNone(find_duplicate_position(recognition, existing))

    def test_source_url_match_takes_precedence_over_company_role(self) -> None:
        recognition = _recognition(
            source_url="https://www.wanted.co.kr/wd/363433?ref=x",
            company="에이콘",
            role="Backend Engineer",
        )
        existing = [
            ExistingPositionTask(
                task_id="company_role_match",
                task_url="https://app.clickup.com/t/cr",
                company="에이콘",
                role="Backend Engineer",
                source_url="https://www.wanted.co.kr/wd/000000",
            ),
            ExistingPositionTask(
                task_id="source_url_match",
                task_url="https://app.clickup.com/t/su",
                company="Unrelated",
                role="Unrelated",
                source_url="https://www.wanted.co.kr/wd/363433/",
            ),
        ]
        match = find_duplicate_position(recognition, existing)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.task_id, "source_url_match")
        self.assertEqual(match.match_basis, "source_url")

    def test_empty_source_url_does_not_match_empty_existing_source_url(self) -> None:
        recognition = _recognition(source_url="", company="Acme", role="Engineer")
        existing = [
            ExistingPositionTask(
                task_id="t4",
                task_url="https://app.clickup.com/t/t4",
                company="Globex",
                role="Manager",
                source_url="",
            ),
        ]
        self.assertIsNone(find_duplicate_position(recognition, existing))

    def test_empty_company_role_does_not_false_match(self) -> None:
        recognition = _recognition(
            source_url="https://www.wanted.co.kr/wd/333",
            company="",
            role="",
        )
        existing = [
            ExistingPositionTask(
                task_id="t5",
                task_url="https://app.clickup.com/t/t5",
                company="",
                role="",
                source_url="https://www.wanted.co.kr/wd/444",
            ),
        ]
        self.assertIsNone(find_duplicate_position(recognition, existing))


if __name__ == "__main__":
    unittest.main()
