# Fresh-shell handoff — APP 01 마감 후 APP 02 기기 이름 단일화

이 문서는 오염된 이전 작업폴더를 이어 쓰지 않고 새 Codex/Claude 셸에서 재개하기 위한
실행 프롬프트다.

## 0. 현재 상태

- 안전한 작업폴더:
  `C:\Users\DELL\Desktop\Valuehire_v5-login-machine-browser-app01-clean`
- 브랜치: `task/login-machine-browser-app01-clean`
- 현재 HEAD: `dd8fbf094af47cb5f285b43831f95fbec5e353a6`
- APP 01 Codex 적대 검토: PASS
- APP 01 Claude 새 문맥 검토: 주간 한도 때문에 미완료
- 오염되어 배송 금지인 과거 작업폴더:
  `C:\Users\DELL\Desktop\Valuehire_v5-login-machine-browser-app01`
- APP 02 전 APP 01 문서 마감 변경은 아직 커밋 전일 수 있으므로 먼저 `git status`와
  `git log -5 --oneline`을 확인한다.

## 1. 새 셸의 첫 작업 — APP 01 독립 Claude 마감

1. 레포의 `AGENTS.md`, `docs/harness.md`, `$st`, `harness`, `login` 지침을 먼저 읽는다.
2. 위 안전한 작업폴더에서 `git status --short`가 기대한 문서 변경 외 깨끗한지 확인한다.
3. Claude 새 문맥에 APP 01 브리핑, 최종 diff, 정책 검사, verdict만 제공하고 다음을 적대
   검토시킨다.
   - APP 01이 정책·정적 연결만 바꿨는가.
   - LinkedIn 자동 로그아웃·아이디/비밀번호 제출·새 탭·고정 포트/프로필 추측이 활성
     진입점에 남았는가.
   - `HUMAN_AUTH`, `HANDOFF`, `AUTH_CONFLICT`가 섞였는가.
   - 비밀 원문·파생값이 인자/stdout/stderr/로그/영수증/산출물/모델 메시지에 들어갈 수
     있는가.
   - 정책과 APP 17이 증명한 exact endpoint/profile/target만 쓰는가.
4. Claude가 FAIL이면 반례를 잡는 실패 검사를 먼저 커밋한 뒤 최소 수정한다. 관련 검사
   125개와 별도 프롬프트 검사 5개, Codex 새 문맥 검토를 다시 통과시킨다.
5. Claude가 PASS이면:
   - 구현 목표 문서 APP 01 상태를 `완료`로 바꾼다.
   - verdict의 `three_way_agree=true`, `status=complete`와 Claude 근거를 기록한다.
   - APP 01 문서 마감만 별도 커밋한다.
6. Claude PASS 전에는 APP 02 코드를 시작하지 않는다.

## 2. APP 02 전용 새 브랜치

APP 01 마감 커밋을 기준으로 APP 02 전용 새 worktree와
`task/login-machine-browser-app02` 브랜치를 만든다. APP 01 브랜치나 오염된 과거
작업폴더에서 APP 02를 직접 구현하지 않는다.

## 3. APP 02 구현 프롬프트

역할: 함대 식별자 계약 담당자. 모든 생산 경로가 동일한 세 기기 이름만 사용하도록 한다.

목표:

- 정식 기기 ID를 `macmini`, `macbook`, `winpc`로 고정한다.
- `macbook_pro` 같은 과거 별칭은 입력 경계에서만 정규화한다.
- 저장·영수증·잠금 키에는 정식 ID만 남긴다.

먼저 읽을 파일:

- `tools/multi_position_sourcing/job_queue.py`
- `tools/multi_position_sourcing/fleet_args.py`
- `tools/multi_position_sourcing/fleet_dispatch.py`
- `supabase/migrations/`
- `docs/engineering/login-machine-browser-decomposition-briefing-2026-07-26.html`의 APP 02
- `docs/engineering/login-machine-browser-implementation-goal-2026-07-26.md`

입력:

- 명령의 `machine` 값
- heartbeat·브라우저 보고서·작업 행의 `machine` 값

산출물:

- 정식 `MachineId` 타입과 `normalize_machine_id` 함수
- 데이터베이스 제약과 이전 값 호환 규칙

실패 검사를 먼저 작성하고 별도 커밋한다.

- `macbook_pro`와 `macbook`이 서로 다른 잠금 키를 만들면 실패한다.
- 모르는 기기명이 기본 기기로 바뀌면 실패한다.
- 저장 계층에 별칭이 남으면 실패한다.
- Discord 파서부터 worker 환경변수와 데이터베이스 행까지 동일 ID가 아니면 실패한다.

최소 구현:

- 한 모듈에 정식 ID·별칭·검증을 집중한다.
- 파서·작업 큐·heartbeat·receipt가 공용 함수를 사용하게 한다.
- 잘못된 값은 임의 추측 없이 거부한다.
- 기존 사용자 변경과 APP 01 정책을 보존한다.

검증:

- `python -m pytest -q tests/test_fleet_args.py tests/test_fleet_dispatch.py`
- `python -m pytest -q tests/test_machine_identity.py`
- Discord 입력→worker 환경변수→데이터베이스 행의 동일 ID를 spy/integration 검사로
  증명한다.
- 저장 계층에 별칭이 0개임을 검사한다.
- 구현 후 Codex와 Claude가 번갈아 새 문맥에서 적대 검토한다. 반례가 나오면 실패 검사를
  먼저 추가하고 다시 고친다.

완료 증거:

- 세 정식 ID와 허용 별칭 표
- 저장 계층의 별칭 0개 검사 결과
- 실패 검사 커밋, 최소 구현 커밋, 관련·전체 검사 수치
- 자기 반증과 Codex·Claude 검토 근거
- `docs/engineering/login-machine-browser-implementation-goal-2026-07-26.md`의 APP 02 상태
- APP 03용 fresh-shell handoff

금지:

- 기기 자동 선택 로직
- heartbeat 구현
- 기존 작업 데이터의 무근거 일괄 수정
- 브라우저 실행·종료·탭 조작
- 실제 비밀 읽기·출력
- 테스트 약화·삭제
- APP 03 구현
- push·PR·merge

## 4. 알려진 격리 항목

- APP 01 범위 밖 런타임 선행 장벽, Hook, SQL/event/store, 비밀 제공자·적용기,
  기기 조사 결함은 각각 APP 09~17, 24~36의 소유 범위다.
- `test_fleet_worker.py`와 `test_login_harness_hook.py` 전체 묶음의 기존 22개 실패는
  Windows CLI 경로와 브라우저 증거 fixture 문제다. APP 02 기기 ID 계약이 직접 원인인
  실패가 아니면 섞어 고치지 말고 별도로 기록한다.
