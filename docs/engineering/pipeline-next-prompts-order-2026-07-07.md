# 무인 헤드헌팅 파이프라인 — 다음 작업 프롬프트 리스트·순서 (2026-07-07)

> 각 항목은 새 세션에 붙여넣어 `/st` 로 착수하는 킥오프 프롬프트다. **한 조각 = 한 worktree = 인수기준 1개.**
> 착수 전 항상: `make red-ledger`(clean) + `git worktree list`(다른 세션 충돌 확인) + 해당 조각 "이미 됐는지" 과거회수.

---

## 완료(다시 하지 마라)
- **PC-D2b**(PR#67)·**PC-K6**(PR#66, +launchd PATH 6109e75)·**PC-A3**(PR#68)·**PC-C2**(PR#73, d10b2e2) 병합.
- 각 `docs/engineering/<slug>.verdict.json` 에 G/V1/V2/T 3자 증거.
- 라이브 3계단 goal 문서 작성됨: `pc-f2-…`, `pc-f4a-…`, `pc-f4b-…-goal-2026-07-07.md`.

## 의존성·병렬 지도 (환각 없이 — 실측)
```
라이브 사슬(순차):  PC-C2 ✅ → PC-C3b → (PC-F2) → PC-F4a → PC-F4b(수동 로그인)
독립(병렬 가능):    PC-F5(portal_worker raw CDP)   PC-C5(연봉 필드) → PC-C6
```
- **C3b** 는 C2(✅) 소비 + 하드캡 제거 + `&start` 다중페이지. **F2** 는 라이브 러너에 R4 배선(C3b 와 같은 파일 `humansearch_cdp_run.py` 를 건드려 C3b 다음 권장).
- **F4a→F4b** 는 순차. F4b 는 실 로그인·launchd 실부팅이라 일부 수동 verdict.
- **F5·C5** 는 사슬을 안 막아 아무 때나 병렬 착수 가능(단 F5·C5 는 humansearch/models 파일이라 활성 세션과 충돌 확인).

---

## ① PC-C3b — 전수조사 다중페이지 순회 (다음, C2 소비) · L3
> `/st PC-C3b 구현한다. 과거회수부터 하고 착수해라.`
- **배경(실측)**: `tools/multi_position_sourcing/humansearch_cdp_run.py:250 main(max_profiles=25, start=0)` 이 `cards[:max_profiles]`(:265) 로 GOLD 를 25에서 자른다. 브랜치 `task/humansearch-multipos`(f137c76, **다른 세션 WIP**)에 이미 `run_one(max_pages=3)` 고정 다중페이지가 있으나 **하드캡 제거 + C2 결정 소비는 미완**.
- **계약**: `plan_result_count_traversal(channel, result_count)`(PC-C2, `humansearch.py`)로 밴드 결정 → `full` 이면 GOLD 전건(하드캡 없음), `top_n` 이면 limit 만, `abort/add_condition` 이면 순회 안 함. `collect_cards(tab, start)` 를 `&start=N` 오프셋으로 다중페이지 순회(페이싱 PC-E1 `deterministic_delay_ms` 재사용, SOT2).
- **인수기준(기계)**: 26~60건 GOLD 가 페이지당 25에서 안 잘리고 전건 순회됨을 러너레벨 테스트로 단언; top_n 밴드는 limit 에서 멈춤; abort 는 0회. `verify.sh` exit 0.
- **⚠️ 충돌**: 지정 워크트리가 `task/humansearch-multipos`(재개/병합). **먼저 그 브랜치 상태 확인 후 rebase/merge 전략 결정** — 새 방 파기 전에 그 WIP 를 흡수할지 판단(중복 구현 금지).
- **비범위**: 러너면 하드제외(PC-C3a 완료)·R4 배선(PC-F2).

## ② PC-F2 — detector→라이브 러너 R4 배선 · L3
> goal 문서 준비됨: `docs/engineering/pc-f2-detector-live-runner-wiring-goal-2026-07-07.md` → `/st` 로 그대로 착수.
- 핵심: `owner_activity.compute_yield_decision`/`worker_should_yield` 를 `humansearch_cdp_run.py` 순회 루프에 배선(사장님 크롬 점유 시 양보, R4). 순회 도중 캡차/세션락 STOP 도 루프 안으로.
- C3b 와 같은 파일이라 **C3b 다음에** 하는 게 충돌 적음.

## ③ PC-F4a — 자동재개 데몬 순수 결정함수 · L3
> goal 문서 준비됨: `docs/engineering/pc-f4a-autoresume-daemon-decision-goal-2026-07-07.md`.
- resume 방향(양보→대기→재개) 다틱 결정 순수함수. `harvest_driver.decide_tick`/`resolve_repo_dir` 재사용(재구현 금지).

## ④ PC-F4b — 상주 데몬 라이브 실운영 · L3 (일부 수동)
> goal 문서 준비됨: `docs/engineering/pc-f4b-live-resident-daemon-goal-2026-07-07.md`.
- 기계검증: `runner_for_channel` 팩토리(현재 RuntimeError 스텁) + `valuehire-search-loop.sh` 라이브 배선(페이크 스모크). **수동 verdict**: 실 로그인·실 playwright·launchd 실부팅(사장님 맥). 데몬 자동 load 금지.

## ⑤ (병렬) PC-F5 — portal_worker linkedin_rps 전체 attach → raw CDP 단일탭 · L2
> `/st PC-F5 구현한다.` — `tools/multi_position_sourcing/portal_worker.py` connectOverCDP 전체 attach(INV5 위반, 탭 과다 hang)를 raw CDP 단일탭으로. 의존성 없음, 사슬 안 막음.

## ⑥ (병렬) PC-C5 → PC-C6 — 연봉 자산 수집 · L2/L3
> `/st PC-C5 구현한다.` — `CapturedProfile`·`CandidateResultCard` 에 `salary_raw`/`salary_source` 필드 추가(의존성 없음). 이어 PC-C6(사람인/잡코리아 캡처·저장 러너에서 실수집, dep C5·B4·C4a).

---

## 규율(반드시)
- `/st` L3 풀하네스: worktree → RED→GREEN → verify exit 0 → G(뮤테이션) → V1(Codex)+V2(리셋 Claude) 병렬 → `<slug>.verdict.json` 3자 → CI 초록 merge → 장부 GREEN → worktree 정리.
- ⚠️ **교훈(PC-C2 실측)**: 뮤테이션 검증 전 반드시 GREEN/수정을 **커밋**하라 — 안 그러면 `git restore` 가 미커밋 구현을 되돌린다.
- **Codex(V1) 는 placeholder 자주 반환** → transcript jsonl 본문 확보(빈 응답=통과 아님). PC-C2 에서 V1 이 실제로 float/str/None 타입 fail-closed 구멍을 잡았다(가짜 통과 아님).
- 검사 인터프리터 `/Users/kangsangmo/Valuehire_v5/.venv/bin/python`(websocket 보유). worktree: `PYTHONSAFEPATH=1 PYTHONPATH=<wt> …/.venv/bin/python -m pytest <wt>/tests/ -q`.
- 로그인 크롬 kill 금지. 발송 자동금지. 크롬 점유 시 양보·자동재개(R4).
