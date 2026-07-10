# 함대 작업 큐(단계 A) — goal (2026-07-11)

모드: code-change · 위험등급 L3(공유 스키마 + 라이브 DB DDL) · worktree: task/fleet-jobs-schema

## 현재 상태 (확인된 사실)
- Discord 명령 파싱·권한은 `tools/multi_position_sourcing/discord_routing.py:14` 에 이미 있음(run-search 등 5종).
- Supabase 적재 패턴 정본: `supabase/migrations/20260708_organization_analysis.sql`(RLS+service_role) + `scripts/humansearch_supabase_backfill.py:48`(REST 헤더).
- 3대 머신(맥미니·맥북·윈도우) 잡 분배 큐가 없음 — 리서치 문서(사장님 2026-07-11)와 순차 플랜(docs/prompts/fleet-control-sequential-prompts-2026-07-11.md)이 요구.

## 핵심 질문
Discord 명령 → 머신별 워커로 잡을 유실 없이, 계정 충돌(세션 밀어내기) 없이 전달하는 최소 스키마는?

## 계약(스펙) — 입출력 JSON
- jobs 행: {machine∈(macmini|macbook|winpc), skill∈(humansearch|aisearch|url), position_url(http/https),
  params(dict), requested_by(비공백), role∈(owner|member), status(전이 화이트리스트), account_key(기본 portal:{machine})}
- RPC: claim_next_job(p_machine)→jobs행|빈, release_job(p_job_id,p_status∈done|failed|cancelled|paused_for_human,…),
  resume_job(p_job_id: paused_for_human→queued)

## 인수 기준 (기계 검사)
1. 무효 입력 fail-closed — tests/test_job_queue.py 45개.
2. 같은 account_key 는 동시에 한 머신만 클레임(라이브 DB에서 두 번째 클레임 None 증명).
3. 라이브 왕복: enqueue→claim→release→재클레임 (jobs id 1·2).
4. ./verify.sh exit 0.
5. 발송성 스킬이 큐에 못 들어감(FLEET_SKILLS 고정 테스트, SOT28).

## 적대검증 정조준
- plpgsql claim 루프의 동시성(unique_violation 후 계속), release_job 의 락 잔존 경로, _env 상위 순회 오집, 테스트의 구현 베끼기 여부.

## 비범위
- 워커(단계 B), Discord 연결(단계 C), heartbeat(단계 G). 실제 서치 잡 라이브 실행은 아침 사장님 항목.

## 적대 검증 로그
- (작성 중 — verdict.json 참조)
