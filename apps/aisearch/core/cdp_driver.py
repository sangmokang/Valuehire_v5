"""V1 3차 결함 ①②④(+4차 ①②④⑩) — 실제 브라우저 실행 호출부: raw CDP 드라이버.

goal: docs/engineering/aisearch-fleet-goal-2026-07-28.md §2(3사 동시 검색),
§4 AC-2/AC-3/AC-7/AC-8. 오케스트레이터(run_search_pipeline)의 주입 포트
(BrowserDriverPort / fetch_list_page / fetch_detail_page / poll_driver_events)를
Chrome DevTools Protocol 위에서 구현한다.

패턴 출처(재사용 — 해당 모듈은 수정하지 않는다):
- tools/multi_position_sourcing/raw_cdp.py `CDPTab.send` — id 프레이밍 +
  1회 왕복. 사장님 크롬 탭 수백 개에서 playwright connectOverCDP 전체 attach 가
  hang 하므로 목표 탭 1개에만 raw WebSocket 으로 붙는 패턴.
- selector·value 는 반드시 json.dumps 로 이스케이프해 JS 에 넣는다
  (injection·따옴표 안전 — raw_page_adapter.py 패턴).

설계 원칙(V1 4차 적대검증 반영):
- **신뢰 입력(결함 ①)**: 텍스트 입력은 JS value 대입이 아니라 CDP Input 도메인
  (``Input.insertText``)으로, 검색 실행(Enter)은 ``Input.dispatchKeyEvent``
  3종(rawKeyDown/char/keyUp)으로, 체크박스는 ``Input.dispatchMouseEvent``
  클릭 시퀀스(결함 ②)로 넣는다. JS 는 포커스 이동(``/*vh:focus*/``)과 좌표
  계산(``/*vh:rect*/``)에만 쓴다. ``<select>`` 요소만 예외적으로 value+change
  (``/*vh:select*/``) — 키 입력으로 조작할 수 없는 요소다.
- **로드 완료 대기(결함 ②/⑧)**: 모든 이동(검색 실행·다음 페이지·상세 진입)
  후 ``document.readyState=='complete'`` 폴링(주입 sleep)으로 로드 완료를
  기다린 뒤에만 입력/HTML 읽기를 한다. 타임아웃이면 명시적 실패(fail-closed).
- **자동 입력 표식(결함 ④a)**: 자동 입력 시퀀스 전후로 페이지 전역 플래그
  (``__vh_auto_input_active``)를 켜고 꺼서, 감시 스크립트가 자동화 입력을
  사람 입력으로 오인하지 않는다(CDP Input 이벤트는 isTrusted=true 라 표식이
  없으면 자기 입력에 스스로 정지한다).
- **감시 재설치(결함 ④b)**: 페이지 이동(navigate·다음 페이지)마다 감시
  스크립트 설치 상태를 리셋하고, 스냅샷의 ``present=false``(이동으로 소실)
  감지 시 자동 재설치한다.
- **확장 감지(결함 ④c)**: 캡차/클라우드플레어에 더해 2FA·체크포인트·
  멀티세션(중복 로그인) 문구를 감지해 차단 신호로 발행한다(→ BLOCKED).
- **연결 단위 락(결함 ⑩)**: 같은 연결(트랜스포트)에 대한 동시 호출은 드라이버
  내부 락으로 직렬화한다 — id 프레이밍 응답 혼선 방지. 채널 간 병렬성은
  채널당 독립 드라이버(각자 탭/연결)로 확보한다(run.py 조립).
- CDP 트랜스포트는 **주입식** — ``send_command(method, params) -> result``
  callable 하나만 받는다. 실 웹소켓은 :func:`connect_websocket_transport`
  (지연 import)로만 만들며, 단위 테스트는 페이크 트랜스포트로 전 명령
  시퀀스를 검증한다(실 브라우저/9222 접속 0).
- 실패는 전부 fail-closed: 셀렉터 미발견·navigation errorText·로드 타임아웃·
  결과건수 숫자 없음·has_next 비불리언·JS 예외 → :class:`CdpDriverError`.
- 캡차/사람 입력 폴링(poll_events)은 intervention.feed_driver_events 규격
  이벤트를 돌려준다. 스냅샷 형식 위반은 임의 추정 없이 차단 신호로
  돌려준다(E8 fail-closed — 모니터가 BLOCKED 처리).
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable, Mapping, Optional

__all__ = [
    "RPS_KEYWORDS_SELECTOR",
    "RPS_LOCATION_SELECTOR",
    "RPS_SCHOOL_SELECTOR",
    "RPS_YEARS_MIN_SELECTOR",
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

#: RPS 필터 입력 필드(약한 참조 — 라이브 검증 대상). 결함 ① — 지역·대학·경력
#: 필터는 payload 전달로 끝나지 않고 이 필드들에 실제 입력 시퀀스로 적용한다.
RPS_LOCATION_SELECTOR = (
    "input[data-test-location-typeahead-input], "
    "input[placeholder*='location' i]"
)
RPS_SCHOOL_SELECTOR = (
    "input[data-test-school-typeahead-input], "
    "input[placeholder*='school' i]"
)
RPS_YEARS_MIN_SELECTOR = (
    "input[data-test-years-of-experience-min], "
    "input[aria-label*='minimum years' i]"
)

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

#: 로드 완료 대기(결함 ②/⑧) 기본값 — 주입식 sleep 으로 폴링한다.
LOAD_TIMEOUT_SECONDS: float = 15.0
LOAD_POLL_INTERVAL_SECONDS: float = 0.2

#: 캡차/차단 화면 감지 프로브(약한 참조) — 발견 시 즉시 BLOCKED 신호.
_CAPTCHA_PROBE_JS = (
    "!!(document.querySelector(\"iframe[src*='captcha'],iframe[src*='recaptcha'],"
    "#captcha,.captcha,[id*='arkose']\"))"
)
_CLOUDFLARE_PROBE_JS = (
    "!!(document.querySelector('#challenge-form,#cf-challenge-running')"
    "||/cloudflare/i.test(document.title||''))"
)

#: 결함 ④c — 2FA·체크포인트·멀티세션 문구 감지(페이지 텍스트+제목 스캔).
_PAGE_TEXT_JS = "(((document.body&&document.body.innerText)||'')+' '+(document.title||''))"
_TWOFA_PROBE_JS = (
    "/(two[- ]?factor|2\\ub2e8\\uacc4 ?\\uc778\\uc99d|\\uc778\\uc99d\\ubc88\\ud638|"
    "verification code|\\ubcf8\\uc778 ?\\ud655\\uc778|OTP \\uc785\\ub825)/i"
    f".test({_PAGE_TEXT_JS})"
)
_CHECKPOINT_PROBE_JS = (
    "/(checkpoint|\\ubcf4\\uc548 ?\\uc810\\uac80|security check|"
    "unusual activity|\\ube44\\uc815\\uc0c1\\uc801\\uc778 ?\\ud65c\\ub3d9)/i"
    f".test({_PAGE_TEXT_JS})"
)
_MULTISESSION_PROBE_JS = (
    "/(\\ub2e4\\ub978 (\\uae30\\uae30|\\uacf3)\\uc5d0\\uc11c \\ub85c\\uadf8\\uc778|"
    "\\uc911\\ubcf5 ?\\ub85c\\uadf8\\uc778|multiple sessions|signed in (on another|elsewhere)|"
    "session (was )?opened elsewhere)/i"
    f".test({_PAGE_TEXT_JS})"
)

#: 사람 입력 관측 카운터 전역 키(페이지 컨텍스트).
_OBSERVER_KEY = "__vh_aisearch_human_inputs"
#: 결함 ④a — 자동 입력 표식 전역 키. 켜져 있는 동안의 입력 이벤트는
#: 감시 카운터가 세지 않는다(자기 입력을 사람 입력으로 오인 금지).
_AUTO_FLAG_KEY = "__vh_auto_active"


class CdpDriverError(RuntimeError):
    """드라이버 실행 실패 — 전부 fail-closed(조용한 무시 금지)."""


class DetailPageBlocked(CdpDriverError):
    """V1 독립검증 결함1 — 상세페이지 자체에서 캡차/2FA/클라우드플레어 등이 감지됨.

    목록 페이지 복귀 후에만 차단신호를 검사하면 이미 늦다(캡차 화면이 그대로
    후보 데이터로 저장됨) — 그래서 상세페이지에 머무는 동안 캡처 전에 검사한다.
    """

    def __init__(self, events: list[dict]) -> None:
        super().__init__(f"상세 페이지 차단 신호 감지: {events!r}")
        self.events = events


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


def _focus_js(selector: str) -> str:
    """결함 ① — 입력 전 포커스 이동(입력 자체는 CDP Input 도메인이 한다)."""
    return (
        "/*vh:focus*/(function(){"
        f"var e=document.querySelector({json.dumps(selector)});"
        "if(!e)return false;"
        "if(e.scrollIntoView)e.scrollIntoView({block:'center'});"
        "e.focus();"
        "if(e.select)e.select();"
        "return true;})()"
    )


def _rect_js(selector: str) -> str:
    """결함 ② — 클릭 좌표 계산(클릭 자체는 Input.dispatchMouseEvent 가 한다)."""
    return (
        "/*vh:rect*/(function(){"
        f"var e=document.querySelector({json.dumps(selector)});"
        "if(!e)return false;"
        "if(e.scrollIntoView)e.scrollIntoView({block:'center'});"
        "var r=e.getBoundingClientRect();"
        "return{x:r.left+r.width/2,y:r.top+r.height/2};})()"
    )


def _select_js(selector: str, value: str) -> str:
    """``<select>`` 전용 — 키 입력으로 조작할 수 없는 요소의 옵션 선택.

    (텍스트 입력에 이 패턴을 쓰면 결함 ① 재발 — _insert_text 를 쓸 것.)
    """
    return (
        "/*vh:select*/(function(){"
        f"var e=document.querySelector({json.dumps(selector)});"
        "if(!e)return false;"
        f"e.value={json.dumps(value)};"
        "e.dispatchEvent(new Event('change',{bubbles:true}));"
        "return true;})()"
    )


#: Enter 키 이벤트 3종(rawKeyDown/char/keyUp) — Input.dispatchKeyEvent 파라미터.
_ENTER_KEY_EVENTS: tuple[dict, ...] = (
    {
        "type": "rawKeyDown",
        "key": "Enter",
        "code": "Enter",
        "windowsVirtualKeyCode": 13,
        "nativeVirtualKeyCode": 13,
    },
    {"type": "char", "text": "\r", "key": "Enter"},
    {
        "type": "keyUp",
        "key": "Enter",
        "code": "Enter",
        "windowsVirtualKeyCode": 13,
        "nativeVirtualKeyCode": 13,
    },
)


class CdpDriver:
    """주입식 CDP 트랜스포트 위의 브라우저 드라이버 어댑터.

    오케스트레이터 포트 대응:
    - run_js: BrowserDriverPort(AC-8 배너 dispatch 스니펫 evaluate)
    - fetch_list_page / fetch_detail_page: AC-3 페이지 공급자
    - poll_events: AC-7 InterventionMonitor 이벤트 공급자

    결함 ⑩ — 드라이버 1개 = 연결(탭) 1개가 계약이다. 내부 락이 같은 연결에
    대한 동시 호출을 직렬화하고, 채널 간 병렬성은 채널당 드라이버 인스턴스를
    따로 만들어 얻는다(같은 트랜스포트를 두 드라이버가 공유하면 계약 위반).
    """

    def __init__(
        self,
        send_command: Transport,
        *,
        sleep: Callable[[float], None] = time.sleep,
        poll_interval: float = LOAD_POLL_INTERVAL_SECONDS,
        load_timeout: float = LOAD_TIMEOUT_SECONDS,
    ) -> None:
        self._send = send_command
        self._sleep = sleep
        self._poll_interval = poll_interval
        self._load_timeout = load_timeout
        self._observers_installed = False
        self._last_human_inputs = 0
        #: 결함 ⑩ — 연결 단위 락: 같은 연결 동시 호출 직렬화(응답 혼선 방지).
        self._conn_lock = threading.Lock()
        #: 5차 결함 ① — 마지막 목록 페이지 URL. 상세 프로필을 현재 탭으로 연
        #: 뒤 여기로 복귀해야 '다음 페이지' 순회(20페이지)가 이어진다.
        self._last_list_url: str = ""

    # ── 기본 evaluate/navigate ──────────────────────────────────────────

    def _cmd(self, method: str, params: dict) -> dict:
        with self._conn_lock:  # 결함 ⑩ — 연결 점유는 한 번에 한 호출만
            result = self._send(method, params)
        if not isinstance(result, dict):
            raise CdpDriverError(f"{method} 응답 형식 위반: {result!r}")
        return result

    def _evaluate(self, expression: str) -> Any:
        result = self._cmd(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
        )
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
        result = self._cmd("Page.navigate", {"url": url})
        if result.get("errorText"):
            raise CdpDriverError(f"navigation 실패({url}): {result['errorText']}")
        # 결함 ④b — 이동으로 페이지 컨텍스트가 갈리면 감시 스크립트도 소실된다.
        self._observers_installed = False
        # 결함 ② — 이동 후 로드 완료를 기다린 뒤에만 후속 입력/읽기를 한다.
        self.wait_for_load()

    def wait_for_load(self) -> None:
        """결함 ②/⑧ — readyState=='complete' 폴링(주입 sleep), 타임아웃 시
        명시적 실패(fail-closed). 실 sleep 은 라이브에서만 쓰인다."""
        attempts = max(1, int(self._load_timeout / self._poll_interval))
        state: Any = None
        for attempt in range(attempts):
            state = self._evaluate("/*vh:ready*/document.readyState")
            if state == "complete":
                return
            self._sleep(self._poll_interval)
        raise CdpDriverError(
            f"페이지 로드 대기 타임아웃(fail-closed): readyState={state!r}, "
            f"{self._load_timeout}s 초과"
        )

    def current_url(self) -> str:
        return str(self._evaluate("/*vh:url*/location.href") or "")

    def capture_html(self) -> str:
        """(c) — 현재 페이지 HTML 캡처(전량 저장용 원문)."""
        return str(
            self._evaluate("/*vh:html*/document.documentElement.outerHTML") or ""
        )

    # ── 신뢰 입력 시퀀스(결함 ①②④a) ──────────────────────────────────

    def _set_auto_flag(self, active: bool) -> None:
        marker = "auto_on" if active else "auto_off"
        value = "1" if active else "0"
        self._evaluate(f"/*vh:{marker}*/(window.{_AUTO_FLAG_KEY}={value},true)")

    def _focus(self, selector: str) -> None:
        if self._evaluate(_focus_js(selector)) is not True:
            raise CdpDriverError(
                f"셀렉터 미발견 — 포커스 실패(fail-closed): {selector}"
            )

    def _insert_text(self, selector: str, value: str) -> None:
        """결함 ① — 포커스 후 CDP Input.insertText 로 신뢰 입력한다."""
        self._set_auto_flag(True)  # 결함 ④a — 자동 입력 표식 ON
        try:
            self._focus(selector)
            self._cmd("Input.insertText", {"text": value})
        finally:
            self._set_auto_flag(False)

    def _press_enter(self, selector: str) -> None:
        """결함 ① — Input.dispatchKeyEvent(Enter 3종)로 검색/칩 확정 실행."""
        self._set_auto_flag(True)
        try:
            self._focus(selector)
            for event in _ENTER_KEY_EVENTS:
                self._cmd("Input.dispatchKeyEvent", dict(event))
        finally:
            self._set_auto_flag(False)

    def _click(self, selector: str) -> None:
        """결함 ② — 체크박스 등은 좌표 계산 후 마우스 클릭 시퀀스로 조작한다."""
        self._set_auto_flag(True)
        try:
            rect = self._evaluate(_rect_js(selector))
            if (
                not isinstance(rect, dict)
                or not isinstance(rect.get("x"), (int, float))
                or not isinstance(rect.get("y"), (int, float))
            ):
                raise CdpDriverError(
                    f"셀렉터 미발견 — 클릭 좌표 실패(fail-closed): {selector}"
                )
            base = {"x": rect["x"], "y": rect["y"], "button": "left", "clickCount": 1}
            self._cmd("Input.dispatchMouseEvent", {"type": "mousePressed", **base})
            self._cmd("Input.dispatchMouseEvent", {"type": "mouseReleased", **base})
        finally:
            self._set_auto_flag(False)

    def _select_option(self, selector: str, value: str) -> None:
        """``<select>`` 옵션 선택 — 텍스트 입력에는 사용 금지(결함 ① 참조)."""
        if self._evaluate(_select_js(selector, value)) is not True:
            raise CdpDriverError(
                f"셀렉터 미발견 — 선택 실패(fail-closed): {selector}"
            )

    # ── 입력/검색 실행 ─────────────────────────────────────────────────

    def run_rps_search(self, boolean_query: str) -> int:
        """(a) — RPS Keywords 필드에 Boolean 문자열 입력(신뢰 입력) → 검색
        실행(Enter) → 로드 대기 → 결과건수 읽기. 숫자를 못 읽으면 fail-closed."""
        if not isinstance(boolean_query, str) or not boolean_query.strip():
            raise CdpDriverError("RPS Boolean 문자열이 비어 있다(fail-closed)")
        self._insert_text(RPS_KEYWORDS_SELECTOR, boolean_query)
        self._press_enter(RPS_KEYWORDS_SELECTOR)
        self.wait_for_load()  # 결함 ② — 검색 실행 후 결과 로드 완료까지 대기
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

    def apply_rps_filters(self, payload: Mapping[str, Any]) -> None:
        """결함 ① — 지역·대학·경력 필터를 "전달"이 아니라 실제 입력 시퀀스로
        적용한다(각 값: 신뢰 입력 + Enter 확정)."""
        location = payload.get("location")
        if isinstance(location, str) and location.strip():
            self._insert_text(RPS_LOCATION_SELECTOR, location)
            self._press_enter(RPS_LOCATION_SELECTOR)
        for university in payload.get("universities") or ():
            if not isinstance(university, str) or not university.strip():
                raise CdpDriverError(
                    f"대학 필터 값 형식 위반(fail-closed): {university!r}"
                )
            self._insert_text(RPS_SCHOOL_SELECTOR, university)
            self._press_enter(RPS_SCHOOL_SELECTOR)
        required = payload.get("required_filters") or {}
        min_years = required.get("min_years") if isinstance(required, Mapping) else None
        if min_years is not None:
            self._insert_text(RPS_YEARS_MIN_SELECTOR, str(min_years))
            self._press_enter(RPS_YEARS_MIN_SELECTOR)

    def run_descriptor(self, descriptor: Mapping[str, Any]) -> None:
        """(b) — 사람인/잡코리아 디스크립터: URL 이동(로드 대기) → 입력 단계
        실행 → 검색 실행 → 로드 대기.

        스텝 종류(kind): "text"(기본) = 신뢰 입력(Input.insertText, 다중 값은
        값마다 Enter 로 칩 확정), "checkbox" = 마우스 클릭 시퀀스(결함 ②),
        "select" = ``<select>`` 옵션 선택. 모든 스텝 후 첫 텍스트 스텝 셀렉터에
        Enter 로 검색을 실행한다.
        """
        url = descriptor.get("url")
        if not isinstance(url, str) or not url:
            raise CdpDriverError(f"디스크립터 url 이 비어 있다: {descriptor!r}")
        self.navigate(url)  # 내부에서 로드 완료 대기(결함 ②)
        steps = sorted(descriptor.get("steps") or [], key=lambda s: s["order"])
        for step in steps:
            kind = step.get("kind", "text")
            values = step.get("values") or []
            if kind == "checkbox":
                self._click(step["selector"])  # 결함 ② — 클릭 이벤트 시퀀스
                continue
            if kind == "select":
                for value in values:
                    self._select_option(step["selector"], str(value))
                continue
            if kind != "text":
                raise CdpDriverError(f"미지 스텝 kind(fail-closed): {kind!r}")
            multi = len(values) > 1
            for value in values:
                self._insert_text(step["selector"], str(value))
                if multi:  # 칩형 입력 — 값마다 Enter 로 확정
                    self._press_enter(step["selector"])
        submit_step = next(
            (s for s in steps if s.get("kind", "text") == "text"), None
        )
        if submit_step is not None:
            self._press_enter(submit_step["selector"])  # 검색 실행
            self.wait_for_load()  # 결함 ② — 검색 결과 로드 완료까지 대기

    def execute_search(self, search_payload: Mapping[str, Any]) -> None:
        """오케스트레이터 search_payload(2차 결함 9 규격)를 채널별로 실행."""
        channel = search_payload.get("channel")
        if channel == LINKEDIN_CHANNEL:
            # 결함 ① — 필터(지역·대학·경력)를 실제 적용한 뒤 Boolean 검색 실행.
            self.apply_rps_filters(search_payload)
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
        # 결함 ④b — 페이지 이동이므로 감시 스크립트 재설치 대상.
        self._observers_installed = False
        # 결함 ②/⑧ — 다음 페이지 로드 완료 전에는 어떤 읽기도 하지 않는다.
        self.wait_for_load()

    def fetch_list_page(
        self, channel: str, page: int, search_payload: Mapping[str, Any]
    ) -> dict:
        """AC-3 fetch_list_page(channel, page, payload) 계약 구현.

        1페이지 = 검색 실행(즉시 실행 가능한 payload 그대로), 2페이지부터는
        "다음 페이지" 클릭. 모든 이동은 로드 완료 대기 후에만 읽는다(결함 ②).
        항상 {url, content, detail_refs, has_next} 반환.
        """
        if not isinstance(page, int) or page < 1:
            raise CdpDriverError(f"page 는 1 이상 정수여야 한다: {page!r}")
        if page == 1:
            self.execute_search(search_payload)
        else:
            self.goto_next_page(channel)
        url = self.current_url()
        # 5차 결함 ① — 상세 열람 후 복귀 지점으로 목록 URL 을 기억한다.
        self._last_list_url = url
        return {
            "url": url,
            "content": self.capture_html(),
            "detail_refs": self.list_detail_refs(channel),
            "has_next": self.has_next_page(channel),
        }

    def fetch_detail_page(self, channel: str, ref: str) -> dict:
        if not isinstance(ref, str) or not ref:
            raise CdpDriverError(f"상세 ref 가 비어 있다(fail-closed): {ref!r}")
        self.navigate(ref)  # 내부에서 로드 완료 대기(결함 ②/⑧)
        # V1 독립검증 결함1 — 캡처 전에 "이 상세페이지" 상태로 차단신호를 확인한다.
        # 목록 페이지 복귀 후에만 검사하면 상세페이지의 캡차/2FA 화면이 그대로
        # 후보 데이터로 저장된다. human_input 은 여기서 판단하지 않는다(signal만).
        block_events = [e for e in self.poll_events() if e.get("type") == "signal"]
        if block_events:
            if self._last_list_url:
                self.navigate(self._last_list_url)  # 내부에서 로드 완료 대기
            raise DetailPageBlocked(block_events)
        content = self.capture_html()
        # 5차 결함 ① — 상세 프로필은 현재 탭으로 열므로, 캡처 후 반드시 목록
        # 페이지로 복귀(로드 대기 포함)해야 '다음 페이지' 컨트롤을 목록 화면
        # 기준으로 찾을 수 있다(20페이지 순회 지속).
        if self._last_list_url:
            self.navigate(self._last_list_url)  # 내부에서 로드 완료 대기
        return {"url": ref, "content": content}

    # ── (d) 사람 입력/캡차 폴링 → InterventionMonitor 이벤트 공급 ────────

    def install_observers(self) -> None:
        """페이지 컨텍스트에 사람 입력 카운터 리스너를 설치한다(멱등).

        결함 ④a — 자동 입력 표식(``__vh_auto_input_active``)이 켜져 있는 동안의
        입력은 세지 않는다(자동화 입력을 사람 입력으로 오인 금지).
        """
        self._evaluate(
            "/*vh:observe*/(function(){"
            f"if(window.{_OBSERVER_KEY}!==undefined)return true;"
            f"window.{_OBSERVER_KEY}=0;"
            "['mousedown','keydown','wheel','touchstart'].forEach(function(t){"
            "window.addEventListener(t,function(){"
            f"if(window.{_AUTO_FLAG_KEY})return;"
            f"window.{_OBSERVER_KEY}++;"
            "},{capture:true,passive:true});});return true;})()"
        )
        self._observers_installed = True
        self._last_human_inputs = 0  # 새 페이지 컨텍스트 — 카운터 기준 리셋

    def poll_events(self) -> list[dict]:
        """intervention.feed_driver_events 규격 이벤트 목록을 돌려준다.

        - 사람 입력 카운터 증가 → {"type": "human_input"}
        - 캡차/클라우드플레어/2FA/체크포인트/멀티세션 감지 → {"type": "signal"}
          (결함 ④c — 전부 BLOCKED 유도 신호)
        - 감시 스크립트 소실(present=false, 결함 ④b) → 자동 재설치
        - 스냅샷 형식 위반 → 차단 신호(driver_snapshot_invalid) — E8 fail-closed.
        """
        if not self._observers_installed:
            self.install_observers()
        snapshot = self._evaluate(
            "/*vh:snapshot*/(function(){return{"
            f"h:(window.{_OBSERVER_KEY}||0),"
            f"present:(window.{_OBSERVER_KEY}!==undefined),"
            f"captcha:{_CAPTCHA_PROBE_JS},"
            f"cloudflare:{_CLOUDFLARE_PROBE_JS},"
            f"twofa:{_TWOFA_PROBE_JS},"
            f"checkpoint:{_CHECKPOINT_PROBE_JS},"
            f"multisession:{_MULTISESSION_PROBE_JS}"
            "};})()"
        )
        bool_fields = (
            "present",
            "captcha",
            "cloudflare",
            "twofa",
            "checkpoint",
            "multisession",
        )
        if (
            not isinstance(snapshot, dict)
            or not isinstance(snapshot.get("h"), int)
            or isinstance(snapshot.get("h"), bool)
            or not all(isinstance(snapshot.get(f), bool) for f in bool_fields)
        ):
            return [
                {
                    "type": "signal",
                    "kind": f"driver_snapshot_invalid:{snapshot!r}",
                }
            ]
        events: list[dict] = []
        if snapshot["present"]:
            human_inputs = snapshot["h"]
            if human_inputs > self._last_human_inputs:
                events.append({"type": "human_input"})
            self._last_human_inputs = max(self._last_human_inputs, human_inputs)
        else:
            # 결함 ④b — 이동으로 감시 스크립트가 소실됐다: 즉시 재설치.
            # 소실 스냅샷의 카운터(0)는 사람 입력 판단에 쓰지 않는다.
            self.install_observers()
        for field, kind in (
            ("captcha", "captcha"),
            ("cloudflare", "cloudflare"),
            ("twofa", "2fa"),
            ("checkpoint", "checkpoint"),
            ("multisession", "multisession"),
        ):
            if snapshot[field]:
                events.append({"type": "signal", "kind": kind})
        return events
