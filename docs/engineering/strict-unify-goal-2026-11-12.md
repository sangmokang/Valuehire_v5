# strict 스킬 단일화 + GitOps 배포 위생 — goal (2026-11-12)

- 모드: code-change · 등급: **L3**. SOT 수정(SOT-30)과 전역 진입점 배포 경로를 바꾸므로 L3로 분류했다.
- 지시: 오너가 2026-11-12에 두 가지를 지시했다. "strict 스킬을 GitOps 10원칙 관점으로 리뷰하고, /codex:adversarial-review와 함께 반영해 스킬을 같이 쓰고, 유사한 st 스킬은 지워라."
- 읽은 SOT: `docs/sot/30-strict-mode-contract.md`, `Makefile`, `verify.sh`, `scripts/harness/task.sh`, `tools/codex_skill_sync/sync.py`, `tests/test_strict_v5_port.py`, `tests/test_codex_skill_sync.py`.
- 워크트리: `../Valuehire_v5-strict-unify`(branch `task/strict-unify`, base `origin/main` b04bb96).
  - `make task`를 쓰지 않은 이유: task.sh가 메인 체크아웃의 `.harness/`와 `.claude/`에 기록하고, 현재 체크아웃 HEAD(작업 브랜치)를 base로 삼는다. 그래서 origin/main을 base로 하는 `git worktree add`를 썼다.

## 현재 상태 (사실, file:line)

1. **사본 4개가 서로 다르다**(md5 기준, 2026-11-12 실측).
   - `skills/st/SKILL.md` d679731a…
   - `.codex/skills/st/SKILL.md` 4e78dfa0…
   - `~/.codex/skills/st/SKILL.md` efb73995…
   - `~/.claude/skills/strict/SKILL.md` a194c087…
2. **SOT가 존재하지 않는 정본을 가리킨다.**
   - `docs/sot/30-strict-mode-contract.md:3-4`는 정본을 `valuehire_v4`로, 설치기를 `tools/install-strict-skill.sh`로 지목한다.
   - 그런데 v4 origin/main(d273c088)에는 `install-strict-skill.sh`가 없다(`git ls-tree` 결과 0건).
   - SOT는 같은 줄에서 "v5 안에 사본을 두지 않는다"고 하지만, v5에는 `skills/st`와 `.codex/skills/st`가 있다.
3. **오래된 사본이 거짓 통제를 주장한다.**
   - `skills/st/SKILL.md:46-47`은 "`strict:gate`가 goal·verdict·skip 증가·L3 signoff·크기 제한을 막는다"고 쓴다.
   - SOT-30 §통제수준은 v5 strict:gate를 **planned(미구현)**로 둔다.
4. **종료 게이트가 판독 실패 시 PASS를 낸다.**
   - `scripts/harness/strict-exit-gate.py:41`: 경로가 없으면 조용히 생략한다.
   - `:44`: git rc≠0이면 생략한다.
   - `:49-50`: 예외가 나면 경고만 낸다.
   - 결과적으로 위 세 경우 모두 exit 0과 PASS로 끝난다.
5. **배포 경로가 손 복사다.**
   - 전역 사본은 레포 커밋과 연결된 기록이 없다. 그래서 무엇이 언제 어떤 커밋에서 설치됐는지 추적할 수 없다.
   - `tools/codex_skill_sync/sync.py:16-17`은 `strict→st` 별칭을 보존하려고 strict를 skip한다.
6. **테스트가 부재만 검사한다.**
   - `tests/test_strict_v5_port.py:50-52`는 옛 경로가 없는지만 본다. strict 진입점이 실제로 존재하는지(positive discovery)는 검사하지 않는다.

## GitOps 10원칙 매핑

| # | 원칙 | 우리 상황 | 현재 갭 (근거) | 판정 |
|---|---|---|---|---|
| 1 | Git = Single Source of Truth | 스킬 진입점이 v4·v5·`~/.claude`·`~/.codex` 4곳에 흩어져 있음 | 현재 상태 1·2 | **채택**: v5 `skills/strict`(Claude)와 `.codex/skills/strict`(Codex)를 유일한 정본으로 삼는다. 두 파일의 core 블록은 해시로 같음을 강제한다. SOT-30 정본 포인터를 v5로 옮긴다. |
| 2 | 자동 동기화(Argo CD) | 사람이 손으로 cp한다 | 현재 상태 5 | **부분 채택**: `tools/sync-strict-skill.sh` 러너를 만든다. 설치는 명시적으로 실행할 때만 한다. 자동 주기 동기화(cron·launchd)는 **보류**한다. 설치 권한을 오너 승인에 묶어 두기 위해서다. |
| 3 | App 코드와 배포 설정 레포 분리 | 단일 사용자, 단일 레포 | 레포를 나누면 SOT가 다시 둘이 된다 | **보류**: 레포 분리 비용이 이득보다 크다. 대신 경로를 분리한다(정본 `skills/strict`, 배포 대상은 전역 경로). |
| 4 | PR 승인 기반 Production 배포 | 설치 시점이 PR 전후와 무관함 | 전역 strict §7 "같은 PR에서 install 실행" | **채택**: 러너 `--install`은 `HEAD == origin/main`이고 대상 경로가 clean일 때만 허용한다. 즉 병합된 커밋에서만 설치된다. |
| 5 | Helm + Kustomize 환경 오버레이 | core와 레포 overlay가 개념상 분리돼 있음 | 엔진별(Claude/Codex) 차이가 사본 전체를 갈라놓음 | **채택(경량)**: 공유 core(`<!-- strict-core:begin/end -->`)와 엔진별 헤더로 나눈다. 레포 overlay는 SOT-30 표를 그대로 쓴다. |
| 6 | Secret을 Git에 평문 저장 금지 | `.env*`는 gitignore에 있음 | 스킬 문서에 비밀 취급 규칙이 없음 | **채택**: core §10에 "비밀은 커밋·로그·보고에 넣지 않는다. 증거에는 마스킹·해시만 남긴다"를 넣는다. |
| 7 | 자동 Rollback을 무조건 신뢰하지 않기 | 종료 게이트가 판독 실패를 PASS로 처리함 | 현재 상태 4 | **채택**: fail-closed로 바꾼다. 설치 전 백업을 남기고, 롤백 절차는 "revert PR → 병합 → 재설치"를 사람이 확인하는 방식으로 한다. |
| 8 | Drift Detection | 감지 수단이 없음 | 현재 상태 1 | **채택**: `--check`가 정본 해시와 설치본 해시를 대조한다. 남은 st 별칭도 보고한다. 드리프트가 있으면 exit 1. |
| 9 | 배포 관측성 | 설치 이력이 없음 | 현재 상태 5 | **채택**: 설치 시 `.strict-install.json`(commit, tree hash, 시각)을 남기고 설치 전후 해시를 출력한다. |
| 10 | ApplicationSet 멀티클러스터 | 대상은 2개(Claude·Codex 전역)와 다른 머신 | 머신 여러 대에서 쓰는 경우 | **부분 채택**: 러너가 엔진 2개를 한 번에 처리한다. 다른 머신은 `git pull` 후 같은 러너를 실행한다. 중앙 일괄 배포는 **보류**한다. |

## Codex 적대 리뷰 (2026-11-12, thread 01a1cd20-9b18-7060-b201-f59a4892e8a4) 원문 요약과 조치

| # | 심각도 | 지적 | 조치 |
|---|---|---|---|
| 1 | high | exit gate가 판독 실패 시 PASS를 낸다(strict-exit-gate.py:39-50). | fail-closed로 바꾼다. 마커 스키마를 검증하고 레포 동일성을 검사한다. 행위 테스트 6건을 추가한다. |
| 2 | high | SOT가 고정되지 않은 외부 정본(v4)에 의존한다. | 정본을 v5로 옮긴다. v4 사본은 "동결, 별도 제거 PR"로 명시한다. |
| 3 | high | 남은 st 사본이 거짓 통제를 약속한다(skills/st:46-47). | 가장 완전한 사본(R1~R8과 입력영역표가 있는 전역 strict)을 기준으로 합친다. 거짓 주장은 제거한다. |
| 4 | high | 설치가 승인된 릴리스에 묶여 있지 않다. | `--install`을 origin/main에서만 허용한다. 원자적으로 교체하고 백업을 남기며 설치 기록을 남긴다. |
| 5 | medium | 부재만 검사하는 테스트로는 st→strict 이행을 보호할 수 없다. | 양 엔진 positive discovery, core 패리티, 별칭 부재, 러너 거부와 설치 행위를 테스트한다. |

## 계약 (입출력)

- `scripts/harness/strict-exit-gate.py`: exit 0과 `PASS`는 아래 표의 "PASS" 행에서만 나온다. 나머지는 exit 1과 `FAIL`이다.
- `tools/sync-strict-skill.sh`
  - `--check`: 쓰기 0. stdout에 엔진별로 `OK|DRIFT|MISSING`, src/dest 해시, legacy 잔존 여부를 출력한다. 드리프트가 0이면 exit 0, 아니면 1.
  - `--install`: 조건이 맞지 않으면 exit 3으로 거부한다(쓰기 0). 조건이 맞으면 설치하고 전후 해시와 `.strict-install.json`을 남긴다.
  - 그 외 인자는 exit 2와 usage를 출력한다.
  - 설치 대상은 env `CLAUDE_HOME`(기본 `~/.claude`)과 `CODEX_HOME`(기본 `~/.codex`)이다.

### 입력영역표 — strict-exit-gate

| 입력 (마커 `.claude/strict-active.json`) | 처리 |
|---|---|
| 마커 없음 | PASS (strict 작업 없음) |
| 마커 정상 + 워크트리 clean + 같은 레포 | PASS |
| 마커 정상 + 워크트리에 미커밋 변경 | FAIL (기존 동작) |
| JSON 깨짐 / 최상위가 객체 아님 | FAIL |
| `slug`·`worktree` 누락 또는 빈 문자열/비문자열 | FAIL |
| worktree 경로가 존재하지 않거나 디렉터리가 아님 | FAIL |
| git rc≠0 (git 저장소 아님 등) | FAIL |
| git 타임아웃(`STRICT_EXIT_GATE_TIMEOUT`, 기본 15초) | FAIL |
| 워크트리의 git-common-dir가 이 레포와 다름 | FAIL |
| runner-lease 잔존 | 기존대로 WARN (판정에는 영향 없음) |
| 그 외 전부 (예상하지 못한 예외) | FAIL |

### 입력영역표 — sync-strict-skill.sh

| 입력 | 처리 |
|---|---|
| `--check`, 설치본 = 정본 | exit 0, OK |
| `--check`, 설치본 다름 / 없음 | exit 1, DRIFT/MISSING (쓰기 0) |
| `--check`, legacy(`~/.claude/commands/st.md`, `~/.codex/skills/st`) 잔존 | LEGACY 줄 출력. 그 자체로는 exit 1이다(드리프트로 간주). |
| `--install`, HEAD ≠ origin/main | exit 3 거부, 쓰기 0 |
| `--install`, 정본 경로에 미커밋 변경 | exit 3 거부, 쓰기 0 |
| `--install`, origin/main 참조 없음 | exit 3 거부 |
| `--install`, 조건 충족 | 대상마다 임시 디렉터리를 만든 뒤 원자적으로 rename한다. 기존 디렉터리는 `<home>/.strict-backups/<ts>/`로 옮긴다(skills/ 밖이라 스킬 로더가 백업을 중복 스킬로 읽지 않는다). 전후 해시와 `.strict-install.json`을 남긴다. |
| `--install --remove-legacy` | 위 설치 후 legacy를 백업 디렉터리로 옮긴다(삭제하지 않음). |
| 인자 없음 / 알 수 없는 인자 | exit 2, usage |
| 그 외 전부 | 명시적 실패(`set -euo pipefail`) |

## 예외표 (작업 수행)

| 상황 | 처리 |
|---|---|
| 기존 테스트가 st 경로를 기대함 | positive 검사로 갱신한다. assertion 삭제는 금지. |
| codex_skill_sync가 strict를 다른 이름으로 덮어씀 | ADAPTED_ALIASES 값을 `strict`로 바꾼다. 소유자를 sync-strict-skill.sh로 명시하고 skip은 유지한다. |
| 전역 경로 쓰기가 필요해짐 | 중단한다. 오너 승인 후 별도로 진행한다(이 PR 범위 밖). |
| v4 레포 사본 처리 | 범위 밖이다. "동결" 표기만 하고, 제거는 별도 PR로 남은 위험에 기록한다. |
| 그 외 전부 | 명시적으로 중단하고 이 표를 갱신한다. |

## 인수 기준 (EARS)

- WHEN `pytest tests/test_strict_unify.py tests/test_strict_v5_port.py tests/test_codex_skill_sync.py` runs, THEN 전부 통과한다. 그리고 RED 커밋에서는 새 행위 테스트가 실패해야 한다.
- 검증 명령: `./verify.sh` (exit 0).
- counter-AC: exit gate에 fail-open 코드를 되돌리는 mutant를 적용하면 새 테스트가 실패해야 한다.

## 롤백 절차

1. 이 PR을 revert하는 PR을 만들어 병합한다.
2. 병합된 origin/main에서 `tools/sync-strict-skill.sh --install`을 실행한다. revert 후에는 러너가 없으므로 3번으로 간다.
3. `<home>/.strict-backups/<ts>/strict`를 원래 이름으로 되돌린다(`mv`). 수동이며 사람이 확인한다.
4. `--check` 또는 해시 비교로 복원 상태를 확인한다.
- 영향 반경: 전역 strict 진입점 2개(Claude·Codex). 레포 런타임 코드에는 영향이 없다.

## 비범위

- v4 레포 사본 제거. 자동 주기 동기화. 레포 분리. 전역 경로 실제 설치(오너 승인 후).

## 적대 검증 로그

(구현 후 기록)

### G (구현자) 증거 — 2026-11-12
- RED(f57198d): `pytest tests/test_strict_unify.py` → 20 failed, 4 passed. 실패 사유는 전부 기대 동작 부재(exit 0 반환·파일 없음·러너 없음 rc 127). 문법 오류 0.
- GREEN: `pytest tests/test_strict_unify.py tests/test_strict_v5_port.py tests/test_codex_skill_sync.py` → 48 passed.
- `./verify.sh` → 3407 passed, 4 xfailed, 138 subtests passed, `verify: pytest exit=0`(기준선 3383 + 신규 24).
- mutation
  - 종료 게이트를 fail-open으로 되돌리는 mutant(JSON 판독 실패·타임아웃 → `[]`) → 2 failed(broken_marker_json, git_timeout). 원복 후 24 passed.
  - sync 러너 리비전 가드를 제거하는 mutant → `test_sync_install_refused_off_origin_main` failed. 원복 후 24 passed.
- 라이브 `--check`(쓰기 0, 실제 전역 경로) → exit 1.
  - claude: DRIFT(src 06f1cc3f… / dest 01620ffd…)
  - codex: MISSING
  - LEGACY 2건(`~/.claude/commands/st.md`, `~/.codex/skills/st`)
- 크기: 파일 10개, +약 500줄. 파일 5개·300줄 지향을 넘는다. 늘어난 분량의 대부분은 SKILL 문서 2개(core 블록이 두 진입점에 복제된 부분)다. 실행 코드는 exit gate +67줄, sync 러너 +110줄이다. 분할하지 않은 이유: st 제거, strict 생성, core 패리티 테스트가 한 원자 단위다. 나누면 중간 커밋에서 진입점이 0개가 된다.
