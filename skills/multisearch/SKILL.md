---
name: multisearch
description: "Use when running Valuehire multi-position candidate sourcing from Discord queue workers (Claude/Codex): group active positions, search Saramin/Jobkorea/LinkedIn RPS/public web fail-closed, deduplicate profiles, score candidates across positions, and record eligible saved profiles in ClickUp FY26AI_Search list 901818680208 as position parent Tasks plus candidate Subtasks."
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
- ClickUp 기록은 FY26AI_Search list `901818680208`
  (`https://app.clickup.com/9018789656/v/li/901818680208`)에 포지션 부모 Task + 후보 Subtask 로 남긴다.
  부모/후보 `profile_url` 중복검사와 프로필 저장 증거 확인이 먼저이며, Subtask에는 반드시
  `Profile URL`, `점수`, `왜 잘 맞는지`, `후보자 프로필 요약`을 함께 남긴다.
- Discord 개인톡과 서버 채널 호출은 `docs/search-access.md`, 채널 allowlist, role allowlist 기준으로 fail-closed 처리한다.

## When to Use

Use when:
- 사용자가 “multisearch”, “멀티서치”, “여러 포지션 서치”, “포털 소싱 레이어”, “사람인/잡코리아/LinkedIn RPS 같이 돌려”라고 요청할 때
- Discord 큐에서 Claude 또는 Codex 워커로 Valuehire 후보자 AI Search를 실행하려 할 때
- 한 후보를 여러 ClickUp 포지션에 reverse-match하고 싶을 때
- 포털별 키워드, 큐, 중복 제거, ClickUp FY26AI_Search Task/Subtask 기록 형식을 함께 점검해야 할 때

Don't use for:
- 이력서 1개를 active 포지션에 매칭하는 작업: `vh_match_resume` 또는 resume matching 절차를 사용한다.
- 단일 포지션 후보 탐색만 필요한 작업: `search` Skill 또는 `vh_ai_search_position`을 우선한다.
- 메시지, 이메일, InMail, 제안 발송: 별도 승인과 별도 절차가 필요하다.
- 캡차, 2FA, IP 보안 경고 자동 우회: visible browser에서 사람이 직접 해결하도록 대기하고, 해결 후 같은 세션을 재검증한다.

## Source Documents

이 Skill은 다음 문서를 기준으로 합니다.

- **`docs/sot/22-talent-search-filters.md` (+ `.json`) — 3채널 인재검색 필터·DOM SSOT. 사람인·잡코리아·LinkedIn RPS별 키워드/필터를 만들기 전에 반드시 먼저 읽는다.** URL·입력법·결과수 임계가 채널마다 다르므로 **절대 섞지 않는다**(R5: 채널을 직무로 가르지 않음). 셀렉터·결과수 판단 트리·완화 폴백 전체는 같은 폴더 `.json`.
- **로그인 정책: `docs/sot/26-portal-login-spec.json` (`26-portal-login-spec@1.5.0`).**
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

Discord 개인톡에서 큐 작업을 요청할 수 있는 사용자는 `docs/search-access.md`의 `Discord Contacts` 표를 기준으로 합니다. 실행 에이전트는 Claude 또는 Codex입니다.

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

## Portal Login Preflight

로그인은 `26-portal-login-spec@1.5.0`의 사이트별 결정만 따릅니다.

- 사람인·잡코리아: 정확한 기존 target 후보가 1개일 때만 사이트별 저장 아이디·비밀번호를 최대 1회 제출합니다. 후보 0개/복수 또는 제공자 부재는 인증 조작 0회 `HANDOFF`입니다.
- LinkedIn 인증 기기 1개: 그 기기의 유일한 target을 인증 조작 0회로 재사용합니다.
- LinkedIn 인증 기기 0개: 현재 턴 승인과 APP 17 경로 결정이 같은 기기를 가리키고 정확 후보가 1개일 때만 APP 30/31의 `LINKEDIN_LI_AT` 참조 적용을 최대 1회 허용합니다.
- LinkedIn 인증 기기 수 미증명 또는 APP 30/31 미준비: 인증 조작 0회 `HANDOFF`입니다.
- LinkedIn 인증 기기 2개 이상·멀티세션: terminal `AUTH_CONFLICT`입니다. 다른 기기 자동 로그아웃·Continue/Confirm·신뢰도 선택·재시도는 금지합니다.
- 실제 captcha·2FA·checkpoint는 `HUMAN_AUTH`이며 이 경우에만 사람 개입 대기를 사용합니다.

비밀 원문과 파생값은 입력, 명령행, stdout, stderr, 로그, 영수증, 산출물, 모델 메시지에 넣지 않습니다. 모든 필수 채널이 `READY`일 때만 큐 항목을 검색 단계로 넘깁니다.

## 운영 안정성 (로그인 외 안전 장치)

- **검색 시간제한**: 검색 1건이 멈춘 페이지에 영원히 매달리지 않도록 기본 60초 시간제한을 둡니다. 초과하면 그 항목은 에러로 정리하고 큐는 계속 진행합니다. (`run_one_search`, `PortalWorkerConfig.search_timeout_seconds`)
- **셀렉터 드리프트 감지**: 포털이 화면 HTML을 바꿔 입력칸 위치가 안 맞으면 조용히 실패하지 않고 사라진 항목을 보고합니다. (`login_selector_preflight`)
- **크롬 잔재 잠금 정리**: 크롬이 비정상 종료되며 남긴 단일실행 잠금 파일(SingletonLock 등)을 워커가 프로필 잠금을 확보한 상태에서만 정리합니다. 저장된 로그인과 쿠키는 건드리지 않습니다. (`clear_stale_singleton_locks`)

## 로그인 결과 소비 경계

로그인 정책 정본은 `docs/sot/26-portal-login-spec.json`의 `26-portal-login-spec@1.5.0`입니다.
multisearch는 `login` 스킬이 반환한 로그인 판정 결과만 소비합니다. 브라우저·탭·프로필을
시작·종료·재시작하지 않고, 로그인 입력·쿠키 주입·스냅샷 복구·자동 로그아웃을 실행하지 않습니다.
`HUMAN_AUTH`, `HANDOFF`, `AUTH_CONFLICT`는 검색 불가 상태로 그대로 보고하며 다른 상태로 바꾸지 않습니다.

## 라이브 수집 안정성 (검증된 교훈 2026-06-17)

- **LinkedIn Recruiter 결과는 JS 렌더가 느리다 — 검색 직후 1초만 기다리고 긁으면 0건이 나온다(실제 발생).** 결과 selector(`a[href*="/talent/profile/"]`)가 나타날 때까지 최대 ~15초 `wait_for_selector` + 스크롤 후 수집한다. selector 자체는 정상이며 문제는 대기 부족이었다. talent search는 `searchKeyword=` URL로 진입하고, `("A" OR "B") AND (지역)` Boolean으로 JD 전체를 포괄한다.
- 사람인 talent-pool은 `main/tutorial` 페이지로 빠지거나 중간 인증 리다이렉트로 `login_redirect` not_ready 오탐이 날 수 있다 — 검색화면 마커(`input.search_input`/`#career_min`/`#career_max`) 도달을 직접 확인하고, 기업회원 URL(`ut=c`)로만 진입한다.
- 채널이 막혀 0건이면 "후보 없음"이 아니라 **"채널 제한으로 미확보"**로 보고한다(원인 단정 금지 — 0건이 selector 탓인지 결과없음인지 증거 없이 단정하지 않는다).
- 보낼 후보는 원시 수집 그대로가 아니라 **직무·지역·연차로 선별**해서만 내보낸다(원시 결과엔 직무 무관 후보가 섞인다). 보내는 모든 profile URL은 **실제로 열어 이름이 페이지에 있는지 확인**한 것만 쓴다(URL 절대 오류 금지).

APP 01은 실제 비밀 읽기·입력이나 로그인 실행 명령을 제공하지 않습니다. multisearch는
`skills/login/SKILL.md`의 로그인 판정 결과만 소비할 뿐이며, 과거 자동 로그인·스냅샷 재주입·
프로필 재시작·로그인 URL 이동·재인증 알림 시험을 대체 실행하지 않습니다. 안전한 제공자·적용기·
함대 증거가 준비되지 않으면 브라우저를 그대로 보존하고 `HANDOFF`합니다.

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

## ClickUp FY26AI_Search Output Contract

AI Search 결과를 ClickUp에 남길 때는 FY26AI_Search list `901818680208`의 칸반 Task/Subtask 구조를 씁니다.
부모 Task 는 포지션 단위로 중복 검색 후 재사용하고, 후보 Subtask 는 같은 부모 아래 `profile_url` 로
중복 검색 후 없을 때만 생성합니다. 프로필 저장 증거가 없는 후보는 ClickUp 등록 대상이 아닙니다.

후보 Subtask 또는 보조 Activity/comment에는 반드시 아래 4가지를 함께 씁니다.

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
- `tools/multi_position_sourcing/humansearch_register.py`
- `tools/multi_position_sourcing/clickup_activity.py`

주의:
- URL, 점수, 적합 이유, 프로필 요약, 프로필 저장 증거 중 하나라도 없으면 ClickUp 기록을 보류한다.
- 실제 ClickUp Task/Subtask/comment 생성은 별도 쓰기 게이트와 승인 뒤에만 한다.

## Queue Behavior

Discord 요청은 공유 큐를 거쳐 Claude 또는 Codex 워커가 claim/resume합니다. 브라우저를 즉흥 조작하지 않습니다.

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
