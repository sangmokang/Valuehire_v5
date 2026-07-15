---
name: login
description: "사람인·잡코리아·LinkedIn 로그인 준비, 기존 CDP 브라우저 재사용, 사람 개입 보호, 창·탭 증식 방지, 로그인 세션 보존·수명 측정·안전한 유지가 필요한 모든 작업에서 사용한다. Claude, Codex, Hermes 공용."
---

# Login — 3사 브라우저 로그인·세션 보존 표준

이 스킬은 macOS에서 사람인, 잡코리아, LinkedIn Recruiter/RPS를 여는 모든 작업의 선행 절차다.
Claude, Codex, Hermes는 검색·프로필 열람·포지션 등록보다 먼저 이 스킬을 적용한다. 다른 운영체제에서는 사람 활동 감지 계약이 없으므로 `HUMAN_ACTIVE`로 중단하고 macOS와 같은 안전성을 주장하지 않는다.

정본 우선순위(앞의 문서가 뒤의 문서보다 우선한다):
- 기계 판독 안전계약: `skills/login/browser-control-contract.json`
- 사람용 실행 프롬프트: 이 `SKILL.md`
- 로그인 판정과 차단 신호: `docs/sot/26-portal-login-spec.json`
- 참고만 하는 과거 기록: `docs/ai-search/portal-login-live-search-runbook-2026-06-17.md`
- 브라우저 실행·중복 방지: `scripts/portal_browsers.sh`
- 기존 탭 단일 연결·표시: `tools/multi_position_sourcing/raw_cdp.py`
- 사람 활동 감지: `tools/multi_position_sourcing/owner_activity.py`

과거 기록이나 기존 코드가 이 스킬/안전계약과 충돌하면 과거 기록을 따르지 않는다.

## 0. 절대 규칙

아래 규칙은 권고가 아니라 중단 조건이다.

1. 먼저 찾고, 나중에 연다. 실행 중인 브라우저, CDP endpoint, 영속 프로필, 대상 사이트 탭을 모두 조사하기 전에는 브라우저나 탭을 만들지 않는다.
2. 기존 브라우저와 로그인된 탭을 최우선으로 재사용한다. 정확한 대상 탭 하나에 raw CDP로 연결한다.
3. 사람이 키 입력, 마우스 조작, 로그인, captcha/2FA/checkpoint 해결을 하는 동안 AI의 click/type/navigate/close는 0회다. 읽기 전용 상태 확인만 허용한다.
4. 사람이 만든 로그인 세션을 소유권과 무관하게 보존한다. 로그인 성공 후 창을 닫지 않는다. 탭을 닫지 않는다. 프로필을 삭제하지 않는다.
5. CDP 연결 해제와 브라우저 종료를 구분한다. 작업 종료 시 WebSocket만 끊는다. `context.close()`, `browser.close()`, `page.close()`, Chrome kill, `scripts/portal_browsers.sh stop|restart`를 호출하지 않는다.
6. 창과 탭을 반복 생성하지 않는다. 기존 브라우저가 있으면 새 창 0개가 원칙이다. 대상 탭이 없을 때만 동일 브라우저에 새 탭 1개까지 허용하며, 생성 직후 다시 목록을 확인한다.
7. 보안 챌린지는 자동 우회하지 않는다. captcha, 2FA, checkpoint, 이상 접근, 세션 충돌, LinkedIn multiple-sign-in 화면은 즉시 사람에게 넘긴다. 같은 제출을 반복하지 않는다.
8. 비밀번호, 쿠키, 토큰, 세션 저장값은 출력·복사·문서화하지 않는다. 저장 자격증명 입력은 검증된 로그인 실행기가 맡는다.
9. AI가 붙은 탭에는 `vh-automation-badge`를 표시한다. 표시 실패 시 몰래 조작하지 말고 AI_ATTACHED 진입을 보류한다.
10. 로그인 성공은 URL 추측이 아니라 사이트별 로그인 마커로 증명한다. 증명 전에는 검색을 시작하지 않는다.

## 1. 상태기계

한 번에 정확히 한 상태만 유지한다. 상태를 건너뛰지 않는다.

| 상태 | 뜻 | 허용 행동 | 전이 조건 |
|---|---|---|---|
| `DISCOVER` | 브라우저·CDP·탭·프로필 조사 중 | 프로세스/endpoint/`/json/list` 읽기 | 대상 탭과 사람 활동 판정 완료 |
| `HUMAN_ACTIVE` | 최근 사람 입력 또는 브라우저 점유 | 무조작, 상태 읽기, 대기 | OS idle 180초 이상 또는 명시적 양보. 단 로그인 개입 중이면 `HUMAN_AUTH` 우선 |
| `AI_ATTACHED` | AI가 기존 탭 하나에 연결하고 배지 표시 | 해당 탭만 조작 | 로그인 필요→자동 로그인, 챌린지→`HUMAN_AUTH`, 성공→`AUTHENTICATED` |
| `HUMAN_AUTH` | 사람이 로그인/보안 챌린지 처리 중 | 무조작, 5초 이상 간격의 읽기 전용 로그인 마커 확인 | 로그인 마커 확인 + 마지막 키 입력/마우스 활동 후 15초 조용함 |
| `AUTHENTICATED` | 사이트별 로그인 증명 완료 | 증거 기록, 원래 작업 시작 | 30분 경과→`KEEPALIVE`, 로그아웃 신호→`AUTH_LOST` |
| `KEEPALIVE` | 세션 수명 연장을 위한 안전 확인 | 읽기 전용 페이지 또는 이미 열었던 프로필 상세 1회 방문 | 로그인 마커 재확인→`AUTHENTICATED`, 실패→`AUTH_LOST` |
| `AUTH_LOST` | 로그인 마커 소실/로그인 화면 전환 | 자동 로그인 1회 또는 사람 인계 | 성공→`AUTHENTICATED`, 챌린지→`HUMAN_AUTH` |
| `HANDOFF` | 사람에게 안전하게 넘김 | 배지 제거, CDP 연결만 해제 | 종료. 브라우저·창·탭·프로필은 유지 |

### 사람 점유 판정

- 자동 작업 전 `tools.multi_position_sourcing.owner_activity.detect_owner_activity_snapshot()`의 OS idle 신호를 확인한다.
- 최근 키 입력 또는 마우스 활동으로 idle이 180초 미만이면 `HUMAN_ACTIVE`다. 브라우저 화면을 훔쳐 읽거나 키로깅하지 않는다.
- 감지 실패·권한 부족·값 없음은 사람이 사용 중인 것으로 보고 fail-closed 한다.
- 일반 작업은 180초 idle 후 자동 재개할 수 있다. 그러나 AI가 보안 챌린지를 사람에게 넘긴 `HUMAN_AUTH` 상태는 임의 시간초과로 닫거나 재개하지 않는다.
- `HUMAN_AUTH`에서 로그인 마커가 나타나도 즉시 클릭하지 않는다. 마지막 사람 활동 뒤 최소 15초 조용함을 확인한 후 `AUTHENTICATED`로 전이한다.
- 대기 중에는 같은 창을 앞으로 가져오지 않는다. 챌린지를 처음 사람에게 넘길 때만 해당 탭을 한 번 보여주고 이후 포커스를 빼앗지 않는다.

## 2. 브라우저 선택 순서

아래 순서를 고정한다. 아래 단계가 성공하면 다음 단계로 가지 않는다.

1. 실행 중인 모든 Chrome/Chromium 프로세스에서 `--remote-debugging-port`와 `--user-data-dir`를 조사한다.
2. 각 살아있는 endpoint의 `/json/list`를 읽고, 정확한 사이트 URL과 로그인 마커가 있는 탭을 찾는다.
3. 로그인된 정확한 탭이 있으면 그 탭 하나에 raw CDP attach한다. 전체 브라우저를 enumerate하는 `connectOverCDP`는 사용하지 않는다.
4. 같은 영속 프로필의 Chrome 프로세스가 살아 있는데 CDP만 잠깐 무응답이면 새 브라우저를 열지 않는다. 기다린 뒤 재확인하며 재실행하지 않는다.
5. 대상 탭이 없고 기존 CDP 브라우저가 안전하게 재사용 가능할 때만 동일 창에 대상 탭 1개를 연다. 열기 전후 탭 수와 target id를 기록하고 두 번째 탭은 만들지 않는다.
6. 호환되는 브라우저 프로세스 자체가 없을 때만 `./scripts/portal_browsers.sh start <saramin|jobkorea|linkedin>`을 대상 채널별로 한 번 실행한다. 인자 없는 `start`는 3사 전체가 명시적으로 필요할 때만 허용한다. 이 스크립트의 프로세스/프로필 중복 가드를 우회하지 않는다.
7. 시작 후 CDP가 바로 응답하지 않아도 start를 반복 호출하지 않는다. 프로세스가 있으면 기다리고, 없고 명확히 실패했을 때만 원인을 보고한다.

포트는 9222/9223/9224/9225로 추측하지 않는다. 다음 명령으로 실제 살아있는 endpoint를 구한다.

```bash
./scripts/portal_browsers.sh status
./scripts/portal_browsers.sh cdp saramin
./scripts/portal_browsers.sh cdp jobkorea
./scripts/portal_browsers.sh cdp linkedin
```

금지:
- 매 시도마다 Chrome 실행
- 매 재시도마다 새 탭 생성
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
- `HANDOFF`에서는 배지를 제거하고 CDP WebSocket만 닫는다.
- 로그인된 탭, 창, 브라우저 프로세스는 제거하지 않는다.

## 4. 로그인 실행 순서

대상 채널을 전부 정한 뒤 한 번에 점검한다. 흐름 중간에 사이트마다 뒤늦게 로그인하지 않는다.

1. 세 사이트의 기존 탭과 로그인 마커를 읽기 전용으로 확인한다.
2. 로그인된 채널은 그대로 보존하고 다시 로그인하지 않는다.
3. 로그아웃 채널은 동일한 raw CDP target에서 공식 로그인 화면으로 이동한다. 새 page/context/browser를 만들지 않는다.
4. 저장 자격증명은 실행 프로세스 안에서만 읽고 동일 target의 폼에 1회 제출한다. 비밀값을 stdout, shell 인자, 산출물, 모델 대화에 넣지 않는다.
5. 제출 직후 fresh DOM과 URL을 읽어 보안 챌린지를 먼저 판정한다. captcha/2FA/checkpoint/이상 접근/세션 충돌이면 즉시 `HUMAN_AUTH`로 바꾸고 제출·클릭을 멈춘다.
6. `HUMAN_AUTH` 중 navigate/click/type/submit/popup-close는 금지다. 현재 URL과 로그인 마커를 읽는 것 외에는 하지 않는다.
7. 사람이 해결하면 동일 탭·동일 프로필에서 로그인 마커를 5초 간격으로 읽기만 한다. 성공 마커와 OS idle 15초를 모두 확인한 뒤 재개한다.

### 현재 저장소에서 금지된 과거 실행기

`tools.multi_position_sourcing.portal_login`은 보존 모드가 아니므로 사용 금지다. 이 실행기는 새 page/context를 만들고 종료 시 page/context를 닫을 수 있으며 LinkedIn에서 전체 `connectOverCDP`를 사용한다. 따라서 이 스킬의 표준 실행기로 호출하면 안 된다.

안전한 로그인 경로는 다음 조건을 모두 충족해야 한다.

- `tools.multi_position_sourcing.raw_cdp`로 기존 target 하나에만 attach
- 브라우저·context·page 생성 0회(대상 탭이 정말 없을 때 허용된 새 탭 1회 제외)
- `page.close()`, `context.close()`, `browser.close()` 호출 0회
- 사람 개입 대기시간 무제한; 외부 중단 시에도 WebSocket만 해제
- 모든 사람 안내를 쉬운 한국어로 표시

이 조건을 충족하는 자동 로그인 어댑터가 현재 실행환경에서 확인되지 않으면 위험한 과거 실행기로 대체하지 않는다. 기존 세션을 보존하고 동일 탭을 `HUMAN_AUTH`로 넘긴다. “자동 로그인을 했다”고 거짓 보고하지 않는다.

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
- `enterprise-authentication/sessions`, `multiple sign-ins`, `Only one session`은 세션 충돌이다. 계속 버튼을 자동 클릭하지 않는다. 다른 머신의 로그인된 세션까지 찾고 사람이 사용할 세션을 결정하게 한다.

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

1. 마지막 로그인 확인 또는 keepalive 후 30분 이상 지났을 때만 검토한다. 주기는 30분 하나만 사용하며 더 자주 실행하지 않는다.
2. keepalive 직전에 사람 활동을 새로 측정한다. `HUMAN_ACTIVE`, `HUMAN_AUTH`, 감지 실패면 즉시 SKIP한다. 이전에 측정한 idle 값을 재사용하지 않는다.
3. 기본 행동은 현재 페이지의 로그인 마커를 읽기만 하고 navigation을 SKIP하는 것이다. 마커가 살아 있으면 클릭하지 않는다.
4. navigation은 현재 탭이 AI 전용 안전 탭이고, 미저장 폼/dirty 입력이 없으며, 유료 차감이 없는 경로임이 모두 확인된 경우만 허용한다. 하나라도 불명확하면 SKIP한다.
5. 허용된 경우에도 이미 이번 작업에서 정상적으로 무료 열람했던 프로필 상세 URL을 1회 방문한다. 새 후보, 유료 프로필, 열람 차감 가능 프로필은 열지 않는다.
6. 검증된 무료 프로필이 없으면 임의 후보를 클릭하지 않는다. AI 전용 안전 탭에서 talent pool/home의 읽기 전용 경로만 1회 방문하거나 SKIP한다.
7. 방문 후 로그인 마커를 다시 확인하고 `last_verified_at`, `last_keepalive_at`, `session_age_seconds`를 갱신한다. 원래 페이지를 복원해야 하는 공유 탭이었다면 처음부터 navigation 조건을 충족하지 못한 것이다.
8. 팝업, 모달, 유료 차감, 저장, 제안, InMail, Send 버튼은 절대 누르지 않는다.
9. 로그인 화면으로 바뀌면 반복 새로고침하지 않고 `AUTH_LOST`로 전이한다.

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
| 사람이 일반 브라우징 중 | `HUMAN_ACTIVE`; 180초 idle까지 양보 |
| 로그인 성공 직후 자동화 작업이 끝남 | `HANDOFF`; 배지만 제거하고 창·탭·프로필 유지 |
| CDP 설정 포트 무응답, 같은 프로필 프로세스 생존 | 재실행 금지; 실제 포트 탐색 후 기다림 |
| 탭이 여러 개 있음 | 정확 URL·로그인 마커로 1개 선택; 나머지 닫지 않음 |
| 대상 탭 없음, 기존 브라우저 있음 | 동일 브라우저에 새 탭 1개만 생성; 새 창 0개 |
| captcha/2FA/checkpoint | 앞에 한 번 보여주고 `HUMAN_AUTH`; 자동 우회·재제출 0회 |
| LinkedIn 세션 충돌 | 계속 클릭 금지; 다른 로그인 머신/세션 탐색 후 사람 결정 |
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

설치기는 `login` 폴더의 `SKILL.md`와 `browser-control-contract.json`만 갱신하며 다른 스킬을 건드리지 않는다. 설치 후 각 에이전트를 새 세션에서 시작해 `login` 발견 여부를 확인한다.

## 10. 실행 전·후 체크리스트

실행 전:
- [ ] `login` 스킬을 읽었다.
- [ ] 사람 활동 판정에 성공했고 최근 입력이면 양보했다.
- [ ] 모든 실행 중 브라우저·실제 CDP endpoint·영속 프로필을 조사했다.
- [ ] 정확한 기존 탭을 찾기 전에 새 브라우저/탭을 만들지 않았다.
- [ ] AI 배지의 실행 주체와 작업명이 맞다.

실행 후:
- [ ] 사이트별 로그인 마커를 fresh DOM에서 확인했다.
- [ ] `authenticated_at`, `last_verified_at`, `session_age_seconds`를 기록했다.
- [ ] 사람 개입 중 AI 조작은 0회였다.
- [ ] 새 창은 0개이며 새 탭은 필요한 경우 최대 1개였다.
- [ ] 브라우저·창·탭·프로필 종료는 0건이다.
- [ ] 배지를 제거하고 CDP 연결만 해제했다.
