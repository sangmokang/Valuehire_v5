"""Exact target, HUMAN_AUTH, click/Back keepalive의 실행 계약."""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing.portal_worker import ProfileLockError
from tools.multi_position_sourcing.session_guard import (
    _cleanup_keepalive_badge,
    AuthObservation,
    BrowserTargetRef,
    LoginWindowLocator,
    ManagedBrowserProcess,
    SafeKeepaliveTarget,
    cleanup_exact_login_presentation,
    execute_keepalive_roundtrip,
    present_exact_login_window_once,
    resolve_managed_browser_process,
    resolve_existing_target,
    wait_for_human_auth,
)


def _ref(url: str = "https://www.linkedin.com/talent/home") -> BrowserTargetRef:
    return BrowserTargetRef(
        site="linkedin_rps",
        endpoint="http://127.0.0.1:9225",
        target_id="target-exact",
        websocket_url="ws://target-exact",
        initial_url=url,
        browser_pid=4321,
    )


def _safe(**overrides: object) -> SafeKeepaliveTarget:
    values: dict[str, object] = {
        "target_id": "target-exact",
        "source_url": "https://www.linkedin.com/talent/home",
        "selector": "a[data-vh-safe-keepalive]",
        "destination_url": "https://www.linkedin.com/talent/projects",
        "method": "GET",
        "target_attr": "_self",
        "download": False,
        "dedicated_tab": True,
        "clean_form": True,
        "previously_opened_free": True,
        "risk_labels": (),
    }
    values.update(overrides)
    return SafeKeepaliveTarget(**values)


def test_resolver_uses_one_managed_endpoint_and_exact_target_never_first_fallback() -> None:
    calls: list[str] = []
    wrong = {
        "id": "first-wrong",
        "type": "page",
        "url": "https://www.linkedin.com/talent/home",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9225/devtools/page/first-wrong",
    }
    exact = {
        "id": "target-exact",
        "type": "page",
        "url": "https://www.linkedin.com/talent/home",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9225/devtools/page/target-exact",
    }

    def list_pages(endpoint: str):
        calls.append(endpoint)
        return [wrong, exact]

    ref = resolve_existing_target(
        "linkedin_rps",
        target_id="target-exact",
        managed_endpoint_resolver=lambda _site: "http://127.0.0.1:9225",
        list_pages=list_pages,
    )
    assert ref.target_id == "target-exact"
    assert ref.websocket_url == "ws://127.0.0.1:9225/devtools/page/target-exact"
    assert calls == ["http://127.0.0.1:9225"]

    with pytest.raises(LookupError):
        resolve_existing_target(
            "linkedin_rps",
            managed_endpoint_resolver=lambda _site: "http://127.0.0.1:9225",
            list_pages=lambda endpoint: [wrong, exact],
        )


def test_managed_browser_process_binds_exact_port_profile_and_root_pid() -> None:
    class Result:
        returncode = 0
        stdout = """\
  111 /Applications/Chrome --remote-debugging-port=9224 --user-data-dir=/tmp/other
  222 /Applications/Google Chrome --remote-debugging-port=9225 --user-data-dir=/tmp/LinkedIn Profile --no-first-run
  223 /Applications/Google Chrome --type=renderer --remote-debugging-port=9225 --user-data-dir=/tmp/LinkedIn Profile --no-first-run
"""

    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> Result:
        calls.append(command)
        assert kwargs == {
            "capture_output": True,
            "text": True,
            "timeout": 15,
            "check": False,
        }
        return Result()

    process = resolve_managed_browser_process(
        "linkedin_rps",
        "http://127.0.0.1:9225",
        runner=run,
    )

    assert process == ManagedBrowserProcess(222, "/tmp/LinkedIn Profile")
    assert calls == [["ps", "ax", "-o", "pid=,command="]]


@pytest.mark.parametrize(
    "command",
    [
        "python worker.py --remote-debugging-port=9225 --user-data-dir=/tmp/profile",
        (
            "python /tmp/Google Chrome --remote-debugging-port=9225 "
            "--user-data-dir=/tmp/LinkedIn Profile"
        ),
        (
            "/Applications/Google Chrome --remote-debugging-port=9225 "
            "--user-data-dir=/tmp/LinkedIn Profile https://example.com"
        ),
        (
            "/Applications/Google Chrome --remote-debugging-port=9225 "
            "--user-data-dir=/tmp/LinkedIn Profile about:blank"
        ),
        (
            "/Applications/Google Chrome --remote-debugging-port=9225 "
            "--user-data-dir=/tmp/LinkedIn Profile data:text/plain,hello"
        ),
        (
            "/Applications/Google Chrome --remote-debugging-port=9225 "
            "--user-data-dir=/tmp/LinkedIn Profile www.example.com"
        ),
    ],
)
def test_managed_browser_process_rejects_non_chrome_or_trailing_positional_url(
    command: str,
) -> None:
    class Result:
        returncode = 0
        stdout = f"222 {command}\n"

    with pytest.raises(LookupError):
        resolve_managed_browser_process(
            "linkedin_rps",
            "http://127.0.0.1:9225",
            runner=lambda *_args, **_kwargs: Result(),
        )


def test_managed_browser_process_accepts_repo_launcher_trailing_start_url() -> None:
    class Result:
        returncode = 0
        stdout = (
            "222 /Applications/Google Chrome "
            "--remote-debugging-port=9225 "
            "--remote-debugging-address=127.0.0.1 "
            "--user-data-dir=/tmp/LinkedIn Profile "
            "--no-first-run --no-default-browser-check "
            "--disable-session-crashed-bubble --restore-last-session=false "
            "https://www.linkedin.com/talent/home\n"
        )

    process = resolve_managed_browser_process(
        "linkedin_rps",
        "http://127.0.0.1:9225",
        runner=lambda *_args, **_kwargs: Result(),
    )

    assert process == ManagedBrowserProcess(222, "/tmp/LinkedIn Profile")


def test_resolver_binds_process_before_page_and_rejects_endpoint_swap() -> None:
    endpoints = iter(("http://127.0.0.1:9225", "http://127.0.0.1:9338"))
    page_calls: list[str] = []

    with pytest.raises(LookupError, match="changed"):
        resolve_existing_target(
            "linkedin_rps",
            target_id="target-exact",
            managed_endpoint_resolver=lambda _site: next(endpoints),
            browser_process_resolver=lambda _site, endpoint: ManagedBrowserProcess(
                222, "/tmp/linkedin"
            ),
            list_pages=lambda endpoint: page_calls.append(endpoint) or [],
        )

    assert page_calls == []


def test_resolver_rechecks_browser_process_after_exact_page_selection() -> None:
    processes = iter((
        ManagedBrowserProcess(222, "/tmp/linkedin"),
        ManagedBrowserProcess(333, "/tmp/restarted-linkedin"),
    ))
    page = {
        "id": "target-exact",
        "type": "page",
        "url": "https://www.linkedin.com/talent/home",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9225/devtools/page/target-exact",
    }

    with pytest.raises(LookupError, match="process changed"):
        resolve_existing_target(
            "linkedin_rps",
            target_id="target-exact",
            managed_endpoint_resolver=lambda _site: "http://127.0.0.1:9225",
            browser_process_resolver=lambda _site, _endpoint: next(processes),
            list_pages=lambda _endpoint: [page],
        )


@pytest.mark.parametrize(
    ("site", "url"),
    [
        ("linkedin_rps", "https://www.linkedin.com/feed/"),
        ("saramin", "https://www.saramin.co.kr/zf_user/jobs/list/domestic"),
        ("jobkorea", "https://www.jobkorea.co.kr/Recruit/Home"),
    ],
)
def test_resolver_rejects_wrong_official_domain_surface(site: str, url: str) -> None:
    with pytest.raises(LookupError):
        resolve_existing_target(
            site,
            target_id="wrong-surface",
            managed_endpoint_resolver=lambda _site: "http://127.0.0.1:9225",
            list_pages=lambda _endpoint: [
                {
                    "id": "wrong-surface",
                    "type": "page",
                    "url": url,
                    "webSocketDebuggerUrl": "ws://127.0.0.1:9225/devtools/page/wrong-surface",
                }
            ],
        )


def test_human_auth_wait_survives_past_900_seconds_without_mutation_or_refocus() -> None:
    assert "timeout" not in inspect.signature(wait_for_human_auth).parameters
    elapsed = 0.0
    probes = 0
    forbidden: list[str] = []

    def auth_probe() -> AuthObservation:
        nonlocal probes
        probes += 1
        authenticated = probes >= 183
        return AuthObservation(
            authenticated=authenticated,
            challenge=not authenticated,
            url="https://www.linkedin.com/talent/home" if authenticated else "https://www.linkedin.com/login",
            proof_names=("recruiter_nav",) if authenticated else (),
        )

    def owner_snapshot():
        return SimpleNamespace(
            owner_activity_detected=probes < 184,
            idle_seconds=15.0 if probes >= 184 else 0.0,
            detection_status="ok",
        )

    def sleep(seconds: float) -> None:
        nonlocal elapsed
        assert seconds >= 5.0
        elapsed += seconds

    result = wait_for_human_auth(
        auth_probe=auth_probe,
        owner_snapshot=owner_snapshot,
        sleep=sleep,
        stop_requested=lambda: False,
    )

    assert result is not None and result.authenticated
    assert elapsed > 900
    assert forbidden == []


def test_human_auth_requires_auth_marker_and_fifteen_seconds_quiet() -> None:
    idle = iter((None, 14.9, 15.0))
    sleeps: list[float] = []

    result = wait_for_human_auth(
        auth_probe=lambda: AuthObservation(
            authenticated=True,
            challenge=False,
            url="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            proof_names=("account", "search"),
        ),
        owner_snapshot=lambda: SimpleNamespace(
            owner_activity_detected=False,
            idle_seconds=next(idle),
            detection_status="ok",
        ),
        sleep=lambda seconds: sleeps.append(seconds),
        stop_requested=lambda: False,
    )

    assert result is not None and result.authenticated
    assert len(sleeps) == 2
    assert all(seconds >= 5 for seconds in sleeps)


def test_human_auth_never_accepts_owner_activity_even_with_large_idle_value() -> None:
    sleeps: list[float] = []
    result = wait_for_human_auth(
        auth_probe=lambda: AuthObservation(
            authenticated=True,
            challenge=False,
            url="https://www.linkedin.com/talent/home",
            proof_names=("talent_surface", "recruiter_account"),
        ),
        owner_snapshot=lambda: SimpleNamespace(
            owner_activity_detected=True,
            idle_seconds=999.0,
            detection_status="ok",
        ),
        sleep=lambda seconds: sleeps.append(seconds),
        stop_requested=lambda: bool(sleeps),
    )
    assert result is None
    assert sleeps == [5.0]


def test_human_auth_stop_after_probes_wins_over_authenticated_result() -> None:
    stop_checks = 0
    probes: list[str] = []

    def stop() -> bool:
        nonlocal stop_checks
        stop_checks += 1
        return stop_checks >= 2

    result = wait_for_human_auth(
        auth_probe=lambda: probes.append("auth") or AuthObservation(
            authenticated=True,
            challenge=False,
            url="https://www.linkedin.com/talent/home",
            proof_names=("talent_surface", "recruiter_account"),
        ),
        owner_snapshot=lambda: probes.append("owner") or SimpleNamespace(
            owner_activity_detected=False,
            idle_seconds=15.0,
            detection_status="ok",
        ),
        sleep=lambda _seconds: pytest.fail("stop after probes must not sleep"),
        stop_requested=stop,
    )

    assert result is None
    assert probes == ["auth", "owner"]


class _KeepaliveTab:
    def __init__(self) -> None:
        self.target_id = "target-exact"
        self.url = "https://www.linkedin.com/talent/home"
        self.trace: list[str] = []
        self.forbidden_calls: list[str] = []

    def send(self, method: str, params: dict | None = None):
        if method == "Page.getNavigationHistory":
            self.trace.append("history")
            if self.url.endswith("/projects"):
                return {
                    "currentIndex": 2,
                    "entries": [
                        {"id": 41, "url": "https://www.linkedin.com/talent/previous"},
                        {"id": 42, "url": "https://www.linkedin.com/talent/home"},
                        {"id": 43, "url": "https://www.linkedin.com/talent/projects"},
                    ],
                }
            return {
                "currentIndex": 1,
                "entries": [
                    {"id": 41, "url": "https://www.linkedin.com/talent/previous"},
                    {"id": 42, "url": "https://www.linkedin.com/talent/home"},
                ],
            }
        if method == "Page.navigateToHistoryEntry":
            self.trace.append(f"back:{params['entryId']}")
            self.url = "https://www.linkedin.com/talent/home"
            return {}
        if method == "Target.getTargetInfo":
            return {
                "targetInfo": {
                    "targetId": self.target_id,
                    "type": "page",
                    "url": self.url,
                }
            }
        if method in {"Page.navigate", "Target.createTarget", "Target.closeTarget", "Browser.close"}:
            self.forbidden_calls.append(method)
            raise AssertionError(method)
        raise AssertionError(method)

    def current_url(self) -> str:
        self.trace.append(f"url:{self.url.rsplit('/', 1)[-1]}")
        return self.url

    def click_safe_link(self, target: SafeKeepaliveTarget) -> bool:
        self.trace.append("click")
        self.url = target.destination_url
        return True


def test_keepalive_success_clicks_then_history_back_with_two_fresh_gates() -> None:
    tab = _KeepaliveTab()
    gates = 0

    def gate() -> None:
        nonlocal gates
        gates += 1
        tab.trace.append(f"gate{gates}")

    result = execute_keepalive_roundtrip(
        tab,
        _ref(),
        _safe(),
        auth_probe=lambda current: AuthObservation(
            authenticated=True,
            challenge=False,
            url=current.current_url(),
            proof_names=("recruiter_nav",),
        ),
        mutation_gate=gate,
    )

    assert result["status"] == "ok"
    assert result["restore_pending"] is False
    assert gates == 2
    assert tab.trace == [
        "url:home",
        "history",
        "gate1",
        "click",
        "url:projects",
        "url:projects",
        "history",
        "url:projects",
        "url:projects",
        "history",
        "gate2",
        "back:42",
        "url:home",
        "url:home",
        "history",
        "url:home",
        "url:home",
        "history",
    ]
    assert tab.forbidden_calls == []


def test_owner_returns_after_click_sets_restore_pending_and_never_backs() -> None:
    tab = _KeepaliveTab()
    gates = 0

    def gate() -> None:
        nonlocal gates
        gates += 1
        tab.trace.append(f"gate{gates}")
        if gates == 2:
            raise ProfileLockError("owner activity blocks raw browser mutation")

    result = execute_keepalive_roundtrip(
        tab,
        _ref(),
        _safe(),
        auth_probe=lambda current: AuthObservation(
            authenticated=True,
            challenge=False,
            url=current.current_url(),
            proof_names=("recruiter_nav",),
        ),
        mutation_gate=gate,
    )

    assert result["status"] == "restore_pending"
    assert result["restore_pending"] is True
    assert not any(item.startswith("back:") for item in tab.trace)
    assert tab.forbidden_calls == []


@pytest.mark.parametrize("loss_gate", [1, 2])
def test_keepalive_roundtrip_never_mislabels_lease_ownership_loss(
    loss_gate: int,
) -> None:
    tab = _KeepaliveTab()
    gates = 0

    def gate() -> None:
        nonlocal gates
        gates += 1
        if gates == loss_gate:
            raise ProfileLockError("raw browser lease ownership was lost")

    with pytest.raises(ProfileLockError, match="ownership was lost"):
        execute_keepalive_roundtrip(
            tab,
            _ref(),
            _safe(),
            auth_probe=lambda current: AuthObservation(
                authenticated=True,
                challenge=False,
                url=current.current_url(),
                proof_names=("recruiter_nav",),
            ),
            mutation_gate=gate,
        )

    assert not any(item.startswith("back:") for item in tab.trace)
    assert ("click" in tab.trace) is (loss_gate == 2)


def test_target_identity_change_after_click_never_sends_back() -> None:
    tab = _KeepaliveTab()

    def click_and_swap(target: SafeKeepaliveTarget) -> bool:
        tab.trace.append("click")
        tab.url = target.destination_url
        tab.target_id = "different-target"
        return True

    tab.click_safe_link = click_and_swap
    gates: list[str] = []
    result = execute_keepalive_roundtrip(
        tab,
        _ref(),
        _safe(),
        auth_probe=lambda current: AuthObservation(
            authenticated=True,
            challenge=False,
            url=current.current_url(),
            proof_names=("recruiter_nav",),
        ),
        mutation_gate=lambda: gates.append("gate"),
    )

    assert result["status"] == "target_changed"
    assert result["restore_pending"] is True
    assert gates == ["gate"]
    assert not any(item.startswith("back:") for item in tab.trace)


def test_destination_auth_failure_never_sends_back() -> None:
    tab = _KeepaliveTab()
    gates: list[str] = []
    result = execute_keepalive_roundtrip(
        tab,
        _ref(),
        _safe(),
        auth_probe=lambda current: AuthObservation(
            authenticated=False,
            challenge=True,
            url=current.current_url(),
            proof_names=(),
        ),
        mutation_gate=lambda: gates.append("gate"),
        navigation_timeout_seconds=0,
    )
    assert result["status"] == "destination_unverified"
    assert result["restore_pending"] is True
    assert gates == ["gate"]
    assert not any(item.startswith("back:") for item in tab.trace)


def test_click_exception_after_navigation_is_pending_not_clean_failure() -> None:
    tab = _KeepaliveTab()

    def navigate_then_raise(target: SafeKeepaliveTarget) -> bool:
        tab.url = target.destination_url
        raise RuntimeError("execution context destroyed")

    tab.click_safe_link = navigate_then_raise
    result = execute_keepalive_roundtrip(
        tab,
        _ref(),
        _safe(),
        auth_probe=lambda current: AuthObservation(
            authenticated=True,
            challenge=False,
            url=current.current_url(),
            proof_names=("recruiter_nav",),
        ),
        mutation_gate=lambda: None,
    )
    assert result["status"] != "click_failed"
    assert result["restore_pending"] is True or result["status"] == "ok"


def test_keepalive_waits_for_async_click_and_async_history_restore() -> None:
    tab = _KeepaliveTab()
    pending: list[tuple[str, int]] = []

    def click_later(target: SafeKeepaliveTarget) -> bool:
        tab.trace.append("click")
        pending.append((target.destination_url, 2))
        return True

    original_send = tab.send

    def send(method: str, params: dict | None = None):
        if method == "Target.getTargetInfo" and pending:
            url, remaining = pending[0]
            if remaining <= 0:
                tab.url = url
                pending.pop(0)
            else:
                pending[0] = (url, remaining - 1)
        if method == "Page.navigateToHistoryEntry":
            tab.trace.append(f"back:{params['entryId']}")
            pending.append(("https://www.linkedin.com/talent/home", 2))
            return {}
        return original_send(method, params)

    tab.click_safe_link = click_later
    tab.send = send
    result = execute_keepalive_roundtrip(
        tab,
        _ref(),
        _safe(),
        auth_probe=lambda current: AuthObservation(
            authenticated=True,
            challenge=False,
            url=current.current_url(),
            proof_names=("recruiter_account",),
        ),
        mutation_gate=lambda: None,
        sleep=lambda _seconds: None,
        navigation_timeout_seconds=0.5,
    )
    assert result["status"] == "ok"
    assert result["restore_pending"] is False


def test_keepalive_never_reports_ok_if_source_auth_probe_redirects_immediately() -> None:
    tab = _KeepaliveTab()

    def probe(current: _KeepaliveTab) -> AuthObservation:
        url = current.current_url()
        observation = AuthObservation(True, False, url, ("recruiter_account",))
        if url.endswith("/home") and any(item.startswith("back:") for item in tab.trace):
            tab.url = "https://www.linkedin.com/checkpoint/challenge"
        return observation

    result = execute_keepalive_roundtrip(
        tab,
        _ref(),
        _safe(),
        auth_probe=probe,
        mutation_gate=lambda: None,
        sleep=lambda _seconds: None,
        navigation_timeout_seconds=0.1,
    )
    assert result["status"] != "ok"
    assert result["restore_pending"] is True


def test_keepalive_requires_a_stability_dwell_after_history_restore() -> None:
    tab = _KeepaliveTab()
    source_dwell = 0.0

    def sleep(seconds: float) -> None:
        nonlocal source_dwell
        if any(item.startswith("back:") for item in tab.trace) and tab.url.endswith("/home"):
            source_dwell += seconds
            if source_dwell >= 0.15:
                tab.url = "https://www.linkedin.com/checkpoint/challenge"

    result = execute_keepalive_roundtrip(
        tab,
        _ref(),
        _safe(),
        auth_probe=lambda current: AuthObservation(
            authenticated=True,
            challenge=False,
            url=current.current_url(),
            proof_names=("recruiter_account",),
        ),
        mutation_gate=lambda: None,
        sleep=sleep,
        navigation_timeout_seconds=1.0,
    )

    assert result["status"] != "ok"
    assert result["restore_pending"] is True


def test_non_integer_history_entry_id_fails_before_mutation() -> None:
    tab = _KeepaliveTab()
    original_send = tab.send

    def send(method: str, params: dict | None = None):
        result = original_send(method, params)
        if method == "Page.getNavigationHistory":
            result["entries"][result["currentIndex"]]["id"] = "42"
        return result

    tab.send = send
    gates: list[str] = []
    result = execute_keepalive_roundtrip(
        tab,
        _ref(),
        _safe(),
        auth_probe=lambda _tab: pytest.fail("history must fail before auth"),
        mutation_gate=lambda: gates.append("gate"),
    )
    assert result["status"] == "skipped_history_mismatch"
    assert gates == []


def test_window_ambiguity_fails_before_title_badge_or_focus_mutation() -> None:
    class Tab:
        target_id = "target-exact"

        def __init__(self) -> None:
            self.mutations: list[str] = []

        def current_url(self) -> str:
            return "https://www.linkedin.com/talent/home"

        def eval(self, expression: str):
            if expression == "document.title":
                return "LinkedIn Talent Solutions"
            self.mutations.append("title")
            return "[LOGIN HERE][Codex][linkedin][target-exact] LinkedIn Talent Solutions"

        def mark_busy(self, *_args, **_kwargs) -> bool:
            self.mutations.append("badge")
            return True

        def send(self, method: str, params: dict | None = None):
            if method == "Browser.getWindowForTarget":
                return {"bounds": {"left": 0, "top": 0, "width": 1200, "height": 800}}
            if method == "Page.bringToFront":
                self.mutations.append("focus")
                return {}
            raise AssertionError(method)

    tab = Tab()
    gates: list[str] = []

    def ambiguous(_identity):
        raise RuntimeError("ambiguous window")

    with pytest.raises(RuntimeError, match="ambiguous"):
        present_exact_login_window_once(
            tab,
            _ref(),
            agent="Codex",
            mutation_gate=lambda: gates.append("gate"),
            window_resolver=ambiguous,
            window_capture=lambda _window_id: b"never",
        )

    assert gates == []
    assert tab.mutations == []


class _PresentationTab:
    target_id = "target-exact"

    def __init__(self) -> None:
        self.url = "https://www.linkedin.com/talent/home"
        self.title = "LinkedIn Talent Solutions"
        self.mutations: list[str] = []
        self.busy_label = ""
        self.busy_bound_url = self.url
        self.clear_busy_calls: list[tuple[str, str]] = []
        self.loader_id = "loader-1"

    def current_url(self) -> str:
        return self.url

    def eval(self, expression: str):
        if expression == "document.title":
            return self.title
        if "return document.title===" in expression:
            self.title = "LinkedIn Talent Solutions"
            self.mutations.append("title_restore")
            return True
        if "document.title=" in expression:
            self.title = "[LOGIN HERE][Codex][linkedin][target-exact] LinkedIn RPS login"
            self.mutations.append("title")
            return self.title
        raise AssertionError(expression)

    def mark_busy(self, label: str, *, expected_url: str) -> bool:
        assert expected_url == self.url
        self.busy_label = label
        self.busy_bound_url = expected_url
        self.mutations.append("badge")
        return True

    def set_title_if_badge_owned(
        self,
        title: str,
        *,
        expected_url: str,
        badge_label: str,
    ) -> str | None:
        if (
            expected_url != self.url
            or badge_label != self.busy_label
            or not self.busy_label
            or self.title.startswith("[LOGIN HERE][")
        ):
            return None
        previous_title = self.title
        self.title = title
        self.mutations.append("title")
        return previous_title

    def clear_busy(
        self,
        label: str,
        *,
        expected_url: str,
        badge_bound_url: str | None = None,
    ) -> bool:
        bound_url = expected_url if badge_bound_url is None else badge_bound_url
        self.clear_busy_calls.append((expected_url, bound_url))
        if (
            label != self.busy_label
            or bound_url != self.busy_bound_url
            or expected_url != self.url
        ):
            return False
        self.busy_label = ""
        self.mutations.append("clear_badge")
        return True

    def restore_title_if_badge_owned(
        self,
        original_title: str,
        *,
        expected_url: str,
        badge_label: str,
        title_prefix: str,
    ) -> str | None:
        if (
            expected_url != self.url
            or badge_label != self.busy_label
            or not self.busy_label
            or not self.title.startswith(title_prefix)
        ):
            if (
                expected_url == self.url
                and badge_label == self.busy_label
                and self.busy_label
                and not self.title.startswith(title_prefix)
            ):
                return "title_changed"
            return None
        self.title = original_title
        self.mutations.append("title_restore")
        return "restored"

    def send(self, method: str, params: dict | None = None):
        if method == "Browser.getWindowForTarget":
            return {"bounds": {"left": 0, "top": 0, "width": 1200, "height": 800}}
        if method == "Page.bringToFront":
            self.mutations.append("focus")
            return {}
        if method == "Target.getTargetInfo":
            return {
                "targetInfo": {
                    "targetId": self.target_id,
                    "type": "page",
                    "url": self.url,
                }
            }
        if method == "Page.getFrameTree":
            return {
                "frameTree": {
                    "frame": {
                        "id": "main-frame",
                        "loaderId": self.loader_id,
                        "url": self.url,
                    }
                }
            }
        raise AssertionError((method, params))


def _window(_identity):
    return SimpleNamespace(cg_window_id=180)


def test_presentation_gate_failure_before_dispatch_can_retry_same_episode() -> None:
    tab = _PresentationTab()
    attempts = 0

    def first_gate_fails() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("owner active")

    with pytest.raises(RuntimeError, match="owner active"):
        present_exact_login_window_once(
            tab,
            _ref(),
            agent="Codex",
            episode_id="episode-a",
            mutation_gate=first_gate_fails,
            window_resolver=_window,
            window_capture=lambda _window_id: b"png",
            application_activator=lambda pid: tab.mutations.append(f"activate:{pid}") or True,
        )

    assert tab.mutations == []
    locator = present_exact_login_window_once(
        tab,
        _ref(),
        agent="Codex",
        episode_id="episode-a",
        mutation_gate=first_gate_fails,
        window_resolver=_window,
        window_capture=lambda _window_id: b"png",
        application_activator=lambda pid: tab.mutations.append(f"activate:{pid}") or True,
    )
    assert locator.presentation_count == 1
    assert tab.mutations == ["badge", "title", "focus", "activate:4321"]


def test_presentation_is_once_per_episode_but_new_episode_is_allowed() -> None:
    tab = _PresentationTab()
    kwargs = {
        "agent": "Codex",
        "mutation_gate": lambda: None,
        "window_resolver": _window,
        "window_capture": lambda _window_id: b"png",
        "application_activator": lambda pid: tab.mutations.append(f"activate:{pid}") or True,
    }
    first = present_exact_login_window_once(tab, _ref(), episode_id="episode-a", **kwargs)
    with pytest.raises(RuntimeError, match="already presented"):
        present_exact_login_window_once(tab, _ref(), episode_id="episode-a", **kwargs)
    cleanup = cleanup_exact_login_presentation(
        tab,
        _ref(),
        first,
        mutation_gate=lambda: None,
    )
    assert cleanup["status"] == "cleanup_ok"
    present_exact_login_window_once(tab, _ref(), episode_id="episode-b", **kwargs)
    assert tab.mutations.count("focus") == 2


def test_inactive_tab_marker_is_resolved_after_page_bring_to_front() -> None:
    tab = _PresentationTab()
    marked_resolves = 0

    def resolver(identity):
        nonlocal marked_resolves
        if identity.title_marker:
            marked_resolves += 1
            if "focus" not in tab.mutations:
                raise RuntimeError("inactive tab title is not the CGWindow title yet")
        return SimpleNamespace(cg_window_id=180)

    locator = present_exact_login_window_once(
        tab,
        _ref(),
        agent="Codex",
        episode_id="inactive-tab",
        mutation_gate=lambda: None,
        window_resolver=resolver,
        window_capture=lambda _window_id: b"png",
        application_activator=lambda _pid: True,
    )
    assert locator.cg_window_id == 180
    assert marked_resolves >= 1


def test_presentation_rejects_spa_target_drift_before_focus_or_capture() -> None:
    tab = _PresentationTab()
    gates = 0
    captures: list[int] = []

    def gate() -> None:
        nonlocal gates
        gates += 1
        if gates == 3:
            tab.url = "https://www.linkedin.com/talent/projects"

    with pytest.raises(RuntimeError, match="target.*changed"):
        present_exact_login_window_once(
            tab,
            _ref(),
            agent="Codex",
            episode_id="spa-drift",
            mutation_gate=gate,
            window_resolver=_window,
            window_capture=lambda window_id: captures.append(window_id) or b"png",
            application_activator=lambda _pid: True,
        )

    assert "focus" not in tab.mutations
    assert captures == []


def test_presentation_rejects_same_url_reload_during_first_mutation_gate() -> None:
    tab = _PresentationTab()
    gates = 0

    def reload_during_gate() -> None:
        nonlocal gates
        gates += 1
        if gates == 1:
            tab.loader_id = "loader-2"

    with pytest.raises(RuntimeError, match="document changed"):
        present_exact_login_window_once(
            tab,
            _ref(),
            agent="Codex",
            episode_id="same-url-reload",
            mutation_gate=reload_during_gate,
            window_resolver=_window,
            window_capture=lambda _window_id: b"png",
            application_activator=lambda _pid: True,
        )

    assert tab.mutations == []


def test_presentation_requires_readable_document_identity_before_mutation() -> None:
    class LoaderUnreadableTab(_PresentationTab):
        def send(self, method: str, params: dict | None = None):
            if method == "Page.getFrameTree":
                raise RuntimeError("frame tree unavailable")
            return super().send(method, params)

    tab = LoaderUnreadableTab()
    gates: list[str] = []

    with pytest.raises(RuntimeError, match="document identity is unavailable"):
        present_exact_login_window_once(
            tab,
            _ref(),
            agent="Codex",
            episode_id="missing-loader",
            mutation_gate=lambda: gates.append("gate"),
            window_resolver=_window,
            window_capture=lambda _window_id: b"png",
            application_activator=lambda _pid: True,
        )

    assert gates == []
    assert tab.mutations == []


def test_badge_reload_race_rebinds_guarded_cleanup_to_actual_document() -> None:
    class ReloadingBadgeTab(_PresentationTab):
        def mark_busy(self, label: str, *, expected_url: str) -> bool:
            self.loader_id = "loader-2"
            return super().mark_busy(label, expected_url=expected_url)

    tab = ReloadingBadgeTab()
    with pytest.raises(RuntimeError, match="changed while installing visible badge"):
        present_exact_login_window_once(
            tab,
            _ref(),
            agent="Codex",
            episode_id="badge-reload",
            mutation_gate=lambda: None,
            window_resolver=_window,
            window_capture=lambda _window_id: b"png",
            application_activator=lambda _pid: True,
        )

    locator = getattr(tab, "_vh_human_auth_cleanup_locator")
    assert locator._document_loader_id == "loader-2"
    result = cleanup_exact_login_presentation(
        tab,
        _ref(),
        locator,
        mutation_gate=lambda: None,
    )
    assert result["status"] == "cleanup_ok"
    assert tab.busy_label == ""
    assert tab.mutations == ["badge", "clear_badge"]


def test_badge_dispatch_interrupt_still_cleans_exact_replacement_badge() -> None:
    class InterruptedBadgeTab(_PresentationTab):
        def mark_busy(self, label: str, *, expected_url: str) -> bool:
            applied = super().mark_busy(label, expected_url=expected_url)
            self.loader_id = "loader-2"
            assert applied is True
            raise KeyboardInterrupt("after badge dispatch")

    tab = InterruptedBadgeTab()
    with pytest.raises(KeyboardInterrupt, match="after badge dispatch"):
        present_exact_login_window_once(
            tab,
            _ref(),
            agent="Codex",
            episode_id="badge-interrupt",
            mutation_gate=lambda: None,
            window_resolver=_window,
            window_capture=lambda _window_id: b"png",
            application_activator=lambda _pid: True,
        )

    locator = getattr(tab, "_vh_human_auth_cleanup_locator")
    assert locator._badge_marker_pending is True
    assert locator._document_loader_id == "loader-1"
    cleanup = cleanup_exact_login_presentation(
        tab,
        _ref(),
        locator,
        mutation_gate=lambda: None,
    )
    assert cleanup["status"] == "cleanup_ok"
    assert cleanup["cleanup_pending"] is False
    assert tab.busy_label == ""
    assert tab.mutations == ["badge", "clear_badge"]


def test_title_dispatch_is_bound_to_original_badge_document() -> None:
    class ReloadingTitleTab(_PresentationTab):
        def set_title_if_badge_owned(
            self,
            title: str,
            *,
            expected_url: str,
            badge_label: str,
        ) -> str | None:
            self.loader_id = "loader-2"
            self.busy_label = ""
            return None

    tab = ReloadingTitleTab()
    with pytest.raises(RuntimeError, match="title marker could not be installed"):
        present_exact_login_window_once(
            tab,
            _ref(),
            agent="Codex",
            episode_id="title-reload",
            mutation_gate=lambda: None,
            window_resolver=_window,
            window_capture=lambda _window_id: b"png",
            application_activator=lambda _pid: True,
        )

    assert "title" not in tab.mutations
    assert "focus" not in tab.mutations


def test_presentation_refuses_to_adopt_stale_login_title_as_original() -> None:
    tab = _PresentationTab()
    marker = "[LOGIN HERE][Codex][linkedin][target-exact]"
    tab.title = marker + " LinkedIn RPS login"

    with pytest.raises(RuntimeError, match="title marker could not be installed"):
        present_exact_login_window_once(
            tab,
            _ref(),
            agent="Codex",
            episode_id="stale-title",
            mutation_gate=lambda: None,
            window_resolver=_window,
            window_capture=lambda _window_id: b"png",
            application_activator=lambda _pid: True,
        )

    locator = getattr(tab, "_vh_human_auth_cleanup_locator")
    assert locator._title_marker_applied is False
    cleanup = cleanup_exact_login_presentation(
        tab,
        _ref(),
        locator,
        mutation_gate=lambda: None,
    )
    assert cleanup["status"] == "cleanup_title_original_unknown"
    assert cleanup["cleanup_pending"] is True
    assert tab.title == marker + " LinkedIn RPS login"
    assert "title_restore" not in tab.mutations


def test_title_dispatch_interrupt_reports_pending_instead_of_false_cleanup() -> None:
    class InterruptedTitleTab(_PresentationTab):
        def set_title_if_badge_owned(
            self,
            title: str,
            *,
            expected_url: str,
            badge_label: str,
        ) -> str | None:
            previous = super().set_title_if_badge_owned(
                title,
                expected_url=expected_url,
                badge_label=badge_label,
            )
            assert isinstance(previous, str)
            raise KeyboardInterrupt("after title dispatch")

    tab = InterruptedTitleTab()
    with pytest.raises(KeyboardInterrupt, match="after title dispatch"):
        present_exact_login_window_once(
            tab,
            _ref(),
            agent="Codex",
            episode_id="title-interrupt",
            mutation_gate=lambda: None,
            window_resolver=_window,
            window_capture=lambda _window_id: b"png",
            application_activator=lambda _pid: True,
        )

    locator = getattr(tab, "_vh_human_auth_cleanup_locator")
    assert locator._title_marker_pending is True
    assert locator._title_marker_applied is False
    cleanup = cleanup_exact_login_presentation(
        tab,
        _ref(),
        locator,
        mutation_gate=lambda: None,
    )
    assert cleanup == {
        "status": "cleanup_title_original_unknown",
        "cleanup_pending": True,
        "mutations": 1,
    }
    assert tab.title.startswith("[LOGIN HERE][")


def test_presentation_polls_read_only_for_async_window_marker_propagation() -> None:
    tab = _PresentationTab()
    marked_attempts = 0

    def resolver(identity):
        nonlocal marked_attempts
        if identity.title_marker:
            marked_attempts += 1
            if marked_attempts == 1:
                raise RuntimeError("marker not propagated yet")
        return SimpleNamespace(cg_window_id=180)

    locator = present_exact_login_window_once(
        tab,
        _ref(),
        agent="Codex",
        episode_id="async-marker",
        mutation_gate=lambda: None,
        window_resolver=resolver,
        window_capture=lambda _window_id: b"png",
        application_activator=lambda _pid: True,
        window_sleep=lambda _seconds: None,
    )

    assert locator.cg_window_id == 180
    assert marked_attempts >= 2


def test_handoff_cleanup_removes_owned_badge_and_restores_private_title_guardedly() -> None:
    tab = _PresentationTab()
    marker = "[LOGIN HERE][Codex][linkedin][target-exact]"
    tab.busy_label = marker
    tab.title = marker + " LinkedIn RPS login"
    gates: list[str] = []
    locator = LoginWindowLocator(
        agent="Codex",
        site="linkedin_rps",
        browser_pid=4321,
        profile_path="/tmp/profile",
        cdp_endpoint="http://127.0.0.1:9225",
        target_id_suffix="target-exact",
        sanitized_title=tab.title,
        sanitized_url=tab.url,
        cg_window_id=180,
        screenshot_sha256="a" * 64,
        screenshot_size_bytes=3,
        _original_title="LinkedIn Talent Solutions",
        _marker=marker,
        _title_marker_applied=True,
    )

    result = cleanup_exact_login_presentation(
        tab,
        _ref(),
        locator,
        mutation_gate=lambda: gates.append("gate"),
    )

    assert result == {"status": "cleanup_ok", "cleanup_pending": False, "mutations": 2}
    assert gates == ["gate", "gate"]
    assert tab.busy_label == ""
    assert tab.title == "LinkedIn Talent Solutions"


def test_handoff_cleanup_restores_dynamic_title_that_keeps_owned_marker_prefix() -> None:
    tab = _PresentationTab()
    marker = "[LOGIN HERE][Codex][linkedin][target-exact]"
    tab.busy_label = marker
    tab.title = marker + " LinkedIn RPS login (1)"
    locator = LoginWindowLocator(
        "Codex", "linkedin_rps", 4321, "/tmp/profile", "http://127.0.0.1:9225",
        "target-exact", marker + " LinkedIn RPS login", tab.url, 180, "a" * 64, 3,
        _original_title="LinkedIn Talent Solutions",
        _marker=marker,
        _document_loader_id=tab.loader_id,
        _title_marker_applied=True,
    )

    result = cleanup_exact_login_presentation(
        tab,
        _ref(),
        locator,
        mutation_gate=lambda: None,
    )

    assert result["status"] == "cleanup_ok"
    assert tab.title == "LinkedIn Talent Solutions"
    assert marker not in tab.title


def test_handoff_cleanup_preserves_natural_title_change_but_clears_badge() -> None:
    tab = _PresentationTab()
    locator = present_exact_login_window_once(
        tab,
        _ref(),
        agent="Codex",
        episode_id="natural-title-change",
        mutation_gate=lambda: None,
        window_resolver=_window,
        window_capture=lambda _window_id: b"png",
        application_activator=lambda _pid: True,
    )
    tab.title = "LinkedIn Talent Solutions — updated by site"

    result = cleanup_exact_login_presentation(
        tab,
        _ref(),
        locator,
        mutation_gate=lambda: None,
    )

    assert result == {"status": "cleanup_ok", "cleanup_pending": False, "mutations": 1}
    assert tab.title == "LinkedIn Talent Solutions — updated by site"
    assert tab.busy_label == ""


def test_handoff_cleanup_uses_loader_identity_for_same_document_pushstate() -> None:
    tab = _PresentationTab()
    marker = "[LOGIN HERE][Codex][linkedin][target-exact]"
    original_url = tab.url
    tab.busy_label = marker
    tab.title = marker + " LinkedIn RPS login"
    tab.url = original_url + "?same-document=1"
    locator = LoginWindowLocator(
        "Codex", "linkedin_rps", 4321, "/tmp/profile", "http://127.0.0.1:9225",
        "target-exact", tab.title, original_url, 180, "a" * 64, 3,
        _original_title="LinkedIn Talent Solutions",
        _marker=marker,
        _document_loader_id=tab.loader_id,
        _badge_bound_url=original_url,
        _title_marker_applied=True,
    )

    result = cleanup_exact_login_presentation(
        tab,
        _ref(),
        locator,
        mutation_gate=lambda: None,
    )

    assert result["status"] == "cleanup_ok"
    assert tab.busy_label == ""
    assert tab.title == "LinkedIn Talent Solutions"
    assert tab.clear_busy_calls == [(tab.url, original_url)]


def test_keepalive_badge_cleanup_clears_same_document_pushstate_guardedly() -> None:
    tab = _PresentationTab()
    label = "[KEEPALIVE][Codex][linkedin][target-exact]"
    original_url = tab.url
    assert tab.mark_busy(label, expected_url=original_url) is True
    document_loader_id = tab.loader_id
    tab.url = "https://www.linkedin.com/talent/projects"
    gates: list[str] = []

    result = _cleanup_keepalive_badge(
        tab,
        _ref(),
        label,
        mutation_gate=lambda: gates.append("gate"),
        document_loader_id=document_loader_id,
        badge_bound_url=original_url,
    )

    assert result == {"status": "cleanup_ok", "cleanup_pending": False}
    assert gates == ["gate"]
    assert tab.busy_label == ""
    assert tab.clear_busy_calls == [(tab.url, original_url)]


def test_keepalive_badge_cleanup_skips_replaced_document_without_mutation() -> None:
    tab = _PresentationTab()
    label = "[KEEPALIVE][Codex][linkedin][target-exact]"
    original_url = tab.url
    assert tab.mark_busy(label, expected_url=original_url) is True
    document_loader_id = tab.loader_id
    tab.url = "https://www.linkedin.com/talent/projects"
    tab.loader_id = "loader-2"
    gates: list[str] = []

    result = _cleanup_keepalive_badge(
        tab,
        _ref(),
        label,
        mutation_gate=lambda: gates.append("gate"),
        document_loader_id=document_loader_id,
        badge_bound_url=original_url,
    )

    assert result == {
        "status": "cleanup_not_applicable_document_changed",
        "cleanup_pending": False,
    }
    assert gates == []
    assert tab.clear_busy_calls == []


def test_handoff_cleanup_never_mutates_a_new_document() -> None:
    tab = _PresentationTab()
    tab.url = "https://www.linkedin.com/talent/home?after-login=1"
    locator = LoginWindowLocator(
        "Codex", "linkedin_rps", 4321, "/tmp/profile", "http://127.0.0.1:9225",
        "target-exact", "login", "https://www.linkedin.com/login", 180, "a" * 64, 3,
    )
    gates: list[str] = []
    result = cleanup_exact_login_presentation(
        tab,
        _ref(),
        locator,
        mutation_gate=lambda: gates.append("gate"),
    )
    assert result["status"] == "cleanup_not_applicable_navigation_changed"
    assert gates == []
    assert tab.mutations == []


@pytest.mark.parametrize(
    "override",
    [
        {"target_id": "other"},
        {"dedicated_tab": False},
        {"clean_form": False},
        {"previously_opened_free": False},
        {"method": "POST"},
        {"target_attr": "_blank"},
        {"download": True},
        {"destination_url": "https://evil.example/steal"},
        {"destination_url": "https://www.linkedin.com/talent/logout"},
        {"destination_url": "https://www.linkedin.com/talent/inmail/send"},
        {"destination_url": "https://www.linkedin.com/talent/profile/new-candidate"},
        {"destination_url": "https://www.linkedin.com/talent/%6c%6f%67%6f%75%74"},
        {"destination_url": "https://www.linkedin.com/talent/%2573end"},
        {"risk_labels": ("paid",)},
        {"risk_labels": ("save",)},
        {"risk_labels": ("send",)},
        {"risk_labels": ("modal",)},
        {"risk_labels": ("new_candidate",)},
    ],
)
def test_unsafe_keepalive_candidate_never_mutates(override: dict[str, object]) -> None:
    tab = _KeepaliveTab()
    gates: list[str] = []
    result = execute_keepalive_roundtrip(
        tab,
        _ref(),
        _safe(**override),
        auth_probe=lambda _tab: pytest.fail("unsafe target must stop before auth probe"),
        mutation_gate=lambda: gates.append("gate"),
    )
    assert result["status"] == "skipped_unsafe"
    assert gates == []
    assert tab.trace == []
