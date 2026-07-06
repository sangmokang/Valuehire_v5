# PC-F2 — detector→라이브 러너(humansearch_cdp_run) R4 배선 + multipos/preflight 회수 · 구현 킥오프

> 새 세션에 이 내용을 붙여넣어 `/st` 로 착수. **한 조각 = 한 worktree = 인수기준 1개.**
> 상태: **open (미착수 — 라이브 러너에 detector 미배선).** ⚠️ 선행 **PC-C3b 미완** — 아래 「선행 리스크」 먼저 읽어라.

---

## /st PC-F2(라이브 러너 R4 배선) 구현한다. 과거회수부터 하고 착수해라.

### 저장소 / SOT (먼저 읽어라)
- 저장소: `/Users/kangsangmo/Valuehire_v5` (main). 규칙 `CLAUDE.md`, 루프 `docs/harness.md`, 장부 `.harness/red-ledger.tsv`.
- 백로그 정의: `docs/engineering/valuehire-pipeline-consolidation-backlog-2026-07-01.json` **PC-F2**(:525) — `requirement_ids:[R4]`, `depends_on:[PC-F1, PC-C3b]`, worktree `task/humansearch-r4-wiring`.
- 선행(완료): **PC-F1** = `owner-activity-detector`(PR#55 merged, squash `8537496`, `owner-activity-detector.verdict.json`) — 순수 detector 병합됨.
- 선행(**미완**): **PC-C3b**(backlog:319, 전수조사 하드캡 제거+다중페이지) — 장부에 GREEN 행 없음. 아래 「선행 리스크」.
- 착수 전 `make red-ledger`(clean 확인) + `git worktree list`(humansearch 계열 다른 세션 작업 중인지 — 같은 파일 충돌 회피).

### 위험등급 · 모드
- **code-change · L3** — 라이브 무인 러너에 R4(양보·자동재개) 첫 강제 배선. SOT 불변식(①3사 자동로그인 안 막음 ②크롬 점유 양보·자동재개 ③발송 자동금지)에 직접 닿음. 풀하네스: worktree → RED→GREEN → G→V1(Codex)+V2(리셋 Claude) **병렬** → verdict.json 3자.

### 현재 상태 (직접 연 file:line — 이번 조사에서 확인)
**detector 는 이미 있고, Harvest(저수지) 경로엔 배선됐지만, 라이브 humansearch 러너엔 미배선.** 즉 F2 는 미착수.

- `tools/multi_position_sourcing/owner_activity.py:42` — 순수 `compute_yield_decision(*, frontmost_is_chrome, os_idle_seconds, idle_threshold_seconds=180)`(PC-F1). `:97` `detect_owner_activity_snapshot(...)` OS 읽기→순수계약 위임. `:141` `detect_owner_activity(**kwargs)->bool`. **병합 완료, 소비처 대기 중.**
- `tools/multi_position_sourcing/harvest_policy.py:38` — `worker_should_yield(*, owner_activity_detected)->bool` 계약(R4). **owner_activity 는 이 계약으로만 소비하기로 PC-F1 docstring(:9~10)에 명시.**
- **이미 배선된 소비처(Harvest 경로 — 이번 조각 대상 아님):**
  - `tools/multi_position_sourcing/harvest_driver.py:32-33` import, `:57` `compute_yield_decision` 로 `decide_tick`, `:153` `detect_owner_activity_snapshot()` 로 CLI 기본 owner-check ON(PC-D2b).
  - `tools/multi_position_sourcing/harvest_runner.py:18` import, `:169`·`:260` `worker_should_yield(...)` 게이트.
  - `tools/multi_position_sourcing/queue_runner.py:71-72` owner_activity 이유로 STOP.
- **미배선 = 이번 조각 대상 (라이브 humansearch 러너):**
  - `tools/multi_position_sourcing/humansearch_cdp_run.py` — **`owner_activity`/`compute_yield_decision`/`worker_should_yield` import·호출 0건**(grep 실측: NONE). 
  - `humansearch_cdp_run.py:250 main()` 순회 루프(`:265` `for i, card in enumerate(cards[:max_profiles], 1)`)는 프로필을 1건씩 열며(`:267` `process_profile`) **양보 판단을 전혀 하지 않는다.** 유일한 라이브 게이트는 `:262` `assert_live_or_abort(tab)`(preflight, 1회·순회 시작 전).
  - `:67` `human_delay(20~45s)` 딜레이는 있으나 이는 페이싱일 뿐 R4(사장님 크롬 점유 감지→양보)가 아니다.
- **캡차 STOP 은 preflight 에만 존재:** `humansearch_preflight.py:139` `captcha` 프로브 + `:89`/`:106` `no_captcha` 체크 → `:155` ok=False 면 `PreflightError`. 그러나 이는 **순회 시작 전 1회**뿐 — 순회 도중 캡차/세션락이 뜨면 잡지 못한다. PC-F2 인수기준의 "캡차 감지 시 STOP" 은 **순회 루프 안**을 요구한다.

### 근본 원인
PC-F1 이 detector 를 순수 계약으로 만들어 뒀지만(seam), **라이브 humansearch 러너는 아직 그 seam 을 소비하지 않는다.** Harvest 경로(PC-D2b)만 배선됐고, 사장님이 실제로 손으로 돌리는 `humansearch_cdp_run` 라이브 순회는 여전히 사장님 크롬 점유와 무관하게 프로필을 계속 연다 — R4(SOT2) 위반 가능. 또 preflight 캡차 게이트가 "시작 전 1회"라 순회 도중 뜬 캡차/세션락은 봇처럼 계속 두드릴 위험이 남는다.

### ⚠️ 선행 리스크 — PC-C3b 미완 (착수 판단 먼저)
- backlog 상 PC-F2 `depends_on` 에 **PC-C3b**(전수조사 — `cards[:max_profiles]` 하드캡 제거 + `collect_cards` `&start` 다중페이지 순회) 포함(:533-536).
- **PC-C3b 는 장부에 GREEN 행이 없다**(`grep C3b .harness/red-ledger.tsv` → 0건). PC-C3a(러너면 하드제외)는 PR#58 로 완료됐으나 **C3b(다중페이지 순회)는 미완.**
- 두 조각은 **같은 파일(`humansearch_cdp_run.py`)의 같은 순회 루프**를 만지고 **같은 reuse_branch(`task/humansearch-multipos`)** 를 회수 대상으로 한다(backlog:30 — "C3a/C3b/F2 회수 대상"). C3b 가 `cards[:max_profiles]` 하드캡을 다중페이지 순회로 바꾸는 순간, F2 가 넣을 "각 프로필 전 양보" 지점의 루프 형태가 바뀐다.
- **판단 3택 (착수 세션이 사장님/오케스트레이터에 확인):**
  1. **C3b 먼저 닫고 F2 착수**(정석 — depends_on 준수). 권장.
  2. **F2 를 단일-페이지 순회 기준으로 먼저 배선**하되, 양보 지점을 "카드 순회 루프의 매 프로필 직전"이라는 **루프-형태 불변 지점**에 두어 C3b 의 다중페이지화가 F2 배선을 깨지 않게 설계(회귀 테스트로 고정). C3b 는 별 조각으로.
  3. **C3b+F2 를 한 worktree 에서 순서대로**(원자성 분할 포기) — 인수기준 1개 원칙 위반이라 비권장.
- 어느 쪽이든 **verdict 잔여리스크에 PC-C3b 상태를 명시**하고, F2 테스트는 C3b 병합 후에도 GREEN 유지되게 루프-불변 지점에 배선한다.

### 계약 (SDD — 손대기 전에 박아라)
```python
# tools/multi_position_sourcing/humansearch_cdp_run.py (배선; 재구현 금지·PC-F1/preflight 재사용)

# (1) 양보 판단 — 순수계약 재사용. 러너는 스냅샷을 읽어 worker_should_yield 로만 소비.
from tools.multi_position_sourcing.owner_activity import detect_owner_activity_snapshot
from tools.multi_position_sourcing.harvest_policy import worker_should_yield
# 주입 가능해야 테스트가 결정론이 된다 — main()·process 루프에 detector 콜러블을 파라미터로:
def main(max_profiles=25, start=0, *, owner_snapshot=detect_owner_activity_snapshot) -> None: ...

# (2) 순회 루프(:265 근처) — 각 프로필 open 직전에 양보 체크:
#   snap = owner_snapshot()
#   if worker_should_yield(owner_activity_detected=snap.owner_activity_detected):
#       log("R4 yield — 사장님 크롬 점유 감지, 순회 양보(정지)"); break  # 봇처럼 반복 재시도 금지(SOT2)
#   → 이미 저장된 results.json 은 보존(부분 결과 유지), 남은 카드는 두드리지 않는다.

# (3) 순회 도중 캡차/세션락 STOP — preflight 프로브를 루프 안에서도 1회씩(또는 N건마다):
from tools.multi_position_sourcing.humansearch_preflight import assert_live_or_abort, PreflightError
#   process_profile 후(또는 카드 open 후) assert_live_or_abort(tab) 로 재확인 →
#   PreflightError(캡차/세션충돌/로그인리다이렉트/결과0) 면 잡아서 즉시 break·사유 로그(재네비 금지).
```
- **재구현 금지(SOT5):** 양보 결정은 `compute_yield_decision`/`worker_should_yield` 단일출처만. 캡차 판정은 `humansearch_preflight` 단일출처만. 러너는 *배선*만.
- **detector 주입 파라미터**로 만들어 테스트가 OS 를 읽지 않고 결정론으로 양보/재개/STOP 경로를 찌를 수 있게 한다(harvest_driver 의 `--skip-owner-check`·주입 패턴 선례 일치).

### 인수 기준 (기계 단언 — verify.sh exit 0)
새 pytest(예: `tests/test_humansearch_r4_wiring.py`), 가짜 tab + 주입 detector 로:
1. **양보:** `owner_snapshot` 이 `owner_activity_detected=True`(크롬 앞창) 를 반환 → 순회 루프가 프로필을 **0건(또는 그 시점 이후 0건) open**, `results.json` 은 그때까지분 보존, 로그에 R4 양보 기록. 로그 문구가 아니라 **process_profile 호출 횟수**로 단언.
2. **재개:** `owner_activity_detected=False`(사장님 자리 비움, idle≥180) → 순회 정상 진행(카드 수만큼 open).
3. **단일출처 일치:** 러너의 양보 판단이 `worker_should_yield(compute_yield_decision(...))` 와 전 그리드 일치(재구현 아님 — 심볼 참조 단언).
4. **순회 도중 캡차 STOP:** 가짜 tab 이 K번째 프로필 후 캡차/세션락 프로브를 반환 → `assert_live_or_abort` 가 `PreflightError` → 루프 즉시 break, 남은 카드 미접근(재네비게이션 0회 — 봇 금지), 사유 로그.
5. **루프-불변(C3b 대비):** 양보 체크가 "매 프로필 직전" 지점에 있어, `cards[:max_profiles]` 하드캡이 다중페이지 순회로 바뀌어도(PC-C3b) 배선이 유효하다는 회귀 단언(가능하면 순회 소스를 함수로 추출해 단일-페이지/다중-페이지 양쪽에서 같은 게이트 통과).
6. `./verify.sh` exit 0 (baseline 참고: 최근 전체 스위트 **977 passed + 4 xfailed**, PC-K6 시점 — 착수 시 `make red-ledger`·`./verify.sh` 로 현재 baseline 재확인 후 +신규).

### 주관 단언(수동 verdict 몫)
- 실제 사장님 크롬 점유 감지→라이브 양보→손 떼면 자동재개의 **엔드투엔드 실동작**은 기계검사 완결 불가(OS 앞창/idle 실측 필요) — 순수 결정·배선만 기계검증, 실운영 관측은 수동으로 남긴다("완료" 아님 명시). 자동재개 데몬 결정은 PC-F4a/F4a2 몫.

### 적대검증 정조준
- **페이크 GREEN:** 테스트가 로그 문자열만 보고 실제로는 프로필을 계속 여는데 통과하지 않게 — `process_profile` 호출 횟수(부작용)로 단언.
- **양보 지점 오배치:** 양보 체크를 순회 시작 전 1회만 두면 순회 도중 사장님이 크롬을 켜도 못 멈춘다 → 반드시 **매 프로필 직전** 루프 안.
- **단일출처 우회:** 러너가 `if frontmost_is_chrome:` 같은 로직을 재구현하면 SOT5 위반 — `compute_yield_decision`/`worker_should_yield` 심볼 참조를 강제(뮤테이션: 재구현하면 detector 규칙 변경이 러너에 반영 안 됨을 잡는 테스트).
- **fail-open 사고:** detector 예외/None 스냅샷 시 러너가 계속 돌면 SOT2 위반 — `owner_activity` 는 감지 실패=fail-closed 양보(True)로 이미 설계됨(`owner_activity.py:53`·`:119`·`:122`). 러너가 그 True 를 실제로 양보로 쓰는지 단언.
- **캡차 재시도 루프:** 순회 도중 캡차 STOP 후 러너가 같은 URL 을 재네비게이션하면 봇(SOT2) — break 후 재접근 0회 단언.
- **C3b 충돌:** F2 배선이 `cards[:max_profiles]` 하드캡 형태에 못박혀 있으면 C3b 다중페이지화가 배선을 깬다 → 루프-불변 지점 + 회귀 테스트(인수기준 5).
- **고아 아님:** 배선이 실제 실행 경로(`__main__`→`main`→순회 루프)에 닿는지 확인(harvest_driver 처럼 CLI 진입까지).

### 비범위
- **PC-C3b**(다중페이지 전수조사) 자체 구현 — 선행 조각(위 「선행 리스크」). F2 는 배선만, 하드캡 제거는 C3b.
- 자동재개 데몬 순수결정(PC-F4a)·라이브 경로 선택(PC-F4a2)·launchd 실부팅.
- Harvest 경로 detector 배선(이미 PC-D2b 로 완료).
- ai-search-pipeline-wip `portal_worker` 살베지의 러너 품질 개선(회수 확인만; 별 조각이면 사장님 확인).
- 라이브 포털 러너 팩토리 실구동(PC-F4b/K6).

### ⛔ 안전 (SOT — 약화 금지)
- **① 3사(사람인·잡코리아·링크드인) 자동 로그인을 막지 마라.** 이 조각은 양보/STOP 배선만 — 로그인 흐름 미변경.
- **② 크롬 점유 양보·자동재개(R4/SOT2):** 사장님 크롬 앞창 감지 시 라이브 순회를 **양보(정지)**, 손 떼면 재개. 이 조각의 핵심. 봇처럼 창 열닫 반복·URL 연타·캡차 후 무한재시도 **금지** — STOP 은 break+사유로그, 재네비게이션 0.
- **③ 발송(제안·메일 "보내기") 자동 금지(SOT3):** 러너는 채점·저장까지만. Discord/InMail 발송은 이 조각 무관·미추가.

### 환경 함정(실측)
- 검사 인터프리터 `/Users/kangsangmo/Valuehire_v5/.venv/bin/python`(websocket 보유). `.venv-playwright` 는 collection 깨짐 — 쓰지 마라. worktree: `PYTHONSAFEPATH=1 PYTHONPATH=<worktree> <repo>/.venv/bin/python -m pytest <worktree>/tests/ -q`.
- CI 는 websocket 미설치 — `humansearch_cdp_run` 은 `raw_cdp` 를 **지연 import**(PC-C3a 에서 CI collect 수정)로 통과. **신규 최상단 websocket/raw_cdp import 금지** — detector/preflight import 는 순수모듈이라 안전하지만, 새 배선이 raw_cdp 를 모듈 최상단으로 끌어올리지 않게 주의.
- 테스트는 실제 CDP·브라우저 없이 **가짜 tab 객체**(navigate/eval/screenshot/close 스텁)와 **주입 detector**로 돌린다 — OS·네트워크 미접근.
- Codex(V1): placeholder 자주 반환(transcript jsonl `tasks/<agentId>.output` 의 tool_result 본문 확보) · 워크트리 직접쓰기 차단(뮤테이션은 `/private/tmp` 복사본) · Codex CLI 'Operation not permitted' 시 V1 을 fresh Claude 서브에이전트로 대체(매트릭스 허용, verdict 본문 명시).

### 적용 게이트
harness 0~6 + **gate4b: G(자기 mutation — 양보게이트 제거/조건반전/재구현우회/캡차게이트 제거 각각 caught) → V1(Codex) + V2(리셋 Claude) 병렬** → `docs/engineering/pc-f2-detector-live-runner-wiring.verdict.json` 3자 증거(G/V1/V2/T). CI 초록+merge 전까지 "완료" 없음.

### ⭐ 마지막에 — 전체 프로세스 상세 브리핑(recap) 필수
끝낼 때 사장님께 쉬운 한국어로: ①무엇을 배선했나(파일·PR번호 — "사장님이 크롬 쓰면 검색이 스스로 멈추게 연결") ②왜(전엔 라이브 검색이 사장님 크롬을 안 봐서 계속 돌 수 있었다) ③**어떻게 검증했나 — G/V1(Codex)/V2(리셋 Claude)/T 각 검증자가 실제로 잡은 결함과 수정 구체적으로** ④증거 숫자 그대로(passed/xfailed) ⑤남은 것(PC-C3b 다중페이지·PC-F4a 자동재개 데몬·실동작 수동확인) + 선행 리스크 처리 결과 ⑥재개/되돌리기 방법. 과장·"아마도" 금지.
