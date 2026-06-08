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
- Discord 개인톡 호출은 `docs/search-access.md`의 허용 사용자만 fail-closed로 통과시킨다.

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
- 캡차, 2FA, IP 보안 경고 우회: 발견 즉시 중단한다.

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

중단 조건:
- 캡차
- 2FA
- IP 보안/이상 접근 경고
- 계정 잠금/경고
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
5. 포지션이 없으면 후보 검색을 시작하지 말고 포지션명을 물어본다.
6. 기본 실행 엔진은 Codex로 둔다.

구현 파일:
- `tools/multi_position_sourcing/access.py`

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

`docs/search-access.md`와 `.env.local` 기준으로 사람인·잡코리아는 포털별 환경변수를 우선 사용합니다. 비밀값은 절대 출력하지 않습니다.

우선순위:
- 사람인: `SARAMIN_USERNAME` / `SARAMIN_PASSWORD`
- 잡코리아: `JOBKOREA_USERNAME` / `JOBKOREA_PASSWORD`
- 하위 호환: `JOB_PORTAL_USERNAME` / `JOB_PORTAL_PASSWORD`

구현 파일:
- `tools/multi_position_sourcing/access.py`의 `portal_credential_status()`

검증 예시:
```bash
python3 -m unittest tests/test_multi_position_sourcing.py -v
```

운영 메모:
- 잡코리아는 `https://www.jobkorea.co.kr/Corp/Person/Find` 접근 후 로그인 링크가 보이면 `https://www.jobkorea.co.kr/Login/Login_Tot.asp`에서 로그인한다.
- 사람인은 반드시 기업회원 로그인 경로를 사용한다: `https://www.saramin.co.kr/zf_user/auth?ut=c&url=https%3A%2F%2Fwww.saramin.co.kr%2Fzf_user%2Fmemcom%2Ftalent-pool%2Fmain%2Fsearch`.
- 기업회원 로그인 성공 확인 신호: `로그인` 링크 0개, `로그아웃` 표시 1개, `input.search_input`, `#career_min`, `#career_max`가 검색 화면에 존재한다.
- `ut=c` 없이 로그인하면 개인회원 흐름으로 빠질 수 있으므로 사람인 multisearch에서는 실패로 취급하고 기업회원 URL로 재시도한다.
- 캡차, 2단계 인증, 보안문자, 이상 접근 경고, 시간초과가 나오면 우회하지 말고 채널 제한/중단으로 보고한다.

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
- 사장님 Chrome 사용 중이면 중단한다.
- 캡차/2FA/IP 보안/selector 실패/게이트 누락이면 stopped reason을 남긴다.
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
