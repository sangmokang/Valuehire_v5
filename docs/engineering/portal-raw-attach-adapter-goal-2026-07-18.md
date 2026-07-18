# Goal — raw CDP → playwright-page 어댑터 (TODO-2b 대공사 조각 B1, 2026-07-18)

- 모드: code-change / 위험등급: **L3**(포털 검색 실행부 인프라 — 사장님 세션 attach 전제)
- 워크트리: `/Volumes/SSD/Valuehire_v5-portal-channel-cdp-endpoint` (조각 A·마커검증과 같은 브랜치 — V1·V2 "묶어라")

## 현재 상태 (직접 확인)
- SOT-26 INV5(`docs/sot/26-portal-login-spec.json:23-28`): 사장님 크롬 탭 수백개면 playwright
  `connectOverCDP` 전체 attach 가 hang → **목표 탭 1개에만 raw CDP WebSocket** 직접 attach.
- 그러나 검색 실행부(`portal_worker.py` run_one_search·_apply_filters·_collect_cards 등)가
  playwright page API 에 얽힘: page.locator(7)·goto(1)·wait_for_timeout(3)·on(2)·url,
  locator.count(5)·fill(3)·click(1)·first(1)·inner_text(2).
- `raw_cdp.CDPTab`(raw_cdp.py:110): send/eval(Runtime.evaluate)/navigate/screenshot 제공 —
  locator/fill/click 없음. 그래서 검색부를 raw 위에서 돌리려면 **어댑터**가 필요.

## 계약 (SDD — 어댑터 인터페이스)
`raw_page_adapter.py`: raw_cdp.CDPTab 을 감싸 검색부가 쓰는 playwright 표면만 제공.
```
class RawLocator:
  def __init__(tab, selector, index=0)
  async def count() -> int              # querySelectorAll(sel).length
  async def fill(value)                 # el[index].value=value + input/change 이벤트 dispatch
  async def click()                     # el[index].click()
  async def inner_text() -> str         # el[index].innerText
  @property first -> RawLocator         # index=0 고정
class RawPage:
  def __init__(tab)
  def locator(selector) -> RawLocator
  async def goto(url, wait_until=?, timeout=?)   # tab.navigate
  async def wait_for_timeout(ms)
  @property url -> str                  # location.href (동기 캐시 or eval)
  def on(event, handler)                # 조각 B1 은 no-op(모니터는 조각 B2)
```
- selector·value 는 반드시 JSON 직렬화로 이스케이프(injection·따옴표 안전).
- eval 은 tab.eval(=Runtime.evaluate returnByValue) 1회 왕복으로. 주입 tab 으로 라이브 분리 테스트.

## 인수 기준 (EARS + 검증)
- WHEN locator("#x").count() THEN tab.eval 이 querySelectorAll('#x').length 를 평가하고 그 int 반환.
- WHEN locator("#k").fill("hi") THEN 그 요소 value="hi" 설정 + input/change 이벤트 dispatch 되는 JS 가 eval 됨.
- WHEN locator(sel).click() THEN 그 요소 .click() 이 eval 됨.
- WHEN "선택자'\"위험" 처럼 따옴표 든 selector THEN 이스케이프돼 깨진 JS 안 만듦(injection 방지).
- WHEN inner_text() THEN el.innerText 반환.
- counter-AC: 매칭 요소 없으면 count()=0, fill/click 은 조용히 no-op(예외 안 던짐) 또는 명시적 실패 — 계약 확정.
- 검증: `.venv/bin/python -m pytest tests/test_raw_page_adapter.py -q` exit 0 + `./verify.sh` exit 0.

## 비범위 (다음 조각)
- 조각 B2: start() saramin/jobkorea 를 find_verified_channel_endpoint + raw 단일탭 attach +
  RawPage 로 이행(run_one_search 가 RawPage 로 그대로 돌게). page.on 모니터(재로그인 감지) 배선.
- 조각 B3: 실크롬 라이브 검증(사람인 검색 1건, 세션 보존) — 사장님 입회.

## 적대 검증 로그
- `portal-raw-attach-adapter.verdict.json` 참조.
