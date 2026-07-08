# Valuehire_v5 맥시마이즈 로드맵 (2026-07-07)

> 문서 경로: `docs/engineering/repo-maximize-goal-2026-07-07.md` (HTML 쌍둥이: 같은 이름 `.html`)
> 상위 근거: `CLAUDE.md`(SOT 불변식) · `docs/harness.md`(게이트) ·
> `docs/engineering/valuehire-pipeline-consolidation-spec-2026-07-01.md`(R1~R10 스펙) ·
> `docs/engineering/valuehire-pipeline-consolidation-backlog-2026-07-01.json`(PC-* 백로그) ·
> `.harness/red-ledger.tsv`(완료 원장, 2026-07-07 기준)

---

## (0) 사장님께 한 줄 요약

> 후보 찾는 부품은 이미 대부분 만들어져 있습니다. 이제 남은 건 **"이어 붙이기"**입니다 —
> ① 찾은 이력서를 창고(DB)에 차곡차곡 쌓고, ② 쌓인 이력서를 모든 열린 포지션과 밤낮없이
> 자동으로 견주어 보고, ③ 메일함에 온 새 포지션을 알아서 등록하고, ④ 검색 로봇이 사장님
> 크롬을 방해하지 않으면서 스스로 멈췄다 다시 도는 것. 이 문서는 그 이어 붙이기의 순서와,
> 각 조각을 시킬 때 복사해 붙일 지시문(프롬프트)입니다.

---

## (1) 사장님 니즈 6개 → 현황 → 빈틈 매트릭스

| # | 니즈(사장님 말) | 이미 있는 부품 (GREEN) | 빠진 조각 | 조각 ID |
|---|---|---|---|---|
| N1 | 상시 ClickUp 포지션 ↔ 후보 프로필 매칭 | `harvest_runner.arun_harvest_cycle`(PC-D2b), `match.py`, `clickup_activity.py`, ClickUp 실쓰기(PC-A1/A2a/A3) | 임베딩 영속(pgvector)·매치 라이브 소비 미연결, ClickUp active 포지션 전수 순회 러너 없음 | **PC-D3, PC-N3** |
| N2 | 본 레쥬메 재활용 — SQLite/Supabase 저장 | Supabase `profile_archives`(레쥬메 전문+url, PR#48), `scripts/humansearch_supabase_backfill.py` | 레포 내 SQLite 저수지 store 미바인딩(런간 누적 안 됨), 리스팅 페이지 무조건 저장 레일 미연결, 연봉 필드 부재 | **PC-D1, PC-C4a/C4b, PC-C5/C6** |
| N3 | 저장된 레쥬메 상시 매칭 (역방향: 새 포지션 → 기존 레쥬메) | `embed.py`, `match_jd_to_reservoir` 계약 | N1과 동일 — 임베딩 영속 + 상시 재매칭 크론 없음 | **PC-D3, PC-N3** |
| N4 | URL 자동 등록 + Gmail 순회 중복확인 | `position_registration.py`, `position_dedup.find_duplicate_position`(회사·직무·URL 정규화 중복판정), Discord 디스패처(PC-A3), weekly-update 스킬(수동 절차) | Gmail→포지션 파서 순수함수 없음, 상시 인입 크론 없음, 임의 포털 URL 파서(PC-A4) 미완 | **PC-N1a, PC-N1b, PC-A4, PC-B3** |
| N5 | Humansearch 쉽게 실행 + 후보를 더 맞는 다른 포지션에도 연결 | `humansearch_cdp_run.py`(전수 다중페이지 C3b GREEN, R4 배선 F2 GREEN, 러너면 하드제외 C3a), 채점 `score_humansearch` | 러너에 포지션 하드코딩(`POSITION`/`SEARCH_URL_BASE` 상수) → 매번 스크래치패드 오버라이드, 교차 포지션 재매칭 없음 | **PC-N4, PC-N3** |
| N6 | AISearch 3사(링크드인·사람인·잡코리아) 브라우저 방해 없이 안정 | 봇방지 페이싱(PC-E1), 점유감지 순수모듈(PC-F1), 라이브 배선(PC-F2 GREEN), 챌린지 감지 SOT26 파리티(PC-F3), 포트 분리(9223/9224/9225), 탭 증식 가드(PR#72) | 자동재개 데몬 미완(F4a 순수함수는 GREEN 추정 — 원장 확인 필요, **F4b 상주 실운영 미완**), portal_worker linkedin_rps 전체 attach(INV5 위반) 잔존 | **PC-F4a/F4b, PC-F5** |

**핵심 판정:** 니즈 6개 중 5개가 기존 스펙(R1~R10)의 미완 조각과 정확히 겹친다.
순수 신규는 3개뿐 — **PC-N1a/N1b(Gmail 인입)**, **PC-N3(상시 교차 재매칭)**, **PC-N4(러너 포지션 주입화)**.

---

## (2) 목표 아키텍처 (이어 붙인 뒤 모습)

```
[Gmail 받은편지함] ──PC-N1a/N1b──▶ 포지션 파싱 → find_duplicate_position 중복확인
                                          │ 신규만
                                          ▼
[ClickUp FY26ClientsPosition 901814621569]  ◀── 임의 URL 등록(PC-A4) · Discord 명령(A3, GREEN)
        │ active 포지션 순회
        ▼
검색식 생성(B2, GREEN) → 검색 URL을 포지션 태스크에 저장(PC-B3) ── ★사람 검수
        │
        ▼
Humansearch 전수 순회(C3b GREEN) — 포지션 주입화(PC-N4)로 어떤 포지션이든 한 줄 실행
        │  ├─ 리스팅 무조건 저장 save_rail(PC-C4a) + 연봉 캡처(PC-C5/C6)
        │  ├─ 하드제외(C3a GREEN) · 채점 · 졸업연도 경력상한(GREEN)
        │  └─ Supabase profile_archives 적재(GREEN)
        ▼
Reservoir 저수지 — SQLite 런간 누적(PC-D1) + pgvector 임베딩(PC-D3)
        │
        ▼
상시 교차 재매칭(PC-N3): 새 포지션 ↔ 기존 레쥬메, 새 레쥬메 ↔ 전체 active 포지션
        │  적합 후보 → ClickUp 포지션 자식 태스크로 자동 연결(85+만, SOT28 게이트)
        ▼
발송 드래프트(G1 캡가드 GREEN, G2 컴포저) → SOT28 게이트 통과분만 자동, 나머지 ★사람 클릭

[상시 운전 계층]  R4 점유감지(F1/F2 GREEN) → 자동재개 데몬(PC-F4a/F4b)
                 봇방지 페이싱(E1 GREEN) · raw CDP 단일탭(PC-F5) · 포트 9223/9224/9225
```

---

## (3) 작업 순서 (의존성 기준)

앞이 뒤를 막는 순서다. 병렬 가능 조각은 같은 줄에 묶었다.

1. **PC-F4a → PC-F4b** — 자동재개 데몬 완성. 이것 없이는 "상시"가 성립 안 함(멈추면 방치됨 = SOT R4 위반).
2. **PC-D1** — SQLite 저수지 store. 레쥬메 재활용(N2)의 척추.
3. **PC-C4a ∥ PC-N4** — 리스팅 무조건 저장 레일 / 러너 포지션 주입화. 서로 독립, 병렬 워크트리 가능.
4. **PC-D3** — pgvector 임베딩 영속 + match 라이브 소비.
5. **PC-N3** — 상시 교차 재매칭 크론(니즈 N1+N3+N5 후반을 한 번에).
6. **PC-N1a → PC-N1b** — Gmail 포지션 인입 파서 → 상시 크론.
7. **PC-B3 ∥ PC-A4** — 검색 URL ClickUp 저장 / 임의 URL 등록 파서.
8. **PC-C5/C6 ∥ PC-F5** — 연봉 자산 수집 / INV5 raw CDP 단일탭 정리.

---

## (4) 조각별 복붙 프롬프트

아래 각 블록을 **새 Claude 세션(깨끗한 컨텍스트)**에 그대로 붙여넣는다.
모든 프롬프트는 harness 게이트(워크트리·RED 먼저·verify·2패스 적대검증)를 내장한다.

### 공통 머리말 (모든 프롬프트 맨 앞에 이미 포함됨)

```
/strict 모드. docs/harness.md 게이트 전부 준수: make red-ledger 확인 → 이슈/인수기준 1개 →
워크트리(worktrees/<NAME>, 브랜치 task/<NAME>)에서 실패 테스트 먼저 커밋(RED) → 최소 구현(GREEN) →
./verify.sh 숫자 그대로 보고 → 스스로 적대적 반증 → codex:rescue(막히면 fresh Claude V1 대체) 2차 적대검증 →
make ship → PR·CI 초록 확인. 시작 전에 과거 지시·기존 코드 회수(중복 구현 금지).
SOT 불변식(자동로그인 유지·R4 양보/자동재개·발송은 SOT28 게이트·쉬운 한국어 보고·2패스) 절대 약화 금지.
```

---

### P1. PC-F4a/F4b — 자동재개 상주 데몬 (니즈 N6)

```
[공통 머리말 적용]
작업: PC-F4a(자동재개 순수 결정함수)와 PC-F4b(상주 데몬 실운영)를 완성한다.
근거: docs/engineering/valuehire-pipeline-consolidation-backlog-2026-07-01.json 의 PC-F4a·PC-F4a2·PC-F4b,
직전 인수인계 문서(커밋 3c87f30, C3b→F2→F4a→F4b 로드맵). .harness/red-ledger.tsv 에서
humansearch-r4-wiring(PC-F2)까지 GREEN 확인 후, F4a 완료 여부를 원장·git log 로 먼저 회수하라(중복 구현 금지).
인수기준: (F4a) compute 계열 순수함수 — 사장님 크롬 idle 판정 시 resume 결정, REPO_DIR 해석,
페이크 실행자 호출횟수로 경계 검증. (F4b) scripts/valuehire-search-loop.sh 또는 launchd 경로에
상주 데몬 배선 — 점유 감지 시 정지, idle 복귀 시 자동재개, 크래시루프 금지(PR#66 회귀 유지),
경로 드리프트 제거. 봇방지 페이싱(harvest_policy, PC-E1)을 재사용하고 새 간격 로직을 만들지 마라.
SOT R4: "잠깐 양보·자동 재개"다 — 멈추고 방치하는 코드는 인수 실패.
```

### P2. PC-D1 — SQLite 저수지 store (니즈 N2)

```
[공통 머리말 적용]
작업: PC-D1 — save_rail 산출(캡처된 후보 프로필)을 레포 내 SQLite 파일에 런간 누적으로 영속화한다.
근거: 백로그 PC-D1, harvest_runner.py 의 run_harvest_cycle, humansearch_supabase_sync.py 의
profile_archives 계약(레쥬메 전문+url, url 무효/본문 공허 = 적재 거부 fail-closed — 동일 원칙 적용).
인수기준: ① 같은 후보(url+position 키) 재적재 시 중복 없이 upsert ② 프로세스 재시작 후에도
이전 런 데이터 조회 가능 ③ Supabase 동기화(scripts/humansearch_supabase_backfill.py)와 충돌 없음
— SQLite 가 로컬 진실, Supabase 는 미러. 스키마에 salary_raw/salary_source 컬럼을 미리 포함해
PC-C5 와의 재작업을 막아라(값은 지금 비워둠). DB 파일 경로는 REPO_DIR 해석 순수함수(PC-D2a2) 재사용.
```

### P3a. PC-C4a — 리스팅 무조건 저장 레일 (니즈 N2)

```
[공통 머리말 적용]
작업: PC-C4a — humansearch 순회 중 리스팅(목록) 페이지의 후보 카드를 상세 진입 여부와 무관하게
전건 저장하는 save_rail 어댑터를 배선한다.
근거: 백로그 PC-C4a/C4b, 스펙 R8, 사람인 규칙(저장=차감0). humansearch_cdp_run.py 의 collect_cards
다중페이지 순회(PC-C3b GREEN)에 주입한다 — 새 순회 로직 금지.
인수기준: 페이크 탭으로 N페이지 순회 시 카드 전건이 store 적재 호출로 이어짐(호출횟수 검증),
저장 실패가 순회를 중단시키지 않음(fail-open 로깅). 후속으로 C4b(SOT25 INV6 문서 드리프트 정합)까지
같은 턴에 처리 — 코드와 SOT 가 "저장 금지 vs 저장" 로 갈라진 부분을 R8 기준으로 단일화.
```

### P3b. PC-N4 — humansearch 러너 포지션 주입화 (니즈 N5)

```
[공통 머리말 적용]
작업: PC-N4(신규) — tools/multi_position_sourcing/humansearch_cdp_run.py 의 모듈 상수
POSITION(42행)·SEARCH_URL_BASE(30행) 하드코딩을 제거하고, CLI 인자(ClickUp task id 또는
포지션 JSON 경로 + 검색 URL)로 주입받게 한다.
근거: 메모리 humansearch-run-method(현재는 스크래치패드 런타임 오버라이드로 우회 중 — 이 우회를 없애는 게 목적),
posting_models.py 의 Position 모델, clickup_activity.py.
인수기준: ① 인자 없이 실행하면 fail-closed(과거 하드코딩 포지션으로 몰래 돌지 않음)
② ClickUp task id 주면 JD·검색URL 을 태스크(댓글의 /url 산출물 포함)에서 읽어 Position 구성
③ 기존 테스트 전부 GREEN 유지(회귀 0). 완료 후 .claude/skills/humansearch SKILL 문서의 실행법 갱신.
```

### P4. PC-D3 — pgvector 임베딩 영속 + match 라이브 (니즈 N1·N3)

```
[공통 머리말 적용]
작업: PC-D3 — embed.py 임베딩을 Supabase pgvector 에 영속화하고, match.py 의
match_jd_to_reservoir 가 라이브로 그 저장소를 소비하게 배선한다.
근거: 백로그 PC-D3, 스펙 R3, PC-D1 의 SQLite store(선행 — 원장에서 GREEN 확인 후 착수).
인수기준: ① 후보 적재 시 임베딩 1회 생성·영속(재적재 시 재계산 없음) ② JD 텍스트 입력 →
저수지 전체에서 유사도 상위 K 재랭킹 반환(페이크 임베딩으로 결정론 테스트) ③ Supabase 장애 시
fail-closed 도메인 예외(빈 결과를 성공처럼 반환 금지). 네트워크 호출은 테스트에서 전부 페이크.
```

### P5. PC-N3 — 상시 교차 재매칭 (니즈 N1·N3·N5) — **⚡ Codex 위임 조각 (토큰 절약)**

> **실행 주체 규칙(2026-07-07 사장님 지시):** 이 조각의 **구현은 Codex 가 한다.**
> Claude 는 토큰을 아끼기 위해 ① 인수인계 프롬프트 전달, ② 결과물 적대검증(V1),
> ③ 게이트/원장 확인만 담당한다. 역할이 뒤집히므로 2패스 검증은
> "Codex 구현 → Codex 자체 반증 → **Claude 독립 적대검증(V1)**" 순으로 성립한다.
> Codex CLI 가 'Operation not permitted' 로 막히면(알려진 환경 이슈) 그때만
> fresh Claude 서브에이전트로 대체하되, 대체 사실을 보고에 명기한다.

**Claude 세션에 붙일 위임 지시(짧게 — Claude 토큰 최소화):**

```
PC-N3 상시 교차 재매칭을 Codex 에 위임해 구현해라. Claude 인 너는 직접 구현하지 마라 —
아래 [Codex 인수인계 프롬프트]를 codex:rescue 로 전달하고, 완료 보고가 오면
.harness/red-ledger.tsv·verify.sh 숫자·테스트 증거만 확인한 뒤 독립 적대검증(V1) 1회를 수행해라.
V1 에서 깨지면 깨진 증거만 Codex 에 돌려보내 재작업시켜라(네가 고치지 마라).
```

**[Codex 인수인계 프롬프트] — 자체완결, 그대로 전달:**

```
저장소: /Users/kangsangmo/Valuehire_v5. docs/harness.md 게이트 전부 준수:
워크트리(worktrees/pc-n3-cross-rematch, 브랜치 task/pc-n3-cross-rematch)에서 실패 테스트 먼저
커밋(RED) → 최소 구현(GREEN) → ./verify.sh 숫자 그대로 보고 → 스스로 적대적 반증 1회.
시작 전에 .harness/red-ledger.tsv 와 git log 에서 PC-N3·PC-D3 상태를 회수하라(PC-D3 선행 필수 —
미완이면 착수하지 말고 그 사실만 보고). 중복 구현 금지 — 아래 기존 부품에 주입/확장만 한다.

작업: PC-N3(신규) — 두 방향 상시 재매칭 크론.
(a) 새 포지션이 ClickUp FY26ClientsPosition(901814621569) 에 등록되면 → 기존 저수지(SQLite,
PC-D1) 레쥬메 전체와 매칭, (b) 새 레쥬메가 저수지에 적재되면 → active 포지션 전체와 매칭
(원래 찾던 포지션이 아니어도 — "더 잘 맞는 다른 포지션 연결"이 목적).

재사용할 기존 부품(새로 짜면 인수 실패):
- 매칭: tools/multi_position_sourcing/match.py 의 match_jd_to_reservoir (PC-D3 라이브 경로)
- ClickUp 쓰기: position_registration.py 경로의 ClickUpCreateTask(list_id 지원, PC-A0/A1) +
  build_position_custom_fields(PC-A2a)
- R4 양보: owner_activity.compute_yield_decision → worker_should_yield (PC-F1/F2)
- 페이싱: harvest_policy 의 pacing 순수함수(PC-E1)
- 중복판정 키: url+position (humansearch_supabase_sync 와 동일 원칙)

인수기준(테스트로 증명, 네트워크·ClickUp 은 전부 페이크로 결정론 검증):
① threshold 이상만 해당 포지션 자식 태스크로 등록, 같은 url+position 재실행 시 등록 0건
② 이미 다른 포지션에 등록된 후보도 더 맞는 포지션이 나오면 추가 연결(기존 연결 삭제/이동 금지)
③ 사장님 크롬 점유 감지 시 yield, idle 복귀 시 재개(R4) — 페이크 신호로 경계 검증
④ 자동 발송 절대 없음 — 연결(등록)까지만. 발송 코드 경로가 생기면 인수 실패(SOT28)
⑤ 실행 시간대 기본 새벽 03~05 KST(설정 주입 가능), 직무로 채널을 가르지 않는다(2026-06-23 지시)
⑥ 매칭·등록 결과는 원장(로그/DB)에 기록 — 재실행 멱등

완료 보고 형식: 변경 파일 목록, RED 커밋 해시, verify.sh 결과 숫자, 자체 반증에서 시도한 공격과
결과. 병합(ship)은 하지 말고 브랜치 상태로 두라 — Claude V1 적대검증 통과 후 병합한다.
```

### P6. PC-N1a → PC-N1b — Gmail 포지션 자동 인입 (니즈 N4)

```
[공통 머리말 적용]
작업: PC-N1a(신규) — Gmail 스레드 텍스트 → 포지션 후보(회사·직무·JD 본문·원본 URL) 파싱 순수함수.
PC-N1b(신규) — Gmail 을 주기 순회해 신규 포지션을 ClickUp 에 자동 등록하는 크론 러너.
근거: position_dedup.find_duplicate_position(회사·직무 정규화 + canonical_posting_url — 중복판정은
이걸 그대로 재사용, 새 중복 로직 금지), dispatch_register_position(PC-A3 GREEN — 등록 경로 재사용),
weekly-update 스킬 ①영역(현재 수동 절차 — 이 자동화가 대체 대상임을 스킬 문서에 명기).
인수기준: (N1a) 실제 포지션 메일 픽스처 3종 이상에서 회사·직무·URL 추출, 포지션 아닌 메일은
None(fail-closed). (N1b) ① 이미 등록된 포지션 재수신 시 등록 0건(중복확인 증거 로그)
② 처리한 메시지 id 원장 기록(재순회 시 재처리 없음) ③ Gmail 읽기 실패 시 크래시루프 금지.
등록만 한다 — 답장·라벨 변경 등 메일함 변형은 라벨 1개(처리표시) 외 금지.
```

### P7. PC-B3 ∥ PC-A4 — URL 저장·임의 URL 인입 (니즈 N4·N5)

```
[공통 머리말 적용]
작업: PC-B3 — 확보된 검색 URL(사람 검수 통과분)을 ClickUp 포지션 태스크 커스텀필드/댓글에 저장.
PC-A4 — 사장님이 던진 임의 포털 채용공고 URL 을 파싱해 포지션 등록으로 잇는 파서 확장.
근거: 백로그 PC-B3·PC-A4, /url 스킬(RPS 는 프로젝트당 라이브 검색 1개 — 링크1개+Boolean 레시피
저장 방식 유지, 2026-07-03 라이브 검증), build_position_custom_fields(PC-A2a GREEN).
인수기준: (B3) 저장 포맷이 /url 스킬 산출물과 호환 — humansearch 가 그대로 순회 가능.
(A4) 사람인·잡코리아·원티드 공고 URL 픽스처에서 회사·직무 추출 → find_duplicate_position 통과
후에만 등록. 두 조각은 독립 — 병렬 워크트리 2개로 진행 가능.
```

### P8. PC-C5/C6 ∥ PC-F5 — 연봉 자산 · INV5 정리 (니즈 N2·N6)

```
[공통 머리말 적용]
작업: PC-C5 — CapturedProfile·CandidateResultCard 에 salary_raw/salary_source 필드 추가(순수 모델 확장).
PC-C6 — 사람인/잡코리아 상세에서 연봉·처우 텍스트 캡처해 저수지에 적재하는 러너 배선.
PC-F5 — portal_worker 의 linkedin_rps 전체 attach(INV5 위반)를 raw CDP 단일탭으로 교체.
근거: 백로그 PC-C5·C6·F5, 메모리 portal-debug-chrome-ports(9223/9224/9225·CDP_HTTP 오버라이드),
url-rps-raw-cdp 함정 4가지, PC-D1 스키마(salary 컬럼 선반영 확인).
인수기준: (C5) 기존 테스트 회귀 0. (C6) 연봉 텍스트 없는 프로필은 None 저장(추정치 생성 금지).
(F5) connectOverCDP 전체 attach 코드 경로 제거 — 사장님 탭 과다 환경에서 hang 재현 테스트로 증명.
```

---

## (5) 운영 원칙 (전 조각 공통)

- **한 조각 = 한 워크트리 = 인수기준 1개.** 두 조각을 한 PR 에 섞지 않는다.
- **부품 재사용 우선.** `find_duplicate_position`·`save_rail`·`harvest_policy`·`worker_should_yield`·
  `dispatch_register_position` 이 이미 있다 — 비슷한 걸 새로 짜면 게이트 위반.
- **fail-closed.** 파싱 실패·네트워크 장애·빈 본문은 조용히 성공 처리하지 않는다.
- **발송은 SOT28.** 이 로드맵의 어떤 조각도 "보내기"를 새로 자동화하지 않는다 — 등록·연결·드래프트까지만.
- **매 조각 착수 전 원장 회수.** `.harness/red-ledger.tsv` 와 git log 에서 해당 PC-ID 가 이미
  GREEN 인지 먼저 확인한다(이 문서 작성 시점 기준 C3b·F2 는 로컬 GREEN, push 대기였음).
