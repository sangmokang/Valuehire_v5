# 사장님 양보 3분 자동 재개 (SOT29 개정) + LinkedIn 로그인 머신 탐색 prompting — goal (2026-07-15)

이슈: https://github.com/sangmokang/Valuehire_v5/issues/107 · 모드 code-change+SOT 개정 · 위험 L3(운영 불변식 개정 — 사장님 명시 지시)

## 사장님 지시 (최우선, 원문 요지)
1. "paused 후 자동 등록 전부 중단" 원칙(#104)은 **폐기**. 대신: **"내 눈치를 봐라. 내가 쓸 동안은
   멈췄다가, 3분 뒤까지 이상이 없으면 계속 시작해."** 이 로직을 방해하는 코드는 전부 삭제.
   이 원칙을 SOT로 박는다.
2. LinkedIn 은 winpc/macmini/macbook(사장님 표현 "Macpro" = 맥북 프로로 해석, 함대 명칭 유지)
   셋 중 하나가 로그인 상태 — 로그인된 기기/브라우저를 탐색해 찾도록 잡 프롬프트에 명시(prompting).

## 현재 상태 (직접 확인)
- `tools/multi_position_sourcing/owner_activity.py:31` — 이미 같은 원칙 구현:
  `DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS = 180.0`(크롬 앞창=양보, idle≥180s=재개). 사장님 원칙과 일치.
- **방해 코드 1**: `fleet_worker.py:44` `PAUSE_COOLDOWN_SECONDS = 600` — 10분 대기(QA-2).
- **방해 코드 2**: `fleet_worker.py` paused 분기 `self._variant_backlog.clear()` — 영구 폐기(#104).
- **방해 코드 3**: `tests/test_fleet_reliability.py:310` `assert PAUSE_COOLDOWN_SECONDS >= 300` —
  5분 이상을 스펙으로 강제(사장님 3분 원칙과 충돌).
- LinkedIn 로그인 머신 라우팅(이슈 D, PR#103)은 존재: heartbeat `linkedin_rps_logged_in` →
  `linkedin_ready_machines` → `fleet_dispatch._route_linkedin_machine`. 그러나 잡 **프롬프트**에는
  "로그인된 브라우저를 탐색해 확인하라"는 지시가 없음(`build_job_prompt` 규칙 1~18 확인).

## 계약 (SDD)
```python
# fleet_worker.py
OWNER_YIELD_RESUME_SECONDS: int = 180          # SOT29 INV9 단일 출처
PAUSE_COOLDOWN_SECONDS = OWNER_YIELD_RESUME_SECONDS  # 하위호환 별칭(=180)

sleep_seconds_after("paused_for_human", poll) -> 180

FleetWorker(..., clock: Callable[[], float] | None = None)  # 기본 time.monotonic
# 상태 전이: paused_for_human 발생 → _backlog_resume_at = clock() + 180 (폐기 아님)
# _enqueue_idle_variant: clock() < _backlog_resume_at 이면 no-op(양보 중),
#                        경과 후 idle 부터 1건씩 자동 재개.

build_job_prompt(job with skill="url") -> 프롬프트에 포함:
#  "로그인된" + "macmini/macbook/winpc" + 탐색·확인 지시(신규 규칙 19)
```
SOT: `docs/sot/29-fleet-control.json` invariants 에 `INV9_owner_yield_3min` 추가,
`29-fleet-control.md` 동기 개정, 루트 `CLAUDE.md` 규칙 ② 에 3분(180초) 수치 명시.

## 인수 기준 (기계 — tests/test_owner_yield_3min.py)
1. `sleep_seconds_after("paused_for_human", 30) == 180`, 코드에 600 잔존 0.
2. paused 후 backlog 미폐기 + 3분 전 idle 은 enqueue 0 + 3분 후(주입 시계) idle 은 재개.
3. skill=url 프롬프트에 로그인 머신 탐색 지시 포함.
4. SOT29 json 에 INV9(180) 존재.
- 기존 `test_session_batch.py::test_paused_for_human_clears_backlog_no_night_reentry` 는
  사장님 스펙 변경으로 **교체**(약화 아님 — verdict 에 사유 기록).
- `test_fleet_reliability.py` 의 `>=300` 단언은 `==180` 스펙으로 교체(방해 코드 3 삭제).

## 비범위
- owner_activity 감지기의 fleet_worker 직접 배선(비-macOS fail-closed 가 winpc 를 영구 정지시킴 — 별도 설계 필요).
- 머신 명칭 변경(macbook→macpro): 함대 전체 마이그레이션이라 별도 이슈. 사장님 "Macpro"는 맥북 프로로 해석.
- Supabase 서버측 pause 장벽(#105)은 그대로 후속.

## 적대 검증 로그
(게이트 4b 에서 채움)
