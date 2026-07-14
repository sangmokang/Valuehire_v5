# Codex 작업 지시서 — fleet 완료 시 ClickUp 등록 + 후보별 디스코드 리포트

> 이 문서를 그대로 `codex exec`(또는 대화형 `codex`) 프롬프트로 붙여넣어 실행한다.
> Claude가 아니라 Codex가 구현자다 — 아래 harness 절차(자기 적대검증 포함)를 **네가 직접** 지켜라.

## 0. 너의 역할과 제약

이 저장소(`Valuehire_v5`)는 "코드는 안 믿는다 — 두 번 깐다" 원칙을 쓴다. 보통은 Claude가 구현하고
Codex Rescue가 독립 2차 검증을 하는데, 이번엔 **네가 구현자다.** 그러니 너는:
1. 구현한다.
2. 다 만든 뒤, **너 자신이 아니라 완전히 남의 코드인 것처럼** 다시 한번 적대적으로 깨본다
   (증거 없이 "됐다" 금지 — 실제로 pytest 실행, 실제로 코드 읽고 반례 찾기).
3. `## 적대 검증 로그`에 무엇을 어떻게 깼는지 실제 명령/출력과 함께 남긴다.
둘 다 통과 못 하면 "완료"라고 하지 마라.

## 1. 저장소·워크트리 규칙 (필수)

- 작업 위치: `C:\Users\DELL\Desktop\Valuehire_v5` (Windows).
- **메인 작업트리를 직접 고치지 마라.** `bash scripts/harness/task.sh <slug>` 로 워크트리를 판 뒤
  그 안에서만 작업한다(`../Valuehire_v5-<slug>` 에 생성됨, 브랜치 `task/<slug>`).
- **베이스 커밋은 반드시 `999a47a`(현재 HEAD)여야 한다 — `main` 브랜치가 아니다.**
  `main`(`a34ab81`)엔 아직 이 작업이 쓰는 `natural_fleet_command_text`/자연어 fleet 라우팅
  기능 자체가 없다(그건 `4e2f4e5`에서 도입, `999a47a`가 그걸 포함하는 최신 지점). `task.sh`를
  현재 메인 작업트리(HEAD=999a47a)에서 실행하면 자동으로 이 지점에서 갈라진다 — 다른 브랜치로
  체크아웃하지 마라.
- 이미 같은 계열의 다른 작업 브랜치가 있다: `task/humansearch-portal-search-skill`
  (PR #96, 병합 대기 중, 자연어 URL→humansearch 자동선택). 이번 작업은 그 브랜치에 의존하지
  않는다(건드리는 파일이 다름 — `fleet_worker.py`/`humansearch_register.py` 쪽) — **독립적으로
  `999a47a`에서 새 워크트리를 파라.** 나중에 두 PR이 합쳐질 때 파일이 겹치지 않으니 충돌 걱정 안 해도 된다.
- **⚠️ 베이스라인 사전 결함(중요, 반드시 읽어라)**: 이 워크트리를 아무것도 안 고치고
  `./verify.sh`(또는 `python -m pytest tests/ -q`)만 돌려도 **54개가 이미 실패한다.**
  전부 이 Windows 개발 머신의 포털 브라우저 프로필 잠금·암호화 이식성 문제
  (`test_portal_tab_guard.py`, `test_portal_bg_login_plumbing.py`, `test_portal_cdp_discovery.py`,
  `test_search_machine_config.py`, `test_multi_position_sourcing.py`의 포털락/스냅샷 계열 등)이고,
  이 작업이 건드리는 `fleet_worker.py`/`humansearch_register.py`와는 무관하다(별도 진행 중인
  작업). **네 변경 전후로 이 54개 숫자가 그대로인지만 확인하면 된다** — 이 54개를 고치려 들지
  마라(범위 밖, 시간 낭비). Gate 4 보고 시 "타겟 스위트 결과" + "전체 스위트 실패 개수가
  54에서 안 늘었다"를 같이 적어라.
- **Gate 5(ship)도 이 54개 때문에 자동으로 막힌다** (`scripts/harness/ship.sh`가 `verify.sh`
  exit code로 판정하는데, 54개 pre-existing 실패 때문에 항상 non-zero). 그러니 `make ship`
  대신 직접: `git push -u origin task/<slug>` 후 PR 생성. `gh` CLI가 이 머신에 없을 수 있다 —
  없으면 `git credential fill`로 얻은 토큰으로 GitHub REST API(`POST /repos/sangmokang/Valuehire_v5/pulls`)를
  직접 호출해라(토큰을 절대 로그/출력에 남기지 말 것). PR 본문에 "베이스가 999a47a라 PR #96과
  같은 계열의 무관한 선행 커밋 2개(`4e2f4e5`, `999a47a`)가 같이 포함된다"는 점과 "54개는
  무관한 사전 결함"이라는 점을 반드시 적어라.

## 2. 배경 — 왜 이 작업을 하는가

`docs/sot/29-fleet-control.md` 체계로 디스코드에서 `/fleet-run`(또는 자연어)으로 aisearch/humansearch
잡을 큐에 넣으면, 각 머신(`macmini`/`macbook`/`winpc`)의 `fleet_worker.py`가 그 잡을 받아
`claude -p <프롬프트>`로 실제 서치를 실행한다. 서치 완료 후:
- `tools/multi_position_sourcing/fleet_worker.py:build_job_prompt()`의 규칙 12·17이 이미
  `claude -p`에게 `FLEET_SEARCH_RECEIPT:` 마커 뒤에 후보별 JSON
  (`candidate_name, profile_url, channel, score, why_fit, profile_summary, evidence,
  hard_excluded, saved` 등)을 stdout 마지막 줄에 출력하라고 시키고 있다.
- `validate_aisearch_receipt()`(같은 파일)가 그 영수증의 스키마를 검증한다 — **그런데 지금은
  `job.get("skill") == "aisearch"`일 때만 이 검증을 돈다** (`run_once()` 안,
  `if job.get("skill") == "aisearch":` 조건문). `humansearch` 잡은 이 검증을 완전히 건너뛴다.
- 검증 통과 후 `run_once()`는 그냥 `self._notify(job, f"✅ 잡 #{job_id} 완료 ({self.machine}):\n{result['summary'][:1500]}")`
  로 **AI가 stdout에 쓴 자유 텍스트 요약을 그대로 잘라서** 디스코드로 보낸다 — 이미 받아둔
  구조화된 영수증(candidates 리스트)을 전혀 재사용하지 않는다.
- 클릭업 FY26AI_Search(리스트 901818680208) 등록 로직은 이미
  `tools/multi_position_sourcing/humansearch_register.py`에 있다(`register_clickup_fy26_ai_search()`,
  `build_message()`, `post_discord()` 등) — 근데 이건 **fleet 파이프라인에서 전혀 호출되지
  않는다.** 이 모듈은 다른(수동/단일 포지션) 워크플로우용으로 만들어졌다(아래 3-2 참고,
  그대로 재사용하면 안 됨).

사장님 요청 원문: "여러 사람이 다른 디스코드 아이디로 명령을 할 때 브라우저가 새로 열려서
서로 간섭하지 않거나 순차적으로 처리하도록 하고 결과를 클릭업의 aisearch [FY26AI_Search
리스트]에 등록하고 디스코드 답변으로도 profile url, 매칭 점수 100점만점에 몇점, 왜 잘맞는지
이유, 프로필의 약력 브리핑까지 해서 오도록 SPEC 에 박고, HARNESS hook 에 등록해줘."

## 3. 인수 기준 (EARS) — 워크트리 2개로 쪼갠다

### AC-1 (워크트리 `fleet-completion-clickup-discord-report`)

> When fleet 잡(`aisearch` 또는 `humansearch`)이 `done` 상태로 완료되면, then 시스템은
> (a) `humansearch`도 `aisearch`와 동일하게 `FLEET_SEARCH_RECEIPT` 영수증 검증을 통과해야만
> 완료 처리해야 하고, (b) 검증 통과 후 채널별 후보 중 `score >= 70`(`PASS_THRESHOLD`) &&
> `hard_excluded == False` && `saved == True`인 후보를 클릭업 FY26AI_Search(리스트
> `901818680208`)에 등록해야 하며, (c) 디스코드 완료 알림에 그 등록 대상 후보 각각의
> `profile_url`, `score`(/100 표기), `why_fit`, `profile_summary`를 채널별로 나눠 포함해야 한다.

**검증 명령**: 새 워크트리에서 `python -m pytest tests/test_fleet_worker.py -q` (+ 새로 추가할
`test_fleet_worker.py`의 케이스들).

**counter-AC(가짜 완료로 치지 마라)**:
- humansearch 잡이 영수증 검증 없이 그냥 `done` 처리되는 것(지금 버그 그대로 방치).
- 70점 미만 후보나 `hard_excluded=True`/`saved=False` 후보까지 클릭업에 등록되는 것
  (SOT3/SOT5 위반 — 하드제외·미저장 후보 노출 금지).
- 같은 후보가 같은 포지션에 중복 등록되는 것(`register_clickup_fy26_ai_search`가 이미
  `_search_clickup_tasks`로 중복검사를 하니 **그 함수를 그대로 써라, 재구현 금지**).
- 디스코드 메시지가 여전히 AI 자유 텍스트 요약(`result['summary'][:1500]`)이고 구조화된
  4필드가 안 들어있는 것.
- 발송(제안/InMail/이메일 send)류 스킬·동작을 이 경로에서 트리거하는 것(SOT28 — 이 작업은
  "브리핑 등록"이지 "발송"이 아니다. `register_clickup_fy26_ai_search`/`post_discord`도
  발송이 아니라 브리핑 등록용이라는 걸 그 파일 상단 docstring이 명시함 — 그 경계를 넘지 마라).

**구현 시 반드시 참고할 기존 코드(재발명 금지, 아래 그대로 재사용)**:
- `tools/multi_position_sourcing/humansearch_register.py`:
  - `register_clickup_fy26_ai_search(*, position_name, position_id, passers, channel, clickup_search_tasks, clickup_create_task, dry_run)` —
    실제 ClickUp Task/Subtask 생성 + 중복검사. **그대로 호출해라.**
  - `PASS_THRESHOLD = 70` (같은 파일 상단, `humansearch.py`에서 import).
  - **주의**: `eligible()`/`clickup_registration_eligible()`은 쓰지 마라 — 이 두 함수는
    `reconstruct_captured_profile()`로 학력/재직이력 전체를 다시 조립해 하드제외를
    재판정하는데, 우리 `FLEET_SEARCH_RECEIPT` 영수증엔 그런 전체 이력 데이터가 없다(가벼운
    완료증거 스키마다). 대신 **영수증 자체의 `hard_excluded`/`saved`/`score` 필드를 직접
    걸러서** 위 필터 조건(score>=70 && hard_excluded==False && saved==True)을 네가 직접
    적용해라 — `_create_clickup_task`/`_candidate_task_description`은 `result.get(...)`로
    필드가 없어도(`education`/`employment_history` 등) 안전하게 기본값 처리하니
    `register_clickup_fy26_ai_search`에 바로 넘겨도 죽지 않는다(직접 확인함).
  - **필드명 매핑 필요**: 영수증 후보 dict는 `profile_url`/`candidate_name` 키를 쓰는데
    `register_clickup_fy26_ai_search`/`_candidate_task_description`는 `result["url"]`/
    `result.get("name")`를 읽는다 — 클릭업 등록 직전에 `{"url": c["profile_url"],
    "name": c["candidate_name"], "score": c["score"], "why_fit": c["why_fit"],
    "profile_summary": c["profile_summary"], ...}` 형태로 매핑 dict를 만들어 넘겨라.
    `score`/`why_fit`/`profile_summary` 키 이름은 이미 일치하니 그대로 두면 된다.
  - `position_name`/`position_id`: 잡 페이로드(`job_queue.py:new_job_payload`)엔
    `position_url`만 있고 이름/ID 필드가 없다. `position_url`(클릭업 링크)에서 task id를
    추출해 `position_id`로 쓰고, `position_name`은 (선택) 클릭업 API로 그 task를 조회해
    이름을 가져오거나, 못 가져오면 URL 자체를 fallback으로 써라 — **절대
    `register_clickup_fy26_ai_search`의 모듈 상단 기본값(`POSITION_NAME`,
    `POSITION_ID` — 이건 완전히 다른 특정 포지션 하드코딩값이다)에 그냥 기대지 마라.**
    명시 인자로 항상 넘겨라.
  - **디스코드 메시지**: `build_message()`/`clickup_comment_body()`는 재사용하지 마라 —
    LinkedIn RPS 전용으로 `education`/`breakdown`(학력/직무/논리/안정 4분할 점수) 같은
    영수증에 없는 필드를 요구하고, 사장님이 원하는 포맷(profile_url·score·why_fit·
    profile_summary 4개만)과도 다르다. `fleet_worker.py`에 새 포맷 함수를 하나 만들어라
    (이름 예: `format_fleet_completion_report(receipt, job)`), 채널별로 나눠 후보마다
    `이름 — {score}/100`, `왜 잘 맞는지: {why_fit}`, `약력: {profile_summary}`,
    `{profile_url}` 를 담고, 디스코드 2000자 제한을 넘으면 잘라라(기존 관례,
    `post_discord`의 `message[:1990]` 패턴 참고).
- `tools/multi_position_sourcing/fleet_worker.py`:
  - `validate_aisearch_receipt(stdout, params)` — 이미 있는 검증 함수, 그대로 재사용.
    `run_once()`의 `if job.get("skill") == "aisearch":` 를
    `if job.get("skill") in ("aisearch", "humansearch"):` 로 넓혀라.
  - `run_once()`가 검증 통과 후 `self._notify(...)` 부르는 지점에서, 위에서 만든 등록+포맷
    로직을 끼워 넣어라. **ClickUp/Discord 호출이 실패해도 잡 자체는 `done`으로 이미 확정된
    뒤여야 한다(fail-soft) — job 상태를 이 등록 실패 때문에 되돌리지 마라**(서치 자체는
    성공했으니). 대신 등록 실패는 별도 알림/로그로 남겨라(예: `discord_notify`로 경고).
  - `discord_notify(job, text)` — 기존 디스코드 발신 함수, 그대로 재사용.

### AC-2 (워크트리 `fleet-sequential-processing-spec`, AC-1과 독립·더 작음)

> When 동시에 여러 디스코드 사용자가 같은 머신(예: 기본값 `macmini`)으로 fleet-run 명령을
> 여러 개 보내면, then 그 머신의 `fleet_worker`는 한 번에 한 잡만 `claim`·실행해야 하고
> (동시에 두 번째 크롬 세션을 열지 않아야 하고), 나머지는 큐에서 순서대로 대기해야 한다.

이건 **이미 이렇게 동작하는 것으로 보인다** — `job_queue.py`의 `claim_next()`가 원자적 큐
클레임(Supabase RPC/조건부 UPDATE 등)이고 `fleet_worker.py`의 `loop()`가 싱글스레드로
`run_once()`를 순차 호출하는 구조이기 때문. **이번 AC는 새 기능을 만드는 게 아니라, 이 보장을
기계 검증 가능한 테스트로 못박고 SOT 문서에 명시하는 것이다.**

**할 일**:
1. `job_queue.py`의 `claim_next()` 구현을 읽고, 두 워커(또는 같은 워커의 두 연속 호출)가
   같은 잡을 동시에 못 가져가는지(원자성) 확인 — 이미 DB 레벨에서 보장되면 그 근거(RPC/조건부
   UPDATE where절)를 테스트 주석에 file:line으로 남기고, 동시 클레임 시도를 시뮬레이션하는
   테스트를 추가해라(가짜 DB 클라이언트로 두 번 연속 claim 시도 → 두 번째는 빈 결과).
2. `docs/sot/29-fleet-control.md`(또는 `.json`)에 "동시 명령이 몰려도 머신당 순차 처리"를
   한 줄 명문화해라(SOT diff 필요 — strict 규칙: 동작을 문서화하는 거라 SOT 수정 자체는
   기존 동작을 안 바꾸니 위험하지 않다).
3. **주의**: 이건 "새 브라우저를 열어서 안 겹치게" 방식이 아니라 "하나씩 순서대로 처리"
   방식이다(사장님 요청 원문의 두 옵션 중 후자) — 혼동하지 마라, 여러 브라우저를 동시에
   열게 만드는 방향으로 고치지 마라(그건 사고 위험을 늘린다).

## 4. 공통 규칙 (SOT, 어기지 마라)

- `docs/sot/28-auto-send-policy.json`(SOT28) — 이 작업의 어떤 코드 경로도 제안/InMail/이메일
  "발송"을 직접 트리거하면 안 된다. ClickUp Task 생성과 Discord 브리핑 메시지는 "등록"이지
  "발송"이 아니다 — 이 구분을 지켜라.
- `docs/sot/29-fleet-control.md`(SOT29) — 계정↔머신 바인딩·락 정책을 재구현하지 마라.
- 캡차/2FA/사람 개입 관련 기존 `PAUSED_FOR_HUMAN` 처리 로직(`fleet_worker.py`)을 건드리지 마라
  (이 작업 범위 밖).
- 파일 5개 초과 / diff 300줄 초과하면 AC를 더 쪼개라.

## 5. 산출물 (머지 전 필수)

각 워크트리마다:
1. `docs/engineering/<주제>-goal-2026-07-14.md` — 현재상태(file:line 증거)·근본원인·AC(EARS+검증명령+counter-AC)·게이트계획·SOT체크리스트·비범위·롤백.
2. RED 테스트 커밋 → 최소구현 GREEN 커밋(각각 별도 커밋, RED가 먼저).
3. 위 §0의 자기 적대검증 — 실제로 pytest 실행 결과와 함께 goal 문서 `## 적대 검증 로그`에
   무엇을 어떻게 깨보려 했는지 적어라(반증 시도 서술, "됐다"만 쓰지 마라).
4. `git push -u origin task/<slug>` 후 PR(§1의 gh 없을 때 대안 참고). PR 본문에 "베이스가
   999a47a라 무관한 선행 커밋 포함", "54개는 무관한 사전 결함" 명시.
5. 마지막에 사장님께 보고할 **한국어로 쉽게 쓴 3줄 요약**을 PR 본문 맨 위에 추가해라
   (예: "무엇을 했는지 / 왜 / 다음에 뭘 할지" — CLAUDE.md 0번 규칙과 동일 톤, 기술 용어 대신
   쉬운 말로).
