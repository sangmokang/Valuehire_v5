# Goal — 채널별 CDP endpoint 해석 (TODO-2b 조각 A, 2026-07-18)

- 모드: code-change / 위험등급: **L2**(순수 해석 함수 추가 — 기존 launch 방식 미변경, 회귀 0 지향)
- 워크트리: `/Volumes/SSD/Valuehire_v5-portal-channel-cdp-endpoint` (branch task/portal-channel-cdp-endpoint)
- 상위 작업: TODO-2b(SOT-26 §13) — 사람인·잡코리아를 launch_persistent_context 소유 →
  portal_browsers.sh 기동 크롬 CDP attach 로 이행. **이 조각(A)은 그 기반**이고, 실제
  connect_over_cdp 이행·프로필 lock 정리·browser_policy 채널별 검문은 조각 B(별도, L3).

## 현재 상태 (직접 확인한 file:line)
- `scripts/portal_browsers.sh:74-91`: saramin=9223 · jobkorea=9224 · linkedin=9225 포트로
  각각 `--remote-debugging-port`(:163) + `--user-data-dir`(:165) 크롬을 이미 CDP로 띄운다.
  포트는 `SARAMIN_PORT`/`JOBKOREA_PORT`/`LINKEDIN_PORT` env 로 override.
- `portal_worker.py:623-635`: **linkedin_rps 만** `connect_over_cdp(config.chrome_cdp_endpoint)` 로
  그 크롬에 붙는다. `:636-649`: saramin·jobkorea 는 `launch_persistent_context` 로 워커가
  **별도 브라우저를 또 띄운다**(portal_browsers.sh 크롬을 무시) → 프로세스 종료 시 동반 종료.
- `portal_worker.py:37-67,187`: `chrome_cdp_endpoint` 기본은 채널 무관 단일값
  (env→policy SOT→9222). 채널별 포트(9223/9224/9225)와 불일치.

## 근본 원인
채널→CDP endpoint 매핑이 없다. 그래서 saramin·jobkorea 가 portal_browsers.sh 가 띄운
채널별 크롬에 붙을 방법 자체가 부재 → 자기 브라우저를 새로 띄우는 경로만 존재.

## 계약 (입출력 — SDD)
새 순수 함수 `resolve_channel_cdp_endpoint(channel, *, value=None, env=os.environ) -> str`
우선순위(높은→낮은):
1. `value` 가 http 로 시작 → 그대로(호출부 명시).
2. 전역 env `VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT` 가 http 로 시작 → 그대로.
3. 채널별 포트 env(`SARAMIN_PORT`|`JOBKOREA_PORT`|`LINKEDIN_PORT`) → `http://127.0.0.1:{port}`.
4. 채널 기본 포트(saramin=9223, jobkorea=9224, linkedin_rps=9225) → `http://127.0.0.1:{port}`.
- `public_web` 은 CDP 대상 아님 → `ValueError`(호출부가 부르면 안 되는 채널).
- 기본 포트·env 이름은 `portal_browsers.sh` 와 **정확히 동일**(SOT 정합, 재발명 금지).

## 인수 기준 (EARS + 검증 명령)
- WHEN channel=saramin, env 비어있음 THEN `http://127.0.0.1:9223`. (jobkorea=9224, linkedin_rps=9225)
- WHEN `SARAMIN_PORT=19223` THEN saramin → `http://127.0.0.1:19223`.
- WHEN 전역 `VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT=http://x:1` THEN 모든 채널 그 값(포트 env 무시).
- WHEN `value="http://y:2"` THEN 전역 env 보다 우선.
- WHEN channel=public_web THEN ValueError.
- counter-AC: 포트 env 가 비URL 쓰레기여도 채널 기본 포트로 폴백(크래시 금지).
- 검증: `.venv/bin/python -m pytest tests/test_portal_channel_cdp_endpoint.py -q` exit 0 + `./verify.sh` exit 0.

## 비범위 (조각 B로)
- saramin/jobkorea start() 를 connect_over_cdp 로 실제 이행.
- ProfileLock / clear_stale_singleton_locks(launch 전용) 정리.
- browser_policy.assert_browser_ready 채널별 endpoint 검문.
- 라이브 실크롬 attach 검증.

## 적대 검증 로그
- `portal-channel-cdp-endpoint.verdict.json` 참조.
