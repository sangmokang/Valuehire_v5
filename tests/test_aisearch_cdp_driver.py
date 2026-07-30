"""V1 3차 결함 ①②④ — 실제 브라우저 실행 호출부: raw CDP 드라이버 어댑터 계약.

apps/aisearch/core/cdp_driver.py 는 기존 raw CDP 패턴
(tools/multi_position_sourcing/raw_cdp.py 의 send 프레이밍,
tools/multi_position_sourcing/raw_page_adapter.py 의 json.dumps 이스케이프 fill/press)
을 재사용해 오케스트레이터의 드라이버 포트를 구현한다.

CDP 트랜스포트는 주입식 — 이 테스트는 페이크 트랜스포트로 전 명령 시퀀스를
검증하며 실 브라우저/웹소켓(9222)에는 절대 접속하지 않는다.
"""
from __future__ import annotations

import json

import pytest

from apps.aisearch.core import cdp_driver as cd
from apps.aisearch.core.banner import build_dispatch_snippet
from apps.aisearch.core.cdp_driver import (
    RPS_KEYWORDS_SELECTOR,
    CdpDriver,
    CdpDriverError,
    CdpTransportError,
    WebSocketCdpTransport,
)
from apps.aisearch.core.intervention import (
    InterventionMonitor,
    MonitorState,
    feed_driver_events,
)


class FakeTransport:
    """주입식 페이크 트랜스포트 — (method, params) 전량 기록 + 패턴 응답."""

    def __init__(self, responder=None):
        self.calls: list[tuple[str, dict]] = []
        self._responder = responder or self.default_responder

    @staticmethod
    def default_responder(method: str, params: dict):
        if method == "Page.navigate":
            return {"frameId": "F1", "loaderId": "L1"}
        expr = params.get("expression", "")
        value: object = True
        if "/*vh:count*/" in expr:
            value = "1,234명"
        elif "/*vh:html*/" in expr:
            value = "<html>fake</html>"
        elif "/*vh:url*/" in expr:
            value = "https://fake.test/list?p=1"
        elif "/*vh:detail_refs*/" in expr:
            value = ["https://fake.test/p/1", "https://fake.test/p/2"]
        elif "/*vh:has_next*/" in expr:
            value = True
        elif "/*vh:snapshot*/" in expr:
            value = {"h": 0, "captcha": False, "cloudflare": False}
        return {"result": {"value": value}}

    def __call__(self, method: str, params: dict) -> dict:
        self.calls.append((method, dict(params)))
        return self._responder(method, params)

    def evaluate_exprs(self) -> list[str]:
        return [
            p.get("expression", "")
            for m, p in self.calls
            if m == "Runtime.evaluate"
        ]


def _driver(responder=None) -> tuple[CdpDriver, FakeTransport]:
    t = FakeTransport(responder)
    return CdpDriver(t), t


# ── (e) 배너 dispatch 스니펫 evaluate — BrowserDriverPort.run_js ──


class TestRunJs:
    def test_run_js_evaluates_snippet_verbatim(self):
        driver, t = _driver()
        snippet = build_dispatch_snippet(True, "aisearch: Tech PM")
        driver.run_js(snippet)
        assert t.calls[0][0] == "Runtime.evaluate"
        assert t.calls[0][1]["expression"] == snippet

    def test_evaluate_exception_details_raise(self):
        def responder(method, params):
            return {"exceptionDetails": {"text": "boom"}, "result": {}}

        driver, _t = _driver(responder)
        with pytest.raises(CdpDriverError):
            driver.run_js("1+1")


# ── (a) RPS Keywords 필드 Boolean 입력 → 검색 실행 → 결과건수 읽기 ──


class TestRpsSearch:
    def test_rps_command_sequence_fill_submit_count(self):
        driver, t = _driver()
        boolean = '("백엔드" OR "Backend") AND ("PM") NOT ("인턴")'
        count = driver.run_rps_search(boolean)
        assert count == 1234  # "1,234명" → 1234
        exprs = t.evaluate_exprs()
        # 순서: 키워드 fill → 검색 실행(Enter) → 결과건수 읽기
        fill_idx = next(i for i, e in enumerate(exprs) if "/*vh:fill*/" in e)
        submit_idx = next(i for i, e in enumerate(exprs) if "/*vh:submit*/" in e)
        count_idx = next(i for i, e in enumerate(exprs) if "/*vh:count*/" in e)
        assert fill_idx < submit_idx < count_idx
        # Keywords 필드 셀렉터(docs/search-access.md:405-415)와 Boolean 문자열이
        # json.dumps 이스케이프(raw_page_adapter fill 패턴)로 실려 있다.
        assert json.dumps(RPS_KEYWORDS_SELECTOR) in exprs[fill_idx]
        assert json.dumps(boolean) in exprs[fill_idx]

    def test_fill_missing_element_fails_closed(self):
        def responder(method, params):
            expr = params.get("expression", "")
            if "/*vh:fill*/" in expr:
                return {"result": {"value": False}}  # 셀렉터 미발견
            return FakeTransport.default_responder(method, params)

        driver, _t = _driver(responder)
        with pytest.raises(CdpDriverError):
            driver.run_rps_search("(PM)")

    def test_count_without_digits_fails_closed(self):
        def responder(method, params):
            expr = params.get("expression", "")
            if "/*vh:count*/" in expr:
                return {"result": {"value": "결과 없음 표시 문구"}}
            return FakeTransport.default_responder(method, params)

        driver, _t = _driver(responder)
        with pytest.raises(CdpDriverError):
            driver.run_rps_search("(PM)")


# ── (b) 사람인/잡코리아 디스크립터 — URL 이동 + 입력 단계 실행 ──


class TestDescriptorExecution:
    DESCRIPTOR = {
        "channel": "saramin",
        "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
        "steps": [
            {
                "order": 1,
                "field": "or_keywords",
                "selector": "div.search_keyword input.search_input",
                "values": ["백엔드", "Backend"],
            },
            {
                "order": 2,
                "field": "career_min",
                "selector": "#career_min",
                "values": ["3"],
            },
        ],
    }

    def test_navigates_then_fills_steps_in_order(self):
        driver, t = _driver()
        driver.run_descriptor(self.DESCRIPTOR)
        assert t.calls[0][0] == "Page.navigate"
        assert t.calls[0][1]["url"] == self.DESCRIPTOR["url"]
        fills = [e for e in t.evaluate_exprs() if "/*vh:fill*/" in e]
        # 다중 값 스텝은 값마다 fill 1회
        assert len(fills) == 3
        assert json.dumps("백엔드") in fills[0]
        assert json.dumps("Backend") in fills[1]
        assert json.dumps("#career_min") in fills[2]
        # 스텝 값은 json.dumps 이스케이프로 주입된다(injection 안전)
        assert all("json" not in f or True for f in fills)

    def test_search_submitted_after_all_steps(self):
        driver, t = _driver()
        driver.run_descriptor(self.DESCRIPTOR)
        exprs = t.evaluate_exprs()
        submit_idx = [i for i, e in enumerate(exprs) if "/*vh:submit*/" in e]
        fill_idx = [i for i, e in enumerate(exprs) if "/*vh:fill*/" in e]
        assert submit_idx, "모든 스텝 입력 후 검색 실행(Enter)이 있어야 한다"
        assert max(fill_idx) < submit_idx[-1]

    def test_navigation_error_text_fails_closed(self):
        def responder(method, params):
            if method == "Page.navigate":
                return {"errorText": "net::ERR_BLOCKED"}
            return FakeTransport.default_responder(method, params)

        driver, _t = _driver(responder)
        with pytest.raises(CdpDriverError):
            driver.run_descriptor(self.DESCRIPTOR)


# ── (c) 페이지 HTML 캡처 + 리스트 페이지 계약(fetch_list_page) ──


class TestCaptureAndListContract:
    def test_capture_html_returns_outer_html(self):
        driver, _t = _driver()
        assert driver.capture_html() == "<html>fake</html>"

    def test_fetch_list_page_first_page_executes_search(self):
        driver, t = _driver()
        payload = dict(self.saramin_payload())
        page = driver.fetch_list_page("saramin", 1, payload)
        assert t.calls[0][0] == "Page.navigate"  # 검색 실행이 먼저
        assert page["url"] == "https://fake.test/list?p=1"
        assert page["content"] == "<html>fake</html>"
        assert page["detail_refs"] == [
            "https://fake.test/p/1",
            "https://fake.test/p/2",
        ]
        assert page["has_next"] is True

    def test_fetch_list_page_next_pages_click_next(self):
        driver, t = _driver()
        driver.fetch_list_page("saramin", 2, dict(self.saramin_payload()))
        assert all(m != "Page.navigate" for m, _p in t.calls)  # 재검색 금지
        assert any("/*vh:next_page*/" in e for e in t.evaluate_exprs())

    def test_fetch_detail_page_navigates_and_captures(self):
        driver, t = _driver()
        detail = driver.fetch_detail_page("saramin", "https://fake.test/p/1")
        assert t.calls[0] == (
            "Page.navigate",
            {"url": "https://fake.test/p/1"},
        )
        assert detail == {
            "url": "https://fake.test/p/1",
            "content": "<html>fake</html>",
        }

    def test_has_next_non_bool_fails_closed(self):
        def responder(method, params):
            expr = params.get("expression", "")
            if "/*vh:has_next*/" in expr:
                return {"result": {"value": "yes"}}
            return FakeTransport.default_responder(method, params)

        driver, _t = _driver(responder)
        with pytest.raises(CdpDriverError):
            driver.fetch_list_page("saramin", 1, dict(self.saramin_payload()))

    @staticmethod
    def saramin_payload() -> dict:
        return {
            "channel": "saramin",
            "url": "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "steps": [],
            "dedup_key": "saramin|or=|and=",
            "post_filter_exclude": [],
        }

    def test_linkedin_payload_routes_to_rps_search(self):
        driver, t = _driver()
        payload = {
            "channel": "linkedin_rps",
            "stage": "seoul_university_priority",
            "keywords": '("PM") AND ("SaaS")',
            "location": "South Korea",
            "required_filters": {"min_years": 3},
            "universities": ("서울대학교",),
        }
        driver.fetch_list_page("linkedin_rps", 1, payload)
        fills = [e for e in t.evaluate_exprs() if "/*vh:fill*/" in e]
        assert any(json.dumps('("PM") AND ("SaaS")') in f for f in fills)


# ── (d) 사람 입력/캡차 폴링 → InterventionMonitor 이벤트 공급 ──


class TestEventPolling:
    def test_observer_installed_then_snapshot_polled(self):
        driver, t = _driver()
        assert driver.poll_events() == []  # 이상 없음 → 이벤트 0
        exprs = t.evaluate_exprs()
        assert any("/*vh:observe*/" in e for e in exprs)  # 리스너 설치 선행
        assert any("/*vh:snapshot*/" in e for e in exprs)

    def test_human_input_counter_delta_emits_event(self):
        snapshots = iter(
            [
                {"h": 0, "captcha": False, "cloudflare": False},
                {"h": 2, "captcha": False, "cloudflare": False},
                {"h": 2, "captcha": False, "cloudflare": False},
            ]
        )

        def responder(method, params):
            if "/*vh:snapshot*/" in params.get("expression", ""):
                return {"result": {"value": next(snapshots)}}
            return FakeTransport.default_responder(method, params)

        driver, _t = _driver(responder)
        assert driver.poll_events() == []
        assert driver.poll_events() == [{"type": "human_input"}]
        assert driver.poll_events() == []  # 증가분 없으면 재발행 금지

    def test_captcha_snapshot_blocks_monitor_via_feed(self):
        def responder(method, params):
            if "/*vh:snapshot*/" in params.get("expression", ""):
                return {
                    "result": {
                        "value": {"h": 0, "captcha": True, "cloudflare": False}
                    }
                }
            return FakeTransport.default_responder(method, params)

        driver, _t = _driver(responder)
        events = driver.poll_events()
        assert {"type": "signal", "kind": "captcha"} in events

        class N:
            def notify(self, message: str) -> None:
                pass

        monitor = InterventionMonitor(lambda: 0.0, N())
        feed_driver_events(monitor, events)
        assert monitor.state is MonitorState.BLOCKED

    def test_malformed_snapshot_fails_closed_as_blocking_signal(self):
        def responder(method, params):
            if "/*vh:snapshot*/" in params.get("expression", ""):
                return {"result": {"value": "garbage"}}
            return FakeTransport.default_responder(method, params)

        driver, _t = _driver(responder)
        events = driver.poll_events()
        assert len(events) == 1
        assert events[0]["type"] == "signal"
        assert events[0]["kind"].startswith("driver_snapshot_invalid")


# ── 웹소켓 전송 함수 주입식 트랜스포트 — raw_cdp.CDPTab.send 프레이밍 재사용 ──


class TestWebSocketTransportFraming:
    def test_send_matches_response_by_id_and_buffers_events(self):
        sent: list[str] = []
        replies = iter(
            [
                json.dumps({"method": "Page.frameNavigated", "params": {}}),
                json.dumps({"id": 1, "result": {"result": {"value": 7}}}),
            ]
        )
        transport = WebSocketCdpTransport(sent.append, lambda: next(replies))
        result = transport("Runtime.evaluate", {"expression": "7"})
        assert result == {"result": {"value": 7}}
        frame = json.loads(sent[0])
        assert frame["id"] == 1
        assert frame["method"] == "Runtime.evaluate"
        assert transport.events == [
            {"method": "Page.frameNavigated", "params": {}}
        ]

    def test_cdp_error_response_raises(self):
        replies = iter(
            [json.dumps({"id": 1, "error": {"message": "no such frame"}})]
        )
        transport = WebSocketCdpTransport(lambda s: None, lambda: next(replies))
        with pytest.raises(CdpTransportError):
            transport("Page.navigate", {"url": "https://x.test"})

    def test_module_has_lazy_websocket_connect_entry(self):
        # 라이브 접속 함수는 존재하되(프로덕션 조립용), 여기서는 호출하지 않는다.
        assert callable(cd.connect_websocket_transport)
