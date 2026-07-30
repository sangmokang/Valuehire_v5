"""V1 3차 결함 ①②④ — 실제 브라우저 실행 호출부: raw CDP 드라이버 어댑터.

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §2(3사 동시 검색),
§4 AC-2/AC-3/AC-7/AC-8. 오케스트레이터(run_search_pipeline)의 주입 포트
(BrowserDriverPort / fetch_list_page / fetch_detail_page / poll_driver_events)를
Chrome DevTools Protocol 위에서 구현한다.

패턴 출처(재사용 — 해당 모듈은 수정하지 않는다):
- tools/multi_position_sourcing/raw_cdp.py `CDPTab.send` — id 프레이밍 +
  Runtime.evaluate(returnByValue) 1회 왕복. 사장님 크롬 탭 수백 개에서
  playwright connectOverCDP 전체 attach 가 hang 하므로 목표 탭 1개에만 raw
  WebSocket 으로 붙는 패턴.
- tools/multi_position_sourcing/raw_page_adapter.py `RawLocator.fill/press` —
  selector·value 는 반드시 json.dumps 로 이스케이프해 JS 에 넣는다
  (injection·따옴표 안전), input/change 이벤트 dispatch + Enter 는
  KeyboardEvent 3종 + form.requestSubmit.

설계 원칙:
- CDP 트랜스포트는 **주입식** — ``send_command(method, params) -> result``
  callable 하나만 받는다. 실 웹소켓은 :func:`connect_websocket_transport`
  (지연 import)로만 만들며, 단위 테스트는 페이크 트랜스포트로 전 명령
  시퀀스를 검증한다(실 브라우저/9222 접속 0).
- 모든 evaluate 표현식에 ``/*vh:...*/`` 마커를 넣어 명령 시퀀스를
  결정론적으로 검증/모킹할 수 있게 한다.
- 실패는 전부 fail-closed: 셀렉터 미발견·navigation errorText·결과건수
  숫자 없음·has_next 비불리언·JS 예외 → :class:`CdpDriverError`.
- 캡차/사람 입력 폴링(poll_events)은 intervention.feed_driver_events 규격
  이벤트를 돌려준다. 스냅샷 형식 위반은 임의 추정 없이 차단 신호로
  돌려준다(E8 fail-closed — 모니터가 BLOCKED 처리).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping, Optional

__all__ = [
    "RPS_KEYWORDS_SELECTOR",
    "CdpDriver",
    "CdpDriverError",
    "CdpTransportError",
    "WebSocketCdpTransport",
    "connect_websocket_transport",
]

#: send_command(method, params) -> CDP result dict — 주입식 트랜스포트 계약.
Transport = Callable[[str, dict], dict]

LINKEDIN_CHANNEL = "linkedin_rps"

#: LinkedIn RPS Keywords 필드(Boolean 검색) — docs/search-access.md:405-415.
#: id 는 ember 동적 suffix 라 안정 속성(data-test-...)으로 잡는다.
RPS_KEYWORDS_SELECTOR = "textarea[data-test-free-text-single-value-facet-textarea]"

#: RPS 결과건수 표시 후보 셀렉터 — LinkedIn DOM 은 자주 바뀌므로 "약한 참조"
#: (docs/search-access.md:387-389)로 복수 후보를 순서대로 시도한다.
RPS_RESULT_COUNT_SELECTORS = (
    "[data-test-search-results-count]",
    ".hp-core-temp-search-results-count",
    "header.search-results__header",
)

#: 채널별 리스트 → 상세 프로필 링크 셀렉터(약한 참조 — 라이브 검증 대상).
DETAIL_LINK_SELECTORS: dict[str, str] = {
    LINKEDIN_CHANNEL: "a[data-test-link-to-profile-link]",
    "saramin": "a[href*='talent-pool'][href*='view']",
    "jobkorea": "a[href*='/Corp/Person/'][href*='View']",
}

#: 채널별 "다음 페이지" 컨트롤 셀렉터(약한 참조 — 라이브 검증 대상).
NEXT_PAGE_SELECTORS: dict[str, str] = {
    LINKEDIN_CHANNEL: "button[aria-label='Next']",
    "saramin": "div.pagination a.next, a.btn_next",
    "jobkorea": "div.tplPagination a.next, a.tplBtn.next",
}

#: 캡차/차단 화면 감지 프로브(약한 참조) — 발견 시 즉시 BLOCKED 신호.
_CAPTCHA_PROBE_JS = (
    "!!(document.querySelector(\"iframe[src*='captcha'],iframe[src*='recaptcha'],"
    "#captcha,.captcha,[id*='arkose']\"))"
)
_CLOUDFLARE_PROBE_JS = (
    "!!(document.querySelector('#challenge-form,#cf-challenge-running')"
    "||/cloudflare/i.test(document.title||''))"
)

#: 사람 입력 관측 카운터 전역 키(페이지 컨텍스트).
_OBSERVER_KEY = "__vh_aisearch_human_inputs"


class CdpDriverError(RuntimeError):
    """드라이버 실행 실패 — 전부 fail-closed(조용한 무시 금지)."""


class CdpTransportError(RuntimeError):
    """CDP 트랜스포트 오류(error 응답 등)."""


class WebSocketCdpTransport:
    """웹소켓 전송 함수 주입식 트랜스포트 — raw_cdp.CDPTab.send 프레이밍 재사용.

    send_text/recv_text 만 주입받으므로 실 소켓 없이도 프레이밍을 검증할 수
    있다. 요청 id 와 일치하지 않는 수신 메시지(CDP 이벤트 등)는 ``events`` 에
    버퍼링한다(raw_cdp.py:532-549 패턴).
    """

    def __init__(
        self,
        send_text: Callable[[str], Any],
        recv_text: Callable[[], str],
    ) -> None:
        self._send_text = send_text
        self._recv_text = recv_text
        self._next_id = 0
        self.events: list[dict] = []

    def __call__(self, method: str, params: Optional[dict] = None) -> dict:
        self._next_id += 1
        mid = self._next_id
        self._send_text(
            json.dumps({"id": mid, "method": method, "params": params or {}})
        )
        while True:
            message = json.loads(self._recv_text())
            if message.get("id") == mid:
                if "error" in message:
                    raise CdpTransportError(
                        f"CDP error({method}): {message['error']}"
                    )
                result = message.get("result", {})
                return result if isinstance(result, dict) else {}
            self.events.append(message)


def connect_websocket_transport(ws_url: str) -> WebSocketCdpTransport:
    """실 웹소켓 트랜스포트 — 라이브 실행 전용(테스트에서는 절대 호출 금지).

    websocket-client 는 지연 import 한다(raw_cdp.py:22-24 와 같은 이유 —
    페이크 트랜스포트만 쓰는 경로가 websocket 설치/연결에 의존하지 않게).
    """
    import websocket  # 지연 import — 라이브 연결 시점에만 필요

    ws = websocket.create_connection(ws_url, suppress_origin=True)
    transport = WebSocketCdpTransport(ws.send, ws.recv)
    for domain in ("Page.enable", "Runtime.enable"):
        transport(domain, {})
    return transport


def _fill_js(selector: str, value: str) -> str:
    """raw_page_adapter.RawLocator.fill 패턴 — json.dumps 이스케이프 필수."""
    return (
        "/*vh:fill*/(function(){"
        f"var e=document.querySelector({json.dumps(selector)});"
        "if(!e)return false;"
        f"e.value={json.dumps(value)};"
        "e.dispatchEvent(new Event('input',{bubbles:true}));"
        "e.dispatchEvent(new Event('change',{bubbles:true}));"
        "return true;})()"
    )


def _enter_js(selector: str) -> str:
    """raw_page_adapter.RawLocator.press('Enter') 패턴 재사용."""
    return (
        "/*vh:submit*/(function(){"
        f"var e=document.querySelector({json.dumps(selector)});"
        "if(!e)return false;"
        "['keydown','keypress','keyup'].forEach(function(t){"
        "e.dispatchEvent(new KeyboardEvent(t,{key:'Enter',bubbles:true}));});"
        "if(e.form&&e.form.requestSubmit){e.form.requestSubmit();}"
        "return true;})()"
    )


class CdpDriver:
    """주입식 CDP 트랜스포트 위의 브라우저 드라이버 어댑터.

    오케스트레이터 포트 대응:
    - run_js: BrowserDriverPort(AC-8 배너 dispatch 스니펫 evaluate)
    - fetch_list_page / fetch_detail_page: AC-3 페이지 공급자
    - poll_events: AC-7 InterventionMonitor 이벤트 공급자
    """

    def __init__(self, send_command: Transport) -> None:
        self._send = send_command
        self._observers_installed = False
        self._last_human_inputs = 0

    # ── 기본 evaluate/navigate ──────────────────────────────────────────

    def _evaluate(self, expression: str) -> Any:
        result = self._send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        )
        if not isinstance(result, dict):
            raise CdpDriverError(f"Runtime.evaluate 응답 형식 위반: {result!r}")
        if result.get("exceptionDetails"):
            raise CdpDriverError(
                f"JS 예외: {result['exceptionDetails']!r} (expr={expression[:120]!r})"
            )
        inner = result.get("result", {})
        return inner.get("value") if isinstance(inner, dict) else None

    def run_js(self, snippet: str) -> None:
        """AC-8 (e) — 배너 dispatch 스니펫 등 임의 JS 를 그대로 evaluate."""
        self._evaluate(snippet)

    def navigate(self, url: str) -> None:
        result = self._send("Page.navigate", {"url": url})
        if isinstance(result, dict) and result.get("errorText"):
            raise CdpDriverError(f"navigation 실패({url}): {result['errorText']}")

    def current_url(self) -> str:
        return str(self._evaluate("/*vh:url*/location.href") or "")

    def capture_html(self) -> str:
        """(c) — 현재 페이지 HTML 캡처(전량 저장용 원문)."""
        return str(
            self._evaluate("/*vh:html*/document.documentElement.outerHTML") or ""
        )

    # ── 입력/검색 실행 ─────────────────────────────────────────────────

    def _fill(self, selector: str, value: str) -> None:
        if self._evaluate(_fill_js(selector, value)) is not True:
            raise CdpDriverError(f"셀렉터 미발견 — 입력 실패(fail-closed): {selector}")

    def _press_enter(self, selector: str) -> None:
        if self._evaluate(_enter_js(selector)) is not True:
            raise CdpDriverError(f"셀렉터 미발견 — 실행 실패(fail-closed): {selector}")

    def run_rps_search(self, boolean_query: str) -> int:
        """(a) — RPS Keywords 필드에 Boolean 문자열 입력 → 검색 실행 →
        결과건수 읽기. 숫자를 못 읽으면 fail-closed."""
        if not isinstance(boolean_query, str) or not boolean_query.strip():
            raise CdpDriverError("RPS Boolean 문자열이 비어 있다(fail-closed)")
        self._fill(RPS_KEYWORDS_SELECTOR, boolean_query)
        self._press_enter(RPS_KEYWORDS_SELECTOR)
        selectors_js = json.dumps(list(RPS_RESULT_COUNT_SELECTORS))
        text = self._evaluate(
            "/*vh:count*/(function(){"
            f"var sels={selectors_js};"
            "for(var i=0;i<sels.length;i++){"
            "var e=document.querySelector(sels[i]);"
            "if(e&&e.innerText)return e.innerText;}"
            "return '';})()"
        )
        digits = re.sub(r"[^0-9]", "", str(text or ""))
        if not digits:
            raise CdpDriverError(
                f"RPS 결과건수를 읽지 못했다(fail-closed): {text!r}"
            )
        return int(digits)

    def run_descriptor(self, descriptor: Mapping[str, Any]) -> None:
        """(b) — 사람인/잡코리아 디스크립터: URL 이동 → 입력 단계 실행 → 검색.

        다중 값 스텝(예: 사람인 OR 키워드 칩)은 값마다 fill + Enter(칩 확정),
        단일 값 스텝은 fill 만 한다. 모든 스텝 후 첫 스텝 셀렉터에 Enter 로
        검색을 실행한다.
        """
        url = descriptor.get("url")
        if not isinstance(url, str) or not url:
            raise CdpDriverError(f"디스크립터 url 이 비어 있다: {descriptor!r}")
        self.navigate(url)
        steps = sorted(descriptor.get("steps") or [], key=lambda s: s["order"])
        for step in steps:
            values = step.get("values") or []
            multi = len(values) > 1
            for value in values:
                self._fill(step["selector"], str(value))
                if multi:  # 칩형 입력 — 값마다 Enter 로 확정
                    self._press_enter(step["selector"])
        if steps:
            self._press_enter(steps[0]["selector"])  # 검색 실행

    def execute_search(self, search_payload: Mapping[str, Any]) -> None:
        """오케스트레이터 search_payload(2차 결함 9 규격)를 채널별로 실행."""
        channel = search_payload.get("channel")
        if channel == LINKEDIN_CHANNEL:
            self.run_rps_search(str(search_payload.get("keywords") or ""))
        elif channel in ("saramin", "jobkorea"):
            self.run_descriptor(search_payload)
        else:
            raise CdpDriverError(f"미지 채널 payload(fail-closed): {channel!r}")

    # ── AC-3 페이지 공급자(fetch_list_page / fetch_detail_page) ─────────

    def _detail_selector(self, channel: str) -> str:
        try:
            return DETAIL_LINK_SELECTORS[channel]
        except KeyError:
            raise CdpDriverError(f"미지 채널(fail-closed): {channel!r}") from None

    def list_detail_refs(self, channel: str) -> list[str]:
        selector = self._detail_selector(channel)
        refs = self._evaluate(
            "/*vh:detail_refs*/(function(){"
            f"return Array.from(document.querySelectorAll({json.dumps(selector)}))"
            ".map(function(a){return a.href;}).filter(Boolean);})()"
        )
        if not isinstance(refs, list) or not all(
            isinstance(r, str) for r in refs
        ):
            raise CdpDriverError(f"상세 링크 목록 형식 위반(fail-closed): {refs!r}")
        return refs

    def has_next_page(self, channel: str) -> bool:
        selector = NEXT_PAGE_SELECTORS.get(channel)
        if selector is None:
            raise CdpDriverError(f"미지 채널(fail-closed): {channel!r}")
        value = self._evaluate(
            "/*vh:has_next*/(function(){"
            f"var e=document.querySelector({json.dumps(selector)});"
            "return !!(e&&!e.disabled);})()"
        )
        if not isinstance(value, bool):
            # AC-3 _require_has_next 와 같은 원칙 — 조용한 추정 금지.
            raise CdpDriverError(f"has_next 는 bool 이어야 한다: {value!r}")
        return value

    def goto_next_page(self, channel: str) -> None:
        selector = NEXT_PAGE_SELECTORS.get(channel)
        if selector is None:
            raise CdpDriverError(f"미지 채널(fail-closed): {channel!r}")
        clicked = self._evaluate(
            "/*vh:next_page*/(function(){"
            f"var e=document.querySelector({json.dumps(selector)});"
            "if(!e||e.disabled)return false;e.click();return true;})()"
        )
        if clicked is not True:
            raise CdpDriverError(
                f"다음 페이지 컨트롤 미발견(fail-closed): {selector}"
            )

    def fetch_list_page(
        self, channel: str, page: int, search_payload: Mapping[str, Any]
    ) -> dict:
        """AC-3 fetch_list_page(channel, page, payload) 계약 구현.

        1페이지 = 검색 실행(즉시 실행 가능한 payload 그대로), 2페이지부터는
        "다음 페이지" 클릭. 항상 {url, content, detail_refs, has_next} 반환.
        """
        if not isinstance(page, int) or page < 1:
            raise CdpDriverError(f"page 는 1 이상 정수여야 한다: {page!r}")
        if page == 1:
            self.execute_search(search_payload)
        else:
            self.goto_next_page(channel)
        return {
            "url": self.current_url(),
            "content": self.capture_html(),
            "detail_refs": self.list_detail_refs(channel),
            "has_next": self.has_next_page(channel),
        }

    def fetch_detail_page(self, channel: str, ref: str) -> dict:
        if not isinstance(ref, str) or not ref:
            raise CdpDriverError(f"상세 ref 가 비어 있다(fail-closed): {ref!r}")
        self.navigate(ref)
        return {"url": ref, "content": self.capture_html()}

    # ── (d) 사람 입력/캡차 폴링 → InterventionMonitor 이벤트 공급 ────────

    def install_observers(self) -> None:
        """페이지 컨텍스트에 사람 입력 카운터 리스너를 설치한다(멱등)."""
        self._evaluate(
            "/*vh:observe*/(function(){"
            f"if(window.{_OBSERVER_KEY}!==undefined)return true;"
            f"window.{_OBSERVER_KEY}=0;"
            "['mousedown','keydown','wheel','touchstart'].forEach(function(t){"
            "window.addEventListener(t,function(){"
            f"window.{_OBSERVER_KEY}++;"
            "},{capture:true,passive:true});});return true;})()"
        )
        self._observers_installed = True

    def poll_events(self) -> list[dict]:
        """intervention.feed_driver_events 규격 이벤트 목록을 돌려준다.

        - 사람 입력 카운터 증가 → {"type": "human_input"}
        - 캡차/클라우드플레어 감지 → {"type": "signal", "kind": ...}
        - 스냅샷 형식 위반 → 차단 신호(driver_snapshot_invalid) — E8 fail-closed.
        """
        if not self._observers_installed:
            self.install_observers()
        snapshot = self._evaluate(
            "/*vh:snapshot*/(function(){return{"
            f"h:(window.{_OBSERVER_KEY}||0),"
            f"captcha:{_CAPTCHA_PROBE_JS},"
            f"cloudflare:{_CLOUDFLARE_PROBE_JS}"
            "};})()"
        )
        if (
            not isinstance(snapshot, dict)
            or not isinstance(snapshot.get("h"), int)
            or isinstance(snapshot.get("h"), bool)
            or not isinstance(snapshot.get("captcha"), bool)
            or not isinstance(snapshot.get("cloudflare"), bool)
        ):
            return [
                {
                    "type": "signal",
                    "kind": f"driver_snapshot_invalid:{snapshot!r}",
                }
            ]
        events: list[dict] = []
        human_inputs = snapshot["h"]
        if human_inputs > self._last_human_inputs:
            events.append({"type": "human_input"})
        self._last_human_inputs = max(self._last_human_inputs, human_inputs)
        if snapshot["captcha"]:
            events.append({"type": "signal", "kind": "captcha"})
        if snapshot["cloudflare"]:
            events.append({"type": "signal", "kind": "cloudflare"})
        return events
