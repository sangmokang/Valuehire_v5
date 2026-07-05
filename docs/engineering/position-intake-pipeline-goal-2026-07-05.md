# 포지션 인입 파이프라인 구현 목표 (2026-07-05)

## 현재 상태 증거

- `docs/engineering/position-intake-pipeline-prompt-2026-07-05.md:25`-`28` — Gmail 메일 텍스트를 기존 등록 파서가 소비할 `"포지션 등록 ..."` 메시지로 바꾸는 순수함수가 필요하다.
- `docs/engineering/position-intake-pipeline-prompt-2026-07-05.md:31`-`35` — 최종 소비자는 `parse_discord_position_registration_request`이고, 파서 자체는 고치지 않는다.
- `docs/engineering/position-intake-pipeline-prompt-2026-07-05.md:49`-`58` — 등록 성공 결과를 받아 `url_presetting`, `jd_set_build` 2개 후속 작업을 멱등 큐에 넣어야 한다.
- `docs/engineering/position-intake-pipeline-prompt-2026-07-05.md:68`-`76` — 정기 루틴은 Gmail MCP 검색 → 승인 게이트 → 등록 → 후속 큐 소화 순서이며, 자동 발송은 없다.
- `tools/multi_position_sourcing/request_parser.py:49`-`130` — 등록 라우팅은 기존 파서가 결정한다.
- `tools/multi_position_sourcing/position_registration.py:57` — FY26ClientsPosition 리스트 ID 단일 상수는 `FY26_CLIENTS_POSITION_LIST_ID`다.
- `tools/multi_position_sourcing/position_registration.py:296`-`399` — 등록 결과 타입은 `RegistrationOutcome`; 모든 등록 경로는 `external_posting_sent=False`, `secret_emitted=False`를 유지한다.
- `tools/multi_position_sourcing/register_position_dispatch.py:37`-`45` — 기존 디스패처는 파서가 먹는 `"포지션 등록"` 메시지를 조립한다.

## 근본 원인

클릭업 등록 경로는 이미 있지만, 고객 메일을 이 경로의 입력 shape로 바꾸는 순수 인입부와 등록 완료 후 `/url`/`jd builder` 후속 작업을 예약하는 큐가 없다. 정기 루틴도 외부 Gmail/ClickUp 실행을 직접 안전하게 감싸는 계약이 없어 승인 전 실제 write를 막는 로컬 게이트가 없다.

## 인수 기준

1. PI-1: `build_registration_message_from_email(subject, body)`는 채용 URL 메일과 JD 본문 메일을 기존 등록 파서가 라우팅할 수 있는 메시지로 바꾸고, 일반 메일은 빈 문자열로 fail-closed 한다.
2. PI-2: `enqueue_position_followups(outcome, ...)`는 성공한 `RegistrationOutcome`에 대해 `url_presetting`, `jd_set_build` 두 작업만 큐에 기록한다. 같은 포지션을 2회 넣어도 큐는 2건이다. 실패/스킵 결과는 큐에 넣지 않는다.
3. PI-3: `run_scheduled_position_intake(...)`는 고정 Gmail 검색 쿼리를 MCP 어댑터에 넘긴다. 자동 허용 또는 메시지별 승인 전에는 dry-run preview만 만들고 큐에 넣지 않는다. 승인 후에만 등록 결과로 후속 큐를 만든다.
4. 후속 큐 소화는 사장님 크롬 점유 또는 채널 차단 신호에서 실행자 호출 0회로 멈춘다. 실제 `/url`/`jd builder` 실행은 주입형 executor에 맡기고, 자동 send 작업은 만들지 않는다.

## 입력/출력 계약

- 입력: `subject: str`, `body: str` 또는 `IntakeEmail(message_id, subject, body, from_email, received_at)`.
- 등록 메시지 출력: `""` 또는 `"포지션 등록 <url>"` 또는 `"포지션 등록\n<JD본문>"`.
- 후속 큐 항목: `position_key`, `task`, `status`, `task_id`, `task_url`, `clickup_list_id`, `created_at`, `updated_at`, `dry_run`.
- 후속 작업 task 값: `url_presetting | jd_set_build`만 허용한다.
- 승인 상태 전이: `ignored` → `approval_required`(dry-run only) → `registered`(approved/auto) → `queued` → `done|blocked`.

## 비범위

- Gmail OAuth 데몬 신규 구현.
- 실제 Gmail 읽기, 실제 ClickUp 쓰기, 실제 `/url`/`jd builder` 실행.
- Discord/메일/LinkedIn/포털 발송 자동 클릭.
- 기존 등록 파서 확장 또는 임의 포털 URL 등록 파서 확장(PC-A4 범위).

## 검증 명령

- `make red-ledger`
- focused: `.venv/bin/python -m pytest tests/test_position_intake_pipeline.py -q` (fallback: `python3 -m pytest ...`)
- full: `./verify.sh`

## SOT 체크리스트

- `CLAUDE.md` SOT: 발송 자동 금지, 사장님 크롬 점유 시 양보, 두 번 깨기.
- `docs/harness.md`: RED → GREEN, worktree, verify.
- `docs/sot/25-ai-search-execution-process.json`: INV2/INV3/INV4 준수.
- `docs/sot/26-portal-login-spec.json`: 캡차/멀티세션 자동 우회 금지.
- `docs/sot/27-humansearch-browsing-preflight.json`: fail-closed, 반복 retry 금지.
