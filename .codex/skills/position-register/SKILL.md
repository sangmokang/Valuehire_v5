---
name: position-register
description: 사장님이 "포지션 등록", "JD 등록", "사람인 잡코리아 등록", "잡코리아만 등록", "사람인만 등록", "이직제안 JD 등록", "후보자에게 보낼 메일 등록", "클릭업 포지션 전수 등록" 같은 요청을 할 때 사용. 클릭업/사장님이 준 채용 포지션(JD)을 사람인·잡코리아 양쪽 인재풀에 "이직 제안용 포지션"으로 등록(발송 아님)까지 로그인부터 한 번에 자동 진행. 회사 조사(캐시) → 본문(사람인과 잡코리아 동일 구조) → 사람인 candidate-manage 포지션 추가 → 잡코리아 채용포지션 등록까지 raw CDP 단일탭 selector/value 주입. 인자(args)에 "잡코리아만"/"사람인만" 지정 시 해당 채널만 등록(미지정=둘 다). 링크드인 InMail은 본 스킬 범위 밖 — linkedin-rps-jd-set-builder 스킬, 3사 동시는 position 스킬로 라우팅. 채널 범위·호출법은 §0.5 참조.
---

# 포지션 등록 (사람인 + 잡코리아 이직제안 JD 일괄 등록)

> 2026-06-15 사장님 명시 — "로그인부터 등록까지 빠르게 이어지도록 원칙으로 박아. 이게 그냥 주입하면 되는거잖아." 어글리랩 PM 라이브 등록(사람인+잡코리아)에서 검증된 흐름을 단일 진실로 박제. 채널별 깊은 규칙은 `saramin-talent-sourcing` / `jobkorea-talent-sourcing` SKILL 참조.

## 0. 절대 원칙 (사장님 명시)

| # | 원칙 |
|---|------|
| P0 | **로그인부터 등록까지 한 번에, 좌표 헤매기 금지** — chrome MCP 익스텐션 기다리지 말고 곧장 **raw CDP 단일탭**(`docs/sot/26-portal-login-spec.json` connection.method)으로 목표 탭 1개에만 attach. ⛔ `connectOverCDP("http://localhost:9222")` 전체 attach 금지(탭 과다 시 hang, 2026-06-25 161탭 실측). 전용 프로파일 `~/.cache/valuehire-chatgpt-chrome`. name selector 일괄 주입. |
| P1 | **로그인 순서**: ①기존 9222 세션 attach 후 login_state_check(GNB 계정명) ②로그아웃이면 `.env.local` 자격증명으로 raw CDP 자동 로그인(사람인 selectors.id/password/submit, 잡코리아는 '서치펌' 탭 먼저 — 검증 절차 §3-R2 ②) ③캡차/2FA/멀티세션 락만 사람 게이트. 잡코리아 실로그인 셀렉터 원본 = `tools/jobkorea-bulk-register/auto-login.mjs`(실재). ⛔ `tools/multi_position_sourcing/portal_autologin.py`·`docs/sot/26-portal-login-spec.json`은 **부재(죽은 참조)** — 가리키지 말 것(2026-07-01 확인). |
| P2 | **사람인과 잡코리아 본문은 자구까지 동일** (사장님 "사람인하고 똑같이"). 회사 소개(매출·투자·인원·**대표 quote** 포함)는 양쪽 모두 필수. 빈약한 4줄 본문 금지. |
| P3 | **등록만, 발송 금지** — 포지션 풀/마스터에 등록까지. 후보자 발송(차감)은 별도 사장님 지시. |
| P4 | **회사 조사 캐시 우선** — `~/.cache/saramin-company-research/<slug>.json`. 없으면 WebSearch 조사(추정 금지, 미확인은 표기). |
| P5 | **고용형태(잡코리아) 필수** — 안 넣으면 등록 실패. 정규직 기본. |

## 0.5 채널 범위 선택 — 잡코리아만 / 사람인만 / 둘 다 (호출법)

이 스킬은 **사람인·잡코리아 전용**이다. 호출 시 **인자(args)에 채널을 자연어로 명시**하면 그 채널만 실행한다.

| 원하는 것 | 호출 예시 | 실행 단계 |
|---|---|---|
| **잡코리아만** | `/position-register 잡코리아만 — <JD>` | §3만 (사람인 §2 skip) |
| **사람인만** | `/position-register 사람인만 — <JD>` | §2만 (잡코리아 §3 skip) |
| **둘 다(기본)** | `/position-register <JD>` (채널 미지정) | §2 + §3 |
| **링크드인만** | → 본 스킬 범위 밖. `linkedin-rps-jd-set-builder`(InMail 템플릿) | — |
| **3사 동시(+링크드인)** | → `position` 스킬(`/position`) | — |

- 인자에 "잡코리아"만 있고 "사람인" 없음 → 잡코리아만. 반대도 동일. 둘 다 없거나 둘 다 있으면 둘 다.
- ⛔ **링크드인을 이 스킬로 처리하지 말 것** — InMail 본문 구조(개요 인사+회사 브리핑+JD+설득+클로징, 1,899자)가 달라 `linkedin-rps-jd-set-builder`가 전담. 여기서 억지로 하면 고아·잘못된 본문.
- 진입 전 [1] 로그인 보장은 **선택된 채널만** 수행(잡코리아만이면 잡코리아 로그인만 확인).

## 1. 전체 흐름 (로그인 → 등록, 한 번에)

```
[0] 전용 프로파일 9222 기동 (이미 떠있으면 skip)
    lsof -ti tcp:9222 || nohup "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --remote-debugging-port=9222 --user-data-dir="$HOME/.cache/valuehire-chatgpt-chrome" \
      --no-first-run --no-default-browser-check \
      "https://www.saramin.co.kr/zf_user/auth" "https://www.jobkorea.co.kr/corp/person/find" &
[1] 로그인 보장 (P1) — docs/sot/26-portal-login-spec.json
    set -a; source .env.local; set +a
    # raw CDP 단일탭 attach → login_state_check(GNB '강상모/Valueconnect' = LOGGED_IN)
    # 로그아웃이면 26 스펙 channels.saramin.selectors 로 raw CDP 자동 로그인
    #   사람인 login_url: /zf_user/auth?ut=c&url=...search, id=input[name=id] pw=input[name=password] submit=button[type=submit]
    #   잡코리아 login_url: /Login/Login_Tot.asp → '서치펌' 탭 → id=input[name=id|userId|M_ID] pw=input[type=password] submit=텍스트"로그인" (검증 절차·캡차게이트=§3-R2 ②. 이미 로그인이면 searchfirm/home 리다이렉트)
    # 잡코리아 셀렉터 원본=tools/jobkorea-bulk-register/auto-login.mjs (실재. ⛔ connectOverCDP 전체attach+구포털 URL이라 셀렉터만 차용, §3-R2 ②). multi_position_sourcing/portal_autologin.py·SOT26 부재.
[2] 포지션 소스 확보
    - ClickUp FY26ClientsPosition(list_id=901814621569) 또는 사장님이 준 JD
    - 회사별 그룹화
[3] 회사 조사 (캐시 hit → 사용 / miss → WebSearch) — **§1.5 회사 브리핑 8요소 밀도 기준 충족 필수**
[4] 본문 생성 (회사별·포지션별, 사람인=잡코리아 동일 내용) → ~/.cache/saramin-positions/<slug>-<pos>.json
[5] 사람인 등록 (candidate-manage 포지션 추가) — §2
[6] 잡코리아 등록 (채용포지션 등록) — §3
[7] 검증 (카드 생성 / 등록 포지션 자동선택) + 보고
```

## 1.5 회사 브리핑 밀도 기준 — 8요소 (2026-07-02 사장님 지시 "회사 소개 좀 더 밀도 있게" · 3채널 공통 SOT)

후보자가 이 회사를 처음 듣는다고 가정하고, **"검토할 이유가 되는 숫자와 사실"**로 채운다. 빈약한 소개는 제안 수락률을 직접 깎는다 — 이 기준이 3채널(사람인 offerComment / 잡코리아 EXEC_WORK / LinkedIn InMail [회사] 단) 본문의 회사 소개 SOT다. LinkedIn 스킬 R20(7요소)도 이 8요소로 상향 통일.

| # | 요소 | 예 (모델솔루션) |
|---|------|----------------|
| ① | **한 줄 정의** — 무엇을 누구에게 파는가 | 애플·구글·삼성·테슬라 등 글로벌 1,000곳+에 시제품·목업·QDM 공급하는 제품개발 파트너 |
| ② | **설립·연혁 핵심** | 1993년 설립 |
| ③ | **상장/투자 단계** | 2022년 코스닥 상장(업계 최초, 종목 417970) |
| ④ | **매출·이익 (연도 명시)** | 2024년 매출 약 680억, 영업이익 전년비 +92% |
| ⑤ | **임직원 수** | 약 330명 |
| ⑥ | **모기업/계열·주요 주주** | 한국타이어 그룹 계열(지분 62.92%) |
| ⑦ | **대표 소개 + 공개 발언 quote (출처 필수)** | ※미확인이면 "※미확인" 표기 — 날조 금지 |
| ⑧ | **최근 뉴스·신사업 1~3건** | K-휴머노이드 연합 참여, 로봇 액추에이터 신사업 |

운영 규칙:
- **출처 있는 것만** 쓴다(추측·날조 금지). 확인 못 한 요소는 본문에서 빼고 캐시에 `"ceo": "※미확인"`처럼 남긴다 — 다음 실행이 그 칸만 조사하면 된다.
- **8요소 중 6개 미만**이면 등록 전에 사장님께 보고(비상장 초기 스타트업 등 공개 정보가 원래 적은 회사는 예외 승인 후 진행).
- 캐시(`~/.cache/saramin-company-research/<slug>.json`)에 요소별 키 + `sources[]`(URL)로 저장 — 재조사 0회 목표.
- 왜 8요소인가: 후보자 설득에 실제로 작동하는 건 형용사가 아니라 **규모(④⑤)·안정성(③⑥)·방향(⑧)·리더십(⑦)**의 조합이다. 하나라도 빠지면 그 축의 설득이 통째로 빈다.

## 2. 사람인 등록 — candidate-manage 포지션 추가 (검증된 selector, 2026-06-15 / 2026-06-19 진입경로 박제)

진입 (사장님 명시 2026-06-19): **GNB 상단 "인재풀" ▾ 드롭다운 > "포지션 관리"** = `https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/candidate-manage`.
- ⚠️ **tutorial 리다이렉트 함정**: candidate-manage 직접 goto 시 페이지 로딩 미완 순간 URL이 `.../main/tutorial`로 보이고 "로그인" 버튼·[포지션 추가] 없음처럼 보인다 → **이는 일시적 로딩 상태**다. `waitUntil:'networkidle'` + 2~3초 대기하면 정상 "포지션 관리" 화면("Valueconnect 강상모" + 이용권 + 후보 카드 + 포지션 목록)으로 안착한다. URL만 보고 "미로그인/tutorial" 단정 금지(2026-06-19 오판 교훈).
→ 우상단 **[+ 포지션 추가]** click (`button.btn_add_position`, 텍스트 "포지션 추가") → 슬라이드 패널.

| 필드 | selector | 내용 |
|------|----------|------|
| 포지션명* | `input[name="hiringTitle"]` | `회사명(서비스), 직무 (약칭)` |
| 제안 내용(후보자에게 보낼 메일) | `textarea[name="offerComment"]` | 인사 + valuehire 도입부 + **[회사 소개]**(매출·투자·인원·대표 quote) + [이 포지션] + [근무 조건] + 서명 (한도 2000자) |
| 업무 내용 | `textarea[name="chargeWork"]` | [주요업무] + [자격요건] + [우대사항] + [근무 조건] (JD 원본, 한도 2000자) |
| 저장 | `button` textContent==='저장' | 패널 안 visible |

- 입력: **raw CDP value setter**(`Object.getOwnPropertyDescriptor(proto,'value').set` + input/change dispatch — React Hook Form 인식. 2026-06-25 검증). ⛔ Playwright `fill()`은 raw CDP 단일탭 SOT(26)에서 비사용. 검증: offer>300·charge>300·제목 한글깨짐(`/[ㄱ-ㅣ]{2,}/`) 없음 → 저장. **패널은 클릭 후 3.5초 대기 후 필드 탐지(26 interaction_hardening)**.
- 성공 = 패널 닫힘 + 목록 맨 앞 카드 생성 + 진행중 카운트 +1, 등록가능 -1.
- **valuehire 도입부 문구(고정)**: "밸류커넥트의 커리어 구독 서비스 valuehire를 통해 본 제안을 수락해 주시면, 보다 정교하게 다듬은 이력서 피드백을 회신드리고, 앞으로 커리어 방향과 맞닿은 포지션이 생길 때마다 가장 먼저 안내드리고자 합니다. (제안 수락 시 개인정보 수집·이용에 동의하신 것으로 간주됩니다.)"

## 3. 잡코리아 등록 — 채용포지션 등록 (검증된 selector, 2026-06-15)

진입: `corp/person/find` → 아무 후보자 상세(`resume/view?rNo=`) → **[포지션 제안]** → 차감안내 모달 **[확인]**(`page.mouse.click` rect, JS .click 안 먹음) → 제안 모달 → **[채용포지션 등록]** → 등록 폼(인라인 모달).

| 필드 | selector | 내용 |
|------|----------|------|
| 포지션명* | `input[name="GI_PSTN"]` | `회사명(서비스) 직무 (약칭)` |
| 직무* | popup (아래) | rect 단순 click 금지 — inner checkbox + 이벤트 시퀀스 |
| 고용형태* | dropdown | **필수** — "선택하세요" click → 옵션(정규직/계약직/위촉직) click |
| 입사후 업무* | `textarea[name="EXEC_WORK"]` | [회사 소개](대표 quote 포함) + [이 포지션] + [주요 업무] + [자격요건] — **사람인 본문과 동일** |
| 우대사항 | `textarea[name="ST"]` | [우대사항] |
| 근무지 | `input[name="WORK_AREA_ADDR_DP"]` | 선택 |
| 연봉 | `input[name="MIN_SALARY_AMT"]`/`MAX_SALARY_AMT` | 선택 |
| 등록 | `button` textContent==='포지션 등록' | |

**직무선택 popup** (R44: 다른 필드보다 먼저):
1. [직무선택] click → popup
2. `[data-part-ctgr-code="<코드>"]` 카테고리 `page.mouse.click` → 1.5s wait
3. `[data-part-code="<하위코드>"]` 항목 선택 — **rect click 아님**:
```js
const el=document.querySelector('[data-part-code="1000188"]'); const inp=el.querySelector('input');
['pointerover','pointerdown','mousedown','pointerup','mouseup','click'].forEach(t=>(inp||el).dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));
if(inp){inp.checked=true; inp.dispatchEvent(new Event('change',{bubbles:true}));}
```
4. [확인] → 직무* 필드에 칩 표시 확인.

**잡코리아 직무 카테고리 코드 (data-part-ctgr-code)**: 기획·전략 10026 / 법무·사무·총무 10027 / 인사·HR 10028 / 회계·세무 10029 / 마케팅·광고·MD 10030 / AI·개발·데이터 10031 / 디자인 10032 / 물류·무역 10033 / 운전·운송·배송 10034 / 영업 10035 / 고객상담·TM 10036 / 금융·보험 10037 / 식·음료 10038 / 고객서비스·리테일 10039 / 엔지니어링·설계 10040 / 제조·생산 10041 / 교육 10042 / 건축·시설 10043 / 의료·바이오 10044 / 미디어·문화·스포츠 10045 / 공공·복지 10046

**기획·전략(10026) 하위 part-code**: 경영·비즈니스기획 1000185 / 웹기획 1000186 / 마케팅기획 1000187 / **PL·PM·PO 1000188** / 컨설턴트 1000189 / CEO·COO·CTO 1000190 / AI기획자 1000414 / AI사업전략 1000415

**AI·개발·데이터(10031) 하위 part-code** (2026-07-01 투바이트 백엔드 라이브 수집): **백엔드개발자 1000229** / 프론트엔드개발자 1000230 / 웹개발자 1000231 / 앱개발자 1000232 / 시스템엔지니어 1000233 / 네트워크엔지니어 1000234 / DBA 1000235 / 데이터엔지니어 1000236 / 데이터사이언티스트 1000237. (백엔드/서버 JD → 1000229)

**인사·HR(10028) 하위 part-code** (2026-07-02 모델솔루션 라이브 수집): **인사담당자 1000201** (HR/조직문화/채용 JD → 1000201). ⚠️ 10028 카테고리 클릭 후 popup에는 10026 하위(경영·비즈니스기획 등)와 10027 하위(경영지원 1000191~노무사 1000200)까지 함께 렌더되므로 텍스트 매칭(/인사|채용|HR/)으로 골라야 한다 — "첫 항목" 선택은 오선택.

직무 매핑(JD→카테고리>하위): PM/PO→기획·전략>PL·PM·PO(1000188) / 개발자·AI엔지니어→AI·개발·데이터(10031) / 마케터→마케팅·광고·MD(10030) / 디자이너→디자인(10032) / 영업·BD→영업(10035) / HR→인사·HR(10028) / 재무→회계·세무(10029). **가장 가까운 것 아무거나 OK (사장님 명시 — 직무 선택에 시간 쓰지 말 것).**

- 등록 성공 = 모달 닫히고 제안 작성 모달로 복귀(등록 포지션 자동 선택 + 담당 헤드헌터 Tim Sangmokang + 연락처 자동).

### 3-R. Root Cause 박제 (2026-06-19 뤼튼 Finance Data Analyst 라이브 등록에서 확인 — "왜 클릭이 안됐나")

사장님 9222(전용 프로파일)에 **탭이 수십 개** 떠 있을 때 잡코리아 등록이 반복 실패한 근본 원인 5가지. 이 순서대로 박는다:

1. **playwright `connectOverCDP` 전체 attach hang** — 사장님 9222에 탭 30개면 connectOverCDP가 모든 탭(youtube·chatgpt 등 무거운 페이지 포함)에 attach하느라 timeout/hang. ws 연결(`<ws connected>`)은 되는데 그 후 `ctx.pages()`/evaluate에서 멈춤. → **raw CDP로 등록폼 탭 1개에만 직접 연결**(아래 패턴). 새 탭 생성·전체 attach 회피.
   ```js
   const list = await (await fetch('http://localhost:9222/json/list')).json();
   const t = list.find(x=>x.type==='page'&&/jobkorea.*resume\/view/.test(x.url));
   const ws = new WebSocket(t.webSocketDebuggerUrl); // node22 global WebSocket
   // send('Runtime.evaluate',{expression,returnByValue:true}) / send('Input.dispatchMouseEvent',{type,x,y,button:'left',clickCount:1})
   // send('Page.captureScreenshot',{format:'png'})
   ```
2. **고용형태 selectBox(`.devemplybox`)는 `evaluate().click()` 무시** — 옵션은 `.devemplybox` **밖 전역**에 렌더되고 dropdown 열린 직후에만 DOM 존재. JS click·dispatchEvent 다 무력. → **실제 마우스 좌표 클릭**: 박스 `Input.dispatchMouseEvent(mousePressed→mouseReleased)` → 1.2s → 전역에서 textContent==='정규직' 요소 rect → 같은 실제 클릭. (5회 evaluate 클릭 전부 실패 → CDP 마우스로 한 번에 성공)
3. **고용형태 미선택 시 `[포지션 등록]` 눌러도 폼 안 닫힘** — 고용형태는 필수. `.selectBox-button-text`가 '정규직'으로 바뀐 것 확인 후에만 등록.
4. **`[포지션 등록]` 클릭은 `button` 태그만 정밀 타게팅** — `button,a,li,span,div` 전체에서 "포지션 등록" 텍스트로 찾으면 작은 span/div를 골라 좌표가 빗나가 클릭이 헛침. `[...document.querySelectorAll('button')].find(텍스트==='포지션등록')`의 rect 중앙만 클릭.
5. **직무 10029(회계·세무) 첫 하위 = "관리회계"** (회계담당자 아님). 선택 성공 판정을 `/회계담당자/`로 하면 false 오판 → 직무 칩 텍스트(`회계·세무 계열`)나 칩 존재로 판정.

**회계·세무(10029) 하위 part-code**: 관리회계(첫 항목) 등 — FP&A·재무 직무는 10029 첫 하위로 충분(가장 가까운 것 OK).

### 3-R2. 신포털 라이브 시행착오 박제 (2026-07-01 투바이트 백엔드 — 끝까지 등록 성공, 단계마다 헤맨 지점)

라이브 1건(투바이트 백엔드 개발자) 등록을 끝낸 실제 경로. **3-R의 connectOverCDP hang을 넘어, "후보 상세 → 제안 모달 → 채용포지션 등록"까지 raw CDP로 완주**한 기록. 헤맸던 4지점을 순서대로 박는다.

**① 인재 열람 세션 ≠ 제안/등록 세션 — [포지션 제안] 누르면 "기업 로그인이 필요" 모달이 뜬다 (가장 큰 함정)**
- `corp/person/find`가 "밸류커넥트"로 로그인돼 보여도(GNB 계정명 있음), 후보 상세에서 **[포지션 제안]** 을 누르는 순간 **"기업 로그인이 필요한 서비스입니다"** 모달(서치펌 라디오 + valueconnect ID + 비번칸 + [로그인])이 뜬다. 열람 권한과 제안/등록 권한 세션이 분리돼 있다.
- ⚠️ **이 모달은 iframe 안에 렌더된다** → 메인 document의 `querySelectorAll('input')`이 **빈 배열**, `body.innerText`에 "기업 로그인이 필요"가 **안 잡힘**(iframe 격리). "로그인 모달 없음"으로 **오판하기 쉽다**. iframe 유무(`[...document.querySelectorAll('iframe')].some(f=>/login/i.test(f.src))`)로 판정.

**② Claude 직접 로그인 — 검증된 셀렉터 절차 (사장님 명시 2026-07-01 "로그인 내가 도와줬는데 그거 니가 직접 하는 것 꼭 넣어라")**
- **셀렉터 원본 = `tools/jobkorea-bulk-register/auto-login.mjs`** (실재 — value setter 주입·캡차 게이트 로직 검증됨). ⛔ 단 이 파일은 `connectOverCDP` 전체 attach + 구포털 `hh.jobkorea.co.kr` URL이라 **그대로 실행 금지** — 아래 셀렉터·주입 로직만 차용해 raw CDP 단일탭으로 옮긴다.
- ⛔ **[포지션 제안] 눌러 뜨는 iframe 인라인 로그인 모달에서 좌표로 씨름 금지** (2026-07-01 실패: 비번칸 좌표+`Input.insertText`→[로그인] 누르니 `Login.asp`로 튕기고 그 탭이 광고로 hung).
- ✅ **Claude 직접 로그인 절차 (새 탭 + 메인 document 폼, iframe 회피):**
  1. **로그인 판정**: `curl -X PUT "http://127.0.0.1:9222/json/new?https://www.jobkorea.co.kr/Login/Login_Tot.asp"` → 새 탭 ws attach. **이미 로그인이면 `searchfirm/home`(밸류커넥트 서치펌 홈)으로 리다이렉트**(2026-07-01 라이브 확인) = 로그인됨, 로그인 skip하고 등록 진행. 입력란이 보이면 ↓ 로그인.
  2. **서치펌 회원 탭** 선택(기업/서치펌 중 서치펌).
  3. **value setter 주입** (메인 document 폼이라 iframe 문제 없음): ID = `input[name="id"], input[name="userId"], input[name="M_ID"]` ← `JOBKOREA_USERNAME`, PW = `input[type="password"]` ← `JOBKOREA_PASSWORD`.
     ```js
     const setVal=(el,v)=>{const s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));};
     setVal(document.querySelector('input[name="id"],input[name="userId"],input[name="M_ID"]'), window.__u);
     setVal(document.querySelector('input[type="password"]'), window.__p);
     ```
     (자격증명은 `window.__u`/`__p` 변수 경유 — 셸·로그에 평문 노출 금지)
  4. **주입 검증** `idLen>0 && pwLen>0`(빈 로그인 방지) → **캡차/2FA 선감지**(`iframe[src*="recaptcha"]`·`/보안문자|2단계 인증|인증번호/`) 있으면 **클릭 말고 중단 = 사람 게이트**(계정 잠금 방지).
  5. **[로그인] click**: `button, input[type="submit"]` 중 텍스트/`value`에 "로그인" 포함 & `!disabled`.
  6. **성공 판정**: URL이 `/Login`·`/Auth/Login` 벗어남. 이후 **또 다른 새 탭**에서 후보 상세 진입 → 모달 없이 제안 모달 열림(세션 쿠키 전용 프로파일 공유).
- ⚠️ **검증 상태(정직)**: 2026-07-01 당시 이미 서치펌 로그인된 상태라 위 폼 주입 자체는 라이브 재현 못 함(인라인 모달은 사장님이 수동으로 풀어줌). 셀렉터·로직은 auto-login.mjs 검증 코드 출처이고, "이미 로그인 시 searchfirm/home 리다이렉트"는 라이브 확인. **다음 로그아웃 상태에서 이 절차로 자동 로그인 시도 후 결과를 여기 갱신.**

**③ 사장님 9222 탭의 광고(doubleclick)로 기존 탭이 hung → 새 탭으로 회피**
- 후보 상세/로그인 탭이 `googleads.g.doubleclick.net` iframe 등으로 **busy → `Runtime.evaluate`·`Page.enable`이 30초 무응답**(ws 연결 자체는 됨, `Page.handleJavaScriptDialog`는 "No dialog showing" 즉답 → native 모달 아님 = 순수 페이지 hung).
- → 멈춘 탭을 붙들지 말고 **`/json/new` PUT으로 새 탭 생성** 후 그 탭 ws로 작업. 새 탭은 광고 로드 전이라 evaluate 정상.

**④ "고용형태"·"면접 후 결정" 텍스트가 페이지에 중복 존재 → textContent 매칭 오탐**
- 등록 폼의 "고용형태" 라벨/"면접 후 결정" 체크박스를 `textContent==='고용형태'`로 찾으면, **화면 밖(y≈6300) 다른 위치의 동일 텍스트**를 잡아 엉뚱한 좌표(클릭 무효)를 반환한다.
- → **가시영역 필터**: rect의 `y>0 && y<1200 && width>0`만 채택. 고용형태 dropdown은 직접 좌표(폼 우상단 ≈ x1085,y335) 클릭이 더 안전. 정규직 옵션은 dropdown 열린 뒤 가시영역에서 `^정규직$` rect 클릭.

**검증된 등록 폼 진입·완주 시퀀스 (2026-07-01)**: 새 탭 → 후보 상세(`resume/view?rNo=`) → [포지션 제안](rect click) → **차감 안내 [확인]**(rect click, "제안 1건 차감" — 누른다고 차감 아님, 발송 시 차감) → 제안 모달 → **[+채용포지션 등록]**(rect click) → 등록 폼(GI_PSTN/직무/고용형태/EXEC_WORK/ST) 주입 → **[포지션 등록]**(`button` 정밀 타게팅) → 폼 닫힘 + 제안 모달 "포지션 정보"에 **등록 포지션 자동 선택**되면 성공. ⛔ [제안보내기]는 누르지 않는다(P3, 발송=차감).

### 3-R3. 신포털 추가 실측 (2026-07-02 모델솔루션 인사담당 라이브 완주)

1. **차감 안내 모달이 생략되는 케이스 존재** — [포지션 제안] 클릭 시 차감 [확인] 없이 곧장 제안 모달이 열릴 수 있다(이미 열람한 후보 등). [확인] 버튼 미발견을 실패로 단정하지 말고 제안 모달 존재(채용포지션 등록 버튼)로 판정.
2. **고용형태 dropdown 버튼 = 채용 포지션 입력칸 우측의 "고용형태" 텍스트 요소**(폼 우상단). `.devemplybox` 클래스 탐색이 빗나가면 `textContent==='고용형태'` 가시영역 마지막 요소 rect를 실제 마우스 클릭 → 1.2~1.5초 → 가시영역 `^정규직$` rect 클릭. 선택 후 박스 텍스트가 "정규직"으로 바뀐 것 확인.
3. **성공 판정은 innerText 매칭이 아니라 input value** — 등록 후 제안 모달의 포지션명은 `input`의 value라 `body.innerText`에 안 잡힌다. "폼 닫힘(GI_PSTN 부재) + 스크린샷의 포지션 정보 자동선택"으로 판정(2026-07-02 innerText 검증이 성공 건을 실패로 오판).
4. **사람인 자동로그인 라이브 검증(2026-07-02)** — 로그아웃 상태에서 P1 절차(auth?ut=c 폼에 value setter 주입 → [로그인] rect 클릭) 그대로 성공, `hiring.saramin.co.kr/home` 리다이렉트 = 성공 판정. 캡차 없이 통과.

## 4. 팝업 자동 처리 (좌표 헤매기·사람 떠넘기기 금지)

- 모든 페이지/모달 진입 직후 첫 액션: `page.evaluate(()=>{window.alert=()=>true;window.confirm=()=>true;})` (R40 — native alert freeze 방지).
- 차감 안내/confirm 모달 [확인]: JS `.click()` 안 먹으면 `getBoundingClientRect` 중앙 → `page.mouse.click(x,y)` (native input event).
- 사람인 잔류 confirm "작성중 내용 변경": [변경] 자동 click.

## 5. 자격증명·캐시 위치

| 항목 | 위치 |
|------|------|
| 전용 프로파일 | `~/.cache/valuehire-chatgpt-chrome` (포트 9222) |
| 자격증명 | `.env.local` (SARAMIN_USERNAME/PASSWORD, JOBKOREA_USERNAME/PASSWORD) |
| 잡코리아 로그인 셀렉터 원본 코드 | `tools/jobkorea-bulk-register/auto-login.mjs` (id/M_ID·password·[로그인]·캡차게이트. ⛔ connectOverCDP 전체 attach+구포털 URL이라 셀렉터만 차용, §3-R2 ②) |
| ⛔ 죽은 참조(쓰지 말 것) | `docs/sot/26-portal-login-spec.json`, `tools/multi_position_sourcing/portal_autologin.py` — 둘 다 부재(2026-07-01 확인) |
| 회사 조사 캐시 | `~/.cache/saramin-company-research/<slug>.json` |
| 포지션 본문 캐시 | `~/.cache/saramin-positions/<slug>-<pos>.json` |

## 6. 사람인 vs 잡코리아 본문 매핑 (P2 — 동일 내용)

| 사람인 | 잡코리아 |
|--------|----------|
| offerComment = 인사+valuehire+[회사소개]+[이포지션]+[근무조건]+서명 | (제안 메시지 — 발송 시 입력) |
| chargeWork = [주요업무]+[자격요건]+[우대사항]+[근무조건] | EXEC_WORK = [회사소개]+[이포지션]+[주요업무]+[자격요건] / ST = [우대사항] |

→ 회사 소개(대표 quote 포함)는 사람인 offerComment·잡코리아 EXEC_WORK 양쪽에 **동일하게** 들어간다.

## 7. [치명적] 브라우저 자동화 방어 원칙 (사람인/잡코리아 공통, 2026-06-22)

> 과거 로그 분석 결과 '세션 만료 리다이렉트', '로그인 팝업 오인식', '텍스트 불일치'로 수많은 토큰과 시간을 낭비했다. 반드시 준수한다.

### 원칙 1 — 3단계 상태 트리이징 (Pre-flight Check)

페이지 로드 또는 상호작용 시작 전, **URL과 DOM 상태를 무조건 교차 검증**한다.

1. **리다이렉트 감지:** `candidate-manage`를 요청했는데 URL에 `tutorial` 또는 `auth`가 포함되면 세션 만료. 즉시 [세션 복구/로그인 플로우]로 분기한다.
2. **로그인 팝업 차단:** `[role="dialog"]`가 발견되면 내부 텍스트에 "로그인", "아이디", "비밀번호"가 있는지 확인한다. 로그인 팝업이 메인 화면을 가리고 있으면 어떤 버튼도 클릭할 수 없다 — "다이얼로그 있음 = 등록 모달 열림"으로 착각 금지.

### 원칙 2 — "모달 오픈" 성공 판정의 교차 검증

단순히 `[role="dialog"]`가 존재한다고 모달이 열린 것이 아니다.

- **가짜 오픈 방지:** 모달이 열렸다고 판단하면, 반드시 그 모달 내부에 **최종 타깃 필드(포지션명 input, 직무 드롭다운)**가 `offsetWidth > 0`으로 Visible & Enabled인지 확인한 뒤 "✓ 모달 OPEN" 로그를 남긴다.

### 원칙 3 — 셀렉터 유연성 및 스크린샷 검증

- **텍스트 매칭 느슨하게:** `button.textContent.trim() === '이직 제안'` 같은 완전 일치 대신 `/이직|제안/.test(b.textContent||'')` 패턴 또는 클래스 기반 셀렉터와 조합한다. UI 업데이트 시 텍스트가 바뀌어도 살아남는다.
- **최후의 보루 (스크린샷):** 로케이터가 3번 이상 타임아웃이나 `null`을 반환하면 코드로 계속 치지 말고 `/tmp/debug-[timestamp].jpg`로 스크린샷을 찍어 **비전(Vision) 능력으로 직접 눈으로 확인** 후 좌표(X, Y) 클릭으로 전환한다.
