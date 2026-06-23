# AI Search 전략 v2 — Goal 문서 (2026-06-22)

> 대상 레포: `Valuehire_v5` (`tools/multi_position_sourcing/`). SOT: `CLAUDE.md`·`docs/harness.md`.
> 위험등급 L3 (공유 모듈 + SOT 불변식 변경 + 마이그레이션). 한 번에 한 조각, RED→GREEN, 세 번 깨기.
> 사장님 지시(2026-06-21~22) 5개 작업묶음을 기록. 작업방 `task/ai-search-strategy-v2`.

---

## 현재 상태 (직접 연 file:line — 추측 금지)

- **5분류 룰(제거 대상):** `grouping.py:11~19 ROLE_SIGNALS`(부분문자열 카운트로 7 RoleFamily 분류),
  `grouping.py:33~42 infer_role_family`, `segments.py:20~26 CANONICAL_SEGMENTS`(5개),
  `segments.py:39~48 SEGMENT_BY_FAMILY`. 키워드도 하드코딩표: `keywords.py:5 PORTAL_STANDARD_WORDS`,
  `grouping.py:21~30 CORE_KEYWORDS`. → **LLM이 JD를 이해해 키워드 뽑는 방식**으로 교체.
- **segment_id 적재면(연쇄 주의):** `match.py:69 in_segment 필터`, `harvest_runner.py`(segment 구동 큐),
  `embed.py:122/136`, `reservoir_log.py:23/46/61`, `models.py:72`.
- **owner 양보(수정 완료분):** `owner_activity.py detect_owner_activity_snapshot`(foreground앱+유휴시간,
  키내용 안 읽음, fail-closed), `queue_runner.py:66~73`(감지시 stopped→pending 보존, 다음 사이클 재검사로
  암묵 재개). 보존 브랜치 `task/ai-search-pipeline-wip`(362 tests GREEN).
- **검색 결과 대기(보존분):** `portal_worker.py wait_for_search_results`(empty vs timeout 분류, 상한 15s).
- **봇 행동 문제(사장님 실측):** 자동화가 혼자 창 open/close 반복, URL 연속 입력, 알람 뜬 뒤 같은 시도 반복.

## 핵심 질문 / 근본 원인

1. JD를 **사람 헤드헌터 수준으로 이해**해 사이트별(AND/OR·국영문·띄어쓰기·축약어) 최적 키워드를 뽑는가?
2. 5개 고정 분류라는 **틀에 욱여넣는 손실**을 없애되, segment_id에 의존하는 match/harvest를 안 깨는가?
3. owner가 쓰면 **잠깐 멈췄다 자동 재개**(방치 금지)되는가? 봇처럼 안 구는가?
4. 0건이 나오면 **"필드에 키워드가 진짜 들어갔나"부터 의심**하는가?

## 작업묶음 (요구사항 추적표)

| ID | 작업 | 인수 기준(기계 단언 위주) | 의존 |
|---|---|---|---|
| **W0** | SOT #2 재작성 (잠깐 멈춤+자동재개+봇금지) | CLAUDE.md #2 문구 교체 ✅(이 커밋) | — |
| **W1** | 방어적 브라우저 조작 4원칙 적용 | pre-flight(URL tutorial/auth·로그인팝업 텍스트 감지) / 모달 진짜열림 교차검증 / 셀렉터 느슨+3타임아웃→스크린샷 비전좌표 / 실패→`docs/engineering/selectors-error-ledger.md` append·다음실행 선독 | W0 |
| **W2** | 양보→**상주 poller 자동재개** + 봇행동 가드 | owner활성→pause, 유휴→resume를 **반복 루프**로 단언(가짜 어댑터) / 같은 실패 N회 반복 차단 | W0, WIP 머지 |
| **W3** | 3사 병렬 서치 | 사람인·잡코리아·링크드인 동시, **사장님 창과 분리된 전용 컨텍스트** | W1, W2 |
| **W4** | LLM 키워드 고도화 + 5분류 제거 | JD→사이트별 키워드/AND·OR(라이브 검증)·국영문·변형 / 0건→필드값 되읽기 검증 / segment 의존 제거 또는 LLM 라벨로 대체(무회귀) | W1 |

## 적용 게이트
harness 게이트 0~6. 각 W는 별 worktree·RED먼저·`./verify.sh` exit0·세 번 깨기(자기→Codex fresh→codex:rescue reset)·verdict.json. 라이브 단계(W1·W3·W4)는 H4(사장님 로그인된 크롬) 실증 1건.

## 적대검증 정조준 항목 (가짜 GREEN 차단)
- W4: "키워드 함수 존재" 문자열 단언 금지 → **실제 생성 결과의 사이트별 형식·국영문 동시·0건시 필드되읽기 동작**을 단언.
- W2: "pause 됨"만 보지 말고 **유휴 후 실제 resume 사이클**을 단언(재개 누락=치명).
- W1: 셀렉터 존재가 아니라 **모달 타깃 필드 visible&enabled** + 실패가 ledger에 실제 append되는지.
- segment 제거: match/harvest **무회귀**(기존 그룹/로그 계약 유지) 증명.

## 비범위
캡차/2FA 자동돌파 금지(계정정지) · 발송 자동클릭 금지(사람 게이트) · CDP 함대(별 repo) 제외.

## 사람 결정 / 대기
- H1 합격 점수선, H2 임베딩 차원(256 vs 1536) — P3 적재 단계에서.
- H4 라이브 검증용 로그인된 크롬은 사장님이 띄워둠.

## 진행 순서
W0(완료) → W4(키워드, 최고가치) → W1(방어적 조작) → W2(자동재개·봇가드) → W3(병렬).

## 적대 검증 로그

### W0 (SOT#2 재작성 + 목표문서) — 커밋 7ad887d
- 문서 변경. 회귀 없음(486 passed). 판단 단언(문구 명료성)은 사장님 직접 승인(2026-06-22 "잠깐 멈췄다 자동 재개"로 확정).

### W4-1 (LLM 키워드 생성기) — RED 432dfb4 → GREEN 34fd7ab
- **G(자기):** 495 passed. 라이브 claude -p haiku 스모크(saramin 평문 국영문/축약어, linkedin AND/OR) 확인.
- **T(기계 mutation):** mutant A(dedup제거)/B(전채널 boolean)/C(빈키워드 에러제거) **3개 전부 kill**, 되돌림 후 GREEN, 트리 청결. → 테스트가 구현 베끼기 아니라 관측가능 동작을 잡음 증명.
- **V1(Codex 독립):** 본문 미반환 2회(이 환경 SendMessage 미지원). 독립 적대검증 컨텍스트 확보 실패 → 보류.
- **판정:** 기계증거는 통과, **독립 V 보류로 "진행 중"**. verdict: `ai-search-strategy-v2-w4-keywords.verdict.json`.
- **남은 배선(비고):** 이 생성기는 아직 검색 경로(`portal_queue_executor`/`keywords.build_keyword_plan`)에 미배선 — 다음 조각(W4-2)에서 배선 + 5분류 제거 무회귀.

### W4-2 (LLM 키워드→KeywordSession 변환 `build_llm_keyword_sessions`) — RED → GREEN ca9e96b
- **G(자기):** 14 keyword tests, 전체 500 passed. 키워드1개=세션1개(순서보존), boolean 채널은 `filters['boolean_query']` 적재, 평문 채널 비움, 한 채널이라도 키워드 0이면 에러 전파.
- **T(기계 mutation):** mutant E(채널 에러 삼킴 continue)→`test_generation_error_propagates` kill / mutant F(boolean 미적재)→`test_boolean_query_carried_in_filters_for_linkedin` kill. 되돌림 후 GREEN, 트리 청결. mutant D(평문채널에도 boolean=""실음)는 **동치 mutant**(빈문자열=없음)이라 생존 — 의미상 결함 아님(기록).
- **함정 기록:** mutation 때 `git checkout`이 **미커밋 GREEN을 날림** → 이후 "GREEN 커밋 먼저 → mutation" 순서로 교정.
- **V1(Codex 독립):** 환경 제약으로 보류(동일). **판정: 기계증거 통과, 독립V 보류 → "진행 중".**
- **아직 검색 미배선:** 변환부까지 완료. 실제 큐/runner가 이걸 쓰게 하는 배선 + 사람인/잡코리아 AND/OR 라이브 검증 + 0건시 필드 되읽기는 다음 조각(W4-3, 라이브 H4 필요).

### W4-3a (포지션→채널별 QueueItem `build_llm_queue_items`) — RED → GREEN
- **G(자기):** 19 keyword tests, 전체 505 passed. 포지션 원문→LLM 키워드→채널별 QueueItem(status=pending, group_id=`llm-<position_id>`, 채널별 세션만). 그룹핑/5분류 우회.
- **T(기계 mutation):** mutant G(채널 스코핑 제거)→`test_queue_item_keyword_plan_is_channel_scoped` kill. 되돌림 후 GREEN, 트리 청결.
- **코드 사슬 완성:** `Position → build_llm_queue_items → QueueItem(LLM keyword_plan) → keywords_for_item → 검색`. 단, 이 함수를 실제 진입점(dry_run/queue 생성)이 호출하게 하는 최종 배선 + 라이브는 미완.
- **V1 보류 동일.** 판정: 기계증거 통과, 독립V 보류 → "진행 중".

## 라이브 차단 기록 (2026-06-22)
- 링크드인 CDP 탭이 `uas/login-cap`+`recaptcha`+`uc=scraping`(스크래핑 탐지) 상태 → SOT상 캡차 우회 금지(사람이 풂). 사람인/잡코리아 탭 미오픈.
- ⚠️ 링크드인이 이미 봇 탐지로 찍힘 → 라이브 자동검색은 탐지 악화 위험. W3(병렬)·W4-3 라이브는 사장님 크롬 정상화 후.

### W3-1 (단일 검색 큐 4채널 펼침 — dry_run 진입점 배선) — RED → GREEN
- **지시(2026-06-23):** "search 하나로 사람인·잡코리아·링크드인·챗지피티(공개웹) 모두 풀로서치".
- **근본원인(직접 연 file:line):** `dry_run.py:102` 큐 빌더가 `channel="saramin"` 하드코딩 → 4채널 중 사람인만 큐 적재. 키워드 생성기(`llm_keywords.DEFAULT_CHANNELS`)·실행계층은 이미 4채널 가능.
- **G(자기):** RED `test_single_search_queue_covers_all_channels`(기대4,실제[saramin]) → `_ordered_unique_channels`로 그룹 keyword_plan 전 채널 펼침 → 전체 **507 passed, 5 subtests**. 자력 mutant(seen[:1]) kill 후 복구·트리청결.
- **V1(Codex 독립, agentId a1c0f984a47a5e63d):** PASS + 본문 재현 — diff `2 files, 67+/2-`(약화없음), RED 재현, mutant kill, `507 passed in 10.32s`. 두 컨텍스트 독립 재현 일치(three_way_agree=true). verdict: `ai-search-strategy-v2-w3-channel-fanout.verdict.json`.
- **⚠️ 비범위/미완:** 라이브 포털 실검색(run_live_queue_cycle)은 미수행 — LinkedIn 봇탐지 차단 + SOT 캡차우회금지. skills/search 문서의 4채널 선언도 별도 미반영. "풀로 라이브 서치"는 아직 아님.
