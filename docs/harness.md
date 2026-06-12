# Harness — 표준 작업 루프

> **목적은 단 하나: 출력의 변동성을 줄여 재현 가능하게 만든다.**
> 같은 입력에 같은 품질이 나오도록, 모든 변경을 게이트로 통과시킨다.
> 리포에 무엇이든 추가/변경하는 작업(코드·**스킬·문서·배관**)은 이 절차를 따른다.
> 각 단계는 게이트가 있고, 통과 못 하면 다음으로 가지 않는다. 단계를 건너뛰지 않는다.

배관은 `Makefile` + `verify.sh` + `scripts/harness/*` + pre-push 훅 + `.github/workflows/verify.yml`로
이 레포에 구현돼 있다. 최초 1회: `make install-hooks`. 러너: `requirements-dev.txt` 또는 `.venv-playwright`.

## 0 — 시작 자격 (게이트)
- `make red-ledger` 실행. 미해결 RED(=`.harness/red-ledger.tsv`의 RED 행 또는 현재 `verify` 실패)가 있으면
  새 작업을 시작하지 않는다. 그것부터 닫는다.
- 깨끗한 컨텍스트인지 확인(아니면 /clear).

## 1 — 스펙(이슈)
- GitHub 이슈를 만든다(`gh issue create`). 반드시 **인수 기준**: "무엇이 참이면 끝났는가."
- 인수 기준은 두 종류로 나눠 적는다 (게이트 4에서 각각 판정):
  - **기계 단언** — `./verify.sh`로 검사 가능한 것(테스트·구조·참조 존재). 가능한 한 여기로.
  - **판단 단언** — 기계로 못 재는 품질(논증의 타당성, 지시문의 명료성, 과장 없음). 게이트 4b 독립 검증자가 판정.
- 기계 단언 하나로 못 적으면 너무 크다 → 쪼개서 별도 이슈로.

## 2 — RED 먼저 (worktree)
- **main은 읽기 전용.** 코드든 스킬이든 문서든, 모든 변경은 `make task NAME=...` 로 worktree에서 시작한다
  (브랜치 `task/<slug>`, 격리 작업트리 `../Valuehire_v5-<slug>`, ledger에 RED 등록).
  worktree는 격리·병렬·깔끔한 롤백을 준다. 안 쓰면 변경 없이 자동 정리된다.
- 인수 기준을 **실패하는 검사**로 먼저 만들어 커밋(RED 확인). 아티팩트 유형별 "RED"는 아래 표.
  이 검사를 GREEN으로 만드는 것 외엔 손대지 않는다.

| 아티팩트 | 인수 기준(예) | RED 증명 | verify 단언(게이트 4a) |
|---|---|---|---|
| **코드** | 동작이 참 | 실패하는 pytest | `./verify.sh` exit 0 |
| **스킬**(SKILL.md) | 트리거에 뜨고 절차 산출물이 규격대로 | 계약검사 실패(frontmatter·트리거·참조경로 부재) | 스킬 계약 테스트 GREEN |
| **문서**(HTML/MD) | 구조·근거가 참 | 구조/참조검사 실패 | 깨진 태그 0·근거 코드경로 실존·끊긴 앵커 0 |
| **배관**(make/hook/CI) | 명령이 그 동작을 함 | 명령 부재 스모크 실패 | 스모크 exit 0 + 멱등 |

## 3 — 구현
- RED→GREEN 최소 변경만. 규모 목표 파일 1~5 / diff 50~300줄.
- 작업 중 새 문제 → 고치지 말고 새 이슈로 분리(+ `.harness/red-ledger.tsv`에 RED 추가).
- **자기확장 규칙: 새 대상을 추가하면 그 대상의 verify 단언 + 픽스처를 같은 커밋에 추가한다.**
  - 새 캡처 사이트(사람인·잡코리아·LinkedIn·ChatGPT 등) → 그 사이트 verify 단언 + 픽스처.
  - 새 스킬 → 그 스킬 계약 테스트.  새 근거-인용 문서 → 그 문서 참조-존재 테스트.

## 4 — 검증 (두 게이트)
- **4a · 기계 판정.** `./verify.sh` 실행, 출력 숫자(`N passed, M failed`)를 그대로 붙인다.
  exit 0 아니면 "진행 중". "고쳤습니다/재로드하세요" 금지. **멈추지 않는다.**
- **4b · 독립 검증자 (Generate-Verify).** 판단 단언이 있는 작업(문서·스킬·프롬프트)은
  **생성자와 분리된** 검증자가 판정한다. 검증자는 "통과"가 아니라 **반증**을 임무로 한다:
  주장이 실제 코드/사실과 맞는가? 과장·환각 경로는 없는가? 인수 기준을 정말 만족하는가?
  서브에이전트로 띄우거나(병렬 다중 렌즈: 사실성·구조·논증), 별 세션에서 재검토한다. 반증 못 깨면 통과.
- 두 게이트 GREEN이면 `.harness/red-ledger.tsv`의 해당 행을 RED→GREEN으로(또는 제거).

## 5 — 배송
- `make ship`(verify 재실행 → push → PR). `main`에서는 ship 거부(`make task`로 브랜치부터).
  pre-push 훅 + CI(`verify.yml`)가 verify를 재실행한다.
- PR 본문: 이슈 링크 + 증명 테스트(기계) + 검증자 판정(판단) + verify 출력.
- CI 초록 + merge 전까지 "완료"는 없다.

## 6 — 종료 + 진화
- merge 후 worktree 정리(`git worktree remove`) + /clear. 다음 작업은 게이트 0부터.
- **진화(escaped-defect 환류).** 게이트를 통과했는데 나중에 결함이 새어나왔다면,
  그 결함을 잡는 **검사를 먼저 추가**(RED)한 뒤 고친다. 하니스는 실패에서 자란다 —
  이론이 아니라 운영에서 검증된 단언만 쌓인다. 반복되는 4b 지적은 4a 기계검사로 승격한다.

---
### 배관 명령 요약
| 명령 | 게이트 | 동작 |
|---|---|---|
| `make red-ledger` | 0 | 미해결 RED 점검 (있으면 비-0) |
| `make task NAME=x` | 2 | worktree 생성 + ledger RED 등록 (모든 아티팩트 공통) |
| `make verify` / `./verify.sh` | 4a | 테스트 전체, exit 0 == GREEN |
| (독립 검증자) | 4b | 생성자와 분리된 반증 검토 — 판단 단언 판정 |
| `make ship` | 5 | verify → push → PR (main 거부) |
| `make install-hooks` | — | pre-push 훅 설치 (최초 1회) |

### 설계 메모
- **단일 verify 게이트 원칙**: 아티팩트 유형이 늘어도 게이트를 늘리지 않는다.
  스킬·문서의 기계 단언도 같은 `./verify.sh`(pytest) 안에 계약 테스트로 얹는다.
- **변동성을 시간에 분산**: 게이트 4b/진화는 변동성을 한 번에 없애려 하지 않는다 —
  반복 검토와 환류로 평균을 끌어올린다. (cf. `docs/ai-search/` 저수지 모델과 같은 원리.)
- 출처: 게이트 4b(Generate-Verify)·게이트 6 진화는 revfactory/harness의 품질 게이트·진화
  메커니즘을 이 RED/verify/worktree 루프에 이식한 것.

### 미해결 RED
- 현재 미해결 RED는 `make red-ledger`로 확인한다 (하드코딩하지 않는다 — 또 옛 정보가 된다).
- 이력: `profile-recovery-proof`(시한폭탄 테스트)·`reservoir-doc-harden`(PR#2)은 GREEN으로 닫힘.
