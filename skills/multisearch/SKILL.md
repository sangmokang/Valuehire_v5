---
name: multisearch
description: "Use when running Valuehire multi-position candidate sourcing from Discord/Hermes: group active positions, search Saramin/Jobkorea/LinkedIn RPS/public web fail-closed, deduplicate profiles, score candidates across positions, and write Profile URL, score, fit reason, and profile summary into ClickUp Activity."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [valuehire, ai-search, multisearch, discord, clickup, sourcing, recruiting]
    related_skills: [search]
---

# Valuehire Multisearch — Multi-Position Portal Sourcing Layer

## Overview

이 Skill은 여러 포지션을 한 번에 묶어 후보자를 찾는 Valuehire AI Search 확장 절차입니다. 단일 포지션용 `search` Skill이 “한 포지션을 깊게 보는 지도”라면, `multisearch`는 “여러 포지션을 같은 길목으로 묶어 한 번에 탐색하는 교통 정리”입니다.

기본값은 dry-run/read-only입니다. 사람인, 잡코리아, LinkedIn RPS, ChatGPT/공개 웹 검색, ClickUp, Supabase에 실제 쓰기·저장·발송을 하려면 사장님 승인과 환경 게이트가 모두 필요합니다.

핵심 목표:
- 여러 포지션을 직무군, 연차, 회사 맥락으로 그룹화한다.
- 사람인·잡코리아·LinkedIn RPS·ChatGPT/공개 웹별 키워드와 필터를 만든다.
- 상세 프로필만 저장 대상으로 삼고, 리스트 페이지는 저장하지 않는다.
- 같은 후보를 여러 포지션에 역매칭하고 점수화한다.
- ClickUp Activity에는 반드시 `Profile URL`, `점수`, `왜 잘 맞는지`, `후보자 프로필 요약`을 함께 남긴다.
- Discord 개인톡과 서버 채널 호출은 `docs/search-access.md`, 채널 allowlist, role allowlist 기준으로 fail-closed 처리한다.

## When to Use

Use when:
- 사용자가 “multisearch”, “멀티서치”, “여러 포지션 서치”, “포털 소싱 레이어”, “사람인/잡코리아/LinkedIn RPS 같이 돌려”라고 요청할 때
- Discord에서 Hermes를 호출해 Valuehire 후보자 AI Search를 실행하려 할 때
- 한 후보를 여러 ClickUp 포지션에 reverse-match하고 싶을 때
- 포털별 키워드, 큐, 중복 제거, ClickUp Activity 기록 형식을 함께 점검해야 할 때

Don't use for:
- 이력서 1개를 active 포지션에 매칭하는 작업: `vh_match_resume` 또는 resume matching 절차를 사용한다.
- 단일 포지션 후보 탐색만 필요한 작업: `search` Skill 또는 `vh_ai_search_position`을 우선한다.
- 메시지, 이메일, InMail, 제안 발송: 별도 승인과 별도 절차가 필요하다.
- 캡차, 2FA, IP 보안 경고 자동 우회: visible browser에서 사람이 직접 해결하도록 대기하고, 해결 후 같은 세션을 재검증한다.

## Source Documents

이 Skill은 다음 문서를 기준으로 합니다.

- `docs/ai-search/multi-position-sourcing-layer-2026-06-08.md`
- `docs/search-access.md`
- `skills/search/SKILL.md`

주의: 사용자가 말한 `docs/engineering/multi-position-portal-sourcing-layer-goal-2026-06-08.md`가 현재 체크아웃에 없으면, 같은 날짜의 `docs/ai-search/multi-position-sourcing-layer-2026-06-08.md`를 우선 확인하고 경로 차이를 보고합니다.

## Safety Gates

기본은 fail-closed입니다.

라이브 작업 전에 아래가 모두 필요합니다.

1. 사장님 승인
   - `OWNER_SIGNOFF=approved`
   - 포털 소싱이면 `OWNER_SIGNOFF_SOURCE=approved`
2. 라이브 실행 플래그
   - `ENABLE_SKILL_A_SOURCE_RUNNER=1` 또는 해당 실행기의 명시 플래그
3. 발송 금지 플래그
   - `SKILL_A_SOURCE_NO_LIVE_CONTACT=1`
   - InMail, 이메일, 제안 발송은 별도 승인 전까지 0건
4. RPS 쓰기 게이트
   - `RPS_EXPORT_ALLOW_WRITE=1` 없으면 LinkedIn RPS export/write 금지
5. ClickUp/Supabase 쓰기 게이트
   - 토큰과 service role key는 서버/로컬 비밀값에서만 읽고 출력하지 않는다.

사람 개입 대기 조건:
- 캡차/보안문자
- 2FA/인증번호
- LinkedIn checkpoint/challenge
- IP 보안/이상 접근 경고
- 계정 잠금/경고

중단 조건:
- human intervention timeout
- headless 실행에서 사람 개입이 비활성화된 상태의 보안 challenge
- 사장님 Chrome 사용 중 감지
- selector 전부 실패
- 상세 프로필 본문과 OCR 텍스트가 모두 비어 있음

## Discord Personal DM Routing

Discord에서 Hermes를 개인톡으로 호출할 수 있는 사용자는 `docs/search-access.md`의 `Discord Contacts` 표를 기준으로 합니다.

현재 문서 기준 허용 사용자:
- 이상혁 / Rogan / `1404643716320329728`
- 김충수 / `834330913469890570`
- 김형준 / Julian / `1153183633297911848`

라우팅 규칙:
1. Discord 이벤트가 개인톡인지 확인한다.
2. 보낸 사람 Discord ID가 `docs/search-access.md`의 허용 목록에 있는지 확인한다.
3. 둘 중 하나라도 아니면 실행하지 않는다.
4. 허용된 개인톡이면 후보자 AI Search intent를 추출한다.
5. ClickUp/Wanted URL과 JD 본문이 함께 있으면 `url_plus_pasted_jd`로 보고 JD 본문을 우선 사용한다.
6. 포지션이 없으면 후보 검색을 시작하지 말고 포지션명을 물어본다.
7. 기본 실행 엔진은 Codex로 두되 600초 timeout/Claude 한도 조합에서는 `tools.multi_position_sourcing.timeout_recovery`로 bounded artifact를 반환한다.

구현 파일:
- `tools/multi_position_sourcing/access.py`
- `tools/multi_position_sourcing/discord_routing.py`

## Discord Server Channel Routing

서버 채팅방 호출은 slash command를 기본 경로로 둡니다. Bot mention은 보조 경로로만 허용하고, 채널 일반 prefix/free-text 명령은 Message Content privileged intent가 필요하므로 기본 설계에서 제외합니다.

지원 명령:
- `/search-status`
- `/run-search source:saramin keyword:"backend"`
- `/session-status`
- `/relogin-needed`

라우팅 규칙:
1. Slash command 또는 직접 bot mention만 파싱한다.
2. 서버 채널은 `DISCORD_ALLOWED_CHANNEL_IDS`에 포함되어야 한다.
3. 사용자는 `docs/search-access.md`의 Discord Contacts에 있거나 `DISCORD_ALLOWED_ROLE_IDS` 중 하나를 가져야 한다.
4. Slash command 응답은 ephemeral로 보낸다.
5. Bot mention 응답은 공개 채널에 짧은 ack만 남기고 세부 상태는 DM으로 보낸다.
6. 검색 실행은 queue enqueue/dry-run까지이며, LinkedIn 자동 클릭·프로필 순회·InMail 발송은 하지 않는다.

구현 파일:
- `tools/multi_position_sourcing/discord_routing.py`

검증 예시:
```bash
python3 -m unittest tests/test_multi_position_sourcing.py -v
```

## Position Grouping

여러 포지션은 다음 축으로 묶습니다.

- role family: backend, frontend, ai_ml, product_po, growth, sales, operations
- seniority range: 최소/최대 연차 버킷
- company context: 회사 규모, 투자 단계, 산업, 조직 분석, talent-density 메모
- core keywords: 포털 검색에 쓸 표준 직무어

구현 파일:
- `tools/multi_position_sourcing/models.py`
- `tools/multi_position_sourcing/grouping.py`
- `tools/multi_position_sourcing/keywords.py`

## Portal Credential Preflight

`docs/search-access.md`와 `.env.local` 기준으로 사람인·잡코리아·LinkedIn RPS 자격증명 설정 여부를 점검합니다(비밀값은 절대 출력하지 않습니다). **SOT 불변식: 3사 모두 자동 로그인합니다 — 절대 막지 않습니다.** 세션 preflight는 기존 로그인 세션이 있으면 그대로 사용하고, 없으면 **사람인·잡코리아·LinkedIn RPS 모두 `.env.local`/Keychain 자격증명으로 자동 로그인(아이디·비밀번호 입력·제출)** 합니다. 자격증명이 설정돼 있지 않으면 `credentials_not_configured`로 보고합니다. 단 **캡차/2FA/IP보안/checkpoint 같은 보안 챌린지는 절대 자동 우회하지 않고** visible browser에서 사람이 해결할 때까지 기다립니다(우회 시 계정 잠금 위험). LinkedIn도 자동 로그인이 보안 챌린지에 막히면 정지 후 사람 개입으로 폴백합니다. 운영 복구에서는 검증 스냅샷 재주입이 먼저이며, 3사 자동 재로그인은 스냅샷 복구 실패 후에만 Mac Keychain 자격증명으로 수행합니다(LinkedIn은 복구 실패 시 정지+Discord 알림).

자격증명 존재 확인만으로 큐를 실행하면 안 됩니다. 사람인, 잡코리아, LinkedIn RPS는 보호 채널로 취급하고, 워커별 persistent profile 또는 LinkedIn CDP attach 세션에서 로그인 마커가 확인된 경우에만 큐 항목을 처리합니다. 세션이 확인되지 않으면 해당 항목은 pending으로 유지하고 resume 사유를 남깁니다.

## 운영 안정성 (자동 복구 동작)

로그인은 한 번 풀려도 대부분 자동으로 회복됩니다. 워커가 가진 안정 장치(코드에 구현됨):

- **재로그인 지수 백오프**: 세션이 끊겨 자동 재로그인할 때 네트워크/타임아웃 같은 *일시적 오류*가 나면 곧바로 포기하지 않고 텀을 늘려가며(1초→2초…) 최대 3회 다시 시도합니다. 단, **보안 챌린지(캡차/2FA/checkpoint)로 막힌 경우(깨끗한 실패)는 절대 재시도하지 않고 한 번에 멈춥니다** — 계정 잠금을 막기 위함. (`recover_after_reauth`, `relogin_backoff_base_seconds`)
- **검색 시간제한**: 검색 1건이 멈춘 페이지에 영원히 매달리지 않도록 기본 60초 시간제한을 둡니다. 초과하면 그 항목은 에러로 정리하고 큐는 계속 진행합니다. (`run_one_search`, `PortalWorkerConfig.search_timeout_seconds`)
- **셀렉터 드리프트 감지**: 포털이 로그인 화면 HTML을 바꿔 입력칸 위치가 안 맞으면, 조용히 실패하지 않고 어떤 항목(아이디/비번/제출)이 사라졌는지 보고합니다 → 운영자가 셀렉터를 고칠 수 있습니다. (`login_selector_preflight`)
- **크롬 잔재 잠금 정리**: 크롬이 비정상 종료되며 남긴 단일실행 잠금 파일(SingletonLock 등)을, 워커가 프로필 잠금을 확보한 상태에서만 정리해 재시작 실패를 막습니다. **저장된 로그인(쿠키 등)은 절대 건드리지 않습니다.** (`clear_stale_singleton_locks`)

**SOT 불변식 재확인**: 위 어떤 동작도 **보안 챌린지를 자동 우회하거나 반복해서 두드리지 않습니다.** 보안 챌린지가 뜨면 멈추고 visible browser에서 사람이 해결한 뒤 같은 세션을 재검증합니다.

Mac Keychain 자격증명 계정:
- 사람인: `valuehire.portal_credentials` / `saramin:username`, `saramin:password`
- 잡코리아: `valuehire.portal_credentials` / `jobkorea:username`, `jobkorea:password`
- LinkedIn RPS: `valuehire.portal_credentials` / `linkedin_rps:username`, `linkedin_rps:password` (env: `LINKEDIN_USERNAME`/`LINKEDIN_PASSWORD`)

구현 파일:
- `tools/multi_position_sourcing/access.py`의 `portal_credential_status()`
- `tools/multi_position_sourcing/portal_session.py`
- `tools/multi_position_sourcing/portal_worker.py`
- `tools/multi_position_sourcing/portal_snapshot.py`
- `tools/multi_position_sourcing/portal_ops.py`
- `tools/multi_position_sourcing/portal_autologin.py`
- `tools/multi_position_sourcing/portal_runtime.py`
- `tools/multi_position_sourcing/portal_live_check.py`
- `tools/multi_position_sourcing/portal_login.py`

운영 세션 준비 명령:
```bash
python3 -m tools.multi_position_sourcing.portal_live_check init-session-key \
  --output artifacts/portal_session_key_init_latest.json

python3 -m tools.multi_position_sourcing.portal_live_check init-portal-credentials \
  --channels saramin,jobkorea,linkedin_rps \
  --output artifacts/portal_credentials_init_latest.json

python3 -m tools.multi_position_sourcing.portal_live_check init-discord-webhook \
  --output artifacts/discord_webhook_init_latest.json

python3 -m tools.multi_position_sourcing.portal_live_check readiness \
  --output artifacts/portal_live_readiness_latest.json

python3 -m tools.multi_position_sourcing.portal_live_check supabase-access-check \
  --output artifacts/portal_supabase_access_latest.json

python3 -m tools.multi_position_sourcing.portal_login \
  --channels saramin,jobkorea,linkedin_rps \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --chrome-cdp-endpoint http://127.0.0.1:9222 \
  --output artifacts/portal_session_status_latest.json
```

`init-session-key`는 Mac Keychain 세션 암호화 키를 생성/검증하되 키 값은 출력하지 않습니다. `init-portal-credentials`는 사람인/잡코리아/LinkedIn RPS env 자격증명을 모두 Mac Keychain으로 적재하되 값은 출력하지 않습니다. `init-discord-webhook`은 Discord 재인증 webhook env 값을 Mac Keychain으로 적재하되 URL은 출력하지 않습니다. `readiness`는 실제 포털/Discord에 접속하지 않지만 Supabase REST/RPC 접근 probe를 수행해 서비스 역할 키 거부를 live DoD 전에 실패시킵니다. readiness와 `supabase-access-check`는 HTTP status/error type, safe HTTP error hint, JWT role/expiry/ref-match 같은 safe key diagnostics만 기록하며 응답 본문, URL, 키 값은 출력하지 않습니다. `supabase-access-check`는 `reauth_events`, `latest_validated_session_snapshot`, `validated_session_snapshots`, `reauth_weekly_counts` 접근을 별도로 probe합니다. `portal_login`은 비밀값을 출력하지 않고 채널별 `ready`, `login`, `note`, `url`만 기록합니다. 사람인/잡코리아는 `launch_persistent_context`의 `userDataDir`를 1차 영속 계층으로 쓰며, `storage_state` launch 옵션을 쓰지 않습니다. LinkedIn은 열린 headed Chrome에 CDP로 attach하고, 기존 세션이 없으면 `.env.local`/Keychain 자격증명으로 자동 로그인하며, `worker_id=default` 단일 프로필만 허용하고 그 프로필도 OS 파일락으로 직렬화합니다. 보안문자, 2FA, checkpoint, 이상 접근이 나오면 자동 우회하지 않고 visible browser에서 사람이 해결할 때까지 대기합니다. 사람이 해결하고 검색 화면 또는 RPS 세션이 재확인되면 `human_intervention_ok`로 저장하고, 제한 시간 안에 해결되지 않으면 `human_intervention_timeout`으로 남깁니다.

운영 live restart persistence 검증 명령:
```bash
python3 -m tools.multi_position_sourcing.portal_live_check restart-smoke \
  --channel saramin \
  --keyword "백엔드 개발자" \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --output artifacts/portal_restart_smoke_saramin.json
python3 -m tools.multi_position_sourcing.portal_live_check restart-smoke \
  --channel jobkorea \
  --keyword "백엔드 개발자" \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --output artifacts/portal_restart_smoke_jobkorea.json
python3 -m tools.multi_position_sourcing.portal_live_check restart-smoke \
  --channel linkedin_rps \
  --keyword "백엔드 개발자" \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --chrome-cdp-endpoint http://127.0.0.1:9222 \
  --output artifacts/portal_restart_smoke_linkedin_rps.json
```

이 명령은 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, Mac Keychain의 `valuehire.session_state/session_state_v2` 암호화 키를 사용해 두 번의 별도 worker lifecycle에서 paced search, validated encrypted snapshot 저장, reauth event 기록, 스냅샷 재주입, 사람인/잡코리아 keychain auto-relogin fallback, LinkedIn Discord alert fallback을 검증합니다. `passed=true`는 두 lifecycle 모두 `reauth_cause` 없이 `status=searched`일 때만 기록됩니다. 프로필 손상 DoD는 검증 스냅샷을 먼저 만들고 해당 프로필의 활성 워커를 멈춘 뒤 `--delete-profile-before-start --confirm-delete-profile ~/.valuehire/portal_profiles/<site>/<worker_id> --disable-auto-relogin`로 실행합니다. 삭제 경로는 `.profile.lock`이 잡힌 프로필을 거부합니다. 이후 `reauth_cause=profile_corrupt`, `recovery.recovered_by=snapshot_reinject`를 확인합니다.

로그인 성공 직후 validated snapshot 캡처:
```bash
python3 -m tools.multi_position_sourcing.portal_live_check capture-snapshot \
  --channel saramin \
  --profile-root ~/.valuehire/portal_profiles \
  --worker-id default \
  --output artifacts/portal_snapshot_capture_saramin.json
```

LinkedIn Discord 재인증 알림 및 계측 확인:
```bash
python3 -m tools.multi_position_sourcing.portal_live_check discord-alert-test \
  --record-reauth-event \
  --output artifacts/portal_discord_alert_test_latest.json
```
이 명령은 LinkedIn `forced_logout` synthetic alert를 실제 Discord webhook으로 보내고, Supabase `reauth_events`에 `linkedin_rps/default/forced_logout/human` row를 기록합니다. 출력은 delivery/recording status와 비밀값 없는 이벤트 metadata만 포함합니다.

주간 reauth 계측 확인:
```bash
python3 -m tools.multi_position_sourcing.portal_live_check reauth-weekly-counts \
  --week-start 2026-06-08T00:00:00+00:00 \
  --output artifacts/portal_reauth_weekly_counts_latest.json

python3 -m tools.multi_position_sourcing.portal_live_check reauth-weekly-trend \
  --latest-week-start 2026-06-08T00:00:00+00:00 \
  --weeks 4 \
  --output artifacts/portal_reauth_weekly_trend_latest.json
```
출력은 `site`, `worker_id`, `cause`, `recovered_by`, `count` 집계와 최신/직전 주 총계, 주간 delta, zero-event week 수만 포함하며 비밀값과 raw session state를 포함하지 않습니다.

Supabase snapshot metadata 확인:
```bash
python3 -m tools.multi_position_sourcing.portal_live_check snapshot-metadata \
  --channel saramin \
  --worker-id default \
  --output artifacts/portal_snapshot_metadata_saramin.json
python3 -m tools.multi_position_sourcing.portal_live_check snapshot-metadata \
  --channel jobkorea \
  --worker-id default \
  --output artifacts/portal_snapshot_metadata_jobkorea.json
```
이 출력은 `encrypted_envelope=VHSS1`, `encrypted_bytes`, validation metadata만 포함하고 encrypted payload나 raw session state는 포함하지 않습니다.
앱은 Supabase RPC 호출 전에 `VHSS1` encrypted envelope가 아닌 snapshot payload를 거부하고, DB schema도 같은 envelope constraint를 적용합니다.

DoD 산출물 감사:
```bash
python3 -m tools.multi_position_sourcing.portal_dod_audit \
  --session-status artifacts/portal_session_status_latest.json \
  --restart-smoke-artifact artifacts/portal_restart_smoke_saramin.json \
  --restart-smoke-artifact artifacts/portal_restart_smoke_jobkorea.json \
  --restart-smoke-artifact artifacts/portal_restart_smoke_linkedin_rps.json \
  --profile-recovery-artifact artifacts/portal_live_check_saramin_profile_loss.json \
  --profile-recovery-artifact artifacts/portal_live_check_jobkorea_profile_loss.json \
  --snapshot-metadata-artifact artifacts/portal_snapshot_metadata_saramin.json \
  --snapshot-metadata-artifact artifacts/portal_snapshot_metadata_jobkorea.json \
  --discord-alert artifacts/portal_discord_alert_test_latest.json \
  --weekly-counts artifacts/portal_reauth_weekly_counts_latest.json \
  --weekly-trend artifacts/portal_reauth_weekly_trend_latest.json \
  --secret-scan-path artifacts \
  --output artifacts/portal_session_dod_audit_latest.json
```
이 감사는 safe JSON artifact, 로컬 파일락/poison snapshot probe, `artifacts/` 아래 plaintext Playwright storage state 잔존 여부를 확인합니다. `passed=false`이면 live DoD 완료로 보지 않습니다.

검증 예시:
```bash
python3 -m unittest tests/test_multi_position_sourcing.py -v
```

운영 메모:
- 잡코리아는 `https://www.jobkorea.co.kr/Corp/Person/Find` 접근 후 로그인 링크가 보이면 `https://www.jobkorea.co.kr/Login/Login_Tot.asp`에서 로그인한다.
- 사람인은 반드시 기업회원 로그인 경로를 사용한다: `https://www.saramin.co.kr/zf_user/auth?ut=c&url=https%3A%2F%2Fwww.saramin.co.kr%2Fzf_user%2Fmemcom%2Ftalent-pool%2Fmain%2Fsearch`.
- 기업회원 로그인 성공 확인 신호: `로그인` 링크 0개, `로그아웃` 표시 1개, `input.search_input`, `#career_min`, `#career_max`가 검색 화면에 존재한다.
- `ut=c` 없이 로그인하면 개인회원 흐름으로 빠질 수 있으므로 사람인 multisearch에서는 실패로 취급하고 기업회원 URL로 재시도한다.
- 캡차, 2단계 인증, 보안문자, 이상 접근 경고가 나오면 자동 우회하지 말고 visible browser에서 사람 개입을 기다린다. 시간초과 또는 headless 모드에서는 채널 제한/중단으로 보고한다.
- LinkedIn은 계정/비밀번호를 자동 입력하지 않는다. 기존 세션 확인과 만료 감지만 수행하고, checkpoint 또는 로그인 요구가 보이면 수동 재로그인 필요 상태로 보고한다.

## Portal Search Rules

사람인/잡코리아:
- 검색 세션마다 기존 칩과 필터를 초기화한다.
- 한 세션에는 표준 포털 직무어 1개만 넣는다.
- `서브컬쳐`, `ontology`, `settlement`, `short-form` 같은 좁은 키워드는 첫 검색어가 아니라 LLM screening keyword로 둔다.
- 상세 프로필 페이지만 저장한다.
- iframe/body 누락이 있으면 OCR 텍스트를 붙이고, 그래도 비어 있으면 중단한다.

LinkedIn RPS:
- 검색 키워드는 JD 전체를 포괄하도록 Boolean 값으로 구성합니다.
- 반드시 `AND`, `OR`, 괄호 `()`, 정확한 구문 검색 `""`를 섞어 사용합니다.
- 예: `("CMO" OR "Chief Marketing Officer" OR "Head of Marketing" OR "Marketing Lead") AND (Korea OR Seoul) AND (commerce OR "consumer app" OR D2C OR grocery OR food) AND (growth OR "performance marketing" OR CRM OR retention)`
- 후보 검색은 `Open to work` 필터를 먼저 켠 뒤 우선 수행합니다.
- `/talent/profile/` URL만 후보 근거로 인정합니다.
- InMail 발송은 금지합니다.
- export/write는 별도 게이트 없이는 하지 않습니다.

## Dedup and Profile Save

후보 식별은 canonical profile URL 기준입니다.

- LinkedIn `/talent/profile/<id>`와 `/in/<slug>`를 정규화한다.
- 사람인/잡코리아는 안정적인 profile ID query key가 있을 때만 정규화한다.
- query string과 fragment는 제거한다.
- TTL 안에 이미 본 후보는 다시 열지 않는다.

구현 파일:
- `tools/multi_position_sourcing/dedup.py`

## Reverse Match and Scoring

후보 1명을 여러 포지션에 매칭할 때는 top 3~5개 포지션을 반환합니다.

반드시 포함할 항목:
- candidate URL
- profile summary
- recommended position ID
- score
- why fit
- why not
- evidence paths
- score breakdown

점수 축:
- JD must-have 직접 일치
- 연차/seniority
- 학력/전공 또는 동등 경력
- 현재/과거 회사 신호
- 회사 stage/industry/culture fit
- 한국/언어/지역 신호
- 근거 품질
- risk penalty

구현 파일:
- `tools/multi_position_sourcing/scoring.py`

## ClickUp Activity Output Contract

AI Search 결과를 ClickUp Activity에 남길 때는 반드시 아래 4가지를 함께 씁니다.

```text
[AI Search / Multisearch 후보 결과]
Profile URL: {{profile_url}}
점수: {{score}}/100
대상 포지션 ID: {{position_id}}
후보자 프로필 요약:
{{profile_summary}}

왜 잘 맞는지:
- {{fit_reason_1}}
- {{fit_reason_2}}

리스크/확인 필요:
- {{risk_or_gap}}

근거:
- {{evidence_path_or_source_url}}
```

구현 파일:
- `tools/multi_position_sourcing/clickup_activity.py`

주의:
- URL, 점수, 적합 이유, 프로필 요약 중 하나라도 없으면 Activity 쓰기를 보류한다.
- 실제 ClickUp comment 생성은 별도 쓰기 게이트와 승인 뒤에만 한다.

## Queue Behavior

Hermes는 브라우저를 즉흥 조작하지 않고 공유 큐를 claim/resume하는 방식으로 동작합니다.

큐 항목:
```json
{
  "group_id": "string",
  "channel": "saramin|jobkorea|linkedin_rps",
  "keyword_plan": [],
  "status": "pending|claimed|done|failed|stopped",
  "attempts": 0,
  "last_error": "",
  "next_run_at": "ISO-8601"
}
```

동작:
- Chrome CDP가 없으면 pending을 유지한다.
- 사람인/잡코리아/LinkedIn RPS 로그인 세션이 확인되지 않으면 해당 채널 항목은 pending을 유지한다.
- 사장님 Chrome 사용 중이면 중단한다.
- 캡차/2FA/IP 보안은 portal login preflight에서 사람 개입 대기로 처리하고, timeout/headless/selector 실패/게이트 누락이면 stopped reason을 남긴다.
- 각 cycle은 searched groups, opened profiles, saved profiles, matched profiles, stopped reasons를 보고한다.

구현 파일:
- `tools/multi_position_sourcing/queue_runner.py`

## Dry-Run Command

```bash
python3 -m tools.multi_position_sourcing.dry_run --output artifacts/multi_position_sourcing/dry-run-latest.json
```

드라이런 산출물에는 다음이 들어가야 합니다.
- side effect flags가 모두 false
- position groups
- backend/product_po keyword plans
- sample profile canonical URL
- sample profile top matches
- sample ClickUp Activity comment
- Discord DM routing result
- queue cycle summary

## Reporting Format

완료 보고는 한국어로 짧게 합니다.

```text
처리 결과: 완료/부분완료/중단
범위: multisearch dry-run / live gated run / skill update
문서 기준: {{읽은 문서 경로}}
검증: {{실행한 테스트와 결과}}

1. Discord 개인톡 라우팅
- 허용 사용자:
- 차단 조건:

2. 소싱 큐
- 그룹 수:
- 채널:
- 중단 사유:

3. ClickUp Activity 포맷
- Profile URL 포함 여부:
- 점수 포함 여부:
- 적합 이유 포함 여부:
- 후보자 프로필 요약 포함 여부:

4. Side Effects
- ClickUp write:
- Supabase write:
- Outreach sent:
```

## Common Pitfalls

1. 사용자가 말한 문서 경로만 믿고 없는 파일을 읽은 척하는 실수: 실제 파일 존재를 확인하고, 없으면 대체 경로를 보고한다.
2. Discord 서버 채널 메시지와 개인톡을 같은 권한으로 취급하는 실수: 개인톡 여부와 사용자 ID allowlist를 둘 다 확인한다.
3. “다른 유저도 쓰게 해줘”를 전체 공개로 해석하는 실수: `docs/search-access.md`에 있는 사람만 허용한다.
4. 후보 리스트 페이지를 저장하는 실수: 상세 프로필만 저장 대상이다.
5. LinkedIn RPS에서 InMail/export를 무심코 누르는 실수: 별도 게이트 전에는 금지다.
6. 점수만 ClickUp에 남기는 실수: URL, 점수, 적합 이유, 프로필 요약이 함께 있어야 한다.
7. 사람인/잡코리아 후보 채널을 v4 production save rail에 이미 연결됐다고 말하는 실수: 현재는 dry-run/adapter contract로 취급한다.
8. 검색 채널 차단을 “후보 없음”으로 결론내리는 실수: “채널 제한으로 미확보”라고 보고한다.

## Verification Checklist

- [ ] `docs/ai-search/multi-position-sourcing-layer-2026-06-08.md` 또는 실제 존재하는 대체 문서를 읽었다.
- [ ] `docs/search-access.md`에서 Discord 허용 사용자를 읽었다.
- [ ] Discord 개인톡 라우팅이 fail-closed인지 확인했다.
- [ ] ClickUp Activity 코멘트에 Profile URL, 점수, 왜 잘 맞는지, 후보자 프로필 요약이 모두 있다.
- [ ] dry-run side effect flags가 모두 false다.
- [ ] 단위 테스트를 실행했다.
- [ ] 라이브 쓰기, 발송, export를 실행하지 않았다.
