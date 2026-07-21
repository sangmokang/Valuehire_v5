---
name: humansearch
description: "사람이 미리 걸어둔 채용사이트 검색결과(LinkedIn Recruiter/RPS·사람인·잡코리아)를 순회해 후보를 채점·등록하는 스킬. 트리거 — \"humansearch\", \"휴먼서치\", \"/humansearch\", \"이 검색 URL로 후보 찾아\", \"이 화면 순회해서 후보 솎아줘\", \"리스팅 돌면서 채점\", 반조립 서치 URL+포지션(ClickUp task/텍스트/URL, 복수 가능)을 주며 \"서치해라\" 할 때 발동. 검색어 생성·필터 입력은 하지 않는다(그건 aisearch) — 걸어둔 결과의 순회·채점(학력30·직무50·논리10·이직안정10, 합격 70+)·ClickUp FY26AI_Search(901818680208) 부모 Task+후보 Subtask 등록·전부 저장(스크린샷→텍스트+DB)·Discord 채널 814353841088757800 중간/완료 보고까지 한 턴에 끝낸다. 요청 시 핵심 후보 1명에게 개인화 제안(InMail) 문구를 골든샘플(references/inmail-golden-sample.md) 기준으로 만든다 — 이력 요약·전화통화 요청·과장 금지, 개인화 오프너+회사브리핑+JD 구조, 저장 또는 채팅창 제공까지. 제안 발송(Send)은 절대 자동으로 누르지 않는다 — 사장님 수동 게이트."
---

# humansearch — Claude Code 발동 심(로컬)

정본(SOT)은 레포에 있다. **이 파일은 발동용 심** — 절차·규칙·설정을 여기 복제하지 않는다.

## ⛔ 시작 게이트 (생략 금지)
0. **/login 먼저 (2026-07-20 사장님 지시)**: 브라우저에 붙기 전 `login` 스킬(`skills/login/SKILL.md`)을 먼저 적용한다 — 기존 CDP 브라우저·정확한 기존 탭만 재사용(새 창 0·새 탭 0), 로그인 마커 증명 후에만 순회 시작. 로그아웃이면 login 스킬 절차로 복구하고, 캡차·2FA·세션충돌이면 STOP.

발동 즉시, 작업 전에 반드시 읽는다:
1. `skills/humansearch/SKILL.md` — 절차 정본(순회·채점·발송 + **확장 스펙 2026-07-02** 5요건 + 실행 함정)
2. `skills/humansearch/humansearch.config.json` — 설정 단일 출처(가중치·합격선·하드제외·`position_inputs`·`clickup_registration`·`persistence`·`reporting`)
3. 메모리 — humansearch-run-method(러너 포지션 하드코딩 → 스크래치패드 런타임 오버라이드),
   humansearch-runner-skips-hard-exclude, humansearch-english-school-name-underscore,
   linkedin-rps-harvest-background-tab, humansearch-profile-url-no-hand-retype

## 실행 경로 (재사용 — 새 러너 금지)
- 순회·채점: `tools/multi_position_sourcing/humansearch_cdp_run.py` 를 **스크래치패드 드라이버에서
  모듈 전역 오버라이드**(`R.SEARCH_URL_BASE`·`R.POSITION`·`R.OUT_DIR`·`R.LOG`)로 재사용.
  포지션이 복수면 1차 채점 후 raw 필드로 `score_humansearch` 재채점(재오픈 금지).
- 프리플라이트(fail-closed): `assert_live_or_abort` — 카드 0/로그인/캡차/세션충돌이면 즉시 STOP.
  수확 전 `Page.bringToFront` + `Emulation.setFocusEmulationEnabled` 필수.
- 등록: ClickUp MCP(부모 검색→없으면 생성→Subtask+댓글 1개). 보고는 **사장님 DM** —
  `scripts/dm_report.py`(hermes_v5 봇, 유저 814353841088757800 → DM 채널 1512503041448743092,
  ⚠️ 814…800 은 유저 ID지 채널 아님). DM 불가 시 `VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL` 폴백.
- 저장: results.json + `~/.vh-data/ai-search-candidates.db` `ai_search_candidates`
  (url,position_id) upsert — 열어본 프로필 전원, 점수 무관.

## LinkedIn RPS 세션 문맥 보존 (`SESSION_CONTEXT_PRESERVATION`, #156)

- 이미 인증된 정확한 RPS target 하나만 재사용한다. 다른 Chrome 프로필의 RPS 세션 신호나
  target/profile/endpoint 불일치는 `AUTH_CONFLICT`이며 새 탭·두 번째 로그인 없이 중단한다.
- 수확 JSON은 canonical `profile_url`과 query 포함 원본 `navigation_url`을 둘 다 보존한다. 이동은
  `navigation_url`, 저장·중복제거는 `profile_url`만 사용한다.
- 이동 직후 차단 검사를 추출·스크린샷·DB 저장·채점보다 먼저 한다. 세션 충돌은 terminal이며
  Continue/Confirm·자동 로그인·재네비게이션·두 번째 사람 인계를 하지 않는다.

## 등록 직전 3중 게이트 (순서 고정)
1. 영문 학교명→한글 신호 보정 재채점 (SKY·성균관 저평가 방지)
2. `hard_exclude_reason` 전원 재적용 (프리랜서·단기이직 2회+ / '외주' 마커는 문맥 확인)
3. `is_valid_profile_url` — URL 은 수확 JSON 원본 복붙만(손입력 금지)

## 안전 불변식
제안/메일 발송 자동 클릭 금지(SOT3) · 사장님 크롬 점유 시 양보 후 자동 재개(R4) ·
캡차/차단 감지 시 STOP, 같은 URL 재네비게이션 반복 금지 · 보고는 한국어로 쉽게(SOT0).
