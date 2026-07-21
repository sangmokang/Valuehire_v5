"""Escaped-defect regressions for LinkedIn Recruiter session context (#156).

These tests intentionally describe the safe traversal contract before the
production runner implements it.  A Recruiter result link is a navigation
capability, while the bare profile URL is only the stable storage identity.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from tools.multi_position_sourcing import humansearch_cdp_run as hcr
from tools.multi_position_sourcing.humansearch_preflight import PreflightError


PROFILE_URL = "https://www.linkedin.com/talent/profile/AEMAA-test"
NAVIGATION_URL = (
    PROFILE_URL
    + "?authType=name&authToken=search-scoped-token"
    + "&searchContextId=search-context-156"
)


@dataclass(frozen=True)
class _OwnerIdle:
    owner_activity_detected: bool = False


def _card(*, profile_url: str = PROFILE_URL, navigation_url: str = NAVIGATION_URL) -> dict:
    return {
        "url": profile_url,
        "navigation_url": navigation_url,
        "name": "Candidate One",
        "snippet": "robotics",
    }


def test_card_harvest_preserves_exact_navigation_href_with_query(monkeypatch) -> None:
    """The DOM href query must survive harvest instead of being split away."""

    class HarvestTab:
        def eval(self, script: str):
            if "querySelectorAll" not in script:
                return None
            # Emulate the browser result of the emitted extraction script.  The
            # current script has no navigation_url field, so this stays absent.
            row = {
                "url": PROFILE_URL,
                "name": "Candidate One",
                "snippet": "robotics",
            }
            if "navigation_url" in script:
                row["navigation_url"] = NAVIGATION_URL
            return [row]

    monkeypatch.setattr(hcr.time, "sleep", lambda _seconds: None)

    rows = hcr.extract_cards_from_current_page(HarvestTab())

    assert rows[0]["url"] == PROFILE_URL
    assert rows[0]["navigation_url"] == NAVIGATION_URL


def test_profile_open_prefers_navigation_url_over_bare_profile_url() -> None:
    """A canonical bare URL must never replace the result link for navigation."""

    class StopAfterNavigate(RuntimeError):
        pass

    opened: list[str] = []

    class Tab:
        def navigate(self, url: str, *, wait_ms: int) -> None:
            opened.append(url)
            raise StopAfterNavigate

    with pytest.raises(StopAfterNavigate):
        hcr.process_profile(Tab(), _card(), 1)

    assert opened == [NAVIGATION_URL]


def test_missing_existing_recruiter_target_never_creates_new_tab(monkeypatch, tmp_path) -> None:
    """Missing target is a terminal preflight failure, not permission to create one."""

    created: list[str] = []
    monkeypatch.setattr(hcr, "OUT_DIR", tmp_path)
    monkeypatch.setattr(hcr, "LOG", tmp_path / "run.log")
    monkeypatch.setattr(hcr.cdp, "find_page_by_url", lambda _needle: None)

    def forbidden_new_tab(url: str):
        created.append(url)
        raise RuntimeError("new tab forbidden")

    monkeypatch.setattr(hcr.cdp, "new_tab", forbidden_new_tab)

    with pytest.raises(RuntimeError):
        hcr.main(owner_snapshot=lambda: _OwnerIdle())

    assert created == []


def test_enterprise_auth_stops_before_extract_screenshot_or_archive(
    monkeypatch, tmp_path
) -> None:
    """A conflict page must be detected immediately and never saved as a candidate."""

    trace: list[str] = []

    class Tab:
        def navigate(self, url: str, *, wait_ms: int) -> None:
            trace.append(f"navigate:{url}")

        def eval(self, _script: str):
            trace.append("extract")
            return {
                "name": "We have detected multiple sign-ins",
                "headline": "",
                "otw": False,
                "summary": "",
                "education": "",
                "dates": [],
                "full": "Only one session allowed",
            }

        def screenshot(self, _path: str) -> None:
            trace.append("screenshot")

    class Archive:
        def save(self, **_kwargs):
            trace.append("archive")
            return type("Receipt", (), {"row_id": 1})()

    def conflict_check(_tab) -> None:
        trace.append("block-check")
        raise PreflightError(
            {
                "ok": False,
                "reasons": ["enterprise-authentication/sessions"],
                "checks": {"no_session_conflict": False},
                "card_count": 0,
            }
        )

    monkeypatch.setattr(hcr, "OUT_DIR", tmp_path)
    monkeypatch.setattr(hcr, "LOG", tmp_path / "run.log")
    monkeypatch.setattr(hcr, "human_delay", lambda: None)
    monkeypatch.setattr(
        "tools.multi_position_sourcing.profile_archive_store.ProfileArchiveStore",
        Archive,
    )

    rows = hcr.process_cards_with_r4(
        Tab(),
        [_card(), _card(profile_url=PROFILE_URL + "-two", navigation_url=NAVIGATION_URL + "-two")],
        owner_snapshot=lambda: _OwnerIdle(),
        live_check=conflict_check,
    )

    assert rows == []
    assert trace == [f"navigate:{NAVIGATION_URL}", "block-check"]
    assert not (tmp_path / "results.json").exists()
