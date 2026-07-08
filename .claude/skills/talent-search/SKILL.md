---
name: talent-search
description: 사장님이 자주 쓰는 4개 채용 사이트의 인재 검색 URL과 필터 입력 워크플로우. 사람인/잡코리아/LinkedIn Recruiter(RPS)/ChatGPT/Claude.ai에서 후보자 찾을 때 사용. 자동화 워커가 일반 검색 URL(채용공고 풀)을 잘못 호출하지 않도록 정확한 talent pool URL과 필터 순서를 명시. "인재 검색", "talent search", "후보자 찾기", "사람인 잡코리아 링크드인" 키워드 트리거.
---

# 인재 검색 (Talent Search) URL & 필터 워크플로우

사장님이 매번 헷갈리지 않도록 4개 채널의 **정확한 인재 검색 URL** 과 **필터 입력 순서** 를 고정.

## 절대 규칙 (사장님 2026-05-21 명시)

1. **인재 검색 ≠ 채용공고 검색** — 통합검색 / `search?searchword=...` 같은 일반 검색 URL은 후보자 풀이 아니라 공고 풀이라 0명 나옴.
2. **필터를 차분히 하나하나 입력** — 키워드 → 직무 → 경력 → 지역 → 학력 순서로 천천히. 한 번에 모두 URL에 박지 말 것.
3. **인증/캡차 요청 시 자동화 즉시 stop** — 사람이 통과시킬 때까지 절대 자동화 액션 추가 금지.
4. **사람이 chrome 개입할 때는 가만히 있을 것** — 사장님이 직접 로그인·캡차·필터 입력 중에는 자동화 action 0. (그 시점에 chrome 자동화 띄우면 충돌·세션 깨짐.)
5. **인재DB 라이선스 필요** — 사장님 계정이 헤드헌터/기업 회원이어야 인재검색 진입 가능. 라이선스 없으면 fail.

## 4개 채널 인재 검색 URL (사장님 화면 캡처로 확인)

### 1. 사람인 (인재풀)
- URL: `https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search`
- **🔥 한 턴 전체 워크플로우(8단계 + 85점 자동발송 게이트 + R6 프로필 무조건 저장)는 별도 스킬 → [`saramin-talent-sourcing`](../saramin-talent-sourcing/SKILL.md)**
- 입력 구조:
  - 상단 키워드 박스 3개: **OR** (하나 이상의 키워드 포함) / **AND** (키워드를 모두 포함) / **NOT** (제외할 키워드)
  - AI 추천 검색어 (사이트가 자동 제안)
  - 빠른 필터 칩: 대기업/코스닥/코스피/국내 유명대학/인서울 대학/평균 근속 3년/최근 제안 많이 받음/요즘 뜨는 인재/적극 구직 중
  - 좌측 필터: 스페셜 태그, **경력 (선택~선택 년)**, 지역, 직무, **학력 체크박스 (고등학교/대학 2,3년/대학 4년/석사/박사)**, **연봉 범위 (최저~최고)**, 재직/구직 (체크박스), 기업 규모
- 결과 카드: 이름OO · N세 · 경력 N년 N개월 / 회사 · 부서 · 직책 / 학교(졸업) / 스킬 태그 / **후보자 저장** · **이직 제안하기** 버튼

### 2. 잡코리아 (인재검색)
- URL: `https://www.jobkorea.co.kr/corp/person/find`
- **🔥 한 턴 전체 워크플로우(20단계 + 85점 자동발송 게이트)는 별도 스킬 → [`jobkorea-talent-sourcing`](../jobkorea-talent-sourcing/SKILL.md)**
- 입력 구조:
  - 상단: **통합검색 ▼** / 키워드 자유 입력 / **직무·스킬 ▼** / **지역 ▼** / **상세검색 ▼** / 검색조건 불러오기 ▼
  - 좌측 필터: **경력 (☐신입 + N~N년 입력 + 해외 근무 경험 포함 체크박스)**, 나이/성별, 구직 상태, 이력서 업데이트일, 입사 지원일, 최근 활동일, 제안상품 적용 여부, 평균 근속년수, 기업 규모, 선호 조건
- 결과: "TOP 인재" 카드 (이름OO · (남/여, 만N세) · NN년N개월 / 회사 · 직군 / 스킬 태그 / # 요즘 뜨는 인재 · # 다른 기업이 많이 찾음 · # 최근 구직 활동)

### 3. LinkedIn Recruiter (RPS — Recruiter Pipeline Search)
- URL: `https://www.linkedin.com/talent/home`
- 라이선스: **Value Connect Recruiter 계정** 필수 (일반 LinkedIn 계정 X)
- 진입 후:
  - 홈에서 **"Get started by typing anything here"** 자연어 검색 박스
  - 또는 **Projects** 탭 → 기존 프로젝트 진입 → 그 안에서 검색·InMail
  - AI 추천 예시: "Show me Global Business Managers who know International Expansion", "Find me Cloud Infrastructure Engineers with Kubernetes expertise"
- 결과: candidates / InMails sent / InMails accepted 통계 + 후보자 카드

### 4. ChatGPT / Claude.ai (AI 검색 채널)
- ChatGPT 후보자추천 프로젝트 (사장님 본인 프로젝트): `https://chatgpt.com/g/g-p-68c22af4c45081919e206acb134b71b0-hubojacuceon/project`
- Claude.ai 신규 대화: `https://claude.ai/new`
- **단일 탭 / 사장님 직접 붙여넣기** (자동화 멀티탭 금지 — Cloudflare/계정 리스크. 2026-05-17 정책)
- 프롬프트 첫 줄에 `[AI-SEARCH] {회사} / {포지션} / {YYYY-MM-DD HH:MM}` 마커 필수
- Claude.ai 는 "이 작업은 실시간 웹 검색입니다. 학습 데이터만으로는 안 됩니다" 강화 문구 추가

## 필터 입력 순서 (사람인·잡코리아 공통, 차분히 단계별)

1. **키워드 1~3개** (간단히, "5년 이상" 같은 부가 텍스트 제외)
2. **직무 카테고리** (드롭다운에서 선택, 자유 입력 X)
3. **경력 년차 범위** (예: 3~10년)
4. **지역** (예: 서울 전체)
5. **학력** (체크박스 다중 선택)
6. **(선택) 연봉, 재직/구직, 기업 규모**
7. **검색 버튼 클릭**

각 단계 사이 **1~2초 wait**. 한 번에 너무 빠른 입력 → 봇 검출.

## 자동화 워커가 지켜야 할 행동

| OK | 금지 |
|----|------|
| ✅ 위 정확한 talent pool URL로 진입 | ❌ 일반 검색 URL (`search?searchword=`) 사용 |
| ✅ JD 본문에서 필터 값 추출 후 단계별 입력 | ❌ 포지션 제목 그대로 검색 박스에 박기 |
| ✅ Cloudflare / "Please verify you're a human" / 로그인 리다이렉트 감지 시 즉시 stop | ❌ 봇 검출 후 retry — 계정 잠금 위험 |
| ✅ 사람이 인증 진행 중에는 chrome 조작 0 | ❌ 사람 작업 중 자동화 액션 끼어들기 |

## 관련 파일

- 사람인 워커: `tools/saramin-sourcing/`
- 잡코리아 워커: `tools/jobkorea-sourcing/`
- LinkedIn 워커: `tools/linkedin-sourcing/`
- ChatGPT/Claude.ai 단일탭 흐름: `chatgpt-position-sourcing` 스킬 + `/kanban` PeekView "🚀 AI Search 실시하기" 버튼
- 디스코드 알림 헬퍼: `tools/ai-search-shared/src/discord-notify.ts`
- 프로필 아카이브: `tools/profile-archiver/`

## AI Search 프로세스 정례화 (2026-05-21 사장님 명시)

자동화 워커가 "키워드 N개 한 번에 박아 넣기" 식으로 일하면 검색 0명 또는 14,649명처럼 무의미한 결과가 나옴. 다음 5단계를 반드시 지킬 것 (사장님 명시: "AI Search 프로세스 돌릴 때 나올 수 있는 빈번한 문제").

### 1) JD 맥락 분석 체크리스트 (키워드 추출 전)

JD 본문을 5축으로 분해 — 각각 OR/AND/NOT 어디로 보낼지 결정:

| 축 | 예시 | 매핑 |
|----|------|------|
| **산업** | F&B / QSR / 외식 / 프랜차이즈 / SaaS / 게임 / 핀테크 | **AND** (필수 도메인 한 개만 골라 좁히기) |
| **직무** | 브랜드 마케팅 / Brand Manager / IMC / 그로스 | **OR** (직무 동의어 묶음) |
| **스킬·툴** | Tableau / Adjust / Figma / SQL | 너무 많으면 우선 1~2개만 OR |
| **경력** | 8~12년 | 좌측 combobox |
| **제외** | 신입 / 신졸 / 인턴 | **NOT** (필요 시) |

핵심: **AND 키워드 1개**만으로 결과가 보통 90% 좁아짐. 너무 specific한 AND 여러 개는 결과 0명 만듦.

### 2) 검증된 사람인 입력 절차 (2026-05-21 라이브 확인)

```
[step 1] ref_34 (검색 박스 초기화 버튼) click          ← 이전 검색 잔재 제거 (사장님 이전 검색 자동 복원됨)
[step 2] ref_19 (OR 입력 박스) click                  ← focus
[step 3] javascript_tool: navigator.clipboard.writeText("키워드")
[step 4] computer: key "cmd+v"                        ← 한국어 자모 timing 우회
[step 5] computer: wait 2초
[step 6] computer: key "Return"                       ← chip 등록 (필수)
[step 7] (AND) ref_21 click → step 3~6 반복
[step 8] (NOT) ref_23 click → step 3~6 반복
[step 9] 경력 ref_39 form_input "8" / ref_40 form_input "12"
[step 10] 검색 버튼 ref_24 click ← ★사장님 컨펌 후★ (라이선스 1회 차감)
```

**금지 패턴 (실패 확인됨)**:
- ❌ `form_input ref_19 value="한국어"` — 빈 값 들어감 (사람인은 keyboard event만 받음)
- ❌ `computer type "여러 한국어 단어"` — 자모/공백 소실, 모든 단어 한 chip에 붙어 검색 0명
- ❌ `setNativeValue` + dispatchEvent — 사람인 plain DOM 이지만 핸들러 미동작
- ❌ Enter 안 누르고 검색 — chip으로 안 들어가서 검색 안 됨

### 3) 결과 수 모니터링 (사람인 빠른 필터 chip 수치)

검색 박스 채운 직후 자동 표시되는 chip 수치 (`국내 유명 대학 N+`, `평균 근속 3년 N+` 등) 로 결과 수 즉시 판단:

| 빠른 필터 수치 | 의미 | 다음 행동 |
|--------------|------|----------|
| **10,000+** | 너무 광범위 | AND 키워드 1개 추가 |
| **1,000~5,000** | 여전히 많음 | AND 추가 또는 빠른 필터 클릭 (적극 구직 중 등) |
| **100~500** | 적절 | 검색 버튼 click |
| **0~50** | 너무 좁음 | AND 1개 빼거나 다른 산업 키워드로 |
| **0** | AND 조건 모순 | AND 키워드 재검토 |

### 4) 검증 체크리스트 (검색 버튼 누르기 전)

- [ ] OR 박스에 정확한 직무 키워드 chip (공백 살아있음)
- [ ] AND 박스에 산업 키워드 1개 chip
- [ ] NOT 박스에 제외 키워드 (필요 시)
- [ ] 경력 combobox 정확한 범위
- [ ] 학력 체크박스 (default 그대로 OK)
- [ ] 빠른 필터 수치 100~500 수준
- [ ] (선택) `평균 근속 3년` / `적극 구직 중` / `요즘 뜨는 인재` 빠른 필터 click

### 5) 잡코리아 / LinkedIn Recruiter 적용 (학습된 패턴)

- 한국어 입력: 동일하게 **clipboard + cmd+v + Enter** 패턴
- 단일 입력 박스 + chip 추가 (사람인 동일) 인지 확인 필요
- LinkedIn 은 자연어 검색 박스 — clipboard paste 그대로 적용 가능
- 잡코리아: 통합검색 ▼ / 직무·스킬 ▼ / 지역 ▼ / 상세검색 ▼ 드롭다운별 진입 필요

### 6) 사장님 명시 절대 규칙 (반복)

- 검색 버튼 click 전 사장님 컨펌 (라이선스 차감)
- 사람이 chrome 개입 시 자동화 action 0
- 봇 검출 즉시 stop + OPS_INCIDENTS 디스코드 알림
- 키워드 chip 사이 1~2초 wait
- 잘못된 chip으로 검색 누르지 말 것

## 변경 이력

- 2026-05-21 — 사장님이 화면 캡처로 4개 사이트 정확한 URL 알려주심. 그 전 워커들은 일반 통합검색 URL을 호출해서 0명 / FAIL.
- 2026-05-21 — 사람인 인재풀 입력 절차 라이브 검증 + 정례화 5단계 추가. "AI Search 프로세스 빈번한 문제" 정의 (키워드 1개 = 광범위, AND로 좁히기, 결과 수 모니터링).
