# Valuehire AI Search 정식 재구현을 위한 Harness Engineering 프롬프트

## 문서 목적

이 문서는 기존 `search` skill의 내용을 바탕으로 Valuehire AI Search를 정식 제품/시스템으로 다시 구현한다고 가정할 때 사용할 수 있는 Harness Engineering 중심의 프롬프트입니다.

핵심 목표는 단순히 “후보를 찾아줘”가 아니라, AI Search가 안정적으로 반복 실행되고, 검증 가능하며, 실패를 관측할 수 있고, 사람이 운영 가능한 소프트웨어 시스템으로 구현되도록 요구사항·테스트·평가·데이터 계약·안전장치를 먼저 고정하는 것입니다.

---

## Harness Engineering 관점의 핵심 원칙

정식 구현은 모델 프롬프트, 검색 로직, 후보 점수화 로직만으로 완성되지 않습니다. 반드시 아래 하네스가 함께 설계되어야 합니다.

1. Input Harness
   - ClickUp task 원문을 안정적으로 수집하고 정규화합니다.
   - task id, task url, company, role, JD, must-have, nice-to-have, negative signals를 구조화합니다.
   - API 실패, 필드 누락, 중복 포지션, 비정형 JD를 테스트합니다.

2. Strategy Harness
   - 포지션별 search strategy가 매번 재현 가능한 구조로 생성되는지 검증합니다.
   - target pool, keyword matrix, Boolean queries, scoring rubric이 필수 schema를 만족해야 합니다.
   - 민감 조건은 역량 조건으로 변환되는지 테스트합니다.

3. Discovery Harness
   - 후보 탐색 채널별 결과를 raw evidence로 저장합니다.
   - ChatGPT Search, Bing, Brave, LinkedIn 공개 URL, GitHub, Scholar, Notion, portfolio 등 채널별 adapter를 분리합니다.
   - 검색엔진 차단, 429, captcha, 빈 결과, 중복 URL을 관측 가능하게 만듭니다.

4. Evidence Harness
   - 후보별 source URL이 실제 접근 가능한지 검증합니다.
   - URL별로 어떤 주장에 대한 근거인지 분리합니다.
   - LinkedIn URL만 있고 본문을 열람하지 못한 경우에는 URL만 기록하고 경력 검증 근거로 쓰지 않습니다.

5. Scoring Harness
   - 100점 만점 rubric을 코드/프롬프트 양쪽에서 동일하게 적용합니다.
   - 점수에는 반드시 fit_reason, risk_or_gap, source_urls가 연결되어야 합니다.
   - Evidence Quality가 낮으면 높은 점수를 제한하는 guardrail을 둡니다.

6. Privacy & Safety Harness
   - 공개 채용/업무 연락처만 수집합니다.
   - 개인용/사적/업무연락금지/채용연락금지/do not contact 문구가 있으면 연락처를 제외합니다.
   - 민감정보, 비공개 정보, 데이터브로커성 정보, 유출성 정보는 저장하지 않습니다.
   - outreach는 자동 발송하지 않습니다.

7. Output Harness
   - 사람 검토용 결과와 기계 처리용 JSON을 모두 생성합니다.
   - 후보별 필수 4요소(profile_url, summary, match_score, fit_reason)를 강제합니다.
   - schema validation 실패 시 결과를 확정하지 않습니다.

8. Evaluation Harness
   - golden set 포지션과 기대 산출물을 만들어 회귀 테스트합니다.
   - 검색 쿼리 품질, 후보 적합도, 근거 충실도, 개인정보 안전성, 중복 제거율을 평가합니다.
   - 모델 변경, 프롬프트 변경, 검색 adapter 변경 시 동일 benchmark를 돌립니다.

9. Observability Harness
   - 각 run마다 run_id를 부여합니다.
   - 입력, 전략, 검색 쿼리, raw result, normalized candidate, scoring decision, error를 분리 로깅합니다.
   - 실패 원인을 “후보 없음”이 아니라 “채널 차단”, “쿼리 품질 부족”, “근거 부족”, “schema failure” 등으로 구분합니다.

---

## 정식 구현 요청 프롬프트

아래 프롬프트를 구현 에이전트 또는 개발팀에게 그대로 전달할 수 있습니다.

```text
당신은 Valuehire AI Search를 정식 제품 수준으로 재구현하는 Staff-level AI Systems Engineer입니다.

목표는 ClickUp 포지션 1건을 입력받아, 공개 근거 기반 후보자를 탐색하고, 포지션별 검색 전략을 생성하며, 후보를 점수화하고, 사람이 검토 가능한 결과와 기계 처리 가능한 JSON을 생성하는 AI Search 시스템을 구현하는 것입니다.

단, 단순한 LLM prompt workflow가 아니라 Harness Engineering을 중심으로 구현해야 합니다. 즉, 입력/전략/검색/근거/점수화/개인정보/출력/평가/관측 가능성 하네스를 먼저 설계하고, 각 하네스가 테스트 가능해야 합니다.

## 절대 원칙

1. 기존 Valuehire_v4 코드, npm script, DB adapter, Kanban route, Chrome/CDP 자동화 구현체에 의존하지 마세요.
2. ClickUp task가 포지션 원천 정보입니다.
3. ClickUp 조회는 브라우저가 아니라 ClickUp API로 수행하세요.
4. 후보자는 공개 URL로 확인 가능한 사람만 기록하세요.
5. placeholder/demo/fake 후보를 만들지 마세요.
6. 후보자에게 이메일, 메시지, InMail, DM을 자동 발송하지 마세요.
7. 나이, 성별, 학교 서열 등 차별 가능성이 있는 조건은 직접 필터로 사용하지 말고, 경력·역량·성과 조건으로 변환하세요.
8. 확인되지 않은 정보는 추정하지 말고 risk_or_gap에 기록하세요.
9. ClickUp token, API key, cookie, password, service key는 절대 출력하거나 로그에 남기지 마세요.
10. 구현 완료의 기준은 “코드 작성”이 아니라 테스트와 샘플 run이 통과하는 것입니다.

## 구현 범위

다음 모듈을 설계하고 구현하세요.

### 1. Input Harness: ClickUp Position Intake

요구사항:
- ClickUp task URL 또는 task id를 입력받습니다.
- `GET https://api.clickup.com/api/v2/task/<task_id>`로 task를 조회합니다.
- token은 환경변수 `CLICKUP_API_TOKEN` 또는 `CLICKUP_TOKEN`에서 읽습니다.
- token 값은 로그/에러/출력에 절대 노출하지 않습니다.
- task name, status, list/folder, description/JD, custom fields를 수집합니다.
- 회사명과 직무명을 task name과 JD에서 추출합니다.
- must_have, nice_to_have, negative_signals, target_companies, process_context를 구조화합니다.

테스트해야 할 케이스:
- 정상 task URL
- task id만 입력
- 잘못된 task id
- token 없음
- API 401/403/404/429/5xx
- description이 비어 있는 task
- JD가 한국어/영어 혼합인 task
- 회사명/직무명이 task name에 없는 task

산출 schema:
```json
{
  "position": {
    "clickup_task_id": "string",
    "clickup_url": "string",
    "task_name": "string",
    "status": "string",
    "list_or_folder": "string",
    "company_name": "string|null",
    "role_title": "string|null",
    "jd_raw": "string",
    "business_context": "string|null",
    "must_have": ["string"],
    "nice_to_have": ["string"],
    "negative_signals": ["string"],
    "target_companies": ["string"],
    "process_context": "string|null"
  },
  "intake_warnings": ["string"]
}
```

### 2. Strategy Harness: Fresh Search Strategy

요구사항:
- 기존 구현체 없이 포지션별 검색전략을 새로 생성합니다.
- must-have, nice-to-have, negative signal을 검색 가능한 조건으로 정규화합니다.
- 민감하거나 차별 가능성이 있는 조건은 직접 필터가 아니라 역량 기반 조건으로 변환합니다.
- target talent pool과 adjacent pool을 분리합니다.
- keyword matrix를 role title, core technology, evidence term, target company, Korean keyword 축으로 만듭니다.
- Boolean/X-ray query set을 생성합니다.
- scoring rubric을 포지션에 맞게 조정하되 기본 100점 구조를 유지합니다.

반드시 생성할 항목:
- position_summary
- normalized_requirements
- target_talent_pools
- lower_priority_or_avoid_pools
- search_keyword_matrix
- boolean_query_set
- channel_plan
- scoring_rubric
- evidence_requirements
- discovery_handoff_prompt

테스트해야 할 케이스:
- AI Engineer 포지션
- non-AI software engineer 포지션
- seniority가 애매한 포지션
- 민감조건이 포함된 포지션
- target company가 명시된 포지션
- target company가 없는 포지션

### 3. Discovery Harness: Candidate Discovery

요구사항:
- 공개적으로 접근 가능한 출처에서 후보 리드를 수집합니다.
- 검색 채널 adapter를 분리하세요.
- 가능한 채널: ChatGPT Search handoff, Bing/Brave/Google X-ray, LinkedIn public URL, GitHub, Google Scholar, arXiv, Notion, portfolio, tech blog.
- 검색 결과는 raw result와 normalized lead로 분리 저장합니다.
- 검색엔진 차단이나 rate limit을 후보 없음으로 오판하지 마세요.
- 후보자별 중복 URL과 동일 인물 가능성을 deduplicate합니다.

채널 실패 분류:
- `blocked_by_captcha`
- `rate_limited`
- `no_results`
- `network_error`
- `parser_error`
- `insufficient_evidence`

Lead schema:
```json
{
  "lead_id": "string",
  "name_or_public_identifier": "string|null",
  "profile_url": "string",
  "source_channel": "string",
  "raw_title": "string|null",
  "raw_snippet": "string|null",
  "source_urls": ["string"],
  "dedupe_keys": ["string"],
  "discovery_warnings": ["string"]
}
```

### 4. Evidence Harness: Evidence Extraction & Verification

요구사항:
- 후보별 source URL을 열람/검증하고, 어떤 주장에 대한 근거인지 분리합니다.
- LinkedIn URL은 열람하지 못했다면 URL 자체만 evidence로 기록하고, 경력/학력의 본문 근거로 사용하지 마세요.
- GitHub profile, README, pinned profile repo, blog link, portfolio, Notion, Scholar, official page를 확인합니다.
- 공개된 채용/업무 연락처가 있으면 수집하되, 금지 문구가 있으면 제외합니다.
- commit author metadata, 유출성 정보, 데이터브로커성 연락처는 사용하지 마세요.

Evidence schema:
```json
{
  "candidate_id": "string",
  "evidence_items": [
    {
      "url": "string",
      "source_type": "linkedin|github|portfolio|notion|scholar|paper|blog|official|other",
      "claim_type": "identity|current_role|career|education|technical|domain|leadership|contact|other",
      "claim_text": "string",
      "confidence": "high|medium|low",
      "access_status": "accessible|url_only|blocked|not_found",
      "collected_at": "ISO-8601 string"
    }
  ],
  "recruiting_contact": "string|null",
  "contact_source_url": "string|null",
  "privacy_warnings": ["string"]
}
```

### 5. Scoring Harness: Candidate Scoring & Normalization

요구사항:
- 후보 점수는 100점 만점입니다.
- 기본 rubric은 아래를 사용합니다.
  - Core Requirement Fit: 30
  - Problem-Solving Fit: 20
  - Production & MLOps Fit: 15
  - Domain / Company Pool Fit: 15
  - Seniority & Leadership Fit: 10
  - Evidence Quality: 10
- 포지션별 조정이 필요하면 조정 이유를 scoring_rubric에 남기세요.
- 점수에는 반드시 source_urls, fit_reason, risk_or_gap가 연결되어야 합니다.
- Evidence Quality가 낮거나 필수 4요소가 없으면 priority_contact로 올리지 마세요.
- 현재 Freelancer/Freelance 중심으로 표기된 후보는 제외하지 않되 우선순위를 최하위로 낮추고 risk_or_gap에 명시하세요.

Normalized candidate schema:
```json
{
  "candidate": {
    "name_or_public_identifier": "string",
    "profile_url": "string",
    "current_or_recent_company": "string|null",
    "current_or_recent_role": "string|null",
    "education_summary": "string|null",
    "career_summary": "string",
    "linkedin_url": "string|null",
    "github_url": "string|null",
    "portfolio_url": "string|null",
    "notion_url": "string|null",
    "recruiting_contact": "string|null",
    "contact_source_url": "string|null",
    "summary": "string",
    "match_score": 0,
    "score_breakdown": {
      "core_requirement_fit": 0,
      "problem_solving_fit": 0,
      "production_mlops_fit": 0,
      "domain_company_pool_fit": 0,
      "seniority_leadership_fit": 0,
      "evidence_quality": 0
    },
    "fit_reason": "string",
    "technical_evidence": "string|null",
    "domain_evidence": "string|null",
    "leadership_evidence": "string|null",
    "risk_or_gap": "string|null",
    "source_urls": ["string"],
    "recommended_action": "priority_contact|verify_more|hold|reject"
  }
}
```

### 6. Privacy & Safety Harness

요구사항:
- 연락처는 후보자가 공개 프로필/이력서/포트폴리오/Notion/GitHub/Scholar/공식 페이지에 채용/업무 목적 또는 일반 contact로 공개한 경우에만 수집합니다.
- 다음 표현이 연락처 근처에 있으면 수집하지 마세요.
  - 개인용
  - 사적 연락처
  - 업무 연락 금지
  - 채용 연락 금지
  - recruiting 연락 금지
  - do not contact for work/recruiting
- 다음 정보는 절대 수집하지 마세요.
  - 주민등록번호
  - 생년월일
  - 가족 정보
  - 건강 정보
  - 종교
  - 정치 성향
  - 비공개 커뮤니티 정보
  - 유출/스크래핑/데이터브로커성 정보
- outreach는 시스템 범위 밖입니다. 어떤 상황에서도 자동 발송하지 마세요.

필수 guardrail:
- privacy scanner를 output 직전에 실행합니다.
- 금지 정보 발견 시 결과에서 제거하고 privacy_warnings에 남깁니다.
- recruiting_contact가 있으면 contact_source_url도 필수입니다.

### 7. Output Harness

요구사항:
- 사람 검토용 markdown report와 기계 처리용 JSON을 모두 생성합니다.
- 사람 검토용 report가 먼저 나오고 JSON은 뒤에 붙습니다.
- 후보별 필수 4요소가 없으면 확정 결과가 아니라 `verify_more` 또는 `reject`로 처리합니다.

Markdown output format:
```text
# Valuehire AI Search Result

처리 결과: 완료|부분완료|중단
범위: intake|strategy|discovery|scoring|handoff
포지션: {company_name} / {role_title} / {clickup_task_id}

## 1. ClickUp Intake
- Task name:
- Status/List:
- 핵심 조건:

## 2. Fresh Search Strategy
- Target pools:
- 핵심 키워드:
- 대표 검색 쿼리:
- Scoring 기준:

## 3. Candidate List

### 후보 1: {name_or_public_identifier}
- Profile:
- LinkedIn:
- GitHub:
- Portfolio/Notion:
- 공개 채용/업무 연락처:
- 연락처 출처 URL:
- 현재/최근 역할:
- 학력 요약:
- 경력사항 요약:
- 요약:
- 점수:
- 적합 이유:
- 근거 URL 직접 목록:
- 리스크/확인 필요:
- 추천 액션:

## 4. Side Effects
- DB write: none
- Kanban update: none
- Browser automation: none
- Outreach sent: none

## 5. Verification
- 실행/조회한 채널:
- 실패/제한된 채널:
- schema validation 결과:
- privacy scan 결과:
```

### 8. Evaluation Harness

요구사항:
- golden set 기반 평가를 구현합니다.
- 최소 5개 이상의 포지션 fixture를 만듭니다.
- 각 fixture에는 기대 search strategy, 금지되어야 하는 output, 최소 schema 조건을 포함합니다.

평가 지표:
- Intake parse accuracy
- Requirement normalization quality
- Query diversity
- Candidate evidence coverage
- Duplicate rate
- Invalid URL rate
- Unsupported claim rate
- Privacy violation rate
- Schema pass rate
- Human review usefulness

테스트 유형:
- unit test
- integration test
- schema validation test
- privacy red-team test
- regression test
- replay test with frozen raw search results

### 9. Observability Harness

요구사항:
- 모든 run에 run_id를 부여합니다.
- 각 단계별 artifact를 분리 저장합니다.
  - intake.json
  - strategy.json
  - queries.json
  - raw_results.jsonl
  - leads.jsonl
  - evidence.jsonl
  - scored_candidates.json
  - report.md
  - validation.json
- 로그에는 secret을 남기지 않습니다.
- 실패 사유를 구조화합니다.

Run status enum:
- `completed`
- `partial_completed`
- `stopped_by_scope_limit`
- `failed_intake`
- `failed_strategy`
- `failed_discovery`
- `failed_validation`
- `failed_privacy_scan`

## Architecture 요구사항

가능하면 다음 구조를 사용하세요.

```text
src/
  clickup/
    client.ts
    intake.ts
  strategy/
    normalize-requirements.ts
    build-keyword-matrix.ts
    generate-queries.ts
    build-rubric.ts
  discovery/
    adapters/
      chatgpt-search-handoff.ts
      bing.ts
      brave.ts
      github.ts
      scholar.ts
      notion.ts
      portfolio.ts
    dedupe.ts
    lead-normalizer.ts
  evidence/
    fetch-url.ts
    extract-evidence.ts
    verify-claims.ts
    contact-policy.ts
  scoring/
    score-candidate.ts
    score-guards.ts
  privacy/
    privacy-scan.ts
    redact.ts
  output/
    markdown-report.ts
    json-output.ts
  evaluation/
    fixtures/
    golden-runner.ts
    metrics.ts
  observability/
    run-artifacts.ts
    logger.ts
  validation/
    schemas.ts
    validate.ts
```

## Definition of Done

구현 완료 조건은 다음입니다.

1. ClickUp task URL 또는 task id로 intake가 동작합니다.
2. token이 없거나 API가 실패할 때 안전하게 실패합니다.
3. strategy JSON이 schema validation을 통과합니다.
4. query set이 최소 10개 이상 생성됩니다.
5. discovery adapter 실패가 구조화되어 기록됩니다.
6. 후보별 source URL이 최소 1개 이상 있어야 합니다.
7. 필수 4요소 없는 후보는 priority_contact가 될 수 없습니다.
8. privacy scanner가 금지 정보와 금지 연락처를 제거합니다.
9. markdown report와 JSON output이 모두 생성됩니다.
10. golden fixture regression test가 통과합니다.
11. sample run artifact가 생성됩니다.
12. DB write, Kanban update, outreach는 기본 구현에서 발생하지 않습니다.

## 구현 순서

1. schema부터 작성하세요.
2. fixture와 golden expected output을 먼저 만드세요.
3. ClickUp intake를 구현하세요.
4. strategy generator를 구현하세요.
5. output validator를 구현하세요.
6. discovery adapter는 mock/replay 가능한 구조로 구현하세요.
7. evidence extraction과 privacy scan을 구현하세요.
8. scoring과 guardrail을 구현하세요.
9. markdown/JSON output을 구현하세요.
10. end-to-end sample run을 실행하고 artifact를 검증하세요.

## 최종 응답에 포함할 것

개발 완료 후 다음을 보고하세요.

- 구현한 모듈 목록
- 생성한 schema 목록
- 테스트 명령과 실제 결과
- sample run artifact 경로
- 실패/미구현/제한 사항
- 다음 작업 제안

주의: 실제 실행하지 않은 테스트 결과를 만들어내지 마세요. 실패했다면 실패 원인과 다음 조치를 명확히 보고하세요.
```

---

## 구현 에이전트에게 추가로 줄 수 있는 짧은 버전

```text
Valuehire AI Search를 fresh implementation으로 구현하세요. 기존 Valuehire_v4 코드와 자동화에 의존하지 말고, ClickUp API intake → search strategy → discovery → evidence verification → scoring → markdown/JSON handoff까지 구현하세요.

핵심은 Harness Engineering입니다. 입력, 전략, 검색, 근거, 점수화, 개인정보, 출력, 평가, 관측 가능성 하네스를 각각 schema/test/artifact 중심으로 설계하세요.

가짜 후보 생성 금지, 공개 URL 없는 후보 기록 금지, outreach 자동 발송 금지, 민감정보/비공개정보 수집 금지, token/secret 로그 출력 금지입니다.

완료 기준은 코드 작성이 아니라 schema validation, privacy scan, golden fixture regression, sample run artifact 생성까지 통과하는 것입니다.
```

---

## 체크리스트

- [ ] ClickUp API 기반 intake
- [ ] Secret redaction
- [ ] Position schema
- [ ] Strategy schema
- [ ] Lead schema
- [ ] Evidence schema
- [ ] Candidate schema
- [ ] Privacy policy scanner
- [ ] Contact collection policy
- [ ] Search channel adapters
- [ ] Raw result artifact 저장
- [ ] Dedupe logic
- [ ] Scoring rubric
- [ ] Score guardrails
- [ ] Markdown report
- [ ] JSON output
- [ ] Golden fixtures
- [ ] Regression test
- [ ] Observability artifacts
- [ ] No DB write by default
- [ ] No Kanban update by default
- [ ] No outreach by default
