# 30 — strict 모드 계약 (v5 포인터 + overlay)

> 2026-07-20 신설(단위⑥ 이식). **2026-11-12 정본 이전(strict-unify, GitOps 원칙 1 Single Source of Truth)**: strict 진입점·core 규칙의 정본은 **이 레포(v5)** 의 `skills/strict/SKILL.md`(Claude)·`.codex/skills/strict/SKILL.md`(Codex) 두 파일이다 — 두 파일의 `strict-core` 블록은 바이트 단위로 같아야 하며 `tests/test_strict_unify.py`가 해시로 강제한다. 이전 정본 `valuehire_v4:docs/sot/30-strict-mode-contract.md`는 **동결**(더 이상 갱신하지 않음; v4 사본 제거는 별도 PR). 이 문서는 core를 v5에서 어떻게 적용하는지(overlay)를 정의한다.
> 진입점은 전역 경로(~/.claude/skills/strict, ~/.codex/skills/strict)에 **배포 산출물**로 설치된다 — 설치는 병합된 origin/main에서 `tools/sync-strict-skill.sh --install`로만(러너가 그 외 리비전을 거부), 드리프트 감지는 `--check`. **st 별칭(/st·$st)은 폐지**되었고 strict로 통합됐다(옛 `skills/st`·`.codex/skills/st` 제거). 옛 `.claude/skills/strict`·`.claude/commands/strict.md` 레포 사본은 계속 두지 않는다.
>
> - **🟢 쉽게 말하면**: 엄격 모드 규칙책의 원본은 v4에 한 권만 있습니다. 이 문서는 "v5에서는 어떤 명령으로 그 규칙을 지키는지"만 적은 안내판입니다.

## R1~R8 요약 (전문은 `skills/strict/SKILL.md` core §4)

R1 분해→스펙→**예외 케이스 표**(마지막 행 "그 외 전부 → 명시적 중단") · R2 **질문 금지** 게이트(허용 = 2FA·캡차·본인확인/파괴적·비가역/표 밖 신규 상황의 중단 보고) · R3 러너 소유 + **read-back** 대조(v5 실물: `tools/multi_position_sourcing/portal_worker.py` readback verification) · R4 **재발 원장**(정본 장부 = v4 `docs/sot/31-strict-recurrence-ledger.md` — 원장은 사장님 교정 장부라 레포별 분산 금지, v5 작업도 그 장부를 읽고 인용한다) · R5 **단위 관문** · R6 실패=**평가 케이스** 파이프라인 · R7 정정 2회=**세션 리셋** · R8 위임·보고 위생.

## v5 overlay — core 개념 ↔ 이 레포 실물

| core 개념 | v5 실물 |
|---|---|
| 시작자격 검사 | `make red-ledger` (scripts/harness/red-ledger.sh, `.harness/red-ledger.tsv`) |
| 워크트리 | `make task NAME=<slug>` → `../Valuehire_v5-<slug>` (branch `task/<slug>`) — strict 마커(.claude/strict-active.json)도 이 러너가 생성 |
| 기계 검증 | `./verify.sh` (pytest 전체, exit 0 == GREEN) |
| 배송 | `make ship` (verify 재실행 → push → PR) |
| Claude 훅 | `.claude/hooks/harness-dispatch.py`(PreToolUse 가드 디스패처, guards/*.py 자동 발견) + `.claude/hooks/stop-evidence-gate.py`(Stop — 미커밋 잔존 1턴 저지 + R2 질문 금지, sentinel 99→settings 래퍼가 2로 승격) |
| R3 리스 가드 | `.claude/hooks/guards/runner-lease.py` — 판정 본체는 `tools/harness/runner_lease.py` **한 곳**(v4와 동일 파일, CLI check/issue/release) |
| 종료 등가 게이트(Codex 등 훅 없는 실행기) | `make strict-exit-gate` (scripts/harness/strict-exit-gate.py) — exit 0 + PASS 출력 없으면 "완료" 선언 금지. **fail-closed**(2026-11-12): 마커 판독 불가·스키마 위반·워크트리 없음·다른 레포·git rc≠0·타임아웃 = FAIL |
| 진입점 배포·드리프트 | `tools/sync-strict-skill.sh --install`(병합된 origin/main에서만) · `--check`(쓰기 0) · `make strict-sync-check` |
| read-back(R3 ②) | 기존 구현 — portal_worker.py `readback verification`(검색 입력 재읽기 대조, 불일치 fail) |

## 통제 수준 (정직 표기 — v5 기준)

| 규칙 | v5 통제 수준 |
|---|---|
| 시작자격 RED 차단 | **runner** (make red-ledger) |
| Stop 미커밋 잔존·질문 금지 | **hook** (stop-evidence-gate.py + settings 배선) — 마커는 task.sh(러너)가 생성, TTL 24h |
| 브라우저 손조작 리스 가드 | **hook** (guards/runner-lease.py) + **runner** (runner_lease.py CLI) |
| read-back | **runner** (portal_worker 기존) |
| 종료 등가 게이트 | **runner** (make strict-exit-gate, fail-closed) |
| 진입점 단일 정본·core 패리티 | **runner** (tests/test_strict_unify.py — verify.sh 경유) |
| 전역 설치 = 병합 리비전만 | **runner** (sync-strict-skill.sh 거부 로직) · 설치 자동 주기 실행은 **planned 아님/보류**(오너 승인 수동 실행) |
| git pre-push | **runner** (scripts/harness/pre-push — 기존) · pre-commit strict 게이트는 **planned**(v5 strict:gate 상당 검사기 미구현) |
| R1·R5~R8 | **policy** (정본 문서 + goal + V1 공격) |

planned 항목을 현재형으로 서술하는 문서는 계약 위반이다(정본 AC3와 동일).

## 변경 규칙

core 규칙 변경은 이 레포 `skills/strict`·`.codex/skills/strict` 두 파일을 같은 PR에서 함께 고쳐서만(core 패리티 테스트). 이 overlay 변경은 ADR + 사람 승인 PR로만. 옛사본(.claude/skills/strict, skills/st 등)을 되살리거나 전역 사본을 직접 고치는 변경은 드리프트 재발이므로 금지 — 병합 후 sync 러너로 배포한다.
