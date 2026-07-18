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

## 조각 B2 완결 계약 (2026-07-18, PR #149)

전역 기본을 바꾸면 `portal_login`·스냅샷·복구가 요구하는 Playwright context가 깨진다.
따라서 실제 운영 소비자는 `portal_live_check.run_profile_only_live_search` 한 경로만
`connection_mode="raw_single_tab"`으로 opt-in 한다. 기존 guarded/login/snapshot 경로는
이 PR의 비범위이며 기존 persistent-context 동작을 보존한다.

입력 도메인:

| 입력 | 허용 | 결과 |
|---|---:|---|
| `connection_mode="persistent_context"` | 예 | 기존 Playwright 경로 그대로 |
| `connection_mode="raw_single_tab"`, 보호 포털 3사 | 예 | 기존 exact target 1개만 raw attach |
| `type != "page"` | 아니오 | 후보에서 제외 |
| `notsaramin.co.kr` 같은 부분문자열 룩얼라이크 | 아니오 | exact host 규칙으로 제외 |
| 대상 사이트 target 없음/죽은 endpoint | 아니오 | `LookupError`, 새 창·새 탭 fallback 없음 |

결정 표:

| 상황 | attach | 브라우저/탭 생성 | 종료 |
|---|---:|---:|---|
| raw 검색 성공 | exact target 1개 | 0 | WebSocket+배지만 해제, 탭/창은 유지 |
| raw 발견 실패 | 0 | 0 | fail-closed |
| persistent 기본 | 기존 계약 | 기존 계약 | 기존 계약 |

추가 인수 기준:

- RawLocator는 생산 호출면 `nth/get_attribute/press`를 지원하여 카드가 조용히 0건으로
  유실되지 않는다.
- `RawPage.url`은 문자열 property이며, fresh URL 확인은 별도 async read로 로그인
  리다이렉트를 검출한다.
- Playwright `timeout=45000`은 raw `navigate(wait_ms=45000)`로 전달하지 않는다.
- `find_verified_channel_target`은 endpoint와 exact target을 한 번에 반환하여 재탐색
  TOCTOU를 만들지 않는다.
- 실브라우저 쓰기 검증은 이번 턴에 하지 않는다. mock end-to-end에서 전체 브라우저
  연결, 새 탭 생성, 브라우저·탭 파괴가 모두 0임을 먼저 증명한다.

## 적대 검증 로그
- `portal-raw-attach-adapter.verdict.json` 참조.

## 최종 생산 완결 정정 (2026-07-18)

조각 B2까지 같은 PR에서 배선되어 어댑터는 더 이상 고아가 아니다.
`run_profile_only_live_search → PortalWorker(raw_single_tab) → RawPage/RawLocator`가 실제
생산 호출 경로다. `nth/get_attribute/press`, fresh URL/event bridge, 비차단 attach/navigation,
exact lifecycle, cancellation-safe handoff까지 포함한다.

`require_badge=True`에서는 legacy fresh-ID fallback이 없다. 브라우저 Overlay로 실제 합성된
marker를 full-viewport PNG에서 challenge color/좌표로 증명하고, label의 ASCII slug+SHA-256
축약을 immutable custom-element tag에 넣는다. 성공 proof의 resolved object는 실제
fill/click/press/navigation까지 유지되며 동일 object에서 identity/URL/visibility/selector와
행동을 한 `Runtime.callFunctionOn`으로 실행한다. proof 동안 owner가 돌아오는 경우를 위해
mutation 직전 canonical guard를 재실행한다. reproof/action 실패는 stale overlay를 지우고
uncertain state와 lease를 보존한다.

종료는 DOM marker와 Overlay의 exact clear acknowledgement 후 raw WebSocket만 닫는다.
Chrome·profile·context·page target·로그인 session은 닫거나 삭제하지 않는다.
