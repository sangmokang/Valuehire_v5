# goal — CLAUDE.md 전면 개편 (2026-08-03)

## ① 현재 상태 (증거)

- `CLAUDE.md` 73줄. 중복 26줄(불변식5 `:33-42` + "5번 규칙 풀이" `:46-61`) = **36%**.
- 저장소 지도·작업 명령 **0건**: `grep 'verify\|make \|pytest\|tools/\|tests/' CLAUDE.md` → 히트는 `:19` "말하지 말 것" 예시 하나뿐.
- 반복해서 물리는 함정(검사 환경 numpy 부재, `verify.sh` 인터프리터 자동탐색, Stop 훅 발동 조건)이 규칙서에 없다.

## ② 근본 원인

규칙서가 **정책 선언문**이지 **작업 지침**이 아니다. 매 대화에 실리는 비용을 내면서
"코드를 읽으면 알 수 있는 것"도 "코드를 읽어도 모르는 것"도 담지 않았다.
그 결과 매 작업마다 저장소 구조를 처음부터 다시 찾고, 같은 함정을 다시 밟는다.

**규칙서 비대화는 이미 실제 손실을 냈다.** `tools/multi_position_sourcing/matching_score_contract.py:379-382`:

> 기본 시스템 프롬프트를 그대로 두면 프로젝트·전역 CLAUDE.md 와 스킬이 실려서 추출 요청을
> 작업 지시로 읽고 되묻는다 — JSON 이 없으니 그 후보가 통째로 버려진다(2026-08-01 라이브).

## ③ 인수 기준 (AC · 1개)

**Where 규칙서가 저장소 구조·코드 동작을 기술하는 경우, 시스템은 그 기술이 실제 저장소와
일치함을 기계로 검증할 수 있어야 한다.**

- 검증 명령: `./verify.sh` (exit 0) / 단위: `pytest tests/test_claude_md_contract.py`
- counter-AC (가짜 완료):
  - 규칙서에 문장만 늘리고 검사가 그 문장을 실제로 읽지 않으면 가짜.
  - 경로 실존만 확인하고 **역할 서술의 진위**를 확인하지 않으면 가짜 — 이번 개편에서
    실제로 나온 오류가 전부 "경로는 맞는데 역할이 틀린" 유형이었다.
  - 파일 개수·줄 수 같은 **변동 수치를 규칙서에 박으면** 곧 낡는다(`docs/harness.md:117` 교훈).
    검사가 수치를 강제하면 파일 하나 추가할 때마다 규칙서를 고쳐야 하므로 오히려 해롭다.

## ④ 게이트 진행

| 게이트 | 결과 |
|---|---|
| 0 | `make red-ledger` 비-0 → 원인 조사: RED 19건 **전부 브랜치 소멸(merge 완료)**, `./verify.sh` **3377 passed exit 0**. 원장 잔재로 판정, 같은 작업방에서 정리 |
| 1 | 본 문서 |
| 2 | `tests/test_claude_md_contract.py` RED — **4 failed, 10 passed** (지도·명령·함정 부재로 실패. 문법·import 오류 아님) |
| 3 | `CLAUDE.md` 교체 → **14 passed** |
| 3.5 | 배선: 이 산출물은 문서이고 검증 경로는 `verify.sh` → `pytest tests/` → 본 계약 테스트. 고아 아님 |
| 4a | 1차 **4 failed / 3387 passed** → §하니스가 잡은 것 참조 → 재실행 **3391 passed, 2 skipped, 4 xfailed, 138 subtests passed / exit 0** |
| 4b | V1(Codex) 사전 사실검증 완료 — `.harness/v1-claude-md-claims-verdict.md` |

## ⑤ codex 적대검증 항목

개편 **이전에** 초안의 주장 15개를 V1(Codex)에 넘겨 전수 사실검증했다. 판정 전문은
`.harness/v1-claude-md-claims-verdict.md`(본 커밋에 동봉). 요지:

| 판정 | 건수 | 내용 |
|---|---|---|
| CONFIRMED | 5 | 저장소 규모·CI 제약·`verify.sh` 동작·자기확장 규칙 |
| OVERSTATED | 7 | 중복 "절반"(실제 34%), "pytest+playwright만"(postgres 누락), "정면 충돌"(전역 파일이 이미 충돌 해소 조항 보유), 커밋 한국어 "100%"(실제 57%) 등 |
| FALSE | 2 | **C7** 커밋으로 위임 여부 판정 불가 / **C13** "SOT diff 동봉해야 머지 가능" 규칙은 이 저장소에 존재하지 않음 |
| 혼재 | 1 | **C9** 파일 역할 매핑 — 5그룹 중 2그룹 오분류 |

**초안에서 제거·정정한 것**: C13(없는 규칙 신설 → 삭제), C9 오분류 3건(`dedup.py`·`grouping.py`·`jd_outreach.py`),
C4b(CI 서술), C10(테스트 네이밍 "관례" 주장 삭제), C11(Stop 훅 발동 조건 명시), C15(커밋 한국어 → "권장"),
변동 수치 전량 삭제.

## ⑥ SOT 체크리스트

- 읽음: `docs/sot/26-portal-login-spec.json`(규칙 A), `docs/sot/28-auto-send-policy.json`(규칙 C),
  `docs/sot/29-fleet-control.md`(규칙 B), `docs/sot/30-strict-mode-contract.md`(Stop 훅 §4·§4.5), `docs/harness.md`.
- **SOT 수정 필요 없음.** 불변식의 내용은 그대로 두고 표현만 압축했다. 계약 테스트
  `test_invariants_survive` 가 6개 불변식 키워드의 생존을 강제한다.

## ⑦ 비범위

- 전역 `~/.claude/CLAUDE.md`(442줄)는 저장소 밖 파일 — 이번에 손대지 않는다.
- `claude -p` 호출부 API 키 미제거 구멍은 **별건**(`task/apikey-strip-live`).
- `.claude/hooks/stop-evidence-gate.py:11` docstring이 존재하지 않는 `npm run wt`를 가리키는 문서 오류(실제는 `make task`). 기록만 남기고 이번 범위 밖.

## ⑧ 롤백 절차

`git revert <merge-sha>` 한 번으로 끝난다. 문서 1개 + 테스트 1개 + 원장뿐이라
런타임 동작에 영향이 없다.

## ⑨ 영향 반경

규칙서·원장·테스트만 바뀐다. 프로덕션 코드 변경 0건.
잘못되면 "규칙서가 실제와 다른 설명을 담는" 문서 결함이 남을 뿐 라이브는 멈추지 않는다.
다만 규칙서는 모든 후속 작업의 입력이므로, 틀린 지도는 **후속 작업 전체의 오류로 번진다** —
그래서 계약 테스트로 고정한다.

## ⑩ 계약 스펙

`tests/test_claude_md_contract.py` 가 규칙서에 거는 계약:

| 검사 | 계약 |
|---|---|
| `test_map_paths_exist` | 본문 백틱 안의 저장소 경로는 전부 실존(런타임 산출물 `RUNTIME_ARTIFACTS` 제외). glob 허용 |
| `test_map_covers_core_engine` | 핵심 엔진 경로가 지도에 존재 |
| `test_auto_send_does_not_import_dedup` | 규칙서 주장("발송 중복 방지는 원장이 한다")과 코드 일치 |
| `test_grouping_groups_positions_not_candidates` | `grouping.py` 는 `Position` 을 받는다 |
| `test_login_barrier_verifies_receipt_rather_than_logging_in` | `login_barrier.py` 는 영수증 검증기 |
| `test_claude_p_callsites_listed_in_map` | 규칙서가 지목한 LLM 호출부에 실제 `claude -p` 존재 |
| `test_invariants_survive` | 불변식 6종 키워드 생존(약화 금지) |
| `test_gate_commands_present` | 작업 명령 4종 존재 |
| `test_known_traps_documented` | 함정 3종(numpy·API 키·Stop 훅) 존재 |

**의도적으로 검사하지 않는 것**: 파일 개수·줄 수 등 변동 수치(§③ counter-AC 참조).

---

## 적대 검증 로그

### V1 — Codex 사실검증 (2026-08-03, 개편 전 초안 대상)

- 판정 전문(본문 그대로 보존): `.harness/v1-claude-md-claims-verdict.md` (50KB)
- 실행: `codex:codex-rescue` 에이전트, agentId `V1-claims-audit@session-c537c0c6`
- VERDICT: *"기계로 확인 가능한 사실은 대체로 정확하나, 강제되지 않는 규칙을 강제되는 것처럼
  쓴 것(C13), 커밋 이력으로 알 수 없는 것을 단정한 것(C7), 훅의 발동 조건을 통째로 생략한
  것(C11), 파일명만 보고 역할을 붙인 것(C9) 네 가지는 반드시 정정해야 한다."*

### V2 — Claude 재현 (같은 날, 격리 재현)

V1이 제시한 증거를 직접 재현했다. 재현 명령과 결과:

| V1 주장 | 재현 명령 | 결과 |
|---|---|---|
| CLAUDE.md 주입 라이브 장애 기록 존재 | `sed -n '370,395p' tools/multi_position_sourcing/matching_score_contract.py` | **일치** — 379~381행에 2026-08-01 장애 기록 확인 |
| Stop 훅 증거게이트는 함대 워커 전용 | `grep -n VH_BUSY_TASK .claude/hooks/stop-evidence-gate.py` | **일치** — `:126` 환경변수 없으면 즉시 통과 |
| 전역 규칙서에 충돌 해소 조항 존재 | `sed -n '1,10p' ~/.claude/CLAUDE.md` | **일치** — G(나)의 "정면 충돌" 판정이 틀렸음을 확인, V1 채택 |
| 훅에 R2 질문금지 기능 존재(G가 누락) | `sed -n '36,50p' .claude/hooks/stop-evidence-gate.py` + `docs/sot/30-strict-mode-contract.md:10,20,30` | **일치** — 규칙서에 반영 |

**G·V1·V2 일치 판정**: 15개 주장 전부 동일 결론. 갈린 항목 C6은 V2 재현 결과 **V1이 옳고
G가 틀림**으로 확정, 정정 후 반영.

### 하니스가 잡은 것 — 기존 계약 테스트의 불변식 약화 차단

교체본을 넣고 전체검사를 돌리자 **내가 몰랐던 기존 계약 3건이 빨개졌다.**
`tests/test_sot_distrust_doublecheck_doc.py` 가 CLAUDE.md 본문을 이미 검사하고 있었다:

| 실패한 검사 | 요구 문구 | 내가 바꾼 표현 | 조치 |
|---|---|---|---|
| `test_p1_distrust_principle_in_sot` | `믿지않는다` 또는 `믿지말고` | "헛점이 있다고 전제한다" | **원 문구 복원** |
| `test_p1_distrust_is_numbered_invariant` | `SOT 불변식` 섹션 + `^\d+\. \*\*` 5개↑ | 섹션명을 "절대 금지선"으로 변경 | **섹션명에 SOT 불변식 복원** |
| `test_p2_two_pass_in_sot` | `작은기능단위`/`작은단위`/`기능단위` | "작게 자른다" | **"작은 기능 단위로 만든다"로 복원** |

의미는 같아도 **계약 문구를 바꾸면 약화로 간주된다.** 계약이 옳으므로 테스트를 고치지 않고
규칙서 표현을 되살렸다(SOT 우선 원칙). 수정 후 25 passed.

> 이 사건 자체가 이번 개편의 근거다 — 사람이 "의미는 같으니 괜찮다"고 판단한 변경을
> 기계가 잡았다. 지도·불변식은 사람 기억이 아니라 검사로 지켜야 한다.

### 알려진 flaky (이번 변경과 무관)

`tests/test_portal_tab_guard.py::test_start_does_not_relaunch_when_process_alive_but_cdp_dead`
가 전체검사 동시 실행 시 1회 실패했으나 **단독 재실행 6 passed**. 크롬 프로필/포트 자원
경합으로 보인다. 본 변경과 인과 없음(문서·테스트만 변경). 별건 관찰 대상으로 남긴다.

### 뮤테이션 점검 (R2 가짜 GREEN 차단)

| 일부러 깨뜨린 것 | 기대 | 결과 |
|---|---|---|
| `CLAUDE.md` 에서 numpy 함정 문구 삭제 | `test_known_traps_documented` 빨개짐 | **1 failed** ✅ |
| `auto_send.py` 에 `from .dedup import ...` 추가 | `test_auto_send_does_not_import_dedup` 빨개짐 | **1 failed** ✅ |

둘 다 원복 확인(`git status` 로 검증).
