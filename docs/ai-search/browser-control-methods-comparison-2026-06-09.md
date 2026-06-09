# 코드/셸이 브라우저를 제어하는 방식 — 비교 분석

> 작성일: 2026-06-09 · 대상: Valuehire 포털 자동화(`tools/multi_position_sourcing`)
> 출처: Playwright 공식 문서(playwright.dev/python) + 본 저장소 실제 코드

---

## 0. 한눈에 보기 (TL;DR)

"셸/코드가 브라우저를 제어한다"는 것은 결국 **자동화 프로세스(Python·Playwright)가 어느 브라우저에, 어떤 방식으로 붙느냐**의 문제입니다. 크게 두 갈래입니다.

| 갈래 | 한 줄 설명 | 본 저장소 사용처 |
|------|-----------|------------------|
| **붙기 (Attach)** | 사람이 이미 켜둔 브라우저에 **원격으로 접속**해 조종 | LinkedIn RPS |
| **띄우기 (Launch)** | 자동화가 **자기 전용 브라우저를 새로 실행** | 사람인 · 잡코리아 |

> 우리 코드는 이 둘을 채널별로 의도적으로 나눠 씁니다 (`portal_worker.py:350~365`). LinkedIn은 "붙기", 사람인·잡코리아는 "띄우기".

---

## 1. 네 가지 제어 방식

Playwright(우리가 쓰는 자동화 엔진) 기준으로 실무에서 쓰이는 방식은 4가지입니다.

### A. `connect_over_cdp` — 켜져 있는 Chrome에 CDP로 붙기 ⭐ LinkedIn

```python
# portal_worker.py:351
browser = await playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
context = browser.contexts[0]   # 사람이 쓰던 그 세션을 그대로 물려받음
```

- **CDP** = Chrome DevTools Protocol. Chrome을 `--remote-debugging-port=9222`로 켜면 열리는 "원격 조종용 문".
- 자동화가 브라우저를 **새로 띄우지 않고**, 사람이 로그인까지 끝낸 실제 Chrome 창에 **그대로 접속**합니다.
- 공식 제약: **Chromium 계열에서만 동작**(Firefox/WebKit 불가). 엔드포인트는 `http://host:port` 또는 `ws://...` 형식.

### B. `launch_persistent_context` — 전용 Chromium을 프로필 폴더로 띄우기 ⭐ 사람인·잡코리아

```python
# portal_worker.py:357
context = await playwright.chromium.launch_persistent_context(
    user_data_dir=profile_dir,   # 쿠키·로그인 상태가 디스크에 저장됨
    headless=False,
    args=[...],
)
```

- 자동화가 **자기 전용 Chromium 창을 새로 실행**합니다. 사람이 쓰는 Chrome과 완전히 별개.
- `user_data_dir`(프로필 폴더)에 쿠키·localStorage가 **저장**되므로, 다음 실행 때 **로그인이 유지**됩니다.
- 공식 제약 2가지:
  1. **같은 프로필 폴더로 두 개 동시 실행 불가.**
  2. **Chrome의 기본 "User Data" 폴더를 가리키면 안 됨** (Chrome 정책 변경으로 페이지 로딩 실패/종료). 반드시 **별도 빈 폴더**를 자동화 전용으로 써야 함 → 우리 코드가 `~/.valuehire/portal_profiles/<채널>/<worker>`로 분리하는 이유.

### C. `launch` + `new_context` — 매번 깨끗한 일회용 브라우저

```python
browser = await playwright.chromium.launch(headless=True)
context = await browser.new_context()   # 쿠키·세션 없음, 무균 상태
```

- 실행할 때마다 **로그인·쿠키가 전혀 없는 깨끗한 상태**. 테스트·CI에 이상적.
- 우리 포털 자동화에는 **부적합** — 매번 다시 로그인해야 하고 세션 유지가 안 됨.

### D. `connect` — Playwright 서버 프로토콜로 붙기

```python
browser = await playwright.chromium.connect("ws://...")  # launchServer로 띄운 서버
```

- CDP가 아니라 **Playwright 전용 프로토콜**. `BrowserType.launchServer`로 띄운 Playwright 서버에 접속.
- **Playwright 버전이 양쪽 일치해야 함**(1.2.x 호환). 원격 머신/도커 분리 실행용. 우리는 안 씀.

---

## 2. 장단점 비교표

| 항목 | A. CDP 붙기 (LinkedIn) | B. Persistent 띄우기 (사람인·잡코리아) | C. 일회용 launch | D. Playwright connect |
|------|:---:|:---:|:---:|:---:|
| **로그인 세션 유지** | ◎ 사람이 한 로그인 그대로 | ○ 프로필 폴더에 저장 | ✕ 매번 초기화 | △ 서버 설정 따라 |
| **사람 수동개입(2FA·캡차)** | ◎ 사람이 직접 처리 가능 | ○ headed면 가능 | ✕ 어려움 | △ |
| **봇 탐지 회피** | ◎ 진짜 사용자 Chrome | ○ 자동화 Chromium(탐지 여지↑) | ✕ 깨끗해서 오히려 의심 | ○ |
| **격리성(독립성)** | ✕ 사람 브라우저와 공유·간섭 | ◎ 완전 독립 창 | ◎ 완전 독립 | ◎ |
| **동시 실행(여러 워커)** | △ 한 Chrome에 종속 | ○ 폴더별 분리 가능(같은 폴더는 불가) | ◎ 무제한 | ◎ |
| **실제 Chrome 확장 사용** | ◎ 사람 Chrome의 확장 그대로 | ○ `--load-extension`으로 주입 | △ | △ |
| **사람 작업 방해** | ✕ 사람이 그 창 쓰면 충돌 | ◎ 별창이라 무관 | ◎ | ◎ |
| **운영 복잡도(준비물)** | Chrome을 `--remote-debugging-port`로 미리 켜둬야 | 프로필 폴더만 있으면 됨 | 없음 | 서버 띄워야 |
| **헤드리스(백그라운드) 적합** | △ 사람 창이라 보통 headed | ○ headless 가능 | ◎ | ◎ |
| **브라우저 종류 제약** | Chromium 전용 | 전부 가능(주로 Chromium) | 전부 가능 | 전부 가능 |

범례: ◎ 매우 좋음 · ○ 좋음 · △ 보통/조건부 · ✕ 나쁨/불가

---

## 3. 왜 채널마다 다른 방식을 쓰나 (설계 근거)

### LinkedIn RPS → "붙기(CDP)"를 쓰는 이유
- LinkedIn은 **봇 탐지·체크포인트(checkpoint)가 매우 공격적**. 자동화가 띄운 깨끗한 브라우저는 쉽게 막힙니다.
- **사람이 직접 로그인·2FA를 끝낸 진짜 Chrome 세션**에 그대로 올라타면 탐지 위험이 가장 낮습니다.
- 그래서 코드도 LinkedIn을 **단일 headed 워커(`worker_id="default"`)로 강제**하고(`portal_worker.py:170~174`), 발송(Send)은 자동으로 안 누르고 사람 게이트로 둡니다.
- 대가: 사람이 그 Chrome을 미리 `--remote-debugging-port=9222`로 켜둬야 하고, 그 창을 자동화가 점유합니다.

### 사람인 · 잡코리아 → "띄우기(Persistent)"를 쓰는 이유
- 이 둘은 LinkedIn만큼 탐지가 빡세지 않아, **자동화 전용 Chromium**으로 충분히 안정적으로 돕니다.
- 프로필 폴더에 로그인이 저장되니, `.env.local`의 아이디/비번으로 **한 번 로그인하면 이후 세션 유지**.
- 사람 브라우저와 **완전히 분리**되어, 사장님이 평소 Chrome을 쓰는 중에도 백그라운드에서 간섭 없이 실행 가능.

---

## 4. 이번 변경(2026-06-09)이 바꾼 것 / 안 바꾼 것

| | 변경 전 | 변경 후 |
|--|--------|--------|
| **LinkedIn CDP 주소** | 코드 6곳에 `http://127.0.0.1:9222` 하드코딩 | `.env.local`의 `VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT` 한 줄로 제어 |
| **우선순위** | 코드 고정 | CLI 인자 > 환경변수 > 기본값(`127.0.0.1:9222`) |
| **사람인·잡코리아** | `launch_persistent_context` | **변경 없음** (CDP 주소를 애초에 안 씀) |

> 핵심: 이번 변경은 **"붙기(A)" 방식의 접속 주소를 설정으로 뺀 것**뿐. "띄우기(B)"를 쓰는 사람인·잡코리아는 CDP 주소와 무관하므로 단 한 줄도 영향받지 않습니다.

관련 헬퍼: `resolve_chrome_cdp_endpoint()` (`portal_worker.py:31`)

---

## 5. 의사결정 가이드 — 새 채널을 추가할 때

```
탐지가 빡센 사이트(LinkedIn급)인가?
├─ 예 → A. connect_over_cdp (사람 로그인 세션에 붙기)
│        · 사람 개입(2FA/캡차) 필요, 발송은 수동 게이트
│
└─ 아니오 → 로그인 세션을 유지해야 하나?
            ├─ 예 → B. launch_persistent_context (전용 프로필 폴더)
            │        · 사람인·잡코리아 패턴. 백그라운드 가능
            │
            └─ 아니오(매번 깨끗해도 됨) → C. launch + new_context
                     · 테스트/CI/일회성 스크래핑
```

원격 머신·도커로 브라우저를 분리 운영해야 하면 **D. connect**(Playwright 서버)를 검토.

---

## 6. 운영 체크리스트

- [ ] **LinkedIn**: Chrome을 `--remote-debugging-port=9222`로 켰는가? (안 켜면 CDP 접속 실패)
- [ ] **포트 변경 시**: `.env.local`의 `VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT`만 수정.
- [ ] **사람인·잡코리아**: 프로필 폴더(`~/.valuehire/portal_profiles/...`)가 artifacts 밖에 있는가? (코드가 강제 검증)
- [ ] **같은 프로필 폴더 중복 실행 금지** — Playwright가 거부함.
- [ ] **3사 자동로그인은 절대 막지 말 것** (SOT 불변식).

---

## 7. 질문 ①: "사람인·잡코리아도 CDP로 돌리면 더 좋은가?"

**결론: 무조건 더 좋은 게 아닙니다. 운영 목적에 따라 갈립니다.** 지금의 분리(LinkedIn=CDP, 사람인·잡코리아=Persistent)는 우연이 아니라 합리적 선택입니다.

### 사람인·잡코리아를 CDP로 바꾸면 — 얻는 것 / 잃는 것

| | CDP로 바꿨을 때 |
|--|----------------|
| ✅ 얻는 것 | 사장님이 로그인해 둔 진짜 Chrome 세션 재사용(재로그인 불필요) · 봇 탐지 회피 ↑ · 캡차/2FA를 사람이 즉시 처리 |
| ❌ 잃는 것 | **백그라운드 무인 실행 불가** — 사장님이 그 Chrome을 쓰는 순간 충돌 · **동시 실행 어려움**(한 Chrome·한 default 컨텍스트에 사람인+잡코리아+LinkedIn이 몰림) · 사장님 Chrome 점유 |

### 왜 지금 방식이 더 나은가 (핵심)

우리 운영 모델의 목표는 **"사장님이 주무시는 새벽 03~05시 KST에 무인(Cron) 자동 실행"**입니다 (`clickup-position-talent-matching` 스킬). 이 목표에는 **Persistent(B)가 정확히 맞습니다**:

- 사장님 Chrome과 **완전히 분리**되어, 사장님이 낮에 Chrome을 써도 새벽 자동화와 안 부딪힘.
- 사람인·잡코리아는 LinkedIn만큼 탐지가 빡세지 않아 전용 Chromium으로도 안정적.
- 프로필 폴더 + 암호화 스냅샷으로 세션이 유지되므로 매번 로그인 안 해도 됨.

반면 LinkedIn은 탐지가 극심해 **사람 세션에 올라타야만(=CDP)** 살아남기 때문에, 어쩔 수 없이 사람 개입형(헤디드·수동 발송 게이트)으로 둡니다.

> **권장: 현 분리 유지.** 사람인·잡코리아를 CDP로 바꾸는 건 "무인 새벽 자동화"를 포기하고 "사장님이 지켜보는 수동 실행"으로 전환할 때만 의미가 있습니다.

---

## 8. 질문 ②: "Headless냐 Headed냐?"

### 우리 코드의 현재 규칙 (`portal_live_check.py:1381` 등)

```python
mode = "headed" if channel == "linkedin_rps" else ("headless" if config.headless else "headed")
```

| 채널 | 기본 모드 | 강제 여부 |
|------|-----------|-----------|
| **LinkedIn RPS** | 항상 **Headed** | 강제 — CDP로 붙는 headed Chrome이라 headless 불가 (`portal_worker.py:173`) |
| **사람인·잡코리아** | 기본 **Headed**, `--headless`로 전환 가능 | 선택 |

### 둘의 결정적 차이 — "사람 개입(캡차·2FA)" 가능 여부

런북 명문 규칙:
- **Headed**(화면 보임): 캡차·2FA·체크포인트가 뜨면 **사람이 풀 때까지 멈췄다가, 세션 재검증 후 자동 재개**.
- **Headless**(백그라운드): **사람 개입이 비활성화** → 캡차/체크포인트가 뜨면 그 채널은 그냥 **`not_ready`로 멈춤**.

### 그래서 언제 무엇을?

| 상황 | 권장 | 이유 |
|------|------|------|
| 최초 로그인 / 자격증명 갱신 / 탐지 잦은 사이트 | **Headed** | 캡차·2FA를 사람이 풀어야 함 |
| 세션이 이미 유효한 정기 무인 실행(Cron 새벽) | **Headless 가능** | 백그라운드·화면 불필요. 단, 도전 발생 시 복구 못 하고 스킵 |
| LinkedIn | **무조건 Headed** | 선택지 없음 |

> **핵심 트레이드오프**: Headless = 무인·백그라운드(but 캡차 만나면 포기) ↔ Headed = 복구 가능(but 화면·사람 필요). 무인 서버에서 Headless를 쓰려면 **암호화 스냅샷 폴백**(§9)이 세션을 받쳐줘야 안전합니다.

---

## 9. 질문 ③: 우리 프로젝트의 "세션 문제" — 구조와 진실

사장님이 겪어온 "세션이 자꾸 끊긴다" 문제의 정체를 층위로 정리합니다.

### 9-1. 세션은 어디에 저장되나 (3중 구조)

| 층 | 채널 | 저장 위치 | 역할 |
|----|------|-----------|------|
| **1차: 프로필 폴더** | 사람인·잡코리아 | `~/.valuehire/portal_profiles/<채널>/<worker>` (디스크) | 쿠키·로그인 상태 영속. **`storage_state`는 런치 옵션으로 안 넘김** — 폴더가 곧 세션 |
| **1차: 실제 Chrome** | LinkedIn | 사장님 Chrome(CDP 접속) | 사람이 로그인한 세션 그대로 |
| **2차: 암호화 스냅샷** | 전 채널 | Supabase(암호화 바이트) | 1차가 깨지면 **재주입(reinject)으로 복구** (`portal_snapshot.py`) |

### 9-2. 세션이 끊기는 진짜 원인

1. **포털 측 만료** — 사람인·잡코리아·LinkedIn이 일정 시간 후 세션 무효화.
2. **IP/보안 경고·체크포인트** — 비정상 접근 감지 시 재인증 요구.
3. **프로필 손상**(`reauth_cause=profile_corrupt`) — 디스크 프로필이 깨짐.
4. **동시 점유 충돌** — 같은 프로필 폴더를 둘이 열거나, MCP·Playwright가 같은 Chrome을 동시에 잡음(§10).

### 9-3. 끊겼을 때 복구 흐름 (자동/수동 분기)

```
세션 끊김 감지 (reauth_cause: http_401/403 · login_redirect · profile_corrupt)
│
├─ 사람인·잡코리아 → 키체인/.env 자격증명으로 자동 재로그인 시도
│                    실패 시 → 암호화 스냅샷 재주입 → 그래도 실패 시 not_ready
│
└─ LinkedIn → 자동 발송/조작 금지. Discord로 "재인증 필요" 알림 → 사람이 처리
```

캡차·2FA·체크포인트는 **어떤 경우에도 우회하지 않습니다**(SOT 불변식). 감지되면 멈추고 사람에게 넘깁니다.

### 9-4. ⚠️ 가장 중요한 오해 — "세션 유지하려고 계속 열어두면 안 되나?"

**안 됩니다. 런북이 명시적으로 금지합니다.**

> "this runbook is not a session keepalive recipe. Do not use repeated profile opens such as 'one profile every 10 minutes' to keep a portal session alive."

- **10분마다 프로필 열기 같은 keepalive 하트비트 = 금지.** 포털이 봇·어뷰징으로 보고 계정을 더 빨리 막습니다.
- 허용되는 세션 관리는 **① 검색 직전 on-demand readiness 체크, ② 로그인 만료 감지, ③ 수동 재로그인 알림** 뿐.
- 즉 "세션이 끊긴다"는 건 버그가 아니라 **설계상 정상** — 끊기면 그때 복구(자동 재로그인/스냅샷/알림)하는 모델입니다. 끊김을 억지로 막는 게 아니라, **끊김을 빠르게 감지하고 안전하게 복구**하는 게 우리 전략입니다.

---

## 10. 질문 ④: "Claude in Chrome, Playwright… 접속 장치 혼돈" 완전 정리

사장님이 혼란스러운 이유는 — **우리 프로젝트가 브라우저를 건드리는 경로가 실제로 3가지**이기 때문입니다. 스크린샷에서 "Claude(MCP)가 이 브라우저에 디버깅 시작" 배너가 뜬 것도 이 중 하나입니다.

### 세 가지 접속 장치

| # | 장치 | 무엇을 조종하나 | 어떻게 | 본 저장소 사용처 |
|---|------|----------------|--------|------------------|
| 1 | **MCP `claude-in-chrome`** (Chrome 확장) | **사장님이 보는 실제 Chrome** | 확장이 직접 클릭·입력 (스크린샷 배너) | `talent-search`, `codeit-talent-archive-search` 등 대화형 스킬 |
| 2 | **Playwright `connect_over_cdp`** | **사장님 실제 Chrome**(CDP 포트) | 포트 9222로 원격 접속 | LinkedIn RPS 포털 자동화 |
| 3 | **Playwright `launch_persistent_context`** | **별도 전용 Chromium** | 자동화가 새 창 띄움 | 사람인·잡코리아 포털 자동화 |

### 핵심 — 1번과 2번은 "같은 Chrome"을 노린다 (충돌 지점!)

- **MCP claude-in-chrome(1)** 과 **Playwright CDP(2)** 는 **둘 다 사장님의 실제 Chrome**을 잡습니다.
- 둘이 동시에 같은 Chrome을 제어하려 하면 **서로 간섭**합니다. 스크린샷의 "디버깅 시작 / 취소" 배너는 MCP가 그 Chrome을 점유하려는 신호 — 이때 Playwright LinkedIn 자동화가 같이 붙으면 충돌하거나 세션이 꼬일 수 있습니다.
- **3번(사람인·잡코리아)** 만 완전히 독립이라 충돌과 무관합니다.

### 혼돈을 없애는 한 장 그림

```
사장님 실제 Chrome (포트 9222로 열림)
   ├── [장치 1] MCP claude-in-chrome 확장  ──┐  같은 Chrome을 노림
   └── [장치 2] Playwright CDP (LinkedIn)   ──┘  → 동시 사용 금지!

별도 전용 Chromium (자동화가 띄움)
   └── [장치 3] Playwright launch_persistent (사람인·잡코리아)  → 독립, 안전
```

### 충돌 방지 규칙

1. **MCP(1)와 Playwright-CDP(2)를 동시에 돌리지 말 것.** LinkedIn 포털 자동화 중에는 MCP claude-in-chrome로 같은 Chrome을 조작하지 않기.
2. **사장님 Chrome 점유 가드** — 사장님이 Chrome을 쓰는 중이면 CDP 자동화(LinkedIn)는 멈춤. 사람인·잡코리아(3)는 별창이라 계속 가능.
3. **포트 일원화** — CDP 접속 주소는 이제 `.env.local`의 `VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT` 한 곳에서만 관리(이번 변경). MCP와 Playwright가 같은 포트를 가정하므로, 포트를 바꾸면 양쪽 다 맞춰야 함.

---

## 11. 종합 권장 운영 모델

| 채널 | 접속 장치 | 모드 | 실행 시점 | 세션 복구 |
|------|-----------|------|-----------|-----------|
| **LinkedIn RPS** | Playwright CDP (장치 2) | Headed 고정 | 사장님 Chrome 켜져 있고 안 쓰는 시간 | Discord 알림 → 수동 |
| **사람인** | Playwright Persistent (장치 3) | Headed(최초)→Headless(정기) | 새벽 Cron 무인 가능 | 자동 재로그인 + 스냅샷 |
| **잡코리아** | Playwright Persistent (장치 3) | Headed(최초)→Headless(정기) | 새벽 Cron 무인 가능 | 자동 재로그인 + 스냅샷 |
| **대화형 탐색** | MCP claude-in-chrome (장치 1) | Headed | 사장님이 직접 지시할 때 | 사람이 직접 |

**황금 규칙 3줄:**
1. LinkedIn(CDP)과 MCP는 **같은 Chrome** → 둘을 **동시에 켜지 말 것**.
2. 사람인·잡코리아(Persistent)는 **별창** → 무인·백그라운드의 주력.
3. 세션은 **끊기는 게 정상** → keepalive로 막지 말고, **감지+복구**로 대응.

---

## 부록: 용어 사전

| 용어 | 뜻 |
|------|-----|
| **CDP** | Chrome DevTools Protocol. 브라우저를 원격 조종하는 프로토콜. |
| **endpoint / 엔드포인트** | 접속 주소. 예: `http://127.0.0.1:9222`. |
| **headed / headless** | 화면 보이는 모드 / 화면 없이 백그라운드 모드. |
| **persistent context** | 쿠키·로그인을 디스크 폴더에 저장해 유지하는 브라우저 컨텍스트. |
| **user_data_dir / 프로필 폴더** | 브라우저 세션 데이터(쿠키·localStorage)가 저장되는 폴더. |
| **context (브라우저 컨텍스트)** | 한 브라우저 안의 독립된 세션 단위(시크릿창 같은 격리 단위). |
