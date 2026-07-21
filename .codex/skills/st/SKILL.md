---
name: st
description: "Strict Codex execution mode. Use when the user invokes $st, asks for 엄격 모드(codex), strict mode, 레포 SOT/goal spec/test/wiring/adversarial verification, or wants a task handled only after evidence-backed validation. Applies to code-change, noncode, and mixed tasks; classifies security, money, production writes, external sending, deployment, and destructive actions as L3, and treats the owner’s explicit current-turn command such as 보내/발송/등록/게시 as approval after evidence-backed validation."
---

# $st — 엄격 모드(codex) · 정본 계약 SOT-30 어댑터

Treat the rest of the user's message after `$st` as the task.

엄격 모드(codex)로 진행해. **정본 계약은 레포의 `docs/sot/30-strict-mode-contract.md`다** — 있으면 그 문서(core+overlay)가 이 스킬보다 우선하고, 없는 레포에서는 아래 core 규칙만 적용한다. Claude `/strict`·`/st`와 이 스킬이 다르게 말하면 SOT-30이 이긴다.

목표:
- 아래 작업을 끝까지 구현/검증한다.
- 완료라고 말하기 전에 레포 SOT, 테스트, 배선, 적대검증 증거를 확보한다.
- 권한/로그인/운영 write/외부 발송/배포/파괴 작업은 L3로 분류한다. 단, 사업 오너가 현재 턴에서 명시적으로 "보내", "발송", "등록", "게시", "실행"처럼 실행을 지시한 경우에는 그 문장을 owner signoff로 간주하고, 대상·수신자·내용·횟수·기존 배선 검증 후 실행한다.

진행 규칙:
1. 첫 줄에 산출물 모드와 위험등급을 선언한다.
   - 산출물 모드: code-change | noncode | mixed
   - 위험등급: L0 저위험, L1 근거형 비코드, L2 일반 코드/중간 위험, L3 보안·데이터 손상·마이그레이션·릴리스·외부 발송·되돌리기 어려운 작업
   - 보안/돈/운영 write/외부 발송/파괴 작업은 항상 L3

2. 구현 전에 현재 레포의 SOT를 찾아서 실제로 읽고, 읽은 경로를 보고한다.
   - 있는 것만 읽는다: CLAUDE.md, AGENTS.md, README*, CONTRIBUTING*, docs/README.md, docs/sot/**, harness 문서, package.json, Makefile, pyproject.toml
   - 검증 명령은 추측하지 말고 실제 파일/스크립트 존재로 확인한다.
   - `docs/sot/30-strict-mode-contract.md`(strict 정본)와 `docs/sot/19-harness-loop.md`(게이트 원본)가 있으면 이 스킬 문구보다 우선한다.

3. L1 이상이면 먼저 goal/계약 스펙을 남긴다.
   - 가능하면 docs/engineering/<slug>-goal-<YYYY-MM-DD>.md 생성
   - 포함: 현재 상태 증거(file:line), 근본 원인, 인수 기준, 비범위, 검증 명령, SOT 체크리스트
   - code 작업이면 입력/출력 shape, 필드, 타입, 함수/API 시그니처, 상태 전이를 명시한다.
   - analysis/research 작업이면 최종 답변 스키마와 주장별 근거·반례·한계를 명시한다.
   - **결정성 규율(입력 영역 표)** — L2 이상 code-change는 구현 전 4단계 의무(SOT-30 §1-11, 통제 수준 policy):
     ① 입력 영역 표: "무엇이 입력인가"부터 정의(명시 인자 + 암묵 입력: DB 상태·설정·flag·시계·동시 실행) 후 전체를 표로 열거(정상/빈값·null/경계/형식위반/중복·재시도/외부장애, 해당 시 시간·동시성·스트리밍/부분·버전 축 추가), 각 행에 "처리" 또는 "명시적 거부(fail-fast)" 지정, 마지막 행은 "그 외 전부 → 명시적 거부"(catch-all). 금지 대상 = 표 밖 입력의 의미 추정·정상화·조용한 fallback(과잉 방어 금지) — fail-fast 안전장치(스키마 검증·deny-by-default·unknown throw)는 catch-all 행의 구현으로 허용.
     ② 결정 목록: 애매한 결정(동일성 기준·경계 포함·에러 정책·순서 보장)을 열거해 오너 확정. 확정 없는 결정을 코드에 임의 삽입 금지.
     ③ 표↔테스트 대응: 표 각 행 = 테스트 1개 이상. 파서·정규화는 실입력 픽스처 먼저 수집.
     ④ 스펙 공격: "완전하다" 선언 금지. V1 적대검증은 구현만이 아니라 표·결정 자체를 공격한다("표에 없는 현실 입력이 존재하는가?").

4. L2 이상이면 변경 전에 worktree 상태를 확인한다.
   - 레포에 워크트리 러너가 있으면 그것만 쓴다(ValueHire: `npm run wt -- <issue>-<slug>`). 없으면 `git worktree add`.
   - git repo 밖이면 "워크트리 미적용 - 대상 경로가 git repo 밖"이라고 보고한다.
   - 사용자 변경을 되돌리지 않는다.
   - 기존 구현을 먼저 rg로 찾고, 새로 만들기보다 재사용/연결/보강을 우선한다.
   - 테스트를 약화하거나 삭제하지 않는다.

5. 구현은 RED -> GREEN으로 한다.
   - 가능한 경우 실패하는 focused test 또는 재현 명령을 먼저 확보한다.
   - 최소 변경으로 통과시킨다.
   - 프로덕션 호출 경로에 실제로 배선됐는지 grep/코드 추적으로 확인한다.
   - "참조 있음"만으로 정상 판정하지 말고 호출그래프 끝까지 본다.

6. 검증은 실제 명령 출력으로 한다.
   - package.json에 `strict:gate`가 있으면 먼저 실행한다. 이 gate는 **존재·배선·마커 검사기**다(필수 npm scripts 배선, 필수 SOT/하네스 파일, 내용 마커). goal 문서·verdict.json·test skip/only/todo·L3 signoff·diff 크기는 검사하지 않는다 — 그 항목들은 아직 planned(SOT-30 §4)이므로 스스로 점검하고, 기계가 검사한다고 주장하지 않는다.
   - focused test 우선
   - 그 다음 lint/typecheck/build/verify 중 레포에 실제 존재하는 명령
   - 출력과 exit code를 읽고, 실패하면 원인/재현/다음 수정 방향을 goal 문서나 보고에 남긴다.

7. L2 이상은 적대검증을 한다.
   - 가능하면 다음 형태로 다른 엔진 검증을 실행한다:
     env -u ANTHROPIC_API_KEY claude -p "<작업과 diff를 적대적으로 검토해. 가짜 완료, 미배선, 테스트 약화, 누락된 edge case, 과장된 완료 주장을 찾아라. VERDICT: PASS|FAIL 로 시작하고 file:line 근거를 포함해라.>"
   - claude가 없거나 실행 불가하면 그 한계를 보고하고, Codex 자체 2차 검증으로 대체한다.
   - Claude 판정은 그대로 믿지 말고 Codex가 직접 file:line/명령을 재현해서 맞는지 재공격한다.
   - 가능하면 <slug>.verdict.json에 generator, v1, v2, failed_attempts, three_way_agree, status, command, exit_code, artifact, hash를 기록한다.
   - `PASS라고 말했다`는 증거가 아니다. 어떤 반증을 시도했고 왜 실패했는지, 재실행 가능한 명령과 산출물 hash를 남긴다.
   - 테스트 `skip/only/todo` 추가, 테스트 삭제, assertion 약화, snapshot 무근거 갱신은 완료조건 위반이다.

8. L3는 owner signoff를 확인한 뒤에만 운영 write, 배포, 외부 발송, destructive action을 실행한다.
   - owner signoff가 없는 경우에는 로컬 분석/수정/테스트/dry-run까지만 진행한다.
   - 사업 오너의 현재 턴 명시 명령("보내", "발송", "등록", "게시", "실행" 등)은 owner signoff다. 이때는 거부하지 말고, 무엇을 어디에 몇 번 쓰는지와 검증 근거를 확인한 뒤 실행한다.
   - 수신자·대상·본문·채널·횟수가 불명확하거나, 보안/돈/파괴/대량 발송 위험이 새로 발견되면 그 구체 항목만 질문한다.
   - L3 승인 산출물에는 대상, 채널, 횟수, payload hash, 일회성 nonce, TTY 직접 확인을 남긴다. `OWNER_SIGNOFF=true` 같은 상주 env만으로는 승인으로 보지 않는다.
   - L3 자동화는 "절대 발생하면 안 되는 결과" 1개를 먼저 정의하고, 그것을 막는 실제 기계 통제(가드·러너)의 증거를 남긴다(SOT-30 §1-10).

9. 작업 크기를 제한한다.
   - 한 세션은 한 인수 기준(AC)만 끝낸다.
   - 파일 5개 초과 또는 implementation diff 300줄 초과면 작업 분할 필요로 보고하고 범위를 줄인다.

9.5 강화 v2 — R1~R5 (SOT-30 §4.5)
   - R1: L2+ code-change는 goal에 작업 분해표(단위=AC 1개=검증 1개) + 단위별 계약 + **예외 케이스 표**(모델이 먼저 예외 산정, 각 행 "자동 처리"/"명시적 중단+사유", 마지막 행 "그 외 전부 → 명시적 중단"). 표에 없는 상황 = 임의 판단 금지, 중단+표 갱신 후 재개.
   - R2 **질문 금지**: 스펙·SOT·예외표에 답이 있는 사항을 되묻는 것 = 위반. 허용 = 2FA·캡차·본인확인 / 파괴적·비가역 / 표에 없는 신규 상황(중단 보고+표 갱신안). Codex에는 Stop 훅이 없으므로 **종료 등가 게이트**를 쓴다: 마지막 단계에서 `npm run strict:exit-gate`(있으면)를 의무 실행하고, exit 0 출력이 없으면 "완료"라고 선언하지 않는다. V1 검증 항목에 "불필요 질문 0건" 포함.
   - R3 러너 소유 + **read-back**: 손 조작(로그인·검색어 입력·발송·창 조작)은 레포 러너로만. 위험 입력(검색어·수신자·본문·발송 대상)은 전송 전 read-back 대조 의무 — 불일치면 진행 금지+기록. 공유 도구(포털 러너·CDP 유틸)의 내장 가드가 러너 리스 마커를 스스로 검사해 없으면 exit 비0으로 거부한다(도구가 자기를 지키므로 Codex에서도 걸린다). git pre-commit/pre-push 훅도 실행기 무관 게이트다.
   - R4 재발 원장: 착수 시 `docs/sot/31-strict-recurrence-ledger.md`(있으면)를 읽고 관련 행을 goal에 인용. 같은 지적 2회째 = 승격 작업 즉시 발행 의무.
   - R5 단위 관문: 단위 N 검증 통과 전 N+1 착수 금지. V1/V2는 분해표·예외표 자체도 공격한다.
   - R6 실패=평가 케이스: 사장님 신고 실패 1건 = 재발 원장 1행 = 회귀 케이스 1건(20~50 시작 → 배포 전 100% 스위트 졸업).
   - R7 정정 2회=세션 리셋: 같은 작업 정정 2회+ = 세션을 버리고 배운 것을 반영한 새 프롬프트로 재시작(리셋 전 원장·goal 기록).
   - R8 위임·보고 위생: 하위 위임 4칸 템플릿(목표/반환 형식/쓸 도구/하지 말 것)+체크포인트 재개 · 실제 돌리지 않은 검증 언급 금지 · 도구 호출 6~8회마다 진행 보고 · 지침 가지치기 · 도구 인자 poka-yoke.

10. 승격·재라우팅·정직성 (SOT-30 Lesson 6 불변조건)
   - 같은 지적을 2회째 받으면 통제 승격(문서 H2 → 러너 H3 → 훅 H4) 후보로 보고한다.
   - PreToolUse 훅에 차단되면 작업을 포기하지 말고, stderr가 안내하는 정식 러너로 갈아타 완주한다.
   - 미구현(planned) 통제를 구현된 것처럼 서술하지 않는다. Claude 전용 훅 기능(Stop 등)을 Codex 기능처럼 쓰지 않는다.

최종 보고는 짧게:
- Summary
- Files Changed
- Verification
- Assumptions / Risks

스킬 자체를 수정하는 작업이면 마지막 작업 줄 앞에 이 한 줄도 적용한다:

추가 규칙: SKILL.md, .codex/skills/**, .claude/skills/**, frontmatter name/description, trigger 문구를 다루는 작업이면 skill-creator 기준을 먼저 적용하고, 가능하면 quick_validate.py <skill-folder>로 검증한다. strict 진입점 3파일을 고치면 같은 변경에서 tools/install-strict-skill.sh 로 전역 미러를 갱신하고 해시 대조를 남긴다.
