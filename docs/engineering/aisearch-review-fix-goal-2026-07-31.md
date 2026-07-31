# goal — aisearch 전수 리뷰 결함 수정 + 브랜치 통합 (2026-07-31)

- 등급: **L3** (외부 발송·내부 인증키 노출·SOT25/SOT29 계약 수정·되돌리기 어려운 병합 포함)
- 워크트리: `../Valuehire_v5-aisearch-review-fix-20260731` · 브랜치 `task/aisearch-review-fix-20260731`
- 베이스라인: `./verify.sh` → `3178 passed, 4 xfailed, 105 subtests passed` · `verify: pytest exit=0`
- 읽은 SOT: `docs/sot/25-ai-search-execution-process.json`, `docs/sot/26-portal-login-spec.json`,
  `docs/sot/28-auto-send-policy.json`, `docs/sot/29-fleet-control.md`, `docs/sot/30-strict-mode-contract.md`,
  `docs/search-access.md`, `CLAUDE.md`(SOT 불변식 1~5)

## 0. 과거 지시 회수 (게이트 0)

| 회수한 것 | 경로 | 이번 작업에 주는 제약 |
|---|---|---|
| 프로필 저장 증거 게이트가 **이미 구현돼 있음** | `tools/multi_position_sourcing/humansearch_register.py:230` `has_saved_profile_evidence()`, `:292` 등록 게이트, `:428` subtask 필드, `:614` 스펙 검증 | H1은 새 계약을 발명하지 않는다. humansearch 쪽 계약(증거 문자열 + 채널·position 일치 + `missing` 거부)을 aisearch `recorders.py`에 **동형으로** 옮긴다. 중복 구현 금지. |
| SOT25 `candidate_subtask_required_fields` = **5필드** | `docs/sot/25-ai-search-execution-process.json:51` | goal 문서(`aisearch-fleet-goal-2026-07-28.md` §5)의 "필수 4필드" 서술이 SOT와 불일치 → AC-3a로 정정. |
| SOT25 `profile_save_evidence_required: true` / `profile_save_evidence_fields: ["evidence"]` | 같은 파일 `clickup_registration_contract` | "증거 없으면 subtask 생성 금지"는 SOT 원문 요구. fail-closed가 기본값. |
| SOT 불변식 2 — 개입 후 60초 내 자동 재개, "멈추고 방치" 금지 | `CLAUDE.md` §SOT 불변식 2 | H3/F6: 자동 재개는 **시도 횟수로 포기하면 안 된다**. 6회 소진 후 종료 = SOT 위반. |
| SOT 불변식 3 — 자동 발송은 SOT28 게이트 통과 시에만 | `docs/sot/28-auto-send-policy.json` | 비범위: 이번 PR은 발송 코드를 **추가하지 않는다**. |

## 1. 현재 상태 (추측 없이 file:line — 라인은 `origin/task/aisearch-orchestrator` 기준)

미병합 8커밋: `3648e53`, `ec59f3a`, `e284864`, `62feff9`, `48ae818`, `941c2f1`, `29c169f`, `8d5987e`
(`git diff --stat main...origin/task/aisearch-orchestrator` = 15 files, +1194/-392)

### 1.1 사장님 스펙이 지목한 결함 (HIGH 5 · MEDIUM 6)

| ID | 위치 | 사실 |
|---|---|---|
| H1 | `apps/aisearch/core/recorders.py:34` | subtask 필수 필드가 4개 — `saved_profile_evidence` 없음. 저장 증거 없이도 등록된다. |
| H2 | `apps/aisearch/core/orchestrator.py:206-223` | 제외어 스캔이 후보 고유 필드가 아닌 텍스트 전체(JD 공통 문구 포함)를 훑는다. |
| H3 | `apps/aisearch/run.py:371` | `waiting_resume` 상태를 만들고 소비하는 주체가 main에 없다(브랜치 `29c169f`가 부분 해소). |
| H4 | `apps/aisearch/core/portal_search.py:195-204` | 체크박스 조작에 목표 상태 개념이 없어 이미 체크된 항목을 다시 눌러 해제한다. |
| H5 | `apps/aisearch/run.py:89-108` | `JsonlPageStore` 멱등키에 `page_type`이 빠져 `make_row_id`와 계약 불일치. 저장이 비원자적(전체 재기록). |
| M1 | `apps/aisearch/core/cdp_driver.py` `fetch_list/detail` | 저장 직전 차단 재확인 없음 — 캡차 화면 HTML이 데이터로 저장될 수 있다. |
| M2 | `apps/aisearch/core/orchestrator.py:511-544` | 한 채널 예외 시 첫 예외만 재발생, 타 채널 협조적 중단 신호·전체 보고 없음. |
| M3 | `apps/aisearch/core/intervention.py:163-184` | `pending_notifications`에 쌓인 알림을 다시 보내는 경로가 없다. |
| M4 | `apps/aisearch/core/cdp_driver.py:440-445` | RPS 결과건수를 여러 요소 텍스트를 이어붙여 파싱 — 잘못된 수를 낼 수 있고 실패가 조용하다. |
| M5 | `apps/aisearch/core/admin_api_client.py:67-72` | 200 응답이 dict가 아니면 이후 `.get()`에서 `AttributeError`. |
| M6 | `apps/aisearch/core/data/seoul_universities.py` | 서울 소재 4년제 누락(감리교신학대·장로회신학대·한국성서대·서울기독대 등). |

### 1.2 2026-07-31 브랜치 diff 리뷰에서 **추가로** 발견 (12건, F1~F12)

| ID | 위치 | 사실 | 등급 |
|---|---|---|---|
| F1 | `cdp_driver.py:614` (`fetch_detail_page`) | `poll_events()`는 `_last_human_inputs` 워터마크를 올리는 **상태 변경 함수**인데 반환값에서 `signal`만 쓰고 `human_input`을 버린다 → 상세페이지 열람 중 사장님 개입이 오케스트레이터 모니터에 **영원히 도달하지 않는다**(SOT 불변식 2 위반). | HIGH |
| F2 | `admin_api_client.py:67` | 성공 판정이 `status_code < 300` 뿐. 삭제될 `admin_api.py:167`에 있던 `payload.get("ok") is not True` 검사가 정본에 없다 → 200 + `{"ok":false}`가 "등록됨"으로 원장에 남는다. | HIGH |
| F3 | `admin_api_client.py:40,46` | `base_url` 스킴 검증·키 형식 검증 없음 → `http://`로 설정하면 `x-internal-key`가 평문 전송. 인자로 준 `base_url`에는 `.strip()`도 안 걸린다. | HIGH(보안) |
| F4 | `admin_api_client.py:30` | `HttpAdminApiClient`가 프로덕션에서 **한 번도 인스턴스화되지 않는다**(테스트 2곳뿐). "배선됨"이라는 전제가 사실이 아니며, `admin_api.py` 삭제로 전송 전 계약검증(점수 0~100·미지 필드 거부)이 통째로 사라진다. | MEDIUM |
| F5 | `recorders.py:54` `ALL_STEPS` + `:196` | `admin_register`가 첫 단계인데 `DualRecorder(admin=None)`이 기본값 → admin 미주입 구성에서 첫 단계가 `AttributeError`로 죽고 **ClickUp·Discord 보고까지 0건**. | MEDIUM |
| F6 | `run.py:451` | 자동 재개가 `max_resume_attempts=6 × 5초 = 30초`로 **고정 포기**. 사장님이 30초 넘게 크롬을 쓰면 `waiting_resume` 그대로 종료 = "멈추고 방치". | MEDIUM |
| F7 | `orchestrator.py:273-277` (재개 경로) | 재개 실행에서 기완결 후보는 `continue`로 건너뛰어 새 리포트 `registered`에 안 들어가고 **초안도 생성되지 않는다** → 재개가 한 번이라도 돌면 수치 축소·초안 영구 누락. | MEDIUM |
| F8 | `session_lock.py:50-66` | 크래시로 남은 락을 **절대 자동 회수하지 않는다** → 이후 링크드인 채널이 매번 실패, 그 예외가 `orchestrator.py:544`에서 재발생해 파이프라인 전체 `aborted`(사람인·잡코리아 결과까지 폐기). 사람 손 없이 복구 불가. | MEDIUM |
| F9 | `session_lock.py:52-56` | `mkdir` 성공과 `owner.json` 기록(`:67`) 사이 창 → 동시 시작 시 진 쪽이 "손상된 락 — 수동 해제" 오진단. 정상 경합이 수동 개입 사건으로 승격. | MEDIUM |
| F10 | `session_lock.py:55` | `_read_meta()`가 dict를 보장하지 않아 `owner.json`이 `[]`면 `meta.get`에서 `AttributeError`. | LOW |
| F11 | `run.py:456-460` | 리포트 `mode`/`live`가 `args.live`만 반영 → `recorder=`로 live 레코더를 주입하면 **실제 쓰기가 일어나는데 원장엔 dry-run**으로 남는다(증거 왜곡). | LOW |
| F12 | `recorders.py:389` | `name`을 채우는 추출기가 없어 전부 `"이름 미확인"` → v4 dedup이 이름 기반이면 포지션당 1건으로 병합될 수 있다. | LOW/MEDIUM |

### 1.3 근본 원인 (증상별이 아닌 계통)

1. **계약이 문서에만 있고 코드에 없음** — SOT25 5필드·증거 게이트, `make_row_id` 멱등키, 체크박스 목표 상태 모두 "코드가 알아서" 상태. (H1·H4·H5·AC-3a/3b)
2. **상태를 바꾸는 조회 함수** — `poll_events()`가 워터마크를 전진시키는데 호출부가 일부만 소비. (F1)
3. **fail-open 기본값** — HTTP 2xx=성공, `admin=None` 허용, JSON 타입 미검증, 스킴 미검증. (F2·F3·F5·M5·F10)
4. **"포기"가 SOT보다 먼저** — 재개 6회 제한, 락 자동회수 금지, 채널 예외 first-raise. (F6·F8·M2)
5. **관측/원장이 실제와 어긋남** — dry-run 표기, registered 누락, 결과건수 이어붙이기. (F11·F7·M4)

## 2. 계약 (SDD — 입출력 모양 먼저)

```
# H1 · SOT25 정합
CandidateSubtask = {
  profile_url: str(비어있지 않음), score: int(0..100), why_fit: str,
  profile_summary: str, saved_profile_evidence: str(비어있지 않음, "missing" 아님)
}
register(candidate) -> Registered | RejectedNoEvidence   # 증거 없으면 예외, subtask 미생성

# H2 · 제외어 스캔 범위
exclusion_scan_fields = (career, education, profile_text, score_evidence)  # 후보 고유
excluded_from_scan   = (draft_inputs.jd_summary, draft_inputs.briefing_elements)  # JD 공통

# H4 · 체크박스
CheckboxAction = { selector: str, desired_state: bool }   # click 아님 — 목표 상태
driver.set_checkbox(a) -> {clicked: bool}                 # 현재==목표면 clicked=False

# H5 · 저장 멱등키
row_id = (channel, page_type, url, position_ref)          # make_row_id 와 동일
store.save(rows) -> 임시파일 write + fsync + os.replace   # 원자적

# M5/F2/F3 · admin 응답
200 + dict + ok=True                  -> Recorded
200 + dict + ok!=True                 -> AdminApiResponseError
200 + non-dict JSON                   -> AdminApiResponseError
>=300                                 -> AdminApiRegisterError
base_url 스킴 != https                -> AdminApiConfigError (평문 전송 금지)
```

## 3. 입력 영역 표 (SOT-30 §1-11 ①) — 대표 3개 단위

### H1 `record_candidate(candidate)`
| 축 | 입력 | 처리 |
|---|---|---|
| 정상 | 5필드 모두 채워짐 | 등록 |
| 빈값/null | `saved_profile_evidence` 없음/""/None | **명시적 거부**(fail-closed, subtask 미생성) |
| 형식위반 | `saved_profile_evidence == "missing"` | **명시적 거부** |
| 경계 | `score` 0 / 100 | 등록 · 그 밖(음수·101·비정수)은 **명시적 거부** |
| 중복/재시도 | 같은 `profile_url` 재등록 | 기존 dedup 경로 유지(이번 범위 밖, 회귀만 확인) |
| 외부장애 | admin 미주입(`admin=None`) | **명시적 거부**(생성자 fail-fast — F5) |
| 그 외 전부 | — | **명시적 거부** |

### H5 `JsonlPageStore.save`
| 축 | 입력 | 처리 |
|---|---|---|
| 정상 | 새 행 | append 후 원자적 교체 |
| 중복 | 동일 `(channel,page_type,url,position_ref)` | 덮어쓰기(1건 유지) |
| 경계 | `page_type`만 다른 동일 URL | **서로 다른 행**(현재는 병합됨 — 결함) |
| 외부장애 | 쓰기 도중 크래시 | 기존 파일 무손상(임시파일 미교체) |
| 그 외 전부 | — | **명시적 실패** |

### admin 응답
(§2 계약 표가 그대로 입력 영역 표 — 5행 + catch-all `그 외 전부 → AdminApiResponseError`)

## 4. 작업 분해표 (R1) — 단위 = AC 1개 = 검증 1개, R5 순차 관문

| # | 단위 | AC (EARS) | 검증 명령 | counter-AC |
|---|---|---|---|---|
| U1 | 브랜치 병합 | 미병합 8커밋을 커밋 단위 리뷰 후 병합한다 | `git log main..origin/task/aisearch-orchestrator` 빈 출력 · `./verify.sh` exit 0 | 충돌을 자동 해결하면 실패(E-a) |
| U2 | admin 클라이언트 단일화 | `admin_api.py` 제거 후에도 PR#250 개선 4항목이 정본에 존재한다 | 항목별 대조표 + `pytest tests/test_aisearch_admin_api_client.py` | 두 클라이언트 동시 존재 시 실패 |
| U3 | H1 5필드+증거 게이트 | 증거 없는 후보는 subtask가 생성되지 **않는다** | RED→GREEN 테스트 | 증거 없이 등록되면 실패 |
| U4 | H2 스캔 범위 | JD에만 제외어가 있으면 후보를 제외하지 **않는다** | RED→GREEN | JD "인턴"+정상후보 → 제외 0 / 후보 경력 "인턴" → 제외 1 |
| U5 | H3+F6 자동 재개 | 개입이 끝나면 **시간 제한 없이** 재개한다 | RED→GREEN | 6회 소진 후 종료 경로가 남아 있으면 실패 |
| U6 | H4 체크박스 목표상태 | 이미 체크된 항목은 클릭하지 **않는다** | RED→GREEN | checked 상태에서 클릭 1회라도 발생하면 실패 |
| U7 | H5 멱등키+원자적 쓰기 | `page_type`이 키에 포함되고 저장이 원자적이다 | RED→GREEN(크래시 시뮬) | 기존 행 1건이라도 유실되면 실패 |
| U8 | M1 저장 직전 차단 프로브 | 차단 화면은 저장되지 **않는다** | RED→GREEN | 캡차 HTML이 저장되면 실패 |
| U9 | M2 채널 협조적 중단 | 한 채널 실패 시 타 채널에 중단 신호 + `channel_errors` 전량 보고 | RED→GREEN | 에러 1건만 보고되면 실패 |
| U10 | M3 알림 재발신 | 종료 전 `pending_notifications`를 flush하고 실패는 리포트에 표면화 | RED→GREEN | 조용히 버려지면 실패 |
| U11 | M4 건수 파싱 | 단일 카운트 요소로 파싱, 실패는 명시적 실패 | RED→GREEN | 이어붙인 값이 나오면 실패 |
| U12 | M5+F2+F3 admin 응답/전송 안전 | 비-dict·`ok:false`·비-https를 각각 명시적 예외로 거부 | RED→GREEN | 하나라도 통과하면 실패 |
| U13 | M6 서울 4년제 보완 | 누락 4개교 포함 + 소재지 근거 주석 | RED→GREEN(전체성 테스트) | 누락 1개라도 있으면 실패 |
| U14 | F1 상세페이지 개입 신호 | 상세 열람 중 사장님 입력이 모니터에 도달한다 | RED→GREEN | 입력이 유실되면 실패 |
| U15 | F4+F5 admin 배선·fail-fast | 프로덕션 경로에서 정본 클라이언트가 실제로 생성되고, 미설정이면 즉시 명시적 실패 | RED→GREEN + 배선 증명(엔트리포인트→호출 경로) | 고아 코드면 실패 |
| U16 | F7 재개 시 집계 | 재개 후 리포트 `registered`/`drafts`가 실제와 일치한다 | RED→GREEN | 수치가 줄면 실패 |
| U17 | F8+F9+F10 세션락 | stale 락 자동 회수 · 경합/손상 구분 · dict 타입 검증 | RED→GREEN | 크래시 1회로 영구 정지되면 실패 |
| U18 | F11+F12 원장 정합 | 리포트 live 표기가 실제 레코더를 반영 · 이름 미확보 시 URL 기반 식별키 동봉 | RED→GREEN | 실제 쓰기인데 dry-run 표기면 실패 |
| U19 | 문서 정정 AC-3a/3b/3c | 4필드→5필드 · 스키마 unique 정합 · 라이브 백로그 항목 추가 | `grep` 대조 | SOT 원문과 불일치면 실패 |

## 5. 예외 케이스 표 (R1 ③)

| 상황 | 처리 |
|---|---|
| 병합 충돌 — 계약·게이트 파일 | **명시적 중단 + 보고**(E-a, 자동 해결 금지) |
| 병합 충돌 — 그 외(문서·테스트 목록) | 양쪽 보존 후 보고 |
| 8커밋 중 스펙 위반 코드 | 그 커밋만 revert + 사유 기록(E-b) |
| RED이 문법 오류로 실패 | RED 무효 — 다시 작성 |
| GREEN을 위해 테스트 약화 필요 | **금지** — 중단 보고 |
| 라이브(실계정) 호출이 필요해 보임 | **금지** — 중단 보고(이번 PR 비범위) |
| 사장님 크롬 점유 감지 | 자동 작업 양보, 60초 후 자동 재개(SOT 불변식 2) |
| V1(codex) 결과가 "Done만/빈 결과" | 무효 — 재실행 |
| 그 외 표에 없는 상황 | **명시적 중단**(E-c) |

## 6. 적대검증 정조준 (V1/V2가 먼저 때릴 곳)

1. F1 수정이 `poll_events()` 워터마크를 **두 번 소비**하게 만들지 않았는가(신호 중복/유실).
2. U15 배선이 진짜 프로덕션 경로인가 — 테스트가 직접 import해 통과하는 고아가 아닌가.
3. U5 무제한 재개가 **바쁜 대기/봇 행동**(SOT 불변식 2 후단)이 되지 않는가.
4. U17 stale 자동 회수가 **살아있는 다른 기기의 락을 탈취**하지 않는가(E4 위반).
5. U7 원자적 쓰기가 동시 실행 2프로세스에서 마지막 쓰기 승리로 행을 잃지 않는가.
6. 분해표·예외표 자체에 빠진 현실 입력이 있는가(스펙 공격).

## 7. 비범위

- 자동 발송 코드 추가(SOT28) · 라이브 실계정 호출 · v4(admin) 서버측 변경
- `aisearch_pages_raw` 실제 마이그레이션 적용(오너 확정 전 draft 유지)
- LOW/INFO 약 20건 중 위 표에 없는 항목

## 8. 롤백 절차 (L3)

- 병합 전 태그: `git tag pre-aisearch-review-fix-20260731 main`
- 실패 시: PR 미머지 폐기 → 워크트리 제거(`git worktree remove`) → 브랜치 삭제. main 무변화.
- 머지 후 문제 발견 시: `git revert -m 1 <merge-commit>` (단일 머지 커밋으로 되돌림)

## 9. 게이트 계획

0 `make red-ledger` clean ✅ → 1 본 문서 → 2 워크트리 + 단위별 RED 커밋 → 3 RED→GREEN 최소 변경
→ 4 `./verify.sh` exit 0 (출력 숫자 그대로) → 5 `make ship` → PR → CI 초록 → merge → 6 원장 GREEN 기록

## 적대 검증 로그

(후기록 — V1/V2 판정 본문을 여기에 그대로 append)
