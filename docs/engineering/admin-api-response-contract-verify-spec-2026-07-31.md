# admin.valuehire.cc 등록 API 클라이언트 — 응답 계약 검증 Spec (2026-07-31)

> Codex 재검증용 정본. 브랜치 `task/admin-api-response-contract`, 최종 커밋 `082eadd`.
> 이 문서의 조항 번호(S-REQ / S-RES / S-REC / S-ROB / S-TEST)로 합격·불합격을 판정한다.

---

## 0. 대상

| 항목 | 값 |
|---|---|
| 작업방 | `/Volumes/SSD/valuehire_v5/worktrees/admin-api-response-contract` |
| 브랜치 | `task/admin-api-response-contract` (base: `main`) |
| 커밋 범위 | `main..082eadd` (7커밋) |
| 구현 | `apps/aisearch/core/admin_api.py` |
| 테스트 | `tests/test_aisearch_ac6_admin_api.py` |
| 변경 규모 | 2 files, +428 / -33 |

## 1. 정본(SOT) — 판정 근거는 반드시 아래 원본에서 인용할 것

| 무엇 | 경로 |
|---|---|
| 서버 라우트 | `/Users/kangsangmo/Desktop/valuehire_v4/app/api/aisearch/register/route.ts` (커밋 `db7429c2`, PR#744) |
| DB 스키마 | `/Users/kangsangmo/Desktop/valuehire_v4/supabase/migrations/20260507000000_pipeline.sql` |
| 내부키 규칙 | `/Users/kangsangmo/Desktop/valuehire_v4/lib/internalApiKey.ts` |
| 프로젝트 SOT | `/Volumes/SSD/valuehire_v5/CLAUDE.md` (불변식 3 = 자동발송 fail-closed) |
| 작업 절차 | `/Volumes/SSD/valuehire_v5/docs/harness.md` |

**서버 성공 응답은 딱 2개뿐이다** (route.ts 안에 다른 성공 반환 없음):
- `201` → `{ok:true, candidate:<행 전체>, deduped:false}` (신규 insert)
- `200` → `{ok:true, candidate:<행 전체>, deduped:true}` (동일인 update)
- 실패 `400/401/500` → `{ok:false, error:"..."}`
- `pipeline_candidates.id` 는 `uuid primary key default gen_random_uuid()`

## 2. 이번 작업이 고친 근본 원인

요청은 `build_register_request` 로 엄격 검사하면서 **응답은 검사 함수 자체가 없었다.**
그 비대칭 때문에 "payload 가 사전이 아니다"라고 판정한 직후 같은 `raise` 문에서
`payload.get('error')` 를 불러 `AttributeError` 로 죽었다(계약 오류가 아닌 엉뚱한 예외).

해결: 요청과 **대칭인 순수 함수** `parse_register_response` 를 신설하고,
"모양을 확정하기 전에는 절대 꺼내 쓰지 않는다"를 불변식으로 세웠다.
단 **엄격함의 방향은 비대칭**으로 유지한다 — 요청은 모르는 필드를 거부(E12),
응답은 서버가 칸을 늘려도 멈추지 않도록 관용.

---

## 3. 검증 조항

### S-REQ — 요청 계약 (`build_register_request`)

| # | 조항 | 근거 |
|---|---|---|
| S-REQ-1 | `POST {base}/api/aisearch/register`, 헤더 `x-internal-key` + `content-type: application/json` | route.ts |
| S-REQ-2 | 필수: `name`, `profile_url`(http/https), `match_score`(수, 0~100), `why_fit`, `channel` | route.ts:79~90 |
| S-REQ-3 | `match_score < 60` 은 **전송 전** 거부 | route.ts:87 `MIN_MATCH_SCORE` |
| S-REQ-4 | 선택: `profile_summary`(str), `jd_id`/`jd_title`(비어있지 않은 str), `skills`(list[str]) | route.ts |
| S-REQ-5 | 표 밖 필드는 명시적 거부 (E12 catch-all) | 클라이언트 규율 |
| S-REQ-6 | `internal_key` 는 16자 이상 + 앞뒤 공백 없음 + **호출자 주입**(하드코딩 금지) | internalApiKey.ts:17 |
| S-REQ-7 | `base_url` 은 `https://` 강제 | 보안 |
| S-REQ-8 | 공백 판정은 **JS `String.trim()` 집합** — U+FEFF는 공백, U+0085는 공백 아님 (Python `str.strip()` 기본과 다름) | ECMAScript |

### S-RES — 응답 계약 (`parse_register_response`)

| # | 조항 |
|---|---|
| S-RES-1 | 봉투 검사: `Mapping` 이어야 하고, `status` 는 `int`(bool 제외, **100~599**), `text` 는 `str` |
| S-RES-2 | 파싱 실패(`ValueError`, `RecursionError`)는 `AdminApiResponseError` 로 변환 |
| S-RES-3 | payload 는 **JSON 객체**여야 함 (`null`/배열/문자열/숫자 거부) |
| S-RES-4 | 성공은 `status ∈ {200,201}` **그리고** `ok is True` |
| S-RES-5 | `deduped` 는 **엄격 bool** (`"false"`, `null`, `1` 거부) |
| S-RES-6 | `candidate.id` 가 **비어있지 않은 문자열**이어야 등록 성공 인정 (저장 증거) |
| S-RES-7 | `201 ↔ deduped:false`, `200 ↔ deduped:true` (양방향 일치, 어긋나면 fail-closed) |
| S-RES-8 | 응답에 **모르는 필드가 늘어나도 통과** (전방 호환 — 요청과 반대 방향) |
| S-RES-9 | **오류 메시지에 서버 원문 내용 금지.** 후보 개인정보(이름·연락처)가 로그·원장으로 새면 안 됨 — 타입·크기 등 '모양'만 |
| S-RES-10 | **우리 쪽 내부 결함은 '서버 응답 오류'로 둔갑 금지** (예외 범위를 넓히지 말 것) |

### S-REC — 발송 게이트 (`AdminApiRecorder`)

| # | 조항 | 근거 |
|---|---|---|
| S-REC-1 | 기본 **dry-run** — `live=True` 없이는 전송 0회 | CLAUDE.md 불변식 3 (fail-closed) |
| S-REC-2 | `live` 는 **엄격 bool** (`1`, `"true"` 같은 진리값 오용 거부) | 같음 |
| S-REC-3 | dry-run 과 live 결과가 **같은 타입·같은 속성 집합** (`RegisterOutcome`) | 호출자가 한 코드로 처리 |
| S-REC-4 | 내부키가 **dry-run·live 양쪽** 결과에서 가려짐 | 비밀 유출 방지 |
| S-REC-5 | 계약 위반은 `live=True` 여도 전송 0회 | fail-closed |

### S-ROB — 내구성

| # | 조항 |
|---|---|
| S-ROB-1 | `_describe` / `_describe_shape` 는 **어떤 입력에도 예외를 던지지 않는다** (`repr()`·`len()` 이 터지는 값 포함) |
| S-ROB-2 | 적대적 입력(`.get()` 이 터지는 Mapping, 깊은 중첩 JSON, 거대 정수 status)에서도 **계약 오류만** 나온다 |

### S-TEST — 테스트 품질

| # | 조항 |
|---|---|
| S-TEST-1 | 구현의 **모든 검사(guard) 25개**를 하나씩 무력화하면 각각 **최소 1건 이상 실패**해야 한다 (헛테스트 0건) |
| S-TEST-2 | 조항별로 "어느 검사가 잡았는지"가 구분돼야 한다 (중복 검사도 자기 메시지로 고정) |

---

## 4. ⚠️ 검증 도구 함정 (반드시 읽을 것)

`apps/aisearch/core/admin_api.py` **39행**의 JS 공백 집합 문자열에는 **U+2028(LINE
SEPARATOR)·U+2029(PARAGRAPH SEPARATOR)** 가 들어 있다.

Python 의 `str.splitlines()` 는 이 둘도 줄바꿈으로 쪼개므로, **줄 번호가 2씩 밀린다.**
줄 번호 기반 도구(돌연변이 검사 등)를 만들 때 `splitlines()` 를 쓰면 **엉뚱한 코드를
건드리고도 정상인 것처럼 보고**한다. 실제로 1차 조사가 이 함정에 빠져 결과가 통째로
거짓이었다.

- 반드시 `source.split("\n")` 으로 나눌 것
- 도구가 스스로 "ast 가 말하는 `if` 줄과 내가 자른 줄이 같은가"를 먼저 확인할 것

## 5. 이번 작업의 자체 검증 결과 (재현 대상)

| 항목 | 결과 |
|---|---|
| 대상 파일 테스트 | 110 passed |
| 저장소 전체 `./verify.sh` | 3261 passed, 4 xfailed, 105 subtests, exit 0 |
| 돌연변이 전수 조사 | 검사 25개 전부 잡힘 — 헛테스트 0건 |
| 발견·수정한 결함 | 19건 |

## 6. 의도적으로 **넣지 않은** 것 (반박 환영)

`candidate.id` 의 **UUID 형식 검사는 넣지 않았다.**

- 이유: 저장 증거로는 "비어있지 않은 식별자"로 충분하고, 서버 기본키 타입에 클라이언트를
  묶으면 스키마가 바뀔 때 **정상 등록을 전부 막는다**(과잉 검사가 더 위험).
- 반박하려면: 형식 검사가 막아주는 **현실적인 실패 시나리오**를 제시할 것.
  "서버가 UUID를 준다"는 사실만으로는 근거가 되지 않는다(그건 형식 검사가 불필요하다는
  근거에 가깝다).
