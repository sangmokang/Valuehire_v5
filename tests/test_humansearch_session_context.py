from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing import humansearch_cdp_run as runner
from tools.multi_position_sourcing.humansearch_preflight import PreflightError


class _HarvestTab:
    def eval(self, script: str):
        if "const seen" in script:
            if "navigation_url" not in script:
                return [
                    {
                        "url": "https://www.linkedin.com/talent/profile/AAA",
                        "name": "Candidate",
                    }
                ]
            return [
                {
                    "url": "https://www.linkedin.com/talent/profile/AAA",
                    "navigation_url": (
                        "https://www.linkedin.com/talent/profile/AAA"
                        "?project=1752949252&searchHistoryId=21211832492&trk=SEARCH_CONTEXTUAL"
                    ),
                    "name": "Candidate",
                }
            ]
        return None


def test_harvest_keeps_canonical_identity_and_exact_navigation_href(monkeypatch) -> None:
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    cards = runner.extract_cards_from_current_page(_HarvestTab())

    assert cards == [
        {
            "url": "https://www.linkedin.com/talent/profile/AAA",
            "navigation_url": (
                "https://www.linkedin.com/talent/profile/AAA"
                "?project=1752949252&searchHistoryId=21211832492&trk=SEARCH_CONTEXTUAL"
            ),
            "name": "Candidate",
        }
    ]


class _ProfileTab:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.navigated: list[str] = []
        self.extractions = 0
        self.screenshots = 0

    def navigate(self, url: str, wait_ms: int = 0):
        self.navigated.append(url)
        return {"url": url}

    def eval(self, _script: str):
        self.extractions += 1
        return {
            "name": "Candidate",
            "headline": "Robotics Engineer",
            "otw": False,
            "summary": "Robotics control engineer with production experience.",
            "education": "School name Seoul National University 2019",
            "dates": [],
            "full": "Robotics control learning manipulation " * 40,
        }

    def screenshot(self, path: str):
        self.screenshots += 1
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"png")


def _archive_receipt(*_args, **_kwargs):
    return SimpleNamespace(row_id=1)


def test_profile_open_prefers_exact_result_href_over_bare_profile_url(
    monkeypatch, tmp_path: Path
) -> None:
    navigation_url = (
        "https://www.linkedin.com/talent/profile/AAA"
        "?project=1752949252&searchHistoryId=21211832492&trk=SEARCH_CONTEXTUAL"
    )
    tab = _ProfileTab(tmp_path)
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)
    monkeypatch.setattr(
        "tools.multi_position_sourcing.profile_archive_store.ProfileArchiveStore.save",
        _archive_receipt,
    )

    runner.process_profile(
        tab,
        {
            "url": "https://www.linkedin.com/talent/profile/AAA",
            "navigation_url": navigation_url,
            "name": "Candidate",
        },
        1,
    )

    assert tab.navigated == [navigation_url]


def test_session_conflict_stops_before_extract_screenshot_or_archive(
    monkeypatch, tmp_path: Path
) -> None:
    tab = _ProfileTab(tmp_path)
    archive_calls: list[object] = []
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)

    def blocked(_tab):
        raise PreflightError({"reasons": ["multiple sign-ins"]})

    def archive(*args, **kwargs):
        archive_calls.append((args, kwargs))
        return SimpleNamespace(row_id=1)

    monkeypatch.setattr(runner, "assert_not_blocked_or_abort", blocked)
    monkeypatch.setattr(
        "tools.multi_position_sourcing.profile_archive_store.ProfileArchiveStore.save",
        archive,
    )

    with pytest.raises(PreflightError, match="multiple sign-ins"):
        runner.process_profile(
            tab,
            {
                "url": "https://www.linkedin.com/talent/profile/AAA",
                "navigation_url": (
                    "https://www.linkedin.com/talent/profile/AAA"
                    "?project=1752949252&searchHistoryId=21211832492"
                ),
            },
            1,
        )

    assert len(tab.navigated) == 1
    assert tab.extractions == 0
    assert tab.screenshots == 0
    assert archive_calls == []


def test_missing_existing_recruiter_target_never_creates_tab(monkeypatch) -> None:
    monkeypatch.setattr(runner.cdp, "find_page_by_url", lambda _value: None)
    created: list[str] = []

    def forbidden_new_tab(url: str):
        created.append(url)
        raise AssertionError("humansearch must not create a Recruiter tab")

    monkeypatch.setattr(runner.cdp, "new_tab", forbidden_new_tab)

    with pytest.raises(RuntimeError, match="existing.*Recruiter target"):
        runner.main()

    assert created == []
