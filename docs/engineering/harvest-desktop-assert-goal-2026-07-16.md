# harvest-desktop-assert — 환경 의존 단언 제거 goal (2026-07-16)

## 1. 현재 상태
- `tests/test_harvest_driver.py:44` — `assert "Desktop" not in str(root)`.
- 체크아웃이 `~/Desktop/Valuehire_v5` 인 로컬 맥에서는 구현이 정상이어도 항상 FAIL.
  CI(러너 경로에 Desktop 없음)에서만 PASS → 로컬 게이트 0(red-ledger)이 상시 RED.
- 재현: `make red-ledger` → `FAILED tests/test_harvest_driver.py::test_resolve_repo_dir_is_current_checkout` (1 failed, 1500 passed).

## 2. 근본 원인
- 인수 기준 #4의 의도는 "resolve_repo_dir()가 env(VALUEHIRE_REPO_DIR) 드리프트 경로를 무시하고
  현재 체크아웃(`__file__` 파생)을 반환"인데, 이를 **체크아웃 절대경로의 어휘("Desktop")**로 단언해
  머신 위치에 의존하는 검사가 됨. 구현(`tools/multi_position_sourcing/harvest_driver.py:37-39`)은 정상.

## 3. 인수 기준 (EARS)
- **AC1**: While 체크아웃이 어느 경로에 있든(로컬 Desktop 포함), When `VALUEHIRE_REPO_DIR` 에 드리프트 경로가 설정돼 있으면, Then `resolve_repo_dir()` 검사는 "현재 체크아웃 == 반환값"과 "env 경로 ≠ 반환값"으로 판정해야 한다.
  - 검증: `.venv-playwright/bin/python -m pytest tests/test_harvest_driver.py -q`
  - counter-AC: 구현이 env 경로를 따라가도 초록이면 가짜 (뮤테이션으로 반증).

## 4. 계약 스펙
- 입력: env `VALUEHIRE_REPO_DIR`=임의 드리프트 경로. 출력: `Path` == `Path(harvest_driver.__file__).resolve().parents[2]`, ≠ env 경로.

## 5. 비범위
- `resolve_repo_dir()` 구현 변경 없음. 다른 테스트 변경 없음.

## 6. 검증 증거 (Gate 4a + R2)
- 뮤테이션: 구현을 `Path(os.environ[...])` 반환으로 고의 파괴 → 해당 테스트 1 failed (RED 확인) → 원복 → 1 passed.
- worktree `./verify.sh`: `1499 passed, 2 skipped, 4 xfailed, 102 subtests passed in 27.73s`, `verify: pytest exit=0`.

## 적대 검증 로그
(아래에 V1 판정 append)

### V1 (codex-v1-harvest) — 2026-07-16 · VERDICT: PASS

반증 시도(실제 실행):
1. **베이스라인**: `.venv-playwright/bin/python -m pytest tests/test_harvest_driver.py -q` → 20 passed.
2. **뮤테이션 A — env 추종**(`harvest_driver.py:37` 을 `Path(os.environ["VALUEHIRE_REPO_DIR"], ...)` 반환으로 파괴):
   - 전체 테스트 → 1 failed (`test_harvest_driver.py:43 assert root == expected`). RED 확인. 원복 후 20 passed.
3. **새 단언 독립성 격리** — `assert root == expected`(43)와 `.is_dir()`(44)를 `or True` 로 무력화한 뒤 뮤테이션 A 재적용:
   - `test_harvest_driver.py:46 assert root != drifted.resolve()` 단독으로 FAIL 발생.
   - → 새 단언은 **tautology 아님**. env 추종 버그를 앞 단언 없이도 독립 포착(질문 #1 반증 실패 = 건전).
4. **뮤테이션 B — 깊이 off-by-one**(`parents[2]`→`parents[1]`): `:43 assert root == expected` 에서 FAIL. 제거된 "Desktop" 부분문자열 검사가 담당하던 회귀도 `root == expected` 강단언이 그대로 커버함 → 실제 버그 포착력 무손실(질문 #3).
5. **원 의도 약화 여부(질문 #1·#3)**: 옛 `"Desktop" not in str(root)` 는 체크아웃 어휘에 의존한 프록시였고, Desktop 체크아웃 맥에서 정상 구현이어도 상시 RED(환경 의존). 새 `root != drifted.resolve()` 는 AC#4 의 실제 계약("env 드리프트 무시")을 직접 인코딩 → 더 충실. 손실 시나리오 없음(잘못된 반환은 모두 `root == expected` 가 먼저 포착).
6. **부작용/원복**: 모든 뮤테이션 후 `git diff --stat` 공백(무변경) 확인. 매 회 클린 원복.

결론: 새 단언은 드리프트 무시 의도를 약화시키지 않았고, tautology 경로 없으며, 원 버그(fleet 낡은 Desktop/env 드리프트)를 여전히 포착한다. **PASS.**
