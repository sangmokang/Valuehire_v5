---
name: aisearch
description: "Valuehire AI Search를 실행·점검·디버깅한다. \"AI Search 돌려\", \"서치해줘\", \"후보 찾아줘\", \"후보자 서치\", \"포지션 서치\", \"잡코리아도 같이\", \"멀티 서치\", \"ClickUp 포지션으로 후보 찾기\", search candidates 트리거 시 발동. /Users/kangsangmo/Valuehire_v5의 spec-driven SOT(docs/sot/22~26)를 따른다: 사전점검 → 점유·캡차·로그인 게이트 → JD intake → 키워드 5축 → 사람인·잡코리아·LinkedIn RPS 병렬 검색 → 적합도 평가 → 표준 출력계약 → 한국어 보고. v4 코드 절대 비의존(Valuehire_v4 cd·npm 금지). 임의 검색·추정 후보·SOT 단계/게이트 약화 금지. 외부 HOME 폴더에 의존하지 않는 자립형 스킬이다 — 필요한 외부 코드·참조는 vendor/ 에 들여와 있고, SOT·실행 엔진은 레포 경로(docs/sot, tools/)에서 공유한다."
---

# Valuehire AI Search (aisearch)

이 스킬은 **Claude Code(레포 스코프) 측 AI Search 엔트리**이며, 외부 HOME 폴더(codex 스킬·다른 ~/.claude 스킬)에 **런타임 의존하지 않는 자립형**이다. 들여온 외부 코드·참조는 `vendor/`에 있고(`vendor/SOURCES.json`이 출처·복사시점·해시 기록), 자립 여부는 `vendor/check_self_contained.py`가 강제한다. 알맹이(단계 로직·채널 셀렉터·출력 계약)는 **레포의 공유 정본(docs/sot·tools·skills)을 가리키며 복제하지 않는다**(분기·드리프트 방지).

기본 레포 루트: `/Users/kangsangmo/Valuehire_v5`. 다른 Valuehire 체크아웃이면 그 루트를 쓰되 동일 SOT 파일 존재를 확인한다.

## ⛔ 공통 SOT 시작 게이트 (절대 생략 금지)

발동되면 **작업·코딩·브라우저 조작·외부 쓰기 전에 먼저 기존 정의를 회수한다.** 건너뛰면 SOT 위반이다.

반드시 먼저 읽고 보고:
- 루트 SOT: `CLAUDE.md`
- 작업 루프: `docs/harness.md`
- 관련 SOT: `docs/sot/` (특히 22 필터 · 23 DOM · 24 JD평가 · 25 실행프로세스 · 26 포털로그인)
- 기존 구현 진입점: `tools/multi_position_sourcing/` 아래 AI Search 실행·스코어링·브라우저·출력 경로
- 과거 메모리·로그·기존 구현 검색 결과

먼저 보고할 5가지: 읽은 경로 · 기존 구현 진입점 · 재사용/확장할 파일·함수 · 새 파일 필요 여부와 이유 · 외부 쓰기 여부와 승인 게이트.

강제 금지:
- 기존 정의·구현 회수 전 새 코드 작성 금지
- 기존 경로로 가능한데 새 파일·새 러너·새 등록 스크립트 작성 금지
- 스펙을 사후에 추가해 현재 행동을 정당화 금지
- 정의 미발견·스펙 충돌·죽은 참조 발견 시 추측 진행 금지 → **STOP** 후 보고
- 테스트 약화·삭제 금지

외부 쓰기는 항상 L3:
- Discord, ClickUp, 이메일, 채용사이트, 사람인·잡코리아·LinkedIn/RPS 게시·등록·댓글·필드 업데이트·발송은 사장님 **명시 승인** 전까지 dry-run·초안·저장까지만 한다.
- 알람 폭탄 금지. 여러 후보·여러 포지션·여러 항목은 한 메시지/한 댓글로 묶는다.
- `profile_url` 등 필수 URL/필드는 쓰기 직전 무결성 검사를 통과해야 한다.

## First Moves

0. **⛔ /login 먼저 (선행 게이트, 2026-07-20 사장님 지시)**: 포털(사람인·잡코리아·LinkedIn)에 브라우저로 붙는 라이브 작업이면 stage `0_preflight` 진입 전에 `login` 스킬(`.claude/skills/login/SKILL.md`, 정본 `skills/login/`)을 먼저 적용한다 — 기존 CDP 브라우저·정확한 기존 탭만 재사용(새 창 0·새 탭 0), 사이트별 로그인 마커로 증명된 뒤에만 검색을 시작한다. 브리핑·dry-run 등 브라우저 무접촉 작업은 예외.
1. `docs/sot/25-ai-search-execution-process.md`(사람용 입구) → `25-ai-search-execution-process.json`(기계 명세)를 읽는다. **이 JSON이 한 턴의 단계·게이트 권위다.**
2. 라이브/코드 작업 전 SOT 체커를 돌린다:

```bash
python3 .claude/skills/aisearch/vendor/ai_search_sot_check.py --repo /Users/kangsangmo/Valuehire_v5
```

3. 채널 필터·DOM을 다루기 전 `docs/sot/22-talent-search-filters.md`(+`.json`)와 `docs/sot/23-channel-dom-selectors.md`를 읽는다.
4. 구현/디버깅이면 `tools/multi_position_sourcing/`의 정확한 파일을 읽고 재사용한다.

`skills/search/SKILL.md`만 보고 시작하지 않는다 — 그건 legacy/fresh-logic 가이드이고, 운영 스펙은 `docs/sot/25-ai-search-execution-process.json`이다.

## Operating Rules (INV — 약화 금지)

- **스스로 검색 시작 금지.** AI Search는 사용자가 준 positionId·ClickUp 태스크 URL·채용 URL·JD 본문, 또는 특정 단계 실행 명시 지시에서만 시작한다.
- stage 0~4(범위·채널상태·JD출처·키워드전략)가 서기 전엔 일반 웹/포털/ChatGPT/LinkedIn·사람인·잡코리아 검색·후보 발굴을 돌리지 않는다.
- SOT를 편의 판단으로 대체하지 않는다. SOT와 지름길이 충돌하면 SOT 우선. 도구 경로가 없으면 멈추고 막힌 지점을 보고한다.
- 라이브 검색을 비공식 수동 검색으로 조용히 강등하지 않는다. 필요한 채널이 `OCCUPIED`/`BLOCKED`면 그대로 표기하고 게이트를 우회하지 않는다.
- **v5만 사용. v4 코드·npm 금지.**
- `docs/sot/25` stage 순서를 따른다(사용자가 범위를 명시 제한하지 않는 한).
- 포털 액션 전 각 채널을 `READY`/`OCCUPIED`/`BLOCKED`로 분류한다.
- **사장님이 크롬 사용 중이면 자동화 액션 0, 손 떼면 자동 재개**(INV2).
- 캡차·2FA·봇차단·로그인캡·LinkedIn 멀티세션락 → 해당 채널 STOP. 우회·반복재시도 금지(INV4).
- **LinkedIn 세션 문맥 보존(`SESSION_CONTEXT_PRESERVATION`, #156)**: 이미 인증된 exact target 하나만
  재사용하고 다른 Chrome 프로필에 RPS 세션 신호가 있으면 `AUTH_CONFLICT`로 중단한다. 새 탭·두 번째
  로그인·Continue/Confirm은 0회다. 카드의 query 포함 `navigation_url`로 이동하고 canonical
  `profile_url`은 저장·중복제거에만 사용하며, 이동 직후 차단 검사를 추출·스크린샷·저장보다 먼저 한다.
- **채널을 직무로 가르지 않는다**(INV5). 라이브 포털 검색 범위에선 사람인·잡코리아·LinkedIn RPS 모두 전 직무 대상.
- **LinkedIn RPS는 좌측 필터 패널 필수**(2026-07-07 사장님 지시): 검색 시 좌측 "Show filters"를 열어 **Locations = South Korea** 를 드롭다운 제안으로 선택하고, **연차(Years of experience)도 좌측 패널**에 JD ±1~2년 버퍼로 설정한다. 키워드(Boolean)만 넣고 지역·연차를 생략하면 스펙 위반. 상세는 `docs/sot/22-talent-search-filters.json` channels.linkedin.filters.left_panel_required.
- 상세 진입·저장은 차감 0 → 검토 가치 있으면 즉시 저장(INV6). 차감 버튼만 사람 컨펌.
- **발송(제안·메일·InMail·Send·보내기) 자동 금지**(INV3) — 사람이 마지막에 누른다.
- 출력 계약(`profile_url`·`score`·`why_fit`·`profile_summary`) 미충족 후보는 보고하지 않는다.
- ClickUp 기록은 **FY26AI_Search list `901818680208`**
  (`https://app.clickup.com/9018789656/v/li/901818680208`) 고정. AI Search/Humansearch 모두
  부모 Task + 후보 Subtask 구조로 칸반에 남기고, 생성 전 부모 Task와 후보 `profile_url`
  중복검사를 반드시 수행한다. **프로필 저장 증거**(`screenshot`/`evidence_paths`/archive id 등)가
  없는 후보는 등록 금지.
- 보고는 짧고 쉬운 한국어로(CLAUDE.md 0번 규칙).

## Spec Stages (docs/sot/25 stages와 1:1)

1. `0_preflight` — v5 레포 + Chrome/CDP(:9222) 경로 확인. **점유 배지**: raw CDP 로 붙기 전 `export VH_BUSY_TASK=/aisearch`(Codex 면 `VH_BUSY_AGENT=Codex`) → `raw_cdp.attach()` 하면 "🤖 …자동화 사용중 · /aisearch" 배지가 화면에 자동 표시(사장님 점유 인지, SOT 투명성). 규약: humansearch SKILL "브라우저 드라이버" 절.
2. `1_occupancy_captcha_gate` — 캡차·멀티세션·로그인 상태 먼저 확인, 채널 분류.
3. `2_yield_resume` — 사장님 크롬 사용 중 양보, 손 떼면 자동 재개.
4. `3_jd_intake` — ClickUp JD 우선, 비거나 오래되면 공식 채용홈에서 보강. 정리된 포지션은 `docs/sot/24-position-jd-sot.json`.
5. `4_keyword_strategy` — JD를 산업·직무·스킬/툴·경력·제외 5축으로. **AND 1개로 보통 90% 좁힘.**
6. `5_channel_search` — 사람인·잡코리아·LinkedIn RPS **병렬**(INV7, 직렬 금지 → 뒤 채널 누락). talent pool URL만.
7. `6_evaluation` — `docs/sot/24-position-jd-sot.json`의
   `candidate-match-v2-2026-07-24` 계약을 읽는다. LLM은 필수요건 게이트와
   근거가 붙은 D1~D8 소점수만 내고, 총점·등급은 Stage 4 코드만 계산한다.
8. `7_output_contract` — 필수 4필드 충족 후보만 직렬화(아래 출력 계약)하고, ClickUp 기록 범위면 FY26AI_Search 등록 계약을 적용.
9. `8_jd_template_lane` — 신규/오픈 포지션이면 LinkedIn/RPS JD 템플릿 상태까지. **Send 금지.**
10. `9_report` — 채널별 인원·템플릿 상태·다음 키워드·산출물 경로·종료 사유 보고.

## 채널 라우팅

| 사장님 말 | 채널 | 실행 경로(레포 정본) |
|---|---|---|
| "사람인만"·기본 | saramin | 단일 포지션 → `skills/search/SKILL.md` |
| "잡코리아도"·"병렬로"·"전체" | saramin+jobkorea | 다중 → `skills/multisearch/SKILL.md` + `tools/multi_position_sourcing/` |
| "링크드인도" | +linkedin | 위 + LinkedIn RPS JD 레인(`vendor/linkedin-rps-jd-set-builder.md`) |

## 표준 출력 계약

후보 리스트는 항상 **`candidate-output-contract.json`(이 스킬 폴더)** 스키마로 만든다.
필수 4필드 = `profile_url`, `score`, `why_fit`, `profile_summary` — 하나라도 없으면 그 후보는 전송/기록 보류.

- profile_url은 채널별 풀URL만(링크드인·잡코리아=무료, 사람인=이용권 필요·미보유 시 `url_pending=credit-gated`). 내부 id(사람인 residx) 금지.
- 점수 85+ 강력추천 / 70~84 후보 / 70↓ 리스트 제외.
- 디스코드 후보 리스트 기본 채널 = `#ai_search`. webhook 전송엔 **User-Agent 헤더 필수**(없으면 Cloudflare 403). 상세는 계약 JSON의 `discord_send_spec`.
- ClickUp은 FY26AI_Search 보드(list `901818680208`)에 포지션 부모 Task + 후보 Subtask 로 기록한다. 부모/후보 중복검사와 프로필 저장 증거가 없으면 fail-closed.
- 발송(제안·메일·InMail)은 절대 자동 금지 — 이 계약은 "후보 리스트 전송"만.

## When Work Is Limited

- 브리핑·스펙 요약 요청 → 포털 안 돌림. SOT 읽고 요약.
- 전략만 요청 → stage 4에서 멈춤.
- dry-run 요청 → ClickUp·Supabase·Discord·포털 저장·발송 쓰기 0.
- 포지션/JD/출처가 없으면 일반 검색하지 말고 빠진 입력을 한 줄로 묻는다.
- 라이브 검색이 막히면 어느 채널이 왜 막혔는지 보고 — "후보 없음"으로 결론내지 않는다.

## References (레포 정본 — 복제 금지)

- 실행 프로세스 SOT: `docs/sot/25-ai-search-execution-process.json` (+`.md`)
- 채널 필터·DOM: `docs/sot/22-talent-search-filters.json` (+`.md`), `docs/sot/23-channel-dom-selectors.md`
- JD 평가기준: `docs/sot/24-position-jd-sot.json`
- 포털 로그인 스펙: `docs/sot/26-portal-login-spec.json`
- 단일 포지션 판단 로직: `skills/search/SKILL.md` (+ `skills/search/references/`: boolean-strategy·chatgpt-search-cdp-handoff·clickup-ai-search-channel-fallbacks·content-ops-settlement-sourcing·greetinghr-career-page-intake·harness-engineering-reimplementation)
- 다중 포지션·포털 자동복구: `skills/multisearch/SKILL.md`
- 실행 엔진: `tools/multi_position_sourcing/` (dry_run·queue_runner·scoring·portal_*·clickup_activity)
- 출력 계약: `candidate-output-contract.json` (이 스킬 폴더)
- LinkedIn/RPS JD 템플릿: `vendor/linkedin-rps-jd-set-builder.md` (vendored 사본 — 출처·해시는 `vendor/SOURCES.json`)
- 자립형 게이트: `vendor/check_self_contained.py` (HOME 외부 의존 0 + vendor 완비 검사), 들여온 SOT 체커: `vendor/ai_search_sot_check.py`


## 익스텐션 독립 화면·본문 자동 저장

- 사람인·잡코리아·LinkedIn 상세 프로필을 연 직후, 차단 검사와 로그인 마커 확인을 통과하면 채점·다음 화면 이동보다 먼저 아래 정식 실행기를 호출한다. 크롬 익스텐션의 저장 성공 여부를 기다리거나 성공으로 가정하지 않는다.
- 현재 실행 주체(Claude 또는 Codex), 정확한 기존 target id, 수확 원본 전체 profile URL, 포지션 id와 순번을 그대로 넘긴다.

```bash
PYTHONPATH=. python3 -m tools.multi_position_sourcing.session_guard capture-evidence \
  --site <saramin|jobkorea|linkedin_rps> --agent <Claude|Codex> \
  --task ai-search --mode profile --target-id <exact-target-id> \
  --profile-url <full-profile-url> --position-id <position-id> --candidate-index <n>
```

- exit 0 JSON의 `capture_status=saved`, `screenshot_path`, `text_path`, `manifest_path`, `screenshot_sha256`, `visible_text_sha256`를 그 후보의 `evidence`에 그대로 넣는다.
- 명령이 실패하거나 필드가 하나라도 없으면 `saved=true`, 완료 영수증, 점수화, ClickUp/Discord 등록을 금지한다. 캡차·세션 충돌·로그인 소실·사람 사용 중 상태는 해당 채널을 중단하고 우회 캡처하지 않는다.
- 실행기는 기존 탭만 읽고 화면을 저장하며 새 창·새 탭·navigate·focus·close를 하지 않는다.
