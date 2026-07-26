"""Bounded WinPC portal helper contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tools.multi_position_sourcing import winpc_local_portal


def test_keywords_reject_shell_controls_and_keep_safe_portal_terms() -> None:
    assert winpc_local_portal._normalize_keywords(
        [" 백엔드   Spring Boot ", "C++", "Node.js"]
    ) == ("백엔드 Spring Boot", "C++", "Node.js")

    for value in ("backend; whoami", "$(whoami)", "backend`whoami", "a|b", 'a"b'):
        with pytest.raises(ValueError, match="unsafe"):
            winpc_local_portal._normalize_keywords([value])


def test_probe_uses_exact_registered_target_and_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab = SimpleNamespace(closed=False)
    tab.close = lambda: setattr(tab, "closed", True)
    monkeypatch.setattr(winpc_local_portal.os, "environ", {})
    monkeypatch.setattr(
        winpc_local_portal,
        "winpc_environment",
        lambda environ: {"VALUEHIRE_MACHINE": "winpc", "SARAMIN_PORT": "9423"},
    )
    monkeypatch.setattr(
        winpc_local_portal,
        "resolve_existing_target",
        lambda channel: SimpleNamespace(
            target_id="target-1",
            initial_url=(
                "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
            ),
            websocket_url="ws://127.0.0.1:9423/devtools/page/target-1",
        ),
    )
    monkeypatch.setattr(
        winpc_local_portal,
        "_attach_exact_ref",
        lambda ref, *, badge: tab,
    )
    monkeypatch.setattr(
        winpc_local_portal,
        "read_auth_observation",
        lambda _tab, _channel: SimpleNamespace(
            auth_conflict=False,
            challenge=False,
            authenticated=True,
            url="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            proof_names=("logout-control",),
        ),
    )

    result = winpc_local_portal.probe_local_channel(
        "saramin",
        job_id="218",
        environ={},
        system_name="Windows",
    )

    assert result["status"] == "ready"
    assert result["target_id"] == "target-1"
    assert result["browser_preserved"] is True
    assert tab.closed is True


def test_search_wrapper_activates_winpc_and_returns_async_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(winpc_local_portal.os, "environ", {})
    monkeypatch.setattr(
        winpc_local_portal,
        "winpc_environment",
        lambda environ: {"VALUEHIRE_MACHINE": "winpc", "SARAMIN_PORT": "9423"},
    )
    seen: dict[str, object] = {}

    async def run(channel, keywords, *, job_id, sleep=None):
        seen.update(channel=channel, keywords=keywords, job_id=job_id)
        return {"status": "done", "browser_preserved": True}

    monkeypatch.setattr(winpc_local_portal, "_run_portal_search", run)

    result = winpc_local_portal.run_local_portal_search(
        "saramin",
        ["백엔드", "Spring Boot"],
        job_id="218",
        environ={},
        system_name="Windows",
    )

    assert result == {"status": "done", "browser_preserved": True}
    assert seen == {
        "channel": "saramin",
        "keywords": ("백엔드", "Spring Boot"),
        "job_id": "218",
    }


def test_local_monitor_ignores_asset_403_and_dom_evidence_verifies_query() -> None:
    monitor = winpc_local_portal._DomVerifiedLivenessMonitor("saramin")
    monitor._handle_response(SimpleNamespace(status=403, url="https://asset.example"))
    assert monitor.reauth_cause == ""

    class Locator:
        def __init__(self, text, count=1):
            self.text = text
            self._count = count

        @property
        def first(self):
            return self

        async def count(self):
            return self._count

        async def inner_text(self):
            return self.text

    class Page:
        def locator(self, selector):
            if selector == "body":
                return Locator("Node.js 검색 결과 총 1,234명")
            if selector == "span.list_count":
                return Locator("총 1,234명")
            return Locator("", count=0)

    evidence = asyncio.run(
        winpc_local_portal._read_search_evidence(Page(), "saramin", "Node.js")
    )
    assert evidence == (True, True, 1234)


def test_saramin_pagination_selects_the_next_number_before_group_next() -> None:
    class Locator:
        @property
        def first(self):
            return self

        async def count(self):
            return 1

        async def is_visible(self):
            return True

        async def inner_text(self):
            return "2"

        async def get_attribute(self, _name):
            return None

    class Page:
        def __init__(self):
            self.selectors = []

        def locator(self, selector):
            self.selectors.append(selector)
            return Locator()

    page = Page()
    locator = asyncio.run(
        winpc_local_portal._next_page_locator(
            page,
            "saramin",
            next_page_number=2,
        )
    )
    assert locator is not None
    assert page.selectors == ['.PageBox button:has-text("2")']


def test_pagination_rejects_link_outside_protected_surface() -> None:
    class Page:
        async def current_url(self):
            return "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"

        async def goto(self, *_args, **_kwargs):
            raise AssertionError("unsafe navigation must not run")

    class Locator:
        async def get_attribute(self, name):
            assert name == "href"
            return "https://example.com/next"

    with pytest.raises(RuntimeError, match="protected search surface"):
        asyncio.run(winpc_local_portal._advance_page(Page(), Locator(), "saramin"))
