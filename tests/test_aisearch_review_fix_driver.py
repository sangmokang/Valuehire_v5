"""2026-07-31 전수 리뷰 — M1 저장 직전 차단 프로브 · M4 건수 파싱 · F1 개입 신호 (U8/U11/U14).

goal: docs/engineering/aisearch-review-fix-goal-2026-07-31.md

- F1(HIGH): fetch_detail_page 가 poll_events() 를 부르고 signal 만 쓰고 human_input
  을 버렸다. poll_events() 는 워터마크를 전진시키는 **상태 변경 함수**라, 버려진
  사람 입력은 오케스트레이터 모니터에 영영 도달하지 못한다 — 상세 열람 중
  사장님 개입이 자동 조작을 멈추지 못했다(SOT 불변식 2 위반).
- M1: 목록 페이지도 캡처 직전에 차단 신호를 재확인해야 한다(캡차 화면 HTML 이
  데이터로 저장되면 안 된다).
- M4: RPS 결과건수를 여러 숫자가 섞인 텍스트에서 이어붙여 읽었다.
"""
from __future__ import annotations

import pytest

from apps.aisearch.core.cdp_driver import CdpDriver, CdpDriverError, DetailPageBlocked


class _Transport:
    """스냅샷·본문을 제어할 수 있는 페이크 — 실 브라우저 0."""

    def __init__(self, *, snapshots=None, count_text="1,234명"):
        self.calls: list[tuple[str, dict]] = []
        self.snapshots = list(snapshots or [])
        self.count_text = count_text
        self.checked = False

    def _snapshot(self):
        base = {
            "h": 0,
            "present": True,
            "captcha": False,
            "cloudflare": False,
            "twofa": False,
            "checkpoint": False,
            "multisession": False,
        }
        if self.snapshots:
            base.update(self.snapshots.pop(0))
        return base

    def __call__(self, method: str, params: dict) -> dict:
        self.calls.append((method, dict(params)))
        if method == "Page.navigate":
            return {"frameId": "F1"}
        if method.startswith("Input."):
            return {}
        expr = params.get("expression", "")
        value: object = True
        if "/*vh:ready*/" in expr:
            value = "complete"
        elif "/*vh:rect*/" in expr:
            value = {"x": 1.0, "y": 1.0}
        elif "/*vh:checked*/" in expr:
            value = self.checked
        elif "/*vh:count*/" in expr:
            value = self.count_text
        elif "/*vh:html*/" in expr:
            value = "<html>본문</html>"
        elif "/*vh:url*/" in expr:
            value = "https://fake.test/list"
        elif "/*vh:detail_refs*/" in expr:
            value = []
        elif "/*vh:has_next*/" in expr:
            value = False
        elif "/*vh:snapshot*/" in expr:
            value = self._snapshot()
        return {"result": {"value": value}}

    def captured_html_count(self) -> int:
        return sum(1 for m, p in self.calls if "/*vh:html*/" in p.get("expression", ""))


def _driver(transport) -> CdpDriver:
    return CdpDriver(transport, sleep=lambda s: None)


# ── F1 — 상세 열람 중 사람 입력이 유실되지 않는다 ─────────────────────────


def test_f1_human_input_during_detail_fetch_stops_and_reports():
    """V1 3차 계약 — 사람 입력을 보면 캡처·복귀 없이 그 자리에서 멈춘다."""
    from apps.aisearch.core.cdp_driver import HumanInterventionDetected

    t = _Transport(snapshots=[{"h": 3}])
    driver = _driver(t)

    with pytest.raises(HumanInterventionDetected) as exc:
        driver.fetch_detail_page("saramin", "https://fake.test/p/1")

    assert any(e.get("type") == "human_input" for e in exc.value.events)
    assert t.captured_html_count() == 0, "개입을 본 뒤에도 화면을 캡처했다"


def test_f1_human_input_is_delivered_only_once():
    from apps.aisearch.core.cdp_driver import HumanInterventionDetected

    t = _Transport(snapshots=[{"h": 3}])
    driver = _driver(t)
    with pytest.raises(HumanInterventionDetected):
        driver.fetch_detail_page("saramin", "https://fake.test/p/1")

    first = driver.poll_events()
    second = driver.poll_events()

    assert sum(1 for e in first if e.get("type") == "human_input") == 1
    assert not any(e.get("type") == "human_input" for e in second), "같은 입력이 두 번 보고됐다"


def test_f1_detail_block_signal_still_raises():
    t = _Transport(snapshots=[{"captcha": True}])
    with pytest.raises(DetailPageBlocked):
        _driver(t).fetch_detail_page("saramin", "https://fake.test/p/1")


# ── M1 — 목록 페이지도 저장 직전에 차단을 재확인한다 ───────────────────────


def test_m1_list_page_blocked_does_not_capture_html():
    t = _Transport(snapshots=[{"captcha": True}])
    driver = _driver(t)

    with pytest.raises(DetailPageBlocked):
        driver.fetch_list_page("saramin", 1, {"channel": "saramin", "url": "https://x", "steps": []})

    assert t.captured_html_count() == 0, "차단 화면 HTML 이 캡처(=저장 대상)됐다"


def test_m1_clean_list_page_is_captured():
    t = _Transport()
    page = _driver(t).fetch_list_page(
        "saramin", 1, {"channel": "saramin", "url": "https://x", "steps": []}
    )
    assert page["content"] == "<html>본문</html>"
    assert page["has_next"] is False


def test_m1_list_page_human_input_stops_and_is_preserved():
    from apps.aisearch.core.cdp_driver import HumanInterventionDetected

    t = _Transport(snapshots=[{"h": 2}])
    driver = _driver(t)
    with pytest.raises(HumanInterventionDetected):
        driver.fetch_list_page(
            "saramin", 1, {"channel": "saramin", "url": "https://x", "steps": []}
        )

    assert any(e.get("type") == "human_input" for e in driver.poll_events())


# ── M4 — RPS 결과건수 파싱 ────────────────────────────────────────────────


def test_m4_single_count_is_parsed():
    assert _driver(_Transport(count_text="1,234명")).run_rps_search("engineer") == 1234
    assert _driver(_Transport(count_text="총 42 명")).run_rps_search("engineer") == 42


def test_m4_multiple_numbers_fail_explicitly_instead_of_concatenating():
    """counter-AC: '1,234명 중 20명 표시' 를 123420 으로 이어붙이지 않는다."""
    driver = _driver(_Transport(count_text="1,234명 중 20명 표시"))
    with pytest.raises(CdpDriverError) as exc:
        driver.run_rps_search("engineer")
    assert "건수" in str(exc.value)


def test_m4_no_digits_fail_closed():
    with pytest.raises(CdpDriverError):
        _driver(_Transport(count_text="결과 없음")).run_rps_search("engineer")


def test_m4_repeated_same_number_is_not_ambiguous():
    # 같은 수가 두 번 보이는 표기(예: "1,234명 (1,234)")는 모호하지 않다.
    assert _driver(_Transport(count_text="1,234명 (1,234)")).run_rps_search("e") == 1234


# ── 자체 적대검증 — 목록 페이지 차단도 '차단'으로 보고돼야 한다 ─────────────


def test_list_page_block_is_reported_as_blocked_and_alerts():
    """M1 이 만든 목록 차단이 aborted 로 새어나가면 캡차 알림이 안 나간다.

    상세 페이지 차단과 **같은 계약**이어야 한다: 모니터에 신호 공급 → BLOCKED →
    Discord 알림. 예전에는 목록 차단 예외를 아무도 받아주지 않아 E8 abort 로
    떨어졌고, 사장님은 캡차가 떴다는 사실조차 통보받지 못했다.
    """
    from apps.aisearch.core.orchestrator import run_search_pipeline
    from tests.test_aisearch_orchestrator import Harness, _jd
    from apps.aisearch.core.cdp_driver import DetailPageBlocked

    h = Harness(pages=1)

    def block_on_list(channel: str, page: int) -> None:
        raise DetailPageBlocked([{"type": "signal", "kind": "captcha"}])

    h.list_side_effect = block_on_list

    report = run_search_pipeline(_jd(), h.deps())

    assert report.status == "blocked", f"목록 차단이 blocked 로 보고되지 않았다: {report.status}"
    assert any("captcha" in m for m in h.notifier.messages), (
        "목록 차단인데 차단 알림이 나가지 않았다"
    )
