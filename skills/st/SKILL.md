---
name: st
description: "Strict Codex execution mode. Use when the user invokes $st, asks for 엄격 모드(codex), strict mode, 레포 SOT/goal spec/test/wiring/adversarial verification, or wants a task handled only after evidence-backed validation. Applies to code-change, noncode, and mixed tasks; classifies security, money, production writes, external sending, deployment, and destructive actions as L3, and treats the owner’s explicit current-turn command such as 보내/발송/등록/게시 as approval after evidence-backed validation."
---

# $st — 엄격 모드(codex)

Treat the rest of the user's message after `$st` as the task.

엄격 모드(codex)로 진행해.

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
   - `docs/sot/19-harness-loop.md`가 있으면 strict core 원본으로 보고, Codex/Claude 지침보다 우선한다. 충돌하면 레포 SOT를 먼저 따른다.

3. L1 이상이면 먼저 goal/계약 스펙을 남긴다.
   - 가능하면 docs/engineering/<slug>-goal-<YYYY-MM-DD>.md 생성
   - 포함: 현재 상태 증거(file:line), 근본 원인, 인수 기준, 비범위, 검증 명령, SOT 체크리스트
   - code 작업이면 입력/출력 shape, 필드, 타입, 함수/API 시그니처, 상태 전이를 명시한다.
   - analysis/research 작업이면 최종 답변 스키마와 주장별 근거·반례·한계를 명시한다.

4. L2 이상이면 변경 전에 worktree 상태를 확인한다.
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
   - package.json에 `strict:gate`가 있으면 먼저 실행한다. 이 gate가 goal 문서, focused test, verdict.json, test skip/only/todo 증가, L3 signoff, 작업 크기 제한을 막는 완료조건 검사라고 본다.
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

9. 작업 크기를 제한한다.
   - 한 세션은 한 인수 기준(AC)만 끝낸다.
   - 파일 5개 초과 또는 implementation diff 300줄 초과면 작업 분할 필요로 보고하고 범위를 줄인다.

최종 보고는 짧게:
- Summary
- Files Changed
- Verification
- Assumptions / Risks

스킬 자체를 수정하는 작업이면 마지막 작업 줄 앞에 이 한 줄도 적용한다:

추가 규칙: SKILL.md, .codex/skills/**, .claude/skills/**, frontmatter name/description, trigger 문구를 다루는 작업이면 skill-creator 기준을 먼저 적용하고, 가능하면 quick_validate.py <skill-folder>로 검증한다.
