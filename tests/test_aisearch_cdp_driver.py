"""V1 3차 결함 ①②④(+4차 ①②④⑩) — raw CDP 드라이버 어댑터 계약.

apps/aisearch/core/cdp_driver.py 는 기존 raw CDP 패턴(raw_cdp.py 의 send
프레이밍, json.dumps 이스케이프)을 재사용해 오케스트레이터의 드라이버 포트를
구현한다. V1 4차 수정으로 텍스트 입력은 CDP Input 도메인(Input.insertText /
Input.dispatchKeyEvent) 신뢰 입력이며, 모든 이동 후 로드 완료 대기가 있다.

CDP 트랜스포트는 주입식 — 이 테스트는 페이크 트랜스포트로 전 명령 시퀀스를
검증하며 실 브라우저/웹소켓(9222)에는 절대 접속하지 않는다(실 sleep 0).
"""
from __future__ import annotations

import json
import re

import pytest

from apps.aisearch.core import cdp_driver as cd
from apps.aisearch.core.banner import build_dispatch_snippet
from apps.aisearch.core.cdp_driver import (
    RPS_KEYWORDS_SELECTOR,
    CdpDriver,
    CdpDriverError,
    CdpTransportError,
    DETAIL_LINK_SELECTORS,
    WebSocketCdpTransport,
)
from apps.aisearch.core.intervention import (
    InterventionMonitor,
    MonitorState,
    feed_driver_events,
)


class FakeTransport:
    """주입식 페이크 트랜스포트 — (method, params) 전량 기록 + 패턴 응답."""

    SNAPSHOT = {
        "h": 0,
        "captcha": False,
        "cloudflare": False,
        "twofa": False,
        "checkpoint": False,
        "multisession": False,
        "present": True,
    }

    def __init__(self, responder=None):
        self.calls: list[tuple[str, dict]] = []
        self._responder = responder or self.default_responder

    @staticmethod
    def default_responder(method: str, params: dict):
        if method == "Page.navigate":
            return {"frameId": "F1", "loaderId": "L1"}
        if method.startswith("Input."):
            return {}
        expr = params.get("expression", "")
        value: object = True
        if "/*vh:ready*/" in expr:
            value = "complete"
        elif "/*vh:rect*/" in expr:
            value = {"x": 120.0, "y": 48.0}
        elif "/*vh:count*/" in expr:
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
            value = dict(FakeTransport.SNAPSHOT)
        elif "/*vh:reset_rect*/" in expr:
            value = None  # 기본: 화면에 초기화 컨트롤 없음(최초 실행처럼)
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

    def inserted_texts(self) -> list[str]:
        return [p["text"] for m, p in self.calls if m == "Input.insertText"]

    def enter_key_events(self) -> list[dict]:
        return [
            p
            for m, p in self.calls
            if m == "Input.dispatchKeyEvent" and p.get("key") == "Enter"
        ]


def _driver(responder=None) -> tuple[CdpDriver, FakeTransport]:
    t = FakeTransport(responder)
    return CdpDriver(t, sleep=lambda s: None), t


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


# ── (a) RPS Keywords 필드 Boolean 신뢰 입력 → 검색 실행 → 결과건수 읽기 ──


class TestRpsSearch:
    def test_rps_command_sequence_focus_insert_enter_count(self):
        driver, t = _driver()
        boolean = '("백엔드" OR "Backend") AND ("PM") NOT ("인턴")'
        count = driver.run_rps_search(boolean)
        assert count == 1234  # "1,234명" → 1234
        # 4차 결함 ① — Boolean 은 JS value 대입이 아니라 Input.insertText 로.
        assert boolean in t.inserted_texts()
        assert t.enter_key_events(), "검색 실행(Enter 키 이벤트)이 없다"
        # 순서: Keywords 포커스 → insertText → Enter → 로드 대기 → 건수 읽기
        seq: list[str] = []
        for m, p in t.calls:
            e = p.get("expression", "")
            if "/*vh:focus*/" in e and json.dumps(RPS_KEYWORDS_SELECTOR) in e:
                seq.append("focus")
            elif m == "Input.insertText":
                seq.append("insert")
            elif m == "Input.dispatchKeyEvent":
                seq.append("key")
            elif "/*vh:ready*/" in e:
                seq.append("ready")
            elif "/*vh:count*/" in e:
                seq.append("count")
        assert seq.index("focus") < seq.index("insert") < seq.index("key")
        assert seq.index("key") < seq.index("ready") < seq.index("count")
        # 합성 입력(value 대입) 금지 — select 전용 마커만 예외.
        assert not any(
            ".value=" in e
            for e in t.evaluate_exprs()
            if "/*vh:select*/" not in e
        )

    def test_fill_missing_element_fails_closed(self):
        def responder(method, params):
            expr = params.get("expression", "")
            if "/*vh:focus*/" in expr:
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


# ── (b) 사람인/잡코리아 디스크립터 — URL 이동(로드 대기) + 입력 단계 실행 ──


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
                "kind": "text",
            },
            {
                "order": 2,
                "field": "career_min",
                "selector": "#career_min",
                "values": ["3"],
                "kind": "select",
            },
        ],
    }

    def test_navigates_then_inputs_steps_in_order(self):
        driver, t = _driver()
        driver.run_descriptor(self.DESCRIPTOR)
        assert t.calls[0][0] == "Page.navigate"
        assert t.calls[0][1]["url"] == self.DESCRIPTOR["url"]
        # 텍스트 스텝은 신뢰 입력(Input.insertText) — 다중 값은 값마다 1회.
        assert t.inserted_texts() == ["백엔드", "Backend"]
        # select 스텝은 옵션 선택(/*vh:select*/) — 텍스트 입력 금지.
        selects = [e for e in t.evaluate_exprs() if "/*vh:select*/" in e]
        assert len(selects) == 1
        assert json.dumps("#career_min") in selects[0]
        assert json.dumps("3") in selects[0]

    def test_navigation_waits_for_load_before_inputs(self):
        driver, t = _driver()
        driver.run_descriptor(self.DESCRIPTOR)
        nav_i = next(
            i for i, (m, _p) in enumerate(t.calls) if m == "Page.navigate"
        )
        ready_i = next(
            i
            for i, (_m, p) in enumerate(t.calls)
            if "/*vh:ready*/" in p.get("expression", "")
        )
        insert_i = next(
            i for i, (m, _p) in enumerate(t.calls) if m == "Input.insertText"
        )
        assert nav_i < ready_i < insert_i, "이동 후 로드 대기 없이 입력했다"

    def test_search_submitted_after_all_steps(self):
        driver, t = _driver()
        driver.run_descriptor(self.DESCRIPTOR)
        insert_idx = [
            i for i, (m, _p) in enumerate(t.calls) if m == "Input.insertText"
        ]
        enter_idx = [
            i
            for i, (m, p) in enumerate(t.calls)
            if m == "Input.dispatchKeyEvent" and p.get("key") == "Enter"
        ]
        assert enter_idx, "모든 스텝 입력 후 검색 실행(Enter)이 있어야 한다"
        assert max(insert_idx) < enter_idx[-1]

    def test_navigation_error_text_fails_closed(self):
        def responder(method, params):
            if method == "Page.navigate":
                return {"errorText": "net::ERR_BLOCKED"}
            return FakeTransport.default_responder(method, params)

        driver, _t = _driver(responder)
        with pytest.raises(CdpDriverError):
            driver.run_descriptor(self.DESCRIPTOR)

    def test_load_timeout_fails_closed(self):
        def responder(method, params):
            if "/*vh:ready*/" in params.get("expression", ""):
                return {"result": {"value": "loading"}}
            return FakeTransport.default_responder(method, params)

        driver, _t = _driver(responder)
        with pytest.raises(CdpDriverError):
            driver.run_descriptor(self.DESCRIPTOR)


# ── reset_filters — 2026-08-04 라이브 발견 결함 수정 ─────────────────────
#
# 잡코리아 라이브 실행에서, 탭에 이전(무관한) 검색의 필터 칩이 남아 있으면
# 새 검색 입력·제출을 그대로 해도 화면은 계속 옛 칩 기준 결과를 보여줬다
# (스크린샷으로 "Prompt Engineering"+"FastAPI" 칩이 살아있음을 확인). 이제
# run_descriptor 는 스텝 입력 전에 reset_filters 를 먼저 호출해 기존 칩을
# 지운다.
class TestResetFilters:
    def test_clicks_visible_reset_control_when_present(self):
        def responder(method, params):
            expr = params.get("expression", "")
            if "/*vh:reset_rect*/" in expr:
                return {"result": {"value": {"x": 10.0, "y": 20.0}}}
            return FakeTransport.default_responder(method, params)

        driver, t = _driver(responder)
        clicked = driver.reset_filters("jobkorea")
        assert clicked is True
        mouse_calls = [p for m, p in t.calls if m == "Input.dispatchMouseEvent"]
        assert any(c["type"] == "mousePressed" and c["x"] == 10.0 and c["y"] == 20.0 for c in mouse_calls)
        assert any(c["type"] == "mouseReleased" for c in mouse_calls)

    def test_returns_false_when_no_reset_control_visible(self):
        driver, t = _driver()  # 기본 responder — reset_rect=None
        clicked = driver.reset_filters("jobkorea")
        assert clicked is False
        assert not [p for m, p in t.calls if m == "Input.dispatchMouseEvent"]

    def test_unknown_channel_returns_false_without_side_effects(self):
        driver, t = _driver()
        clicked = driver.reset_filters("linkedin_rps")
        assert clicked is False
        assert not [p for m, p in t.calls if m == "Input.dispatchMouseEvent"]

    def test_run_descriptor_resets_before_any_step_input(self):
        def responder(method, params):
            expr = params.get("expression", "")
            if "/*vh:reset_rect*/" in expr:
                return {"result": {"value": {"x": 5.0, "y": 6.0}}}
            return FakeTransport.default_responder(method, params)

        driver, t = _driver(responder)
        driver.run_descriptor(TestDescriptorExecution.DESCRIPTOR)
        reset_click_i = next(
            i for i, (m, _p) in enumerate(t.calls) if m == "Input.dispatchMouseEvent"
        )
        insert_i = next(
            i for i, (m, _p) in enumerate(t.calls) if m == "Input.insertText"
        )
        assert reset_click_i < insert_i, "칩 초기화가 입력보다 먼저여야 한다"


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

    def test_next_page_waits_for_load_before_reading(self):
        driver, t = _driver()
        driver.fetch_list_page("saramin", 2, dict(self.saramin_payload()))
        exprs = t.evaluate_exprs()
        next_i = next(i for i, e in enumerate(exprs) if "/*vh:next_page*/" in e)
        ready_i = next(
            i for i, e in enumerate(exprs) if "/*vh:ready*/" in e and i > next_i
        )
        html_i = next(i for i, e in enumerate(exprs) if "/*vh:html*/" in e)
        assert next_i < ready_i < html_i

    def test_fetch_detail_page_navigates_waits_and_captures(self):
        driver, t = _driver()
        detail = driver.fetch_detail_page("saramin", "https://fake.test/p/1")
        assert t.calls[0] == (
            "Page.navigate",
            {"url": "https://fake.test/p/1"},
        )
        exprs = t.evaluate_exprs()
        ready_i = next(i for i, e in enumerate(exprs) if "/*vh:ready*/" in e)
        html_i = next(i for i, e in enumerate(exprs) if "/*vh:html*/" in e)
        assert ready_i < html_i  # 로드 완료 대기 후에만 HTML 읽기(결함 ⑧)
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

    def test_linkedin_payload_routes_to_rps_search_with_filters(self):
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
        texts = t.inserted_texts()
        assert '("PM") AND ("SaaS")' in texts  # Boolean 신뢰 입력
        # 4차 결함 ① — 필터는 전달이 아니라 실제 입력 시퀀스로 실행된다.
        assert "South Korea" in texts
        assert "서울대학교" in texts
        assert "3" in texts


# ── (d) 사람 입력/캡차 폴링 → InterventionMonitor 이벤트 공급 ──


def _snapshot(overrides: dict) -> dict:
    snap = dict(FakeTransport.SNAPSHOT)
    snap.update(overrides)
    return snap


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
                _snapshot({"h": 0}),
                _snapshot({"h": 2}),
                _snapshot({"h": 2}),
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
                return {"result": {"value": _snapshot({"captcha": True})}}
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

    def test_snapshot_missing_challenge_fields_fails_closed(self):
        """구(舊) 스냅샷 형식(2FA/체크포인트 필드 없음)은 형식 위반 — 차단."""

        def responder(method, params):
            if "/*vh:snapshot*/" in params.get("expression", ""):
                return {
                    "result": {
                        "value": {"h": 0, "captcha": False, "cloudflare": False}
                    }
                }
            return FakeTransport.default_responder(method, params)

        driver, _t = _driver(responder)
        events = driver.poll_events()
        assert len(events) == 1
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


# ── DETAIL_LINK_SELECTORS 라이브 검증 회귀 방지 ──────────────────────────
#
# CSS 속성 셀렉터 [href*=value] 는 대소문자를 구분한다. 2026-08-04 잡코리아
# 인재검색 라이브 실행(실제 검색 결과 HTML)에서 옛 셀렉터
# "a[href*='/Corp/Person/'][href*='View']" 가 실제 소문자 href 와 전혀
# 매치되지 않아 상세 링크가 항상 0건이던 결함을 발견했다. 실제 관측 href
# 문자열을 고정해 같은 대소문자 회귀를 다시 못 잡는 일을 막는다.
JOBKOREA_LIVE_DETAIL_HREF = "/corp/person/find/resume/view?rNo=29465392"


class TestDetailLinkSelectorsMatchRealHrefs:
    def test_jobkorea_selector_substring_occurs_in_real_href(self):
        match = re.search(r"href\*='([^']+)'", DETAIL_LINK_SELECTORS["jobkorea"])
        assert match, "jobkorea 셀렉터에 href*='...' 패턴이 없다"
        needle = match.group(1)
        # 대소문자 그대로 비교 — querySelectorAll 의 실제 매치 동작 재현.
        assert needle in JOBKOREA_LIVE_DETAIL_HREF


# ── list_detail_refs 중복 제거 회귀 방지 ──────────────────────────────────
#
# 2026-08-04 잡코리아 라이브 실행에서 후보 1명당 앵커(<a>)가 2개씩 걸려
# detail_refs 가 실제 후보 수(71명)의 정확히 2배(142)로 나왔다 — 셀렉터 수정
# 직후 곧바로 라이브에서 발견. 중복 상세 진입은 같은 URL을 연달아 두 번
# 여는 기계적 패턴이라 SOT 의 "봇처럼 굴지 않는다" 원칙 위반이자 시간 낭비다.
class TestListDetailRefsDeduplicates:
    def test_duplicate_hrefs_collapse_to_unique_order_preserved(self):
        def responder(method, params):
            expr = params.get("expression", "")
            if "/*vh:detail_refs*/" in expr:
                return {
                    "result": {
                        "value": [
                            "https://fake.test/p/1",
                            "https://fake.test/p/1",
                            "https://fake.test/p/2",
                            "https://fake.test/p/2",
                            "https://fake.test/p/3",
                        ]
                    }
                }
            return FakeTransport.default_responder(method, params)

        driver, _t = _driver(responder)
        refs = driver.list_detail_refs("jobkorea")
        assert refs == [
            "https://fake.test/p/1",
            "https://fake.test/p/2",
            "https://fake.test/p/3",
        ]
