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
- `docs/engineering/pc-a1-clickup-live-write.verdict.json:8` — 실제 ClickUp writer 없이 계약형 페이크로 목적지 배선만 검증된 상태다.
- `/Users/kangsangmo/Desktop/valuehire_v4/tools/gmail-recommendation-clickup-sync/run.mjs:216`-`235` — 기존 Gmail 동기화는 처리한 message id를 state에 남겨 같은 메일 반복 처리를 막는다. 단 자체 Gmail OAuth 방식이라 이번 구현에는 재사용하지 않는다.
- `tools/multi_position_sourcing/harvest_driver.py:13`-`18` — 기존 상시 드라이버는 launchd/스케줄러가 부를 CLI를 두고, fake/live 실행자 종류를 출력에 명시해 라이브인 척하지 않는다.
- ClickUp 공식 문서(2026-07-05 확인): Create Task는 `POST https://api.clickup.com/api/v2/list/{list_id}/task`, Create Task Comment는 `POST https://api.clickup.com/api/v2/task/{task_id}/comment`, Get Tasks는 `GET https://api.clickup.com/api/v2/list/{list_id}/task`다.

## 근본 원인

클릭업 등록 경로는 이미 있지만, 고객 메일을 이 경로의 입력 shape로 바꾸는 순수 인입부와 등록 완료 후 `/url`/`jd builder` 후속 작업을 예약하는 큐가 없다. 정기 루틴도 외부 Gmail/ClickUp 실행을 직접 안전하게 감싸는 계약이 없어 승인 전 실제 write를 막는 로컬 게이트가 없다.

## 인수 기준

1. PI-1: `build_registration_message_from_email(subject, body)`는 채용 URL 메일과 JD 본문 메일을 기존 등록 파서가 라우팅할 수 있는 메시지로 바꾸고, 일반 메일은 빈 문자열로 fail-closed 한다.
2. PI-2: `enqueue_position_followups(outcome, ...)`는 성공한 `RegistrationOutcome`에 대해 `url_presetting`, `jd_set_build` 두 작업만 큐에 기록한다. 같은 포지션을 2회 넣어도 큐는 2건이다. 실패/스킵 결과는 큐에 넣지 않는다.
3. PI-3: `run_scheduled_position_intake(...)`는 고정 Gmail 검색 쿼리를 MCP 어댑터에 넘긴다. 자동 허용 또는 메시지별 승인 전에는 dry-run preview만 만들고 큐에 넣지 않는다. 승인 후에만 등록 결과로 후속 큐를 만든다.
4. PI-3 상태 저장: `state_path`를 명시한 정기 루틴은 `pending_approval_message_ids`와 `processed_message_ids`를 기록한다. 승인 대기 중인 같은 메일은 dry-run preview를 반복하지 않고, 등록 완료된 같은 메일은 재등록하지 않는다.
5. 후속 큐 소화는 사장님 크롬 점유 또는 채널 차단 신호에서 실행자 호출 0회로 멈춘다. 실행자에는 `prompt="/url <ClickUp task>"` 또는 `prompt="jd builder <ClickUp task>"`, `send_allowed=False` 요청만 넘기고, 자동 send 작업은 만들지 않는다.
6. PI-3 한 턴 루틴: `run_position_intake_routine_once(...)`는 owner/blocked 신호를 먼저 확인하고, 통과할 때만 Gmail MCP 어댑터 → 등록 게이트 → 후속 큐 drain 순서로 돈다. owner activity 때는 Gmail/후속 executor 호출이 0회다.
7. 스케줄러용 로컬 CLI: `python -m tools.multi_position_sourcing.position_intake_runner --executor fake ...`는 JSON 이메일 입력으로 한 턴을 실행하고 결과 JSON에 executor 종류, 고정 Gmail 쿼리, followup prompts를 남긴다. `--executor live`는 L3 어댑터 주입 전에는 exit 2로 차단한다.
8. ClickUp REST 어댑터는 기존 `ClickUpCreateTask`/`ClickUpCreateComment`/`ClickUpSearch` 계약에 주입 가능해야 한다. 토큰은 환경변수에서만 읽고, Authorization 헤더에 raw token을 싣되 로그/예외/산출물에 노출하지 않는다. 테스트는 가짜 requester로 endpoint/body/header를 단언하고 실제 네트워크 write는 하지 않는다.

## 입력/출력 계약

- 입력: `subject: str`, `body: str` 또는 `IntakeEmail(message_id, subject, body, from_email, received_at)`.
- 등록 메시지 출력: `""` 또는 `"포지션 등록 <url>"` 또는 `"포지션 등록\n<JD본문>"`.
- 후속 큐 항목: `position_key`, `task`, `status`, `task_id`, `task_url`, `clickup_list_id`, `created_at`, `updated_at`, `dry_run`.
- 후속 작업 task 값: `url_presetting | jd_set_build`만 허용한다.
- 승인 상태 전이: `ignored` → `approval_required`(dry-run only) → `registered`(approved/auto) → `queued` → `done|blocked`.
- 인입 상태 파일: `version`, `processed_message_ids`, `pending_approval_message_ids`. 기본 경로는 `~/.vh-search-results/position_intake/state.json`이나, 러너는 `state_path`를 명시한 경우에만 상태를 쓴다.
- 후속 실행 요청: 기존 큐 필드 + `prompt`, `skill`, `send_allowed=False`, `clickup_task_id`, `clickup_task_url`.
- 루틴 출력: `status`, `gmail_query`, `email_count`, `intake`, `drain`, `followup_prompts`.
- CLI 입력: `--executor fake|live`, `--emails-json`, `--queue-path`, `--state-path`, `--approved-message-id`, `--auto-registration-allowed`, `--skip-owner-check`, `--output`.
- ClickUp 어댑터 입력: `token: str`, `list_id: str`, `title: str`, `body: str`, `task_id: str`.
- ClickUp 어댑터 출력: `create_task(title, body, list_id) -> (task_id, task_url)`, `create_comment(task_id, body) -> comment_id`, `search_existing_positions(recognition, list_id) -> tuple[ExistingPositionTask, ...]`.

## 비범위

- Gmail OAuth 데몬 신규 구현.
- 실제 Gmail 읽기, 실제 ClickUp 쓰기, 실제 `/url`/`jd builder` 실행.
- 실제 ClickUp API 호출 실행. 이 조각은 어댑터 계약과 dry-run/가짜 requester 검증까지만 한다.
- Discord/메일/LinkedIn/포털 발송 자동 클릭.
- 기존 등록 파서 확장 또는 임의 포털 URL 등록 파서 확장(PC-A4 범위).

## 검증 명령

- `make red-ledger`
- focused: `.venv/bin/python -m pytest tests/test_position_intake_pipeline.py -q` (fallback: `python3 -m pytest ...`)
- focused adapter: `python -m pytest tests/test_clickup_adapter.py -q`
- CLI smoke: `python -m tools.multi_position_sourcing.position_intake_runner --executor fake --emails-json <json> --queue-path <path> --state-path <path> --approved-message-id <id> --output <json> --skip-owner-check`
- full: `./verify.sh`

## SOT 체크리스트

- `CLAUDE.md` SOT: 발송 자동 금지, 사장님 크롬 점유 시 양보, 두 번 깨기.
- `docs/harness.md`: RED → GREEN, worktree, verify.
- `docs/sot/25-ai-search-execution-process.json`: INV2/INV3/INV4 준수.
- `docs/sot/26-portal-login-spec.json`: 캡차/멀티세션 자동 우회 금지.
- `docs/sot/27-humansearch-browsing-preflight.json`: fail-closed, 반복 retry 금지.
