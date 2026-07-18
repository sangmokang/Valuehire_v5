"""Exact target, HUMAN_AUTH, click/Back keepalive의 실행 계약."""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing.session_guard import (
    AuthObservation,
    BrowserTargetRef,
    SafeKeepaliveTarget,
    execute_keepalive_roundtrip,
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
        "webSocketDebuggerUrl": "ws://wrong",
    }
    exact = {
        "id": "target-exact",
        "type": "page",
        "url": "https://www.linkedin.com/talent/home",
        "webSocketDebuggerUrl": "ws://exact",
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
    assert ref.websocket_url == "ws://exact"
    assert calls == ["http://127.0.0.1:9225"]

    with pytest.raises(LookupError):
        resolve_existing_target(
            "linkedin_rps",
            managed_endpoint_resolver=lambda _site: "http://127.0.0.1:9225",
            list_pages=lambda endpoint: [wrong, exact],
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
        self.url = "https://www.linkedin.com/talent/home"
        self.trace: list[str] = []
        self.forbidden_calls: list[str] = []

    def send(self, method: str, params: dict | None = None):
        if method == "Page.getNavigationHistory":
            self.trace.append("history")
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

