# Goal — 채널별 exact raw single-target CDP 생산 배선 (TODO-2b, 2026-07-18)

- 모드: code-change / 위험등급: **L3**(실제 포털 세션·기존 탭에 단일 raw CDP attach)
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

## 라이브 실측 발견 (2026-07-18, 조각 B 안전요건)
사장님 실제 환경 포트 스캔(읽기전용 /json/version·/json):
- 9222=사람인 로그인탭 / 9223=잡코리아 / 9224=잡코리아 / 9225=빈탭(linkedin 포트).
- **실제 포트 배치가 portal_browsers.sh 기본(saramin=9223)과 불일치** → 채널→기본포트
  매핑만으로 attach 하면 사람인 작업이 9223(잡코리아 크롬)에 붙는 오접속 사고.
- ⇒ **조각 B 필수 계약**: resolve_channel_cdp_endpoint 로 후보 포트를 얻되, attach 전
  그 endpoint 의 탭에 대상 사이트 로그인 마커가 실제로 있는지 검증(SOT-26 §2). 없으면
  다른 살아있는 포트를 마커로 재탐색. v4 tools/position-batch/lib/cdp-endpoints.mjs 의
  계층 match 와 동형. 조각 A(순수 포트 해석)는 이 검증의 1차 후보 생성기 역할.

## V1 적대검증 반영 (2026-07-18)
- 봉인: 포트 범위 검증(1..65535, 0·65536 폴백) + LINKEDIN_PORT override 테스트(뮤텐트 구멍).
- **조각 B 설계 교정(SOT-26 INV5)**: Playwright 전체 `connect_over_cdp` 확대 금지 —
  저장소는 **raw CDP 단일 탭**(`raw_cdp.py`, browser_policy attach_mode: raw_single_tab)만
  허용. 기존 linkedin `connect_over_cdp` 는 이미 제거 대상 부채. 조각 B 는 connect_over_cdp
  가 아니라 raw_cdp 단일 탭 + 실포트 탐색(portal_browsers.sh cdp) 경로를 재사용한다.
- 고아 확정: 조각 A 단독 merge 금지(운영 호출자 0). 조각 B(raw 단일탭 배선)와 묶어 배송.

## V2 적대검증 반영 (2026-07-18) — 정직성 정정
- **"WIRED" 과장 정정**: 배선은 문법적 고아해소일 뿐, config default_factory+value-우선
  때문에 채널 기본포트가 프로덕션에서 영구 미도달 = 무동작 스캐폴드. TODO-2b 실질
  (saramin/jobkorea 를 portal_browsers.sh 크롬에 attach)은 이 조각에서 0% 전달.
- 작업트리 회귀(isascii 봉인 revert) V2 적발 → 폐기, HEAD 19 passed 복원.
- **조각 B(라이브) 강화 계약**: ① 마커를 substring 이 아닌 **host 단위** 매칭
  (mylinkedin.com·notsaramin.co.kr 오탐 차단) ② 자동화 전용 크롬 식별(user-data-dir/
  포트 배타성 확인)으로 사장님 개인 크롬 오접속 방지 ③ find_verified 를 start() 에
  실제 배선(고아 해소) + 실크롬 라이브 attach 검증(사장님 입회).
- ⛔ PR#149 단독 merge 금지 — 조각 B 실배선과 묶어야(V1·V2 일치).

## 최종 완결 정정 (2026-07-18, 이후 판정이 위 역사 로그보다 우선)

초기 조각 A의 "0%/단독 merge 금지"는 같은 PR에서 조각 B2까지 완성하며 해소했다.
정식 `profile_only` 경로는 관리 Chrome의 executable/profile/root/CDP identity를 확인하고,
공식 host의 로그인된 `type=page` exact target 하나만 raw WebSocket으로 attach한다. 전체
브라우저 attach, 새 창·새 탭 생성, target close, browser/profile/session 종료는 없다.

모든 portal mutation은 채널별 원자 lease/token, 180초 간격의 owner-idle 두 스냅샷,
exact URL, 브라우저-owned Overlay의 렌더 challenge, label-derived immutable custom tag,
동일한 resolved CDP object identity에 묶인다. 렌더 proof 뒤 owner guard를 다시 수행하고,
그 동일 object에서 `Runtime.callFunctionOn`으로 identity/visibility/URL/행동을 원자 실행한다.
내비게이션 뒤에는 exact lifecycle을 확인하고 새 문서에 marker를 재주입·재증명한다.
clear/socket/partial acknowledgement가 불명확하면 fail-closed로 lease를 유지한다.

이 PR은 위 `profile_only raw_single_tab` 검색 범위에서 standalone merge 가능하다. 다만
사용자가 로그인해야 할 OS 창을 찾아 맨앞에 표시하는 window locator와 HUMAN_AUTH 대기,
safe click→Browser Back keepalive는 별도 `login` 스킬 구현 범위이며 여기서 해결했다고
주장하지 않는다.
