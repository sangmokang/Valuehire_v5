---
name: saramin-talent-sourcing
description: 사람인(saramin.co.kr) 기업회원 valueconnect 계정으로 인재풀 검색 → 프로필 무조건 저장(크롬 익스텐션 트리거) → 적합도 평가 → 이직 제안 발송까지 한 턴을 자동 수행. 사장님이 매번 8단계를 타이핑하지 않도록 명문화. 프로필은 발견 즉시 무조건 저장(상세 진입 = 차감 0, 제안 발송 = 차감 1). 85점 이상 적합도(좋은학교 + 이직안정성 + 직무직결성) 후보자만 자동 발송. 트리거 키워드 — "사람인 서치", "사람인 인재검색", "Saramin sourcing", "사람인 인재풀", "valueconnect 사람인", "사람인 이직 제안", "사람인 한 턴 돌려"
---

# 사람인 인재 서치 → 프로필 무조건 저장 → 적합도 평가 → 이직 제안 (한 턴 워크플로우)

> 2026-05-22 사장님 명시 — 사람인(saramin.co.kr) 인재풀에서 "제대로 된 후보자" 찾는 한 턴 SOP. talent-search 메타 가이드의 사람인 섹션을 이 스킬로 위임. 잡코리아 한 턴(`jobkorea-talent-sourcing`)과 1:1 대응되는 형태로 작성됨. 첫 실 타겟 = **뤼튼테크놀로지스 Product Engineer**.

---

## 0. 절대 규칙 (사장님 명시 — 절대 위반 금지)

| # | 규칙 | 근거 |
|---|------|------|
| R0 | **85점 이상만 자동 이직 제안 발송** | 1건 차감 + 실 메일 발송 = 되돌릴 수 없는 액션. 사장님 2026-05-22 명시 |
| R1 | **자격증명은 SKILL 평문 금지** | `~/.secrets/saramin.env` 격리(chmod 600). source 후 `$SARAMIN_ID`/`$SARAMIN_PW` 만 참조 |
| R2 | **사람 개입 시 자동화 즉시 정지** | 사장님이 chrome 만지거나 "내가 할께" 신호 → 모든 자동화 action 0. 메모리 [feedback_human_intervention_pause] |
| R3 | **봇 검출(캡차/차단 페이지) 즉시 STOP** | 재시도 금지 — 계정 잠금 위험. `OPS_INCIDENTS` 디스코드 알림 후 사장님 수동 풀이 |
| R4 | **이직 제안 발송 = 라이선스 차감** | 프로필 상세 진입 / 후보자 저장 = 차감 0, 이직 제안 발송 = 1건 차감. 발송 직전 미리보기 사장님께 보여드릴 것 |
| R5 | **'프리랜서' 단어 포함 후보는 절대 발송 X** (코드 레벨 강제) | 사장님 2026-05-22 명시 — **워커는 카드 텍스트 + 프로필 상세 본문 + 회사명 + 직책 + 자기소개 모두 검사해서 정규식 `/프리랜서|Freelancer|외주|Contract\s*Worker|프리\b/i` 매칭 시 즉시 패스. 점수 0, R6 저장 skip, 이직 제안 발송 절대 금지. 워커 출력 로그에 `[FREELANCER_FILTER] candidate_id=... matched="..." skipped`. 발송 직전 모달에서도 한 번 더 검사.** |
| **R6** | **🔥 후보자 프로필은 발견 즉시 무조건 저장** | **2026-05-22 사장님 명시 — "프로필앞으로 무조건 저장하도록해". 검토 가치가 있어 보이는 카드는 점수와 무관하게 (a) `후보자 저장` 버튼 click + (b) 크롬 익스텐션 프로필 아카이버 자동 트리거 + (c) Supabase `pipeline_candidates` upsert. 저장은 차감 0이므로 비용 0, 자산은 영구.** |
| R7 | **사람인 빠른 필터 chip "국내 유명 대학" + "인서울 대학" 기본 ON** | 사장님 워크플로우 step 3 명시. 좋은 학교 35점 가중치(A축)와 직결 |
| R8 | **학력 체크박스 — 대학(4년) + 석사 ON, 대학(2,3년)·박사·고등학교는 OFF (디폴트 유지)** | 사장님 워크플로우 step 4 + 캡처(image #7) 명시 |
| **R9** | **🔥 JS 코드 안의 한국어 unicode escape (`\uXXXX`) 절대 금지 — 직접 한국어 문자 사용 필수** | 2026-05-23 라이브 검증 — "뤼튼"→"뛤튼" 으로 깨짐 사고. 자동화 워커는 모든 한국어를 escape 없이 source code 에 그대로 작성 (예: `'뤼튼테크놀로지스'` ✅, `'뛤튼...'` ❌). 잘못된 회사명으로 등록 → 후보자에게 사고 |
| **R10** | **🔥 textarea 본문 채우기 = `document.execCommand('insertText', false, content)` 만 허용** | React Hook Form 환경. DOM-only `setValue` + dispatchEvent 패턴은 React state 와 sync 안 됨 → 미리보기/발송 silent fail. `el.focus() + el.select() + execCommand('delete') + execCommand('insertText', false, content)` 이 native input event 발생 → React state sync 보장 |
| **R11** | **🔥 [추가] click 이 모달 form 의 textarea reset 트리거** | 사람인 모달의 [+포지션 추가] sub-form 에서 [추가] click 시 `jobOffer.offerComment` / `jobOffer.chargeWork` textarea 가 비워짐. 그러므로 **본문 channel 채움은 반드시 [추가] click 후** 에 진행 |
| **R12** | **🔥 자동화는 [미리보기] click 전까지만 — 미리보기/발송은 사장님 수동 click** | JS `.click()` / 좌표 click 모두 [미리보기] popup window 안 뜸 (popup blocker 또는 native click only). [제안 발송] 도 R0/R4 사장님 직접만. 자동화는 모든 필드 채움 + 발송 버튼 활성 + 검증까지 |
| **R13** | **🔥 React useId 가 매 세션 다른 element id 생성 (`_r_38_`, `_r_3d_` 등) → id selector 절대 금지** | 매 세션마다 다른 random id. `[name="..."]` / `input[placeholder="..."]` / textContent 매칭만 사용. ID 사용 시 다음 자동화 깨짐 |
| **R14** | **🔥 listbox open 상태에서 textarea fill 차단됨** | 2026-05-23 라이브 검증 — listbox 가 floating 으로 textarea 위 overlay 시 focus 안 받음 → execCommand insertText 효과 없음 (`commentLen:0`). **textarea fill 전 listbox 닫기 필수** (`if(document.querySelector('[role="listbox"]')) combo.click()`) |
| **R15** | **🔥 listbox 옵션 click 시 "작성중인 내용 변경할까요?" confirm 모달** | textarea 채워진 상태에서 옵션 변경 시 사람인이 데이터 손실 방지 confirm 모달 띄움. **[변경] 버튼 click 자동 처리 필요**: `Array.from(buttons).find(b => b.textContent.trim()==='변경').click()`. 만약 비어있으면 confirm 모달 없이 즉시 변경 |
| **R16** | **🔥 본문 안 "• " 글머리표 → 사람인 list-style 과 겹쳐 두 개 표시** | 2026-05-23 사장님 명시 — "블릿포인트가 왜 두 개씩 떠". 본문에 "•" 사용 시 textarea 의 list-style auto-add 와 합쳐져 시각적으로 두 개. **글머리표 "•" 제거. "-" / "—" 또는 글머리표 없이 자연스러운 줄바꿈** 사용 |
| **R17** | **🔥 회사 소개 부족 = 후보자 무시 위험** | 2026-05-23 사장님 명시 — "회사에 대한 소개 부분이 상당히 약하네". 본문 ① 의 회사 부분 (▣ 회사 / ▣ 제품 / ▣ 최근 모멘텀) 은 §17.10 F2~F7 기준 모두 포함 필수: 누적 투자·매출 추이·MAU·임직원·미션 + 제품 라인업 + 글로벌 경쟁사 + 외신 인용 + 임원 quote. 6~10줄 빈약 본문 금지 |
| **R18** | **🔥 [제안 발송] 버튼 click 은 fullClick pattern 만 통과** | JS `.click()` / 좌표 `computer left_click` 둘 다 안 통함. **fullClick 패턴**: `btn.scrollIntoView({block:'center'}); btn.focus();` + 9개 mouse events sequence (`pointerover/enter/mouseover/enter/pointerdown/mousedown/pointerup/mouseup/click`, 모두 `bubbles:true,clientX:cx,clientY:cy`) + Enter key. **R12 폐기 — 자동 발송 가능**. 단 모든 검증 (commentLen>0 + chargeLen>0 + sendBtnDisabled=false) 통과 후 |
| R31 | **자동화 도중 발견한 root cause → QA-XXX 즉시 영구 등록** | 사장님 명문 "지금 과정도QA이슈로 삼아서 해결하고 skill 업데이트해". `docs/engineering/qa/issue-log.md` 에 prevent recurrence 명시. 상세 → 본 SKILL R31 |
| R32 | **사장님 코칭 즉시 R-번호 부여 → SKILL 영구화 (메타 규칙)** | 사장님 명문 "내가 중간중간 코칭한거 다 skill에 반영해". 다음 세션 동일 실수 반복 금지. 상세 → 본 SKILL R32 |
| **R33** | **🔥 실패 셀렉터·팝업 방해는 레저 파일에 즉시 기록 (Self-Correction Loop)** | 예상치 못한 셀렉터 에러·팝업 방해 발생 시 `URL / 실패한 셀렉터 / 화면 특이점(예: "로그인 팝업이 dialog 레이어를 먹어버림")`을 `docs/engineering/selectors-error-ledger.md`에 append. 다음 실행 시 이 파일을 **가장 먼저 읽고** 동일 주소·상황에서 같은 실수를 반복하지 않도록 코드를 방어적으로 작성한다. R31 강화판 (2026-06-22) |

---

## 1. 환경 준비

```bash
# (a) 자격증명 격리 위치 확인
ls -la ~/.secrets/saramin.env   # -rw------- 이어야 함

# 처음 한 번 (이미 있으면 skip)
cat > ~/.secrets/saramin.env <<'EOF'
export SARAMIN_ID="valueconnect"
export SARAMIN_PW="<실제 비밀번호를 여기에 직접 입력 — SKILL 문서에는 평문 금지(R1). 노출 시 즉시 rotate>"
export SARAMIN_ACCOUNT_TYPE="corp"   # 기업회원
EOF
chmod 600 ~/.secrets/saramin.env

# (b) 자격증명 로드 (서브셸 한정)
source ~/.secrets/saramin.env
echo "ID: $SARAMIN_ID  /  TYPE: $SARAMIN_ACCOUNT_TYPE"

# (c) Chrome 디버그 모드 (이미 떠 있으면 skip)
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug &

# (d) 프로필 아카이버 크롬 익스텐션 활성 확인
#     tools/profile-archiver/ — 사람인 프로필 페이지에서 자동 hook
```

**도구 선택:**
- 1순위: `mcp__claude-in-chrome__*` — 사장님 로그인 세션 그대로 활용
- 2순위: `playwright-core` + `connectOverCDP("http://localhost:9222")` — tools/saramin-sourcing 워커
- 프로필 저장: **크롬 익스텐션 `tools/profile-archiver/`** 가 사람인 프로필 페이지 진입 시 자동 hook (스샷 + 텍스트 hybrid 저장)

---

## 2. 로그인 (스킵 가능 — 이미 로그인되어 있으면)

URL: `https://www.saramin.co.kr/zf_user/auth?url=%2Fzf_user%2F`

1. **기업회원 탭 클릭** (개인회원이 디폴트 — 반드시 변경)
2. 아이디 입력: `$SARAMIN_ID` (= valueconnect)
3. 비밀번호 입력: `$SARAMIN_PW`
4. **아이디 저장 체크박스는 OFF 유지** (보안)
5. **로그인** 버튼 click

```javascript
// 자격증명을 hardcode 하지 말 것 — process.env 에서만 읽기
const id = process.env.SARAMIN_ID;
const pw = process.env.SARAMIN_PW;
if (!id || !pw) throw new Error("source ~/.secrets/saramin.env 먼저 실행");
```

**검증**: 로그인 성공 시 우상단에 "**Valueconnect / 강상모 ▾**" 노출. URL 이 `/zf_user/memcom/...` 로 이동.

---

## 3. 인재풀 진입

URL: `https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search`

⚠️ **이 URL 만 인재풀**. `search?searchword=...` 같은 일반 통합검색 URL은 채용공고 풀이라 0명 나옴 ([reference_talent_search_urls](../talent-search/SKILL.md) 절대 규칙 1번).

진입 시 상단에 **"원하는 직무에 딱 맞는 우수한 인재를 찾아보세요"** + 3분할 키워드 박스(OR / AND / NOT) 노출.

---

## 4. 빠른 필터 chip — '국내 유명 대학' + '인서울 대학' 클릭 (R7)

검색 박스 바로 아래 빠른 필터 chip 줄:

```
🎓 국내 유명 대학 3,300+    🎓 인서울 대학 1,900+    📊 평균 근속 3년 1,300+
🔥 적극 구직 중 1,000+      ⭐ 요즘 뜨는 인재 800+
IT개발·데이터 > 백엔드/서버개발 10,800+
IT개발·데이터 > 웹개발 8,400+
IT개발·데이터 > 프론트엔드 ...
```

**필수 click (사장님 워크플로우 step 3):**
- ✅ 🎓 **국내 유명 대학**
- ✅ 🎓 **인서울 대학**

(선택) 포지션 따라 추가:
- 평균 근속 3년 (이직 안정성 30점 자동 가산)
- 적극 구직 중 (응답률 ↑)
- 요즘 뜨는 인재
- IT개발·데이터 > 백엔드/서버개발 (Product Engineer 같은 풀스택 — 백·웹·프론트 3개 토글 OR)

---

## 5. 좌측 패널 — 연차 / 학력 / 추가 필터 (R8, 사장님 워크플로우 step 4)

좌측 사이드바 필터 패널:

### 5.1 경력 (필수)
```
경력 ▾
   [최소년차 ▾]  ~  [최대년차 ▾]
   근속연수    [선택 ▾]
   휴식기간    [선택 ▾]
```

**연차 매핑 규칙 (사장님 명시):**
- JD 의 "경력 N~N년" 표기에 **±1~2년 버퍼** 추가
- 예: JD "5~10년" → 패널 "4~12년" 또는 "3~11년"
- 예: JD "경력 무관" → 패널 "1~15년"
- 뤼튼 Product Engineer (1인 개발/AI 코딩 도구 활용 경험) → "**3~8년**" 권장

### 5.2 지역 (선택)
대부분 패스 — 원격/하이브리드 포지션 많아 지역 제한 X.
지역 필수인 포지션만 `서울` 선택.

### 5.3 직무 (선택)
빠른 필터 chip 에서 이미 IT개발·데이터 카테고리 잡았으면 skip.
세분화 필요 시 `직무 ▾` 에서 multi-select.

### 5.4 학력 체크박스 (필수, R8)
```
학력 ⓘ
  ☐ 고등학교
  ☐ 대학(2,3년)
  ☑ 대학(4년)     ← 필수 ON
  ☑ 석사           ← 필수 ON
  ☐ 박사

  ☐ 재학·휴학·수료·중퇴·자퇴 포함
  ☐ 해외 대학 제외
```

사장님 워크플로우 step 4 + 캡처(image #7) 명시: **대학(4년) + 석사 ON, 그 외 OFF**.

### 5.5 연봉 (선택)
```
연봉 ⓘ
  [최저연봉 ▾]  ~  [최고연봉 ▾]
```
대부분 패스 — 연봉 필터 걸면 풀이 너무 좁아짐. JD 의 연봉 상단이 명시된 경우에만 사용.

### 5.6 재직/구직 (선택)
빠른 필터 chip "적극 구직 중" 으로 대체 가능.

---

## 6. 키워드 입력 — OR / AND / NOT (한국어 입력 절차)

상단 키워드 박스 3분할:

| 박스 | 의미 | 사용 |
|------|------|------|
| **OR** (하나 이상 포함) | 직무 동의어 묶음 | "Product Engineer", "프로덕트 엔지니어", "Full Stack" |
| **AND** (모두 포함) | 산업/도메인 1개로 좁히기 | "AI" |
| **NOT** (제외) | 신입/인턴/프리랜서 | "신입", "인턴", "프리랜서" |

### 한국어 입력 패턴 (사람인 라이브 검증된 절차 — [talent-search](../talent-search/SKILL.md) §2)

```
[step 1] 키워드 박스 click → focus
[step 2] javascript_tool: navigator.clipboard.writeText("키워드")
[step 3] computer: key "cmd+v"        ← 한국어 자모 timing 우회
[step 4] computer: wait 2초
[step 5] computer: key "Return"       ← chip 등록 (필수)
[step 6] computer: key "Escape"       ← AI 추천 dropdown 닫기 (다음 박스 click 보호)
[step 7] 다음 키워드 → step 2~6 반복
```

### 🔥 DOM Selector 라이브 검증 (2026-05-22 V1 자동화 성공)

| 단계 | element | Selector | 비고 |
|------|---------|----------|------|
| OR 키워드 input | `<input type="text" class="search_input">` | `div.search_default input.search_input` | force click 필요 (AI 추천 dropdown overlay 회피) |
| AND 키워드 input | 동일 | `div.search_word_include input.search_input` | |
| NOT 키워드 input | 동일 | `div.search_word_except input.search_input` | |
| 빠른 필터 chip | `<button class="tag_item">` | `button.tag_item:has-text("국내 유명 대학")` | 텍스트 매칭 |
| 검색 버튼 | `<button class="search_submit">` | `button.search_submit` | |
| 결과 카운트 | `<span class="list_count">` | `span.list_count` | "총 N 명" |
| 결과 카드 | `<div class="talent_list_item">` | `div.talent_list_item` | 페이지당 20개 |
| 카드 내 후보자 ID | `<div class="check_area" residx="...">` | `div.check_area[residx]` | 사람인 내부 id |
| 카드 클릭 (상세) | `<a href="javascript:void(0)">` | `div.talent_list_item div.summary_info a` | 새 창 열림 |
| [후보자 저장] 버튼 | `<button>` | `button:has-text("후보자 저장")` (카드 내부) | R6 자동 click |
| [이직 제안] 버튼 | `<button>` | `button:has-text("이직 제안")` (카드 내부) | R0 발송 트리거 |

**라이브 검증 V1 실행 결과** (2026-05-22, OOC Global Brand Marketer (북미)):
- 검색: 660명 결과 / 카드 selector 매칭: 20개 / R5 프리랜서 자동 skip: 1명 ("외주" 매칭) / R6 자동 저장: 19명 / 에러: 0
- 참고 스크립트: `tools/_tmp/saramin-talent-pool-v1.mjs` (Playwright + connectOverCDP 9222)

**금지 패턴 (실패 확인됨):**
- ❌ `form_input value="한국어"` — 빈 값 들어감 (사람인은 keyboard event만 받음)
- ❌ `computer type "여러 한국어 단어"` — 자모/공백 소실, 모든 단어 한 chip 에 붙어 검색 0명
- ❌ Enter 안 누르고 검색 → chip 으로 안 등록됨

### JD → 키워드 매핑 (뤼튼 Product Engineer 예시)

| 박스 | 키워드 chip | 근거 |
|------|-----------|------|
| **OR** | `Product Engineer`, `프로덕트 엔지니어`, `Full Stack`, `풀스택` | 직무 동의어 |
| **AND** | `AI` | 산업/도메인 (1개만!) |
| **NOT** | `신입`, `인턴`, `프리랜서` | 제외 |

**AND 너무 specific 금지** — "AI" + "Claude Code" + "Cursor" 동시에 AND 박으면 결과 0명. AI 만 AND, 나머지는 OR.

### 결과 수 모니터링 (chip 수치)

검색 박스 채운 직후 자동 표시되는 빠른 필터 chip 수치(`국내 유명 대학 N+`, `인서울 대학 N+`) 로 즉시 판단:

| 수치 | 의미 | 다음 행동 |
|------|------|----------|
| 10,000+ | 너무 광범위 | AND 키워드 1개 추가 |
| 1,000~5,000 | 여전히 많음 | AND 추가 또는 빠른 필터 click |
| 100~500 | 적절 | **검색 버튼 click 가능** |
| 0~50 | 너무 좁음 | AND 1개 빼기 |
| 0 | AND 조건 모순 | AND 키워드 재검토 |

---

## 7. 검색 버튼 click + 정렬 — '추천순'

오른쪽 파란색 **검색** 버튼 click.

결과 화면 좌상단 정렬:
- ✅ **추천순** (디폴트 / 사장님 명시)
- ❌ 업데이트일순
- ❌ 경력순
- ❌ 학력순

총 N명 표시 — `총 1,126 명` 처럼 결과 카운트가 좌상단에 나옴.

상단 `Focus` 박스: "**적극적으로 제안을 기다리는 인재**" — 응답률 ↑ 카드 우선.

---

## 8. 후보자 카드 리스트 — 펼쳐서 경력 평가

각 카드 구성:
```
☐ [프로필 사진]   이OO · 남 33세 · 경력 10년 6개월        [후보자 저장]
                  지니언스 인프라개발팀 (2022-10-01 ~ 재직중, 직전연봉 7,100 만원)
                  사내 그룹웨어 및 B2B 파트너 시스템 운영 및 개발 ...    [이직 제안하기]
                  의식주컴퍼니 플랫폼테크그룹 (1년 9개월) · 한서기술 ... 외 3건
                  장안대학교 인터넷정보통신과 (졸업)
                  [백엔드/서버개발] [웹개발] [프론트엔드] [+6]
                  [Node.js] [Vue.js] [MyBatis] [+12]
                  📈 코스닥  ⏱️ 최장 근속 3년                      26-05-14 업데이트
```

### 8.1 자동 평가 — 100점 만점 (사장님 3축 명시, 잡코리아와 동일)

| 축 | 가중치 | 만점 기준 | 감점 기준 |
|----|-------|----------|----------|
| **A. 학교 (35점)** | 35 | 인서울 4년제 OR 지방 국공립대 졸업 | 그 외 -10~-20 |
| **B. 이직 안정성 (30점)** | 30 | 각 직장 평균 근속 2년+ | 개월 단위 연속 이직 -20 |
| **C. 직무 직결성 (35점)** | 35 | JD 핵심 직무·스킬 명시 회사·직책 매칭 | 도메인/스킬 mismatch -10~-25 |

**자동 발송 임계값: 85점 이상**

자세한 정의는 [`jobkorea-talent-sourcing`](../jobkorea-talent-sourcing/SKILL.md) §8 참조 — 동일 규칙.

### 8.2 프리랜서 패스 (R5)

회사명에 "프리랜서" / "비공개" + 직책에 "프리랜서/Freelancer/외주" 단어 → 즉시 패스, 평가 0점.

---

## 9. 🔥 R6 — 후보자 프로필 무조건 저장 (점수와 무관)

**사장님 명시 (2026-05-22): "프로필앞으로 무조건 저장하도록해"**

검토 가치가 있어 보이는 카드(프리랜서 아님 + JD 직무 카테고리 일치) 는 **점수 계산 전에 먼저 무조건 저장**. 저장은 비용 0, 자산은 영구.

### 9.1 저장 3단계 (병렬 OK)

```typescript
// (a) 사람인 [후보자 저장] 버튼 click
//     → 사람인 내부 "찜한 인재" 리스트에 INSERT (계정 단위)
await page.locator('button:has-text("후보자 저장")').nth(cardIdx).click();
await page.waitForSelector('.toast:has-text("저장")');   // 토스트 확인

// (b) 프로필 상세 새 탭 진입 (차감 0)
//     이름 click → 새 탭 https://www.saramin.co.kr/zf_user/.../resume/view?...
const newPage = await context.waitForEvent('page');
await newPage.waitForLoadState('domcontentloaded');

// (c) 크롬 익스텐션 프로필 아카이버 자동 hook
//     tools/profile-archiver/ 가 page URL 패턴(.../resume/view) 매칭 → 스샷+텍스트 hybrid 로컬 SQLite 저장
//     사용자 수동 클릭 불필요 (자동 트리거)
await newPage.waitForSelector('[data-archiver-status="saved"]', { timeout: 10000 });

// (d) Supabase pipeline_candidates upsert (전체 인재 자산)
await supabase.from('pipeline_candidates').upsert({
  source: 'ai_search:saramin:profile',
  source_id: `saramin:${rNo}`,
  name: `${maskedName}OO`,
  raw_text: resumeText,
  ai_assessment: { score, school_score, mobility_score, fit_score, career_path },
  match_score: score,
  metadata: {
    resume_url,
    snapshot_path,           // 익스텐션이 저장한 로컬 PNG 경로
    saved_via: ['saramin_native', 'profile_archiver_extension', 'supabase'],
    captured_at: new Date().toISOString(),
  },
});
```

### 9.2 Career Path 캡처 (3중 저장)

펼친 경력 영역 + 프로필 상세 본문 양쪽에서 추출:

```typescript
const careerPath = await newPage.evaluate(() => {
  const rows = Array.from(document.querySelectorAll('.career_list .career_item, .resume-career li'));
  return rows.map(r => ({
    company: r.querySelector('.company, .corp')?.textContent?.trim(),
    role:    r.querySelector('.role, .position, .duty')?.textContent?.trim(),
    period:  r.querySelector('.period, .term')?.textContent?.trim(),
  }));
});

// candidate_career_paths 테이블이 없으면 pipeline_candidates.ai_assessment.career_path 에 in-place 저장
await supabase.from('candidate_career_paths').insert({
  candidate_id,
  source: 'saramin',
  career_json: careerPath,
  snapshot_path: snapshotPath,
  captured_at: new Date().toISOString(),
}).onConflict('candidate_id,source').merge();
```

### 9.3 저장 후 평가 (점수 ≥ 85 만 §10 으로 진행)

저장은 끝났으므로:
- **점수 ≥ 85** → §10 이직 제안 모달 진행 (R0 자동 발송 조건 충족)
- **점수 < 85** → 칸반 "AI Search/검토 대기" 컬럼에 카드만 등록, 발송 보류, 사장님 컨펌 대기

---

## 10. 🔥 이직 제안 모달 — 라이브 자동화 검증 절차 V2 (2026-05-23)

> **사장님 명시 (2026-05-22): "이 과정은 매우 중요하기 때문에 정확하게 프로세스화 해서 나중에 실수가 없도록 해야함."**
>
> 첫 라이브 등록 (뤼튼테크놀로지스 / Global Brand Marketer (북미) / 후보자 37874592) 에서 발견한 5가지 함정 (T1~T5) 과 라이브 검증된 selector + 순서 명문화. 자동화 워커는 이 §10 만 따르면 됨 — V1 추정 절차 (즉석 포지션 등록 / LLM 매칭 / 자동 발송) 는 모두 V2 흐름에 통합됨.

### 10.0 라이브 검증된 5가지 함정 (절대 위반 금지 — R9~R13 참조)

| # | 함정 | 증상 | 해결 |
|---|------|------|------|
| **T1** | **JS 코드 안의 한국어 unicode escape (`\uXXXX`) 사용** | "뤼튼" → "뛤튼" 으로 깨짐. 잘못된 회사명으로 등록될 사고 위험 | **R9** — 직접 한국어 문자 사용 필수 (`'뤼튼테크놀로지스'` ✅), escape 금지 |
| **T2** | **[추가] click 이 모달 form 의 textarea reset 트리거** | 본문 channel `jobOffer.offerComment` / `chargeWork` 가 비워짐. 발송 시 빈 본문 사고 위험 | **R11** — 올바른 순서: (1) [+포지션 추가] → (2) 회사명/포지션명 → (3) [추가] click → (4) **그 다음** textarea 본문 |
| **T3** | **DOM-only `setValue` + dispatchEvent 가 React Hook Form 상태와 sync 안 됨** | DOM `value` 는 채워졌고 화면도 보이지만, 미리보기/발송 click 시 silent fail (form invalid) | **R10** — `document.execCommand('insertText', false, content)` 만 사용. native input event 발생 → React state sync |
| **T4** | **JS `.click()` / 좌표 click 으로 [미리보기] 버튼 안 떠짐** | popup window 안 뜸. dialogCount 변화 없음. 새 탭/창 생성 안 됨 | **R12** — 사장님 수동 click. 자동화는 입력 + 검증까지만 |
| **T5** | **React useId 가 매 세션 다른 element id 생성 (`_r_38_`, `_r_3d_`, `_r_4m_` 등)** | 다음 세션에서 selector 깨짐 → 자동화 실패 | **R13** — id 절대 사용 금지. `name="..."` / `placeholder="..."` / textContent 매칭만 |

### 10.1 라이브 검증된 안정 selector (V2)

| 필드 | 안정 selector | 비고 |
|------|---------------|------|
| 모달 [이직 제안] 트리거 (페이지 단) | `Array.from(document.querySelectorAll('button')).find(b => (b.textContent||'').trim() === '이직 제안')` | 후보자 상세 페이지 상단 |
| 모달 자체 | `document.querySelector('[role="dialog"]')` | 열림 확인 |
| 제안 포지션 드롭다운 trigger | `document.querySelector('[role="dialog"] [role="combobox"]')` (DOM 순서 첫 번째) | click → listbox 펼침 |
| 드롭다운 옵션 (기존 포지션) | `document.querySelectorAll('[role="option"]')` | 텍스트로 옵션 찾기 |
| **"+ 포지션 추가" 버튼** | `Array.from(document.querySelectorAll('button')).find(b => /^\+?\s*포지션 추가$/.test((b.textContent||'').trim()))` | click → sub-form 활성 |
| 회사명 input | `[name="offerCompanyNm"]` | 채용 회사 입력 |
| 포지션명 input (즉석 등록 sub-form) | `input[placeholder="포지션명 입력"]` | 신규 포지션 등록용 |
| 제안 제목 input | `[name="jobOffer.offerTitle"]` | listbox 표시 라벨 자동 사용 |
| 직무 카테고리 input | `input[placeholder*="직무 입력"]` | 필수 아님 (비워도 발송 가능) |
| **제안 내용 textarea** ① | `[name="jobOffer.offerComment"]` | 한도 2,000자 |
| **업무 내용 textarea** ② | `[name="jobOffer.chargeWork"]` | 한도 2,000자 |
| 제안 내용 저장 체크박스 | `[name="saveTemplate"]` | 다음 발송 재사용 |
| 발송 예약 토글 | `[name="reserve"]` | 즉시 발송이면 OFF 유지 |
| 답변 마감일 input | `input[placeholder="YYYY. MM. DD"]` | 디폴트 7일 후 자동 |
| [추가] 버튼 (sub-form) | `Array.from(document.querySelectorAll('button')).find(b => b.offsetWidth>0 && (b.textContent||'').trim()==='추가' && !b.disabled)` | sub-form 활성 후 자동 활성 |
| [미리보기] 버튼 | `Array.from(document.querySelectorAll('button')).find(b => (b.textContent||'').trim()==='미리보기' && !b.disabled)` | **T4 — 자동 click 불가, 사장님 수동** |
| [제안 발송] 버튼 | `Array.from(document.querySelectorAll('button')).find(b => (b.textContent||'').trim()==='제안 발송' && !b.disabled)` | 모든 필수 필드 채워야 활성. **R12 — 사장님 수동** |

### 10.2 라이브 검증된 9단계 절차 (Step by Step, 사장님 명시 순서 — 절대 위반 금지)

> 후보자 페이지 (`https://hiring.saramin.co.kr/applicant-view/position/resume/<rNo>`) 에서 시작.

```javascript
// 공용 헬퍼 — R10 execCommand insertText 패턴 (React Hook Form state sync 보장)
function fillByExec(selector, content) {
  const el = document.querySelector(selector);
  if (!el) throw new Error(`No element: ${selector}`);
  el.focus();
  el.select();
  document.execCommand('delete', false);
  document.execCommand('insertText', false, content);
  el.dispatchEvent(new Event('blur', {bubbles: true}));
  return el.value;
}

// === Step 1: 모달 열기 ===
//    페이지 상단 [이직 제안] 버튼 click — JS .click() 으로 OK (popup 없음)
//    또는 URL 에 ?modal=hiring-offer 쿼리 + [이직 제안] 페이지 버튼 한 번 click
const offerBtn = Array.from(document.querySelectorAll('button'))
  .find(b => (b.textContent||'').trim() === '이직 제안');
offerBtn?.click();
// wait 2초 — 모달 열림

// === Step 2: 제안 포지션 드롭다운 펼치기 ===
const positionCombo = document.querySelector('[role="dialog"] [role="combobox"]');
positionCombo.click();
// wait 0.5초 — listbox 펼침

// === Step 3: 기존 등록된 포지션 옵션이 있으면 그것 선택, 없으면 [+ 포지션 추가] click ===
//    기존 옵션 매칭 — 회사명+포지션명 textContent 매칭
const existingOption = Array.from(document.querySelectorAll('[role="option"]'))
  .find(o => o.textContent.includes('뤼튼테크놀로지스') && o.textContent.includes('Global Brand Marketer'));
if (existingOption) {
  existingOption.click();
  // Step 4, 5 skip — 바로 Step 6 (textarea) 으로
} else {
  // 신규 포지션 등록 흐름 → [+ 포지션 추가]
  const addPositionBtn = Array.from(document.querySelectorAll('button'))
    .find(b => /^\+?\s*포지션 추가$/.test((b.textContent||'').trim()));
  addPositionBtn?.click();
  // wait 0.5초 — sub-form 활성

  // === Step 4: 회사명 + 포지션명 입력 (sub-form) ===
  //    ⚠️ R9 — JS 코드 안의 한국어 unicode escape 절대 금지. 직접 문자 사용
  fillByExec('[name="offerCompanyNm"]', '뤼튼테크놀로지스');
  fillByExec('input[placeholder="포지션명 입력"]', 'Global Brand Marketer (북미)');

  // === Step 5: [추가] click → listbox 에 새 옵션 INSERT + 자동 선택 ===
  //    ⚠️ R11 — 이 [추가] click 이 textarea form 을 reset 시킴 (`offerComment`/`chargeWork` 비워짐)
  //    그러므로 Step 6 textarea 채움은 반드시 [추가] click 후
  const addBtn = Array.from(document.querySelectorAll('button'))
    .find(b => b.offsetWidth>0 && (b.textContent||'').trim()==='추가' && !b.disabled);
  addBtn?.click();
  // wait 1.5초 — listbox INSERT + auto-select
}

// === Step 6: 본문 textarea 채우기 (반드시 [추가] click 후 — R11) ===
//    ⚠️ R10 — DOM-only setValue 안 됨. execCommand('insertText') 만 React state sync.
//    본문 ①·② 는 §17.3 템플릿 + §17.10 F1~F13 기준 + §17.8 회사 캐시 + JD 매핑
fillByExec('[name="jobOffer.offerComment"]', OFFER_COMMENT_TEXT);   // 본문 ① (한도 2000자)
fillByExec('[name="jobOffer.chargeWork"]',   CHARGE_WORK_TEXT);     // 본문 ② (한도 2000자)

// === Step 7: 제안 내용 저장 체크박스 ON (다음 같은 포지션 발송 시 재사용) ===
const saveCb = document.querySelector('[name="saveTemplate"]');
if (saveCb && !saveCb.checked) saveCb.click();

// === Step 8: 자동화 결과 검증 (필수 — 발송 전 안전망) ===
const validation = {
  selectedPosition: document.querySelector('[role="dialog"] [role="combobox"]')?.textContent,
  offerCompanyNm:   document.querySelector('[name="offerCompanyNm"]')?.value,
  offerTitle:       document.querySelector('[name="jobOffer.offerTitle"]')?.value,
  commentLen:       (document.querySelector('[name="jobOffer.offerComment"]')?.value || '').length,
  chargeLen:        (document.querySelector('[name="jobOffer.chargeWork"]')?.value || '').length,
  saveTemplate:     document.querySelector('[name="saveTemplate"]')?.checked,
  sendBtnDisabled:  Array.from(document.querySelectorAll('button'))
                      .find(b => (b.textContent||'').trim()==='제안 발송')?.disabled,
  // 한국어 깨짐 검증 (R9)
  companyBroken: document.querySelector('[name="offerCompanyNm"]')?.value?.includes('뛤') || false,
};

console.assert(validation.offerCompanyNm === '뤼튼테크놀로지스', 'T1 회사명 깨짐!');
console.assert(validation.sendBtnDisabled === false, 'T3 React state sync 안 됨!');
console.assert(validation.commentLen > 0 && validation.chargeLen > 0, 'T2 textarea 비어있음!');

// === Step 8.5: listbox 닫기 (R14 — fill 전 필수) ===
//    R14 — listbox 가 열린 상태면 textarea fill 효과 없음. fill 전 listbox 닫음
if (document.querySelector('[role="listbox"]')) {
  document.querySelector('[role="dialog"] [role="combobox"]')?.click();
  // wait 0.5초
}

// === Step 9: 자동 [제안 발송] click — §10.3 fullClick 패턴 ===
// R12 폐기 — R18 fullClick 으로 자동 발송 가능
```

### 10.2.1 listbox 옵션 변경 시 confirm 모달 처리 (R15)

기존 등록된 옵션을 click 으로 변경 시 사람인이 "**작성중인 내용을 변경할까요?**" confirm 모달 띄움 (textarea 가 채워져 있을 때만):

```javascript
// 옵션 click 후 1초 wait → confirm 모달 떴는지 확인
const changeBtn = Array.from(document.querySelectorAll('button'))
  .find(b => b.offsetWidth>0 && (b.textContent||'').trim()==='변경');
if (changeBtn) {
  changeBtn.click();  // textarea reset OK — Step 6에서 다시 채울 거임
}
```

### 10.3 자동 발송 (R18 fullClick 패턴 — 2026-05-23 V2.1 라이브 검증)

> **R12 폐기.** 사장님 명시 (2026-05-23): "수동하지 말라고 했지, 니가 해. 왠만하면 나한테 작업 떠넘기다가 프로세스 다 망쳐." fullClick 패턴으로 [제안 발송] 자동 click. [미리보기]는 popup blocker로 자동 click 불가하므로 미리보기 skip + 발송 자동.

```javascript
// === Step 9: 자동 [제안 발송] click (R18 fullClick 패턴) ===
function fullClick(btn) {
  btn.scrollIntoView({block:'center'});
  btn.focus();
  const r = btn.getBoundingClientRect();
  const x = r.x + r.width/2, y = r.y + r.height/2;
  ['pointerover','pointerenter','mouseover','mouseenter','pointerdown','mousedown','pointerup','mouseup','click'].forEach(t => {
    btn.dispatchEvent(new MouseEvent(t, {bubbles:true,cancelable:true,view:window,button:0,clientX:x,clientY:y}));
  });
  btn.dispatchEvent(new KeyboardEvent('keydown', {bubbles:true,key:'Enter',keyCode:13,which:13}));
}

// 발송 전 최종 안전망 — 모든 검증 통과 후만 click
const sendBtn = Array.from(document.querySelectorAll('button'))
  .find(b => b.offsetWidth>0 && (b.textContent||'').trim()==='제안 발송' && !b.disabled);
if (!sendBtn) throw new Error('[제안 발송] button not found or disabled');

// 마지막 검증
const finalCheck = {
  selected: document.querySelector('[role="dialog"] [role="combobox"]')?.textContent,
  commentLen: document.querySelector('[name="jobOffer.offerComment"]')?.value?.length || 0,
  chargeLen: document.querySelector('[name="jobOffer.chargeWork"]')?.value?.length || 0,
  companyBroken: /[㄰-㆏ᄀ-ᇿ]/.test(document.querySelector('[name="offerCompanyNm"]')?.value || '') || (document.querySelector('[name="offerCompanyNm"]')?.value || '').includes('뛤'),
};
if (finalCheck.commentLen < 500) throw new Error('R17 위반 — 본문 ① 너무 짧음');
if (finalCheck.chargeLen < 300) throw new Error('R17 위반 — 본문 ② 너무 짧음');
if (finalCheck.companyBroken) throw new Error('R9 위반 — 회사명 깨짐');

fullClick(sendBtn);

// === Step 10: 발송 결과 확인 (3초 대기) ===
// 기대값: "제안 발송 완료" 모달 표시, "📧 {이름}님에게 이직 제안을 보냈어요"
//        우상단 카운트 "N/M건" 의 N 이 1 감소 + 좌상단 "제안 K건" 의 K 가 1 증가
```

### 10.3.1 미리보기 (선택)

[미리보기] 버튼은 사람인이 popup window 로 띄우는데 chrome popup blocker / native click only 정책으로 **자동 click 으로는 popup 안 뜸** (T4). 시각 검증 필요한 경우:
- 자동화 워커가 screenshot 캡처 (모달 안의 textarea 내용 시각 확인) 사장님 보고 후 발송 결정
- 또는 fullClick 으로 발송 직진 (R0 컨디션 모두 통과 시)

### 10.4 본문 텍스트 작성 (§17 + §17.3 + §17.10)

본문 ① (`jobOffer.offerComment`) 와 본문 ② (`jobOffer.chargeWork`) 의 실제 텍스트는 별도 섹션 참조:

| 구성요소 | 위치 |
|---------|------|
| 본문 ① 통합 템플릿 (회사 정보·궤도·제품·뉴스·임원·페르소나·처우·전형) | §17.3 |
| 본문 ① 품질 기준 F1~F13 | §17.10 |
| 회사별 캐시 (`~/.cache/saramin-company-research/<slug>.json`) | §17.4 |
| 본문 ② = JD 본문 그대로 매핑 (주요업무·자격요건·우대사항·복지·근무조건·채용전형) | §17.3 §17.11 |
| **R5 프리랜서 패스 — 발송 직전 모달 본문 + 회사명 + 직책 정규식 재검사** | §0 R5 |

### 10.5 자동 발송 판단 (R0 — 사장님 수동 click 의 컨펌 보조)

자동화 워커가 사장님께 보고할 때, R0 기준의 자동 발송 추천 / 컨펌 대기를 명시:

```javascript
const SHOULD_AUTO_SEND = (
  candidate.score >= 85 &&            // R0
  candidate.school_score >= 25 &&     // A 축 70% 이상
  candidate.mobility_score >= 20 &&   // B 축 67% 이상
  candidate.fit_score >= 25 &&        // C 축 70% 이상
  !candidate.freelancer_flag          // R5
);

if (SHOULD_AUTO_SEND) {
  // 디스코드 #ops-candidates 알림 + 사장님께 "[미리보기] 클릭하시면 자동 추천 발송 OK"
} else {
  // 디스코드 알림 + 사장님께 "85점 미만 / 프리랜서 의심 — 사장님 컨펌 필요"
}
```

**자동 발송 (R18, V2.1):** SHOULD_AUTO_SEND === true 인 경우 §10.3 의 fullClick 패턴으로 [제안 발송] 자동 click. 발송 후 "제안 발송 완료" 모달 + 카운터 1 감소 확인. SHOULD_AUTO_SEND === false 인 경우만 사장님께 컨펌 메시지 + screenshot.

---

## 11. 발송 — '제안 발송' 버튼 click

미리보기 닫고 본 모달의 **제안 발송** 버튼 click (캡처 image #12 하단 우측).

발송 성공 시:
- 사람인 토스트: "제안이 발송되었습니다"
- 우리 측 즉시 액션:
  1. 디스코드 `#ops-candidates` 알림 (회사·포지션·후보자 + 점수 + 근거)
  2. 칸반보드 `/kanban?board=FY26_Candidates` 카드 INSERT
  3. `candidate_activity_log` INSERT (`event_type='saramin_offer_sent'`)
  4. `pipeline_candidates.metadata.outreach.saramin_offer_at = NOW()`

---

## 12. 칸반보드 등록 + 컨택 기록

```sql
INSERT INTO pipeline_candidates (
  source, source_id, name, ai_assessment, match_score, metadata, board_id
) VALUES (
  'ai_search:saramin:profile',
  'saramin:<rNo>',
  '<회사>/<포지션>/<이름>OO',
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
      'channel',         'saramin',
      'message_template','custom',
      'sent_at',         NOW(),
      'rNo',             '<saramin_id>'
    ),
    'snapshot_path', '/tmp/profile-archiver/saramin/<rNo>.png',
    'saved_via', jsonb_build_array(
      'saramin_native',
      'profile_archiver_extension',
      'supabase'
    )
  ),
  'FY26_Candidates'
);

INSERT INTO candidate_activity_log (candidate_id, event_type, ts, payload)
VALUES (
  <candidate_id>,
  'saramin_offer_sent',
  NOW(),
  jsonb_build_object(
    'position_id', '...',
    'preview_url', '...',
    'score', 92,
    'matched_position_score', 88
  )
);
```

---

## 13. 한 턴 완료 후 보고 형식

사장님께 디스코드 `#ops-candidates` + Claude Code 응답으로:

```
🟢 사람인 한 턴 완료 — {회사} / {포지션}
검색 결과: N명
프로필 무조건 저장(R6): M명 ✅
85점 이상 자동 발송: K명
85점 미만 사장님 컨펌 대기: P명
패스(프리랜서/저점): Q명

자동 발송 명세:
1. 이OO · 92점 · {매칭근거 한 줄} · 칸반 등록 ✅
2. 김OO · 88점 · ... · 칸반 등록 ✅

저장된 프로필 (저장만, 발송 X):
- 박OO (82점) — 평균 근속 짧음, 사장님 컨펌 필요
- 정OO (78점) — 학교 약함, 사장님 컨펌 필요

남은 이직 제안 건수: {N}/{S} (시작 시 {S}건, -{K}건 차감)
```

---

## 14. 오류 처리 (즉시 STOP 조건)

| 신호 | 행동 |
|------|------|
| URL 에 `/captcha`, `/block`, `/denied`, `/robot` | `SaraminBlockedError` 던지고 STOP + 디스코드 `#ops-incidents` 알림 |
| URL 에 `/zf_user/auth` 로 리다이렉트 | `SaraminNotLoggedInError` — 사장님께 수동 재로그인 요청 |
| reCAPTCHA iframe 노출 | 즉시 STOP, 절대 자동 해결 시도 X |
| 사장님이 chrome 만지면 | tab focus event 감지 → 자동화 action 0 (메모리 [feedback_human_intervention_pause]) |
| 이직 제안 모달에서 "잔여 건수 부족" 노출 | 새 한 턴 거절 — 사장님께 상품 갱신 요청 |
| 프로필 아카이버 익스텐션 응답 없음 (`[data-archiver-status]` 미부여) | 워닝 로그 + Supabase upsert 만 진행 (R6 일부 보장) |

---

## 15. 참고 자산

| 항목 | 위치 |
|------|------|
| 자격증명 | `~/.secrets/saramin.env` (chmod 600) |
| 메타 가이드 | `~/.claude/skills/talent-search/SKILL.md` |
| 잡코리아 한 턴 (1:1 대응) | `~/.claude/skills/jobkorea-talent-sourcing/SKILL.md` |
| 프로필 아카이버 | `tools/profile-archiver/` (R6 핵심) |
| 사람인 워커 | `tools/saramin-sourcing/` (있으면) |
| 디스코드 알림 | `tools/ai-search-shared/src/discord-notify.ts` (channel: `OPS_CANDIDATES`) |
| 칸반 보드 | `/kanban?board=FY26_Candidates` |
| 시스템 감사 | `docs/engineering/qa/ai-search-system-audit-2026-05-21.html` |
| Supabase 테이블 | `pipeline_candidates`, `candidate_career_paths`, `candidate_activity_log`, `pipeline_position_cards` |

---

## 16. 사람인 vs 잡코리아 — 한 줄 차이

| 항목 | 사람인 | 잡코리아 |
|------|--------|---------|
| URL | `/zf_user/memcom/talent-pool/main/search` | `/corp/person/find` |
| 키워드 박스 | **OR / AND / NOT 3분할 노출** | 통합검색 ▼ 드롭다운 단일 + 키워드 모드 토글 |
| 빠른 필터 | `국내 유명 대학`, `인서울 대학`, `요즘 뜨는 인재` chip | 좌측 패널 체크박스 |
| 학력 | 대학(4년) + 석사 ON | 대학교(4년) + 대학원 ON |
| 정렬 | 추천순 (디폴트) | 추천순 (선택 필수) |
| 차감 | 이직 제안 발송 시 1건 | 포지션 제안 발송 시 1건 |
| 메시지 모드 | 단일 textarea + `✨ AI 제안 내용 만들기` 버튼 | 등록 포지션 / 진행중 공고 분기 |
| R6 핵심 | **사장님 명시 — 무조건 저장 (이 SKILL)** | (잡코리아도 같은 정책 적용 권장) |

---

## 17. 🏢 회사 조사 절차 (Company Research) — 발송 전 필수

> 2026-05-22 사장님 명시 — "회사에 대한 조사를 너무 등한시 한다. 최근 재무·투자·뉴스·인원·매출 구조·제품 분석·임원 뉴스·유튜브·아웃스탠딩 뉴스 다 넣어야 한다."

**적용 시점**: 모든 신규 포지션 발송 전 — `[제안 내용]` textarea 와 `[업무 내용]` textarea 채우기 직전.

**목적**: 후보자가 받은 메시지를 보고 "어 이 회사 진짜네" 라고 신뢰할 수 있도록, 회사 가치·궤도·임팩트·문화를 압축적으로 녹여 넣음. 가져온 정보는 한 줄 한 줄 사실 근거 확인.

### 17.1 항목별 데이터 소스 표

| # | 조사 항목 | 데이터 소스 (우선순위) | 자동화 도구 |
|---|----------|----------------------|------------|
| 1 | **최근 재무** (매출·영업이익·자본금) | [THE VC](https://thevc.kr/), [Saramin 기업정보](https://www.saramin.co.kr/zf_user/company-info), [잡플래닛](https://www.jobplanet.co.kr), DART 공시 | WebSearch + 회사명 |
| 2 | **투자 상황** (시리즈·누적·기업가치·VC 명단) | THE VC `/<회사>/fundings`, [Crunchbase](https://www.crunchbase.com), AI타임스·전자신문·서울경제·매일경제 | WebSearch "<회사> 시리즈 누적" |
| 3 | **최근 뉴스 국내** | ZDNet Korea, 전자신문, AI타임스, 서울경제·매일경제·한국경제 | WebSearch (현재 year 명시) |
| 4 | **외신 뉴스** | Yahoo Finance, Morningstar, Business Wire, TechCrunch, Fortune, Bloomberg | WebSearch "<영문회사명> funding/launch" |
| 5 | **임직원 인원** | Saramin 기업정보, 잡플래닛, LinkedIn 회사 페이지 | WebFetch saramin.co.kr/zf_user/company-info |
| 6 | **매출 구조** (B2B/B2C·주요 매출원) | 회사 IR · 외신 review · ZDNet 매출 기사 | WebSearch "<회사> 매출 구조 ARR" |
| 7 | **제품 예리한 분석** (강점·차별점·경쟁사) | 회사 공식 사이트, 회사 블로그, 외신 product review | WebFetch 공식 사이트 + 외신 |
| 8 | **임원 인터뷰·발표** (대표·CTO·VP) | YouTube search, 외신 interview, AI타임스 인터뷰 | WebSearch "<대표 이름> 인터뷰" |
| 9 | **유튜브 소식** (제품 데모·키노트·뉴스) | YouTube `site:youtube.com <회사>` | WebSearch with `site:youtube.com` |
| 10 | **🔥 아웃스탠딩 뉴스 요약** (스타트업 산업 분석 매체) | [outstanding.kr](https://outstanding.kr) — 사장님이 직접 스크레이핑 운영 | `tools/outstanding-scraper/` |

### 17.2 회사 조사 자동화 워크플로우 (모든 신규 포지션 발송 전 실행)

```bash
# 1. 회사명·포지션 컨텍스트 준비
COMPANY="뤼튼테크놀로지스"
COMPANY_EN="Wrtn Technologies"
POSITION="[OOC] Global Brand Marketer (북미)"

# 2. WebSearch 병렬 (Claude 직접 호출, 한 메시지에 3~5 쿼리 묶기)
#    - "<회사> 시리즈 누적 투자 <year>"
#    - "<COMPANY_EN> funding round <year>"
#    - "<회사> 매출 임직원 MAU <year>"
#    - "<COMPANY_EN> revenue ARR <year>"
#    - "<회사> 대표 인터뷰 OR 발표 <year>"

# 3. WebFetch 핵심 페이지 (한 회사당 3~5개)
#    - https://thevc.kr/<slug> (영문 또는 한글 변환)
#    - https://www.saramin.co.kr/zf_user/company-info/view?csn=<csn>
#    - https://www.jobplanet.co.kr/companies/<id>/landing/<회사>
#    - 회사 공식 사이트 /about · /company · /investors

# 4. 아웃스탠딩 스크레이핑 — 우리 자체 db 검색
cd /Users/kangsangmo/Desktop/Valuehire_v4/tools/outstanding-scraper
node dist/cli.js search --keyword "<회사명>" --limit 5
# 또는 archive.db / Supabase outstanding_articles 테이블 SQL

# 5. 유튜브 — Claude 가 직접 검색 후 핵심 1~2개 영상 요약 (Title + Date + Channel)
#    site:youtube.com "<회사>" 검색 결과의 최근 1년 영상 우선

# 6. 통합 브리핑 — 위 10개 항목을 textarea 본문에 압축 (각 항목 1~3줄)
```

### 17.3 textarea 본문 통합 템플릿 (사장님 명시 격식)

**제안 내용 textarea** (사람인 한도 2,000자, 다수 후보자에게 동일 발송 — 개인화 메시지 X):

```
안녕하세요.

테크 서치펌 밸류커넥트의 헤드헌터 강상모입니다.
<회사>의 <포지션> 포지션 제안드리고자 연락드립니다.

▣ 회사 — <회사 영문명> (<설립연도> 설립)
- 누적 투자 <X>억원 / 시리즈 <N> <Y>억원 마무리 (<날짜>)        ← 항목 2
- 기업가치 <Z>억원 / 투자자: <VC 리스트>                           ← 항목 2
- 매출 추이: 20YY <A>억 → 20YY <B>억 (<배수> 배 성장)            ← 항목 1
- 매출 구조: <B2C/B2B 비중·주요 매출원 1~2개>                     ← 항목 6
- 임직원 약 <N>명 (사람인·잡플래닛 기준)                          ← 항목 5
- 미션·비전: "<한 줄 미션>"

▣ 제품·시장 포지션
- <대표 제품/서비스 1줄 설명>                                       ← 항목 7
- <카테고리 내 경쟁사 1~2개 비교 — 차별점>                         ← 항목 7
- <외신/주요 매체 주목 사례>                                        ← 항목 4

▣ 최근 모멘텀 (최근 6개월)
- <뉴스 1: 날짜 + 핵심>                                              ← 항목 3
- <뉴스 2: 외신 보도 또는 임원 인터뷰>                              ← 항목 4·8
- <유튜브/아웃스탠딩 분석 1줄>                                     ← 항목 9·10

▣ 포지션 — <포지션명> 핵심
<JD 본문에서 직무 정체성 3~5줄 압축>

▣ 처우·문화
- 정규직 / <근무지> / <경력 조건> / <수습 기간>
- <복지 1~2개 핵심>
- <보상 구조 핵심>

▣ 다음 스텝
관심 있으시면 30분 캐주얼 콜로 포지션·문화·처우·인터뷰 절차 상세 먼저 듣고 결정하실 수 있습니다. 회신 부탁드립니다.

강상모 드림 | 밸류커넥트
sangmokang@valueconnect.kr | 010-3929-7682
🔗 valuehire.cc — 큐레이션 커리어 기회 구독
```

**업무 내용 textarea** (사람인 한도 2,000자):

```
[<포지션> — 주요업무]
<JD 의 주요업무 목록 그대로>

[자격요건]
<JD 의 자격요건 그대로>

[우대사항]
<JD 의 우대사항 그대로>

[근무 조건]
- 정규직 / <근무지> / <경력 조건> / 포트폴리오 여부

[채용 전형]
<JD 의 채용 전형 그대로>
```

### 17.4 회사별 캐시 — 같은 회사 다음 포지션 재사용

회사 조사는 **회사별 1회**. 같은 회사의 다른 포지션 발송 시 캐시 재사용:

```bash
# 회사별 브리핑 JSON 저장
~/.cache/saramin-company-research/<회사_slug>.json
# 예: ~/.cache/saramin-company-research/wrtn-technologies.json
```

JSON 구조:
```json
{
  "company_name": "뤼튼테크놀로지스",
  "company_en": "Wrtn Technologies",
  "researched_at": "2026-05-22T...",
  "finance": { "revenue_latest_kr": 471, "revenue_latest_year": 2025, "growth_x": 15 },
  "funding": { "total_kr": 1300, "latest_series": "B", "latest_kr": 1080, "valuation_kr": 3400, "investors": ["굿워터캐피탈(리드)", "BRV", "캡스톤파트너스", "Antler", "ZVC"] },
  "headcount": 200,
  "news_recent": [{"date":"2026-04-15","title":"OOC 북미 런칭","source":"Yahoo Finance"}, ...],
  "products": { "main": "Crack(크랙)/OOC", "competitors": ["Character.AI","Replika"] },
  "executive_quotes": [{"who":"이세영 대표","quote":"2026 미국 진출 → 2027 ARR $700M → 2028 IPO"}],
  "outstanding_articles": [{"date":"...","title":"..."}],
  "youtube": [{"title":"...","url":"...","date":"..."}]
}
```

### 17.5 캐시 만료

- **기본 TTL: 30일** — 회사 정보는 빠르게 바뀌므로
- **강제 갱신 트리거**: 새 시리즈 투자 뉴스, IPO 발표, 대표 교체 등 — 사장님 명시 또는 우리 뉴스 모니터링이 detect 시
- **사장님 명시 갱신**: "뤼튼 회사 조사 다시" 같은 명령 시 즉시 새로 수집

### 17.6 사장님 명시 절대 규칙 (회사 조사)

| # | 규칙 |
|---|------|
| C1 | **추정·짐작 금지** — 모든 숫자(투자·매출·인원) 는 1회 이상 외부 매체에서 확인. 모르면 적지 말 것 |
| C2 | **outdated 정보 금지** — 6개월 이상 된 매출·투자 수치는 갱신 검색 |
| C3 | **아웃스탠딩 뉴스 반드시 포함** — 사장님이 직접 스크레이핑 운영 (`tools/outstanding-scraper/`). 회사 관련 기사 있으면 1~2개 핵심 인용 |
| C4 | **임원 인터뷰 1개 인용** — 대표·CTO 의 최근 1년 발언 1개로 회사 비전·궤도 확립 |
| C5 | **외신 보도 1개 인용** — 글로벌 매체 (Yahoo / Morningstar / Bloomberg / TechCrunch 등) 보도가 있으면 1개 포함 |
| C6 | **WebSearch 후 Sources 명시** — 발송한 메시지의 모든 수치는 source URL 1회 확인 (메시지 본문에는 안 넣지만 내부 audit log 에 기록) |

### 17.7 다른 포지션 등록 시 절차 (사장님 명시 — 이 SKILL.md 그대로 따름)

새 포지션 등록 시:
1. 사장님이 채용공고 본문 (JD) 던지심
2. 워커가 **회사명 추출** → `~/.cache/saramin-company-research/<slug>.json` 캐시 확인
3. 캐시 hit (≤30일) → 그대로 사용 / miss → 17.2 자동화 워크플로우 실행 → 캐시 저장
4. 17.3 템플릿에 회사 정보 + JD 매핑 → `[제안 내용]` `[업무 내용]` 두 textarea 본문 생성
5. 사장님 컨펌 (DRY RUN preview) → 라이브 발송

### 17.8 현재 캐시된 회사 (2026-05-22 기준)

`~/.cache/saramin-company-research/` 디렉토리 — 6개 회사 1차 조사 완료. 다음 포지션 발송 시 즉시 재사용 가능:

| 회사 | slug.json | 핵심 지표 |
|------|-----------|----------|
| 뤼튼테크놀로지스 | `wrtn-technologies.json` | 누적 1,300억 / 매출 471억(2025) / MAU 600만+ / OOC 2026-04 북미 런칭 |
| 모벤시스 | `movensys.json` | 임직원 54명 / Mitsubishi 지분 / WMX 세계 최초 SW 모션 컨트롤러 / 시장 $14.3B |
| 코드잇 | `codeit.json` | 매출 307억(2025) / 첫 흑자전환 / 누적 140억 / 코스닥 예심 |
| 두나무 | `dunamu.json` | 상반기 매출 8,019억 / 업비트 운영 / Web3 인프라 |
| 스푼랩스 | `spoon-labs.json` | KRAFTON 2회 1,390억 / 비글루 해외 매출 70%+ / LA 진출 |
| TwelveLabs | `twelve-labs.json` | 누적 $107M / Databricks·Snowflake·SKT 투자 / Video AI |

### 17.10 🔥 본문 초안 품질 기준 (F1~F13)

> 사장님 2026-05-22 — 후보자가 메일 처음 봤을 때 진지하게 검토할 수 있도록 데이터 압축 + 정성스러운 초안. 빈약한 본문 (회사명/포지션/급여/고용형태 4줄) 금지.

**필수 포함 요소** (1개라도 빠지면 발송 X):

| # | 요소 | 출처 | 최소 길이 |
|---|------|------|----------|
| F1 | **첫 줄 hook** — 후보자가 메일 처음 봤을 때 "어 들어볼만 한데" | 회사·포지션 매력 한 줄 | 1줄 |
| F2 | **회사 핵심 가치** — 누적 투자 / 매출 / MAU / 임직원 / 미션 | §17 캐시 JSON | 4~6줄 |
| F3 | **회사 궤도** — 매출 성장 배수 + 같이 영업손실/burn rate 도 정직하게 | §17 캐시 + 아웃스탠딩 | 1~2줄 |
| F4 | **제품 포지션** — 카테고리 + 글로벌 경쟁사 1~3개 비교 | §17 캐시 products | 2~3줄 |
| F5 | **🔥 외신 인용 1개** | Yahoo Finance / Morningstar / Bloomberg / TechCrunch / Business Wire 등 | 1줄 |
| F6 | **🔥 아웃스탠딩 분석 1개** | `outstanding.kr` (`tools/outstanding-scraper/` 또는 WebSearch `site:outstanding.kr`) | 1~2줄 |
| F7 | **🔥 임원 quote 1개** | 대표/CTO 의 최근 1년 발언 (외신·국내·유튜브) | 1~2줄 |
| F8 | **포지션 임팩트** — 이 자리가 회사에서 차지하는 의미 (첫 멤버? 핵심 라인업? 전략 포인트?) | JD + 회사 컨텍스트 | 2~3줄 |
| F9 | **타깃 후보자 페르소나** — 어떤 출신·경력 분이 적합한지 (회사·산업·역할 3~5개 명시) | JD AI Search 본문의 1~6순위 회사군 | 2~3줄 |
| F10 | **처우·문화** — 정확 (정규직/근무지/경력/수습/복지) | JD + 채용공고 | 4~5줄 |
| F11 | **채용 전형** — JD 그대로 | JD | 1~2줄 |
| F12 | **다음 스텝** — "30분 캐주얼 콜" 또는 사장님 명시 톤 | 표준 | 1~2줄 |
| F13 | **연락처 footer** | 강상모 / 밸류커넥트 / sangmokang@valueconnect.kr / 010-3929-7682 / valuehire.cc | 3줄 |

**금지 패턴** (사장님 2026-05-22 캡처에서 본 실패 사례):
- ❌ "회사: X - 국내 대표 생성형 AI 플랫폼 기업 / 포지션: X / 급여: 협의 후 결정 / 고용형태: 정규직" — 4줄짜리 빈약 본문
- ❌ "정규직사람" 같은 오타 + 한국어 문법 깨짐
- ❌ 우리가 §17 으로 조사한 데이터 (1,300억 누적 / MAU 600만 / 외신 보도 / 임원 비전) 단 한 글자도 안 들어가는 본문
- ❌ 자랑조 ("국내 1위", "혁신 기업", "최고의 인재" 같은 추상 표현 남발)
- ❌ JD 의 핵심 직무·자격·우대를 임의로 짧게 줄이거나 누락

### 17.11 🔥 공식 채용공고 명확 인지 (사장님 2026-05-22 명시)

> "공식 채용공고를 명확히 인지해라". JD 본문의 모든 디테일을 사람인 form 의 textarea 에 반영. 임의 축약 X.

**JD 인지 체크리스트** (발송 직전 1회):
- [ ] 회사명 정확 (한글·영문 둘 다 인지)
- [ ] 포지션 풀네임 — 직급 / 부서 / 모집 인원
- [ ] 고용형태 — 정규직/계약직/프리랜서/인턴 (R5 프리랜서면 발송 X)
- [ ] 근무지 — 본사 / 내·외근 / 원격
- [ ] 경력 — 신입 / N년 이상 / N년 이하 / 무관
- [ ] 학력 — 전공 명시 여부 + 학력 수준
- [ ] 주요업무 — JD 본문 글머리표 모두
- [ ] 자격요건 — JD 본문 글머리표 모두
- [ ] 우대사항 — JD 본문 글머리표 모두
- [ ] 채용 전형 — 단계별 (서류 → ... → 최종)
- [ ] 처우 — 연봉 협의 여부 / 인센티브 / 복지 / 수습 기간
- [ ] 합격보상 — 지원자·추천인 금액

**JD 원본 SoT (Single Source of Truth)**:
- 1순위: 사장님이 직접 던지신 메시지 (캡처 또는 본문)
- 2순위: Supabase `pipeline_position_cards.jd_text` (ClickUp sync)
- 3순위: 회사 공식 채용 페이지 URL (예: `wrtn.career.greetinghr.com`)

위 3개 source 중 가장 최신·풍부한 것 사용. 우리 캐시 JSON 의 회사 정보 + JD = textarea 본문 완성.

### 17.9 즉시 실행 명령 (사장님 한 줄로 invoke)

```bash
# (a) 회사 조사 강제 갱신 (캐시 invalid / 신규 회사 / 사장님 명시 "회사 조사 다시")
COMPANY="<회사명>" SLUG="<slug>" bash tools/saramin-talent-pool/research-company.sh
# → WebSearch 병렬 + outstanding-scraper + YouTube + JSON 저장

# (b) 캐시 hit 확인 + textarea 본문 생성 + DRY RUN preview
cat ~/.cache/saramin-company-research/<slug>.json    # 캐시 확인
POS_JSON=<position_id_or_path> \
COMPANY_SLUG=<slug> \
CANDIDATE_URL=https://hiring.saramin.co.kr/applicant-view/position/resume/<rNo> \
node tools/saramin-talent-pool/direct-send.mjs --dry-run

# (c) 라이브 발송 (사장님 컨펌 후, R0 85점+ 자동 또는 사장님 명시)
... 동일 명령 --dry-run 제거

---

## R17: chrome MCP `read_page` 금지 — lone surrogate JSON 오류 세션 마비

- **금지**: `read_page` 또는 `javascript_tool`로 사람인 모달 HTML 대량(1MB+) 수신 → UTF-16 lone surrogate가 JSON에 깨진 채 전달 → Anthropic API 400(`no low surrogate in string`) → conversation history 전체 오염 → 이후 모든 요청 실패.
- **대안**: `find` (selector 기반, 결과 소량) + `javascript_tool`(짧은 응답 `{ok:true}` 수준만). 화면 분석은 screenshot(binary라 안전).
- **복구**: 터지면 `/clear` 또는 신규 세션.
- **관련**: QA-243, jobkorea-talent-sourcing 동일 규칙.

---

## R18: 자동화 한 사이클 = screenshot → 좌표 측정 → click → screenshot 검증

- 좌표를 절대 guess하지 말 것. 매 액션 전 screenshot으로 현재 좌표 측정 → 그 좌표로 click → 즉시 screenshot으로 결과 검증.
- 모달 위치는 viewport 크기에 따라 달라짐 — 매번 screenshot에서 측정.
- 사람인 이직 제안 모달의 경우 [추가] click·textarea fill·[제안 발송] fullClick 패턴 모두 screenshot 검증 필수.

---

## R19: 사람 개입 신호 — 사장님 손수 작업 발견 시 chrome 액션 0

- **트리거**: "이거 입력하지마" / "내가 할게" / "내가 ~ 클릭해" / 모달에 사장님이 직접 입력한 값 발견.
- **즉시 행동**: chrome MCP 액션 0. 사장님 화면 건드리지 않는 작업(file system, ClickUp MCP read, screenshot 모니터)으로 전환.
- 사장님 작업 완료 신호("이제 다음 해", "ㅇㅋ 진행해") 받기 전까지 대기.
- 관련: `feedback_human_intervention_pause` 메모리.

---

## R20: 사람인 정규화 unified.jsonl 사용법

- **경로**: `~/.cache/saramin-positions/unified.jsonl` (각 line = JSON, 단일 schema)
- **필수 필드**: `position_name`, `duties`, `qualifications`, `work_location`, `employment_type`
- **누락 필드**: `category_l1` → 회사 + position_name으로 추론
- **다음 batch에서 raw `*.json` 직접 읽지 말고 unified.jsonl만 사용.**
- 관련: jobkorea R20 동일 패턴.

---

## R21: 첫 widget 검증 후 나머지 필드 입력은 batch 한 번에

- **사장님 명문**: "모달창 뜨고 정규직 클릭한 다음부터는 필드입력 더 빠릿하게 해 중간텀 두지마"
- 첫 widget 1개(직종·고용형태 등) click 검증(screenshot) 끝나면, 그 이후 모든 텍스트 필드 입력은 `browser_batch` 단일 호출에 묶어서 한 번에. wait 0.
- screenshot 검증은 batch 마지막 step으로만 1회.
- **절대 금지**: wait 1 / wait 2 / screenshot → 분석 → click → screenshot 같은 step-by-step 1초 cycle. 1건 cycle을 10초 → 60초로 늘려 사장님 frustration 유발.

---

## R22: 탭 ID는 사장님에게 노출 금지

- **사장님 명문**: "내가 그탭을 어떻게 알아"
- chrome 탭 식별은 사장님 화면에 보이는 정보(탭 제목 + URL 마지막 path + 가장 최근 열린 탭)로만 안내.
- 숫자 ID는 내부 로그·코드에만. 사용자 facing 메시지에서 절대 언급 금지.

---

## R23: 사장님이 보는 화면 식별 = 탭 title + URL + page heading

- 잘못된 안내: "탭 632986843에 떴어요" ❌
- 올바른 안내: "사람인 이직 제안 탭 (후보자 37874592, 레OO)" ✅ / "Chrome 창 '이직 제안하기' 제목, 사람인 로고 + 레OO 후보자 페이지" ✅
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
- batch 등록 전 ClickUp FY26ClientsPosition 보드 read → custom field "사람인 등록 완료" 마킹된 task_id list 확보 → unified.jsonl과 cross-check해서 중복 제외.
- 잡코리아도 동일: "잡코리아 등록 완료" 마킹 기준.

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
- 올바른 안내: "Chrome 탭 줄에서 가장 최근 열린 탭, 제목 'review.html' 또는 '사람인 등록 검수'" ✅
- `file:///` URL chrome 변환 버그가 있으면 `osascript -e 'tell application "Google Chrome" to open location "file:///..."'`로 강제 정상화.

---

## R30: 사람인·잡코리아 동일 데이터로 동시 batch

- **사장님 명문**: "사람인 잡코리아 모두 등록해"
- `~/.cache/saramin-positions/unified.jsonl`과 `~/.cache/jobkorea-positions/unified.jsonl`을 동일 source(ClickUp FY26 task)에서 정규화.
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

- **2026-05-23** — R17(read_page 금지·lone surrogate·QA-243) + R18(screenshot 우선 사이클) + R19(사람 개입 즉시 정지) + R20(saramin unified.jsonl) + R21(batch 한 번에·빠릿하게) + R22(탭ID 노출 금지) + R23(화면 식별 안내) + R24(깨끗 reset) + R25(Multi Agent 병렬) + R26(중복 확인 ClickUp) + R27(/goal 끝까지) + R28(hint 즉시 trial) + R29(리뷰 위치 안내) + R30(양 사이트 동시 batch) + R31(QA 영구 등록) + R32(코칭 즉시 R화 메타 규칙) 추가. 사장님 이번 세션 코칭 전체 반영.
- **2026-05-22** — 사장님 명시 8단계 워크플로우 + 85점 자동 발송 정책(좋은학교/이직안정성/직무직결성 3축) + 자격증명 `~/.secrets/saramin.env` 격리 + **R6 프로필 무조건 저장(사람인 native + 크롬 익스텐션 + Supabase 3중 저장)** + 첫 실 타겟 = 뤼튼테크놀로지스 Product Engineer. 잡코리아 한 턴 스킬과 1:1 대응.
- **2026-05-22 (V1 라이브 자동화 검증)** — Playwright + CDP 9222 로 풀 자동화 검증 성공. **§6 DOM Selector 라이브 검증 표** 추가 (OR/AND/NOT input + 빠른필터 chip + 검색 버튼 + 결과 카드 + 후보자 저장 버튼 모두 selector 확정). **R5 강화 (정규식 `/프리랜서|Freelancer|외주|Contract Worker|프리\b/i`, 코드 레벨 강제, 카드 텍스트 + 프로필 상세 + 회사명 + 직책 모두 검사, 발송 직전 모달에서도 한 번 더)**. 라이브 결과: OOC Brand Marketer (북미) 검색 660명, 카드 20개, 프리랜서 자동 skip 1건 ("외주"), R6 자동 저장 19건, 에러 0. 참고 스크립트: `tools/_tmp/saramin-talent-pool-v1.mjs`. **V2 (이직 제안 모달 자동화 + R0 85점+ 자동 발송)는 다음 라운드** — 모달 selector 정찰 후 작성.
- **2026-05-22 (§17 회사 조사 절차 추가)** — 사장님 명시 "회사 조사를 너무 등한시한다". 모든 신규 포지션 발송 전 10개 항목 회사 조사 의무 (재무·투자·뉴스·외신·인원·매출 구조·제품 분석·임원 인터뷰·유튜브·아웃스탠딩). 데이터 소스 표 + 자동화 워크플로우 + textarea 본문 통합 템플릿 + 회사별 캐시 (`~/.cache/saramin-company-research/<slug>.json`, TTL 30일) + 절대 규칙 C1~C6 (추정 금지·outdated 금지·아웃스탠딩 반드시·임원 인터뷰·외신 인용·Sources audit) 명문화. 다른 포지션 등록 시도 이 절차 따름. 라이브 검증 (뤼튼테크놀로지스): 누적 투자 1,300억 / 시리즈 B 1,080억 / 기업가치 3,400억 / 매출 471억 (2025) / MAU 600만+ / OOC 북미 2026-04-15 런칭 / 2028 IPO 목표 — 8개 외부 source 확인.
- **2026-05-23 (V2 이직 제안 모달 라이브 자동화 완전 검증)** — 사장님 명시 "이 과정은 매우 중요하기 때문에 정확하게 프로세스화 해서 나중에 실수가 없도록 해야함". 뤼튼테크놀로지스 / Global Brand Marketer (북미) / 후보자 37874592 (레OO 여 1996년생 고려대학교 대학원 석사) 라이브 시도에서 발견한 **5가지 함정 (T1~T5)** 모두 명문화. **§0 절대 규칙 R9~R13 신설** (T1=한국어 unicode escape 금지 / T2=textarea reset 트리거 / T3=DOM-only setValue React state sync 안 됨 / T4=자동 [미리보기] click 불가 / T5=React useId 매 세션 다름). **§10 전체 V2 절차로 통째 rewrite** — 라이브 검증된 안정 selector 표 (§10.1) + 9단계 자동화 절차 코드 (§10.2, `execCommand('insertText')` 패턴) + 사장님 수동 단계 M1~M4 (§10.3) + 본문 텍스트 §17 cross-reference (§10.4) + R0 자동 발송 판단 (§10.5). 자동화는 모든 필드 채움 + 검증 + STOP → 사장님 [미리보기] [제안 발송] 수동 click.
- **2026-05-23 (V2.1 자동 발송 + 5가지 추가 함정 보강) — 첫 실 발송 성공** — 사장님 명시 "수동하지 마. 니가 해. 끝까지" + "이 과정 매우 중요 정확하게 프로세스화 해서 다음 안 틀리도록". V2 절차 끝까지 가는 과정에서 **5가지 추가 함정 (T6~T10) 발견 → §0 R14~R18 신설**: T6/R14=listbox open 시 textarea fill 차단 (commentLen 0) → fill 전 listbox 닫기 / T7/R15=옵션 변경 시 "작성중 내용 변경할까요?" confirm 모달 → [변경] 자동 click / T8/R16=본문 "•" 글머리표가 사람인 list-style 과 겹쳐 두 개 표시 → 글머리표 "—"/"-" 또는 제거 / T9/R17=회사 소개 약함 = 후보자 무시 위험 → F2~F7 모두 포함 필수 / T10/R18=[제안 발송] click 은 fullClick 패턴 (scrollIntoView + focus + 9개 mouse events + Enter key) 만 통과 → **R12 폐기, 자동 발송 가능**. **§10.3 자동 발송 절차로 rewrite** + **§10.2.1 옵션 변경 confirm 모달 처리** + **§10.2 Step 8.5 listbox 닫기 명시**. 첫 실 발송 성공 검증: 후보자 37874592 레OO 에게 뤼튼테크놀로지스 / Global Brand Marketer (북미) 이직 제안 발송 완료. 우상단 카운트 325→324 (1건 차감 확인), 좌상단 제안 2건→3건 (증가 확인). 본문 1,534자 + 998자, 회사명 정상 ("뤼튼테크놀로지스"). + **listbox 옵션 등록 시 한국어 escape 깨짐 사고 (Global Growth Marketer 회사명 "뤼튼"→"뛤튼") 사장님 명시 후 회복 — R9 다시 강조**.

---

## R39: 자동화 상황에서 "사장님 손수" 표현 절대 금지

- **사장님 명문**: "앞으로 사장님이 손수 라는 말은 최소한 사람인 잡코리아나 자동화를 꾀하는 상황에서는 하지마"
- 적용: chrome MCP / Playwright / 자동화 worker 컨텍스트에서 사용자에게 "사장님이 직접/손수 해주세요" 표현 절대 사용 금지.
- 자동화로 해결할 길 모두 시도 후, 정말 불가능하면 "사용자 화면에서 1회 click 부탁"으로 우회 표현.

---

## R40: 사람인 native `window.alert` dialog freeze 위험

- **재현**: 포지션 등록 또는 특정 form 제출 → native alert 표시 → CDP/Playwright automation 전체 block → 후속 자동화 불가.
- **root cause**: `window.alert` 는 main thread 차단. CDP/automation tool 모두 block됨.
- **해법 우선순위**:
  1. **페이지 진입 시 `window.alert = () => true; window.confirm = () => true;` override** — 가장 안전
  2. 키보드 Enter 단독으로는 dismiss 안 됨
  3. 마지막 fallback: 사용자 chrome 화면 [확인] 1회 click
- **적용**: 매 automation batch 시작 전 `javascript_tool` 로 alert override 강제.

---

## R41: 사람인 검색 input 수정 후 "검색" 버튼 click 필수

- **검증 결과**: OR/AND/NOT input 변경 + chip 클릭 후 자동 검색 안 됨. "검색" 버튼 명시 click 필수.
- free text search 아님 — 필터 + 명시 버튼 클릭 패턴만 작동.

---

## R42: 회사별 포지션명 매핑 — Product Engineer = 국내 직무 표기 확인 필수

- 해외 회사(뤼튼) Product Engineer = 국내 사람인 직무체계에서 가장 가까운 카테고리 재확인.
- 회사 조사 (§17) 에서 경쟁사 국내 채용공고 매핑 포함 — "뤼튼 같은 레벨 회사들은 국내에서 뭐라고 부르나?" 검색.

---

## R43: 모달 내 listbox + textarea 상호작용 = 순서 중요

- listbox 열린 상태 → textarea 입력 차단 (R14 재강조).
- textarea 입력 후 → listbox 옵션 변경은 confirm 모달 뜸 (R15 재강조).
- **순서**: ① listbox 닫기 → ② textarea 채우기 → ③ 필요 시 listbox 재오픈 + 옵션 변경.

---

## R44: 이직 제안 메일 한글명 검증 강화

- **사고**: listbox 에서 회사명/포지션명 선택 시 "뤼튼"→"뛤튼" 등 한글 자모 분리 오류 (R9 근본 재확인).
- **발송 직전 최종 검증**: textarea 본문 + listbox 표시 명 + 헤더 회사명 모두 한글 오류 체크 정규식 `/[ㄱ-ㅣ]+/` (자모만 포함).
- 발견 시 abort + alert 후 사장님 수동 확인 요청.

---

## R45: Batch cycle 최소화 — 검증만 screenshot, 나머지 한 번에

- **사장님 명문**: "필드 입력을 더 빠르게 해. 휴지기를 갖으려면 다 등록하고 휴지기를 갖어"
- 적용: 단일 후보자 1건 cycle = (1) [추가] click + screenshot 검증 / (2) 모든 textarea + listbox 입력 batch / (3) 최종 검증 screenshot / (4) fullClick [제안 발송].
- 입력 중간에 wait·screenshot 검증 절대 금지. 배치 = 1회성.

---

## §10.V3 포지션 풀 일괄 등록 batch (2026-05-23 라이브 검증)

> 이직 제안 모달 안 [+포지션 추가] sub-form 으로 **회사명 + 포지션명 2필드** 만 채워 포지션 풀에 영구 등록하는 batch. cache 41건 → 36건 신규 등록 0 fail 완전 자동 (사장님 R45 명시 — 사람 개입 0).

### V3 흐름

```
auto-login.mjs (세션 만료 시) → hiring 탭 진입
  ↓
[이직 제안] button click → 모달 OPEN
  ↓
combobox click → listbox OPEN + 기존 포지션 dedupe set 캡처
  ↓
record loop (cache N건):
  - DEDUPE skip (position name 25자 부분일치)
  - listbox.scrollTop = scrollHeight (R49)
  - [+포지션 추가] click (boundingBox area 최대 visible 우선)
  - fillByExec(offerCompanyNm, position name 입력)
  - [추가] click → listbox INSERT
  - (listbox 자동 OPEN 유지 — close-click 금지, R49)
```

### V3 코드: tools/saramin-bulk-register-from-jobkorea/{register-batch,auto-login}.mjs

---

## R46: hiring.saramin.co.kr stale modal freeze — 5분 이상 방치 시 CDP timeout

- **재현**: hiring URL ?modal=hiring-offer 띄워둔 채 5분 이상 방치 → chrome MCP `javascript_tool` / `navigate` 모두 CDP 45초 timeout.
- **root cause**: 사람인 React app 가 heavy + WebSocket idle disconnect + main thread 무한 대기.
- **해법**:
  1. batch 시작 전 항상 `page.reload({ waitUntil: 'domcontentloaded' })` 강제.
  2. modal URL 직접 navigate 후 [이직 제안] button click 으로 fresh trigger.
  3. chrome MCP 대신 **Playwright `connectOverCDP("http://localhost:9222")` 직접 접근** 우선.

---

## R47: hiring 도메인 별도 SSO — chrome saved password 자동 로그인

- **함정**: hiring.saramin.co.kr 은 saramin.co.kr 본 도메인과 **별도 SSO 세션**. ~24시간 비활성 → 모든 hiring URL → `/zf_user/auth` redirect.
- **부차 함정**: chrome MCP `navigate` 가 `auth?ut=c&url=https%3A%2F%2F...` query 차단 (`[BLOCKED: Cookie/query string data]`). Playwright 만 우회.
- **해법** (`tools/saramin-bulk-register-from-jobkorea/auto-login.mjs`):
  1. saramin auth 페이지 ID/PW input value 확인 — chrome 자동완성 채워져 있는지 (보통 12자/10자).
  2. 채워져 있으면 `button[type="submit"]` click.
  3. `waitForURL(u => !u.includes("/zf_user/auth"))` navigate 대기.
  4. `hiring.saramin.co.kr/applicant-view/position/resume/<rNo>?modal=hiring-offer` 재진입.
  5. 모달 자동 안 뜸 → [이직 제안] button click trigger.
- **fallback**: chrome saved password 부재 → 사장님께 1회 입력 + `~/.secrets/saramin.env` 생성. **(메모리에 격리됐다고 적혀있지만 실 파일 부재인 경우 다수 — 확인 필수)**.

---

## R48: `?modal=hiring-offer` query 만으로 모달 자동 안 열림 — [이직 제안] button click 필수

- 사람인 hiring URL 에 `?modal=hiring-offer` 가 있어도 페이지 로딩 후 React state 자동 반영 안 됨. 명시 button click 필요.
- 정규식 `/이직\s*제안/` 으로 "이직 제안" / "이직제안" 변형 모두 매칭. anchored `^...$` 금지 (R13 재강조 — id selector 아닌 textContent 매칭에서도 strict 패턴 깨짐).

```javascript
const btn = Array.from(document.querySelectorAll('button'))
  .find(b => /이직\s*제안/.test(b.textContent || '') && b.offsetWidth > 0);
btn?.click();
await page.waitForTimeout(2500);
```

---

## R49: [+포지션 추가] listbox scroll + dropdown close-click 금지 (alternating fail 원인)

- **함정 1**: 사람인 listbox 안의 [+포지션 추가] 버튼이 visible 영역 밖 (`x:0,y:0,w:0,h:0`). `listbox.scrollTop = listbox.scrollHeight` 끝까지 scroll 필요.
- **함정 2 (치명)**: `[추가]` click 후 listbox 가 **자동 OPEN 상태 유지** (방금 INSERT 한 옵션 selected 표시). 다음 cycle 에서 combobox click 으로 close → 다시 click 으로 open 패턴 적용 시 **두 번 toggle 되어 결국 close 상태 → [+포지션 추가] 안 보임 → 정확히 alternating 실패 (18/18) 발생**.
- **해법**:
  ```javascript
  // listbox OPEN 보장 — 이미 open 이면 close 하지 않음
  let lbOpen = await page.locator('[role="listbox"]').count() > 0;
  if (!lbOpen) {
    await page.evaluate(() => document.querySelector('[role="dialog"] [role="combobox"]')?.click());
    await page.waitForTimeout(800);
  }
  // listbox scroll to bottom
  await page.evaluate(() => {
    const lb = document.querySelector('[role="listbox"]');
    if (lb) lb.scrollTop = lb.scrollHeight;
  });
  await page.waitForTimeout(400);
  // [+포지션 추가] 최대 area visible 우선 click
  await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button')).filter(b => /포지션\s*추가/.test(b.textContent||''));
    let best = null, bestArea = 0;
    for (const b of btns) {
      const r = b.getBoundingClientRect();
      const area = r.width * r.height;
      if (area > bestArea && !b.disabled) { best = b; bestArea = area; }
    }
    best?.scrollIntoView({ block: 'center' });
    best?.click();
  });
  ```
- **2~3회 retry 패턴 권장** — 첫 시도 실패 시 다음 cycle 에서 listbox state 자연 회복. register-batch.mjs 5회 누적 시도로 36/36 0 fail 검증.

---

## R50: [추가] sub-form 제출 후 listbox INSERT 자동 — verify는 batch 끝에서만

- `[추가]` click 성공 = listbox 옵션 카운트 증가 (정확한 카운트는 사람인 lazy loading 으로 부정확하지만 추세 증가).
- **R45 위반 금지** — 매 record cycle 마다 listbox dump + verify 안 함. batch 끝에 1회만 dropdown 재오픈 + 신규 옵션 검색.
- results.jsonl 영속화로 resume 보장 — `success: true` 만 skip, fail 은 다음 run 에서 재시도.

---

## R51: `[name="offerCompanyNm"]` silent fail — 정상 동작

- `document.execCommand('insertText', false, '뤼튼테크놀로지스')` 실행 후 `el.value === ''` 빈 문자열로 나옴. **그러나 [추가] 활성 + 등록 정상**.
- 추정: 사람인 포지션 풀 등록 시 회사명은 후보자 페이지 컨텍스트에서 inherit. listbox 표시도 포지션명만 (예: `combo_text = "뤼튼 AX Backend Engineer (NestJS·Mong"`).
- **fail 처리 금지** — position fill 성공 + [추가] 활성 + click 통과 = 등록 성공.
- 단 `R9` 한국어 깨짐 검증은 position name 만 (`fillResult.position.value_after`) 적용.

---

## §10.V4 포지션 마스터 수정 패널 자동화 (2026-05-25 라이브 검증)

> V3 batch 76건은 회사명+포지션명만 등록되어 본문이 비어있었음 (QA-252). V4 흐름 — `talent-pool/main/candidate-manage` 의 포지션 수정 패널 textarea 2개에 회사 브리핑 + JD 영구 저장.

### V4 흐름

```
새 탭(ctx.newPage) → talent-pool/main/candidate-manage navigate
  ↓
검색 input[placeholder*="포지션 및 생성자명"] React-safe setter + Enter
  ↓
visible h2/h3 textContent === EXPECTED_TITLE 정확 매칭 → card.closest('.position_card')
  ↓ card.setAttribute('data-vh-target', '1') + scrollIntoView
점3개 svg button (aria-label="포지션 옵션 레이어 열림", ~28x28) click → menu OPEN
  ↓ 1.5s wait
[포지션 수정] menu item — 점3개 좌표 proximity (Δy<300, Δx<250) + tag 우선순위(button>a>LI>DIV)
  → LI/DIV 인 경우 내부 button.click() + mousedown/up dispatch 필수 (R54)
  ↓ retry 6×500ms — 패널 OPEN animation 대기
패널 OPEN: h2/h3 "포지션 수정" + input[name="hiringTitle"].value assertion ★
  ↓ assertion FAIL → 즉시 [취소] click + abort (R55, wrong card 저장 방지)
textarea[name="offerComment"] (제안 내용, 한도 2000자) ← React-safe setter
textarea[name="chargeWork"]   (업무 내용, 한도 2000자) ← React-safe setter
  ↓
[저장] button click — assertion 통과 후에만 (R57)
  ↓ 2.5s wait
패널 닫힘 verify → 영구 저장 완료
```

### V4 DOM 셀렉터 표

| 위치 | Selector | 비고 |
|------|----------|------|
| 검색 input | `input[placeholder*="포지션"]` 또는 `[placeholder*="생성자"]` | React-safe setter + Enter trigger 필수 |
| 카드 | `.position_card` (검색 후 visible) | h2/h3 textContent 로 정확 매칭 |
| 카드 title | `h2, h3, [class*="title"]` (카드 안) | textContent === EXPECTED_TITLE |
| 점3개 button | `button:has(svg)` (카드 안, ~28x28, aria-label "포지션 옵션 레이어 열림") | textContent 'XXXX'=='' 조건 X — aria-label 텍스트 통과 허용 |
| 메뉴 item "포지션 수정" | portal (document.body 끝). 점3개 좌표 proximity 매칭 | LI/DIV click 무효 → 내부 button click 필수 |
| 패널 제목 | `h2/h3` "포지션 수정" | 패널 OPEN 검증용 |
| **포지션명 (assertion)** | `input[name="hiringTitle"]` 또는 `input[id="position_title"]` | **★ R55 — value === EXPECTED_TITLE 검증 필수** |
| 제안 내용 | `textarea[name="offerComment"]` 또는 `textarea[id="position_content"]` | 한도 2,000자 |
| 업무 내용 | `textarea[name="chargeWork"]` 또는 `textarea[id="work_content"]` | 한도 2,000자 |
| 저장/취소 | `button` textContent === "저장"/"취소" (visible) | 저장은 assertion 통과 후에만 |

### V4 본문 구성 (사장님 명시 2026-05-25)

#### 제안 내용 (~500~700자, **블릿 구조 필수**)
1. 인사 (1~2줄)
2. **[회사 소개]** 블릿 — 미션 / 운영 서비스 / 투자 / **매출(필수)** / **인원(필수)** / 글로벌 / 이번 포지션 소속 부서·성과
3. **[근무 조건]** 블릿 — 고용 형태 / 근무지 / 연봉·스톡옵션
4. CTA 고정 문구 — `수락해주시면 조금 더 상세한 내용을 설명드려보고 싶습니다. 편히 수락 부탁드립니다.`

#### 업무 내용 (~800~1,500자, **원본 raw 그대로 보존**)
| 섹션 | 출처 | 규칙 |
|------|------|------|
| [담당 업무] | jobkorea raw `jd_main_duties` | 원본 어미(`-습니다`) 유지, 압축 금지 |
| [자격요건] | jobkorea raw `jd_qualifications` | 원본 그대로 |
| [우대사항] | jobkorea raw `jd_preferred` | 원본 그대로 |
| [복리후생] | jobkorea raw `jd_benefits` | unified.jsonl 변환 시 누락 (QA-253) |
| [전형 절차] | jobkorea raw `selection_process` | unified.jsonl 변환 시 누락 (QA-253) |

---

## R52: 카드 점3개 button selector — aria-label 텍스트 통과 허용

- 사람인 talent-pool 카드 점3개 button 은 `aria-label="포지션 옵션 레이어 열림"` 텍스트가 button textContent 에 포함됨 (visually hidden).
- `textContent.length < 3` 조건 너무 엄격 — fail. **올바른 조건**: `svg 포함 + boundingBox 12~50px 정사각형 + offsetWidth > 0`. textContent 무시.
- R52: 카드 점3개 selector = `button:has(svg)` + boundingBox 12~50px + (text === '' OR /옵션\s*레이어|more|menu|메뉴/.test(text))

---

## R53: 메뉴 item — portal + 점3개 좌표 proximity 매칭 필수

- 사람인 talent-pool 카드 점3개 click 시 메뉴는 **portal 로 body 끝에 떠 있음** (카드 안 X). 모든 카드 의 메뉴 element 가 hidden state 로 DOM 존재.
- `document.body` 전체에서 `textContent === '포지션 수정'` 만으로 매칭하면 **wrong card 의 메뉴 항목 click** 위험 (V1 사고).
- **R53**: 매 사이클 점3개 button 의 `getBoundingClientRect()` 좌표 기록 (`window.__vhDotRect`) + 메뉴 item 좌표가 `Δy < 300 && Δx < 250` 안인 것만 선택.

---

## R54: LI/DIV menu item click 무효 — 내부 button.click() + mousedown/up dispatch 필수

- 메뉴 item 의 visible 후보 중 `<LI>` 또는 `<DIV>` 만 매칭되는 경우 `el.click()` 효과 없음 (사람인 React onClick 이 내부 button 에 binding).
- **R54**: tag 우선순위 `BUTTON > A > LI > DIV > SPAN`. LI/DIV 가 1위면 `el.querySelector('button, a, [role="menuitem"]')` 로 내부 clickable element 찾아 click. `mousedown` + `mouseup` + `click` 모두 dispatch.

```js
const target = items[0];
const inner = target.querySelector('button, a, [role="menuitem"]');
if (inner && !['BUTTON','A'].includes(target.tagName)) target = inner;
target.dispatchEvent(new MouseEvent('mousedown', opts));
target.dispatchEvent(new MouseEvent('mouseup',   opts));
target.click();
```

---

## R55: ★ 패널 OPEN 후 hiringTitle assertion 필수 — wrong card 저장 방지 핵심

- 점3개 click + 메뉴 click 후 우측 슬라이드 패널이 열렸을 때, 패널의 `input[name="hiringTitle"].value` 가 **사용자가 의도한 포지션명과 정확히 일치**하는지 assertion 필수.
- 불일치 시 즉시 [취소] click + abort. **fill 금지, 저장 절대 금지**.
- V1 사고 (2026-05-25): 검색 후 카드 매칭이 부정확해 [AX Team] Agent Developer 의 수정 패널에 뤼튼 본문 fill — [저장] 직전 발견 + [취소] 로 데이터 오염 회피.

```js
if (panelCheck.hiring_title_value !== EXPECTED_TITLE) {
  await page.evaluate(() => Array.from(document.querySelectorAll('button')).find(b => b.offsetWidth > 0 && (b.textContent || '').trim() === '취소')?.click());
  throw new Error(`R55 — wrong panel expected="${EXPECTED_TITLE}" got="${panelCheck.hiring_title_value}"`);
}
```

---

## R56: 패널 OPEN retry 6×500ms — animation 대기

- 메뉴 click 후 패널 등장까지 animation 시간 필요. 한 번에 verify 하면 `input[name="hiringTitle"]` null.
- **R56**: 매 500ms 마다 verify, 최대 6회 retry (3초). `hiring_title_value` 비어있지 않으면 break.

---

## R57: [저장] click 전 assertion + 길이 검증 필수

- batch 모드에서 record 마다 [저장] 자동 click 시 — R55 assertion + textarea 길이(offer/duties 각 100자 이상) 검증 후에만 click. 미달 시 [취소] + abort.
- `tools/saramin-bulk-register-from-jobkorea/click-save-with-assertion.mjs` 표준 패턴.

---

## 변경 이력

- **2026-05-25 (V4 포지션 수정 패널 라이브 검증 — talent-pool/main/candidate-manage)** — 어제 V3 batch 76건은 회사명+포지션명만 등록되어 본문(회사 브리핑·JD·복리후생·전형)이 비어있었음(QA-252). 사장님 명시 흐름: `talent-pool/main/candidate-manage` → 검색 → 카드 점3개 → [포지션 수정] → 우측 슬라이드 패널 textarea 2개 fill → [저장] = **포지션 마스터 영구 저장**. **§10.V4 섹션 + R52~R57 신설**. R52(점3개 selector·aria-label) / R53(menu portal + 점3개 좌표 proximity 매칭) / R54(LI/DIV click 무효 → 내부 button + mousedown/up dispatch 필수) / R55(★ 패널 OPEN 후 `input[name="hiringTitle"].value` assertion 필수 — wrong card 저장 방지 핵심) / R56(패널 OPEN retry 6×500ms — animation 대기) / R57([저장] click 전 assertion + 길이 검증 필수). QA-252/253/254 등록. 첫 라이브 검증 — 뤼튼 AI Engineer (크랙·AI스토리·컨텍스트엔지니어링) 포지션 마스터 본문 저장 성공 (제안 549자 + 업무 806자). 산출물: `tools/saramin-bulk-register-from-jobkorea/{fill-position-master-one-v2,click-save-with-assertion}.mjs`.

- **2026-05-23 (V3 batch 일괄 등록 라이브 검증)** — cache 41건 → 36건 신규 등록 0 fail 완전 자동 (사장님 명시 — 사람 개입 0). **§10.V3 포지션 풀 일괄 등록 batch 섹션** + **R46~R51 신설**. R46(hiring stale freeze) / R47(별도 SSO + chrome saved password auto-login) / R48(modal query 무력 → button click 필수) / R49(listbox scroll + close-click 금지 = alternating fail 원인) / R50(verify batch 끝에서만) / R51(offerCompanyNm silent fail = 정상). QA-249/250/251 등록. 산출물: `tools/saramin-bulk-register-from-jobkorea/{auto-login,register-batch,register-one}.mjs`.
- **2026-05-23** — R39(자동화 상황 "손수" 금지) + R40(native alert freeze 해법) + R41(검색 버튼 필수 click) + R42(Product Engineer 포지션명 매핑 재확인) + R43(listbox+textarea 순서) + R44(한글명 검증 강화) + R45(batch cycle 최소화) 추가. 2026-05-23 batch 자동화 새로운 lessons 영구화.
- **2026-06-18** — §S (다중 키워드 검색 시나리오 플래닝 엔진) 신설. 사장님 명시: "소수정예 정밀 키워드, 결과 적으면 즉시 다음 시도, 지체 없이 빠르게." SQL·Query·RDB·dbt·Airflow·FinOps·IR 키워드 매트릭스 포함.

---

## §S. 다중 키워드 검색 시나리오 플래닝 엔진 (2026-06-18 사장님 명시)

> "여러 차례 검색 시도를 하기 위해서 다채로운 검색 시나리오가 필요하다. 결과 리스트에 몇 명 없으면 빠르게 다른 시도를 하도록 하고 이 과정은 지체 없이 빠르게 이뤄져야 한다."

### §S-0. 이 채널(사람인)의 적용 컨텍스트

- 사람인 인재풀 검색 화면에서 매 시나리오를 순서대로 실행한다.
- 결과 판단은 `span.list_count` 또는 `총 N명` 텍스트로 즉시 읽는다.
- 딜레이: 시나리오 간 4~15초 랜덤 (human-pacing, SOT S0.5).
- NOT 박스(`프리랜서`, `신입`, `인턴`)는 매 시나리오마다 반드시 유지.

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
6. **NOT 박스 고정**: `프리랜서`, `신입`, `인턴` — 매 시나리오마다 기본 입력 (제외 대상)

### §S-2. 결과 수 즉시 판단 의사결정 트리

```
키워드 입력 → span.list_count 즉시 읽기
      │
      ├─ 0~4명  → [즉시 포기] 다음 시나리오 (대기 0초)
      │
      ├─ 5~80명 → [GOLD] 전수 처리
      │             ① 프로필 무조건 저장 (R6)
      │             ② 이직잦음·프리랜서 제외 (AC-9 기준)
      │             ③ dedup 후 통합 pool에 추가
      │
      ├─ 81~300명 → [부분 처리] 상위 40명 (추천순 2페이지)만
      │              → 처리 완료 후 다음 시나리오
      │
      └─ 300명+  → [AND 재시도] AND 키워드 1개 추가
                    예: OR="SQL" 결과 1,200명 → AND="Finance" 추가
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

### §S-4. 이직잦음·프리랜서 제외 판단 기준 (R5 확장)

**이직잦음 판단**: 최근 5년 내 1년 미만 재직 2회 이상 → 제외 (저장 금지)

```javascript
function hasFrequentJobChange(careerPath) {
  const recentShortStints = careerPath.filter(job => {
    const months = parseMonths(job.period);
    const isRecent = isWithin5Years(job.endDate);
    return months < 12 && isRecent;
  });
  return recentShortStints.length >= 2;
}
```

**프리랜서 판단**: 프로필에 "프리랜서", "freelance", "개인사업자" 명시 → 제외

**두 조건 모두 해당 시 → 저장하지 않고 로그만 남긴다.** (R6 예외 — 이 경우만 저장 건너뜀)

### §S-5. 시나리오 실행 루프 (Playwright 패턴)

```javascript
async function runScenarioEngine(jd, page) {
  const scenarios = buildScenarios(jd); // §S-3 매트릭스 기반
  const pool = new Map(); // profile_url → candidate (dedup)
  const log = [];

  for (const s of scenarios) {
    // 1. 빠르게 검색박스 초기화 후 키워드 입력 (clipboard paste 패턴)
    await clearSearchFilters(page);
    await inputKeywordClipboard(page, s.orKeywords.join(' '));
    if (s.andKeyword) await inputAndKeyword(page, s.andKeyword);
    // NOT 박스: 프리랜서, 신입, 인턴 항상 입력
    await inputNotKeywords(page, ['프리랜서', '신입', '인턴']);

    // 2. 결과 수 즉시 확인 (대기 없이)
    const count = await getResultCount(page); // span.list_count
    log.push({ id: s.id, keywords: s.orKeywords, andKeyword: s.andKeyword, count });

    // 3. 즉시 판단 — 지체 없이
    if (count < 5) {
      console.log(`[S${s.id}] ${s.orKeywords} → ${count}명 — 즉시 포기`);
      await randomDelay(2, 4); // 최소 딜레이 후 다음
      continue;
    }

    if (count > 300) {
      // AND 재시도
      const fallback = s.narrowFallback || '재무';
      await inputAndKeyword(page, fallback);
      const newCount = await getResultCount(page);
      if (newCount < 5 || newCount > 300) {
        console.log(`[S${s.id}] AND 재시도 후 ${newCount}명 — 포기`);
        continue;
      }
    }

    // 4. GOLD 처리
    const limit = count <= 80 ? count : 40;
    console.log(`[S${s.id}] ${s.orKeywords} → ${count}명 — GOLD 처리 (${limit}명)`);

    const candidates = await collectCandidates(page, limit);
    for (const c of candidates) {
      if (pool.has(c.profile_url)) continue;
      if (hasFrequentJobChange(c.careerPath) || c.isFreelancer) continue;
      pool.set(c.profile_url, { ...c, scenario: s.id });
    }

    // 5. 시나리오 간 human-pacing (4~15초)
    await randomDelay(4, 15);
  }

  return { candidates: Array.from(pool.values()), log };
}
```

### §S-6. 일반 포지션 시나리오 생성 규칙

Finance/Data 외 다른 포지션에서도 동일 패턴 적용:

1. **P1 정밀**: 직무명 그대로 → 영문 직무명 → 핵심 도구/자격증 (예: CFA, SQLD)
2. **P1 정밀**: JD 내 "필수 조건"에 등장한 기술 키워드 하나씩
3. **P2 중간**: 우대사항 키워드 하나씩 + 직무 도메인 AND
4. **P3 광범위**: 직무 상위 카테고리 (예: "재무분석", "경영관리")

**규칙**: 절대로 키워드를 하나만 쓰지 않는다. 10개 미만의 시나리오라면 JD를 더 꼼꼼히 분해한다.

### §S-7. 완료 보고 형식

```
🟢 사람인 시나리오 플래닝 완료 — {포지션명}

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
  S1 FP&A: 42명 → GOLD 전수
  S2 Finance Data Analyst: 12명 → GOLD 전수
  S3 SQL+Finance: 28명 → GOLD 전수
  S4 Query+재무분석: 7명 → GOLD 전수 ⭐
  S5 dbt: 4명 → 즉시 포기
  S6 Airflow+Finance: 9명 → GOLD 전수 ⭐
  ...
```
