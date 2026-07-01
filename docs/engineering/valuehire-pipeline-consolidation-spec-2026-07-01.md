# Valuehire 후보-소싱 통합 파이프라인 Spec (2026-07-01)

> 문서 경로: `docs/engineering/valuehire-pipeline-consolidation-spec-2026-07-01.md`
> 기계판독 백로그: `docs/engineering/valuehire-pipeline-consolidation-backlog-2026-07-01.json`
> 근거: 이 저장소의 CLAUDE.md(SOT) · `docs/harness.md`(게이트) · maps/gaps 종합 조사(2026-07-01)

---

## (0) 한 줄 목적

> **사장님께:** 지금은 후보 찾는 기능들이 여러 조각으로 흩어져 있어서 손으로 이어 붙여 씁니다. 이걸 "한 번 켜두면 알아서 도는 한 줄기 파이프라인"으로 잇는 설계도이고, 큰 걸 한 번에 만들지 않고 작은 조각으로 잘라 순서대로 붙입니다.

**목적:** ClickUp 포지션 → 포털별 검색 URL 생성(사람 검수) → 검색 URL 저장 → Humansearch 전수 채점·하드제외·레쥬메/연봉 저장 → Reservoir 최적합 대기열 축적 → 포털별 맞춤 JD 발송 드래프트 → **사람이 마지막 발송 클릭**, 이 흐름을 하나의 항상-켜진 파이프라인으로 통합한다. 단, 무거운 일괄 구현은 금지하고 "한 조각 = 한 worktree = 인수기준 1개"로만 전진한다.

---

## (1) 목표 아키텍처 (텍스트 다이어그램)

> **사장님께:** 아래는 물이 위에서 아래로 흐르듯 일이 이어지는 그림입니다. 별표(★)는 반드시 사람이 손으로 확인/클릭하는 곳입니다.

```
[ClickUp FY26ClientsPosition 보드]
        │  (포지션 JD 순회)
        ▼
① 인입/등록  position_registration.py  ── 실 ClickUp 쓰기 + 목적지 리스트 + 커스텀필드/부모-자식/연봉필드
        │
        ▼
② 검색식 생성  llm_keywords.py (LinkedIn Boolean 3단 / 사람인 AND·OR·NOT / 잡코리아 칩)
        │        └─ ★사람 검수 게이트 (사람이 필터/URL 승인)
        ▼
③ 검색 URL 저장  → ClickUp 포지션 태스크(커스텀필드/댓글)에 확보 URL 보관
        │
        ▼
④ Humansearch 전수 순회  humansearch_cdp_run.py + raw_cdp.py
        │   ├─ 결과수 판단 트리(GOLD 전수)  humansearch.plan_result_count_traversal
        │   ├─ 리스팅 페이지 무조건 저장(save_rail)  ← 레쥬메 전건
        │   ├─ 연봉/처우 캡처(salary_raw)             ← 사람인·잡코리아 자산
        │   ├─ 가중 채점 score_humansearch
        │   └─ ★하드제외 게이트(프리랜서·단기이직2회+·전문대)  register.eligible()
        ▼
⑤ Reservoir 대기열  harvest_runner.run_harvest_cycle → SQLite 영속 store(런간 누적)
        │   └─ embed(pgvector) → match_jd_to_reservoir(최적합 재랭킹)
        │        · 상시 드라이버(항상-켜짐, R4 양보/자동재개, 봇 금지 페이싱)
        ▼
⑥ 발송 드래프트  jd_outreach.build_linkedin_inmail_jd (회사브리핑 7요소 + JD핵심, ≤1,899자)
        │        (사람인·잡코리아·Gmail 채널은 후속)
        ▼
⑦ ★사람이 마지막 "보내기" 클릭 (SOT 3 — 자동 발송 절대 금지)

[가로지르는 공통 계층]
  · 포털 점유/로그인/R4 양보:  owner_activity.py(task/ai-search-pipeline-wip 회수) → compute_yield_decision → worker_should_yield / queue_runner 게이트 / rps_switch
  · 봇방지 페이싱 primitive:  harvest_policy(PC-E1, 간격·지터·최대단계 캡, SOT22 단일 출처) — 모든 라이브 루프 재사용
  · 라이브 검색 실행자:  ExecuteHarvestItem 어댑터(PC-D5, GuardedPortalSearchRunner 래핑·챌린지 STOP) — 상시 Harvest 이음매
  · 거버넌스:  harness 게이트(worktree·RED·verify·2패스) / SOT preflight / 자립화 게이트 / CI
```

핵심 원칙: **부품(순수함수·계약)은 이미 대부분 GREEN**, 빠진 것은 "조립(라이브 배선·영속·상시 순환)"이다. 새 러너/스크립트를 처음부터 짜지 않고 기존 계약(`save_rail`·`worker_should_yield`·`find_duplicate_position`·`hard_exclude_reason`)에 **주입/확장**한다.

---

## (2) 요구사항 → 컴포넌트/현황 매트릭스

> **사장님께:** 요구사항별로 "어디까지 됐고 뭐가 빠졌는지"를 한 줄씩 정리한 표입니다. `partial`은 반쯤 됐다는 뜻입니다.

| 요구ID | 요구 요약 | 핵심 컴포넌트 | 현황 | 결정적 빈틈 | 대응 조각 |
|---|---|---|---|---|---|
| R1 | ClickUp 포지션(JD) 쉬운 인입 | `position_registration.py`·`position_dedup.py` | partial | 실 ClickUp 쓰기 배선 0, 목적지 리스트/커스텀필드/부모-자식 없음(연봉은 후보측 R9로 이관), Discord 핸들러 없음 | PC-A1·A2a·A2b·A3·A4 |
| R2 | 포털별 송부 JD 커스터마이즈(1,899자) | `vendor/linkedin-rps-jd-set-builder.md`(prose) | partial | 실행코드 0(의사코드), 1,899 가드·컴포저·테스트 0, 3채널 전무 | PC-G1·G2·G3 |
| R3 | 최적합 후보 상시 순환으로 대기열 충전 | `harvest_runner.py`·`match.py`·`embed.py` | partial | 영속 store 미연결, 상시 드라이버 없음(dry_run만), **라이브 실행자(ExecuteHarvestItem) 구현자 0**, 운영 SOT 미배선 | PC-D1·D2a·D2b·D3·D4·D5 |
| R4 | 포털 점유/로그인/R4 양보·자동재개·봇 금지 | `queue_runner.py`·`owner_activity(wip 회수)`·`harvest_policy.py`·`rps_switch.py` | partial | owner-activity 신호원 부재, **봇방지 페이싱 primitive 없음**, 라이브 러너 R4 미배선, 상주 재개 데몬 없음, INV5 전체attach 위반 | PC-E1·F1·F2·F3·F4a·F4b·F5 |
| R5 | 검색 URL 순회 → 적합후보 등록(Humansearch) | `humansearch.py`·`humansearch_register.py` | partial | **하드제외 미배선(확정 결함)** — 정의만 있고 프로덕션 호출자 0(3면 유출)+매처 자체 우회(전문대 띄어쓰기·프리랜서 제로폭·2차검증 재현) | PC-C0·C1a1·C1a·C3a·C1b |
| R6 | JD→다각도 필터/URL 생성(3단 트라이) | `llm_keywords.py`·`channel_search_render.py` | partial | STEP C 3단·STEP E 완화 없음, 사람인/잡코리아 라이브 소비 0, 생성기 3중 병존 | PC-B1·B2a·B2b·B4·B5 |
| R7 | 포지션당 전수조사(GOLD 전량) | `humansearch.py`(트리 없음) | partial | 결과수 판단 트리 미구현(채널별 밴드), 러너가 `cards[:max_profiles]` 하드캡 + 단일페이지만 수확 → GOLD 누락 | PC-C2·C3a·C3b |
| R8 | 리스팅 페이지에서도 레쥬메 전건 저장 | `harvest_runner.py`·`portal_worker.py` | partial | 리스팅 카드 저장 레일 미연결, SOT 3중 드리프트(저장 vs 금지) | PC-C4a·C4b |
| R9 | 사람인/잡코리아 연봉·처우 자산 수집 | `models.py`(후보 필드 없음), `posting_models.py`(포지션 필드 없음) | partial | 후보측 salary 필드 부재(blocking primitive), 캡처 러너 없음. 포지션측 salary 원시필드도 부재 → 연봉은 후보 자산으로 단일화 | PC-C5·C6 |
| R10 | 후보 맞춤 JD를 "보낼 수 있는 상태"로 완성 | `jd_outreach(신규)`·`selectors.py`(발송금지) | partial | 채널별 컴포저 실행코드 0, 조립 단계 부재(발송 게이트만 완비) | PC-G1·G2·G3 |
| RE2 | (R2/R10 세부) 1,899자 하드캡 단일 불변식 실체화 | `vendor` 스펙만 | partial | 코드/테스트 어디에도 1,899 가드 없음 | PC-G1 |
| **통합** | ClickUp→검색→저장→Humansearch→Reservoir→드래프트→사람발송 한 줄기 | 전 컴포넌트 | 미조립 | 스테이지 간 실 배선(③ URL 저장·⑤ 상시 순환·라이브 실행자·⑦ 발송 게이트)이 끊겨 있음 | PC-B3·D5·D2b·D4 (글루) |

**중복 위험 지도(착수 전 반드시 회수) — 2026-07-01 git 재검증 · 2차검증 보강:**
- ClickUp 인입 3갈래: position-registration(본선) / weekly-update Gmail→ClickUp / reservoir-gmail-clickup `clickup_writer.py`(미구현). → **반드시 `position_registration.py` 확장**.
- JD→키워드 3중: `keywords.py`(고정표, 라이브가 씀) / `llm_keywords.py`(dormant) / `humansearch_cdp_run.py`(하드코딩). → **PC-B1에서 단일 진실 확정 후 확장**.
- 포털 접근 2스택: Playwright(고테스트·프로덕션 호출자 0·INV5 위반) vs raw CDP(라이브 사용·R4 가드 없음). → **세번째 스택 신설 금지**.
- JD 발송 자산: 전역 `~/.claude/skills/{saramin,jobkorea,recruit-post,position,linkedin-rps}`에만 존재(git 미추적). → **PC-G에서 회수·성문화**.
- **미병합 라이브배선 `task/ai-search-pipeline-wip`(고유커밋 1개, 971 insertions, `portal_worker.py` +209/-6 유일 미병합 편집 + `owner_activity.py`·테스트):** PC-F1·B4·D5·D3·F2·F5 착수 전 게이트0.5에서 회수/살베지 필수. `compute_yield_decision` 심볼 자체는 아직 없음.
- **⚠️ [2차검증 V2 지적·T확인] 1차 중복지도는 완결이 아니었다.** git for-each-ref 전수 재점검으로 **고유커밋 있는 미병합 브랜치 5개가 더** 발견됨: **`task/ai-search-tdd-goal-prompt`(커밋 8개 — 최대, 1차 완전 누락)**, **`task/docs-drop-v4-refs`(커밋 2개 — `multi-position-sourcing-layer-2026-06-08.md`를 편집해 PC-C4b 대상과 충돌)**, `home-wip-20260617`(2)·`task/salvage-home-wip`(2)·`task/vision-fallback-recovery`(1). → **게이트0.5 삭제/회수 결정 전, 이 전체 목록을 대상으로 재점검**(백로그 JSON `branch_facts.unmerged_partial_additional_2nd_pass`).
- 완전 병합(고유커밋 0)돼 재사용 아닌 브랜치: `ai-search-strategy-v2`(0/20)·`saramin-search-url`(0/44)·`portal-bg-login`(0/39) → 게이트6 삭제 대상.
- 미병합 동시편집 충돌: `humansearch_cdp_run.py`(multipos↔preflight), `portal_queue_executor.py`(wip↔linkedin-boolean-inject), **`multi-position-sourcing-layer-2026-06-08.md`(docs-drop-v4-refs↔PC-C4b, 2차검증 신규).**



---

## (3) 잘게 자른 백로그

> **사장님께:** 아래 한 줄이 곧 "작업방 하나"입니다. 각 줄은 검사(테스트) 하나만 통과하면 끝나도록 아주 잘게 잘랐습니다. 우선순위 P0가 먼저 막고 있는 것들입니다.

| id | 제목 | 재사용브랜치 | 요구ID | 우선 | 의존 | 인수기준(요약·전문=백로그 JSON) | SOT가드 |
|---|---|---|---|---|---|---|---|
| PC-A0 | ClickUpCreateTask 시그니처에 목적지 list_id 추가(순수 리팩터·회귀) | 신규 (position_registration.py — 다른 미병합 브랜치 미편집) | R1 | **P0** | — | ClickUpCreateTask 계약이 목적지 list_id 인자를 받도록 확장되고, 기존 run_position_registration 호출자·tests/tes… | SOT5·SOT3 |
| PC-A1 | ClickUp 실 쓰기 배선 + 목적지 리스트(FY26ClientsPosition) | 신규 (position_registration.py 확장 — position_registration.py는 다른 미병합 브랜치가 편집 안 함, 충돌 낮음) | R1 | **P0** | PC-A0 | tests/test_position_registration.py를 확장한 통합테스트가, 계약형 페이크 ClickUp 어댑터를 주입한 라이브 경로(dry_run=False)에서 비중복·confidence>=0.55 샘… | SOT5·SOT3·하드제외 |
| PC-A2a | 등록 본문 커스텀필드 매퍼(회사·직무·status·원본URL·고용형태·근무지) | 신규 (build_registration_body 확장) | R1 | P1 | PC-A1 | 신규 테스트가 필드매퍼가 회사·직무·status(segment)·원본URL·고용형태·근무지 커스텀필드를 정확히 산출함을 단… | SOT5·SOT3·연봉 |
| PC-A2b | 포지션(부모)-후보(자식) 링크 payload — 후보 스테이지 뒤 조립 | 신규 | R1 | P2 | PC-A1 | 신규 테스트가 기존 포지션(부모) task_id와 후보 결과 픽스처로부터 자식 링크 payload를 정확히 1건 생성함을 단… | SOT5·SOT3 |
| PC-A3 | register-position Discord 디스패치 핸들러(end-to-end) | task/discord-position-briefing (고유커밋 1개, discord_briefing.py) | R1 | P1 | PC-A1 | 신규 테스트가 register-position 슬래시커맨드 인가 통과 payload에서 run_position_registration이 계약형 페이크 어댑터로 정확히 1회 디스패치되고 external_posting_… | SOT3·SOT5 |
| PC-A4 | 임의 포털 URL 등록 파서 확장 + intake-posting-url 회수·병합 | task/intake-posting-url (재개/병합; request_parser.py 고유커밋 1개) | R1 | P2 | PC-A1 | request_parser 등록 경로가 사람인·잡코리아·greetinghr·programmers 포함 임의 채용 URL을 등록 인입으로 라우팅하고 SEARCH 억… | SOT5 |
| PC-B1 | JD→검색 생성기 단일화 결정(라이브 진실 확정) + 문서 회수 | main (task/ai-search-strategy-v2 병합됨 PR#30 — 브랜치 재사용 아님, main에서 분기) | R6 | P1 | — | docs/sot 또는 harness goal에 keywords.py(고정표)·llm_keywords.py(LLM)·humansearch_cdp_run(하드코딩)… | SOT5 |
| PC-B2a | generate_boolean_tiers 순수함수(정밀⊆표준⊆확장 3단) | main (task/ai-search-strategy-v2 병합됨) | R6 | P1 | PC-B1 | generate_boolean_tiers(position)가 정밀⊆표준⊆확장 단조확장 3tier를 반환하고, 3단 모두 연차·지역·Open-to-Work 토큰 미… | SOT5·SOT2·v4금지 |
| PC-B2b | 기존 boolean_query 주입 경로 = 정밀 tier 바이트 동일(회귀) | main (PR#31 inject_boolean_queries 병합; task/linkedin-boolean-inject 고유커밋 3개 미병합 — 게이트0.5 회수) | R6 | P1 | PC-B2a | 회귀 테스트가 main의 기존 boolean_query 주입 경로(llm_keywords.inject_boolean_queries)가 generate_boolean_tiers '정밀' tier와 바이트 동일함을 단… | SOT5·v4금지 |
| PC-B3 | 확보 검색 URL을 ClickUp 포지션에 저장(사람 검수 게이트 뒤) | 신규 (PC-A1 ClickUp writer 재사용) | R6,R1 | P1 | PC-A1 | 신규 테스트가 사람 검수 승인 플래그가 있는 채널별 검색 URL 묶음을 계약형 페이크 어댑터로 해당 포지션 태스크 커스텀필드/댓글에 정확히 1회 저장하고, 승인 없으면 저장 0회임을 단… | SOT3·SOT5 |
| PC-B4 | 사람인 AND/OR/NOT·잡코리아 칩 라이브 타이핑 소비 배선 | main(render_search_for_session 이미 존재) + task/ai-search-pipeline-wip 살베지 (유일 미병합 portal_worker 라이브배선; saramin-search-url은 병합·무편집이라 재사용 대상 아님) | R6 | P2 | PC-B1 | render_search_for_session 산출 입력계획을 portal_worker가 사람인 3박스/잡코리아 칩에 실제 입력하는 라이브 큐 경로에 프로덕션 호… | SOT2·SOT5·SOT3 |
| PC-B5 | STEP E 완화 재검색 루프(통과후보<목표수) | 신규 | R6 | P2 | PC-B2a, PC-E1 | 순수 함수가 통과후보수·목표수 입력에 정밀→표준→확장 단계 완화 결정을 결정론 반환하고, 무한 반복 방지(최대 단계 캡)·봇 페이싱 경계(PC-E1 페이싱 pri… | SOT2·SOT5 |
| PC-C0 | 하드제외 매처 정규화 통일 — 공백·제로폭·NFKC 단일 normalize()(2차검증 재현 우회 차단) | 신규 (humansearch.hard_exclude_reason/_is_low_tier_school 강화) | R5 | **P0** | — | tests/test_humansearch_skill.py 확장이 단일 normalize()(공백 collapse + 제로폭/포맷문자 U+200B..U+200D·U… | SOT5·하드제외 |
| PC-C1a1 | 러너 dict→CapturedProfile 재구성 어댑터(fail-closed, 무손실 요구 아님) | 신규 (models.CapturedProfile 재구성 헬퍼) | R5 | **P0** | — | 신규 테스트가 register dict→CapturedProfile 재구성 헬퍼가 가용 필드(education·employment_history[EmploymentTenure 튜플]·visible_text 등)를 복… | SOT5·하드제외 |
| PC-C1a | 하드제외 게이트를 등록 경계(register.eligible())에 배선 | 신규 (humansearch.hard_exclude_reason 재사용; task/humansearch-multipos 회피) | R5 | **P0** | PC-C1a1, PC-C0 | tests/test_humansearch_register.py에서 score>=70·유효URL이나 (a)프리랜서 마커, (b)단기이직2회 신호, (c)전문대(PORTAL_SCHOOL_CUT_CHANNELS 채널) 후… | SOT5·SOT3·하드제외 |
| PC-C1b | 발송 승격 게이트 하드제외(미래 자동발송용, 범위 한정 — 라이브 누출차단 primitive 아님) | 신규 (humansearch 점수→PositionMatch 승격 경계 확장) | R5 | P2 | PC-C1a1, PC-C3a | 자동 발송이 활성화될 때 CapturedProfile→PositionMatch 승격 지점(현행 유일 라이브 승격은 러너 humansearch_cdp_run.py:162)에 hard_exclude 통과 후보만 승격되도… | SOT5·SOT3·하드제외 |
| PC-C2 | 포지션당 전수조사 결과수 판단 트리(순수함수, 채널별 밴드) | 신규 (humansearch.py 확장) | R7 | P1 | — | plan_result_count_traversal(channel,result_count)가 docs/sot/22 result_count_decision_tree를… | SOT5·SOT2 |
| PC-C3a | 러너면 하드제외 — humansearch_cdp_run 캡처 직후 results.json 하드제외 0건 | task/humansearch-multipos (재개; humansearch_cdp_run.py) | R5,R7 | **P0** | PC-C0 | humansearch_cdp_run이 프로필 캡처(CapturedProfile prof 보유, :162 승격 직전) 직후 hard_exclude_reason(pr… | SOT5·하드제외 |
| PC-C3b | 전수조사 — cards[:max_profiles] 하드캡 제거 + collect_cards &start 다중페이지 순회 | task/humansearch-multipos (재개/병합) | R7 | P1 | PC-C2, PC-E1 | humansearch_cdp_run이 plan_result_count_traversal(PC-C2) 결정으로 GOLD 밴드 전건을 순회하고 collect_card… | SOT2·SOT5·하드제외 |
| PC-C4a | 리스팅 페이지 무조건 저장 save_rail 어댑터(코드+테스트) | 신규 (harvest_runner.SaveRail 계약 재사용 — origin/task/reservoir-harvest-queue 병합됨) | R8 | P1 | — | tests/test_listing_save_rail.py에서 M개 CandidateResultCard를 카운팅 페이크 save_rail에 흘리면 상세진입·점수게이… | SOT5·하드제외·리스팅·R4·R8 |
| PC-C4b | 리스팅-저장 SOT 드리프트 정합(§5:178·SOT25 INV6 → R8) | 신규 (문서 정합) | R8 | P1 | — | multi-position-sourcing-layer §5:178('Do not save list pages')·SOT25 INV6('상세=저장') 문구를 CLA… | SOT5·R8 |
| PC-C5 | CapturedProfile·CandidateResultCard에 salary_raw/salary_source 필드 추가 | 신규 (models.py 확장; humansearch_cdp_run 브랜치 회피) | R9 | P1 | — | tests/test_captured_profile_salary.py가 (1)salary_raw(str/None, 미확인 None=fail-closed)·salary_source 필드 존재, (2)harvest_run… | SOT5·SOT3·v4금지·연봉 |
| PC-C6 | 사람인/잡코리아 프로필 캡처·저장 러너(연봉 자산 실수집) | main (task/saramin-search-url 병합·무편집) + PC-B4 라이브 포털 배선 | R9,R8 | P2 | PC-C5, PC-B4, PC-C4a | 사람인/잡코리아 라이브 프로필에서 salary_raw 포함 CapturedProfile을 save_rail로 레포내 저장소에 무조건 저장하는 프로덕션 경로가 배선되고(리스팅-저장 레일은 PC-C4a 단일 계약 재사용… | SOT2·SOT1·v4금지·연봉·리스팅 |
| PC-D1 | save_rail → 레포내 SQLite 영속 저수지 store 바인딩(런간 누적) | origin/task/reservoir-harvest-queue (병합됨, harvest_runner 재사용) | R3,R8 | **P0** | — | run_harvest_cycle을 2회(런1:3건 발견, 런2:2건 중 1건은 런1과 canonical_url 중복) 구동하면 임시 SQLite store에 정확히 4행이 canonical_url로 중복제거 영속됨을… | INV6·SOT5·SOT3·하드제외·자립화 |
| PC-D2a | Harvest 드라이버 순수 결정함수(주기·yield·anti-bot 간격·REPO_DIR 해석) | 신규 | R3 | P1 | PC-D1, PC-F1, PC-E1 | 결정론 pytest가 (1)주기 산출, (2)owner_activity yield 시 skip 결정, (3)anti-bot 간격(PC-E1 페이싱 재사용)을 순수… | SOT2·SOT5·자립화·R4 |
| PC-D2a2 | Harvest/데몬 REPO_DIR 해석 순수함수(자립화 경로) | 신규 | R3 | P1 | — | 순수함수가 REPO_DIR을 현재 체크아웃으로 결정론 해석하고 HOME/Desktop 등 외부 경로를 배제함을 단… | SOT5·자립화 |
| PC-D2b | 상시 Harvest 드라이버 실운영(라이브 경로) — 페이크 실행자 호출횟수로 검증 | 신규 (dry_run-only launchd loop 교체) | R3 | P2 | PC-D2a, PC-D5, PC-F3 | 주입된 페이크 실행자(ExecuteHarvestItem)의 호출횟수/인자로 드라이버가 dry_run이 아닌 라이브 사이클 경로를 호출함을 결정론 단언(로그 문구… | SOT2·SOT5·자립화 |
| PC-D3 | 임베딩 영속층(Supabase pgvector) 연결 + match 라이브 소비 | origin/task/reservoir-embeddings (병합됨) + task/ai-search-pipeline-wip match.py(+8) 살베지 확인 | R3 | P1 | PC-D1 | ingest_profile_embedding이 pgvector store에 upsert하고 match_jd_to_reservoir가 런간 누적된 영속 저수지에서… | SOT5·하드제외·자립화 |
| PC-D4 | SOT25 + aisearch SKILL에 reservoir/harvest 경로 배선 | 신규 | R3 | P1 | PC-D1 | docs/sot/25 실행 스테이지와 .claude/skills/aisearch/SKILL.md가 harvest/reservoir/segment 경로를 명시 호출… | SOT5·v4금지·출력계약 |
| PC-D5 | 라이브 ExecuteHarvestItem 어댑터(GuardedPortalSearchRunner→harvest 계약, 챌린지 STOP) | task/ai-search-pipeline-wip 살베지 (portal_worker 라이브배선) + GuardedPortalSearchRunner(portal_runtime.py) 재사용 | R3,R4 | P1 | PC-F3 | GuardedPortalSearchRunner를 harvest 계약(HarvestItem→Iterable[profile], 챌린지 감지 시 STOP)으로 감싸는 어댑터가, 결정론 소비 테스트에서 프로필 Iterabl… | SOT2·SOT5·SOT1 |
| PC-E1 | 봇방지 페이싱 primitive(harvest_policy 결정론 간격·지터·최대단계 캡, SOT22 단일 출처) | 신규 (harvest_policy.py 확장 — SOT22 delay 상수 읽기) | R4 | P1 | — | harvest_policy 순수함수가 docs/sot/22의 delay 상수(random_delay_between_keywords_ms 20000~60000·sh… | SOT2·SOT5·R4 |
| PC-F1 | owner-activity detector 순수모듈(compute_yield_decision) | task/ai-search-pipeline-wip (owner_activity.py·test_owner_activity.py 미병합 선존 — 게이트0.5 회수 후 detect_owner_activity_snapshot을 순수 compute_yield_decision 계약으로 추출/개명; 신규 파일 재작성 금지) | R4 | **P0** | — | tests/test_owner_activity.py에서 compute_yield_decision가 (a)frontmost_is_chrome=True→yield=T… | SOT2·SOT5·SOT1·SOT3·R4 |
| PC-F2 | detector→라이브 러너(humansearch_cdp_run) 배선 + multipos/preflight 회수 | task/humansearch-multipos (+ origin/task/humansearch-preflight 병합) + ai-search-pipeline-wip portal_worker 살베지 확인 | R4 | P1 | PC-F1, PC-C3b | humansearch_cdp_run 순회 루프가 각 프로필 전 compute_yield_decision→worker_should_yield로 양보/재개하고 캡차… | SOT2·SOT5·SOT1·R4 |
| PC-F3 | _has_security_challenge를 SOT26 unified_regex로 통일(완전 파리티) | main (task/portal-bg-login 병합됨 — _has_security_challenge in main:portal_login.py) | R4 | P1 | — | 신규 테스트가 portal_login._has_security_challenge가 SOT26 block_detection.unified_regex 전체 토큰 집합(recaptcha·자동입력 방지·/uas/login·… | SOT1·SOT2·SOT5 |
| PC-F4a | 자동재개 데몬 순수 결정함수(idle→resume·REPO_DIR·페이크 실행자 호출횟수 경계) | 신규 | R4 | P2 | PC-D2a, PC-F1, PC-F2, PC-E1 | 결정론 pytest가 (1)idle→라이브 재개 결정, (2)크롬 점유→양보(PC-F1 재사용), (3)anti-bot 간격(PC-E1 재사용)을 순수함수로 단언… | SOT2·SOT3·SOT5·자립화 |
| PC-F4a2 | 자동재개 라이브 경로 선택 결정함수(페이크 실행자 호출횟수 + REPO_DIR) | 신규 | R4 | P2 | PC-F4a, PC-D2a2 | 주입 페이크 실행자의 호출횟수/인자로 데몬이 dry_run 아닌 라이브 경로를 선택함을 결정론 단언하고 REPO_DIR(PC-D2a2)이 이 체크아웃으로 고정됨을 단… | SOT2·SOT3·자립화 |
| PC-F4b | 상주 자동재개 데몬 실운영(라이브) + 경로 드리프트 제거 | 신규 (search-loop.sh/launchd 교체) | R4 | P2 | PC-F4a, PC-D2b, PC-D5 | 실제 상주 데몬이 손 떼면(idle) 라이브 사이클을 자동 재개하고 사장님 크롬 점유 시 양보함을 수동 확인 + verdict 증거로 축적(순수 결정은 PC-F4… | SOT2·SOT3·자립화 |
| PC-F5 | INV5 위반 제거 — portal_worker linkedin_rps 전체 attach → raw CDP 단일탭 | main (task/portal-bg-login 병합됨 — connect_over_cdp in main:portal_worker.py:513) | R4 | P2 | — | portal_worker linkedin_rps 분기가 connect_over_cdp 전체 attach를 쓰지 않고 raw 단일탭 경로를 쓰며 browser_po… | SOT2·INV5·SOT5·SOT1 |
| PC-G1 | 아웃리치 JD 1,899자 캡 가드(assert_outreach_jd_within_cap) | task/track-claude-skills (스킬 벤더링 회수 뒤에 착지) | R2,R10,RE2 | P1 | — | assert_outreach_jd_within_cap('가'*1900)은 OutreachJdCapError를 raise하고 assert_outreach_jd_wi… | SOT3·SOT5·v4금지 |
| PC-G2 | LinkedIn InMail 본문 컴포저(build_linkedin_inmail_jd, 순수함수) | task/track-claude-skills | R2,R10 | P1 | PC-G1 | tests/test_linkedin_inmail_jd.py에서 ax-sales-lead 골든 픽스처 입력에 반환 문자열이 (1)R20 회사브리핑 7요소 전부 (2)R21 P.S. CTA(valuehire.cc/res… | SOT3·SOT5·하드제외·v4금지 |
| PC-G2b | InMail 컴포저 산출이 1,899자 캡가드 통과(길이 불변식) | task/track-claude-skills | R2,R10,RE2 | P1 | PC-G2, PC-G1 | 긴 회사브리핑/JD 픽스처에 build_linkedin_inmail_jd 산출이 assert_outreach_jd_within_cap(PC-G1)을 통과(<=1899)하고, 초과 유발 픽스처에서는 OutreachJd… | SOT3·SOT5 |
| PC-G3 | 사람인/잡코리아/Gmail 채널 JD 커스터마이저(전역 스킬 회수·성문화) | task/track-claude-skills | R2,R10 | P2 | PC-G2 | 각 채널 순수 컴포저가 전역 ~/.claude/skills 자산을 회수해 구현되고, Gmail은 create_draft 초안까지만(자동 send 없음) 생성하는… | SOT3·SOT5·v4금지 |
| PC-H1 | 거버넌스 CI 자립화 — HOME 외부파일 hard-assert 제거/skip 가드 | task/track-claude-skills | R5 | P1 | — | test_skill_sot_preflight_gate·test_skill_reference_integrity가 클린 러너(HOME=/home/runner)에서도… | SOT5·자립화 |
| PC-H2 | .claude/skills git 추적 + 자립화 게이트를 verify.sh/CI에 배선 | task/track-claude-skills (재개/병합) | R5 | P1 | PC-H1 | .gitignore가 .claude/skills를 추적하고 check_self_contained.py가 verify.sh(pytest)에 배선되어 HOME 외부의… | SOT5·자립화·v4금지 |


**우선순위 근거(2차검증 반영):** P0 **8개**(PC-A0·A1·**C0·C1a1·C1a·C3a**·D1·F1). 하드제외 불변식(사장님 0순위)은 한 곳만 막으면 새므로 **매처 정확성(C0)+dict 재구성(C1a1)+등록면(C1a)+러너면(C3a)** 네 면을 모두 P0로 닫는다 — 안 부르는 것(배선)뿐 아니라 **불러도 새는 것(전문대 띄어쓰기·프리랜서 제로폭 우회, 2차검증 재현)**까지. 나머지 P0는 실 등록(A0 시그니처→A1 라이브 쓰기)·저수지 영속(D1)·R4 신호원(F1). **[정정] 종전 P0였던 PC-C1b는 대상 함수(eligible_matches_for_send)가 프로덕션 호출자 0개(dead)라 독립 누출차단이 아님 → P2(미래 자동발송용)로 강등**하고 발송면은 C1a+C3a가 닫는다. 공용 선행 primitive(페이싱 PC-E1·라이브 실행자 PC-D5)는 P1.

---

## (4) 실행 규율 (반드시 통과할 거버넌스 관문)

> **사장님께:** 아래는 "어떤 조각이든 반드시 지나야 하는 검문소"입니다. 검문소를 통과 못 하면 "됐다"고 가져오지 않습니다.

각 조각은 예외 없이 `docs/harness.md` 게이트를 순서대로 통과한다.

1. **게이트 0 — 시작자격.** `make red-ledger` GREEN(장부에 RED 없음) + 깨끗한 컨텍스트. RED가 하나라도 있으면 새 작업 금지.
2. **게이트 0.5 — 과거지시 회수(중복 구현 금지, SOT5).** 착수 전 반드시 회수: (a) 이 조각의 `reuse_branch`/관련 worktree 상태, (b) `git ls-files`·전역 `~/.claude/skills`, (c) maps/gaps의 중복 위험 지도. **신규 러너/스크립트/`clickup_writer.py`를 새로 짜지 않는다 — 기존 계약을 확장/주입한다.**
3. **게이트 1 — 스펙.** 이슈 + 인수기준 1개(이 백로그의 acceptance_criterion). 한 조각 = 인수기준 1개.
4. **게이트 2 — RED 먼저(워크트리).** `make task`로 `worktrees/<slug>` + `task/<slug>` 브랜치 생성 + 장부 RED 등록. **메인 작업트리에서 직접 소스 수정 금지.** 실패하는 테스트를 먼저 커밋한다.
5. **게이트 3 — 구현.** RED→GREEN 최소 변경. 파일 스코프를 미병합 브랜치와 겹치지 않게 최소화(예: 하드제외는 러너가 아니라 `register.eligible()` 경계에 두어 `humansearch_cdp_run.py` 충돌 회피).
6. **게이트 4a — 검증.** `./verify.sh`(= `pytest tests/ -q`) exit 0. 출력 숫자를 그대로 보고(현재 로컬 기준 614 passed + 5 subtests, 조각마다 신규 테스트 포함해 증가).
7. **게이트 4b — 2패스 적대검증(SOT5).** (1) 내가 먼저 스스로 적대적으로 깨본다(빈 값·잘못된 입력·막힌 사이트·중복·하드제외 우회·1,900자 경계). (2) `/codex:rescue`(Codex Rescue)에게 독립 2차 적대검증을 넘긴다. 두 패스와 결과를 `<slug>.verdict.json`에 Generate→Verify 증거로 축적. 둘 다 통과 전엔 "됐다" 없음.
8. **게이트 5 — 배송.** `make ship`→PR. **CI 초록 + merge 전까지 "완료" 없음.** 단 현행 CI는 HOME 외부파일 결합으로 클린 러너에서 FAIL하는 함정이 있으므로 **PC-H1을 우선 처리**해 게이트5를 실효화한다(그 전까지는 로컬 verify + 수동 확인으로 대체, 우회 사실을 verdict에 명시).
9. **게이트 6 — 종료.** merge 후 워크트리 회수·`/clear`. 병합된 stale 브랜치 정리: origin/task/reservoir-* 6종, task/humansearch-skill, **그리고 고유커밋 0으로 완전 병합된 `task/ai-search-strategy-v2`·`task/saramin-search-url`·`task/portal-bg-login`**(재사용 대상 아님). 단 `task/ai-search-pipeline-wip`은 미병합 라이브배선(portal_worker 등)이 살아 있으므로 삭제 전 PC-F1·B4·D5·D3·F2·F5가 회수/살베지 완료했는지 먼저 확인.

**공통 자립화/보고 규율:**
- **자립화 게이트:** 산출물·저장소는 레포 내부에만 둔다. `~/.vh-search-results`(HOME)·`/Users/.../Desktop/Valuehire_v5` 경로 의존 금지. `.claude/skills/aisearch/vendor/check_self_contained.py` 통과.
- **v4 금지:** AI Search는 v4 코드 절대 비의존. `Valuehire_v4` cd/import/복사 금지, v5 자체 구현만.
- **출력계약:** 후보 결과는 항상 JSON(`profile_url`·`score`·`why_fit`·`summary`), `#ai_search`로 전송.
- **보고:** 사장님께는 쉬운 한국어로(SOT 0번 규칙).

---

## (5) 리스크 · 미확정

> **사장님께:** 아직 확실하지 않아 확인이 필요한 것들과, 잘못 건드리면 위험한 지점입니다.

**최상위 리스크**
- **[2차검증 V1·T재현] 하드제외 매처 자체가 우회됨(배선과 별개의 라이브 결함).** `hard_exclude_reason`을 배선해도 매처가 샌다: `education='OO전 문 대학 졸업'`(띄어쓰기)→`None`(정상은 low_tier_school), `visible_text='프리\u200b랜서'`(제로폭)→`None`(정상은 freelancer). `_is_low_tier_school`은 공백 collapse 없음, freelancer는 `\s+`만 접고 제로폭 U+200B은 NFKC·\s 어느 쪽도 못 제거(전각 ＦＲＥＥＬＡＮＣＥ는 NFKC로 막힘). → **PC-C0(단일 normalize: 공백+제로폭+NFKC)를 P0 선행 primitive로 신설.** 즉 하드제외는 **이중 결함**(0 호출 + 매처 누출).
- **[2차검증 V2·T확인] 중복지도 미완결.** 1차 지도에서 고유커밋 있는 미병합 브랜치 5개 누락(특히 `ai-search-tdd-goal-prompt` 8커밋, `docs-drop-v4-refs`가 PC-C4b 대상 파일 충돌). → §2 지도 보강, 게이트0.5 삭제/회수 전 전수 재점검 필수.
- **하드제외 유출(현재 라이브 결함) — 유출면 3개.** `hard_exclude_reason`을 호출하지 않는 소비면이 세 곳이다: ① 러너 `humansearch_cdp_run.py`의 `results.json`, ② 등록 경계 `humansearch_register.eligible()`, ③ 발송 게이트 `humansearch.eligible_matches_for_send()`(humansearch.py:255, `score>=70·URL`만 보고 하드제외 미호출). 게다가 ③은 `PositionMatch`(candidate_url·score만, education/visible_text/employment_history 없음)를 받아 구조적으로 `hard_exclude_reason`(CapturedProfile 필요)를 **호출할 수조차 없다** → 채점→PositionMatch 승격 **전** 상류에서 걸러야 한다. → **매처정확성=PC-C0, dict재구성=PC-C1a1, 등록면=PC-C1a, 러너면=PC-C3a(모두 P0)**로 차단. **발송면 PC-C1b는 P2로 강등**(대상 eligible_matches_for_send가 프로덕션 호출자 0개=dead code, 오늘 누출은 C1a+C3a가 닫음 — 2차검증 V2·T확인). leaf 한 곳만 막으면 나머지로 샌다.
- **CI가 사장님 맥에서만 초록.** 거버넌스 테스트가 HOME 외부파일 실존을 hard-assert → 게이트5(CI 초록 후 merge)가 실효 우회. → PC-H1로 먼저 닫는다.
- **미병합 브랜치 병합 충돌(정정판).** 실제 동시편집 충돌은 `humansearch_cdp_run.py`(multipos +290 / origin/preflight +5)와 `portal_queue_executor.py`(ai-search-pipeline-wip +30 / linkedin-boolean-inject) 두 곳이다. 특히 **`task/ai-search-pipeline-wip`(미병합, portal_worker +209 유일 편집)**가 계획 전체에서 누락돼 있었다 → PC-F1·B4·D5·D3·F2·F5 착수 전 게이트0.5 회수/살베지 필수, 파일 스코프 최소화로 완화. (종전 `portal_worker.py(saramin/boolean)`·`request_parser.py·discord_routing.py` 충돌 표기는 사실오류로 철회 — §2 참조.)
- **봇처럼 굴 위험(SOT2) — 공용 페이싱 primitive 부재.** 상시 Harvest 루프(PC-D2b)·완화 재검색(PC-B5)·전수 순회(PC-C3b)·자동재개 데몬(PC-F4b)을 순진하게 짜면 창 반복개폐·URL 연타·알람 후 무한재시도가 될 수 있다. 현행 `harvest_policy`는 `worker_should_yield`(R4 양보)만 있고 sleep/jitter/interval/최대단계 캡이 전무하다. 네 조각이 페이싱을 제각각 재구현하면 드리프트한다 → **결정론 페이싱 primitive(PC-E1)를 P1 선행 조각으로 신설하고 네 라이브 조각이 depends_on으로 재사용**(SOT22 delay 상수 단일 출처). anti-bot 간격은 SOT2를 지탱하는 blocking primitive다.
- **상시 Harvest 이음매의 라이브 실행자 부재.** `harvest_runner.run_harvest_cycle`은 `execute_item`(ExecuteHarvestItem)을 주입받는데 리포 전체에 비-테스트 구현자·호출자가 0개다. 라이브 검색기 `GuardedPortalSearchRunner`는 있으나 `queue_runner`의 `ExecuteItem` 계약(시그니처 다름)에 묶여 드롭인 재사용 불가 → PC-D2b의 "실경로(dry_run 아님)"는 선언된 의존만으로 달성 불가. **PC-D5(ExecuteHarvestItem 어댑터, GuardedPortalSearchRunner 래핑·챌린지 STOP)를 선행 조각으로 신설**하고 PC-D2b·F4b가 depends_on. 그 전까지 PC-D2b는 dry_run으로만 스코프.

**미확정(구현 전 확정 필요)**
- **리스팅 저장 SOT 3중 드리프트.** CLAUDE.md R8("리스팅에서도 저장") ↔ `multi-position-sourcing-layer §5`("Do not save list pages") ↔ SOT25 INV6("상세=저장"). → PC-C4에서 R8 방향으로 같은 커밋 정합.
- **영속 저장소 대상.** 레포내 SQLite vs Supabase pgvector 확정 필요(PC-D1은 SQLite로 시작, PC-D3에서 pgvector 연결).
- **사람인/잡코리아 연봉 노출 위치 + salary 명명 단일화.** 후보 상세 DOM에 연봉/처우가 실제로 있는지, 리스팅 vs 상세 어디인지 라이브 미확인(SOT22는 연봉을 "검색 필터"로만 문서화). → PC-C5는 필드만 먼저, 라이브 셀렉터는 PC-C6에서 실측. **명명 충돌 해소:** 종전 PC-A2가 등록 본문(포지션 JD)에 `salary_raw`를 넣으려 했으나 `posting_models.py`(ExtractedPosting/PostingRecognition/RegistrationOutcome)에는 salary 필드가 전혀 없고(grep 0건) R9 blocking-primitive는 후보측 `models.py`만 가리킨다. → **연봉은 후보 자산으로 단일화**(후보측 PC-C5의 `salary_raw`만 사용), PC-A2a(커스텀필드 매퍼)에서 salary 제거. 포지션 JD 연봉이 별도로 필요해지면 그때 `posting_models` 전용 필드를 선행 조각으로 신설.
- **생성기 라이브 진실.** `keywords.py`(고정표) vs `llm_keywords.py`(dormant) vs 하드코딩 중 어느 것을 살릴지 → PC-B1에서 확정 후에만 B2/B4 진행.
- **task/track-claude-skills 병합 상태.** `.claude/`가 `.gitignore`로 무시 중 → PC-G/H 착수 전 이 브랜치 진행상황 회수 필요.

**적대검증 low·잔여 항목(반영은 하되 확정/주의 필요):**
- **(low, PC-A1) ClickUp 어댑터 시그니처 변경 파급.** `ClickUpCreateTask = Callable[[str,str], tuple[str,str]]`에는 목적지 `list_id` 인자가 없다. 인수기준에서 list_id 목적지를 단언하려면 시그니처를 확장해야 하고 `run_position_registration`의 기존 호출자·`tests/test_position_registration.py` 전부에 파급된다 → PC-A1 인수기준에 "기존 호출자/테스트 회귀 없음"을 함께 못박음(반영). 착수 시 파급 범위 재확인 필요.
- **(low, PC-F3) 챌린지 정규식 파리티 범위.** 현행 `_has_security_challenge`는 7개 용어(보안문자·CAPTCHA·2단계·인증번호·이상 접근·checkpoint·challenge)뿐이라 SOT26 unified_regex(recaptcha·자동입력 방지·/uas/login·login-cap·unusual activity·verify you·multiple sign-ins·Only one session·enterprise-authentication·authwall·protechts)를 크게 누락한다. 특히 RPS 멀티세션 락 신호 누락 → PC-F3 인수기준을 부분집합 열거가 아니라 **전체 토큰 완전 파리티**로 강화(반영).
- **(low, PC-A3/PC-C6 의존 간선) 과잉/누락.** PC-A3는 페이크 어댑터라 A1 실쓰기를 행사하지 않으므로 A3→A1은 순서 편의일 뿐(병렬 착수 가능, 인수기준에 명시). PC-C6는 리스팅-저장 계약을 PC-C4a와 공유하므로 depends_on에 PC-C4a를 추가해 레일 갈래를 단일화(반영). (PC-B3→PC-A1은 실제 ClickUp writer가 필요하므로 유지.)
- **(low→반영, PC-C5) 인수기준에서 게이트0 전제 분리.** `make red-ledger GREEN`은 게이트0 시작자격 전제조건이지 이 조각의 인수기준(게이트1)이 아니다 → 인수기준에서 분리 표기(범주 오류 제거).
- **(잔여 리스크, PC-D2b/PC-F4b) 상주 데몬은 단일 pytest로 완결 판정 불가.** 항상-켜진 데몬은 verify.sh exit 0 한 방으로 "완료"를 기계 판정할 수 없다 → 순수 결정함수(PC-D2a/PC-F4a)로 기계검증하고 실경로 여부는 **주입한 페이크 실행자 호출횟수**로 판정(로그 문구 아님), 실제 상주 운영은 수동 확인 + verdict 증거로 축적한다(설계상 잔여 리스크).
- **(미확정, PC-B4/PC-D5 살베지 범위) ai-search-pipeline-wip 회수 단위.** wip의 고유커밋 1개에 971 insertions가 19파일로 뭉쳐 있어 조각별로 잘라 살베지하는 것 자체가 위험하다. 착수 전 게이트0.5에서 portal_worker 슬라이스만 떼어 회수할지, 브랜치를 먼저 정리(salvage/close)할지 확정 필요.

---

_생성: 2026-07-01 · 근거 문서 = CLAUDE.md(SOT) · docs/harness.md · maps/gaps 조사. 이 Spec은 게이트 1(스펙) 산출물이며, 각 조각은 별도 worktree에서 RED→GREEN→2패스로 전진한다._

---

## 적대검증 반영 로그 (2026-07-01)

> 적대적 검증관 4렌즈(중복·SOT·원자성·의존순서)의 지적을 실제 git·소스로 재검증한 뒤 반영했다. 백로그 29 → **37 조각**. 모든 인용 사실은 `git rev-list --left-right`·`git diff --name-only`·소스 grep으로 재현 확인함(반영 전 검증 = SOT5).

### A. 중복 렌즈 (duplication)
- **[high 반영] PC-F1 재사용브랜치 정정.** `owner_activity.py`·`test_owner_activity.py`는 `신규`가 아니라 미병합 `task/ai-search-pipeline-wip`에 이미 존재(main엔 없음, 검증). reuse_branch를 그 브랜치로 바꾸고 "회수한 detector를 순수 `compute_yield_decision` 계약으로 리팩터, 신규 파일 재작성 금지"로 명시. (단 `compute_yield_decision` 심볼 자체는 wip에도 없음 → 계약은 신규.)
- **[high 반영] ai-search-pipeline-wip 누락 복구.** 이 미병합 브랜치(고유커밋 1개·971 insertions)가 `portal_worker.py`(+215, 유일 미병합 편집)·`portal_queue_executor.py`(+30)·`match.py`·`dry_run.py`·`queue_runner.py`·`scoring.py`·`portal_login.py`를 재작성함을 확인. §2 중복지도·최상위 리스크에 추가하고 PC-B4·D3·F2·F5·신규 PC-D5가 게이트0.5에서 회수/살베지하도록 배선. PC-B4 재사용브랜치를 "병합·무편집"인 saramin-search-url에서 wip 살베지로 교체.
- **[med 반영] 완전 병합 브랜치 6곳 재라벨.** ai-search-strategy-v2(0/20)·saramin-search-url(0/44)·portal-bg-login(0/39)은 고유커밋 0 = 재사용/재개 대상 아님(재사용 코드는 이미 main에). PC-B1·B2a·B4·C6·F3·F5의 reuse_branch를 "main(병합됨)"으로 바꾸고 게이트6 삭제 대상에 추가.
- **[med 반영] §2 충돌 목록 정정.** 종전 `portal_worker.py(saramin/boolean)`·`request_parser.py·discord_routing.py 동시수정`은 사실오류(git 확인: saramin 병합·무편집, boolean은 portal_worker 미편집, request_parser는 intake만·discord는 discord_briefing만) → 철회. 실제 충돌 `portal_queue_executor.py`(wip↔boolean) 추가, `humansearch_cdp_run.py`(multipos↔preflight) 유지. PC-A3·A4 공유파일 없음 → SOT가드 프레이밍 완화.

### B. SOT 렌즈
- **[high 반영] 하드제외 유출면 3개.** 발송 게이트 `eligible_matches_for_send`(humansearch.py:255)는 `PositionMatch`(profile 필드 없음)를 받아 `hard_exclude_reason`을 호출 불가함을 확인. PC-C1을 **C1a(등록면+dict→CapturedProfile 무손실 재구성·fail-closed)** / **C1b(발송면: 승격 전 상류 필터)**로 분리, 러너 results.json면은 PC-C3에서 차단. 세 면 모두 P0/필수로 명시.
- **[med 반영] 채널별 밴드.** SOT22는 사람인/잡코리아 5~80, RPS 5~60으로 임계가 다름을 확인. PC-C2 인수기준을 채널별 파라미터라이즈(사람인/잡코리아 80·300 경계 포함)로 강화하고 "RPS 60 상한 전채널 복사 금지"를 SOT가드에 못박음. PC-C3에 collect_cards start 오프셋 다중페이지 순회 추가(라이브 가짜 GREEN 방지).
- **[med 반영] 하드제외 데이터 형상.** 러너 dict엔 ocr_text 없음·employment_history가 dict라 fail-open 위험 확인 → PC-C1a에 무손실 재구성·재구성 실패 시 fail-closed 단언 추가.
- **[med 반영] 포지션측 연봉 부재.** `posting_models.py`에 salary 필드 0건 확인 → 연봉을 후보 자산으로 단일화(PC-C5만), PC-A2에서 salary 제거. §5 미확정에 기록.
- **[med 반영] PC-D1 로그 입도.** `run_harvest_cycle`은 아이템당 1건(in=out=N) 로그이고 SaveRail은 None 반환이라 프로필당 로그 주입 불가 확인 → 인수기준을 "아이템당 로그 + SQLite 프로필당 행"으로 정합.
- **[low 반영·기록] PC-A1 list_id 시그니처, PC-F3 정규식 완전 파리티** → §5 low 항목에 남김(인수기준에도 최소 반영).

### C. 원자성 렌즈
- **[high 반영] PC-B2 분리** → B2a(순수 3단 생성) + B2b(기존 주입=정밀 tier 바이트 동일 회귀, PR#31 대상).
- **[high 반영] PC-A2 분리** → A2a(커스텀필드, 연봉/부모자식 제외) + A2b(부모-자식 링크, 후보 스테이지 뒤). 연봉은 PC-C5로.
- **[high 반영] PC-C4 분리** → C4a(리스팅 save_rail 코드+테스트, depends 없음) + C4b(SOT 드리프트 문서 정합). C4→D1 과잉 의존 제거.
- **[med 반영] PC-C1 전문대 케이스** 누락 → C1a 인수기준에 (c) 전문대(학교컷 채널) 0건 추가.
- **[med 반영] PC-D2/PC-F4 측정불가** → 각각 순수 결정함수(D2a/F4a, 페이크 실행자 호출횟수로 판정) + 상주 운영(D2b/F4b, 수동 verdict)으로 분리.
- **[low 반영] PC-C5** 인수기준에서 `make red-ledger`(게이트0 전제)를 분리.

### D. 의존순서 렌즈
- **[high 반영] 라이브 실행자 이음매.** `ExecuteHarvestItem` 구현자·호출자 0개 확인(GuardedPortalSearchRunner는 다른 계약) → **신규 PC-D5(어댑터, 챌린지 STOP)** 신설, PC-D2b·F4b가 depends_on. 그 전 PC-D2b는 dry_run 스코프.
- **[med 반영] PC-C4→PC-D1 과잉 직렬화 제거**(C4a depends 없음).
- **[med 반영] 봇방지 페이싱 primitive 부재** → **신규 PC-E1**(harvest_policy 결정론 간격/지터/캡, SOT22 단일출처) 신설, PC-B5·C3·D2a·F4a가 depends_on 재사용.
- **[low 반영] PC-A3→PC-A1 최소화 명시, PC-C6→PC-C4a 의존 추가**(리스팅-저장 레일 단일화). PC-B3→PC-A1은 정당하므로 유지.

### 반영하지 않은/부분 반영 지적 (근거·판단)
- **SOT#1의 "러너를 채점-전 초크포인트로" 원안은 부분만 채택.** 하드제외를 러너(`humansearch_cdp_run`) 안으로 옮기면 PC-C1이 애초에 회피하려던 multipos/preflight 동시편집 충돌을 되살린다. 그래서 러너면은 러너를 이미 편집하는 **PC-C3**에서 차단하고, 등록·발송면은 C1a/C1b로 분리해 충돌 없이 3면을 닫는 쪽으로 합성 반영. (원안의 "3면 차단" 의도는 완전 수용, 배치만 충돌회피형으로 조정.)

_반영자: 수석 엔지니어 · 검증: git/소스 재현 · 절차: harness 게이트1 스펙 갱신(코드 변경 아님, 후속 조각이 각 worktree에서 RED→GREEN→2패스로 이행)._


---

## 적대검증 반영 로그 (2026-07-02 · 2차 독립검증 G→V1(Codex)→V2(리셋 Claude)+T)

> `/strict-portable` L3. G(이 문서·1차 4렌즈)를 **다른 도구(Codex=V1)·리셋 컨텍스트(Claude=V2)·기계 재실행(T)**가 다시 깼다. 장부: `valuehire-pipeline-consolidation-spec.verdict.json`.

**3자 일치(사실):** 문서의 뼈대 사실 10개(브랜치 병합상태·hard_exclude 0호출·owner_activity 미병합·salary/1899 부재·러너 하드캡·HOME assert)는 T·V1·V2 모두 CONFIRMED. 기존 테스트 `614 passed, exit 0`(로컬). Codex의 "verify 실패"는 codex 샌드박스 임시폴더 부재 오탐 → T로 반증.

**착수 전 반드시(백로그 29→37→44):**
- **[V1·T재현 high] 하드제외 매처 우회 2건** → 신규 **PC-C0**(공백·제로폭·NFKC 단일 normalize, P0). 하드제외는 배선(0호출)+매처(누출) 이중 결함으로 격상.
- **[V2·T확인 high] PC-C1b 오지정** — 대상 `eligible_matches_for_send`는 프로덕션 호출자 0(사람 발동), 유일 라이브 승격은 러너 `humansearch_cdp_run.py:162`. → C1b **P0→P2 강등·재작성**(미래 자동발송용), 발송면은 C1a+**신규 C3a(러너면 P0)**가 닫음. 러너면을 3-dep P1에서 P0로 승격.
- **[V2·T확인 high] 중복지도 미완결** — 미병합 브랜치 5개 누락(`ai-search-tdd-goal-prompt` 8커밋 등), `docs-drop-v4-refs`↔PC-C4b 파일 충돌 → §2 보강.
- **[V1·V2 high] 원자성 위반 6조각 분할:** A1→**A0**(시그니처)+A1(라이브 쓰기), C1a→**C1a1**(재구성)+C1a(게이트), C3→**C3a**(러너면)+**C3b**(전수 페이지네이션), D2a→D2a+**D2a2**(REPO_DIR), F4a→F4a+**F4a2**(라이브경로), G2→G2+**G2b**(1899 캡). 그래프 재검증: 순환 0·의존누락 0·P0가 비-P0 의존 0.
- **[V2 med] PC-C1a1 "무손실 재구성" 불가** — 원본 dict에 ocr_text 결손 가능 → "무손실" 삭제, 가용필드 복원+결손 fail-closed로 재정의.

**반영 안 함/후속:** llm_keywords 빈 boolean_query fail-open, harvest_runner 이벤트루프 async 버그는 V1(Codex) repro만 있고 T 미재현 → 백로그 아닌 `verdict.json`에 PLAUSIBLE로 남기고 해당 조각(PC-B2b·PC-D5) 착수 시 재현·처리. portal_worker "+215"→"+209" 정정(무해).

_반영: git 재실행·소스 grep·라이브 repro로 검증. 코드 변경 아님(스펙 게이트1 갱신). 상태 = 진행중(각 조각 worktree에서 RED→GREEN→2패스)._
