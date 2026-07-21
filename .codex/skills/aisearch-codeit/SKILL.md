---
name: aisearch-codeit
description: 코드잇(codeit, careers.codeit.com)을 타겟으로 한 AI Search 후보 소싱. 코드잇 채용 공고를 라이브로 순회·3계층 분류(부트캠프 강사 / 멘토 / 일반 실무)하고, 카테고리·역할별로 LinkedIn 딥링크 URL + 사람인·잡코리아 인재검색 입력 payload + 코드잇 경력 가중치(2~3년~10년 미만 우대) AI Search 프롬프트를 생성한다. 트리거 — "/aisearch_codeit", "aisearch codeit", "코드잇 AI Search", "코드잇 후보 찾아", "코드잇 포지션 소싱", "코드잇 강사/멘토/엔지니어 찾아줘". 범용 AI Search(chatgpt-position-sourcing)의 코드잇 특화 버전.
---

# /aisearch_codeit — 코드잇 타겟 AI Search

코드잇은 카테고리 분류가 매우 명확한 에듀테크 회사(부트캠프 강사·멘토·실무 3계층)다. 이 스킬은 코드잇 채용 공고를 **라이브로** 받아 분류하고, 카테고리/역할별 **인재검색 필터·프롬프트**를 한 번에 만들어 준다. 범용 흐름은 [`chatgpt-position-sourcing`](../../.claude/skills/chatgpt-position-sourcing/SKILL.md) · URL/필터는 [`talent-search`](../../.claude/skills/talent-search/SKILL.md)를 따른다.

## 한 줄 실행

```bash
# 카테고리/역할 목록 (네트워크 불필요)
node tools/aisearch-codeit/run.mjs --list

# 한 역할에 대한 채널 URL·payload·프롬프트 생성 (라이브 공고 fetch)
node tools/aisearch-codeit/run.mjs --category general --role "백엔드 엔지니어"
node tools/aisearch-codeit/run.mjs --category bootcamp_instructor --role "Spring 백엔드 부트캠프 강사"
node tools/aisearch-codeit/run.mjs --category mentor --role "프론트엔드 엔지니어 커리어 멘토"

# JSON 출력 (자동화 연계)
node tools/aisearch-codeit/run.mjs --category general --role "프로덕트 디자이너" --json
```

부작용 0: 읽기 전용 GET + 출력만. **발송·등록·자동입력 없음.** 실제 검색 버튼/제안 발송은 사장님 확인 게이트(라이선스 차감).

## 1. 코드잇 카테고리 (라이브 실측 — careers.codeit.com)

데이터 출처: `https://careers.codeit.com/ko/recruit` 의 `<script id="__NEXT_DATA__">` → `dehydratedState.queries[queryKey=["openings"]]`. 브라우저 User-Agent 필수(봇 UA는 403). 인덱스 하드코딩 금지(`queryKey[0]==="openings"` 로 find).

| 사장님 분류 | 코드잇 occupation/고용형태 | 예시 역할 |
|---|---|---|
| **bootcamp_instructor** (부트캠프/특강 강사) | Tech·Creative 프리랜서 "…강사" | 풀스택·Spring백엔드·AI엔지니어·데이터분석·웹퍼블리싱·프로덕트디자인·그래픽디자인·IT창업 강사 |
| **mentor** (멘토 & 파트너) | Mentor & Partner 프리랜서 | 부트캠프 멘토, 커리어 멘토(이력서코칭/모의면접), 텐엑스 전문가, 콘텐츠 파트너 |
| **general** (일반 실무) | 정규/계약/인턴 | 백엔드 엔지니어, 프로덕트 디자이너, 브랜드 마케터, 영상 PD, PM, 교육 PM, 교육행정 매니저, B2B 세일즈, 리크루터, 총무 |

분류 규칙(`categorize.mjs`): 멘토 우선 → 강사 → 일반. ("부트캠프 멘토"가 강사로 오분류되지 않게.) careerType 3종(EXPERIENCED/NEW_COMER 신입/NOT_MATTER 경력무관) 정규화.

## 2. 채널별 검색 필터 (라이브 검증된 계약)

### LinkedIn — 딥링크 가능 ✅ (단, public 검색은 단순 쿼리만)
- URL: `https://www.linkedin.com/search/results/people/?keywords=<Boolean>&geoUrn=["105149562"]&origin=FACETED_SEARCH`
- 한국 geoUrn = **105149562** (검증됨).
- Boolean: 대문자 AND/OR/NOT, 따옴표=정확구, 괄호=그룹.
- ⚠️ **라이브 교훈(2026-06-30)**: public 검색은 Boolean 복잡도에 상한이 있다. `6 OR + 6 tech OR + NOT` 또는 `6 OR + AND "Spring"(따옴표)` → **"결과 없음"(0명)**. `타이틀 OR 3개(한·영 혼합) + AND Spring(무따옴표)` → 실제 한국 후보 다수(CJ·롯데렌탈·카카오 출신). → `buildLinkedinPublicQuery` 가 이 단순 형태를 자동 생성. NOT·다중 AND·풀 Boolean 은 **Recruiter/Sales Nav 키워드 칸** 또는 사람인/잡코리아 박스에서.
- 경력 년차 필터: public 검색엔 URL 없음(Recruiter 전용) → 키워드(Senior/Lead, NOT junior) + 프롬프트 점수로 처리.

### 사람인 인재풀 — 딥링크 불가 (UI 입력 payload)
- base: `https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search` (기업회원 로그인 필수)
- payload: `{ or:[], and:[], not:[], careerFrom, careerTo, education }` — OR/AND/NOT **3개 박스**에 chip 입력(인라인 연산자 없음). 한국어는 clipboard+cmd+v+Enter.
- AND 1개로 ~90% 좁힘. 다중 AND = 0명. 검색 버튼은 사장님 확인 후.

### 잡코리아 인재검색 — 딥링크 불가 (UI 입력 payload)
- base: `https://www.jobkorea.co.kr/corp/person/find` (기업+서치펌 토글 ON)
- payload: 통합검색 박스모드(AND/OR/NOT chip) + 좌측 경력 패널 + 상세검색 학력. 제안 발송 = 1건 차감(사장님 확인).

## 3. 키워드 발굴 (한영·대소문자·띄어쓰기 변형)

`categoryKeywords.mjs` — 33개 역할 시드(워크플로우 도출). 각 역할에 `core_keywords`(백엔드/Backend/back-end/서버 개발자 …), `boolean_or`(직무 동의어), `boolean_and`(도메인/스킬 앵커), `boolean_not`(신입/인턴 제외), `tech_skills`, `linkedin_keywords_query`(Recruiter 풀 Boolean). 시드에 없는 역할은 `searchFilters.buildKeywordVariants(role)` 가 사전 기반으로 변형 생성.

## 4. 코드잇 경력 가중치 (사장님 명시 — 젊고 인재밀도 높은 후보 우대)

`codeitPrompt.buildCodeitAiSearchPrompt({ positionTitle, jdText, role, careerBand })` 가 생성하는 프롬프트는:
- **경력 2~3년 ~ 10년 미만** 후보에 최고 가중치(코드잇 선호 밴드).
- **10년 이상** 시니어·**2년 미만** 주니어 감점.
- 직무 적합성 + 학력(상위권/우수 배경) 반영, 위 경력 밴드 가중 최우선.
- `experience_years`/`experience_band`(under_2|2_to_3|3_to_10|over_10)/`codeit_fit_score` 필드 강제.
- 코드잇 현직자 배제 + 노이즈 도메인/프리랜서 자동 배제(R10 계열).

생성된 프롬프트는 ChatGPT 후보자추천 프로젝트(R11 계정 라우팅)에 입력하거나, `claude -p`(Max 0원)로 처리한다.

## 5. 전체 흐름 (한 카테고리 소싱)

1. `node tools/aisearch-codeit/run.mjs --category <cat> --role "<역할>"` → 채널 URL·payload·프롬프트 출력.
2. **LinkedIn**: 출력된 딥링크를 **로그인된 브라우저**로 연다 → 후보 확인. (프로필 저장은 `codeit-talent-archive-search` 스킬 + 프로필 아카이버 익스텐션.)
3. **사람인/잡코리아**: payload 의 OR/AND/NOT·경력·학력을 [`talent-search`](../../.claude/skills/talent-search/SKILL.md) §2 절차로 UI 입력. 검색 버튼은 사장님 확인.
4. **AI Search 프롬프트**: ChatGPT 후보자추천 프로젝트에 입력 → JSON 결과를 `chatgpt-position-sourcing` 흐름으로 칸반 적재.
5. 적합도 + 코드잇 경력 밴드 가중으로 정렬 → 사장님 검토.

## 절대 규칙

- **발송·등록·자동입력 자동 실행 금지** — URL/payload/프롬프트 생성까지만. 검색 버튼·제안 발송은 사장님 확인(라이선스 차감).
- **사장님 chrome 점유 시 자동화 0** — 사람이 로그인/입력 중엔 끼어들지 않는다.
- **봇 검출/캡차/로그인 리다이렉트 즉시 stop** — 재시도 금지(계정 잠금).
- **직무로 채널 가르지 않기** — 코드잇 카테고리는 *검색 키워드 선택*일 뿐, LinkedIn·사람인·잡코리아 전 채널에 각 카테고리 제공. ([[feedback_no_channel_routing_by_job]])

## 관련 파일

- 도구: `tools/aisearch-codeit/{run,categorize,searchFilters,codeitPrompt,categoryKeywords}.mjs` + `tests/`
- goal: `docs/engineering/aisearch-codeit-goal-2026-06-30.md`
- 범용 AI Search: `chatgpt-position-sourcing` · URL/필터: `talent-search` · 3사 JD 등록: `position`
- 코드잇 *재직자* 검색(별개): `codeit-talent-archive-search`
