# 30 — strict 모드 계약 (v5 포인터 + overlay)

> 2026-07-20 신설(단위⑥ 이식). **정본(전문)은 v4 레포** `valuehire_v4:docs/sot/30-strict-mode-contract.md` — core 규칙(L0~L3·H1~H4·§1 core 1~11·§4.5 R1~R8)의 전문은 그쪽 한 곳에만 둔다(전문 복제 = 드리프트 재발 경로라 금지). 이 문서는 v5에서 그 core를 어떻게 적용하는지(overlay)만 정의한다.
> 진입점(/strict·/st·$st)은 전역 미러(~/.claude, ~/.codex — v4 `tools/install-strict-skill.sh`가 갱신)가 서빙하므로 v5 레포 안에 사본을 두지 않는다(2026-07-20 옛사본 제거).
>
> - **🟢 쉽게 말하면**: 엄격 모드 규칙책의 원본은 v4에 한 권만 있습니다. 이 문서는 "v5에서는 어떤 명령으로 그 규칙을 지키는지"만 적은 안내판입니다.

## R1~R8 요약 (정본 §4.5 — 여기서는 이름만, 전문은 v4)

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
| 종료 등가 게이트(Codex 등 훅 없는 실행기) | `make strict-exit-gate` (scripts/harness/strict-exit-gate.py) — exit 0 + PASS 출력 없으면 "완료" 선언 금지 |
| read-back(R3 ②) | 기존 구현 — portal_worker.py `readback verification`(검색 입력 재읽기 대조, 불일치 fail) |

## 통제 수준 (정직 표기 — v5 기준)

| 규칙 | v5 통제 수준 |
|---|---|
| 시작자격 RED 차단 | **runner** (make red-ledger) |
| Stop 미커밋 잔존·질문 금지 | **hook** (stop-evidence-gate.py + settings 배선) — 마커는 task.sh(러너)가 생성, TTL 24h |
| 브라우저 손조작 리스 가드 | **hook** (guards/runner-lease.py) + **runner** (runner_lease.py CLI) |
| read-back | **runner** (portal_worker 기존) |
| 종료 등가 게이트 | **runner** (make strict-exit-gate) |
| git pre-push | **runner** (scripts/harness/pre-push — 기존) · pre-commit strict 게이트는 **planned**(v5 strict:gate 상당 검사기 미구현) |
| R1·R5~R8 | **policy** (정본 문서 + goal + V1 공격) |

planned 항목을 현재형으로 서술하는 문서는 계약 위반이다(정본 AC3와 동일).

## 변경 규칙

core 규칙 변경은 v4 정본에서만. 이 overlay 변경은 ADR + 사람 승인 PR로만. 옛사본(.claude/skills/strict 등)을 되살리는 변경은 드리프트 재발이므로 금지 — 진입점 수정은 v4에서 하고 installer로 미러를 갱신한다.
