# 저수지 확장 — Gmail 수집 + 운영 임베딩 + ClickUp 매칭 기록 (Goal Prompt)

> 이어지는 단계: `docs/ai-search/reservoir-model-implementation-goal-prompt.md`(커밋 1~6, 이미 main 머지)의 **연속 커밋 7~11**.
> 근간 비용분석: 「이력서 ↔ 포지션 매칭 비용 경제성 분석」(2026-06-19, Supabase 실측). 임베딩 백필 $0.07 1회 → pgvector $0 → `claude -p` $0.
> 사용법: 아래 코드블록 전체를 복사해 `/goal ` 뒤에 붙여넣는다. 기본은 **커밋 7만** 시작.

---

## 현재 실측 상태 (착수 전 반드시 대조)

기존 reservoir 엔진(커밋 1~6)은 **인터페이스·로직·테스트는 완성, 운영 배선은 스텁**이다:
- `tools/multi_position_sourcing/embed.py` — sha1 해시 임베더(**256d**, 순수파이썬) + `InMemoryEmbeddingStore`.
  주석 명시: *"운영 임베더(OpenAI/Supabase)는 동일 시그니처로 주입 교체", "운영은 Supabase pgvector(`profile_embeddings`)로 교체"*. → **주입 심(seam)이 이미 설계돼 있음.**
- `tools/multi_position_sourcing/match.py` — 인메모리 `ReservoirEntry` top-K 코사인 + `scoring.py` 재랭킹. `valuehire_vector_search` RPC 미연결.
- `tools/multi_position_sourcing/clickup_activity.py` — **결과 본문 포맷터 이미 존재**(Profile URL/점수/why-fit/why-not/요약). ClickUp **API 쓰기만 빠짐**.
- `docs/ai-search/embeddings.sql` — `profile_embeddings(canonical_url, segment_id, source_channel CHECK(saramin|jobkorea|linkedin_rps|public_web), embedding **vector(256)**, model 'sha1-hash-256-v1')`.
- Gmail 수집 / `claude -p` 내러티브 / 실 OpenAI 임베딩 / ClickUp API 쓰기 = **전부 미구현**.

### ⚠️ 착수 전 사람(사장님/Supabase) 확인 — 코드와 레포트의 불일치
1. **저수지 테이블 정체** — 레포트의 `pipeline_candidates`(7,427건)와 엔진의 `profile_embeddings`가 같은 풀인가, 별개인가?
   - 같으면: 테이블명·스키마 통일. 다르면: 둘을 잇는 브리지(또는 `pipeline_candidates`를 운영 store로 채택) 결정.
2. **임베딩 차원** — 엔진 스키마 `vector(256)`(sha1 스텁) vs 레포트 `text-embedding-3-small` **1536d**. 운영 전환 = 컬럼 차원 256→1536 마이그레이션 + 모델 교체.
3. **`valuehire_vector_search` RPC** — 실제 시그니처(`query_embedding`, `match_count`, 세그먼트 필터 여부) 확인.
4. **`claude -p` 무료 보장** — 호출 시 `ANTHROPIC_API_KEY` 비운 환경(Max 구독, $0)인지 확인.

---

## 복붙용 Goal 블록

```
docs/ai-search/reservoir-model-implementation-goal-prompt.md(커밋 1~6, main 머지 완료)를 잇는 커밋 7~11을 harness 표준 루프로 단계적 구현한다. 목표: ① Gmail에 받은 레쥬메를 저수지에 수집, ② 스텁 임베더/스토어를 운영(OpenAI 임베딩 + Supabase pgvector)으로 교체, ③ 매칭 결과를 ClickUp에 자동 기록. 모두 tools/multi_position_sourcing/ 위에서 증분으로, 기존 주입 심(Embedder 타입·store 인터페이스)을 깨지 않고 갈아끼운다.

[워크트리 규칙] main은 읽기 전용. 한 커밋 = 이슈 1개 = 워크트리 1개(worktrees/<name>, 브랜치 task/<name>) = 인수기준 1개. make task NAME=... 로 파고, RED 테스트→구현→verify→make ship(PR)→CI 초록→merge→worktree 정리까지 그 안에서 끝낸다. 메인 직접 수정 금지.

[구현 형태] 엔진(수집·임베딩·매칭·ClickUp 쓰기)은 tools/ 코드로 구현하고 pytest로 검증한다. 스킬(skills/)은 "저수지 돌려/매칭 기록해줘" 진입점과 사람 검수 게이트(경계선·발송 직전 확인)만 얇게 맡는다. 매칭·점수·기록 본문 로직을 스킬 텍스트로 구현하지 않는다(재현성). clickup_activity.py의 기존 본문 포맷터를 재사용한다(중복 구현 금지).

[비용 헌법 — 레포트 확정, 절대 위반 금지]
- 전건 LLM 매칭 금지(7,427 × 포지션 = 호출 폭발). 항상 pgvector로 top-K(10) 좁힌 뒤 LLM은 top 3~5 내러티브에만.
- 임베딩은 신규/변경 후보만 1회 생성 후 영구 재사용(embedding IS NULL/해시변경만). 매 쿼리 재생성 금지.
- 매칭·내러티브 LLM은 claude -p(Max 구독, $0). ANTHROPIC_API_KEY 경유(유료) 금지 — 호출 시 키 비운다.
- 운영 임베딩은 OpenAI text-embedding-3-small(1536d). 1회 백필 약 $0.07 실측 로그를 남긴다.

[관측가능성 — 모든 단계 공통, 생략 금지] 기존 reservoir_log 스키마(JSON 1줄: ts,run_id,machine,segment_id,site,line,in_count,out_count,dropped_count,status,fail_reason,latency_ms)를 새 라인에도 그대로 쓴다. fail-closed: 빠진 건수·이유를 반드시 로그로 남긴다. 로그 스키마는 verify 계약 테스트로 검증.

[열거형·타입 3곳 동시확장 — P1, 하나라도 빠지면 런타임 reject] 새 채널/라인을 추가할 땐 반드시 같은 커밋에서 아래 3곳을 함께 고친다(검증서 확인된 구멍):
- models.py:7 `Channel` Literal(현재 saramin|jobkorea|linkedin_rps|public_web)에 `'gmail'` 추가.
- reservoir_log.py:17 `RESERVOIR_LINES`(현재 harvest|index|match|calibrate|send)에 `'narrate'`·`'clickup_write'` 추가.
- embeddings.sql `source_channel CHECK`에 `'gmail'` 추가.
세 곳 중 하나만 빠져도 site='gmail'/line='narrate' 로그는 `ReservoirLogContractError`로 거부된다(reservoir_log.py:88). 확장 단언+픽스처를 같은 커밋에(자기확장).

[커밋 — 순서대로, 한 번에 하나]
7. Gmail 레쥬메 수집(새 Harvest 채널): Gmail에서 레쥬메(첨부 PDF/DOCX/본문) 식별→파싱→CapturedProfile로 정규화→기존 ingest_profile_embedding 경로로 저수지 적재.
   - [P1 멱등키 데이터모델 — 구현 전 필수] 기존 적재 경로는 canonical_url(=profile.profile_url) 단일키로 dedup한다(dedup.py:15, embeddings.sql canonical_url unique). 그런데 Gmail 레쥬메는 외부 profile_url이 없을 수 있다 → CapturedProfile.profile_url은 필수 필드(models.py:84,104)라 비울 수 없다. 따라서 **합성 canonical 키 `gmail://<message_id>` 규칙**을 정의해 profile_url에 채우고, 그게 곧 멱등키가 되게 한다(같은 메일=같은 message_id=같은 canonical → 재적재 0). dedup.canonical_profile_url의 비-http(`gmail://`) 입력이 깨지지 않게 fallback을 추가하고 그 픽스처+테스트를 같은 커밋에. 메일 본문에 LinkedIn/포털 URL이 있으면 그걸 우선 canonical로, 없을 때만 `gmail://<message_id>`.
   - source_channel='gmail'은 위 [열거형 3곳 동시확장] 규칙대로 Channel·CHECK·RESERVOIR_LINES와 함께 추가.
   - 신규 gmail_ingest.py. site='gmail', line='harvest'/'index' 로그.
   - RED: ① 동일 메일 2회 수집→프로필 1건(멱등, canonical=`gmail://msgid`로 dedup) ② URL 없는 레쥬메도 적재되고 재수집 시 0 ③ 첨부/파싱 실패 메일 fail-closed 로깅(dropped+사유) ④ 파싱 결과가 세그먼트로 분류.
8. 운영 임베더·스토어 주입(스텁→실물): embed.py의 Embedder를 OpenAI text-embedding-3-small(1536d)로, InMemoryEmbeddingStore를 Supabase pgvector store로 주입 교체(시그니처 불변). embeddings.sql 차원 256→1536 마이그레이션(또는 pipeline_candidates 채택 — 착수 전 확인 1·2 결정 반영). embedding IS NULL 후보만 배치(100건) 백필하는 backfill 엔트리. 약 $0.07 실측 비용 로그. RED: 백필이 NULL만 채우고 재실행 시 추가 0(멱등), 차원·모델이 스키마와 일치.
9. 매칭 실연결 + claude -p 내러티브: match_jd_to_reservoir를 Supabase 벡터검색(valuehire_vector_search 또는 pgvector top-K=10)에 연결. top 3~5만 claude -p haiku로 잘맞는점/안맞는점/프로필요약 생성→ai_assessment에 영속화(있으면 스킵, 재호출 0). claude -p는 ANTHROPIC_API_KEY 비운 환경에서 호출($0). 신규 narrate.py. line='narrate' 로그. RED: 같은 JD·같은 저수지면 같은 순서(결정론), 내러티브가 이미 있으면 LLM 미호출, LLM 호출 수 ≤ 설정 상한.
10. ClickUp 기록 출력: 선택 후보를 ClickUp FY26AI_Search(list 901818680208)에 부모task(고객사명, 포지션명-YY.MM.DD / 본문=JD) + 후보별 서브task로 기록. 서브task 본문은 clickup_activity.format_clickup_activity_comment 재사용(Profile URL/점수/why-fit/why-not/요약). 작성한 subtask id 영속화→재매칭 시 중복 생성 금지(갱신). 직무 카테고리=FY26ClientsPosition status로 세그먼트 필터. 신규 clickup_writer.py(api.clickup.com, CLICKUP_API_TOKEN). line='clickup_write' 로그. SOT 3번(보내기=사람 게이트): 기록은 사람 검수 승인 후에만. RED: 템플릿 정확 생성, 동일 포지션 재기록 중복 0, 토큰이 코드 밖 노출 안 됨.
11. Chrome Extension(얇은 진입점): ClickUp 포지션 task를 연 상태에서 버튼→task_id 획득→자사 백엔드 /match 호출→후보 패널(점수·why-fit/why-not·요약) 표시→사람이 체크박스로 선택→"ClickUp에 기록"(커밋 10 경로). ClickUp/Supabase/OpenAI 키는 Extension에 두지 않고 백엔드에만. MV3, app.clickup.com 호스트 권한, content script+side panel. RED(E2E): 실 포지션 1건 end-to-end 완주, Extension 번들 grep에 키 0건.

[SOT 불변식 — 절대 약화 금지] 3사 자동로그인 안 막음 · 맥북 Chrome 점유 시 무인 워커 즉시 정지(R4) · "보내기/기록"은 사람이 마지막에 누름(자동발송·자동기록 금지) · 사장님께 쉬운 한국어 보고 · 내 코드는 두 번 깐다(나 먼저 적대검증 → Codex Rescue 2차).

[완료 판정 숫자] 임베딩 백필 후 NULL 0(또는 사유 로깅된 잔여만)·실측 ≈$0.07 · 포지션 추가매칭 LLM 비용 $0(Max) · 매칭 top-20 적합도≥85 비율 ≥70% · 동일 포지션 재매칭 편차 ≈0 · ClickUp 재기록 중복 0.

지금은 커밋 7(Gmail 수집)만 시작한다.
```

---

## 커밋 요약

| # | 기능 | 한 줄 | 형태 | 신규 파일 |
|---|---|---|---|---|
| 7 | Gmail 수집 | 받은 레쥬메를 저수지에 무조건 저장(멱등) | 코드 | `gmail_ingest.py` |
| 8 | 운영 임베딩 | 스텁→OpenAI 1536d + Supabase pgvector, $0.07 백필 | 코드 | embed.py 주입 + 마이그레이션 |
| 9 | 실매칭+내러티브 | pgvector top-10 → claude -p top5 근거($0) | 코드 | `narrate.py` |
| 10 | ClickUp 기록 | FY26AI_Search 부모/서브태스크 자동 작성 | 코드 | `clickup_writer.py` |
| 11 | Chrome Extension | 포지션 화면에서 매칭→검수→기록(사람 게이트) | 코드+사람 | extension/ |

- **재사용(중복 구현 금지):** 본문 포맷=`clickup_activity.py`, 적재 경로=`ingest_profile_embedding`, 매칭=`match_jd_to_reservoir`, 점수=`scoring.py`, 로그=`reservoir_log.py`, 주입 심=`embed.py`의 Embedder/store.
- **비용:** 백필 1회 $0.07 → 이후 포지션 추가매칭 영구 $0(pgvector + claude -p Max).
- **사람 게이트(SOT 3):** ClickUp 기록은 자동 발송이 아니라, Extension에서 사람이 검수·승인한 후에만 작성.

---

## 적대 검증 로그 (G→V1→V2, 2026-06-20)

G=Claude(작성) → V1=Codex(독립 적대검증) → V2=Claude 리셋(V1 재반박). 모든 결정적 증거는 오케스트레이터가 코드 `파일:라인`으로 직접 재확인함.

| 항목 | V1 판정 | V2 재판정 | 최종(오케스트레이터 확정) | 증거 |
|---|---|---|---|---|
| Gmail 멱등키/profile_url 충돌 | (놓침) | **신규 P1** | **확정 결함** | `models.py:84,104` `profile_url: str`(필수), `dedup.py:15` canonical은 URL 전제, `embeddings.sql:10` `canonical_url unique` — Gmail message_id 저장처 없음 |
| enum/타입 3곳 동시확장 | 8b 타당 | J1 보강 | **확정 결함** | `reservoir_log.py:17` LINES=(harvest,index,match,calibrate,send), `models.py:7` Channel=(saramin,jobkorea,linkedin_rps,public_web) — 'gmail'/'narrate'/'clickup_write' 거부됨 |
| status→segment 매핑 부재 | 치명적 | 과장→보통 | **확정 결함(보통)** | `segments.py:20` 세그먼트 5개 vs FY26ClientsPosition status ~13개, 매핑 코드 없음 |
| claude -p 세션한도 | 치명적 | 과장→보통 | **확정 결함(보통)** | `docs/ai-search/discord-search-timeout-recovery-2026-06-09.md` 세션한도 장애 이력 실재, fail-closed RED 미요구 |
| cosine 차원 가드 | 7 잔여 | 유지 | **확정 결함(경미)** | `embed.py:56` `zip(av,bv)` 차원 다르면 silent truncate, 테스트 미커버 |
| $0.07 토큰 상한 | 5 타당 | 유지 | **확정 결함(경미)** | `embed.py:64` 임베딩 텍스트 길이상한 없음 |
| clickup_activity 재사용 | 1 보통 | 유지 | **확정 결함(경미)** | `clickup_activity.py:12` comment 포맷터, `candidate_url`이 LinkedIn 보장 안 됨 → subtask body 어댑터 필요 |
| 백엔드 /match 부재 | 치명적 | **false positive** | **기각(범위표기만 보완)** | 문서가 백엔드를 Phase 11 "구현 지시"로 명명, 존재 단정 아님. 단 신규파일표에 백엔드 누락 |
| ClickUp list ID 불일치 | 치명적 | **false positive** | **기각** | `search-access.md:424` FY26 candidates=901814621142/clients=901814621569와 별개. `901818680208`=**FY26AI_Search**(라이브 ClickUp로 확정), 정상 |
| 미구현 모듈 명명(gmail_ingest 등) | 치명적 | 정상 | **기각** | goal prompt가 신규 모듈을 명명하는 것은 본질 |

**집계:** 확정 결함 7(P1×2 + 보통×2 + 경미×3) / 기각 3(V1 false positive 2 + 과장 분류 1).

## 교정 지시 — 구현 전 Phase 블록에 접어 넣을 것 (검증 반영)

- **[P1 ✅ 본문 반영 완료] 커밋 7 Gmail 데이터모델 충돌 해소:** 합성 canonical 키 `gmail://<message_id>` 규칙 → 커밋 7 본문 "[P1 멱등키 데이터모델]"에 접어 넣음.
- **[P1 ✅ 본문 반영 완료] enum·타입 3곳 동시확장:** `Channel` Literal + `RESERVOIR_LINES` + `embeddings.sql CHECK` → 관측가능성 절 "[열거형·타입 3곳 동시확장]"에 접어 넣음.
- **[P2] 커밋 9 claude -p fail-closed:** Phase 9 RED에 "세션한도/rate-limit 초과 시 fail-closed 로깅 + graceful skip(빠진 건수·이유 기록), 자동 재시도 백오프" 추가. 과거 장애(2026-06-09) 재발 방지. claude -p 호출은 ANTHROPIC_API_KEY 비운 환경 + 타임아웃 래퍼로.
- **[P2] 커밋 10 status→segment 매핑:** ClickUp ~13 status를 5 segment로 접는 **결정론 매핑 테이블**을 명세하고 RED로 고정(예: backend/frontend/devops/app/ai-ml/data → it_ai_data 등). status는 `segment_for_position`에 직접 안 들어가므로 status→RoleFamily→segment 변환부 신설.
- **[P2] 신규파일 요약표 정정:** 커밋 11에 백엔드 HTTP 서버(예: FastAPI `app/` 또는 `tools/.../match_api.py`)가 **신규 구축 대상**임을 표에 명시(현재 `extension/`만 적혀 범위 과소표기). Extension은 이 백엔드를 호출.
- **[P3] 커밋 8 차원 가드:** `cosine_similarity`에 `len(a)==len(b)` 단언 추가 + 256/1536 혼재 RED. 백필 전 구·신 차원 혼재 금지.
- **[P3] 커밋 8 토큰 상한:** OpenAI 임베딩 입력에 토큰 상한(truncate) 적용해 $0.07 견적 보호. 실측 비용 로그 필수.
- **[P3] 커밋 10 본문 어댑터:** `clickup_activity.format_clickup_activity_comment`는 comment용이므로 subtask **description** 본문용 어댑터를 얇게 추가(LinkedIn URL 없으면 후보 출처 URL로 대체 표기).

> **비용 헌법·아키텍처 결론은 유효함**(백필 1회 후 영구 $0, 2단계 검색). 위 교정은 데이터모델·런타임 계약·범위 정직성의 구멍을 막는 것이며, 전략 자체를 뒤집지 않는다.
> ⚠️ 이 문서는 현재 git untracked다. main 커밋 시 worktree 규율(`make task`)로 올린다.
