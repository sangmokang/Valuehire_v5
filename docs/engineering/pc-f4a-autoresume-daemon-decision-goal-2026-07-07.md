# PC-F4a — 자동재개 데몬 순수 결정함수(idle→resume·페이크 실행자 호출횟수 경계) · 구현 킥오프

> 새 세션에 이 내용을 붙여넣어 `/st` 로 착수. **한 조각 = 한 worktree = 인수기준 1개.**

---

## /st PC-F4a(자동재개 데몬 순수 결정함수) 구현한다. 과거회수부터 하고 착수해라.

### ⚠️ 먼저 — "이미 반쯤 되어 있음"(silently already-done) 판정
착수 전에 **아래를 사실로 인정하고 시작**해라. PC-D2b/K6 처럼 이미 병합된 코드를 모르고 재구현하면 게이트 위반이다.

- **한-tick 짜리 idle→resume 방향은 이미 구현·병합됐다.** `harvest_driver.py:50-64` `decide_tick` 이 `run == not compute_yield_decision(...)` 로 이번 tick 을 돌릴지 결정하고, **재개 사유 문자열까지 이미 있다** — `harvest_driver.py:64` `TickDecision(run=True, reason="owner idle — resume live cycle")`. 즉 "사장님이 손 떼면(idle) 이번 tick 은 돌린다"는 **단일 tick 재개 결정은 PC-D2b(PR#67)로 이미 GREEN**이다.
- 그러므로 F4a 는 "재개 방향을 새로 만드는" 조각이 **아니다**. F4a 가 실제로 더하는 것은 **여러 tick 에 걸친 yield→(대기)→resume 루프 결정**과, **재개 순간의 anti-bot 간격 합성(PC-E1)**, 그리고 **재개 경계에서의 페이크 실행자 호출횟수 단언**뿐이다. 이 세 가지는 리포에 **아직 없다**(grep `decide_resume|resume_after|resume_decision|wait_ticks` → 0건, 2026-07-07 실측).
- **결론: F4a 는 열려 있다(genuinely open). 단, 아주 얇다** — decide_tick(PC-F1) 위에 PC-E1 페이싱을 얹는 합성 한 겹. 아래 "근본 원인"에서 "폴딩 권고"까지 읽고, 얇게 유지해라(새 판단 로직 재구현 금지).

### 저장소 / SOT (먼저 읽어라)
- 저장소: `/Users/kangsangmo/Valuehire_v5` (main). 규칙 `CLAUDE.md`, 루프 `docs/harness.md`, 장부 `.harness/red-ledger.tsv`.
- 백로그: `docs/engineering/valuehire-pipeline-consolidation-backlog-2026-07-01.json` PC-F4a(line 554-569).
- 선행 goal: `docs/engineering/reservoir-harvest-driver-goal-2026-07-04.md`(PC-D2b — decide_tick/drive_cycle_once 도입), `docs/engineering/pc-k6-daemon-crashloop-goal-2026-07-04.md`(데몬 경로).
- 착수 전 `make red-ledger`(clean 확인) + `git worktree list`(다른 세션 파일 안 건드림).

### 위험등급 · 모드
- **code-change · L3** (자동재개 = R4 자동재개 SOT 불변식 + SOT2 봇 금지 — 재개 순간 URL 연타·무한재시도로 봇처럼 굴면 안 됨). 풀하네스: worktree → RED→GREEN → G→V1(Codex)+V2(리셋 Claude) **병렬** → `docs/engineering/pc-f4a-autoresume-daemon-decision.verdict.json` 3자 증거.
- 단, **이 조각은 순수 결정함수만**이다. 실제 상주 데몬 구동은 PC-F4b(수동 verdict). "완료"는 기계검증 부분에 한한다.

### 현재 상태 (직접 연 file:line — 2026-07-07 실측)
**있는 것(재사용 대상 — 재구현 금지):**
- `tools/multi_position_sourcing/harvest_driver.py:37-39` `resolve_repo_dir()` — 모듈 위치에서 checkout 루트 파생(`Path(__file__).resolve().parents[2]`), env/HOME/Desktop 미참조. **F4a2 몫이지 F4a 몫 아님**(백로그 acceptance 명시). 이 조각에서 REPO_DIR 새 함수 만들지 마라 — 이미 있다.
- `harvest_driver.py:42-64` `TickDecision`(frozen) + `decide_tick(...)` — 한 tick run/yield 결정. `:56-64` `run == not compute_yield_decision`. `:64` 재개 사유 `"owner idle — resume live cycle"` **이미 존재**.
- `tools/multi_position_sourcing/owner_activity.py:42-59` `compute_yield_decision(*, frontmost_is_chrome, os_idle_seconds, idle_threshold_seconds=180.0)` — 크롬 앞창 OR idle<threshold → yield=True, idle=None → fail-closed yield. **양보/재개 판단의 단일 출처(PC-F1, PR#55 GREEN)**.
- `tools/multi_position_sourcing/harvest_policy.py:92-102` `deterministic_delay_ms(*, kind, step, seed)` — [min,max] 안 결정론 지터(재시작 재현). `:110-116` `should_continue_pacing(*, step, max_steps=None)` — step>=cap 정지(URL 연타·무한재시도 차단). `:105-107` `max_keyword_steps()` — SOT22 캡. **anti-bot 페이싱 단일 출처(PC-E1, PR#57 GREEN)**.
- `harvest_driver.py:67-88` `drive_cycle_once(...)` — 한 tick 라이브 사이클(segments→큐→`arun_harvest_cycle`). **F4a 의 "한 tick 실행" 단위가 이것**이다.

**없는 것(F4a 가 채울 이음매):**
- **여러 tick 에 걸친 resume 루프 결정 함수** — grep `decide_resume|resume_after|resume_decision|wait_ticks|yield_then` → 0건(2026-07-07). decide_tick 은 **기억이 없다**(memoryless, 한 tick). yield→대기→재개 전이를 순수함수로 낸 것이 없다.
- **재개 순간 anti-bot 간격 합성** — decide_tick 은 페이싱을 **일절 건드리지 않는다**(harvest_driver.py 안에 `deterministic_delay_ms`/`should_continue_pacing` 호출 0건). 백로그 acceptance (3) "anti-bot 간격(PC-E1 재사용)"이 미충족.
- **재개 경계 호출횟수 단언** — 기존 테스트는 **한 사이클 안** 호출횟수만 본다: `tests/test_harvest_driver.py:74-101`(segments2×sites2 → 정확히 4회), `:104-124`(owner_activity_detected=True → 0회). **yield tick 들 동안 0회 → 재개 후 정확히 N회, 재개 경계에서 중복실행 0**을 보는 다중-tick 경계 단언은 없다.

### 근본 원인 (왜 F4a 가 별도로 필요한가 / 어디까지만 필요한가)
저수지 드라이버(PC-D2b)는 **한 tick** 을 완성했다: "지금 양보냐 재개냐"(decide_tick)와 "재개면 한 사이클 돌린다"(drive_cycle_once). 하지만 상주 데몬은 **시간축**에서 산다 — 사장님이 크롬을 쓰는 동안 여러 tick 을 양보하다가, 손을 떼면 **다시 이어서** 돈다(R4 자동재개). 이 "양보 구간 → 재개" 전이를, 그리고 재개할 때 **봇처럼 즉시 두드리지 않도록 PC-E1 간격을 끼우는 합성**을, 순수함수로 못박은 것이 없다. F4b(실 데몬)가 이 결정을 소비하기 전에, **시계·OS·포털 없이 결정론으로 기계검증**되어야 하는 부분이 정확히 F4a 다.

**폴딩 권고(정직하게):** F4a 가 더하는 로직은 얇다 — decide_tick(있음) + should_continue_pacing/deterministic_delay_ms(있음)의 **합성 한 겹 + 다중-tick 경계 단언**. 그럼에도 **F4b 로 접지 말고 별 조각으로 유지**하기를 권한다. 이유: 재개 경계 호출횟수·간격은 **상주 데몬 없이 기계검증 가능한 유일한 지점**이고, F4b 는 수동 verdict(실 부팅)라 여기서 못박지 않으면 회귀 봉인이 사라진다. 단, 새 판단식을 만들지 말고 **기존 두 순수 출처의 합성**으로만 구현해라(재구현하면 게이트 위반).

### 계약 (SDD — 손대기 전에 박아라)
```python
# tools/multi_position_sourcing/harvest_driver.py (추가 — 새 파일 만들지 마라, 같은 모듈에 얹어라)

@dataclass(frozen=True)
class ResumeDecision:
    """양보 구간 뒤 이번 tick 에 재개할지 + 재개 시 삽입할 anti-bot 간격(ms) + 사유."""
    resume: bool
    delay_ms: int          # resume=False 면 0. resume=True 면 PC-E1 deterministic_delay_ms 결과.
    reason: str

def decide_resume(
    *,
    frontmost_is_chrome: bool,
    os_idle_seconds: float | None,
    ticks_yielded: int,               # 직전까지 연속 양보한 tick 수(0=방금까지 돌던 중)
    seed: int,                        # run_id 해시 등 — 재현 가능한 지터
    idle_threshold_seconds: float = DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS,
    pacing_kind: str = "short",
) -> ResumeDecision:
    """PC-F1 decide_tick 로 재개여부 판단(재구현 금지) → 재개면 PC-E1 로 간격 합성.

    - resume == decide_tick(frontmost_is_chrome, os_idle_seconds, ...).run  (단일출처)
    - resume=True 면 delay_ms = deterministic_delay_ms(kind=pacing_kind, step=ticks_yielded, seed=seed)
      → 손 떼자마자 0ms 로 두드리지 않는다(SOT2 봇 금지). ticks_yielded 를 step 으로 써
      매 재개가 같은 간격이 되지 않게(고정 간격 = 봇 신호) 흩는다.
    - resume=False 면 delay_ms=0, reason 은 decide_tick 사유 그대로(양보).
    """
```
**불변식:**
- 순수함수 — 시계/OS/포털/네트워크 미접촉. 입력만으로 결정(결정론).
- **PC-F1 단일출처 재사용**: 재개여부는 `decide_tick`(→ `compute_yield_decision`)만 쓴다. 크롬 앞창/idle 임계 판단을 **재구현하지 않는다**.
- **PC-E1 단일출처 재사용**: 간격은 `deterministic_delay_ms`/`should_continue_pacing`만 쓴다. delay 상수 하드코딩·새 지터식 금지(SOT5, SOT22 이중정의 금지).
- **REPO_DIR·라이브 경로 선택은 F4a 범위 밖**(백로그 acceptance 명시 → PC-F4a2). 이 조각에서 `resolve_repo_dir` 새로 만들거나 executor fake/live 선택 로직 추가 금지.

### 인수 기준 (기계 단언 — verify.sh exit 0)
새 pytest(예: `tests/test_autoresume_decision.py`):
1. **idle→재개**: `frontmost_is_chrome=False, os_idle_seconds>=180` → `resume=True`, `delay_ms>0`(PC-E1 경계 [min,max] 안), 사유에 resume 취지.
2. **크롬 점유→양보(PC-F1 재사용)**: `frontmost_is_chrome=True` → `resume=False, delay_ms=0`, idle 무관. `os_idle_seconds=None` → fail-closed `resume=False`.
3. **anti-bot 간격(PC-E1 재사용)**: `decide_resume` 의 `delay_ms` 가 `deterministic_delay_ms(kind, step=ticks_yielded, seed)` 와 **정확히 일치**(직접 호출 결과와 ==). `_SOT22_PATH` monkeypatch 로 상수 조작 시 delay 도 따라 변함(하드코딩 뮤턴트 RED — anti-bot-pacing.verdict.json 의 V1 지적 재현).
4. **재개 그리드 단일출처**: `decide_resume(...).resume == decide_tick(...).run` 를 (chrome × idle{None, <180, >=180}) 전 그리드에서 단언(로직 드리프트 0).
5. **페이크 실행자 호출횟수 경계(핵심 델타)**: 다중-tick 하네스에서 —
   - 양보 구간 K tick 동안 주입 페이크 실행자 호출 **정확히 0회**(전 레코드 skip).
   - 재개 tick 1회에서 `drive_cycle_once` 경유 **정확히 segments×sites 회**(예 2×2=4), 재개 경계에서 **중복실행 0**(양보했던 사이클을 처음부터 다시 돌리지 않음 — 봇 금지).
   - 재현: 기존 `tests/test_harvest_driver.py:74-101`(사이클 내 4회)·`:104-124`(yield 0회) 패턴을 **재개 경계로 확장**, 로그 문구 아닌 호출 기록으로 단언.
6. **결정론/재현**: 같은 (frontmost, idle, ticks_yielded, seed) → 같은 `ResumeDecision`. `PYTHONHASHSEED` 다른 3프로세스에서 `delay_ms` 동일(PC-E1 32bit 믹서 재현성 상속).
7. `./verify.sh` exit 0 (baseline 954 passed·3 xfailed + 신규 — PC-D2b 시점 954, 착수 시 `make red-ledger`로 현재 baseline 재확인).

### 주관 단언(수동 verdict 몫 — 이 조각 아님)
- 실제 상주 데몬이 손 떼면 자동재개하고 크롬 점유 시 양보하는 **실 부팅 관측**은 PC-F4b(사장님 맥 수동). F4a 는 순수 결정만 기계검증 — "완료"는 기계검증 부분에 한한다고 명시.

### 적대검증 정조준
- **페이크 GREEN**: `decide_resume` 가 delay 를 상수로 반환하면서 테스트만 통과하는가 → 기준3(SOT22 monkeypatch 로 delay 연동 강제)로 봉인.
- **PC-F1 드리프트**: 재개여부를 decide_tick 안 거치고 자체 판단하면 기준4 그리드가 잡는다.
- **재개 경계 중복실행**: 양보 후 재개 시 큐를 처음부터 다시 밀어 사이트를 두 번 두드리는가(SOT2 봇) → 기준5 "중복실행 0".
- **고정 간격**: `ticks_yielded`(step)와 무관하게 매 재개가 같은 delay 면 봇 신호 → step 을 지터에 실제로 반영하는지 단언.
- **고아**: `decide_resume` 가 실제로 소비되는가 — 이 조각은 seam(소비자는 F4b). goal 에 "staged seam, 소비 PC-F4b" 명시하고 verdict 잔여리스크에 적는다.

### 비범위
- 실 상주 데몬 구동·launchd plist/`valuehire-search-loop.sh` 교체(**PC-F4b/K6**).
- REPO_DIR 해석 함수 신설·라이브 경로(fake/live) 선택(**PC-F4a2** — 이미 `resolve_repo_dir` 있음, 선택 로직은 F4a2).
- detector→라이브 러너(humansearch_cdp_run) 배선(**PC-F2**).
- segment→keyword 사전, playwright 라이브 러너 팩토리 실구동(**PC-F4b**).

### ⛔ 안전 (SOT)
- **R4 자동재개는 기본 ON.** 재개 결정을 끄는 기본값을 넣지 마라 — 손 떼면 이어서 도는 게 SOT 불변식②(잠깐 양보·자동재개). 단 재개는 **사람처럼**: 0ms 즉시 두드림 금지, PC-E1 간격 필수(봇 금지).
- **크롬 점유 시 즉시 양보**(SOT 불변식②) — `frontmost_is_chrome=True`면 idle 무관 resume=False. 로그인된 크롬 kill 금지(이 조각은 순수함수라 브라우저 미접촉이지만, 데몬 소비 시 원칙).
- **3사 자동로그인 안 막음**(불변식①) — 이 결정함수는 로그인 흐름을 건드리지 않는다.
- **발송 자동 금지**(불변식③) — 무관하지만 파이프라인 원칙. 재개가 제안 발송을 자동으로 누르는 경로로 이어지지 않게.
- **데몬 자동 load/start 금지** — 이 조각은 테스트만. 실 부팅은 PC-F4b 사장님 수동.

### 환경 함정 (실측)
- 검사 인터프리터 `/Users/kangsangmo/Valuehire_v5/.venv/bin/python`(websocket 보유). `.venv-playwright`는 collection 깨짐 — 쓰지 마라.
- worktree 실행: `PYTHONSAFEPATH=1 PYTHONPATH=<worktree> <repo>/.venv/bin/python -m pytest <worktree>/tests/ -q`.
- CI 는 websocket 미설치 — 러너 import 는 raw_cdp **지연 import** 로 통과. 신규 파일 최상단에 websocket 계열 import 넣지 마라(harvest_driver 는 이미 지연 import 관례).
- 이 조각은 순수함수라 OS/포털 미접촉 → CI 안전. `deterministic_delay_ms` 재현성은 `PYTHONHASHSEED` 무관(32bit 믹서, harvest_policy.py:83-89) — 3프로세스 동일값으로 단언.
- Codex(V1): placeholder 자주 반환(transcript jsonl `tasks/<agentId>.output` tool_result 본문으로 verdict 확인) · 워크트리 직접쓰기 차단(뮤테이션은 `/private/tmp` 복사본에서).

### 적용 게이트
harness 0~6 + **gate4b: G(자기 mutation) → V1(Codex) + V2(리셋 Claude) 병렬** → `docs/engineering/pc-f4a-autoresume-daemon-decision.verdict.json` 3자 증거.
- 뮤테이션 표적: delay 상수화(간격 무력화)·decide_tick 우회(자체 판단)·재개 경계 중복실행·step 지터 무시·fail-closed 반전.
- Codex 막히면(이 환경 'Operation not permitted') V1 을 fresh Claude 서브에이전트 적대검증으로 대체(MEMORY 규칙), 본문 verdict 확인.

### 의존성 리스크 (착수 판단)
- **PC-F1(PR#55)·PC-E1(PR#57) 병합 완료** — F4a 가 재사용할 두 순수 출처 준비됨. 착수 가능.
- **PC-D2a 는 red-ledger 에 GREEN 없음(status None)** — 그러나 그 산출물(`decide_tick`·`resolve_repo_dir`)은 **PC-D2b(PR#67)로 이미 harvest_driver.py 에 착지**. F4a 가 필요한 decide_tick 은 존재하므로 **de-facto 충족**. (PC-D2a 의 미착지분은 "주기(cadence) 산출" 순수함수 — F4a acceptance 는 cadence 불요구, 무관.) 이 "장부엔 없지만 코드엔 있음"을 착수 노트에 남겨라.
- **PC-F2 는 미착수(status None)** 이고 F4a 의 depends_on 에 있으나, **순수 결정층 F4a 는 PC-F2 의 라이브 배선을 실제로 필요로 하지 않는다** — PC-F2 는 detector→라이브 러너 배선(live), F4a 는 순수함수. depends_on 이 **과선언**돼 있다. 실제 소비 의존은 F4b. 착수 막지 말고, verdict 잔여리스크에 "PC-F2 미배선 = 실 데몬 소비는 F4b 대기"로 명시.

### ⭐ 마지막에 — 전체 프로세스 상세 브리핑(recap) 필수
끝낼 때 사장님께 쉬운 한국어로: ①무엇을 만들었나(파일·PR번호·`decide_resume` 한 겹) ②왜(사장님 손 떼면 다시 이어서 도는 결정을, 봇처럼 즉시 두드리지 않게 간격까지 붙여 못박음) ③**어떻게 검증했나 — G/V1(Codex)/V2(리셋 Claude) 각 검증자가 실제로 잡은 결함과 수정 구체적으로** ④증거 숫자 그대로(예: "검사 다 통과, N개") ⑤남은 것(실제 자동재개 데몬 구동은 PC-F4b 에서 사장님 맥 수동 확인, REPO_DIR/라이브경로 선택은 F4a2) ⑥재개 명령. 과장·"아마도" 금지.
