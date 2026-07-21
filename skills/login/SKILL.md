---
name: login
description: "사람인·잡코리아·LinkedIn 로그인 준비, 기존 CDP 브라우저 재사용, 사람 개입 보호, 창·탭 증식 방지, 로그인 세션 보존·수명 측정·안전한 유지가 필요한 모든 작업에서 사용한다. Claude, Codex, Hermes 공용."
---

# Login — 3사 브라우저 로그인·세션 보존 표준

이 스킬은 macOS와 명시적으로 위임된 WinPC에서 사람인, 잡코리아, LinkedIn Recruiter/RPS를 여는 모든 작업의 선행 절차다.
Claude, Codex, Hermes는 검색·프로필 열람·포지션 등록보다 먼저 이 스킬을 적용한다. WinPC는 현재 턴에 사장님이 실행 기기를 명시한 경우에만 기존 로그인 세션을 사용하며 idle 기반 자동 재개를 하지 않는다. 그 밖의 운영체제나 위임 없는 WinPC 실행은 `HUMAN_ACTIVE`로 중단하고 macOS와 같은 안전성을 주장하지 않는다.

정본 우선순위(앞의 문서가 뒤의 문서보다 우선한다):
- 기계 판독 안전계약: `skills/login/browser-control-contract.json`
- 사람용 실행 프롬프트: 이 `SKILL.md`
- 로그인 판정과 차단 신호: `docs/sot/26-portal-login-spec.json`
- 참고만 하는 과거 기록: `docs/ai-search/portal-login-live-search-runbook-2026-06-17.md`
- 관리 브라우저 프로세스·endpoint 조회: `scripts/portal_browsers.sh status|cdp`
- 기존 탭 단일 연결·표시: `tools/multi_position_sourcing/raw_cdp.py`
- 사람 활동 감지: `tools/multi_position_sourcing/owner_activity.py`

과거 기록이나 기존 코드가 이 스킬/안전계약과 충돌하면 과거 기록을 따르지 않는다.

## 0. 절대 규칙

아래 규칙은 권고가 아니라 중단 조건이다.

1. 먼저 찾고, 로그인 흐름에서는 새로 열지 않는다. 실행 중인 브라우저, CDP endpoint, 영속 프로필, 대상 사이트 탭을 조사해 정확한 기존 target만 사용한다.
2. 기존 브라우저와 로그인된 탭을 최우선으로 재사용한다. 정확한 대상 탭 하나에 raw CDP로 연결한다.
3. 사람이 키 입력, 마우스 조작, 로그인, captcha/2FA/checkpoint 해결을 하는 동안 AI의 click/type/navigate/close는 0회다. 읽기 전용 상태 확인만 허용한다.
4. 사람이 만든 로그인 세션을 소유권과 무관하게 보존한다. 로그인 성공 후 창을 닫지 않는다. 탭을 닫지 않는다. 프로필을 삭제하지 않는다.
5. CDP 연결 해제와 브라우저 종료를 구분한다. 작업 종료 시 WebSocket만 끊는다. `context.close()`, `browser.close()`, `page.close()`, Chrome kill, `scripts/portal_browsers.sh stop|restart`를 호출하지 않는다.
6. 로그인 흐름은 창과 탭을 생성하지 않는다. 기존 브라우저의 정확한 CDP target만 재사용하며 새 창 0개, 새 탭 0개다. 대상 탭이 없으면 임의 페이지를 만들지 말고 정확한 브라우저·프로필·endpoint 정보와 함께 중단한다.
7. 보안 챌린지는 자동 우회하지 않는다. captcha, 2FA, checkpoint, 이상 접근은 즉시 사람에게 넘기고 같은 제출을 반복하지 않는다. LinkedIn 세션 충돌·multiple-sign-in은 사람 인증 인계가 아닌 terminal `AUTH_CONFLICT`로 즉시 중단한다.
8. 비밀번호, 쿠키, 토큰, 세션 저장값은 출력·복사·문서화하지 않는다. 저장 자격증명 입력은 검증된 로그인 실행기가 맡는다.
9. AI가 붙은 탭에는 `vh-automation-badge`를 표시한다. 표시 실패 시 몰래 조작하지 말고 AI_ATTACHED 진입을 보류한다.
10. 로그인 성공은 URL 추측이 아니라 사이트별 로그인 마커로 증명한다. 증명 전에는 검색을 시작하지 않는다.

### LinkedIn RPS 단일 세션 보존 (`SESSION_CONTEXT_PRESERVATION`, #156)

- LinkedIn Recruiter는 한 좌석의 세션이 여러 Chrome 프로필에서 서로를 로그아웃시킬 수 있다. 관리용
  Chrome만 보지 말고, 알려진 Chrome 프로필·endpoint에서 이미 인증된 RPS target이 있는지 먼저 읽는다.
  다른 프로필의 RPS 세션 신호가 있으면 `AUTH_CONFLICT`로 중단하며 두 번째 프로필에서 로그인하지 않는다.
- 정확한 기존 target에서 로그인 마커가 이미 참이면 로그인 관련 mutation은 **0회**다. 로그인 URL 이동,
  자격증명 제출, 새 브라우저·새 창·새 탭 생성, 다른 프로필 전환을 하지 않고 같은 target에서 원래 작업만 재개한다.
- `enterprise-authentication/sessions`, `multiple sign-ins`, `Only one session`은 `AUTH_LOST`가 아니라
  terminal `AUTH_CONFLICT`다. 자동 로그인·Continue/Confirm 클릭·세션 종료 선택·reload/navigation retry를
  하지 않는다. 사람이 한 번 해결한 같은 실행에서 재발해도 두 번째 로그인 인계를 만들지 않고 영구 중단한다.
- Recruiter 결과의 bare `profile_url`은 저장·중복제거 식별자일 뿐이다. 프로필 이동은 검색 결과 DOM에서
  수확한 query 포함 원본 `navigation_url`을 그대로 쓰며, 이동 직후 차단 검사를 추출·스크린샷·저장보다 먼저 한다.

## 1. 상태기계

한 번에 정확히 한 상태만 유지한다. 상태를 건너뛰지 않는다.

| 상태 | 뜻 | 허용 행동 | 전이 조건 |
|---|---|---|---|
| `DISCOVER` | 브라우저·CDP·탭·프로필 조사 중 | 프로세스/endpoint/`/json/list` 읽기 | 대상 탭과 사람 활동 판정 완료 |
| `HUMAN_ACTIVE` | 사장님이 3사 포털 화면을 만지는 중(크롬 활성 탭이 3사 도메인 + 최근 입력) | 무조작, 상태 읽기, 대기 | OS idle 60초 이상 또는 명시적 양보. 단 로그인 개입 중이면 `HUMAN_AUTH` 우선 |
| `AI_ATTACHED` | AI가 기존 탭 하나에 연결하고 배지 표시 | 해당 탭만 조작, 사람 인증 인계 시 정확한 창 1회 표면화 | 로그인 필요→자동 로그인, 챌린지→`HUMAN_AUTH`, 세션충돌→`AUTH_CONFLICT`, 성공→`AUTHENTICATED` |
| `HUMAN_AUTH` | 사람이 로그인/보안 챌린지 처리 중 | 무조작, 5초 이상 간격의 읽기 전용 로그인 마커 확인 | 로그인 마커 확인 + 마지막 키 입력/마우스 활동 후 15초 조용함 |
| `AUTHENTICATED` | 사이트별 로그인 증명 완료 | 증거 기록, 원래 작업 시작 | 사람인·잡코리아 15분/링크드인 30분 경과→`KEEPALIVE`, 로그아웃 신호→`AUTH_LOST` |
| `KEEPALIVE` | 세션 수명 연장을 위한 안전 확인 | 검증된 읽기 전용 링크 1회 클릭 후 동일 탭의 이전 history entry로 Browser Back | 원래 URL·로그인 마커 재확인→`AUTHENTICATED`, 실패→`AUTH_LOST` |
| `AUTH_LOST` | 로그인 마커 소실/로그인 화면 전환 | 자동 로그인 1회 또는 사람 인계 | 성공→`AUTHENTICATED`, 챌린지→`HUMAN_AUTH` |
| `AUTH_CONFLICT` | LinkedIn 단일좌석 세션 충돌 | 읽기 전용 증거 기록 후 영구 중단 | terminal; 자동 로그인·확인 클릭·재표면화·재시도 0회 |
| `HANDOFF` | 사람에게 안전하게 넘김 | guard 허용 시 title/배지 복원, 아니면 cleanup pending; CDP 연결만 해제 | 종료. 브라우저·창·탭·프로필은 유지 |

### 사람 점유 판정

- 자동 작업 전 `tools.multi_position_sourcing.owner_activity.detect_owner_activity_snapshot()`의 OS idle 신호를 확인한다.
- (2026-07-20 사장님 지시) 사장님 개입은 **크롬 활성 탭이 3사(사람인·잡코리아·링크드인) 도메인일 때만** 인정한다 — 유튜브 등 다른 화면 사용은 개입이 아니므로 양보하지 않는다. 3사 화면에서 최근 입력으로 idle이 60초 미만이면 `HUMAN_ACTIVE`다. 판정에는 앞창 앱 이름·OS idle·활성 탭 **호스트(도메인)** 만 읽는다 — 페이지 내용·전체 URL·키입력은 보지도 기록하지도 않는다.
- 감지 실패·권한 부족·값 없음은 fail-closed 한다(단 탭 호스트 판독 실패는 idle 60초 유계 대기 — 무기한 아님).
- 일반 작업은 60초 idle 후 자동 재개할 수 있다(로그인 우선순위 최상 — 3사 화면을 만지던 중이라도 60초 뒤 자동 로그인). 그러나 AI가 보안 챌린지를 사람에게 넘긴 `HUMAN_AUTH` 상태는 임의 시간초과로 닫거나 재개하지 않는다.
- `HUMAN_AUTH`에서 로그인 마커가 나타나도 즉시 클릭하지 않는다. 마지막 사람 활동 뒤 최소 15초 조용함을 확인한 후 `AUTHENTICATED`로 전이한다.
- 대기 중에는 같은 창을 앞으로 가져오지 않는다. 챌린지를 처음 사람에게 넘기기 직전 `AI_ATTACHED`에서만 정확히 해석된 창을 한 번 보여주고, `HUMAN_AUTH` 진입 후 focus/focus_again은 0회다.

### 로그인할 창·페이지를 정확히 표시

사람에게 인증을 넘기기 전에 정확한 CDP target과 macOS 창을 다음 순서로 1:1 결합한다.

1. 관리된 site endpoint를 가진 **정확한 기존 Chrome 프로세스**의 명령행에서 `--remote-debugging-port`, `--user-data-dir`, browser PID를 결합한다. macOS `ps -o command=`가 argv 따옴표를 보존하지 않으므로 다음 ` --flag` 경계까지를 값으로 읽어 공백 포함 profile path를 자르지 않는다. page target WebSocket의 `SystemInfo.getProcessInfo`에 PID를 묻거나 포트를 추측하지 않는다. 같은 endpoint/profile을 주장하는 루트 프로세스가 0개 또는 여러 개면 중단한다.
2. 그 endpoint의 정확한 기존 target id와 `Browser.getWindowForTarget` bounds를 읽고, 스킬 폴더 기준 상대 경로 `scripts/macos_window_locator.swift`를 실행한다. 먼저 title marker 없이 **같은 PID + CDP bounds**로 현재 Space 밖 창까지 포함해 유일한 CGWindowID를 preflight한다. 0개이거나 여러 개면 어떤 title·배지·focus도 보내지 않고 fail-closed 한다.
3. 인계 직전 해당 target에만 `[LOGIN HERE][<agent>][<site>][<target-id-suffix>]` **title prefix**와 `vh-automation-badge`를 붙인다. 비활성 탭의 `document.title`은 OS 창 제목에 아직 반영되지 않으므로 fresh guard 뒤 `Page.bringToFront`를 먼저 1회 실행하고, 그 다음 **같은 PID + 같은 bounds + prefix marker**로 다시 해석한 CGWindowID가 preflight와 같은지 확인한다. 이어 PID-bound `NSRunningApplication.activate`를 fresh guard 뒤 1회 실행하고, 활성화 후 같은 CGWindowID가 on-screen이면서 전역 최상단 layer-0 창인지 증명한다. title `contains`나 첫 창 fallback은 금지다.
4. 사용자에게 agent, site, 브라우저 PID, profile path, CDP endpoint, target id 끝자리, 정제한 title, query/fragment를 제거한 URL, CGWindowID, 앱 활성화 증거를 반드시 표시한다.
5. 스크린샷이 필요하면 전체 화면이 아니라 `screencapture -x -l <CGWindowID>`로 그 창만 캡처한다. 다른 PID의 창 제목은 출력하거나 캡처하지 않는다. 0700 임시 디렉터리와 0600 PNG 삭제가 실패하면 성공으로 숨기지 않고 fail-closed 한다.
6. `HUMAN_AUTH` 진입 후에는 5초 이상 간격으로 fresh 로그인 마커와 OS idle만 읽는다. 시간제한은 없으며, 성공 마커, `owner_activity_detected=false`, 마지막 사람 입력 후 15초 조용함이 모두 성립해야 재개한다.

### 세 에이전트 공용 점유권

Claude, Codex, Hermes가 동시에 같은 사이트를 다루지 못하게 `DISCOVER`보다 먼저 사이트별 점유권을 잡는다.

- 경로: `~/.valuehire/browser_locks/login-<site>.lock`
- 획득: 원자적 디렉터리 생성(`mkdir`)이 성공한 한 실행만 소유자다. 소유자 토큰과 PID를 내부 파일에 기록한다.
- 점유권을 얻지 못하면 브라우저·탭 생성과 CDP 조작을 0회로 유지하고 기다린다. 기존 lock을 자동 삭제하거나 빼앗지 않는다.
- lock이 낡아 보여도 자동 제거하지 않는다. 기록된 프로세스와 실제 브라우저 작업이 모두 끝났음을 사람이 확인한 경우에만 정리한다.
- 소유자는 `HANDOFF`까지 lock을 유지하고, 종료 시 자기 토큰이 일치할 때만 제거한다.
- target attach 직전에도 자기 토큰을 다시 확인한다. 탭이 없으면 생성하지 않고 `HANDOFF`한다.

### 모든 변경 조작 직전 장벽

최초 점검만으로는 부족하다. AI가 붙은 뒤 사람이 타이핑을 시작할 수 있으므로 navigate/click/type/submit 등 모든 변경 조작 직전에 아래를 매번 반복한다.

1. 사이트 점유권 토큰이 아직 자기 것인지 확인한다.
2. 사장님 개입 신호를 읽는다 — 크롬 활성 탭이 3사 도메인이면 OS idle 60초 이상인지 확인한다(3사 아님이 확정이면 idle 무관 통과).
3. 1초 동안 아무 조작 없이 기다린다.
4. 같은 신호를 두 번째 읽어 판정이 유지되는지(idle 증가 중) 확인한다.
5. 두 검사와 토큰이 모두 유효할 때 변경 조작 딱 1회만 실행한다. 다음 조작 전에는 1번부터 다시 한다.

어느 검사든 실패하면 예정된 CDP 명령을 보내지 않고 `HUMAN_ACTIVE`로 전이한다. 감지 실패도 동일하다. 읽기 전용 상태 확인은 허용하지만 navigate, focus, popup-close도 변경 조작으로 취급한다.

## 2. 브라우저 선택 순서

아래 순서를 고정한다. 아래 단계가 성공하면 다음 단계로 가지 않는다.

1. 실행 중인 모든 Chrome/Chromium 프로세스에서 `--remote-debugging-port`와 `--user-data-dir`를 조사한다.
2. 각 살아있는 endpoint의 `/json/list`를 읽고, 정확한 사이트 URL과 로그인 마커가 있는 탭을 찾는다.
3. 로그인된 정확한 탭이 있으면 그 탭 하나에 raw CDP attach한다. 전체 브라우저를 enumerate하는 `connectOverCDP`는 사용하지 않는다.
4. 같은 영속 프로필의 Chrome 프로세스가 살아 있는데 CDP만 잠깐 무응답이면 새 브라우저를 열지 않는다. 기다린 뒤 재확인하며 재실행하지 않는다.
5. 대상 탭이 없으면 새 탭이나 새 창을 만들지 않는다. 정확한 사이트·profile·endpoint가 어떤 것이었는지 보고하고 `HANDOFF`한다.
6. 호환되는 관리 브라우저 프로세스가 없더라도 로그인 흐름이 `start`, 새 브라우저, 새 창, 새 탭을 자동 실행하지 않는다. 기대한 site/profile/endpoint와 `managed_browser_missing`을 보고하고 `HANDOFF`한다. 브라우저 시작은 사업 오너가 별도로 명시한 실행 요청에서만 별도 정식 러너가 수행한다.

포트는 9222/9223/9224/9225로 추측하지 않는다. 다음 명령으로 실제 살아있는 endpoint를 구한다.

```bash
./scripts/portal_browsers.sh status
./scripts/portal_browsers.sh cdp saramin
./scripts/portal_browsers.sh cdp jobkorea
./scripts/portal_browsers.sh cdp linkedin
```

금지:
- 매 시도마다 Chrome 실행
- 로그인 흐름에서 `scripts/portal_browsers.sh start` 자동 실행
- 매 재시도마다 새 탭 생성
- 대상 탭이 없다고 `new_page`/새 탭으로 로그인 페이지 생성
- 같은 프로필로 두 Chrome 실행
- 설정 포트가 죽었다는 이유만으로 로그인 세션 없음 판정
- 한 사이트 로그인 실패 때문에 다른 사이트 창까지 restart

## 3. AI 사용 표시

AI가 조작권을 얻은 대상 탭 하나에만 배지를 붙인다.

```bash
export VH_BUSY_AGENT="Claude"   # Codex 또는 Hermes로 실제 실행 주체를 기록
export VH_BUSY_TASK="login:<saramin|jobkorea|linkedin>"
```

`raw_cdp.attach()`가 화면 상단에 DOM id `vh-automation-badge`를 주입해야 한다. attach의 배지 주입은 기존 코드에서 best-effort이므로, 첫 click/type/navigate 전에 DOM에서 배지 존재를 직접 재확인한다. 배지가 없으면 어떤 변경 조작도 하지 않고 `HANDOFF`한다. 배지 문구에는 실행 주체와 작업을 표시한다. 배지는 클릭을 가리지 않아야 하며 페이지 이동 후 다시 나타나야 한다.

- 배지가 이미 있으면 새 배지를 쌓지 말고 내용만 갱신한다.
- 사람이 조작을 시작하면 AI는 즉시 무조작으로 전환한다. 배지는 `사람 로그인 대기 · AI 무조작`처럼 상태를 바꾼다.
- `HANDOFF`에서는 fresh lease/idle mutation guard가 허용할 때만 원래 title과 배지를 복원하고 CDP WebSocket만 닫는다. 사람이 다시 활동해 cleanup guard가 막히면 UI를 건드리지 않고 `cleanup_pending=true`를 보고한 뒤 WebSocket만 닫는다.
- 로그인된 탭, 창, 브라우저 프로세스는 제거하지 않는다.

## 4. 로그인 실행 순서

대상 채널을 전부 정한 뒤 한 번에 점검한다. 흐름 중간에 사이트마다 뒤늦게 로그인하지 않는다.

1. 세 사이트의 기존 탭과 로그인 마커를 읽기 전용으로 확인한다.
2. 로그인된 채널은 그대로 보존하고 다시 로그인하지 않는다.
3. 로그아웃 채널은 동일한 raw CDP target에서 공식 로그인 화면으로 이동한다. 새 page/context/browser를 만들지 않는다.
4. 저장 자격증명은 실행 프로세스 안에서만 읽고 동일 target의 폼에 1회 제출한다. 비밀값을 stdout, shell 인자, 산출물, 모델 대화에 넣지 않는다.
5. 제출 직후 fresh DOM과 URL을 읽어 보안 챌린지를 먼저 판정한다. captcha/2FA/checkpoint/이상 접근이면 즉시 `HUMAN_AUTH`로 바꾸고 제출·클릭을 멈춘다. LinkedIn 세션 충돌이면 창을 표면화하지 않고 terminal `AUTH_CONFLICT`로 중단한다.
6. 챌린지를 한 번 표면화한 뒤 `HUMAN_AUTH`로 진입한다. `HUMAN_AUTH` 중 navigate/reload/back/click/type/submit/popup-close/close/focus/new-page는 금지다. 현재 URL·fresh 로그인 마커·OS idle을 읽는 것 외에는 하지 않는다.
7. 사람이 해결할 때까지 시간제한 없이 5초 이상 간격으로 읽기 폴링만 한다. 성공 마커와 OS idle 15초를 모두 확인한 뒤 재개한다.

### 현재 저장소에서 금지된 과거 실행기

`tools.multi_position_sourcing.portal_login`은 보존 모드가 아니므로 사용 금지다. 이 실행기는 새 page/context를 만들고 종료 시 page/context를 닫을 수 있으며 LinkedIn에서 전체 `connectOverCDP`를 사용한다. 따라서 이 스킬의 표준 실행기로 호출하면 안 된다.

안전한 로그인 경로는 다음 조건을 모두 충족해야 한다.

- `tools.multi_position_sourcing.raw_cdp`로 기존 target 하나에만 attach
- 브라우저 context·page·새 탭 생성 0회
- `page.close()`, `context.close()`, `browser.close()` 호출 0회
- 사람 개입 대기시간 무제한; 외부 중단 시에도 WebSocket만 해제
- 모든 사람 안내를 쉬운 한국어로 표시

이 조건을 충족하는 자동 로그인 어댑터가 현재 실행환경에서 확인되지 않으면 위험한 과거 실행기로 대체하지 않는다. 기존 세션을 보존하고 동일 탭을 정식 login session guard의 `HUMAN_AUTH`로 넘긴다. 레거시 사람 대기 함수가 `human_auth_runner_required`를 반환하면 이는 중단 신호가 아니라 정확한 target/window 식별을 갖춘 정식 러너로 전환하라는 fail-closed 신호다. “자동 로그인을 했다”고 거짓 보고하지 않는다.

### 정식 session guard 실행기

사람 인증 인계는 legacy login 함수나 즉석 CDP 스크립트가 아니라 다음 정식 진입점으로 실행한다. 실행기는 site lease를 먼저 획득하고, 위 절차로 찾은 기존 target 하나에만 attach한다. 정확한 target이 여러 개면 `--target-id`로 하나를 명시하고, 없으면 만들지 않는다.

```bash
PYTHONPATH=. python3 -m tools.multi_position_sourcing.session_guard human-auth \
  --site linkedin_rps \
  --agent Codex \
  --target-id '<existing-target-id>'
```

이 명령은 lease 충돌이나 `HUMAN_ACTIVE`를 종료 오류로 취급하지 않고 브라우저 무조작 상태로 기다린다. 허용 상태가 되고 일반 로그인·보안 챌린지일 때만 정확한 창을 1회 표시한 뒤 locator JSON을 출력하고, `HUMAN_AUTH` 동안 timeout 없이 읽기 전용으로 기다린다. 세션 충돌이면 창을 표시하지 않고 `AUTH_CONFLICT`로 종료한다. 정상 완료·명시적 stop·Ctrl-C·표시/출력/대기 예외 모두에서 fresh guard로 title/배지 cleanup을 시도하고, 막히면 `cleanup_pending`으로 둔 채 창·탭·프로필은 유지하고 CDP 연결만 해제한다.

세션 유지는 아래 정식 진입점만 쓴다. `--safe-target-json`은 사람이 사전 감사한 정확한 기존 target의 동일 origin·GET·`_self`·무료 읽기 전용 링크 레코드여야 한다. 최소한 `target_id`, `source_url`, `selector`, `destination_url`, `method`, `target_attr`, `download`, `dedicated_tab`, `clean_form`, `previously_opened_free`, `risk_labels`를 담는다. 레코드가 있어도 실행기가 위험 URL/selector denylist, 동일 origin, fresh DOM link 속성, target id, navigation history 추가·복원을 다시 증명한다. 파일이 없거나 값/증명이 하나라도 틀리면 fail-closed SKIP한다.

```bash
PYTHONPATH=. python3 -m tools.multi_position_sourcing.session_guard keepalive \
  --site linkedin_rps \
  --agent Codex \
  --safe-target-json '<pre-audited-safe-target.json>'
```

keepalive는 동일 target의 allowlist 링크 1회 click과 `Page.navigateToHistoryEntry(previous_entry)` Browser Back 왕복만 허용한다. URL·selector는 최대 4회 percent-decode한 표면까지 위험 토큰을 검사하고, 남은 percent triplet은 거부한다. click과 Back의 비동기 이동은 exact target·URL·로그인·history를 연속 2회 안정 확인하며 auth probe 직후 target을 다시 읽는다. 새 탭·새 창·`goto(source_url)` fallback·재시도는 없다.

## 5. 사이트별 결정적 증명

URL 하나만으로 로그인 성공을 선언하지 않는다. fresh DOM에서 아래 증거를 확인한다.

### 사람인

- 기업회원 talent pool: `https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search`
- 성공: 계정명 또는 `로그아웃`이 보이고, 검색 화면에 `input.search_input`, `#career_min`, `#career_max`가 존재한다.
- 실패: 계정명 없이 `로그인 | 회원가입`, 기업회원 auth 화면, 지속되는 tutorial redirect.
- 로그인은 반드시 `ut=c` 기업회원 경로를 사용한다.

### 잡코리아

- 인재검색: `https://www.jobkorea.co.kr/Corp/Person/Find`
- 성공: 헤더에 `로그아웃`과 기업명/계정 신호가 있고 인재검색 화면이 로드된다.
- 실패: `로그인` 링크만 있고 `로그아웃`이 없거나 로그인 폼으로 이동한다.
- 자동 로그인은 기업회원 탭을 선택한 뒤 검증된 실행기가 자격증명을 제출한다.

### LinkedIn

- Recruiter/RPS: `https://www.linkedin.com/talent/`
- 성공: `/talent/` home/search/profile이 login-cap이나 enterprise-authentication으로 이동하지 않고 로드되며, Recruiter 계정/메뉴 마커가 함께 보인다. URL만으로 성공 판정하지 않는다.
- 실패: 일반 로그인, `/uas/login-cap`, authwall, checkpoint.
- `enterprise-authentication/sessions`, `multiple sign-ins`, `Only one session`은 세션 충돌이다. 읽기 전용 증거만 기록하고 `AUTH_CONFLICT`로 중단한다. Continue/Confirm 클릭·자동 로그인·사람 인증 인계·재시도는 모두 금지한다.

차단 단어가 일반 안내문에 우연히 포함될 수 있다. 차단 판정 전 실제 화면과 URL을 읽기 전용으로 한 번 교차 확인한다. 실제 챌린지가 맞으면 자동 우회하지 않는다.

## 6. 로그인 수명 측정과 KEEPALIVE

각 사이트에 대해 비밀값 없이 다음 메타데이터만 메모리 또는 작업 산출물에 기록한다.

```json
{
  "site": "saramin|jobkorea|linkedin",
  "authenticated_at": "ISO-8601",
  "last_verified_at": "ISO-8601",
  "session_age_seconds": 0,
  "last_keepalive_at": "ISO-8601|null",
  "proof": ["login marker names only"],
  "state": "AUTHENTICATED"
}
```

- `authenticated_at`: 이번 실행에서 로그인 마커를 처음 확정한 시각. 기존 세션이면 `first_observed_authenticated_at` 의미로 기록하며 실제 쿠키 생성시각이라고 과장하지 않는다.
- `last_verified_at`: 로그인 마커를 마지막으로 재확인한 시각.
- `session_age_seconds`: 현재 시각과 `authenticated_at`의 차이. 계산값이며 쿠키 만료시간으로 부르지 않는다.
- 쿠키, storage state, 계정 ID, 비밀번호, profile 본문은 이 기록에 넣지 않는다.

KEEPALIVE 규칙:

1. 마지막 로그인 확인 또는 keepalive 후 사람인·잡코리아는 900초(15분), LinkedIn RPS는 1800초(30분) 이상 지났을 때만 검토한다. 과거의 `30분 하나` 공통 주기는 폐기한다.
2. keepalive 직전에 사람 활동을 새로 측정한다. `HUMAN_ACTIVE`, `HUMAN_AUTH`, 감지 실패면 즉시 SKIP한다. 이전에 측정한 idle 값을 재사용하지 않는다.
3. 기본은 SKIP이다. 현재 탭이 AI 전용이고 미저장 폼/dirty 입력이 없으며, 정확한 target id가 유지되고, 동일 origin의 GET 읽기 전용 링크가 검증된 경우만 클릭/Browser Back 왕복을 허용한다.
4. 허용 대상은 이미 정상적으로 무료 열람했던 프로필 상세 또는 talent pool/home 안의 allowlist 링크다. 새 후보, 유료/차감 프로필, `target=_blank`, download, 팝업, 모달, 저장, 제안, InMail, Send는 0회다.
5. 클릭 전 source target id, 정확한 source URL, `Page.getNavigationHistory`의 현재 entry와 이전 entry를 기록한다.
6. 사이트 lease token + OS idle 2회 + 1초 dwell의 새 mutation guard를 통과한 뒤 allowlist 링크를 단 1회 클릭한다.
7. 동일 target id, 예상한 destination URL, fresh 로그인 마커, source→destination history를 **연속 2회** 확인한다. auth probe 직후 target/URL을 다시 읽어 즉시 checkpoint로 redirect된 표본을 성공으로 인정하지 않는다. 하나라도 다르면 성공으로 기록하지 않고 중단한다.
8. 복원 직전 lease/idle mutation guard를 **새로** 통과한 후 `Page.navigateToHistoryEntry(previous_entry)`로 Browser Back한다. `goto(source_url)` fallback과 재시도는 금지다.
9. 클릭 후 사람 활동이 감지되거나 두 번째 guard가 실패하면 Back을 보내지 않고 `restore_pending=true`로 두어 사람에게 양보한다.
10. 동일 target id·정확한 원래 URL·fresh 로그인 마커·원래 history entry가 **연속 2회** 복원된 후에만 `last_verified_at`, `last_keepalive_at`, `session_age_seconds`를 갱신한다.
11. 로그인 화면으로 바뀌면 반복 새로고침하지 않고 `AUTH_LOST`로 전이한다.

KEEPALIVE는 세션 영구 보장을 뜻하지 않는다. 실제로 관찰한 지속시간만 보고한다.

## 7. 종료와 인계

정상 종료 순서:

1. 마지막 로그인 마커와 상태 메타데이터를 기록한다.
2. 진행 중인 사람 입력이 없는지 확인한다.
3. 자동화 배지만 제거한다.
4. raw CDP WebSocket만 닫는다.
5. 브라우저, 창, 탭, 영속 프로필은 그대로 둔다.
6. 다음 작업자에게 사이트별 상태, 실제 endpoint, target id, 마지막 확인시각, 사람 개입 여부만 넘긴다. 비밀값은 넘기지 않는다.

다음 문장이 종료 보고에 있어야 한다.

```text
브라우저 보존: 창/탭/프로필 종료 0건, CDP 연결만 해제
```

## 8. 반례별 즉시 행동

| 상황 | 즉시 행동 |
|---|---|
| 사람이 로그인 폼에 타이핑 중 | `HUMAN_AUTH`; 무조작. 성공 마커 + 15초 조용함까지 대기 |
| 사람이 3사 포털 화면을 만지는 중 | `HUMAN_ACTIVE`; 60초 idle까지 양보 |
| 사람이 유튜브 등 3사 외 화면 사용 중 | 개입 아님 — 양보 없이 진행(2026-07-20 사장님 지시) |
| 로그인 성공 직후 자동화 작업이 끝남 | `HANDOFF`; 배지만 제거하고 창·탭·프로필 유지 |
| CDP 설정 포트 무응답, 같은 프로필 프로세스 생존 | 재실행 금지; 실제 포트 탐색 후 기다림 |
| 탭이 여러 개 있음 | 정확 URL·로그인 마커로 1개 선택; 나머지 닫지 않음 |
| 대상 탭 없음, 기존 브라우저 있음 | 새 탭 0개·새 창 0개; 기대한 site/profile/endpoint를 표시하고 `HANDOFF` |
| captcha/2FA/checkpoint | 앞에 한 번 보여주고 `HUMAN_AUTH`; 자동 우회·재제출 0회 |
| LinkedIn 세션 충돌 | `AUTH_CONFLICT`로 영구 중단; Continue/Confirm·자동 로그인·사람 인증 인계·재시도 0회 |
| 로그인 마커 소실 | `AUTH_LOST`; 자동 로그인 1회, 챌린지면 사람 인계 |
| keepalive 중 유료/저장 모달 | 닫기조차 자동으로 누르지 말고 중단·보고 |

## 9. 세 에이전트 설치

저장소 정본을 세 로컬 스킬 위치에 같은 바이트로 설치한다.

```bash
python3 -m tools.install_login_skill
```

설치 위치:
- Claude: `~/.claude/skills/login/`
- Codex: `~/.codex/skills/login/`
- Hermes: `~/.hermes/skills/login/`

설치기는 `login` 폴더의 정본 트리(`SKILL.md`, `browser-control-contract.json`, `scripts/` 자산)를 사전 검증한 후 세 위치에 같은 바이트로 재귀 설치하며 다른 스킬을 건드리지 않는다. 설치 후 각 에이전트를 새 세션에서 시작해 `login` 발견 여부를 확인한다.

## 10. 실행 전·후 체크리스트

실행 전:
- [ ] `login` 스킬을 읽었다.
- [ ] 사람 활동 판정에 성공했고 최근 입력이면 양보했다.
- [ ] 모든 실행 중 브라우저·실제 CDP endpoint·영속 프로필을 조사했다.
- [ ] 로그인 흐름 전체에서 새 브라우저·새 창·새 탭을 만들지 않았다.
- [ ] AI 배지의 실행 주체와 작업명이 맞다.

실행 후:
- [ ] 사이트별 로그인 마커를 fresh DOM에서 확인했다.
- [ ] `authenticated_at`, `last_verified_at`, `session_age_seconds`를 기록했다.
- [ ] 사람 개입 중 AI 조작은 0회였다.
- [ ] 새 창은 0개이며 새 탭도 0개였다.
- [ ] 브라우저·창·탭·프로필 종료는 0건이다.
- [ ] fresh guard가 허용하면 title/배지를 복원했고, 막히면 `cleanup_pending`을 보고했으며 CDP 연결만 해제했다.

## 11. 다중 기기 운영 패턴 — 주력 PC와 검색 실행기

이 표는 Hermes login preflight가 매 실행마다 읽는 기기 역할 정본이다. 기존 로그인 세션이 있는 host를 새 로그인보다 항상 우선한다.

| 역할 | 현재 기기 | 비고 |
|---|---|---|
| 주력 PC(primary) | Macmini | Discord gateway와 owner 기본 실행기 |
| AI Search 실행기 | Macmini, MacBook Pro, WinPC | live session host 우선, 없으면 표 순서 |
| LinkedIn 주간 | Macmini(주력 PC) | 기존 RPS 세션 우선 |
| LinkedIn 야간 | MacBook Pro 또는 WinPC | 현재 턴 owner 위임이 있을 때만 |
