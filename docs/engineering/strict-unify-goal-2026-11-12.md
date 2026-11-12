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
| 레포 판독(`CLAUDE_PROJECT_DIR`/cwd → git-common-dir) 실패 — 레포 밖 실행 등 (V1 2차 #1) | FAIL |
| 마커 위치: 이 레포의 **모든 체크아웃**(`git worktree list`)의 `.claude/strict-active.json` — task.sh 는 실행된 체크아웃에 마커를 쓰므로 (V1#1, 2차 #2) | 마커마다 검사 |
| worktree 목록 판독 실패 | FAIL |
| 마커 lstat 이 FileNotFoundError 외 오류(접근 거부 등) (V1 2차 #1) | FAIL |
| 마커 없음 (lexists 거짓) | PASS (strict 작업 없음) |
| 마커가 심링크(깨진 링크 포함)·디렉터리 등 일반 파일 아님 (V1#5) | FAIL |
| 마커 정상 + 워크트리 clean + 같은 레포 | PASS |
| 마커 정상 + 워크트리에 미커밋 변경 | FAIL (기존 동작) |
| JSON 깨짐 / 최상위가 객체 아님 | FAIL |
| `slug`·`worktree` 누락 또는 빈 문자열/비문자열 | FAIL |
| worktree 경로가 존재하지 않거나 디렉터리가 아님 | FAIL |
| git rc≠0 (git 저장소 아님 등) | FAIL |
| git 타임아웃(`STRICT_EXIT_GATE_TIMEOUT`, 기본 15초) | FAIL |
| 워크트리의 git-common-dir가 이 레포와 다름 | FAIL |
| runner-lease 잔존 | 기존대로 WARN (판정에는 영향 없음) |
| 레포 자체 판독 실패/타임아웃 | FAIL (main 바깥 catch-all) |
| 그 외 전부 (예상하지 못한 예외) | FAIL |

### 입력영역표 — sync-strict-skill.sh

| 입력 | 처리 |
|---|---|
| `--check`, 설치본 = 정본 | exit 0, OK |
| `--check`, 설치본 다름 / 없음 | exit 1, DRIFT/MISSING (쓰기 0) |
| `--check`, legacy(`~/.claude/commands/st.md`, `~/.codex/skills/st`) 잔존 | LEGACY 줄 출력. 그 자체로는 exit 1이다(드리프트로 간주). |
| `--install`, HEAD ≠ origin/main | exit 3 거부, 쓰기 0 |
| `--install`, 정본 경로 **추적 파일**에 미커밋 수정 | exit 3 거부, 쓰기 0 |
| 정본 경로에 untracked·ignored 파일(.env 등) (V1#2) | 거부하지 않음 — 설치 내용은 **HEAD 커밋 객체에서 `git archive`**로만 꺼내므로 혼입 0 |
| 해시 도구 실패·빈/형식 이상 해시 (V1#4) | exit 4, 비교하지 않음 |
| 다른 설치 진행 중(락 `$CLAUDE_HOME/.strict-sync.lock` 존재) (V1#3) | exit 3 거부, 쓰기 0 |
| 두 번째 대상 준비(스테이징) 실패 (V1#3) | exit 5, **두 대상 모두 무변경**(교체는 둘 다 준비된 뒤에만), 스테이징·락 정리 |
| 교체(mv) 중 실패 | exit 5, 이미 교체한 대상을 백업에서 복원 |
| 복원 자체 실패 (V1 2차 #3) | 다른 엔진 복원은 계속, exit 6 + 미복원 대상·백업 위치 stderr 명시 |
| 교체 중 TERM/INT/HUP 신호 (V1 2차 #3) | trap → 전체 복원, exit 7 (kill -9 는 잡을 수 없음 — 백업은 남음) |
| 준비 단계 해시 실패 (V1 2차 #4) | 현재 셸에서 검증(`hash_of`) → exit 4, 교체 전 중단 |
| 연속 재설치 | 백업 id = UTC초-pid-random — 충돌 없음 |
| `--install`, origin/main 참조 없음 | exit 3 거부 |
| `--install`, 조건 충족 | 두 대상을 스테이징·해시 검증한 뒤 순서대로 rename한다(엔진 간 진정한 원자성은 불가 — 실패 시 복원으로 보완). 기존 디렉터리는 `<home>/.strict-backups/<ts>/`로 옮긴다(skills/ 밖이라 스킬 로더가 백업을 중복 스킬로 읽지 않는다). 전후 해시와 `.strict-install.json`을 남긴다. |
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

### V1 1차 (Codex, fresh read-only, thread 01a1cd2b-61e6-7ec2-bc3c-9d0912877503, 리뷰 대상 1557a48) — VERDICT FAIL
1. [high] 워크트리에서 실행하면 메인 체크아웃의 마커를 못 찾고 PASS를 낸다(strict-exit-gate.py:87-94).
2. [high] 설치가 커밋 밖의 내용(ignored·숨은 untracked)을 복사한다(sync:76-87).
3. [high] 교체가 원자적이지 않고 실패 시 복구가 없다. 엔진 간 부분 설치, 락 없음, 백업 이름 충돌(sync:83-95).
4. [high] 해시 실패 시 빈 해시끼리 같다고 보고 OK와 드리프트 0을 낸다(sync:52-55). Codex가 재현함.
5. [medium] 깨진 심링크 마커를 "마커 없음"으로 보고 PASS를 낸다(gate:92-96).

**조치** — RED 925ddf3: 7 failed, 26 passed. 이후 수정:
- 마커 위치를 git-common-dir 기준으로 찾는다.
- 마커가 lexists인데 일반 파일이 아니면 FAIL로 처리한다.
- main 바깥에 catch-all을 둔다.
- 설치 내용을 `git archive HEAD`로 꺼낸다.
- 락을 건다.
- 두 대상을 모두 스테이징한 뒤에 교체하고, 실패하면 복원한다.
- 백업 id를 초-pid-random으로 만든다.
- 해시 실패와 형식 이상은 exit 4로 처리한다.

**결과**
- 관련 테스트 57 passed.
- `./verify.sh` 3416 passed, 4 xfailed, `pytest exit=0`.
- mutant 2개를 추가로 확인했다. 해시 검증 제거 → hash_tool 테스트 failed. archive 대신 작업트리 복사 → commit_content 테스트 failed. 둘 다 원복 후 33 passed.
- 남은 한계: 엔진 간 진정한 원자적 교체는 불가하다. 디렉터리 rename 두 번 사이에 프로세스가 강제 종료(kill -9)되면 복원 코드가 돌지 못한다. 이 경우 백업은 남는다.

### V1 2차 (Codex, fresh read-only, thread 01a1cd32-03ff-7460-be4b-f373c8e03970, 리뷰 대상 a1aa9f7) — VERDICT FAIL
1. [high] 레포 판독 실패(CLAUDE_PROJECT_DIR=/tmp)·마커 접근 거부 → PASS. Codex가 재현함.
2. [high] 연결 체크아웃에서 task.sh로 만든 마커를 건너뛴다. task.sh는 마커를 자기가 실행된 체크아웃에 쓴다.
3. [high] 두 번째 엔진 복원이 실패하면 set -e 때문에 첫 엔진 복원이 중단된다. SIGTERM 시 부분 설치 상태가 남는다.
4. [medium] 준비 단계에서 해시가 실패해도 빈 해시끼리 비교해 통과한다(명령 치환 안의 exit).
5. [medium] 이전 Codex 사본에 있던 L3 "TTY 직접 확인" 요건이 통합 core에서 빠졌다.

**조치**
- RED 7ab86b8: 8 failed, 33 passed.
- 수정 내용
  - 레포 판독 실패 → GateError FAIL.
  - lstat에서 FileNotFoundError만 부재로 인정한다.
  - 모든 체크아웃(`git worktree list`)에서 마커를 찾는다. 실제 task.sh로 통합 테스트했다.
  - 교체 구간은 errexit를 끄고 단계마다 직접 검사한다. 복원 실패를 모아 두고 다른 엔진 복원은 계속한다(exit 6). 신호 trap이 오면 전체를 복원한다(exit 7).
  - 해시는 `hash_of`로 현재 셸에서 검증한다.
  - TTY 직접 확인을 복원했다.
  - 추가로 직접 대조해 core에서 빠진 이전 통제 5개를 찾아 복원하고 테스트로 고정했다: snapshot 무근거 갱신 금지, 기존 구현 재사용 우선, quick_validate, 분석 작업의 답변 스키마, 호출그래프 끝까지 추적.
- mutant 2개
  - 복원 실패 시 즉시 exit → restore_failure 테스트 failed.
  - lstat OSError를 부재로 처리 → access_denied 테스트 failed.
  - 둘 다 원복했다.
- 결과: 관련 66 passed. `./verify.sh` 3425 passed, 4 xfailed, `pytest exit=0`.
- 실제 환경 영향 점검: v5 체크아웃 16개 중 마커가 있는 곳은 0개다. 모든 체크아웃으로 탐색을 넓혀도 당장 오탐 FAIL은 없다.
