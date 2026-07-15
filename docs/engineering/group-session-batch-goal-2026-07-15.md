# 그룹 세션 배치 (배치 확장 + 심야 지속) — goal (2026-07-15)

이슈: https://github.com/sangmokang/Valuehire_v5/issues/104 · 모드 code-change · 위험 L2

## 현재 상태 (직접 확인)
- `tools/multi_position_sourcing/grouping.py:79` `group_positions()` — 존재하나 실전 미배선.
  호출부는 `dry_run.py:141`(데모)뿐. fleet 경로(fleet_dispatch/fleet_worker)에서는 고아.
- `tools/multi_position_sourcing/fleet_dispatch.py:129` fleet-run 분기 — 잡 params 를 그대로 큐에 싣는다.
- `tools/multi_position_sourcing/fleet_worker.py:393` `run_once` — `claim_next` 가 None 이면 "idle" 반환만 하고 끝.
  done 종결 후 후속은 `_enqueue_followup`(fleet_worker.py:474, 이슈 A 선례)만 있음 — params.followup_skill 1건.
- 실제 진행 중 포지션 리스트 = `docs/sot/24-position-jd-sot.json` (positions[3], must_have/nice_to_have/responsibilities/experience 포함).

## 근본 문제
로그인 세션 1회 확보가 포지션 1개 검색으로 끝난다. 유사 포지션·미소진 필터 변형이 같은 세션/심야 유휴 시간에 이어지지 않는다.

## 계약 (SDD — 입출력 먼저)
새 모듈 `tools/multi_position_sourcing/session_batch.py` (순수 코어 + SOT24 로더):

```python
load_active_positions(path=SOT24) -> tuple[Position, ...]
# SOT24 positions[] → Position 매핑. position_id=clickup_task_id,
# jd_text=summary+responsibilities+must_have 결합, source_url=clickup_url.
# 파일 없음/형식 오류 → () (fail-soft: 그룹 세션 미첨부일 뿐 잡 자체는 막지 않음)

group_session_params(position_url: str, positions: Sequence[Position]) -> dict | None
# group_positions(positions) 호출 → position_url 이 속한 그룹 탐색.
# 반환: {"group_id": str, "sibling_position_urls": [str], "note": str,
#        "pending_variants": [{"channel": str, "keyword": str, "filters": dict}, ...]}
# pending_variants = 그룹 표준 키워드(채널별 첫 키워드=원 잡이 커버) 제외 나머지, 총 6개 캡.
# 미매칭/포지션 0개 → None

variant_job_payload(base_job: Mapping, variant: Mapping, group_id: str) -> dict | None
# new_job_payload 재사용(fail-closed 그대로). params={"group_id", "variant",
# "idempotency_key": f"group:{group_id}:variant:{channel}:{keyword}"[:160]}.
# 변형 잡에는 group_session 을 싣지 않는다(1단계 체인 — 무한 enqueue 방지, 이슈 A 동일 원칙).
```

배선:
1. `fleet_dispatch.dispatch_fleet_command` fleet-run(skill=humansearch) → fail-soft 로
   `params["group_session"] = group_session_params(url, load_active_positions())`.
   params 는 `build_job_prompt` 의 "추가 파라미터" 줄로 스킬 실행에 전달 → note 로
   같은 로그인 세션 내 유사 포지션 연속 검색을 지시(humansearch 연결).
2. `fleet_worker.FleetWorker`:
   - humansearch 잡 done 종결 시 params.group_session.pending_variants → 인스턴스 backlog 저장.
   - `run_once` 가 idle(claim_next=None)일 때 backlog 에서 1건만 enqueue(회당 1건 자연 스로틀).
   - paused_for_human 발생 시 backlog 전량 폐기 — 캡차/사장님 개입 상황 자동 재진입 금지(SOT29 §2).

## 인수 기준 (기계 — tests/test_session_batch.py)
1. dispatch 시 group_positions 가 실포지션 리스트에 적용되어 params.group_session 이 실린다.
2. done 후 idle 이면 미소진 변형 1건 자동 enqueue, 소진 시 중단(무한 enqueue 없음).
3. paused_for_human 후에는 idle 이어도 enqueue 없음.
4. 변형 페이로드는 new_job_payload 검증(fail-closed)을 통과한 것만 enqueue.

## 판단 단언
- SOT29 양보 경로(browser_policy·PAUSE_COOLDOWN·paused 쿨다운) 무변경·무약화.
- SOT28: enqueue 는 검색 스킬(humansearch)만 — 발송성 스킬 생성 경로 없음.

## 비범위
- 그룹 backlog 의 DB 영속화(워커 재시작 시 소실 허용 — 후속 이슈).
- aisearch/url 스킬로의 그룹 확장.
- SOT24 밖 포지션 소스(ClickUp 라이브 조회).

## 적대 검증 로그
(게이트 4b 에서 채움)
