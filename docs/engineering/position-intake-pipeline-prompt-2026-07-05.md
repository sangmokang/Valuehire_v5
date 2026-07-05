# 포지션 인입 파이프라인 붙여넣기용 프롬프트 (Gmail 감시 → ClickUp 등록 → /url·JD 조리 자동 후속)

> 배경(2026-07-05 사장님 지시): "포지션이 들어오면, Gmail 에서 상시 돌고 있다가 고객 메일을 긁어
> 바로 클릭업에 등록하고, 링크드인 검색 사전세팅까지. 클릭업 URL 을 프롬프트에 안 붙여도 프로세스에
> 들어가게." — 근거 가이드: `docs/engineering/skill-trio-url-aisearch-humansearch-guide-2026-07-05.md` §4.5
>
> 현황(코드 확인): 클릭업 등록 디스패처는 **있다**(`tools/multi_position_sourcing/register_position_dispatch.py`,
> PR#68 PC-A3). 없는 건 ① Gmail 인입 감지 ② 등록 성공 → /url·JD 조리 자동 후속, 두 조각뿐이다.
>
> ⚠️ v4 코드 절대 금지(`ai-search-no-v4-code`). Gmail 은 자체 OAuth 데몬을 새로 짜지 말 것 —
> Claude Code 의 Gmail MCP(`mcp__claude_ai_Gmail__search_threads` 등)와 스케줄 실행(cron/routine)을 쓴다.

---

## A. 개발용 프롬프트 (조각별로 아래 블록을 그대로 붙여넣기 — 한 조각 = 한 세션)

### 조각 1 — PI-1: Gmail 인입 파서 (메일 → 등록 요청)

```
/st 포지션 인입 파이프라인 조각 PI-1을 harness 게이트대로 구현해라.

너는 Valuehire_v5(/Users/kangsangmo/Valuehire_v5)에서 일한다. 최상위 규칙은 CLAUDE.md(SOT)와
docs/harness.md. 보고는 쉬운 한국어. 한 조각 = 한 worktree = 인수기준 1개. RED 먼저.

[목표] 고객 포지션 메일(제목+본문 텍스트)을 받아, 기존 등록 파서가 소비할 수 있는
"포지션 등록 …" 메시지로 변환하는 순수함수 build_registration_message_from_email 을
tools/multi_position_sourcing/ 에 추가한다. 네트워크·Gmail 호출 없음(입력은 문자열) —
Gmail 읽기는 조각 3의 스케줄 러너가 MCP로 한다.

[재사용(SOT5) — 먼저 읽고 재구현 금지]
- tools/multi_position_sourcing/request_parser.py — parse_discord_position_registration_request
  가 최종 소비자다. 이 파서가 인식하는 형식("포지션 등록 <url>" / "포지션 등록\n<JD본문>")으로만
  변환한다. 파서 자체를 고치지 않는다.
- tools/multi_position_sourcing/register_position_dispatch.py — _registration_message_from_invocation
  의 조립 패턴 참고(같은 계약).

[인수기준(기계검증 1개)] 픽스처 3종 — ①채용 URL 포함 메일 ②JD 본문만 있는 메일
③포지션 아닌 일반 메일 — 에 대해 ①②는 parse_result.should_route_to_registration == True,
③은 False(빈 문자열 반환, fail-closed). pytest 는 .venv/bin/python 으로.

[비범위] Gmail API 호출, ClickUp 쓰기, /url 실행. 발송 0(SOT3).
```

### 조각 2 — PI-2: 등록 성공 → 후속 작업 큐 (검색 세팅·JD 조리 예약)

```
/st 포지션 인입 파이프라인 조각 PI-2를 harness 게이트대로 구현해라. (PI-1 merge 후)

[목표] run_position_registration 성공 결과(RegistrationOutcome)를 받아, 후속 작업 2건
— {"task": "url_presetting"}(=/url 검색 사전세팅), {"task": "jd_set_build"}(=JD 조리) —
을 로컬 큐 파일(~/.vh-data/ 아님, 레포 밖 데이터 디렉토리는 humansearch persistence 관례 재사용)에
멱등 기록하는 enqueue_position_followups 를 추가한다. 같은 포지션 재등록 시 중복 큐 금지(upsert).

[재사용] tools/multi_position_sourcing/position_registration.py 의 RegistrationOutcome ·
FY26_CLIENTS_POSITION_LIST_ID(901814621569 — 리스트 ID는 코드 상수 재사용, 하드코딩 복제 금지).

[인수기준] 등록 성공 픽스처 → 큐에 정확히 2건, 같은 입력 2회 호출 → 여전히 2건(멱등),
등록 실패(outcome 실패 플래그) → 0건. RED 먼저, pytest exit 0 숫자 그대로.

[비범위] /url·jd builder 실제 실행(그건 조각 3의 러너가 큐를 읽어 스킬로 수행), 발송 0.
```

### 조각 3 — PI-3: 스케줄 러너 (Gmail MCP 폴링 + 큐 소화)

```
/st 포지션 인입 파이프라인 조각 PI-3(운영 배선)을 진행해라. (PI-1·PI-2 merge 후)

[목표] 정기 실행 루틴(스케줄/cron) 하나를 만든다. 한 턴에:
1. Gmail MCP(search_threads)로 최근 N시간 고객 포지션 메일 검색(라벨/발신자 조건은
   dev@valueconnect.kr 계정에서 사장님과 합의한 쿼리 1개로 고정, 프롬프트에 명시).
2. 새 메일이면 PI-1 파서 → PI-2 계약대로 dry_run 등록 미리보기를 만들어 **사장님 DM 승인 후**
   실제 ClickUp 등록(외부 쓰기는 L3 — 자동 등록 전 승인 게이트, 단 사장님이 "자동 등록 허용"을
   명시하면 그때부터 무승인 등록).
3. 등록된 포지션은 후속 큐를 소화: /url 로 링크드인 검색 사전세팅 → "jd builder"로 JD 셋 조리
   (둘 다 저장까지만, Send 0).
4. 사장님 크롬 점유 시 양보 후 자동 재개(R4), 캡차/차단 시 해당 채널 STOP, 보고는 DM 한 건으로 묶기.

[인수기준] 라이브 1회: 테스트 메일 1건 → ClickUp 포지션 Task 생성 확인(링크 첨부) →
그 Task 댓글에 /url 산출물(라이브 검색 링크+레시피) 확인 → RPS 템플릿 저장 확인. 셋 다 증거 첨부.
```

---

## B. 운영용 한 마디 (개발 완료 전에도 지금 바로 쓰는 수동 버전)

| 하고 싶은 것 | 붙여넣을 말 |
|---|---|
| 방금 온 고객 메일로 포지션 등록+검색세팅+JD조리까지 | `이 메일로 포지션 등록하고, /url 사전세팅에 jd builder까지 해줘: <메일 본문 붙여넣기 또는 Gmail 제목>` |
| 등록만 | `포지션 등록 <채용 URL 또는 JD>` |
| 검색 세팅만 | `/url <회사, 역할>` (전수는 그냥 `/url`) |
| JD 조리만 | `jd builder <회사, 역할>` |

클릭업 URL 은 어디에도 안 붙여도 된다 — 포지션 리스트(901814621569)·후보 결과 리스트(901818680208)는 스킬 기본값.
