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
