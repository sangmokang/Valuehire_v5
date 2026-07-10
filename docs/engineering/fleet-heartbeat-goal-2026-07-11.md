# 함대 heartbeat + watchdog(단계 G) — goal (2026-07-11)

모드: code-change · 위험등급 L3(경보 발송·상주 데몬) · worktree: fleet-heartbeat

## 현재 상태
- 단계 A~C(#83~85): 큐·워커·Discord 명령 병합.
- PR#66 이 크래시는 잡지만 "죽었는데 아무도 모름"은 못 막음.
- OPS_HEALTH webhook 존재(.env.local DISCORD_WEBHOOK_URL_OPS_HEALTH).

## 계약(스펙)
- heartbeat_payload(machine, worker_pid, now_iso) → {machine, beat_at, worker_pid}. 무효 머신 ValueError.
- stale_machines(rows[{machine,beat_at_epoch}], now_epoch, expected) → 5분 초과 또는 누락 머신.
- should_alert(machine, last_alert_epoch, now_epoch) → 30분 억제.
- Watchdog.run_once(now_epoch) → stale 경보(억제 반영), notify 실패 fail-soft. 반환 실제 경보 머신.
- record_heartbeat RPC upsert, heartbeats_epoch RPC(epoch 초).

## 인수 기준(기계 검사)
1. tests/test_fleet_heartbeat.py 14개(경계·억제·fail-soft·배선·마이그레이션).
2. 워커 loop 이 record_heartbeat 를 자기 머신으로 호출(배선 테스트).
3. 라이브: macmini/macbook heartbeat→heartbeats_epoch→winpc stale→watchdog --once 경보.
4. ./verify.sh exit 0.

## 적대검증 정조준
- stale 5분 경계 off-by-one, 누락 머신 처리, 30분 억제 재시작 후 상태, notify 예외 fail-soft,
  heartbeat 실패가 워커 잡 처리를 막는지, epoch 시간대(UTC) 정합.

## 비범위
- watchdog/worker plist 설치는 수동(아침). 실서치 잡 heartbeat 라이브 장기가동 아침.

## 적대 검증 로그
- (verdict.json 참조)
