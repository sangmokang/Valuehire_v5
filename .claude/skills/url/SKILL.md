---
name: url
description: "ClickUp 포지션(기본 리스트 901814621569)을 기준으로 LinkedIn Recruiter(RPS) 인재검색을 *미리 세팅*해, 나중에 /humansearch 가 바로 순회하도록 준비하는 스킬. RPS 프로젝트 확인·재사용(없으면 생성·모두공개) → Locations South Korea + 경력필터 → JD 분석해 영/한 핵심 키워드 → Boolean 3단(정밀·표준·확장)을 Keywords 에 넣어 실행·건수 확인 → 라이브 검색을 정밀·OTW 로 남김 → 그 포지션 Task 댓글에 [라이브 검색 링크 1개 + tier별 Boolean 레시피]를 등록. ⚠️ RPS는 프로젝트당 라이브 검색 1개만 유지하므로 tier별 독립 URL 저장은 성립 안 함(2026-07-03 라이브 검증) — 링크1개+레시피로 저장하고 tier 전환은 Boolean 재입력. 트리거 — \"/url\", \"url 미리 만들어\", \"RPS 서치 URL 준비\", \"이 포지션 링크드인 서치 URL 등록\", \"서치 URL 세팅\", \"포지션 URL 미리 세팅\". 검색어 실행·후보 채점은 humansearch 가, 검색식 산출은 boolean-strategy 를 재사용한다."
---

# url — LinkedIn RPS 서치 URL 사전 제작 · ClickUp 등록

> 한 줄: **포지션 → RPS 프로젝트 세팅 → Boolean 검색을 한 번 실행 → 결과화면 URL 수확 → ClickUp 포지션 Task에 저장.**
> 나중에 `/humansearch` 가 포지션명만 듣고 그 URL로 바로 들어가 순회·채점하게 만드는 "준비" 스킬이다.
> **이 스킬은 후보를 채점·발송하지 않는다.** 검색을 *걸어두기만* 한다. (채점·발송 = `humansearch`)

기본 레포 루트: `/Users/kangsangmo/Valuehire_v5`.
기본 ClickUp 포지션 리스트: **901814621569** (사장님 지정 — https://app.clickup.com/9018789656/v/li/901814621569).

---

## ⛔ 공통 SOT 시작 게이트 (절대 생략 금지)

발동되면 **작업·브라우저 조작·외부 쓰기 전에 먼저 기존 정의를 회수한다.** 건너뛰면 SOT 위반이다.

반드시 먼저 읽고 보고:
- 루트 SOT: `CLAUDE.md` (특히 0번 규칙·SOT 불변식 1~5)
- 작업 루프: `docs/harness.md`
- 관련 SOT: `docs/sot/22`(필터·결과수 트리) · `docs/sot/23`(채널 DOM 셀렉터) · `docs/sot/26`(포털 로그인)
- 검색식 규칙: `skills/search/references/boolean-strategy.md` (Title+Skill+Domain, 3단 정밀·표준·확장 — **복제 말고 재사용**)
- RPS 관례: `.claude/skills/aisearch/vendor/linkedin-rps-jd-set-builder.md` (§0 R3~R5 세션·양보·봇차단 규칙)
- 다운스트림 계약: `skills/humansearch/SKILL.md` + `skills/humansearch/humansearch.config.json` (이 스킬의 산출물을 humansearch 가 소비)
- 과거 메모리(아래 "메모리" 절)

먼저 보고할 5가지: 읽은 경로 · 기존 구현 진입점 · 재사용/확장할 파일·함수 · 새 파일 필요 여부와 이유 · 외부 쓰기(ClickUp·RPS) 여부와 승인 게이트.

강제 금지: 회수 전 새 코드/URL 생성 금지 · 기존 경로로 가능한데 새 러너 작성 금지 · 사후 스펙으로 정당화 금지 · 정의 미발견·충돌·죽은 참조 시 추측 진행 금지(→ STOP 후 보고) · 테스트 약화 금지.

## 메모리 (발동 즉시 확인)
- `rps-search-execute-method` — **RPS는 URL로 자동실행 안 됨.** 검색창에 타이핑 후 "Start a keyword search" 를 눌러야 결과가 뜬다 → 그래서 검색을 실제로 1회 실행해 **결과 URL을 수확**한다.
- `portal-search-needs-real-input` — RPS 검색 실행은 raw CDP 합성입력이 안 먹는다. **검색어 입력·실행은 claude-in-chrome 확장 실제입력**으로. (읽기·수확은 raw CDP OK)
- `linkedin-rps-harvest-background-tab` — 백그라운드 탭이면 가상스크롤이 5명만 렌더 → 수확 전 `Page.bringToFront` + focus emulation 필수.
- `talent-search`, `rps-search-execute-method`, `keep-logged-in-browser-alive` — 로그인된 RPS 크롬 kill/stop 금지.

---

## ⛔ 안전 불변식 (항상 · SOT 약화 금지)
- **발송·InMail·제안 "보내기"는 절대 자동 클릭 금지(SOT3).** 이 스킬은 *검색만* 걸어둔다. 후보 접촉 0.
- **사장님 크롬 점유 시 즉시 양보 → 손 떼면 자동 재개(SOT2/R4).** 창 여닫기·URL 연타·알람 후 무한 재시도 금지. 봇처럼 굴지 않는다.
- **캡차·봇차단·2FA·로그인 리다이렉트·멀티세션락 감지 시 즉시 STOP.** retry 금지(RPS 계정 잠금 위험).
- **로그인된 RPS 크롬 kill/stop 금지.** 세션 유지(`keep-logged-in-browser-alive`).
- 행동 전 **DOM 덤프로 셀렉터 확인**(SOT23 evidence-first). 추측 셀렉터 금지.
- 보고는 **짧고 쉬운 한국어**(CLAUDE.md 0번 규칙).

## 🖥️ 브라우저 드라이버
- **검색어 입력·필터 클릭·"Start a keyword search" 실행 = claude-in-chrome 확장 실제입력**(합성입력 안 먹음).
- **결과 URL·DOM 수확 = raw CDP 단일탭 OK**(`tools/multi_position_sourcing/raw_cdp.py`, `suppress_origin=True`). 수확 직전 `Page.bringToFront`.
- **🔴 점유 배지**: raw CDP 로 붙기 전에 `export VH_BUSY_TASK=/url`(Codex 면 `VH_BUSY_AGENT=Codex`). `raw_cdp.attach()` 하면 화면에 "🤖 …자동화 사용중 · /url" 배지가 자동으로 뜬다(사장님이 점유 인지, SOT 투명성). 상세 규약은 humansearch SKILL "브라우저 드라이버" 절.
- 사장님 :9222 세션에 우선 붙고, 로그아웃이면 `docs/search-access.md`/SOT26 기준으로 LinkedIn RPS도 시크릿 저장소 자동 로그인을 1회 시도한다. 캡차·2FA·checkpoint·멀티세션 락 우회만 금지.

---

## 입력 / 범위
- **인자 있음**(예: `/url 코드잇 백엔드`, ClickUp task URL/ID, JD 본문) → 그 포지션 1건만.
- **인자 없음**(그냥 `/url`) → 리스트 **901814621569**(FY26ClientsPosition)의 **살아있는(=마감 아님) 포지션 전수 순회**.
  - ⚠️ 이 보드엔 `active`라는 상태가 없다. 상태는 **카테고리**(scraped·backend/fullstack/cto·ai/ml/data·po/pm/기획·frontend·designer·sales/bd·marketing·devops/sre/security/qa·hr/finance/strategy/etc·c-level·app·etc)와 **마감 2종**(`closedpositions`=done, `complete`=closed)으로 나뉜다.
  - "살아있음" 판정 = **status_group 이 done/closed 가 아닌 것**(즉 `closedpositions`·`complete` 제외한 전부). `include_closed=false` 또는 status 필터로 마감 2종을 뺀다.
  - **stub 스킵**: `status=scraped` 인데 JD 본문(`markdown_description`)이 비었거나 이름이 코드/약어뿐(예: "BGZT")이면 미완성 껍데기 → 건너뛰고 보고에 남긴다.
- 포지션 원천은 ClickUp API(브라우저 아님)로 읽는다. Discord/인자에 JD 본문이 충분하면 그걸 우선 사용.

---

## 실행 단계 (포지션 1건 기준 — 전수면 이 블록을 포지션마다 반복)

### STEP 0 — 과거 회수 + RPS 프로젝트 세팅 (확인 우선, 없을 때만 생성)
0. **과거 회수 먼저(필수, SOT5)**: 그 포지션 ClickUp Task의 **댓글**을 읽는다(설명만 보지 말 것 — 2026-07-03 라이브에서 실제로 놓쳤던 함정). 이전 `/url`·RPS 후보수집·Boolean 이력이 댓글에 있으면 그 검색식·건수를 **참조·병합**하고 중복 실행하지 않는다.
1. **기존 프로젝트 확인 먼저**: 아래 "내 ACTIVE 프로젝트" 목록에서 같은 포지션 프로젝트가 이미 있는지 본다. 프로젝트 검색창에 회사명(한글)을 넣어 필터한다.
   `https://www.linkedin.com/talent/projects?filters=%7B%22OWNER%22%3A%5B%22urn%3Ali%3Ats_seat%3A243272211%22%5D%2C%22STATE%22%3A%5B%22ACTIVE%22%5D%7D&scFilters=%5B%7B%22sourcingChannelType%22%3A%22SEARCH_ONLY%22%7D%5D&sortBy=LAST_ENGAGED`
   - 있으면 그 프로젝트를 재사용(새로 만들지 않는다). 공개 상태(`Public`)도 그대로 확인만.
2. **없으면 생성**: `https://www.linkedin.com/talent/create/new/req-details` 에서 프로젝트 생성.
   - 프로젝트명 = **`회사명, 역할`** (실제 RPS 관례 — 예: `번개장터, PM`·`이우소프트, Proj. PM`·`모벤시스, Robotics`. `[포지션]…` 접두사는 InMail subject용이고 프로젝트명엔 안 씀).
   - **공개 범위 = "모두에게 공개"(Anyone in my organization)** 라디오 명시 클릭 + 선택 검증(다음 헤드헌터 재사용, R12 정신).
3. 생성/진입한 프로젝트에서 **Recruiter search** 로 이동. 여기서 검색을 건다.

### STEP 1 — JD 분석 → 핵심 키워드 (영/한)
- JD를 `boolean-strategy` **STEP A~B** 로 파싱: Title(직무) · Skill(변별력 2~3개) · Domain(도메인/산업).
- **각 요소를 영/한·표기변형으로** 확장 (예: `"Backend Engineer" OR "백엔드 개발자" OR "서버 개발자"`).
- **연차·경력년수·지역·연봉/OTW 는 검색식에 넣지 않는다**(boolean-strategy 불변식) — 이것들은 아래 필터/OTW 토글이 따로 처리.

### STEP 2 — Boolean 3단 세팅 + South Korea 기본
- **Show filter 열기** → **Locations = South Korea** 를 기본으로 설정(디폴트 신뢰 금지, 명시 클릭·검증).
- keyword(검색창)에 `boolean-strategy` **STEP C** 3단 검색식을 순서대로 준비:
  | 단계 | 구성 | 목적 |
  |---|---|---|
  | 정밀 | Title AND (Skill 2~3 모두 AND) AND Domain | 가장 적합한 소수 |
  | 표준 | Title AND (Skill 2~3 OR 묶음) AND Domain | 적정 풀 |
  | 확장 | Title AND (Skill OR) — Domain 완화/제거 | 풀 넓히기 |
  - 형식: `("A" OR "B") AND ("C" OR "D") AND ("E")` 한 줄, 구절은 따옴표로 묶음.

### STEP 3 — 검색 실행 + tier별 건수 확인 (⚠️ RPS는 프로젝트당 라이브 검색 1개)
> 🔴 **2026-07-03 라이브 검증으로 확정된 핵심 사실**: RPS 프로젝트는 **`searchHistoryId` 하나 = 라이브 검색 하나**만 유지한다. Keywords·필터를 편집하면 **같은 검색을 덮어쓴다.** 그래서 tier마다 수확한 `searchContextId` URL은 **독립 스냅샷이 아니다** — 나중에 그 URL을 열면 전부 "현재 라이브 검색"으로 리다이렉트된다. 즉 **"tier별 URL을 여러 개 저장"은 성립하지 않는다.** → 저장은 **Boolean 레시피(텍스트) + 라이브 검색 링크 1개**로 한다.

각 Boolean 단(정밀·표준·확장)을 **한 번씩 실행해 건수만 확인**한다(URL 여러 개를 최종 산출물로 믿지 말 것):
1. **Keywords 필드 편집**(연필) → 전체선택(cmd+a) → 레시피 타이핑(확장 실제입력, 한글 자모 안 깨짐 확인) → **Enter 로 실행**. (URL만으로 실행 안 됨 — 메모리 `rps-search-execute-method`.)
2. **Locations = South Korea(전국)** 추가, 필요 없는 잔여 필터(엉뚱한 Skill 등) 제거. 경력 필터는 JD 연차대(native filter)로.
3. **Open to work 스포트라이트** 토글로 OTW-only ↔ 전체 건수를 각각 확인해 메모. (스포트라이트가 실제 필터로 작동함 — 켜면 줄고 끄면 는다.)
4. **최종 라이브 검색은 humansearch에 가장 쓸모있는 tier로 남긴다** — 보통 **정밀·OTW**(정밀 + 구직중). 이게 프로젝트의 현재 검색이 된다.
- ⚠️ 사람처럼 천천히(검색 간 텀). 봇 패턴·연타 금지. 캡차·봇차단 뜨면 즉시 STOP.

### STEP 4 — ClickUp 등록 (포지션 Task 댓글: 레시피 + 링크 1개)
- 대상: 그 포지션의 ClickUp Task(기본 리스트 901814621569). 없으면 STOP 후 보고(임의 생성 금지).
- STEP 0 에서 본 **기존 소싱/`/url` 댓글은 덮지 않는다** — 새 댓글로 추가하되 그 이력을 참조·병합 언급.
- **댓글 1개**로 아래 형식(알람 폭탄 금지):

  ```
  ### RPS 서치 URL 준비 (/url · {날짜})
  project: {회사, 역할} — https://www.linkedin.com/talent/hire/{projectId}/discover/recruiterSearch
  visibility: org-public | location: South Korea | 경력: {N–M}년
  ⚠️ RPS는 프로젝트당 라이브 검색 1개 → tier 전환은 아래 Boolean을 Keywords에 붙여넣기(URL 여러 개 저장 불가).
  현재 라이브 검색 = [정밀·OTW] {N}명 → https://www.linkedin.com/talent/hire/{projectId}/discover/recruiterSearch
  Boolean 레시피:
  - 정밀 (전체 {N}/OTW {N}): ("직무 EN+KR") AND ("도메인") AND ("개발신호")
  - 표준 (전체 {N}/OTW {N}): ("직무 EN+KR") AND ("도메인 넓게")
  - 확장: 직무만 (도메인 없음, 너무 넓음 — 비권장)
  ```
- 저장하는 링크는 **프로젝트 recruiterSearch 진입 URL**(`…/discover/recruiterSearch`, stale searchContextId 없이) — 이게 "현재 라이브 검색"을 여는 안정 링크다.
- 링크 무결성 게이트: `https://www.linkedin.com/talent/hire/{projectId}/discover/recruiterSearch` 형태 확인(깨진 링크 금지, 사장님 0순위).

### STEP 5 — /humansearch 핸드오프 계약
- humansearch 는 포지션명/positionId 로 ClickUp Task를 찾아 이 댓글을 파싱 → **라이브 검색 링크를 열어 순회**한다(현재 = 정밀·OTW). 다른 tier가 필요하면 댓글의 Boolean 레시피를 Keywords에 붙여넣어 전환.
- 그래서 이 스킬의 출력 = **① humansearch가 바로 열 라이브 검색 링크 1개 + ② tier 전환용 Boolean 레시피 텍스트**. (여러 개의 tier별 결과 URL이 아니다 — RPS 구조상 성립 안 함.)
- 보고(한국어, 쉽게): "포지션 N건 링크드인 검색 준비해서 클릭업에 넣어뒀어요. 이름만 부르시면 바로 순회합니다."

---

## 비범위 (하지 않는 것)
- 후보 프로필 열기·채점·저장·발송 (= `humansearch`).
- 사람인·잡코리아 검색 (= `saramin`/`jobkorea` 계열, 이 스킬은 **LinkedIn RPS 전용**).
- InMail/JD 템플릿 작성 (= `linkedin-rps-jd-set-builder`).
- 캡차·2FA·봇차단 우회 (감지 시 STOP).
- ClickUp Task 임의 생성 (포지션 Task 없으면 보고만).
