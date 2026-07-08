---
name: position
description: 한 포지션(JD)을 사람인·잡코리아·LinkedIn 3사 인재풀에 "이직 제안용 포지션"으로 한 번에 등록(발송 아님, 등록만). AI Search(후보 소싱)를 시작하면 자동으로 호출돼 같은 포지션을 3사에 동시 등록한다. 트리거 — "/position", "3사 등록", "3사 등록: <회사명>, <포지션명>"(사장님 표준 호출 한 줄 — §1.5 명명 규칙), "포지션 등록", "사람인 잡코리아 링크드인 jd 등록", "포지션 3사 올려", 그리고 **AI Search/포지션 소싱 시작**(chatgpt-position-sourcing·칸반 AI Search·position-batch가 돌면 같은 포지션을 /position 으로 3사 JD 등록 병행). 핵심: raw CDP 단일탭으로 웹페이지 진입을 빠르게(사장님 9222 탭 과다 → connectOverCDP 전체 attach hang 회피), 시행착오는 빠르게 흡수.
---

# /position — 사람인·잡코리아·LinkedIn 3사 JD 등록 (AI Search 자동 호출)

> 2026-06-19 사장님 명시 — "잡코리아·링크드인·사람인 등록 프로세스를 /position 으로 묶고, AI Search 시작하면 자동으로 호출해서 바로 3사에 JD 등록해. 웹페이지 진입은 빠르게, 시행착오를 겪더라도 문제를 최대한 빠르게."

## 0. 절대 원칙

| # | 원칙 |
|---|------|
| P0 | **등록만, 발송 절대 금지.** 사람인 [저장]·잡코리아 [포지션 등록]까지만. 사람인 제안발송·잡코리아 [제안보내기]·LinkedIn [Send] 는 절대 자동으로 누르지 않는다(계정 정지·오발송 위험). |
| P1 | **빠른 진입 (사장님 명시).** 좌표 헤매기·사람 떠넘기기 금지. **2026-06-25 확정: raw CDP 단일탭(node22 global WebSocket + fetch /json/list)** 이 SOT다 — `docs/sot/26-portal-login-spec.json` connection.method. 161탭 실측에서 빠르게 동작. ⛔ `connectOverCDP('http://localhost:9222')` 전체 attach는 탭 과다 시 hang(폐기). ※ 과거 '단일탭 WS URL pages()=[] 오류'는 playwright connectOverCDP를 단일 WS로 쓴 케이스이지, node raw WebSocket 직접 제어(cdp.mjs)는 정상. 막히면 §1-R 순서로 전환. |
| P2 | **AI Search 시작 = /position 자동 호출 — 2026-06-22 G3 배선 완료.** `npm run ai-search:all -- --auto-register` 또는 `node tools/run-ai-search-all.mjs --auto-register` 플래그로 AI Search 완료 후 `run-skill-a-portal-registration-runner.mjs` 자동 트리거. OWNER_SIGNOFF_SARAMIN_REGISTER/JOBKOREA_REGISTER 게이트는 orchestrator 내부에서 보호됨. LinkedIn은 별도 게이트. |
| P3 | **본문은 사람인=잡코리아=LinkedIn 동일 소스.** 회사 소개(매출·투자·대표 quote)는 3사 모두 필수. 본문 캐시 `~/.cache/saramin-positions/<slug>-<pos>.json`(offerComment/chargeWork/jobkorea_exec_work/jobkorea_st/GI_PSTN). 회사조사 캐시 `~/.cache/saramin-company-research/<slug>.json`. |

## 1. 빠른 진입 SOT — raw CDP 단일탭 (2026-06-25 확정 · docs/sot/26-portal-login-spec.json)

**2026-06-25 확정: raw CDP 단일탭(node22 global WebSocket + fetch)이 SOT.** 사장님 9222에 탭 161개여도 빠르게 동작(라이브 검증). 로그인·등록·검색 전부 이 방식. ⛔ `connectOverCDP('http://localhost:9222')` 전체 attach는 탭 과다 시 enumerate/attach로 hang하므로 금지. ※ 과거 '단일탭 WS URL pages()=[]'는 playwright connectOverCDP를 단일 WS로 물린 케이스이지 node raw WebSocket 직접 제어가 아니다.

목표 사이트 탭 1개에만 raw CDP WebSocket 으로 직접 붙기:

```js
// node22 global WebSocket — 외부 의존 0
const list = await (await fetch('http://localhost:9222/json/list')).json();
const t = list.find(x => x.type === 'page' && /saramin|jobkorea|linkedin/.test(x.url)); // 목표 탭
const ws = new WebSocket(t.webSocketDebuggerUrl);
let id = 0; const pending = {};
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending[m.id]) { pending[m.id](m); delete pending[m.id]; } };
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending[i] = r; ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async expr => (await send('Runtime.evaluate', { expression: expr, returnByValue: true })).result?.result?.value;
const click = async (x, y) => { await send('Input.dispatchMouseEvent', { type:'mousePressed', x, y, button:'left', clickCount:1 }); await send('Input.dispatchMouseEvent', { type:'mouseReleased', x, y, button:'left', clickCount:1 }); };
const fill = (name, text) => ev(`(()=>{const el=document.querySelector('[name="${name}"]');el.value=decodeURIComponent("${encodeURIComponent(text)}");el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return el.value.length;})()`);
const shot = async f => { const s=await send('Page.captureScreenshot',{format:'png'}); if(s.result?.data) (await import('node:fs')).writeFileSync(f, Buffer.from(s.result.data,'base64')); };
await new Promise(r => ws.onopen = r); await send('Runtime.enable'); await send('Page.enable');
```

- 입력(한글)은 `evaluate` 에서 `decodeURIComponent(encodeURIComponent(text))` 로 — atob/btoa 는 한글 깨짐.
- 클릭은 `Input.dispatchMouseEvent`(실제 마우스). custom selectBox·option 은 `evaluate().click()`·dispatchEvent 를 무시한다.
- 매 스크립트 끝 `process.exit(0)`(WebSocket 미닫힘 hang 방지). `ws.close()` 후 exit.

### 1-R. 시행착오 빠른 전환 순서 (막히면 멈추지 말고 다음으로)
1. (raw CDP 단일탭이 기본) 혹시 connectOverCDP를 쓰다 hang → 즉시 **raw CDP 단일탭**(위)으로 전환.
2. JS click 무력 → **Input.dispatchMouseEvent 실제 좌표**.
3. 버튼 클릭 빗나감 → **`button` 태그만** 정밀(`[...document.querySelectorAll('button')].find(텍스트일치)` 의 rect 중앙). span/div 섞으면 작은 요소 골라 빗나간다.
4. 페이지가 tutorial/로딩 미완으로 보임 → **networkidle/2~3초 대기**(URL만 보고 미로그인·실패 단정 금지).
5. 탭이 꼬임/여러 개 → /json/list 로 **목표 탭 URL 정확 매칭**해 그 탭만 작업.

## 1.5 채널 라우팅 한눈에 (2026-07-02 명확화 — 어떤 스킬이 어떤 채널을 등록하나)

| 사장님이 치는 한 줄 (명명 규칙, 2026-07-02 확정) | 스킬 | 코드/패턴 |
|---|---|---|
| **`3사 등록: <회사명>, <포지션명>`** (+JD 본문 또는 ClickUp 링크) | **`position`(본 스킬)** — §2 순서로 완주 | raw CDP 단일탭 (§1) |
| **`잡코리아만 등록: …`** / **`사람인만 등록: …`** | `position-register` (§0.5 args 라우팅) | 동 스킬 §2/§3 셀렉터 |
| **`링크드인 템플릿: …`** (또는 "jd builder") | `linkedin-rps-jd-set-builder` (Save as new까지, Send 금지) | 동 스킬 §1A/§5~§8 |
| **`채용공고 등록: …`** (공고 게시 — 인재풀 제안 아님) | `recruit-post-builder` | — |

명명 원칙: **"어디에(3사/채널명) 등록: 회사명, 포지션명"** 한 줄이면 끝. 회사명+포지션명만 있으면 JD는 ClickUp(FY26ClientsPosition)·캐시에서 스스로 회수한다. 회사 소개 밀도는 `position-register` **§1.5 회사 브리핑 8요소**가 3채널 공통 SOT.

본문 소스는 3채널 공통 캐시 1개(`~/.cache/saramin-positions/<slug>.json`, GI_PSTN/EXEC_WORK/ST 기준)다. 사람인 offerComment/chargeWork·잡코리아 EXEC_WORK/ST·LinkedIn InMail 본문 모두 이 캐시에서 조립(§0 P3, position-register §6 매핑).

> **2026-07-02 모델솔루션 인사담당 라이브 3사 완주 실증** — 사람인(로그아웃 상태에서 자동로그인 성공→카드 생성) → 잡코리아(차감 모달 없이 제안 모달 즉시 열리는 케이스 확인·직무 인사담당자 1000201·등록 후 자동선택) → LinkedIn(Save as new 토스트, 조직공유 라디오 증거). 채널별 발견사항은 각 스킬 변경이력 참조.

## 2. 3사 등록 순서 (한 포지션 = 사람인 → 잡코리아 → LinkedIn)

[0] 본문·회사조사 캐시 확보 (`position-register` §2~§4 흐름) — 회사조사 캐시 hit/miss, 본문 생성(사람인=잡코리아 동일, 회사소개 대표 quote 필수).
[1] **사람인** — `position-register` §2: GNB 인재풀 ▾ > 포지션 관리(=`/talent-pool/main/candidate-manage`) → [+ 포지션 추가](`button.btn_add_position`) → hiringTitle/offerComment/chargeWork fill → [저장]. 성공 = 패널 닫힘 + 목록 맨 앞 카드.
[2] **잡코리아** — `position-register` §3 + **§3-R Root Cause**: 후보 상세 → [포지션 제안] → 차감 [확인](실제 클릭) → [채용포지션 등록] → GI_PSTN/EXEC_WORK/ST fill → 직무 popup(10029 회계·세무 등 가까운 것) → **고용형태 정규직(반드시 `Input.dispatchMouseEvent` 실제 클릭, 필수)** → [포지션 등록](**`button` 태그만 정밀**). 성공 = 폼 닫힘 + 제안 모달 복귀. **[제안보내기] 금지.**
[3] **LinkedIn** — `linkedin-rps-jd-set-builder`: RPS InMail 본문(개인화 인사+회사 브리핑+JD 압축, 1,900자) → "Save as new" 템플릿 저장. **[Send] 금지.**
[4] 검증·보고 — 3사 각각 등록 성공 화면 캡처 + 본문 동일성. 실패한 채널은 정직히 표기(가짜 완료 금지).

> 사람인·잡코리아 selector·Root Cause 전문은 `position-register` SKILL §2/§3/§3-R 를 단일 진실로 따른다(중복 박제 금지). LinkedIn 은 `linkedin-rps-jd-set-builder`.

## 3. AI Search 자동 호출 (P2 배선)

- **칸반/ChatGPT AI Search 로 한 포지션 후보 소싱을 시작하면**(chatgpt-position-sourcing·position-batch-flow), 같은 포지션을 /position 으로 **3사 JD 등록까지 병행**한다. 소싱(후보 찾기)과 등록(포지션 올리기)은 같은 포지션의 양면이므로 한 번에.
- 입력 포지션 식별: ClickUp task(FY26ClientsPosition) 또는 사장님이 준 URL/JD. 동일 포지션을 소싱 대상이자 3사 등록 대상으로 쓴다.
- 자동 호출 후에도 **발송은 사장님 게이트**(P0) — 3사 등록까지만 자동, 후보 발송은 별도 지시.

## 4. 자격증명·캐시 (position-register 와 공유)

| 항목 | 위치 |
|------|------|
| 전용 프로파일 | `~/.cache/valuehire-chatgpt-chrome` (포트 9222) |
| 자격증명 | `.env.local`(SARAMIN_*/JOBKOREA_*), LinkedIn 세션 |
| 회사조사 캐시 | `~/.cache/saramin-company-research/<slug>.json` |
| 포지션 본문 캐시 | `~/.cache/saramin-positions/<slug>-<pos>.json` |
| 로그인 SOT | `docs/sot/26-portal-login-spec.json` (raw CDP·로그인판정·차단탐지·선제 일괄). 셀렉터 원본=`tools/multi_position_sourcing/portal_autologin.py` |
