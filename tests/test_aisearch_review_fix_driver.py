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


def test_f1_human_input_during_detail_fetch_reaches_next_poll():
    # 첫 스냅샷(상세 진입 시 차단 프로브)에서 사람 입력 1건이 관측된다.
    t = _Transport(snapshots=[{"h": 3}])
    driver = _driver(t)

    driver.fetch_detail_page("saramin", "https://fake.test/p/1")

    events = driver.poll_events()
    assert any(e.get("type") == "human_input" for e in events), (
        "상세 열람 중 감지된 사람 입력이 사라졌다 — 모니터가 개입을 알 수 없다"
    )


def test_f1_human_input_is_delivered_only_once():
    t = _Transport(snapshots=[{"h": 3}])
    driver = _driver(t)
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


def test_m1_list_page_human_input_is_preserved_too():
    t = _Transport(snapshots=[{"h": 2}])
    driver = _driver(t)
    driver.fetch_list_page("saramin", 1, {"channel": "saramin", "url": "https://x", "steps": []})

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
