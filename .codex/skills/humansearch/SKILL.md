---
name: humansearch
description: 사장님이 채용 사이트(LinkedIn Recruiter/RPS·사람인·잡코리아)에 검색을 직접 걸어둔 리스팅 화면(또는 RPS recruiterSearch URL)을 받아, 후보 프로필을 하나씩 열어(또는 raw CDP 로 리스트 수확) JD와 점수(학력30·직무50·논리10·이직안정10) 매김 → 합격(70점+) 후보만 묶어 **Discord #ai_search 또는 ClickUp FY26AI_Search 보드(부모 Task + 후보 Subtask)** 로 등록하는 스킬. 검색어 생성·필터 입력은 하지 않는다(사람이 이미 걸어둠). 트리거 — "humansearch", "휴먼서치", "이 화면 순회해서 후보 솎아줘", "리스팅 돌면서 채점해서 디스코드로", "이 RPS 검색결과로 후보 찾아 ClickUp 에 등록", "포지션 Task 만들고 Subtask 에 후보 리스팅", 포지션명/positionId/RPS URL 을 주며 "이 검색결과 순회". search/multisearch(스킬이 검색까지 함)와 달리 humansearch 는 사람이 걸어둔 결과를 순회·채점·등록만 한다.
---

# humansearch — 사람이 걸어둔 검색을 순회·채점·발송

## ⛔ 공통 SOT 시작 게이트 (절대 생략 금지)

이 스킬이 발동되면 **작업·코딩·브라우저 조작·외부 쓰기 전에 먼저 기존 정의를 회수한다.**
이 게이트를 건너뛰면 SOT 위반이다.

반드시 먼저 읽고 보고:
- 루트 SOT: `CLAUDE.md`
- 작업 루프: `docs/harness.md`
- 관련 SOT: `docs/sot/`
- 이 스킬 설정: `skills/humansearch/humansearch.config.json`
- 기존 구현 진입점: `tools/multi_position_sourcing/humansearch.py` 및 이미 존재하는 순회/발송 경로
- 과거 메모리·로그·기존 구현 검색 결과

먼저 보고할 5가지:
- 읽은 경로
- 기존 구현 진입점
- 재사용·확장할 파일/함수
- 새 파일 필요 여부와 이유
- 외부 쓰기 여부와 승인 게이트

강제 금지:
- 기존 정의·구현 회수 전 새 코드 작성 금지
- 기존 경로로 가능한데 새 파일·새 러너·새 등록 스크립트 작성 금지
- 스펙을 사후에 추가해 현재 행동을 정당화 금지
- 정의 미발견·스펙 충돌·죽은 참조 발견 시 추측 진행 금지 → **STOP** 후 보고
- 테스트 약화·삭제 금지

외부 쓰기는 항상 L3:
- Discord, ClickUp, 이메일, 채용사이트, 사람인·잡코리아·LinkedIn/RPS 게시·등록·댓글·필드 업데이트·발송은
  사장님 **명시 승인** 전까지 dry-run, 초안, 저장까지만 한다.
- 알람 폭탄 금지. 여러 후보·여러 항목은 한 메시지 또는 한 댓글로 묶는다.
- `profile_url` 등 필수 URL/필드는 쓰기 직전 무결성 검사를 통과해야 한다.

사장님이 검색을 **이미 걸어둔** 상태에서 시작한다. 검색어 생성·필터 입력은 이 스킬의 일이 아니다
(그건 `search`/`multisearch`). humansearch 는 **목록 순회 → 프로필 1건씩 열기 → 채점 → 합격자
묶어 Discord 발송**만 한다.

설정 단일 출처: `skills/humansearch/humansearch.config.json` (가중치·합격선·제외·순회 규칙).
판정 로직 단일 출처: `tools/multi_position_sourcing/humansearch.py`.

## 🖥️ 브라우저 드라이버 — raw CDP 단일탭 주력 (2026-06-26 사장님 지시)
- **주력 = raw CDP 단일탭**: `tools/multi_position_sourcing/raw_cdp.py`. 디버그 크롬에
  websocket 으로 **한 타깃에만** 붙어 `Page.navigate`·`Runtime.evaluate`·`Page.captureScreenshot`.
  탭이 수십 개라 playwright `connect_over_cdp` 전체 attach 가 hang 되므로 단일탭 raw CDP 로 간다.
- **⚠️ CDP 포트 못박지 말 것 (2026-07-08 실사고).** 링크드인이 표준 9225 아닌 다른 포트(예: 9338)로
  떠 있어 도구가 죽은 포트로 붙는 오진이 났다. raw CDP 호출 **전에** 실제 살아있는 크롬의
  엔드포인트를 헬퍼로 해석해 `CDP_HTTP` 로 넘긴다(raw_cdp 가 이 env 를 호출 시점에 읽음):
  ```bash
  export CDP_HTTP="$(./scripts/portal_browsers.sh cdp linkedin)"   # 사람인=saramin, 잡코리아=jobkorea
  ```
  헬퍼는 그 프로필로 **실제 살아있는 크롬의 remote-debugging-port** 를 찾아준다. 살아있는 크롬이
  없으면 비정상 종료(재실행·포트 추정 금지 — 그 창에서 사람이 로그인/캡차 처리, SOT 안전 불변식).
  참고 메모리 [[portal-debug-chrome-ports]].
- **Origin 403 우회**: Chrome 이 Origin 헤더 붙은 ws 핸드셰이크를 거부 → `suppress_origin=True`.
  (`--remote-allow-origins` 로 크롬 재기동할 필요 없음.)
- **폴백 = MCP claude-in-chrome**: 확장이 연결돼 있고 raw CDP 가 불가할 때만.
- 전용 탭 1개에만 붙는다 — 사장님이 보던 다른 탭은 건드리지 않는다(양보 R4).
- **🔴 점유 표시 배지 (2026-07-08 사장님 지시 — 모든 서치·Codex 공통).** `raw_cdp.attach()` 하면
  화면 상단 중앙에 **"🤖 <에이전트> 자동화 사용중 · <작업>"** 배지가 자동으로 뜬다(사장님이 "내가
  쓰는 중"을 바로 봄, SOT 투명성). `pointer-events:none` 이라 사장님 클릭을 막지 않고, navigate 후
  자동 재주입되며, `tab.close()` 시 사라진다. **라벨은 env 로 지정**한다(실 서치 전에 export):
  ```bash
  export VH_BUSY_AGENT=Claude       # Codex 에서 돌릴 땐 VH_BUSY_AGENT=Codex
  export VH_BUSY_TASK=/humansearch  # /url · /aisearch 등 현재 작업명
  # 끄려면: export VH_BADGE_OFF=1
  ```
  배지 주입 실패는 서치를 절대 깨지 않는다(best-effort). 수동 제어: `tab.mark_busy(label)`/`tab.clear_badge()`.

## ⛔ 안전 불변식 (항상)
- **제안·메일 "보내기"는 절대 자동으로 누르지 않는다(SOT 3).** humansearch 는 후보 "브리핑"만 보낸다.
- **사장님이 크롬을 쓰는 동안에는 즉시 양보**하고, 손을 떼면 자동으로 다시 이어 한다(SOT 2 / R4).
  봇처럼 창 여닫기·URL 연타·알람 후 무한 재시도 하지 않는다.
- **보안 챌린지(캡차·봇차단·로그인 리다이렉트) 감지 시 즉시 STOP.** retry 금지(계정 잠금).
- 행동 전 **DOM 덤프**로 셀렉터를 확인한다(SOT23 evidence-first). 추측 셀렉터 금지.
- 브라우저는 **raw CDP 단일탭이 주력**(위 "브라우저 드라이버" 절). MCP claude-in-chrome 는 폴백.

### LinkedIn RPS 세션 문맥 보존 (`SESSION_CONTEXT_PRESERVATION`, #156)

- `/login`을 먼저 적용해 **이미 인증된 정확한 RPS target 하나**를 재사용한다. 다른 Chrome 프로필에서
  RPS 세션이 보이거나 target/profile/endpoint가 맞지 않으면 `AUTH_CONFLICT`로 중단한다. 새 브라우저·
  새 창·새 탭·두 번째 프로필 로그인은 0회다.
- `/login`이 증명한 기존 target id를 `exact_target_id`로 고정하고, 스크래치패드 드라이버도
  `R.main(..., target_id=exact_target_id)`로 넘긴다. 값이 없거나 실행 직전 target/profile/endpoint가
  달라지면 추측·fallback 없이 중단한다.
- 수확 시 카드의 query 포함 원본 href를 `navigation_url`로, query를 제거한 canonical URL을
  `profile_url`/`url`로 함께 저장한다. bare `profile_url`은 저장·중복제거에만 쓰고 브라우저 이동에는 쓰지 않는다.
- 각 프로필은 원본 `navigation_url`로 이동하며, 이동 직후 `assert_not_blocked_or_abort`를 **추출·스크린샷·
  아카이브·채점보다 먼저** 실행한다. `enterprise-authentication/sessions`를 후보 화면으로 저장하면 안 된다.
- 세션 충돌은 로그인 만료와 다르다. Continue/Confirm·자동 로그인·reload/navigation retry를 하지 않으며,
  사람이 한 번 해결한 같은 실행에서 재발해도 두 번째 로그인 안내 없이 그 채널을 영구 중단한다.

## 입력
다음 중 최소 하나가 있으면 시작하며, **모두 복수 허용**(2026-07-02 확장 — 아래 "확장 스펙" 참조):
포지션(포지션명 · ClickUp positionId · JD 텍스트 · URL) · 반조립 검색결과 URL.
- positionId 가 있으면 ClickUp JD 를 읽어 `Position`(must_haves/nice_to_haves) 으로 만든다(기존 경로 재사용).
- 화면만 있으면 보이는 포지션 컨텍스트 + 사장님 1줄 요약을 JD 로 쓴다.
- 채널은 활성 탭 URL(talent pool 패턴)로 추론하거나 사장님이 지정. 안전하면 3채널 **병렬**.

## 순회 (config.traversal)
- 최대 **10페이지**, 페이지는 **랜덤 순서**로 오간다(`start=0,25,50…` 무작위 — 순차 패턴 회피).
- **너무 빠른 속도 금지 — 사람처럼 천천히.** 링크드인은 프로필/키워드 간 20~60초 랜덤,
  사람인·잡코리아는 카드 간 3~8초. 링크드인은 **Open to work** 위주, 랜덤값 부여 후 하나씩 클릭.
- 채널별 "결과수 판단 트리"(0~4 포기 / GOLD 전수 / 81~300 상위 일부)는 SOT22 를 그대로 따른다.

## 프로필 1건 처리
1. 상세 진입(라이선스 차감 0) → **화면 스크린샷 1장 저장**(`~/.vh-search-results/{channel}/{date}/...`).
2. 레쥬메 텍스트 추출 → `CapturedProfile`(education·skills·employment_history·summary·evidence_paths) 구성.
3. **채점 전 하드 제외**(`hard_exclude_reason`): 프리랜서·잦은 단기이직(12개월 미만 2회+)·전문대 등.
   - 사람인·잡코리아만 학교 컷. **지방 국공립대·단국대 이상은 허용.** 링크드인은 학교 컷 미적용.
   - **세계 명문대 학력 만점(2026-06-26):** UCLA·미국 Ivy(예일·프린스턴·컬럼비아·코넬·UPenn 등)·
     세계 top(옥스브리지·임페리얼·UCL·ETH·NUS·도쿄대·토론토대 등)은 학력 30/30. 단일 출처는
     `scoring.HIGH_TIER_SCHOOL_SIGNALS`. ⚠️ substring 매칭이라 'Berkeley College'(≠UC Berkeley) 류
     오탐 가능 → 의심 시 사람/LLM 판단으로 보정.
   - "하위권 지방 사립"의 미세 판단은 기계가 다 못 한다 → 의심되면 사람/LLM 판단으로 거른다.
4. 통과한 후보만 채점(`score_humansearch`): 학력30·직무50·논리10·이직안정10 → 0~100.

## 발송 (config.output)
- **70점 이상**만 Discord **#ai_search** 로. 합격자 여러 명을 **한꺼번에** 보낸다.
- 메시지 포맷은 기존 `discord_briefing.format_discord_candidate_briefing()` 재사용
  (Profile URL · 점수 · 학력/경력 요약 · JD 와 잘 맞는 부분 · 안 맞는 부분 · 근거).
- ⚠️ **발송 직전 반드시 `eligible_matches_for_send(matches)` 로 거른다** — 이 함수가
  점수 70+ **그리고** `is_valid_profile_url()` 통과 후보만 남긴다(단일 관문). 빈값·내부공백·
  상대경로·`javascript:void`·비http URL 은 여기서 차단(사장님 0순위: 프로필 url 절대 오류 없어야 함).

## 확장 스펙 (2026-07-02 사장님 지시 — /humansearch 5요건)

1. **입력 = 반조립 서치 URL 복수.** 사람인·잡코리아·링크드인(RPS)의 사람이 걸어둔(반조립)
   검색 URL 을 여러 개 받아, 안전하면(세션충돌·봇가드 없음) 채널별 동시(병렬) 순회,
   위험 감지 시 순차 폴백(기존 `channels.execution` 규칙 그대로).
2. **포지션 = ClickUp task / 텍스트 / URL, 복수 허용.** 한 검색 결과를 여러 JD 로 동시
   채점할 수 있다 — 프로필 재오픈 없이 results.json 의 원시 필드(raw)로 재채점한다.
3. **ClickUp 등록(FY26AI_Search, list `901818680208`).** 포지션 부모 Task 를 먼저 검색해
   없으면 생성, 있으면 재사용. **후보도 같은 부모 아래 `profile_url` 로 중복검사 후** 없을 때만
   Subtask 로 등록한다. 등록처는 반드시 `https://app.clickup.com/9018789656/v/li/901818680208`
   이며 다른 리스트/Activity-only 기록은 스펙 위반. 합격(70+) 후보는 Subtask 로 등록하며 매칭 이유를
   간단히 적는다. 우선 신호: 학력(서울권 대학·해외 우수대·지방 국공립), 직무 적합성,
   이직 안정(잦은 단기이직 아님), 프리랜서 제외, **Open to work(OTW) 우선**(이직 의향 분명).
4. **전부 저장.** 열어본 프로필과 검색 리스트는 점수 무관 모두 저장 — 스크린샷 1장 →
   텍스트 전환(`visible_text`) → results.json + 후보 DB(`~/.vh-data/ai-search-candidates.db`
   `ai_search_candidates`, 포지션별 1행 upsert) → **Supabase 적재(2026-07-03 사장님)**:
   `profile_archives`(레쥬메 전문+url, url 없으면 거부) + `sourcing_results`(포지션별
   url·학력·경력·점수·fit_reason). 매퍼 `humansearch_supabase_sync.py`, 적재기
   `scripts/humansearch_supabase_backfill.py`(멱등 — 신규만 insert). **프로필 저장 증거
   (`screenshot`/`evidence_paths`/archive id 등)가 없는 후보는 ClickUp 등록 금지**다.
5. **Discord 보고 = 사장님 DM.** 서치 절차 **중간 보고**(시작·페이지 단위)와 완료 보고를
   사장님(유저 `814353841088757800`)에게 **hermes_v5 봇 DM**(`scripts/dm_report.py`,
   DM 채널 `1512503041448743092`)으로 보낸다. ⚠️ 814353…800 은 채널 ID 가 아니라 유저 ID —
   `/channels/814…/messages` 는 404(2026-07-02 사고). 백업 봇 hermes(1512501524792738064,
   DM 채널 1509944917009629364, 토큰 별도). DM 불가 시
   `VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL`(#ai_search) 폴백. 알람 폭탄 금지 —
   중간 보고는 페이지 단위 1건, 완료 1건으로 묶는다.

6. **서치 후 검색어 확장·갭 재검색 (2026-07-03).** 순회가 끝나면
   `tools/multi_position_sourcing/humansearch_keyword_expand.py expand_search_terms()` 로
   사장님 검색어를 **한↔영·띄어쓰기 변형**으로 확장하고, JD 핵심 키워드 중 못 덮은 갭
   (missing)을 찾는다. 기계 확장 결과는 **LLM(Claude)이 문맥 검증·큐레이션**한 뒤
   재검색 후보(research_queries)로 확정 — 갭이 있으면 재검색을 제안·실행하고,
   갭 리포트를 완료 DM 에 포함한다. (RPS 재검색은 검색창 실입력 필요 —
   memory: rps-search-execute-method.)
7. **완료 보고에 ClickUp URL 포함 (2026-07-03).** 완료 DM 에는 등록한 포지션
   부모 Task 의 ClickUp URL 을 반드시 넣는다 — 사장님이 DM 에서 바로 클릭해 확인.
8. **핵심 후보 개인화 제안(InMail) 문구 작성 — 발송 아님 (2026-07-03, 골든샘플 기준).**
   사장님이 "핵심 후보에게 제안 준비/보여줘" 류를 요청하면. **문구 구조·절대규칙은
   `references/inmail-golden-sample.md` 를 그대로 따른다**(복제 말고 그 파일을 읽는다).
   - 합격자 중 **JD 정중앙에 가장 근접한 1명** 선정(도메인·역할·안정성, **1촌 가점**). 근거 1줄 보고.
   - 문구(v2) = ① 개인화 오프너(**이력 보고 제안하는 뉘앙스 + 정곡 관찰 1줄**, ⚠️이력 요약·나열 금지,
     추천·CEO 맥락은 출처 있는 사실만) ② **회사 브리핑**(position-register §1.5 8요소, 출처 있는 사실만)
     ③ **[주요 업무]·[자격 요건] JD 윤문 불릿**(ClickUp/공식 채용에서 찾아 윤문) ④ **왜 검토할 만한가
     2~3불릿** ⑤ **VERIFIED-PULL 문단**(레주메 주면 무료 이력서 피드백) ⑥ 클로징+서명+P.S. 인입 CTA.
   - ❌ **금지 워딩**: 전화통화 요청('통화하자'), "꼭 맞아서/정확히 맞물린다"류 과장, 후보 이력 요약.
   - ✅ **가독성**: 문단·불릿으로 나눈다(한 덩어리 금지).
   - **언어 자동 선택 (2026-07-03, 사장님 정정)**: **한국어가 기본.** 로마자 한국 이름(한국 성씨)·
     한글 신호(한국 대학)면 한국인 → 한국어. 명백한 외국인(비한국 이름+한글 0)만 본문 영어
     (인사말·P.S.는 한국어 허용) — `body_language_for_profile()` 로 기계 판정.
   - ⛔ **발송 전 기계 체크리스트 통과 전 문구 제공 금지 (2026-07-03, Movensys 사고 봉인)**:
     `python3 -m tools.multi_position_sourcing.inmail_precheck --body-file <문구파일> --profile-name
     "<수확 name 그대로>" --channel linkedin_rps` 가 **exit 0** 이어야 저장/전달 가능.
     ① 인사말 이름=수확 프로필 이름(불일치·추출실패 STOP) ② 글자수 — LinkedIn **1,899자**·
     사람인/잡코리아 2,000자 ③ 금지 워딩 린트(통화/전화·딱맞류·중괄호·HTML주석) ④ 회사 브리핑
     요소(§1.5 8요소) 6개 미만이면 보고 후 진행 ⑤ 자모 단독 출현·기지 오타 STOP + 컴포저 입력 후
     스크린샷 대조 ⑥ VERIFIED-PULL 문단 + P.S. 인입 CTA 존재(부재 STOP). 언어 규칙 위반은
     warning(보고 후 진행). 상세는 골든샘플 "발송 전 기계 체크리스트" 절.
   - **채널 경계**: humansearch #8 은 **핵심 후보 1명 개인화 문구**만. 대량 템플릿 저장은
     `linkedin-rps-jd-set-builder`, 사람인·잡코리아 등록은 `position-register` 관할.
   - **마무리 = 발송이 아니라 저장/전달**: `Save as new template` 로 저장하거나, **문구를 채팅창에
     그대로 제공**해 사장님이 직접 붙여넣게 한다(사장님 선호 — 브라우저 조작 불필요).
   - ⛔ **Send 절대 자동 클릭 금지(SOT3)** — 발송은 사장님 손. 컴포저 입력 시 한글은 붙여넣기
     (clipboard+cmd+v)나 한 문단 단일 type.

### 실행 함정 (경험 명문화 — 감으로 재시도 금지)
- **백그라운드 탭 = 카드 0 렌더.** 수확 전 `Page.bringToFront` + `Emulation.setFocusEmulationEnabled`
  필수("카드 0 · 결과수 1.4K+" 프리플라이트 증상의 근본 원인, 2026-07-02 재확인).
- **영문 학교명 저평가.** RPS 학력은 영문 표기 — 등록 전 영문→한글 신호 보정 재채점.
- **하드제외 재적용.** CDP 러너는 점수만 매김 — 등록 직전 `hard_exclude_reason` 을 후보
  전원에 다시 돌린다(프리랜서·단기이직 2회+). '외주' 마커는 주변 문맥 확인(외주화 오탐).
- **재개(resume).** results.json 이 있으면 seen url 을 이어받아 중복 진입·덮어쓰기 방지.
- **RPS 결과 수확 = 가상 스크롤(2026-07-03).** 결과 리스트는 한 번에 4~8명만 렌더된다 →
  **결과 컨테이너를 조금씩 스크롤하며 그때그때 DOM 을 긁는다.** 수십 회 scroll+await 를 한
  JS 호출에 몰아넣으면 **렌더러가 프리즈(CDP Runtime.evaluate timeout)** → 짧은 grab(루프 없음)과
  `computer scroll` 을 **교차**한다.
- **InMail 컴포저 한글 입력(2026-07-03).** 본문을 shift+Enter 로 문단 나눠 여러 번 타이핑하면
  **포커스가 빠져 뒷 문단이 안 들어간다**(글자수로 확인). 본문은 **한 문단으로 단일 `type` 1회**가
  안전(줄바꿈 최소화). 입력 뒤 **글자수·한글 깨짐을 스크린샷으로 검증**. 줄바꿈에 Enter 금지
  (soft newline 만) — 오발송 방지.

## 등록 레인 B — ClickUp FY26AI_Search (부모 Task + 후보 Subtask)
사장님이 "ClickUp 에 등록"·"포지션 Task 만들고 Subtask 에 후보 리스팅"이라 하면 Discord 대신(또는 병행) 이 레인.
대상 리스트: **FY26AI_Search 보드 = list `901818680208`**
(`https://app.clickup.com/9018789656/v/li/901818680208`). 등록 전 **과거 회수**로 같은
포지션 Task 가 이미 있는지 `clickup_filter_tasks(list_ids=[901818680208])` 로 확인(중복 생성
금지). 부모가 있으면 재사용한다. 부모가 없을 때만 새 부모 Task 를 만든다.

1. **입력 = ClickUp positionId(FY26ClientsPosition) + 사장님이 걸어둔 RPS `recruiterSearch` URL.**
   - positionId 로 JD 를 읽어 채점 기준(직무·경력밴드·우대)을 세운다.
   - RPS URL 은 그 탭으로 이동만 하고(검색어 재입력 금지 — 이미 걸림), 결과를 **raw CDP 로 수확**한다.
2. **수확 = raw CDP 단일탭, 25명/페이지 가상스크롤 함정 주의**: `Page.bringToFront` 후 `window.scrollBy` 로 훑으며 `a[href*="/talent/profile/"]` 카드(name·url·ctx: 경력이력/학력/스킬)를 누적. 백그라운드 탭이면 5명만 렌더됨(→ [[linkedin-rps-harvest-background-tab]]). 수확 JSON 은 스크래치패드에 저장한다.
3. **채점 후 등록**:
   - **부모 Task**: `clickup_create_task(list_id=901818680208, name="[회사] 포지션 (요약, 경력밴드) — AI Search (LinkedIn RPS) YYYY-MM-DD", priority=high)`. 설명에 원 포지션 URL·검색조건·채점기준·"제안 자동발송 안 함" 명시.
   - **후보 Subtask**(70점+만): 생성 전 `profile_url` 로 같은 부모 아래 기존 Subtask 를 검색한다. 있으면 재사용/skip, 없으면 `clickup_create_task(list_id=901818680208, parent=<부모id>, name="{이름} — {점수}점 🟢 · {한줄요약} · {학교}")`, 설명 `**Profile:** {profile_url}` + 적합/미스매치 1줄 + **프로필 저장 증거**를 넣는다.
   - **fail-closed**: 중복검사 미수행, list id 불일치, profile_url 무효, 프로필 저장 증거 없음 중 하나라도 있으면 Task/Subtask 생성 금지.
   - 점수대: 85+ 강력추천, 70~84 후보, 70↓ 미등록. 밴드 하회/초과는 이름·설명에 명시(예 "리더급 참고").
   - 고객사 현직자는 **제외**(예: JD 회사 재직중이면 등록 금지).

## ⛔ profile_url 무결성 (레인 A·B 공통, 사장님 0순위)
- profile_url 은 **절대 손으로 옮겨 적지 않는다.** 수확 JSON(`*_cards.json`)의 `url` 을 **문자 단위 그대로** 붙인다. 손입력 시 뒷부분이 잘려 **다른 사람/깨진 프로필**로 간다([[humansearch-profile-url-no-hand-retype]]).
- 등록/발송 직전 검증: 게시할 URL == 수확 원본 `byname[name]` (스크립트 대조). 불일치 1건이라도 있으면 **게시 중단·정정**.
- Discord 레인은 `eligible_matches_for_send()`(점수 70+ **그리고** `is_valid_profile_url()`)가 단일 관문. ClickUp 레인도 동일 기준을 등록 전에 코드로 적용한다.

## 비범위
검색어 생성·필터 자동 입력(=search/multisearch), **제안/InMail/메일 "발송"(Send) 자동 클릭**
(=사람 수동 게이트 — 단, #8 InMail *작성창 준비*는 발송 직전까지 in-scope),
새 DOM 셀렉터 표 작성(=SOT23 재사용).
