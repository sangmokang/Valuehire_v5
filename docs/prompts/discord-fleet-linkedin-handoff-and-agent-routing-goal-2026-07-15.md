# Goal — Discord Fleet: LinkedIn 핸드오프·듀얼 에이전트 라우팅·시작 알림 (2026-07-15)

> 이 문서는 2026-07-15 세션에서 나온 요구사항을 harness 게이트 1(스펙) 형식으로 정리한
> goal 프롬프트 모음이다. 실행은 게이트 0(`make red-ledger`)부터 순서대로.
> 각 이슈는 **인수 기준 1개**, worktree 1개, PR 1개를 원칙으로 한다.

## 0. 세션 요약 (컨텍스트)

1. **disearch 스킬 병합** — codex가 `origin/docs/fleet-b-codex-handoff-prompt`(commit
   `52739f1`)에 만들어두고 main에 안 올라가 있던 Discord 서치 감사 스킬을 로컬 커밋
   `4a0813e`로 main에 병합함. `skills/disearch/`(codex용) +
   `.claude/skills/disearch/`(Claude용, 스크립트 경로를 `$HOME/.codex` 비의존 repo-relative로
   수정). **origin에 아직 push 안 함** — 별도 확인 필요.
2. **미병합 브랜치 전수 감사** — main에 안 올라간 다른 완성 코드가 있는지 백그라운드
   에이전트로 ~60개 원격 브랜치를 스캔 완료. **결과 리포트는 아직 사용자에게 전달 안 함**
   — "브랜치 감사 결과 보여줘"라고 하면 이어서 보고.
3. `/disearch` 라이브 실행 — fleet-run 제어평면 감사 완료, 224개 테스트 GREEN, HIGH 결함
   5건 확인(코드 변경은 미실행, 승인 대기).
4. 아래 §1~§3, §5, §6 이 이번에 확정된 신규 스펙. §4 는 "이미 구현돼 있어 신규 작업 불필요"로
   판정된 항목(기록만). §0.5 는 "쉘 명령 그대로 전달" 요구에 대한 기술 확인.

## 0.5 "쉘창 명령 그대로 전달" — 사장님 지시로 **채택 확정** (2026-07-15 정정)

> 이전 판단("안전 템플릿 유지, verbatim 전달로 되돌리지 않는다")을 **철회한다.**
> 사장님이 명시적으로 "쉘 명령 그대로 전달해라 — /disearch 같은 고정 명령만 시킬 게
> 아니라, 서치든 코드 수정이든 다목적으로 쓸 거다"라고 지시했고, 이건 본인 시스템에
> 대한 위험 감수 결정이다(오너 권한 범위 — 최상위 규칙 "사용자의 명시적 지시가 항상
> 최우선"). 아래 §7(이슈 F)에서 구체적으로 스펙화한다.

### 기술 검토 — 이게 이슈 A~E와 충돌하지 않는 이유
- **이슈 A/B/C(fleet-run 큐 경로)는 그대로 둔다.** 그 경로는 검색 전용(SOT28 발송게이트,
  `FLEET_SKILLS` 화이트리스트)이고, 팀원도 쓸 수 있는 다인용·감사가능 큐다. 여기에
  verbatim을 섞으면 팀원도 임의 명령을 큐에 넣을 길이 생겨 SOT28이 무너진다 — **하면 안
  된다.**
- **verbatim 전달은 이미 존재하는 다른 경로(`scripts/discord_command_listener.py`,
  오너 전용 DM 브리지)에 얹는다.** 이 경로는 이미 오너 전용(`OWNER_ID` fail-closed),
  큐/멀티유저가 아니라 1:1 DM, `/disearch` 감사에서 `LEGACY`로 분류했지만 그건 "격리해야
  할 위험"이 아니라 "지금 사장님이 원하는 바로 그 기능"이었던 것으로 재해석한다.
- **남는 위험은 그대로 남는다 — 숨기지 않는다.** 인가·큐·발송게이트 없음, 임의 로컬
  파일/셸 접근 가능(Claude/Codex의 자체 도구 권한 범위 내), 원문 그대로 프롬프트 인젝션
  경계가 사실상 "오너 본인이 입력했다"는 것 하나뿐. **이건 오너 DM 1:1 채널에서만 허용하고,
  fleet-run 큐/팀원 경로로는 절대 확장하지 않는다**를 이슈 F의 불변식으로 못박는다.

---

## 1. 이슈 A — fleet-run "링크드인/linkedin" 트리거 → url→aisearch 순차 핸드오프

### 배경
`natural_fleet_command_text`(`tools/multi_position_sourcing/hermes_fleet_bridge.py`)는
현재 "링크드인"이라는 단어를 특별 취급하지 않는다. "@hermes_v5 <포지션 링크>
링크드인에서 찾아"는 그냥 일반 "찾아" 트리거로 처리되어 aisearch가 바로 큐잉되고,
그 포지션의 LinkedIn RPS 라이브서치가 사전에 준비(`/url`)되어 있는지 확인하는 단계가 없다.

### 확정 설계 (가벼운 순차 발사 — DB 마이그레이션 없음)
- 자연어에 "링크드인" **또는 영문 "linkedin"**(대소문자 무관)이 포함되고 포지션 URL(검색결과
  URL 아님)이 있으면 skill=url, `params.followup_skill="aisearch"`.
- `skill:` 이 명시되어 있으면 이 규칙 무시(기존 "명시 우선" 원칙 유지).
- `fleet_worker`가 그 잡을 `status=done`으로 release할 때 `params.followup_skill`을 보고
  동일 `position_url`·`machine`·`requested_by`로 aisearch 잡을 자동 enqueue.
  **체이닝은 1단계 고정**(후속 잡엔 `followup_skill`을 심지 않음 — 무한 체인 방지).
- url 잡이 `failed`/`paused_for_human`/`cancelled`로 끝나면 후속 잡 미발사.
- `DEFAULT_REPORT_CHANNEL`(fleet_worker.py) == `DM_CHANNEL`(discord_command_listener.py)
  리터럴 동치 회귀 가드 테스트 추가 — 이 값이 갈라지면 캡차/로그인 알림이 사장님 DM
  밖으로 조용히 샐 수 있음.
- **(추가) "사람인"/"잡코리아" 트리거 → skill=aisearch 직행.** 링크드인과 달리 사람인·잡코리아는
  이 레포에 RPS 같은 "사전 검색 준비" 스킬이 없으므로 url 전단계 없이 바로 aisearch.
  이미 `_default_skill_for_urls`가 대부분 이렇게 동작하지만(검색결과 URL이 안 섞여 있으면
  aisearch 기본값), "링크드인" 신규 분기와 뒤섞여 우선순위가 흐려지지 않도록 명시 테스트로
  고정한다.
- **(확인) 기기 별칭 "Win"(대소문자 무관) → winpc.** 코드 확인 결과 자연어 경로
  (`words = set(re.findall(...low...))`, `low = raw.lower()`)와 직접 명령 경로
  (`_classify_bare_fleet_run_token`의 `token.lower() in _MACHINE_ALIASES`) 모두 **이미
  대소문자 무관하게 처리한다.** 새 코드 불필요 — 회귀 방지용 테스트 케이스만 추가.

### 인수 기준 (./verify.sh 로 검사 가능한 단언 1개 — pytest 신규 스위트)
- "https://career.wrtn.io/ko/o/172878 이 포지션 링크드인에서 찾아" → skill=url,
  params.followup_skill=aisearch
- "... position linkedin search please"(영문) → 동일 결과
- "이 포지션 사람인이랑 잡코리아에서 찾아줘 <URL>" → skill=aisearch (followup_skill 없음),
  channels=(saramin,jobkorea)
- "skill:aisearch" 가 명시된 문장은 이 규칙을 타지 않는다
- "... Win 에서 링크드인 찾아줘 <URL>" → machine=winpc **그리고** skill=url(링크드인 규칙과
  독립적으로 동시 적용됨을 확인)
- `new_job_payload(params={"followup_skill": "aisearch"})` → 유효 payload,
  `params={"followup_skill": "not-a-skill"}` → None
- `FleetWorker`가 `followup_skill=aisearch`인 잡을 done으로 release하면 큐에
  skill=aisearch, 동일 position_url/machine/requested_by 잡이 정확히 1건 추가(mock queue)
- 동일 잡을 failed/paused_for_human/cancelled로 release하면 enqueue 호출 0건
- 후속으로 enqueue된 aisearch 잡의 payload엔 `followup_skill` 키가 없음(1단계 체이닝 고정)
- `DEFAULT_REPORT_CHANNEL == DM_CHANNEL` 리터럴 동치 테스트 통과

### 게이트 2 프롬프트
```
make task NAME=linkedin-url-aisearch-handoff
위 인수 기준 전부를 실패하는 테스트를 tests/test_hermes_fleet_bridge.py,
tests/test_job_queue.py, tests/test_fleet_worker.py 에 추가하고 커밋(RED 확인 —
.venv/bin/python -m pytest 로 실패를 직접 확인한 뒤 커밋).
RED→GREEN 최소 변경:
- hermes_fleet_bridge.py: natural_fleet_command_text 에 "링크드인"/"linkedin" 트리거 분기
- job_queue.py: new_job_payload 에 params.followup_skill 검증
- fleet_worker.py: done release 경로에 후속 잡 enqueue 로직(체이닝 1단계 강제)
목표 규모: 파일 3개, diff 50~300줄. ./verify.sh 실행, 출력 그대로 보고. make ship.
```

---

## 2. 이슈 B — fleet 잡 에이전트 선택(claude|codex)

### 배경
Discord로 받은 명령을 "Claude Code 또는 Codex 쉘에 그대로 입력한 것처럼" 동작시킨다.
`FleetWorker.runner`는 이미 교체 가능한 콜러블 구조(`_run_claude` 하나뿐). Codex 비대화형
실행은 `codex exec <prompt>`로 확인함(claude -p와 동형).

⚠️ **기술 제약**: codex CLI는 이 세션 실행 머신(`/Users/kangsangmo/.local/bin/codex`)에서만
확인됨 — macmini/winpc/macbook 각 fleet 머신 설치 여부는 **미확인**(SOT29 §7과 같은 성격의
하드웨어 체크리스트, 코드 범위 밖).

### 확정 설계
- fleet-run 옵션에 `agent:claude|codex` 명시 지정 허용(기존 `machine:`/`skill:` 패턴과 동일).
- 자연어에 "codex" 단어가 있으면 agent=codex, 없으면 기본 claude(명시 우선 원칙 재사용).
- `new_job_payload`는 `params.agent`가 있으면 `{"claude","codex"}` 중 하나인지 검증,
  아니면 None(fail-closed).
- `FleetWorker`는 `job.params.agent`에 따라 `_run_claude` 또는 신규 `_run_codex`
  (`codex exec`) 선택. 미지정 시 기존과 100% 동일(회귀 없음).
- **범위 밖**: 3개 머신 각각의 codex 설치·인증 확인(사장님 수동, 별도 이슈).

### 인수 기준
- "... codex ..." 포함 자연어 → options.agent="codex"
- 명시 없음 → agent 키 없음 또는 "claude"(기존 호출부 하위호환)
- `new_job_payload(params={"agent":"codex"})` 유효, `params={"agent":"gpt4"}` → None
- `FleetWorker`(runner 미지정)가 agent="codex" 잡 처리 시 subprocess 호출 인자가
  `["codex","exec",prompt]`인지 mock으로 검증
- agent 미지정 잡은 기존 테스트(claude -p 호출)가 그대로 통과 — 회귀 0

### 게이트 2 프롬프트
```
(이슈 A merge 후) make task NAME=fleet-agent-claude-codex
위 인수 기준을 RED→GREEN.
파일: hermes_fleet_bridge.py(agent 파싱), job_queue.py(agent 검증),
fleet_worker.py(_run_codex 추가 + 선택 로직) + 각 테스트.
목표 규모: 파일 3개, diff 50~200줄.
⚠️ 테스트는 subprocess 호출 인자를 mock으로 캡처 — 실제 codex 실행 없이 GREEN 가능해야 함.
./verify.sh 실행, 출력 그대로 보고. make ship.
```

---

## 3. 이슈 C — fleet_worker 잡 claim 시 "실행 시작" 중간 알림

### 배경
`discord_notify`는 이미 enqueue/완료/실패/일시정지를 사장님 DM
(`DEFAULT_REPORT_CHANNEL == 1512503041448743092`, 유저 `814353841088757800`)으로 보낸다.
다만 claim 직후 ~ 완료 사이 공백이 있어 오래 걸리는 잡의 진행 여부를 알 수 없다.

### 확정 설계
- `FleetWorker.run_once`가 잡을 claim하고 `build_job_prompt`가 성공한 직후(실행 직전),
  dry_run이 아니면 `"▶️ 잡 #{id} 실행 시작 ({machine}, skill={skill}) — position: {url}"`
  알림 1회.
- fail-soft(전송 실패해도 잡 진행에 영향 없음) — 기존 `_notify` 규약 재사용.
- dry_run=True 경로는 알림 추가 안 함(중복 방지).

### 인수 기준
`run_once`가 정상 잡(dry_run=False) 처리 시 mock notifier 호출 순서가
`["▶️ 실행 시작...", "✅ 완료..."(또는 실패/일시정지)]` 순으로 기록됨.
dry_run=True 경로는 "▶️ 실행 시작" 알림이 호출 안 됨.

### 게이트 2 프롬프트
```
make task NAME=fleet-worker-start-notify
위 인수 기준을 RED→GREEN.
파일: tools/multi_position_sourcing/fleet_worker.py(run_once에 self._notify 한 줄) +
tests/test_fleet_worker.py(알림 순서 검증).
목표 규모: 파일 2개, diff 20~60줄 — 가장 작은 이슈, 먼저 처리해도 무방.
./verify.sh 실행, 출력 그대로 보고. make ship.
```

---

## 5. 이슈 D — LinkedIn RPS가 로그인된 실제 머신을 찾아 라우팅 (정책 결정 필요)

### 배경
지금은 `build_fleet_job_payload`(fleet_dispatch.py)가 machine 미지정 시 무조건
`"macmini"`로 기본값을 박는다. 요청은 "RPS가 다른 맥북/맥미니에 로그인돼 있으면 그
머신을 찾아서 서치"다.

⚠️ **기술 확인 — 지금은 불가능하다(코드 추가 필요).**
- `portal_login.py`가 쓰는 `artifacts/portal_session_status_latest.json`은 **머신
  로컬 파일**이다 — 중앙에서 "어느 머신이 RPS 로그인 상태인지" 조회할 방법이 없다.
- `discord_routing.py`의 `session-status`/`relogin-needed` 슬래시 명령은 스키마만 있고
  (`SCHEMA_ONLY`, `/disearch` 감사에서 확인한 것과 동일 패턴) 실제 리시버가 없다.
- **SOT29 §2와 정면 충돌**: `docs/sot/29-fleet-control.md:20` —
  "LinkedIn Recruiter 시트가 1개뿐이면 LinkedIn 잡은 `macmini` 전용으로 묶는다."
  이건 사장님이 이미 확정한 정책이다. "로그인된 머신을 찾아 라우팅"으로 바꾸려면
  이 SOT 조항 자체를 개정해야 한다 — **코드만으로 결정할 사안이 아니다.**

### 제안 설계 (구현 전 정책 확인 필요)
1. 기존 heartbeat 배선(`fleet_heartbeat.py:heartbeat_payload`, 1분마다 RPC)에
   `linkedin_rps_logged_in: bool` 필드를 추가(로컬 `portal_session_status_latest.json`을
   워커가 heartbeat 전송 시 읽어서 채움). DB 마이그레이션 필요(heartbeats 테이블 컬럼 추가).
2. `build_fleet_job_payload`/`fleet_dispatch`가 skill=url 또는 링크드인 관련 잡을 만들 때,
   machine 미지정이면 heartbeat 조회로 `linkedin_rps_logged_in=true`인 머신을 선택.
   **아무도 로그인 안 돼 있으면 기존처럼 macmini로 폴백**(fail-safe, 무동작보다 나음).
3. SOT29 §2 문구를 "고정 macmini 전용" → "로그인 상태 기반 라우팅, 미검출 시 macmini
   폴백"으로 개정(사장님 승인 필요 — 라이선스 좌석 정책과 직결).

### 결정 필요 사항 (진행 전 확인)
- 이 정책 변경(SOT29 §2 개정)을 승인하는지.
- 승인되면 별도 이슈로 스펙 확정 후 게이트 1부터 — heartbeat 스키마 변경이 껴 있어
  "가벼운" 규모가 아니다(DB 마이그레이션 1개 + heartbeat/dispatch 로직 변경).

## 6. 이슈 E — fleet_worker 실행 시 브라우저 "자동화 사용중" 배지 배선

### 배경
`raw_cdp.py:55~57`에 이미 `VH_BUSY_TASK`/`VH_BUSY_AGENT` 환경변수를 읽어
"🤖 {agent} 자동화 사용중 · {task}" 배지를 띄우는 메커니즘이 있다(`/url` 스킬 문서에
"raw CDP 전에 `export VH_BUSY_TASK=/url`" 지침으로 이미 안내됨). 다만 `fleet_worker.py`는
`claude -p`/`codex exec` 서브프로세스를 띄울 때 이 env를 **설정하지 않는다** — 스킬 자체
프롬프트가 그 지침을 담고 있어 서브에이전트가 알아서 export 하길 기대하는 구조다.

⚠️ **"disearch중" 표기 관련 확인 필요**: `disearch`는 이 대화에서 만든 **감사(audit) 스킬
이름**이지, 서치를 수행하는 스킬이 아니다(서치는 `url`/`aisearch`/`humansearch`). 배지에
문자 그대로 "disearch"를 쓰면 실제 동작(예: aisearch 실행 중)과 다른 라벨이 붙어 오히려
헷갈릴 수 있다. **기존 메커니즘을 그대로 살려서, 배지가 실제 실행 중인 스킬+잡 번호를
보여주도록 하는 쪽을 제안한다** — 예: `🤖 자동화 사용중 · fleet #24 (aisearch)`.
문자 그대로 "disearch"라는 고정 라벨을 원하면 알려달라(그러면 실제 스킬명 대신 이 고정
문자열을 쓰도록 변경).

### 제안 설계 (사용자 확인 후 게이트 1 확정)
- `FleetWorker`가 러너(`_run_claude`/`_run_codex`) 호출 직전, subprocess 환경에
  `VH_BUSY_TASK=f"fleet #{job_id} ({skill})"`, `VH_BUSY_AGENT=agent`(claude/codex)를 주입.
- 잡 종료(done/failed/paused_for_human) 시 해당 env는 그 서브프로세스와 함께 종료되므로
  별도 해제 로직 불필요(프로세스 스코프 env — 다음 잡에 잔존 안 함).

### 인수 기준 (배지 라벨 확정 후 작성 — 아래는 초안)
`_run_claude`/`_run_codex` 호출 시 전달되는 subprocess env에 `VH_BUSY_TASK`가
`job_id`와 `skill`을 포함하고, `VH_BUSY_AGENT`가 선택된 agent와 일치함을 mock으로 검증.

### 게이트 2 프롬프트 (라벨 확정 후 실행)
```
make task NAME=fleet-worker-busy-badge
파일: tools/multi_position_sourcing/fleet_worker.py(러너 호출 시 env 주입) + 테스트.
목표 규모: 파일 2개, diff 20~50줄.
./verify.sh 실행, 출력 그대로 보고. make ship.
```

---

## 7. 이슈 F — Discord DM = 쉘 프론트엔드 (다목적 명령, verbatim 전달)

### 배경
사장님이 원하는 것: Discord DM에 뭘 치든(서치든, "이 코드 버그 있는 것 같은데 고쳐줘"
같은 임의 구현 지시든) 그게 **그대로 쉘에서 `claude -p`/`codex exec`를 친 것과 동일하게
동작**하고, 결과가 Discord로 돌아온다 — Discord를 쉘의 프런트엔드로 쓰겠다는 것.
`scripts/discord_command_listener.py`가 이미 이 뼈대(오너 DM 폴링 → 원문 그대로
`claude -p` → 결과 회신)를 갖고 있다. 지금 안 되는 건 **codex 선택지가 없다는 것**뿐 —
나머지(오너 전용 인가, 원문 그대로 전달, DM 회신)는 이미 verbatim이다.

### 확정 설계
1. **agent 선택을 명시 접두어로만 인식한다** — 자연어 임의 문장 안에 우연히 "codex"라는
   단어가 섞일 수 있으므로(예: "이거 코덱스 라이브러리 얘기야"), fleet 경로(이슈 B)처럼
   문장 전체를 훑어 단어 매칭하지 않는다. 대신 메시지가 **`codex:` 로 시작할 때만**(대소문자
   무관, 앞뒤 공백 허용) agent=codex로 전환하고 그 접두어를 벗겨낸 나머지를 프롬프트로 쓴다.
   접두어 없으면 기존과 동일 agent=claude, 프롬프트는 원문 그대로(진짜 verbatim 유지).
2. **원문은 절대 재구성하지 않는다**(이슈 A/B의 "안전 템플릿"과 정반대 — 여기가 바로
   verbatim이 필요한 지점). 접두어 파싱만 하고 나머지 텍스트는 1바이트도 안 건드린다.
3. **오너 전용 게이트는 그대로 유지**(`OWNER_ID` 하드코딩, fail-closed) — 이슈 F는 이
   불변식을 절대 완화하지 않는다. 이게 fleet-run 팀원 경로로 새면 SOT28이 무너진다.
4. **회신은 이미 Discord DM으로 옴**(`_send()`) — "쉘 프런트엔드처럼 보이게"는 이미
   충족. 추가로 요청 접수 시 즉시 "⏳ 접수: ... — 실행 중…"(이미 있음)에 선택된 agent를
   표시해 사장님이 어느 엔진이 도는지 알 수 있게 한다: "⏳ 접수(codex): ... — 실행 중…".

### 인수 기준
- `select_agent_and_prompt("찾아줘 이 링크")` → `("claude", "찾아줘 이 링크")`(원문 그대로,
  1바이트도 안 바뀜)
- `select_agent_and_prompt("codex: 이 버그 고쳐줘 foo.py 43번째 줄")` →
  `("codex", "이 버그 고쳐줘 foo.py 43번째 줄")`
- `select_agent_and_prompt("Codex:   fix bug")`(대소문자·여러 공백) →
  `("codex", "fix bug")`
- `select_agent_and_prompt("이거 코덱스 얘기인데 찾아줘")`(접두어 아닌 문장 중간 "코덱스"/
  "codex") → `("claude", "이거 코덱스 얘기인데 찾아줘")`(오탐 방지 — 접두어일 때만 전환)
- `_run_claude`/`_run_codex`(신규) 선택 후 실제 subprocess 인자가 각각
  `["claude","-p",prompt]` / `["codex","exec",prompt]`인지 mock으로 검증
- 기존 `select_new_commands`/`is_kill_command`/`acquire_single_instance_lock` 등 기존
  테스트 전부 회귀 없이 통과

./verify.sh 로 pytest 레벨 검증. 라이브 Discord/claude/codex 실행 없음.

### 게이트 2 프롬프트
```
make task NAME=discord-dm-shell-frontend-codex
위 인수 기준을 RED→GREEN.
파일: scripts/discord_command_listener.py(select_agent_and_prompt 순수함수 추가,
_run_claude를 agent 인자 받는 형태로 확장 또는 _run_codex 신규 추가, main loop 에서
선택 반영 + 접수 메시지에 agent 표시) + tests/test_discord_command_listener.py.
목표 규모: 파일 2개, diff 40~120줄.
⚠️ 원문 재구성 금지 — 접두어 파싱 이후 텍스트는 그대로 프롬프트로 전달(진짜 verbatim).
⚠️ OWNER_ID 게이트·킬스위치·단일인스턴스락 등 기존 안전장치는 절대 약화하지 않는다.
./verify.sh 실행, 출력 그대로 보고. make ship.
```

---

## 4. 이미 충족되어 신규 작업 불필요 (기록용 — 재작업 금지)

검토 결과 아래 항목은 **이미 코드+테스트로 구현되어 있음**. 새 이슈를 만들지 않는다.

| 요구사항 | 근거 |
|---|---|
| Discord 명령 실행 시 중간/완료 보고를 사장님(`814353841088757800`) DM으로 | `fleet_worker.py:31 DEFAULT_REPORT_CHANNEL`가 `discord_command_listener.py:28 DM_CHANNEL`(사장님 개인 DM)과 동일 리터럴 — enqueue/실패(6종)/일시정지/완료 알림 이미 전부 이 채널로 감. 유일한 공백(claim~완료 사이)은 §3 이슈 C로 메움 |
| ClickUp `901818680208`에 포지션별 중복확인 후 SubTask에 profile_url·요약·적합/미스매치 등록 | `skills/humansearch/SKILL.md:125, 202~212` — 부모 Task 재사용, 후보 profile_url 중복검사 후 등록, fail-closed 게이트(중복검사 미수행/list id 불일치/url 무효/저장증거 없음 시 생성 금지). `test_humansearch_register.py` 등 164 passed |
| 열어본 프로필 전부 저장(점수 무관) | `skills/humansearch/SKILL.md:127~132` — results.json + 로컬 DB + Supabase(`profile_archives`+`sourcing_results`, 멱등 upsert). "저장 증거 없는 후보는 ClickUp 등록 금지" |
| Boolean 검색어 한/영/띄어쓰기 JD 키워드 추가 발굴 | `tools/multi_position_sourcing/humansearch_keyword_expand.py:112 expand_search_terms()` — 한↔영·띄어쓰기 변형 확장 + JD 갭 리포트 + LLM 큐레이션. `test_humansearch_keyword_expand.py` GREEN |

라이브 실행(실제 포지션 1건으로 `/humansearch` 돌려서 ClickUp에 정말 이 형식대로 등록되는지
실측)은 이 문서 범위 밖 — 승인 시 별도 진행.

---

## 다음 행동
1. **이슈 F(오너 승인·지시 완료 — 바로 게이트 0→2 진행)**: 사장님이 이번에 명시적으로
   실행을 지시했으므로 우선 착수 대상.
2. 이슈 C(가장 작음) → A(확장판) → B → E(배지 라벨 확정 후) 순서로 나머지 워크트리 진행.
   **이슈 D는 SOT29 §2 개정 승인부터.**
3. 이슈 D 진행 여부(SOT29 §2 "macmini 전용" 정책 개정 승인) 확인.
4. 이슈 E 배지 라벨 확정("disearch" 고정 문자열 vs 실제 스킬명+잡번호) 확인.
5. disearch 커밋(`4a0813e`) origin push 여부 확인.
6. 미병합 브랜치 감사 리포트 전달 여부 확인.
