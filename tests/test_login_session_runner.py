"""Exact target, HUMAN_AUTH, click/Back keepalive의 실행 계약."""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing.session_guard import (
    AuthObservation,
    BrowserTargetRef,
    ManagedBrowserProcess,
    SafeKeepaliveTarget,
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
  222 /Applications/Chrome --remote-debugging-port=9225 '--user-data-dir=/tmp/LinkedIn Profile'
  223 /Applications/Chrome --type=renderer --remote-debugging-port=9225 '--user-data-dir=/tmp/LinkedIn Profile'
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
        "history",
        "gate2",
        "back:42",
        "url:home",
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
            raise RuntimeError("owner active")

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
