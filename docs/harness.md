# Harness — 표준 작업 루프

코드를 건드리는 모든 작업(버그 수정, 새 기능, 서치 기능 추가, 포지션 처리, 스크래퍼 수정)은
이 절차를 따른다. 각 단계는 게이트가 있고, 통과 못 하면 다음 단계로 가지 않는다.

배관은 `Makefile` + `verify.sh` + `scripts/harness/*` + pre-push 훅으로 이 레포에 구현돼 있다.
최초 1회: `make install-hooks` (pre-push 훅 설치). 러너: `requirements-dev.txt` 또는 `.venv-playwright`.

## 게이트 0 — 시작 자격
- `make red-ledger` 실행. 미해결 RED(=`.harness/red-ledger.tsv`의 RED 행 또는 현재 `verify` 실패)가 있으면
  새 작업을 시작하지 않는다. 그것부터 닫는다.
- 깨끗한 컨텍스트인지 확인(아니면 /clear).

## 1 — 스펙(이슈)
- GitHub 이슈를 만든다(`gh issue create`). 반드시 **인수 기준 1개**:
  "무엇이 참이면 끝났는가"를 `./verify.sh`로 검사 가능한 단언(=테스트)으로.
- 단언 하나로 못 적으면 너무 크다 → 쪼개서 별도 이슈로.

## 2 — RED 테스트 먼저
- `make task NAME=...` 로 worktree를 판다(브랜치 `task/<slug>`, ledger에 RED 등록).
- 인수 기준을 실패하는 테스트로 작성해 커밋(RED 확인).
  이 테스트를 GREEN으로 만드는 것 외엔 손대지 않는다.

## 3 — 구현
- RED→GREEN 최소 변경만. 규모 목표 파일 1~5 / diff 50~300줄.
- 작업 중 새 문제 → 고치지 말고 새 이슈로 분리(+ `.harness/red-ledger.tsv`에 RED 추가).
- **자기확장 규칙: 새 캡처 대상/사이트(사람인·잡코리아·LinkedIn·ChatGPT 등)를 추가하면
  그 사이트의 verify 단언 + 픽스처를 같은 커밋에 추가한다.**

## 4 — 검증(기계가 판정)
- `./verify.sh` 실행, 출력 숫자(`N passed, M failed`)를 그대로 붙인다.
- exit 0 아니면 "진행 중". "고쳤습니다/재로드하세요" 금지. 멈추지 않는다.
- GREEN이면 `.harness/red-ledger.tsv`의 해당 작업 행을 RED→GREEN으로(또는 제거).

## 5 — 배송
- `make ship`(verify 재실행 → push → PR). pre-push 훅이 verify를 한 번 더 재실행한다.
- PR 본문: 이슈 링크 + 증명 테스트 + verify 출력.
- CI 초록 + merge 전까지 "완료"는 없다. (CI는 아직 미설치 — `.github/workflows` 추가 시 활성)

## 게이트 6 — 종료
- merge 후 worktree 정리(`git worktree remove`) + /clear. 다음 작업은 게이트 0부터.

---
### 배관 명령 요약
| 명령 | 게이트 | 동작 |
|---|---|---|
| `make red-ledger` | 0 | 미해결 RED 점검 (있으면 비-0) |
| `make task NAME=x` | 2 | worktree 생성 + ledger RED 등록 |
| `make verify` / `./verify.sh` | 4 | 테스트 전체, exit 0 == GREEN |
| `make ship` | 5 | verify → push → PR |
| `make install-hooks` | — | pre-push 훅 설치 (최초 1회) |

### 아직 없는 것(후속 과제)
- `.github/workflows/verify.yml` — 게이트 5의 "CI 초록"을 실제로 강제하려면 필요.
- 사전 존재 RED: `profile-recovery-proof` (테스트 2건). 게이트 0가 막고 있음 — 별도 이슈로 닫을 것.
