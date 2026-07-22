# 실행 프롬프트 — 밸류하이어 단일 디스코드 봇 콘솔 (2026-07-22)

> **쓰는 법**: 아래 §0 공통 헤더를 먼저 읽히고, 그다음 **AC 블록 하나만** 골라 붙여넣는다.
> 한 번에 여러 AC 를 붙여넣지 않는다 — 한 AC = 한 워크트리 = 인수 기준 1개(Harness 게이트).
> 설계 SOT: `docs/prompts/discord-single-bot-console-goal-2026-07-22.md` (이하 **GOAL**)

---

## §0. 공통 헤더 (모든 AC 앞에 그대로 붙인다)

```
너는 밸류하이어 v5 저장소에서 작업한다. 아래 규율을 예외 없이 따른다.

[규율]
- 최상위 규칙: /Volumes/SSD/valuehire_v5/CLAUDE.md 의 SOT 불변식 5개. 특히
  (1) 3사 로그인은 자동화가 수행하되 2FA·캡차만 사람에게 넘김
  (2) 사장님이 3사 포털을 만지는 중이면 양보, 60초 무이상 시 자동 재개
  (3) 발송은 SOT28 게이트를 전부 통과할 때만 — 이번 작업에서는 봇의 자동 발송을 만들지 않는다
  (4) 사장님께 보고할 때는 쉬운 한국어 존댓말, 기술 용어 나열 금지
  (5) 내 코드를 믿지 않는다 — 내가 먼저 깨보고, Codex Rescue 가 한 번 더 깬다
- 절차: docs/harness.md 의 게이트를 순서대로. 게이트를 못 통과하면 다음으로 가지 않는다.
- 엄격 모드: docs/sot/30-strict-mode-contract.md 를 적용한다.
- 설계 SOT: docs/prompts/discord-single-bot-console-goal-2026-07-22.md (이하 GOAL). 이 문서와
  충돌하는 판단을 하지 말고, 충돌이 보이면 코드를 고치기 전에 먼저 보고한다.

[작업 격리 — 반드시 지킬 것]
- 메인 작업트리에서 소스를 직접 고치지 않는다. worktrees/<AC이름>/ 에 브랜치 task/<AC이름> 을 판다.
- 그 워크트리 안에서 RED → 구현 → 검증 → PR 까지 끝낸다.

[순서 — 어기면 게이트 위반]
1. 과거 지시 회수: 이 AC 와 겹치는 코드·문서·스킬이 이미 있는지 먼저 찾는다(중복 구현 금지).
   최소한 GOAL §3 의 증거 파일들을 직접 열어 현재 상태를 눈으로 확인한다.
2. RED 먼저: 실패하는 테스트를 tests/ 에 쓰고 커밋한다. 테스트 없이 구현 코드를 쓰지 않는다.
3. 구현: RED 를 GREEN 으로 만드는 최소 변경만. 리팩터링·부수 개선을 섞지 않는다.
4. 검증: ./verify.sh 를 돌리고 출력 숫자를 그대로 보고한다(꾸미지 않는다).
5. 적대검증 V1: 내가 만든 것을 내가 깬다. 최소 아래를 시도하고 결과를 적는다 —
   빈 값 / 잘못된 타입 / 권한 없는 사용자 / 같은 요청 2회 / 외부 장애(큐·API 죽음) / 긴 입력.
6. 적대검증 V2: Codex Rescue 에게 같은 코드를 넘겨 독립 재검증. verdict 를
   docs/engineering/<AC이름>.verdict.json 으로 남긴다.
7. 배송: PR 을 올린다. CI 초록 + merge 전에는 "완료"라고 말하지 않는다.

[보고 형식]
- 사장님께 보고할 때는 쉬운 한국어로 "무엇을 했는지 / 왜 / 다음에 뭘 할지"만.
- 검사 결과는 숫자를 그대로. 안 된 것은 안 됐다고 분명히 쓴다.
- 비밀(토큰·쿠키·비밀번호·API 키)은 어떤 출력에도 넣지 않는다.

[금지]
- SOT 33 HR-1 라이브 영수증과 HR-2 큐 drain 없이 Hermes를 bootout·격리·삭제하지 않는다.
- 봇 토큰당 활성 gateway는 정확히 1개다. Hermes와 direct gateway를 같은 토큰으로 동시에 연결하지 않는다.
- 디스코드에서 임의 셸 명령을 실행하는 기능을 만들지 않는다(사장님이 명시적으로 반려).
- 제안·메일 발송을 자동으로 누르는 코드를 만들지 않는다.
- 기존 v4 의 requireOwner/requireAdmin 동작을 바꾸지 않는다(추가만 한다).
```

---

## AC-0 — 착수 게이트 (결정 수집 + 인벤토리 확정)

```
[AC-0] 착수 게이트. 코드를 쓰지 않는다. 문서만 확정한다.

할 일:
1. GOAL §4 능력 인벤토리의 각 증거(파일:줄)를 직접 열어 지금도 사실인지 재확인한다.
   틀린 것이 있으면 GOAL 을 고치고 무엇이 달랐는지 보고한다.
2. GOAL §8 의 A급 엣지 케이스(E1~E10, E21~E25) 중 "결정" 칸이 빈 항목을 모두 모아
   사장님께 물을 목록으로 정리한다. 각 항목마다 추천안 1개와 그 이유 한 줄을 붙인다.
3. E22(백엔드 없는 T5·T8), E23(고장난 T6)에 대해서는, 각각 별도 작업으로 뺐을 때의
   영향(무엇을 못 하게 되는지)을 한 줄로 적는다.
4. 사장님 결정을 받아 GOAL §8 의 "결정" 칸을 채운다.

완료 판정: GOAL §8 A급 항목의 결정 칸이 모두 채워짐. 코드 변경 0줄.
사장님께: 결정이 필요한 것만 쉬운 말로 묶어서 한 번에 여쭙는다. 여러 번 나눠 묻지 않는다.
```

---

## AC-1 — 단일 봇 뼈대

```
[AC-1] 디스코드 단일 봇의 뼈대를 세운다. 새로 짜지 말고 기존 것을 승격한다.

바탕: scripts/discord_direct_gateway.py (705줄, 현재 꺼져 있음). 이 파일에는 이미
신원 확인·감사로그·멱등키·최소권한 큐 클라이언트가 들어 있다. 지우고 새로 짜지 않는다.

이번 AC 의 범위(딱 이만큼만):
- 실행형 명령 5개: /aisearch /humansearch /url /login /skill  (GOAL §6.1)
  · 공통 인자 engine: claude|codex, machine: macmini|macbook|winpc
  · /skill 은 DB 화이트리스트가 3종으로 막혀 있으므로(GOAL §4 T4), 이번에는 명령만 만들고
    허용 목록 밖이면 "아직 지원하지 않습니다"로 거부한다. 마이그레이션은 AC 밖.
- 조회형 명령 1개: /jobs — 최근 작업 상태 요약 + 웹 링크
- 명령을 받으면 큐에 넣고 즉시 잡 번호를 회신한다. 봇 프로세스 안에서 브라우저를 열지 않는다.

먼저 옮길 것(안 하면 봇이 기동 불가):
- tools/multi_position_sourcing/direct_receiver.py:38 이 hermes_fleet_bridge 를 import 한다.
  거기서 쓰는 파싱 함수를 헤르메스 이름이 안 붙은 새 모듈로 먼저 옮긴다. 원본은 아직 지우지 않는다
  (Hermes는 SOT 33 HR-3 원자적 전환 전까지 살아 있어야 한다). 이사 후 기존 테스트가 계속 통과해야 한다.

RED 로 먼저 쓸 테스트(최소):
- 허용되지 않은 사용자의 명령 → 거부되고 큐에 안 들어감
- 허용되지 않은 채널의 명령 → 거부
- 같은 디스코드 event_id 로 두 번 → 잡은 1개, 두 번째는 기존 잡 번호 회신
- engine 미지정 → params.agent 가 claude
- engine:codex → params.agent 가 codex
- 잘못된 URL(스킴 없음, 공백 포함, 제어문자) → 거부
- 큐가 죽었을 때 → 명령을 삼키지 않고 "지금 접수 불가"를 회신
- /skill 로 화이트리스트 밖 스킬 → 거부

완료 판정:
- ./verify.sh exit 0 (숫자 그대로 보고)
- 실채널 왕복 1건: 디스코드에서 /aisearch 를 실제로 쳐서 잡 번호가 돌아오고,
  jobs 테이블에 queued 행이 생긴 것을 확인(잡 번호를 증거로 남긴다).
  ※ 실채널 테스트는 사장님 승인을 받고 진행한다. 승인 전에는 실행하지 않는다.
```

---

## AC-1.5 — v4 봇 전용 API 층

```
[AC-1.5] v4(/Volumes/SSD/valuehire_v4)에 봇 전용 API 층을 만든다.

배경: 봇은 브라우저가 아니라서 v4 의 세션 쿠키 인증(requireOwner/requireAdmin)을 통과할 수
없다. 그래서 봇 전용 토큰 인증을 "추가"한다. 기존 가드는 절대 건드리지 않는다.

이번 AC 의 범위(딱 2개 라우트만):
- src/auth/botTokenGuard.ts (신규): Authorization: Bearer <VALUEHIRE_BOT_TOKEN> 검사.
  · 토큰은 환경변수에서만 읽는다. 코드·로그·에러 본문에 절대 찍지 않는다.
  · 상수 시간 비교를 쓴다(타이밍 공격 방지).
  · 토큰 미설정이면 이 가드는 항상 거부한다(fail-closed). 조용히 통과시키지 않는다.
- app/api/bot/jobs/route.ts (신규, GET): public.jobs 조회.
  · v4 표준 패턴을 따른다 — src/lib/supabase.ts 의 createServerSupabaseClient()(service_role).
  · 응답에 requested_by 원문·params 전문 같은 민감정보를 그대로 싣지 않는다(필요한 것만).
  · 상태별 필터(queued/running/paused_for_human/done/failed/cancelled)와 개수 제한 지원.
- app/api/bot/kpi/route.ts (신규, GET): 기존 app/api/admin/owner/metrics/weekly 의
  계산 로직을 재사용한다. 계산식을 복사해서 다시 구현하지 않는다(SOT 이중화 금지).

RED 로 먼저 쓸 테스트(최소):
- 토큰 없음 → 401
- 틀린 토큰 → 401
- 환경변수 미설정 → 맞는 토큰을 보내도 거부
- 올바른 토큰 → 200 + 예상 스키마
- 기존 owner 라우트가 그대로 동작(회귀 없음)
- 응답 본문에 토큰·service_role 키가 섞여 나오지 않음

완료 판정: v4 테스트 GREEN + 기존 owner 라우트 무회귀 증명.
주의: v4 는 별도 저장소다. v4 안에서도 워크트리를 파고, v4 의 검증 명령(package.json 확인)을 쓴다.
```

---

## AC-2 — 엔진 선택(클로드/코덱스) 종단 연결

```
[AC-2] /aisearch engine:codex 로 넣은 잡이 실제로 codex 로 실행되는지 끝까지 연결한다.

이미 있는 것(새로 만들지 말 것):
- tools/multi_position_sourcing/fleet_worker.py:415 _run_claude, :486 _run_codex
- 같은 파일 :835-848 — params.agent == "codex" 면 코덱스로 분기하고 라벨도 codex 로 표기

할 일: 봇 → 큐 → 워커까지 params.agent 가 끊기지 않고 전달되는지 확인하고, 끊긴 곳을 잇는다.

RED 로 먼저 쓸 테스트:
- engine:codex 로 만든 잡의 params.agent 가 큐 행에 그대로 저장됨
- 워커가 그 잡을 집었을 때 선택된 실행기가 codex 이고, 결과 라벨도 codex 로 기록됨
- engine 미지정 → claude
- engine 값이 이상함(대문자, 공백, 모르는 이름) → 거부. 조용히 claude 로 떨어뜨리지 않는다
- (E8 결정 반영) 그 머신에 코덱스가 없을 때의 동작 — AC-0 에서 사장님이 정한 대로 구현

완료 판정: ./verify.sh GREEN + 코덱스로 실제 실행된 잡 1건의 로그를 증거로 제출.
```

---

## AC-3 — 안전 게이트 + 하네스 훅

```
[AC-3] GOAL §7 의 게이트 G1~G8 과 §9 의 훅 H1~H4 를 건다. 문장 지시가 아니라 코드로 막는다.

훅 구조(이미 있는 것을 쓴다): .claude/hooks/guards/<이름>.py 에 check(tool, tool_input) 를
두면 모든 툴 호출에 문이 걸린다. 사유 문자열을 반환하면 차단. 템플릿은 guards/_template.py,
예시는 guards/runner-lease.py, 테스트는 .claude/hooks/tests/ 를 본다.

만들 훅 4개:
- guards/discord-bot-send.py       : 잡 실행 중 제안·메일 발송 도구 호출 차단
- guards/discord-bot-login-gate.py : 로그인 영수증 없이 검색 스킬 도구 호출 차단
                                     (영수증: artifacts/portal_session_status_latest.json)
- guards/discord-bot-skill-whitelist.py : 허용 목록 밖 스킬 발동 차단
- Stop 훅 확장 : 결과 증거(건수·요약) 없이 "완료" 보고하면 차단

중요 — 훅만 믿지 말 것:
harness-dispatch.py 는 가드 로드가 실패하면 fail-open(통과)이다. 즉 훅은 2층 방어일 뿐이다.
1층은 봇 코드 안의 게이트(GOAL §7)여야 한다. 두 층을 모두 만들고, 각각 따로 테스트한다.

RED 로 먼저 쓸 테스트: 각 게이트마다 "막혀야 하는 요청이 실제로 막히는지" 1건씩 + 정상 요청이
막히지 않는지 1건씩. 훅 테스트는 .claude/hooks/tests/ 패턴을 따른다.

완료 판정: ./verify.sh GREEN + 게이트별 거부 증거.
```

---

## AC-4 — Fleet-job 탭 (v4)

```
[AC-4] admin.valuehire.cc/ai-search-list 에 세 번째 탭 "Fleet-job" 을 만든다.

고칠 파일(정확히 이 지점들):
- app/ai-search-list/_components/AiSearchViewSwitcher.tsx
  · :14  type ViewKey = "list" | "clickup"  →  "fleet" 추가
  · :16-21 props 인터페이스에 fleet 데이터 prop 추가
  · :24-30 useState / useEffect 딥링크 파싱이 ?view=fleet 를 인식하도록
  · :45-52 role="tablist" 안에 세 번째 버튼 추가(aria-selected, tabStyle 동일 패턴)
  · :53 삼항 2분기 → 3분기
- app/ai-search-list/_components/FleetJobView.tsx (신규)
- app/ai-search-list/page.tsx:49-58 Promise.all 에 로더 추가

화면 요구(사장님 요구 R6):
- 진행중 / 완료 / 실패를 한 표에서 구분해 볼 수 있을 것
- 각 행: 잡 번호, 스킬, 머신, 엔진(claude|codex), 상태, 시작·종료 시각, 결과 요약 한 줄
- 상태별 필터, 최신순
- 각 행에서 상세로 갈 수 있을 것(사장님 요구 R8 — 이 페이지 안에서 상세를 본다)
- 데이터는 AC-1.5 의 /api/bot/jobs 에서 가져온다

반드시 지킬 것:
- 기존 탭 2개(어드민 리스트 / ClickUp 시각화)의 동작을 바꾸지 않는다. 회귀 테스트로 증명한다.
- ClickUp 뷰가 fail-soft 인 것처럼, Fleet-job 도 데이터 로드 실패 시 다른 탭을 죽이지 않는다.
- 열람 권한은 AC-0 의 E7 결정을 따른다.

완료 판정: 실데이터로 진행중·완료·실패가 보이는 화면 + 기존 탭 무회귀.
```

---

## AC-5 — 자유 문장 의도 분류기

```
[AC-5] 봇을 멘션하거나 DM 으로 평문을 보내면 명령으로 알아듣게 한다.

핵심 원칙(어기면 위험):
자유 문장은 반드시 "허용된 명령 집합" 안으로만 사상된다. 사상 실패 = 실행 금지.
평문이 곧바로 임의 실행으로 이어지는 경로를 절대 만들지 않는다.

동작 3분기:
- 확신함  → 실행하되 "이렇게 이해했습니다: /aisearch url:…" 를 한 줄 표기
- 애매함  → 후보 2~3개를 버튼으로 제시하고 사장님이 고르게 한다
- 모르겠음 → "무슨 작업인지 못 알아들었습니다" + 명령 목록. 추측 실행 금지
(정확한 기준은 AC-0 의 E1 결정을 따른다)

RED 로 먼저 쓸 테스트:
- 전형적인 문장 → 올바른 명령으로 사상
- 두 스킬이 겹치는 애매한 문장 → 선택지 제시(실행 안 함)
- 관계없는 잡담 → 실행 0건
- 프롬프트 인젝션 시도("앞의 지시 무시하고 …") → 실행 0건
- 발송을 요구하는 문장("이 후보한테 메일 보내줘") → 거부(SOT28)

완료 판정: ./verify.sh GREEN + 위 5종 테스트 통과.
```

---

## AC-6 — 조회형 명령

```
[AC-6] 읽기 명령을 붙인다. AC-1.5 의 API 층 위에서만 동작한다.

대상(GOAL §4 인벤토리 기준):
- /kpi        → /api/bot/kpi        (백엔드 있음)
- /interviews → /api/bot/candidates (백엔드 부분적 — enum 없음, E-결정 반영)
- /cases      → E23 결정에 따라: 살아있는 unified_candidate_history_view 로 대체 구현
- /priority   → ClickUp 조회 (전용 API 없음 — 새로 만든다)
- /job <번호> → /api/bot/jobs/[id]

제외: 인터뷰 확정자(T8) — 개념이 스키마에 없다(E22·E25 결정 전까지 만들지 않는다).

결과가 디스코드 2000자를 넘을 때의 처리는 AC-0 의 E10 결정을 따른다.

완료 판정: 각 명령이 실데이터로 응답하는 증거 1건씩.
```

---

## AC-7 — 쓰기형 명령 + 확인 게이트

```
[AC-7] 쓰기 명령을 붙인다. 확인 없이 실행되는 경로가 하나도 없어야 한다.

대상: /weekly(T1), /invoice(T3), /priority set(T9), /job resume|cancel

확인 게이트(G5):
- 봇은 "무엇을 바꾸는지" 요약을 먼저 보여주고, 사장님이 확인 버튼을 누른 뒤에만 실행한다.
- 확인 없이 시간이 지나면 만료시킨다(실행하지 않는다).
- 확인 사실을 감사로그에 남긴다(누가·언제·무엇을).

계산서(/invoice) 특별 취급:
등록하면 배분 3행이 자동 생성되고 컨설턴트에게 메일이 자동 발송된다(되돌리기 어려움).
AC-0 의 E3 결정을 그대로 따른다. 결정이 "초안만"이면 봇은 절대 발행 API 를 호출하지 않는다.

RED 로 먼저 쓸 테스트:
- 확인 없이 실행 시도 → 아무 것도 안 바뀜(DB 무변화를 증명)
- 확인 만료 후 → 실행 안 됨
- 다른 사람이 대신 확인 → 거부
- 같은 확인을 두 번 → 1회만 실행

완료 판정: ./verify.sh GREEN + "확인 없이는 안 바뀐다"를 DB 상태로 증명.
```

---

## Hermes retirement 공통 실행 헤더

> 아래 HR 블록은 SOT 33(`docs/sot/33-hermes-retirement.md`)의 실행 프롬프트다.
> **한 작업방에는 인수 기준 하나만** 둔다. HR 블록을 둘 이상 한 작업방에 붙이지 않는다.

```text
[공통 절대 규칙]
- Discord 입력 → 단일 direct gateway → 자연어/슬래시 해석 → 영속 큐 → fleet worker
  → Claude Code 또는 Codex → 원 요청자에게 결과 회신 경로만 현재 경로로 만든다.
- 새 직결 봇 실증 전에 Hermes를 중단하거나 삭제하지 않는다.
- 봇 토큰당 활성 gateway는 정확히 1개다. 같은 이벤트를 두 수신자가 동시에 받으면 FAIL이다.
- queued/running/paused_for_human이 0이고 Claude/Codex 실작업의 done+Discord 회신 영수증이
  모두 생기기 전에는 폐기 단계로 가지 않는다.
- Hook과 생산 코드 기동 게이트를 이중으로 둔다. Hook 로드 실패도 fail-closed다.
- ~/.hermes 같은 넓은 경로를 rm -rf 하지 않는다. 권한 0700의 명시적 quarantine으로 먼저 옮긴다.
- 토큰·쿠키·비밀번호·service-role 원문은 출력·로그·영수증·Git에 남기지 않는다.
- 각 HR은 RED→GREEN→전체 verify→독립 재검증→PR/CI/merge까지 끝내고 다음 HR로 간다.
- 영수증 정본은 artifacts/discord-cutover/hermes-retirement-receipt.json이다.
```

## HR-0 — 의존성 전수조사

```
[HR-0] 코드나 프로세스를 중단·격리·삭제하지 않는다. 의존성 inventory 하나만 완성한다.

PID, launchd label/plist, 플러그인 심링크, config, 세션, cron, Discord 명령, 양 레포 import와
호출자를 조사한다. 최소 대상은 SOT 33 §3 HR-0의 7개 경로다.

산출물: artifacts/discord-cutover/hermes-dependency-inventory.json
각 발견 파일은 live caller / historical-only / removable 중 정확히 하나로 분류한다.
호출자가 남으면 move_first를 표시한다. UNKNOWN이 하나라도 남으면 실패다.

RED: 일부러 분류 없는 fixture와 호출자 있는 디렉터리 삭제 후보를 넣어 검사기가 거부함을 증명한다.
완료: UNKNOWN 0, 모든 항목 근거·호출자 포함, 전체 verify와 독립 재검증 통과.
```

## HR-1 — direct gateway 라이브 인수

```
[HR-1] Hermes를 삭제하지 않는다. direct gateway 경로의 라이브 인수만 증명한다.

공유 lease, 운영 최소권한 RPC, worker heartbeat가 모두 유효할 때만 gateway를 시작한다.
같은 event_id 두 번 → job_id 하나를 증명한다. engine=claude 1건, engine=codex 1건,
자연어 입력 1건을 실제 Discord에서 처리한다. 두 엔진 잡은 queued→running→done이고 원 요청자
response_id가 정확히 하나여야 한다. Hermes와 동시 응답이면 즉시 FAIL이다.

같은 운영 토큰으로 Hermes와 direct gateway를 동시에 연결하지 않는다. 격리 test bot identity나
통제된 단독 연결 구간을 쓴다. 실증 후 direct gateway는 HR-2 동안 다시 멈춘다.

영수증: event_id, job_id, agent, 상태전이, Discord response_id, gateway lease_id.
```

## HR-2 — Hermes 신규 접수 동결·큐 drain

```
[HR-2] direct gateway는 아직 시작하지 않는다. Hermes 신규 접수만 동결한다.

기존 queued/running/paused_for_human을 완료 또는 owner 취소로 0까지 정리한다. 관찰 구간 전후
jobs 증가 0을 기계 검사한다. Hermes 프로세스와 로그인 브라우저는 아직 종료하지 않는다.

완료: 신규 행 0, queue_nonterminal_count 0. 둘 중 하나라도 아니면 HR-3 금지.
```

## HR-3 — 원자적 수신기 전환과 rollback

```
[HR-3] SOT 33 순서 그대로 한 번에 전환한다.

1) Discord 명령 payload 백업
2) direct 설정·lease readiness 검사(아직 연결 금지)
3) Hermes launchctl bootout
4) Hermes PID·Discord 연결 0 확인
5) direct gateway 기동·공유 lease 획득 확인
6) 실제 처리할 명령만 Discord 등록
7) 승인 테스트 명령 1건 왕복

중간 실패 자동 rollback: direct 중단 → 명령 payload 복구 → Hermes plist/플러그인 원위치
→ Hermes gateway 재기동 → 실패 원인·복구 결과 영수증 기록.

완료: direct gateway 1, Hermes gateway 0, 같은 명령 응답 1, rollback_tested=true.
```

## HR-4 — 복구 가능한 격리와 24시간 단독 운영

```
[HR-4] 코드는 삭제하지 않는다. plist·valuehire 플러그인·~/.hermes를 권한 0700의 명시적
quarantine으로 이동한다. 비밀 파일 내용·목록을 로그나 archive listing으로 출력하지 않는다.

launchd 재평가와 재부팅 뒤 Hermes PID 0을 확인한다. direct gateway를 기본 24시간 단독 운영한다.
중복 응답·큐 고착·회신 유실·heartbeat 단절이 있으면 HR-5로 가지 않고 HR-3 rollback을 판정한다.

완료: 24시간 Hermes PID 0, duplicate_response_count 0, direct lease 위반 0.
```

## HR-5 — 저장소 runtime 코드 제거

```
[HR-5] SOT 33의 v4/v5 제거 후보마다 HR-0 inventory를 다시 대조한다.

direct_receiver 파싱은 fleet_args 등 중립 모듈 이사 완료를 먼저 증명한다. tools/hermes-agent 아래
outstanding-news 등 unrelated cron 호출자는 중립 디렉터리로 먼저 이사한다. caller가 남은 폴더는
삭제하지 않는다. 역사 문서는 RETIRED로 남기고 현재 운영 문서·SKILL.md의 Hermes 권장은 제거한다.

완료: 생산 import/call graph Hermes runtime 참조 0. 남은 문자열은 역사/retirement allowlist만.
```

## HR-6 — 토큰 회전과 유령 재접속 봉쇄

```
[HR-6] 24시간 안정 증거와 owner 승인 후에만 Discord bot token을 회전한다.

새 토큰은 direct gateway 비밀 저장소 한 곳에만 쓴다. 옛 토큰을 가진 격리 Hermes 연결 실패를
확인한다. 영수증에는 SHA-256 지문만 기록한다. Supabase service-role 키를 gateway에 주지 않는다.

완료: 새 token으로 direct gateway 1개, old token Hermes 재접속 실패.
```

## HR-7 — 최종 폐기와 문서 정리

```
[HR-7] quarantine 보존기간 종료와 owner 최종 승인 뒤에만 격리본을 휴지통 등 복구 가능한 방식으로
제거한다. launchd plist·플러그인 심링크·~/.hermes 원위치가 모두 없어야 한다.

docs/search-access.md와 SOT 29·31·33을 Discord → direct gateway → queue → worker로 통일하고,
과거 Hermes 문서는 폐기됨+최종 폐기일을 표시한다.

필수 Hook:
- .claude/hooks/guards/discord-e2e-cutover.py
- .claude/hooks/guards/hermes-retirement.py
- Stop Hook 완료증거 확장(SOT 33 §4.3)

최종 영수증 필수 필드:
schema_version, git_sha_v4, git_sha_v5, phase, discord_bot_id, command_fingerprint,
direct_gateway_pid, direct_gateway_lease_id, hermes_pid_count, hermes_launchctl_count,
queue_nonterminal_count, claude_job_id, claude_response_id, codex_job_id, codex_response_id,
duplicate_response_count, quarantine_paths, remaining_runtime_references, rollback_tested,
verified_at, verifier_sha256.

PID/launchd/플러그인/비밀 사본/runtime caller 0, direct lease 1, Claude/Codex 실제 회신,
중복 0, reboot 후 유령 0, 전체 verify, 기계 영수증이 전부 있어야만 완료라고 보고한다.
```

---

## 부록 — 사장님께 보고할 때의 문장 예시

| 상황 | 이렇게 말한다 |
|---|---|
| 검사 통과 | "검사 다 통과했어요(393개). 이상 없습니다." |
| 일부 실패 | "검사 393개 중 2개가 실패했습니다. 원인은 ○○이고, 지금 고치는 중입니다." |
| 작업방 | "따로 작업방 만들어서 고치고, 올렸습니다." |
| 올릴 준비 | "올린 거 합쳐도 되는 상태예요. 검사도 통과했고요." |
| 막혔을 때 | "○○ 때문에 막혔습니다. 사장님이 △△를 정해주셔야 다음으로 갑니다." |
