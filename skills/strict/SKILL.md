---
name: strict
description: 사장님(강상모) 표준 엄격 작업 모드 — Claude 진입점. goal prompting · "난 니 코드 안 믿어" 증거 강제 · Harness 게이트 · SOT 준수 · G→V1→V2 교차 적대검증 · GitOps 배포 위생을 한 번에 적용한다. st 별칭은 폐지되었고 strict로 통합됐다(2026-11-12) — "/st"·"/ST"·"$st"는 이제 이 스킬의 트리거 단어일 뿐 별도 스킬·커맨드가 없다. 트리거 — "엄격", "엄격하게", "빡세게", "제대로 검증", "goal로 해", "goal prompting", "코드 안 믿어", "harness로", "/strict", "/st", "/ST", "엄격모드", "적대 검증", "적대적 검증". 코드 변경뿐 아니라 리서치·분석·기획 검증 요청에도 발동.
---

# strict — 엄격 작업 모드 (Claude)

## Claude 엔진 헤더 (core 밖 — 엔진별 차이는 여기에만 둔다)

- **발동 즉시 첫 줄**: "**엄격 모드(strict)** — 모드 `code-change|noncode|mixed` · 등급 `L0~L3` · 격리 워크트리 + 게이트 + G→V1→V2 교차 적대검증으로 진행합니다." + 등급 판정 이유 1줄.
- **V1 방법(Claude → Codex)**: `/codex:adversarial-review --fresh`(read-only). 결과 본문과 thread id를 goal 적대 검증 로그에 남긴다. 쓰기 권한 있는 rescue 호출로 대체하지 않는다.
- **Stop 훅**: 레포가 `.claude/hooks/stop-evidence-gate.py`를 배선했으면 미커밋 잔존·스펙 내 확인 질문으로 끝나는 턴을 1턴 저지한다(hook). 배선이 없는 레포에서는 §6 종료 게이트를 직접 실행한다.

<!-- strict-core:begin -->
## 공통 core (Claude·Codex 동일 — 이 블록은 두 엔진 진입점에서 바이트 단위로 같아야 한다. 테스트: tests/test_strict_unify.py)

> 정본 = 이 레포(ValueHire v5)의 `skills/strict/SKILL.md`(Claude)·`.codex/skills/strict/SKILL.md`(Codex) + `docs/sot/30-strict-mode-contract.md`(overlay). 레포 SOT가 이 스킬과 다르게 말하면 SOT가 이긴다. 다른 레포에서는 이 core만 적용하고 그 레포 규칙 문서를 overlay로 삼는다.
> 규칙마다 통제 수준(policy | runner | hook | planned)이 다르다. **planned(미구현) 통제를 구현된 것처럼 말하지 않는다.**

### 1. 위험 등급 (L0~L3 단일 모델)

| 등급 | 해당 | 요구 검증 |
|---|---|---|
| L0 | 사소한 수정·단순 답변 | 자체 점검. code면 워크트리는 그래도 필수 |
| L1 | 분석·조언·리서치 | 주장-근거 매핑 + 반례 1회 + 출처 |
| L2 | 일반 코드 변경 | RED→GREEN + verify 실행 + 배선 증명 + V1 판정 |
| L3 | 인증·PII·과금·외부 발송·마이그레이션·파괴·배포·SOT 수정 | 풀하네스: G→V1→V2 + verdict.json + 테스트 약화/mutation 검사 + owner signoff |

"그냥 빨리"라고 명시 면제하면 L0. 보안·돈·외부 발송·되돌리기 어려움이 걸리면 무조건 L3.

### 2. 워크트리 강제 (code-change 전 등급)

소스를 바꾸는 모든 작업은 격리 워크트리에서만 한다. 레포 규약 러너가 있으면 그것만 쓴다(v5 overlay: `make task NAME=<slug>` — SOT-30 표). 없으면 `git worktree add`. git 밖이면 "워크트리 미적용 — git 밖"이라고 보고한다. 메인 작업트리 직접 수정 = 게이트 위반 — 발견 즉시 워크트리로 옮겨 처음부터 다시 탄다. 사용자 변경을 되돌리지 않는다. strict 마커(`.claude/strict-active.json`)는 러너가 소유한다 — 손으로 만들거나 몰래 지우지 않는다.

### 3. goal prompting (L1+)

코드 전에 `docs/engineering/<주제>-goal-<YYYY-MM-DD>.md`: 현재 상태(file:line, 추측 금지) · 근본 원인 · 인수 기준(EARS + 검증 명령 + counter-AC, 1개 단위) · 계약(입출력 모양 먼저) · 게이트 계획 · 적대검증 정조준 · 비범위 · `## 적대 검증 로그`(후기록). L3는 롤백 절차 + 영향 반경 추가.

**결정성 규율(입력 영역 표) — L2 이상 code-change는 구현 전 4단계 의무 (policy):**
- ① **입력 영역 표**: 명시 인자 + 암묵 입력(DB 상태·설정·flag·시계·동시 실행)을 정의하고 정상/빈값·null/경계/형식위반/중복·재시도/외부장애 행을 열거, 각 행에 "처리" 또는 "명시적 거부", 마지막 행은 **"그 외 전부 → 명시적 거부"**. 표 밖 입력의 의미 추정·조용한 fallback 금지.
- ② **결정 목록**: 애매한 결정(동일성 기준·경계 포함·에러 정책·순서)을 열거해 오너 확정. 확정 없는 결정을 코드에 넣지 않는다.
- ③ **표↔테스트 대응**: 표 각 행 = 테스트 1개 이상.
- ④ **스펙 공격**: "완전하다" 선언 금지. V1은 표·결정 자체를 공격한다.

### 4. 강화 v2 — R1~R8

- **R1** 분해→스펙→**예외 케이스 표**(각 행 "자동 처리" 또는 "명시적 중단+사유", 마지막 행 "그 외 전부 → 명시적 중단"). 표에 없는 상황 = 중단+표 갱신 후 재개.
- **R2 질문 금지**: 스펙·SOT·예외표에 답이 있는 것을 되묻지 않는다. 허용은 2FA·캡차·본인확인 / 파괴적·비가역 / 표 밖 신규 상황의 중단 보고뿐.
- **R3** 손 조작은 레포 러너가, 판단은 모델이. 위험 입력은 전송 전 **read-back** 대조(불일치 = 진행 금지+기록).
- **R4 재발 원장**: 착수 시 원장(있으면 `docs/sot/31-strict-recurrence-ledger.md`)을 읽고 관련 행을 goal에 인용. 같은 지적 2회째 = 승격(러너/훅) 작업 즉시 발행.
- **R5 단위 관문**: 단위 N 검증 통과 전 N+1 착수 금지.
- **R6** 실패 신고 1건 = 원장 1행 = 회귀 케이스 1건.
- **R7** 같은 작업 정정 2회 = 세션 리셋(리셋 전 원장·goal 기록).
- **R8** 위임 4칸 템플릿(목표/반환 형식/쓸 도구/하지 말 것) · 실제 돌리지 않은 검증 언급 금지 · 6~8회 호출마다 진행 보고.

### 5. "난 니 코드 안 믿어" — 증거 없는 완료 금지

- 완료 ≠ 테스트 초록불. 완료 = 프로덕션 배선 + 라이브 1건 실증.
- "고쳤습니다/should/probably" 금지. fresh 증거(명령 + 출력 숫자 그대로, 화면이면 캡처)만.
- **배선 증명(L2+)**: 엔트리포인트→새 코드 호출 경로 첨부. 동적 패턴은 런타임 추적. "테스트가 직접 import해서 통과"는 배선 아님.
- RED는 올바른 이유로 실패해야 한다(문법 오류가 아니라 기대 동작 결여).
- 테스트 약화(skip/only/todo 증가·assertion 제거·테스트 삭제)로 GREEN 만들기 = 항상 위반. L3는 mutation 증거(수동 mutant 1개: 적용→실패 확인→복원).

### 6. 게이트

0 시작자격(v5: `make red-ledger`) + 과거 회수 → 1 스펙(EARS AC 1개) → 2 워크트리 + RED 먼저 커밋 → 3 최소 변경(파일 1~5 / diff 50~300줄 지향, 초과 시 분할 보고) → 4 검증(v5: `./verify.sh` exit 0 출력 그대로) + 라이브 1건 → 5 push→PR→CI 초록, merge 전 완료 없음 → 6 merge 후 정리.
레포에 `strict:gate`류 검사기가 있으면 실행하되, 그것이 **실제로 무엇을 검사하는지**만 주장한다(존재·배선·마커 검사기는 goal·verdict·signoff·diff 크기를 검사하지 않는다 — 그 항목은 planned).
**종료 게이트**: Stop 훅이 없는 실행기(Codex 등)는 마지막 단계에서 `make strict-exit-gate`를 의무 실행하고, exit 0 + PASS가 없으면 "완료"라고 말하지 않는다. 이 게이트는 fail-closed다 — 마커 판독 불가·워크트리 없음·다른 레포·git 실패·타임아웃은 전부 FAIL.

### 7. 교차 적대검증 G→V1→V2 (L3 필수, L2는 V1까지)

- **V1**: 다른 엔진의 **fresh 세션 + read-only** 적대 리뷰(엔진별 방법은 이 파일 상단 헤더). 산출물(코드+AC+증거)만 전달, 추론 과정 비전달. "Done만/빈 결과"는 무효 — 판정 본문 + 반증 시도 + transcript/thread id 확보.
- **V2**: 리셋 컨텍스트가 goal + verdict.json만 읽고 V1 판정 자체를 재공격(V1 증거 격리 재현, PASS면 "놓친 고아 없나", FAIL이면 "과장 아닌가"). 갈리면 결론 내지 않는다.
- 판정은 `<slug>.verdict.json`(generator/v1/v2/failed_attempts/three_way_agree/status + command/exit_code/artifact/hash). goal `## 적대 검증 로그`에 본문 append. 실패 시 감 재시도 금지 — 원인 회수 후 `failed_attempts[]` 누적.

### 8. L3 승인

- owner signoff 없이는 로컬 분석·수정·테스트·dry-run까지만.
- 사업 오너의 **현재 턴** 명시 명령("보내/발송/등록/게시/실행")은 signoff다 — 대상·채널·횟수·검증 근거를 확인한 뒤 실행한다. 불명확한 구체 항목만 묻는다.
- L3 승인 산출물: 대상/채널/횟수/payload hash/일회성 nonce. `OWNER_SIGNOFF=true` 같은 상주 env만으로는 승인이 아니다.
- L3 자동화는 "절대 발생하면 안 되는 결과" 1개를 먼저 정의하고 그것을 막는 기계 통제(가드·러너)의 증거를 남긴다.

### 9. SOT 준수 + 승격

- 구현 전 레포 SOT(`docs/sot/*`, CLAUDE.md/AGENTS.md, Makefile, package.json)를 실제로 읽고 경로를 보고한다. 검증 명령은 추측하지 말고 파일 존재로 확인한다.
- 동작 변경이 SOT 서술을 바꾸면 같은 PR에 SOT diff 동봉.
- 같은 지적 2회 = 통제 승격(문서 H2 → 러너 H3 → 훅 H4) 검토 보고. 훅에 차단되면 방법이 틀린 것 — 안내된 정식 러너로 재라우팅해 완주.
- 스킬 자체를 다루면 skill-creator 기준을 먼저 적용한다.

### 10. 배포 위생 (GitOps — 2026-11-12 채택)

- **Single Source of Truth**: strict 진입점의 정본은 이 레포 한 곳. 전역 사본(`~/.claude/skills/strict`, `~/.codex/skills/strict`)은 배포 산출물이다 — 전역에서 직접 고치지 않는다.
- **PR 승인 기반 배포**: 진입점 변경은 PR→병합 후 `tools/sync-strict-skill.sh --install`로만 설치한다(러너가 `HEAD == origin/main`이 아니면 거부). 같은 PR 안에서 전역 설치 금지.
- **드리프트 감지**: `tools/sync-strict-skill.sh --check`로 정본↔설치본 해시를 대조한다(쓰기 0). 드리프트를 손으로 덮지 말고 원인을 회수한다.
- **관측성**: 설치 기록(`.strict-install.json`: commit·hash·시각)과 설치 전후 해시를 증거로 남긴다.
- **자동 롤백 불신**: 롤백 = revert PR 병합 → 재설치 → `--check`로 확인. 백업(`<home>/.strict-backups/`)은 사람이 확인하고 복원한다.
- **Secret**: 비밀(토큰·쿠키·비밀번호·.env)은 커밋·로그·보고·증거에 평문으로 넣지 않는다 — 마스킹 또는 해시만.

### 11. 마무리 체크 (해당 등급 전부 ✅ 아니면 "진행 중")

- [ ] 모드+등급 첫 줄 선언 · goal 경로 · 읽은 SOT 경로 · 과거 회수 인용
- [ ] (code) 워크트리 경로·브랜치, 메인 직접 수정 0건
- [ ] (L2+) RED→GREEN 증거 · verify exit 0 출력 그대로 · 배선 증명 · 라이브 1건 · 크기 초과 시 분할
- [ ] (L2+) V1 판정 본문(fresh·read-only, thread/agent id) · (L3) V2 + verdict.json
- [ ] (L3 운영 write) target/channel/count/payload hash/nonce
- [ ] (UI) 실제 화면 캡처 · (noncode) 주장-근거 매핑 + 반례 + 출처
- [ ] (진입점 수정 시) 병합 후 sync `--install` → `--check` 드리프트 0
- [ ] 보고: 쉬운 한국어 존칭, 무엇을/왜/증거/다음, 약어 첫 사용 시 풀이. 요청 없으면 JSON 보고 강제 안 함.
<!-- strict-core:end -->
