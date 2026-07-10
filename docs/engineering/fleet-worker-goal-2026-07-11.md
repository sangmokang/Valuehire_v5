# 함대 워커(단계 B) — goal (2026-07-11)

모드: code-change · 위험등급 L3(claude -p 실행·크롬 규칙 접점) · worktree: fleet-worker

## 현재 상태
- 단계 A(PR #83 merged): jobs/account_locks + claim/release/resume/cancel RPC + JobQueueClient.
- Discord 보고 패턴 정본: `scripts/dm_report.py`(봇 토큰 로드·429 백오프).
- 워커가 없어 큐의 잡을 실행할 주체가 없음.

## 계약(스펙)
- 입력: 환경변수 VALUEHIRE_MACHINE ∈ (macmini|macbook|winpc) — 없으면 기동 거부.
- 잡 실행: build_job_prompt(job) → `claude -p`(레포 루트, 40분 timeout).
  프롬프트 필수 요소 = 스킬 발동 문구(.claude/skills, /mnt 금지) + 타 스킬 금지 + 발송 금지(SOT28)
  + 크롬 프로필 보존 + PAUSED_FOR_HUMAN 프로토콜 + 한국어 보고.
- 출력 판정: PAUSED_FOR_HUMAN 마커 > exit code > 빈 출력 불신.
  paused → release(paused_for_human, error=사유) + Discord 개입 안내.
- dry-run: claude 절대 미실행, 큐 왕복만.

## 인수 기준 (기계 검사)
1. tests/test_fleet_worker.py 13개(머신 fail-closed·프롬프트 계약·파싱·루프 1턴·배선 실체).
2. 발송성 스킬 잡은 claude 실행 없이 failed 처리(게이트 테스트).
3. 라이브: 실제 큐에서 dry-run 1턴(enqueue→claim→done→Discord 보고).
4. ./verify.sh exit 0.

## 적대검증 정조준
- 프롬프트 인젝션(position_url/params 에 지시문 삽입 시 규칙 무력화?), PAUSED 마커 위조,
  notifier 실패가 잡 상태를 오염시키는지, timeout 후 잡 상태, loop 의 예외 처리.

## 비범위
- 잡별 Discord 스레드 생성(discord_thread_id)은 단계 C 에서 명령 층과 함께.
- launchd plist 설치·실서치 잡 라이브 실행은 아침 사장님 항목.

## 적대 검증 로그
- (verdict.json 참조)
