---
name: harness
description: 코드를 건드리는 모든 작업의 표준 진행 절차. '작업 시작', '버그 수정', '새 기능', '서치 기능 추가', '포지션 처리', '스크래퍼 수정' 등에서 트리거. 게이트를 통과 못 하면 다음 단계로 못 간다.
---

# Harness — 표준 작업 루프
코드를 건드리는 모든 작업은 이 절차를 따른다. 각 단계는 게이트가 있고,
통과 못 하면 다음 단계로 가지 않는다. 단계를 건너뛰지 않는다.

## 게이트 0 — 시작 자격
- `make red-ledger` 실행. verify RED인 미해결 작업이 있으면 새 작업을 시작하지 않는다. 그것부터 닫는다.
- 깨끗한 컨텍스트인지 확인(아니면 /clear).

## 1 — 스펙(이슈)
- GitHub 이슈를 만든다. 반드시 **인수 기준 1개**: "무엇이 참이면 끝났는가"를 ./verify.sh로 검사 가능한 단언으로.
- 단언 하나로 못 적으면 너무 크다 → 쪼개서 별도 이슈로.

## 2 — RED 테스트 먼저
- `make task NAME=...`로 worktree를 판다.
- 인수 기준을 실패하는 테스트로 작성해 커밋(RED 확인). 이 테스트를 GREEN으로 만드는 것 외엔 손대지 않는다.

## 3 — 구현
- RED→GREEN 최소 변경만. 규모 목표 파일 1~5 / diff 50~300줄.
- 작업 중 새 문제 → 고치지 말고 새 이슈로 분리.
- **자기확장 규칙: 새 캡처 대상/사이트를 추가하면 그 사이트의 verify 단언 + 픽스처를 같은 커밋에 추가한다.**

## 4 — 검증(기계가 판정)
- `./verify.sh` 실행, 출력 숫자를 그대로 붙인다.
- exit 0 아니면 "진행 중". "고쳤습니다/재로드하세요" 금지. 멈추지 않는다.

## 5 — 배송
- `make ship`(push→PR). pre-push hook이 verify를 재실행.
- PR 템플릿 채움: 이슈 링크 + 증명 테스트 + verify 출력.
- CI 초록 + merge 전까지 "완료"는 없다.

## 게이트 6 — 종료
- merge 후 /clear. 다음 작업은 게이트 0부터.

---

## 워크트리 적용 (게이트 2의 실체)

**한 작업 = 한 워크트리.** 게이트 2의 `make task NAME=...`는 메인 작업트리를 건드리지 않고
격리된 git worktree를 파는 것이다. 이 격리가 Harness가 깨지지 않게 하는 핵심이다.

### 왜 워크트리인가
- **메인 오염 금지**: 작업은 항상 별도 worktree/브랜치에서 진행. `main`은 항상 초록(merge된 상태)으로 유지.
- **충돌 없는 병렬**: 여러 작업이 서로 다른 worktree에서 동시에 돌아도 파일이 안 섞인다.
- **RED 보존**: RED 테스트 커밋이 그 worktree 안에 갇혀 있어, 검증 전까지 메인으로 새지 않는다.
- **깨끗한 폐기**: 작업이 엎어지면 worktree만 날리면 된다(`git worktree remove`). 메인은 무손상.

### 표준 절차
1. **판다**: `make task NAME=fix-scraper` → `worktrees/fix-scraper/` 에 `task/fix-scraper` 브랜치로 worktree 생성.
   - `make` 미정비 시 동등 명령: `git worktree add worktrees/fix-scraper -b task/fix-scraper`
   - Claude Code 내부에서는 `EnterWorktree` 툴 또는 superpowers `using-git-worktrees` 스킬로 동일 격리 확보.
2. **그 안에서만 작업**: 게이트 2~4(RED→구현→verify)를 전부 이 worktree 안에서 수행. 메인 디렉터리로 나오지 않는다.
3. **배송**: 게이트 5의 `make ship`은 이 worktree 브랜치를 push하고 PR을 연다. pre-push hook이 worktree 안에서 `./verify.sh`를 재실행한다.
4. **회수**: merge 후 `make task-done NAME=fix-scraper`(= `git worktree remove worktrees/fix-scraper`)로 worktree를 제거하고 게이트 6의 /clear.

### 게이트 규칙(워크트리)
- 메인 작업트리에서 직접 소스 파일을 수정하면 게이트 위반. 즉시 worktree로 옮긴다.
- 한 worktree에 인수 기준 1개만. 두 개를 한 worktree에 섞으면 게이트 1로 되돌아가 쪼갠다.
- 미해결(verify RED) worktree가 남아 있으면 게이트 0에서 새 작업을 시작하지 않는다 — `make red-ledger`가 그 worktree들을 센다.

> 사전 요건: 이 repo가 아직 git 저장소가 아니면 `git init` 후 원격/CI를 붙여야 워크트리·`make ship`·pre-push hook이 동작한다. 인프라(`Makefile`, `verify.sh`, PR 템플릿)는 미비 시 별도 이슈로 먼저 세운다.
