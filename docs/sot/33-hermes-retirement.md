# SOT 33 — Discord direct gateway 전환과 Hermes 완전 폐기

> 상태: 실행 계약. 2026-07-22 사업 오너 지시 `AC-HR`.
> 상위 목표: `docs/prompts/discord-single-bot-console-goal-2026-07-22.md`.
> 실행 프롬프트: `docs/prompts/discord-single-bot-console-exec-prompts-2026-07-22.md`.
> 운영 계약: SOT 29(함대·큐) + SOT 31(신뢰성) + SOT 32(자연어 해석) + 이 문서.
> 모든 단계는 별도 Harness 작업방에서 RED→GREEN→전체 verify→독립 재검증한다.

## 1. 목표 경로

```text
Discord 입력
→ 단일 direct gateway
→ 자연어/슬래시 해석
→ 영속 큐
→ fleet worker
→ Claude Code 또는 Codex
→ 원 요청자에게 결과 회신
```

이 경로가 라이브로 검증된 뒤에만 Hermes의 Discord 수신, LLM 판단 계층, 플러그인,
launchd, 레거시 브리지, 비밀 사본과 운영 코드를 제거한다. `Discord → direct gateway →
queue → worker`가 현재 운영 경로이며, gateway 프로세스는 Claude/Codex를 직접 실행하지 않는다.

## 2. 절대 규칙

1. **새 직결 봇 실증 전에 Hermes를 중단하거나 삭제하지 않는다.**
2. Hermes와 직결 봇이 같은 Discord 이벤트를 동시에 받게 하지 않는다.
3. 봇 토큰당 활성 gateway는 정확히 1개다.
4. Hermes 제거 전에 `queued/running/paused_for_human` 작업이 0개여야 한다.
5. Claude 실작업 1건과 Codex 실작업 1건이 각각 `done`과 Discord 회신까지 완료되지
   않으면 폐기 단계로 진입하지 않는다.
6. Hook만 믿지 않는다. 생산 코드의 기동 게이트와 Hook을 이중으로 둔다. Hook 로드 실패는
   생산 코드의 fail-closed 기동 게이트가 다시 막는다.
7. ~/.hermes 같은 넓은 경로를 rm -rf로 삭제하지 않는다. 먼저 명시적 격리 경로로
   이동해 복구 가능하게 보존한다.
8. v4 `tools/hermes-agent` 아래에는 이름만 Hermes이고 다른 cron이 쓰는 스크립트가 있을 수
   있다. 호출자 0을 증명하거나 중립 경로로 먼저 이사하기 전에는 폴더 전체를 삭제하지 않는다.
9. 비밀값은 출력·로그·영수증·Git에 남기지 않는다. 토큰은 SHA-256 지문만 기록한다.
10. 한 작업방에는 인수 기준 하나만 둔다. HR-0~HR-7을 합쳐 구현하거나 다음 단계 증거를
    앞 단계의 추정값으로 채우지 않는다.

## 3. 단계와 단방향 게이트

단계 전환 정본은 `artifacts/discord-cutover/hermes-retirement-receipt.json`의 `phase`와
라이브 검사 결과다. 환경변수만으로 단계 통과를 주장하지 않는다. 검사기는 현재 단계 파일,
프로세스, launchd, 큐, gateway lease와 Discord 회신을 다시 읽는다.

### HR-0. 의존성 전수조사

실행 중인 Hermes PID, launchd label, plist, 플러그인 심링크, config, 세션, cron,
Discord 명령, 레포 import와 호출자를 전수 수집한다. 결과는
`artifacts/discord-cutover/hermes-dependency-inventory.json`에 machine-readable JSON으로 남긴다.

최소 조사 대상:

- `/Volumes/SSD/valuehire_v4/tools/hermes-agent/`
- `/Volumes/SSD/valuehire_v5/ops/hermes-plugin/`
- `hermes_fleet_bridge.py`
- `hermes_position_context.py`
- `scripts/discord_command_listener.py`
- `~/.hermes/plugins/`
- `~/Library/LaunchAgents/ai.hermes.gateway.plist`

모든 발견 항목은 `live caller` / `historical-only` / `removable` 중 정확히 하나로 분류한다.
호출자가 남은 항목은 삭제 대상이 아니라 `move_first`로도 표시한다. 완료 조건은 관련 파일
전체의 `UNKNOWN이 0`이고, 분류 근거와 호출자 목록이 JSON에 있는 것이다.

### HR-1. 직결 경로 라이브 인수

직결 gateway는 공유 lease를 획득해야만 기동한다. 최소권한 Supabase RPC가 실제 운영 DB에서
응답하고 대상 worker heartbeat가 유효해야 한다. 같은 Discord `event_id`를 두 번 전달해도
`job_id`는 하나만 생성돼야 한다.

다음 라이브 작업을 각각 1건 수행한다.

1. `engine=claude`
2. `engine=codex`
3. 자연어 입력 1건(동일 direct gateway 경로)

두 엔진 잡은 각각 `queued → running → done`으로 전이하고 원 요청자에게 정확히 1회 회신한다.
Hermes 응답과 직결 봇 응답이 동시에 오는 경우 즉시 FAIL한다. 봇 토큰당 활성 gateway 1개를
지키기 위해 HR-1 실증은 격리된 테스트 bot identity 또는 통제된 단독 연결 구간에서 수행하며,
같은 운영 토큰의 Hermes와 direct gateway를 동시에 연결하지 않는다. 실증 후 direct gateway는
HR-2 동안 다시 정지하고 기존 Hermes 수신을 유지한다.

완료 영수증에는 `event_id`, `job_id`, `agent`, 상태 전이, `Discord response_id`,
`gateway lease_id`가 있어야 하며 Claude/Codex 두 건이 `done`이어야 한다.

### HR-2. 신규 Hermes 접수 동결

새 direct gateway는 아직 시작하지 않은 상태에서 Hermes의 신규 작업 접수만 동결한다.
기존 `queued/running/paused_for_human` 작업을 완료하거나 owner 취소로 0건까지 정리한다.
Hermes가 새 큐 행을 만들지 못하는 것을 기계적으로 검사한다. Hermes 프로세스와 로그인
브라우저는 이 단계에서 아직 종료하지 않는다.

완료 조건은 관찰 구간 전후 `jobs` 행 증가가 0이고 `queue_nonterminal_count=0`인 것이다.

### HR-3. 원자적 수신기 전환

다음 순서를 바꾸지 않는다.

1. 현재 Discord 명령 payload를 백업한다.
2. direct gateway 설정과 lease readiness를 검사하되 아직 연결하지 않는다.
3. Hermes gateway를 launchctl bootout 한다.
4. Hermes PID와 Discord 연결이 0인지 확인한다.
5. direct gateway를 기동하고 공유 lease 획득을 확인한다.
6. 직결 봇이 실제 처리할 명령만 Discord에 등록한다.
7. 승인된 테스트 명령 1건을 왕복한다.

중간 실패 시 자동 rollback:

1. direct gateway를 중단한다.
2. Discord 명령 payload를 백업본으로 복구한다.
3. Hermes plist와 플러그인을 원위치한다.
4. Hermes gateway를 다시 올린다.
5. rollback 결과와 실패 원인을 영수증에 기록한다.

완료 조건은 direct gateway 1개, Hermes gateway 0개, 같은 명령 응답 1개다.

### HR-4. 격리 운영

- `ai.hermes.gateway.plist`는 삭제하지 않고 명시적 `quarantine` 폴더로 이동한다.
- `~/.hermes/plugins/valuehire*`를 quarantine으로 이동한다.
- `~/.hermes` 전체는 권한 0700인 로컬 격리 경로로 이동한다.
- 비밀 파일은 archive 내용 목록이나 로그에 출력하지 않는다.
- 격리 후 재부팅 또는 launchd 재평가에서도 Hermes가 다시 뜨지 않는지 확인한다.
- direct gateway는 기본 24시간 동안 단독 운영한다.

이 기간에 중복 응답, 큐 고착, 회신 유실, worker heartbeat 단절이 발생하면 코드 삭제로 가지
않고 HR-3 rollback 여부를 판정한다. 완료 조건은 24시간 동안 Hermes PID 0, 중복 응답 0,
direct gateway lease 위반 0이다.

### HR-5. 저장소 코드 제거

v5 제거 후보:

- `ops/hermes-plugin/valuehire_fleet/`
- `hermes_fleet_bridge.py`
- `hermes_position_context.py`
- Hermes 전용 테스트와 설치기
- `scripts/discord_command_listener.py`의 실행 진입점

v4 제거 후보:

- `tools/hermes-agent/valuehire/`의 Hermes 전용 Claude/Codex 어댑터
- `vh_code`, `vh_skill_run`, Hermes Kanban dispatcher
- Hermes gateway 설치·재시작 코드

`direct_receiver`가 쓰는 파싱은 `fleet_args` 같은 중립 모듈로 이사를 완료했는지 먼저 검사한다.
`outstanding-news` 등 `tools/hermes-agent` 아래 unrelated launchd/cron 호출자는 중립 디렉터리로
먼저 이사한다. 역사 문서는 삭제하지 않고 `RETIRED`로 표시한다. 현재 운영 문서와 SKILL.md에서
Hermes를 권장하는 문구는 제거한다.

완료 조건은 생산 코드 import/call graph에서 Hermes runtime 참조가 0이고, 남은 문자열은 역사
문서 또는 retirement 검사 allowlist에만 있는 것이다. `Hermes 생산 코드 호출자 0`을 기계적으로
증명하지 못한 디렉터리는 삭제하지 않는다.

### HR-6. 비밀과 유령 재접속 봉쇄

direct gateway가 안정된 뒤 owner 승인 하에 Discord bot token을 회전한다. 새 토큰은 direct
gateway의 비밀 저장소 한 곳에만 기록한다. 격리된 Hermes의 옛 토큰으로 Discord 연결이 실패하는
것을 확인한다. 토큰 원문은 어떤 영수증에도 기록하지 않고 SHA-256 지문만 기록한다. Supabase
service-role 키를 직결 gateway에 제공하지 않는다.

완료 조건은 새 토큰으로 direct gateway 1개만 연결되고 옛 토큰을 가진 Hermes 재접속이
실패하는 것이다.

### HR-7. 최종 폐기와 문서 정리

격리본 보존기간이 끝나고 owner가 최종 승인하면 휴지통 등 복구 가능한 방식으로 제거한다.
launchd plist, 플러그인 심링크, `~/.hermes` 원위치가 모두 없어야 한다.

- `docs/search-access.md`의 운영 봇 표준을 direct gateway로 변경한다.
- SOT 29·31·33의 현재 경로를 `Discord → direct gateway → queue → worker`로 통일한다.
- 과거 Hermes 문서에는 `폐기됨`과 최종 폐기일을 표시한다.

## 4. 이중 안전 게이트

### 4.1 생산 코드 기동 게이트

direct gateway의 실제 startup 경로가 lease, 최소권한 RPC, worker heartbeat, `event_id`, 단계
상태를 다시 검사한다. 하나라도 없으면 Discord에 연결하기 전에 종료한다. gateway 프로세스가
Claude/Codex를 직접 실행하거나 `skill=agent`를 owner 서명 없이 적재하는 경로는 생산 코드가
거부한다.

### 4.2 필수 PreToolUse Hook

1. `.claude/hooks/guards/discord-e2e-cutover.py`
   - lease/RPC/worker readiness 없이 direct gateway 기동 차단
   - `event_id` 없는 Discord enqueue 차단
   - gateway 프로세스 내부 Claude/Codex 직접 실행 차단
   - owner 서명 없는 `skill=agent` 차단
2. `.claude/hooks/guards/hermes-retirement.py`
   - HR-1 영수증 없이 Hermes bootout·격리·삭제 차단
   - 격리 완료 후 Hermes start/restart/install 차단
   - Hermes import·플러그인·새 어댑터 재도입 차단
   - 호출자가 남은 디렉터리 삭제 차단

### 4.3 Stop Hook 확장

다음 증거 없이는 `Hermes 완전 폐기 완료` 보고를 차단한다.

- Hermes PID 0
- launchctl label 0
- 플러그인 심링크 0
- 미종료 Discord 잡 0
- direct gateway lease 1
- Claude/Codex 라이브 성공 영수증
- 원 요청자 Discord response_id
- 전체 verify exit 0
- reboot 후 유령 재기동 0
- rollback 검증 결과

Hook 활성 상태는 환경변수만으로 주장하지 않는다. 검사기가 현재 단계 파일과 라이브 상태를
다시 읽어 판정한다.

## 5. 기계 영수증 계약

정본 경로: `artifacts/discord-cutover/hermes-retirement-receipt.json`

필수 필드:

- `schema_version`
- `git_sha_v4` / `git_sha_v5`
- `phase`
- `discord_bot_id`
- `command_fingerprint`
- `direct_gateway_pid`
- `direct_gateway_lease_id`
- `hermes_pid_count`
- `hermes_launchctl_count`
- `queue_nonterminal_count`
- `claude_job_id` / `claude_response_id`
- `codex_job_id` / `codex_response_id`
- `duplicate_response_count`
- `quarantine_paths`
- `remaining_runtime_references`
- `rollback_tested`
- `verified_at`
- `verifier_sha256`

영수증은 secret-free다. 토큰 원문·쿠키·비밀번호·service-role 값·비밀 파일 내용이나 목록을
포함하지 않는다. `verifier_sha256`은 검사기 코드의 SHA-256이며, 토큰 지문과 혼동하지 않는다.

## 6. 최종 완료 정의

Hermes를 단순히 껐다는 뜻이 아니다. 다음 조건이 전부 참이어야만
`Hermes 완전 폐기 완료`라고 보고한다.

- Discord 실수신자는 direct gateway 1개
- Hermes 프로세스·launchd·플러그인·비밀 사본 0
- Hermes 생산 코드 호출자 0
- Claude와 Codex 실제 실행·결과 회신 성공
- 중복 응답 0
- 재부팅 후 Hermes 재기동 0
- 전체 테스트 통과
- 기계 영수증 존재

하나라도 증명하지 못하면 현재 `phase`와 누락 증거를 보고하며, 완료 문구를 쓰지 않는다.
