# PC-D2b — 상시 Harvest 드라이버(라이브 사이클 경로) goal (2026-07-04)

> `/st` L3 · mode=code-change · worktree `task/reservoir-harvest-driver`
> 백로그: `docs/engineering/valuehire-pipeline-consolidation-backlog-2026-07-01.json` PC-D2b
> 선행: PC-D5(PR#54, `harvest_executor.HarvestSearchExecutor`) · PC-E1(PR#57) · PC-F1(PR#55) · PC-F3(`challenge-detect-sot26-parity.verdict.json`)

## 현재 상태 (직접 확인)
- `tools/multi_position_sourcing/harvest_runner.py:98` — `run_harvest_cycle` 은 sync 전용. `_resolve`(`harvest_runner.py:76`)는 실행중 이벤트루프 안에서 async `execute_item` 을 fail-closed 로 거부하고 "live async 드라이버는 execute_item 을 직접 await 하는 async 경로를 써야 한다(BUG-HARVEST-ASYNC)"고 명시.
- `tools/multi_position_sourcing/harvest_executor.py:50` — 라이브 실행자 `HarvestSearchExecutor`(PC-D5)는 **async** `__call__`. 리포 전체에 이를 `run_harvest_cycle` 에 꽂는 프로덕션 드라이버가 0개(고아 상태, grep `HarvestSearchExecutor` → 정의+테스트뿐).
- `scripts/valuehire-search-loop.sh:4` — 현행 데몬 루프는 `REPO_DIR=~/Desktop/Valuehire_v5`(경로 드리프트) + `dry_run` 모듈만 호출. 라이브 사이클 경로 미호출. (데몬 교체 자체는 PC-K6.)
- 페이싱·양보 재료는 병합됨: `harvest_policy.py`(PC-E1), `owner_activity.compute_yield_decision`(PC-F1).

## 근본 원인
저수지 Harvest 의 심장(`run_harvest_cycle`)과 라이브 실행자(PC-D5)가 있는데 **둘을 잇는 드라이버가 없다**. 또 심장이 sync 전용이라 async 라이브 실행자를 상주 루프에서 돌릴 공식 경로가 없다(BUG-HARVEST-ASYNC).

## 계약 (SDD — 입출력 먼저)
```python
# tools/multi_position_sourcing/harvest_runner.py (추가)
async def arun_harvest_cycle(queue, *, execute_item, save_rail, run_id, today,
                             owner_activity_detected=False, log_root=None) -> HarvestCycleSummary
# run_harvest_cycle 과 동일 의미론(R4 skip / fail-closed / 무조건 저장 / 12필드 로그),
# 단 execute_item 코루틴을 직접 await — 실행중 루프 안에서도 동작.

# tools/multi_position_sourcing/harvest_driver.py (신규)
def resolve_repo_dir() -> Path
# 모듈 파일 위치에서 파생한 현재 체크아웃 루트. env(VALUEHIRE_REPO_DIR)·HOME·Desktop 미참조.

@dataclass(frozen=True)
class TickDecision: run: bool; reason: str
def decide_tick(*, frontmost_is_chrome: bool, os_idle_seconds: float | None,
                idle_threshold_seconds: float = DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS) -> TickDecision
# run == not compute_yield_decision(...) (PC-F1 단일출처, 재구현 금지)

async def drive_cycle_once(*, execute_item, save_rail, segments, machine, run_id, today,
                           owner_activity_detected=False, log_root=None) -> HarvestCycleSummary
# build_harvest_queue(segments, machines=(machine,), sites=sites_for_machine(machine))
# → arun_harvest_cycle(...) — dry_run 모듈을 일절 호출하지 않는 라이브 사이클 경로.

def main(argv=None) -> int
# --executor {fake,live} --segments s1,s2 --machine m --run-id --today --log-root --output
# --keywords-json (live 필수) --skip-owner-check(기본은 감지 ON, R4)
# exit 0=사이클 완료 / 2=인자 fail-closed. 출력 JSON에 executor 종류 명시(라이브인 척 금지).
```

## 인수 기준 (기계 단언)
1. 주입 페이크 실행자 호출횟수/인자: segments 2개 × 사이트 2개(사람인·잡코리아) → 정확히 4회, 인자는 해당 `HarvestItem`. 로그 문구가 아니라 호출 기록으로 단언.
2. R4: `owner_activity_detected=True` → 실행자 호출 0회, 전 레코드 `skip`.
3. async 실행자를 **실행중 이벤트루프 안에서** 직접 await(sync 경로가 못 하는 케이스) 성공.
4. `resolve_repo_dir()` = 현재 체크아웃(모듈 위치 파생), env `VALUEHIRE_REPO_DIR`/Desktop 드리프트 무시.
5. `decide_tick` 이 `compute_yield_decision` 과 전 그리드 일치(단일출처).
6. CLI: fake 스모크 exit 0 + 산출 JSON + `logs/reservoir/<today>.jsonl` 기록 / 빈 segments·live 무키워드 exit 2.
7. `./verify.sh` exit 0 (baseline 895 passed, 3 xfailed + 신규).

## 주관 단언(수동 verdict 몫)
- launchd 실운영(상주)은 기계검사 완결 불가 — PC-K6 에서 데몬 교체 후 수동 확인. live 실행자 실구동(playwright 스택)은 PC-F4b/K6 몫.

## 적대검증 정조준
- 페이크 GREEN: 테스트가 sync 경로만 찌르고 live 는 async 경로를 타는 불일치 → 드라이버는 async 단일 경로(`arun_harvest_cycle`)만 쓴다. 테스트도 같은 경로.
- `arun_harvest_cycle` 이 sync 판과 의미론 드리프트(로그/저장/fail-closed) — 공용 헬퍼 추출로 단일출처화, 기존 `test_reservoir_harvest.py` 그대로 GREEN 이어야.
- CLI 가 owner 감지 기본 OFF 로 배송되는 사고(SOT2 위반) — 기본 ON, 끄려면 명시 플래그.

## 비범위
- launchd plist/`valuehire-search-loop.sh` 교체(PC-K6), playwright 라이브 러너 팩토리 실구동(PC-F4b/K6), segment→keyword 사전 구축(주입 JSON).

## 적대 검증 로그
(G/V1/V2/T — `docs/engineering/reservoir-harvest-driver.verdict.json` 에 축적)
