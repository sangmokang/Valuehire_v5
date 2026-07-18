# Goal — 원자적 enqueue-or-get (디스코드 직결 조각 B)

- 근거: docs/prompts/discord-direct-connect-goal-2026-07-17.md §5 B, §6-2(같은 이벤트 2회→잡 1개·응답 1회), INV-D5(raw 예외 미노출).
- 모드: code-change / 위험등급: L2 (큐 데이터정합 — 외부발송·파괴 없음, 1파일)

## 현재 상태 (수정 전)
- DB: `supabase/migrations/20260713_fleet_job_idempotency.sql` — `params->>'idempotency_key'` 부분 유니크 인덱스 존재.
- 클라이언트: `JobQueueClient.enqueue`(job_queue.py)는 POST /jobs 만 하고, 중복 삽입 시 PostgREST 409(23505)를 그대로 던짐 → (a) 기존 잡 회수 없음(같은 디스코드 이벤트 2회 → 잡 2개 시도·1개는 에러), (b) raw DB 메시지(키 값·내부 상세)가 상위로 노출(INV-D5 위반).

## 계약
- `JobQueueConflictError(RuntimeError)`: HTTP 오류를 raw 본문 없이 감싼 예외(코드만).
- `enqueue`: POST 가 409 + payload 에 idempotency_key 존재 → `job_by_idempotency_key` 로 기존 잡 회수해 반환. 회수 실패/키 없음/기타 HTTP 오류 → `JobQueueConflictError`(원문·체인 버림, `from None`).
- `job_by_idempotency_key(key) -> dict|None`: 키 URL 인코딩 후 `/jobs?params->>idempotency_key=eq.<key>&limit=1` 조회.

## 인수 기준
- [x] 기계: test_idempotent_enqueue.py 6개 GREEN + test_job_queue 무손상, ./verify.sh exit 0(실측 verdict).
- [x] 뮤턴트: 409 회수 무력화→1 failed, redact 제거→3 failed. 감지 후 원복(커밋 후).
- [x] 배선: enqueue = fleet_dispatch:159·discord_command_listener:200·fleet_worker:948/994 실호출부, idempotency_key = hermes_fleet_bridge 가 채움(고아 0).
- [ ] 4b: V1(Codex) 독립 반증.

## 비범위
- 라이브 실 DB 왕복(진짜 409 재현) — 조각 J(전용 테스트 큐).
- 다른 유니크 제약(idempotency 외) 충돌의 세분류 — 현재 idempotency 인덱스가 유일한 관련 유니크.
- 409 회수와 POST 사이의 TOCTOU 는 DB 유니크가 원자성 보장(회수는 이미 커밋된 행을 읽음).

## 적대 검증 로그
- G 자기반증: 409-but-no-existing(다른 유니크 위반) → redact 예외 경로 테스트. 500 등 비-409 도 redact 확인.
- V1(Codex): verdict.json.
