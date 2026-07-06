# 코덱스 인수인계 프롬프트 — 무인 헤드헌팅 파이프라인 남은 작업 (2026-07-07)

> 아래 「=== 여기부터 복사 ===」 블록 전체를 코덱스(codex CLI)에 붙여넣어 착수시킨다.
> 코덱스는 `.claude/skills/`·`CLAUDE.md` 를 읽지 않으므로 이 프롬프트는 **전부 자체 포함**이다.

=== 여기부터 복사 ===

너는 지금부터 이 저장소의 "무인 헤드헌팅 파이프라인" 남은 조각들을 **끝까지** 구현하는 실행자다.
저장소 루트: /Users/kangsangmo/Valuehire_v5 (git, 기본 브랜치 main). 반드시 아래 규율을 지켜라.

## 0. 절대 규칙 (SOT 불변식 — 약화 금지)
1. 사람인·잡코리아·링크드인 3사 자동 로그인을 막지 마라.
2. 사장님이 크롬을 쓰는 동안엔 자동작업을 잠깐 멈추고(양보), 손 떼면 자동 재개(R4). 봇처럼 창 반복 개폐·URL 연타·무한 재시도 금지.
3. 제안/메일 자동발송은 자동발송 정책(docs/sot/28-auto-send-policy.json, SOT28)의 게이트를 **전부** 통과할 때만. 하나라도 어긋나면 발송 안 함(fail-closed). 이 조각들은 발송 로직을 건드리지 않는다 — 검색/순회/판단만.
4. 사장님께 보고는 **쉬운 한국어**로. 기술 약자·게이트 번호 나열 금지. "무엇을/왜/다음"만.
5. 네 코드를 믿지 마라 — 두 번 깐다. 시작 전 과거 회수(이미 있는지 검색)부터.

## 1. 작업 규율 (조각마다 이 게이트 전부 통과 — 못 통과하면 "완료" 금지)
- 한 조각 = 한 git worktree = 인수기준 1개. **main 에서 직접 소스 수정 금지.**
  - 워크트리: `git worktree add worktrees/<slug> -b task/<slug>`
- 게이트 0 시작자격: `make red-ledger`(clean 확인) + `git worktree list`(다른 세션과 같은 파일 충돌 확인) + 그 조각이 **이미 됐는지** 코드/장부/`docs/engineering/*.verdict.json` 검색(과거 회수).
- 게이트 1 스펙: 손대기 전 입출력 계약(함수 시그니처·반환 shape)을 goal 문서 `docs/engineering/<slug>-goal-2026-07-07.md` 에 박아라.
- 게이트 2 RED 먼저: 실패하는 테스트를 **먼저** 작성·커밋(실패 메시지가 기대 동작 결여를 보여야).
- 게이트 3 GREEN: 최소 변경으로 통과. 기존 테스트 삭제·약화(skip/assert 제거) 금지.
- 게이트 4 검증: 아래 "검사 명령"으로 exit 0 확인, 출력 숫자를 그대로 기록.
- 게이트 4b 적대검증(L3 필수):
  - (G, 너) 뮤테이션 최소 2개(조건 반전/경계 부등호/반환 상수화)를 **임시 적용→테스트 실패 확인→되돌림**.
    ⚠️ **뮤테이션 전 반드시 현재 구현을 커밋하라.** 안 그러면 되돌릴 때 `git restore` 가 미커밋 구현까지 날린다(PC-C2 에서 실제로 두 번 겪은 함정).
  - (V1, 독립 2차) 서로 다른 컨텍스트의 검증자로 한 번 더 깨라. 코덱스가 생성자이므로 V1 은 **fresh Claude** 로:
    `claude -p "적대적으로 이 함수를 깨라. 반례·생존 뮤턴트·SOT 드리프트를 찾아라: <파일:함수>. goal=<goal.md>. 통과면 재현한 근거를, FAIL 이면 정확한 반례(입력→기대vs실제)와 재현 명령을 반환."`
    (claude 가 없거나 막히면 최소한 뮤테이션+경계 전수 + 스스로 리셋해 재검토한 표를 남겨라.)
  - V1 이 결함을 잡으면: 바로 재시도하지 말고 **근본 원인**을 verdict 의 failed_attempts[] 에 적고, 그 원인을 어떻게 푸는지 쓴 뒤 수정 → 재검증(수렴까지).
  - 증거를 `docs/engineering/<slug>.verdict.json` 에 역할별(generator/v1/status)로 남겨라. exit_code·test_result·mutation_evidence·counterexample 포함.
- 게이트 5 배송: `git push -u origin task/<slug>` → `gh pr create --base main` → `gh pr checks <n>` 초록 확인 → `gh pr merge <n> --squash --delete-branch`.
- 게이트 6 종료: `.harness/red-ledger.tsv` 에 `<slug>\tGREEN\t#<pr>\t<한줄요약>` 추가·커밋·push → `git worktree remove worktrees/<slug> --force` → 로컬 브랜치 삭제.
- 고아 금지: 새 코드가 프로덕션 진입점에서 실제로 불리는지 `grep` 으로 증명(안 불리면 결함). 순수함수 seam 이면 "소비자 조각" 을 goal 에 명시.

## 2. 검사 명령 (환경 함정 — 실측)
- 검사 인터프리터는 **/Users/kangsangmo/Valuehire_v5/.venv/bin/python** (websocket 보유). `.venv-playwright` 는 CDP 테스트 collect 깨짐.
- 워크트리에서 검사:
  `PYTHONSAFEPATH=1 PYTHONPATH=<워크트리절대경로> /Users/kangsangmo/Valuehire_v5/.venv/bin/python -m pytest <워크트리>/tests/ -q`
  (⚠️ 메인 저장소에서 `PYTHONSAFEPATH=1` 을 쓰면 cwd 가 sys.path 에서 빠져 `tools` import 가 깨진다 — 그땐 `./verify.sh` 를 써라. baseline: main 1025 passed, 4 xfailed.)
- CI(GitHub Actions)는 websocket 미설치 → 러너 import 하는 테스트는 raw_cdp 지연 import 덕에 통과. **새로 최상단 websocket import 추가 금지.**
- 로그인된 포털 크롬(9222 등) 절대 kill/stop 금지. 자동화 브라우저만 정리.
- 뮤테이션은 워크트리 쓰기가 막히면 `/private/tmp` 로 복사 후 거기서.

## 3. 할 일 — 순서대로 (roadmap: docs/engineering/pipeline-next-prompts-order-2026-07-07.md)
아래를 **①부터 순서대로** 하나씩 게이트 0~6 전부 통과시켜 병합까지 끝내라. 한 조각 끝나면 다음으로.

### ① PC-C3b — 전수조사 다중페이지 순회 (slug: humansearch-multipage-full)
- 목표: 라이브 순회가 GOLD 전건을 페이지당 25에서 자르지 않고 순회. PC-C2 의 결정을 소비.
- 실측 현황:
  - `tools/multi_position_sourcing/humansearch_cdp_run.py:250 def main(max_profiles=25, start=0)` → `for i, card in enumerate(cards[:max_profiles], 1)` (약 :265) 가 25에서 하드캡. `collect_cards(tab, start)` (:115) 가 `&start={start}` 로 페이지 이동.
  - **PC-C2 완료(PR#73, main)**: `tools/multi_position_sourcing/humansearch.py` 에 `plan_result_count_traversal(channel, result_count) -> TraversalPlan(action,limit,band,channel)`. action ∈ {abort, full, top_n, add_condition}, full=limit None(전건), top_n=limit N. **이걸 재사용하라(재구현 금지).**
  - 페이싱은 `tools/multi_position_sourcing/harvest_policy.py` `deterministic_delay_ms(kind,step,seed)` 재사용(SOT2, 봇방지).
  - ⚠️ **충돌 주의**: 브랜치 `task/humansearch-multipos`(다른 세션 WIP)에 이미 `run_one(max_pages=3)` 고정 다중페이지가 있다. **새 워크트리 파기 전에 그 브랜치 상태(`git log main..task/humansearch-multipos`, diff)를 확인**하고, 흡수(rebase/cherry-pick)할지 새로 할지 판단하라. 같은 파일을 겹쳐 고치면 병합 충돌.
- 계약(예): 러너가 결과수를 읽어 `plan_result_count_traversal(channel, count)` 호출 → full 이면 하드캡 없이 `&start=0,25,50…` 다중페이지로 전건 수집, top_n 이면 limit 까지만, abort/add_condition 이면 순회 0.
- 인수기준(기계): 26~60건 GOLD 가 안 잘리고 전건 수집됨을 러너레벨 테스트(가짜 tab/카드 주입, 호출횟수·수집수 단언)로 단언. top_n 은 limit 에서 멈춤. abort 는 collect 0회. verify exit 0.
- 비범위: 러너면 하드제외(PC-C3a 완료)·R4 양보 배선(다음 ②).

### ② PC-F2 — detector→라이브 러너 R4 배선 (slug: humansearch-r4-wiring)
- goal 초안 있음: `docs/engineering/pc-f2-detector-live-runner-wiring-goal-2026-07-07.md` (읽고 착수).
- `owner_activity.compute_yield_decision`/`harvest_policy.worker_should_yield` 를 `humansearch_cdp_run.py` 순회 루프에 배선: 매 프로필 전 사장님 크롬 점유 감지 시 양보(R4), 순회 도중 캡차/세션락도 STOP. C3b 와 같은 파일이라 **C3b 다음에** 하라.

### ③ PC-F4a — 자동재개 데몬 순수 결정함수 (slug: autoresume-daemon-decision)
- goal 초안 있음: `docs/engineering/pc-f4a-autoresume-daemon-decision-goal-2026-07-07.md`.
- 양보→대기→재개(idle→resume) 다틱 결정 순수함수. `harvest_driver.decide_tick`/`resolve_repo_dir` 재사용.

### ④ PC-F4b — 상주 데몬 라이브 실운영 (slug: live-resident-daemon)  ※ 일부 수동
- goal 초안 있음: `docs/engineering/pc-f4b-live-resident-daemon-goal-2026-07-07.md`.
- 기계검증분만 코덱스가: `harvest_driver._runner_for_channel`(현재 RuntimeError 스텁) 팩토리 + `scripts/valuehire-search-loop.sh` 라이브 배선(페이크 실행자 스모크). **실 로그인·실 playwright·launchd 실부팅은 사장님 수동** — 자동 load/start 금지, verdict 에 "수동 판정 필요" 로 남겨라(이건 완료 아님).

### (병렬 가능, 사슬 안 막음 — ①~④ 사이 언제든)
- ⑤ PC-F5: `tools/multi_position_sourcing/portal_worker.py` linkedin_rps 전체 attach → raw CDP 단일탭(slug: portal-worker-rawcdp).
- ⑥ PC-C5→C6: `CapturedProfile`/`CandidateResultCard` 에 salary_raw/salary_source 필드 추가 후 사람인·잡코리아 캡처 러너 실수집.

## 4. 다 끝낸 뒤 (반드시)
각 조각 병합·장부 GREEN·워크트리 정리를 마쳤으면, 마지막에 **쉬운 한국어로** 사장님께 보고:
①무엇을 고쳤나(조각·PR번호) ②왜(사장님 관점 한 줄) ③어떻게 검증했나(내 뮤테이션/독립검증이 실제로 잡은 결함과 수정) ④증거 숫자 그대로(검사 통과 수·PR번호·장부 GREEN) ⑤남은 것·수동확인 필요분 ⑥재개/되돌리기 명령. 과장·"아마도" 금지.

지금 ① PC-C3b 부터 게이트 0(과거회수·충돌확인)으로 시작하라.

=== 여기까지 복사 ===
