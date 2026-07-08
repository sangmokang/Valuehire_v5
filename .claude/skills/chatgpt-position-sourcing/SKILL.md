---
name: chatgpt-position-sourcing
description: 사장님이 "/kanban 의 고객사 포지션에 대해 ChatGPT 후보자추천 프로젝트로 AI Search 돌려줘", "이 포지션에 적합한 후보자 찾아줘", "AI Search 결과 등록", "ChatGPT 매칭 후보 채워줘", "포지션 ChatGPT 매칭" 같은 요청을 하실 때 사용. /kanban?board=FY26_Clients 포지션 PeekView 의 "AI Search 실시하기" 버튼 → ChatGPT 후보자추천 프로젝트 → 결과 가져오기 모달 흐름을 책임지고 끝까지 마무리. LinkedIn/Notion/GitHub/Scholar/공개 웹 5채널 결과를 사이드바 + 후보자 칸반 "AI Search" 컬럼 양쪽에 등록.
---

# ChatGPT 후보자추천 프로젝트 AI Search (포지션 기반)

## ⚡ R0 — AI Search 시작 = /position 자동 호출 (사장님 명시 2026-06-19)

이 AI Search(후보 소싱)를 **시작하는 즉시**, 같은 포지션을 `/position` 스킬로 **사람인·잡코리아·LinkedIn 3사에 JD 등록까지 병행**한다. 소싱(후보 찾기)과 등록(포지션 올리기)은 같은 포지션의 양면이므로 한 번에 처리한다.
- 호출: 동일 포지션(ClickUp task / URL / JD)을 `/position` 에 넘긴다. 3사 등록은 발송이 아니라 등록까지만(`/position` P0 — 발송 금지).
- 웹 진입은 빠르게: `/position` §1 raw CDP 단일탭(사장님 9222 탭 과다 → connectOverCDP hang 회피). 시행착오는 §1-R 순서로 빠르게 전환.

## 언제 발동하는가

다음 같은 요청이 들어오면 즉시 발동:

- "이 포지션으로 AI Search 돌려줘"
- "ChatGPT 매칭으로 후보자 찾아"
- "/kanban 의 ㅇㅇㅇ 포지션에 적합한 사람"
- "AI Search 결과 등록해줘"
- "포지션 ChatGPT 매칭"
- "후보자추천 프로젝트로 검색"

## 🔥 R11 — 사용자별 ChatGPT 프로젝트 URL 라우팅 (사장님 명시 2026-05-26)

AI Search 실행 시 **현재 로그인된 ChatGPT 계정(이메일)** 기준으로 다른 프로젝트 URL 사용:

| 사용자 | 프로젝트 URL | 비고 |
|--------|------------|------|
| **sangmokang@valueconnect.kr** | `https://chatgpt.com/g/g-p-68c22af4c45081919e206acb134b71b0-hubojacuceon/project` | 사장님 — 기존 URL 유지 |
| **kcs / julian / rogan @valueconnect.kr** | `https://chatgpt.com/g/g-p-6a14d0354c6881918f8a772bcb51cd3b-ai-search/project` | 내부 팀 3명 — 별도 프로젝트 |
| **B2B 다른 고객사 (밸류커넥트 외 회사)** | **절대 ChatGPT 흔적 노출 금지** | UI/Discord/이메일 모든 라벨에서 "ChatGPT" "AI Search" 단어 ChatGPT 출처 노출 X — `ai_assessment` 같은 일반 표현만 |

### R11-1 라우팅 적용 위치

| 위치 | 적용 방법 |
|------|----------|
| `tools/chatgpt-sourcing/.env` | `CHATGPT_PROJECT_URL` 사용자별 분기 — env override 또는 user 매핑 룰 |
| `tools/chatgpt-sourcing/src/chatgpt.ts` `cli.ts` `batch.ts` `match/index.ts` | startUrl 결정 시 사용자 이메일 확인 → 매핑 |
| MCP claude-in-chrome 수동 흐름 | 시작 시 ChatGPT 우상단 계정 이메일 확인 → 올바른 프로젝트 URL 강제 |
| B2B 고객사 화면 (admin.valuehire.cc 외부 노출) | source 필드 `ai_search` 로 정규화 (QA-199 기존 정책 유지) |

### R11-2 검증 절차 (모든 실행 전 의무)

```javascript
// 실행 전 chrome 우상단 프로필 click → 이메일 확인
const accountEmail = document.querySelector('[data-testid*="account"]')?.textContent?.match(/[\w.-]+@[\w.-]+/)?.[0];

// 라우팅
const URL_MAP = {
  "sangmokang@valueconnect.kr": "https://chatgpt.com/g/g-p-68c22af4c45081919e206acb134b71b0-hubojacuceon/project",
  "kcs@valueconnect.kr": "https://chatgpt.com/g/g-p-6a14d0354c6881918f8a772bcb51cd3b-ai-search/project",
  "julian@valueconnect.kr": "https://chatgpt.com/g/g-p-6a14d0354c6881918f8a772bcb51cd3b-ai-search/project",
  "rogan@valueconnect.kr": "https://chatgpt.com/g/g-p-6a14d0354c6881918f8a772bcb51cd3b-ai-search/project",
};
const targetUrl = URL_MAP[accountEmail];
if (!targetUrl) throw new Error(`Unknown account: ${accountEmail}`);
```

### R11-3 B2B 고객 노출 금지 (QA-199 + 2026-05-26 강화)

B2B 고객사 화면 (admin.valuehire.cc 외부 노출 시) 절대 금지 표현:
- ❌ "ChatGPT 매칭"
- ❌ "AI Search by ChatGPT"
- ❌ "ChatGPT 후보자추천"
- ❌ "GPT-4 검증"
- ❌ source/channel 필드에 "chatgpt" 문자 노출

✅ 사용 가능 표현:
- "AI 검증 결과"
- "AI 매칭 점수"
- "AI 추천 후보자"
- source 필드 정규화: `ai_search` 또는 `ai_assessment`

`tools/chatgpt-sourcing/src/db.ts` `supabase.ts` 의 source insert 시 `ai_search:<channel>` 형태로 정규화하는 기존 로직 유지 — `ai_search:chatgpt` 같은 표현 금지.

---

## 🔥 R10 — 노이즈 채널·도메인 자동 배제 (사장님 명시 2026-05-25)

> "헤드헌터로서 컨택하기가 불가능한 후보자들도 많았는데 프리랜서로 크몽에서 강사를 하고 있는 사람은 시장과 관련이 없는 것이다... 차라리 링크드인, 깃헙, Notion Resume로 한정하는게 더 나아보인다."

### R10-1 채널 한정 (LinkedIn + GitHub + Notion Resume 만)

**기존 5채널** (linkedin/github/scholar/notion/web) **→ 3채널 한정**:
- ✅ **linkedin** — 헤드헌터 컨택 친화, InMail 가능, Open to Work 시그널
- ✅ **github** — 개발자 신원 검증, 이메일·블로그 공개 빈도 높음
- ✅ **notion** — 본인이 의도적으로 공개한 이력서·포트폴리오
- ⚠️ **scholar** — 학술 포지션(JD에 PhD·Research·Postdoc 명시)만 추가 허용
- ⚠️ **web** — 다음 3가지만 허용:
  - `<name>.github.io` GitHub Pages 개인 사이트
  - 본인 명의 도메인 (`<name>.com`, `<name>.dev`, `<name>.io`, `<name>.me` 등)
  - 회사 공식 employee page (`<company>.com/people/...`)
  - **rocketpunch.com** (한국 채용 사이트, 본인 공개 이력서) — semi-good

### R10-2 노이즈 도메인 절대 배제

다음 도메인의 URL 은 **추천 금지**:
- **프리랜서·강사 마켓플레이스**: `kmong.com`, `taling.me`, `class101.net`, `inflearn.com`, `udemy.com`
- **SNS**: `instagram.com`, `twitter.com`, `x.com`, `youtube.com/@`, `youtube.com/channel`
- **개인 블로그**: `brunch.co.kr`, `medium.com/@`, `velog.io`, `tistory.com`, `naver.com/blog`

### R10-3 프리랜서 자동 패스

`headline` 또는 `name` 에 다음 키워드 포함 시 즉시 배제:
- `프리랜서`, `Freelancer`, `외주`, `강사`, `Tutor`, `Coach`

### R10-4 is_contactable 필드 의무

각 후보자 JSON 에 `is_contactable: bool` + `contactable_reason: string` 필드 추가:
- LinkedIn 최근 90일 활동 / Open to Work 시그널 / GitHub 이메일 공개 / Notion 연락처 등
- `is_contactable=false` 후보자는 **출력 금지**

### R10-5 match_score 재구성 (100점)

- 학교 35점 + 이직 안정성 30점 + 직무 직결성 15점 + **컨택 가능성 20점**
- 컨택 가능성 세부: 활동 시그널 10 + 구직 의사 5 + 공개 연락처 5

### R10-6 1차 라이브 검증 (2026-05-25)

원본 144명 ChatGPT 결과 분석:
- **38명 (26%) 노이즈** 자동 배제
  - 프리랜서 키워드: Grace (91점, "프리랜서/마케팅 에이전시")
  - 학자 6명 (Scholar 채널, 50점대)
  - 공개 웹 신원 불분명: 오원우 90점 (`wonuoh.me`)
- **101명 (70%)** 헤드헌터 컨택 가능
- 5명 (3.5%) Rocketpunch (semi-good)

→ R10 적용 시 동일 prompt 재실행해도 노이즈 사전 차단됨.

### R10-7 신규 prompt 템플릿

[프롬프트 템플릿](#프롬프트-템플릿) v2 로 교체 (아래 §프롬프트 템플릿 참조).

---

## 사장님이 직접 설정한 정책 (2026-05-17)

1. **단일 탭만 사용**. 멀티탭 자동화(`tools/chatgpt-sourcing`)는 웹 부하 우려로 본 흐름에서는 사용하지 않음. 무조건 사장님이 직접 띄우는 ChatGPT 탭 한 개에서 검색.
2. **검색 진입 URL 고정**: `https://chatgpt.com/g/g-p-68c22af4c45081919e206acb134b71b0-hubojacuceon/project`
   - 사장님이 만든 후보자추천 GPT 프로젝트. 다른 ChatGPT 채팅 절대 사용 금지.
3. **시작부 마커 의무**: 프롬프트 첫 줄에 반드시
   `[AI-SEARCH] {회사} / {포지션} / {YYYY-MM-DD HH:MM}`
   형식의 마커. 사장님이 나중에 ChatGPT 프로젝트 히스토리에서 즉시 검색·재방문할 수 있어야 함.
4. **채널 5종**: linkedin, github, scholar, notion, web. 채널별 다른 데이터.
   - **linkedin** → `profile_url` 에 LinkedIn 프로필 URL. UI 에서 클릭 시 바로 LinkedIn 으로 이동 (Source: ChatGPT 흔적 노출 금지).
   - **github** → `profile_url` + `github_contacts {linkedin, blog, email, website}` 모두 채움. UI 가 4개 모두 별도 링크로 표기.
   - **scholar** → `profile_url` 에 Google Scholar.
   - **notion** → 공개 노션 페이지 URL.
   - **web** → 공개 레쥬메·블로그·기타 웹 페이지 URL. 빠짐없이 수확.
5. **모든 후보자 100점 만점 점수** + **"잘 맞는 점"(strengths) 3-5개** + **"안 맞는 점"(weaknesses) 1-3개** 필수.
6. **결과는 두 곳에 동시 적재**:
   - 포지션 PeekView 우측 "AI Search 후보자" 사이드바
   - 후보자 칸반(/kanban?board=FY26_Candidates 등) 의 **"AI Search" 컬럼** (최좌측, ClickUp 동기화 대상 외 staging)

## 워크플로우 (사장님 직접 실행 시)

1. /kanban?board=FY26_Clients 진입.
2. 대상 포지션 카드 클릭 → 풀폭 PeekView 열림.
3. 우측 상단 큰 그라데이션 버튼 **🚀 AI Search 실시하기 (ChatGPT 새 탭 + JD 자동 복사)** 클릭.
   - 프롬프트가 클립보드에 자동 복사됨.
   - ChatGPT 후보자추천 프로젝트가 새 탭으로 열림.
4. 새 탭에서 ⌘V 로 붙여넣고 전송.
5. ChatGPT 가 JSON 형식 응답을 반환 (```json``` 코드블록 있어도 OK).
6. ChatGPT 응답 전체 복사.
7. PeekView 로 돌아와 **📥 결과 가져오기 (ChatGPT 응답 JSON 붙여넣기)** 버튼 클릭.
8. 모달에 ⌘V 붙여넣고 "저장하기".
9. 사이드바 자동 갱신 + alert 로 "N건 등록" 확인.
10. /kanban?board=FY26_Candidates 로 가면 "AI Search" 컬럼에 후보자들이 점수순으로 정렬되어 있음.

## 🔥🔥 SOT — Claude 가 직접 실행한다 (사장님 명시 2026-06-01, 최우선)

> 사장님 명시: **"사람이 바쁘고 사람이 입력하는 데에서 큰 개발과 도전이 멈춰진다. 니가 직접 실행하는 방향으로 명기하란 말이야. 명심해."**

**기본값 = Claude 가 `claude-in-chrome` MCP 로 ChatGPT 단일 탭을 직접 조작해 처음부터 끝까지 자율 수행.** 사장님께 "프롬프트 복사해서 직접 붙여넣으세요" 식으로 떠넘기는 것은 **금지**(과거 "사장님 직접 실행" 정책은 폐기). 사람 입력 대기 = 병목 = 개발 정지.

### Claude 직접 실행 절차 (매 AI Search 의무)

1. **포지션 카드 ID 확인** — board+포지션명으로 `pipeline_position_cards` 조회(service role REST). 카드가 없으면 직접 적재(직접 INSERT)까지 한다.
2. **JD 본문 확보** — 카드 `jd_text` 또는 `/api/pipeline/position-cards/[id]` GET.
3. **프롬프트 생성** — [프롬프트 템플릿](#프롬프트-템플릿). 첫 줄 `[AI-SEARCH-V2]` 마커 필수. 직무 특성(개발 vs HW/세일즈 등)에 맞춰 채널·키워드 조정.
4. **MCP 로 직접 입력·전송** — `tabs_context_mcp` 로 ChatGPT 후보자추천 프로젝트 탭 확인(R11 계정 라우팅) → 입력창 클릭 → 프롬프트 입력(클립보드 `pbcopy`+⌘V 또는 `computer type`) → Enter 전송. **사람 손 개입 0.**
5. **응답 대기·수확** — 웹 검색 소싱은 수십 초~수 분. `computer wait`+`get_page_text` 폴링으로 생성 완료(정지버튼→전송버튼 전환) 감지 후 JSON 추출.
6. **칸반 자동 등록** — JSON 파싱 → `POST /api/pipeline/position-cards/[id]/ai-search` (또는 dev 미가동 시 `pipeline_candidates` 직접 INSERT: board=<prefix>_Candidates, stage=ai_search, source=ai_search:<channel>, ai_assessment 채움).
7. **사장님께는 결과만 가져온다** — "N명 등록 완료, 상위 후보 요약" 형태로 보고. 중간 입력을 시키지 않는다.

**폴백(아래 "사장님 직접 실행 시" 섹션)은 MCP 크롬이 끊겼거나 사장님이 명시적으로 본인이 하겠다고 할 때만.**

### 이게 "기억력" 문제의 해법 (Hermes 불필요)
사장님이 같은 지시를 반복하게 되는 건 Claude 기억 부재가 아니라 **이 SOT 파일·메모리에 안 박혔기 때문**. 본 SKILL(SOT) + `memory/feedback_*` 에 박으면 다음 세션부터 자동 적용된다. 별도 Hermes 영속메모리 어댑터 불필요. 관련 [[feedback_claude_code_direct_over_hermes_adapter]].

## 프롬프트 템플릿 (V2 — R10 적용, 2026-05-25)

```
[AI-SEARCH-V2] {회사} / {포지션} / {YYYY-MM-DD HH:MM}

# {회사} / {포지션} 후보자 매칭 검색 V2

당신은 채용 매칭 분석가입니다. 사장님 명시 2026-05-25 규칙에 따라 **헤드헌터 컨택 가능 후보자만** 추천하세요.

## 핵심 원칙 (절대 위반 금지)

1. **3채널 한정**: LinkedIn / GitHub / Notion Resume 만 사용. 다음 도메인 절대 추천 금지:
   - 프리랜서·강사 마켓플레이스: kmong.com, taling.me, class101.net, inflearn.com, udemy.com
   - SNS: instagram.com, twitter.com, x.com, youtube.com/@..., youtube.com/channel
   - 개인 블로그: brunch.co.kr, medium.com/@, velog.io, tistory.com, naver.com/blog
2. **프리랜서·강사 자동 배제**: headline/name 에 "프리랜서·Freelancer·외주·강사·Tutor·Coach" 포함 시 즉시 제외
3. **scholar 채널은 학술 포지션만** (JD 에 PhD·Research·Postdoc 명시된 경우만)
4. **web 채널 (공개 웹) 은 다음만 허용**:
   - `<name>.github.io` GitHub Pages 개인 사이트
   - 본인 명의 도메인 (`<name>.com`, `<name>.dev`, `<name>.io`, `<name>.me` 등)
   - 회사 공식 employee page
   - rocketpunch.com 은 OK (한국 채용 사이트, 본인 공개 이력서)

## match_score 정의 (100점 만점)

- 학교 (35점): 인서울 4년제 OR 지방 국공립대 졸업
- 이직 안정성 (30점): 각 직장 평균 근속 2년+
- 직무 직결성 (15점): JD 핵심 직무·스킬 매칭
- **컨택 가능성 (20점)**: LinkedIn 최근 90일 활동 +10 / Open to Work +5 / 공개 연락처 +5

⚠️ **컨택 불가 후보자 (is_contactable=false) 는 출력 금지**

## 채널별 수집 규칙

- **linkedin**: `linkedin.com/in/<username>` 형식. 회사·직책·경력 연도 명시.
- **github**: `github.com/<username>` 형식. 프로필 README, 언어·기술 스택, github_contacts (linkedin·blog·email·website) 모두 채움.
- **notion**: `notion.site/...` 또는 `<workspace>.notion.so/...`. 본인 공개 이력서·포트폴리오만.

## JD
{jd 본문}

## 출력 형식 (JSON only — 다른 설명 금지)

{
  "candidates": [
    {
      "name": "이름",
      "headline": "현재 직무 · 회사 (예: Senior PM @ Toss)",
      "channel": "linkedin | github | notion",
      "profile_url": "https://...",
      "is_contactable": true,
      "contactable_reason": "최근 LinkedIn 활동 / Open to Work / GitHub 이메일 공개 / etc.",
      "match_score": 0~100,
      "score_breakdown": { "school": 0~35, "stability": 0~30, "jd_fit": 0~15, "contactability": 0~20 },
      "summary": "한 줄 요약",
      "strengths": ["JD 잘 맞는 점 3~5개"],
      "weaknesses": ["JD 안 맞는 점 1~3개"],
      "github_contacts": { "linkedin": "...", "blog": "...", "email": "...", "website": "..." }
    }
  ]
}

⚠️ is_contactable=false 후보자 출력 금지
⚠️ kmong/taling/blog/instagram/twitter/youtube URL 출력 금지
⚠️ 프리랜서/강사/외주 키워드 후보자 출력 금지

채널별 5명 이상, 총 15명 이상 추천. JSON 만 출력하고 빠르게 응답해주세요.
```

## ⚠️ V1 → V2 변경 사항

| 항목 | V1 (2026-05-17) | V2 (2026-05-25) |
|------|----------------|-----------------|
| 채널 | 5개 (LinkedIn·GitHub·Scholar·Notion·Web) | 3개 (LinkedIn·GitHub·Notion) + 학술 포지션만 Scholar |
| 노이즈 도메인 | 명시 없음 | kmong·taling·blog·SNS 명시 배제 |
| 프리랜서 배제 | 명시 없음 | headline/name 키워드 자동 패스 |
| 컨택 가능성 | 점수 가중치 없음 | match_score 20점 가중치 |
| 신원 필드 | 없음 | `is_contactable` + `contactable_reason` |
| 점수 breakdown | 단일 점수 | 4축 세부 (school/stability/jd_fit/contactability) |

V1 결과 (2026-05-23 batch, 144명) 분석: 26% 노이즈, 70% good. R10 적용 시 노이즈 사전 차단.

## 데이터 흐름

```
ChatGPT JSON
   │
   ▼
POST /api/pipeline/position-cards/[id]/ai-search
   │
   ▼  INSERT into pipeline_candidates
      • board_id = "<prefix>_Candidates"  (Clients → Candidates 매핑)
      • stage = "ai_search"
      • source = "ai_search:<channel>"   (detectChannel 인식)
      • ai_assessment = { summary, strengths, weaknesses, profile_url, github_contacts, sourced_from_position_id, ingested_at }
   │
   ├─→ GET /api/pipeline/position-cards/[id]/ai-search  (PeekView 사이드바)
   └─→ /kanban?board=FY26_Candidates 의 "AI Search" 컬럼
```

## 관련 파일

- 버튼·모달·카드: `app/kanban/_components/ClientPositionPeekView.tsx`
- API GET/POST: `app/api/pipeline/position-cards/[id]/ai-search/route.ts`
- 후보자 칸반 컬럼 정의 (AI Search 최좌측): `app/kanban/_lib/boardConfig.ts` (CANDIDATE_COLUMNS)
- 마이그레이션: `supabase/migrations/20260517040000_candidates_board_ai_search.sql`
- 이슈 로그: `docs/engineering/qa/issue-log.md` QA-203~207

## 절대 하지 말 것

- ❌ ChatGPT 자동화 멀티탭 (Cloudflare/계정 리스크). `tools/chatgpt-sourcing` 멀티탭 모드는 본 흐름과 무관.
- ❌ "Source: ChatGPT" 또는 ChatGPT 흔적을 운영 화면에 노출. 사장님 정책 (QA-199).
- ❌ ai_search 컬럼을 ClickUp 동기화 대상으로 만들기. 로컬 staging 전용.
- ❌ 사장님 확인 없이 후보자 자동 삭제. 칸반에서 사장님이 직접 "제안(추천대기)" 로 드래그할 때까지 ai_search 컬럼에 보관.
