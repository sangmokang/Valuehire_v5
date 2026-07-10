# 함대 Discord 명령 층(단계 C) — goal (2026-07-11)

모드: code-change · 위험등급 L3(권한·발송 게이트 접점) · worktree: fleet-discord

## 현재 상태
- 단계 A(#83): 작업 큐 + JobQueueClient(enqueue/resume/cancel/recent).
- 단계 B(#84): fleet_worker 가 큐를 소비.
- Discord 인가·라우팅 정본: `discord_routing.py`(route_discord_invocation, allowlist),
  기존 디스패치 패턴: `register_position_dispatch.py`.
- 큐에 잡을 넣을 Discord 진입점이 없음.

## 계약(스펙)
- 명령: fleet-run(skill,url,machine?), fleet-status, fleet-resume(job), fleet-cancel(job).
- 권한: fleet-run/status = 인가된 멤버·owner. resume/cancel = owner 전용.
- fleet-run → new_job_payload → queue.enqueue. resume→queue.resume, cancel→queue.cancel, status→queue.recent.
- 반환: {action: enqueued|resumed|cancelled|status|denied|denied_owner_only|error, ...}
- 발송 게이트(SOT28): 디스패처는 발송 함수를 절대 부르지 않는다. 큐엔 검색 스킬만.

## 인수 기준(기계 검사)
1. tests/test_fleet_dispatch.py 16개(명령 등록·페이로드 fail-closed·owner 게이트·발송 정적 게이트).
2. 기존 run-search(source/keyword) 의미 불변(SUPPORTED 에 잔존, payload set 테스트 갱신만).
3. 라이브: owner fleet-run→큐 insert→status→cancel, 미인가 denied.
4. ./verify.sh exit 0.

## 적대검증 정조준
- 멤버가 resume/cancel 우회 가능한가(owner 판정 허점), fleet-run 으로 발송성 스킬/타머신 주입,
  route_discord_invocation 인가 약화 여부, job 옵션 파싱(음수·비정수·오버플로).

## 비범위
- 실제 Discord 인터랙션 수신 서버(게이트웨이 연결)는 register_discord_commands 등록까지만.
  상시 리스너 확장은 아침/후속. 실서치 잡 라이브 실행도 아침 사장님 항목.

## 적대 검증 로그
- (verdict.json 참조)
