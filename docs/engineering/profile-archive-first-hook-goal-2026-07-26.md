# 후보자 프로필 저장 강제 훅 — goal (2026-07-26)

> 모드: mixed(진단→code) · 등급 **L2** (내부 저장 파이프라인 배선 + PreToolUse 훅, 외부 발송·PII 유출 아님)
> 정본 SOT: `docs/sot/26-portal-login-spec.json`(browser_evidence_capture.failure_policy), SOT-30(strict), SOT-27(가드 규약)

## 0. 현재 상태 (실측, file:line·DB 조회)

- 며칠 전 코드 = **#185/#186 "익스텐션 독립 브라우저 증거 캡처"**(PR#186 merged 2026-07-23). 저장 writer = `tools/multi_position_sourcing/profile_archive_store.py`(`ProfileArchiveStore.save/save_with_finalizer`), 유일 호출처 = `tools/multi_position_sourcing/browser_evidence.py`.
- **DB는 두 개**(실측):
  - 옛 익스텐션 DB `~/.valuehire/captures/profiles.db`(`captured_profiles`, 40건, 마지막 2026-06-11, saramin 0건) — 폐기 경로.
  - 새 캡처 DB `~/.valuehire/profile_archives.sqlite3`(`profile_archive_receipts`, 123건, linkedin 118·saramin 5, 마지막 2026-07-23). **UNIQUE(position_id, profile_url).**
- **현재 CEO가 보던 후보자(사람인 이력서 `19452507`, 차OO)는 두 DB 모두 0건 = 미저장.** 원인: 저장은 `humansearch/aisearch` **러너가 프로필을 방문할 때만**(profile-mode) `capture_owned_browser_evidence`로 트리거된다. CEO가 **수동으로 이력서를 열면 어떤 러너도 캡처하지 않으므로 저장이 새는 구조**.
- SOT-26 `browser_evidence_capture.failure_policy` = "fail-closed; **saved/score/advance/complete is forbidden**"(영수증 없이 채점·전진·완료 금지). 그러나 이 정책은 **러너 코드 안에만** 있고 **harness 훅으로 강제되지 않음** → 우회·수동 경로에서 미저장이 조용히 통과.
- 저장 진입 계약: `session_guard.run_capture_evidence_episode(task in {ai-search,humansearch}=profile mode, 필수: target_id·profile_url·position_id·candidate_index)` (`session_guard.py:2020`).

## 1. 인수 기준 (EARS, 이슈 A)

- **AC**: 후보자 "전진성" 작업(제안 발송·ClickUp 후보 등록·pos-fill 등록모달 채우기)을 시도하는 harness tool 호출은, 그 후보자(profile_url)에 대한 **신선한 ProfileArchiveStore 영수증이 없으면 PreToolUse 훅이 exit 2로 차단**하고 정식 캡처 러너로 안내한다.
- 검증 명령: `pytest tests/test_profile_archive_gate.py tests/test_discord_bot_guards.py -q` + 훅 디스패치 라이브 1건.
- counter-AC: 신선한 영수증이 있으면 통과(정상 경로 미차단). 저장 자체와 무관한 읽기·검색·로그인은 통과.

## 2. 작업 분해표 (R1)

| # | 단위 | AC | 검증 |
|---|---|---|---|
| U1 | 순수 게이트 `profile_archive_gate.block_reason(tool, tool_input, has_receipt)` | 전진성 도구 + 영수증 없음 → 사유; 있음/무관 도구 → None | `tests/test_profile_archive_gate.py` |
| U2 | 영수증 조회 `receipt_exists(db, position_id, profile_url)` (profile_archives.sqlite3) | UNIQUE 키로 존재·신선 판정 | 동일 테스트 |
| U3 | PreToolUse 훅 `guards/profile-archive-first.py` (U1+U2 배선) | 제안/등록 Skill·tool 차단, 읽기/검색/로그인 통과 | `tests/test_discord_bot_guards.py` |
| U4 | (라이브) 현재 후보자 캡처로 실증·저장 | capture-evidence profile-mode 1건 저장 | DB 조회 |

## 3. 입력 영역 표 (결정성)

입력 = PreToolUse stdin `{tool_name, tool_input}` + 후보자 식별자(profile_url/position_id) + 영수증 DB 상태.

| 행 | 입력 | 처리 |
|---|---|---|
| 1 | tool=Skill, skill ∈ {jdbuilder, pos-fill, saramin/jobkorea proposal} + 후보 식별자 有 + 영수증 無 | 차단(exit 2) |
| 2 | 동일 + 영수증 有(신선) | 통과 |
| 3 | tool=Skill, skill ∈ {aisearch, humansearch, url, login} | 통과(저장은 이 러너가 수행) |
| 4 | tool=Bash 읽기(cat/rg/grep/ls), 검색, 로그인 | 통과 |
| 5 | 후보 식별자 파싱 불가(tool_input 어디에도 프로필 URL 없음) | 통과(이 게이트 대상 아님) |
| 6 | 영수증 DB 파일 없음/열기 실패 | fail-closed 차단(전진성 도구에 한해) |
| 7 | position_id 없이 profile_url만 | profile_url canonical 단독 매칭, 없으면 차단 |
| 8 | URL이 중첩 필드/대체 필드명(candidate_url 등)에 숨음 | **재귀 스캔으로 검출·차단**(V1 봉인) |
| 9 | URL 전체 percent-encoding | **최대 3회 디코드 후 검출·차단**(V1 봉인) |
| 10 | 여러 후보 URL 중 일부만 저장 | **전수 검사 — 하나라도 미저장이면 차단**(V1 봉인) |
| 11 | 저장 URL과 쿼리/트레일링슬래시만 다름 | canonical 정규화로 **동일 취급**(과잉차단 방지, V1 봉인) |
| 12 | jobkorea Co_Read?rNo / linkedin talent/hire/../profile | browser_evidence 정본 형식 반영해 검출 |
| 13 | **그 외 전부** | 통과(좁은 게이트 — 전진성 스킬 + 프로필 URL 있을 때만) |

> 주의: tool_input 문자열은 **고정 필드가 아니라 전 중첩 값 재귀 스캔**한다(§goal V1 반영).

## 4. 예외 케이스 표 (R1)

| 상황 | 처리 |
|---|---|
| 영수증 DB 잠김/IO 오류 | 전진성 도구 차단 + 사유(정식 캡처 러너 안내) |
| 수동 브라우징(도구 호출 아님) | 훅 범위 밖 — 캡처는 러너로 유도(문서/러너 안내) |
| 영수증은 있으나 오래됨(신선도) | 신선도 기준 미정 → **결정필요**(아래 §5) |
| **그 외 전부** | 명시적 통과(좁은 게이트) |

## 5. 결정 목록

| 결정 | 채택 값(보수 기본) | 근거 |
|---|---|---|
| 영수증 신선도 | **존재만 확인(만료 없음)** — 프로필 아카이브는 1회 저장이 목적, 로그인처럼 만료 개념 아님 | UNIQUE(position_id, profile_url) 재저장 방지 설계 |
| 차단 대상 도구 | 제안 발송·후보 등록·pos-fill (전진성) — 검색·로그인·읽기 제외 | SOT-26 "score/advance/complete forbidden" |
| profile_url 식별 위치 | tool_input의 문자열에서 saramin/jobkorea/linkedin 프로필 URL 정규식 추출 | poka-yoke |

## 6. 비범위
- 수동 브라우징 자동 저장(도구 호출이 아니라 훅으로 못 잡음 — 별도 익스텐션/러너), 옛 captures/profiles.db 마이그레이션, 원격(Supabase) 동기화.

## 7. 게이트·워크트리
- 워크트리: `../Valuehire_v5-profile-archive-first-hook` (branch `task/profile-archive-first-hook`, `make task`).

## 적대 검증 로그

### V1 (codex fresh, read-only, 2026-07-26) — FAIL → 전건 봉인
- CRITICAL: 자동발송 스킬 `clickup-position-talent-matching` 누락 → `_ADVANCE_SKILLS`에 전 발송/등록 스킬 추가.
- HIGH: jobkorea `/Recruit/Co_Read?rNo=` 미검출 → 정규식을 browser_evidence 정본 형식(corp/person·/person/·searchfirm·co_read·resume)에 맞춤.
- HIGH: 다중 URL 첫 번째만 검사 → 전 문자열의 모든 URL 전수, 하나라도 미저장이면 차단.
- HIGH: candidate_url·중첩 필드·전체 percent-encoding 우회 → tool_input 전 값 재귀 스캔 + 최대 3회 percent-decode.
- MEDIUM: trailing slash/query 차이 과잉차단 → canonical_url 정규화로 양측 대조.
- MEDIUM: import 실패 fail-open → 디스패처 기존 계약(fail-open)이라 잔존 위험으로 명시(정상 환경 8가드 로드·차단 실증).
- 라이브 재현: 우회 4건(clickup/Co_Read/candidate_url/percent-encoded) 전부 exit 2 차단 확인, 정상 검색 exit 0. gate 31 + 훅 회귀 20 green.
- V1 판정 본문/agentId는 verdict.json 참조.
