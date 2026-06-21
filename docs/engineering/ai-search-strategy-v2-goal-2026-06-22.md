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
(비워둠 — 각 조각 G→V1→V2 판정을 여기 채운다.)
