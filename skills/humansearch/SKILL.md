---
name: humansearch
description: 사장님이 채용 사이트(LinkedIn Recruiter/RPS·사람인·잡코리아)에 검색을 직접 걸어둔 리스팅 화면을 받아, 후보 프로필을 하나씩 열어 스크린샷 저장 → JD와 점수(학력30·직무50·논리10·이직안정10) 매김 → 합격(70점+) 후보만 묶어 Discord #ai_search 로 보내는 스킬. 검색어 생성·필터 입력은 하지 않는다(사람이 이미 걸어둠). 트리거 — "humansearch", "휴먼서치", "이 화면 순회해서 후보 솎아줘", "리스팅 돌면서 채점해서 디스코드로", "지금 보이는 검색결과로 후보 찾아 #ai_search 로", 포지션명/positionId 를 주며 "이 검색결과 순회". search/multisearch(스킬이 검색까지 함)와 달리 humansearch 는 사람이 걸어둔 결과를 순회·채점·발송만 한다.
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
- **주력 = raw CDP 단일탭**: `tools/multi_position_sourcing/raw_cdp.py`. 사장님 9222 디버그 크롬에
  websocket 으로 **한 타깃에만** 붙어 `Page.navigate`·`Runtime.evaluate`·`Page.captureScreenshot`.
  탭이 수십 개라 playwright `connect_over_cdp` 전체 attach 가 hang 되므로 단일탭 raw CDP 로 간다.
- **Origin 403 우회**: Chrome 이 Origin 헤더 붙은 ws 핸드셰이크를 거부 → `suppress_origin=True`.
  (`--remote-allow-origins` 로 크롬 재기동할 필요 없음.)
- **폴백 = MCP claude-in-chrome**: 확장이 연결돼 있고 raw CDP 가 불가할 때만.
- 전용 탭 1개에만 붙는다 — 사장님이 보던 다른 탭은 건드리지 않는다(양보 R4).

## ⛔ 안전 불변식 (항상)
- **제안·메일 "보내기"는 절대 자동으로 누르지 않는다(SOT 3).** humansearch 는 후보 "브리핑"만 보낸다.
- **사장님이 크롬을 쓰는 동안에는 즉시 양보**하고, 손을 떼면 자동으로 다시 이어 한다(SOT 2 / R4).
  봇처럼 창 여닫기·URL 연타·알람 후 무한 재시도 하지 않는다.
- **보안 챌린지(캡차·봇차단·로그인 리다이렉트) 감지 시 즉시 STOP.** retry 금지(계정 잠금).
- 행동 전 **DOM 덤프**로 셀렉터를 확인한다(SOT23 evidence-first). 추측 셀렉터 금지.
- 브라우저는 **raw CDP 단일탭이 주력**(위 "브라우저 드라이버" 절). MCP claude-in-chrome 는 폴백.

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
   없으면 생성, 있으면 재사용. 합격(70+) 후보는 Subtask 로 등록하며 매칭 이유를
   간단히 적는다. 우선 신호: 학력(서울권 대학·해외 우수대·지방 국공립), 직무 적합성,
   이직 안정(잦은 단기이직 아님), 프리랜서 제외, **Open to work(OTW) 우선**(이직 의향 분명).
4. **전부 저장.** 열어본 프로필과 검색 리스트는 점수 무관 모두 저장 — 스크린샷 1장 →
   텍스트 전환(`visible_text`) → results.json + 후보 DB(`~/.vh-data/ai-search-candidates.db`
   `ai_search_candidates`, 포지션별 1행 upsert).
5. **Discord 보고 = 사장님 DM.** 서치 절차 **중간 보고**(시작·페이지 단위)와 완료 보고를
   사장님(유저 `814353841088757800`)에게 **hermes_v5 봇 DM**(`scripts/dm_report.py`,
   DM 채널 `1512503041448743092`)으로 보낸다. ⚠️ 814353…800 은 채널 ID 가 아니라 유저 ID —
   `/channels/814…/messages` 는 404(2026-07-02 사고). 백업 봇 hermes(1512501524792738064,
   DM 채널 1509944917009629364, 토큰 별도). DM 불가 시
   `VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL`(#ai_search) 폴백. 알람 폭탄 금지 —
   중간 보고는 페이지 단위 1건, 완료 1건으로 묶는다.

### 실행 함정 (경험 명문화 — 감으로 재시도 금지)
- **백그라운드 탭 = 카드 0 렌더.** 수확 전 `Page.bringToFront` + `Emulation.setFocusEmulationEnabled`
  필수("카드 0 · 결과수 1.4K+" 프리플라이트 증상의 근본 원인, 2026-07-02 재확인).
- **영문 학교명 저평가.** RPS 학력은 영문 표기 — 등록 전 영문→한글 신호 보정 재채점.
- **하드제외 재적용.** CDP 러너는 점수만 매김 — 등록 직전 `hard_exclude_reason` 을 후보
  전원에 다시 돌린다(프리랜서·단기이직 2회+). '외주' 마커는 주변 문맥 확인(외주화 오탐).
- **재개(resume).** results.json 이 있으면 seen url 을 이어받아 중복 진입·덮어쓰기 방지.

## 비범위
검색어 생성·필터 자동 입력(=search/multisearch), 제안/InMail/메일 발송(=사람 수동 게이트),
새 DOM 셀렉터 표 작성(=SOT23 재사용).
