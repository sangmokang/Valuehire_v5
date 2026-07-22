# 구현 지시서 — 디스코드 검색을 "말"에서 "코드"로 (룰베이스 실행기 전환, 2026-07-21)

> 규율: `docs/sot/30-strict-mode-contract.md`(strict) + `docs/harness.md` 게이트 + CLAUDE.md SOT 불변식.
> 등급: **L2**(운영 경로 코드 변경). 단위별 RED→GREEN + `./verify.sh` + 배선 증명 + V1 적대검증 필수.
> 실행 장소: **Claude Code(이 레포)에서 구현** → **Codex가 V1 적대검증** → **Hermes/디스코드에서 라이브 확인**.
> 선행 문서(중복 금지): `docs/prompts/hermes-login-gate-before-search-skills-2026-07-21.md` (로그인 게이트 U1~U6).
> 이 문서는 그 다음 조각 — **워커가 AI에게 부탁하는 대신 스크립트를 직접 돌리게** 만드는 작업이다.

---

## 0. 사장님께 한 줄 (쉬운 말)

지금은 디스코드에서 검색을 시키면, 마지막 순간에 **AI에게 한국어로 "이렇게 해줘"라고 19줄 부탁**하고 끝납니다.
그래서 매번 다르게 움직이고, 로그인도 될 때만 됩니다.
이 작업은 그 부탁을 **정해진 순서대로 도는 프로그램**으로 바꿉니다. AI는 "어떤 검색어로 찾을까"만 정하고,
로그인·검색·페이지 넘김·저장은 전부 코드가 합니다.

---

## 1. 착수 전 확인된 사실 (2026-07-21 실측 · 추측 아님)

| # | 사실 | 증거 |
|---|---|---|
| G1 | 디스코드→큐→머신배정까지는 이미 결정적 코드다 | `ops/hermes-plugin/valuehire_fleet/__init__.py:294-318`, `fleet_dispatch.py`, `job_queue.py` |
| G2 | **결정성이 끊기는 지점은 정확히 한 곳** — 잡 1건이 한국어 규칙 19개 프롬프트로 변환된다 | `fleet_worker.py:187-270` (`build_job_prompt`) |
| G3 | 그 프롬프트는 `claude -p` 또는 `codex exec` 서브프로세스로 넘어간다 | `fleet_worker.py:415-457`, `486-505`, 호출부 `811-813`·`834-847` |
| G4 | **완료 영수증은 모델 자기신고다.** `login_verified`/`saved_receipts`를 모델이 직접 써 넣는다 | `fleet_worker.py:271-300` (`validate_aisearch_receipt`) |
| G5 | 프롬프트 규칙 8번의 "180~420초 랜덤 지연"은 **이미 코드에 있다** — 글로 중복 부탁 중 | `humansearch_cdp_run.py:78` `human_delay(180,420)` |
| G6 | 결정적 순회 러너가 이미 있다: 페이지 넘김·카드 추출·하드제외·사장님 양보·fail-closed 라이브 게이트까지 | `humansearch_cdp_run.py:126-353`, `429`(`assert_live_or_abort`) |
| G7 | **그러나 러너는 링크드인 검색 1건이 상수로 박혀 있다** — 포지션·검색URL 파라미터 없음 | `humansearch_cdp_run.py:38-44`(`SEARCH_URL_BASE`), `:419`(`find_page_by_url("searchContextId=8d792952")`) |
| G8 | 러너 진입점은 `sys.argv[1..2]`(max_profiles·start) 뿐 — argparse 없음 | `humansearch_cdp_run.py:455-458` |
| G9 | 로그인 실행기 + 영수증 파일은 이미 있다 (새로 만들지 말 것) | `portal_login.py:760-805`, 영수증 `artifacts/portal_session_status_latest.json` |
| G10 | 3사 셀렉터 폴백 사전이 이미 있다 | `selectors.py`, `portal_autologin.py:29-90`, `docs/sot/23-channel-dom-selectors.md` |
| G11 | 채점은 이미 결정적 함수다 | `scoring.py`, `humansearch.py` |
| G12 | 머신 레지스트리(머신별 채널 포트·프로필)가 이미 있다 | `search_machine.py:44-120` |
| G13 | 워커는 잡 시작 전 로그인 검증을 **한 번도** 부르지 않는다 | `fleet_worker.py` 임포트 목록(1-40행)에 `portal_login`·`portal_session`·`humansearch_preflight` 없음 |

### 과거 지시 회수 (Gate 0)

- SOT: `26-portal-login-spec.json`(INV1·INV2 자동로그인 의무), `27-humansearch-browsing-preflight.json`(fail-closed),
  `29-fleet-control.md`(INV9 60초 양보·계정↔머신 1:1), `31-fleet-run-reliability.md`(P1~P3 배포 결함).
- 스킬: `skills/disearch/SKILL.md` — 이 경로의 감사 절차 정본. 분류 라벨(LIVE_CONFIRMED/WIRED_IN_REPO/…)을 그대로 쓴다.
- 이미 있는 것: `portal_login.py`, `portal_autologin.py`, `humansearch_cdp_run.py`, `scoring.py`, `selectors.py`,
  `search_machine.py`, `humansearch_preflight.py`. **새 로그인·새 순회·새 채점 구현 금지 — 파라미터화하고 호출만 한다.**
- 재발 원장(R4): "이미 있는 코드를 안 부르고 프롬프트로 다시 부탁" 패턴은 로그인 게이트 문서에서 이미 1회 지적됨.
  **2회째이므로 통제 승격(문서 → 러너) 대상이다.**

---

## 2. 목표 (한 문장)

**디스코드에서 `humansearch`·`aisearch` 잡이 실행될 때, 브라우저를 만지는 모든 동작(로그인·검색어 입력·순회·저장)은
파라미터를 받는 파이썬 러너가 수행하고, LLM은 브라우저 접근 없이 "검색 계획 JSON" 1건만 산출한다.
완료 영수증은 모델이 쓴 문장이 아니라 러너가 쓴 파일이다.**

**비목표(하지 않는다)**: 새 로그인 로직·새 순회 로직·새 채점기 작성, 캡차/2FA 자동 우회, LinkedIn 세션충돌 자동 해결,
`skill=url`·`skill=agent` lane 변경, 게이트웨이 단일화(운영 조치 — §7 참조), 발송 게이트(SOT28) 완화.

---

## 3. 선행 조건 (코드 아님 — 이거 안 하면 아래를 다 해도 증상 동일)

`docs/sot/31-fleet-run-reliability.md` S1·S3. 착수 전 사장님 승인 아래 확인만 하고, 결과를 goal 문서에 기록한다.

1. 디스코드 봇 토큰당 게이트웨이 **1개**인지 (`/fleet-run` 응답이 정확히 1개인지)
2. 3대 머신에 fleet-worker가 떠 있는지 (`fleet-status` heartbeat 나이)
3. 3대 `.env.local` Supabase 열쇠가 각 머신에서 401 없이 통과하는지

**이 3개가 GREEN이 아니면 라이브 검증(§8)이 불가능하므로 단위 착수는 하되 "완료" 선언은 금지한다.**

---

## 4. 작업 분해표 (R1 — 단위 1개 = 인수기준 1개 = 검증 1개 · 단위 관문 R5 적용)

앞 단위가 GREEN이 되기 전 뒤 단위에 착수하지 않는다. diff 예산: 단위당 파일 1~3개 / 50~300줄. 초과 시 멈추고 분할 보고.

| 단위 | 산출물 | 인수 기준 (EARS) | 검증 명령 |
|---|---|---|---|
| **C0** | `humansearch_cdp_run.py` 파라미터화 | 러너가 `--channel`·`--search-url`·`--position-file`·`--max-pages`·`--out` 를 인자로 받으면, 시스템은 상수 `SEARCH_URL_BASE`·하드코딩 탭 검색어를 쓰지 않고 주어진 값으로 동작하며, 인자 누락 시 기본값 추정 없이 **명시적 거부**한다 | `pytest tests/test_humansearch_runner_cli.py -q` |
| **C1** | `tools/multi_position_sourcing/search_plan.py` — 계획 JSON 스키마 + 순수 검증 함수 | 임의 객체가 주어지면 시스템은 `validate_search_plan()`으로 결정적으로 수락/거부하고, 스키마 밖 키·빈 키워드·미지 채널·URL 아닌 값을 **정규화 없이 거부**한다 | `pytest tests/test_search_plan.py -q` |
| **C2** | 계획 생성기 `build_search_plan()` — LLM 1회 호출, **브라우저 도구 없음** | JD/포지션 텍스트가 주어지면 시스템은 LLM에서 계획 JSON을 받아 C1로 검증하고, 검증 실패 시 **1회만** 재요청한 뒤 두 번째 실패는 재시도 없이 중단한다 | `pytest tests/test_search_plan_builder.py -q` |
| **C3** | `tools/multi_position_sourcing/search_orchestrator.py` — 결정적 실행 순서 | 검증된 계획이 주어지면 시스템은 ①로그인 게이트 ②러너 실행 ③결과 파일 산출 ④결정적 채점 순서로만 진행하고, 어느 단계든 실패하면 다음 단계를 시작하지 않는다(fail-closed) | `pytest tests/test_search_orchestrator.py -q` |
| **C4** | `fleet_worker.py` 실행 분기 배선 | 잡의 skill이 `humansearch`·`aisearch`이면 워커는 `build_job_prompt`+`claude -p` 대신 C3을 호출하고, 그 외 skill은 기존 경로를 그대로 쓴다 | `pytest tests/test_fleet_worker*.py -q` |
| **C5** | 영수증 진짜화 (`fleet_worker.validate_aisearch_receipt`) | 완료 판정 시 시스템은 모델이 쓴 `login_verified`/`saved_receipts`를 신뢰하지 않고 **러너가 쓴 결과 파일과 로그인 영수증 파일**로만 참을 인정한다 | `./verify.sh` |

### 배선 지점 (정확한 위치)

- **C4 삽입점**: `fleet_worker.py:811` `prompt = build_job_prompt(job)` **직전**에 skill 분기.
  기존 러너 주입 계약(`self.runner`, `_runner_injected`, `fleet_worker.py:628-629`)을 깨지 않는다 —
  테스트가 러너를 주입하면 기존 경로가 그대로 살아 있어야 한다.
- **C4 예외 처리**: 어떤 예외도 잡을 `running` 고아로 두지 않는다 — `fleet_worker.py:849-853` 의 기존
  fail-closed 규율(QA-7)을 새 분기에도 동일 적용한다.
- **로그인 게이트**: 선행 문서 U1~U3의 `evaluate_login_gate`를 **실행 호스트에서** 호출한다. 새로 만들지 않는다.
  선행 문서가 아직 미구현이면 C3에서 `portal_login.run_portal_login_preflight` + 영수증 판독으로 최소 게이트를 두되,
  선행 문서 병합 후 그 함수로 교체하고 중복 구현을 삭제한다.
- **머신별 값**: 채널 포트·프로필은 `search_machine.require_search_machine(os.environ["VALUEHIRE_MACHINE"])`로 얻는다.
  경로 하드코딩 금지(`fleet_worker.py` 서문 규율과 동일).

---

## 5. 계약 (SDD — 입출력 모양 먼저)

```python
# tools/multi_position_sourcing/search_plan.py
Channel = Literal["saramin", "jobkorea", "linkedin_rps"]

@dataclass(frozen=True)
class ChannelPlan:
    channel: Channel
    search_url: str | None        # 사람이 걸어둔 URL(humansearch). None이면 keywords로 러너가 조립(aisearch)
    keywords: tuple[str, ...]     # 1개 이상, 공백만인 항목 금지
    exclude_keywords: tuple[str, ...]
    min_years: int | None
    max_pages: int                # 1~50. 기본값 추정 금지 — 계획에 반드시 명시

@dataclass(frozen=True)
class SearchPlan:
    job_id: int
    skill: Literal["humansearch", "aisearch"]
    position_url: str
    channels: tuple[ChannelPlan, ...]   # 1개 이상
    plan_sha256: str                    # 계획 원문 해시 — 영수증 대조용

class SearchPlanError(ValueError): ...

def validate_search_plan(raw: object, *, job: Mapping[str, Any]) -> SearchPlan: ...
def build_search_plan(job: Mapping[str, Any], *, llm) -> SearchPlan: ...   # llm 주입(테스트 격리)
```

```python
# tools/multi_position_sourcing/search_orchestrator.py
@dataclass(frozen=True)
class SearchOutcome:
    status: Literal["done", "paused_for_human", "failed"]
    reason: str                  # 기계 판독 코드
    summary_ko: str              # 사장님/디스코드용 한국어 한 줄 (비밀값 금지)
    results_path: str | None     # 러너가 실제로 쓴 파일
    login_receipt_path: str | None
    counts: Mapping[str, int]    # opened / saved / hard_excluded / scored / passers

def run_search_job(job, *, plan, machine, now) -> SearchOutcome: ...
```

**불변식**: 비밀번호·쿠키·토큰은 `summary_ko`·로그·아티팩트 어디에도 넣지 않는다(login SKILL.md §0-8).
계획 JSON은 검색어와 URL만 담는다 — 자격증명·발송 지시를 담을 수 없다(스키마에서 거부).

---

## 6. 입력 영역 표 + 예외 표 (SOT-30 §1-11 ① / R1 ③ — 각 행 = 테스트 1개 이상, 마지막 행 catch-all)

| # | 입력/상황 | 판정 | 행동 |
|---|---|---|---|
| 1 | 정상 계획 + 로그인 영수증 신선 | 수락 | 러너 실행 |
| 2 | LLM이 JSON 아닌 문장 반환 | `PLAN_MALFORMED` | 파싱 시도 1회 재요청, 2회차 실패는 중단 |
| 3 | 계획에 스키마 밖 키 / 미지 채널 / 빈 keywords | `PLAN_INVALID` | 정규화·추정 **금지**, 즉시 중단 |
| 4 | `max_pages` 누락 또는 0/음수/50 초과 | `PLAN_INVALID` | 기본값 채워넣기 금지 |
| 5 | `search_url`이 3사 도메인 밖 | `PLAN_INVALID` | 임의 URL 실행 금지(SSRF·오탐 방지) |
| 6 | 로그인 영수증 없음/오래됨/`ready:false` | `LOGIN_NOT_READY` | 기존 로그인 실행기 **1회** 호출 후 재판정, 2회차 없음 |
| 7 | 캡차·2FA·checkpoint 신호 | `paused_for_human` | 러너 재호출 0회, 창 1회 표면화 + 디스코드 알림 (SOT29 §4) |
| 8 | LinkedIn `multiple sign-ins`·세션충돌 | `AUTH_CONFLICT`(terminal) | 자동 로그인·Continue 클릭·재시도 **0회**, 영구 중단 |
| 9 | 사장님이 3사 포털 화면 조작 중 | 보류 | 무조작 대기, **60초 무이상 시 자동 재개**(SOT29 INV9) — 무기한 중단 코드 금지 |
| 10 | 러너가 0건 반환 | `EMPTY_RESULT` | 성공으로 치지 않음. 셀렉터·로그인·검색어 중 무엇이 원인인지 러너 로그로 구분해 보고 |
| 11 | 러너 중간 크래시 / 타임아웃 | `failed` | 잡을 running 고아로 두지 않고 release(failed) (기존 QA-7 규율) |
| 12 | 결과 파일은 있는데 로그인 영수증이 없음 | `failed` | 영수증 없는 결과는 **채택하지 않는다**(G4 자기신고 재발 방지) |
| 13 | 배정 머신 ≠ 실행 머신 | 거부 | 계정↔머신 1:1(SOT29 §2) — 원격 영수증을 로컬 판정으로 대체 금지 |
| 14 | `VALUEHIRE_MACHINE` 미설정/미등록 | 거부 | `search_machine.require_search_machine`의 fail-closed 사용 |
| 15 | 계획에 발송·InMail·메일 관련 지시가 섞임 | 거부 | SOT28 발송 게이트 — 스키마에 발송 필드 자체를 두지 않는다 |
| 16 | 같은 잡이 두 번 실행됨(재시도·중복 claim) | 거부 | 기존 idempotency/account_lock 재사용, 새 락 신설 금지 |
| 17 | **그 외 전부** | 거부 | 명시적 중단 + 이 표 갱신안 보고 (임의 판단 금지) |

### 결정 목록 (오너 확정 필요 — 코드에 임의 삽입 금지)

1. `aisearch`에서 검색어를 사이트 UI에 넣는 방식: 러너가 URL 조립인가, 폼 입력인가? (채널마다 다를 수 있음)
2. `max_pages` 상한 기본 정책: 프롬프트 규칙 8은 "최소 10페이지 또는 마지막 페이지"였다 — 계획 JSON 필수값으로 옮기되 상한은?
3. LLM 계획 생성기를 어떤 엔진으로 돌릴 것인가(`claude -p` 재사용 vs 직접 API) — 재사용이면 브라우저 도구 차단 방법 명시 필요.

---

## 7. 게이트 절차 (harness / SOT-19)

0. `npm run red-ledger` — RED 있으면 새 작업 금지. **⚠️ 현재 메인 작업트리에 로그인·플러그인 관련 미커밋 변경 10개 파일이 있다** — 착수 전 처리(커밋 or stash)를 먼저 정하고 그 위에 얹지 않는다.
1. 워크트리: `npm run wt -- <issue>-rulebase-search-runner` (임의 `git worktree add` 금지).
2. **RED 먼저**: 단위별로 §6 표의 해당 행을 테스트로 먼저 쓰고, **올바른 이유로** 실패하는 것을 확인한 뒤 커밋.
3. GREEN: 최소 변경. 단위 관문(R5) 준수.
4. 검증: `npm run strict:gate`(있으면) + `./verify.sh` 출력 숫자 그대로 인용 + **라이브 1건**(§8).
5. 배선 증명: "테스트가 import해서 통과"는 배선 아님. 워커 로그에 새 분기 진입 라인 + 러너가 쓴 결과 파일 경로를 첨부.
6. V1 적대검증(Codex, fresh·read-only): 정조준 지시는 §9.
7. SOT diff 동봉: 동작이 `docs/sot/25-ai-search-execution-process.*` / `29-fleet-control.md` 서술을 바꾸면 같은 PR에 반영.

---

## 8. 완료 정의 (전부 ✅ 아니면 "진행 중")

- [ ] 디스코드에서 `/aisearch`(또는 `/fleet-run aisearch`) 1건 → 워커 로그에 **새 결정적 분기 진입** 확인
- [ ] 로그인 안 된 상태 → **검색이 시작되지 않고** 사유가 디스코드로 온다(캡처)
- [ ] 로그인 된 상태 → 러너가 실제로 페이지를 넘기고 결과 파일이 생성된다(파일 경로 + 건수 인용)
- [ ] 같은 명령을 2회 실행했을 때 **같은 계획 해시 → 같은 순서**로 움직인다(결정성 증거)
- [ ] `humansearch_cdp_run.py`에 포지션·검색URL 상수 하드코딩 참조 0건
- [ ] 완료 영수증이 모델 문장이 아니라 러너 산출 파일로 판정된다(모델이 거짓 영수증을 써도 실패하는 테스트 존재)
- [ ] §6 표 17행 전부 테스트 존재, `./verify.sh` exit 0 (숫자 그대로)
- [ ] 새 창 0개·새 탭 0개·브라우저 종료 0건·프로필 삭제 0건 (login SKILL.md §0)
- [ ] 비밀값이 메시지·로그·아티팩트 어디에도 없다
- [ ] V1(Codex) 판정 본문 확보 — 경로 + agentId

---

## 9. V1 적대검증 정조준 (Codex에게 그대로 전달)

`/codex:adversarial-review --fresh` (fresh 세션 · read-only). 산출물(코드 + 인수기준 + 증거)만 전달한다.

1. §6 표 **17행 밖의 현실 입력**이 존재하는가? (특히 채널별 DOM 변경, 부분 로딩, 세션이 순회 도중 만료되는 경우)
2. 결정적 분기를 **우회해 옛 `claude -p` 경로로 되돌아가는** 조건이 남아 있는가? (러너 주입 플래그, params.agent, 예외 폴백)
3. 영수증 대조가 **모델이 파일을 직접 써서** 우회 가능한가? (러너 산출물과 모델 산출물의 경로가 분리돼 있는가)
4. 실패 시 **조용히 통과(fail-open)** 하는 분기가 있는가? 특히 `except Exception` 뒤 계속 진행하는 곳.
5. SOT29 INV9(60초 자동 재개)를 **영구 중단으로 바꿔버리는** 코드가 새로 생겼는가?
6. 잡이 `running` 고아로 남는 새 경로가 생겼는가? (러너 크래시·타임아웃·release 실패)
7. "결정적"이라는 주장이 과장인가 — 실제로 남아 있는 비결정 요소를 전부 열거하라.
