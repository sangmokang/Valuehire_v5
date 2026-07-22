from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing import humansearch_cdp_run as runner
from tools.multi_position_sourcing.humansearch_preflight import PreflightError
from tools.multi_position_sourcing.session_guard import BrowserTargetRef


SOURCE_SEARCH_URL = (
    "https://www.linkedin.com/talent/hire/1752949252/discover/recruiterSearch"
    "?searchContextId=context-156&searchHistoryId=21211832492"
    "&searchRequestId=request-156"
)


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
                    "source_search_url": SOURCE_SEARCH_URL,
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
            "source_search_url": SOURCE_SEARCH_URL,
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
        if _script == "location.href":
            return self.navigated[-1] if self.navigated else ""
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

    result = runner.process_profile(
        tab,
        {
            "url": "https://www.linkedin.com/talent/profile/AAA",
            "navigation_url": navigation_url,
            "source_search_url": SOURCE_SEARCH_URL,
            "name": "Candidate",
        },
        1,
    )

    assert tab.navigated == [navigation_url]
    assert result["url"] == "https://www.linkedin.com/talent/profile/AAA"
    assert result["navigation_url"] == navigation_url
    assert result["source_search_url"] == SOURCE_SEARCH_URL


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
                "source_search_url": SOURCE_SEARCH_URL,
                "name": "Candidate",
            },
            1,
        )

    assert len(tab.navigated) == 1
    assert tab.extractions == 0
    assert tab.screenshots == 0
    assert archive_calls == []


def test_candidate_identity_mismatch_stops_before_screenshot_or_archive(
    monkeypatch, tmp_path: Path
) -> None:
    tab = _ProfileTab(tmp_path)
    archive_calls: list[object] = []
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)

    original_eval = tab.eval

    def wrong_candidate(script: str):
        payload = original_eval(script)
        if isinstance(payload, dict):
            payload["name"] = "토트, Physical AI Engineer"
        return payload

    tab.eval = wrong_candidate  # type: ignore[method-assign]

    def archive(*args, **kwargs):
        archive_calls.append((args, kwargs))
        return SimpleNamespace(row_id=1)

    monkeypatch.setattr(runner, "assert_not_blocked_or_abort", lambda _tab: {"ok": True})
    monkeypatch.setattr(
        "tools.multi_position_sourcing.profile_archive_store.ProfileArchiveStore.save",
        archive,
    )

    with pytest.raises(RuntimeError, match="candidate identity mismatch"):
        runner.process_profile(
            tab,
            {
                "url": "https://www.linkedin.com/talent/profile/AAA",
                "navigation_url": (
                    "https://www.linkedin.com/talent/profile/AAA"
                    "?project=1752949252&searchHistoryId=21211832492"
                ),
                "source_search_url": SOURCE_SEARCH_URL,
                "name": "Candidate",
            },
            1,
        )

    assert tab.screenshots == 0
    assert archive_calls == []


@pytest.mark.parametrize("missing_name", ["", "   "])
def test_missing_candidate_name_is_terminal_before_navigation(
    monkeypatch, tmp_path: Path, missing_name: str
) -> None:
    tab = _ProfileTab(tmp_path)
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)

    with pytest.raises(PreflightError, match="candidate name"):
        runner.process_profile(
            tab,
            {
                "url": "https://www.linkedin.com/talent/profile/AAA",
                "navigation_url": (
                    "https://www.linkedin.com/talent/profile/AAA"
                    "?project=1752949252&searchHistoryId=21211832492"
                ),
                "source_search_url": SOURCE_SEARCH_URL,
                "name": missing_name,
            },
            1,
        )

    assert tab.navigated == []
    assert tab.screenshots == 0


@pytest.mark.parametrize(
    ("profile_url", "navigation_url"),
    [
        (
            "https://evil.example/talent/profile/AAA",
            "https://www.linkedin.com/talent/profile/AAA?project=1752949252",
        ),
        (
            "https://www.linkedin.com/talent/profile/AAA",
            "http://www.linkedin.com/talent/profile/AAA?project=1752949252",
        ),
        (
            "https://www.linkedin.com/talent/profile/AAA",
            "https://www.linkedin.com/talent/profile/AAA?x=1",
        ),
    ],
)
def test_unscoped_or_untrusted_profile_urls_stop_before_navigation(
    monkeypatch, tmp_path: Path, profile_url: str, navigation_url: str
) -> None:
    tab = _ProfileTab(tmp_path)
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)

    with pytest.raises(PreflightError, match="profile URL"):
        runner.process_profile(
            tab,
            {
                "url": profile_url,
                "navigation_url": navigation_url,
                "source_search_url": SOURCE_SEARCH_URL,
                "name": "Candidate",
            },
            1,
        )

    assert tab.navigated == []
    assert tab.screenshots == 0


def test_stale_profile_url_after_navigation_is_terminal_before_extract(
    monkeypatch, tmp_path: Path
) -> None:
    tab = _ProfileTab(tmp_path)
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)
    original_eval = tab.eval

    def stale_url(script: str):
        if script == "location.href":
            return "https://www.linkedin.com/talent/profile/STALE?project=1752949252"
        return original_eval(script)

    tab.eval = stale_url  # type: ignore[method-assign]

    with pytest.raises(PreflightError, match="profile identity"):
        runner.process_profile(
            tab,
            {
                "url": "https://www.linkedin.com/talent/profile/AAA",
                "navigation_url": (
                    "https://www.linkedin.com/talent/profile/AAA?project=1752949252"
                ),
                "source_search_url": SOURCE_SEARCH_URL,
                "name": "Candidate",
            },
            1,
            live_check=lambda _tab: {"ok": True},
        )

    assert tab.extractions == 0
    assert tab.screenshots == 0


def test_profile_is_rechecked_after_screenshot_before_archive(
    monkeypatch, tmp_path: Path
) -> None:
    tab = _ProfileTab(tmp_path)
    checks = {"count": 0}
    archive_calls: list[object] = []
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)

    def late_conflict(_tab):
        checks["count"] += 1
        if checks["count"] == 3:
            raise PreflightError({"reasons": ["late session conflict"]})
        return {"ok": True}

    monkeypatch.setattr(
        "tools.multi_position_sourcing.profile_archive_store.ProfileArchiveStore.save",
        lambda *args, **kwargs: archive_calls.append((args, kwargs)),
    )

    with pytest.raises(PreflightError, match="late session conflict"):
        runner.process_profile(
            tab,
            {
                "url": "https://www.linkedin.com/talent/profile/AAA",
                "navigation_url": (
                    "https://www.linkedin.com/talent/profile/AAA?project=1752949252"
                ),
                "source_search_url": SOURCE_SEARCH_URL,
                "name": "Candidate",
            },
            1,
            live_check=late_conflict,
        )

    assert checks["count"] == 3
    assert tab.screenshots == 1
    assert archive_calls == []
    assert list(tmp_path.glob("*.png")) == []


def test_identity_context_error_stops_remaining_profile_traversal(
    monkeypatch, tmp_path: Path
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)
    monkeypatch.setattr(runner, "LOG", tmp_path / "run.log")
    monkeypatch.setattr(runner, "human_delay", lambda: None)

    def context_error(_tab, card, _idx, **_kwargs):
        opened.append(card["url"])
        raise PreflightError({"reasons": ["candidate identity mismatch"]})

    monkeypatch.setattr(runner, "process_profile", context_error)
    rows = runner.process_cards_with_r4(
        object(),
        [
            {"url": "https://www.linkedin.com/talent/profile/AAA"},
            {"url": "https://www.linkedin.com/talent/profile/BBB"},
        ],
        owner_snapshot=lambda: SimpleNamespace(owner_activity_detected=False),
    )

    assert rows == []
    assert opened == ["https://www.linkedin.com/talent/profile/AAA"]


def test_collect_cards_checks_session_before_scrolling_or_extracting(monkeypatch) -> None:
    trace: list[str] = []

    class Tab:
        def navigate(self, url: str, wait_ms: int = 0):
            trace.append(f"navigate:{url}")

        def eval(self, _script: str):
            trace.append("eval")
            raise AssertionError("blocked results page must not be extracted")

    def blocked(_tab):
        trace.append("block-check")
        raise PreflightError({"reasons": ["multiple sign-ins"]})

    monkeypatch.setattr(runner, "assert_not_blocked_or_abort", blocked)

    with pytest.raises(PreflightError, match="multiple sign-ins"):
        runner.collect_cards(Tab(), 25)

    assert trace[0].startswith("navigate:")
    assert trace[1:] == ["block-check"]


def test_card_scroll_rechecks_session_and_stops_before_card_extraction() -> None:
    trace: list[str] = []
    checks = {"count": 0}

    class Tab:
        def eval(self, script: str):
            trace.append("card-extract" if "const seen" in script else "scroll")
            return []

    def late_conflict(_tab):
        checks["count"] += 1
        if checks["count"] == 3:
            raise PreflightError({"reasons": ["late multiple sign-ins"]})
        return {"ok": True}

    with pytest.raises(PreflightError, match="late multiple sign-ins"):
        runner.extract_cards_from_current_page(Tab(), live_check=late_conflict)

    assert "card-extract" not in trace


def test_final_scroll_top_is_preceded_by_a_fresh_session_check() -> None:
    trace: list[str] = []
    checks = {"count": 0}

    class Tab:
        def eval(self, script: str):
            if "scrollTo" in script:
                trace.append("scroll-top")
            return []

    def conflict_before_scroll_top(_tab):
        checks["count"] += 1
        if checks["count"] == 9:
            raise PreflightError({"reasons": ["conflict before scroll top"]})
        return {"ok": True}

    with pytest.raises(PreflightError, match="conflict before scroll top"):
        runner.extract_cards_from_current_page(
            Tab(), live_check=conflict_before_scroll_top
        )

    assert "scroll-top" not in trace


def test_exact_recruiter_target_refuses_generic_or_ambiguous_tabs(monkeypatch) -> None:
    with pytest.raises(PreflightError, match="explicit Recruiter target id"):
        runner.resolve_exact_recruiter_target()

    calls: list[tuple[str, str | None]] = []

    def exact_resolver(site: str, *, target_id: str | None = None):
        calls.append((site, target_id))
        return BrowserTargetRef(
            site="linkedin_rps",
            endpoint="http://127.0.0.1:9224",
            target_id="exact-2",
            websocket_url="ws://127.0.0.1:9224/devtools/page/exact-2",
            initial_url=runner.SEARCH_URL_BASE,
            profile_path="/tmp/linkedin-profile",
            browser_pid=4242,
        )

    target = runner.resolve_exact_recruiter_target(
        target_id="exact-2", target_resolver=exact_resolver
    )
    assert calls == [("linkedin_rps", "exact-2")]
    assert target["id"] == "exact-2"
    assert target["_endpoint"] == "http://127.0.0.1:9224"
    assert target["_profile_path"] == "/tmp/linkedin-profile"


def test_navigation_scope_must_match_harvest_search_context(
    monkeypatch, tmp_path: Path
) -> None:
    tab = _ProfileTab(tmp_path)
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)

    with pytest.raises(PreflightError, match="search scope"):
        runner.process_profile(
            tab,
            {
                "url": "https://www.linkedin.com/talent/profile/AAA",
                "navigation_url": (
                    "https://www.linkedin.com/talent/profile/AAA"
                    "?project=other-project&searchHistoryId=other-history"
                ),
                "source_search_url": SOURCE_SEARCH_URL,
                "name": "Candidate",
            },
            1,
        )

    assert tab.navigated == []


def test_any_conflicting_shared_scope_key_rejects_navigation(
    monkeypatch, tmp_path: Path
) -> None:
    tab = _ProfileTab(tmp_path)
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)

    with pytest.raises(PreflightError, match="search scope"):
        runner.process_profile(
            tab,
            {
                "url": "https://www.linkedin.com/talent/profile/AAA",
                "navigation_url": (
                    "https://www.linkedin.com/talent/profile/AAA"
                    "?project=other-project&searchHistoryId=21211832492"
                ),
                "source_search_url": SOURCE_SEARCH_URL,
                "name": "Candidate",
            },
            1,
        )

    assert tab.navigated == []


def test_conflicting_search_request_id_rejects_navigation(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)

    with pytest.raises(PreflightError, match="search scope"):
        runner._validate_profile_card_context(
            {
                "url": "https://www.linkedin.com/talent/profile/AAA",
                "navigation_url": (
                    "https://www.linkedin.com/talent/profile/AAA"
                    "?project=1752949252&searchHistoryId=21211832492"
                    "&searchRequestId=other-request"
                ),
                "source_search_url": SOURCE_SEARCH_URL,
                "name": "Candidate",
            }
        )


def test_badge_mutation_runs_lease_guard_immediately_before_dom_change() -> None:
    trace: list[str] = []

    class Tab:
        def eval(self, _script: str):
            return SOURCE_SEARCH_URL

        def mark_busy(self, _label: str, *, expected_url: str):
            trace.append(f"badge:{expected_url}")
            return True

    runner._mark_busy_or_abort(
        Tab(), mutation_guard=lambda: trace.append("lease.assert_owned")
    )

    assert trace == ["lease.assert_owned", f"badge:{SOURCE_SEARCH_URL}"]


def test_non_search_talent_source_path_is_rejected(monkeypatch, tmp_path: Path) -> None:
    tab = _ProfileTab(tmp_path)
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)

    with pytest.raises(PreflightError, match="profile URL"):
        runner.process_profile(
            tab,
            {
                "url": "https://www.linkedin.com/talent/profile/AAA",
                "navigation_url": (
                    "https://www.linkedin.com/talent/profile/AAA?project=1752949252"
                ),
                "source_search_url": (
                    "https://www.linkedin.com/talent/not-a-search?project=1752949252"
                ),
                "name": "Candidate",
            },
            1,
        )

    assert tab.navigated == []


def test_cli_accepts_explicit_target_id() -> None:
    assert runner._parse_cli_args(["runner.py", "25", "0", "exact-target"]) == (
        25,
        0,
        "exact-target",
    )


def test_main_holds_one_linkedin_profile_lease_and_releases_on_attach_error(
    monkeypatch, tmp_path: Path
) -> None:
    trace: list[str] = []

    class Lease:
        def acquire(self):
            trace.append("acquire")

        def assert_owned(self):
            trace.append("assert_owned")

        def release(self):
            trace.append("release")

    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)
    monkeypatch.setattr(runner, "LOG", tmp_path / "run.log")
    ref = BrowserTargetRef(
        site="linkedin_rps",
        endpoint="http://127.0.0.1:9224",
        target_id="exact",
        websocket_url="ws://127.0.0.1:9224/devtools/page/exact",
        initial_url=runner.SEARCH_URL_BASE,
        profile_path="/tmp/linkedin-profile",
        browser_pid=4242,
    )
    monkeypatch.setattr(
        runner.cdp,
        "attach",
        lambda _target, **_kwargs: (_ for _ in ()).throw(RuntimeError("attach failed")),
    )

    with pytest.raises(RuntimeError, match="attach failed"):
        runner.main(
            target_id="exact",
            target_resolver=lambda *_args, **_kwargs: ref,
            lease_factory=lambda _site: Lease(),
        )

    assert trace == ["acquire", "assert_owned", "assert_owned", "release"]


def test_conflict_target_is_attached_without_badge_and_only_disconnected(
    monkeypatch, tmp_path: Path
) -> None:
    trace: list[str] = []

    class Lease:
        def acquire(self):
            trace.append("lease.acquire")

        def assert_owned(self):
            trace.append("lease.assert_owned")

        def release(self):
            trace.append("lease.release")

    class Tab:
        def disconnect(self):
            trace.append("tab.disconnect")
            return True

        def close(self):
            raise AssertionError("humansearch must never run badge cleanup on conflict")

    ref = BrowserTargetRef(
        site="linkedin_rps",
        endpoint="http://127.0.0.1:9224",
        target_id="exact",
        websocket_url="ws://127.0.0.1:9224/devtools/page/exact",
        initial_url=runner.SEARCH_URL_BASE,
        profile_path="/tmp/linkedin-profile",
        browser_pid=4242,
    )
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)
    monkeypatch.setattr(runner, "LOG", tmp_path / "run.log")

    def attach(_target, *, badge: bool):
        trace.append(f"attach.badge={badge}")
        return Tab()

    monkeypatch.setattr(runner.cdp, "attach", attach)
    monkeypatch.setattr(
        runner,
        "assert_not_blocked_or_abort",
        lambda _tab: (_ for _ in ()).throw(
            PreflightError({"reasons": ["multiple sign-ins"]})
        ),
    )

    with pytest.raises(PreflightError, match="multiple sign-ins"):
        runner.main(
            target_id="exact",
            target_resolver=lambda *_args, **_kwargs: ref,
            lease_factory=lambda _site: Lease(),
        )

    assert "attach.badge=False" in trace
    assert "tab.disconnect" in trace
    assert trace[-1] == "lease.release"


def test_safe_target_proves_badge_before_first_navigation(monkeypatch, tmp_path: Path) -> None:
    trace: list[str] = []

    class Lease:
        def acquire(self):
            trace.append("lease.acquire")

        def assert_owned(self):
            trace.append("lease.assert_owned")

        def release(self):
            trace.append("lease.release")

    class Tab:
        def eval(self, script: str):
            if script == "location.href":
                return runner.SEARCH_URL_BASE
            return None

        def mark_busy(self, _label: str, *, expected_url: str):
            trace.append(f"badge:{expected_url}")
            return True

        def navigate(self, _url: str, wait_ms: int = 0):
            trace.append("navigate")
            raise RuntimeError("stop after first navigation")

        def close(self):
            trace.append("tab.close")
            return True

        def disconnect(self):
            trace.append("tab.disconnect")
            return True

    ref = BrowserTargetRef(
        site="linkedin_rps",
        endpoint="http://127.0.0.1:9224",
        target_id="exact",
        websocket_url="ws://127.0.0.1:9224/devtools/page/exact",
        initial_url=runner.SEARCH_URL_BASE,
        profile_path="/tmp/linkedin-profile",
        browser_pid=4242,
    )
    monkeypatch.setattr(runner, "OUT_DIR", tmp_path)
    monkeypatch.setattr(runner, "LOG", tmp_path / "run.log")
    monkeypatch.setattr(runner.cdp, "attach", lambda _target, **_kwargs: Tab())
    monkeypatch.setattr(runner, "assert_not_blocked_or_abort", lambda _tab: {"ok": True})

    with pytest.raises(RuntimeError, match="stop after first navigation"):
        runner.main(
            target_id="exact",
            target_resolver=lambda *_args, **_kwargs: ref,
            lease_factory=lambda _site: Lease(),
        )

    assert trace.index(f"badge:{runner.SEARCH_URL_BASE}") < trace.index("navigate")
    assert "tab.close" in trace
    assert trace[trace.index("tab.close") - 1] == "lease.assert_owned"
    assert trace[-1] == "lease.release"


def test_recruiter_profile_extractor_uses_document_title_for_candidate_name() -> None:
    assert "location.pathname.includes('/talent/profile/')" in runner.EXTRACT_JS
    assert "const titleName = (document.title || '')" in runner.EXTRACT_JS
    assert "? titleName : h1Name" in runner.EXTRACT_JS


def test_missing_existing_recruiter_target_never_creates_tab(monkeypatch) -> None:
    monkeypatch.setattr(runner.cdp, "list_pages", lambda: [])
    created: list[str] = []

    def forbidden_new_tab(url: str):
        created.append(url)
        raise AssertionError("humansearch must not create a Recruiter tab")

    monkeypatch.setattr(runner.cdp, "new_tab", forbidden_new_tab)

    with pytest.raises(RuntimeError, match="explicit Recruiter target id"):
        runner.main()

    assert created == []
