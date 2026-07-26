# Goal — 로그인·기기·브라우저 40단위 구현 선행 정리

- 작성: 2026-07-26
- 모드: noncode / 위험등급: L1
- 목적: 새 구현에 앞서 `.harness/red-ledger.tsv`에 남은 두 개의 과거 RED가 실제 미완료인지 재검증하고, 완료 근거가 있는 행만 GREEN으로 정정한다.

## 현재 상태와 근거

| 항목 | 확인한 근거 | 판정 |
|---|---|---|
| `nl-gateway-connect` | 구현 커밋 `17ad672`가 `scripts/discord_direct_gateway.py`와 `tests/test_gateway_nl_connect.py`를 포함하며 PR #177로 병합됨. 후속 집계 행 `nl-shell-ac-n2-n4`도 GREEN임. | 과거 RED 행이 닫히지 않은 기록 오류 |
| `hermes-retirement-contract` | 구현 커밋 `e697dc3`, `docs/engineering/hermes-retirement-contract.verdict.json`의 `three_way_agree=true`, `status=Contract complete`, 후속 HR-0 PR #181 병합 기록이 존재함. | 과거 RED 행이 닫히지 않은 기록 오류 |
| 기준 커밋 전체 검사 | `a141459c645830f719fc2b5db517d0c60c77d594`에 대한 GitHub Actions Verify 실행 `30177729326`이 `success`로 완료됨. | 기준선 GREEN |
| 현재 WinPC 로컬 검사 | Linux 전용 `fcntl`, `os.uname()`을 import하는 기존 검사 3개가 Windows Python 수집 단계에서 중단됨. | 제품 회귀가 아닌 검사 실행 환경 불일치. 이 정리에서 코드를 바꾸지 않음 |

## 인수 기준

1. 위 두 과거 행만 완료 근거를 붙여 GREEN으로 바뀐다.
2. 다른 ledger 행과 제품 코드·테스트는 바뀌지 않는다.
3. ledger의 미해결 RED 수가 0이 된다.
4. 기준 커밋의 공식 전체 검사 성공 URL과 로컬 환경 제한을 숨기지 않고 남긴다.

## 입력·출력

| 구분 | 입력 | 출력 |
|---|---|---|
| 기록 정정 | 병합 커밋, 후속 GREEN 행, 독립 판정 파일 | 근거가 포함된 GREEN 행 2개 |
| 기준선 판정 | GitHub Actions 실행 결과, WinPC 로컬 수집 오류 | 공식 기준선 성공 + 로컬 환경 제한 기록 |

## 예외 처리

| 상황 | 처리 |
|---|---|
| 병합 커밋 또는 완료 판정이 없음 | RED를 유지하고 작업을 중단 |
| 완료 근거끼리 충돌 | RED를 유지하고 별도 조사 |
| 다른 RED 발견 | 해당 행을 수정하지 않고 별도 작업으로 분리 |
| 로컬 Windows 전용 호환 문제 | 테스트를 건너뛰거나 약화하지 않고 공식 Linux 검사와 대상별 검사를 사용 |
| 그 외 전부 | 임의 정정하지 않고 명시적으로 중단 |

## 비범위

- 제품 코드와 테스트의 Windows 이식
- 로그인 정책 또는 브라우저 동작 변경
- 브라우저 실행·종료·탭 조작
- push·PR·merge
