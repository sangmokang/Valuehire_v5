# Goal 프롬프트 — aisearch-zero 완성

아래 지시를 Valuehire v5 저장소에서 `$st`로 실행합니다. 목표는
`apps/aisearch-zero`를 문서 초안에서 휴대 가능한 코드 리뷰 제품으로 완성하는 것입니다.

## 실행 지시

엄격 모드로 이 Goal을 끝까지 수행하십시오. 진행 중 기존 정의에 답이 있는 사항을 사용자에게
되묻지 마십시오. 파괴적 행동, 본인확인, 표에 없는 신규 상황만 중단 보고 대상입니다.

현재 상태를 완료로 오인하지 마십시오.

- `runtime-code: none`
- `enforced: false`
- 현재 초안은 불만 기록과 설계 기준일 뿐입니다.
- 문서만 작성하고 완료 선언 금지입니다.

## 먼저 읽고 회수할 것

1. `CLAUDE.md`, `AGENTS.md`, `docs/harness.md`, `docs/sot/30-strict-mode-contract.md`
2. 존재한다면 `apps/aisearch-zero/README.md`, `manifest.md`, `docs/complaints.md`,
   `docs/strict-adversarial-review.md`
3. `docs/prompts/goal-full-codebase-review.md`와 현재 코드 리뷰·검증 실행 경로
4. 메모리, 기존 코드, 문서의 `aisearch-zero`, `controller-owned`, `run state` 사례

기존 구현을 재사용할 때는 호출 경로와 검증 결과를 증명하십시오. 존재하지 않는 기능이나
계획 단계의 통제를 이미 작동하는 것처럼 쓰지 마십시오.

## 제품 목표

완성품은 모델의 완료 주장을 믿지 않는 controller-owned 코드 리뷰 실행기입니다.
리뷰 대상과 기준을 manifest로 고정하고, 모든 상태와 증거를 controller가 검증한 뒤에만
`final.json`을 생성해야 합니다.

입력 계약:

- `target_repo`: 리뷰할 저장소의 정규화된 루트
- `base_revision`: 비교 기준 커밋
- `review_scope`: 허용된 상대경로 목록
- `acceptance_criteria`: 검증 가능한 완료 조건 목록
- `verification_commands`: 허용된 읽기·검사 명령 목록

필수 출력:

- `manifest.json`: 입력 계약과 기준 해시
- `state.json`: 현재 단계, 잠금, 증거, 전이 기록
- `findings.json`: 심각도, 근거 위치, 재현 방법, 반례
- `report.md`: 사람이 읽는 코드 리뷰 결과
- `final.json`: controller가 검증한 최종 판정

## 절대 불변식

- 외부 서비스 write 0건입니다. 브라우저 조작 금지, 자동발송 금지, 배포 금지입니다.
- 리뷰 실행은 기본적으로 읽기 전용입니다. 자동 코드 수정은 이번 범위 밖입니다.
- 테스트 삭제·약화 금지입니다. `skip`, `only`, `todo`, assertion 삭제로 통과시키지 마십시오.
- 현재 저장소의 AI Search, 로그인, 사람 양보, 발송 안전장치를 약화하지 마십시오.
- 숨은 fallback 금지입니다. 다른 스킬, 사용자 홈, 과거 작업 폴더를 몰래 읽지 마십시오.
- 절대경로 금지입니다. 모든 저장소 경로는 `target_repo` 기준 상대경로로 계산하십시오.
- secret 원문을 상태, 로그, 프롬프트, 오류, 결과에 기록하지 마십시오.
- 증거 없는 완료 금지입니다. 경고를 성공으로 바꾸거나 상태 부재를 성공으로 보지 마십시오.

## 입력 영역 표

| 입력·상태 | 처리 |
|---|---|
| 정상 manifest, 깨끗한 저장소, 유효한 기준 커밋 | 새 run을 시작 |
| `apps/aisearch-zero`가 없음 | 첫 단위에서 추적 가능한 기본 골격 생성 |
| 기존 draft가 있음 | 내용과 해시를 보존하고 명시적 마이그레이션 |
| 필수 입력이 빈값·null·잘못된 타입 | 오류 코드와 함께 명시적 중단 |
| 기준 커밋·허용 경로가 없음 | 추측하지 않고 명시적 중단 |
| 대상 저장소에 미커밋 변경이 있음 | 목록을 기록하고 명시적 중단 |
| 같은 manifest 재실행 | 같은 `run_id`로 안전하게 재개 |
| 다른 manifest가 같은 `run_id` 사용 | 충돌로 명시적 중단 |
| `state.json` 없음·손상·버전 불일치 | 성공 처리하지 않고 명시적 중단 |
| 동시 실행 또는 잠금 소유자 불일치 | 기존 run을 건드리지 않고 명시적 중단 |
| 검증 명령 실패·시간초과·부분 출력 | 실패 증거를 보존하고 명시적 중단 |
| 독립 검토 도구가 없음 | 누락을 기록하고 완료 금지 |
| controller 쓰기 중 프로세스 종료 | 이전 완전한 파일을 보존하고 재개 가능 상태 유지 |
| 모델 출력이 schema를 위반 | 결과를 폐기하지 말고 격리 후 명시적 중단 |
| 두 번째 Mac 검증 불가 | 로컬 검사는 남기되 휴대 가능 완료 선언 금지 |
| 그 외 전부 → 명시적 중단 | 표를 갱신하고 새 검사부터 추가 |

## 결정 목록

- 구현 언어는 macOS 기본 환경에서 실행 가능한 Python 표준 라이브러리를 우선합니다.
- 추가 패키지가 꼭 필요하면 manifest와 `doctor` 결과에 정확한 버전과 이유를 공개합니다.
- 상태 경로는 대상 저장소 내부의 무시된 run 디렉터리이며 `run_id`와 `machine_id`로 격리합니다.
- 상태 파일은 임시 파일, flush, fsync, rename 순서의 원자적 write로 저장합니다.
- 프로세스 잠금과 상태 소유권을 모두 확인합니다. 경고만 남기고 계속하지 마십시오.
- 모델은 findings 후보만 냅니다. schema, 경로, 커밋, 명령 결과, 최종 판정은 controller가 검증합니다.
- CLI는 최소 `doctor`, `bootstrap`, `review`, `resume`, `status`, `verify`를 제공합니다.
- 설치는 clean clone에서 한 명령으로 재현되며 사용자 홈의 기존 상태를 덮어쓰지 않습니다.

## 목표 구조

```text
apps/aisearch-zero/
  README.md
  manifest.schema.json
  state.schema.json
  final.schema.json
  bin/aisearch-zero
  src/aisearch_zero/
    cli.py
    controller.py
    contracts.py
    state_store.py
    evidence.py
    reviewers.py
  tests/
  fixtures/
```

구조는 검증 결과로 더 작게 만들 수 있지만, 계약·상태·controller 소유권을 합쳐 숨기지는 마십시오.

## 작업 분해와 순서

한 단위 = 인수 기준 1개입니다. 각 단위는 별도 이슈, 별도 작업 공간, 실패 검사,
최소 구현, 관련 검사, 독립 재검토, 전체 검사, 검토 요청, 병합 순서로 닫습니다.
앞 단위가 병합되기 전에는 다음 단위를 시작하지 마십시오.

1. 초안 보존과 추적 가능한 기본 골격
2. manifest·state·final schema와 엄격한 validator
3. `run_id`·`machine_id` 격리, 잠금, 원자적 상태 저장
4. 대상 커밋·범위 스냅샷과 secret 제거 증거
5. reviewer 입력·출력 adapter와 `findings.json` 검증
6. 허용 명령 실행, 결과 해시, 실패 보존, controller 최종 판정
7. CLI `doctor`·`bootstrap`·`review`·`resume`·`status`·`verify`
8. 고정 fixture 회귀 검사와 손상·동시성·재시도 공격
9. clean clone 및 두 번째 Mac 설치·스모크 검증

각 단위에서 새 결함이 나오면 해당 단위를 닫기 전에 실패 검사로 고정하십시오. 범위 밖 결함은
별도 이슈로 남기고 현재 단위에 섞지 마십시오.

## 기계 검증

- 단위별 검사를 먼저 실행하고 실제 통과·실패 개수를 기록합니다.
- 저장소의 `./verify.sh`를 실행하고 종료값이 0이 아니면 완료가 아닙니다.
- 절대경로, 홈 스킬 참조, secret 표본, 자동발송·외부 쓰기 호출이 0건인지 검사합니다.
- 손상 JSON, 사라진 state, 다른 run, 동시 실행, 중간 종료, 재시도 입력을 각각 공격합니다.
- 모델이 가짜 근거 위치나 허용 범위 밖 파일을 내면 controller가 거부하는지 검사합니다.
- clean clone에서 `bootstrap`과 `doctor`를 실행하고, 이어서 fixture 리뷰 1건을 완주합니다.
- 두 번째 Mac에서도 같은 커밋으로 `doctor`와 fixture 리뷰 1건을 실행해 결과 schema를 대조합니다.

## 독립 재검토

각 단위와 최종본을 생성자와 다른 컨텍스트가 읽기 전용으로 공격하게 하십시오. 다음을 찾습니다.

- 상태 없음·손상·충돌이 성공으로 흐르는 경로
- 모델 출력이 controller 검증을 우회하는 경로
- 현재 Mac의 경로·설치·로그인 상태에 대한 숨은 의존
- 테스트가 구현 문구를 그대로 따라 써 함께 틀리는 경우
- 문서만 존재하거나 호출되지 않는 고아 코드
- 실행하지 않은 검사를 완료처럼 보고하는 문구

독립 검토 결과를 그대로 믿지 말고 근거를 직접 재현하십시오. 결함이면 실패 검사를 추가한 뒤
수정하고 다시 검토합니다.

## 최종 완료 조건

아래가 모두 참일 때만 `apps/aisearch-zero/manifest.md`의 상태를 구현 완료로 바꿀 수 있습니다.

1. 모든 파일이 저장소에 추적되고 clean clone에서 실행됩니다.
2. CLI 여섯 명령이 도움말과 실제 동작 검사를 통과합니다.
3. manifest·state·findings·final schema가 유효하고 controller만 최종본을 씁니다.
4. 누락·손상·충돌·동시성·부분 쓰기·재시도 검사가 모두 통과합니다.
5. 관련 검사와 전체 검사가 통과하고 테스트 약화가 0건입니다.
6. 독립 재검토 지적이 재현·해소됐고 남은 차단 결함이 0건입니다.
7. clean clone과 두 번째 Mac에서 같은 fixture 결과 계약을 충족합니다.
8. 외부 서비스 write, 브라우저 조작, 발송, 배포가 모두 0건입니다.
9. 모든 변경이 검토 요청과 자동 검사를 통과해 기본 브랜치에 병합됐습니다.

하나라도 거짓이면 상태는 진행 중 또는 중단입니다. 일부 코드, 일부 검사, 문서 완성만으로 전체
완료를 주장하지 마십시오.

## 최종 보고

사장님께 쉬운 한국어로 요청, 구현 결과, 검사 개수, 두 차례 확인 결과, 남은 위험, 다음 행동을
짧게 보고하십시오. 실제 실행하지 않은 검사와 외부 작업은 언급하지 마십시오.
