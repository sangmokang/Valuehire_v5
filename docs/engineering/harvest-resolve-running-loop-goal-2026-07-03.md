# Goal — PC-K4 BUG-HARVEST-ASYNC 봉인 (실행중 이벤트루프에서 코루틴 resolve) · 2026-07-03

> 모드: code-change · 위험등급 L3(무인 상시 수집 파이프라인). 근거: addendum-2026-07-02 R13/PC-K4(verdict PLAUSIBLE→백로그 승격).

## 현재 상태 (직접 연 file:line + 재현)
- `tools/multi_position_sourcing/harvest_runner.py:76-80` — `_resolve(value)`: `if asyncio.iscoroutine(value): return asyncio.run(value)`.
- 호출부: `harvest_runner.py:131` `found = tuple(_resolve(execute_item(item)))` (run_harvest_cycle 내부).
- **재현(T, 2026-07-03):** sync 컨텍스트에서는 정상. **실행중 이벤트루프 안에서 `_resolve(코루틴)` → `RuntimeError: asyncio.run() cannot be called from a running event loop`** + 코루틴 미await 경고.
- 배선 상태: `run_harvest_cycle` 프로덕션 호출자 0(아직 라이브 미배선, PC-D5 live 드라이버 미착수). `_resolve`는 run_harvest_cycle(테스트 배선)이 호출. **이 조각은 미래 라이브 경로(async 드라이버)의 크래시를 미리 봉인하는 spec-sanctioned 하드닝**이며, 그 사실을 verdict에 명시한다(현재 프로덕션 무영향).

## 근본 원인
`asyncio.run`은 실행중 루프에서 호출 불가. live Harvest 드라이버가 async 컨텍스트로 run_harvest_cycle을 돌리고 execute_item이 코루틴을 반환하면 사이클이 통째로 크래시(0건 수집).

## 계약 (SDD)
`_resolve(value)`:
- 코루틴 아님 → 그대로 반환.
- 코루틴 + 실행중 루프 없음 → `asyncio.run`(현행 유지).
- 코루틴 + 실행중 루프 있음 → 별도 스레드의 새 루프에서 완료(현재 루프 블로킹·미await 경고 회피). 크래시 금지.

## 인수기준 (기계검증 1)
`tests/test_harvest_resolve_loop.py` GREEN: (a) 비코루틴 passthrough, (b) sync 컨텍스트 코루틴 resolve(회귀), (c) **실행중 이벤트루프에서 `_resolve(코루틴)`가 RuntimeError 없이 결과 반환**, (d) 실행중 루프에서 `run_harvest_cycle`(async execute_item)가 크래시 없이 저장 완료. + `./verify.sh` exit 0.

## 적용 게이트
harness 0→1→2(RED)→3(GREEN)→4(verify)→4b(자기적대+Codex V1+Claude V2)→5(ship PR).

## 적대검증 정조준
- 스레드-새루프 방식이 코루틴을 정확히 완주하나(예외 전파 포함).
- execute_item이 예외를 raise하는 코루틴이면 run_harvest_cycle fail-closed 유지되나.
- 중첩 루프·타임아웃·결과 형상(튜플) 보존.

## 비범위
run_harvest_cycle 라이브 배선(PC-D5), execute_item 실구현.

## 적대 검증 로그
(비움 — 게이트4b에서 채움)
