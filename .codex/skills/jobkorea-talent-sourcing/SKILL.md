---
name: jobkorea-talent-sourcing
description: 잡코리아(jobkorea.co.kr) 기업회원/서치펌 계정으로 인재검색 → 적합도 평가 → 포지션 제안 발송까지 한 턴을 자동 수행. 사장님이 매번 20단계를 타이핑하지 않도록 명문화. 85점 이상 적합도(좋은학교 + 이직안정성 + 직무직결성) 후보자만 자동 발송. 트리거 키워드 — "잡코리아 서치", "잡코리아 인재검색", "JobKorea sourcing", "잡코리아 포지션 제안", "valueconnect 잡코리아", "잡코리아 한 턴 돌려"
---

# 잡코리아 인재 서치 → 적합도 평가 → 포지션 제안 (한 턴 워크플로우)

> 2026-05-22 사장님 명시 — `docs/engineering/qa/ai-search-system-audit-2026-05-21.html` Critical Gap #1 "Saramin·JobKorea·LinkedIn 통합 오케스트레이션 SKELETON" 해결을 위한 잡코리아 전용 깊이 가이드. talent-search 메타 가이드의 잡코리아 섹션을 이 스킬로 위임.

---

## 0. 절대 규칙 (사장님 명시 — 절대 위반 금지)

| # | 규칙 | 근거 |
|---|------|------|
| R0 | **85점 이상만 자동 포지션 제안 발송** | 1건 차감(275/300) + 실 이메일 발송 = 되돌릴 수 없는 액션. 사장님 2026-05-22 명시 |
| R1 | **자격증명은 SKILL 평문 금지** | `~/.secrets/jobkorea.env` 격리(chmod 600). source 후 `$JOBKOREA_ID`/`$JOBKOREA_PW` 만 참조 |
| R2 | **사람 개입 시 자동화 즉시 정지** | 사장님이 chrome 만지거나 "내가 할께" 신호 → 모든 자동화 action 0. 메모리 [feedback_human_intervention_pause] |
| R3 | **봇 검출(캡차/차단 페이지) 즉시 STOP** | 재시도 금지 — 계정 잠금 위험. OPS_INCIDENTS 디스코드 알림 후 사장님 수동 풀이 |
| R4 | **인재DB 라이선스 차감은 사장님 컨펌 후** | 프로필 상세 진입 시 차감 0 / 포지션제안 발송 시 1건 차감 — 발송 직전 미리보기 화면 캡처를 사장님께 보여드릴 것 |
| R5 | **'프리랜서' 단어 포함 레쥬메는 패스** | 사장님 명시 |
| R6 | **발송 전 "등록 포지션 명 검색" 사전 확인** — 0건이면 즉시 STOP | 2026-05-22 라이브 발견: 잡코리아 등록 포지션 부재 시 자동 발송 자체가 불가능. 사장님이 채용포지션 등록 화면에서 직접 등록 필요 |
| R7 | **한국어 키워드 입력은 영어 fallback 우선** — `clipboard.writeText("뤼튼") + cmd+v` 는 "뒤튼" 같은 자모 분리 오타 위험 | 2026-05-22 라이브 발견. 가능하면 영문 키워드 (Nest.js, Product, Marketing) 로 검색, 한글 필수 시 `computer type "한국어"` 직접 폴백 |
| R8 | **비IT 도메인도 같은 흐름** — 마케팅/디자인/세일즈/HR/운영도 동일 20단계 적용 | 사장님 2026-05-22 명시 "내가 일일히 말 안 해도 알아야 함". 도메인별 키워드/직무카테고리만 매핑 다름. §5-A 참조 |
| R9 | **막힘·실패 시 무조건 재시도 강제** — 캡차(R3) 외 모든 장애는 끝까지 재시도해서 적임 후보자 찾아 발송 | 사장님 2026-05-22 명시 "막히는 것은 무조건 다시 실행하도록 강제하고 계속 문제 해결해서 적임 후보자 찾아서 발송". §19-A 재시도 정책 참조 |
| R10 | **사장님 컨펌 묻지 말고 자율 진행 — 발송 완수가 최우선 목표** | 사장님 2026-05-22 명시 "나에게 묻지 말고 왠만한 것은 스스로 문제 해결해서 반드시 후보에게 메일을 보내는 것을 목표로 할것". 회사에 도움되는 방향이면 컨펌 회수 0, 발송까지 완수. AskUserQuestion·컨펌 메시지 금지. STOP 조건은 R3(캡차) 만. 결과만 Discord 종합 보고. |
| R11 | **Discord 송부 시 후보자별 profile URL 반드시 embed.url 필드에 — 누락 시 abort + 재송부** | 사장님 2026-05-22 명시 "디스코드로 보낸 후보자 url 넣으라고. 안그러면 확인할 길이 없다". 후보자 정보를 fields 안에 묶으면 안 됨(url 필드 없음). 각 후보자 = 별도 embed 1개로 분리. 송부 직전 url 검증 — 누락 시 abort. |
| R12 | **등록 포지션 직무·JD 일치 검증 강제 + 미리보기 사장님 송부 필수** | 🛑 **2026-05-22 트랙 D 사고 원인** — "모벤시스" 회사명만 매칭하고 "Physical AI Research" R&D 엔지니어 등록 포지션을 사업개발/기술영업 후보자에게 재활용 → 잡코리아 자동 JD 첨부로 무관한 JD 발송. **재발 방지**: ① 등록 포지션 검색 시 회사명 + 직무명 동시 매칭 필수 (직무 mismatch 시 자동 등록 fallback §13-A 진입) ② 미리보기 페이지(`/Corp/Person/PositionOfferPreview`) 캡처를 Discord 송부 + **사장님 명시 OK 받기 전 제안보내기 click 금지** ③ "선택한 포지션 정보는 제안 내용에 포함되어 발송됩니다" 문구 인지 |
| R31 | **자동화 도중 발견한 root cause → QA-XXX 즉시 영구 등록** | 사장님 명문 "지금 과정도QA이슈로 삼아서 해결하고 skill 업데이트해". `docs/engineering/qa/issue-log.md` 에 prevent recurrence 명시. 상세 → 본 SKILL R31 |
| R32 | **사장님 코칭 즉시 R-번호 부여 → SKILL 영구화 (메타 규칙)** | 사장님 명문 "내가 중간중간 코칭한거 다 skill에 반영해". 다음 세션 동일 실수 반복 금지. 상세 → 본 SKILL R32 |
| **R33** | **🔥 실패 셀렉터·팝업 방해는 레저 파일에 즉시 기록 (Self-Correction Loop)** | 예상치 못한 셀렉터 에러·팝업 방해 발생 시 `URL / 실패한 셀렉터 / 화면 특이점(예: "로그인 팝업이 dialog 레이어를 먹어버림")`을 `docs/engineering/selectors-error-ledger.md`에 append. 다음 실행 시 이 파일을 **가장 먼저 읽고** 동일 주소·상황에서 같은 실수를 반복하지 않도록 코드를 방어적으로 작성한다. R31 강화판 (2026-06-22) |

### 13-D. 잡코리아 직무 트리 React 자동화 (2026-05-22 사장님 옵션 2 명시)

잡코리아 포지션 등록 폼의 **직무 선택** = React state 기반 popup 트리. JS .click() 만으로는 state 갱신 안 됨 → 3 레이어 폴백:

**1순위 — React Props onClick 직접 호출**
```javascript
const findReactProps = (el) => Object.keys(el).find(k => k.startsWith('__reactProps$'));
const triggerReactClick = (el) => {
  const key = findReactProps(el);
  if (key && el[key].onClick) {
    el[key].onClick({ preventDefault: ()=>{}, stopPropagation: ()=>{}, target: el, currentTarget: el });
    return true;
  }
  return false;
};
```

**2순위 — Synthetic MouseEvent 합성 (mousedown + mouseup + click)**
```javascript
const triggerMouseClick = (el) => {
  const r = el.getBoundingClientRect();
  ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(type => {
    el.dispatchEvent(new MouseEvent(type, {
      bubbles: true, cancelable: true, view: window,
      clientX: r.x + r.width/2, clientY: r.y + r.height/2
    }));
  });
};
```

**3순위 — computer.left_click 좌표 직접 click (visual 폴백)**

### 13-D-1. 트리 click 흐름 (Stage)
```
Stage 1: [직무선택] button click → popup 열림 (1초 wait)
Stage 2: 1차 카테고리 (예: "마케팅·광고·MD") click → 하위 트리 펼침 (0.5초 wait)
Stage 3: 2차 카테고리 (예: "마케팅") click → 3차 노출 (0.5초 wait)
Stage 4: 3차 직무명 (예: "브랜드마케터") click → 체크박스 또는 라디오 활성
Stage 5: popup 하단 [확인] / [선택 완료] button click → popup 닫힘
```

### 13-D-2. 매 단계 검증
```javascript
// 1초 wait 후 popup 노출 검증
const popupOpen = document.querySelector('.layer-job-tree, [class*="job-tree"], [role="dialog"]')?.offsetParent !== null;
if (!popupOpen) { /* 폴백 진입 */ }

// 카테고리 펼침 검증 (자식 노드 노출 여부)
const expanded = document.querySelector('[data-expanded="true"], .expanded') !== null;
```

### 13-D-3. 회사·직무 → 잡코리아 카테고리 매핑

| 클릭업 직무명 패턴 | 1차 | 2차 | 3차 |
|------------------|-----|-----|-----|
| Backend/Frontend/AI Engineer | IT 개발·데이터 | 개발자 | 백엔드/프론트엔드/AI엔지니어 |
| Product Manager / PO / PM | IT 개발·데이터 | 기획자 | 서비스기획자/PO |
| Product Designer | 디자인 | UI/UX | UX·UI 디자이너 |
| 마케터 / Brand Marketer / Growth | 마케팅·광고·MD | 마케팅 | 브랜드마케터/퍼포먼스마케터 |
| Content Marketer / Editor | 마케팅·광고·MD | 콘텐츠 | 콘텐츠 에디터 |
| Sales / BD / Account Manager | 영업·고객상담 | 영업 | 기술영업/B2B영업 |
| 기술영업 / Technical Sales | 영업·고객상담 | 영업 | 기술영업 |
| HR / Recruiter / People Ops | 인사·총무·노무 | 인사 | 리쿠르터/HRBP |
| Finance / FP&A / Accountant | 회계·세무·재무 | 재무 | FP&A/회계 |
| Strategy / Corp Dev | 경영·기획·전략 | 전략기획 | 사업기획 |
| 강사 / 멘토 / 커리어 코치 | 교육 | 강사 | 교육강사 |
| 콘텐츠 PD / 영상 / 디자이너 | 미디어 | PD·연출 | 콘텐츠PD |
| 보안 / Security | IT 개발·데이터 | 보안 | 정보보안 |
| Data Analyst / Scientist | IT 개발·데이터 | 데이터 | 데이터분석가 |
| Operations / Project Manager | 경영·기획·전략 | 운영기획 | 프로젝트매니저 |

직무명 keyword fuzzy match. 매핑 없으면 "**경영·기획·전략 → 기타**" 폴백.

---

### 13-C. 정정 발송 절차 (R13 신설, 2026-05-22 트랙 D 사고 후속)

**트리거**: 사장님이 "잘못 보낸 후보자에게 정정 발송" 명령 또는 SKILL 자체 검증으로 mismatch 감지.

```
[1단계] 잘못 보낸 후보자 식별
  - 트랙별 발송 명세 (rNo + 발송 JD + 정확한 JD) 확보
  - Discord 발송 로그에서 추출 또는 사장님 명시

[2단계] 올바른 등록 포지션 정비
  - SKILL §13-A 자동 등록 fallback 으로 정확한 포지션 신규 등록
  - 포지션 명은 회사명 + 직무명 정확히 (예: "모벤시스 기술영업 매니저")
  - 중복 등록 OK (사장님 명시)

[3단계] 정정 메시지 템플릿
  - 첫 줄: 정정 안내 + 사과
  - 본문: 후보자별 매칭 근거 + 올바른 회사·포지션 강조
  - 시그니처: Tim Sangmokang / valuehire.cc

  예시:
  ```
  안녕하세요. 테크 서치펌 밸류커넥트의 헤드헌터 강상모 입니다.

  앞서 전송된 포지션 정보가 잘못 매칭되었습니다. 정중히 사과드립니다.
  정확한 포지션 정보로 다시 안내드립니다.

  {올바른 회사명}의 {올바른 직무명} 포지션입니다.
  {후보자별 매칭 근거 1줄}이 좋으셔서 이 포지션을 안내드립니다.

  앞선 안내는 무시해 주시고 본 안내가 정확한 포지션입니다.
  꼭 응해주시지 않아도 차후 커리어에 대해 말씀 나눠보고 싶습니다.

  - valuehire.cc
  감사합니다.
  No1. Tech Searchfirm Valueconnect Inc.
  ```

[4단계] R12 미리보기 게이트 적용
  - 첫 후보자 미리보기 캡처 → Discord 송부 → 사장님 "OK" 받기
  - 사장님 OK 후 동일 패턴 나머지 3명 자동 진행 (메시지 후보자별 매칭 근거만 변경)
  - 4명 완료 시 종합 Discord 보고

[5단계] 잔여 건수 추가 차감 인지
  - 정정 발송 = 추가 1건 차감 (기존 발송 + 정정 발송 = 2건/후보자)
  - 사장님께 차감 변동 보고
```

### 13-B. 등록 포지션 직무 일치 검증 (R12 상세)

**❌ 금지 패턴 (트랙 D 사고 사례)**:
```
검색 키워드: "모벤시스" (회사명만)
   ↓
결과: "모벤시스, Physical AI Research" 1건 매칭
   ↓
회사명 일치 → 자동 선택 → 발송
   ↓
🛑 사업개발/기술영업 후보자에게 R&D 엔지니어 JD 자동 첨부
```

**✅ 강제 패턴 (R12)**:
```
검색 키워드: "모벤시스" → N건 결과
   ↓
각 결과의 직무명 추출 (예: "Physical AI Research", "기술영업 매니저")
   ↓
JD 직무명(예: "기술영업 매니저")과 단어 일치 검증
   ↓
일치하면 선택 / 불일치하면 §13-A 자동 등록 fallback 진입
   ↓
미리보기 click → 캡처 → Discord 송부 → 사장님 OK → 제안보내기
```

**미리보기 사장님 OK 게이트** (R12 명시):
- 미리보기 페이지 URL: `https://www.jobkorea.co.kr/Corp/Person/PositionOfferPreview`
- 전체 페이지 screenshot 캡처
- Discord embed 로 송부 — title "🔍 발송 직전 미리보기 — {후보자} / {포지션}"
- 사장님 답신 "OK" / "발송" / "GO" 받기 전 제안보내기 click 금지
- R10(자율 진행) 보다 R12 우선 (사고 재발 방지)

### 17-A-1. Discord embed 형식 — 절대 강제 (R11)

**❌ 금지 패턴**:
```json
// 후보자 4명을 fields 안에 묶으면 URL 못 넣음
{"title": "트랙 결과", "fields": [
  {"name": "김OO 90점", "value": "...rNo=20777597..."}  // ❌ URL 없음
]}
```

**✅ 강제 패턴**:
```json
[
  {
    "title": "🏆 1. 김OO (남, 만34세) — 90점",
    "url": "https://www.jobkorea.co.kr/corp/person/find/resume/view?rNo=20777597",
    "color": 5763719,
    "description": "명지대 산업경영공학 / 코그넥스 GAM 매니저 / 자동화·머신비전 10년\n**매칭**: 모벤시스 JD 완전 직결",
    "footer": {"text": "rNo=20777597 · 트랙 D #1 · 잔여 259/300"}
  },
  { "title": "🥈 2. 김OO ...", "url": "https://...rNo=12040391", ...},
  { "title": "🥉 3. 이OO ...", "url": "https://...rNo=29848535", ...},
  { "title": "⭐ 4. 이OO ...", "url": "https://...rNo=17288344", ...}
]
```

**송부 직전 검증 (자동)**:
```javascript
for (const embed of embeds) {
  if (!embed.url && embed.title?.includes('OO')) {  // 후보자 embed
    throw new Error(`Discord embed url 누락: ${embed.title}`);
  }
}
```

검증 실패 시 abort + 재구성 후 재송부 (R11 우선).

### 19-A. 강제 재시도 정책 (R9 상세)

| 장애 신호 | 행동 | 최대 재시도 |
|----------|------|----------|
| 페이지 로딩 timeout / CDP freeze | 페이지 reload + 30초 wait → 재시도 | 5회 |
| 세션 만료 / 로그인 페이지 리다이렉트 | SKILL §2-A 자동 재로그인 → 원래 페이지 재진입 → 재시도 | 3회 |
| 등록 포지션 검색 0건 | 회사명 → 회사+직무 → 직무명 → 스킬명 fallback → 그래도 0건이면 §13-A 자동 등록 | 4단계 fallback |
| textarea 한국어 자모 분리 | JS .value 실패 시 → clipboard+cmd+v 폴백 → 그것도 실패 시 computer.type 한 글자씩 | 3 방법 |
| textarea default 메시지 잔존 (clear 불완전) | (1) JS: `ta.focus(); ta.setSelectionRange(0, ta.value.length); document.execCommand('delete');` (2) JS native setter: `Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(ta, ''); ta.dispatchEvent(new Event('input', {bubbles:true}));` 후 즉시 setter.call(ta, newMsg) (3) cmd+A → Delete → 신규 paste | 3 방법 (2026-05-22 트랙 C 라이브 발견) |
| 포지션 등록 모달 직무 트리 선택 시 CDP timeout | 기존 등록 포지션 재활용 (도메인 미스매치는 textarea 메시지에서 정확한 회사·포지션 명시로 보정) | 1차 회피 |
| 모달 미열림 / 버튼 click 무반응 | wait 3초 + 다시 click → 좌표 click 폴백 → JS .click() 폴백 | 3 방법 |
| **Layered modal stuck** (DOM `visible:false` 이지만 화면에 표시 — "차감 확인" 안내 시) | (1) 좌표 click 우선 — DOM selector 무시 (2) 모달 inner button JS `.click()` 강제 (3) `document.querySelectorAll('button').forEach(b => { if (b.innerText.includes('확인') && b.offsetParent === null) { b.style.visibility='visible'; b.click(); } })` | 3 방법 (2026-05-22 트랙 B 라이브 발견) |
| **자동 등록 fallback 성공 패턴** (SKILL §13-A) | "뤼튼" 검색 0건 → 채용포지션 등록 페이지 → 정규직·직무카테고리·서울·JD 본문 자동 입력 → 등록 완료 → 모달 재진입 → 자동 매칭 | 트랙 B 라이브 검증 (2026-05-22) |
| **한국어 키워드 정확 입력 (자모 검증)** | `String.fromCodePoint(0xB93C, 0xD2BC)` 으로 "뤼튼" 같은 회사명 입력 — JS literal 한국어보다 안정 | 트랙 B 라이브 검증 |
| **헤드헌터 select 패턴 (잡코리아 특수 UI)** | 시각적 dropdown 이 실제로는 `input[type=radio][name="choose-headhunter"][data-info=...]` 안에 숨겨짐. JS: `const r = document.querySelector('input[name="choose-headhunter"][data-info*="Tim"]'); r.checked = true; r.click(); r.dispatchEvent(new Event('change', {bubbles:true}));` | 트랙 A 라이브 검증 (2026-05-22) |
| **등록 포지션 select 패턴 (잡코리아 특수 UI)** | 동일 패턴 `input[type=radio][name="lb_position_info"][data-title="뤼튼 Backend Engineer"]`. radio click + change event | 트랙 A 라이브 검증 |
| **"입력 내용 저장" 체크박스 효과** | 1번째 발송 시 ✓ 체크 → 헤드헌터/전화/이메일/부서명/응답기간 모두 다음 발송 자동 복원 (1회 입력 1회 저장) — 2~N번째 발송 속도 대폭 향상 | 트랙 A 라이브 검증 |
| 빈 검색 결과 (824 → 0명) | 필터 1개씩 완화 → 키워드 OR 추가 | 3회 |
| Discord webhook 실패 | exponential backoff (1s, 2s, 4s) 재시도 | 3회 |
| 잡코리아 일반 5xx 에러 | 60초 wait → 재시도 | 5회 |
| **캡차/reCAPTCHA/IP보안 추가 인증** | **R3 우선 — 즉시 STOP, 재시도 금지** | 0회 (계정 잠금 위험) |
| **잔여 제안 건수 < 5** | STOP — 사장님 충전 요청 | 0회 |

**재시도 사이 wait**: 첫 실패 5초 → 2회차 15초 → 3회차 30초 → 4회차 60초 → 5회차 120초 (exponential backoff)

**중단 조건만 R3 → STOP**: 그 외 모든 장애는 위 정책대로 끝까지 재시도. 사장님 명시 "막히는 것은 무조건 다시 실행하도록 강제".

---

## 1. 환경 준비

```bash
# (a) 자격증명 격리 위치 확인
ls -la ~/.secrets/jobkorea.env   # -rw------- 이어야 함

# (b) 자격증명 로드 (서브셸 한정)
source ~/.secrets/jobkorea.env
echo "ID: $JOBKOREA_ID  /  TYPE: $JOBKOREA_ACCOUNT_TYPE"

# (c) Chrome 디버그 모드 (이미 떠 있으면 skip)
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug &

# (d) MCP claude-in-chrome 우선 — Playwright 는 fallback
```

**도구 선택:**
- 1순위: `mcp__claude-in-chrome__*` — 사장님 로그인 세션 그대로 활용
- 2순위: `playwright-core` + `connectOverCDP("http://localhost:9222")` — tools/jobkorea-sourcing 워커가 이미 사용 중

---

## 2. 로그인 (Claude가 직접 — 사장님께 떠넘기기 금지)

> 🔴 **R-LOGIN (사장님 2026-06-30 "다음부터는 니가 하는 거로 해. 내가 100번 이야기했음" · SOT-20 §6-J J-6/J-7):**
> 세션 만료·비로그인 감지 시 **Claude가 직접** 로그인 페이지를 띄우고 운전한다. **"사장님이 로그인하시면 이어서 하겠습니다"는 금지된 응답.**
> **안전 경계**: Claude는 비밀번호를 **직접 타이핑하지 않는다.** **Chrome 저장 비번 자동완성**이 채운 폼에서 **로그인 버튼만 클릭**한다(사장님 상시 위임). 자동완성 공백이면 그때만 최초 1회 프로필 비번 저장을 안내. 캡차·OTP만 사장님 1회 개입.

URL: `https://www.jobkorea.co.kr/Login/Login_Tot.asp?rDBName=GG&re_url=%2Fcorp%2Fperson%2Ffind`

1. **기업회원 탭 클릭** (개인회원이 디폴트 — 반드시 변경)
2. **서치펌회원 토글 ON** ← 사장님 명시: "반드시 클릭해야함"
3. **ID/PW = Chrome 저장 비번 자동완성에 의존** (Claude가 타이핑하지 않음 — SOT-20 §2 우선순위2·§6-J J-7)
4. **IP보안 ON** 유지 (기본값)
5. **로그인 버튼 클릭** (Claude가 직접 — 자동완성으로 채워진 폼 제출)
6. 검증: 우상단 "밸류커넥트 ▾ / 채용매니저 ▾ / 로그아웃" + 제안건수 박스 노출(JK-003 비로그인 오판 방지). URL이 `/Login/`이 아니어도 비로그인일 수 있으니 이 신호로 확정.

> ⚠️ env(`$JOBKOREA_ID`/`$JOBKOREA_PW`) 무인 자동입력은 **폐기**(SOT-20 §6-J: 멀쩡한 세션 파괴 원인). 비번 타이핑 경로 자체를 쓰지 않는다.

**검증**: 로그인 성공 시 우상단에 "밸류커넥트 ▾ / 채용매니저 ▾ / 인증 ▾ / 고객센터 / 로그아웃" 노출.

### 2-A. 세션 만료 자동 재로그인 (2026-05-22 사장님 명시)

발송 시도 중 "**기업 로그인이 필요한 서비스입니다**" 모달 / Login 페이지 리다이렉트 감지 시 자동 재로그인 후 발송 흐름 이어서 진행:

```
[감지 신호]
  - URL 에 /Login/ 포함
  - 모달 텍스트 "기업 로그인이 필요한 서비스입니다"
  - 포지션 제안 버튼 click 시 로그인 페이지로 튐
  ↓
[자동 재로그인 절차]
1. 현재 탭에서 https://www.jobkorea.co.kr/Login/Login_Tot.asp?rDBName=GG&re_url=%2F 진입
2. 기업회원 탭 click (디폴트가 개인회원 → 변경)
3. 서치펌회원 토글 ON click (필수, 라디오 또는 체크박스)
4. ID 입력 박스 → $JOBKOREA_ID (~/.secrets/jobkorea.env 에서 source)
5. PW 입력 박스 → $JOBKOREA_PW
6. IP보안 ON 유지 (디폴트)
7. 로그인 버튼 click
8. wait 5초
9. 성공 검증: 우상단 "밸류커넥트 ▾" 노출 또는 "/corp/" 경로 진입
10. 원래 후보자 페이지로 복귀: history.back() 또는 rNo URL 재진입
11. 발송 흐름 (포지션 제안 click → 모달 → 메시지 작성 → 발송) 재개
```

⚠️ **자동 재로그인 중단 조건** (R3 우선):
- 캡차(reCAPTCHA, "보안 인증 필요") 노출 → 즉시 STOP
- "IP 차단", "비정상 접근" 페이지 → 즉시 STOP
- 로그인 시도 3회 실패 → 즉시 STOP (계정 잠금 위험)
- "이메일·문자 추가 인증 필요" → 즉시 STOP (사장님 수동 진행)

위 중단 조건 발생 시 OPS_INCIDENTS Discord 알림 + 사장님께 수동 로그인 요청 메시지.

---

## 3. 인재검색 진입

URL: `https://www.jobkorea.co.kr/corp/person/find`

진입 후 상단에 **"포지션제안 서비스 / 2026.07.29 까지 / 남은 제안 건수 N/300"** 박스 노출. 이 숫자가 한 턴마다 차감됨.

---

## 4. 상세검색 필터 (필수)

1. 상단 **상세검색 ▼** 클릭 → 패널 펼침
2. **학력/전공** 탭 (디폴트):
   - ✅ 대학교(4년) 졸업
   - ✅ 대학원 졸업
   - ✅ 재학중/졸업예정/중퇴/수료/휴학 포함 (체크박스)
   - ❌ 대학(2,3년) 졸업
   - ❌ 고등학교 졸업 이하
   - ❌ 해외졸업(예정) 제외 — uncheck
3. 다른 탭(산업/직급/직책/고용형태/연봉/외국어/우대조건) 은 포지션 따라 선택적으로

---

## 5. 통합검색 키워드 입력 (가장 중요한 단계)

검색 박스 위 **통합검색 ▼** 드롭다운에서 키워드 모드 선택:

| 모드 | 의미 | 예시 |
|------|------|------|
| **AND** (그리고) | 모든 키워드 포함 | 산업/도메인 묶음 |
| **OR** (또는) | 하나 이상 포함 | 직무 동의어 묶음 |
| **NOT** (제외) | 제외할 키워드 | 신입/인턴 |

### 한국어 입력 패턴 (사람인과 동일 — 라이브 검증된 절차)
```
[step 1] 키워드 박스 click → focus
[step 2] javascript_tool: navigator.clipboard.writeText("키워드")
[step 3] computer: key "cmd+v"        ← 한국어 자모 timing 우회
[step 4] computer: wait 2초
[step 5] computer: key "Return"       ← chip 등록 (필수)
```

### 5-A. 도메인별 키워드 매핑 가이드 (사장님 명시 — 비IT 도메인도 같은 흐름)

JD 본문을 5축으로 분해 — 각각 AND/OR/NOT 어디로 보낼지 결정:

#### IT/개발 (뤼튼 Product Engineer 예시)
| 축 | 매핑 | 예시 |
|----|------|------|
| 산업 | AND | "AI", "B2C", "SaaS", "핀테크" |
| 직무 | OR (영문 우선) | "Product Engineer", "Full Stack", "Backend Engineer" |
| 스킬 | OR (1~2개, 영문) | "Nest.js", "Next.js", "Node.js", "React" |
| 경력 | 좌측 패널 | 2~6년 |
| 제외 | NOT | "신입", "인턴", "프리랜서" |

#### 마케팅·디자인 (뤼튼 Global Brand Marketer 예시)
| 축 | 매핑 | 예시 |
|----|------|------|
| 산업 | AND | "AI", "B2C", "Consumer" |
| 직무 | OR (영문 우선) | "Brand Marketing", "Growth", "Content", "Performance Marketing", "Marketing Manager" |
| 스킬/특수요건 | OR | "Influencer", "Reddit", "TikTok", "Global", "북미", "영어 능통" |
| 경력 | 좌측 패널 | 3~8년 |
| 직무 카테고리 (좌측 필터) | 선택 | **마케팅·디자인** (잡코리아 직무 트리) |
| 제외 | NOT | "신입", "프리랜서" |

#### 세일즈·BD
| 축 | 매핑 | 예시 |
|----|------|------|
| 산업 | AND | (도메인별, 예: "SaaS", "Enterprise", "B2B") |
| 직무 | OR (영문 우선) | "Sales", "Business Development", "Account Manager", "Enterprise Sales" |
| 스킬 | OR | "B2B", "Enterprise", "Salesforce", "ARR" |
| 직무 카테고리 | 선택 | **영업·고객상담** |

#### HR·재무·운영
| 축 | 매핑 | 예시 |
|----|------|------|
| 직무 | OR | "HRBP", "Recruiter", "People Ops", "Finance", "Accounting", "COO", "Strategy" |
| 직무 카테고리 | 선택 | **인사·총무·노무** / **회계·세무·재무** / **경영·기획·전략** |

#### 해외·외국어 우대 (포지션 어느 도메인이든)
| 우대 | 좌측 필터 |
|------|----------|
| 영어 능통 | 상세검색 → 외국어/해외경험 → 영어 |
| 북미 거주 | 상세검색 → 외국어/해외경험 → 해외 근무 경험 포함 |
| 영어 비즈니스 레벨 필수 | NOT 제거 + 외국어/해외경험 필수 체크 |

**금지 패턴:**
- ❌ 너무 specific 한 AND 여러 개 → 결과 0명
- ❌ Enter 안 누르고 검색 → chip으로 안 등록됨
- ❌ `form_input value="한국어"` → 빈 값 들어감 (clipboard + cmd+v + Enter 만)

---

## 6. 좌측 패널 — 연차 / 추가 필터

- **경력 ▼**: 신입 체크박스 OR `N ~ N 년` 범위 입력
- (선택) 나이/성별, 구직 상태, 이력서 업데이트일, 입사 지원일, 최근 활동일, 평균 근속년수, 기업 규모, 선호 조건

연차는 JD 의 "경력 N~N년" 표기를 그대로 매핑.

---

## 7. 정렬 — '추천순'

검색 결과 우상단 정렬 드롭다운에서:
- ❌ 업데이트일순 (default)
- ✅ **추천순** ← 사장님 명시
- ❌ 경력순
- ❌ 학력순

---

## 8. 후보자 카드 화살표 펼치기 → 경력 평가

각 카드 우측 **▾ 화살표** 클릭하면 **경력사항** 펼침:

```
경력사항
총 경력 N년 , 평균 근속 N년 이상
회사1 │ 직책1 │ 기간1
회사2 │ 직책2 │ 기간2
회사3 │ 직책3 │ 기간3
...
```

### 자동 평가 — 100점 만점 (사장님 3축 명시)

| 축 | 가중치 | 만점 기준 | 감점 기준 |
|----|-------|----------|----------|
| **A. 학교 (35점)** | 35 | 인서울 4년제 OR 지방 국공립대 졸업 | 그 외 -10~-20 |
| **B. 이직 안정성 (30점)** | 30 | 각 직장 평균 근속 2년+ | 개월 단위 연속 이직 -20, 짧은 경력 전후 탄탄하면 ±0 |
| **C. 직무 직결성 (35점)** | 35 | JD 핵심 직무·스킬 명시 회사·직책 매칭 | 도메인/스킬 mismatch -10~-25 |

**자동 발송 임계값: 85점 이상**

### A. 좋은 학교 정의 (사장님 명시)
- **인서울 4년제**: 서울 소재 4년제 대학 (서·연·고·서강·성·한·중·경·외·시 + 건·동·홍 + 광운·인하·아주·세종·국민·숙명·이화 등)
- **지방 국공립대**: 지방 거점 국립대 (부산대·경북대·전남대·전북대·충남대·충북대·강원대·제주대·경상대 + 서울과기대·인천대·UNIST·DGIST·GIST·KAIST·POSTECH 등)
- **사이버대학·전문대학·해외 학사 단독은 감점**

### B. 이직 안정성 정의 (사장님 명시)
- ✅ 평균 근속 2년+ (예: 3년·2.5년·1.5년·2년)
- ❌ 개월 단위 연속 이직 (예: 6개월·8개월·10개월·1년 — 이런 패턴이면 -20)
- ⚠️ 중간에 1년 남짓 짧은 경력이 있어도 **전후 회사가 탄탄**하면 인정 (감점 없음)
- **유니콘/인재밀도 높은 조직 출신**(토스·당근·뤼튼·OpenAI 출신·네이버·카카오 등) → A 축 +5 보너스

### C. 직무 직결성 (JD 와 1:1 매핑)
- JD 의 "주요업무·자격요건·우대사항" 키워드가 후보자 경력에 얼마나 직접 등장하는가
- "AI 코딩 도구 활용 1인 개발 경험" 같은 specific 요건은 매칭 시 +10

---

## 9. Career Path 캡처 + Supabase 저장

화살표 펼친 상태(경력사항 패널 노출)에서:

```typescript
// (a) 펼친 영역 스크린샷 캡처
await page.locator('.career-detail-panel').screenshot({ path: snapshotPath });

// (b) 텍스트 추출 → 구조화
const careerPath = await page.evaluate(() => {
  const rows = Array.from(document.querySelectorAll('.career-detail-panel .career-row'));
  return rows.map(r => ({
    company: r.querySelector('.company')?.textContent?.trim(),
    role:    r.querySelector('.role')?.textContent?.trim(),
    period:  r.querySelector('.period')?.textContent?.trim(),
  }));
});

// (c) Supabase pipeline_candidates 또는 candidate_career_paths 테이블에 저장
await supabase.from('candidate_career_paths').insert({
  candidate_id,         // 잡코리아 rNo (resume number)
  source: 'jobkorea',
  career_json: careerPath,
  snapshot_path: snapshotPath,
  captured_at: new Date().toISOString(),
});
```

`candidate_career_paths` 테이블이 없으면 `pipeline_candidates.ai_assessment.career_path` JSONB 에 in-place 저장.

---

## 10. 프리랜서 필터 (자동 패스)

화살표 펼친 후 회사명에 **"프리랜서"** 또는 **"비공개"** + 직책에 "프리랜서/Freelancer/외주" 단어 포함 시 → **즉시 패스**, 평가 0점, 다음 카드로.

---

## 11. 프로필 상세 — 새창 진입

후보자 카드 **이름 클릭** 시 새 탭으로 `https://www.jobkorea.co.kr/corp/person/find/resume/view?rNo=<N>` 열림.

⚠️ **이 단계는 차감 0** — 안심하고 캡처/저장 가능.

```typescript
// 새 탭 감지
const newPage = await context.waitForEvent('page');
await newPage.waitForLoadState('domcontentloaded');

// (a) 풀페이지 스크린샷
await newPage.screenshot({ path: `${snapshotDir}/${rNo}.png`, fullPage: true });

// (b) 텍스트 추출 (이력서 본문)
const resumeText = await newPage.evaluate(() => document.body.innerText);

// (c) Supabase 저장 — pipeline_candidates 본체
await supabase.from('pipeline_candidates').upsert({
  source: 'ai_search:jobkorea:profile',
  source_id: `jobkorea:${rNo}`,
  raw_text: resumeText,
  ai_assessment: { score, school_score, mobility_score, fit_score, career_path },
  match_score: score,
  metadata: { resume_url, snapshot_path, captured_at },
});
```

---

## 12. 매칭 포지션 선택 (우리 회사 포지션 중 최적)

현재 우리(밸류커넥트)가 관리 중인 모든 포지션 중에서 이 후보자에게 가장 잘 맞는 포지션을 1개 선정:

```sql
-- pipeline_position_cards 에서 active 포지션 전부 + JD 본문
SELECT id, company_name, position_title, raw_payload->>'description' AS jd
FROM pipeline_position_cards
WHERE lifecycle_status IN ('active','sourcing')
ORDER BY created_at DESC;
```

LLM 매칭 점수 계산 (Claude/ChatGPT):
```
이 후보자({이름,학력,경력}) 와 가장 잘 맞는 포지션을 다음 중 고르고
1~100 점수와 한 줄 근거를 JSON 으로 답하라:
{positions...}
출력: {"position_id": "...", "match_score": N, "reason": "..."}
```

**최고 점수 포지션 1개만** 사용. 차순위는 보내지 않음.

---

## 13. 포지션 제안 모달 (1건 차감 안내 팝업)

후보자 상세 페이지 우측 **포지션 제안 버튼** 클릭 시 모달:
> "포지션 제안 시, 제안 건수 1건이 차감됩니다.
>  인재가 제안 수락 후, 연락처 정보를 확인하실 수 있습니다."

→ **확인** click

다음 모달 (실 제안 작성):
- **제안인재**: {이름}OO (남/여, 만N세)
- **포지션 정보**: ⦿ 등록 포지션 ⦾ 진행중 공고  
  → **등록 포지션 명 검색** 박스에서 step 12에서 고른 포지션 검색·선택

### ⚠️ 등록 포지션 검색 키워드 순서 (R6 보강 — 2026-05-22 라이브 학습)

잡코리아 등록 포지션은 사장님이 보통 **"{회사명} {직무}"** 한국어/한영혼용으로 등록 (예: "뤼튼 Backend Engineer", "코드잇 PM"). 따라서 검색 순서:

1. **회사명(한국어)** — "뤼튼", "코드잇", "당근", "토스" — 가장 먼저
2. **회사명+직무** — "뤼튼 Backend", "코드잇 PM"
3. **직무명만** — "Backend Engineer", "Product Engineer", "Brand Marketer"
4. **스킬·도구명 (최후)** — "Nest.js", "React" — 사장님이 이렇게 등록하실 가능성 거의 없음

❌ **금지**: 스킬·도구명("Nest.js") 부터 검색하면 0건 → R6 STOP 오발동 (실제로는 등록 포지션 있는데 못 찾는 경우)

✅ **권장 검증**: 검색 0건 시 → 회사명만 → 직무 일반명 순서로 fallback 시도. 그래도 0건이면 진짜 미등록.

### 13-A. 검색 0건 진짜 미등록 시 — 포지션 자동 등록 fallback (사장님 2026-05-22 명시: "중복 등록해도 좋다")

**원칙**: 사장님 일일이 등록 안 하셔도 자동 흐름이 등록까지 마무리. 중복 등록 허용 (잡코리아는 같은 회사·직무를 여러 번 등록해도 무방).

```
[검색 결과 0건 감지]
  ↓
모달 우측 [+ 채용포지션 등록] 버튼 click
  ↓
새 탭/페이지 진입 → 채용포지션 등록 폼
  ↓
필수 필드 자동 입력 (JD 기반):
  - 회사명: "뤼튼테크놀로지스" (또는 JD 의 회사명)
  - 포지션 명: "{회사 약칭} {직무명}" 패턴 — 예: "뤼튼 Product Engineer", "뤼튼 OOC Brand Marketer (북미)"
  - 직무 카테고리: JD 직무 → 잡코리아 카테고리 매핑 (예: Product Engineer → 백엔드개발자/프론트엔드개발자)
  - 고용형태: 정규직
  - 근무지역: 서울 (JD 명시 시 그대로)
  - 직무 내용: JD 본문 "주요업무" 섹션
  - 자격요건: JD 본문 "자격요건" 섹션
  - 우대사항: JD 본문 "우대사항" 섹션
  - 혜택: JD 본문 "혜택 및 복지" 섹션
  ↓
[등록] 버튼 click → 등록 완료
  ↓
포지션 제안 모달 재진입 (또는 다시 열기)
  ↓
"등록 포지션 명 검색" 박스에 방금 등록한 명칭 검색 → 1건 매칭 → 선택
  ↓
나머지 18~20단계 정상 진행 (메시지 + 헤드헌터 + 발송)
```

**중복 등록 정책**: 잡코리아는 동일 회사·동일 직무명 중복 등록 허용. 매번 발송 트랙마다 새로 등록해도 시스템 차단 없음. 사장님 명시 "검색해보고 없으면 중복 등록해도 좋다".

**JD 본문 출처**: 사장님이 메시지로 보내주신 JD 텍스트가 1차 — `pipeline_position_cards.raw_payload.description` 이나 메시지 컨텍스트에서 추출.

**자동 등록 실패 시 fallback**: 등록 폼 필드 변경 등으로 실패하면 → 사장님께 "잡코리아 채용포지션 등록 폼 변경 — 직접 등록 후 알려주세요" Discord 알림 + STOP.
- **제안내용**: textarea (아래 §14 템플릿)
- **응답기간**: 디폴트 5일 후 (그대로)
- **담당 헤드헌터**: 드롭다운 → **Tim Sangmokang** (사장님 default — value=valueconnect_001 의 표시명. "강상모" 옵션도 있으나 사장님은 Tim 사용)
- **부서명**: (선택)
- **전화번호**: 010-3929-7682
- **휴대폰번호**: (선택, 알림 문자 받기 체크)
- **이메일**: sangmokang@valueconnect.kr ← 비공개 체크 X

---

## 14. 메시지 템플릿 — '저장된 입력 내용 불러오기'

**저장된 입력 내용 불러오기** 버튼이 폼 우측에 있음. 클릭하면 사장님이 미리 저장한 템플릿 로드.

저장된 템플릿이 없거나 포지션 맞춤 변형이 필요한 경우 — 아래 3종 중 1개 자동 채우기:

### Template A — 첫 인사 (포지션 명시)
```
안녕하세요.

테크 서치펌 밸류커넥트의 강상모 라고 합니다. 인사드리게 되어 반갑습니다 :)
{회사명}에서 좋은 기회로 인재를 모시고 있습니다.
관련해서 말씀 나눠보고 싶습니다.

감사합니다 !
강상모 드림
```

### Template B — 후보자 맞춤 (한 줄 근거 포함, **권장**)
```
안녕하세요.

테크 서치펌 밸류커넥트의 헤드헌터 강상모 라고 합니다.
{한_줄_매칭_근거 — 예: "Node.js 기반 백엔드 5년 경험과 1인 개발 운영 경험"}이 좋으시고
커리어를 잘 유지해오셔서 관심이 갔는데요,
혹시 {회사명}의 {포지션명} 포지션 고려 가능하실까요?
꼭 응해주시지 않아도 차후 커리어에 대해서 말씀 나눠보고 싶습니다.

- valuehire.cc (본인 레쥬메와 직결되는 커리어 기회들을 구독해드립니다.)

감사합니다.
No1. Tech Searchfirm Valueconnect Inc.
```

### Template C — 입력 내용 저장 체크 (필수)
모달 하단 **☐ 입력 내용 저장** → ✅ 체크 (다음번 같은 헤드헌터·연락처 재사용)

---

## 15. 미리보기 (15% — 발송 직전 게이트)

**미리보기** 버튼 click → 새 창 `https://www.jobkorea.co.kr/Corp/Person/PositionOfferPreview` 열림. 후보자에게 실제 가는 형태로 렌더링됨.

### 미리보기 게이트 (자동 발송 판정)

```typescript
const SHOULD_AUTO_SEND = (
  candidate.score >= 85 &&            // R0
  candidate.school_score >= 25 &&     // A 축 70% 이상
  candidate.mobility_score >= 20 &&   // B 축 67% 이상
  candidate.fit_score >= 25 &&        // C 축 70% 이상
  !candidate.freelancer_flag &&       // R5
  candidate.matched_position_score >= 80
);

if (SHOULD_AUTO_SEND) {
  // 미리보기 캡처 저장 + 디스코드 #candidates 알림 + 발송 click
} else {
  // 미리보기 캡처를 사장님께 보여드리고 컨펌 대기
  console.log("85점 미만 후보자 — 발송 보류, 사장님 컨펌 필요");
}
```

---

## 16. 발송 — '제안보내기' 버튼 click

`miribogi` 창 닫고 본 모달로 돌아온 뒤 **제안보내기** click.

발송 성공 시:
- 잡코리아 측 토스트: "제안 발송 완료"
- 우리 측 즉시 액션:
  1. 디스코드 `#ops-candidates` 알림 (회사·포지션·후보자 + 점수 + 근거)
  2. 칸반보드 `/kanban?board=FY26_Candidates` 에 후보자 카드 INSERT
  3. `candidate_activity_log` INSERT (event_type='jobkorea_offer_sent')
  4. `pipeline_candidates.metadata.outreach.jobkorea_offer_at = NOW()`

---

## 17. 칸반보드 등록 + 컨택 기록

```sql
INSERT INTO pipeline_candidates (
  source, source_id, name, ai_assessment, match_score, metadata, board_id
) VALUES (
  'ai_search:jobkorea:profile',
  'jobkorea:<rNo>',
  '<회사>/<포지션>/<이름>',
  jsonb_build_object(
    'score',          92,
    'school_score',   32,
    'mobility_score', 28,
    'fit_score',      32,
    'rationale',      '...한 줄 근거...',
    'career_path',    '[...JSON...]',
    'matched_position_id', '<uuid>'
  ),
  92,
  jsonb_build_object(
    'outreach', jsonb_build_object(
      'channel',         'jobkorea',
      'message_template','B',
      'sent_at',         NOW(),
      'rNo',             '9304968'
    ),
    'snapshot_path', '/tmp/jobkorea-snapshots/9304968.png'
  ),
  'FY26_Candidates'
);

INSERT INTO candidate_activity_log (candidate_id, event_type, ts, payload)
VALUES (
  <candidate_id>,
  'jobkorea_offer_sent',
  NOW(),
  jsonb_build_object('position_id', '...', 'preview_url', '...', 'score', 92)
);
```

---

## 17-A. Discord 알림 규칙 (사장님 2026-05-22 명시 — 절대)

후보자 Discord 송부 시 **반드시 다음 3종 정보 포함**:
1. **profile URL** (필수) — `https://www.jobkorea.co.kr/corp/person/find/resume/view?rNo={rNo}` 또는 사람인 동등 URL. Discord embed 의 `url` 필드에 넣으면 title 이 클릭 가능 링크가 됨
2. **후보자 프로필 요약** — 이름·성별·나이·학교·소속·핵심 스킬·매칭 근거 한 줄
3. **100점 만점 매칭 점수** — title 또는 fields 에 명시

❌ URL 누락 = 사장님이 클릭 못 함 = 평가/제안 불가능 → **반드시 재송부**

embed 형식 예시:
```json
{
  "title": "🏆 1. 강OO (남, 만31세) — 91점",
  "url": "https://www.jobkorea.co.kr/corp/person/find/resume/view?rNo=15161326",
  "description": "중앙대 컴공 / 장례박사 부장 6년2개월 / NestJS+React 1인 개발\\n**스킬**: ...\\n**근거**: ...",
  "footer": {"text": "rNo=15161326 · 재직중 · 평균근속 3년+"}
}
```

## 18. 한 턴 완료 후 보고 형식

사장님께 디스코드 `#ops-candidates` + Claude Code 응답으로:

```
🟢 잡코리아 한 턴 완료 — {회사} / {포지션}
검토 후보자: N명 (펼친 카드)
85점 이상 자동 발송: M명
85점 미만 사장님 컨펌 대기: K명
패스(프리랜서/저점): P명

자동 발송 명세:
1. {이름1}OO · 92점 · {매칭근거 한 줄} · 칸반 등록 ✅
2. {이름2}OO · 88점 · ... · 칸반 등록 ✅

남은 제안 건수: {N}/300 (시작 시 {S}건, -{M}건 차감)
```

---

## 19. 오류 처리 (즉시 STOP 조건)

| 신호 | 행동 |
|------|------|
| URL 에 `/captcha`, `/block`, `/denied`, `/robot` | `JobkoreaBlockedError` 던지고 STOP + 디스코드 `#ops-incidents` 알림 |
| URL 에 `/Login/` 으로 리다이렉트 | `JobkoreaNotLoggedInError` — 사장님께 수동 재로그인 요청 |
| reCAPTCHA iframe 노출 | 즉시 STOP, 절대 자동 해결 시도 X |
| 사장님이 chrome 만지면 | tab focus event 감지 → 자동화 action 0 (메모리 [feedback_human_intervention_pause]) |
| 남은 제안 건수 < 5 | 새 한 턴 시작 거절 — 사장님께 충전 요청 |

---

## 20. 참고 자산

| 항목 | 위치 |
|------|------|
| 자격증명 | `~/.secrets/jobkorea.env` (chmod 600) |
| 기존 워커(공개공고 메타) | `tools/jobkorea-sourcing/src/jobkorea-worker.ts` |
| 워커 README | `tools/jobkorea-sourcing/README.md` |
| 4개 채널 메타 가이드 | `~/.claude/skills/talent-search/SKILL.md` |
| 시스템 감사 | `docs/engineering/qa/ai-search-system-audit-2026-05-21.html` |
| 디스코드 알림 | `tools/ai-search-shared/src/discord-notify.ts` (channel: `OPS_CANDIDATES`) |
| 프로필 아카이브 | `tools/profile-archiver/` |
| 칸반 보드 | `/kanban?board=FY26_Candidates` |

---

## 20-A. 클릭업 → 잡코리아 일괄 등록 워크플로우 (사장님 2026-05-22 명시)

### 트리거
- "클릭업 포지션 잡코리아에 일괄 등록"
- "고객사 포지션 일괄 등록"
- "{회사명} 모든 포지션 등록"

### 전체 흐름 (3 Phase, 안전 최대치 분산)

```
[Phase 0] 데이터 수집 (LLM only, chrome 자원 0)
  ├─ 클릭업 FY26ClientsPosition (list_id=901814621569) 전체 추출
  │   • mcp__claude_ai__clickup_filter_tasks 페이지별 (page=0,1,2,...)
  │   • status 분류: scraped / marketing / ai-ml-data / hr-finance-strategy-etc / closedpositions
  │   • 회사명 추출 (이름 시작의 "[회사명]" 또는 "[포지션]회사명,")
  │   • 중복 제거 (같은 회사·같은 포지션 명)
  └─ 회사별 그룹화 (회사명 → 포지션 list)

[Phase 1] 회사 8축 깊이 조사 (Opus subagent, chrome 자원 0)
  └─ §20-B 회사 조사 8축 가이드 적용

[Phase 2] 잡코리아 일괄 등록 (chrome 자동화, 안전 분산)
  ├─ 우선순위 회사부터 (Phase 1 결과 기준)
  ├─ 시간당 limit 15~20건 (캡차 회피 - 과거 데이터)
  ├─ 회사 사이 5분 wait
  ├─ 등록 폼 자동 입력:
  │   • 포지션 명: "[회사명] 직무명 (간략 자격)" (예: "뤼튼테크놀로지스 Backend Engineer (5년+)")
  │   • 직무 카테고리: SKILL §5-A 도메인 매핑
  │   • 고용형태: 정규직 / 계약직 / 인턴 (포지션 명에서 추출)
  │   • 근무지역: 회사 본사 (Phase 1 조사 결과)
  │   • JD 본문:
  │       (a) [About 회사] §20-B 조사 결과 250자 paste
  │       (b) [주요업무] 클릭업 원본 JD
  │       (c) [자격요건] 클릭업 원본 JD
  │       (d) [우대사항] 클릭업 원본 JD
  │       (e) [채용 정보] 모집인원·고용형태·근무지
  ├─ R12 미리보기 게이트 — 첫 1개만 사장님 OK 후 자동 batch
  └─ R3 캡차 즉시 STOP / R9 캡차 외 재시도

[Phase 3] 보고 + 메모리
  ├─ 회사별 등록 명세 Discord 송부
  ├─ HTML 보고서 — docs/operations/jobkorea-bulk-registration-{YYYY-MM-DD}.html
  └─ memory: project_jobkorea_bulk_registration_{YYYY-MM-DD}
```

---

## 20-B. 회사 깊이 조사 8축 (사장님 2026-05-22 "예리하게 조사")

각 회사마다 다음 8축 모두 조사. 표면적인 정보 X — 예리한 분석 강제. **WebSearch + WebFetch + outstanding.kr 스크레이핑 적극 활용**.

| 축 | 조사 내용 | 출처 우선순위 |
|----|-----------|---------------|
| **1. 재무** | 매출·영업이익·당기순이익 (최근 2~3년) / 자본 상황 (증자·차입) | 공시(전자공시·KOSPI/KOSDAQ) / 외부감사보고서 / 회사 공식 발표 |
| **2. 투자** | 시리즈 단계·valuation·투자자·최근 라운드 (2024~2026) | 더브이씨(thevc.kr) / 스타트업레이더 / 벤처스퀘어 / 회사 공식 |
| **3. 최근 뉴스** | 2025~2026 회사 동향 (제품 출시·M&A·확장·구조조정 등) | 매일경제·한국경제·조선비즈 / **outstanding.kr** |
| **4. 인원** | 총 직원 수 + 증감 (1년 전 대비) / 부서별 비중 | 잡플래닛 / 리멤버 / 회사 공식 채용 페이지 |
| **5. 매출 구조** | 수익 모델·세그먼트별 비중·고객사 구조 (B2B/B2C) | IR 자료 / 회사 블로그 / 사업보고서 |
| **6. 제품 예리한 분석** | 차별화·로드맵·강약점·경쟁사 대비 / 최근 신제품 | 회사 블로그·뉴스레터 / 제품 리뷰 / 경쟁사 자료 |
| **7. 임원 뉴스** | 최근 임원 영입·이탈·승진 (2025~2026) | LinkedIn·thevc.kr·기업 IR / 채용 뉴스 |
| **8. 유튜브 + 아웃스탠딩** | 회사 공식 유튜브 활동(구독자·최근 영상) / **outstanding.kr 보도 요약** | YouTube 채널 / outstanding.kr 검색 |

### ⚠️ 뉴스·임원 시간 한도 (사장님 2026-05-22 명시 "최근 뉴스만 — 조선시대 X")

**최근 6~12개월 (2025~2026) 만 인정**. 그 이전은:
- ❌ 2022·2023·2024 상반기 임원 변동
- ❌ 옛 시리즈 투자 라운드 (최근 라운드만)
- ❌ 단순 역사적 사실 ("2020년 OO에 인수" 같은 배경 정보는 한 줄만)
- ✅ 최근 6~12개월 임원 영입·승진·이탈
- ✅ 2025~2026 매출·실적·신제품
- ✅ 최근 라운드·M&A·합병·매각 추진

**예시 (잘못된 vs 올바른)**:
- ❌ "최재화 COO → 공동대표 승진 (2023)" — 2년 전 옛 정보
- ❌ "이재후 前 대표 → 네이버 이탈 (2022)" — 4년 전 옛 정보
- ✅ "김윤 CSO 영입 (2024.11, 前 SKT CTO)" — 임팩트 있는 최근 핵심
- ✅ "김진성 신임 대표 선임 (2025.2)" — 최근 핵심

작성 시 시점 명시 필수 — "(2025.4)" "(2024.11)" 등. 시점 없는 정보는 검증 후 사용.

### 8축 조사 결과 → JD About 섹션 (사장님 2026-05-22 명시 "더 깊이 — 매출·인원·재무·투자·경영자 인터뷰 다 녹여")

❌ **금지**: 250자 단순 요약 — 사장님이 "너무 약하다" 명시
✅ **강제 구조**: **600~900자, 6개 영역 모두 포함**

```markdown
[About {회사명}]
{한 줄 핵심 정체성·시장 포지션}.

📊 재무·성장
• 매출 (2024·2025 최근 2년 수치, 성장률)
• 영업이익 또는 ARR
• 시점 명시 (예: "2025 매출 471억 +1,432%")

💰 투자·자본
• 최근 라운드·시리즈·valuation (2024~2026)
• 리드 투자자 + 누적 투자자
• 누적 투자액

👥 조직
• 인원 (1년 전 대비 증감 명시)
• 본사·해외 거점
• 주요 부서·CIC 구조

🚀 최근 변화 (2025~2026 만, 옛 정보 X)
• 신제품·신규 시장 진입
• 합병·인수·CIC 신설
• IPO·상장 계획

💬 경영자 메시지 (필수 — 사장님 명시)
한 줄 인용 또는 핵심 비전 메시지.
"{대표·CSO·CTO 등 핵심 임원 발언 한 줄}" — {출처}
또는 인터뷰 핵심 한 줄 추출.

📰 최근 보도 (있으면)
Outstanding·언론 기사 한 줄 + URL.

[채용 매력 3 bullet]
• 회사 단계의 unique 매력 (IPO·M&A·확장 등)
• 직무·도메인의 차별점
• 문화·보상의 unique 강점
```

### 예시 — 뤼튼테크놀로지스 (600자+, 6 영역 모두)

```
[About 뤼튼테크놀로지스]
일 활성 사용자 500만 명의 한국 1위 AI 플랫폼 '뤼튼' + 캐릭터챗 '크랙(Crack)' + 일본 '캬라푸' 운영. 한국 1호 AI 서비스 유니콘 후보.

📊 재무·성장
• 2025 매출 471억 원 (전년 30억 → +1,432% 폭증)
• ARR $70M 달성 (2025 말) · 2027 ARR $700M 목표
• 매출 폭증 + 공격 확장 단계 (영업손실 588억)

💰 투자·자본
• 시리즈 B 누적 1,080억 원 (2025.4 마감) · 누적 총 1,300억 원
• Goodwater Capital 리드 / BRV·캡스톤·Antler·Z VC·우리벤처

👥 조직
• 약 81명 (소수정예 유지)
• AX CIC 설립 — B2B·B2G AI 트랜스포메이션 분리

🚀 최근 변화 (2025~2026)
• 2025.4 크랙(Crack) 독립 앱 정식 론칭
• 2025 중반 일본 '캬라푸' 출시 → 빠른 안착
• 2026.2 미국 본격 진입 발표 · 2028 IPO 목표

💬 이세영 대표 메시지
"비용 효율보다 제품 품질 우선 — 토큰을 10배 더 쓰더라도 더 나은 결과를 만든다. AI native B2C 1세대 Product Maker가 결정·구현·배포까지 직접 한 사람으로 책임진다."

📰 최근 보도
Outstanding "매출 15배 늘면서, 영업손실 2배 커진 뤼튼" — 공격적 글로벌 확장·인재 영입 단계.

[채용 매력]
• 2028 IPO 목표 → 스톡옵션 가치 잠재력
• 미국·일본 동시 글로벌 확장 단계
• "1주일 1배포" 빠른 사이클 + 결정권 큰 권한
```

**규칙**:
- 단순 사실 나열 X → 임팩트 있는 숫자 + 시점 + 메시지
- 경영자 인터뷰 누락 시 SKILL 위반 (사장님 명시)
- 600자 미만 시 자동 보강 (8축 조사 결과 재활용)
- 모든 숫자 시점 명시 (예: "2025.4" "2024년 말")

### 📋 5 회사 JD About 템플릿 (사장님 2026-05-22 명시 "이 양식이야 - paste 가능")

ASCII 양식 (이모지 X, 불릿 X, 하이픈만). 각 약 1,100자. 잡코리아 textarea 직접 paste 가능.

#### 1. 뤼튼테크놀로지스

```
[About 뤼튼테크놀로지스]
일 활성 사용자 500만 명의 한국 1위 AI 플랫폼 '뤼튼' + 캐릭터챗 '크랙(Crack)' + 일본 '캬라푸' 운영. 한국 1호 AI 서비스 유니콘 후보.

[재무/성장]
- 2025 매출 471억 원 (전년 30억 -> +1,432% 폭증)
- ARR $70M 달성 (2025 말 기준) / 2027 ARR $700M 목표
- 매출 폭증 + 공격 확장 단계 (영업손실 588억)

[투자/자본]
- 시리즈 B 누적 1,080억 원 (2025.4 마감) / 누적 총 1,300억 원
- Goodwater Capital 리드 / BRV, 캡스톤, Antler, Z VC, 우리벤처

[조직]
- 약 81명 (소수정예 유지)
- AX CIC 설립 - B2B/B2G AI 트랜스포메이션 분리

[최근 변화 (2025~2026)]
- 2025.4 크랙(Crack) 독립 앱 정식 론칭
- 2025 중반 일본 '캬라푸' 출시 - 빠른 안착
- 2026.2 미국 본격 진입 발표 / 2028 IPO 목표

[이세영 대표 메시지]
"비용 효율보다 제품 품질 우선 - 토큰을 10배 더 쓰더라도 더 나은 결과를 만든다. AI native B2C 1세대 Product Maker가 결정/구현/배포까지 직접 한 사람으로 책임진다."

[최근 보도]
Outstanding "매출 15배 늘면서, 영업손실 2배 커진 뤼튼" - 공격적 글로벌 확장/인재 영입 단계.
```

#### 2. 코드잇

```
[About 코드잇]
"5분마다 인생이 바뀐다" - 국내 1위 코딩 교육/부트캠프 플랫폼. AI/부트캠프 양대 축 성장으로 흑자 전환에 성공한 에듀테크.

[재무/성장]
- 2025 매출 307억 원 (2023 41억 -> 2025 307억, 2년 7.5배 성장)
- 2025 영업이익 56억 원 (첫 흑자 전환)
- 2026 매출 500억/영업이익 100억 전망 (2026 Q1 매출 100억 예상)

[투자/자본]
- 2025.9 Pre-IPO 98억 원 유치
- 코스닥 이익미실현 특례 자진 철회 -> 2026.3 일반 상장 전환

[조직]
- 약 40~50명 (소수정예)

[최근 변화 (2025~2026)]
- 2025 흑자 전환 - 매출 +70%/영업이익 32억(상반기)
- 2025 프론트엔드 부트캠프 수강생 1위, 백엔드 3분기 1위
- AI 채용 솔루션 'KADE' 출시 - 부트캠프 단일 의존도 분산
- 글로벌(영어권) 시장 진출 시작

[강영훈/이윤수 공동대표 메시지]
2026.3 일반 상장 전환 발표 - "코드 교육을 넘어 AI 시대 인재 인프라" 비전.

[최근 보도]
Outstanding "코드잇, 매출 307억 영업이익 56억.. 특례 대신 일반 상장 도전".
```

#### 3. 모벤시스

```
[About 모벤시스 (MOVENSYS)]
1996년 MIT 출신 양부호 박사가 보스턴에 세운 소프트서보가 모태인, PC 기반 모션 컨트롤 SW(최대 128축)로 장영실상을 수상한 토종 글로벌 자동화 기업.

[재무/성장]
- 2024 매출 149억 2,401만 원 (공시 기준)
- 비상장 비공개 (반도체/2차전지/디스플레이 안정 매출)

[투자/자본]
- 2020 크레센도 에쿼티 파트너스 투자
- 2024 자율주행로봇(AMR) 통합제어 SW 국책과제 선정

[조직]
- 약 58~60명 (잡코리아/사람인 기준)
- 한국, 미국(보스턴), 일본 3국 법인

[최근 변화 (2025~2026)]
- AMR 통합제어 SW 국책과제 수행 중
- 대만/중국 시장 본격 진출 추진 발표
- 반도체/2차전지/FPD 장비 동시 공급

[제품 핵심]
WMX: PC 기반 최대 128축 동시 제어 - 일본 OMRON/독일 Beckhoff와 경쟁하는 국산 유일 SW 모션 컨트롤. IR52 장영실상 수상(2022).

[김기훈 대표 메시지]
"하드웨어 PLC가 아닌 PC 기반 SW 모션 - 30년 MIT 기술력으로 반도체/2차전지 핵심 산업 자동화 책임진다."
```

#### 4. 스푼랩스

```
[About 스푼랩스 (SpoonLabs)]
오디오 라이브 '스푼(Spoon)'과 숏폼 드라마 '비글루(Vigloo)' 두 글로벌 콘텐츠 플랫폼을 운영하는 콘텐츠 테크 기업. 크래프톤이 1,200억 단독 투자.

[재무/성장]
- 2024 연결 매출 563억 원 (해외 매출 318억, 비중 60%+)
- 2024 상반기 250억 돌파 (역대 최고)
- 2023부터 2년 연속 흑자

[투자/자본]
- 2024.9 크래프톤 단독 1,200억 원 전략적 투자
- 누적 투자 1,400억 원+ 추정

[조직]
- 153명 (2025.9 기준, 전년 137명 -> +12%)
- 서울 강남구 본사

[최근 변화 (2025~2026)]
- 비글루 2025 연말결산 - 로맨스 장르 초강세, 스낵컬처 -> '몰입형 정주행' 전략
- 비글루 스튜디오 출시 - 숏드라마 업계 최초 제작사 성과 분석 시스템
- 일본/미국 오리지널 콘텐츠 마케팅 본격화

[제품 핵심]
Spoon: 일본 오디오 라이브 1위. Vigloo: 7개 언어 지원, 숏폼 드라마 글로벌. 해외 매출 60%+ 실질 글로벌 기업.

[최혁재 대표 메시지]
"한국 콘텐츠를 글로벌 사용자에게 - 오디오와 영상 듀얼 플랫폼으로 일본/미국 시장 공략."
```

#### 5. 지미존스 (역전에프앤씨)

```
[About 역전에프앤씨 (지미존스 마스터 프랜차이즈)]
가맹 1,000호점 '역전할머니맥주' + 미국 1위 샌드위치 브랜드 '지미존스(Jimmy John's)' 한국 마스터 프랜차이즈 운영 F&B 그룹.

[재무/성장]
- 2024 매출 1,086억 원
- 역전할머니맥주 가맹 1,000호점 돌파 (2025)
- 안정적 매출 + 가맹 확장 단계

[투자/자본]
- 케이스톤파트너스 2022 지분 100% 인수 (1,350억 원)
- PEF 100% 소유 - 빠른 가맹 확장 자금 여력

[조직]
- 약 82명 (2025.5 기준)
- 케이스톤 파견 임원 체제

[최근 변화 (2025~2026)]
- 2024.10 지미존스 강남역 1호점 -> 2025 직영 8개점 확대
- 공정거래위원회 지미존스 가맹사업 등록 완료
- 2026 가맹 본격화 예정
- 케이스톤 푸드올마켓 추가 인수 추진 - F&B 포트폴리오 확장

[제품 핵심]
역전할머니맥주: 호프 프랜차이즈 1,000호점 규모/인지도. 지미존스: 미국 본사 2,600개 매장 노하우 + 한국 현지화 메뉴.

[채용 매력]
- 매출 1,086억 안정 F&B + 지미존스 한국 1호 마스터 신사업 합류
- 케이스톤 PEF 자금력으로 빠른 매장 확장 계획
```

---

### ⚠️ 잡코리아 textarea ASCII 규칙 (사장님 2026-05-22 명시)

잡코리아 채용포지션 등록 폼은 **이모지와 불릿포인트를 '?' 로 인식**. 등록 후 화면에 깨진 글자 표시. 따라서:

**❌ 금지** (잡코리아에서 '?' 로 깨짐):
- 이모지: 📊 💰 👥 🚀 💬 📰 ✅ ⭐ 🎯 등 모든 emoji
- 유니코드 불릿: • · ◦ ▪ ▫
- 화살표 일부: → ← (일부 케이스 깨짐, → 는 종종 OK)
- 따옴표 일부: " " ' '  (curly quotes 깨짐)

**✅ 사용 가능** (ASCII 또는 안전):
- 하이픈: `-` (불릿 대신)
- 별표: `*`
- 대괄호: `[섹션 제목]`
- 일반 따옴표: `"..."`
- 줄바꿈 + 들여쓰기로 계층 표현
- 한글 + 영문 + 숫자 + 일반 기호 (.,?!:;-_)

**변환 예시**:
```
❌ (깨짐)
📊 재무·성장
• 2025 매출 471억 원
• ARR $70M 달성

✅ (정상)
[재무·성장]
- 2025 매출 471억 원
- ARR $70M 달성
```

**자동 변환 규칙** (SKILL JD About 생성 시):
1. 이모지 모두 제거
2. `•` → `-`
3. `📊·💰·👥·🚀·💬·📰` 헤더 → `[섹션 제목]`
4. `"..." ' '` → `"..." '...'`
5. 검수 단계에서 화면 캡처 → '?' 검색 → 발견 시 abort + 재작성

### 8축 부족 시 안전 장치

- 출처 빈약 시 `(추정)` 명시 — 거짓 정보 등록 절대 X
- 회사 공식 채용 페이지에서 직접 확인 시 1순위
- WebSearch 결과 2개 이상 일치할 때만 사실로 등록

| 구성 요소 | 위치 | 역할 |
|----------|------|------|
| Master SKILL | `~/.claude/skills/{name}/SKILL.md` | 단일 진실 출처(SSoT) |
| Sync 스크립트 | `~/.config/valueconnect-skills-sync/sync.sh` | master → 미러 cp (cmp 동일 시 skip) |
| LaunchAgent | `~/Library/LaunchAgents/com.valueconnect.skills-sync.plist` | macOS native — fswatch 불필요 |
| WatchPaths | `~/.claude/skills/jobkorea-talent-sourcing` + `saramin` + `talent-search` | 3개 디렉토리 변경 감지 → sync 즉시 실행 |
| 로그 | `~/.config/valueconnect-skills-sync/sync.log` | 변경 발생 시 timestamp + 어떤 SKILL sync 됐는지 |

**동작 흐름**:
```
사장님이 ~/.claude/skills/jobkorea-talent-sourcing/SKILL.md 수정
   ↓
macOS launchd WatchPaths 이벤트 감지 (즉시)
   ↓
sync.sh 자동 실행 (RunAtLoad + 변경 이벤트)
   ↓
cmp -s 비교 → 다르면 cp → 같으면 noop
   ↓
~/Desktop/Valueconnect-Ops/skills/jobkorea-talent-sourcing/SKILL.md 자동 갱신
   ↓
sync.log 에 timestamp 기록
```

**검증 명령**:
```bash
launchctl list | grep skills-sync          # 등록 확인
diff -q ~/.claude/skills/jobkorea-talent-sourcing/SKILL.md \
        ~/Desktop/Valueconnect-Ops/skills/jobkorea-talent-sourcing/SKILL.md
tail ~/.config/valueconnect-skills-sync/sync.log
```

**재등록 (필요 시)**:
```bash
launchctl unload ~/Library/LaunchAgents/com.valueconnect.skills-sync.plist
launchctl load ~/Library/LaunchAgents/com.valueconnect.skills-sync.plist
```

---

## R14: 등록 폼 자동화 — React widget hidden input 직접 set 패턴 (2026-05-23 사장님 명시)

잡코리아 등록 폼의 popup tree·dropdown은 React state 기반. JS `dispatchEvent('click')` + jQuery `.trigger('click')` 만으로는 hidden form state 미반영 → **QA-233**.

**해결 시퀀스**:
1. 카테고리 button → `data-part-ctgr-code` 추출 (아래 카테고리 코드 표 참조)
2. sub-category button → `data-part-code` (소분류 코드) + `data-kwrd-code` 추출
3. React native setter로 hidden input 강제 갱신:
```javascript
const setI = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
setI.call(document.querySelector('input[name="Part_Code2"]'), partCode);
setI.call(document.querySelector('input[name="Kwrd_Code2"]'), kwrdCode);
document.querySelector('input[name="Part_Code2"]').dispatchEvent(new Event('input', { bubbles: true }));
document.querySelector('input[name="Kwrd_Code2"]').dispatchEvent(new Event('input', { bubbles: true }));
```
4. visual 라벨 업데이트 위해 button click 도 함께 시도 (`$('button[data-part-ctgr-code="10031"]').trigger('click')`)
5. 잡코리아 내부 fn 직접 호출 시도 (예: `window.fnPartSel && window.fnPartSel(partCode)`)

### 잡코리아 직무 카테고리 코드 매핑

| 카테고리 | data-part-ctgr-code |
|----------|---------------------|
| 기획·전략 | 10026 |
| 법무·사무·총무 | 10027 |
| 인사·HR | 10028 |
| 회계·세무 | 10029 |
| 마케팅·광고·MD | 10030 |
| AI·개발·데이터 | 10031 |
| 디자인 | 10032 |
| 물류·무역 | 10033 |
| 운전·운송·배송 | 10034 |
| 영업 | 10035 |
| 고객상담·TM | 10036 |
| 금융·보험 | 10037 |
| 식·음료 | 10038 |
| 고객서비스·리테일 | 10039 |
| 엔지니어링·설계 | 10040 |
| 제조·생산 | 10041 |
| 교육 | 10042 |
| 건축·시설 | 10043 |
| 의료·바이오 | 10044 |
| 미디어·문화·스포츠 | 10045 |
| 공공·복지 | 10046 |

---

## R15: 등록 payload 회사 소개 필수 (2026-05-23 사장님 명시 — QA-235)

모든 payload JSON 작성 시 `~/.cache/saramin-company-research/<slug>.json` 의 `about_textarea_draft` 600~900자 본문을 `jd_about` 또는 `company_full_about` 필드에 그대로 포함. 잡코리아 등록 [상세 요강] 영역에 paste. **단순 한 줄 `position_summary` 만 넣는 것 금지.**

---

## R16: HTML 검수 페이지 블릿 prefix 제거 (2026-05-23 사장님 명시 — QA-234)

payload JSON list 항목 (responsibilities, requirements, preferred) 이 "- " 또는 "• " prefix 가진 경우 `<li>` 변환 전 `^[-·•▪︎\s]+` 정규식으로 strip 필수. 미처리 시 "- •" 이중 bullet 렌더링 → 사장님 "블릿 두개 뜬다" 지적.

---

## R17: chrome MCP `read_page` 금지 — lone surrogate JSON 오류 세션 마비

- **금지**: `read_page` 또는 `javascript_tool`로 잡코리아 모달 HTML 대량(1MB+) 수신 → UTF-16 lone surrogate가 JSON에 깨진 채 전달 → Anthropic API 400(`no low surrogate in string`) → conversation history 전체 오염 → 이후 모든 요청 실패.
- **대안**: `find` (selector 기반, 결과 소량) + `javascript_tool`(짧은 응답 `{ok:true}` 수준만). 화면 분석은 screenshot(binary라 안전).
- **복구**: 터지면 `/clear` 또는 신규 세션.
- **관련**: QA-243, saramin-talent-sourcing 동일 규칙.

---

## R18: 자동화 한 사이클 = screenshot → 좌표 측정 → click → screenshot 검증

- 좌표를 절대 guess하지 말 것. 매 액션 전 screenshot으로 현재 좌표 측정 → 그 좌표로 click → 즉시 screenshot으로 결과 검증.
- 모달 위치는 viewport 크기(1256×952 / 1302×944 / 1288×934)에 따라 달라짐 — 매번 screenshot에서 측정.
- 진짜 등록 모달 진입 흐름: 인재검색 → 후보자 click → 이력서 view → 우상단 [포지션 제안] → 모달 내 [+ 채용포지션 등록] → **등록 모달**에서 모든 widget(고용형태 dropdown·직무선택 popup) 좌표 click 정상 작동.
- 관련: QA-242.

---

## R19: 사람 개입 신호 — 사장님 손수 작업 발견 시 chrome 액션 0

- **트리거**: "이거 입력하지마" / "내가 할게" / "내가 ~ 클릭해" / 모달에 사장님이 직접 입력한 값(주소 자동완성·연봉 등) 발견.
- **즉시 행동**: chrome MCP 액션 0. 사장님 화면 건드리지 않는 작업(file system, ClickUp MCP read, screenshot 모니터)으로 전환.
- 사장님 작업 완료 신호("이제 다음 해", "ㅇㅋ 진행해") 받기 전까지 대기.
- 관련: `feedback_human_intervention_pause` 메모리.

---

## R20: 41건 정규화 unified.jsonl 사용법

- **경로**: `~/.cache/jobkorea-positions/unified.jsonl` (41건, 각 line = JSON)
- **회사별 건수**: wrtn 10 / codeit 8 / spoon-labs 7 / yeogi 10 / yeokjeon-fnc 6 = 41건
- **필수 필드 0건 누락**: `position_name`, `duties`, `qualifications`, `work_location`, `employment_type` (정규직 default)
- **누락 23건**: `category_l1` → SKILL §13-D 카테고리 추론 로직 (회사 + position_name → 추론) 활용
- **다음 batch에서 raw `*.json` 직접 읽지 말고 unified.jsonl만 사용.**
- 관련: QA-241.

---

## R21: 첫 widget 검증 후 나머지 필드 입력은 batch 한 번에

- **사장님 명문**: "모달창 뜨고 정규직 클릭한 다음부터는 필드입력 더 빠릿하게 해 중간텀 두지마"
- 고용형태 dropdown 1개 click 검증(screenshot) 끝나면, 그 이후 모든 텍스트 필드 입력은 `browser_batch` 단일 호출에 묶어서 한 번에 실행. wait 0.
- screenshot 검증은 batch 마지막 step으로만 1회.
- **절대 금지**: wait 1 / wait 2 / screenshot → 분석 → click → screenshot 같은 step-by-step 1초 cycle. 1건 cycle을 10초 → 60초로 늘려 사장님 frustration 유발.

---

## R22: 탭 ID는 사장님에게 노출 금지

- **사장님 명문**: "내가 그탭을 어떻게 알아"
- chrome 탭 식별은 사장님 화면에 보이는 정보(탭 제목 + URL 마지막 path + 가장 최근 열린 탭)로만 안내.
- 632986843 같은 숫자 ID는 내부 로그·코드에만. 사용자 facing 메시지에서 절대 언급 금지.

---

## R23: 사장님이 보는 화면 식별 = 탭 title + URL + page heading

- 잘못된 안내: "탭 632986843에 떴어요" ❌
- 올바른 안내: "잡코리아 이력서 보기 탭 (rNo=29444797, JOO 후보자)" ✅ / "Chrome 창 '이력서 보기' 제목, JOBKOREA 로고 + JOO 후보자 페이지" ✅
- URL fragment·query·rNo는 사장님이 주소창에서 확인 가능하니 OK.

---

## R24: 사장님 "내가 열었던것은 닫고" → 깨끗 reset 후 시작

- **사장님 명문**: "내가 열었던것은 닫고 니가 등록해"
- 사장님이 손수 작업하던 모달·탭이 있으면, 사장님이 직접 닫을 시간 주고, **새 후보자·새 모달로 처음부터 시작**.
- 사장님이 절반 채워둔 form 위에 자동화 덧씌우면 충돌 + 데이터 오염. 절대 금지.

---

## R25: "Multi Agent로" 명령 → subagent 병렬 spawn 의무

- **사장님 명문**: "절대 멈추지마 Multi Agent로 사람인 잡코리아 모두 등록해 /goal"
- file 작업·QA 영구화·중복 체크·별도 사이트 등록은 background subagent 병렬 spawn (`run_in_background:true`).
- main agent는 chrome 자동화에 집중.
- **주의**: chrome MCP는 1개 conversation에 1개 instance만 안전 → subagent에 chrome 위임 금지.

---

## R26: "중복 확인" → ClickUp board read 후 cross-check

- **사장님 명문**: "클릭업 포지션 다해 중복 확인하고"
- 41건 batch 등록 전 ClickUp FY26ClientsPosition 보드 read → custom field "잡코리아 등록 완료" 마킹된 task_id list 확보 → unified.jsonl과 cross-check해서 중복 제외.
- 사람인도 동일: "사람인 등록 완료" 마킹 기준.

---

## R27: "/goal" 명령 → 끝까지 진행, wait/check-in 최소화

- **사장님 명문**: "/goal"
- AskUserQuestion 최소화. 의사결정이 명확하면 묻지 말고 진행.
- 사장님이 explicit하게 "물어봐" / "확인해" 하지 않으면 자동 진행.
- **예외**: 사람 개입 신호(R19) 발견 시 즉시 정지.

---

## R28: 사장님 hint → 즉시 trial 후 30초 안에 결과 보고

- **사장님 명문**: "고용형태 그냥 Tab 이동하고 스페이스 눌러도 일단 뜨긴 하잖아"
- 사장님이 단편적 hint를 주시면, 그 자리에서 1회 trial → 결과(성공/실패) screenshot 검증 → 30초 안에 보고.
- hint 무시하고 다른 길 가지 말 것.

---

## R29: "리뷰가 어디 떠있는데?" → 화면 위치를 사람이 알 수 있게 안내

- 잘못된 안내: "탭 632986829에 떴어요" ❌
- 올바른 안내: "Chrome 탭 줄에서 가장 최근 열린 탭, 제목 'review.html' 또는 '잡코리아 등록 검수'" ✅
- `file:///` URL chrome 변환 버그가 있으면 `osascript -e 'tell application "Google Chrome" to open location "file:///..."'`로 강제 정상화.

---

## R30: 잡코리아·사람인 동일 데이터로 동시 batch

- **사장님 명문**: "사람인 잡코리아 모두 등록해"
- `~/.cache/jobkorea-positions/unified.jsonl`과 `~/.cache/saramin-positions/unified.jsonl`을 동일 source(ClickUp FY26 task)에서 정규화.
- 한 site 등록 후 다른 site는 카테고리 매핑만 변환해서 batch.
- lock 충돌 없으면 main agent 순차 처리. 충돌 시 subagent 분리.

---

## R31: "지금 과정도 QA 이슈로" → 발견된 root cause는 QA-XXX 등록

- **사장님 명문**: "지금 과정도QA이슈로 삼아서 해결하고 skill 업데이트해"
- 자동화 도중 발견된 모든 root cause(lone surrogate, schema 다름, 잘못된 form 진입 등)는 `docs/engineering/qa/issue-log.md`에 QA-XXX로 즉시 영구 등록.
- fix 코드와 함께 prevent recurrence 명시.
- 참조: R32(메타 규칙).

---

## R32: "내가 중간중간 코칭한거 다 skill에 반영" → 사장님 코칭 즉시 R-번호 영구화

- **사장님 명문**: "내가 중간중간 코칭한거 다 skill에 반영해"
- 사장님이 자동화 도중 주신 모든 hint·correction·preference는 그 자리에서 SKILL R-번호 부여하고 영구화.
- 다음 세션에서 같은 실수 반복 금지.
- **메타 규칙**: 이 R32 자체가 메타 규칙. 사장님이 코칭하면 즉시 추가 R 만들고 SKILL 업데이트.
- 참조: R31(QA 영구 등록).

---

## 변경 이력

- **2026-05-23** — R21(batch 한 번에·빠릿하게) + R22(탭ID 노출 금지) + R23(화면 식별 안내) + R24(깨끗 reset) + R25(Multi Agent 병렬) + R26(중복 확인 ClickUp) + R27(/goal 끝까지) + R28(hint 즉시 trial) + R29(리뷰 위치 안내) + R30(양 사이트 동시 batch) + R31(QA 영구 등록) + R32(코칭 즉시 R화 메타 규칙) 추가. 사장님 이번 세션 코칭 전체 반영.
- **2026-05-23** — R17(chrome MCP read_page 금지·lone surrogate 세션 마비·QA-243) + R18(screenshot 우선 자동화 사이클·QA-242) + R19(사람 개입 즉시 chrome 정지) + R20(41건 unified.jsonl 사용법·QA-241) 추가.
- **2026-05-23** — R14(React widget hidden input set 패턴 + 카테고리 코드 21종) + R15(회사 소개 필수) + R16(블릿 prefix 제거) 추가. QA-233/234/235 연동.
- **2026-05-22** — 사장님 명시 20단계 + 85점 자동 발송 정책(좋은학교/이직안정성/직무직결성 3축) + 자격증명 `~/.secrets/jobkorea.env` 격리 + Career Path Supabase 저장 + 첫 실 타겟 = 뤼튼테크놀로지스 Product Engineer.

---

## R39: 자동화 상황에서 "사장님 손수" 표현 절대 금지

- **사장님 명문**: "앞으로 사장님이 손수 라는 말은 최소한 사람인 잡코리아나 자동화를 꾀하는 상황에서는 하지마"
- 적용: chrome MCP / Playwright / 자동화 worker 컨텍스트에서 사용자에게 "사장님이 직접/손수 해주세요" 표현 절대 사용 금지.
- 자동화로 해결할 길 모두 시도 후, 정말 불가능하면 "사용자 화면에서 1회 click 부탁"으로 우회 표현.

---

## R40: 잡코리아 [포지션 등록] 성공 시 native `window.alert` dialog 뜸 → 렌더러 freeze

- **재현**: [포지션 등록] click → "포지션 등록되었습니다." native alert 표시 → CDP `Runtime.evaluate` timeout 45000ms → renderer frozen으로 후속 자동화 불가.
- **root cause**: `window.alert` 는 main thread 차단. CDP/automation tool 모두 block됨.
- **사장님 명문**: "지금 해봐 자바 스크립트건 뭐건 이 팝업을 클릭해서 다시 등록하는 상태로 가도록 해줘"
- **해법 우선순위**:
  1. **모달 진입 즉시 `window.alert = () => true; window.confirm = () => true;` override** (모달 열린 후 첫 액션으로 실행) — 가장 안전
  2. 키보드 Enter 단독으로는 dismiss 안 됨 (사장님 chrome focus 확인 필요)
  3. 마지막 fallback: 사용자 chrome 화면 [확인] 1회 click
- **R40-PRE**: 매 모달 진입 직후 첫 batch에 `javascript_tool`로 alert override 강제.

---

## R41: 직무·전문분야 search input은 자동완성 dropdown 없음 (free text type만)

- **검증 결과**: 좌측 column "AI·개발·데이터" → 우측 sub-list checkbox click 패턴만 작동.
- 사장님 hint "직무 입력하세요 자유롭게 입력하면 직무에 맞게 넣으면 상관 없음"은 잘못된 해석 — search는 filter 기능. 카테고리 + sub-list 명시 선택 필요.

---

## R42: AI Engineer / AI 직군 = "데이터사이언티스트" sub-category로 매핑

- 잡코리아 AI·개발·데이터 column → 데이터사이언티스트 (서버 검증 OK)
- AI 머신러닝개발자 등 표시 없을 수 있음. 데이터사이언티스트가 가장 가까운 매핑.

---

## R43: [포지션 등록] click 후 navigation 대기 = page still loading 45초 (정상)

- chrome MCP screenshot이 "Page still loading" 오류로 즉시 fail해도 frustration 금지. 등록 진행 중. dialog 처리 후 정상화.
- 다음 액션: lighter `tabs_context_mcp` 또는 alert override.

---

## R44: 모달 reset 위험 — popup 닫힌 후 입력값 다 날아가는 경우

- **재현**: 1번째 등록 성공 → 2번째 [+ 채용포지션 등록] → 모달 → 직무선택 popup → 우측 sub-category checkbox click → 확인 → **모달 다른 모든 필드 빈 상태로 reset됨**
- root cause: 일부 popup click 시퀀스가 modal state reset 유발 (popup 외부 click으로 잘못 감지).
- **재발 방지**: 직무선택은 **다른 필드 입력 전에 가장 먼저** 진행. 그 후 채용포지션·고용형태·입사후업무·우대사항·[포지션 등록] 한 번에 batch.

---

## R45: 41건 등록 휴지기는 다 끝나고 한 번에

- **사장님 명문**: "필드 입력을 더 빠르게 해. 휴지기를 갖으려면 다 등록하고 휴지기를 갖어"
- 적용: 1건 cycle 안에서 wait·screenshot 검증 최소화 (browser_batch 한 번에 최대한 묶음). 41건 다 끝난 후 종합 검증 + 휴지.

---

## R46: 직무선택 popup 우측 sub-list checkbox는 X=646 (QA-247)

- **재현**: 우측 sub-list row 텍스트 라벨 (X≈685, 예: "백엔드개발자" 텍스트) 클릭 → 시각적 hover 효과만 발생, checkbox state 미변경. [확인] 누르면 "직무를 선택해 주세요" 빨간 에러.
- **root cause**: 잡코리아 직무선택 popup은 row 전체가 clickable이 아니라 checkbox(X=646 부근)만 활성. 라벨 텍스트 영역은 label `for` 연결 없는 plain span.
- **재발 방지**: 우측 sub-list 클릭은 **항상 X=646 좌표 사용**. 시각적 라벨 위치(X=685)는 절대 사용 금지.
- **검증된 Y 좌표 (1288x934 viewport, popup 위치)**:
  - row 1: Y=346 / row 2: Y=369 / row 3: Y=392 / row 4: Y=416 / row 5: Y=440
  - row 6: Y=463 / row 7: Y=487 / row 8: Y=510 / row 9: Y=534 / row 10: Y=556

---

## R47: 좌측 카테고리 클릭 후 우측 sub-list 렌더링 wait 필요 (QA-248)

- **재현**: 좌측 카테고리 (예: 기획·전략 X=320,Y=346) 클릭 직후 같은 batch에서 우측 (X=646,Y=346) 클릭 → 우측 sub-list가 아직 DOM에 mount 안 됐을 수 있음. 결과: checkbox 미변경, "직무를 선택해 주세요" 에러.
- **root cause**: jobkorea sub-list rendering이 비동기. browser_batch 동일 트랜잭션 안에 좌측+우측 click 묶으면 race condition.
- **재발 방지**: 좌측 카테고리 click → screenshot 한 번 (sub-list 렌더링 강제 sync) → 우측 click. 또는 batch 내 좌측 click 후 무의미한 다른 click(예: 우측 빈 영역) 1개 삽입.
- **detection**: 등록 후 "직무를 선택해 주세요" 빨간 메시지 발견되면 즉시 직무선택 popup 재오픈하여 재시도 (R47 적용).

---

## 📖 Lessons Learned — 41건 batch 자동화 (2026-05-23, 핵심만)

41건 등록 완료까지의 시도→실패→재시도 흐름. **다음 batch는 이 표만 보고 함정 회피 가능**.

| # | 시도 | 실패 사유 | 재시도 / 해결 | R-rule |
|---|------|---------|------------|--------|
| 1 | `read_page`로 잡코리아 모달 HTML 읽기 | 응답 1MB+, UTF-16 lone surrogate → Anthropic API 400 reject → 세션 전체 마비 | `find`(selector 소량) + `javascript_tool`(짧은 응답) + `screenshot`(binary 안전)만 사용 | R17 / QA-236 |
| 2 | 포지션 제안 모달 안의 inline form에 입력 (1시간 헛돌이) | 그 모달은 "기존 등록 포지션 발송용" — 새 포지션 등록 폼 아님 | 포지션 제안 모달 → 우상단 **[+ 채용포지션 등록]** → 별도 등록 모달 진입 | R18 / QA-242 |
| 3 | 첫 회사 데이터 schema 그대로 다른 회사 적용 | wrtn/codeit=flat, spoon/yeogi/yeokjeon=nested → 4개 폴더 모두 None | `gget()` 다중 키 경로 resolver + `unified.jsonl` 41건 단일 schema 사전 생성 | — / QA-241 |
| 4 | popup 차단 native alert 떴는데 CDP 그냥 진행 | renderer freeze 45초+ | `window.alert=()=>true;window.confirm=()=>true` JS override **사전** 주입 | R40 / QA-246 |
| 5 | 직무선택 popup 검색 input에 자유 텍스트 입력 | placeholder는 "직무·전문분야 입력하세요"지만 사실은 자유 텍스트 검색 안 됨 — 좌측 카테고리 + 우측 sub-list 필수 | 카테고리 click 기반 자동화로 전환 | R41 |
| 6 | 우측 sub-list row label(X≈685) 클릭 | label `for` 없는 plain span — hover 효과만, checkbox state 미변경 → [확인] 후 "직무를 선택해 주세요" | **항상 X=646** (checkbox 본체) 클릭. label 좌표 절대 사용 금지 | **R46 / QA-247** |
| 7 | 좌측 카테고리 click과 우측 sub-list click을 같은 `browser_batch`에 묶음 | sub-list DOM mount 비동기 → 우측 click이 빈 영역에 떨어짐 → 동일 에러 | 좌측 click → **screenshot 1회**(렌더링 sync 강제) → 우측 click | **R47 / QA-248** |
| 8 | 직무선택 뒤에 다른 필드(채용포지션·고용형태…) 입력 후 다시 직무 popup 재오픈 | popup 외부 click으로 잘못 감지 → 모달 다른 필드 전부 reset | **직무선택을 가장 먼저** 마치고 나머지 필드 한 번에 batch | R44 |
| 9 | cmd+a + Delete 후 새 텍스트 type | 잔류 텍스트 남음 | Delete 대신 **Backspace** 사용 | R-rule / QA-240 |
| 10 | screenshot 좌표 한 번 측정해서 batch 재사용 | viewport 변동(1302x944 → 1288x934)으로 칸 어긋남 | 사이클마다 직전 screenshot 측정 + 카테고리별 좌표 표 유지 | — / QA-244 |
| 11 | navigate 후 chrome extension 권한 자동 유지 가정 | 새 URL 진입 시 권한 reset → 후속 click 실패 | navigate 직후 권한 refresh 한 번 | — / QA-245 |
| 12 | 입사후업무에 주요 업무 bullet만 입력 | 사장님 즉시 지적: "회사 소개부터 시작해야지" | 첫 줄 `[회사명]` + 회사 소개 1~2줄 + `[주요 업무]` bullet list **강제** | R36 |
| 13 | 사이클마다 검증 휴지기 갖기 | 사장님 지적: "휴지기 갖으려면 다 끝나고" | 1건 안에서 wait·screenshot 최소화(browser_batch 묶음). 41건 끝난 후 종합 검증 | R45 |
| 14 | 자동화 컨텍스트에서 "사장님 손수" 표현 사용 | 사장님 명시 금지 | 자동화 진행 시 "손수" 단어 출력 금지 | R39 |
| 15 | 카테고리 매핑에서 SRE / AI Engineer / 클라우드 보안 직접 분류 | 잡코리아는 직무 트리가 더 좁음 | SRE → 시스템엔지니어 / AI Engineer → 데이터사이언티스트 / 클라우드 보안 → 보안엔지니어 | R42 / R-매핑표 |

**좌표 표 (1288x934 viewport, 검증된 값):**
- 좌측 카테고리: 기획·전략(320,346) / 인사·HR(320,369) / 마케팅·광고·MD(320,391) / 디자인(320,414) / 회계·세무(495,369) / AI·개발·데이터(495,391) / 영업(495,436)
- 우측 sub-list (X=646 절대): row Y=346/369/392/416/440/463/487/510/534/556

**사이클 액션 시퀀스 (검증된 16-step batch):**
1. [+ 채용포지션 등록] (850,263)
2. JS alert override
3. 직무선택 (870,306)
4. 좌측 카테고리
5. screenshot (R47 sub-list sync)
6. 우측 sub-list X=646 (R46)
7. 확인 (697,652)
8. 채용포지션 input (615,272) → type
9. 고용형태 (855,272)
10. 정규직 (847,337)
11. 입사후업무 (685,475) → R36 회사소개+주요업무
12. 우대사항 (685,583) → bullet list
13. [포지션 등록] (651,682)
14. screenshot 검증
15. 모달 닫힘 + 잔여 라이선스 동일(=발송 0) 확인
16. 다음 사이클

---

## 변경 이력

- **2026-05-23** — R39(자동화 상황 "손수" 금지) + R40(native alert freeze 해법) + R41(직무 search free text 아님) + R42(AI→데이터사이언티스트 매핑) + R43(page still loading 정상) + R44(모달 reset 위험) + R45(41건 배치 휴지) 추가. 2026-05-23 batch 자동화 새로운 lessons 영구화.
- **2026-05-23 (후속)** — R46(우측 sub-list X=646 checkbox 절대) + R47(좌측 카테고리 클릭 후 sub-list 렌더링 wait) 추가. 41/41 batch 완료(잡코리아 잔여 라이선스 253/300, 발송 0, 등록만). QA-247/248 lessons 영구화.
- **2026-05-23 (Lessons 총정리)** — 41건 batch 시도→실패→재시도 흐름 15개 항목을 한 표로 정리. 좌표 표 + 16-step 검증된 사이클 시퀀스 명문화. 다음 batch는 표만 보고 함정 회피 가능.
- **2026-06-18** — §S (다중 키워드 검색 시나리오 플래닝 엔진) 신설. 사장님 명시: "소수정예 정밀 키워드, 결과 적으면 즉시 다음 시도, 지체 없이 빠르게." SQL·Query·RDB·dbt·Airflow·FinOps·IR 키워드 매트릭스 포함.

---

## §S. 다중 키워드 검색 시나리오 플래닝 엔진 (2026-06-18 사장님 명시)

> "여러 차례 검색 시도를 하기 위해서 다채로운 검색 시나리오가 필요하다. 결과 리스트에 몇 명 없으면 빠르게 다른 시도를 하도록 하고 이 과정은 지체 없이 빠르게 이뤄져야 한다."

### §S-0. 이 채널(잡코리아)의 적용 컨텍스트

- 잡코리아 인재검색 화면(`people/find`)에서 매 시나리오를 순서대로 실행한다.
- 결과 판단은 `총 {N}명` 텍스트 또는 리스트 카드 수로 즉시 읽는다.
- 딜레이: 시나리오 간 4~15초 랜덤 (human-pacing, SOT S0.5).
- 잡코리아 특유의 한글 입력 방식: `clipboard.writeText` + `Ctrl+A` + `Ctrl+V` + `Enter` (R10 준수).
- R9(장애물 즉시 재시도) / R10(JS execCommand insertText 금지 — clipboard paste) 유지.

### §S-1. 핵심 설계 원칙

1. **JD → 시나리오 자동 생성**: JD를 직무·스킬·도구·도메인·우대사항 5축으로 분해 → 10~15개 키워드 시나리오
2. **Priority 1 정밀 검색 먼저**: 소수(5~30명)가 나오는 정밀 키워드 우선 — 이 소수가 잘 맞을 확률 최고
3. **결과 수 즉시 판단 — 지체 없이**:
   - **0~4명**: 즉시 포기, 다음 시나리오 (스크롤·대기 없이)
   - **5~80명**: GOLD — 전수 처리 (모두 저장·평가)
   - **81~300명**: 상위 2페이지(40명)만 처리 후 다음 시나리오
   - **300명+**: AND 키워드 1개 추가 후 즉시 재시도
4. **소수정예 우선**: 검색 횟수 > 1회 대량 수집. 5명의 정밀 타겟 > 200명 광범위 수집
5. **전체 수집 후 중복 제거**: profile_url 기준 dedup, 동일인 중복 평가 금지
6. **제외 조건 고정**: 이직잦음·프리랜서·신입·인턴 — 매 시나리오마다 NOT 필터 또는 수집 후 제외

### §S-2. 결과 수 즉시 판단 의사결정 트리

```
키워드 입력 → "총 N명" 즉시 읽기
      │
      ├─ 0~4명  → [즉시 포기] 다음 시나리오 (대기 0초)
      │
      ├─ 5~80명 → [GOLD] 전수 처리
      │             ① 프로필 저장 (R6 준수)
      │             ② 이직잦음·프리랜서 제외
      │             ③ dedup 후 통합 pool에 추가
      │
      ├─ 81~300명 → [부분 처리] 상위 40명 (추천순 2페이지)만
      │              → 처리 완료 후 다음 시나리오
      │
      └─ 300명+  → [AND 재시도] AND 키워드 1개 추가
                    재검색 후 다시 판단 트리 진입
                    AND 추가 후에도 300+ → 즉시 포기
```

### §S-3. Finance/Data 포지션 키워드 매트릭스 (기준 예시)

| 시나리오 | 우선순위 | OR 키워드 | AND 키워드 | 예상 결과 수 | 소수정예 |
|---------|---------|----------|-----------|------------|---------|
| S1 | **P1** | `FP&A` | - | 10~50명 | ⭐ |
| S2 | **P1** | `Finance Data Analyst` | - | 5~30명 | ⭐⭐ |
| S3 | **P1** | `SQL` | `Finance` | 10~40명 | ⭐ |
| S4 | **P1** | `Query` | `재무분석` | 5~20명 | ⭐⭐ |
| S5 | **P1** | `dbt` | - | 3~15명 | ⭐⭐ (3 미만 즉시 포기) |
| S6 | **P1** | `Airflow` | `Finance` | 5~20명 | ⭐⭐ |
| S7 | **P1** | `FinOps` | - | 3~15명 | ⭐⭐ |
| S8 | **P1** | `IR` | `데이터` | 10~40명 | ⭐ |
| S9 | **P2** | `데이터 파이프라인` | `재무` | 5~25명 | ⭐ |
| S10 | **P2** | `RDB` | `Finance` | 5~20명 | ⭐⭐ |
| S11 | **P2** | `BI` | `FP&A` | 10~50명 | ⭐ |
| S12 | **P2** | `IR Factbook` | - | 3~20명 | ⭐⭐ |
| S13 | **P2** | `데이터 웨어하우스` | `재무` | 5~30명 | ⭐ |
| S14 | **P3** | `KPI 지표` | `재무` | 20~100명 | 부분 처리 |
| S15 | **P3** | `재무분석` | `데이터분석` | 30~200명 | 부분 처리 |

> **S3~S10 핵심**: SQL·Query·RDB·dbt·Airflow·FinOps·IR이 재무 도메인과 결합하면 전국에서도 소수만 해당. 5~30명이면 전원 최우선 타겟.

### §S-4. 이직잦음·프리랜서 제외 판단 기준

**이직잦음 판단**: 최근 5년 내 1년 미만 재직 2회 이상 → 제외 (저장 금지)

**프리랜서 판단**: 프로필에 "프리랜서", "freelance", "개인사업자", "독립계약자" 명시 → 제외

**두 조건 모두 해당 시 → 저장하지 않고 건너뛴다.**

```javascript
// §S-5 루프에서 호출하는 함수 — 잡코리아 전용 (사람인 §S-4와 동일 로직)
function hasFrequentJobChange(careerPath) {
  if (!careerPath || careerPath.length === 0) return false;
  const recentShortStints = careerPath.filter(job => {
    const months = parseMonths(job.period);     // "1년 3개월" → 15
    const isRecent = isWithin5Years(job.endDate); // 최근 5년 이내 종료
    return months < 12 && isRecent;
  });
  return recentShortStints.length >= 2; // 2회 이상 = 이직잦음
}

function isFreelancer(candidate) {
  const markers = ['프리랜서', 'freelance', 'freelancer', '개인사업자', '독립계약자'];
  const text = (candidate.currentTitle + ' ' + candidate.companyName + ' ' + (candidate.summary || '')).toLowerCase();
  return markers.some(m => text.includes(m.toLowerCase()));
}
```

### §S-5. 시나리오 실행 루프 (잡코리아 Playwright 패턴)

```javascript
async function runJobkoreaScenarioEngine(jd, page) {
  const scenarios = buildScenarios(jd);
  const pool = new Map(); // profile_url → candidate (dedup)
  const log = [];

  for (const s of scenarios) {
    // 1. 검색어 초기화 후 키워드 입력 (R10: clipboard paste)
    await clearJobkoreaSearch(page);
    const keyword = s.andKeyword
      ? `${s.orKeywords.join(' ')} ${s.andKeyword}`
      : s.orKeywords.join(' ');
    await page.evaluate(async (kw) => {
      await navigator.clipboard.writeText(kw);
    }, keyword);
    await page.keyboard.press('Control+a');
    await page.keyboard.press('Control+v');
    await page.keyboard.press('Enter');

    // 2. 결과 수 즉시 확인 (R9: 장애 시 재시도)
    const count = await getJobkoreaResultCount(page);
    log.push({ id: s.id, keyword, count });

    // 3. 즉시 판단
    if (count < 5) {
      console.log(`[S${s.id}] "${keyword}" → ${count}명 — 즉시 포기`);
      await randomDelay(2, 5);
      continue;
    }

    if (count > 300) {
      const fallback = s.narrowFallback || '재무';
      const narrowKeyword = `${keyword} ${fallback}`;
      await inputJobkoreaKeyword(page, narrowKeyword);
      const newCount = await getJobkoreaResultCount(page);
      if (newCount < 5 || newCount > 300) continue;
    }

    // 4. GOLD 처리
    const limit = count <= 80 ? count : 40;
    console.log(`[S${s.id}] "${keyword}" → ${count}명 — GOLD 처리 (${limit}명)`);
    const candidates = await collectJobkoreaCandidates(page, limit);

    for (const c of candidates) {
      if (pool.has(c.profile_url)) continue;
      if (hasFrequentJobChange(c.careerPath) || c.isFreelancer) continue;
      pool.set(c.profile_url, { ...c, scenario: s.id });
    }

    // 5. human-pacing (4~15초)
    await randomDelay(4, 15);
  }

  return { candidates: Array.from(pool.values()), log };
}
```

### §S-6. 일반 포지션 시나리오 생성 규칙

Finance/Data 외 다른 포지션에서도 동일 패턴 적용:

1. **P1 정밀**: 직무명 그대로 → 영문 직무명 → 핵심 도구/자격증
2. **P1 정밀**: JD 내 "필수 조건" 기술 키워드 하나씩
3. **P2 중간**: 우대사항 키워드 하나씩 + 직무 도메인 AND
4. **P3 광범위**: 직무 상위 카테고리 (예: "재무분석", "경영관리")

**규칙**: 절대로 키워드를 하나만 쓰지 않는다. 10개 미만의 시나리오라면 JD를 더 꼼꼼히 분해한다.

### §S-7. 완료 보고 형식

```
🟢 잡코리아 시나리오 플래닝 완료 — {포지션명}

총 시나리오: {N}개
  GOLD 수집: {M}개 시나리오
  즉시 포기(결과 0~4명): {K}개
  AND 재시도: {P}개

수집 결과:
  원시 후보: {X}명
  dedup 후: {Y}명
  이직잦음/프리랜서 제외: {Z}명
  최종 후보: {W}명

시나리오 상세:
  S1 FP&A: 38명 → GOLD 전수
  S4 Query+재무분석: 6명 → GOLD 전수 ⭐
  S5 dbt: 3명 → 즉시 포기
  S7 FinOps: 8명 → GOLD 전수 ⭐
  ...
```
