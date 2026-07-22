# Goal — 밸류하이어 단일 디스코드 봇 콘솔 (2026-07-22)

> 이 문서는 **작업 지시서(goal prompt)** 다. 구현자는 이 문서를 SOT로 삼는다.
> 규율: `docs/sot/30-strict-mode-contract.md`(strict) + `docs/harness.md` 게이트 + `CLAUDE.md` SOT 불변식.
> Hermes 전환·폐기 정본: `docs/sot/33-hermes-retirement.md`(SOT 33). 이 문서의 §10보다 상세하며 충돌 시 SOT 33을 따른다.
> 등급: **L3**(운영 경로 신설 + 기존 통제면 폐기 + 웹 화면 추가). 단계마다 RED→GREEN + `./verify.sh` + 배선 증명 + V1(자체 적대검증) + V2(Codex Rescue) 필수.

---

## 0. 사장님께 한 줄 (쉬운 말)

지금은 디스코드 명령을 받는 창구가 **두 벌**(헤르메스 / 안 쓰는 자체 봇)이라 어느 쪽이 받았는지 알 수 없고, 명령을 먹고 조용히 무응답인 경우가 로그로 확인됩니다. 이 작업은 **창구를 하나로 줄이고**(헤르메스 완전 폐기), 그 창구에서 **클로드와 코덱스에게 일을 시키고**, 무슨 일이 돌고 있는지 **웹 화면 표 하나로** 보이게 만드는 것입니다.

---

## 1. 사장님이 확정하신 요구사항 (2026-07-22 지시, 원문 보존)

| # | 요구 | 확정 상태 |
|---|---|---|
| R1 | "에르메스는 완전히 지워, 혼돈의 원인이다" | **확정** — 폐기 |
| R2 | 새 봇 하나가 **클로드 코드와 코덱스를 동작시켜 스킬을 수행**하게 한다 | **확정** |
| R3 | 디스코드를 **쉘창처럼** — 거기서 명령을 내리면 Codex/Claude Code 에게 작업이 할당되는 구조 | **확정** |
| R4 | 자유도는 **"스킬 호출 + 자유 문장 지시" 둘 다 허용**(선택지 2번). 단 위험 행동은 코드로 차단 | **확정** |
| R5 | 입력·출력·조회·편집이 가능해야 한다 | **확정** |
| R6 | 작업 큐가 쌓이면 **진행중 / 완료 / 실패**를 볼 수 있는 화면 | **확정** |
| R7 | 화면 위치 = `https://admin.valuehire.cc/ai-search-list` 안에 **Fleet-job 탭**을 만들어 거기에 작업 리스트 | **확정** |
| R8 | 상세 내용은 `ai-search-list` 에서 본다 | **확정** |
| R9 | 클로드/코덱스를 **선택적으로 호출** | **확정**(기술적으로 가능 — §3 F5) |
| R10 | 엣지 케이스는 **별도로 사장님께 레포팅** | **확정** — §8 |
| R11 | **Harness Hook** 으로 구현해 이상 없이 동작 | **확정** — §9 |

### R5·R3 이 커버해야 할 작업 10종 (사장님 열거, 원문 순서 보존)

| # | 작업 | 성격 |
|---|---|---|
| T1 | weekly 미팅 업데이트 | 쓰기 |
| T2 | KPI 조회 | 읽기 |
| T3 | 계산서 발행 명령 | 쓰기(외부 효과) |
| T4 | Skill 실행 | 실행 |
| T5 | Ontology 입력 — 고객사 정보를 DB에 입력 | 쓰기 |
| T6 | 과거 후보자 면접 사례 조회(Ontology 로부터) | 읽기 |
| T7 | 과거 면접자 확인 | 읽기 |
| T8 | 인터뷰 확정자 확인 | 읽기 |
| T9 | 포지션 Priority | 읽기+쓰기 |
| T10 | aisearch · url · login · humansearch (핵심 스킬) | 실행 |

---

## 2. 범위 밖 (이번에 하지 않는 것)

- 제안·메일 **발송**(Send) 자동화 — SOT28 유지. 봇은 초안까지만. 사장님 명시 지시 건은 예외(CLAUDE.md SOT 3).
- 디스코드에서 임의 셸 명령 실행(`git`, `rm` 등) — 사장님이 2번을 고르셨으므로 **금지**.
- v4 웹 화면의 기존 탭 2개(어드민 리스트 / ClickUp 시각화) 동작 변경.

---

## 3. 착수 전 확인된 사실 (2026-07-22 실측, 추측 아님)

| # | 사실 | 증거 |
|---|---|---|
| F1 | 헤르메스 게이트웨이가 **실행 중**이며 디스코드 명령의 실질 수신자다 | `launchctl list` → `ai.hermes.gateway` PID 36086, `~/Library/LaunchAgents/ai.hermes.gateway.plist` |
| F2 | 헤르메스 로그에 **오류 누적**: 최근 3000줄에 Traceback 227건, ImportError/ModuleNotFoundError 20건, DB `OperationalError` 19건, `Plugin command dispatch failed` 1건. `gateway.error.log` 13MB | `~/.hermes/logs/errors.log`, `gateway.error.log` |
| F3 | `/aisearch`·`/humansearch`·`/url` 은 헤르메스 플러그인의 **인테이크 핸들러**로만 존재 | `ops/hermes-plugin/valuehire_fleet/__init__.py` `_DIRECT_SEARCH_COMMANDS`(~L304), `register()`(L311-322) |
| F4 | 두 번째 창구 `scripts/discord_direct_gateway.py`(705줄)는 **꺼져 있으나 완성도 높음** — 인증·감사로그·멱등키·최소권한 큐 클라이언트 보유. 새 봇의 뼈대로 재사용 | `scripts/discord_direct_gateway.py:104,198,222,586,660` |
| F5 | **클로드/코덱스 선택 실행은 이미 구현돼 있다.** `params.agent == "codex"` 면 `_run_codex`, 아니면 `_run_claude` | `tools/multi_position_sourcing/fleet_worker.py:415,486,835-848` |
| F6 | 작업 큐 테이블 `public.jobs` 의 상태값이 이미 6종 — 사장님이 원하시는 화면에 그대로 쓸 수 있다 | `supabase/migrations/20260711_fleet_jobs_queue.sql:5-21` (`queued/running/paused_for_human/done/failed/cancelled`) |
| F7 | `jobs` 테이블은 **service_role 전용**. anon/authenticated 는 전부 revoke. 웹에서 읽으려면 별도 조치 필요 | 같은 파일 L36-38 |
| F8 | 최소권한 RPC 3종이 이미 있다(enqueue / recent / idempotency 조회). resume·cancel 은 의도적으로 미지원 | `supabase/migrations/20260719_discord_gateway_minimal_privilege_rpc.sql`, `scripts/discord_direct_gateway.py:624-640` |
| F9 | 명령 이름 정의는 한 곳에 있다 | `tools/multi_position_sourcing/discord_routing.py:13-31` |
| F10 | 워커 프롬프트에 **로그인 선행 강제가 코드로 없다** — 문장 지시만. 사후 `login_verified` 는 모델 자기신고라 위조 가능 | `docs/prompts/hermes-login-gate-before-search-skills-2026-07-21.md` F15~F17, `fleet_worker.py:187-268` |
| F11 | Harness 훅 구조: `guards/<이름>.py` 에 `check(tool, tool_input)` 를 두면 **모든 툴 호출**에 문이 걸린다(사유 문자열 반환 = 차단). 로드 실패는 fail-open | `.claude/hooks/harness-dispatch.py:1-45`, `.claude/settings.json` PreToolUse `.*` |
| F12 | 종료 게이트도 있다 — Stop 훅 `stop-evidence-gate.py`(exit 99 → 차단) | `.claude/settings.json` Stop |
| F13 | 검증 명령은 `./verify.sh` (= `pytest tests/ -q`) | `verify.sh:23-33` |
| F14 | v4 는 Next.js App Router. 대상 화면은 `app/ai-search-list/`, 탭 전환은 `AiSearchViewSwitcher.tsx` 담당, ClickUp fetch 는 fail-soft | `/Volumes/SSD/valuehire_v4/app/ai-search-list/page.tsx:22-56` |

> **F-INV (능력 인벤토리)** — T1~T10 각각의 백엔드 존재 여부는 §4 표에 별도 기재한다. 조사 결과가 채워지기 전에는 어떤 작업도 "있다"고 전제하지 않는다.

---

## 4. 능력 인벤토리 (T1~T10 백엔드 실측)

> 상태 표기: `EXISTS_API`(프로그램이 부를 수 있는 진입점 있음) / `EXISTS_UI_ONLY`(화면·스킬로만 존재) / `PARTIAL` / `NONE`.
> **NONE 인 항목은 이번 범위에서 "봇 명령"이 아니라 "먼저 만들어야 할 백엔드"로 분류한다.**

| T | 능력 | 상태 | 진입점 (봇이 부를 것) | 증거 | 비고 |
|---|---|---|---|---|---|
| T1 | weekly 미팅 업데이트 | **PARTIAL** | `GET/POST /api/weekly/meeting-notes` (v4) | v4 `app/api/weekly/meeting-notes/route.ts:26-58`, 인증 `getRequestUser` L65-67 | 회의록 저장은 API 있음. **수치 집계(ClickUp·Gmail)는 node CLI 스크립트뿐** — 봇이 부를 HTTP 진입점 없음 |
| T2 | KPI 조회 | **EXISTS_API** | `GET /api/admin/owner/metrics/weekly?week=` | v4 `app/api/admin/owner/metrics/weekly/route.ts:1-100`, 가드 `requireOwner` L36 | 4대 지표 + 8주 시계열. 읽기 전용 |
| T3 | 계산서 발행 | **EXISTS_API** | `POST /api/admin/owner/invoices` | v4 `app/api/admin/owner/invoices/route.ts:1-84`, `src/lib/owner/settlement.ts`, v5 `.codex/skills/taxbill/SKILL.md:29-53` | 등록 시 `commission_payouts` 3행 자동생성 + **컨설턴트에게 자동 이메일 발송**. 외부 효과 큼 → E3 |
| T4 | Skill 실행(일반) | **PARTIAL** | RPC `discord_gateway_enqueue(...)` | `supabase/migrations/20260719_...rpc.sql:47-75` | **허용 스킬이 `humansearch/aisearch/url` 3종으로 DB에서 하드 고정**(L60-62). `/skill` 로 다른 스킬을 돌리려면 마이그레이션 필요 |
| T5 | Ontology 입력(고객사 DB) | **NONE** | 없음 | `docs/wiki/customer-ontology/*.jsonl`, `*.md` (파일뿐) | **Supabase 테이블도 API도 없음.** 지금은 사람이 파일을 직접 편집. 봇 명령을 붙이려면 백엔드 신규 개발 |
| T6 | 과거 면접 사례 조회 | **PARTIAL(고장)** | `GET /api/admin/candidate-timeline?candidate_id=` | v4 `app/api/admin/candidate-timeline/route.ts:656-662`, `supabase/migrations/20260529000000_drop_pre_interview_tables.sql:5-8` | **핵심 테이블 `admin_candidate_pre_interviews` 가 2026-05-29 삭제됨.** 프로덕션에서 이 부분은 500 에러(L490-494). `unified_candidate_history_view` 쪽만 살아 있음 |
| T7 | 과거 면접자 확인 | **PARTIAL** | `GET /api/pipeline/candidates?jd_id=&q=` | v4 `app/api/pipeline/candidates/route.ts:7-16`, `supabase/migrations/20260516180000_pipeline_boards.sql:197,212` | "면접함/안함"을 가르는 컬럼·enum 없음. ClickUp 자유텍스트 상태에 의존 |
| T8 | 인터뷰 확정자 확인 | **NONE** | 없음 | 전 저장소 검색 0건. `pipeline_position_cards.stage` 값에도 없음(`...pipeline_boards.sql:212`) | **개념 자체가 스키마에 정의돼 있지 않다.** 무엇을 "확정"으로 볼지부터 정의 필요 |
| T9 | 포지션 Priority | **PARTIAL(읽기UI만)** | 조회: 전용 API 없음 / 변경: 없음 | v4 `app/kanban/_components/ClientPositionPeekView.tsx:64-65,84,1045-1061` | ClickUp 커스텀 필드를 화면에 배지로 보여줄 뿐. **변경 코드 0건** — 바꾸려면 ClickUp MCP 직접 호출 |
| T10 | aisearch·url·login·humansearch | **EXISTS_API(큐)** | RPC `discord_gateway_enqueue` → `claim_next_job` → `release_job` | `20260711_fleet_jobs_queue.sql:135-214`, `direct_receiver.py:105`, `job_queue.py:473` | 큐 등록은 확정 경로. 실제 수행은 워커의 클로드/코덱스가 SKILL.md 따라 실행 |

### 4.1 이 인벤토리가 뜻하는 것

- **바로 명령만 붙이면 되는 것(3)**: T2 KPI, T3 계산서, T10 핵심 스킬
- **손보면 되는 것(4)**: T1(집계 API 신설), T4(DB 화이트리스트 확장), T7(면접 여부 판정 기준 정의), T9(ClickUp 쓰기 경로)
- **백엔드를 새로 만들어야 하는 것(2)**: **T5 Ontology 입력**, **T8 인터뷰 확정자** → 별도 작업으로 분리, 이번 봇 1차 범위 밖 후보
- **고장난 것(1)**: **T6 면접 사례 조회** — 테이블이 이미 삭제돼 프로덕션 500. 봇을 붙이기 전에 이것부터 고쳐야 함

### 4.2 웹 화면(Fleet-job 탭)이 jobs 를 읽는 방법

| 경로 | 볼 수 있는 것 | 판정 |
|---|---|---|
| 새 v4 API 라우트 + service_role | 전체 컬럼 자유 조회 | **채택** — 진행중/완료/실패 + 오류메시지까지 보여주려면 필수. v4 표준 패턴(`src/lib/supabase.ts:9-11` + `requireAdmin`)을 그대로 따름 |
| 기존 anon RPC `discord_gateway_recent_jobs` | `id/machine/skill/status/created_at` 5개뿐 | 부족 — 오류·요청자·결과요약 안 보임 |

현재 v4 에 `jobs` 를 읽는 라우트는 **없음**(신규 개발 대상).

---

## 5. 목표 아키텍처

```
디스코드 (채널 1개 = 콘솔)
        │  슬래시 명령  또는  자유 문장(멘션/DM)
        ▼
┌──────────────────────────────────────────┐
│ valuehire-bot  (신규, 단일 창구)          │   ← scripts/discord_direct_gateway.py 를 승격
│ 위치: v5 / 사장님 컴퓨터 상주(상시 연결)  │
│  1) 신원·권한 확인 (누가, 어느 채널)      │
│  2) 명령 해석                             │
│     - 정형: /aisearch url:… engine:codex  │
│     - 자유문: "이 포지션 검색해줘"        │  → 의도 분류기(허용 스킬 집합으로만 사상)
│  3) 안전 게이트 (발송 금지·쓰기 확인 등)  │
│  4) 실행형 → 큐 적재 / 조회·쓰기형 → v4 호출 │
│  5) 즉시 회신: 잡 번호 + 웹 링크          │
└───────┬───────────────────────┬──────────┘
        │ 실행형                │ 조회·쓰기형 (T1·T2·T3·T5·T6~T9)
        ▼                       ▼
 Supabase public.jobs    ┌──────────────────────────────┐
      (queued)           │ v4 봇 전용 API 층 (신규)      │
        │                │ /api/bot/*  — Vercel          │
        │                │  Bearer 봇 토큰으로 인증      │
        │                │  (세션 쿠키 가드를 대체)      │
        │                │  → 기존 owner/admin 로직 재사용│
        ▼                └──────────────────────────────┘
┌──────────────────────────────────────────┐
│ fleet_worker (기존, 머신별 상주)          │
│  params.agent 로 실행기 선택:             │
│    claude  → claude -p  (기본)            │
│    codex   → codex exec                   │
│  스킬 발동 프롬프트 생성 → 실행 → 결과    │
└──────────────────────────────────────────┘
        ▼ jobs.status = done / failed / paused_for_human
┌──────────────────────────────────────────┐
│ 디스코드 결과 회신   +   웹 Fleet-job 탭  │
│ admin.valuehire.cc/ai-search-list         │
│   [어드민 리스트] [ClickUp 시각화] [Fleet-job] │
└──────────────────────────────────────────┘
```

### 5.1 핵심 원칙

1. **창구는 하나.** 디스코드 명령을 받는 프로세스는 `valuehire-bot` 뿐이다. 헤르메스는 완전 폐기(§10).
2. **봇은 일을 하지 않는다. 큐에 넣을 뿐이다.** 실제 실행은 항상 워커의 클로드/코덱스가 한다. 봇 프로세스 안에서 브라우저를 열거나 포털에 접속하지 않는다.
3. **자유 문장은 반드시 허용 스킬 집합으로 사상된다.** 사상 실패 = 실행 금지 + 사장님께 되물음. 자유 문장이 곧바로 임의 실행이 되지 않는다.
4. **모든 명령은 멱등키를 갖는다.** 같은 디스코드 이벤트가 두 번 와도 잡은 하나.
5. **읽기와 쓰기를 분리한다.** 읽기는 즉답, 쓰기는 확인 버튼 1회를 거친다(§7).
6. **데이터 로직을 v5 에 복제하지 않는다.** KPI·계산서·후보자 이력은 v4 에 이미 있으므로, 봇은 **v4 의 기존 로직을 API 로 호출**할 뿐 계산식을 다시 구현하지 않는다(SOT 이중화 금지).

### 5.2 배치 결정 — 왜 봇을 v4 에 두지 않는가 (2026-07-22 사장님 문의에 대한 판정)

사장님 지적("v4 에 구현된 기능이 많다")은 **데이터 측면에서 옳다**. 그러나 봇 프로세스 자체는 v4 에 둘 수 없다.

| # | 제약 | 증거 |
|---|---|---|
| C1 | v4 는 Vercel 서버리스 — 요청 때만 깨어난다. 디스코드 게이트웨이는 **상시 웹소켓 연결**이 필요 | `/Volumes/SSD/valuehire_v4/vercel.json` (지속 프로세스 없음, cron 3건뿐) |
| C2 | 사장님이 고른 **자유 문장(R4)** 은 메시지 이벤트 수신이 필요 → 게이트웨이 필수. 슬래시 전용이면 HTTP Interactions 로 Vercel 가능하지만 **3초 응답 제한**이 있어 수 시간짜리 검색과 맞지 않음 | Discord 플랫폼 제약 |
| C3 | 실제 작업(로그인된 크롬, `claude -p`, `codex exec`)은 **사장님 컴퓨터 3대에서만** 가능 | `fleet_worker.py:415,486` |

**따라서 책임을 나눈다:**

| 구성요소 | 위치 | 책임 |
|---|---|---|
| 봇 몸통 | **v5** (머신 상주) | 디스코드 수신, 명령 해석, 게이트, 큐 적재, 결과 회신 |
| 데이터 창구 `/api/bot/*` | **v4** (신규) | KPI·계산서·후보자·주간회의록·작업목록을 봇 토큰으로 열어줌 |
| 웹 화면 Fleet-job 탭 | **v4** | 진행중·완료·실패 목록 + 상세 |
| 실행 워커 | **v5** (머신 상주) | 클로드/코덱스로 스킬 수행 |

이 배치는 E21(봇이 세션 쿠키로 로그인할 수 없는 문제)의 해답이기도 하다 — §8.1.b E21 ㉮ 로 확정.

---

## 6. 명령 표면 (사용자가 보는 것)

### 6.1 실행형 (큐에 적재 → 잡 번호 회신)

| 명령 | 인자 | 하는 일 |
|---|---|---|
| `/aisearch` | `url:` (필수) `engine:` `machine:` | 3사 AI Search |
| `/humansearch` | `url:` (필수, 검색결과 URL) `position:` `engine:` `machine:` | 걸어둔 검색결과 순회·채점 |
| `/url` | `position:` (필수) `machine:` | RPS 검색 URL 사전 세팅 |
| `/login` | `portal:` (saramin\|jobkorea\|linkedin\|all) `machine:` | 로그인 상태 확인·복구 |
| `/skill` | `name:` (필수) `args:` `engine:` `machine:` | 허용 목록 안의 임의 스킬 실행 |

공통 인자 `engine:` = `claude`(기본) \| `codex`. → `params.agent` 로 전달(F5).

### 6.2 조회형 (즉답, 큐 안 씀)

| 명령 | 하는 일 |
|---|---|
| `/jobs` | 최근 작업 상태 요약 + Fleet-job 탭 링크 |
| `/job <번호>` | 한 작업의 상세·진행률·오류 |
| `/kpi` | KPI 조회 (T2) |
| `/interviews` | 과거 면접자·인터뷰 확정자 확인 (T7·T8) |
| `/cases` | 과거 후보자 면접 사례 조회 (T6) |
| `/priority` | 포지션 우선순위 조회 (T9 읽기) |

### 6.3 쓰기형 (확인 1회 후 실행)

| 명령 | 하는 일 |
|---|---|
| `/weekly` | weekly 미팅 업데이트 (T1) |
| `/ontology` | 고객사 정보 DB 입력 (T5) |
| `/invoice` | 계산서 발행 명령 (T3) — 외부 효과, 확인 필수 |
| `/priority set` | 포지션 우선순위 변경 (T9 쓰기) |
| `/job resume\|cancel <번호>` | 작업 재개·취소 (owner 전용) |

### 6.3.b v4 봇 전용 API 층 `/api/bot/*` (신규, §5.2 결정에 따름)

봇이 조회·쓰기형 명령을 처리할 때 부르는 유일한 통로. **기존 owner/admin 라우트를 복사하지 않고, 그 내부 로직을 재사용**한다.

| 라우트 | 메서드 | 대응 명령 | 재사용할 기존 로직 |
|---|---|---|---|
| `/api/bot/jobs` | GET | `/jobs`, Fleet-job 탭 | 신규 — `public.jobs` 를 service_role 로 조회(§4.2) |
| `/api/bot/jobs/[id]` | GET | `/job <번호>` | 신규 |
| `/api/bot/kpi` | GET | `/kpi` | `app/api/admin/owner/metrics/weekly/route.ts` |
| `/api/bot/invoices` | GET·POST | `/invoice` | `app/api/admin/owner/invoices/route.ts` + `src/lib/owner/settlement.ts` |
| `/api/bot/weekly` | GET·POST | `/weekly` | `app/api/weekly/meeting-notes/route.ts` |
| `/api/bot/candidates` | GET | `/interviews`, `/cases` | `app/api/pipeline/candidates`, `candidate-timeline`(E23 판정 반영) |
| `/api/bot/positions` | GET·PATCH | `/priority` | 신규(ClickUp 경유, E24·T9) |

**인증 계약**
- 헤더 `Authorization: Bearer <VALUEHIRE_BOT_TOKEN>` — 봇 프로세스만 보유. 토큰은 절대 로그·디스코드 회신에 노출하지 않는다(G8).
- 가드는 기존 패턴 옆에 **추가**한다: `src/auth/botTokenGuard.ts`(신규) → 통과 시 owner 권한 상당으로 취급. 기존 `requireOwner`/`requireAdmin` 동작은 변경 금지.
- 토큰 불일치·부재 → 401, 본문에 사유 최소화.
- **쓰기 라우트(POST·PATCH)는 봇 토큰만으로 부족**하다. §7 G5(사장님 확인 1회)를 통과한 요청만 봇이 보낸다. 확인 사실은 감사로그에 남긴다.

### 6.4 자유 문장

봇을 멘션하거나 DM으로 평문을 보내면 의도 분류기가 위 명령 중 하나로 사상한다.
- 신뢰도 높음 → 해당 명령 실행 (무엇으로 이해했는지 한 줄 표기)
- 애매함 → 후보 2~3개를 버튼으로 제시
- 사상 실패 → "무슨 작업인지 못 알아들었습니다" + 명령 목록. **추측 실행 금지.**

---

## 7. 안전 게이트 (코드로 강제, 문장 지시 아님)

| G | 게이트 | 실패 시 |
|---|---|---|
| G1 | 신원: 허용 디스코드 사용자·채널만 | 거부 + 감사로그 |
| G2 | 스킬 화이트리스트: 사상된 스킬이 허용 목록 밖이면 실행 금지 | 거부 |
| G3 | **발송 금지**: 잡 프롬프트에 아웃리치·메일 발송 금지 규칙 삽입 + 발송 도구 호출 시 훅 차단 | 차단 |
| G4 | **로그인 선행**: 검색 스킬은 로그인 영수증(`artifacts/portal_session_status_latest.json`)이 유효할 때만 시작 | 잡을 `paused_for_human` 으로 세우고 사장님 호출 |
| G5 | 쓰기 확인: 쓰기형 명령은 요약을 보여주고 확인 버튼 1회 | 미확인 시 미실행 |
| G6 | 멱등: 같은 디스코드 event_id 는 잡 1개 | 기존 잡 번호 회신 |
| G7 | 사장님 양보(R4/SOT29 INV9): 3사 포털을 사장님이 만지는 중이면 대기, 60초 무이상이면 자동 재개 | 대기 후 자동 재개 |
| G8 | 비밀 유출 금지: 토큰·쿠키·비밀번호는 어떤 회신에도 나오지 않는다 | 마스킹 |

---

## 8. 엣지 케이스 — 사장님께 별도 레포팅할 항목 (R10)

> 아래는 **구현자가 마음대로 정하면 안 되는 것들**이다. 각 항목은 사장님 결재를 받고 표의 "결정" 칸을 채운 뒤에야 구현에 들어간다.
> 분류: **A = 지금 결정 필요**(AC-0 차단) / **B = 구현 중 발견되면 보고** / **C = 운영 중 발생 시 알림만**.

### 8.1 A급 — 지금 사장님 결정이 필요한 것
> **결정 채움 기록(2026-07-22 야간)**: 사장님 지시 "난 자러갈거고 니가 마지막까지 완료해 더 묻지마"에 따라 각 항목의 안전측 추천안을 채택해 진행. 기상 후 추인/변경 요청 시 해당 AC 재작업.


| E | 상황 | 왜 문제인가 | 선택지 | 결정 |
|---|---|---|---|---|
| E1 | **자유 문장을 잘못 알아들었을 때** | "이거 검색해줘"를 aisearch 로 이해했는데 실은 humansearch 였다면, 몇 시간짜리 작업이 헛돈다 | ㉮ 무조건 되묻는다(느리지만 안전) ㉯ 신뢰도 높으면 바로 실행하고 "이렇게 이해했습니다" 표기 ㉰ 항상 바로 실행 | **㉯ 채택** — 신뢰도 높으면 실행+"이렇게 이해했습니다" 표기, 애매하면 선택지, 모르면 실행 금지(AC-5 3분기와 동일) |
| E2 | **디스코드 계정이 뚫렸을 때** | 봇이 사장님 명령으로 착각하고 실행 | ㉮ 위험 명령(계산서·발송·삭제)은 2단계 확인 ㉯ 특정 채널에서만 위험 명령 허용 ㉰ 아무 조치 없음 | **㉮ 채택** — 위험 명령(계산서·삭제·발송성)은 확인 게이트 G5 + owner 한정 2단계 |
| E3 | **계산서 발행(T3)이 실제 돈·세금 효과를 낸다** | 잘못 누르면 되돌리기 어렵다. 디스코드에서 한 줄로 되는 게 맞는가 | ㉮ 봇은 **초안만** 만들고 발행 버튼은 웹에서 ㉯ 확인 2회 후 봇이 발행 ㉰ 조회만 허용 | **㉮ 채택** — 봇은 초안만, 발행 버튼은 웹에서(봇은 발행 API 를 부르지 않는다) |
| E4 | **같은 포지션을 두 번 검색 요청** | 포털 조회수·차감·중복 후보가 생긴다 | ㉮ 24시간 내 같은 URL 은 거부하고 기존 잡 보여줌 ㉯ 경고만 하고 실행 ㉰ 제한 없음 | **㉮ 채택** — 24시간 내 같은 URL 재요청은 거부하고 기존 잡 번호 안내(멱등 원칙 연장) |
| E5 | **한 머신에 작업이 몰릴 때** | 맥미니만 계속 쌓이고 맥북·윈도우는 논다 | ㉮ 자동 분배(포털 로그인 상태 기준) ㉯ 사장님이 매번 machine 지정 ㉰ 무조건 맥미니 | **현행 유지 채택** — 미지정 시 기존 기본값(macmini)+LinkedIn 로그인 라우팅, 명시 machine 이 항상 우선(㉮ 자동 분배 확장은 후속) |
| E6 | **작업이 몇 시간째 안 끝날 때** | 죽은 건지 도는 건지 모름 | ㉮ 스킬별 상한(예: 검색 90분) 넘으면 failed 처리 후 알림 ㉯ 무한 대기, 사장님이 취소 ㉰ 상한 넘으면 자동 재시도 1회 | **㉮ 채택** — 스킬별 상한(기존 워커 타임아웃) 초과 시 failed 처리+알림, 자동 무한 재시도 금지 |
| E7 | **웹 Fleet-job 탭을 누가 볼 수 있나** | jobs 에는 요청자·오류메시지가 들어간다 | ㉮ 로그인한 어드민만 ㉯ 회사 구성원 전체 ㉰ 제한 없음 | **㉮ 채택** — 로그인한 어드민만(Fleet-job 탭은 requireAdmin 세션 필요, 봇 API 는 봇 토큰) |
| E8 | **코덱스가 그 머신에 없거나 로그인 안 돼 있을 때** | `engine:codex` 로 넣었는데 실행 불가 | ㉮ 즉시 실패 처리하고 알림 ㉯ 조용히 클로드로 대체 ㉰ 코덱스 있는 머신으로 재배정 | **㉮ 채택** — 즉시 실패 처리+알림. 조용히 claude 로 대체하지 않는다(fail-closed) |
| E9 | **Ontology 입력(T5)에 같은 고객사가 이미 있을 때** | 덮어쓰면 기존 정보가 날아간다 | ㉮ 병합(빈 칸만 채움) ㉯ 덮어쓰기 전 차이를 보여주고 확인 ㉰ 새 버전으로 계속 쌓기 | **보류(E22 ㉮ 종속)** — T5 자체가 1차 범위 밖 |
| E10 | **명령 결과가 디스코드 2000자를 넘을 때** | 후보 30명 결과는 안 들어간다 | ㉮ 상위 5명만 채팅에 + 나머지는 웹 링크 ㉯ 파일 첨부 ㉰ 여러 메시지로 쪼개기 | **㉮ 채택** — 상위 5명만 채팅에, 나머지는 웹 링크 |

### 8.1.b A급 추가 — §4 인벤토리 실측으로 새로 드러난 결정 사항

| E | 상황 | 왜 문제인가 | 선택지 | 결정 |
|---|---|---|---|---|
| E21 | **봇이 v4 API 를 부를 자격**이 없다 | v4 의 모든 owner/admin API 는 **브라우저 세션 쿠키** 기반(`requireOwner`, `requireAdmin`). 봇은 브라우저가 아니라 로그인할 수 없다 | ㉮ 봇 전용 서비스 토큰을 새로 만들어 헤더로 인증(가드에 토큰 분기 추가) ㉯ 봇용 계정을 만들어 세션 쿠키를 보관·갱신 ㉰ 봇이 v4 를 직접 안 부르고 Supabase 를 직접 읽음 | **㉮ 확정** (2026-07-22 사장님 승인 — §5.2) |
| E22 | **T5 Ontology 입력·T8 인터뷰 확정자는 백엔드가 아예 없다** | "명령 붙이기"가 아니라 "기능 신규 개발". 일정이 크게 달라짐 | ㉮ 이번 봇 1차 범위에서 빼고 별도 작업으로 ㉯ 봇 작업에 포함해 같이 개발(오래 걸림) ㉰ 임시로 파일에 적어두는 수준만 | **㉮ 채택** — 이번 봇 1차 범위에서 제외, 별도 작업으로 분리(T5·T8 명령 미구현) |
| E23 | **T6 과거 면접 사례 조회가 이미 고장나 있다** | 테이블이 2026-05-29 에 삭제돼 프로덕션에서 500 에러. 봇을 붙이면 봇도 같이 실패 | ㉮ 먼저 고치고 나서 봇 명령 추가 ㉯ 살아있는 `unified_candidate_history_view` 만으로 대체 구현 ㉰ 이번엔 제외 | **㉯ 채택** — 살아있는 unified_candidate_history_view 로 대체 구현(AC-6) |
| E24 | **T4 `/skill` 은 DB가 3종만 허용**한다 | `humansearch/aisearch/url` 외 스킬은 큐에 들어가지 않게 DB에서 막혀 있음(마이그레이션 필요) | ㉮ 허용 목록을 넓히되 화이트리스트 유지 ㉯ 3종 그대로 두고 `/skill` 은 안 만듦 ㉰ 제한 해제 | **㉯(당장)+㉮(후속) 채택** — 이번엔 3종 그대로, /skill 은 밖이면 "아직 지원하지 않습니다" 거부. 확장 마이그레이션은 별도 작업 |
| E25 | **T8 "인터뷰 확정자"의 정의가 없다** | 스키마 어디에도 이 개념이 없어, 무엇을 확정으로 볼지 사장님만 안다 | ㉮ ClickUp 상태값 중 무엇을 확정으로 볼지 사장님이 지정 ㉯ 새 필드를 만들어 사람이 표시 ㉰ 보류 | **㉰ 채택** — 보류(정의 확정 전 미구현) |

### 8.2 B급 — 구현 중 발견되면 즉시 보고

| E | 상황 | 보고 사유 |
|---|---|---|
| E11 | §4 인벤토리에서 T1~T10 중 백엔드가 **NONE** 인 항목 | "봇 명령 추가"가 아니라 "백엔드 신규 개발"이 되어 일정이 달라짐 |
| E12 | `jobs` 테이블을 웹에서 읽는 데 필요한 권한 변경(F7) | DB 권한을 여는 일이라 보안 판단이 필요 |
| E13 | 헤르메스 삭제 시 **다른 기능이 같이 죽는 것**이 발견될 때(예: 크론·알림이 헤르메스에 얹혀 있었음) | 폐기 순서를 바꿔야 함 |
| E14 | 로그인 선행 게이트(G4)가 기존 검색 성공률을 떨어뜨릴 때 | 안전과 성공률의 교환 — 사장님 판단 |
| E15 | 자유 문장 분류에 LLM 호출이 필요해 **비용·지연**이 생길 때 | 규칙 기반으로 갈지 결정 필요 |

### 8.3 C급 — 운영 중 발생하면 알림만 (사전 결정 불필요)

| E | 상황 | 봇의 동작 |
|---|---|---|
| E16 | 캡차·2FA·체크포인트 | 잡을 `paused_for_human` 으로 세우고, 브라우저 창을 앞으로 띄우고, 디스코드로 호출 (SOT 불변식 1) |
| E17 | 사장님이 크롬으로 3사 화면을 만지는 중 | 대기 → 60초 무이상 시 자동 재개 (SOT29 INV9) |
| E18 | 포털 로그아웃 감지 | 저장된 자격증명으로 자동 재로그인 1회 시도, 실패 시 E16 처리 |
| E19 | 큐(Supabase) 일시 장애 | 봇이 "지금 접수 불가"라고 즉답. 명령을 삼키지 않음 |
| E20 | 워커가 죽은 채 잡이 `running` 으로 남음 | 하트비트 끊김 감지 후 `failed` 로 회수하고 알림 |

---

## 9. Harness Hook 설계 (R11)

`.claude/hooks/guards/` 에 파일을 추가하는 방식(F11). 훅은 **fail-open** 이므로, 훅만으로 보안을 세우지 않고 **봇 코드 안의 게이트(§7)와 이중**으로 건다.

| 훅 | 파일 | 막는 것 |
|---|---|---|
| H1 | `guards/discord-bot-send.py` | 잡 실행 중 제안·메일 발송 도구 호출 (G3 2층) |
| H2 | `guards/discord-bot-login-gate.py` | 로그인 영수증 없이 검색 스킬 툴 호출 (G4 2층) |
| H3 | `guards/discord-bot-skill-whitelist.py` | 허용 목록 밖 스킬 발동 (G2 2층) |
| H4 | Stop 훅 확장 | 잡을 "완료"로 보고하면서 증거(결과 요약·건수)가 없으면 차단 (F12 재사용) |

각 훅은 `.claude/hooks/tests/` 에 대응 테스트를 둔다(기존 `test_runner_lease_guard.py` 패턴).

---

## 10. Hermes 완전 폐기 실행 계약 (R1, SOT 33)

정본 경로는 다음 하나다.

```text
Discord 입력 → 단일 direct gateway → 자연어/슬래시 해석 → 영속 큐
→ fleet worker → Claude Code 또는 Codex → 원 요청자에게 결과 회신
```

새 직결 봇 실증 전에 Hermes를 중단하거나 삭제하지 않는다. Hermes와 직결 gateway가 같은
이벤트를 동시에 받지 않으며, 봇 토큰당 활성 gateway는 정확히 1개다. 폐기 전에는
`queued/running/paused_for_human`이 0이고 Claude/Codex 실작업이 각각 `done` 및 Discord
회신까지 끝나야 한다. Hook만 믿지 않고 생산 코드의 기동 게이트와 이중으로 막는다.

넓은 경로를 `rm -rf`로 지우지 않는다. `~/.hermes`와 plist·플러그인은 먼저 권한 0700의
명시적 quarantine으로 옮겨 복구 가능하게 보존한다. v4 `tools/hermes-agent`는 unrelated
cron 호출자 0을 증명하거나 중립 경로로 이사하기 전에는 폴더 전체를 제거하지 않는다.

| 단계 | 한 작업방의 인수 기준 | 다음 단계 진입 증거 |
|---|---|---|
| HR-0 | PID·launchd·plist·플러그인·config·세션·cron·Discord 명령·양 레포 import/caller 전수조사 | 모든 항목이 `live caller`/`historical-only`/`removable`, UNKNOWN 0인 JSON |
| HR-1 | 공유 lease·최소권한 RPC·worker heartbeat·event 멱등 확인 후 Claude/Codex/자연어 라이브 왕복 | 두 엔진 `queued → running → done`, 각 Discord response_id, 중복 응답 0 |
| HR-2 | direct gateway는 멈춘 상태로 Hermes 신규 접수만 동결하고 기존 큐를 정리 | 관찰 전후 신규 행 0, 미종료 잡 0 |
| HR-3 | Discord payload 백업 → Hermes bootout/PID 0 → direct gateway lease 1 → 명령 등록·왕복 | direct 1, Hermes 0, 응답 1; 중간 실패 자동 rollback 영수증 |
| HR-4 | plist·플러그인·`~/.hermes`를 quarantine하고 재부팅/launchd 재평가 후 24시간 단독 운영 | Hermes PID 0, 중복 0, lease 위반 0이 24시간 유지 |
| HR-5 | caller 0 또는 move-first 뒤 v4/v5 Hermes runtime 코드 제거, 역사 문서는 RETIRED | 생산 import/call graph runtime 참조 0 |
| HR-6 | owner 승인 후 Discord bot token 회전, 새 비밀 저장소 한 곳만 사용 | 새 토큰 direct 1, 옛 Hermes 재접속 실패, 영수증에는 SHA-256 지문만 |
| HR-7 | 보존기간·최종 승인 뒤 격리본을 휴지통 등 복구 가능한 방식으로 제거하고 운영 문서 정리 | 프로세스·launchd·심링크·비밀 사본·runtime caller 0 |

필수 Hook은 `.claude/hooks/guards/discord-e2e-cutover.py`와
`.claude/hooks/guards/hermes-retirement.py`다. Stop Hook은 PID/launchd/플러그인/미종료 큐 0,
direct gateway lease 1, Claude/Codex 라이브 성공, 원 요청자 response_id, 전체 verify exit 0,
reboot 후 유령 재기동 0, rollback 검증 결과가 없으면 완료 보고를 막는다.

기계 영수증 정본은 `artifacts/discord-cutover/hermes-retirement-receipt.json`이다. 필수 필드는
`schema_version`, `git_sha_v4`, `git_sha_v5`, `phase`, `discord_bot_id`,
`command_fingerprint`, `direct_gateway_pid`, `direct_gateway_lease_id`, `hermes_pid_count`,
`hermes_launchctl_count`, `queue_nonterminal_count`, `claude_job_id`, `claude_response_id`,
`codex_job_id`, `codex_response_id`, `duplicate_response_count`, `quarantine_paths`,
`remaining_runtime_references`, `rollback_tested`, `verified_at`, `verifier_sha256`다.

토큰·쿠키·비밀번호 원문은 코드·로그·영수증·Git에 남기지 않는다. Supabase service-role 키를
direct gateway에 제공하지 않는다. 위 증거가 하나라도 없으면 `Hermes 완전 폐기 완료`라고
보고하지 않는다.

---

## 11. 작업 사다리 (인수 기준 = 작업방 1개)

각 단계는 독립 워크트리 + RED 먼저 + `./verify.sh` GREEN + V1/V2 적대검증.

| AC | 내용 | 완료 판정 |
|---|---|---|
| AC-0 | 능력 인벤토리 확정(§4) + 엣지케이스 사장님 결재(§8) | 문서 GREEN, 사장님 승인 |
| AC-1 | 단일 봇 뼈대 — 기존 게이트웨이 승격, 명령 표면 §6.1 + `/jobs` | 테스트: 명령 파싱·인증·멱등. 실채널 왕복 1건 |
| AC-1.5 | **v4 봇 전용 API 층 신설** — `botTokenGuard` + `/api/bot/jobs`, `/api/bot/kpi` 2개 라우트로 시작 | 봇 토큰으로 200, 토큰 없으면 401. 기존 owner 라우트 회귀 없음 |
| AC-2 | engine 선택(claude\|codex) 종단 연결 | 코덱스로 지정한 잡이 실제 codex 로 실행된 로그 |
| AC-3 | 안전 게이트 G1~G8 + 훅 H1~H4 | 각 게이트 거부 테스트 |
| AC-4 | Fleet-job 탭 (v4) — `AiSearchViewSwitcher.tsx` 3분기 확장(§4 A 참조), `/api/bot/jobs` 소비 | 진행중/완료/실패 표가 실데이터로 보임. 기존 탭 2개 무회귀 |
| AC-5 | 자유 문장 의도 분류기 | 사상 성공·애매·실패 3종 테스트 |
| AC-6 | 조회형 명령(T2·T6·T7·T9 읽기) + `/api/bot/*` 조회 라우트 완성 | 각 명령 실데이터 응답 (T8 은 E22·E25 결정 전까지 제외) |
| AC-7 | 쓰기형 명령(T1·T3·T9 쓰기) + 확인 게이트 | 확인 없이는 미실행 테스트 (T5 는 E22 결정 전까지 제외) |

Hermes retirement는 위 제품 AC와 합치지 않고 SOT 33의 별도 사다리로 실행한다.

| HR | 내용 | 완료 판정 |
|---|---|---|
| HR-0 | 의존성 전수조사 | UNKNOWN 0인 machine-readable inventory |
| HR-1 | 직결 라이브 인수 | Claude/Codex done + Discord response_id + lease_id |
| HR-2 | 신규 Hermes 접수 동결·큐 drain | 신규 행 0 + 미종료 잡 0 |
| HR-3 | 원자적 수신기 전환·rollback | direct 1 + Hermes 0 + 왕복 1 |
| HR-4 | 복구 가능한 격리·24시간 soak | PID/중복/lease 위반 0 |
| HR-5 | caller 증명 후 저장소 runtime 제거 | 생산 import/call graph 참조 0 |
| HR-6 | 토큰 회전·유령 재접속 봉쇄 | 새 token direct 1 + old token Hermes 실패 |
| HR-7 | 보존기간 뒤 최종 폐기·문서 정리 | SOT 33 §6의 최종 조건 전부 참 |

---

## 12. 검증 계약

- 기계 판정: `./verify.sh` exit 0 (출력 숫자 그대로 보고)
- 배선 증명: 각 AC 마다 "실제로 그 경로를 탄다"는 라이브 증거 1건(잡 번호·로그·스크린샷)
- V1: 구현자 자체 적대검증(빈 값·중복·권한 없는 사용자·엔진 미지정·큐 장애)
- V2: Codex Rescue 독립 재검증 — verdict 파일을 `docs/engineering/` 에 남김
- HR-0~HR-7은 한 작업방에 하나만 두고, 각 단계의 SOT 33 완료 단언을 기계 증거로 판정한다.
- HR-4의 기본 24시간 관찰을 줄이거나 코드 삭제와 병행하지 않는다.
- 완료 보고는 CLAUDE.md 0번 규칙대로 **쉬운 한국어**로.
