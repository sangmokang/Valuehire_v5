# PC-K6 — 상주 데몬 크래시-루프 제거 + 경로 드리프트 수리 · 구현 킥오프

> 새 세션에 이 내용을 붙여넣어 `/st` 로 착수. **한 조각 = 한 worktree = 인수기준 1개.**

---

## /st PC-K6(상주 데몬 크래시-루프 수리) 구현한다. 과거회수부터 하고 착수해라.

### 저장소 / SOT (먼저 읽어라)
- 저장소: `/Users/kangsangmo/Valuehire_v5` (main). 규칙 `CLAUDE.md`, 루프 `docs/harness.md`, 장부 `.harness/red-ledger.tsv`.
- 설계도: `docs/engineering/valuehire-pipeline-consolidation-spec-addendum-2026-07-02.md`(PC-K6 정의·§3), backlog json.
- 착수 전 `make red-ledger`(clean 확인) + `git worktree list`(다른 세션 A-계열 작업 중 — 그 파일 안 건드림).

### 위험등급 · 모드
- **code-change · L3** (상주 데몬 = 되돌리기 어려운 OS 동작 + SOT 불변식 ①3사 자동로그인 안 막음 ②크롬 점유 양보 ③봇 금지). 풀하네스: worktree → RED→GREEN → G→V1→V2(**병렬**) → verdict.json 3자.

### 현재 상태 (직접 연 file:line — 이번 조사에서 확인)
크래시-루프 **근본원인 확정**:
- `scripts/launchd/com.valuehire.search-runner.plist` — `ProgramArguments`/`WorkingDirectory`/`EnvironmentVariables.VALUEHIRE_REPO_DIR`/로그경로가 전부 **`/Users/kangsangmo/Desktop/Valuehire_v5`** 를 가리킴 + `RunAtLoad=true` + **`KeepAlive=true`**.
- `scripts/valuehire-search-loop.sh:4` — `REPO_DIR="${VALUEHIRE_REPO_DIR:-/Users/kangsangmo/Desktop/Valuehire_v5}"`. `set -euo pipefail`(:2) + `cd "$REPO_DIR"`(:10) → 경로 부재면 즉시 종료 → KeepAlive 무한 재시작.
- **실측**: `/Users/kangsangmo/Desktop/Valuehire_v5` 없음. 실제 repo `/Users/kangsangmo/Valuehire_v5` 존재. 현재 search-runner 는 미로드(load 하면 크래시-루프).
- 루프는 `python3 -m tools.multi_position_sourcing.dry_run --output ...`(`dry_run.py:222 main`, `dry_run=True`) 를 돈다 — dry_run 전용.
- (참고) 형제 데몬 `com.valuehire.portal-browsers.plist`(StartInterval=300, portal_browsers.sh)는 5분마다 3사 디버그 크롬을 띄우다 죽어 깜빡이던 것 → **현재 unload 해둠(응급).** 이 조각에서 그 근본(브라우저가 죽는 이유)까지 볼지, search-runner 데몬만 볼지 스코프 결정.

### 핵심 질문
상주 데몬이 **존재하는 REPO_DIR** 에서 실행되고, 경로 부재/전이 실패에도 **KeepAlive 무한 재시작이 0** 이 되는가? (봇처럼 창을 열었다 닫았다 반복하지 않는다 — SOT2.)

### 계약 (SDD — 손대기 전에 박아라)
**스코프를 2부로 명확히 가른다:**
- **PART 1 (이 조각 = PC-K6 핵심, 지금 가능·기계검증):** 경로 드리프트 + 크래시-루프 제거.
  - `valuehire-search-loop.sh` 가 **자기 위치에서 REPO_DIR 을 도출**(예: `SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"; REPO_DIR="${VALUEHIRE_REPO_DIR:-$SCRIPT_DIR}"`) → Desktop 하드코딩 제거.
  - REPO_DIR 유효성 검사: 없으면 **fail-soft**(명확한 에러 1줄 로그 + KeepAlive 무한재시작을 유발하지 않는 종료전략 — 예: 유효 경로면 진입, 무효면 재시도 백오프 sleep 후 재확인, 즉시 crash-exit 금지). `set -e` 가 `cd` 실패로 프로세스를 죽이지 않게.
  - plist(`com.valuehire.search-runner.plist`) 의 Desktop 경로 4곳(ProgramArguments/WorkingDirectory/VALUEHIRE_REPO_DIR/로그) 을 실제 checkout 경로로 교체(또는 설치 스크립트가 실경로 주입).
  - **계약(테스트 대상 함수/스크립트 동작):**
    - 입력: REPO_DIR 미지정/무효 경로/유효 경로 3케이스.
    - 출력: (a)유효 → 그 경로에서 사이클 진입, (b)무효 → 로그 + 비-크래시(프로세스가 KeepAlive 재시작을 부르는 즉시-exit 하지 않음), (c)plist lint → "Desktop" 문자열 0건 + ProgramArguments 가 존재하는 스크립트 지시.
- **PART 2 (dry_run→라이브 — 이 조각 비범위, PC-D2b 선행):** 부트 시 라이브 경로 선택(페이크 실행자 호출횟수 단언). **PC-D2b(상시 Harvest 드라이버) 미착수라 지금 불가** → 이 조각에서 하지 말고 verdict 잔여리스크에 명시. depends_on: PC-D2b, PC-D2a2, PC-D5(완료).

### 인수 기준 (기계 검사 — verify.sh exit 0)
- 새 pytest(예: `tests/test_daemon_crashloop.py`):
  1. REPO_DIR 해석 순수함수/스크립트: 무효 경로에 **즉시 crash-exit 하지 않음**(fail-soft 관측 — 종료코드/로그).
  2. `valuehire-search-loop.sh` 소스에 `Desktop/Valuehire_v5` 리터럴 **0건**(회귀 봉인).
  3. plist lint: `com.valuehire.search-runner.plist` 에 `Desktop` **0건** + ProgramArguments 경로의 스크립트가 실존.
  4. REPO_DIR 자기도출이 실제 repo 를 가리킴(스크립트 위치 기반).
- 셸 로직은 파이썬에서 subprocess 로 구동해 관측하거나, 경로해석을 파이썬 순수함수로 추출해 단언(테스트 가능하게).

### 적용 게이트
harness 0~6 + **gate4b: G(자기 mutation) → V1(Codex) + V2(리셋 Claude) 병렬** → `docs/engineering/pc-k6-daemon-crashloop.verdict.json` 3자 증거.

### 적대검증 정조준
- fail-soft 가 진짜 무한재시작을 막나, 아니면 여전히 즉시-exit→KeepAlive 재시작인가(정조준).
- 경로 자기도출이 심링크/공백경로/다른 checkout 에서도 맞나.
- plist 교체가 실경로를 가리키나(오타=여전히 죽음).
- SOT2: 데몬이 봇처럼 재시작 폭주하지 않는지(백오프 존재).
- 고아: 새 경로해석/스크립트가 실제 데몬 부팅 경로에 배선됐나(plist→sh→python).

### 비범위
- PART 2(dry_run→라이브·PC-D2b 선행).
- portal-browsers 데몬의 브라우저-죽음 근본(별 조각일 수 있음 — 스코프 시 사장님 확인).
- 실제 launchd load/설치(사장님 맥에서 1회 수동 — 데몬 자동 load 금지, 테스트만).

### ⛔ 안전 (SOT)
- **데몬을 자동으로 load/start 하지 마라** — 수리·테스트만. 로드는 사장님 수동(무한재시작 재발 방지·양보 규칙).
- **로그인된 크롬(9222) kill 금지.** portal-browsers 는 이미 unload 상태 — 다시 켜지 마라(사장님 승인 없이).
- launchd 데몬은 일부 **수동 verdict** 필요(실 부팅은 사장님 맥에서 확인). 순수 결정로직만 기계검증, 실운영은 수동으로 남긴다("완료" 아님 명시).

### 환경 함정(실측)
- 검사 인터프리터 `/Users/kangsangmo/Valuehire_v5/.venv/bin/python`(websocket 보유). worktree: `PYTHONSAFEPATH=1 PYTHONPATH=<worktree> .../.venv/bin/python -m pytest <worktree>/tests/ -q`. baseline 현재 927 passed.
- CI 는 websocket 미설치 — 러너 import 는 raw_cdp 지연import로 통과(신규 최상단 websocket import 금지).
- Codex: placeholder 자주 반환(transcript jsonl `tasks/<agentId>.output` tool_result 본문 확보) · 워크트리 직접쓰기 차단(뮤테이션은 `/private/tmp` 복사본에서) · 전체 pytest 는 HOME/`VALUEHIRE_PORTAL_PROFILE_ROOT` 를 writable 임시경로로 분리.

### ⭐ 마지막에 — 전체 프로세스 상세 브리핑(recap) 필수
끝낼 때 사장님께 쉬운 한국어로: ①무엇을 고쳤나(파일·PR번호) ②왜(크래시-루프가 뭐였고 왜 깜빡였나) ③**어떻게 검증했나 — G/V1(Codex)/V2(리셋 Claude)/T 각 검증자가 실제로 잡은 결함과 수정 구체적으로** ④증거 숫자 그대로 ⑤남은 것(PART 2 라이브는 PC-D2b 후) + 수동확인 필요분(launchd 실부팅) ⑥재개 명령(데몬 load 방법·되돌리기). 과장·"아마도" 금지.
