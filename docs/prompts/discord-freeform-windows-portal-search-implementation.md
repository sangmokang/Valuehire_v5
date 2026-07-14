# Implementation Prompt: Discord 자유문장으로 사람인·잡코리아 Windows AI Search

이 프롬프트를 받은 코딩 에이전트는 `C:\Users\DELL\Desktop\Valuehire_v5`에서 아래 목표를
설명으로 끝내지 말고 코드 구현, 테스트, Windows/Hermes 배포, 라이브 smoke test까지 완료하라.
기존 변경사항을 되돌리지 말고 현재 main과 working tree를 먼저 읽어라.

## 0. 최종 사용자 경험

사장님이 Hermes Discord DM에 아래처럼 자유롭게 입력하면 검색이 시작되어야 한다.

```text
https://app.clickup.com/t/9018789656/86ew25j8k 사람인 잡코리아 찾아
이 포지션 후보 찾아줘 https://app.clickup.com/t/9018789656/86ew25j8k
방금 포지션 사람인부터 돌려
잡코리아도 같이
win
사람인 잡코리아, 프리랜서 빼고 좋은 후보 찾아
```

사용자는 `/fleet-run`, `skill:`, `url:`, `machine:`을 입력하지 않는다. Hermes가 문맥과 URL을
해석하여 내부적으로 다음 잡을 정확히 한 번 enqueue한다.

```text
skill=aisearch
machine=winpc
position_url=<ClickUp URL>
params.channels=[saramin,jobkorea]
params.execution=live
```

## 1. 현재 확인된 Windows 상태

- 머신명: `DESKTOP-6KKOBDD`, fleet machine id는 `winpc`.
- 저장소: `C:\Users\DELL\Desktop\Valuehire_v5`.
- Node와 Claude CLI가 설치되어 있고 `claude -p`는 정상 작동한다.
- `python.exe`는 현재 Windows Store alias뿐이므로 실제 Python 설치/경로 확인이 필요하다.
- Chrome: `C:\Program Files\Google\Chrome\Application\chrome.exe`.
- 영속 로그인 프로필: Chrome `Profile 2`.
- Profile 2에는 사람인·잡코리아 저장 로그인이 존재한다.
- 잡코리아 화면 우측 `밸류커넥트` 표시로 기업 로그인 상태를 육안 확인했다.
- Profile 2에는 Claude Chrome extension이 설치돼 있지만 현재 `claude mcp list`에는 Chrome 제어
  connector가 노출되지 않는다. connector 활성화 또는 별도 Playwright/CDP 실행 통로를 구현해야 한다.
- 현재 CDP `127.0.0.1:9222`는 열려 있지 않다.
- 작업 스케줄러 `ValuehirePortalKeepAlive`가 현재 5분 고정으로 등록돼 있다. 이 고정 주기는 최종
  요구와 맞지 않으므로 구현 과정에서 랜덤 3~7분 프로필 순회 스케줄로 교체해야 한다.
- keepalive 스크립트: `ops/windows/keep-portal-session.ps1`.
- Windows 로컬에는 Discord/Supabase `.env.local`이 확인되지 않았다. 비밀값은 중앙 Hermes 또는
  승인된 secret store에서 공급하고 출력/커밋하지 않는다.

## 2. 절대 불변식

1. Chrome Profile 2를 로그아웃, 삭제, 초기화, 쿠키 삭제, 다른 머신으로 복사하지 않는다.
2. 프로필을 동시에 두 browser process에서 열지 않는다. 머신/계정 lock을 먼저 획득한다.
3. 후보 상세는 한 번에 하나만 연다. 다음 후보 상세를 클릭하기 전 매번 180~420초(3~7분)의
   새 랜덤 지연을 뽑는다. 직전 지연값 재사용이나 고정 평균 주기 반복은 금지한다.
4. 검색/페이지 전환에도 3~8초 랜덤 지연을 둔다. 고정 주기 반복을 만들지 않는다.
5. 사람인·잡코리아 검색 URL을 사용자에게 요구하지 않는다. 검색 화면으로 직접 이동하고 UI에 입력한다.
6. 1페이지만 수집하고 성공 처리하지 않는다. 최소 10페이지 또는 마지막 페이지까지 순회한다.
7. selector 하나가 없다고 중단하지 않는다. fresh DOM inventory → SSOT selector → label/text → 안전한
   좌표 보조 순서로 최대 3개 경로를 시도하고 증거를 남긴다.
8. 기존 세션을 먼저 사용하고 로그아웃이면 Profile 2 저장 로그인/승인된 secret store로 자동로그인한다.
9. 일반 실패, timeout, selector drift, redirect는 사용자 승인 질문 없이 자동 복구한다.
10. captcha, 2FA, checkpoint, 봇 인증은 우회하지 않는다. 해당 채널만 `paused_for_human`으로 격리하고
    다른 채널은 계속 수행한다. 정상 작업 중에는 사용자에게 승인 질문을 던지지 않는다.
11. 후보 제안, InMail, 이메일, `Send`/`보내기` 버튼은 누르지 않는다.
12. 비밀번호, 쿠키, 토큰, storage state 원문, 후보 연락처 원문을 Discord/로그/git에 남기지 않는다.
13. 열어본 레쥬메는 점수, 하드 제외, 합격 여부와 무관하게 반드시 저장한다. 저장 실패 상태에서 다음
    후보로 넘어가거나 해당 페이지를 완료 처리하지 않는다.

## 3. 재사용할 기존 코드

- Hermes 자연어 hook: `ops/hermes-plugin/valuehire_fleet/__init__.py`
- 자연어/fleet 파서: `tools/multi_position_sourcing/hermes_fleet_bridge.py`
- 인가/큐 enqueue: `tools/multi_position_sourcing/fleet_dispatch.py`
- worker prompt: `tools/multi_position_sourcing/fleet_worker.py`
- 큐와 account lock: `tools/multi_position_sourcing/job_queue.py`
- JD→채널 필터: `tools/multi_position_sourcing/llm_keywords.py`
- 입력 계획: `tools/multi_position_sourcing/channel_search_render.py`
- 실제 portal worker: `tools/multi_position_sourcing/portal_worker.py`
- login/recovery: `portal_autologin.py`, `portal_login.py`, `portal_runtime.py`, `portal_session.py`
- 후보 hard exclude: `humansearch.py`, `scoring.py`
- SOT: `docs/sot/22-talent-search-filters.*`, `docs/sot/23-channel-dom-selectors.md`,
  `docs/search-access.md`.

새 큐, 새 Discord bot, 별도 후보 스코어러를 만들지 않는다. 현재 끊어진 생성→입력→순회→평가 연결을
위 코드에서 완성한다.

## 4. Discord 자유문장 라우팅

`pre_gateway_dispatch`에서 다음을 구현한다.

1. Discord identity만 신뢰하고 기존 allowlist/owner gate를 그대로 적용한다.
2. ClickUp URL + `찾아`, `서치`, `사람인`, `잡코리아`, `후보`, `win` 의도를 감지한다.
3. URL이 있는 메시지는 `(user_id, channel_id)`별 최근 position context로 저장한다.
4. context TTL은 30분이다. 같은 대화에서 `win`, `잡코리아도`, `방금 포지션`만 입력하면 최근 URL을 쓴다.
5. TTL이 끝났거나 최근 URL이 둘 이상으로 모호하면 enqueue하지 말고 URL 한 개만 요청한다.
6. 같은 Discord message id는 job 1개만 생성한다. idempotency key를 DB 또는 durable state에 저장한다.
7. 일반 URL 대화는 가로채지 않는다. ClickUp/채용 의도가 명확한 경우만 rewrite한다.
8. 자연어 기본 skill은 반드시 `aisearch`다. `humansearch`는 이미 만들어진 검색결과 순회 전용이므로
   사람인·잡코리아 검색식 생성 작업에 쓰지 않는다.

## 5. JD와 검색어 생성

ClickUp task를 API/MCP로 읽어 다음 5축을 구조화한다.

- 산업/도메인
- 직무명/유사직무
- 핵심 기술/도구
- 경력/시니어리티
- 제외 조건

각 핵심 개념마다 다음 변형을 만든다.

- 한국어 붙여쓰기/띄어쓰기: `머신러닝`, `머신 러닝`
- 영문 원형/대소문자/약어: `Machine Learning`, `machine learning`, `ML`
- 한영 직무 동의어: `AI 엔지니어`, `AI Engineer`, `ML Engineer`, `머신러닝 엔지니어`
- 기술 표기 변형: `PyTorch`, `Pytorch`, `파이토치`
- 유사 역할과 도메인 표현

긴 검색식 하나에 모두 넣지 않는다. 정밀/균형/확장 최소 3개 시나리오를 만든다. 각 시나리오는 결과 수를
측정하여 너무 적으면 AND를 완화하고, 너무 많으면 핵심 AND/경력 필터를 강화한다. 0건은 후보 없음으로
판정하지 말고 입력값, 로그인, selector, 결과 count DOM을 재검증한다.

## 6. 사람인 직접 제어

1. 기업회원 인재풀 URL로 이동한다.
2. 로그인 marker와 `input.search_input`, `#career_min`, `#career_max`를 확인한다.
3. OR 칸에는 국문/영문/띄어쓰기/약어 직무 변형을 하나씩 입력한다.
4. AND 칸에는 핵심 기술 1~2개만 입력한다.
5. NOT 칸에는 다음을 항상 입력한다.

```text
프리랜서
freelancer
freelance
개인사업자
독립계약자
외주
신입
인턴
```

6. JD 경력 범위를 native career min/max에 입력한다.
7. 검색 후 결과 수를 확인하고 정밀/균형/확장 시나리오를 순서대로 실행한다.
8. 페이지 1~10 또는 마지막 페이지까지 이동한다. 매 페이지의 unique candidate id/profile URL을 기록한다.
9. 상세를 연 즉시 스크린샷과 레쥬메 본문을 저장하고 저장 영수증을 확인한 뒤에만 3~7분 랜덤 대기를
   거쳐 다음 상세를 클릭한다.

## 7. 잡코리아 직접 제어

1. 기업/서치펌 인재검색 화면으로 이동한다. 일반 채용공고 홈으로 redirect되면 로그인/회원 유형과 실제
   인재검색 진입 링크를 DOM에서 다시 찾아 이동한다.
2. `#txtKeyword` 또는 fresh DOM에서 확인한 keyword input에 키워드를 하나씩 넣고 Enter로 칩을 만든다.
3. 한글 입력이 React 상태에 반영되지 않으면 clipboard paste + Enter 또는 native value setter + input/change
   이벤트를 사용하고, 화면에 생성된 칩 텍스트를 다시 읽어 검증한다.
4. `#txtCareerStart`, `#txtCareerEnd`와 검색 버튼을 사용해 JD 경력을 설정한다.
5. NOT UI가 없으면 수집 직후와 상세 프로필 평가 직전에 하드 제외를 두 번 적용한다.
6. 정밀/균형/확장 시나리오별로 10페이지 또는 마지막 페이지까지 순회한다.
7. 상세를 연 모든 후보는 하드 제외 여부와 무관하게 먼저 원본 URL, 스크린샷, 본문 텍스트를 저장하고
   저장 영수증을 확인한다. 그 다음 하드 제외/채점을 수행한다.

## 8. 하드 제외와 평가

점수 계산 전에 `hard_exclude_reason`을 적용한다.

- 아래 marker가 headline, 경력, 회사명, 직책, OCR/본문 중 하나에 실제 독립 의미로 존재하면 제외:
  `프리랜서`, `freelancer`, `freelance`, `개인사업자`, `독립계약자`, `contract worker`, `외주`.
- 종료된 재직 중 12개월 미만 이직이 2회 이상이면 `frequent_job_change`로 제외한다.
- 현재 재직은 단기이직 횟수에서 제외한다.
- `외주 관리`, `외주사 협업`처럼 본인이 프리랜서라는 뜻이 아닌 문맥은 원문 주변 문장으로 재검증한다.
- 제외 후보는 점수, ClickUp 등록, Discord 후보 목록에 절대 포함하지 않는다.

통과 후보만 `profile_url`, `score`, `why_fit`, `profile_summary`, `channel`, `evidence`를 만든다.

### 열람 레쥬메 무조건 저장 계약

열어본 모든 상세 프로필에 대해 아래를 하나의 원자적 저장 단위로 남긴다.

- `profile_url` 원본(손입력/재구성 금지)
- channel, position_id, scenario, page, candidate_index
- 상세 화면 전체 스크린샷 경로와 SHA-256
- 추출한 레쥬메 본문 전문 또는 OCR 본문
- 수집 시각, 저장 상태, hard_exclude_reason
- 로컬 DB row id 및 Supabase/archive id(사용 가능할 때)

저장 순서는 `상세 열기 → URL 검증 → 스크린샷 → 텍스트 추출 → 로컬 DB commit → 원격 sync 시도 →
저장 영수증 기록 → hard exclude/채점 → 랜덤 3~7분 대기 → 다음 프로필`로 고정한다. 원격 sync가 일시
실패해도 로컬 저장을 먼저 확정하고 durable outbox에 넣어 재시도한다. 로컬 저장 자체가 실패하면 현재
candidate checkpoint에서 멈추고 자동 복구하며 다음 후보를 열지 않는다.

## 9. Windows 영속 실행

1. 실제 Python 3.12를 설치/탐지하고 repo venv를 만든다. PATH alias 문제를 제거한다.
2. `portal_worker.py`의 `fcntl` 전용 lock을 Windows `msvcrt` 또는 cross-platform file lock으로 교체하고
   Linux/macOS 회귀 테스트를 유지한다.
3. Profile 2를 직접 조작할 안전한 통로를 하나만 선택한다.
   - 우선: Claude in Chrome connector를 Claude Code/Cowork에 활성화하고 `Act without asking`으로 설정.
   - 대안: Profile 2 세션을 손상시키지 않는 전용 persistent Playwright/CDP 경로.
4. Chrome 136+의 기본 user-data-dir remote debugging 제한을 우회 꼼수로 깨지 않는다. 새 전용 프로필이
   필요하면 저장 자격증명으로 정상 로그인해 별도 영속 프로필을 만든 뒤 그 프로필만 자동화한다.
5. `ValuehirePortalKeepAlive`의 고정 5분 스케줄을 제거한다. 1분짜리 가벼운 scheduler tick 또는 상시
   interactive worker를 쓰되, 실제 프로필 클릭은 durable `next_profile_at`에 저장한 180~420초 랜덤
   시각에만 수행한다. 재부팅 후에도 남은 대기시간/체크포인트를 복구한다.
6. 로그인 유지 증거는 단순 Chrome process 존재나 탭 새로고침이 아니라, 예정된 시각에 실제 후보
   상세 프로필 1개를 열고 저장한 뒤 로그인 marker가 유지된 것으로 판정한다.
7. fleet worker task를 interactive session에 등록하고 `VALUEHIRE_MACHINE=winpc`로 실행한다.
8. heartbeat와 worker stale 경보를 검증한다.

## 10. 실패 복구 정책

다음 이유 하나로 전체 작업을 포기하지 않는다.

- selector missing: fresh DOM inventory 후 최대 3개 안전 경로 재시도.
- timeout/network: 1/2/5분 backoff 후 최대 3회.
- 일반 홈 redirect: 올바른 기업 인재검색 링크 재탐색.
- login lost: Profile 2 저장 로그인/secret store 자동로그인 후 원래 검색 시나리오부터 재개.
- 페이지 중간 오류: 체크포인트의 `(channel, scenario, page, candidate index)`부터 재개.
- 한 채널 실패: 다른 채널은 계속 진행.

실제 자격증명이 전혀 없거나 보안 챌린지가 발생한 경우만 해당 채널을 paused로 둔다. 정상적인 selector drift나
1페이지 수집 완료를 `done`으로 위장하지 않는다.

## 11. 필수 테스트

최소 다음 자동 테스트를 추가하고 실행한다.

- 자유문장 ClickUp URL → `aisearch/winpc/saramin+jobkorea` 1회 enqueue.
- 최근 URL context 후 `win` 단독 → 같은 URL로 1회 enqueue.
- context TTL 만료/모호함 → enqueue 0.
- 같은 message id 중복 → job 1개.
- 사람인 field plan이 실제 OR/AND/NOT locator 호출로 이어짐.
- 잡코리아 chip plan이 실제 입력+Enter+chip readback으로 이어짐.
- 10페이지 또는 last-page까지 순회하며 페이지 1만으로 done 불가.
- 페이지 6 실패 후 checkpoint resume가 페이지 6부터 재개.
- 프로필 클릭 간격이 각 회차 180~420초이고 최소 20회 표본에서 고정 주기가 아님.
- 열어본 프로필 N건이면 로컬 저장 영수증도 정확히 N건이며 하드 제외 후보도 저장돼 있음.
- 저장 실패 후보 뒤의 다음 프로필 클릭은 0건이고 같은 checkpoint에서 재시도.
- 한영/띄어쓰기/약어 변형 중복 제거.
- 프리랜서 marker와 단기이직 2회 후보 결과 0건.
- Profile 2 종료/삭제/쿠키 정리 호출이 정적 grep 0건.
- captcha/2FA는 해당 채널 paused, 다른 채널 continued.

```powershell
python -m pytest tests/test_hermes_fleet_bridge.py tests/test_hermes_plugin_registration.py `
  tests/test_fleet_dispatch.py tests/test_fleet_worker.py tests/test_channel_search_filters.py `
  tests/test_channel_search_render.py tests/test_multi_position_sourcing.py -q
```

## 12. 라이브 인수 테스트

테스트 포지션:

```text
https://app.clickup.com/t/9018789656/86ew25j8k
```

Discord에 아래 문장을 입력해 검증한다.

```text
이 포지션 사람인 잡코리아에서 좋은 후보 찾아줘 https://app.clickup.com/t/9018789656/86ew25j8k win
```

완료 조건:

- Discord message 1개 → fleet job 1개.
- winpc가 claim하고 heartbeat가 stale이 아님.
- 사람인·잡코리아 로그인 marker 확인.
- 각 채널 정밀/균형/확장 검색식 입력 증거.
- 각 채널 10페이지 또는 마지막 페이지 순회 증거.
- 프로필별 3~7분 랜덤 클릭 간격과 `next_profile_at` 체크포인트 증거.
- 열어본 레쥬메 수와 저장 영수증 수가 동일하고 저장 누락이 0건.
- 프리랜서/잦은 단기이직 하드 제외 통계.
- 통과 후보의 유효 profile URL과 필수 4필드.
- 외부 발송 0건.
- Chrome Profile 2 로그인 유지.

최종 보고는 변경 파일, 테스트 통과 수, 작업 스케줄러 상태, heartbeat age, 채널별 검색 시나리오/페이지
수/원시 후보 수/하드 제외 수/통과 수, 재개 체크포인트만 한국어로 간단히 적는다. 비밀값은 적지 않는다.
