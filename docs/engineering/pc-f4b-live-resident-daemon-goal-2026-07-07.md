# PC-F4b — 상주 자동재개 데몬 실운영(라이브) + 경로 드리프트 제거 · 구현 킥오프

> 새 세션에 이 내용을 붙여넣어 `/st` 로 착수. **한 조각 = 한 worktree = 인수기준 1개.**
> 형제 조각 PC-K6(`docs/engineering/pc-k6-daemon-crashloop-goal-2026-07-04.md`)의 **PART 2가 곧 이 조각**이다 — K6는 크래시-루프·경로만 고쳤고, 라이브 전환은 여기서 한다.

---

## /st PC-F4b(상주 데몬 라이브 실운영 + 경로 드리프트 마감) 구현한다. 과거회수부터 하고 착수해라.

### 저장소 / SOT (먼저 읽어라)
- 저장소: `/Users/kangsangmo/Valuehire_v5` (main). 규칙 `CLAUDE.md`, 루프 `docs/harness.md`, 장부 `.harness/red-ledger.tsv`.
- 선행(완료): **PC-F4a**(봇방지 페이싱 primitive 소비), **PC-D2b**(상시 Harvest 드라이버, PR#67), **PC-D5**(라이브 실행자, PR#54), **PC-K6**(데몬 크래시-루프·경로 드리프트 제거, PR#66).
- 착수 전 `make red-ledger`(clean 확인) + `git worktree list`(다른 세션 파일 안 건드림).
- **과거회수 필수**: 이 조각의 계약은 이미 리포에 seam 으로 스테이징돼 있다(아래 §현재 상태). 새로 만들지 말고 **비어 있는 이음매(runner 팩토리 + loop.sh 배선)만** 채워라 — 중복 구현 금지(CLAUDE.md 5번).

### 위험등급 · 모드
- **code-change · L3** (상주 데몬 = 되돌리기 어려운 OS 동작 + SOT 불변식 ①3사 자동로그인 안 막음 ②크롬 점유 양보·자동재개(R4) ③봇 금지 ④발송 자동금지). 풀하네스: worktree → RED→GREEN → G→V1→V2(**병렬**) → verdict.json 3자.
- ⚠️ **이 조각은 절반이 수동 verdict**다. 기계로 증명 가능한 부분(팩토리 배선·페이크 스모크)과 사람만 확인 가능한 부분(실 로그인·실 playwright 구동·launchd 실부팅)을 §계약에서 PART 1 / PART 2 로 못박는다. PART 2 는 "완료"라고 말하지 않는다.

### 현재 상태 (직접 연 file:line — 이번 조사에서 확인)

**(A) 경로 드리프트 = 이미 제거됨(PC-K6/PR#66). 이 조각의 "경로 드리프트 제거" 파트는 DONE — 회귀 봉인만 유지.**
- `scripts/valuehire-search-loop.sh:4-5` — `SCRIPT_SELF_DIR="$(cd "$(dirname "$0")/.." && pwd)"` + `REPO_DIR="${VALUEHIRE_REPO_DIR:-$SCRIPT_SELF_DIR}"`. Desktop 하드코딩 없음(스크립트 자기위치 도출).
- `scripts/valuehire-search-loop.sh:16-31` — 무효 REPO_DIR·`mkdir`·`cd` 실패 시 즉시 crash-exit 대신 **fail-soft 백오프 재시도**(`RETRY_BACKOFF_SECONDS`, `continue`). `set -uo pipefail`(:2, `-e` 없음)로 `cd` 실패가 프로세스를 죽이지 않음 → KeepAlive 무한재시작 근본원인 제거됨.
- `scripts/launchd/com.valuehire.search-runner.plist:11-27` — `ProgramArguments`/`WorkingDirectory`/`VALUEHIRE_REPO_DIR`/로그경로 4곳 모두 `/Users/kangsangmo/Valuehire_v5`(실경로). `PATH` 고정(:25-26, 최근 커밋). `RunAtLoad=true`(:29-30) + `KeepAlive=true`(:32-33) + `caffeinate -dimsu`(:11).
- 결론: **"경로 드리프트 제거"는 K6에서 끝났다. 이 조각은 그걸 다시 하지 않고, 회귀테스트(Desktop 리터럴 0건)만 승계·유지한다.**

**(B) 루프가 아직 dry_run 을 돈다 = 라이브 미배선(이 조각의 핵심).**
- `scripts/valuehire-search-loop.sh:36-37` — `if /usr/bin/python3 -m tools.multi_position_sourcing.dry_run --output "$ARTIFACT_DIR/dry-run-latest.json"; then` — **라이브 `harvest_driver` 가 아니라 `dry_run` 모듈을 호출**한다. 상주 데몬은 여전히 드라이런 전용.

**(C) 라이브 포털 러너 팩토리가 없다 = 의도적 RuntimeError 스텁.**
- `tools/multi_position_sourcing/harvest_driver.py:105-118` — `_build_live_execute_item` 이 `HarvestSearchExecutor`(PC-D5)를 조립하는데, 그 안 `_runner_for_channel`(:108-113)이 곧장 예외를 던진다:
  - `harvest_driver.py:110-113` — `raise RuntimeError("live portal runner factory 미배선(PC-F4b/K6 몫) — --executor live 는 인자 검증까지만 이 조각의 범위다.")`
  - 즉 `--executor live` 는 지금 **인자 검증(빈 segments·무키워드 fail-closed)까지만** 동작하고, 실제 채널→러너 생성은 비어 있다.
- `harvest_driver.py:91-93` — `_fake_execute_item` 은 포털 스택 없이 빈 튜플 반환(페이크 스모크용, 결정론).
- `harvest_driver.py:121-191` — `main`. `--executor {fake,live}`(:123), `live` 는 `--keywords-json` 필수(:139-146, 없으면 exit 2), owner-check 기본 ON(:150-154, `--skip-owner-check` 없으면 R4 감지), 출력 JSON 에 `executor` 종류 명시(:177, 라이브인 척 금지).

**(D) 이음매 재료는 이미 리포에 있다(고아 아님 — 팩토리만 없음).**
- `tools/multi_position_sourcing/harvest_executor.py:50-101` — `HarvestSearchExecutor`(PR#54). 생성자(:60-70)는 `runner_for_channel: Callable[[Channel], GuardedPortalSearchRunner]` + `keywords_for_segment` 주입. STOP 규율(searched+pause_site=False 만 진행, 그 외 즉시 break, 카드보존)은 검증 완료(harvest-live-executor.verdict.json).
- `tools/multi_position_sourcing/portal_queue_executor.py:107-130` — **팩토리 배선 참조 선례** `make_execute_item(runner_for_channel)`. 주석(:116) `runner_for_channel = lambda channel: build_guarded_runner(channel, ...)` — 그러나 **`build_guarded_runner` 는 리포에 존재하지 않는다**(grep: 이 주석 1곳뿐). 이게 이 조각이 만들 조각.
- `tools/multi_position_sourcing/portal_runtime.py:51-81` — `GuardedPortalSearchRunner.__init__` 이 요구하는 의존: `worker`, `encryptor`(OpenSslSessionEncryptor), `snapshot_store`, `event_store`, `snapshot_validator` (+옵션 `ready_check`/`credential_provider`/`auto_relogin`/`discord_notifier`/`pacing_policies`/`rng`/`sleep`). 팩토리가 채널별로 이걸 조립해야 한다.
- `tools/multi_position_sourcing/portal_live_check.py:38,53-54` — 실제 `GuardedPortalSearchRunner`/`PortalWorker`/`PortalWorkerConfig` 를 구성하는 유일한 비-테스트 호출부(팩토리가 베낄 참조 배선).
- `tools/multi_position_sourcing/portal_worker.py:28-29` — `PortalWorker` CDP 엔드포인트: `VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT` env, 기본 `http://127.0.0.1:9222`. (⚠️ 실전 포트는 9222 아님 — 함정 §환경 참조.)
- `portal_worker.py:collect_result_cards`(run 결과 `candidate_cards`, :661 부근) — **실 카드 추출은 이미 있다**. 이게 ledger 가 말한 "wip portal_worker 살베지"의 알맹이(harvest-live-executor 비범위로 명시된 "라이브 카드추출 품질").

**(E) PC-F4b 작업은 아직 병합된 게 없다.**
- `docs/engineering/` 에 `pc-f4b-*.verdict.json` **없음**(PC-K6·reservoir-harvest-driver·harvest-live-executor·anti-bot-pacing verdict 는 있음). ledger 45(reservoir-harvest-driver)·37(harvest-live-executor)·49(pc-k6) 세 줄이 공통으로 "live 포털러너 팩토리는 PC-F4b 비범위"라고 명시 → **이 조각이 그 미착수 잔여다.**

### 근본 원인
저수지 Harvest 의 심장(`arun_harvest_cycle`)·라이브 실행자(`HarvestSearchExecutor`)·드라이버 CLI(`harvest_driver.main`)까지 다 병합됐지만, **`HarvestSearchExecutor` 에 넣을 실제 `runner_for_channel` 팩토리가 없어서**(`_runner_for_channel` 이 RuntimeError) 라이브 경로가 끊겨 있다. 그래서 상주 데몬 루프(`loop.sh:36`)는 여전히 안전한 `dry_run` 만 돈다. 이 조각은 그 팩토리를 만들어 이음매를 잇고, loop 를 **플래그 뒤에서** 라이브 드라이버로 배선한다.

### 계약 (SDD — 손대기 전에 박아라)

스코프를 **2부**로 명확히 가른다. PART 1 만 기계검증하고 병합한다. PART 2 는 수동 verdict 로 남긴다("완료" 아님).

#### PART 1 — 기계검증(지금 가능): runner_for_channel 팩토리 + loop.sh 라이브 배선 뒤 페이크 스모크

- **(1a) 채널별 러너 팩토리 신설** — `portal_live_check.py`(참조 배선)와 `GuardedPortalSearchRunner.__init__`(portal_runtime.py:54-81) 계약대로, `Channel → GuardedPortalSearchRunner` 를 조립하는 순수 팩토리(예: `build_guarded_runner(channel, *, deps...)`). `harvest_driver._build_live_execute_item` 의 RuntimeError 스텁(:108-113)을 이 팩토리 호출로 교체. **주입점은 하나** — 기존 `HarvestSearchExecutor(runner_for_channel=...)` 계약 그대로(재구현·병렬경로 금지, SOT5).
  - 계약(테스트 대상): 팩토리에 채널을 주면 `run_keyword_search` 를 노출하는 러너를 돌려준다. 채널별로 CDP 엔드포인트/프로필/페이싱 정책이 맞게 바인딩된다. **팩토리는 브라우저 수명주기를 소유하지 않고 지연 생성**(portal_queue_executor.make_execute_item 선례 :122-124).
- **(1b) loop.sh 를 라이브 드라이버로 배선하되 플래그 뒤에** — `scripts/valuehire-search-loop.sh:36` 의 `dry_run` 호출을, 환경변수(예: `VALUEHIRE_SEARCH_EXECUTOR=live|dry_run`, 기본은 **여전히 dry_run 또는 fake** = 안전) 로 분기해 `python3 -m tools.multi_position_sourcing.harvest_driver --executor <mode> --segments ... --machine ... --run-id ... --today ... --keywords-json ...` 를 부르게 한다. **기본값이 라이브가 아니어야 한다** — 라이브는 사장님이 명시적으로 켤 때만.
  - 계약(테스트 대상): (a) 플래그 미지정/`dry_run` → 기존 dry_run 경로(회귀), (b) `fake` → `harvest_driver --executor fake` 스모크 exit 0 + 산출 JSON `executor=="fake"`, (c) 셸이 라이브 인자를 올바로 조립하는지(인자 조립 순수성), (d) `loop.sh` 소스에 `Desktop/Valuehire_v5` 리터럴 **0건**(K6 회귀 봉인 승계).
- **(1c) 페이크 실행자로 드라이버 end-to-end** — `harvest_driver.main(["--executor","fake",...])` 가 owner-check·segments·저장·JSON 산출까지 실 브라우저 없이 도는지(이미 PR#67 커버, **회귀로 유지**). 라이브 팩토리 배선 후에도 `--executor fake` 는 팩토리를 만지지 않아야 한다(페이크가 라이브인 척 금지).

**인수 기준 (PART 1 · 기계 단언 — verify.sh exit 0):**
1. **팩토리 단위**: `build_guarded_runner`(신설)이 각 채널(사람인·잡코리아·linkedin_rps)에 대해 `run_keyword_search` 를 가진 러너를 반환하고, CDP 엔드포인트/채널이 인자대로 바인딩된다(가짜 worker/store 주입으로 단언 — 실 브라우저 없이).
2. **RuntimeError 제거 회귀**: `harvest_driver._build_live_execute_item(...)` 가 더 이상 "live portal runner factory 미배선" 을 던지지 않고, 주입된 팩토리를 `HarvestSearchExecutor.runner_for_channel` 로 넘긴다(호출 기록으로 단언, 로그 문구 아님).
3. **페이크 스모크 격리**: `--executor fake` 는 라이브 팩토리를 **0회** 호출(페이크≠라이브). 산출 JSON `executor=="fake"`.
4. **loop.sh 분기**: 플래그 기본값에서 dry_run/fake(비-라이브) 경로, 명시적 라이브 플래그에서만 `harvest_driver --executor live` 인자 조립. `Desktop/Valuehire_v5` 리터럴 0건(K6 승계).
5. **owner-check 기본 ON 유지**(R4/SOT2): `--skip-owner-check` 없으면 감지 ON(`harvest_driver.py:150-154` 회귀).
6. `./verify.sh` exit 0 (baseline: PC-K6 977 passed+4 xfailed / portal-tab-guard PR#72 이후 최신 — 착수 시 `make red-ledger`·baseline 실측 후 신규분 더함).

#### PART 2 — 수동 verdict(기계검증 불가): 실 로그인 · 실 playwright 구동 · launchd 실부팅

이 부분은 코드로 "GREEN" 을 못 만든다. **모 문서(reservoir-harvest-driver goal §주관 단언 / PC-K6 goal ⛔안전) 잔여리스크를 계승**한다. verdict.json 에 "수동 미검증 잔여"로 명시하고, 병합해도 "실운영 완료"라 말하지 않는다.

**수동 체크리스트(사장님 맥에서, 사람이 눈으로):**
- [ ] 3사(사람인·잡코리아·링크드인) 디버그 크롬이 실 포트(9223/9224/9225)로 살아있고 **사장님이 수동 로그인**돼 있다(캡차=사람 게이트, SOT1 자동로그인 안 막음).
- [ ] `harvest_driver --executor live --keywords-json <실키워드>` 를 **손으로 1회** 실행 → 실제로 검색 카드가 수확되고 저장되며, 챌린지/상한 만나면 즉시 STOP(봇처럼 남은 키워드 안 두드림, SOT2).
- [ ] 라이브 실행 중 사장님이 크롬을 만지면 **즉시 양보**하고, 손 떼면 **자동 재개**된다(R4). 창을 열었다 닫았다 반복하지 않는다.
- [ ] `launchd load` 는 **사장님이 수동 1회**(자동 load/start 금지). `VALUEHIRE_SEARCH_EXECUTOR=live` 로 부팅 시 크래시-루프 0(K6 fail-soft 유지 확인).
- [ ] 발송(제안·메일 "보내기")은 자동으로 안 눌린다(SOT3) — 이 파이프라인은 수확·저장까지만.

### 적대검증 정조준
- **페이크 GREEN 이 라이브인 척 하나**: PART 1 테스트가 실 브라우저 없이 도니, `--executor fake` 가 라이브 팩토리를 만지면 즉시 실패하도록 단언(팩토리 호출 0회). 산출 JSON `executor` 필드가 실제 실행자와 불일치하면 RED.
- **라이브 데몬이 크래시-루프/봇류 반복 안 하나(SOT2)**: 라이브 실행자가 예외를 던져도 loop 는 fail-soft 백오프(K6)라야 하고, `KeepAlive` 가 즉시-재시작 폭주로 이어지지 않는지(백오프 실측). STOP 신호 후 남은 키워드를 계속 두드리지 않는지(HarvestSearchExecutor STOP 규율 회귀).
- **팩토리 고아 여부**: 새 `build_guarded_runner` 가 실제로 `harvest_driver` → `HarvestSearchExecutor` → 데몬 loop 경로에 배선됐나(plist→sh→python→팩토리 전 사슬 추적). 배선 안 되면 또 고아.
- **owner-check 기본 OFF 로 새는 사고**: 라이브 배선하며 실수로 `--skip-owner-check` 를 기본에 넣으면 R4 위반 → 기본 ON 회귀 유지.
- **채널 바인딩 오배선**: 사람인 러너에 잡코리아 CDP 포트가 붙는 등(9223/9224/9225 혼선) — 채널→엔드포인트 매핑 단언.

### 비범위
- 실제 `launchd load`/설치(사장님 맥 1회 수동 — 데몬 자동 load 금지).
- 실 playwright/CDP end-to-end 품질(카드 추출 정확도·사이트 DOM 변화 대응) — 수동 verdict.
- `portal-browsers` 데몬 재로드(현재 미로드, PR#72 이후 사장님 판단).
- segment→keyword 사전 구체 매핑(주입 JSON, 별 조각).
- 발송/제안 스테이지(SOT3 — 이 파이프라인 밖).

### ⛔ 안전 (SOT — 전부)
- **SOT1**: 3사 자동 로그인을 절대 막지 마라. 라이브 러너가 로그인 세션을 건드려 로그인을 깨뜨리면 안 된다. 캡차·재인증은 **사람 게이트**로 멈추고 보고.
- **SOT2 / R4**: 사장님이 크롬 쓰는 동안 자동작업 **잠깐 양보 → 손 떼면 자동 재개**. 봇처럼 창 여닫기·URL 연타·알람 뒤 무한 반복 금지. owner-check 기본 ON.
- **SOT3**: 제안·메일 "보내기" 자동 클릭 금지 — 항상 사람이 마지막에.
- **데몬을 자동으로 load/start 하지 마라** — 수리·테스트만. `launchd load` 는 사장님 수동(무한재시작 재발 방지).
- **로그인된 크롬(9223/9224/9225) kill/stop 금지** — 세션 유지(포털 자동로그인 유지).
- launchd 데몬 실부팅·라이브 구동은 **수동 verdict**. 순수 결정로직·팩토리 배선만 기계검증, 실운영은 "완료" 아님 명시.

### 환경 함정(실측)
- 검사 인터프리터 `/Users/kangsangmo/Valuehire_v5/.venv/bin/python`(websocket 보유). worktree: `PYTHONSAFEPATH=1 PYTHONPATH=<worktree> .../.venv/bin/python -m pytest <worktree>/tests/ -q`.
- **실전 CDP 포트는 9222 아님**: `portal_worker.py:29` 기본은 `9222`지만 실운영은 `portal_browsers.sh` 로 **사람인 9223 / 잡코리아 9224 / 링크드인 9225**(메모리 portal-debug-chrome-ports). 팩토리는 채널별 엔드포인트를 `VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT`(또는 채널별 오버라이드)로 받아야 하고, 테스트는 실 포트에 의존하지 않게 주입.
- CI 는 websocket 미설치 + zsh 부재 — 러너 import 는 지연 import 로 통과(신규 최상단 websocket import 금지), 셸 테스트는 `@requires_zsh` skip 처리(K6 선례).
- Codex(V1): placeholder 자주 반환(transcript jsonl `tasks/<agentId>.output` tool_result 본문 확보) · 워크트리 직접쓰기 차단(뮤테이션은 `/private/tmp` 복사본) · 전체 pytest 는 HOME/`VALUEHIRE_PORTAL_PROFILE_ROOT` 를 writable 임시경로로 분리. Codex 막히면 fresh Claude V1 대체(메모리 codex-rescue-blocked-use-fresh-claude-v1).

### 적용 게이트
harness 0~6 + **gate4b: G(자기 mutation) → V1(Codex) + V2(리셋 Claude) 병렬** → `docs/engineering/pc-f4b-live-resident-daemon.verdict.json` 3자 증거.
- **단, 실운영(PART 2)은 수동 verdict**: 기계 게이트(PART 1)만으로 "완료" 선언 금지. verdict.json 에 "PART 2 수동 미검증 잔여(실 로그인·실 playwright·launchd 실부팅)"를 명시하고, 사장님 맥 수동 체크 전까지 "라이브 실운영 완료" 표현 금지.

### ⭐ 마지막에 — 전체 프로세스 상세 브리핑(recap) 필수
끝낼 때 사장님께 쉬운 한국어로: ①무엇을 배선했나(파일·PR번호 — runner 팩토리 신설 + loop 라이브 플래그) ②왜(지금까지 데몬이 "연습(dry_run)"만 돌았고, 실제 검색으로 넘어가는 마지막 연결선이 비어 있었다) ③**어떻게 검증했나 — G/V1(Codex)/V2(리셋 Claude)/T 각 검증자가 실제로 잡은 결함과 수정 구체적으로** ④증거 숫자 그대로(passed/xfailed, verify exit) ⑤**남은 것 = 수동 확인분**: 사장님이 3사 로그인해 두고, `--executor live` 를 손으로 한 번 돌려보고, launchd 를 수동 load 해야 진짜 "실운영"이라는 점 — 코드만으론 "완료" 아님 ⑥재개/되돌리기 명령(라이브 플래그 켜는 법·끄는 법·데몬 load/unload). 과장·"아마도" 금지.
