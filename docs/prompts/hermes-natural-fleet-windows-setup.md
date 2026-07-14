# Goal Prompt: Hermes 자연어 Discord -> Windows Search Machine

아래 작업을 `C:\Users\DELL\Desktop\Valuehire_v5`에서 끝까지 수행하라. 설명만 하지 말고
코드 확인, 필요한 최소 수정, 테스트, 로컬 서비스 설치 절차와 검증 결과까지 완료하라.
운영 Discord bot 또는 외부 포털에 쓰기 전에 owner 승인을 받아라.

## 목표

Discord의 Hermes DM에서 복잡한 `/fleet-run skill:... url:... machine:...` 입력 없이 다음 문장이
작동해야 한다.

```text
aisearch <ClickUp URL> win
<ClickUp URL> 사람인 잡코리아 win
<ClickUp URL> LinkedIn 사람인 잡코리아 win
<ClickUp URL>
```

- `win`, `windows`, `윈도우`는 `winpc`로 정규화한다.
- ClickUp URL은 포지션 URL이다. 사람인·잡코리아는 검색 URL을 요구하지 않는다.
- JD에서 국문·영문·띄어쓰기·약어 변형을 생성해 사람인 OR/AND/NOT과 잡코리아 칩에 직접 입력한다.
- 명시 머신이 없으면 사람인/잡코리아/ClickUp 작업은 `winpc`가 기본이다.
- LinkedIn 검색 URL만 있는 작업은 기존 계정 바인딩에 따라 `macmini`가 기본이다.
- `macmini`, `macbook`, `winpc`를 명시하면 그 머신을 우선한다.
- URL 없는 `win` 한 단어는 실행하지 않는다. 대상 없는 작업을 추측하지 말고 짧은 사용 예를 답한다.

## 재사용할 구현

- 자연어 rewrite: `ops/hermes-plugin/valuehire_fleet/__init__.py`의 `pre_gateway_dispatch`
- 입력 파싱: `tools/multi_position_sourcing/hermes_fleet_bridge.py`
- 큐 적재/머신 선택: `tools/multi_position_sourcing/fleet_dispatch.py`
- 실행 프롬프트: `tools/multi_position_sourcing/fleet_worker.py`
- 큐/계정 잠금: `tools/multi_position_sourcing/job_queue.py`
- 로그인 정책 정본: `docs/search-access.md`

새 큐, 새 Discord bot, 새 browser runner를 만들지 말고 위 경로를 확장하라.

## 로그인 및 브라우저 계약

1. Windows의 사람인/잡코리아 작업은 반드시 Windows 전용 headed Chrome 프로필에서 실행한다.
2. Windows 작업 스케줄러는 로그인한 사용자의 interactive session에서 실행한다. Session 0 서비스로
   브라우저를 띄우지 않는다.
3. 각 머신의 포털 아이디/비밀번호는 그 머신의 `.env.local`, OS credential store 또는 승인된
   secret store에서만 읽는다. 비밀값, 쿠키, 토큰, storage state를 로그/Discord/git에 출력하지 않는다.
4. 기존 로그인 세션을 먼저 재사용한다. 로그아웃 상태면 저장된 secret으로 정상 자동로그인을 시도한다.
5. captcha, 2FA, checkpoint, 본인확인, 이상접근이 나오면 우회하지 않는다. 즉시
   `PAUSED_FOR_HUMAN: <portal> <machine> <reason>`으로 중단하고 Discord에 job id와 해결할 머신을 알린다.
6. 사람이 해당 머신의 headed Chrome에서 인증을 끝낸 뒤 `/fleet-resume job:<id>`로 재개한다.
7. 로그인된 Chrome 프로필을 로그아웃, 삭제, 초기화하거나 다른 머신으로 복사하지 않는다.
8. 후보 제안, InMail, 이메일의 Send 클릭은 자동화하지 않는다.

## Windows 설치

다음을 PowerShell 기준으로 구현 또는 확인하라.

1. Python/Claude CLI/Chrome 설치와 `claude -p "hi"` 성공.
2. `VALUEHIRE_MACHINE=winpc`, Supabase URL/key, Discord 보고 채널을 사용자 환경 또는 작업
   스케줄러에 주입하되 값은 출력하지 않는다.
3. `python -m tools.multi_position_sourcing.fleet_worker`가 repo root를 cwd로 사용하도록 작업
   스케줄러 task를 만든다. `At log on`, 재시작, interactive user 조건을 사용한다.
4. worker heartbeat가 `winpc`로 보이고 stale이 아닌지 확인한다.
5. 사람인/잡코리아 headed Chrome 프로필 경로가 전용이고 재부팅 뒤에도 세션이 유지되는지 확인한다.

## Hermes 배포

1. Hermes 호스트에서 `ops/hermes-plugin/valuehire_fleet`를
   `~/.hermes/plugins/valuehire_fleet`에 symlink한다. 복사본을 만들지 않는다.
2. Hermes config의 `plugins.enabled`에 `valuehire_fleet`를 추가한다.
3. gateway를 한 번만 재시작하고 로그에서 플러그인 load 실패가 없는지 확인한다.
4. `pre_gateway_dispatch`는 Discord identity만 신뢰해야 한다. Telegram 등 타 플랫폼 ID를 Discord ID로
   간주하지 않는다.
5. 자연어 요청은 알려진 채용 URL이 있을 때만 `/fleet-run`으로 rewrite한다. 일반 URL 대화를
   가로채지 않는다.

## 인수 기준

아래를 전부 증명하라.

```powershell
python -m pytest tests/test_hermes_fleet_bridge.py tests/test_hermes_plugin_registration.py `
  tests/test_fleet_dispatch.py tests/test_fleet_worker.py -q
```

- `aisearch <clickup> win` -> job 1건, `skill=aisearch`, `machine=winpc`,
  `position_url=<clickup>`.
- `<linkedin search url>` -> `machine=macmini`.
- `<saramin/jobkorea url> win` -> `machine=winpc`.
- URL 없는 `win` -> enqueue 0.
- 미인가 Discord user -> enqueue 0.
- 같은 메시지 1회 -> Discord 응답 1개, job 1개.
- Windows worker가 job을 claim하고, 로그인 세션 정상 시 search를 시작한다.
- 강제 로그아웃 테스트에서는 secret 자동로그인이 실행된다. 단 실제 비밀번호는 화면/로그에 노출하지 않는다.
- 테스트용 2FA/checkpoint 신호에서는 `paused_for_human`이 되고 자동 조작이 더 진행되지 않는다.
- `/fleet-resume job:<id>` 후 동일 Windows worker에서 재개된다.
- 사람인·잡코리아 모두 최소 10페이지 또는 마지막 페이지까지 순회한다.
- 상세 프로필은 한 번에 하나씩 매회 새 3~7분 랜덤 지연으로 열며 Profile 2를 종료/초기화하지 않는다.
- 열어본 레쥬메 N건은 점수·하드제외 여부와 무관하게 스크린샷+본문+원본 URL 저장 영수증도 N건이어야 한다.
- 프리랜서 계열 또는 종료된 12개월 미만 재직 2회 이상 후보는 결과에 0건이어야 한다.

마지막 보고에는 변경 파일, 테스트 통과 수, Hermes/Windows 서비스 상태, heartbeat age, 실제 입력 예시
3개, 아직 owner 수동 승인이 필요한 항목만 간단히 적어라. 비밀값은 절대 적지 마라.
