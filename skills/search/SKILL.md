---
name: search
description: "Use when executing the Valuehire AI Search process from a ClickUp position: intake the role, derive a fresh sourcing strategy, create search queries, score candidates, normalize evidence, and prepare next-step handoff without relying on Valuehire_v4 repository code or legacy automation."
version: 2.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [valuehire, ai-search, recruiting, clickup, sourcing, korean]
    related_skills: [recruitment-3-channel-pipeline]
---

# Valuehire AI Search — Fresh Core Logic

## Overview

이 Skill은 ClickUp 포지션 1건을 기반으로 AI Search를 새로 설계·실행할 때 사용한다. 기존 Valuehire_v4 코드레포, npm 스크립트, DB schema, Kanban route, Mac mini worker, Chrome/CDP 자동화 구현체에 의존하지 않는다. 큰 흐름은 유지한다: ClickUp 포지션 intake → 포지션 해석 → 검색전략 수립 → 후보자 탐색 → 적합도 평가 → 후보 정규화 → 다음 단계 handoff.

핵심 목적은 “기반 코드를 실행하는 운영 자동화”가 아니라 “포지션별 후보 서치를 수행하기 위한 독립적인 판단 로직”을 제공하는 것이다. 기존 레포를 참고하지 말라는 사용자의 요청이 있으면 이 Skill만 기준으로 작업한다.

원칙:
- ClickUp task가 포지션 원천 정보다.
- ClickUp 조회는 브라우저가 아니라 ClickUp API로 한다.
- Discord 메시지에 ClickUp/Wanted URL과 JD 본문이 함께 있으면 JD 본문을 우선 사용하고 URL은 참조로만 둔다.
- 기존 Valuehire_v4 코드, package script, DB adapter, Kanban 구현체를 읽거나 실행하지 않는다.
- 실후보만 다룬다. placeholder/demo/fake 후보를 만들지 않는다.
- 후보자에게 메시지, 이메일, InMail을 자동 발송하지 않는다.
- 나이, 성별, 학교 서열 등 민감하거나 차별 가능성이 있는 조건은 직접 필터로 쓰지 말고 경력·역량·성과 조건으로 변환한다.

## When to Use

Use when:
- 사용자가 “search”, “AI Search”, “포지션 서치”, “후보자 롱리스트”, “이 ClickUp 포지션으로 검색”을 요청할 때
- ClickUp task URL을 주고 후보 서치 로직을 만들거나 1~2단계까지만 실행하라고 할 때
- 기존 v4 코드 기반이 아니라 새로 만들 AI Search의 핵심 로직만 가져가려 할 때
- 포지션별 검색 쿼리, 후보 평가표, scoring rubric, handoff payload를 작성할 때

Don't use for:
- 기존 Valuehire_v4 코드 실행, 수정, 디버깅, npm script 검증
- DB insert, Kanban 반영, browser worker 운영, Chrome/CDP 자동화
- 사람인/잡코리아/LinkedIn 메시지 발송
- 캡차/로그인/2FA 우회
- 확인 불가 후보 생성 또는 추정 기반 후보 확정

## Scope Modes

사용자가 단계를 제한하면 반드시 그 지점에서 멈춘다.

### 1단계: ClickUp Position Intake

목표: 포지션 원문을 가져와 검색 가능한 구조로 정리한다.

수행:
1. ClickUp task URL에서 task id를 추출한다.
2. `GET https://api.clickup.com/api/v2/task/<task_id>`로 조회한다.
3. 토큰은 `CLICKUP_API_TOKEN` 또는 `CLICKUP_TOKEN`에서 읽되 절대 출력하지 않는다.
4. 단, Discord 요청 본문에 충분한 JD 텍스트가 함께 있으면 ClickUp 조회 timeout을 기다리지 말고 그 본문으로 2단계 검색전략을 즉시 시작한다.
5. 다음 필드만 요약한다:
   - task id, URL, name, status, list/folder
   - 회사명, 직무명
   - JD 본문
   - 필수조건, 우대조건, 비선호 조건
   - 선호 회사/타겟 산업
   - 채용 프로세스, 조직 맥락

금지:
- ClickUp 브라우저 로그인 시도
- JD 본문이 이미 있는데 ClickUp 조회에 장시간 blocking
- 기존 레포의 ClickUp sync 코드 조회
- DB/Kanban 매칭 시도

### 2단계: Fresh Search Strategy

목표: 기존 구현체 없이 이 포지션에 맞는 검색전략과 후보 평가 로직을 새로 작성한다.

산출물:
- 포지션 해석 요약
- 필수조건/우대조건/제외조건 정규화
- target talent pool
- search keyword matrix
- Boolean/X-ray search query set
- candidate scoring rubric
- evidence requirements
- candidate output schema
- next-step handoff prompt

2단계까지만 요청받으면 여기서 멈춘다. 후보 검색, DB 저장, Kanban 반영, 발송은 하지 않는다.

### 3단계: Candidate Discovery

목표: 공개적으로 확인 가능한 후보를 찾는다.

채널 예시:
- ChatGPT Search 또는 검색 가능한 LLM UI(브라우저/사람 검토용 handoff prompt를 붙여 넣어 실행)
- LinkedIn 공개 프로필
- Google/Bing X-ray 검색
- GitHub, Google Scholar, arXiv, conference pages
- 공개 Notion 포트폴리오/이력 페이지
- 회사 블로그/기술 블로그/발표자료

원칙:
- 공개 URL이 있는 후보만 기록한다.
- 후보 정보는 출처별로 분리해 남긴다.
- 확인되지 않은 정보는 추정하지 않는다.
- LinkedIn URL, GitHub, 포트폴리오, 공개 Notion, 발표/논문/블로그 URL을 후보별로 직접 리스팅한다.
- 연락 수단은 후보자가 채용/업무 연락 목적으로 명시적으로 공개한 연락처를 기록할 수 있다. 예: 채용 플랫폼 이력서 연락처, GitHub profile/README/bio/blog 링크에 명시된 contact, Google Scholar/공식 연구자 프로필에 명시된 contact, 공개 Notion 이력서/포트폴리오의 contact 섹션, 포트폴리오/공개 프로필의 recruiting/work inquiry 이메일, contact form, 업무용 전화번호.
- 단, 연락처 옆에 `사적 연락처`, `개인용`, `업무/채용 연락 금지`, `recruiting 연락 금지`, `do not contact for work/recruiting`처럼 업무·채용 연락에 쓰지 말라는 의사가 명시된 이메일/전화번호는 수집하지 않는다. 비공개/유출성 정보, 데이터브로커성 정보, 민감정보도 수집하지 않는다.
- Freelancer/Freelance로 현재 상태가 표기된 후보는 제외하지는 않되 우선순위를 최하위로 낮추고 `risk_or_gap`에 명시한다.

검색 실행 팁:
- ChatGPT Search를 사용할 수 있으면 3단계에서 Fresh Search Handoff Prompt를 붙여 넣고 실행한다. 결과는 그대로 확정하지 말고 공개 URL을 다시 열람/검증한 뒤 4단계에서 점수화한다.
- ChatGPT Search 결과 화면/대화에는 JSON만 요구하지 말고 사람이 검토할 수 있도록 후보별 LinkedIn URL, 점수 초안, 적합 이유, 학력 요약, 경력사항 요약, 근거 URL 직접 목록, 공개 채용/업무 연락처(있는 경우), 연락처 출처 URL, GitHub/포트폴리오/Notion URL을 함께 요구한다.
- Chrome/ChatGPT 탭이 CDP(`http://127.0.0.1:9222/json/list`)로 열려 있으면 브라우저 UI가 직접 어렵더라도 CDP로 ChatGPT Search를 실행할 수 있다. 세부 절차와 검증 체크리스트는 `references/chatgpt-search-cdp-handoff.md`를 따른다.
- CDP로 ChatGPT Search를 실행할 때는 여러 ChatGPT 탭 중 올바른 project/conversation URL을 고르고, `document.body.innerText` 전체가 아니라 `[data-message-author-role="assistant"]` assistant 메시지를 수집한다. `[data-testid=stop-button]`이 사라지고 `source_urls`/JSON/충분한 후보 수가 보일 때까지 기다린 뒤 raw output과 normalized JSON을 저장한다.
- ChatGPT Search 결과 화면/대화에는 JSON만 요구하지 말고 사람이 검토할 수 있도록 후보별 LinkedIn URL, 점수 초안, 적합 이유, 학력 요약, 경력사항 요약, 근거 URL 직접 목록, 공개 채용/업무 연락처(있는 경우), 연락처 출처 URL, GitHub/포트폴리오/Notion URL을 함께 요구한다.
- GitHub, Google Scholar, 공개 Notion 이력서/포트폴리오를 열람할 때는 profile bio, README, pinned profile repo, blog/homepage link, contact 섹션에 공개된 이메일/전화번호/contact form을 확인해 `recruiting_contact`에 기록한다. 단 commit author metadata, issue 댓글의 우발적 노출, 크롤링 DB/데이터브로커/유출 자료, 업무·채용 연락 금지 의사가 명시된 연락처는 제외한다.
- Google은 자동화 환경에서 captcha가 자주 뜨므로, 막히면 즉시 Brave Search 또는 Bing으로 전환한다.
- Brave Search는 초기 몇 개 쿼리에서 결과가 잘 나올 수 있지만 429 rate limit이 발생할 수 있다. 한 번에 많은 쿼리를 몰아치지 말고 핵심 타겟 회사 1~2개부터 좁혀서 실행한다.
- Bing은 일반 HTML 검색과 `format=rss`를 모두 시도할 수 있다. RSS가 엉뚱한 결과를 줄 수 있으므로 결과 URL/제목에 실제 후보 프로필이 있는지 검증한다.
- 공개 Notion 검색은 `site:notion.site`, `site:*.notion.site`, `site:notion.so`와 직무/회사/기술 키워드를 조합한다.
- 검색엔진이 차단되면 “후보가 없다”고 결론내리지 말고 “검색 채널 제한으로 해당 pool은 미확보”라고 보고한다.
- 3단계 산출물은 scoring 전 리드 목록이다. `match_score`, 최종 우선순위, 컨택 권고는 4단계에서만 확정한다.
- 공개 프로필/이력서/포트폴리오/Notion/GitHub/Google Scholar/공식 연구자 페이지에 공개된 이메일/전화번호/contact form은 기록한다. 단 연락처 옆에 업무·채용 연락 금지 의사가 명시된 경우와 민감정보, 비공개/유출성 정보는 수집하지 않는다.

### 4단계: Candidate Scoring & Normalization

목표: 후보를 같은 기준으로 비교 가능하게 정규화한다.

필수 4요소:
- `profile_url`
- `summary`
- `match_score`
- `fit_reason`

추가 권장:
- `current_or_recent_company`
- `current_or_recent_role`
- `education_summary`
- `career_summary`
- `linkedin_url`
- `github_url`
- `portfolio_url`
- `notion_url`
- `recruiting_contact` (후보자가 채용/업무 연락 목적으로 명시적으로 공개한 이메일, 전화번호, contact page, 채용 플랫폼 공식 연락 경로)
- `contact_source_url`
- `technical_evidence`
- `domain_evidence`
- `leadership_evidence`
- `risk_or_gap`
- `source_urls`

### 5단계: Handoff

목표: 사람이 검토하거나 별도 시스템에 적재할 수 있게 결과를 넘긴다.

이 Skill 자체는 DB/Kanban/ClickUp 저장을 수행하지 않는다. 사용자가 별도 저장을 요청하면 그때 저장 대상과 안전 범위를 확인하고 별도 절차로 진행한다.

## Position Intake Logic

ClickUp task `name`에서 보통 회사명과 직무명을 추출한다.

예시:
- `[포지션]매드업, AI Engineer`
  - company_name: 매드업
  - role_title: AI Engineer

JD 본문에서 다음 블록을 뽑는다.

1. Business context
- 회사가 무엇을 하는지
- 이 포지션이 어떤 제품/조직에 속하는지
- 왜 지금 채용하는지

2. Must-have
- 학력/전공이 꼭 필요한지
- 경력 연차 또는 seniority
- 핵심 기술
- 상용 서비스 경험
- 리딩/협업 요구

3. Nice-to-have
- 특정 도메인
- 특정 기술 스택
- 논문/특허/학회
- 오픈소스/블로그/발표

4. Target background
- 선호 회사
- 선호 산업
- 유사 문제를 풀어본 조직

5. Negative signals
- 너무 초기 스타트업만 경험
- 요구 기술과 무관한 도메인
- 분석/기획 중심으로 모델 개발 깊이가 부족한 경우

민감조건 처리:
- “30대” 같은 표현은 직접 후보 필터로 쓰지 않는다.
- 대신 “석사 이후 5~10년 경력”, “hands-on senior IC”, “과도하게 management-only가 아닌 후보”로 변환한다.

## Requirement Normalization

포지션 조건을 아래처럼 검색 가능한 언어로 변환한다.

### Must-have Template

```text
- Seniority: {{years_or_level}}
- Education/research: {{degree_or_equivalent}}
- Core ML stack: {{frameworks}}
- Model/domain depth: {{cv_nlp_llm_timeseries_recsys_etc}}
- Productionization: {{deployment_mlops_monitoring_ci_cd}}
- Product problem solving: {{business_to_ml_problem_definition}}
- Collaboration: {{po_designer_non_technical_stakeholder}}
```

### Talent Pool Template

```text
Primary pools:
- {{target_company_group_1}} because {{reason}}
- {{target_company_group_2}} because {{reason}}

Adjacent pools:
- {{adjacent_company_or_domain}} because {{reason}}

Avoid / lower priority:
- {{negative_pool}} because {{reason}}
```

## Search Keyword Matrix

검색 쿼리는 하나의 긴 문장이 아니라 축을 조합해 만든다.

### Axis A: Role Titles

- AI Engineer
- Machine Learning Engineer
- ML Engineer
- Deep Learning Engineer
- Applied Scientist
- Research Engineer
- Computer Vision Engineer
- NLP Engineer
- LLM Engineer
- MLOps Engineer
- Staff / Senior / Lead AI Engineer

한국어:
- AI 엔지니어
- 머신러닝 엔지니어
- 딥러닝 엔지니어
- 컴퓨터비전 엔지니어
- NLP 엔지니어
- 리서치 엔지니어
- 추천/검색/광고 ML 엔지니어

### Axis B: Core Technologies

- PyTorch
- TensorFlow
- Deep Learning
- LLM
- RAG
- Agent
- Function Calling
- sLLM
- Computer Vision
- NLP
- Multimodal
- Time-series
- Recommender Systems
- MLOps
- Docker
- Kubernetes
- CI/CD
- model serving
- feature store
- experiment tracking

### Axis C: Evidence Terms

- production
- deployed
- serving
- inference
- fine-tuning
- evaluation
- labeling
- dataset
- metrics
- A/B test
- architecture
- tech lead
- mentoring
- paper
- patent
- CVPR / NeurIPS / ICML / ICLR / ACL / EMNLP

한국어:
- 상용화
- 배포
- 모델 서빙
- 파인튜닝
- 평가 지표
- 레이블링
- 데이터셋 구축
- 실험 설계
- 기술 리딩
- 멘토링
- 논문
- 특허

### Axis D: Target Companies

포지션마다 ClickUp/JD에 나온 선호 회사를 우선 사용한다.

예시 AI Engineer pool:
- Naver / Clova / Search / Ads
- Upstage
- MakinaRocks
- Liner
- Vuno
- Lunit
- NCSoft
- Krafton
- Nexon
- Toss
- Danggeun
- SuaLAB / Cognex Korea

## Query Generation Rules

좋은 쿼리는 3~5개 축만 조합한다. 너무 많은 조건을 한 번에 넣으면 후보가 사라진다.

### LinkedIn / Google X-ray

```text
site:linkedin.com/in ("AI Engineer" OR "Machine Learning Engineer") ("PyTorch" OR "TensorFlow") Korea
```

```text
site:linkedin.com/in ("Senior AI Engineer" OR "Lead AI Engineer") ("MLOps" OR "model serving" OR "Kubernetes") Korea
```

```text
site:linkedin.com/in ("LLM" OR "RAG" OR "Agent") ("PyTorch" OR "fine-tuning") Korea
```

```text
site:linkedin.com/in ("Computer Vision" OR "NLP" OR "Multimodal") ("production" OR "deployed" OR "serving") Korea
```

```text
site:linkedin.com/in ("{{target_company_1}}" OR "{{target_company_2}}" OR "{{target_company_3}}") ("Machine Learning" OR "AI Engineer")
```

### Korean Queries

```text
"AI 엔지니어" "PyTorch" "상용화" "LinkedIn"
```

```text
"머신러닝 엔지니어" "MLOps" "모델 서빙" "Kubernetes"
```

```text
"LLM Agent" "RAG" "Function Calling" "AI Engineer"
```

```text
"컴퓨터 비전" "딥러닝" "PyTorch" "상용 서비스"
```

### GitHub / Technical Evidence Queries

```text
("{{candidate_name}}" OR "{{handle}}") (PyTorch OR TensorFlow OR "machine learning")
```

```text
site:github.com "{{candidate_name}}" "machine learning"
```

```text
site:medium.com OR site:techblog "{{candidate_name}}" "AI" "PyTorch"
```

## Candidate Scoring Rubric

기본 점수는 100점 만점이다. 포지션마다 가중치를 조정할 수 있지만, 조정한 경우 이유를 남긴다.

### 1. Core Requirement Fit — 30점

- 필수 기술 스택 직접 경험: 10점
- 요구 AI 분야 깊이: 10점
- 상용 서비스/제품 적용 경험: 10점

### 2. Problem-Solving Fit — 20점

- 비즈니스 요구를 ML 문제로 정의한 경험: 7점
- 데이터/레이블/평가지표 설계 경험: 7점
- 실험을 통한 성능 개선 또는 A/B test 경험: 6점

### 3. Production & MLOps Fit — 15점

- 모델 서빙/배포/모니터링: 6점
- Docker/Kubernetes/CI/CD 등 운영 환경: 5점
- 안정성/확장성/비용 최적화 경험: 4점

### 4. Domain / Company Pool Fit — 15점

- 명시 선호 회사 또는 매우 유사한 조직: 8점
- 유사 도메인/문제 경험: 5점
- 비선호 배경 리스크 없음: 2점
- 현재 Freelancer/Freelance 중심으로 표기된 경우: 이 항목을 낮게 주고 전체 추천 우선순위를 최하위로 조정

### 5. Seniority & Leadership Fit — 10점

- 요구 연차/레벨 부합: 4점
- 기술 리딩/멘토링/아키텍처 주도: 4점
- cross-functional communication: 2점

### 6. Evidence Quality — 10점

- 공개 프로필/포트폴리오/논문/발표 등 근거 충분: 5점
- 최근 경력과 현재성 확인 가능: 3점
- 불확실성이 낮음: 2점

### Score Bands

- 90~100: 매우 강한 우선 컨택 후보
- 85~89: 우선 검토/컨택 후보
- 75~84: 롱리스트 후보, 추가 검증 필요
- 65~74: 보류 후보
- 0~64: 제외 또는 다른 포지션 검토

## Candidate Evidence Rules

후보를 기록하려면 최소 하나 이상의 공개 근거 URL이 있어야 한다.

추가 참고:
- 검색엔진/LinkedIn/GitHub 채널이 제한될 때의 fallback 절차는 `references/clickup-ai-search-channel-fallbacks.md`를 확인한다. 특히 Bing/LinkedIn 차단 시 GitHub 공개 프로필 HTML과 Google Scholar를 공개 근거로 활용할 수 있지만, LinkedIn 본문을 직접 열람하지 못했다면 URL만 기록하고 내용 검증을 주장하지 않는다.
- 콘텐츠 운영/정산/라이선싱/파트너 운영처럼 non-engineering 운영직을 소싱할 때는 `references/content-ops-settlement-sourcing.md`를 참고한다. 이 역할군은 CMO/AI Engineer식 리더·기술 스코어링이 아니라 계약 데이터, 정산 마감, 콘텐츠 입출고/검수, 파트너 커뮤니케이션, Google Sheets 기반 운영 정확성을 중심으로 평가한다.
- 사용자가 search skill을 “정식 구현”, “재구현”, “제품화”, “Harness Engineering”, “테스트/평가/관측 가능성까지 잡아서 구현”하려는 경우 `references/harness-engineering-reimplementation.md`를 먼저 참고한다. 이 경우 후보 검색 프롬프트가 아니라 Input/Strategy/Discovery/Evidence/Scoring/Privacy/Output/Evaluation/Observability 하네스를 schema, test, artifact 중심으로 설계하도록 요구한다.
- 사용자가 search skill을 “정식 구현”, “재구현”, “제품화”, “Harness Engineering”, “테스트/평가/관측 가능성까지 잡아서 구현”하려는 경우 `references/harness-engineering-reimplementation.md`를 먼저 참고한다. 이 경우 후보 검색 프롬프트가 아니라 Input/Strategy/Discovery/Evidence/Scoring/Privacy/Output/Evaluation/Observability 하네스를 schema, test, artifact 중심으로 설계하도록 요구한다.

허용 근거:
- LinkedIn 공개 프로필 URL
- GitHub profile/repo URL
- 공개 Notion 포트폴리오/이력 URL
- 개인 포트폴리오/홈페이지 URL
- 논문/학회/특허 URL
- 회사/기술블로그 글 URL
- 발표자료/영상/인터뷰 URL
- 공식 프로필 페이지
- 후보자가 채용/업무 연락 목적으로 명시적으로 공개한 contact page, 공개 이메일, 공개 전화번호, 채용 플랫폼 공식 연락 경로
- GitHub profile/README/bio/blog 링크 또는 pinned profile repo에 후보자가 직접 명시한 contact
- Google Scholar/공식 연구자 프로필에 공개된 verified email/contact 또는 연결된 공식 홈페이지의 contact
- 공개 Notion 이력서/포트폴리오 contact 섹션에 명시된 이메일/전화번호/contact form

기록하지 말 것:
- 업무·채용 연락 금지 의사가 명시된 연락처. 예: `사적 연락처`, `개인용`, `업무 연락 금지`, `채용 연락 금지`, `recruiting 연락 금지`, `do not contact for work/recruiting` 등으로 표기된 이메일/전화번호
- 주민등록번호/생년월일/가족/건강/종교/정치 성향 등 민감정보
- 비공개 커뮤니티 정보
- 유출/스크래핑/데이터브로커성 정보
- 확인 불가 추정 정보

불확실한 경우:
- `risk_or_gap`에 명시한다.
- 점수에서 Evidence Quality를 낮춘다.
- “확인 필요”로 표시한다.

## Candidate Output Schema

사람 검토용:

```text
후보 {{n}}: {{name_or_public_identifier}}
- Profile: {{profile_url}}
- LinkedIn: {{linkedin_url_or_unknown}}
- GitHub: {{github_url_or_unknown}}
- Portfolio/Notion: {{portfolio_or_notion_url_or_unknown}}
- 공개 채용/업무 연락처: {{recruiting_contact_or_unknown}}
- 연락처 출처 URL: {{contact_source_url_or_unknown}}
- 현재/최근 역할: {{current_or_recent_role}}
- 학력 요약: {{education_summary_or_unknown}}
- 경력사항 요약: {{career_summary}}
- 요약: {{summary}}
- 점수: {{match_score}}/100
- 적합 이유: {{fit_reason}}
- 근거 URL 직접 목록: {{source_urls}}
- 리스크/확인 필요: {{risk_or_gap}}
- 추천 액션: 우선 컨택 / 추가 검증 / 보류 / 제외
```

기계 처리용:

```json
{
  "position": {
    "clickup_task_id": "...",
    "company_name": "...",
    "role_title": "..."
  },
  "candidate": {
    "name_or_public_identifier": "...",
    "profile_url": "...",
    "current_or_recent_company": "...",
    "current_or_recent_role": "...",
    "education_summary": "...",
    "career_summary": "...",
    "linkedin_url": "...",
    "github_url": "...",
    "portfolio_url": "...",
    "notion_url": "...",
    "recruiting_contact": "...",
    "contact_source_url": "...",
    "summary": "...",
    "match_score": 0,
    "fit_reason": "...",
    "technical_evidence": "...",
    "domain_evidence": "...",
    "leadership_evidence": "...",
    "risk_or_gap": "...",
    "source_urls": ["..."],
    "recommended_action": "priority_contact|verify_more|hold|reject"
  }
}
```

## Fresh Search Handoff Prompt

후보 검색을 다른 LLM/브라우저/사람에게 넘길 때는 아래 프롬프트를 포지션별로 채운다.

```text
다음 포지션에 적합한 공개 후보자를 찾아 주세요.

회사명: {{company_name}}
직무명: {{role_title}}
포지션 요약:
{{position_summary}}

필수조건:
{{must_have}}

우대조건:
{{nice_to_have}}

타겟 후보군:
{{target_pools}}

비선호/주의 후보군:
{{negative_signals}}

검색 요구사항:
1. 공개적으로 확인 가능한 후보만 제시하세요.
2. 각 후보는 사람이 검토할 수 있도록 LinkedIn URL, GitHub URL, 포트폴리오/공개 Notion URL, 점수 초안, 적합 이유, 학력 요약, 경력사항 요약, 근거 URL 직접 목록을 포함하세요.
3. 후보자가 공개 프로필/이력서/포트폴리오/Notion/GitHub/Google Scholar/공식 연구자 페이지에 이메일, 전화번호, contact page, 채용 플랫폼 공식 연락 경로를 공개해 두었으면 `recruiting_contact`와 `contact_source_url`에 남기세요. 단, 연락처 옆에 `사적 연락처`, `개인용`, `업무/채용 연락 금지`, `do not contact for work/recruiting`처럼 업무·채용 연락에 쓰지 말라는 의사가 명시되어 있으면 수집하지 마세요. 민감정보, 비공개/유출성 정보도 수집하지 마세요.
4. 각 후보는 profile_url, summary, match_score, fit_reason 4요소를 반드시 포함하세요.
5. 후보별 근거 URL을 최소 1개 이상 포함하세요.
6. 확인되지 않은 정보는 추정하지 말고 risk_or_gap에 적으세요.
7. 주민등록번호, 생년월일, 가족/건강/종교/정치성향 등 민감정보, 비공개/유출성 정보, 확인 불가 추정 정보는 수집하지 마세요.
8. 점수는 100점 만점으로 주고, 왜 그 점수인지 설명하세요.
9. Freelancer/Freelance로 현재 상태가 표기된 후보는 제외하지 말고 우선순위를 최하위로 낮추고 risk_or_gap에 표시하세요.
10. 먼저 사람이 읽는 후보 리스트를 보여주고, 마지막에만 JSON 배열을 붙이세요.
```

## Reporting Format

작업 완료 또는 중단 시 한국어로 간결하게 보고한다.

```text
처리 결과: 완료/부분완료/중단
범위: {{requested_scope}}
포지션: {{company_name}} / {{role_title}} / {{clickup_task_id}}

1. ClickUp Intake
- Task name:
- Status/List:
- 핵심 조건:

2. Fresh Search Strategy
- Target pools:
- 핵심 키워드:
- 대표 검색 쿼리:
- Scoring 기준:

3. Side Effects
- DB write:
- Kanban update:
- Browser automation:
- Outreach sent:

4. Verification
- 실행/조회한 명령:
- 결과:

다음 필요 조치:
- {{if any}}
```

## Safety Gates

- 외부 발송 0건: 이 Skill은 검색/정리/평가까지만 한다.
- 코드레포 비의존: 사용자가 새로 만들 핵심 로직만 요청하면 기존 v4 코드·스크립트·DB route를 보지 않는다.
- ClickUp API 토큰, service key, cookie, password를 출력하지 않는다.
- 민감조건은 역량 기반 조건으로 변환한다.
- 후보 정보는 공개 출처 기반으로만 작성한다.
- 적합도가 낮거나 4요소가 누락된 후보를 다음 액션 대상으로 올리지 않는다.

## Common Pitfalls

1. 기존 Valuehire_v4 스크립트를 실행하는 실수: 이 Skill은 fresh logic용이다. npm dry-run, Mac mini worker, DB route는 사용하지 않는다.
2. ClickUp 브라우저 로그인 시도: task URL은 API로 조회한다.
3. task id와 내부 DB position id를 찾으려는 실수: 이 Skill에서는 내부 DB id가 필요 없다.
4. “30대” 같은 조건을 직접 필터링하는 실수: 경력/레벨/실무 hands-on 조건으로 바꾼다.
5. 후보를 추정해서 만드는 실수: 공개 URL 없는 후보는 기록하지 않는다.
6. JSON만 만드는 실수: 사람이 읽을 수 있는 후보 설명을 먼저 작성한다.
7. 점수 근거 누락: match_score에는 fit_reason과 source_urls가 따라야 한다.
8. 메시지 발송까지 진행하는 실수: outreach는 별도 승인과 별도 Skill/절차가 필요하다.
9. ChatGPT Search 결과를 잘못 캡처하는 실수: CDP/브라우저 자동화 시 prompt나 sidebar만 저장해 놓고 완료로 보고하지 않는다. assistant-message selector, stop-button 상태, `source_urls`/JSON 존재 여부로 완료를 확인한다.
10. ChatGPT Search가 제시한 회사/서비스 지표를 후보 개인 성과로 단정하는 실수: 개인 기여가 직접 확인되지 않으면 risk/gap에 표시한다.

## Verification Checklist

- [ ] ClickUp task를 API로 조회했다.
- [ ] 토큰/비밀값을 출력하지 않았다.
- [ ] 회사명/직무명/JD 핵심 조건을 추출했다.
- [ ] 민감조건을 역량 기반 조건으로 변환했다.
- [ ] target pool과 negative signal을 분리했다.
- [ ] 검색 키워드 matrix와 대표 쿼리를 만들었다.
- [ ] scoring rubric을 포지션에 맞게 작성했다.
- [ ] 후보 output schema 또는 handoff prompt를 제공했다.
- [ ] 사용자가 제한한 단계 이후 작업을 실행하지 않았다.
- [ ] DB write, Kanban update, browser automation, outreach가 없었음을 보고했다.
