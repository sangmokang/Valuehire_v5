# goal: 링크드인 CDP 포트 하드코딩(9225) 제거 — 실제 살아있는 크롬 포트 자동 탐지

- 날짜: 2026-07-08
- 모드: code-change / 위험등급 L2 (공유 도구·스킬 배선, 발송·파괴 없음)

## 현재 상태 (직접 확인한 `file:line` / 실측)
- `tools/multi_position_sourcing/raw_cdp.py:19` — `CDP_HTTP = "http://localhost:9222"` (모듈 상수, env 안 읽음).
- `tools/multi_position_sourcing/auto_send_runner.py:106` — `os.environ["CDP_HTTP"] = cdp_http` 로 채널 포트를
  주입하지만, raw_cdp 가 env 를 읽지 않아 **주입이 죽어있다**(항상 9222 로 붙음). 부분배선 결함.
- `scripts/portal_browsers.sh:31` — `LINKEDIN_PORT=9225` 하드코딩.
- 실측(2026-07-08): 링크드인 로그인 프로필로 살아있는 크롬은 **9338**(`ps ... --user-data-dir=…linkedin`
  → `remote-debugging-port=9338`, CDP `Chrome/149` 응답). 9225 무응답. `DevToolsActivePort` 파일 없음.
  → 포트를 못박으면 실제 포트와 어긋나 붙지 못함(이번 사고의 뿌리).

## 근본 원인
포트를 코드/스킬에 못박아 둠 + raw_cdp 가 런타임 오버라이드(env)를 무시함.
→ 크롬이 표준 포트가 아닌 곳(9338)에 뜨면 도구가 죽은 포트로 붙어 "브라우저가 죽었다"로 오진.

## 인수 기준 (기계 단언)
1. `scripts/portal_browsers.sh cdp linkedin` 은 **그 프로필로 실제 살아있는 크롬의 포트**를 찾아
   `http://127.0.0.1:<실제포트>` 를 출력한다 — 설정된 `LINKEDIN_PORT` 와 달라도 실제 포트를 우선한다.
   (재현: 설정 19225, 실제 크롬 19338 → 출력 `http://127.0.0.1:19338`)
2. 살아있는 크롬이 없으면 재실행하지 않고 비정상 종료(사람 로그인/캡차 게이트 존중, 봇행동 금지).
3. `raw_cdp` 는 `CDP_HTTP` 환경변수를 **호출 시점에** 읽어 그 엔드포인트로 붙는다(미설정 시 9222 폴백).
   → auto_send_runner 의 기존 포트 주입도 되살아난다.

## 적용 게이트
harness 게이트 0~6, worktree, RED→GREEN, verify(pytest), 배선 grep, R6(skill-creator 로드 완료).

## 적대검증 정조준
- `cdp` 서브커맨드가 표준포트 폴백에 속아 실제(9338)를 놓치지 않는가.
- raw_cdp env 읽기가 import 시점 바인딩이라 늦게 set 된 env(auto_send 패턴)를 놓치지 않는가 → 호출시점 읽기.
- 스킬 지시가 실제 raw_cdp 호출 경로에 배선되는가(고아 아님).

## 비범위
- 사람인/잡코리아 자동 포트 전환 로직(헬퍼는 3채널 공통이나 스킬 배선은 링크드인 우선).
- 로그인/캡차 자동 처리(사람 게이트, SOT).

## 적대 검증 로그
- G(Claude): cdp 서브커맨드 + raw_cdp env + 스킬 배선. RED(exit2/_cdp_base 없음)→GREEN. mutant(포트 못박기)→테스트 FAIL로 가짜GREEN 배제. 실측 linkedin→9338.
- V1(fresh Claude, agentId a651eea0c90dc1bdc): verdict **fail**. 부분배선 없음 확인(env 호출시점·ws 포트 일치·회귀 통과). 결함 2개 재현:
  - ① [BUG] cmd_cdp grep 경계 부재 → /linkedin 이 /linkedin2 오탐.
  - ② [ROBUSTNESS] 신규 테스트 flaky(TIME_WAIT + allow_reuse_address 미설정).
- 수정(G): ① 공백경계 case 정확일치 + 회귀 테스트 추가, ② _free_port + allow_reuse_address=True.
- T(재현): pytest 3회 연속 5 passed(결정성), verify.sh 1114 passed exit0, 실측 3채널 정확.
- 상태: V1 결함 전부 수정·재현 확인. (L2 — V2 리셋 재검증은 L3 전용이라 미적용.)
