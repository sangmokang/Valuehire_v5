"""브라우저 선택 SOT(단일 규칙 파일) + 검문소(fail-closed) 계약 테스트.

목적: "어떤 일에 어떤 브라우저를 쓰는가"를 SKILL 자연어에 흩뿌리지 않고
``browser_policy.json`` 한 장 + 결정론 함수로 강제한다. (CLAUDE.md SOT 불변식 1·2·5)

이 테스트가 단언하는 계약:
1. resolve_browser_target 은 규칙을 **파일에서 읽는다**(하드코딩 아님).
2. assert_browser_ready 는 붙은 브라우저가 규칙과 다르면 **멈춘다**(fail-closed).
3. 기존 resolve_chrome_cdp_endpoint 가 규칙 파일을 기본값 소스로 **배선**해
   쓴다(고아 방지). 우선순위: 명시값 > env > 규칙파일.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing.browser_policy import (
    DEFAULT_BROWSER_POLICY_PATH,
    BrowserPolicyViolation,
    assert_browser_ready,
    load_browser_policy,
    resolve_browser_target,
)


def _write_policy(tmp_path: Path, endpoint: str) -> Path:
    payload = {
        "portal_automation": {
            "tool": "playwright_cdp",
            "cdp_endpoint": endpoint,
            "attach_mode": "raw_single_tab",
            "never_kill": True,
            "yield_on_owner_activity": True,
        },
        "interactive_browsing": {
            "tool": "mcp_claude_in_chrome",
            "note": "사장님 화면 조작은 MCP 크롬으로",
        },
    }
    path = tmp_path / "browser_policy.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_default_policy_file_exists_and_loads() -> None:
    """저장소에 SOT 규칙 파일이 실제로 존재하고 파싱된다."""
    assert DEFAULT_BROWSER_POLICY_PATH.exists(), "browser_policy.json(SOT)이 없다"
    policy = load_browser_policy()
    assert "portal_automation" in policy
    assert "interactive_browsing" in policy


def test_resolve_target_reads_from_file_not_hardcoded(tmp_path: Path) -> None:
    """규칙을 파일에서 읽는다 — 임의 endpoint 를 넣으면 그대로 나와야 한다."""
    policy_path = _write_policy(tmp_path, "http://127.0.0.1:9999")
    policy = load_browser_policy(policy_path)
    target = resolve_browser_target("portal_automation", policy=policy)
    assert target["cdp_endpoint"] == "http://127.0.0.1:9999"
    assert target["tool"] == "playwright_cdp"
    assert target["attach_mode"] == "raw_single_tab"
    assert target["never_kill"] is True


def test_default_policy_portal_uses_9222_raw_single_tab() -> None:
    """SOT 기본값: 포털 자동작업 = 9222 크롬에 raw 단일탭, 안 끔."""
    target = resolve_browser_target("portal_automation")
    assert target["cdp_endpoint"] == "http://127.0.0.1:9222"
    assert target["attach_mode"] == "raw_single_tab"
    assert target["never_kill"] is True


def test_interactive_uses_mcp_chrome() -> None:
    """SOT: 사장님 화면 조작은 MCP 크롬."""
    target = resolve_browser_target("interactive_browsing")
    assert target["tool"] == "mcp_claude_in_chrome"


def test_unknown_action_is_fail_closed() -> None:
    """규칙에 없는 작업명은 추측하지 않고 멈춘다."""
    with pytest.raises(BrowserPolicyViolation):
        resolve_browser_target("nonexistent_action")


def test_assert_browser_ready_blocks_on_mismatch(tmp_path: Path) -> None:
    """검문소: 붙은 브라우저가 규칙과 다르면 멈춘다(fail-closed)."""
    policy = load_browser_policy(_write_policy(tmp_path, "http://127.0.0.1:9222"))
    with pytest.raises(BrowserPolicyViolation):
        assert_browser_ready(
            "portal_automation",
            connected_endpoint="http://127.0.0.1:9333",
            policy=policy,
        )


def test_assert_browser_ready_passes_on_match(tmp_path: Path) -> None:
    """검문소: 규칙과 같은 브라우저면 통과(예외 없음)."""
    policy = load_browser_policy(_write_policy(tmp_path, "http://127.0.0.1:9222"))
    assert_browser_ready(
        "portal_automation",
        connected_endpoint="http://127.0.0.1:9222",
        policy=policy,
    )


def test_resolve_chrome_cdp_endpoint_wired_to_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """배선: resolve_chrome_cdp_endpoint 가 규칙 파일을 **실제로 읽는다**(하드코딩 아님).

    규칙 파일을 9999 로 바꿔치기 → resolve 가 9999 를 돌려줘야 진짜 파일을 읽는 것.
    (기본 9222 로 검증하면 하드코딩과 구분 안 됨 = 가짜 GREEN.)
    우선순위: 명시값 > env > 규칙파일.
    """
    from tools.multi_position_sourcing import browser_policy as bp
    from tools.multi_position_sourcing.portal_worker import (
        CHROME_CDP_ENDPOINT_ENV,
        resolve_chrome_cdp_endpoint,
    )

    fake_policy = _write_policy(tmp_path, "http://127.0.0.1:9999")
    monkeypatch.setattr(bp, "DEFAULT_BROWSER_POLICY_PATH", fake_policy)
    monkeypatch.delenv(CHROME_CDP_ENDPOINT_ENV, raising=False)

    # env 없음 → 규칙파일 값(9999) — 하드코딩 9222 가 아님을 증명
    assert resolve_chrome_cdp_endpoint() == "http://127.0.0.1:9999"
    # 명시값이 최우선
    assert resolve_chrome_cdp_endpoint("http://127.0.0.1:8123") == "http://127.0.0.1:8123"
    # env 가 규칙파일보다 우선
    monkeypatch.setenv(CHROME_CDP_ENDPOINT_ENV, "http://127.0.0.1:7000")
    assert resolve_chrome_cdp_endpoint() == "http://127.0.0.1:7000"


def test_resolve_chrome_cdp_endpoint_warns_on_missing_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """규칙 파일이 없으면 조용히 넘어가지 않고 시끄럽게 경고한 뒤 폴백한다."""
    from tools.multi_position_sourcing import browser_policy as bp
    from tools.multi_position_sourcing.portal_worker import (
        CHROME_CDP_ENDPOINT_ENV,
        DEFAULT_CHROME_CDP_ENDPOINT,
        resolve_chrome_cdp_endpoint,
    )

    monkeypatch.setattr(bp, "DEFAULT_BROWSER_POLICY_PATH", tmp_path / "missing.json")
    monkeypatch.delenv(CHROME_CDP_ENDPOINT_ENV, raising=False)
    with pytest.warns(RuntimeWarning):
        assert resolve_chrome_cdp_endpoint() == DEFAULT_CHROME_CDP_ENDPOINT


def test_worker_attach_blocked_when_endpoint_mismatches_policy(tmp_path: Path) -> None:
    """배선 증명(고아 아님): 워커가 규칙과 다른 CDP 주소로 붙으려 하면
    connect_over_cdp 에 닿기 전에 검문소가 멈춘다(fail-closed)."""
    import asyncio

    from tools.multi_position_sourcing.portal_worker import (
        PortalWorker,
        PortalWorkerConfig,
    )

    class _FakeChromium:
        async def connect_over_cdp(self, *_a: object, **_k: object) -> object:
            raise AssertionError("검문소를 통과해 connect 에 닿으면 안 된다")

    class _FakePlaywright:
        chromium = _FakeChromium()

    # 규칙 SOT 는 9222. 일부러 7777 로 어긋난 주소를 준다 → 막혀야 한다.
    config = PortalWorkerConfig(
        channel="linkedin_rps",
        profile_root=tmp_path,
        chrome_cdp_endpoint="http://127.0.0.1:7777",
    )
    worker = PortalWorker(config, playwright=_FakePlaywright())
    with pytest.raises(BrowserPolicyViolation):
        asyncio.run(worker.start())
