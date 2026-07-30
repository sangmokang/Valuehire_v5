# apps/aisearch(신규) — 3사 인재검색 자동화 + admin.valuehire.cc 연동 goal

> 상태: 스펙 확정 단계(코드 없음). 이 문서는 실제 구현(각 AC별 워크트리) 착수 전 goal prompting 문서다.
> 근거 대화: 2026-07-28 사장님 요구사항 인터뷰(디스코드 DM/채널 정정 포함).

## 0. 왜 이 문서가 있는가

Fable 적대 리뷰(2026-07-27)에서 apps/aisearch 신규 서비스에 대해 나온 BLOCKER 3건
(격리 범위, admin.valuehire.cc 등록, SOT25 리스트 대조)을 먼저 처리한 뒤, 사장님이
직접 상세 요구사항을 구술하셨다. 이 문서는 그 요구사항을 EARS 인수 기준 + 결정 목록 +
예외표로 고정한다.

## 1. 현재 상태 (file:line 근거)

- `apps/aisearch/` 디렉터리는 아직 없다(신규).
- `apps/aisearch-zero/`(manifest.md, docs/complaints.md, docs/strict-adversarial-review.md)는
  **참고자료로만 쓰고 의존하지 않는다** — 2026-07-28 사장님 확정("이건 참고만 하고 의존성 없이 새로 만들어").
- SOT29(`docs/sot/29-fleet-control.md`) 함대 인프라(Supabase jobs/account_locks 큐, fleet_worker.py,
  계정↔머신 바인딩, 60초 자동재개)는 **재사용하지 않는다** — 2026-07-28 사장님 확정("의존성 없이 새로 만들것임").
  즉 apps/aisearch는 SOT29와 완전히 별개의 독립 상태·락 구조를 새로 가진다.
- 매칭 점수 계산 로직은 이미 존재: `tools/multi_position_sourcing/matching_score_contract.py`
  (계약명 `candidate-match-v2-2026-07-24`) + `docs/sot/24-position-jd-sot.json`의
  `evaluation_contract.matching_prompt_contract` — D1~D8 8개 항목 근거 채점 + 결정론적 Stage4 총점.
  이 계약은 **그대로 재사용**한다(사장님 지시: "매칭 점수는 v4,v5에 있는 코드 참고").
- admin.valuehire.cc는 REST API가 없다. 실제 코드(`app/ai-search-list/_data/loader.ts` 등)는
  `valuehire_v4` 레포 소속이며, 이 컴퓨터에는 `/Users/kangsangmo/Desktop/valuehire_v4`에
  launchd 로그만 남아있고 **실제 앱 코드 체크아웃이 없다**(2026-07-28 확인, `find` 결과).
  기존 연동 방식은 `.claude/skills/weekly-update/references/data-sources.md:32-34`가 기록한
  **Supabase `pipeline_candidates` 테이블 직접 upsert**(서비스키 사용, API 경유 아님)뿐이다.
- Discord 봇 자체 client ID는 `1512101118543397056`(`docs/search-access.md:20`, hermes_v5) —
  이 ID는 **DM 대상이 될 수 없다**(봇 자기 자신). 2026-07-28 사장님이 최종적으로
  **채널 `1512503041448743092`**(밸류커넥트 멤버가 보는 일반 소통 채널)로 정정.
- 서치 결과 전용 채널은 별도로 이미 정해져 있던 `1470955309089554554`
  (`.claude/skills/weekly-update/references/data-sources.md:24-29`) — 이번 대화에서 **그대로 유지**하기로
  확정(멤버 채널과 역할 분리, 통합 아님).
- 브라우저 "사용중" 표시용 크롬 익스텐션은 **존재하지 않는다**. `codeit-talent-archive-search/SKILL.md`가
  언급하는 `tools/profile-archiver/`는 2026-07-28 확인 결과 **레포에 실제로 없다**(문서만 있고 코드 없음).
  즉 AC-8은 "기존 익스텐션 확장"이 아니라 **신규 제작**이다.
- `docs/sot/31-strict-recurrence-ledger.md`(strict 스킬이 인용하라고 요구하는 재발 원장)는
  **이 레포에 존재하지 않는다**(`docs/sot/31-fleet-run-reliability.md`만 있음, 이름 다름). 인용할 항목이
  없어 R4 인용은 생략하고 이 사실 자체를 기록해둔다(원장이 아직 안 만들어진 상태).

## 2. 목적 / 범위

**목적**: 사람인·잡코리아·링크드인 RPS에서 JD 기반으로 후보를 찾아, 점수 매기고,
ClickUp + Discord + admin.valuehire.cc 세 곳에 결과를 남긴다. 발송은 하지 않는다.

**포함**:
- 3사(사람인/잡코리아/링크드인 RPS) 동시 검색(사장님 지시: "같이 만들어")
- 3대 기기(Macmini/Macbook/Winpc) 브라우저 상태 모니터링(SOT29와 독립적인 자체 구조)
- 페이지네이션(최대 20페이지) + 열어본 리스트/상세 페이지 전량 Supabase 저장
- 매칭 점수(60점 이상 게이트) + ClickUp/Discord/admin 3중 기록
- 사람 개입 감지(30초) + 캡차/클라우드플레어 감지 시 자동 중단
- 브라우저 사용중 빨간 띠 표시(신규 크롬 익스텐션)
- `/jdbuilder` 연동(후보자 전달 메시지 초안 — 발송 아님)

**비범위**:
- 제안/InMail/메일 자동 발송(항상 사람이 마지막에 누름 — 절대 불변)
- admin.valuehire.cc의 실제 API 엔드포인트 구현(그건 `valuehire_v4` 레포 작업 — 이 문서는
  요구사항/계약까지만, 실제 엔드포인트 코드는 그 레포 체크아웃 이후 별도 goal)
- SOT29 함대 인프라 변경(이번 서비스는 그것과 무관하게 독립적으로 동작)

## 3. 결정 목록 (오너 확정, R2 — 다시 묻지 않음)

| # | 항목 | 확정값 |
|---|---|---|
| D1 | 사람 개입 감지 후 자동재개 대기시간 | **30초** (SOT29의 60초와 별개, 이 서비스 전용 상수) |
| D2 | "서울권대학교" 정의 | **서울 소재 4년제 대학 전체**(캠퍼스 소재지 기준, 서열/명성 기준 아님) |
| D3 | 페이지네이션 상한 | **20페이지**. 도달 시 그 키워드 조합 검색 종료, 다음 불린 변형으로 전환 |
| D4 | Supabase 저장 범위 | **리스트 화면 + 상세 프로필 페이지 둘 다** |
| D5 | 등록(ClickUp/Discord/admin) 점수 기준선 | **60점 이상**(saramin/jobkorea 스킬의 85점 기준과 다름 — 의도된 차이) |
| D6 | 채널 범위 | 사람인·잡코리아·링크드인 **동시 착수** |
| D7 | 발송 게이트 | **자동 발송 절대 금지**(불변) |
| D8 | 캡차/클라우드플레어 발생 시 | **자동 우회 금지 + 즉시 중단 + 사람 알림**(아래 §5 예방책 병행) |
| D9 | 브라우저 사용중 표시 | **빨간 띠** 오버레이(신규 크롬 익스텐션) |
| D10 | 디스코드 결과 채널 | `1470955309089554554`(서치 결과 전용, 기존 유지) |
| D11 | 디스코드 소통 채널 | `1512503041448743092`(밸류커넥트 멤버용 일반 채널, 신규) |
| D12 | admin.valuehire.cc 연동 방식 | **논의 중 — 미확정.** Supabase 직접쓰기(기존 weekly-update 방식, 의존성 있음) vs
  신규 API(의존성 없음, 그러나 `valuehire_v4` 레포에 별도 개발 필요). 사장님이 "API 개발 이어나가자"고
  하셨으나 admin 연동의 최종 방식(직접 DB냐 API냐)은 아직 명시적으로 재확인받지 못했다 — **AC-6 착수 전 재확인 필요**.
- 인프라 재사용 여부(격리 범위): **완전 독립 구조**(SOT29 미재사용, 확정)
- zero 문서 취급: **참고만, 의존 안 함**(확정)
- SOT25 ClickUp 리스트 ID: 사장님 지정 리스트와 **동일**(`901818680208`) — 이중 SOT 문제 없음(확정)

## 4. 인수 기준 (EARS, AC 1개 = 워크트리 1개)

각 AC는 게이트 2(워크트리+RED)부터 게이트 4(verify)까지 독립적으로 진행한다. 아래 순서는
권장 착수 순서이며, 무의존 AC는 병렬 가능(R5).

### AC-1 — 링크드인 RPS 검색 + Boolean 키워드 + 서울 소재 대학 우선순위
- **WHEN** JD와 South Korea 기본 위치가 주어지면
- **THE SYSTEM SHALL** JD 키워드를 한국어/영어 혼합 Boolean(AND/OR/괄호)으로 조합해 RPS Keywords 필드에 입력하고,
  1차로 **서울 소재 대학 졸업자** 우선 필터를 적용해 검색하며, 그 결과가 소진되면 그 때 확장 검색(D2 밖 조건)으로 전환한다.
- 검증: 실제 RPS 화면에서 Keywords 필드에 생성된 Boolean 문자열이 실제로 반영되고, 결과 건수가 갱신되는 것을 스크린샷으로 확인.
- Counter-AC: 서울 소재 대학 확장 조건이 JD의 다른 확정 필수요건(예: 경력연차)보다 우선순위가 높아지면 안 됨 — 필수요건은 항상 게이트.

### AC-2 — 사람인/잡코리아 검색 연동
- **WHEN** 같은 JD가 주어지면
- **THE SYSTEM SHALL** `docs/search-access.md`의 기존 DOM 계약(Saramin talent-pool, Jobkorea Corp/Person/Find)을 재사용해 동일 JD 기반 키워드로 검색한다.
- 검증: 두 채널 각각 실제 결과 화면 캡처 + 건수.

### AC-3 — 페이지네이션 20페이지 cap + 전량 Supabase 저장
- **WHEN** 검색 결과 페이지를 순회할 때
- **THE SYSTEM SHALL** 최대 20페이지까지 순회하고, 각 리스트 페이지와 열어본 상세 프로필 페이지를 빠짐없이 Supabase에 저장한다.
- **IF** 20페이지에 도달하면 **THEN** 그 키워드 조합 검색을 종료하고 다음 불린 변형으로 넘어간다.
- 검증: Supabase 테이블에 실제 row count가 순회한 페이지 수와 맞는지 대조.
- Counter-AC: 21페이지째 요청이 나가면 실패.

### AC-4 — 매칭 점수(기존 계약 재사용) + 60점 게이트
- **WHEN** 후보 프로필이 수집되면
- **THE SYSTEM SHALL** `matching_score_contract.py`(`candidate-match-v2-2026-07-24`)로 0-100점을 계산하고, 60점 미만은 등록 대상에서 제외한다.
- 검증: 알려진 입력 3~5건에 대해 기존 계약과 동일한 점수가 나오는지 회귀 테스트.

### AC-5 — ClickUp + Discord 이중 기록
- **WHEN** 60점 이상 후보가 확정되면
- **THE SYSTEM SHALL** ClickUp `901818680208`(포지션 부모 Task + 후보 Subtask, 중복확인 후) 등록과
  Discord `1470955309089554554`(매칭점수·프로필URL·적합/부적합 이유·매칭근거·학력/경력 브리핑) 게시를 모두 수행하고,
  진행상황/에러는 Discord `1512503041448743092`에 별도 게시한다.
- 검증: 라이브 1건 등록 + 두 채널 실제 메시지 확인.

### AC-6 — admin.valuehire.cc 연동 (⚠️ D12 미확정 — 착수 전 재확인 필수)
- 방식 확정 후 별도 AC로 세분화. (Supabase 직접쓰기 vs 신규 API 중 택1 확정 필요.)

### AC-7 — 사람 개입 감지(30초) + 캡차 감지·중단·알림
- **WHEN** 사람이 해당 브라우저에 마우스/키보드 입력을 하면
- **THE SYSTEM SHALL** 즉시 자동 조작을 멈추고, 마지막 입력으로부터 30초 동안 추가 입력이 없으면 자동 재개한다.
- **IF** 캡차/클라우드플레어/2FA/체크포인트가 감지되면 **THEN** 자동 우회를 시도하지 않고 즉시 중단 + Discord 알림.
- 검증: 개입 시뮬레이션(수동 클릭) 후 실제로 멈추고, 30초 뒤 재개하는지 타임스탬프로 확인.

### AC-8 — 브라우저 사용중 빨간 띠 표시 (신규 크롬 익스텐션)
- **WHEN** 자동화가 특정 브라우저 탭을 조작 중이면
- **THE SYSTEM SHALL** 그 탭 화면 상단에 빨간 띠 오버레이를 표시하고, 조작이 끝나면 제거한다.
- 참고: `tools/profile-archiver/`는 문서에만 있고 실제로 레포에 없으므로 신규 제작(§1 근거).
- 검증: 실제 브라우저 스크린샷으로 빨간 띠 표시/제거 확인.

### AC-9 — /jdbuilder 연동(전달 메시지 초안, 발송 아님)
- **WHEN** 후보가 등록되면
- **THE SYSTEM SHALL** 기존 `/jdbuilder`·`linkedin-rps-jd-set-builder` 규칙(§6 회사 브리핑 — 실측 8요소, `.codex/skills/linkedin-rps-jd-set-builder/SKILL.md:33` 기준. 초안의 "7요소" 표기는 2026-07-28 V1 적대검증에서 정정됨)에 맞춰 후보 전달용 메시지 초안을 만든다. 발송 버튼은 절대 누르지 않는다.
- 검증: 생성된 초안이 글자수 상한을 지키는지, 발송 API가 호출되지 않았는지 로그로 확인.

## 5. 계약 (입출력 모양 — SDD)

- **Supabase 저장 스키마(신규 필요, 미확정)**: 리스트 페이지 스냅샷 + 상세 페이지 스냅샷을 담을 테이블(가칭 `aisearch_pages_raw`). 컬럼 초안: `id, channel, page_type(list|detail), url, captured_at, raw_html_or_text, position_ref, machine`. **오너 확정 필요.**
- **매칭 점수 입출력**: `docs/sot/24-position-jd-sot.json`의 `matching_prompt_contract` 그대로(D1~D8 근거 + gates + total_years → 결정론적 0-100점).
- **ClickUp 등록 계약**: `docs/sot/25-ai-search-execution-process.json`의 `clickup_registration_contract`(필수 4필드: profile_url, score, why_fit, profile_summary) 재사용.
- **Discord 메시지 계약(신규)**: 결과 채널 메시지 = {매칭점수, 프로필URL, 적합/부적합 사유, 매칭 근거, 학력, 경력 브리핑}. 멤버 채널 메시지 = 진행상황/에러(요약형).
- **admin.valuehire.cc 계약**: D12 미확정 — Supabase 직접쓰기면 `pipeline_candidates` upsert 계약(기존 재사용), API면 신규 엔드포인트 계약(별도 문서).

## 6. 예외 케이스 표 (R1)

| # | 상황 | 처리 |
|---|---|---|
| E1 | 캡차/클라우드플레어/2FA 감지 | 명시적 중단 + Discord 알림, 자동 우회 금지(D8) |
| E2 | 사람 마우스/키보드 입력 감지 | 30초 대기 후 자동 재개(D1) |
| E3 | 20페이지 도달 | 해당 키워드 조합 검색 종료, 다음 불린 변형 시도(D3) |
| E4 | 링크드인 동시 2세션 충돌 | 명시적 거부 — 링크드인은 1기기만 허용(사장님 요구사항 원문) |
| E5 | 후보 점수 60점 미만 | 등록하지 않음(D5) |
| E6 | 셀렉터 실종/DOM 변경 | 명시적 중단, 손으로 때우지 않고 셀렉터 사전 수리 후 재시도 |
| E7 | admin.valuehire.cc 방식 미확정 상태에서 AC-6 착수 시도 | 명시적 거부 — D12 재확인 전 착수 금지 |
| E8 | 페이지 중간 저장 실패/저장확인 유실 | 결정론적 멱등키 upsert 로 재시도(중복 0), 재개 불가면 명시적 중단 (2026-07-28 V1 지적 반영) |
| E9 | 이중 기록 부분 성공(ClickUp OK + Discord 실패) | status=partial + 미완 단계 목록 반환, 재시도는 미완 단계만 이어서 완결 (V1 반영) |
| E10 | 차단 알림 발신 실패 | 재시도 후 pending_notifications 큐 보존 — 차단 이벤트 유실 금지 (V1 반영) |
| E11 | 확장 기능 문서 준비 전 표시→제거 경쟁 | 제거 시 예약 부착 취소 — 최신 신호 우선 (V1 반영) |
| E12 | 그 외 표에 없는 모든 상황 | 명시적 중단(임의 추정 금지) |

## 7. 게이트 계획

각 AC = `npm run wt -- aisearch-<AC-slug>` 워크트리 1개, RED 테스트 먼저, `npm run check` +
(있으면) `npm run strict:gate` exit 0, 라이브 1건. L2(일반 코드) 기준 V1(codex 적대검증)까지 필수.
AC-5(ClickUp/Discord 실기록)·AC-6(admin 연동)은 외부 쓰기가 있어 L3 — V1→V2 교차 적대검증 + owner signoff 필요.

## 8. 다음 액션 (오너 확인 필요)

1. **D12(admin.valuehire.cc 연동 방식)** 최종 확정 — Supabase 직접쓰기 재사용 vs 신규 API.
2. Supabase 신규 테이블(`aisearch_pages_raw` 가칭) 스키마 오너 확정.
3. 어느 AC부터 워크트리를 팔지 순서 확정(권장: AC-1 → AC-7 → AC-4 → AC-3 → AC-2 → AC-5 → AC-8 → AC-9 → AC-6).

## 적대 검증 로그

### 2026-07-28 라운드 1 — 구현 + V1(Codex fresh read-only) 1차
- 구현: AC-1~AC-5, AC-7~AC-9 를 워크트리 8개(task/aisearch-ac*-*)에서 RED→GREEN 으로 구현. AC-6 은 D12 미확정으로 E7 규칙에 따라 착수 거부.
- V1 1차 판정: **8개 전부 FAIL** — BLOCKER 15건(잘못된 구조 허용, Boolean 주입, 전환 사유 무시, 재시도 중복 저장, dry-run 을 기록 완료로 표시, 부분 실패 복구 부재, BLOCKED 덮어쓰기, 배너 재출현 경쟁, 게이트 비강제, 배선 부재 등). 판정 전문: 세션 스크래치 `v1-verdict-full.log` 보존.
- 수정 라운드: 워크트리 8개 각각 결함 재현 RED → 수정 GREEN 커밋(각 4커밋). 전체 206 passed.
- 배선 부재 해소: task/aisearch-orchestrator 워크트리에 8브랜치 병합 + `apps/aisearch/core/orchestrator.py` `run_search_pipeline` 신설 — 60점 게이트 강제 경유, BLOCKED 중단, dry-run 기본, 배너 신호, 초안 생성 배선. 220 passed.
- 라이브 증거 보류 항목(코드로 해소 불가, 오너 게이트): 실제 RPS 화면 반영 스크린샷(AC-1), 실 사람인/잡코리아 검색 실행(AC-2), 실제 Supabase 적용(AC-3 — 스키마 오너 확정 필요), ClickUp/Discord 라이브 1건(AC-5 — L3 owner signoff), 실제 브라우저 입력 감지기 연결(AC-7), 익스텐션 실화면 캡처(AC-8). 모두 fail-closed(기본 dry-run/주입식)로 구현되어 라이브 승인 전 외부 쓰기 0.

### 2026-07-28 라운드 2 — V1 2차 재검증(Codex exec, read-only)
- 1차 BLOCKER 15건 재판정: FIXED 9 / STILL-BROKEN 5 / LIVE-PENDING 1. 통합 경로 신규 결함 7건(캡차 후 진행, 제외어 무시, 배너 제거 실패 삼킴, 20p 후 변형 미실행, 순차 실행, 포지션별 저장 덮어쓰기, 기록 실패에도 초안·completed). 220 passed 확인. 전문: 세션 스크래치 `v1-round2-verdict.log`.
- 수정: task/aisearch-orchestrator 에 결함 10건 RED→GREEN(82ed01d→c60d2dc), 248 passed.

### 2026-07-28~31 라운드 3 — V1 3차 재검증(Codex exec, read-only, HEAD c60d2dc)
- 12건 재판정: **FIXED 6 / STILL-BROKEN 6 / LIVE-PENDING 0**. 248 passed 확인.
- 남은 6건: ①실제 RPS 입력 연결 부재 ②실제 사람인/잡코리아 실행 부재 ④실제 입력·캡차 감지 공급자 연결 부재 ⑥목록/상세 저장 직전 BLOCKED 재확인 누락 ⑦제외어가 최종 후보 등록·초안에서 비강제 ⑩라운드로빈은 진짜 동시 실행이 아님(한 채널 블록 시 타 채널 대기).
- 부수 지적: goal 문서가 워크트리에 미커밋 상태(코드·테스트 15곳 인용) → 커밋 필요.

### 라운드 4 (2026-07-31) — 수정 + V1 4차
- 수정(0c149fc): goal 문서 커밋(a64f10e) + STILL-BROKEN 6건 해소 시도 — cdp_driver.py(주입식 CDP 트랜스포트)·run.py(3모드 진입점) 신설. 281 passed.
- V1 4차 판정: FIXED 1 / STILL-BROKEN 5 — CDP 어댑터 현실성 지적(JS 합성 입력, 로드 대기 부재, 자기 입력 오인, 단일 탭 공유, 제외어 심층 미검사) + run.py 결함(기본 모드 브라우저 접촉, 추출기 silent 0).

### 라운드 5 (2026-07-31) — 수정 + V1 5차 + 최종 BLOCKER 수정
- 수정(4f43249): CDP Input 도메인 신뢰 입력·로드 대기·자기 입력 표식·감시 재설치·2FA/체크포인트 감지·제외어 재귀 스캔·채널별 독립 드라이버+연결 락·plan-only 기본(무접촉)·추출기 필수화. 312 passed.
- V1 5차 판정: FIXED 2 / STILL-BROKEN 6 / 신규 BLOCKER 3(상세 후 목록 미복귀로 2페이지 진행 불가, run.py 저장 append 중복+포지션 혼입, 차단 시 Discord 알림 부재) / IMPROVEMENT 3.
- 최종 수정(95606b8→27f2749): BLOCKER 3건 해소 — 상세 후 목록 복귀, channel+position_ref+url upsert, Discord notifier(채널 1512503041448743092) 배선. **321 passed.**

### V2 (2026-07-31, 리셋 컨텍스트 직접 점검)
- 전체 테스트 321 passed / 자동 발송 코드 grep 0건 / BLOCKER 3건 수정 테스트·배선 존재(tests/test_aisearch_v5_blockers.py, run.py position_ref, discord_notify.py) / 기본 모드 plan-only(브라우저 무접촉) 확인.

### 라이브 검증 백로그 (오너 게이트 — 코드만으로 종결 불가, 사장님 복귀 후)
V1 5차 기준 STILL-BROKEN 잔여분은 전부 "실제 브라우저·실계정 없이는 검증 불가" 축으로 수렴:
1. RPS 필터(지역·경력·대학) 실화면 적용·결과건수 갱신 스크린샷(AC-1 검증항).
2. 사람인/잡코리아 실화면 검색 실행·캡처(AC-2), 셀렉터 유효성 확인.
3. 로드 대기가 "새 결과 도착"을 실화면에서 정확히 잡는지(이전 화면 오독 여부).
4. 잡코리아 학력 체크박스 상태 확인 후 토글.
5. 링크드인 멀티세션·enterprise-authentication 문구 등 차단 감지 패턴의 실화면 보강.
6. 3사 동시 실행 시 채널별 실제 탭 분리(현행: 연결은 분리, 탭 URL 지정은 라이브 세팅 필요).
7. Supabase 실 테이블 적용(스키마 오너 확정 D12·§8-2), ClickUp/Discord 라이브 1건(L3 owner signoff), 익스텐션 실화면 캡처.
- V1 5차 IMPROVEMENT 3건(제외어 필드 한정, 결과건수 단일 영역 파싱, 추출기 사전 일괄 검사)도 라이브 라운드에서 함께 처리.
