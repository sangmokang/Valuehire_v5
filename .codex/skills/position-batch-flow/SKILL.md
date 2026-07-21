---
name: position-batch-flow
description: 사장님이 "포지션 배치 돌려" / "active 포지션 일괄 등록" / "position batch" / "오늘자 포지션 처리" / "이번주 포지션 5채널 등록" 키워드 명시 시 활성. ClickUp active 포지션 → 사람인+잡코리아+RPS InMail+이메일+AI Search+/kanban 까지 단일 명령(`pnpm position-batch:run`)으로 처리. Supabase position_batch_* 증분 처리로 N번째 실행 안전 — 새 포지션만 자동 작업. 사장님 chrome 점유 가드 + Rate limit 회피(25×3회) + Send 자동 금지.
---

# Position Batch Flow

## 트리거 키워드

- "포지션 배치 돌려"
- "active 포지션 일괄 등록"
- "position batch"
- "오늘자 포지션 처리"
- "이번주 포지션 5채널 등록"
- "지금 active 포지션 다 돌려"

## 흐름 — 한 줄 명령

```bash
pnpm position-batch:run --triggered-by skill
```

또는 옵션:
```bash
pnpm position-batch:run --dry-run                       # 외부 호출 0, plan 만
pnpm position-batch:run --positions task1,task2          # 특정 포지션만
pnpm position-batch:run --step saramin,jobkorea          # 특정 단계만
pnpm position-batch:run --resume 2026-05-25-1430         # resume
pnpm position-batch:run --force-step rps-save            # 30일 skip 무시
```

## 자동 처리 8단계

```
[0] active CSV 추출 (ClickUp FY26ClientsPosition)
[1] 사람인 등록 (병렬)
[2] 잡코리아 등록 (병렬)
[3] ChatGPT batch — RPS InMail 본문 1,900자 4단 생성 (멀티탭 10)
[4] LinkedIn RPS Save — 25건×3회차 분할 (회차간 5분 휴식)
    제목 = "회사명, 포지션명"
    저장 = "Save as new" + "Anyone in my organization" 라디오 명시
[5] 이메일 → all@valueconnect.kr (포지션당 1통, subject "[포지션]회사명, 포지션명")
[6] ChatGPT AI Search — 멀티탭
[7] /kanban AI Search 컬럼 push
```

## 사전 점검 (BLOCKING)

1. **사장님 chrome 점유 해제** — linkedin/saramin/jobkorea/chatgpt/clickup 도메인이 active 면 STOP
2. **로그인 세션 살아있음** — RPS / 사람인 / 잡코리아 / ChatGPT 멀티탭
3. **Supabase 마이그 적용** — `position_batch_runs/steps` 테이블 존재
4. **환경변수** — `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `RESEND_API_KEY`, `POSITION_BATCH_DISCORD_WEBHOOK`

## 실행 후 확인

- Discord webhook 알림 (시작/단계/완료/실패)
- summary 메일 (dev@valueconnect.kr) — 채널별 success/fail 통계 + resume 명령어
- `/kanban` AI Search 컬럼 후보자 누적 확인
- LinkedIn Templates 페이지 → 신규 템플릿 N건 noted

## 안전 가드 (절대 위반 금지)

- **R0**: Send 버튼 자동 click 절대 금지 — 사장님 수동 발송 게이트
- **R4**: 사람 개입 시 자동화 즉시 정지 (chrome-guard 매 단계 체크)
- **R12**: RPS Save modal "Anyone in my organization" 라디오 명시 클릭 + selected 검증
- **R15**: 25건×3회차 분할 + 회차간 5분 휴식 (LinkedIn 봇 감지 회피)

## 관련 자료

- spec: `docs/superpowers/specs/2026-05-25-position-batch-orchestrator-design.md`
- plan: `docs/superpowers/plans/2026-05-25-position-batch-orchestrator.md`
- 메모리: [[project-linkedin-rps-save-workflow-2026-05-25]]
- 통합: [[linkedin-rps-jd-set-builder]] §16 (RPS Save R-규칙)

## 정기 실행

매주 월요일 03:00 KST launchd cron 자동 실행 (사장님 chrome 점유 시 +6시간 자동 연기).
