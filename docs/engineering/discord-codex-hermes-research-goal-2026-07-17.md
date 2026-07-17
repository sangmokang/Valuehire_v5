# Discord → Codex 전환 조사·구현 계약 (2026-07-17)

## 0. 산출물 계약

- 모드: `noncode`
- 위험등급: `L1`(읽기 전용 조사). 단, 이 문서의 권고를 운영에 반영하는 작업은 Discord·로컬 셸·외부 서비스 쓰기를 바꾸므로 별도 `L3` 작업이다.
- 요청: 현재 Discord 셸/스킬 제어가 Hermes를 통해 구축됐는지 확인하고, Hermes를 우회해 Codex가 `ai-search`, `humansearch`, `url`, `jdbuilder`를 실행할 수 있는지 조사한다.
- 완료 조건:
  1. 현재 실행 중인 Discord 수신기와 실제 플러그인 경로를 확인한다.
  2. 저장소에 있는 Codex 실행 배선과 운영 배포본의 차이를 확인한다.
  3. 네 스킬별 Codex 이식 가능성, 차단 요소, 위험도를 구분한다.
  4. Hermes 유지/부분 제거/완전 제거 대안을 반증과 함께 비교한다.
  5. 외부 쓰기 없이 실행 가능한 검증만 수행하고, 운영 전환은 별도 승인 대상으로 남긴다.
- 비범위: Hermes 중지, Discord 봇 재시작, 플러그인 링크 변경, Codex 설정 변경, 실제 후보 검색, 플랫폼 등록·발송, 메일 발송, PR/push/merge.

## 1. 결론

**가능하다. 다만 “Codex를 Discord에 바로 노출”하는 구조가 아니라, Discord는 인증·중복 방지·작업 접수만 하는 얇은 수신기로 두고 기존 큐와 계정 잠금 뒤에서 Codex가 네이티브 스킬을 실행하게 해야 한다.**

현재 장애의 핵심은 Hermes라는 이름 하나가 아니라 다음 세 층이 서로 어긋난 것이다.

1. 운영 Discord는 Hermes Gateway가 받고 있다.
2. Hermes가 로드한 `valuehire` 플러그인은 v4를, `valuehire_fleet` 플러그인은 현재 저장소가 아닌 47개 커밋 전 별도 checkout을 가리킨다.
3. 최신 저장소에는 Codex 실행 배선이 이미 있지만 운영 연결본에는 반영되지 않았고, 현재 Codex 설정도 비대화형 실행 전에 파싱 오류가 난다.

따라서 권고는 **Hermes의 LLM·스킬 레지스트리·범용 터미널 계층을 제거하되, 기존 큐·오너 확인·계정 잠금·재개·상태 통지는 보존**하는 것이다. 즉 “Hermes를 Codex로 이름만 바꾸기”가 아니라 “제어면은 얇게, 실행은 Codex 네이티브로” 재구성한다.

## 2. 현재 운영 상태의 직접 증거

### 2.1 Discord는 현재 Hermes가 수신한다

- 2026-07-17 런타임 스냅샷에서 `ai.hermes.gateway` 한 개가 실행 중이었다.
- `fleet_worker`, `fleet_watchdog`, `discord_command_listener` 프로세스는 없었다.
- 큐의 읽기 전용 조회에서는 `queued=12`, `running=0`이었다. 세 머신 heartbeat도 각각 약 148시간, 66시간, 8시간 전으로 stale 상태였다. 즉 enqueue 뒤 실제 소비·완료를 보장하는 운영 worker가 현재 없다.
- `~/.hermes/config.yaml:617-620`은 `valuehire`, `valuehire_fleet` 두 플러그인을 모두 활성화한다.
- `~/.hermes/config.yaml:253`의 `busy_input_mode=interrupt` 때문에 작업 중 새 Discord 입력이 기존 Hermes 작업을 중단할 수 있다.
- 실제 플러그인 링크:
  - `~/.hermes/plugins/valuehire` → `/Volumes/SSD/valuehire_v4/tools/hermes-agent/valuehire`
  - `~/.hermes/plugins/valuehire_fleet` → `/Users/kangsangmo/Valuehire_v5-main/ops/hermes-plugin/valuehire_fleet`

판정: **현재 Discord → 셸/스킬 진입점은 Hermes가 맞다. Codex 직접 수신기는 운영 중이 아니다.**

### 2.2 운영 연결본은 최신 저장소가 아니다

- 현재 저장소 HEAD: `53ac4e5`
- Hermes가 참조하는 별도 checkout HEAD: `54a5da6`
- `54a5da6..53ac4e5`: 47 commits.
- Discord/fleet 관련 범위만 비교해도 19개 파일, `+2609/-151` 차이가 있다.
- 이 구간에는 다음 변경이 포함된다.
  - `102090a`: Discord DM의 Codex 선택
  - `a44a39a`: fleet 작업의 Claude/Codex 선택
  - 이후 worker 복구, 로그인 머신 라우팅, 재개·스케줄링 변경

판정: **“Codex 배선이 코드에 있다”와 “지금 Discord에서 쓸 수 있다”는 다른 주장이다. 전자는 참이고 후자는 거짓이다.**

### 2.3 Hermes가 네이티브 스킬 발견을 방해한 실제 징후가 있다

최근 gateway 로그에서 확인한 사례:

- `/jdbuilder`를 알 수 없는 slash command로 거부했다: `~/.hermes/logs/gateway.error.log:184652`.
- Hermes 기본 프로필에서 `humansearch`를 찾지 못했다: 같은 파일 `184568`, `184666`.
- v4 `vh_skill_run`이 Claude를 900초 기다린 뒤 실패했고 Codex 폴백은 별도 환경 게이트가 없어 보류됐다: `184533`, `184565`.
- v4에 없거나 옮겨진 파일 경로를 읽다가 실패했다: `184534-184537`.
- Hermes의 모델 호출 지연이 212초를 넘고 Discord heartbeat가 멈춰 재연결됐다: `184570-184575`.
- gateway 일반 로그는 수신한 Discord 메시지 본문을 평문으로 기록한다.

해석: 검색 전용 fleet 경로에서는 Hermes가 실제 작업을 직접 하지 않고 큐에 넣는 역할이지만, 일반 DM과 slash-command 경로에서는 Hermes의 별도 스킬 목록·v4 작업 디렉터리·타임아웃·폴백 정책이 먼저 개입한다. 사용자가 느낀 “Claude/Codex 스킬을 방해한다”는 관찰에는 직접 근거가 있다.

## 3. 현재 저장소에 이미 있는 Codex 기반

- `tools/multi_position_sourcing/job_queue.py:23-25`는 검색 스킬 `humansearch`, `aisearch`, `url`과 실행 엔진 `claude`, `codex`를 허용한다.
- `tools/multi_position_sourcing/hermes_fleet_bridge.py:317-326`은 메시지의 독립된 `codex` 토큰을 `agent:codex`로 변환한다.
- `tools/multi_position_sourcing/fleet_worker.py:319-333, 641-658`은 `agent=codex` 작업을 `codex exec`로 실행하고 Codex 타임아웃으로 구분한다.
- `scripts/discord_command_listener.py:136-169`은 오너 DM의 `codex:` 접두어를 Codex CLI로 전달한다.

하지만 이 기반은 그대로 운영 투입할 수 없다.

- 직접 DM 수신기는 영속 큐, 작업 취소, heartbeat, 머신 배정, 계정 잠금이 없다.
- 직접 DM 수신기는 오너의 모든 DM을 명령으로 취급하고 완료 뒤에만 처리 id를 저장하는 at-least-once 방식이라, 외부 쓰기 도중 죽으면 같은 작업을 재실행할 수 있다.
- 직접 DM 수신기와 Hermes를 동시에 켜면 같은 메시지를 두 번 처리할 수 있다.
- fleet allowlist에는 `jdbuilder`가 없다.
- Codex CLI는 두 버전이 공존한다. 현재 일반 쉘의 우선 버전은 `0.144.4`로
  `model_reasoning_effort="ultra"`를 파싱한다. 반면 예정된 fleet worker plist의 PATH는
  `0.137.0`을 먼저 선택하고 같은 설정에서 실패한다. 따라서 차단 요소는
  "현재 모든 Codex 실행 실패"가 아니라 **실행 환경별 바이너리 선택 드리프트**다.
- 비용과 외부 쓰기를 수반할 수 있어 실제 모델 실행은 이번 L1 조사에서 하지 않았다.

## 4. 스킬별 이식 가능성

| 스킬 | 현재 Codex 상태 | 판정 | 운영 전 필수 보완 |
|---|---|---|---|
| `$ai-search` | `~/.codex/skills/ai-search/SKILL.md` 존재. 정본 검사 통과. fleet 내부 이름은 `aisearch`. | **가장 먼저 이전 가능** | `aisearch → $ai-search` 명시 매핑, 현재 저장소에서 실행, 브라우저/CDP·ClickUp 1건 읽기 전용 검증 |
| `$humansearch` | `~/.codex/skills/humansearch/SKILL.md` 존재. repo의 raw CDP runner와 채점·사전검문을 사용한다. Hermes 기본 프로필에는 없음. ClickUp 등록은 현재 MCP 연결에 기대는 부분이 있다. | **조건부 이전 가능** | 검색 URL 1건 순회, 점수·중복·등록 전 dry-run, Codex용 ClickUp 등록 연결, 사람 개입/캡차 재개 확인 |
| `$url` | `~/.codex/skills/url/SKILL.md` 존재. 결과 읽기·URL 수확은 raw CDP가 가능하지만 실제 검색어 입력·필터 실행은 `claude-in-chrome`에 묶여 있다. 동기화 모의실행도 `partial` 판정. | **현재 end-to-end 불가** | Claude 전용 입력을 Codex 중립 raw CDP 절차로 교체, 로그인 정책 정합, RPS 한 포지션 live proof, 공유 계정 잠금 유지 |
| `$jdbuilder` | 현재 `~/.codex/skills/jdbuilder`는 없다. v4에는 4채널 통합 스킬이 있고, 현재 Codex에는 LinkedIn 전용 `linkedin-rps-jd-set-builder`만 있다. fleet allowlist에도 없으며 4채널 정본·runner 일부도 v4에만 있다. | **현재 불가** | v5 정본·runner 이식, 4채널/LinkedIn-only 이름 충돌 해소, 별도 owner-only 작업 종류, 채널별 승인·감사 기록, Gmail 실제 발송은 건별 승인 |

### jdbuilder가 별도 취급돼야 하는 이유

v4 `$jdbuilder`는 사람인·잡코리아 등록, LinkedIn 템플릿 저장, Gmail 실제 발송을 한 진입점에 묶는다. 반면 검색 fleet의 정본은 검색 세 스킬만 허용하며 자동 발송을 막는다. `jdbuilder`를 검색 allowlist에 한 줄 추가하면 안전 계약을 깨므로, 다음처럼 분리해야 한다.

- 검색 lane: `ai-search`, `humansearch`, `url`; 읽기·후보 정리 중심, 기존 fleet 안전장치 재사용.
- 등록 lane: `jdbuilder`; owner-only, 채널별 허용 동작 명시, Gmail은 수신자·본문 preview 후 별도 승인, 후보자 발송 Send는 계속 사람 손.

## 5. 대안 비교

| 대안 | 장점 | 반례/위험 | 판정 |
|---|---|---|---|
| Hermes 전체 유지 | 변경량이 가장 작고 현재 Discord 연결을 재사용 | v4+stale v5 이중 플러그인, 별도 LLM/스킬 목록, 오래 걸리는 모델 호출이 Discord heartbeat와 결합 | 비권고 |
| Hermes transport만 임시 유지하고 모든 허용 작업을 Codex 큐로 직행 | 가장 빠른 과도기. 기존 slash command와 큐를 재사용 | Hermes 버전·플러그인 배포 문제는 남고, 일반 DM 경로가 다시 개입할 수 있음 | 단기 교량으로 허용 |
| 얇은 Discord 수신기 + 기존 큐/잠금 + Codex worker | Codex 네이티브 스킬 사용, 단일 정본, 인증·중복·복구 안전장치 보존 | 새 수신기의 운영·감시를 구축해야 함 | **권고 최종안** |
| Discord DM을 곧바로 `codex exec`에 전달 | 구현이 단순 | 계정 탈취가 컴퓨터 제어로 확대, 임의 프롬프트·중복 실행·재시작 복구·계정 동시 사용 문제 | 금지 |

## 6. OpenAI 공식 기능과의 정합

- [Codex SDK](https://developers.openai.com/codex/sdk)는 Codex를 내부 도구·workflow·자체 애플리케이션에 넣는 용도라고 명시한다.
- [비대화형 실행](https://developers.openai.com/codex/noninteractive)은 `codex exec`를 스크립트·파이프라인·예약 작업에 쓰고 권한을 명시적으로 제한하는 방식을 제공한다.
- [Codex app-server](https://developers.openai.com/codex/app-server)는 인증, 대화 이력, 승인, 진행 이벤트가 필요한 깊은 통합용이다. 자동 작업에는 SDK를 쓰라고 권고하며, WebSocket transport는 experimental/unsupported이므로 초기 Discord 연결에는 SDK 또는 로컬 `codex exec`가 더 적합하다.
- 공식 제3자 채널 문서는 GitHub·Slack·Linear를 열거하고 [Slack 연동](https://developers.openai.com/codex/integrations/slack)을 제공하지만 Discord 연동은 제공 목록에 없다. 따라서 Discord bot adapter는 자체 구현 대상이다.

공식 기능을 기준으로도 초기 선택은 `Discord adapter → durable queue → Codex SDK/exec`가 맞다. 대화 이력·중간 이벤트·승인 UI가 꼭 필요해질 때만 app-server를 검토한다.

## 7. 권고 구조

```text
Discord DM/slash
  → owner/guild/channel allowlist
  → 명령 parser (허용 스킬 4개만, 임의 shell 금지)
  → idempotency key + durable job queue
  → machine/account/Chrome-session lock
  → Codex worker
       ├─ aisearch   → $ai-search
       ├─ humansearch → $humansearch
       ├─ url         → $url
       └─ jdbuilder   → owner-only L3 lane
  → progress/final/error를 Discord로 반환
```

보존해야 할 기존 자산:

- Discord sender 확인과 메시지 id 기반 중복 방지
- PostgreSQL 작업 큐와 상태 전이
- 머신 배정, 계정 잠금, Chrome 사용 양보, 캡차 일시정지·재개
- 시작/진행/완료/실패 통지
- 외부 발송·등록 전 승인 게이트

제거해야 할 계층:

- Hermes 일반 LLM이 먼저 요청을 해석하는 경로
- Hermes 고유 스킬 profile과 v4 cwd
- 범용 terminal command 노출
- Hermes 안의 Claude-first → Codex-fallback 중첩 실행
- Discord 메시지 본문 전체의 평문 로그

## 8. 안전한 이행 순서

1. 단일 배포 기준을 `/Volumes/SSD/valuehire_v5`로 고정하고 별도 stale checkout 참조를 없앤다.
2. Codex CLI 설정 오류를 고치고 각 머신의 설치·로그인·브라우저 접근을 읽기 전용 preflight로 확인한다.
3. Hermes를 끄기 전에 검색 3종만 `agent=codex`로 보내는 한 건씩의 side-by-side 시험을 한다.
4. `aisearch → $ai-search` 등 명시 매핑과 결과 계약을 고정한다.
5. 얇은 Discord adapter를 기존 큐 앞에 붙이고, Hermes와 동시 소비되지 않음을 검증한다.
6. `ai-search → humansearch → url` 순서로 읽기 전용/저장 전 dry-run을 통과시킨다.
7. `jdbuilder`는 별도 owner-only lane과 채널별 승인 절차를 만든 뒤, LinkedIn 저장-only부터 검증하고 Gmail 실제 발송은 마지막에 승인받는다.
8. 장애 복구·중복 메시지 replay·캡차 pause/resume를 검증한 뒤 Hermes Gateway를 내린다.

## 9. 반증 점검

- 반론: “Hermes는 단순 전달자라 방해가 아니다.”
  - 부분적으로 참이다. `/fleet-run` 검색 경로에서는 큐에 넣는 역할이 중심이다.
  - 그러나 일반 DM/slash 경로에서 Hermes profile, v4 plugin, Claude-first timeout, Codex fallback gate가 실제로 개입하고 실패했다. 따라서 전체 시스템 관점에서는 방해 원인이 맞다.
- 반론: “최신 repo에 Codex 코드가 있으니 바로 된다.”
  - 거짓이다. 운영 plugin checkout이 47 commits 뒤이고 worker가 실행 중이지 않으며 Codex 설정도 파싱 실패한다.
- 반론: “스킬 파일만 복사하면 네 개 모두 된다.”
  - 거짓이다. `url`은 Claude 전용 도구 표기가 남고 `jdbuilder`는 v5 Codex 정본이 없으며 외부 쓰기 위험이 다르다.
- 반론: “Hermes를 바로 제거하면 구조가 단순해진다.”
  - 단기에는 위험하다. 현재 큐·잠금·재개 기능을 보존하지 않고 직접 수신기로 갈 경우 중복 실행과 계정 충돌이 재발한다.

## 10. 검증 기록과 한계

이번 조사에서 수행한 읽기 전용 검증:

- 실행 프로세스·launchd·플러그인 symlink 확인
- 두 checkout HEAD 및 변경량 비교
- Hermes gateway 최근 로그의 라우팅·타임아웃·heartbeat 오류 확인
- Codex CLI 설치와 `codex exec --help` 확인, 설정 파싱 실패 재현
- Codex 스킬 설치 상태 확인
- `make codex-sync-dry` 성공: 49 candidates, 38 full, 11 partial
- `python3 tools/ai_search_sot_check.py --repo /Volumes/SSD/valuehire_v5` 성공
- Discord/fleet/스킬 관련 자동검사 377개 통과, 예상된 미완성 표시 3개 확인
- 저장소 전체 자동검사 1,614개와 하위검사 102개 통과, 예상된 미완성 표시 4개 확인

미검증:

- 실제 Discord → Codex 모델 1회 실행
- 실제 RPS/사람인/잡코리아 브라우저 조작
- 각 머신의 Codex 로그인·Chrome/CDP·환경변수 준비 상태
- jdbuilder의 채널별 live 등록/메일 발송

이 미검증 항목들은 비용 또는 외부 상태 변경을 수반할 수 있어 별도 L3 승인 후 확인해야 한다.

## 11. 최종 의사결정 요청

권고안을 승인하면 다음 작업은 별도 L3 계약으로 진행한다.

1. 운영 변경 없이 Codex 설정/preflight와 검색 3종 dry-run부터 봉인한다.
2. thin Discord adapter를 기존 큐에 연결한다.
3. 검색 3종을 먼저 전환한다.
4. `jdbuilder`는 별도 승인 lane으로 마지막에 연결한다.

이번 문서 작업에서는 코드, 운영 프로세스, 외부 데이터, Discord 설정을 변경하지 않았다.

## 12. 2026-07-17 구현 승인 계약

사장님이 `$st`로 "v4·v5의 Claude/Codex 스킬을 모두 쓰고, Discord에
자연어로 남겨도 실행"하도록 구축할 것을 승인했다. 이 승인은 코드·검사·PR
범위이며, 현재 실행 중인 Hermes 중지·Discord bot 재시작·플러그인 링크 교체는
이 계약의 생산 배포에 포함하지 않는다. 두 소비자가 같은 DM을 중복 실행하지 않도록
전환은 별도 승인 후 단 한 번만 한다.

### 12.1 구현 조각 A — v4·v5 스킬 발견

- 입력: v5 루트, 선택적 `VALUEHIRE_V4_REPO`, Codex 대상 폴더.
- 출력: `copied`, `skipped`, `collisions`, `classification`, `provenance`.
- 우선순위: v5 Codex-native → v5 Claude → v4 Codex-native → v4 Claude →
  v4 독립 도구 → 사용자 전역 스킬. 같은 이름은 먼저 온 정본이 이긴다.
- 완료 단언: 모의실행이 v4 `jdbuilder`를 포함하고, v5/v4 이름 충돌은 v5를
  선택하며, 대상 폴더를 쓰지 않는다.

### 12.2 구현 조각 B — owner 전용 일반 스킬 작업 계약

- 입력: 인증된 owner Discord message id, 원문, 실행 엔진, 머신.
- 작업 형태: `skill=agent`, `role=owner`, `params.request_text`, `params.agent`,
  `params.approval_id`, `params.prompt_sha256`, `params.approval_sha256`,
  `params.idempotency_key`, `params.execution_mode`.
- `prompt_sha256`는 Discord 원문, `approval_sha256`는 원문·실행기·실행모드·승인번호를
  길이 구분 형식으로 묶은 값이다. 둘 중 하나라도 다르면 실행하지 않는다.
- 상태: `queued → running → done|failed|paused_for_human`; 같은 message id는 한 번만
  등록한다.
- 완료 단언: member·빈 원문·과대 원문·변조된 hash는 거부하고, owner의 정상
  원문만 기존 영속 대기열과 중복 방지 키 뒤에 들어간다.

### 12.3 구현 조각 C — Discord 자연어 → Codex worker

- 입력: owner DM 자연어. 접두어 없으면 Codex, `claude:`는 Claude,
  `codex:`는 Codex로 실행한다.
- 접두어는 실행기 선택에만 쓰며 승인·저장·실행 원문에서는 제거하지 않는다. 따라서
  앞뒤 공백과 줄바꿈을 포함한 Discord 메시지 전체가 같은 해시로 끝까지 보존된다.
- 수신기는 모델을 직접 부르지 않고 조각 B의 대기열에만 등록한다.
- worker는 실행 직전 조각 A로 스킬을 동기화하고, v5를 기본 작업 루트로,
  v4를 추가 작업 루트로 제공한다. `danger-full-access`는 허용하지 않는다.
- owner 원문은 그 문장에 **명시된 대상·채널·횟수**에 대한 현재 승인으로만
  취급하고 범위를 늘리지 않는다.
- 완료 단언: 자연어 DM 1건이 Codex 작업 1건으로 접수되고, 실행 프롬프트가
  v4·v5 스킬 선택 계약과 원문 hash를 검증한 뒤 Codex로 전달된다.

### 12.4 검증 명령

```bash
python3 -m pytest -q tests/test_codex_skill_sync.py
python3 -m pytest -q tests/test_job_queue.py
python3 -m pytest -q tests/test_discord_command_listener.py tests/test_job_queue.py tests/test_fleet_worker.py
./verify.sh
```

최종 판정 전에 생성자 자체 공격 1회, 독립 검토 2회를 실행해 총 3회의
적대적 검증을 남긴다. 실제 Discord 봇 전환, Hermes 중지, 외부 등록·발송은
자동 검사 범위 밖이다.

## 13. 구현 진행 기록

- 조각 A(`#136`, PR `#137`) 병합: v5·v4·사용자 전역의 57개 스킬 이름을 결정적
  우선순위로 발견하며, 충돌 출처와 Codex 완전/부분 동작 분류를 남긴다.
- 조각 B(`#138`, PR `#139`) 병합: owner 일반 작업을 기존 검색 allowlist와 분리하고,
  Discord message id 중복 방지와 원문·실행기·실행모드 변조 검사를 Python·PostgreSQL
  양쪽에 추가했다.
- 조각 C(`#140`) 구현: 수신기의 직접 모델 호출을 제거하고 영속 큐 등록만 남겼다.
  worker는 실행 전 승인 봉투를 재검증하고 v4·v5 스킬을 동기화한다. Codex는
  `read-only|workspace-write`만 허용하며 v5 기본 루트와 v4 추가 루트를 사용한다.
- 이 기록은 코드·자동검사 범위다. 현재 Hermes 중지, Discord 수신기/worker 재시작,
  운영 데이터베이스 마이그레이션 적용, 실제 외부 등록·발송은 수행하지 않았다.

## 14. 최종 검증 기록

- 생성자 자체 반증: 승인 봉투 7종, 실행모드 비정상값 8종, 작성자·채널 위조 3종을
  거부했다. 이 과정에서 빈 실행모드가 기본값으로 보정되던 결함 1건을 찾아 수정했다.
- 독립 검토 1(Discord 수신기): 채널 번호 누락을 owner DM으로 보정하던 결함을 찾아
  수정했다. 수정 후 관련 검사 169개와 동일 반례 재검토를 통과했다.
- 독립 검토 2(worker): Codex 실행파일 위장, 빈 v4 스킬 소스, Claude 읽기 전용 모드
  미적용, 잠금 키 누락 보정 4건을 찾아 수정했다. 수정 후 관련 검사 192개와 동일 반례
  재검토를 통과했다.
- 실제 v5·v4 소스를 임시 대상에 동기화해 54개 복사, 57개 이름 표현, 부분동작 12개,
  누락 0개를 확인했다. 부분동작 스킬은 `claude:` 실행기를 명시할 수 있고, 필요한 도구가
  없으면 성공으로 꾸미지 않고 차단 사유를 보고한다.
- 최종 관련 검사 275개, 저장소 전체 검사 1,666개와 하위검사 102개가 통과했다.
  예상된 미완성 표시 4개 외의 실패는 없다.
