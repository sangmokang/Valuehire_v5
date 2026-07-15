# SOT 30 — /fleet-run 신뢰성 스펙 (2026-07-13)

> 상위 문서: `docs/sot/29-fleet-control.md`(함대 제어 SOT). 이 문서는 2026-07-13 라이브에서
> 발견된 /fleet-run 운영 결함 3건의 **문제 정의 → 해결 계약(스펙) → 인수 기준**을 명기한다.
> 여기 적힌 인수 기준을 전부 통과하기 전에는 "fleet-run 정상"이라고 말하지 않는다.

## 배경 — 2026-07-13 오전 관측 사실 (증거)

| 시각(KST) | 관측 | 출처 |
|---|---|---|
| 07:23·08:56·09:03·09:14 | `/fleet-run` 에 "Unknown command" 응답 4회 | `~/.hermes/logs/gateway.log` (맥북) |
| 09:16 | job 16 enqueued (machine=macmini, status=queued) | Discord JSON 응답 |
| 10:08·10:12 | job 18·19 enqueued (macmini, queued) | Discord JSON 응답 |
| 10:08+ | job 16 이 생성 1시간 경과에도 `started_at=null`, `status=queued` | Discord JSON 응답 |
| 점검 시점 | 맥북 레포 `.env.local` Supabase 열쇠 → REST 401 "Invalid API key" | 직접 재현 |
| 점검 시점 | 맥북에 fleet-worker launchd/프로세스 없음 (`launchctl list`, `pgrep`) | 직접 재현 |
| 점검 시점 | 맥북에 2026-06-17 기동 Hermes 게이트웨이(pid 5846) 상주, 플러그인은 구 v4 `valuehire` 만 enabled | `ps -o lstart`, `~/.hermes/config.yaml` |

## 문제 정의 (P1~P3)

### P1 — 유령 게이트웨이 이중 응답
같은 Discord 봇 토큰을 쓰는 게이트웨이가 **2개 이상** 동시에 살아 있다.
맥북의 2026-06-17 기동분(구 v4 플러그인만 탑재)은 `fleet-*` 명령을 모르므로 매번
"Unknown command"를 회신하고, fleet 플러그인이 실린 다른 게이트웨이가 실제 enqueue 를
수행한다. 사용자는 "모른다"와 "등록했다"를 동시에 받는다.

### P2 — queued 고착 (일꾼 미가동·미감지)
잡이 enqueue 는 되지만 대상 머신(macmini)의 fleet-worker 가 claim 하지 않아
`queued` 상태로 무기한 고착된다. 맥북에는 worker 자체가 미설치라 `machine:macbook`
잡도 동일하게 고착될 상태다. heartbeat/watchdog 층(`fleet_heartbeat.py`)은 존재하나
**worker 가 애초에 뜬 적 없는 머신**의 잡 고착을 사용자에게 알리는 경로가 검증되지 않았다.

### P3 — 머신별 자격증명 드리프트
맥북 레포 `.env.local` 의 `SUPABASE_SERVICE_ROLE_KEY` 가 무효(401)다. 열쇠 회전이
머신별 사본에 전파되지 않아, 같은 코드가 머신에 따라 되고/안 되고 갈린다(P2 의 은닉 원인이
되기도 한다 — worker 를 맥북에 깔아도 401 이면 조용히 실패).

## 해결 계약 (스펙)

### S1 — 게이트웨이 단일성 (P1 해소)
- **불변식**: 한 Discord 봇 토큰당 활성 게이트웨이는 정확히 1개다.
- 구 게이트웨이(맥북 pid 5846, `ai.hermes.gateway` launchd)는 **사장님 승인 후** 내리고,
  fleet 플러그인이 실린 게이트웨이 1개만 남긴다(라이브 프로덕션 봇이므로 무단 재시작 금지 —
  `ops/hermes-plugin/valuehire_fleet/__init__.py` 배포 주석과 동일 규율).
- 플러그인 배선은 심링크 `~/.hermes/plugins/valuehire_fleet` → 레포
  `ops/hermes-plugin/valuehire_fleet` + `config.yaml plugins.enabled` 등재로만 한다
  (사본 드리프트 금지).
- **잔여 위험 명기**: 단일화 전까지 "Unknown command" 응답은 계속 발생한다. 이는 코드 결함이
  아니라 배포 상태 결함이다.

### S2 — queued 고착 감지·보고 (P2 해소)
- **불변식**: `queued` 잡이 `FLEET_QUEUED_STALL_SECONDS`(기본 600초=10분)를 초과해
  claim 되지 않으면, watchdog 이 OPS_HEALTH 채널로 "머신 X 일꾼이 잡 N을 집어가지 않음"
  경보를 낸다(중복 억제 30분, heartbeat 경보와 동일 규율).
- 경보 판정은 순수함수로 구현하고(`stalled_queued_jobs(rows, now_epoch)`), 기계 테스트로
  경계(9분59초/10분1초·행 없음·paused 제외)를 봉인한다.
- worker 설치 상태 자체도 점검 대상: `fleet-status` 응답에 머신별 마지막 heartbeat 나이를
  포함해, 사용자가 "일꾼이 살아 있는지"를 명령 한 번으로 알 수 있게 한다.
- 맥북 worker 설치(`ops/launchd/com.valuehire.fleet-worker.plist`, `VALUEHIRE_MACHINE=macbook`)는
  S3 열쇠 정상화 **이후에만** 진행한다(무효 열쇠로 설치하면 조용한 실패 층이 하나 더 생긴다).

### S3 — 자격증명 단일 출처·기동 검증 (P3 해소)
- **불변식**: fleet 관련 장기 프로세스(worker·watchdog)는 **기동 시** Supabase 열쇠로
  인증 프로브(가벼운 GET 1회)를 수행하고, 401/403 이면 즉시 크래시-루프가 아니라
  "명시 오류 로그 + OPS_HEALTH 보고 후 재시도 백오프"로 들어간다(fail-loud).
  지금처럼 죽은 열쇠가 "조용한 무응답"으로 위장하는 것을 금지한다.
- 열쇠 회전 시 전 머신 `.env.local` 동기화는 수동이므로, 회전 절차 문서에
  "3머신 사본 갱신 + 각 머신에서 프로브 1회" 를 체크리스트로 명기한다.

## 인수 기준 (전부 만족해야 GREEN)

1. `/fleet-run <url>` 1회 발신에 Discord 응답이 **정확히 1개**(enqueued JSON)다.
   "Unknown command" 가 함께 오지 않는다. (S1)
2. macmini 대상 잡이 enqueue 후 `POLL_SECONDS×2`(=60초) 이내 `running` 으로 전이하거나,
   10분 초과 고착 시 OPS_HEALTH 경보가 1건 발생한다. (S2)
3. `fleet-status` 응답에 3머신 heartbeat 나이가 표시된다. (S2)
4. 맥북에서 `python3 -c "...JobQueueClient().recent(1)"` 이 401 없이 성공한다. (S3)
5. 무효 열쇠 주입 테스트에서 worker 가 조용히 죽지 않고 명시 오류를 남긴다(기계 테스트). (S3)
6. 신규 순수함수(`stalled_queued_jobs` 등)는 RED→GREEN 테스트와 2패스 적대검증
   (자기반증 + 독립 2차)을 통과한다. (CLAUDE.md 불변식 5)

## ultracode QA(2026-07-13) 확정 결함과 처치

4관점(정확성·보안·운영신뢰성·스펙정합) 병렬 리뷰 + 발견건별 적대 반증(에이전트 16개)으로
확정된 결함과 처치. 반증에서 기각된 5건(contextvar 신원 오염·is_dm 우회·SSRF·params
인젝션·게이트웨이 훅 경합)은 실결함 아님으로 판정.

| # | 확정 결함 | 심각도 | 처치 |
|---|---|---|---|
| QA-1 | 워커 급사 시 running 고아 + 계정락 잔존 → 머신 큐 조용한 영구 데드락 | high | `stalled_running_jobs`(3000s 초과) + watchdog 경보로 **가시화**. 자동 회수(lease/owner 강제종결 RPC)는 DB 마이그레이션 필요 — **후속 조각** |
| QA-2 | paused_for_human 직후 같은 계정 잡 즉시 claim — 캡차 처리 중 자동화 재진입(SOT29 §2·§4 위반) | high | 워커측 쿨다운에 더해 계정 단위 서버 장벽으로 근본 차단. queued 등록은 보존하고, 같은 비공백 account_key의 모든 일시정지 잡을 수동 해소할 때까지 claim 차단 |
| QA-3 | 비정상 종료 시 stderr 가 stdout 에 붙어 PAUSED 마커가 15줄 창 밖으로 밀림 → 캡차를 failed(재개불가) 오판 | medium | `_run_claude` stdout/stderr 분리, 마커 탐지 stdout 한정, stderr 는 실패 요약에만 |
| QA-4 | release 호출 자체가 실패하면 잡이 조용한 running 고아 | medium | release 재시도 3회(백오프) + 최종 실패 시 "고아 위험" 명시 경보 후 전파 |
| QA-5 | fleet_worker_loop.sh 경로 무가드 → launchd 조용한 크래시루프 / plist 경로 하드코딩(`~/Valuehire_v5`) 머신별 드리프트 | medium | 스크립트에 명시 로그 + 자기위치 폴백 + 재시도(pc-k6 규율). plist 는 설치 시 머신별 경로 확인 필수 |
| QA-6 | 401 시 워커·watchdog 무한 조용 재시도(S3 미구현이던 것) | high | S3 구현으로 해소 — 기동 인증 프로브 + 1회 경보 + 백오프(워커·watchdog 양쪽 배선) |

검증: 신규 계약 테스트 50개(RED 먼저) + 기존 fleet 141개 회귀 0. 변이 5종
(queued 필터 반전·쿨다운 제거·마커 결합 스캔 복원·running 필터 반전·재시도 제거) 전부 사살.

## 후속 조각 (이 스펙의 범위 밖, 장부화)

- **fleet-lease**: jobs 에 lease(만료 시 자동 재큐/failed + 계정락 정리) — QA-1 근본 해소.
  DB 마이그레이션 + claim/heartbeat RPC 변경 필요.
- **gateway-단일화 실행**: S1 은 운영 조치(사장님 승인 필요) — 맥북 pid 5846 구 게이트웨이
  종료 + fleet 플러그인 게이트웨이 1개만 유지.

## 비범위

- winpc worker 설치(별도 트랙).
- Hermes 게이트웨이 자체의 다중 인스턴스 방지 로직(우리 코드가 아님 — 운영 절차로 통제).
- 잡 스킬 실행 품질(humansearch 자체)은 이 스펙 밖.
